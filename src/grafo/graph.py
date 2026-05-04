"""Multigrafo direcionado ponderado para a modelagem de transações financeiras.

Cada vértice representa uma conta bancária (`nameOrig` / `nameDest` no PaySim)
e cada aresta representa uma transação individual. A estrutura é um *multigrafo*
porque permite múltiplas arestas (transações) entre o mesmo par de contas, o que
é essencial para detectar padrões como *smurfing* (fragmentação de depósitos).

Implementação por **lista de adjacência** (escolha justificada no E1/E2 — mais
eficiente em memória para grafos esparsos como redes financeiras reais).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional


@dataclass(frozen=True)
class Edge:
    """Aresta direcionada e ponderada do grafo de transações.

    Atributos:
        source: conta de origem da transação (vértice de saída).
        target: conta de destino da transação (vértice de entrada).
        amount: valor monetário da transação (peso da aresta).
        transaction_type: tipo PaySim (TRANSFER, PAYMENT, CASH_OUT, ...).
        is_fraud: rótulo auxiliar do dataset (1 se fraude conhecida).
    """

    source: str
    target: str
    amount: float = 0.0
    transaction_type: Optional[str] = None
    is_fraud: bool = False


class Graph:
    """Multigrafo direcionado ponderado em lista de adjacência.

    A lista de adjacência é um dicionário ``{vértice: [Edge, ...]}``. Como é um
    multigrafo, a mesma chave pode conter várias arestas com mesmos endpoints —
    o que é essencial para representar transações repetidas entre contas.
    """

    def __init__(self) -> None:
        # Mapa de vértice -> lista de arestas que partem dele.
        self._adjacency: Dict[str, List[Edge]] = {}

    # ------------------------------------------------------------------
    # Operações básicas
    # ------------------------------------------------------------------
    def add_vertex(self, vertex: str) -> None:
        """Adiciona um vértice se ele ainda não existir. Idempotente."""
        if vertex not in self._adjacency:
            self._adjacency[vertex] = []

    def add_edge(
        self,
        source: str,
        target: str,
        amount: float = 0.0,
        transaction_type: Optional[str] = None,
        is_fraud: bool = False,
    ) -> Edge:
        """Adiciona uma aresta direcionada de ``source`` para ``target``.

        Os vértices são criados automaticamente se ainda não existirem. Como o
        grafo é um multigrafo, aresta paralelas são permitidas e armazenadas
        individualmente.
        """
        self.add_vertex(source)
        self.add_vertex(target)
        edge = Edge(
            source=source,
            target=target,
            amount=amount,
            transaction_type=transaction_type,
            is_fraud=is_fraud,
        )
        self._adjacency[source].append(edge)
        return edge

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    def get_adjacency(self, vertex: str) -> List[Edge]:
        """Devolve a lista de arestas que partem do vértice (cópia defensiva)."""
        return list(self._adjacency.get(vertex, []))

    def neighbors(self, vertex: str) -> List[str]:
        """Lista os vértices alcançáveis diretamente a partir de ``vertex``.

        Em um multigrafo, vizinhos podem se repetir se houver arestas paralelas;
        aqui devolvemos a lista de destinos *com* repetições, preservando a
        semântica do multigrafo. Use ``set(g.neighbors(v))`` para uma versão
        única.
        """
        return [edge.target for edge in self._adjacency.get(vertex, [])]

    def vertices(self) -> List[str]:
        """Lista todos os vértices do grafo (ordem inserção, sem repetição)."""
        return list(self._adjacency.keys())

    def edges(self) -> List[Edge]:
        """Lista todas as arestas do grafo, em ordem de inserção."""
        all_edges: List[Edge] = []
        for adj in self._adjacency.values():
            all_edges.extend(adj)
        return all_edges

    # ------------------------------------------------------------------
    # Métricas auxiliares
    # ------------------------------------------------------------------
    def vertex_count(self) -> int:
        """Número de vértices |V|."""
        return len(self._adjacency)

    def edge_count(self) -> int:
        """Número de arestas |E| (contando arestas paralelas)."""
        return sum(len(adj) for adj in self._adjacency.values())

    def has_vertex(self, vertex: str) -> bool:
        return vertex in self._adjacency

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def add_edges_from(self, iterable: Iterable[Edge]) -> None:
        """Adiciona várias arestas a partir de um iterável de :class:`Edge`."""
        for edge in iterable:
            self.add_edge(
                edge.source,
                edge.target,
                amount=edge.amount,
                transaction_type=edge.transaction_type,
                is_fraud=edge.is_fraud,
            )

    def __iter__(self) -> Iterator[str]:
        return iter(self._adjacency)

    def __contains__(self, vertex: object) -> bool:
        return vertex in self._adjacency

    def __len__(self) -> int:  # pragma: no cover - trivial
        return self.vertex_count()

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"Graph(|V|={self.vertex_count()}, |E|={self.edge_count()})"
