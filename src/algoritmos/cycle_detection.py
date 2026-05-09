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
"""

from __future__ import annotations

from typing import Dict, List, Set

from src.grafo.graph import Graph


def find_cycles(graph: Graph) -> List[List[str]]:
    """Encontra todos os ciclos simples em um grafo direcionado.

    Cada ciclo é retornado como uma lista de vértices ``[v0, v1, ..., vk, v0]``
    em que ``v0 == vk[-1]`` (o primeiro vértice se repete no fim para evidenciar
    o fechamento do ciclo).

    Args:
        graph: instância de :class:`Graph` (multigrafo direcionado).

    Returns:
        Lista de ciclos. Cada ciclo é representado pela rotação canônica em
        que o **menor** vértice (em ordem lexicográfica) aparece em primeiro
        lugar, garantindo que o mesmo ciclo não seja reportado duas vezes.

    Notas:
        - Grafo vazio devolve lista vazia.
        - Self-loops (aresta de um vértice para si mesmo) também são ciclos.
    """
    cycles: List[List[str]] = []

    # Pré-computa adjacência única (sem multiplicidade) — basta saber se há
    # ao menos uma aresta entre dois vértices para que exista ciclo simples.
    # Custo: O(V + E)
    adjacency: Dict[str, Set[str]] = {v: set() for v in graph.vertices()}
    for edge in graph.edges():
        adjacency.setdefault(edge.source, set()).add(edge.target)
        # Garante que o destino exista mesmo se nunca for fonte de aresta.
        adjacency.setdefault(edge.target, set())

    # Ordem fixa para reprodutibilidade e para o critério "menor vértice".
    sorted_vertices = sorted(adjacency.keys())

    for start in sorted_vertices:
        # Para garantir unicidade, só consideramos ciclos cujo menor vértice
        # seja exatamente `start`. Vizinhos menores que `start` são ignorados.
        path: List[str] = [start]
        on_path: Set[str] = {start}
        _dfs_cycles(start, start, adjacency, path, on_path, cycles)

    return cycles


def _dfs_cycles(
    start: str,
    current: str,
    adjacency: Dict[str, Set[str]],
    path: List[str],
    on_path: Set[str],
    cycles: List[List[str]],
) -> None:
    """DFS recursiva que coleta ciclos simples cujo menor vértice é ``start``.

    A travessia em si é O(V + E) no pior caso por chamada inicial, e o uso de
    ``on_path`` evita revisitar vértices do caminho corrente — preservando a
    propriedade de ciclo simples.
    """
    for neighbor in adjacency.get(current, ()):  # O(grau(current))
        if neighbor < start:
            # Garantia de unicidade: cada ciclo é descoberto exatamente uma
            # vez, na DFS iniciada a partir do seu menor vértice.
            continue
        if neighbor == start:
            # Fechou ciclo de volta à raiz da DFS — registra rotação canônica.
            cycles.append(path + [start])
        elif neighbor not in on_path:
            path.append(neighbor)            # O(1)
            on_path.add(neighbor)            # O(1)
            _dfs_cycles(start, neighbor, adjacency, path, on_path, cycles)
            path.pop()                       # backtrack — O(1)
            on_path.remove(neighbor)         # backtrack — O(1)


def has_cycle(graph: Graph) -> bool:
    """Detecta a *existência* de ao menos um ciclo direcionado.

    Implementação clássica de DFS com três cores (branco/cinza/preto). É mais
    barata que :func:`find_cycles` quando só queremos saber se há fluxo
    circular, sem enumerar todos.

    Complexidade: tempo O(V + E), espaço O(V).
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {v: WHITE for v in graph.vertices()}

    # Construção do mapa de adjacência única — O(V + E)
    adjacency: Dict[str, Set[str]] = {v: set() for v in graph.vertices()}
    for edge in graph.edges():
        adjacency.setdefault(edge.source, set()).add(edge.target)
        adjacency.setdefault(edge.target, set())

    # Garantir que todos os vértices estejam no mapa de cores.
    for v in adjacency:
        color.setdefault(v, WHITE)

    def visit(u: str) -> bool:
        color[u] = GRAY
        for v in adjacency.get(u, ()):
            if color[v] == GRAY:
                return True  # back edge -> ciclo
            if color[v] == WHITE and visit(v):
                return True
        color[u] = BLACK
        return False

    for vertex in adjacency:
        if color[vertex] == WHITE and visit(vertex):
            return True
    return False
