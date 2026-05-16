# Sentinel AI

Documentacao tecnica do assistente de analise de fraudes integrado ao dashboard.

## Objetivo

O Sentinel AI auxilia o analista a:

- Interpretar ciclos suspeitos detectados pelo algoritmo DFS;
- Entender metricas, graficos e componentes visuais do dashboard;
- Navegar pela interface com orientacao contextual;
- Diferenciar indicios de investigacao de provas definitivas de fraude.

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

## Execucao portavel

O projeto pode rodar de duas formas:

1. **Docker (recomendado)** — funciona em qualquer maquina com Docker instalado:
   ```bash
   cp .env.example .env    # preencher GEMINI_API_KEY
   docker compose up --build
   ```
   Dashboard: `http://127.0.0.1:5000/`

2. **Python local** — usando os scripts de setup:
   - Windows: `.\run_local.ps1`
   - Linux/macOS: `./run_local.sh`
   - Dashboard: abrir `interface/index.html` no navegador ou acessar `http://127.0.0.1:5000/`

Em ambos os casos:

- A API key fica no `.env` (nunca commitado);
- Docker usa `.env` em tempo de execucao via `env_file` no docker-compose;
- O Flask serve o dashboard diretamente na rota `/`;
- O frontend detecta automaticamente a URL do backend.

## Seguranca da chave API

- Nunca commitar o `.env`;
- Nunca colocar chave real no codigo-fonte;
- Nunca colocar chave no Dockerfile;
- Nunca colocar chave no frontend;
- Usar `.env` local para configuracao;
- `.env` esta listado no `.gitignore` e `.dockerignore`;
- Erros do backend retornam mensagem generica, sem dados sensiveis;
- O system prompt proibe o Sentinel AI de inventar dados nao presentes no contexto.

## Validacao

O projeto foi validado com:

- Docker build bem-sucedido;
- Container com status healthy;
- `/health` retornando `{"status": "ok", "apiKeyConfigured": true}`;
- Dashboard servido via Flask na rota `/`;
- Sentinel AI respondendo perguntas no chat;
- `.env` fora do controle de versao.

## Limitacoes

- **MVP academico** — nao e um sistema de producao;
- A IA auxilia a analise, mas **nao prova fraude** — a decisao final cabe ao analista humano;
- O Gemini depende de chave valida e cota disponivel (limite gratuito: 20 req/dia para gemini-2.5-flash);
- Os dados sao locais/embutidos no HTML conforme o escopo atual — upload de CSV externo nao implementado;
- SQL/banco de dados nao foi implementado nesta etapa;
- A enumeracao de todos os ciclos simples tem pior caso teorico exponencial em |V|; em redes esparsas o custo e dominado pela travessia DFS.
