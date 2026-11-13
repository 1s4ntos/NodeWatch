"""Sentinel AI — motor de IA do NodeWatch (provedores, prompts e modos de linguagem).

Nome interno da tecnologia: **Sentinel AI**. Na interface nova ele aparece como **"Assistente de dúvidas"**
(src/api_painel.py, rota /api/painel/assistente); na interface antiga, como o chat "Sentinel AI" (/api/chat em
src/sentinel_ai.py). Os dois usam este mesmo módulo: o mesmo prompt de sistema, os mesmos modos de linguagem
(leiga e técnica) e os mesmos provedores (Gemini por padrão; Anthropic com SENTINEL_PROVIDER=anthropic).

Extraído de src/sentinel_ai.py sem mudar o comportamento do chat antigo.
"""

from __future__ import annotations

import os

PROVIDER = os.environ.get("SENTINEL_PROVIDER", "gemini").lower()

# Provider-specific config
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_VERSION = os.environ.get("GEMINI_API_VERSION", "v1beta")
TEMPO_LIMITE_S = 60
MAX_TOKENS_SAIDA = 4096  # o gemini-2.5-flash gasta parte do limite "pensando"; 1024 cortava respostas
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
        from google.genai import types
        # api_version "v1beta": a v1 (padrão do google-genai 3.x) recusa system_instruction com 400
        # INVALID_ARGUMENT "Developer instruction is not enabled for api version v1". O Sentinel AI depende do
        # prompt de sistema; foi essa a causa do ClientError de 13/11/2026. Timeout explícito em milissegundos.
        _gemini_client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            api_version=GEMINI_API_VERSION, timeout=TEMPO_LIMITE_S * 1000))
    return _gemini_client


class RespostaInvalida(RuntimeError):
    """O provedor respondeu sem texto utilizável (vazio, cortado ou bloqueado)."""


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
            max_output_tokens=MAX_TOKENS_SAIDA,
        ),
    )
    texto = response.text
    if not (texto or "").strip():
        motivo = None
        if getattr(response, "candidates", None):
            motivo = getattr(response.candidates[0], "finish_reason", None)
        raise RespostaInvalida(f"resposta sem texto (finish_reason={motivo})")
    return texto


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


# ---------------------------------------------------------------------------
# Painel do analista: o Sentinel AI por trás do "Assistente de dúvidas"
# ---------------------------------------------------------------------------

PROMPT_PAINEL = """
## MODO PAINEL DO ANALISTA (nova interface) — prevalece sobre as seções anteriores quando houver conflito

Voce esta respondendo dentro do **Assistente de duvidas** do Painel do analista do NodeWatch. Para o usuario, o
seu nome e **"Assistente de duvidas"**; "Sentinel AI" e o nome interno da tecnologia. Se perguntarem quem voce e,
diga que e o Assistente de duvidas do NodeWatch (tecnologia Sentinel AI).

O painel nao usa o grafo de demonstracao, o catalogo de componentes nem o DFS da interface antiga: ignore as
instrucoes sobre `interfaceCatalog`, ciclos DFS e graficos da interface antiga. As **Restricoes Obrigatorias**
continuam valendo integralmente.

### Fonte unica de dados
Use apenas o JSON `contexto_painel` abaixo. Ele foi montado pelo servidor a partir dos resultados gravados da
analise, do modelo salvo e das metricas oficiais. Nunca invente numeros, contas, transacoes, atributos, pesos do
modelo ou explicacoes. Se a informacao nao esta no contexto, diga que nao esta disponivel e sugira onde o
analista pode ver na tela (Visao geral, Contas de maior risco, grafo, Registros, Detalhes da transacao,
Legenda, painel operacional ☰).

### Como o modelo funciona (para explicar corretamente)
- Cabeca `lavagem`: floresta aleatoria (Random Forest) do scikit-learn, supervisionada, treinada no IBM AML
  HI-Small (sintetico) com o rotulo `Is Laundering`, sobre 49 atributos que so olham o passado da transacao.
- Score original (0 a 1) = proporcao media de lavagem nas folhas das arvores; **nao e probabilidade calibrada**.
- Score do painel (0 a 1000) = ordem de prioridade ancorada no limiar: score 701 = limiar do modelo. Alerta =
  score >= 701. Faixas sao sugestoes de uma analise offline; o sistema nao bloqueia nem aprova nada.
- **Nao existe explicacao por transacao gravada.** Para "por que esta transacao foi classificada assim?":
  (1) diga o score, o score original e o limiar; (2) liste os `motivos` verificaveis como FATOS sobre a
  transacao, deixando claro que sao regras fixas e nao a explicacao do modelo; (3) se ajudar, cite as
  `importancias_globais` como informacao sobre o MODELO, nunca como "o que pesou nesta transacao";
  (4) diga explicitamente o que nao e possivel saber (ex.: contribuicao de cada atributo nesta decisao).
- Tipologias e rotulo vem do dataset (simulador), nao do modelo.
- Cite cada transacao pelo campo `id_na_tela` (TX- seguido de pelo menos 6 digitos), exatamente como aparece
  na tabela do painel; nunca escreva o numero sem o prefixo TX-.
- Diferencie metricas historicas do teste oficial (`avaliacao_historica`) dos numeros da analise aberta.

### Formato obrigatorio
Responda em portugues do Brasil, de forma objetiva (ate ~250 palavras, salvo pedido). Organize em secoes com
estes titulos, nesta ordem, omitindo a secao que ficar vazia (mas **Fatos** e **Limitacoes** sempre aparecem
quando a pergunta for sobre resultados, alertas ou classificacoes):

**Fatos** — so o que esta no contexto, com os numeros exatos.
**Inferencias** — conclusoes que decorrem dos fatos (diga de quais).
**Hipoteses** — possibilidades a investigar, marcadas como incertas; nunca como conclusao.
**Limitacoes** — o que o contexto nao permite afirmar.

Termine com um proximo passo de investigacao na tela, quando fizer sentido. Nunca diga que houve fraude ou
lavagem; diga que ha sinais para investigacao.
"""


_SDK = {"gemini": ("google.genai", "google-genai"), "anthropic": ("anthropic", "anthropic")}


def _sdk_instalado() -> bool:
    import importlib.util
    modulo = _SDK.get(PROVIDER, (None, None))[0]
    try:
        return bool(modulo) and importlib.util.find_spec(modulo) is not None
    except (ImportError, ValueError):
        return False


def como_ativar(sit: dict) -> str:
    """O que falta para o Sentinel AI funcionar (texto para a tela), ou '' se nada falta."""
    if not sit["chave_configurada"]:
        return (f"Defina {sit['variavel_da_chave']} no arquivo .env (o Inicializador Rápido pergunta) "
                "e reinicie o servidor.")
    if not sit["biblioteca_instalada"]:
        return (f"Instale a biblioteca {sit['biblioteca']} no ambiente do projeto "
                "(python -m pip install -r requirements.txt) e reinicie o servidor.")
    return ""


def situacao() -> dict:
    """Se o Sentinel AI pode ser usado agora (sem expor a chave): precisa da chave e da biblioteca do provedor."""
    chave, sdk = _has_api_key(), _sdk_instalado()
    return {"disponivel": chave and sdk, "provedor": PROVIDER, "modelo": _get_model_name(),
            "variavel_da_chave": _get_api_key_name(), "chave_configurada": chave, "biblioteca_instalada": sdk,
            "biblioteca": _SDK.get(PROVIDER, (None, PROVIDER))[1]}


def responder_painel(pergunta: str, historico: list, contexto: dict, modo_linguagem: str = "leiga") -> str:
    """Resposta do Sentinel AI no Assistente de dúvidas: mesmo prompt e provedores do chat original,
    mais o bloco do painel e o contexto verificado da análise."""
    import json

    lang = LANGUAGE_PROMPT_TECNICA if modo_linguagem == "tecnica" else LANGUAGE_PROMPT_LEIGA
    system = (SYSTEM_PROMPT + "\n" + lang + "\n" + PROMPT_PAINEL +
              "\n\n## contexto_painel (JSON)\n\n```json\n" +
              json.dumps(contexto, ensure_ascii=False, indent=1, default=str) + "\n```")
    mensagens = [{"role": m["role"], "content": str(m["content"])[:4000]} for m in (historico or [])
                 if m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip()][-10:]
    mensagens.append({"role": "user", "content": pergunta})
    return _call_llm(system, mensagens)


# ---------------------------------------------------------------------------
# Diagnóstico: classificação dos erros e estado REAL da conexão (não basta haver chave)
# ---------------------------------------------------------------------------
import re as _re
import threading as _threading
from datetime import datetime as _dt, timezone as _tz

_trava_estado = _threading.Lock()
_conexao = {"estado": "nao_verificado", "quando": None, "categoria": None, "mensagem": None}

# categoria → (mensagem para o usuário, o que fazer, vale tentar de novo?)
CATEGORIAS = {
    "sem_chave": ("a chave do Gemini não está configurada", "Defina GEMINI_API_KEY no .env e reinicie o servidor.", False),
    "biblioteca_ausente": ("a biblioteca do provedor não está instalada",
                           "Rode python -m pip install -r requirements.txt e reinicie o servidor.", False),
    "chave_invalida": ("a chave do Gemini foi recusada (inválida ou revogada)",
                       "Confira a chave em aistudio.google.com/apikey, corrija o .env e reinicie o servidor.", False),
    "autenticacao": ("o Gemini não aceitou a autenticação", "Confira a chave no .env e reinicie o servidor.", False),
    "permissao": ("a chave não tem permissão para usar este modelo ou esta API",
                  "Confira se a Generative Language API está habilitada para a chave.", False),
    "modelo_indisponivel": ("o modelo configurado não existe ou não está disponível para a chave",
                            "Confira GEMINI_MODEL no .env (padrão: gemini-2.5-flash).", False),
    "requisicao_invalida": ("o Gemini recusou o formato do pedido", "Veja o detalhe técnico nos logs do servidor.", False),
    "limite": ("o limite de uso da API foi atingido", "Espere alguns minutos (ou até a cota renovar) e tente de novo.", True),
    "timeout": ("o Gemini demorou demais para responder", "Tente de novo em instantes.", True),
    "conexao": ("não foi possível conectar ao Gemini", "Confira a internet (proxy/firewall) e tente de novo.", True),
    "servico_indisponivel": ("o serviço do Gemini está indisponível no momento", "Tente de novo em instantes.", True),
    "resposta_invalida": ("o Gemini respondeu sem texto utilizável", "Tente de novo ou reformule a pergunta.", True),
    "erro_interno": ("ocorreu um erro interno ao falar com o Gemini", "Veja o detalhe técnico nos logs do servidor.", True),
}

_PADRAO_CHAVE = _re.compile(r"AIza[0-9A-Za-z_\-]{20,}|sk-ant-[0-9A-Za-z_\-]{10,}")


def mascarar(texto: str) -> str:
    """Remove chaves de API de qualquer texto que vá para logs ou para a tela."""
    t = str(texto)
    for nome in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        v = (os.environ.get(nome) or "").strip()
        if len(v) >= 8:
            t = t.replace(v, "***")
    return _PADRAO_CHAVE.sub("***", t)


def classificar_erro(exc: BaseException) -> dict:
    """Categoria, mensagem ao usuário e detalhe técnico (mascarado) de uma falha do provedor."""
    codigo = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    status = str(getattr(exc, "status", "") or "")
    msg = str(getattr(exc, "message", None) or exc)
    nome = type(exc).__name__
    baixo = (msg + " " + status).lower()
    if isinstance(exc, RespostaInvalida):
        cat = "resposta_invalida"
    elif isinstance(exc, ImportError):
        cat = "biblioteca_ausente"
    elif isinstance(exc, ValueError) and "api_key" in baixo.replace(" ", "_"):
        cat = "sem_chave"
    elif isinstance(codigo, int):
        if codigo == 400 and ("api key not valid" in baixo or "api_key_invalid" in baixo):
            cat = "chave_invalida"
        elif codigo == 401:
            cat = "autenticacao"
        elif codigo == 403:
            cat = "chave_invalida" if "api key" in baixo else "permissao"
        elif codigo == 404:
            cat = "modelo_indisponivel"
        elif codigo == 429:
            cat = "limite"
        elif codigo in (408, 504):
            cat = "timeout"
        elif codigo >= 500:
            cat = "servico_indisponivel"
        else:
            cat = "requisicao_invalida"
    elif "timeout" in nome.lower() or isinstance(exc, TimeoutError):
        cat = "timeout"
    elif "connect" in nome.lower() or "network" in nome.lower() or isinstance(exc, (ConnectionError, OSError)):
        cat = "conexao"
    else:
        cat = "erro_interno"
    texto, acao, repetir = CATEGORIAS[cat]
    detalhe = mascarar(f"{nome}" + (f" {codigo}" if codigo else "") + (f" {status}" if status else "") + f": {msg}")[:500]
    return {"categoria": cat, "mensagem": texto, "acao": acao, "tentar_de_novo": repetir, "detalhe_tecnico": detalhe}


def _marcar(estado: str, categoria=None, mensagem=None) -> None:
    with _trava_estado:
        _conexao.update(estado=estado, categoria=categoria, mensagem=mensagem,
                        quando=_dt.now(_tz.utc).isoformat(timespec="seconds"))


def registrar_sucesso() -> None:
    _marcar("conectado")


def registrar_falha(info: dict) -> None:
    _marcar("falhou", info["categoria"], info["mensagem"])


def estado_conexao() -> dict:
    """Último resultado REAL de uma chamada ao provedor neste processo (ter a chave não prova que funciona)."""
    sit = situacao()
    with _trava_estado:
        c = dict(_conexao)
    if not sit["disponivel"]:
        c.update(estado="nao_configurado", categoria="sem_chave" if not sit["chave_configurada"] else "biblioteca_ausente")
    return c


def verificar_conexao() -> dict:
    """Chamada mínima e real (mesmo cliente, mesmo prompt de sistema curto) para testar a conexão agora."""
    try:
        _call_llm("Responda apenas com a palavra OK.", [{"role": "user", "content": "Teste de conexão do NodeWatch."}])
        registrar_sucesso()
    except Exception as exc:  # classificado, sem expor a chave
        info = classificar_erro(exc)
        registrar_falha(info)
        return {**estado_conexao(), **{k: info[k] for k in ("acao", "tentar_de_novo", "detalhe_tecnico")}}
    return estado_conexao()
