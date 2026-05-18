"""Detecção de ciclos em grafos direcionados via Busca em Profundidade (DFS).

No contexto de transações financeiras, ciclos representam **fluxos circulares
de capital** — dinheiro que sai de uma conta, percorre intermediárias e
retorna à origem. Este é um padrão clássico de lavagem de dinheiro
(*layering*), onde a circulação visa mascarar a procedência do recurso.

Algoritmo
---------
Variante de DFS para enumeração de **ciclos simples** (cada vértice aparece
no máximo uma vez por ciclo). Para evitar contagem duplicada do mesmo ciclo
em rotações distintas, usamos a heurística de Johnson: cada ciclo é reportado
apenas quando o DFS parte do **menor vértice** que ele contém.

Complexidade
------------
* **Tempo:** O(V + E) por chamada de DFS individual; o pior caso teórico
  para enumerar todos os ciclos simples é exponencial em ``V``, mas em
  redes financeiras reais (esparsas) o custo prático é dominado pela
  travessia.
* **Espaço:** O(V) para a pilha de recursão e o conjunto de vértices
  visitados no caminho atual.

Regras de negócio aplicadas
----------------------------
* RN02 — Todo ciclo fechado é reportado, sem filtro por valor mínimo.
* RN03 — Cada ciclo recebe nível de prioridade pelo tipo de maior risco
  presente entre suas arestas: ALTO (TRANSFER), MÉDIO-ALTO (CASH_OUT),
  MÉDIO (PAYMENT), BAIXO (CASH_IN / DEBIT).
* RN05 — Self-loops são classificados como ANOMALIA (categoria separada).
* RN06 — Ciclos ordenados por: prioridade → valor total → intermediários.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from src.grafo.graph import Graph

# ---------------------------------------------------------------------------
# Prioridade de risco por tipo de transação (RN03)
# ---------------------------------------------------------------------------
_TIPO_PRIORIDADE: Dict[str, int] = {
    "TRANSFER": 4,   # ALTO       — Pix, principal vetor de layering
    "CASH_OUT": 3,   # MÉDIO-ALTO — extração frequente no fim de ciclos
    "PAYMENT":  2,   # MÉDIO      — TED / DOC
    "CASH_IN":  1,   # BAIXO      — depósito / crédito
    "DEBIT":    1,   # BAIXO      — débito automático
}
_PRIORIDADE_LABEL: Dict[int, str] = {
    4: "ALTO",
    3: "MÉDIO-ALTO",
    2: "MÉDIO",
    1: "BAIXO",
}


@dataclass
class CycleResult:
    """Resultado enriquecido de um ciclo detectado.

    Atributos:
        path:        vértices do ciclo, com o primeiro repetido no fim.
        category:    "CICLO" (layering) ou "ANOMALIA" (self-loop).
        priority:    nível de risco — "ALTO", "MÉDIO-ALTO", "MÉDIO", "BAIXO".
        total_value: soma dos valores das arestas do ciclo (peso total).
        loss:        diferença entre a primeira e a última aresta do ciclo.
        intermediaries: número de contas intermediárias (len(path) - 2).
    """
    path: List[str]
    category: str           # "CICLO" ou "ANOMALIA"
    priority: str           # "ALTO" | "MÉDIO-ALTO" | "MÉDIO" | "BAIXO"
    total_value: float
    loss: float
    intermediaries: int


def _cycle_priority(path: List[str], graph: Graph) -> Tuple[int, float, float]:
    """Calcula prioridade, valor total e perda de um ciclo.

    Percorre as arestas do grafo que correspondem aos pares consecutivos do
    caminho e retorna o nível numérico de prioridade (maior = mais urgente),
    o valor total movimentado e a perda (entrada - saída).

    Complexidade: O(E) no pior caso por ciclo.
    """
    # Monta um mapa de aresta para consulta rápida: (src, dst) -> [arestas]
    edge_map: Dict[Tuple[str, str], List] = {}
    for edge in graph.edges():
        key = (edge.source, edge.target)
        edge_map.setdefault(key, []).append(edge)

    max_priority = 0
    total_value = 0.0
    amounts: List[float] = []

    for i in range(len(path) - 1):
        src, dst = path[i], path[i + 1]
        candidates = edge_map.get((src, dst), [])
        if candidates:
            edge = candidates[0]  # usa a primeira aresta entre o par
            t = (edge.transaction_type or "").upper()
            prio = _TIPO_PRIORIDADE.get(t, 1)
            max_priority = max(max_priority, prio)
            total_value += edge.amount
            amounts.append(edge.amount)

    loss = (amounts[0] - amounts[-1]) if len(amounts) >= 2 else 0.0
    return max_priority, total_value, loss


def find_cycles(graph: Graph) -> List[CycleResult]:
    """Encontra todos os ciclos simples em um grafo direcionado.

    Cada ciclo é retornado como :class:`CycleResult` com caminho, categoria,
    prioridade de risco, valor total e perda calculados.

    Ordenação final (RN06): prioridade desc → valor total desc → intermediários desc.

    Args:
        graph: instância de :class:`Graph` (multigrafo direcionado).

    Returns:
        Lista de :class:`CycleResult` ordenada por prioridade de risco.

    Notas:
        - Grafo vazio devolve lista vazia.
        - Self-loops são incluídos com category="ANOMALIA" (RN05).
    """
    raw_paths: List[List[str]] = []

    # Pré-computa adjacência única (sem multiplicidade) — O(V + E)
    adjacency: Dict[str, Set[str]] = {v: set() for v in graph.vertices()}
    for edge in graph.edges():
        adjacency.setdefault(edge.source, set()).add(edge.target)
        adjacency.setdefault(edge.target, set())

    sorted_vertices = sorted(adjacency.keys())

    for start in sorted_vertices:
        path: List[str] = [start]
        on_path: Set[str] = {start}
        _dfs_cycles(start, start, adjacency, path, on_path, raw_paths)

    # Enriquece cada ciclo com prioridade, valor e categoria
    results: List[CycleResult] = []
    for path in raw_paths:
        # Self-loop: path = [v, v] — RN05
        is_self_loop = len(path) == 2 and path[0] == path[1]
        category = "ANOMALIA" if is_self_loop else "CICLO"

        prio_num, total_value, loss = _cycle_priority(path, graph)
        priority = _PRIORIDADE_LABEL.get(prio_num, "BAIXO")
        intermediaries = max(0, len(path) - 2)

        results.append(CycleResult(
            path=path,
            category=category,
            priority=priority,
            total_value=total_value,
            loss=loss,
            intermediaries=intermediaries,
        ))

    # RN06 — ordenação: prioridade desc → valor total desc → intermediários desc
    results.sort(
        key=lambda r: (
            _TIPO_PRIORIDADE.get(
                next((k for k, v in _PRIORIDADE_LABEL.items() if v == r.priority), 1
            ), 1),
            r.total_value,
            r.intermediaries,
        ),
        reverse=True,
    )

    return results


def _dfs_cycles(
    start: str,
    current: str,
    adjacency: Dict[str, Set[str]],
    path: List[str],
    on_path: Set[str],
    cycles: List[List[str]],
) -> None:
    """DFS recursiva que coleta ciclos simples cujo menor vértice é ``start``.

    Complexidade: O(V + E) por chamada inicial. O conjunto ``on_path``
    evita revisitar vértices do caminho atual — preservando ciclos simples.
    """
    for neighbor in adjacency.get(current, ()):  # O(grau(current))
        if neighbor < start:
            # Unicidade: cada ciclo é descoberto exatamente uma vez,
            # na DFS iniciada pelo seu menor vértice.
            continue
        if neighbor == start:
            cycles.append(path + [start])
        elif neighbor not in on_path:
            path.append(neighbor)            # O(1)
            on_path.add(neighbor)            # O(1)
            _dfs_cycles(start, neighbor, adjacency, path, on_path, cycles)
            path.pop()                       # backtrack — O(1)
            on_path.remove(neighbor)         # backtrack — O(1)


def has_cycle(graph: Graph) -> bool:
    """Detecta a *existência* de ao menos um ciclo direcionado.

    Implementação clássica de DFS com três cores (branco/cinza/preto). Mais
    eficiente que :func:`find_cycles` quando só importa saber se há ciclo.

    Complexidade: tempo O(V + E), espaço O(V).
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {v: WHITE for v in graph.vertices()}

    adjacency: Dict[str, Set[str]] = {v: set() for v in graph.vertices()}
    for edge in graph.edges():
        adjacency.setdefault(edge.source, set()).add(edge.target)
        adjacency.setdefault(edge.target, set())

    for v in adjacency:
        color.setdefault(v, WHITE)

    def visit(u: str) -> bool:
        color[u] = GRAY
        for v in adjacency.get(u, ()):
            if color[v] == GRAY:
                return True
            if color[v] == WHITE and visit(v):
                return True
        color[u] = BLACK
        return False

    for vertex in adjacency:
        if color[vertex] == WHITE and visit(vertex):
            return True
    return False
