"""Testes unitários do algoritmo principal — DFS de detecção de ciclos.

Casos cobertos (mínimos exigidos pela E3):
  1. Caso base — grafo com ciclo conhecido deve devolvê-lo corretamente.
  2. Grafo vazio — deve retornar lista vazia, sem erros.
  3. Grafo completo — todos os vértices conectados entre si; o algoritmo
     deve executar e devolver pelo menos um ciclo.

Casos extras (bônus, ainda no escopo do MVP):
  4. Grafo acíclico — DAG não deve produzir nenhum ciclo.
  5. Self-loop — aresta de um vértice para si mesmo é um ciclo de comprimento 1.
"""

from __future__ import annotations

from src.algoritmos.cycle_detection import find_cycles, has_cycle
from src.grafo.graph import Graph


# ---------------------------------------------------------------------------
# 1. Caso base — grafo com ciclo conhecido
# ---------------------------------------------------------------------------
def test_caso_base_ciclo_conhecido() -> None:
    """Ciclo C001 -> C002 -> C003 -> C001 (smurfing clássico)."""
    graph = Graph()
    graph.add_edge("C001", "C002", amount=10000.0)
    graph.add_edge("C002", "C003", amount=10000.0)
    graph.add_edge("C003", "C001", amount=9800.0)
    # Aresta isolada que NÃO faz parte do ciclo:
    graph.add_edge("C004", "C005", amount=200.0)

    cycles = find_cycles(graph)

    assert has_cycle(graph) is True
    assert len(cycles) == 1, f"Esperado 1 ciclo, obtido {len(cycles)}: {cycles}"
    # O ciclo é reportado em rotação canônica (menor vértice primeiro):
    assert cycles[0] == ["C001", "C002", "C003", "C001"]


# ---------------------------------------------------------------------------
# 2. Grafo vazio — comportamento controlado
# ---------------------------------------------------------------------------
def test_grafo_vazio_retorna_lista_vazia() -> None:
    """Sem vértices nem arestas, o algoritmo deve devolver [] sem explodir."""
    graph = Graph()

    assert graph.vertex_count() == 0
    assert graph.edge_count() == 0
    assert find_cycles(graph) == []
    assert has_cycle(graph) is False


def test_grafo_apenas_com_vertices_isolados() -> None:
    """Vértices sem arestas também não formam ciclos."""
    graph = Graph()
    graph.add_vertex("A")
    graph.add_vertex("B")
    graph.add_vertex("C")

    assert find_cycles(graph) == []
    assert has_cycle(graph) is False


# ---------------------------------------------------------------------------
# 3. Grafo completo — todos os vértices conectados entre si
# ---------------------------------------------------------------------------
def test_grafo_completo_executa_e_encontra_ciclos() -> None:
    """K3 dirigido (toda aresta nas duas direções) -> múltiplos ciclos."""
    graph = Graph()
    vertices = ["A", "B", "C"]
    for u in vertices:
        for v in vertices:
            if u != v:
                graph.add_edge(u, v, amount=100.0)

    cycles = find_cycles(graph)

    # Espera-se ao menos os ciclos triangulares e os de comprimento 2.
    assert len(cycles) >= 1, "Grafo completo deveria conter ciclos"
    assert has_cycle(graph) is True

    # Sanity check: nenhum ciclo conhecido deve ficar duplicado em rotações
    # diferentes — graças à canonicalização pelo menor vértice.
    canonicas = {tuple(c) for c in cycles}
    assert len(canonicas) == len(cycles), "Ciclos duplicados detectados"


# ---------------------------------------------------------------------------
# 4. Bônus — DAG não tem ciclos
# ---------------------------------------------------------------------------
def test_dag_nao_possui_ciclos() -> None:
    """Grafo acíclico direcionado: A -> B -> C, A -> C."""
    graph = Graph()
    graph.add_edge("A", "B")
    graph.add_edge("B", "C")
    graph.add_edge("A", "C")

    assert find_cycles(graph) == []
    assert has_cycle(graph) is False


# ---------------------------------------------------------------------------
# 5. Bônus — self-loop é considerado ciclo
# ---------------------------------------------------------------------------
def test_self_loop_e_um_ciclo() -> None:
    """Uma aresta A -> A é um ciclo de comprimento 1."""
    graph = Graph()
    graph.add_edge("A", "A", amount=50.0)

    cycles = find_cycles(graph)
    assert cycles == [["A", "A"]]
    assert has_cycle(graph) is True
