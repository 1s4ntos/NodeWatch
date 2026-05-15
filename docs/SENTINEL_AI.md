# Sentinel AI

Resumo tecnico da implementacao do assistente de analise de fraudes integrado ao dashboard FraudGraph.

## Objetivo

O Sentinel AI auxilia o analista a:

- Interpretar ciclos suspeitos detectados pelo algoritmo DFS;
- Entender metricas, graficos e componentes visuais do dashboard;
- Navegar pela interface com orientacao contextual;
- Diferenciar indicios de investigacao de provas definitivas de fraude.

O Sentinel AI **nao toma decisoes**. A decisao final cabe sempre ao analista humano.

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

## Componentes reconhecidos

O Sentinel AI conhece todos os componentes da interface via catalogo (`SENTINEL_UI_CATALOG`):

| Componente | Tipo | Descricao resumida |
|---|---|---|
| **[Barra de Alerta]** | banner | Banner vermelho com resumo de ciclos detectados |
| **[Cards de Estatisticas]** | KPIs | Vertices, Arestas, Volume total, Em risco |
| **[Grafo Interativo]** | visualizacao | Contas como nos, transacoes como setas |
| **[Ciclos Detectados]** | painel | Selecao e visualizacao dos ciclos encontrados |
| **[Detalhes do Ciclo]** | painel | Contas envolvidas, valores, metricas do ciclo |
| **[Top Contas por Risco]** | ranking | 5 contas com maior score de risco |
| **[Tabela de Transacoes]** | tabela | Todas as transacoes com flags EM CICLO e LABELED |
| **[Distribuicao por Valor]** | grafico | Barras por faixa de valor (azul/amarelo) |
| **[Distribuicao por Step Temporal]** | grafico | Barras por step (azul = total, vermelho = fraude) |
| **[Log de Execucao]** | log | Historico de processamento do sistema |

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

## Seguranca

- A API key fica exclusivamente no `.env` (nao versionado);
- O frontend nao armazena nem expoe a chave;
- `.env` esta listado no `.gitignore`;
- Erros do backend retornam mensagem generica, sem dados sensiveis;
- O system prompt proibe o Sentinel AI de inventar dados nao presentes no contexto.

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

## Limitacoes

- O Sentinel AI nao prova fraude — apenas indica padroes para investigacao;
- A decisao final cabe sempre ao analista humano;
- O MVP usa dados embutidos no HTML (upload de CSV externo nao implementado);
- A cota gratuita do Gemini e limitada (20 req/dia para gemini-2.5-flash);
- A enumeracao de ciclos pode ser custosa em grafos muito grandes.
