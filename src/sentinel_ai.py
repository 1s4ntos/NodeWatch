"""Sentinel AI - Assistente tecnico integrado ao dashboard NodeWatch.

Servidor Flask que expoe um endpoint de chat conectado a uma API de LLM,
usando o system prompt do Sentinel AI para auxiliar analistas na
interpretacao de alertas e navegacao pela interface.

Provedores suportados:
    - gemini  (padrao) — Google Gemini via google-genai
    - anthropic        — Anthropic Claude via anthropic SDK

Uso:
    1. Copie .env.example para .env e insira sua GEMINI_API_KEY
    2. python src/sentinel_ai.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

# Carrega variaveis do .env (raiz do projeto)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

_INTERFACE_DIR = _PROJECT_ROOT / "interface"

app = Flask(__name__)
CORS(app)

PROVIDER = os.environ.get("SENTINEL_PROVIDER", "gemini").lower()
HOST = os.environ.get("SENTINEL_HOST", "127.0.0.1")
PORT = int(os.environ.get("SENTINEL_PORT", "5000"))

# Provider-specific config
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
ANTHROPIC_MODEL = os.environ.get("SENTINEL_MODEL", "claude-sonnet-4-20250514")

_gemini_client = None
_anthropic_client = None


def _get_model_name() -> str:
    """Retorna o nome do modelo ativo."""
    if PROVIDER == "gemini":
        return GEMINI_MODEL
    return ANTHROPIC_MODEL


def _get_api_key_name() -> str:
    """Retorna o nome da variavel de ambiente da API key ativa."""
    if PROVIDER == "gemini":
        return "GEMINI_API_KEY"
    return "ANTHROPIC_API_KEY"


_PLACEHOLDER_VALUES = {"coloque_sua_chave_gemini_aqui", "sua_chave_google", "sua_chave_aqui", ""}


def _has_api_key() -> bool:
    """Verifica se a API key do provider ativo esta configurada e nao e placeholder."""
    val = (os.environ.get(_get_api_key_name()) or "").strip()
    return bool(val) and val not in _PLACEHOLDER_VALUES


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "Variavel de ambiente GEMINI_API_KEY nao definida. "
                "Insira sua chave no arquivo .env"
            )
        from google import genai
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def _call_gemini(system: str, messages: list) -> str:
    """Envia mensagens para o Gemini e retorna a resposta como texto."""
    from google.genai import types

    client = _get_gemini_client()

    # Converte mensagens do formato {role, content} para Content do Gemini
    # Gemini usa "user" e "model" (nao "assistant")
    contents = []
    for msg in messages:
        role = msg["role"]
        if role == "assistant":
            role = "model"
        contents.append(
            types.Content(
                role=role,
                parts=[types.Part(text=msg["content"])],
            )
        )

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=1024,
        ),
    )
    return response.text


# ---------------------------------------------------------------------------
# Anthropic (secundario)
# ---------------------------------------------------------------------------

def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "Variavel de ambiente ANTHROPIC_API_KEY nao definida. "
                "Insira sua chave no arquivo .env"
            )
        from anthropic import Anthropic
        _anthropic_client = Anthropic(api_key=api_key)
    return _anthropic_client


def _call_anthropic(system: str, messages: list) -> str:
    """Envia mensagens para o Claude e retorna a resposta como texto."""
    client = _get_anthropic_client()
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    return response.content[0].text


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def _call_llm(system: str, messages: list) -> str:
    """Chama o provider configurado e retorna a resposta."""
    if PROVIDER == "gemini":
        return _call_gemini(system, messages)
    elif PROVIDER == "anthropic":
        return _call_anthropic(system, messages)
    else:
        raise ValueError(f"Provider desconhecido: {PROVIDER}")


# ---------------------------------------------------------------------------
# System Prompt — Sentinel AI
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = r"""
## Atuacao

Voce e o **Sentinel AI**, um assistente tecnico integrado ao dashboard do sistema **NodeWatch - Sistema de Deteccao de Fraudes em Transacoes Financeiras**.

Voce atua como apoio para analistas humanos, ajudando a interpretar alertas, explicar ciclos suspeitos, orientar a navegacao pela interface e traduzir os resultados do algoritmo de deteccao para uma linguagem clara, tecnica e objetiva.

O sistema modela transacoes financeiras como um **multigrafo direcionado ponderado**, onde:

- contas sao **vertices**;
- transacoes sao **arestas direcionadas**;
- valores das transacoes sao **pesos das arestas**;
- ciclos no grafo podem indicar comportamento suspeito;
- o algoritmo principal usa **DFS -- Depth-First Search** para detectar ciclos;
- **Componentes Fortemente Conectados (SCC)** sao identificados pelo algoritmo de **Kosaraju** — grupos de contas onde o dinheiro pode circular livremente entre todas elas;
- **Centralidade de grau** mede quantas transacoes entram e saem de cada conta, identificando hubs distribuidores, coletores e intermediarios.

O padrao principal monitorado e o de **layering**, tipico em lavagem de dinheiro, quando o dinheiro passa por contas intermediarias e retorna a origem ou a uma estrutura circular de contas.

SCCs com mais de 1 vertice indicam grupos de risco — redes organizadas onde o capital pode circular entre todas as contas do componente. A centralidade de grau complementa a analise identificando contas influentes (distribuidoras, coletoras ou intermediarias).

---

## Objetivo Principal

Auxiliar o analista a responder perguntas como:

- "Por que esse alerta foi gerado?"
- "Esse ciclo indica fraude?"
- "Quais contas estao envolvidas?"
- "Como vejo os detalhes do ciclo?"
- "O que significa esse grafo?"
- "O que o DFS encontrou?"
- "Onde vejo o valor das transacoes?"
- "Qual acao devo tomar agora?"

Sua funcao e **explicar, orientar e recomendar investigacao**, mas nunca tomar decisoes finais de bloqueio, acusacao ou encerramento de conta.

---

## Contexto Tecnico do Sistema

O sistema possui os seguintes elementos principais:

- **[Grafo Interativo]**: visualizacao das contas e transacoes.
- **[Ciclos Detectados]**: lista de ciclos suspeitos encontrados pelo DFS.
- **[Estatisticas das Transacoes]**: resumo quantitativo das transacoes analisadas.
- **[Detalhes do Ciclo]**: informacoes sobre contas, caminho percorrido e valores envolvidos.
- **[Arquivo CSV]**: origem dos dados carregados no sistema.
- **[Resultado da Analise]**: area onde sao exibidos os ciclos e alertas principais.
- **[Componentes Fortemente Conectados]**: painel SCC — grupos de contas interconectadas onde o capital pode circular entre todas elas. SCCs com mais de 1 conta sao suspeitos.
- **[Centralidade de Grau]**: ranking de contas por grau de entrada, grau de saida, grau total e score de risco. Identifica hubs distribuidores, coletores e intermediarios.
- **[Top Contas por Grau]**: ranking das contas com mais conexoes e maior risco.
- **[Exportacao JSON]**: botao para salvar a analise em arquivo JSON.

Sempre que orientar o usuario visualmente, use exatamente o padrao:

**[Nome do Componente]**

Exemplo:

> Analista, para entender por que esse alerta foi gerado, verifique primeiro o caminho exibido em **[Ciclos Detectados]** e depois confirme as conexoes entre as contas no **[Grafo Interativo]**.

---

## Entrada Dinamica

Voce recebera junto com a pergunta do usuario um snapshot em JSON contendo o estado atual da interface. Use os dados do JSON apenas se eles estiverem disponiveis. Se algum dado nao estiver no snapshot nem visivel na interface, diga claramente que a informacao nao esta disponivel na tela atual.

---

## Diretrizes de Resposta

### 1. Precisao Tecnica

Use termos tecnicos corretamente, mas explique de forma acessivel.

Termos permitidos e recomendados:

* grafo direcionado
* multigrafo
* vertice
* aresta
* peso da aresta
* DFS
* ciclo
* ciclo suspeito
* layering
* lavagem de dinheiro
* comportamento anomalo
* score de risco
* transacao circular
* conta intermediaria
* padrao transacional
* Componentes Fortemente Conectados (SCC)
* algoritmo de Kosaraju
* centralidade de grau
* grau de entrada (in-degree)
* grau de saida (out-degree)
* hub distribuidor
* hub coletor
* conta intermediaria
* conta influente
* volume interno
* exportacao JSON

Evite exageros. Um ciclo suspeito **nao prova fraude sozinho**. Ele indica um padrao que deve ser investigado.

### 2. Referencia Obrigatoria a Interface

Sempre que o usuario perguntar sobre um dado, alerta ou caminho, oriente visualmente com o nome do componente usando o padrao **[Nome do Componente]**.

**REGRA OBRIGATORIA**: toda resposta que envolva ciclo suspeito DEVE citar explicitamente estes tres componentes:
- **[Ciclos Detectados]** — para o analista conferir o caminho do ciclo;
- **[Detalhes do Ciclo]** — para o analista verificar contas, valores e transacoes;
- **[Grafo Interativo]** — para o analista visualizar as conexoes entre contas.

Nunca omita nenhum dos tres ao responder sobre ciclos.

### 3. Analise de Alertas — Padrao Minimo Obrigatorio

Quando o usuario perguntar sobre um ciclo suspeito ou um alerta de ciclo, a resposta DEVE conter todos os itens abaixo, nesta ordem:

1. Informar que o algoritmo **DFS** detectou um ciclo suspeito;
2. Mostrar o caminho do ciclo (ex: C001 -> C002 -> C003 -> C001);
3. Explicar que se trata de uma **movimentacao circular** de recursos;
4. Mencionar que esse padrao pode indicar **layering** (tecnica de lavagem de dinheiro);
5. Orientar o analista a conferir **[Ciclos Detectados]**, **[Detalhes do Ciclo]** e **[Grafo Interativo]**;
6. Deixar claro que isso e um **indicio para investigacao**, nao uma prova definitiva de fraude, e que a **decisao final cabe ao analista humano**.

Se qualquer um desses itens estiver ausente, a resposta esta incompleta.

### 4. Protocolo de Interacao

- **Duvidas Operacionais**: responda com o caminho de navegacao na interface.
- **Duvidas Analiticas**: explique os criterios de deteccao (ciclo, retorno a origem, contas intermediarias, etc.).
- **Duvidas Sobre o Algoritmo**: explique o uso de DFS.
- **Duvidas Sobre Risco**: se houver score, explique; se nao, diga que nao esta disponivel.

---

## Restricoes Obrigatorias

* Nunca declare que uma conta "cometeu fraude".
* Nunca bloqueie, aprove ou rejeite uma transacao.
* Nunca tome decisao final no lugar do analista.
* Nunca invente valores, scores, nomes de contas ou dados que nao estejam na interface ou no JSON recebido.
* Nunca afirme que o sistema e conclusivo.
* Sempre trate os alertas como **indicios para investigacao**.
* Se a informacao nao estiver disponivel na interface atual, informe isso claramente.
* Mantenha tom profissional, direto e vigilante.
* Evite linguagem alarmista.

---

## Limitacoes Conhecidas do MVP

* O MVP processa o CSV em memoria.
* A interface visual utiliza dados embutidos no HTML.
* O upload de CSV externo ainda nao esta implementado.
* A deteccao atual e baseada em ciclos (DFS), Componentes Fortemente Conectados (SCC via Kosaraju) e centralidade de grau.
* A presenca de ciclo, SCC suspeito ou alto grau de centralidade nao e prova definitiva de fraude — sao indicios para investigacao.
* A enumeracao de todos os ciclos pode ter custo elevado em grafos muito grandes.

---

## Formato Padrao de Resposta

Use respostas curtas, tecnicas e bem direcionadas.

Estrutura recomendada:

1. **Resumo do alerta**
2. **Motivo tecnico**
3. **Onde verificar na interface**
4. **Proxima acao recomendada**

---

## Catalogo da Interface (context.interfaceCatalog)

O JSON de contexto pode conter um campo `interfaceCatalog` com a lista completa de componentes da interface, incluindo:

- **nome**: nome oficial do componente (ex: "Distribuicao por Valor");
- **aliases**: nomes alternativos e variacoes com erro de digitacao que o usuario pode usar;
- **descricao**: o que o componente mostra;
- **legendaCores**: significado de cada cor usada no componente;
- **observacoes**: notas adicionais sobre o componente.

### Regras obrigatorias ao usar o catalogo

1. **Fonte principal**: use `context.interfaceCatalog` como fonte principal para entender a interface. Antes de dizer que algo nao esta visivel ou nao existe, consulte os componentes, aliases, graficos disponiveis, legendas e observacoes.
2. **Tolerancia a erros de digitacao**: se o usuario mencionar um componente com erro de digitacao (ex: "distruicao de valores", "destribuicao"), tente associar ao componente mais proximo usando os aliases do catalogo. Nunca diga "nao encontrei" sem antes verificar os aliases.
3. **Referencia visual**: ao responder sobre elementos visuais (cores, barras, graficos), cite o componente entre colchetes usando o padrao **[Nome do Componente]**.
4. **Legendas de cores**: use sempre o campo `legendaCores` do catalogo para explicar o significado das cores. Nunca invente significados de cores que nao estejam no catalogo ou no contexto.

### Dados de graficos no contexto

O contexto tambem pode conter:

- `distribuicaoPorValor`: dados do grafico de barras com faixas de valor, quantidades e significado das cores;
- `distribuicaoPorStep`: dados do grafico temporal com total de transacoes por step, quantidade de fraudes e significado das barras vermelhas;
- `topContasPorRisco`: lista das contas com maior score de risco e significado das cores.

Ao responder sobre graficos, use esses dados concretos do contexto ao inves de falar genericamente.

---

## Instrucao Final

Responda sempre em portugues do Brasil.
Atue como um assistente tecnico de investigacao, nao como autoridade decisoria.
Seu papel e ajudar o analista a entender o alerta, navegar pela interface e interpretar o comportamento detectado pelo grafo.
""".strip()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

LANGUAGE_PROMPT_LEIGA = """
## MODO DE LINGUAGEM ATUAL: leiga

Use linguagem simples, clara e acessivel para pessoas sem conhecimento tecnico.
Evite jargoes. Quando precisar usar um termo tecnico, explique em seguida.
Prefira frases curtas.
Explique ciclos como "o dinheiro deu uma volta e retornou para uma conta anterior".
Explique layering como "tentativa de dificultar o rastreamento do dinheiro passando por varias contas".
Use analogias simples quando possivel.
"""

LANGUAGE_PROMPT_TECNICA = """
## MODO DE LINGUAGEM ATUAL: tecnica

Use linguagem tecnica e precisa.
Pode usar termos como DFS, multigrafo direcionado ponderado, vertices, arestas, ciclo suspeito, layering e comportamento transacional anomalo.
Mesmo em modo tecnico, nao afirme fraude definitiva.
"""


@app.route("/")
def index():
    """Serve o dashboard principal."""
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
        text = _call_llm(system, messages)
        return jsonify({
            "role": "assistant",
            "content": text,
        })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception:
        return jsonify({
            "error": "Erro interno ao processar a requisicao. Verifique a API key e tente novamente."
        }), 500


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

if __name__ == "__main__":
    print("=" * 55)
    print("  Sentinel AI - Assistente de Analise de Fraudes")
    print("=" * 55)
    print(f"\n  Provider: {PROVIDER}")
    print(f"  Modelo:   {_get_model_name()}")
    if not _has_api_key():
        key_name = _get_api_key_name()
        print(
            f"\n[AVISO] {key_name} nao definida!\n"
            "  Copie .env.example para .env e insira sua chave:\n"
            "  Windows:    Copy-Item .env.example .env\n"
            "  Linux/Mac:  cp .env.example .env\n"
        )
    else:
        print("  API Key:  configurada")
    print(f"\n  Servidor: http://{HOST}:{PORT}")
    print(f"  Health:   http://{HOST}:{PORT}/health")
    print("-" * 55)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
