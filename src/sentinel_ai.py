"""Sentinel AI - Assistente tecnico integrado ao dashboard NodeWatch.

Servidor Flask que expoe um endpoint de chat conectado a uma API de LLM,
usando o system prompt do Sentinel AI para auxiliar analistas na
interpretacao de alertas e navegacao pela interface.

Provedores suportados:
    - gemini  (padrao) — Google Gemini via google-genai
    - anthropic        — Anthropic Claude via anthropic SDK

Tambem serve o painel (rota /), a API somente leitura da secao
"Machine Learning" (/api/ml, em src/api_ml.py) e a API de eventos e previsao
sob demanda (/api/ml/eventos e /api/ml/prever, em src/api_eventos.py). As
duas funcionam sem chave de API.

Uso:
    1. Copie .env.example para .env e insira sua GEMINI_API_KEY (so o chat precisa)
    2. python src/sentinel_ai.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Carrega variaveis do .env (raiz do projeto)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# Permite importar src.* tanto via ``python src/sentinel_ai.py`` quanto ``python -m src.sentinel_ai``
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from src.api_ml import bp as ml_bp  # noqa: E402
from src.api_eventos import bp as eventos_bp, encerrar as encerrar_eventos  # noqa: E402
from src.api_painel import bp as painel_bp  # noqa: E402

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

_INTERFACE_DIR = _PROJECT_ROOT / "interface"

app = Flask(__name__)
# Importacao de CSV de previsoes na secao de ML: limite de 64 MB (+ folga do multipart)
app.config["MAX_CONTENT_LENGTH"] = 800 * 1000 * 1000  # dataset (256 MB) + histórico (512 MB) em Analisar dataset
app.register_blueprint(ml_bp)
app.register_blueprint(eventos_bp)
app.register_blueprint(painel_bp)  # painel do analista (/api/painel)

from src.sentinel_ia import PROVIDER  # noqa: E402
HOST = os.environ.get("SENTINEL_HOST", "127.0.0.1")
PORT = int(os.environ.get("SENTINEL_PORT", "5000"))

# Acesso local (src/seguranca_local.py): nada de "Access-Control-Allow-Origin: *". A página e a API saem do
# mesmo servidor, então nenhum cabeçalho CORS é necessário; só as origens listadas em NODEWATCH_ORIGENS
# (vazia por padrão) recebem permissão explícita.
from src import seguranca_local  # noqa: E402

ORIGENS_EXTRAS = seguranca_local.origens_extras(os.environ.get("NODEWATCH_ORIGENS"))
if ORIGENS_EXTRAS:
    CORS(app, origins=ORIGENS_EXTRAS)


@app.before_request
def _somente_acesso_local():
    """Recusa pedidos com Host não local e pedidos de outra origem às rotas /api (ver seguranca_local)."""
    recusa = seguranca_local.verificar(
        request.method, request.path, request.scheme, request.host, request.headers.get("Origin"),
        request.headers.get("Sec-Fetch-Site"), ORIGENS_EXTRAS, HOST)
    if recusa:
        status, erro, acao = recusa
        return jsonify({"erro": erro, "acao": acao}), status
    return None

# Motor do Sentinel AI (provedores, prompt de sistema, modos de linguagem): src/sentinel_ia.py.
# O mesmo motor atende o chat da interface antiga (/api/chat) e o Assistente de dúvidas do painel.
from src import sentinel_ia  # noqa: E402
from src.sentinel_ia import (  # noqa: E402
    LANGUAGE_PROMPT_LEIGA, LANGUAGE_PROMPT_TECNICA, SYSTEM_PROMPT,
    _call_llm, _get_api_key_name, _get_model_name, _has_api_key,
)


@app.route("/")
def index():
    """Painel do analista, a interface atual (dataset → análise → investigação). É o endereço a usar."""
    return send_from_directory(str(_INTERFACE_DIR), "painel.html")


@app.route("/legado")
def legado():
    """Interface ANTIGA, preservada para consulta: grafos de demonstração, seção de ML antiga (análise de rede,
    Analisar dataset, Eventos) e chat Sentinel AI. Não é o painel do analista; endereços antigos com #ml ou
    #grafos chegam aqui pelo redirecionamento de interface/painel.html."""
    return send_from_directory(str(_INTERFACE_DIR), "index.html")


@app.route("/assets/<path:filename>")
def serve_assets(filename):
    """Serve arquivos estaticos da pasta interface/assets."""
    return send_from_directory(str(_INTERFACE_DIR / "assets"), filename)


@app.route("/api/chat", methods=["POST"])
def chat():
    """Recebe mensagens do chat e retorna resposta do Sentinel AI."""
    if not _has_api_key():
        return jsonify({
            "error": "IA nao configurada. Configure sua GEMINI_API_KEY "
                     "no arquivo .env e reinicie o sistema."
        }), 503

    data = request.get_json(silent=True) or {}
    messages = data.get("messages", [])
    context = data.get("context")
    language_mode = data.get("languageMode", "leiga")

    if language_mode not in ("leiga", "tecnica"):
        language_mode = "leiga"

    if not messages:
        return jsonify({"error": "Nenhuma mensagem enviada."}), 400

    # Monta system prompt com modo de linguagem e contexto dinamico
    lang_block = LANGUAGE_PROMPT_LEIGA if language_mode == "leiga" else LANGUAGE_PROMPT_TECNICA
    system = SYSTEM_PROMPT + "\n" + lang_block
    if context:
        system += (
            "\n\n## Estado atual da interface (JSON)\n\n"
            f"```json\n{json.dumps(context, ensure_ascii=False, indent=2)}\n```"
        )

    try:
        text = sentinel_ia._call_llm(system, messages)
        if not (text or "").strip():
            raise sentinel_ia.RespostaInvalida("resposta vazia do provedor")
    except Exception as exc:
        # Erro classificado: detalhe técnico (mascarado) só no log; usuário recebe mensagem clara
        info = sentinel_ia.classificar_erro(exc)
        sentinel_ia.registrar_falha(info)
        print(f"[Sentinel AI] /api/chat falhou ({info['categoria']}): {info['detalhe_tecnico']}", file=sys.stderr)
        status = {"limite": 429, "timeout": 504, "conexao": 502, "servico_indisponivel": 502,
                  "sem_chave": 503, "biblioteca_ausente": 503}.get(info["categoria"], 500)
        return jsonify({"error": f"{info['mensagem']} {info['acao']}".strip(), "categoria": info["categoria"],
                        "tentar_de_novo": info["tentar_de_novo"]}), status
    sentinel_ia.registrar_sucesso()
    return jsonify({"role": "assistant", "content": text})


@app.route("/health", methods=["GET"])
def health():
    """Health check do Sentinel AI."""
    return jsonify({
        "status": "ok",
        "service": "Sentinel AI",
        "provider": PROVIDER,
        "model": _get_model_name(),
        "apiKeyConfigured": _has_api_key(),
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def linhas_de_inicio(host: str = HOST, porta: int = PORT, origens_extras=None) -> list:
    """Endereços mostrados ao iniciar: o painel novo primeiro; a interface antiga identificada como antiga."""
    origens_extras = ORIGENS_EXTRAS if origens_extras is None else origens_extras
    base = f"http://{host}:{porta}"
    linhas = [f"  Servidor: {base}"]
    if not seguranca_local.host_local(host):
        linhas.append(f"  [AVISO] SENTINEL_HOST={host}: o servidor deixa de ser so local. A API continua recusando"
                      " pedidos de outras origens, mas os dados ficam visiveis para quem alcancar esta maquina.")
    if origens_extras:
        linhas.append(f"  Origens extras liberadas (NODEWATCH_ORIGENS): {', '.join(origens_extras)}")
        if "null" in origens_extras:
            linhas.append("  [AVISO] A origem null tambem vale para iframes sandbox de qualquer site, que agora podem"
                          " chamar a API. Use so enquanto precisar e reinicie o servidor sem NODEWATCH_ORIGENS.")
    linhas += [
        "",
        f"  >> Painel do analista (use este): {base}/",
        "",
        "  Interface antiga, so para consulta (nao e o painel do analista):",
        f"     {base}/legado               grafos de demonstracao e chat Sentinel AI",
        f"     {base}/legado#ml            secao de ML antiga (analise de rede, Analisar dataset)",
        f"     {base}/legado#ml/eventos    eventos: replay, API de ingestao, simulacao",
        f"  Health: {base}/health",
    ]
    return linhas



if __name__ == "__main__":
    print("=" * 55)
    print("  Sentinel AI - Assistente de Analise de Fraudes")
    print("=" * 55)
    print(f"\n  Provider: {PROVIDER}")
    print(f"  Modelo:   {_get_model_name()}")
    if not _has_api_key():
        key_name = _get_api_key_name()
        print(
            f"\n[AVISO] {key_name} nao definida! Ela ativa o Sentinel AI no Assistente de duvidas do painel\n"
            "  (com a sua autorizacao na tela) e o chat da interface antiga. Sem ela, o painel do analista\n"
            "  funciona sem chave e o assistente responde no modo local.\n"
            "  Copie .env.example para .env e insira sua chave:\n"
            "  Windows:    Copy-Item .env.example .env\n"
            "  Linux/Mac:  cp .env.example .env\n"
        )
    else:
        print("  API Key:  configurada")
    print()
    # Modelo de ML: instala a partir de modelos/ (ou baixa, conferindo o SHA-256) e valida antes de servir.
    # Se falhar, o servidor sobe assim mesmo (análises gravadas continuam abrindo) e o painel mostra o motivo.
    from src.ml import provisionamento
    try:
        print("\n".join(provisionamento._linhas(provisionamento.garantir_modelo(_PROJECT_ROOT))))
    except provisionamento.ErroModelo as exc:
        print(f"[ERRO] Modelo de ML indisponivel: {exc.causa}\n       O que fazer: {exc.acao}\n"
              "       O painel abre, mas novas analises ficam bloqueadas ate o modelo ser instalado.")
    print()
    print("\n".join(linhas_de_inicio()))
    print("-" * 55)
    try:
        app.run(host=HOST, port=PORT, debug=False, threaded=True)
    finally:
        encerrar_eventos()  # grava o instantaneo do estado de eventos, se houver
