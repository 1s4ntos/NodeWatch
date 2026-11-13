"""Sentinel AI: leitura da chave, erros classificados do provedor, reserva local e sigilo da chave.

Tudo com provedor falso (nada sai do computador). A chave usada aqui é inventada, no formato de uma chave real,
justamente para provar que ela nunca aparece em resposta, log ou saída de erro.
"""

from __future__ import annotations

import httpx2 as httpx  # o google-genai 3.x usa o httpx2
import pytest
from google.genai import errors as gerros

from src import api_painel, sentinel_ia
from src.sentinel_ai import app
from testes.painel.conftest import abrir_cliente
from testes.painel.test_api_painel import _analisar, _cenario, _enviar, PADROES

CHAVE_FALSA = "AIzaSyTESTE0000000000000000000000000000"  # inventada; 39 caracteres como uma real


def _cliente_erro(codigo, mensagem, status="INVALID_ARGUMENT"):
    corpo = {"error": {"code": codigo, "message": mensagem, "status": status}}
    return (gerros.ServerError if codigo >= 500 else gerros.ClientError)(codigo, corpo)


class Provedor:
    """Provedor falso: devolve as respostas/erros da fila, na ordem."""

    def __init__(self, *fila):
        self.fila, self.chamadas = list(fila), []

    def __call__(self, system, messages):
        self.chamadas.append({"system": system, "messages": messages})
        item = self.fila.pop(0) if len(self.fila) > 1 else self.fila[0]
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture(autouse=True)
def estado_limpo(monkeypatch):
    monkeypatch.setattr(sentinel_ia, "_conexao", {"estado": "nao_verificado", "quando": None, "categoria": None, "mensagem": None})
    monkeypatch.setattr(sentinel_ia, "_gemini_client", None)
    monkeypatch.setattr(sentinel_ia, "PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", CHAVE_FALSA)
    monkeypatch.setattr(sentinel_ia, "_sdk_instalado", lambda: True)


@pytest.fixture
def cliente(tmp_path, fabrica_modelo):
    yield abrir_cliente(tmp_path, fabrica_modelo())
    api_painel._ctx.clear()


@pytest.fixture
def analise(cliente, tmp_path):
    _, reg = _enviar(cliente, _cenario(tmp_path), padroes=PADROES.encode("utf-8"))
    return _analisar(cliente, reg["id"])


def _provedor(monkeypatch, *fila):
    p = Provedor(*fila)
    monkeypatch.setattr(sentinel_ia, "_call_llm", p)
    return p


def _perguntar(cliente, analise, texto, **extra):
    return cliente.post("/api/painel/assistente", json={"pergunta": texto, "analise_id": analise["id"],
                                                        "usar_sentinel": True, **extra}).get_json()


# 1. leitura da chave pelo ambiente (o inicializador grava no .env, que o servidor carrega no ambiente)
def test_chave_lida_do_ambiente(monkeypatch):
    assert sentinel_ia._has_api_key() and sentinel_ia.situacao()["disponivel"]
    monkeypatch.setenv("GEMINI_API_KEY", "  ")
    assert not sentinel_ia._has_api_key()


def test_cliente_gemini_usa_api_v1beta_e_tempo_limite():
    # a causa do "ClientError": a API v1 recusa system_instruction ("Developer instruction is not enabled for api version v1")
    cli = sentinel_ia._get_gemini_client()
    opcoes = cli._api_client._http_options
    assert sentinel_ia.GEMINI_API_VERSION == "v1beta" and opcoes.api_version == "v1beta"
    assert opcoes.timeout == sentinel_ia.TEMPO_LIMITE_S * 1000


# 2. sem chave
def test_sem_chave_estado_nao_configurado_e_modo_local(cliente, analise, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    p = _provedor(monkeypatch, "não deveria ser chamado")
    assert sentinel_ia.estado_conexao()["estado"] == "nao_configurado"
    r = _perguntar(cliente, analise, "o que é o score?")
    assert r["modo"] == "local" and p.chamadas == [] and "GEMINI_API_KEY" in r["aviso"]
    v = cliente.post("/api/painel/assistente/verificar").get_json()
    assert v["estado"] == "nao_configurado" and v["categoria"] == "sem_chave"


# 3. chave inválida e demais códigos HTTP
@pytest.mark.parametrize("erro, categoria, de_novo", [
    (_cliente_erro(400, "API key not valid. Please pass a valid API key."), "chave_invalida", False),
    (_cliente_erro(401, "Request had invalid authentication credentials.", "UNAUTHENTICATED"), "autenticacao", False),
    (_cliente_erro(403, "The caller does not have permission", "PERMISSION_DENIED"), "permissao", False),
    (_cliente_erro(404, "models/gemini-x is not found", "NOT_FOUND"), "modelo_indisponivel", False),
    (_cliente_erro(400, "Developer instruction is not enabled for api version v1."), "requisicao_invalida", False),
    (_cliente_erro(429, "Resource has been exhausted", "RESOURCE_EXHAUSTED"), "limite", True),
    (_cliente_erro(503, "The model is overloaded", "UNAVAILABLE"), "servico_indisponivel", True),
    (httpx.ReadTimeout("tempo esgotado"), "timeout", True),
    (httpx.ConnectError("falha de DNS"), "conexao", True),
    (sentinel_ia.RespostaInvalida("resposta sem texto (finish_reason=SAFETY)"), "resposta_invalida", True),
    (RuntimeError("inesperado"), "erro_interno", True),
])
def test_erros_sao_classificados(erro, categoria, de_novo):
    info = sentinel_ia.classificar_erro(erro)
    assert info["categoria"] == categoria and info["tentar_de_novo"] is de_novo
    assert info["mensagem"] and info["acao"] and "ClientError" not in info["mensagem"]


# 4. sucesso
def test_sucesso_marca_conectado(cliente, analise, monkeypatch):
    _provedor(monkeypatch, "**Fatos**\nHá alertas no recorte.")
    r = _perguntar(cliente, analise, "Quais são os principais riscos encontrados?")
    assert r["modo"] == "sentinel" and r["conexao"]["estado"] == "conectado"
    assert cliente.get("/api/painel/estado").get_json()["assistente"]["sentinel"]["conexao"]["estado"] == "conectado"


# 5. resposta inválida (o provedor devolve sem texto)
def test_resposta_sem_texto_vira_resposta_invalida(monkeypatch):
    class Resp:
        text = None
        candidates = []

    class Modelos:
        def generate_content(self, **_):
            return Resp()

    class Cli:
        models = Modelos()

    monkeypatch.setattr(sentinel_ia, "_gemini_client", Cli())
    with pytest.raises(sentinel_ia.RespostaInvalida):
        sentinel_ia._call_gemini("sistema", [{"role": "user", "content": "oi"}])


# 6, 7, 8 e 9. timeout, conexão, limite → reserva local; falha NÃO é "fora da base"
@pytest.mark.parametrize("erro, categoria", [
    (httpx.ReadTimeout("tempo esgotado"), "timeout"),
    (httpx.ConnectError("sem rede"), "conexao"),
    (_cliente_erro(429, "Resource has been exhausted", "RESOURCE_EXHAUSTED"), "limite"),
])
def test_falha_usa_reserva_local_e_diz_o_motivo(cliente, analise, monkeypatch, erro, categoria):
    _provedor(monkeypatch, erro)
    # pergunta que o modo local sabe responder: a resposta local vem, com o aviso do que falhou
    r = _perguntar(cliente, analise, "o que é o score?")
    assert r["modo"] == "local" and r["sentinel_falha"]["categoria"] == categoria and r["base"]
    assert "O Sentinel AI não respondeu" in r["aviso"] and r["conexao"]["estado"] == "falhou"
    # pergunta fora do alcance do modo local: diz que o Sentinel falhou, não que a pergunta está fora da base
    r = _perguntar(cliente, analise, "Escreva um poema sobre a análise")
    assert r["tipo"] == "sentinel_indisponivel" and "fora da base" not in r["resposta"]
    assert r["sentinel_falha"]["tentar_de_novo"] is True


# 10. a pergunta é preservada e "Tentar de novo" funciona quando o serviço volta
def test_pergunta_preservada_e_nova_tentativa(cliente, analise, monkeypatch):
    p = _provedor(monkeypatch, httpx.ConnectError("sem rede"), "Resposta depois que a rede voltou.")
    pergunta = "Quais contas concentram mais alertas?"
    r = _perguntar(cliente, analise, pergunta)
    assert r["pergunta_preservada"] == pergunta
    r = _perguntar(cliente, analise, r["pergunta_preservada"])
    assert r["modo"] == "sentinel" and r["conexao"]["estado"] == "conectado"
    assert [c["messages"][-1]["content"] for c in p.chamadas] == [pergunta, pergunta]


# 11. endpoints: teste de conexão e chat da interface antiga
def test_endpoint_de_verificacao(cliente, monkeypatch):
    _provedor(monkeypatch, _cliente_erro(400, "API key not valid. Please pass a valid API key."), "OK")
    v = cliente.post("/api/painel/assistente/verificar").get_json()
    assert v["estado"] == "falhou" and v["categoria"] == "chave_invalida" and "detalhe_tecnico" not in v
    v = cliente.post("/api/painel/assistente/verificar").get_json()
    assert v["estado"] == "conectado"


def test_chat_antigo_classifica_o_erro(monkeypatch):
    _provedor(monkeypatch, _cliente_erro(429, "Resource has been exhausted", "RESOURCE_EXHAUSTED"))
    app.config["TESTING"] = True
    resp = app.test_client().post("/api/chat", json={"messages": [{"role": "user", "content": "oi"}]})
    corpo = resp.get_json()
    if resp.status_code in (401, 403):  # proteção local ativa neste processo: o chat não chega ao provedor
        pytest.skip("rota protegida pela segurança local")
    assert resp.status_code == 429 and corpo["categoria"] == "limite" and corpo["tentar_de_novo"] is True


# 12. a chave nunca aparece em resposta, log do sistema ou saída de erro
def test_chave_nunca_aparece(cliente, analise, monkeypatch, tmp_path, capsys):
    vazamento = _cliente_erro(400, f"API key not valid: {CHAVE_FALSA}")
    _provedor(monkeypatch, vazamento)
    r = cliente.post("/api/painel/assistente", json={"pergunta": "Escreva um poema", "analise_id": analise["id"],
                                                      "usar_sentinel": True}).get_data(as_text=True)
    v = cliente.post("/api/painel/assistente/verificar").get_data(as_text=True)
    e = cliente.get("/api/painel/estado").get_data(as_text=True)
    saida = capsys.readouterr()
    logs = "".join(f.read_text(encoding="utf-8", errors="replace") for f in tmp_path.rglob("*") if f.is_file()
                   and f.suffix in (".jsonl", ".log", ".json", ".txt"))
    for texto in (r, v, e, saida.out, saida.err, logs):
        assert CHAVE_FALSA not in texto
    assert "***" in saida.err  # o detalhe técnico foi para o log, mascarado
    assert CHAVE_FALSA not in sentinel_ia.classificar_erro(vazamento)["detalhe_tecnico"]
