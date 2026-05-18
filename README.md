# Sistema de Deteccao de Fraudes em Transacoes Financeiras

Trabalho da disciplina **Teoria dos Grafos** — Profa. Dra. Andrea Ono Sakai.
Entrega **E3 — MVP: Nucleo Funcional com Primeiras Telas** (Grupo 4).

## Integrantes

- Caio Winkler Marangoni — 39968545
- Guilherme Lombardi — 38054264
- Ryan dos Santos Veloso — 37732005

## Visao geral

MVP academico de deteccao de fraudes em transacoes financeiras usando grafos.

O sistema modela transacoes financeiras como um **multigrafo direcionado ponderado**:

- **Contas bancarias** sao vertices do grafo;
- **Transacoes financeiras** sao arestas direcionadas ponderadas (origem -> destino, peso = valor);
- **DFS (Depth-First Search)** detecta ciclos suspeitos — padrao tipico de lavagem de dinheiro (*layering*), em que o capital retorna a conta de origem apos percorrer intermediarias.

O projeto inclui:

- **Dashboard visual interativo** com grafo, estatisticas e tabelas;
- **Sentinel AI** — assistente de analise integrado ao dashboard, alimentado pelo Google Gemini;
- **Execucao com Python** — roda localmente com um unico comando;
- **Scripts de apresentacao** — inicio rapido com um unico comando.

---

## Inicio rapido

### Pre-requisitos

- Python 3.11+
- Chave de API do Google Gemini ([aistudio.google.com/apikey](https://aistudio.google.com/apikey))

### Windows

```powershell
.\start_presentation.ps1
```

### Linux/macOS

```bash
chmod +x start_presentation.sh
./start_presentation.sh
```

Depois acessar:

```
http://127.0.0.1:5000/
```

O script:

- Verifica se o Python esta instalado;
- Cria `.venv` se nao existir;
- Instala dependencias;
- Cria `.env` a partir de `.env.example` se nao existir;
- Valida se a `GEMINI_API_KEY` esta configurada (rejeita placeholders);
- Inicia o backend com `python src/sentinel_ai.py`;
- Nao exibe a chave no terminal.

---

## Como rodar com Python

### Passo a passo (Windows)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python src/sentinel_ai.py
```

### Passo a passo (Linux/macOS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python src/sentinel_ai.py
```

Editar `.env` e preencher a chave:

```env
GEMINI_API_KEY=sua_chave_real_aqui
```

Acessar o dashboard:

```
http://127.0.0.1:5000/
```

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
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\Activate.ps1  # Windows
pip install -r requirements.txt
python src/main.py --input dados/exemplo_transacoes.csv
```

Saida esperada:

```
============================================================
=== Sistema de Deteccao de Fraudes com Grafos ===
============================================================
Arquivo carregado: dados/exemplo_transacoes.csv
Vertices (contas): 10
Arestas (transacoes): 10
Algoritmo a executar: DFS para deteccao de ciclos suspeitos
Complexidade: tempo O(V + E) | espaco O(V)
------------------------------------------------------------
Resultado:
  Ciclo suspeito 1:
    Caminho: C001 -> C002 -> C003 -> C001
    Contas envolvidas (3): C001, C002, C003
  Ciclo suspeito 2:
    Caminho: C006 -> C007 -> C008 -> C006
    Contas envolvidas (3): C006, C007, C008
------------------------------------------------------------
Total de ciclos encontrados: 2
```

---

## Como rodar os testes

```bash
pytest testes/ -v
```

Saida esperada:

```
collected 6 items

testes/test_cycle_detection.py::test_caso_base_ciclo_conhecido PASSED
testes/test_cycle_detection.py::test_dag_nao_possui_ciclos PASSED
testes/test_cycle_detection.py::test_grafo_apenas_com_vertices_isolados PASSED
testes/test_cycle_detection.py::test_grafo_completo_executa_e_encontra_ciclos PASSED
testes/test_cycle_detection.py::test_grafo_vazio_retorna_lista_vazia PASSED
testes/test_cycle_detection.py::test_self_loop_e_um_ciclo PASSED

6 passed in 0.0Xs
```

---

## Algoritmo principal

| Item                   | Valor                                         |
| ---------------------- | --------------------------------------------- |
| Algoritmo              | DFS para deteccao de ciclos em grafo dirigido  |
| Arquivo                | `src/algoritmos/cycle_detection.py`            |
| Complexidade de tempo  | O(V + E) por DFS                              |
| Complexidade de espaco | O(V) (pilha de recursao + conjunto on-path)    |
| Saida                  | Lista de ciclos simples em rotacao canonica    |

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
Sistema-de-Detec-o-de-Fraudes-em-Transa-es-Financeiras/
├── src/
│   ├── sentinel_ai.py             # Backend Flask, health check, proxy Gemini, serve dashboard
│   ├── grafo/
│   │   └── graph.py               # Multigrafo direcionado ponderado
│   ├── algoritmos/
│   │   └── cycle_detection.py     # DFS para deteccao de ciclos
│   ├── leitura/
│   │   └── file_reader.py         # Leitor de CSV (PaySim)
│   └── main.py                    # CLI
├── interface/
│   └── index.html                 # Dashboard visual interativo e chat Sentinel AI
├── testes/
│   └── test_cycle_detection.py    # 6 testes unitarios
├── dados/
│   └── exemplo_transacoes.csv     # Dataset de exemplo
├── docs/
│   ├── SENTINEL_AI.md             # Documentacao tecnica do assistente
│   ├── E1_Grupo4.md
│   ├── E2_Grupo4.md
│   ├── E3_Grupo4.md
│   └── ui/
│       └── README-INTERFACE.md
├── .env.example                   # Modelo de configuracao (sem chave real)
├── start_presentation.ps1         # Inicio rapido no Windows
├── start_presentation.sh          # Inicio rapido no Linux/macOS
├── run_local.ps1                  # Setup local no Windows
├── run_local.sh                   # Setup local no Linux/macOS
├── README.md                      # Este arquivo
├── README_LOCAL.md                # Guia para execucao local
├── README_DEPLOY.md               # Guia de execucao com Python
├── requirements.txt               # Dependencias Python
├── .gitignore
└── LICENSE
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

## Limitacoes

- MVP academico — nao e um sistema de producao;
- A IA auxilia a analise, mas **nao prova fraude** — a decisao final cabe ao analista humano;
- O Gemini depende de chave valida e cota disponivel (limite gratuito de 20 req/dia para gemini-2.5-flash);
- Os dados sao locais/embutidos no HTML conforme o escopo atual — upload de CSV externo nao implementado;
- SQL/banco de dados nao foi implementado nesta etapa;
- A enumeracao de todos os ciclos simples tem pior caso teorico exponencial em |V|; em redes esparsas o custo e dominado pela travessia DFS.
