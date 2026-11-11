"""API de eventos, sessões e previsão sob demanda (src/api_eventos.py).

Usa o ``modelo_minimo`` (dados SINTÉTICOS) e uma raiz temporária: nada toca
``artefatos_ml`` do projeto. As sessões usam um relógio controlável.
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import pytest

pytest.importorskip("flask")
pytest.importorskip("sklearn")

from src import api_eventos, api_ml  # noqa: E402
from src.ml.servico_eventos import Configuracao  # noqa: E402
from src.ml.sessoes import GerenciadorSessoes  # noqa: E402
from src.sentinel_ai import app  # noqa: E402
from testes.ml.conftest import (gerar_rede, gerar_transacoes, gravar_hismall, modelo_minimo,  # noqa: E402,F401
                                nomes_contas)


class Relogio:
    def __init__(self):
        self.t = 2_000_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def relogio():
    return Relogio()


def _preparar(tmp_path: Path) -> None:
    exemplos = tmp_path / "artefatos_ml" / "exemplos"
    exemplos.mkdir(parents=True, exist_ok=True)
    gerar_rede(n_fluxos=4).drop(columns=["split", "alvo"]).to_csv(exemplos / "rede_teste_sem_rotulos.csv", index=False)
    gravar_hismall(gerar_transacoes(800, 40, semente=5), nomes_contas(40),
                   exemplos / "hismall_2022-09-10_sem_rotulo.csv")


@pytest.fixture
def cliente(tmp_path: Path, modelo_minimo, relogio):  # noqa: F811
    _preparar(tmp_path)
    api_eventos.configurar(tmp_path, modelo_minimo, Configuracao(fechar_ocioso_s=0.2),
                           GerenciadorSessoes(relogio=relogio))
    api_ml.configurar(tmp_path)
    app.config["TESTING"] = True
    yield app.test_client()
    api_eventos.configurar(Path(api_eventos._RAIZ))
    api_ml.configurar(Path(api_ml._RAIZ))


def _abrir(cliente) -> dict:
    sid = cliente.post("/api/ml/sessao", json={"rotulo": "teste"}).get_json()["sessao"]["id"]
    return {"X-NodeWatch-Sessao": sid}


def _medicao() -> dict:
    return gerar_rede(n_fluxos=1, por_split=(20, 0, 0)).drop(columns=["split", "alvo"]).iloc[15].to_dict()


def _tx(ident: str = "api-1", ts: str = "2022-09-10T05:31:00Z") -> dict:
    return {"tipo": "transacao", "dados": {
        "id_transacao": ident, "timestamp": ts, "banco_origem": 1, "conta_origem": "A1",
        "banco_destino": 2, "conta_destino": "B2", "valor_pago": 10, "moeda_pagamento": "US Dollar",
        "valor_recebido": 10, "moeda_recebimento": "US Dollar", "formato": "ACH"}}


def _esperar(cliente, cond, timeout=20.0, cab=None):
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        st = cliente.get("/api/ml/eventos/status", headers=cab or {}).get_json()
        if cond(st):
            return st
        time.sleep(0.05)
    raise AssertionError(st)


# ---------------------------------------------------------------------------
# Nada roda sem uma sessão da interface
# ---------------------------------------------------------------------------
def test_servidor_e_status_nao_iniciam_nada(cliente, tmp_path):
    assert cliente.get("/").status_code == 200  # abrir a interface
    st = cliente.get("/api/ml/eventos/status").get_json()
    assert not st["servico"]["trabalhador_ativo"] and st["replays"] == {}
    assert st["servico"]["contadores"] == {} and not st["responsavel"]["definida"]
    assert not (tmp_path / "artefatos_ml" / "previsoes").exists()
    assert cliente.get("/api/ml/analises").get_json()["analises"] == []


@pytest.mark.parametrize("metodo, rota, corpo", [
    ("post", "/api/ml/eventos", {"eventos": [_tx()]}),
    ("post", "/api/ml/eventos/iniciar", {}),
    ("post", "/api/ml/eventos/replay", {"fonte": "rede", "acao": "iniciar"}),
    ("post", "/api/ml/prever/rede", {"medicoes": [{"id_fluxo": "1_2"}]}),
    ("post", "/api/ml/eventos/laboratorio", {}),
    ("post", "/api/ml/eventos/fechar", {}),
    ("post", "/api/ml/analises/x/iniciar", {}),
])
def test_sem_sessao_ativa_recusa_e_nao_processa(cliente, metodo, rota, corpo):
    r = getattr(cliente, metodo)(rota, json=corpo)
    assert r.status_code == 403 and "Nenhum processamento" in r.get_json()["acao"]
    r = getattr(cliente, metodo)(rota, json=corpo, headers={"X-NodeWatch-Sessao": "inventada"})
    assert r.status_code == 403
    st = cliente.get("/api/ml/eventos/status").get_json()
    assert not st["servico"]["trabalhador_ativo"] and st["replays"] == {}


def test_sessao_encerrada_ou_expirada_nao_autoriza(cliente, relogio):
    cab = _abrir(cliente)
    assert cliente.post("/api/ml/sessao/pulso", headers=cab).status_code == 200
    relogio.t += 151  # sem pulso por mais que o prazo
    assert cliente.post("/api/ml/sessao/pulso", headers=cab).status_code == 410
    assert cliente.post("/api/ml/eventos/iniciar", headers=cab).status_code == 403
    cab2 = _abrir(cliente)
    assert cliente.post("/api/ml/sessao/encerrar", headers=cab2).get_json()["encerrada"]
    assert cliente.post("/api/ml/eventos/iniciar", headers=cab2).status_code == 403


# ---------------------------------------------------------------------------
# Eventos com sessão
# ---------------------------------------------------------------------------
def test_ingestao_exige_processamento_iniciado_pela_sessao(cliente):
    cab = _abrir(cliente)
    r = cliente.post("/api/ml/eventos", json={"eventos": [_tx()]}, headers=cab)
    assert r.status_code == 409 and "Iniciar processamento" in r.get_json()["acao"]
    assert cliente.post("/api/ml/eventos/iniciar", headers=cab).status_code == 200
    outra = _abrir(cliente)  # outra aba: precisa assumir explicitamente
    assert cliente.post("/api/ml/eventos", json={"eventos": [_tx()]}, headers=outra).status_code == 409


def test_ingestao_duravel_e_recusas_explicadas(cliente):
    cab = _abrir(cliente)
    cliente.post("/api/ml/eventos/iniciar", headers=cab)
    ruim = {"tipo": "medicao_rede", "dados": {"id_fluxo": "1_2", "timestamp": 1, "rtt_ms": 3}}
    r = cliente.post("/api/ml/eventos", json={"eventos": [_tx(), ruim, {"tipo": "medicao_rede", "dados": _medicao()}]},
                     headers=cab)
    assert r.status_code == 202
    corpo = r.get_json()
    assert corpo["aceitos"] == 2 and corpo["recusados"][0]["motivo"] == "invalido"
    assert corpo["aceitacao"].startswith("durável")
    # retransmissão: reconhecida, nada é refeito
    again = cliente.post("/api/ml/eventos", json={"eventos": [_tx()]}, headers=cab).get_json()
    assert again["aceitos"] == 0 and again["ja_aceitos"][0]["id_evento"] == "tx:api-1"
    _esperar(cliente, lambda st: st["servico"]["contadores"].get("previsoes_lavagem", 0) == 1
             and st["servico"]["contadores"].get("previsoes_rede", 0) == 1)
    assert cliente.get("/api/ml/eventos/consulta?id=tx:api-1").get_json()["situacao"] == "aplicado"
    rec = cliente.get("/api/ml/eventos/recentes?dominio=lavagem").get_json()["linhas"]
    assert rec[0]["id_transacao"] == "api-1" and rec[0]["modo_evento"] == "novo_evento"


def test_expiracao_da_sessao_responsavel_pausa_o_processamento(cliente, relogio):
    cab = _abrir(cliente)
    cliente.post("/api/ml/eventos/iniciar", headers=cab)
    relogio.t += 151
    outra = _abrir(cliente)
    st = cliente.get("/api/ml/eventos/status", headers=outra).get_json()
    assert st["responsavel"]["definida"] and not st["responsavel"]["ativa"] and not st["servico"]["autorizado"]
    # a outra aba assume explicitamente e o processamento continua
    assert cliente.post("/api/ml/eventos/iniciar", headers=outra).status_code == 200
    assert cliente.get("/api/ml/eventos/status").get_json()["servico"]["autorizado"]


def test_reinicio_nao_recupera_sozinho(cliente, tmp_path, modelo_minimo, relogio):  # noqa: F811
    cab = _abrir(cliente)
    cliente.post("/api/ml/eventos/iniciar", headers=cab)
    from src.ml import eventos as ev
    # eventos novos com instantes futuros: o relógio real não fecha o minuto de "b"
    agora = ev.agora() + 3600
    cliente.post("/api/ml/eventos", json={"eventos": [_tx("a", ev.iso(agora)), _tx("b", ev.iso(agora + 60))]},
                 headers=cab)
    _esperar(cliente, lambda st: st["servico"]["contadores"].get("previsoes_lavagem", 0) == 1)
    api_eventos.configurar(tmp_path, modelo_minimo, Configuracao(), GerenciadorSessoes(relogio=relogio))  # reinício
    st = cliente.get("/api/ml/eventos/status").get_json()
    assert not st["servico"]["aberto"] and st["servico"]["recuperacao"]["precisa_recuperar"]
    assert not st["servico"]["trabalhador_ativo"]
    cab = _abrir(cliente)
    r = cliente.post("/api/ml/eventos/iniciar", headers=cab).get_json()
    assert r["restaurado"]["restaurado"]
    st = cliente.get("/api/ml/eventos/status").get_json()
    assert st["servico"]["financeiro"]["transacoes_incorporadas"] == 1
    assert st["servico"]["financeiro"]["pendentes_em_minutos_abertos"] == 1


def test_previsao_sincrona_de_medicoes(cliente):
    cab = _abrir(cliente)
    m = _medicao()
    r = cliente.post("/api/ml/prever/rede", json={"medicoes": [m, {"id_fluxo": "x"}]}, headers=cab)
    assert r.status_code == 200
    corpo = r.get_json()
    p = corpo["previsoes"][0]
    assert p["id"] == f"{m['id_fluxo']}@{int(m['timestamp'])}" and p["horizonte"] == "proxima_medicao"
    assert set(p["probabilidades"]) == {"OK", "RISCO", "FALHA"} and p["versao_modelo"] == "teste-rede"
    assert len(corpo["recusadas"]) == 1


def test_csv_de_rede_vira_fonte_na_exploracao(cliente):
    cab = _abrir(cliente)
    csv = gerar_rede(n_fluxos=2, por_split=(30, 0, 0)).drop(columns=["split", "alvo"]).to_csv(index=False)
    r = cliente.post("/api/ml/prever/rede/csv", data={"arquivo": (io.BytesIO(csv.encode()), "minha rede.csv")},
                     content_type="multipart/form-data", headers=cab)
    assert r.status_code == 201, r.get_json()
    fonte = r.get_json()["fonte_id"]
    fontes = {f["id"]: f for f in cliente.get("/api/ml/fontes").get_json()["fontes"]}
    assert fontes[fonte]["conjunto"]["tipo"] == "completo" and fontes[fonte]["registros"] == 60


def test_replay_de_rede_e_financeiro_ate_o_fim(cliente):
    cab = _abrir(cliente)
    for fonte in ("rede", "financeiro"):
        r = cliente.post("/api/ml/eventos/replay", json={"fonte": fonte, "acao": "iniciar"}, headers=cab)
        assert r.status_code == 200 and r.get_json()["modo"] == "replay_historico"
    st = _esperar(cliente, lambda st: len(st["replays"]) == 2
                  and all(x["situacao"] == "concluido" for x in st["replays"].values()))
    assert st["replays"]["rede"]["processados"] == st["replays"]["rede"]["total"] == 4 * 260
    assert st["replays"]["financeiro"]["processados"] == 800
    assert st["servico"]["rejeitados"].get("atrasada", 0) == 0


def test_laboratorio_pela_api(cliente):
    cab = _abrir(cliente)
    rel = cliente.post("/api/ml/eventos/laboratorio", headers=cab).get_json()["relatorio"]
    assert rel["todos_ok"] and "SIMULAÇÃO" in rel["aviso"]


def test_descartar_volta_ao_estado_vazio(cliente):
    cab = _abrir(cliente)
    cliente.post("/api/ml/eventos/iniciar", headers=cab)
    cliente.post("/api/ml/eventos", json={"eventos": [{"tipo": "medicao_rede", "dados": _medicao()}]}, headers=cab)
    _esperar(cliente, lambda st: st["servico"]["contadores"].get("previsoes_rede", 0) == 1)
    r = cliente.post("/api/ml/eventos/descartar", headers=cab)
    assert r.status_code == 200 and "eventos_novo_evento_rede.csv" in r.get_json()["removidos"]
    st = cliente.get("/api/ml/eventos/status").get_json()
    assert st["servico"]["contadores"] == {} and st["servico"]["saidas"] == []


def test_painel_tem_as_areas_de_eventos_e_analise(cliente):
    html = cliente.get("/legado").get_data(as_text=True)  # interface anterior: fora do fluxo do analista, em /legado
    assert "#ml/eventos" in html and "<AreaEventos" in html and "não é fonte ao vivo" in html
    assert "#ml/analisar" in html and "<AreaAnalisar" in html and "Analisar dataset" in html


def test_bloqueio_pela_api_repetir_e_descartar(cliente, monkeypatch):
    from src.ml import servico_eventos as se
    cab = _abrir(cliente)
    cliente.post("/api/ml/eventos/iniciar", headers=cab)
    monkeypatch.setattr(se, "tabela_previsoes_rede", _falha)
    m = _medicao()
    cliente.post("/api/ml/eventos", json={"eventos": [{"tipo": "medicao_rede", "dados": m}]}, headers=cab)
    st = _esperar(cliente, lambda st: st["servico"]["bloqueio"])
    b = st["servico"]["bloqueio"]
    assert "falha injetada" in b["erro"] and b["ids"] == [f"rede:{m['id_fluxo']}@{int(m['timestamp'])}"]
    assert "eventos" not in b  # só o resumo sai na API
    assert cliente.post("/api/ml/eventos/bloqueio/repetir").status_code == 403  # sem sessão
    assert cliente.post("/api/ml/eventos/bloqueio/repetir", headers=cab).get_json() == {"ok": False}
    r = cliente.post("/api/ml/eventos/bloqueio/descartar", headers=cab).get_json()
    assert r == {"descartados": 1, "ok": True}
    assert cliente.get(f"/api/ml/eventos/consulta?id={b['ids'][0]}").get_json()["situacao"] == "descartado"
    assert not cliente.get("/api/ml/eventos/status").get_json()["servico"]["bloqueio"]


def _falha(*a, **k):
    raise RuntimeError("falha injetada")


def test_analise_pela_api_exige_sessao_e_vira_fonte(cliente, tmp_path):
    from src.ml.analises import GerenciadorAnalises  # noqa: F401
    csv = (tmp_path / "artefatos_ml" / "exemplos" / "hismall_2022-09-10_sem_rotulo.csv").read_bytes()
    dados = {"arquivo": (io.BytesIO(csv), "novo.csv")}
    assert cliente.post("/api/ml/analises", data=dados, content_type="multipart/form-data").status_code == 403
    cab = _abrir(cliente)
    r = cliente.post("/api/ml/analises", data={"arquivo": (io.BytesIO(csv), "novo.csv")},
                     content_type="multipart/form-data", headers=cab)
    assert r.status_code == 201 and r.get_json()["situacao"] == "pronta"
    aid = r.get_json()["id"]
    # validar não gera previsões, e consultar também não inicia nada
    assert cliente.get(f"/api/ml/analises/{aid}").get_json()["progresso"]["processadas"] == 0
    assert cliente.post(f"/api/ml/analises/{aid}/iniciar").status_code == 403
    assert cliente.post(f"/api/ml/analises/{aid}/iniciar", headers=cab).status_code == 200
    fim = time.monotonic() + 30
    while time.monotonic() < fim:
        m = cliente.get(f"/api/ml/analises/{aid}", headers=cab).get_json()
        if m["situacao"] == "concluida":
            break
        time.sleep(0.05)
    assert m["situacao"] == "concluida" and m["progresso"]["processadas"] == 800 and not m["avaliacao"]["disponivel"]
    fontes = {f["id"]: f for f in cliente.get("/api/ml/fontes").get_json()["fontes"]}
    assert fontes[m["fonte_id"]]["conjunto"]["tipo"] == "completo"
    assert cliente.get(f"/api/ml/fontes/{m['fonte_id']}/exportar").status_code == 200
    assert cliente.get(f"/api/ml/fontes/{m['fonte_id']}/resumo").status_code == 200
