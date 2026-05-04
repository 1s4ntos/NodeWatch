# Sistema de Detecção de Fraudes em Transações Financeiras

Trabalho da disciplina **Teoria dos Grafos** — Profa. Dra. Andréa Ono Sakai.
Entrega **E3 — MVP: Núcleo Funcional com Primeiras Telas** (Grupo 4).

O sistema modela transações financeiras como um **multigrafo direcionado
ponderado** (contas = vértices, transações = arestas) e aplica **DFS** para
detectar **ciclos suspeitos** — padrão típico de lavagem de dinheiro
(*layering*), em que o capital retorna à conta de origem após percorrer uma
cadeia de intermediárias.

## Integrantes

- Caio Winkler Marangoni — 39968545
- Guilherme Lombardi — 38054264
- Ryan dos Santos Veloso — 37732005

## Status atual da entrega

- MVP funcional rodando de ponta a ponta (CSV → Grafo → DFS → CLI).
- Algoritmo principal (DFS de detecção de ciclos) implementado e testado.
- 6 testes unitários para o algoritmo principal, todos passando.
- Estrutura alinhada com a arquitetura em camadas definida no E2.

## Pré-requisitos

- Python 3.11+
- `pytest` (instalado via `requirements.txt`)

## Instalação

```bash
git clone https://github.com/1s4ntos/Sistema-de-Detec-o-de-Fraudes-em-Transa-es-Financeiras.git
cd Sistema-de-Detec-o-de-Fraudes-em-Transa-es-Financeiras
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

## Como executar o MVP

Execute a CLI passando um CSV no formato PaySim:

```bash
python src/main.py --input data/exemplo_transacoes.csv
```

Sem argumento, ele usa `data/exemplo_transacoes.csv` por padrão:

```bash
python src/main.py
```

### Saída esperada

```
============================================================
=== Sistema de Detecção de Fraudes com Grafos ===
============================================================
Arquivo carregado: data/exemplo_transacoes.csv
Vértices (contas): 10
Arestas (transações): 10
Algoritmo a executar: DFS para detecção de ciclos suspeitos
Complexidade: tempo O(V + E) | espaço O(V)
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

## Como rodar os testes

```bash
pytest tests/
```

ou, em modo verboso:

```bash
pytest tests/ -v
```

### Saída esperada (pytest -v)

```
collected 6 items

tests/test_cycle_detection.py::test_caso_base_ciclo_conhecido PASSED
tests/test_cycle_detection.py::test_dag_nao_possui_ciclos PASSED
tests/test_cycle_detection.py::test_grafo_apenas_com_vertices_isolados PASSED
tests/test_cycle_detection.py::test_grafo_completo_executa_e_encontra_ciclos PASSED
tests/test_cycle_detection.py::test_grafo_vazio_retorna_lista_vazia PASSED
tests/test_cycle_detection.py::test_self_loop_e_um_ciclo PASSED

6 passed in 0.0Xs
```

## Estrutura do projeto

```
deteccao-fraudes-grafos/
├── src/
│   ├── core/
│   │   └── graph.py            # Multigrafo direcionado ponderado
│   ├── algorithms/
│   │   └── cycle_detection.py  # DFS para detecção de ciclos
│   ├── io/
│   │   └── file_reader.py      # Leitor de CSV (PaySim)
│   └── main.py                 # CLI
├── tests/
│   └── test_cycle_detection.py
├── data/
│   └── exemplo_transacoes.csv
├── docs/
│   ├── E1_DetecçãoFraudesEmTransaçõesFinanceirasGrupo4_Grafos.md
│   ├── E2_Grupo4.md
│   ├── E3_MVP.pdf
│   └── E3_Template.md
├── conftest.py
├── requirements.txt
├── README.md
└── .gitignore
```

## Algoritmo principal

| Item                  | Valor                                           |
| --------------------- | ----------------------------------------------- |
| Algoritmo             | DFS para detecção de ciclos em grafo dirigido   |
| Arquivo               | `src/algorithms/cycle_detection.py`             |
| Complexidade de tempo | O(V + E) por DFS                                |
| Complexidade de espaço| O(V) (pilha de recursão + conjunto on-path)    |
| Saída                 | Lista de ciclos simples em rotação canônica     |

## Formato do CSV de entrada

```csv
step,type,amount,nameOrig,nameDest,isFraud
1,TRANSFER,1000.00,C001,C002,0
1,TRANSFER,1500.00,C002,C003,0
1,TRANSFER,2000.00,C003,C001,1
```

Mapeamento campo → grafo:

- `nameOrig` → vértice de origem
- `nameDest` → vértice de destino
- `amount`   → peso da aresta
- `type`     → tipo da transação (metadado)
- `isFraud`  → rótulo auxiliar (validação)

## Limitações conhecidas

- A enumeração de **todos** os ciclos simples tem pior caso teórico exponencial em |V|.
  Em redes financeiras esparsas o custo prático é dominado pela travessia DFS.
- O MVP processa o CSV inteiramente em memória — não foi otimizado para arquivos