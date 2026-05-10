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
- Interface visual interativa entregue como arquivo HTML autossuficiente.
- Estrutura alinhada com a arquitetura em camadas definida no E2.

## Pré-requisitos

- Python 3.11+ (para a CLI e os testes)
- `pytest` (instalado via `requirements.txt`)
- Navegador moderno — Chrome, Firefox ou Edge (para a interface visual)

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

### Opção 1 — Interface visual (recomendada)

Não requer instalação de dependências nem terminal. Basta abrir o arquivo:

```
interface/index.html
```

Dê **duplo clique** no arquivo pelo gerenciador de arquivos. O dashboard abrirá
diretamente no navegador padrão, mostrando o grafo interativo, os ciclos
detectados e as estatísticas das transações.

> A interface é completamente autossuficiente — todos os dados, estilos e
> componentes estão embutidos no próprio `index.html`. Nenhum servidor ou
> instalação adicional é necessária.

### Opção 2 — CLI (linha de comando)

Execute a CLI passando um CSV no formato PaySim:

```bash
python src/main.py --input dados/exemplo_transacoes.csv
```

Sem argumento, usa `dados/exemplo_transacoes.csv` por padrão:

```bash
python src/main.py
```

### Saída esperada

```
============================================================
=== Sistema de Detecção de Fraudes com Grafos ===
============================================================
Arquivo carregado: dados/exemplo_transacoes.csv
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
pytest testes/
```

ou, em modo verboso:

```bash
pytest testes/ -v
```

### Saída esperada (pytest -v)

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

## Estrutura do projeto

```
Sistema-de-Detec-o-de-Fraudes-em-Transa-es-Financeiras/
├── src/
│   ├── grafo/
│   │   └── graph.py            # Multigrafo direcionado ponderado
│   ├── algoritmos/
│   │   └── cycle_detection.py  # DFS para detecção de ciclos
│   ├── leitura/
│   │   └── file_reader.py      # Leitor de CSV (PaySim)
│   └── main.py                 # CLI
├── testes/
│   └── test_cycle_detection.py
├── dados/
│   └── exemplo_transacoes.csv
├── interface/
│   ├── index.html              # Dashboard interativo (autossuficiente)
├── docs/
│   ├── E1_Grupo4.md
│   ├── E2_Grupo4.md
│   ├── E3_Grupo4.md
|   ├── diagramaE1.png
|   └── diagramaE2.png
│   └── ui/
│       └── README-INTERFACE.md
├── .gitignore
├── LICENSE
├── README.md
├── conftest.py
├── projeto.bundle
├── push_to_github.sh
├── push_to_github.ps1
└── requirements.txt
```

> **Nota sobre os nomes das pastas:** os nomes em PT-BR (`grafo/`, `algoritmos/`,
> `leitura/`, `testes/`, `dados/`) tornam a estrutura auto-explicativa e
> alinhada com a documentação do trabalho. Mapeamento com a estrutura
> originalmente proposta no E2: `core/`→`grafo/`, `algorithms/`→`algoritmos/`,
> `io/`→`leitura/`, `tests/`→`testes/`, `data/`→`dados/`.

## Algoritmo principal

| Item                  | Valor                                           |
| --------------------- | ----------------------------------------------- |
| Algoritmo             | DFS para detecção de ciclos em grafo dirigido   |
| Arquivo               | `src/algoritmos/cycle_detection.py`             |
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
  do tamanho do PaySim completo (~6M linhas). Esse é um item natural para o E4.
- A interface visual exibe os dados do `exemplo_transacoes.csv` embutidos
  diretamente no HTML. Integração com CSV externo via upload está reservada para o E4.
