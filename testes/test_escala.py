"""Testes de escala e de regressão — SCC e detecção de ciclos.

Protegem as otimizações feitas em ``scc._enrich_components`` e em
``cycle_detection.find_cycles``:
  1. Ciclo muito longo não estoura RecursionError (DFS iterativa).
  2. Volume e arestas internas por SCC continuam corretos com vários SCCs
     e arestas que ligam um SCC a outro (não são internas).
  3. Self-loop dentro de um SCC maior continua sendo reportado como ANOMALIA,
     junto com o ciclo real.
  4. Parte acíclica do grafo não gera ciclos nem atrapalha os existentes.
  5. Ciclos em componentes diferentes são todos encontrados.
"""

from __future__ import annotations

from src.algoritmos.cycle_detection import find_cycles
from src.algoritmos.scc import find_scc
from src.grafo.graph import Graph


# ---------------------------------------------------------------------------
# 1. Ciclo longo (acima do limite de recursão padrão do Python, ~1000)
# ---------------------------------------------------------------------------
def test_ciclo_longo_nao_estoura_recursao() -> None:
    n = 3000
    g = Graph()
    for i in range(n):
        g.add_edge(f"V{i:05d}", f"V{(i + 1) % n:05d}", amount=1.0,
                   transaction_type="TRANSFER")

    ciclos = find_cycles(g)

    assert len(ciclos) == 1
    assert ciclos[0].category == "CICLO"
    assert len(ciclos[0].path) == n + 1  # primeiro vértice repetido no fim
    assert ciclos[0].path[0] == ciclos[0].path[-1]


# ---------------------------------------------------------------------------
# 2. Volume interno com vários SCCs e aresta entre componentes
# ---------------------------------------------------------------------------
def test_volume_interno_ignora_arestas_entre_componentes() -> None:
    g = Graph()
    # SCC 1: A <-> B (100 + 50)
    g.add_edge("A", "B", amount=100.0, transaction_type="TRANSFER")
    g.add_edge("B", "A", amount=50.0, transaction_type="TRANSFER")
    # SCC 2: C -> D -> E -> C (10 + 20 + 30), com aresta paralela C->D (5)
    g.add_edge("C", "D", amount=10.0, transaction_type="PAYMENT")
    g.add_edge("C", "D", amount=5.0, transaction_type="PAYMENT")
    g.add_edge("D", "E", amount=20.0, transaction_type="PAYMENT")
    g.add_edge("E", "C", amount=30.0, transaction_type="PAYMENT")
    # Aresta entre SCCs: não é interna a nenhum deles
    g.add_edge("B", "C", amount=999.0, transaction_type="TRANSFER")

    por_vertices = {frozenset(s.vertices): s for s in find_scc(g)}

    scc1 = por_vertices[frozenset({"A", "B"})]
    scc2 = por_vertices[frozenset({"C", "D", "E"})]
    assert scc1.internal_volume == 150.0 and scc1.internal_edges == 2
    assert scc2.internal_volume == 65.0 and scc2.internal_edges == 4


# ---------------------------------------------------------------------------
# 3. Self-loop dentro de um SCC maior
# ---------------------------------------------------------------------------
def test_self_loop_em_scc_maior_continua_anomalia() -> None:
    g = Graph()
    g.add_edge("A", "A", amount=1.0, transaction_type="PAYMENT")
    g.add_edge("A", "B", amount=2.0, transaction_type="TRANSFER")
    g.add_edge("B", "A", amount=3.0, transaction_type="TRANSFER")

    por_categoria = {c.category: c for c in find_cycles(g)}

    assert set(por_categoria) == {"ANOMALIA", "CICLO"}
    assert por_categoria["ANOMALIA"].path == ["A", "A"]
    assert por_categoria["CICLO"].path == ["A", "B", "A"]


def test_self_loop_isolado_continua_anomalia() -> None:
    g = Graph()
    g.add_edge("X", "X", amount=1.0, transaction_type="PAYMENT")
    g.add_edge("X", "Y", amount=1.0, transaction_type="PAYMENT")

    ciclos = find_cycles(g)

    assert [(c.category, c.path) for c in ciclos] == [("ANOMALIA", ["X", "X"])]


# ---------------------------------------------------------------------------
# 4. Parte acíclica não gera ciclos
# ---------------------------------------------------------------------------
def test_parte_aciclica_nao_gera_ciclos() -> None:
    g = Graph()
    # Cadeia sem retorno
    for a, b in [("P1", "P2"), ("P2", "P3"), ("P3", "P4")]:
        g.add_edge(a, b, amount=1.0, transaction_type="PAYMENT")
    # Ciclo ligado à cadeia
    g.add_edge("P4", "Q1", amount=1.0, transaction_type="TRANSFER")
    g.add_edge("Q1", "Q2", amount=1.0, transaction_type="TRANSFER")
    g.add_edge("Q2", "Q1", amount=1.0, transaction_type="TRANSFER")

    ciclos = find_cycles(g)

    assert [c.path for c in ciclos] == [["Q1", "Q2", "Q1"]]


# ---------------------------------------------------------------------------
# 5. Ciclos em componentes diferentes
# ---------------------------------------------------------------------------
def test_ciclos_em_componentes_diferentes_sao_todos_encontrados() -> None:
    g = Graph()
    for a, b in [("A", "B"), ("B", "A"), ("C", "D"), ("D", "E"), ("E", "C")]:
        g.add_edge(a, b, amount=1.0, transaction_type="TRANSFER")

    caminhos = sorted(tuple(c.path) for c in find_cycles(g))

    assert caminhos == [("A", "B", "A"), ("C", "D", "E", "C")]
