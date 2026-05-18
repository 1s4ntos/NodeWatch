"""Testes unitários — SCC com algoritmo de Kosaraju (E4).

Casos cobertos:
  1. Ciclo simples → 1 SCC suspeito com todas as contas do ciclo.
  2. Grafo vazio → lista vazia sem erros.
  3. Vértices sem arestas → cada vértice é SCC isolado (não suspeito).
  4. DAG → cada vértice é SCC isolado.
  5. Volume interno calculado corretamente.
  6. Dois SCCs independentes → detectados separadamente.
  7. Ordenação — suspeitos primeiro, depois tamanho desc.
"""

from __future__ import annotations

from src.algoritmos.scc import find_scc
from src.grafo.graph import Graph


# ---------------------------------------------------------------------------
# 1. Ciclo simples → 1 SCC suspeito
# ---------------------------------------------------------------------------
def test_ciclo_forma_scc_suspeito() -> None:
    """C001→C002→C003→C001 deve formar um único SCC suspeito."""
    g = Graph()
    g.add_edge("C001", "C002", amount=10000.0, transaction_type="TRANSFER")
    g.add_edge("C002", "C003", amount=10000.0, transaction_type="TRANSFER")
    g.add_edge("C003", "C001", amount=9800.0,  transaction_type="TRANSFER")

    sccs = find_scc(g)
    suspicious = [s for s in sccs if s.is_suspicious]

    assert len(suspicious) == 1
    assert set(suspicious[0].vertices) == {"C001", "C002", "C003"}
    assert suspicious[0].size == 3
    assert suspicious[0].is_suspicious is True


# ---------------------------------------------------------------------------
# 2. Grafo vazio
# ---------------------------------------------------------------------------
def test_grafo_vazio_retorna_lista_vazia() -> None:
    """Grafo sem vértices retorna lista vazia."""
    g = Graph()
    assert find_scc(g) == []


# ---------------------------------------------------------------------------
# 3. Vértices isolados → SCCs de tamanho 1
# ---------------------------------------------------------------------------
def test_vertices_isolados_sao_sccs_individuais() -> None:
    """Cada vértice sem aresta forma seu próprio SCC (não suspeito)."""
    g = Graph()
    g.add_vertex("A")
    g.add_vertex("B")
    g.add_vertex("C")

    sccs = find_scc(g)

    assert len(sccs) == 3
    assert all(s.size == 1 for s in sccs)
    assert all(not s.is_suspicious for s in sccs)


# ---------------------------------------------------------------------------
# 4. DAG → sem SCC suspeito
# ---------------------------------------------------------------------------
def test_dag_nao_tem_scc_suspeito() -> None:
    """Grafo acíclico dirigido: cada vértice é SCC isolado."""
    g = Graph()
    g.add_edge("A", "B", amount=100.0)
    g.add_edge("B", "C", amount=100.0)
    g.add_edge("A", "C", amount=100.0)

    sccs = find_scc(g)
    suspicious = [s for s in sccs if s.is_suspicious]

    assert len(suspicious) == 0
    assert len(sccs) == 3  # A, B, C cada um isolado


# ---------------------------------------------------------------------------
# 5. Volume interno correto
# ---------------------------------------------------------------------------
def test_volume_interno_calculado_corretamente() -> None:
    """Volume interno = soma das arestas que ficam dentro do SCC."""
    g = Graph()
    g.add_edge("X", "Y", amount=5000.0, transaction_type="TRANSFER")
    g.add_edge("Y", "X", amount=4800.0, transaction_type="TRANSFER")
    # aresta externa — não entra no volume interno do SCC {X,Y}
    g.add_edge("X", "Z", amount=1000.0, transaction_type="PAYMENT")

    sccs = find_scc(g)
    suspicious = [s for s in sccs if s.is_suspicious]

    assert len(suspicious) == 1
    assert set(suspicious[0].vertices) == {"X", "Y"}
    assert suspicious[0].internal_volume == 9800.0   # 5000 + 4800
    assert suspicious[0].internal_edges  == 2


# ---------------------------------------------------------------------------
# 6. Dois SCCs independentes
# ---------------------------------------------------------------------------
def test_dois_sccs_independentes() -> None:
    """Dois ciclos sem conexão entre si → dois SCCs suspeitos."""
    g = Graph()
    # Ciclo 1: A→B→A
    g.add_edge("A", "B", amount=1000.0, transaction_type="TRANSFER")
    g.add_edge("B", "A", amount=900.0,  transaction_type="TRANSFER")
    # Ciclo 2: C→D→E→C
    g.add_edge("C", "D", amount=2000.0, transaction_type="TRANSFER")
    g.add_edge("D", "E", amount=1900.0, transaction_type="TRANSFER")
    g.add_edge("E", "C", amount=1800.0, transaction_type="TRANSFER")

    sccs = find_scc(g)
    suspicious = [s for s in sccs if s.is_suspicious]

    assert len(suspicious) == 2
    sizes = sorted(s.size for s in suspicious)
    assert sizes == [2, 3]


# ---------------------------------------------------------------------------
# 7. Ordenação — suspeitos primeiro, maior SCC antes
# ---------------------------------------------------------------------------
def test_ordenacao_suspeitos_primeiro() -> None:
    """SCCs suspeitos devem aparecer antes dos isolados."""
    g = Graph()
    g.add_edge("A", "B", amount=1000.0, transaction_type="TRANSFER")
    g.add_edge("B", "A", amount=900.0,  transaction_type="TRANSFER")
    g.add_vertex("Z")  # isolado

    sccs = find_scc(g)

    # primeiro elemento deve ser suspeito
    assert sccs[0].is_suspicious is True
    assert set(sccs[0].vertices) == {"A", "B"}
    # último deve ser isolado
    assert sccs[-1].is_suspicious is False
