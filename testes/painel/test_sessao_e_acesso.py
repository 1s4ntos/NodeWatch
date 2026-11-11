"""Sessão da interface no fluxo de análise e acesso local (origem, Host e CORS)."""

from __future__ import annotations

import io
import time

import pytest

pytest.importorskip("flask")

from src import api_painel, seguranca_local  # noqa: E402
from src.ml.sessoes import PULSO_S, TTL_S  # noqa: E402
from testes.painel.conftest import (CENARIO, D, Ambiente, Portao, abrir_cliente, escrever,  # noqa: E402
                                    linha)

CAB = "X-NodeWatch-Sessao"


def _muitas(n: int = 30):
    return [linha(f"{D} {10 + i // 60:02d}:{i % 60:02d}", 1, f"C{i % 7}", 2, f"K{i % 5}", 1_000 + i) for i in range(n)]


def _enviar(c, tmp_path, linhas=None, nome="d.csv", **kw):
    conteudo = escrever(tmp_path / nome, linhas or CENARIO, com_rotulo=linhas is None).read_bytes()
    r = c.post("/api/painel/datasets", data={"arquivo": (io.BytesIO(conteudo), nome)}, content_type="multipart/form-data", **kw)
    if r.status_code != 201:
        return r, r.get_json()
    for _ in range(300):
        reg = c.get(f"/api/painel/datasets/{r.get_json()['id']}").get_json()
        if reg["status"] != "validando":
            return r, reg
        time.sleep(0.02)
    raise AssertionError("validação não terminou")


def _esperar_fim(c, aid: str) -> dict:
    for _ in range(500):
        m = c.get(f"/api/painel/analises/{aid}").get_json()
        if m["status"] != "em_andamento":
            return m
        time.sleep(0.02)
    raise AssertionError("análise não terminou")


@pytest.fixture
def cliente(tmp_path, fabrica_modelo):
    yield abrir_cliente(tmp_path, fabrica_modelo())
    api_painel._ctx.clear()


@pytest.fixture
def em_curso(tmp_path, fabrica_modelo):
    """Análise de 30 transações parada dentro do 3º bloco (10 já gravadas): ``(cliente, id, portão)``."""
    portao = Portao()
    c = abrir_cliente(tmp_path, fabrica_modelo(portao.em(3)), bloco=5)
    _, reg = _enviar(c, tmp_path, _muitas(30))
    aid = c.post("/api/painel/analises", json={"dataset_id": reg["id"]}).get_json()["id"]
    assert portao.chegou.wait(30)
    yield c, aid, portao
    portao.liberar.set()
    _esperar_fim(c, aid)
    api_painel._ctx.clear()


# -- a sessão é exigida para processar; consultar não exige e não inicia nada ---------------------
def test_politica_da_sessao_e_documentada_no_estado(cliente):
    s = cliente.get("/api/painel/estado").get_json()["sessao"]
    assert (s["ttl_s"], s["pulso_s"]) == (TTL_S, PULSO_S) == (150.0, 15.0) and s["cabecalho"] == CAB
    assert "150 s" in s["leitura"] and "Minimizar ou trocar de aba não encerra" in s["leitura"] and "retomado sozinho" in s["leitura"]
    ver = cliente.get("/api/painel/sessao").get_json()
    assert ver["ativa"] is True and ver["sessao"]["ativa"] is True and ver["politica"]["ttl_s"] == 150.0


def test_sem_sessao_nada_e_processado(cliente, tmp_path):
    bruto = cliente.bruto  # sem o cabeçalho da sessão
    conteudo = escrever(tmp_path / "c.csv", CENARIO, com_rotulo=True).read_bytes()
    r = bruto.post("/api/painel/datasets", data={"arquivo": (io.BytesIO(conteudo), "c.csv")}, content_type="multipart/form-data")
    assert r.status_code == 403 and r.get_json()["sessao_inativa"] is True and "Nada foi processado" in r.get_json()["acao"]
    assert bruto.get("/api/painel/datasets").get_json()["datasets"] == []
    _, reg = _enviar(cliente, tmp_path)                        # com sessão: envia e valida
    for rota, corpo in ((f"/api/painel/datasets/{reg['id']}/validar", None), ("/api/painel/analises", {"dataset_id": reg["id"]})):
        for cab in ({}, {CAB: "sessao-que-nao-existe"}):
            r = bruto.post(rota, json=corpo, headers=cab)
            assert r.status_code == 403 and r.get_json()["sessao_inativa"] is True, rota
    assert bruto.get("/api/painel/analises").get_json()["analises"] == []
    # consultas funcionam sem sessão e não iniciam nada
    for rota in ("/api/painel/estado", "/api/painel/datasets", "/api/painel/analises", f"/api/painel/datasets/{reg['id']}",
                 "/api/painel/operacao/logs", "/api/painel/sessao"):
        assert bruto.get(rota).status_code == 200, rota
    assert bruto.get("/api/painel/estado").get_json()["analise_em_andamento"] is None
    assert list((tmp_path / "artefatos_ml" / "painel" / "analises").iterdir()) == []


def test_pulso_renova_e_a_sessao_expira_sem_ele(cliente):
    for _ in range(4):                                         # pulsos a cada 100 s: nunca passa de 150 s sem sinal
        cliente.relogio.avancar(100)
        assert cliente.post("/api/painel/sessao/pulso").get_json()["ativa"] is True
    cliente.relogio.avancar(TTL_S + 1)                         # 151 s sem pulso
    r = cliente.post("/api/painel/sessao/pulso")
    assert r.status_code == 410 and r.get_json()["ativa"] is False and "não é retomada sozinha" in r.get_json()["acao"]
    assert cliente.get("/api/painel/sessao").get_json()["ativa"] is False
    assert cliente.post("/api/painel/analises", json={"dataset_id": "ds-000000000000"}).status_code == 403


# -- durante a análise ---------------------------------------------------------------------------
def test_analise_para_em_ponto_seguro_quando_a_sessao_expira_e_nao_e_retomada(em_curso, tmp_path, fabrica_modelo):
    c, aid, portao = em_curso
    vivo = c.get(f"/api/painel/analises/{aid}").get_json()
    assert vivo["sessao"] == {**vivo["sessao"], "exigida": True, "desta_sessao": True, "responsavel_ativa": True, "janela_s": 150.0}
    c.relogio.avancar(TTL_S + 1)                               # a aba fechou: nenhum pulso por 151 s
    assert c.get(f"/api/painel/analises/{aid}").get_json()["sessao"]["responsavel_ativa"] is False
    portao.liberar.set()                                       # o bloco em curso termina; o ponto seguro vem em seguida
    fim = _esperar_fim(c, aid)
    assert fim["status"] == "parcial" and fim["interrupcao"] == "sessao_expirada"
    assert fim["resultados"] == {"disponiveis": True, "parciais": True, "pontuadas": 15, "de": 30}
    assert "sessão da interface" in fim["motivo"] and "150 s" in fim["motivo"] and "não é retomada sozinha" in fim["motivo"]
    assert {e["id"]: e["status"] for e in fim["etapas"]}["pontuacao"] == "interrompida"
    eventos = [e["evento"] for e in c.get("/api/painel/operacao/logs?tipo=sistema").get_json()["entradas"]]
    assert "analise_sessao_expirada" in eventos
    # o parcial é consultável, sem sessão
    assert c.bruto.get(f"/api/painel/analises/{aid}/visao").get_json()["registros"]["dataset"] == 15
    # reabrir a interface (nova sessão) não retoma nada
    nova = c.bruto.post("/api/painel/sessao", json={}).get_json()["sessao"]["id"]
    for _ in range(3):
        assert c.bruto.post("/api/painel/sessao/pulso", headers={CAB: nova}).get_json()["ativa"] is True
        assert c.bruto.get(f"/api/painel/analises/{aid}", headers={CAB: nova}).get_json()["status"] == "parcial"
        assert c.bruto.get("/api/painel/estado", headers={CAB: nova}).get_json()["analise_em_andamento"] is None
        time.sleep(0.05)
    assert c.bruto.get(f"/api/painel/analises/{aid}").get_json()["contagens"]["pontuadas"] == 15
    # reiniciar o servidor também não retoma: o manifesto continua parcial e o modelo nem é carregado

    def proibido(chamada: int) -> None:
        raise AssertionError("nenhuma análise pode recomeçar sozinha")

    outro = abrir_cliente(tmp_path, fabrica_modelo(proibido), bloco=5)
    lista = outro.get("/api/painel/analises").get_json()["analises"]
    assert [(a["id"], a["status"], a["registros"]) for a in lista] == [(aid, "parcial", 15)]
    assert outro.get("/api/painel/estado").get_json()["analise_em_andamento"] is None


def test_aba_em_segundo_plano_nao_e_tratada_como_fechamento(em_curso):
    c, aid, portao = em_curso
    for _ in range(6):                                         # navegador espaça os pulsos para 1 por minuto
        c.relogio.avancar(60)
        assert c.post("/api/painel/sessao/pulso").get_json()["ativa"] is True
    assert c.get(f"/api/painel/analises/{aid}").get_json()["sessao"]["responsavel_ativa"] is True
    portao.liberar.set()
    fim = _esperar_fim(c, aid)
    assert fim["status"] == "concluida" and fim["contagens"]["pontuadas"] == 30 and "interrupcao" not in fim


def test_encerrar_a_sessao_interrompe_a_analise(em_curso):
    c, aid, portao = em_curso
    assert c.post("/api/painel/sessao/encerrar").get_json()["encerrada"] is True
    portao.liberar.set()
    fim = _esperar_fim(c, aid)
    assert fim["status"] == "parcial" and fim["interrupcao"] == "sessao_expirada" and fim["resultados"]["pontuadas"] == 15


def test_outra_aba_ativa_pode_assumir_ou_cancelar(em_curso):
    c, aid, portao = em_curso
    outra = c.bruto.post("/api/painel/sessao", json={}).get_json()["sessao"]["id"]
    ver = c.bruto.get(f"/api/painel/analises/{aid}", headers={CAB: outra}).get_json()["sessao"]
    assert ver["desta_sessao"] is False and ver["responsavel_ativa"] is True      # consultar não transfere nada
    assert c.bruto.post(f"/api/painel/analises/{aid}/assumir").status_code == 403  # sem sessão não assume
    assumida = c.bruto.post(f"/api/painel/analises/{aid}/assumir", headers={CAB: outra}).get_json()
    assert assumida["sessao"]["desta_sessao"] is True
    c.relogio.avancar(100)
    assert c.bruto.post("/api/painel/sessao/pulso", headers={CAB: outra}).get_json()["ativa"] is True
    c.relogio.avancar(100)                                     # a primeira aba está há 200 s sem sinal; a segunda, há 100 s
    assert c.post("/api/painel/sessao/pulso").status_code == 410
    portao.liberar.set()
    assert _esperar_fim(c, aid)["status"] == "concluida"


def test_cancelar_exige_sessao_ativa(em_curso):
    c, aid, portao = em_curso
    assert c.bruto.post(f"/api/painel/analises/{aid}/cancelar").status_code == 403
    assert c.get(f"/api/painel/analises/{aid}").get_json()["cancelamento_solicitado"] is False
    assert c.post(f"/api/painel/analises/{aid}/cancelar").get_json()["cancelamento_solicitado"] is True
    portao.liberar.set()
    assert _esperar_fim(c, aid)["status"] == "cancelada"


def test_validacao_para_quando_a_sessao_deixa_de_estar_ativa(tmp_path, fabrica_modelo):
    amb = Ambiente(tmp_path, fabrica_modelo())
    with open(escrever(tmp_path / "c.csv", CENARIO, com_rotulo=True), "rb") as fh:
        reg = amb.datasets.enviar(fh, "c.csv", validar=False)
    parado = amb.datasets.validar(reg["id"], esperar=True, ativa=lambda: False)
    assert parado["status"] == "erro" and "sessão" in parado["erro"]["problemas"][0]["problema"]
    assert "Validar" in parado["erro"]["problemas"][0]["como_corrigir"]
    assert amb.datasets.validar(reg["id"], esperar=True, ativa=lambda: True)["status"] == "valido"
    assert "validacao_interrompida" in [e["evento"] for e in amb.registro.listar("sistema")]


def test_gerenciador_sem_controle_de_sessao_continua_valendo_para_uso_direto(ambiente, cenario):
    m = ambiente.analisar(cenario["dados"])
    assert m["status"] == "concluida" and m["sessao"]["exigida"] is False


# -- origem, Host e CORS ---------------------------------------------------------------------------
EXTERNA = "http://site-externo.example"


def test_pagina_externa_nao_inicia_analise_nem_le_dados(cliente, tmp_path):
    _, reg = _enviar(cliente, tmp_path)
    bruto, cab = cliente.bruto, {CAB: cliente.sid, "Origin": EXTERNA}
    # mesmo com uma sessão válida "roubada", a origem externa é recusada antes de qualquer rota rodar
    r = bruto.post("/api/painel/analises", json={"dataset_id": reg["id"]}, headers=cab)
    assert r.status_code == 403 and "outra origem" in r.get_json()["erro"]
    conteudo = escrever(tmp_path / "x.csv", CENARIO, com_rotulo=True).read_bytes()
    r = bruto.post("/api/painel/datasets", data={"arquivo": (io.BytesIO(conteudo), "x.csv")}, content_type="multipart/form-data", headers=cab)
    assert r.status_code == 403
    for rota in ("/api/painel/datasets", "/api/painel/analises", "/api/painel/estado", f"/api/painel/datasets/{reg['id']}",
                 "/api/painel/operacao/logs", "/api/ml/status"):
        r = bruto.get(rota, headers={"Origin": EXTERNA})
        assert r.status_code == 403 and "Access-Control-Allow-Origin" not in r.headers, rota
    assert bruto.post("/api/painel/sessao", json={}, headers={"Origin": EXTERNA}).status_code == 403   # nem abre sessão
    assert bruto.post("/api/ml/sessao", json={}, headers={"Origin": EXTERNA}).status_code == 403       # rotas antigas também
    # nada foi criado
    assert cliente.get("/api/painel/analises").get_json()["analises"] == []
    assert [d["nome"] for d in cliente.get("/api/painel/datasets").get_json()["datasets"]] == ["d.csv"]


def test_pre_verificacao_cors_de_outra_origem_e_recusada_e_nao_ha_curinga(cliente):
    r = cliente.options("/api/painel/analises", headers={"Origin": EXTERNA, "Access-Control-Request-Method": "POST",
                                                         "Access-Control-Request-Headers": "content-type,x-nodewatch-sessao"})
    assert r.status_code == 403 and "Access-Control-Allow-Origin" not in r.headers
    for rota in ("/api/painel/estado", "/api/painel/datasets", "/api/ml/status", "/"):
        cabs = cliente.get(rota).headers
        assert cabs.get("Access-Control-Allow-Origin") is None, rota   # sem CORS: a página e a API têm a mesma origem
    assert cliente.get("/api/painel/estado").get_json()["acesso"] == {"origens": "somente a própria página (mesma origem)",
                                                                    "cors_curinga": False}


def test_mesma_origem_e_clientes_locais_sem_origem_sao_aceitos(cliente, tmp_path):
    assert cliente.get("/api/painel/estado", headers={"Origin": "http://localhost"}).status_code == 200
    assert cliente.post("/api/painel/sessao/pulso", headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"}).status_code == 200
    r, reg = _enviar(cliente, tmp_path)                      # sem Origin (curl, scripts locais): aceito, com sessão
    assert r.status_code == 201 and reg["status"] == "valido"


def test_escrita_entre_sites_com_origem_nula_e_recusada(cliente, tmp_path):
    _, reg = _enviar(cliente, tmp_path)
    for cab in ({"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "cross-site", "Origin": "null"}, {"Sec-Fetch-Site": "same-site"},
                {"Origin": "null"}, {"Origin": "http://localhost:3000"}, {"Origin": "https://localhost"}):
        r = cliente.post("/api/painel/analises", json={"dataset_id": reg["id"]}, headers=cab)
        assert r.status_code == 403, cab
    assert cliente.get("/api/painel/analises").get_json()["analises"] == []


def test_host_nao_local_e_recusado(cliente):
    for rota in ("/", "/api/painel/estado", "/legado"):
        r = cliente.bruto.get(rota, base_url="http://nodewatch.atacante.example")   # DNS rebinding
        assert r.status_code == 403 and "local" in r.get_json()["erro"], rota
    assert cliente.bruto.get("/", base_url="http://127.0.0.1:5000").status_code == 200
    assert cliente.bruto.get("/api/painel/estado", base_url="http://localhost:5000").status_code == 200


def test_regras_de_acesso_local():
    v = seguranca_local.verificar
    assert v("GET", "/api/painel/estado", "http", "127.0.0.1:5000", None, None) is None
    assert v("POST", "/api/painel/analises", "http", "127.0.0.1:5000", "http://127.0.0.1:5000", "same-origin") is None
    assert v("POST", "/api/painel/analises", "http", "127.0.0.1:5000", "http://localhost:5000", "same-site")[0] == 403  # outra origem
    assert v("POST", "/api/painel/analises", "http", "127.0.0.1:5000", "http://127.0.0.1:8080", None)[0] == 403         # outra porta
    assert v("GET", "/assets/painel.css", "http", "127.0.0.1:5000", EXTERNA, None) is None       # estáticos não têm dados do usuário
    assert v("GET", "/", "http", "192.168.0.10:5000", None, None)[0] == 403
    assert v("GET", "/", "http", "192.168.0.10:5000", None, None, host_configurado="192.168.0.10") is None
    assert v("GET", "/", "http", "[::1]:5000", None, None) is None
    # origem extra só por configuração explícita; o curinga é ignorado
    assert seguranca_local.origens_extras(" http://a.test/ , * ,null,, ") == ["http://a.test", "null"]
    assert seguranca_local.origens_extras(None) == [] and seguranca_local.origens_extras("*") == []
    assert v("POST", "/api/x", "http", "127.0.0.1:5000", "http://a.test", "cross-site", extras=["http://a.test"]) is None
    assert v("POST", "/api/x", "http", "127.0.0.1:5000", "http://b.test", "cross-site", extras=["http://a.test"])[0] == 403


def test_servidor_e_local_por_padrao_e_sem_cors_curinga(monkeypatch):
    import importlib
    import os

    from src import sentinel_ai
    if "SENTINEL_HOST" not in os.environ:
        assert sentinel_ai.HOST == "127.0.0.1"
    if not os.environ.get("NODEWATCH_ORIGENS"):
        assert sentinel_ai.ORIGENS_EXTRAS == []
    fonte = importlib.util.find_spec("src.sentinel_ai").origin
    texto = open(fonte, encoding="utf-8").read()
    assert "\nCORS(app)\n" not in texto and 'origins="*"' not in texto and "origins='*'" not in texto
