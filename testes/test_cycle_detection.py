"""Testes unitários do algoritmo principal — DFS de detecção de ciclos.

Casos cobertos (mínimos exigidos pela E3):
  1. Caso base — grafo com ciclo conhecido deve devolvê-lo corretamente.
  2. Grafo vazio — deve retornar lista vazia, sem erros.
  3. Grafo completo — todos os vértices conectados entre si; o algoritmo
     deve executar e devolver pelo menos um ciclo.

Casos extras (bônus):
  4. Grafo acíclico — DAG não deve produzir nenhum ciclo.
  5. Self-loop — aresta de um vértice para si mesmo é ANOMALIA (RN05).
  6. Vértices isolados — sem arestas, sem ciclos.

Atualizado no E4:
  - find_cycles() agora retorna List[CycleResult] (não mais List[List[str]]).
  - Cada CycleResult expõe: path, category, priority, total_value, loss.
  - Self-loop retorna category="ANOMALIA" (RN05).
  - Ciclos com TRANSFER retornam priority="ALTO" (RN03).
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
    graph.add_edge("C001", "C002", amount=10000.0, transaction_type="TRANSFER")
    graph.add_edge("C002", "C003", amount=10000.0, transaction_type="TRANSFER")
    graph.add_edge("C003", "C001", amount=9800.0,  transaction_type="TRANSFER")
    graph.add_edge("C004", "C005", amount=200.0,   transaction_type="PAYMENT")

    cycles = find_cycles(graph)

    assert has_cycle(graph) is True
    assert len(cycles) == 1, f"Esperado 1 ciclo, obtido {len(cycles)}"
    # Caminho canônico
    assert cycles[0].path == ["C001", "C002", "C003", "C001"]
    # Prioridade ALTO por ser TRANSFER (RN03)
    assert cycles[0].priority == "ALTO"
    # Categoria CICLO (não é self-loop)
    assert cycles[0].category == "CICLO"
    # Valor total correto
    assert cycles[0].total_value == 29800.0
    # Perda: 10000 - 9800 = 200
    assert cycles[0].loss == 200.0


# ---------------------------------------------------------------------------
# 2. Grafo vazio
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
# 3. Grafo completo
# ---------------------------------------------------------------------------
def test_grafo_completo_executa_e_encontra_ciclos() -> None:
    """K3 dirigido (toda aresta nas duas direções) -> múltiplos ciclos."""
    graph = Graph()
    vertices = ["A", "B", "C"]
    for u in vertices:
        for v in vertices:
            if u != v:
                graph.add_edge(u, v, amount=100.0, transaction_type="TRANSFER")

    cycles = find_cycles(graph)

    assert len(cycles) >= 1, "Grafo completo deveria conter ciclos"
    assert has_cycle(graph) is True
    # Sem duplicatas (canonicalização)
    canonicas = {tuple(c.path) for c in cycles}
    assert len(canonicas) == len(cycles), "Ciclos duplicados detectados"
    # Todos de prioridade ALTO (são TRANSFER)
    assert all(c.priority == "ALTO" for c in cycles)


# ---------------------------------------------------------------------------
# 4. DAG não tem ciclos
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
# 5. Self-loop é ANOMALIA (RN05)
# ---------------------------------------------------------------------------
def test_self_loop_e_um_ciclo() -> None:
    """Uma aresta A -> A é detectada como ANOMALIA, não como CICLO (RN05)."""
    graph = Graph()
    graph.add_edge("A", "A", amount=50.0, transaction_type="TRANSFER")

    cycles = find_cycles(graph)

    assert len(cycles) == 1
    assert cycles[0].path == ["A", "A"]
    assert cycles[0].category == "ANOMALIA"   # RN05
    assert has_cycle(graph) is True


# ---------------------------------------------------------------------------
# 6. Prioridade por tipo de transação (RN03)
# ---------------------------------------------------------------------------
def test_prioridade_por_tipo_transacao() -> None:
    """Ciclo com CASH_OUT deve ter prioridade MÉDIO-ALTO, não ALTO."""
    graph = Graph()
    graph.add_edge("X001", "X002", amount=5000.0, transaction_type="CASH_OUT")
    graph.add_edge("X002", "X003", amount=4800.0, transaction_type="CASH_OUT")
    graph.add_edge("X003", "X001", amount=4600.0, transaction_type="CASH_OUT")

    cycles = find_cycles(graph)

    assert len(cycles) == 1
    assert cycles[0].priority == "MÉDIO-ALTO"
    assert cycles[0].category == "CICLO"
    assert cycles[0].loss == 400.0  # 5000 - 4600
