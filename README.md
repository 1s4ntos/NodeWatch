# NodeWatch — Sistema de Detecção de Fraudes em Transações Financeiras

Trabalho da disciplina **Teoria dos Grafos** — Profa. Dra. Andrea Ono Sakai.
Entrega **E3 — MVP: Nucleo Funcional com Primeiras Telas** (Grupo 4).

## Integrantes

- Caio Winkler Marangoni — 39968545
- Guilherme Lombardi — 38054264
- Ryan dos Santos Veloso — 37732005
- Guilherme Liborio Camargo - 48490181

## Visao geral

MVP academico de deteccao de fraudes em transacoes financeiras usando grafos.

O sistema modela transacoes financeiras como um **multigrafo direcionado ponderado**:

- **Contas bancarias** sao vertices do grafo;
- **Transacoes financeiras** sao arestas direcionadas ponderadas (origem -> destino, peso = valor);
- **DFS (Depth-First Search)** detecta ciclos suspeitos — padrao tipico de lavagem de dinheiro (*layering*), em que o capital retorna a conta de origem apos percorrer intermediarias;
- **SCC (Componentes Fortemente Conectados)** via algoritmo de Kosaraju identifica grupos de contas onde o capital pode circular livremente;
- **Centralidade de grau** mede quantas transacoes entram e saem de cada conta, identificando hubs distribuidores, coletores e intermediarios.

O projeto inclui:

- **Dashboard visual interativo** com grafo, estatisticas, SCC, centralidade e tabelas;
- **Sentinel AI** — assistente de analise integrado ao dashboard, alimentado pelo Google Gemini;
- **Exportacao JSON** — salva resultados da analise em arquivo JSON;
- **Execucao com Python** — roda localmente com um unico comando;
- **Scripts de apresentacao** — inicio rapido com um unico comando.

---

## Inicio rapido

### Pre-requisitos

- Python 3.14 (versão testada; mínimo 3.12, exigido pelo `numpy==2.5.4` de `requirements-ml.txt`)
- Chave de API do Google Gemini ([aistudio.google.com/apikey](https://aistudio.google.com/apikey)), só para o chat da interface antiga; o painel do analista funciona sem ela

### Windows com poucos cliques: [Inicializador Rápido](Inicializador%20R%C3%A1pido/)

1. Abra a pasta **`Inicializador Rápido`** na raiz do repositório.
2. Clique duas vezes em **`Iniciar_NodeWatch.bat`**.
3. O navegador abre no painel do analista (`http://127.0.0.1:5000/`) quando ele estiver pronto. Para parar, use **Ctrl+C** na janela.

O primeiro uso cria o `.venv` e baixa as dependências, por isso precisa de conexão com a internet. O painel não exige a chave do Gemini. Mais detalhes estão no [README da pasta](Inicializador%20R%C3%A1pido/README.md).

### Windows (script de apresentação)

```powershell
.\start_presentation.ps1
```

### Linux/macOS

```bash
chmod +x start_presentation.sh
./start_presentation.sh
```

Depois acessar o **painel do analista**:

```
http://127.0.0.1:5000/
```

A interface antiga (grafos de demonstracao, ML antigo e chat Sentinel AI) fica em `http://127.0.0.1:5000/legado`.

O script:

- Verifica se o Python esta instalado;
- Cria `.venv` se nao existir;
- Instala dependencias;
- Cria `.env` a partir de `.env.example` se nao existir;
- Valida se a `GEMINI_API_KEY` esta configurada (rejeita placeholders);
- Inicia o backend com `python src/sentinel_ai.py`;
- Nao exibe a chave no terminal.

---

## Como executar o projeto em uma máquina nova

Testado em 12/11/2026 numa cópia limpa (sem `.venv`, sem `.env`, sem `artefatos_ml/`), num caminho com espaços e acentos: o modelo foi instalado, uma análise nova foi feita pela tela e reaberta depois de reiniciar o servidor, e os 402 testes passaram.

### O que vem no repositório e o que não vem

| Item | Vem no repositório? | Como chega à máquina |
|---|---|---|
| Código, interface, testes | ✅ | `git clone` |
| **Modelo treinado** (`modelos/modelo_unificado.joblib`, 38,8 MB) | ✅ | instalado automaticamente em `artefatos_ml/` na primeira execução, com SHA-256 conferido ([detalhes](modelos/README.md)) |
| Bibliotecas Python | ❌ | `pip install -r requirements.txt -r requirements-ml.txt` (precisa de internet uma vez) |
| Dataset IBM AML HI-Small | ❌ | **não é necessário** para usar o painel; só para treinar de novo (Kaggle, licença CDLA-Sharing-1.0) |
| Exemplos pequenos para testar | ✅ | `docs/exemplos/*.csv` (dados inventados), já listados no painel |
| Chave do Gemini (`.env`) | ❌ | opcional; só o chat da interface antiga usa |

### Pré-requisitos e hardware

- **Python 3.14** (versão testada; mínimo 3.12) e Git.
- **Internet no primeiro uso**, para instalar as bibliotecas (e, se o arquivo do modelo faltar, para baixá-lo).
- **Disco:** cerca de 55 MB do repositório e 540 MB do ambiente virtual (`.venv`), mais as análises que você fizer (cada análise guarda um SQLite).
- **Memória (medida no teste):** o processo com o modelo carregado usa cerca de 305 MB; o pico na análise de 150 mil transações foi de 577 MB, em 3,5 s. Arquivos de milhões de transações precisam de mais de 1 GB livre.
- Não precisa de GPU.

### Instalação e inicialização (comandos testados)

**Windows, com poucos cliques:** duplo clique em `Inicializador Rápido\Iniciar_NodeWatch.bat`. Ele cria o `.venv`, instala as bibliotecas, prepara o modelo e abre o painel.

**Windows, pelo terminal (PowerShell):**

```powershell
git clone https://github.com/1s4ntos/NodeWatch.git
cd NodeWatch
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-ml.txt
.venv\Scripts\python -m src.ml.provisionamento
.venv\Scripts\python src\sentinel_ai.py
```

**Linux/macOS:**

```bash
git clone https://github.com/1s4ntos/NodeWatch.git
cd NodeWatch
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-ml.txt
.venv/bin/python -m src.ml.provisionamento
.venv/bin/python src/sentinel_ai.py
```

O passo `python -m src.ml.provisionamento` é opcional: o servidor faz o mesmo ao iniciar. Rodá-lo antes mostra o resultado com calma. Saída esperada na primeira vez:

```
Modelo instalado em artefatos_ml/ (cópia de modelos/).
[OK] Modelo de ML pronto: lavagem-20261102T083253Z (instalado agora a partir de modelos/); 49 atributos; limiar de alerta 0.0910.
     Bibliotecas: scikit-learn 1.9.1, numpy 2.5.4, pandas 3.1.0, joblib 1.6.0
```

Nas vezes seguintes aparece "(já instalado)" e nada é copiado de novo.

### Executar uma nova análise

1. Abra `http://127.0.0.1:5000/`.
2. Em **Dataset e análise**, envie um `.csv`/`.zip` no formato do IBM AML ou em português (seção [Formato do CSV de entrada](#formato-do-csv-de-entrada)), ou escolha `transacoes_inventadas.csv` na lista **Ou escolher um dataset disponível** e clique em **Validar este dataset**.
3. Clique em **Analisar**. As seis etapas aparecem com o progresso; ao terminar, os indicadores, as contas, o grafo e a tabela aparecem abaixo.
4. A análise fica em **Análises recentes** e pode ser reaberta depois, mesmo após reiniciar o servidor.

### Como saber se a ML está funcionando

- No terminal do servidor: a linha `[OK] Modelo de ML pronto: lavagem-…`.
- No painel: o botão **Analisar** fica habilitado com um dataset válido; se o modelo faltar, aparece o aviso **Modelo não encontrado no servidor** com a causa e o que fazer.
- Em `http://127.0.0.1:5000/api/painel/estado`: `"modelo": {"disponivel": true, "versao": "lavagem-20261102T083253Z", ...}`.
- Depois de uma análise: ☰ → **Logs de ML** mostra "Modelo de lavagem carregado para a análise", com versão e limiar.

### Erros comuns

| Mensagem | Causa | O que fazer |
|---|---|---|
| `Bibliotecas de ML ausentes: scikit-learn, numpy, pandas, joblib` | Só o `requirements.txt` foi instalado | `python -m pip install -r requirements.txt -r requirements-ml.txt` |
| `Versões incompatíveis com o modelo distribuído: scikit-learn …` | Outra versão do scikit-learn no ambiente; o modelo `joblib` depende dela | Instale as versões fixadas num `.venv` novo: `python -m pip install -r requirements-ml.txt` |
| `modelos/modelo_unificado.joblib não confere com o SHA-256 do manifesto` | Arquivo corrompido ou cópia incompleta (por exemplo, ZIP baixado sem o arquivo grande) | `git checkout -- modelos/` ou `python -m src.ml.provisionamento` com internet (baixa e confere) |
| `Falha ao baixar o modelo de …` | Sem internet, ou o endereço não serve o arquivo | Confira a conexão; sem internet, copie `modelos/modelo_unificado.joblib` de outra cópia do repositório |
| `O modelo em artefatos_ml/modelo_unificado.joblib não pôde ser carregado` | Modelo local (treinado aqui) corrompido ou de outra versão | Renomeie ou apague esse arquivo e rode `python -m src.ml.provisionamento` para voltar ao distribuído |
| Análise concluída sem nenhum alerta | Cada análise começa **sem histórico**: contas "sem passado" quase não geram alerta nas primeiras ~72 h do arquivo | Use arquivos que cubram vários dias; para pontuar um dia com o passado, use `python -m src.ml.cli prever --tarefa lavagem --entrada dia.csv --historico dias_anteriores.csv --saida saida.csv` |
| `A porta 5000 esta ocupada` / `Ja ha um NodeWatch rodando … de OUTRA pasta` | Outro servidor na mesma porta | Feche-o com Ctrl+C na janela dele |

### Modo real × demonstrativo

Não existe modo demonstrativo: o painel sempre usa o **modelo real**, treinado no IBM AML HI-Small e distribuído em `modelos/`. Os arquivos de `docs/exemplos/` são **dados inventados** para testar o fluxo; eles passam pelo mesmo modelo, mas não representam o desempenho medido (que está em `docs/ml/resultados/`).

### Estratégia de distribuição (resumo)

O modelo treinado é versionado em `modelos/` com um manifesto (SHA-256, versões, origem dos dados). Na primeira execução ele é instalado em `artefatos_ml/` (pasta de trabalho, fora do Git), validado com uma previsão de teste e nunca carregado sem o SHA-256 conferir. Se o arquivo faltar, é baixado do próprio repositório (`raw.githubusercontent.com/1s4ntos/NodeWatch/main/modelos/…`) ou de `NODEWATCH_MODELO_URL`. O treino continua reproduzível pela CLI com o dataset público. Detalhes em [modelos/README.md](modelos/README.md).

---

## Como rodar com Python

### Passo a passo (Windows)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-ml.txt
python src/sentinel_ai.py
```

### Passo a passo (Linux/macOS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-ml.txt
python src/sentinel_ai.py
```

`requirements-ml.txt` traz scikit-learn, NumPy e pandas, sem os quais o painel não consegue analisar. O `.env` é opcional: só o chat Sentinel AI da interface antiga precisa da chave. Para configurá-lo, copie `.env.example` para `.env` e preencha a chave:

```env
GEMINI_API_KEY=sua_chave_real_aqui
```

Acessar o painel do analista:

```
http://127.0.0.1:5000/
```

O chat Sentinel AI (que usa a chave do Gemini) fica na interface antiga: `http://127.0.0.1:5000/legado`.

Health check:

```
http://127.0.0.1:5000/health
```

Para mais detalhes, consulte [README_LOCAL.md](README_LOCAL.md).

---

## Configuracao do `.env`

O arquivo `.env` armazena a chave de API e **nunca deve ser commitado**.

Exemplo seguro (sem chave real):

```env
SENTINEL_PROVIDER=gemini
GEMINI_API_KEY=coloque_sua_chave_gemini_aqui
GEMINI_MODEL=gemini-2.5-flash
SENTINEL_HOST=127.0.0.1
SENTINEL_PORT=5000
```

| Variavel          | Descricao                           | Valor padrao     |
| ----------------- | ----------------------------------- | ---------------- |
| SENTINEL_PROVIDER | Provider de IA (gemini / anthropic) | gemini           |
| GEMINI_API_KEY    | Chave de API do Google Gemini       | (obrigatorio)    |
| GEMINI_MODEL      | Modelo do Gemini                    | gemini-2.5-flash |
| SENTINEL_HOST     | Host do servidor Flask              | 127.0.0.1        |
| SENTINEL_PORT     | Porta do servidor Flask             | 5000             |

Protecoes:

- `.env` fica apenas na maquina local;
- `.env` esta no `.gitignore` — nao vai para o GitHub;
- A chave nao aparece no frontend nem nos logs.

Para obter uma chave: acesse [Google AI Studio](https://aistudio.google.com/apikey), faca login e clique em "Create API Key".

---

## CLI (linha de comando)

Tambem e possivel rodar a deteccao de ciclos via CLI:

```bash
python src/main.py --input dados/exemplo_transacoes.csv
```

Opcoes adicionais:

```bash
# Exibir Componentes Fortemente Conectados (SCC)
python src/main.py --input dados/exemplo_transacoes.csv --scc

# Exibir centralidade de grau
python src/main.py --input dados/exemplo_transacoes.csv --centralidade

# Exportar resultado em JSON
python src/main.py --input dados/exemplo_transacoes.csv --export-json --output minha_analise

# Tudo junto
python src/main.py --input dados/exemplo_transacoes.csv --scc --centralidade --export-json
```

---

## Como rodar os testes

```bash
pytest testes/ -v
```

Saida esperada:

```
collected 27 items

testes/test_centralidade.py::test_graus_basicos PASSED
testes/test_centralidade.py::test_volumes PASSED
testes/test_centralidade.py::test_risco_acumulado_por_ciclo PASSED
testes/test_centralidade.py::test_classificacao_hub_type PASSED
testes/test_centralidade.py::test_ordenacao_por_risk_score PASSED
testes/test_centralidade.py::test_grafo_vazio_retorna_lista_vazia PASSED
testes/test_cycle_detection.py::test_caso_base_ciclo_conhecido PASSED
testes/test_cycle_detection.py::test_grafo_vazio_retorna_lista_vazia PASSED
testes/test_cycle_detection.py::test_grafo_apenas_com_vertices_isolados PASSED
testes/test_cycle_detection.py::test_grafo_completo_executa_e_encontra_ciclos PASSED
testes/test_cycle_detection.py::test_dag_nao_possui_ciclos PASSED
testes/test_cycle_detection.py::test_self_loop_e_um_ciclo PASSED
testes/test_cycle_detection.py::test_prioridade_por_tipo_transacao PASSED
testes/test_exportador.py::test_secoes_obrigatorias_sempre_presentes PASSED
testes/test_exportador.py::test_secoes_opcionais_incluidas PASSED
testes/test_exportador.py::test_secoes_opcionais_ausentes PASSED
testes/test_exportador.py::test_save_analysis_cria_arquivo PASSED
testes/test_exportador.py::test_sanitize_name PASSED
testes/test_exportador.py::test_sem_sobrescrita PASSED
testes/test_exportador.py::test_estatisticas_corretas PASSED
testes/test_scc.py::test_ciclo_forma_scc_suspeito PASSED
testes/test_scc.py::test_grafo_vazio_retorna_lista_vazia PASSED
testes/test_scc.py::test_vertices_isolados_sao_sccs_individuais PASSED
testes/test_scc.py::test_dag_nao_tem_scc_suspeito PASSED
testes/test_scc.py::test_volume_interno_calculado_corretamente PASSED
testes/test_scc.py::test_dois_sccs_independentes PASSED
testes/test_scc.py::test_ordenacao_suspeitos_primeiro PASSED

27 passed in 0.0Xs
```

---

## Algoritmos

| Algoritmo                          | Arquivo                             | Complexidade      | Saida                                           |
| ---------------------------------- | ----------------------------------- | ----------------- | ----------------------------------------------- |
| DFS para deteccao de ciclos        | `src/algoritmos/cycle_detection.py` | O(V + E) por DFS  | Lista de CycleResult com prioridade e categoria  |
| SCC (Kosaraju)                     | `src/algoritmos/scc.py`             | O(V + E)          | Lista de SCCResult com volume e flags            |
| Centralidade de grau               | `src/algoritmos/centralidade.py`    | O(V + E)          | Lista de AccountCentrality com risk score        |
| Exportacao JSON                    | `src/leitura/exportador.py`         | O(V + E)          | Arquivo JSON com analise completa                |

## Formato do CSV de entrada

```csv
step,type,amount,nameOrig,nameDest,isFraud
1,TRANSFER,1000.00,C001,C002,0
1,TRANSFER,1500.00,C002,C003,0
1,TRANSFER,2000.00,C003,C001,1
```

Mapeamento campo -> grafo:

- `nameOrig` -> vertice de origem
- `nameDest` -> vertice de destino
- `amount`   -> peso da aresta
- `type`     -> tipo da transacao (metadado)
- `isFraud`  -> rotulo auxiliar (validacao)

---

## Principais arquivos

```
NodeWatch/
├── dados/
|   └── analises/
|       └── exemplo_transacoes.csv
├── docs/
|   ├── entregas/
|       ├── E1_Grupo4.md
|       ├── E2_Grupo4.md
|       ├── E3_Grupo4.md
|       ├── diagramaE1.png
|       └── diagramaE2.png
|   ├── lfa/
|       ├── Grupo1_Sprint1.md
|       ├── Grupo1_Sprint2.md 
|       ├── Grupo1_Sprint3.md 
|       ├── Grupo1_Sprint4.md 
|       └── RFC_Grupo1_Automatos_Fraude.md
|   ├── ui/
|       └──  README-INTERFACE.md
|   ├── SENTINEL_AI.md
|   ├── guia-execucao-local.md
|   └── guia-execucao-python.md
├── interface/
|   └── assets/
|       └── logo.png
|   ├──  NodeWatchlogo_transparente.png
|   └──  index.html
├── scripts/
|   ├── push_to_github.ps1
|   ├── push_to_github.sh
|   ├── rush_local.ps1
|   └── rush_local.sh
├── src/
|   ├── algortimos/
|       ├── __init__.py
|       ├── centralidade.py
|       ├── cycle_detection.py
|       └── scc.py
|   ├── grafo/
|       ├── __init__.py
|       └── graph.py
|   ├── leitura/
|       ├── __init__.py
|       ├── exportador.py
|       └── file_reader.py
|   ├── __init__.py
|   ├── main.py
|   └── sentinal_ai.py
├── testes/
|   ├── __init__.py
|   ├── test_centralidade.py
|   ├── test_cycle_detection.py
|   ├── test_exportador.py
|   └── test_scc.py
├── .env.example
├── .gitignore
├── LICENSE
├── README.md
├── conftest.py
├── requirements.txt
├── start_presentation.ps1
└── start_presentation.sh 
```

---

## Seguranca da chave API

- Nunca commitar o `.env`;
- Nunca colocar chave real no codigo-fonte;
- Nunca colocar chave no frontend;
- Usar `.env` local para configuracao;
- O `.env` esta protegido pelo `.gitignore`.

---

## Validacao

O projeto foi validado com:

- Backend Flask iniciando com `python src/sentinel_ai.py`;
- `/health` retornando `{"status": "ok", "apiKeyConfigured": true}`;
- Dashboard servido via Flask na rota `/`;
- Sentinel AI respondendo perguntas no chat;
- `.env` fora do controle de versao (`git status` limpo).

---

## Fluxo do programa
 
- CSV
  - └→ Validação (file_reader)
  - └→ Grafo (graph.py)
    - ├→ DFS          → Ciclos com prioridade de risco
    - ├→ Centralidade → Risk score por conta
    - └→ SCC          → Grupos de contas interligadas
      - └→ CLI (terminal)
      - └→ Dashboard (navegador)
      - └→ JSON (dados/analises/)
                   
---

## Modulo de ML (`src/ml`)

Arquitetura unica e modular (scikit-learn) com uma cabeca por tarefa:

- `estado_rede`: preve o estado da proxima medicao de rede (`dataset_final.csv`);
- `lavagem`: pontua transacoes do IBM AML HI-Small, que e sintetico;
- `fusao_rede_transacao`: fica bloqueada ate existir vinculo verificavel entre transacoes e telemetria.

**Para entender o sistema inteiro, comece pelo manual** [`docs/COMO_FUNCIONA_O_NODEWATCH.md`](docs/COMO_FUNCIONA_O_NODEWATCH.md) (tambem em [PDF](docs/COMO_FUNCIONA_O_NODEWATCH.pdf)).

Instalacao, comandos e protocolo estao em [`docs/ml/README.md`](docs/ml/README.md). Os resultados medidos estao em [`docs/ml/RELATORIO_ML.md`](docs/ml/RELATORIO_ML.md), e o contrato de integracao em [`docs/ml/CONTRATO_INTEGRACAO.md`](docs/ml/CONTRATO_INTEGRACAO.md).

### Painel do analista (pagina inicial)

`http://127.0.0.1:5000/` abre o **painel do analista**: enviar ou escolher um dataset de transacoes, validar, clicar em **Analisar**, acompanhar as etapas e investigar o recorte (indicadores, contas de maior risco, grafo da conta e tabela com filtros). Funciona sem chave de API. Resultados em SQLite e manifesto JSON por analise, em `artefatos_ml/painel/`. Detalhes, decisoes e limites em [`docs/ui/PAINEL_ANALISTA.md`](docs/ui/PAINEL_ANALISTA.md).

| endereco | o que e |
|---|---|
| `http://127.0.0.1:5000/` | **Painel do analista** (interface atual). E o endereco a usar. |
| `http://127.0.0.1:5000/legado` | **Interface antiga**, so para consulta: grafos de demonstracao, ML antigo (analise de rede, Analisar dataset, Eventos) e chat Sentinel AI. |

Os enderecos antigos com `#ml` ou `#grafos` redirecionam para a interface antiga. As secoes abaixo descrevem essa interface antiga.

### Interface antiga (`/legado`): Grafos e Machine Learning

O painel tem duas secoes na navegacao principal: **Grafos** (demonstracao estatica com as 16 transacoes de exemplo) e **Machine Learning** (previsoes e avaliacoes ja produzidas por `src/ml`, mais a area **Eventos**, que gera previsoes novas com o modelo salvo, sem treinar). A secao de ML funciona sem chave do Gemini.

```bash
python -m pip install -r requirements.txt -r requirements-ml.txt
python src/sentinel_ai.py
```

Abra `http://127.0.0.1:5000/legado` e clique em **Machine Learning** (ou va direto a `http://127.0.0.1:5000/legado#ml`). Ha seis areas: Visao geral, Analise de rede, Analise financeira, Avaliacao dos modelos, Analisar dataset e Eventos. Arquivos aceitos, limites e exportacao estao na secao 7 de [`docs/ui/README-INTERFACE.md`](docs/ui/README-INTERFACE.md).

### Analisar dataset: dados novos com o modelo salvo

Na interface antiga, em `http://127.0.0.1:5000/legado#ml/analisar`, selecione um CSV de transacoes ou de medicoes, valide e clique em **Analisar dataset**. Cada analise tem estado proprio, com pausa, retomada, cancelamento e historico opcional. Nada e treinado, e nada comeca sozinho: o processamento exige uma sessao ativa da interface. Formatos, limites e sessao em [`docs/ml/ANALISE_DATASETS.md`](docs/ml/ANALISE_DATASETS.md).

### Eventos: replay historico, API de ingestao e estado financeiro incremental

Na interface antiga, em `http://127.0.0.1:5000/legado#ml/eventos`, e possivel reproduzir arquivos existentes em ordem cronologica (rotulados como *replay historico*, nunca "ao vivo"), receber eventos pela API `POST /api/ml/eventos`, com aceitacao duravel e recuperacao depois de queda, e gerar previsoes de rede a partir de um CSV. As transacoes sao pontuadas por um estado por conta que calcula os 49 atributos financeiros sem reconstruir o historico; a equivalencia com o calculo em lote e testada. A fusao rede+transacao continua indisponivel: ha um laboratorio de **simulacao** que confere as regras de vinculo, mas a validacao preditiva depende de dados reais relacionados. Detalhes em [`docs/ml/EVENTOS.md`](docs/ml/EVENTOS.md) e numeros em [`docs/ml/BENCHMARK_EVENTOS.md`](docs/ml/BENCHMARK_EVENTOS.md).

---

## Limitacoes

- MVP academico — nao e um sistema de producao;
- A IA auxilia a analise, mas **nao prova fraude** — a decisao final cabe ao analista humano;
- O Gemini depende de chave valida e cota disponivel (limite gratuito de 20 req/dia para gemini-2.5-flash);
- A secao Grafos usa dados de exemplo embutidos no HTML (demonstracao estatica) — upload de CSV para grafos nao implementado; a secao Machine Learning le e importa CSVs de previsoes (ate 64 MB, so em memoria) e processa eventos com um trabalhador por processo e estado em memoria (API local, sem autenticacao);
- SQL/banco de dados nao foi implementado nesta etapa;
- A enumeracao de todos os ciclos simples tem pior caso teorico exponencial em |V|; em redes esparsas o custo e dominado pela travessia DFS;
- SCC e centralidade complementam a analise de ciclos, mas nao provam fraude isoladamente.
