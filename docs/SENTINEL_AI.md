# Sentinel AI

Documentacao tecnica do assistente de analise de fraudes integrado ao dashboard.

## Objetivo

O Sentinel AI auxilia o analista a:

- Interpretar ciclos suspeitos detectados pelo algoritmo DFS;
- Entender metricas, graficos e componentes visuais do dashboard;
- Navegar pela interface com orientacao contextual;
- Diferenciar indicios de investigacao de provas definitivas de fraude.
- Interpretar Componentes Fortemente Conectados (SCC) e seu significado para a investigacao;
- Explicar centralidade de grau — contas distribuidoras, coletoras e intermediarias;
- Orientar sobre a exportacao de analises em JSON.

O Sentinel AI **nao toma decisoes e nao prova fraude**. A decisao final cabe **sempre** ao analista humano. A IA indica padroes suspeitos para investigacao — nunca afirma categoricamente que uma transacao e fraudulenta.

## Arquitetura

```
interface/index.html        src/sentinel_ai.py         Google Gemini API
 (React + chat flutuante)    (Flask backend)            (LLM)
         |                          |                        |
         |--- POST /api/chat ------>|                        |
         |    {messages, context,   |--- generate_content -->|
         |     languageMode}        |    {system prompt +    |
         |                          |     context JSON}      |
         |                          |<-- resposta texto -----|
         |<-- {role, content} ------|                        |
```

O motor (provedores, system prompt, modos de linguagem) fica em `src/sentinel_ia.py` e atende dois pontos de entrada:
o chat da interface antiga (`POST /api/chat`, diagrama acima) e o **Assistente de dúvidas** do painel
(`POST /api/painel/assistente`), que envia o contexto verificado da análise só depois da autorização do usuário
(ver docs/ui/PAINEL_ANALISTA.md). Sem `GEMINI_API_KEY`, o chat responde 503 e o Assistente de dúvidas usa o modo local.

1. O frontend envia a pergunta do usuario + snapshot JSON do estado do dashboard;
2. O backend (`src/sentinel_ai.py`) monta o system prompt com modo de linguagem e contexto;
3. O backend chama a API do Gemini (ou Anthropic como alternativa);
4. A resposta volta para o chat flutuante no dashboard.

## O que o Sentinel AI recebe

A cada mensagem, o backend monta um contexto dinamico com:

- **System prompt tecnico** — define papel, regras e restricoes;
- **Snapshot do dashboard** — estado atual em JSON (ciclos detectados, estatisticas, transacoes);
- **Catalogo da interface** — lista de todos os componentes visuais com nomes, aliases e legendas de cores;
- **Dados dos graficos** — distribuicao por valor, distribuicao por step temporal, top contas por risco;
- **Dados de SCC** — componentes fortemente conectados detectados pelo Kosaraju, com volume e flags;
- **Centralidade de grau** — ranking de contas por grau de entrada/saida e score de risco;
- **Status de exportacao JSON** — indica que o dashboard permite exportar a analise.
- **Aliases para erros de digitacao** — reconhece variantes como "distruicao", "distruicao de valores", etc.

O Sentinel AI usa essas informacoes para orientar o analista sobre componentes especificos da interface.

## Componentes reconhecidos

O Sentinel AI conhece todos os componentes da interface via catalogo (`SENTINEL_UI_CATALOG`):

| Componente | Tipo | O que o Sentinel AI orienta |
|---|---|---|
| **[Grafo Interativo]** | visualizacao | Contas como nos, transacoes como setas. Vermelho = em ciclo, cinza = normal. |
| **[Ciclos Detectados]** | painel | Selecao e visualizacao dos ciclos encontrados pela DFS. |
| **[Detalhes do Ciclo]** | painel | Contas envolvidas, valores transferidos, metricas do ciclo selecionado. |
| **[Distribuicao por Valor]** | grafico | Barras por faixa de valor. Azul = normal (< R$10k), amarelo = alto (>= R$10k). |
| **[Distribuicao por Step Temporal]** | grafico | Barras por step. Azul = total, vermelho = transacoes com isFraud=1. |
| **[Top Contas por Risco]** | ranking | 5 contas com maior score. Vermelho >= 80, amarelo 40-79, verde < 40. |
| **[Barra de Alerta]** | banner | Banner vermelho com resumo de ciclos detectados. |
| **[Cards de Estatisticas]** | KPIs | Vertices, Arestas, Volume total, Em risco. |
| **[Tabela de Transacoes]** | tabela | Todas as transacoes com badges EM CICLO (amarelo) e LABELED (vermelho). |
| **[Log de Execucao]** | log | Historico de processamento do sistema. |
| **[Componentes Fortemente Conectados]** | painel | Grupos de contas onde o dinheiro pode circular livremente. SCCs com mais de 1 conta sao suspeitos. |
| **[Centralidade de Grau]** | ranking | Ranking de contas por grau de entrada/saida, grau total e score de risco. |
| **[Top Contas por Grau]** | ranking | Top 10 contas com maior grau e risco. |
| **[Exportacao JSON]** | botao | Exporta a analise completa em arquivo JSON. |

Cada componente possui aliases para tolerar erros de digitacao do usuario.

## Legendas de cores

- **Distribuicao por Valor**: azul = valor normal (< R$10k), amarelo = valor alto (>= R$10k). Nao possui barras vermelhas.
- **Distribuicao por Step Temporal**: azul = total de transacoes, vermelho = transacoes com isFraud=1.
- **Top Contas por Risco**: vermelho = score >= 80, amarelo = 40-79, verde = < 40.
- **Grafo Interativo**: vermelho = conta/aresta em ciclo suspeito, cinza = normal.
- **Tabela de Transacoes**: badge amarelo = EM CICLO, badge vermelho = LABELED (isFraud=1).

## Modos de linguagem

| Modo | Descricao |
|---|---|
| **Leiga** | Linguagem simples, sem jargoes, com analogias. Padrao inicial. |
| **Tecnica** | Termos como DFS, multigrafo, layering, vertices, arestas. |

A preferencia e salva em `localStorage` e persiste entre sessoes.

## Execucao

O projeto roda localmente com Python:

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\Activate.ps1  # Windows
pip install -r requirements.txt
cp .env.example .env         # preencher GEMINI_API_KEY
python src/sentinel_ai.py
```

O chat Sentinel AI original fica na interface antiga: `http://127.0.0.1:5000/legado`. No painel do analista (`http://127.0.0.1:5000/`), o mesmo Sentinel AI está por trás do **Assistente de dúvidas**: quando o usuário autoriza, ele recebe o contexto verificado da análise aberta e interpreta os resultados da Machine Learning. Ver [docs/ui/PAINEL_ANALISTA.md](ui/PAINEL_ANALISTA.md#assistente-de-dúvidas-tecnologia-sentinel-ai).

O motor (provedores, prompt de sistema, modos de linguagem) fica em `src/sentinel_ia.py` e é compartilhado pelas duas interfaces; o bloco `PROMPT_PAINEL` acrescenta as regras do painel (fatos, inferências, hipóteses e limitações; sem explicação inventada para decisões do modelo).

Scripts de inicio rapido:
- Windows: `.\start_presentation.ps1`
- Linux/macOS: `./start_presentation.sh`

A API key fica no `.env` (nunca commitado). O Flask serve o painel do analista em `/` e a interface antiga, com o chat, em `/legado`. O frontend detecta automaticamente a URL do backend.

## Conexao com o Gemini: chave, verificacao e erros

**Como a chave chega ao Sentinel AI.** O inicializador (`Inicializador Rápido/Iniciar_NodeWatch.bat` → `Iniciar_NodeWatch.ps1`) pergunta o token uma vez, com a digitação oculta, e grava só a linha `GEMINI_API_KEY=` do `.env` da pasta principal. O servidor (`src/sentinel_ai.py`) carrega esse `.env` ao iniciar (`load_dotenv`), e o motor (`src/sentinel_ia.py`) lê a variável do ambiente. Uma variável `GEMINI_API_KEY` já definida no Windows tem precedência e o inicializador não pergunta. Trocou a chave? Reinicie o servidor.

**Cliente.** Biblioteca `google-genai` (3.x), modelo `GEMINI_MODEL` (padrão `gemini-2.5-flash`), **API `v1beta`** (`GEMINI_API_VERSION`), tempo limite de 60 s e até 4096 tokens de saída.

> **Causa do erro "O Sentinel AI não respondeu agora (ClientError)" (13/11/2026).** A `google-genai` 3.x usa por padrão a API `v1`, que recusa o prompt de sistema (`system_instruction`) com `400 INVALID_ARGUMENT: Developer instruction is not enabled for api version v1`. Toda pergunta com prompt de sistema falhava, embora a chave fosse válida (uma chamada sem prompt de sistema funcionava). Correção: o cliente é criado com `HttpOptions(api_version="v1beta")`. Além disso, o limite de saída subiu de 1024 para 4096 tokens: o `gemini-2.5-flash` gasta parte do limite "pensando" e cortava respostas.

**Estado da conexão** (o que a tela mostra): ter a chave não prova que ela funciona, então o estado vem do resultado da última chamada real neste servidor.

| Estado | Significado |
|---|---|
| `nao_configurado` | sem chave ou sem a biblioteca do provedor: o assistente responde no **modo local** |
| `nao_verificado` | há chave, mas nenhuma chamada foi feita desde que o servidor subiu |
| `conectado` | a última chamada deu certo |
| `falhou` | a última chamada falhou; `categoria` diz o motivo |

Para testar agora: botão **Testar conexão** no Assistente de dúvidas, ou `POST /api/painel/assistente/verificar` (uma chamada mínima, sem dados da análise).

**Erros classificados** (`classificar_erro` em `src/sentinel_ia.py`). O usuário recebe a mensagem e a ação; o detalhe técnico vai só para o log do servidor (saída de erro e `artefatos_ml/painel/logs/sistema.jsonl`, evento `assistente_sentinel_falhou`), **com a chave mascarada** (`***`).

| Categoria | Origem típica | Tentar de novo? |
|---|---|---|
| `sem_chave` | `GEMINI_API_KEY` ausente ou vazia | não |
| `biblioteca_ausente` | `google-genai` não instalado | não |
| `chave_invalida` | 400 "API key not valid" / 403 com chave recusada | não |
| `autenticacao` | 401 | não |
| `permissao` | 403 (projeto sem acesso à API ou ao modelo) | não |
| `modelo_indisponivel` | 404 (modelo inexistente para a chave) | não |
| `requisicao_invalida` | outros 400 (formato da requisição) | não |
| `limite` | 429 (cota ou taxa) | sim |
| `timeout` | 408/504 ou tempo esgotado | sim |
| `conexao` | sem rede, DNS, proxy, conexão recusada | sim |
| `servico_indisponivel` | 5xx (ex.: 503 "high demand") | sim |
| `resposta_invalida` | resposta sem texto (bloqueio, corte) | sim |
| `erro_interno` | qualquer outro erro | sim |

**Reserva local.** Se o Sentinel AI falhar, a pergunta **não** é tratada como "fora da base": se o modo local tem resposta (glossário, ajuda, números gravados), ela vem com o aviso do que falhou; se não tem, a resposta diz que o Sentinel AI não respondeu. A pergunta fica guardada (`pergunta_preservada`) e a mensagem ganha o botão **Tentar de novo** quando a categoria permite. O chat da interface antiga (`/api/chat`) usa a mesma classificação e devolve `{"error", "categoria", "tentar_de_novo"}` com status 429, 502, 503, 504 ou 500.

**Como testar.**

```powershell
.venv\Scripts\python -m pytest testes/painel/test_sentinel_erros.py testes/painel/test_assistente_sentinel.py -q
```

Os testes usam um provedor falso (nada sai do computador) e cobrem: leitura da chave, API `v1beta`, sem chave, cada código de erro, sucesso, resposta sem texto, tempo esgotado, falha de conexão, limite, reserva local, pergunta preservada com nova tentativa, os endpoints e a ausência da chave em respostas, logs e saída de erro. Teste real: abra o painel, clique em **Testar conexão** e faça uma pergunta com o contexto autorizado.

**Problemas comuns.**

- *"a chave foi recusada"*: chave copiada errada ou revogada; gere outra em aistudio.google.com/apikey, troque a linha no `.env` e reinicie.
- *"limite de uso atingido"*: cota gratuita esgotada por minuto ou por dia; espere e use **Tentar de novo**.
- *"serviço indisponível"* (503): demanda alta no Gemini, passageira; tente de novo.
- *"sem conexão"*: rede, proxy ou firewall bloqueando `generativelanguage.googleapis.com`.
- Mudou a chave e nada mudou: o servidor só lê o `.env` ao iniciar; reinicie pelo inicializador.

## Seguranca da chave API

- Nunca commitar o `.env`;
- Nunca colocar chave real no codigo-fonte;
- Nunca colocar chave no frontend;
- Usar `.env` local para configuracao;
- `.env` esta listado no `.gitignore`;
- Erros do backend retornam mensagem classificada, sem dados sensiveis; o detalhe tecnico vai para o log com a chave mascarada (`mascarar` em `src/sentinel_ia.py`);
- O system prompt proibe o Sentinel AI de inventar dados nao presentes no contexto.

## Validacao

O projeto foi validado com:

- Backend Flask iniciando com `python src/sentinel_ai.py`;
- `/health` retornando `{"status": "ok", "apiKeyConfigured": true}`;
- Dashboard (hoje a interface antiga) servido via Flask, atualmente em `/legado`;
- Sentinel AI respondendo perguntas no chat;
- `.env` fora do controle de versao.

## Limitacoes

- **MVP academico** — nao e um sistema de producao;
- A IA auxilia a analise, mas **nao prova fraude** — a decisao final cabe ao analista humano;
- SCC e centralidade complementam ciclos, mas nao provam fraude isoladamente;
- O Gemini depende de chave valida e cota disponivel (limite gratuito: 20 req/dia para gemini-2.5-flash);
- Os dados sao locais/embutidos no HTML conforme o escopo atual — upload de CSV externo nao implementado;
- SQL/banco de dados nao foi implementado nesta etapa;
- A enumeracao de todos os ciclos simples tem pior caso teorico exponencial em |V|; em redes esparsas o custo e dominado pela travessia DFS.
