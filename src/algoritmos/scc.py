"""Componentes Fortemente Conectados (SCC) via algoritmo de Kosaraju.

Um Componente Fortemente Conectado é um subgrafo maximal onde todo vértice
pode alcançar qualquer outro vértice do mesmo componente seguindo as arestas
na direção correta. Em redes financeiras, um SCC representa um grupo de
contas onde o dinheiro pode circular livremente entre todas elas — indicando
uma rede organizada de fraude, além de ciclos individuais.

Algoritmo de Kosaraju — duas passagens DFS
------------------------------------------
Passagem 1 (grafo original):
    Executa DFS e empilha os vértices por ordem de término. O último vértice
    a terminar vai para o topo da pilha.

Passagem 2 (grafo transposto — todas as arestas invertidas):
    Processa os vértices na ordem do topo da pilha. Cada DFS completa nessa
    passagem descobre exatamente um SCC.

Por que Kosaraju e não Tarjan?
    Ambos têm complexidade O(V + E). Kosaraju foi escolhido pela clareza
    didática: as duas passagens são conceitualmente separadas e mais fáceis
    de explicar e depurar. Tarjan faz tudo em uma DFS com pilha auxiliar —
    mais eficiente na prática, mas mais difícil de manter.

Complexidade
------------
* Tempo:  O(V + E) — duas passagens DFS + construção do grafo transposto.
* Espaço: O(V + E) — grafo transposto + pilha de ordenação + conjuntos.

Regras de negócio aplicadas
----------------------------
* SCCs com mais de 1 vértice são grupos de risco — o dinheiro pode circular
  entre todas as contas do componente.
* O volume total do SCC é a soma de todas as transações internas ao grupo.
* SCCs são ordenados por: tamanho desc → volume interno desc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

from src.grafo.graph import Graph


@dataclass
class SCCResult:
    """Resultado de um Componente Fortemente Conectado.

    Atributos:
        component_id:    índice sequencial do componente (1-based).
        vertices:        contas que pertencem ao componente.
        size:            número de contas no componente.
        internal_volume: soma das transações internas ao componente.
        is_suspicious:   True se size > 1 (circulação possível entre contas).
        internal_edges:  número de arestas internas ao componente.
    """
    component_id:    int
    vertices:        List[str]
    size:            int
    internal_volume: float = 0.0
    is_suspicious:   bool  = False
    internal_edges:  int   = 0


def find_scc(graph: Graph) -> List[SCCResult]:
    """Encontra todos os SCCs usando o algoritmo de Kosaraju.

    Args:
        graph: multigrafo direcionado com as transações.

    Returns:
        Lista de SCCResult ordenada por tamanho desc → volume interno desc.
        Apenas SCCs com size >= 1 são retornados (vértices isolados incluídos
        para completude, mas marcados como is_suspicious=False).

    Complexidade: O(V + E).
    """
    vertices = graph.vertices()
    if not vertices:
        return []

    # --- Passagem 1: DFS no grafo original → pilha de término --- O(V + E)
    adjacency = _build_adjacency(graph)
    visited: Set[str] = set()
    finish_stack: List[str] = []

    for v in vertices:
        if v not in visited:
            _dfs_finish(v, adjacency, visited, finish_stack)

    # --- Grafo transposto: inverte todas as arestas --- O(V + E)
    transposed = _build_transposed(graph)

    # --- Passagem 2: DFS no transposto na ordem reversa da pilha --- O(V + E)
    visited2: Set[str] = set()
    components: List[List[str]] = []

    while finish_stack:
        v = finish_stack.pop()
        if v not in visited2:
            component: List[str] = []
            _dfs_collect(v, transposed, visited2, component)
            components.append(sorted(component))  # ordem determinística

    # --- Enriquece cada componente com volume e flags ---
    results = _enrich_components(components, graph)

    # --- Ordena: suspeitos primeiro, depois tamanho desc, volume desc ---
    results.sort(
        key=lambda r: (r.is_suspicious, r.size, r.internal_volume),
        reverse=True,
    )

    return results


def _build_adjacency(graph: Graph) -> Dict[str, List[str]]:
    """Monta lista de adjacência simples (sem multiplicidade) — O(V + E)."""
    adj: Dict[str, List[str]] = {v: [] for v in graph.vertices()}
    seen: Set[tuple] = set()
    for edge in graph.edges():
        key = (edge.source, edge.target)
        if key not in seen:
            adj[edge.source].append(edge.target)
            seen.add(key)
    return adj


def _build_transposed(graph: Graph) -> Dict[str, List[str]]:
    """Inverte todas as arestas do grafo — O(V + E)."""
    trans: Dict[str, List[str]] = {v: [] for v in graph.vertices()}
    seen: Set[tuple] = set()
    for edge in graph.edges():
        key = (edge.target, edge.source)
        if key not in seen:
            trans[edge.target].append(edge.source)
            seen.add(key)
    return trans


def _dfs_finish(
    start: str,
    adjacency: Dict[str, List[str]],
    visited: Set[str],
    stack: List[str],
) -> None:
    """DFS iterativa — empilha vértices por ordem de término.

    Usa pilha explícita para evitar RecursionError em grafos grandes.
    """
    call_stack = [(start, iter(adjacency.get(start, [])))]
    visited.add(start)

    while call_stack:
        node, neighbors = call_stack[-1]
        try:
            neighbor = next(neighbors)
            if neighbor not in visited:
                visited.add(neighbor)
                call_stack.append(
                    (neighbor, iter(adjacency.get(neighbor, [])))
                )
        except StopIteration:
            call_stack.pop()
            stack.append(node)  # vértice terminou — entra na pilha


def _dfs_collect(
    start: str,
    transposed: Dict[str, List[str]],
    visited: Set[str],
    component: List[str],
) -> None:
    """DFS iterativa no grafo transposto — coleta um SCC completo."""
    stack = [start]
    visited.add(start)

    while stack:
        node = stack.pop()
        component.append(node)
        for neighbor in transposed.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                stack.append(neighbor)


def _enrich_components(
    components: List[List[str]],
    graph: Graph,
) -> List[SCCResult]:
    """Calcula volume interno e flags para cada componente — O(C × E)."""
    results: List[SCCResult] = []

    for idx, vertices in enumerate(components, start=1):
        vertex_set = set(vertices)
        internal_volume = 0.0
        internal_edges  = 0

        for edge in graph.edges():
            if edge.source in vertex_set and edge.target in vertex_set:
                internal_volume += edge.amount
                internal_edges  += 1

        size = len(vertices)
        results.append(SCCResult(
            component_id    = idx,
            vertices        = vertices,
            size            = size,
            internal_volume = internal_volume,
            is_suspicious   = size > 1,
            internal_edges  = internal_edges,
        ))

    return results


def scc_summary(sccs: List[SCCResult]) -> str:
    """Formata resumo dos SCCs para exibição na CLI."""
    suspicious = [s for s in sccs if s.is_suspicious]
    isolated   = [s for s in sccs if not s.is_suspicious]

    lines = [
        "-" * 60,
        "Componentes Fortemente Conectados (Kosaraju)",
        "-" * 60,
        f"  SCCs suspeitos (size > 1): {len(suspicious)}",
        f"  Vértices isolados:         {len(isolated)}",
        "",
    ]

    if suspicious:
        lines.append("  Grupos de risco:")
        for scc in suspicious:
            contas = ", ".join(scc.vertices)
            lines.append(
                f"    SCC #{scc.component_id} — {scc.size} contas "
                f"| Volume interno: R$ {scc.internal_volume:,.2f} "
                f"| Arestas internas: {scc.internal_edges}"
            )
            lines.append(f"      Contas: {contas}")

    lines.append("-" * 60)
    return "\n".join(lines)
