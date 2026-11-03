"""API de eventos e previsão sob demanda (src/api_eventos.py).

Usa o ``modelo_minimo`` (dados SINTÉTICOS) e uma raiz temporária: nada toca
``artefatos_ml`` do projeto.
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import pytest

pytest.importorskip("flask")
pytest.importorskip("sklearn")

from src import api_eventos, api_ml  # noqa: E402
from src.sentinel_ai import app  # noqa: E402
from src.ml.servico_eventos import Configuracao  # noqa: E402
from testes.ml.conftest import (gerar_rede, gerar_transacoes, gravar_hismall, modelo_minimo,  # noqa: E402,F401
                                nomes_contas)


@pytest.fixture
def cliente(tmp_path: Path, modelo_minimo):  # noqa: F811
    exemplos = tmp_path / "artefatos_ml" / "exemplos"
    exemplos.mkdir(parents=True)
    gerar_rede(n_fluxos=4).drop(columns=["split", "alvo"]).to_csv(exemplos / "rede_teste_sem_rotulos.csv", index=False)
    gravar_hismall(gerar_transacoes(800, 40, semente=5), nomes_contas(40),
                   exemplos / "hismall_2022-09-10_sem_rotulo.csv")
    api_eventos.configurar(tmp_path, modelo_minimo, Configuracao(fechar_ocioso_s=0.2))
    api_ml.configurar(tmp_path)
    app.config["TESTING"] = True
    yield app.test_client()
    api_eventos.configurar(Path(api_eventos._RAIZ))
    api_ml.configurar(Path(api_ml._RAIZ))


def _medicao() -> dict:
    return gerar_rede(n_fluxos=1, por_split=(20, 0, 0)).drop(columns=["split", "alvo"]).iloc[15].to_dict()


def _esperar(cliente, cond, timeout=20.0):
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        st = cliente.get("/api/ml/eventos/status").get_json()
        if cond(st):
            return st
        time.sleep(0.05)
    raise AssertionError(st)


def test_status_mostra_fila_modos_e_fusao_pendente(cliente):
    st = cliente.get("/api/ml/eventos/status").get_json()
    s = st["servico"]
    assert s["trabalhador_ativo"] and s["fila"]["capacidade"] > 0
    assert s["fusao"]["validacao_preditiva"].startswith("pendente")
    assert st["fontes_replay"] == {"rede": "rede_teste_sem_rotulos.csv",
                                   "financeiro": "hismall_2022-09-10_sem_rotulo.csv"}
    assert "ao vivo" not in str(st).lower()


def test_ingestao_aceita_validos_e_explica_recusados(cliente):
    tx = {"tipo": "transacao", "dados": {
        "id_transacao": "api-1", "timestamp": "2022-09-10T05:31:00Z", "banco_origem": 1, "conta_origem": "A1",
        "banco_destino": 2, "conta_destino": "B2", "valor_pago": 10, "moeda_pagamento": "US Dollar",
        "valor_recebido": 10, "moeda_recebimento": "US Dollar", "formato": "ACH"}}
    ruim = {"tipo": "medicao_rede", "dados": {"id_fluxo": "1_2", "timestamp": 1, "rtt_ms": 3}}
    r = cliente.post("/api/ml/eventos", json={"eventos": [tx, ruim, {"tipo": "medicao_rede", "dados": _medicao()}]})
    assert r.status_code == 202
    corpo = r.get_json()
    assert corpo["aceitos"] == 2 and corpo["recusados"][0]["motivo"] == "invalido"
    st = _esperar(cliente, lambda st: st["servico"]["contadores"].get("previsoes_lavagem", 0) == 1
                  and st["servico"]["contadores"].get("previsoes_rede", 0) == 1)
    assert st["servico"]["api"]["contadores"]["recusados_invalido"] == 1
    rec = cliente.get("/api/ml/eventos/recentes?dominio=lavagem").get_json()["linhas"]
    assert rec[0]["id_transacao"] == "api-1" and rec[0]["modo_evento"] == "novo_evento"
    assert cliente.post("/api/ml/eventos", json={"eventos": []}).status_code == 400


def test_previsao_sincrona_de_medicoes(cliente):
    m = _medicao()
    r = cliente.post("/api/ml/prever/rede", json={"medicoes": [m, {"id_fluxo": "x"}]})
    assert r.status_code == 200
    corpo = r.get_json()
    p = corpo["previsoes"][0]
    assert p["id"] == f"{m['id_fluxo']}@{int(m['timestamp'])}" and p["horizonte"] == "proxima_medicao"
    assert set(p["probabilidades"]) == {"OK", "RISCO", "FALHA"} and p["versao_modelo"] == "teste-rede"
    assert {"instante_medicao_utc", "processado_em_utc", "classe_prevista", "score_alerta_rede", "alerta_rede",
            "limiar_alerta"} <= set(p)
    assert len(corpo["recusadas"]) == 1


def test_csv_de_rede_vira_fonte_na_exploracao(cliente):
    csv = gerar_rede(n_fluxos=2, por_split=(30, 0, 0)).drop(columns=["split", "alvo"]).to_csv(index=False)
    r = cliente.post("/api/ml/prever/rede/csv", data={"arquivo": (io.BytesIO(csv.encode()), "minha rede.csv")},
                     content_type="multipart/form-data")
    assert r.status_code == 201, r.get_json()
    fonte = r.get_json()["fonte_id"]
    assert fonte == "app:artefatos_ml/previsoes/minha_rede_previsoes_rede.csv"
    fontes = {f["id"]: f for f in cliente.get("/api/ml/fontes").get_json()["fontes"]}
    assert fontes[fonte]["conjunto"]["tipo"] == "completo" and fontes[fonte]["registros"] == 60
    resumo = cliente.get(f"/api/ml/fontes/{fonte}/resumo")
    assert resumo.status_code == 200
    ruim = cliente.post("/api/ml/prever/rede/csv", data={"arquivo": (io.BytesIO(b"a,b\n1,2\n"), "x.csv")},
                        content_type="multipart/form-data")
    assert ruim.status_code == 422 and ruim.get_json()["problemas"]


def test_replay_de_rede_e_financeiro_ate_o_fim(cliente):
    for fonte in ("rede", "financeiro"):
        r = cliente.post("/api/ml/eventos/replay", json={"fonte": fonte, "acao": "iniciar"})
        assert r.status_code == 200 and r.get_json()["modo"] == "replay_historico"
    st = _esperar(cliente, lambda st: all(x["situacao"] == "concluido" for x in st["replays"].values())
                  and len(st["replays"]) == 2)
    assert st["replays"]["rede"]["processados"] == st["replays"]["rede"]["total"] == 4 * 260
    assert st["replays"]["financeiro"]["processados"] == 800
    arquivos = {s["arquivo"] for s in st["servico"]["saidas"]}
    assert {"eventos_replay_historico_rede.csv", "eventos_replay_historico_lavagem.csv"} <= arquivos
    fontes = {f["id"] for f in cliente.get("/api/ml/fontes").get_json()["fontes"]}
    assert "app:artefatos_ml/previsoes/eventos_replay_historico_lavagem.csv" in fontes
    assert cliente.post("/api/ml/eventos/replay", json={"fonte": "x", "acao": "iniciar"}).status_code == 400


def test_laboratorio_pela_api(cliente):
    r = cliente.post("/api/ml/eventos/laboratorio")
    assert r.status_code == 200
    rel = r.get_json()["relatorio"]
    assert rel["todos_ok"] and "SIMULAÇÃO" in rel["aviso"]
    assert cliente.get("/api/ml/eventos/laboratorio").get_json()["relatorio"]["gerado_em"] == rel["gerado_em"]


def test_descartar_volta_ao_estado_vazio(cliente):
    cliente.post("/api/ml/eventos", json={"eventos": [{"tipo": "medicao_rede", "dados": _medicao()}]})
    _esperar(cliente, lambda st: st["servico"]["contadores"].get("previsoes_rede", 0) == 1)
    r = cliente.post("/api/ml/eventos/descartar")
    assert r.status_code == 200 and "eventos_novo_evento_rede.csv" in r.get_json()["removidos"]
    st = cliente.get("/api/ml/eventos/status").get_json()
    assert st["servico"]["contadores"] == {} and st["servico"]["saidas"] == []


def test_painel_tem_a_area_de_eventos(cliente):
    html = cliente.get("/").get_data(as_text=True)
    assert "#ml/eventos" in html and "<AreaEventos" in html and "não é fonte ao vivo" in html


def test_status_mostra_replay_restaurado_sem_objeto(cliente, tmp_path):
    cliente.post("/api/ml/eventos/replay", json={"fonte": "rede", "acao": "iniciar"})
    _esperar(cliente, lambda st: st["replays"].get("rede", {}).get("situacao") == "concluido")
    api_eventos.configurar(tmp_path, api_eventos._ctx["modelo"], Configuracao(fechar_ocioso_s=0.2))  # "reinicia"
    st = cliente.get("/api/ml/eventos/status").get_json()
    assert st["servico"]["restaurado"]["restaurado"] is True
    assert st["replays"]["rede"]["processados"] == 4 * 260 and st["replays"]["rede"]["total"] is None
