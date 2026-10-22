"""Detecção de fan-out e fan-in por janela de tempo.

Padrões procurados:

* **FAN_OUT** — uma conta envia dinheiro para *k* ou mais contas distintas
  dentro de uma janela de tempo curta (dispersão de recursos).
* **FAN_IN**  — uma conta recebe dinheiro de *k* ou mais contas distintas
  dentro de uma janela de tempo curta (concentração de recursos).

Esses padrões não formam ciclos, então não são cobertos por ``cycle_detection``
nem por ``scc``. Dependem do tempo: por isso usam ``Edge.step``.

Complexidade: O(E log E) no total (ordenação das transações de cada conta por
``step``) e O(E) para a varredura com janela deslizante.

Limitação conhecida: contas de altíssimo volume (comércios, folhas de
pagamento) contactam muitas contas distintas de forma legítima. O parâmetro
``max_total_counterparts`` permite ignorá-las, mas o valor adequado precisa ser
medido no dataset (veja ``scripts/benchmark_fan.py``).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from src.grafo.graph import Edge, Graph

FAN_OUT = "FAN_OUT"
FAN_IN = "FAN_IN"
_KINDS = (FAN_OUT, FAN_IN)


@dataclass
class FanResult:
    """Um padrão de fan-out/fan-in encontrado.

    Atributos:
        account:           conta no centro do padrão (origem no FAN_OUT,
                           destino no FAN_IN).
        kind:              ``"FAN_OUT"`` ou ``"FAN_IN"``.
        counterparts:      número de contas distintas na janela escolhida.
        transaction_count: número de transações dentro da janela.
        window_start:      ``step`` da primeira transação da janela.
        window_end:        ``step`` da última transação da janela.
        total_value:       soma dos valores das transações da janela.
        total_counterparts: contas distintas com que a conta interage em todo
                           o período (útil para separar picos de hubs).
        edges:             transações dentro da janela (para rastreio).
    """

    account: str
    kind: str
    counterparts: int
    transaction_count: int
    window_start: int
    window_end: int
    total_value: float
    total_counterparts: int
    edges: List[Edge] = field(default_factory=list, repr=False)


def find_fan_patterns(
    graph: Graph,
    min_counterparts: int = 10,
    window_steps: int = 72,
    max_total_counterparts: Optional[int] = None,
    kinds: Iterable[str] = _KINDS,
) -> List[FanResult]:
    """Encontra contas com fan-out e/ou fan-in concentrado no tempo.

    Args:
        graph: grafo carregado com ``Edge.step`` preenchido.
        min_counterparts: mínimo de contas distintas na janela (*k*).
        window_steps: largura da janela, na mesma unidade de ``step``
            (horas, no PaySim e no CSV convertido da IBM). Duas transações
            estão na mesma janela se ``|step_a - step_b| <= window_steps``.
        max_total_counterparts: se informado, ignora contas que interagem, no
            período todo, com mais contas distintas que esse valor (hubs).
        kinds: quais padrões procurar (``"FAN_OUT"``, ``"FAN_IN"``).

    Returns:
        Lista de :class:`FanResult`, no máximo um por conta e tipo (a janela
        com mais contas distintas; em empate, a mais antiga), ordenada por
        contas distintas decrescente, depois valor total decrescente.

    Raises:
        ValueError: parâmetros inválidos, ou grafo com transações mas sem
            nenhuma informação de ``step``.
    """
    if min_counterparts < 2:
        raise ValueError("min_counterparts deve ser >= 2.")
    if window_steps < 0:
        raise ValueError("window_steps deve ser >= 0.")
    kinds = tuple(kinds)
    for kind in kinds:
        if kind not in _KINDS:
            raise ValueError(f"Tipo desconhecido: {kind!r}. Use {_KINDS}.")

    all_edges = graph.edges()
    if all_edges and all(e.step is None for e in all_edges):
        raise ValueError(
            "O grafo não tem informação de tempo (Edge.step). "
            "Use um CSV com a coluna 'step'."
        )

    results: List[FanResult] = []
    for kind in kinds:
        grouped = _group_edges(all_edges, kind)
        for account, edges in grouped.items():
            total_counterparts = len({_counterpart(e, kind) for e in edges})
            if (
                max_total_counterparts is not None
                and total_counterparts > max_total_counterparts
            ):
                continue
            best = _best_window(edges, kind, window_steps)
            if best is None or best[0] < min_counterparts:
                continue
            distinct, window_edges = best
            results.append(FanResult(
                account=account,
                kind=kind,
                counterparts=distinct,
                transaction_count=len(window_edges),
                window_start=window_edges[0].step,       # type: ignore[arg-type]
                window_end=window_edges[-1].step,        # type: ignore[arg-type]
                total_value=sum(e.amount for e in window_edges),
                total_counterparts=total_counterparts,
                edges=window_edges,
            ))

    results.sort(key=lambda r: (-r.counterparts, -r.total_value, r.kind, r.account))
    return results


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def _counterpart(edge: Edge, kind: str) -> str:
    return edge.target if kind == FAN_OUT else edge.source


def _group_edges(edges: List[Edge], kind: str) -> Dict[str, List[Edge]]:
    """Agrupa transações por conta central, sem self-loops e sem ``step`` nulo."""
    grouped: Dict[str, List[Edge]] = defaultdict(list)
    for e in edges:
        if e.step is None or e.source == e.target:
            continue
        center = e.source if kind == FAN_OUT else e.target
        grouped[center].append(e)
    return grouped


def _best_window(
    edges: List[Edge], kind: str, window_steps: int,
) -> Optional[Tuple[int, List[Edge]]]:
    """Janela deslizante: devolve (contas distintas, transações da janela)."""
    ordered = sorted(edges, key=lambda e: e.step)  # estável: mantém ordem original
    counts: Counter = Counter()
    left = 0
    best_distinct = 0
    best_range: Tuple[int, int] = (0, 0)

    for right, edge in enumerate(ordered):
        counts[_counterpart(edge, kind)] += 1
        while ordered[right].step - ordered[left].step > window_steps:  # type: ignore[operator]
            other = _counterpart(ordered[left], kind)
            counts[other] -= 1
            if counts[other] == 0:
                del counts[other]
            left += 1
        if len(counts) > best_distinct:
            best_distinct = len(counts)
            best_range = (left, right)

    if best_distinct == 0:
        return None
    left, right = best_range
    return best_distinct, ordered[left:right + 1]
