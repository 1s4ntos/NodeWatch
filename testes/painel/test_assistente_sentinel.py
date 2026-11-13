"""Assistente de dúvidas por dentro: Sentinel AI com o contexto da análise, autorização e reserva local.

O provedor de IA é trocado por um falso que registra o que receberia: nada sai do computador nos testes.
"""

from __future__ import annotations

import json
import re

import pytest

from src import api_painel, sentinel_ia
from src.sentinel_ai import app
from testes.painel.conftest import abrir_cliente
from testes.painel.test_api_painel import _analisar, _cenario, _enviar, PADROES


@pytest.fixture
def cliente(tmp_path, fabrica_modelo):
    yield abrir_cliente(tmp_path, fabrica_modelo())
    api_painel._ctx.clear()


@pytest.fixture
def analise(cliente, tmp_path):
    _, reg = _enviar(cliente, _cenario(tmp_path), padroes=PADROES.encode("utf-8"))
    return _analisar(cliente, reg["id"])


class ProvedorFalso:
    def __init__(self, resposta="**Fatos**\nHá 5 transações com alerta.\n\n**Limitacoes**\nNão sei mais.", erro=None):
        self.chamadas, self.resposta, self.erro = [], resposta, erro

    def __call__(self, system, messages):
        self.chamadas.append({"system": system, "messages": messages})
        if self.erro:
            raise self.erro
        return self.resposta


@pytest.fixture
def com_chave(monkeypatch):
    monkeypatch.setattr(sentinel_ia, "_has_api_key", lambda: True)
    monkeypatch.setattr(sentinel_ia, "_sdk_instalado", lambda: True)
    falso = ProvedorFalso()
    monkeypatch.setattr(sentinel_ia, "_call_llm", falso)
    return falso


def _contexto(chamada):
    bruto = chamada["system"].split("## contexto_painel (JSON)", 1)[1]
    return json.loads(re.search(r"```json\n(.*)\n```", bruto, re.S).group(1))


def _perguntar(cliente, analise, texto, **extra):
    return cliente.post("/api/painel/assistente", json={"pergunta": texto, "analise_id": analise["id"], **extra}).get_json()


def test_sem_autorizacao_nada_sai_do_computador(cliente, analise, com_chave):
    r = _perguntar(cliente, analise, "quantos alertas no recorte?")
    assert r["modo"] == "local" and com_chave.chamadas == []


def test_autorizado_sem_chave_responde_no_modo_local_e_explica(cliente, analise, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)  # o .env local pode ter uma chave real
    monkeypatch.setattr(sentinel_ia, "PROVIDER", "gemini")
    falso = ProvedorFalso()
    monkeypatch.setattr(sentinel_ia, "_call_llm", falso)
    r = _perguntar(cliente, analise, "quantos alertas no recorte?", usar_sentinel=True)
    assert r["modo"] == "local" and "GEMINI_API_KEY" in r["aviso"] and falso.chamadas == []


def test_sentinel_recebe_o_contexto_verificado_da_analise(cliente, analise, com_chave):
    r = _perguntar(cliente, analise, "Quais são os principais riscos encontrados?", usar_sentinel=True,
                   filtros={"moeda": "US Dollar"}, historico=[{"role": "user", "content": "oi"},
                                                              {"role": "assistant", "content": "olá"}],
                   modo_linguagem="tecnica")
    assert r["modo"] == "sentinel" and r["resposta"].startswith("**Fatos**") and "Sentinel AI" in r["motor"]
    assert r["contexto_enviado"] and "não decide" in r["aviso"]
    chamada = com_chave.chamadas[0]
    # mesmo motor do chat original: prompt de sistema original + modo de linguagem + bloco do painel
    assert chamada["system"].startswith(sentinel_ia.SYSTEM_PROMPT)
    assert sentinel_ia.LANGUAGE_PROMPT_TECNICA in chamada["system"] and sentinel_ia.PROMPT_PAINEL in chamada["system"]
    assert chamada["messages"][-1] == {"role": "user", "content": "Quais são os principais riscos encontrados?"}
    assert [m["role"] for m in chamada["messages"]] == ["user", "assistant", "user"]
    ctx = _contexto(chamada)
    assert ctx["analise"]["id"] == analise["id"] and ctx["analise"]["aberta"] is True
    assert ctx["recorte"]["filtros_aplicados"] == {"moeda": "US Dollar"}
    assert "registros" in ctx["recorte"] and "contas_de_maior_risco" in ctx["recorte"]
    assert ctx["alertas_principais"]["maiores_scores"], "deveria levar as transações com alerta"
    scores = [t["score"] for t in ctx["alertas_principais"]["maiores_scores"]]
    assert scores == sorted(scores, reverse=True) and all(t["alerta"] for t in ctx["alertas_principais"]["maiores_scores"])
    # a cabeça de teste é uma regra fixa, sem floresta: não há importâncias, e a lista vem vazia (nada inventado)
    assert ctx["modelo"]["importancias_globais"]["maiores"] == [] and "não a decisão" in ctx["modelo"]["importancias_globais"]["o_que_e"]
    assert ctx["modelo"]["versao"] == "teste-painel-v1"
    assert any("não há explicação por transação" in x for x in ctx["limites"])
    assert "transacao_em_foco" not in ctx


def test_transacao_em_foco_vai_no_contexto_com_score_e_motivos(cliente, analise, com_chave):
    alvo = cliente.get(f"/api/painel/analises/{analise['id']}/transacoes?alerta=sim&ordenar=score&direcao=desc").get_json()["linhas"][0]
    _perguntar(cliente, analise, "Por que essa transação foi classificada como suspeita?", usar_sentinel=True,
               transacao_id=alvo["id_exibicao"])
    t = _contexto(com_chave.chamadas[0])["transacao_em_foco"]
    # o ID vai só no formato da tela (TX- e ao menos 6 dígitos), sem o número cru ao lado
    assert re.fullmatch(r"TX-\d{6,}", t["id_na_tela"]) and int(t["id_na_tela"][3:]) == alvo["id_exibicao"]
    assert "id_exibicao" not in t and t["score"] == alvo["score"] and t["alerta"] is True
    assert all(re.fullmatch(r"TX-\d{6,}", x["id_na_tela"]) and "id_exibicao" not in x
               for x in _contexto(com_chave.chamadas[0])["alertas_principais"]["maiores_scores"])
    assert "`id_na_tela`" in sentinel_ia.PROMPT_PAINEL and "TX-" in sentinel_ia.PROMPT_PAINEL
    assert "score_bruto" in t and "motivos" in t and "historico_incompleto" in t


def test_falha_do_provedor_cai_no_modo_local_e_fica_no_log(cliente, analise, monkeypatch):
    monkeypatch.setattr(sentinel_ia, "_has_api_key", lambda: True)
    monkeypatch.setattr(sentinel_ia, "_sdk_instalado", lambda: True)
    monkeypatch.setattr(sentinel_ia, "_call_llm", ProvedorFalso(erro=TimeoutError("sem rede")))
    r = _perguntar(cliente, analise, "quantos alertas no recorte?", usar_sentinel=True)
    assert r["modo"] == "local" and r["sentinel_falha"]["categoria"] == "timeout" and "demorou" in r["aviso"]
    assert "5 transações com alerta" in r["resposta"] and "TimeoutError" not in r["aviso"]  # detalhe técnico só no log
    logs = cliente.get("/api/painel/operacao/logs?tipo=sistema").get_json()["entradas"]
    assert any(e["evento"] == "assistente_sentinel_falhou" for e in logs)


def test_resposta_vazia_do_provedor_nao_e_mostrada_como_resposta(cliente, analise, monkeypatch):
    monkeypatch.setattr(sentinel_ia, "_has_api_key", lambda: True)
    monkeypatch.setattr(sentinel_ia, "_sdk_instalado", lambda: True)
    monkeypatch.setattr(sentinel_ia, "_call_llm", ProvedorFalso(resposta="  "))
    r = _perguntar(cliente, analise, "o que é o score?", usar_sentinel=True)
    assert r["modo"] == "local" and r["sentinel_falha"]["categoria"] == "resposta_invalida" and r["aviso"]


def test_sentinel_exige_sessao_ativa_para_enviar_dados(cliente, analise, com_chave):
    sem_sessao = cliente.bruto.post("/api/painel/assistente", json={
        "pergunta": "principais riscos?", "analise_id": analise["id"], "usar_sentinel": True})
    assert sem_sessao.status_code == 403 and com_chave.chamadas == []


def test_sem_analise_aberta_o_contexto_diz_isso(cliente, com_chave):
    cliente.post("/api/painel/assistente", json={"pergunta": "o que é o score?", "usar_sentinel": True})
    ctx = _contexto(com_chave.chamadas[0])
    assert ctx["analise"]["aberta"] is False and "escala_do_score" in ctx


def test_modo_local_explica_a_transacao_em_foco_sem_inventar_atributos(cliente, analise):
    alvo = cliente.get(f"/api/painel/analises/{analise['id']}/transacoes?alerta=sim&ordenar=score&direcao=desc").get_json()["linhas"][0]
    r = _perguntar(cliente, analise, "por que essa transação foi classificada assim?", transacao_id=alvo["id_exibicao"])
    assert r["modo"] == "local" and f"score {alvo['score']} de 1000" in r["resposta"]
    assert re.search(r"Transação TX-\d{6,}:", r["resposta"])
    assert "não grava quanto cada atributo pesou" in r["resposta"]
    r = _perguntar(cliente, analise, "essa transação é fraude?", transacao_id=alvo["id_exibicao"])
    assert r["tipo"] == "limite"


def test_estado_mostra_o_nome_da_tela_e_a_tecnologia(cliente):
    a = cliente.get("/api/painel/estado").get_json()["assistente"]
    assert a["nome"] == "Assistente de dúvidas" and a["tecnologia"] == "Sentinel AI"
    assert a["servico_externo"] is False and a["sentinel"]["servico_externo"] is True
    assert a["sentinel"]["envia"] and "arquivo do dataset" in a["sentinel"]["nao_envia"]


def test_chat_da_interface_antiga_usa_o_mesmo_motor(monkeypatch):
    from src import sentinel_ai
    falso = ProvedorFalso(resposta="resposta antiga")
    monkeypatch.setattr(sentinel_ai, "_has_api_key", lambda: True)
    monkeypatch.setattr(sentinel_ia, "_call_llm", falso)  # a rota chama o motor (sentinel_ia)
    r = app.test_client().post("/api/chat", json={"messages": [{"role": "user", "content": "oi"}], "languageMode": "tecnica"})
    assert r.status_code == 200 and r.get_json()["content"] == "resposta antiga"
    assert falso.chamadas[0]["system"].startswith(sentinel_ia.SYSTEM_PROMPT)
    assert sentinel_ia.PROMPT_PAINEL not in falso.chamadas[0]["system"]  # o chat antigo continua como era


def test_nome_na_tela_continua_assistente_de_duvidas():
    from pathlib import Path
    secoes = (Path(__file__).resolve().parents[2] / "interface" / "assets" / "painel-secoes.js").read_text(encoding="utf-8")
    assistente = secoes[secoes.index("function Assistente("):secoes.index("Object.assign(window.NW")]
    # o nome do assistente (título do painel e botão) continua "Assistente de dúvidas"
    assert "'rotulo-longo' }, 'Assistente de dúvidas'" in assistente and "'rotulo-curto' }, 'Dúvidas'" in assistente
    assert "h('h2', { id: 'assistente-t', style: { fontSize: '1rem' } }, 'Assistente de dúvidas')" in assistente
    # "Sentinel AI" só aparece como a tecnologia por trás dele, nunca como título, botão ou rótulo de navegação
    assert not re.search(r"h\('(h2|h3|button)'[^)]*\}, 'Sentinel AI'", assistente)
    assert "'rotulo-longo' }, 'Sentinel" not in secoes and "'Tecnologia Sentinel AI" in assistente


def test_importancias_globais_vem_da_floresta_real():
    import numpy as np
    import pandas as pd
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.feature_selection import VarianceThreshold
    from sklearn.pipeline import Pipeline

    from src.ml.modelos import CabecaClassificacao
    from src.painel.contexto_sentinel import importancias_globais

    rng = np.random.default_rng(0)
    X = pd.DataFrame({"forte": rng.random(400), "fraco": rng.random(400), "constante": 1.0})
    y = (X["forte"] > 0.5).astype(int)
    pipe = Pipeline([("constantes", VarianceThreshold(0.0)),
                     ("modelo", RandomForestClassifier(n_estimators=20, random_state=0))]).set_output(transform="pandas")
    pipe.fit(X, y)

    class Modelo:
        def cabeca(self, nome):
            return CabecaClassificacao("lavagem", pipe, [0, 1], list(X.columns), "random_forest", {}, 0.5,
                                       metadados={"versao": "t"})

    imp = importancias_globais(Modelo())
    assert [i["atributo"] for i in imp] == ["forte", "fraco"]      # a coluna constante sai no VarianceThreshold
    assert imp[0]["importancia"] > imp[1]["importancia"]


def test_chave_sem_a_biblioteca_do_provedor_nao_libera_o_sentinel(cliente, analise, monkeypatch):
    """Um .venv antigo pode ter a chave e não ter o google-genai: a tela não oferece o Sentinel e explica o que falta."""
    monkeypatch.setattr(sentinel_ia, "_has_api_key", lambda: True)
    monkeypatch.setattr(sentinel_ia, "_sdk_instalado", lambda: False)
    falso = ProvedorFalso()
    monkeypatch.setattr(sentinel_ia, "_call_llm", falso)
    s = cliente.get("/api/painel/estado").get_json()["assistente"]["sentinel"]
    assert s["disponivel"] is False and "requirements.txt" in s["como_ativar"] and "google-genai" in s["como_ativar"]
    r = _perguntar(cliente, analise, "quantos alertas no recorte?", usar_sentinel=True)
    assert r["modo"] == "local" and "google-genai" in r["aviso"] and falso.chamadas == []
