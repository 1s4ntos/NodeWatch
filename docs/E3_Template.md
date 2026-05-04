# E3 — MVP: Núcleo Funcional com Primeiras Telas

> **Disciplina:** Teoria dos Grafos
> **Prazo:** 10 de maio de 2026
> **Peso:** 25% da nota final

---

## Identificação do Grupo

| Campo | Preenchimento |
|-------|---------------|
| Nome do projeto | Sistema de Detecção de Fraudes em Transações Financeiras |
| Repositório GitHub | https://github.com/1s4ntos/Sistema-de-Detec-o-de-Fraudes-em-Transa-es-Financeiras |
| Integrante 1 | Caio Winkler Marangoni — 39968545 |
| Integrante 2 | Guilherme Lombardi — 38054264 |
| Integrante 3 | Ryan dos Santos Veloso — 37732005 |

---

## 1. Como Executar o MVP

> Instrua como rodar o projeto do zero. Alguém que nunca viu o código deve conseguir executar seguindo estas instruções.

**Pré-requisitos:**

```bash
# Python 3.11 ou superior
python --version
```

**Instalação:**

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

**Execução:**

```bash
# Comando para rodar o MVP
python src/main.py --input data/exemplo_transacoes.csv
```

**Saída esperada:**

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

---

## 2. Algoritmo Implementado

| Campo | Resposta |
|-------|----------|
| Nome do algoritmo | DFS para detecção de ciclos em grafo direcionado |
| Arquivo de implementação | `src/algorithms/cycle_detection.py` |
| Complexidade de tempo | O(V + E) por travessia DFS |
| Complexidade de espaço | O(V) (pilha de recursão + conjunto `on_path`) |

**Trecho do código com comentário de Big-O:**

```python
def find_cycles(graph: Graph) -> List[List[str]]:
    """Encontra todos os ciclos simples em um grafo direcionado."""
    cycles: List[List[str]] = []

    # Construção do mapa de adjacência única — O(V + E)
    adjacency: Dict[str, Set[str]] = {v: set() for v in graph.vertices()}
    for edge in graph.edges():
        adjacency.setdefault(edge.source, set()).add(edge.target)
        adjacency.setdefault(edge.target, set())

    sorted_vertices = sorted(adjacency.keys())  # O(V log V) auxiliar

    for start in sorted_vertices:
        # Cada DFS individual é O(V + E) no pior caso
        path: List[str] = [start]
        on_path: Set[str] = {start}
        _dfs_cycles(start, start, adjacency, path, on_path, cycles)

    return cycles


def _dfs_cycles(start, current, adjacency, path, on_path, cycles) -> None:
    """DFS recursiva — O(V + E) por chamada inicial."""
    for neighbor in adjacency.get(current, ()):  # O(grau(current))
        if neighbor < start:
            continue                       # canonicalização — só descobrimos
                                           # cada ciclo a partir do seu menor vértice
        if neighbor == start:
            cycles.append(path + [start])  # ciclo encontrado
        elif neighbor not in on_path:
            path.append(neighbor)          # O(1)
            on_path.add(neighbor)          # O(1)
            _dfs_cycles(start, neighbor, adjacency, path, on_path, cycles)
            path.pop()                     # backtrack — O(1)
            on_path.remove(neighbor)       # backtrack — O(1)
```

---

## 3. Estrutura do Repositório

> Confirme que a estrutura implementada está de acordo com o E2.

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

**Desvios em relação ao E2:**

- Para o MVP foi entregue apenas o algoritmo principal (DFS de ciclos). As
  pastas `algorithms/centrality.py` e `algorithms/scc.py` previstas no E2 estão
  reservadas para a entrega E4 e ainda não foram criadas.
- Foi adicionado um `conftest.py` na raiz para que `pytest` reconheça o pacote
  `src` sem necessidade de `pip install -e .`.

---

## 4. Telas do MVP

> Nesta entrega, a interface é **CLI** (linha de comando), conforme acordado no
> E2. As "telas" abaixo correspondem às saídas do terminal.

### Tela de Entrada

A tela de entrada confirma o arquivo carregado, conta vértices/arestas e
informa qual algoritmo será executado.

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
```

*Descrição:* exibe ao analista o que entrou no sistema e o que será feito.

### Tela de Resultado

```
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

*Descrição:* lista os ciclos suspeitos encontrados, mostrando o caminho
percorrido e as contas envolvidas. Caso nenhum ciclo seja encontrado, é
exibida uma mensagem clara informando isso.

> Screenshots da CLI rodando serão anexados em `assets/` na entrega final, se
> exigidos pela professora. A saída textual acima é o registro da execução real.

---

## 5. Testes Unitários

| Algoritmo | Caso de teste | Status | Comando para executar |
|-----------|--------------|--------|----------------------|
| DFS de ciclos | Caso base (ciclo conhecido) | OK | `pytest tests/test_cycle_detection.py::test_caso_base_ciclo_conhecido` |
| DFS de ciclos | Grafo vazio | OK | `pytest tests/test_cycle_detection.py::test_grafo_vazio_retorna_lista_vazia` |
| DFS de ciclos | Grafo completo | OK | `pytest tests/test_cycle_detection.py::test_grafo_completo_executa_e_encontra_ciclos` |
| DFS de ciclos | DAG sem ciclos (bônus) | OK | `pytest tests/test_cycle_detection.py::test_dag_nao_possui_ciclos` |
| DFS de ciclos | Self-loop (bônus) | OK | `pytest tests/test_cycle_detection.py::test_self_loop_e_um_ciclo` |
| DFS de ciclos | Vértices isolados (bônus) | OK | `pytest tests/test_cycle_detection.py::test_grafo_apenas_com_vertices_isolados` |

**Como rodar todos os testes:**

```bash
pytest tests/
```

**Resultado atual:**

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

---

## 6. Histórico de Commits

> 8 commits semânticos desta entrega (saída de `git log --oneline`):

| Hash (7 chars) | Mensagem | Autor |
|----------------|----------|-------|
| `c843c30` | feat: cria estrutura base do MVP e arquivos de configuracao | Grupo 4 |
| `98112b5` | feat: implementa multigrafo direcionado ponderado em src/core | Grupo 4 |
| `2673df0` | feat: adiciona leitura de transacoes via CSV no formato PaySim | Grupo 4 |
| `6083338` | feat: implementa DFS para deteccao de ciclos suspeitos | Grupo 4 |
| `73211b8` | feat: cria CLI com telas de entrada e resultado | Grupo 4 |
| `a4cb14e` | test: adiciona testes unitarios para deteccao de ciclos | Grupo 4 |
| `bc67945` | docs: adiciona README e preenche template da E3 | Grupo 4 |
| `8281317` | docs: registra hashes reais dos commits no template da E3 | Grupo 4 |

---

## 7. O que está funcionando / O que ainda falta

| Funcionalidade | Status | Observação |
|---------------|--------|------------|
| Classe do grafo | Completo | Multigrafo direcionado ponderado em lista de adjacência |
| Algoritmo principal (DFS de ciclos) | Completo | Enumera ciclos simples em rotação canônica |
| Leitura de arquivo CSV | Completo | Parser PaySim com validação de cabeçalho |
| Tela de entrada | Completo | Mostra arquivo, |V|, |E| e algoritmo |
| Tela de resultado | Completo | Lista ciclos com caminho e contas envolvidas |
| Testes unitários | Completo | 3 obrigatórios + 3 bônus, todos passando |
| Centralidade de grau | Pendente | Reservado para E4 |
| SCC (Kosaraju) | Pendente | Reservado para E4 |
| Visualização gráfica | Pendente | Migração para Streamlit no E4 |

---

## Checklist de Entrega

- [x] Repositório público e acessível
- [x] .gitignore configurado
- [x] README com instruções de execução do MVP
- [x] Algoritmo principal executando sem erros
- [x] Tela de entrada e tela de resultado demonstráveis
- [x] 3 testes unitários por algoritmo (mínimo caso base passando) — 6 passando
- [x] ≥ 5 commits com prefixos semânticos (feat: