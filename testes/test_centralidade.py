"""Testes unitários — Centralidade de Grau (E4).

Casos cobertos:
  1. Graus básicos — in/out/total corretos para grafo simples.
  2. Volume — volume_in e volume_out somados corretamente.
  3. RN04 — risk_score acumula +15 por ciclo adicional.
  4. Classificação — SUSPEITO para contas em ciclos, DISTRIBUIDOR/COLETOR/NORMAL.
  5. Ordenação — lista retornada ordenada por risk_score desc.
  6. Grafo vazio — retorna lista vazia sem erros.
"""

from __future__ import annotations

from src.algoritmos.centralidade import compute_centrality, AccountCentrality
from src.algoritmos.cycle_detection import find_cycles
from src.grafo.graph import Graph


def _make_cycle_graph() -> Graph:
    """Grafo auxiliar com um ciclo C001→C002→C003→C001."""
    g = Graph()
    g.add_edge("C001", "C002", amount=10000.0, transaction_type="TRANSFER")
    g.add_edge("C002", "C003", amount=10000.0, transaction_type="TRANSFER")
    g.add_edge("C003", "C001", amount=9800.0,  transaction_type="TRANSFER")
    g.add_edge("C004", "C005", amount=200.0,   transaction_type="PAYMENT")
    return g


# ---------------------------------------------------------------------------
# 1. Graus básicos
# ---------------------------------------------------------------------------
def test_graus_basicos() -> None:
    """in_degree, out_degree e degree calculados corretamente."""
    g = Graph()
    g.add_edge("A", "B", amount=100.0, transaction_type="TRANSFER")
    g.add_edge("A", "C", amount=200.0, transaction_type="TRANSFER")
    g.add_edge("B", "A", amount=80.0,  transaction_type="TRANSFER")

    cycles = find_cycles(g)
    accounts = {a.account_id: a for a in compute_centrality(g, cycles)}

    assert accounts["A"].out_degree == 2
    assert accounts["A"].in_degree  == 1
    assert accounts["A"].degree     == 3

    assert accounts["B"].out_degree == 1
    assert accounts["B"].in_degree  == 1
    assert accounts["B"].degree     == 2

    assert accounts["C"].out_degree == 0
    assert accounts["C"].in_degree  == 1
    assert accounts["C"].degree     == 1


# ---------------------------------------------------------------------------
# 2. Volumes
# ---------------------------------------------------------------------------
def test_volumes() -> None:
    """volume_in e volume_out somados corretamente."""
    g = Graph()
    g.add_edge("X", "Y", amount=1000.0, transaction_type="TRANSFER")
    g.add_edge("X", "Y", amount=500.0,  transaction_type="PAYMENT")

    cycles = find_cycles(g)
    accounts = {a.account_id: a for a in compute_centrality(g, cycles)}

    assert accounts["X"].volume_out == 1500.0
    assert accounts["Y"].volume_in  == 1500.0
    assert accounts["X"].volume_in  == 0.0
    assert accounts["Y"].volume_out == 0.0


# ---------------------------------------------------------------------------
# 3. RN04 — risco acumulado por ciclo
# ---------------------------------------------------------------------------
def test_risco_acumulado_por_ciclo() -> None:
    """Conta em 1 ciclo TRANSFER: base=40, +15 por ciclo = 55."""
    g = _make_cycle_graph()
    cycles = find_cycles(g)
    accounts = {a.account_id: a for a in compute_centrality(g, cycles)}

    # C001, C002, C003 estão no ciclo
    for conta in ["C001", "C002", "C003"]:
        assert accounts[conta].cycle_count == 1
        assert accounts[conta].risk_score  == 55  # 40 (TRANSFER) + 15

    # C004 não está em ciclo
    assert accounts["C004"].cycle_count == 0
    assert accounts["C004"].risk_score  == 15  # 15 (PAYMENT), sem ciclo


# ---------------------------------------------------------------------------
# 4. Classificação hub_type
# ---------------------------------------------------------------------------
def test_classificacao_hub_type() -> None:
    """Contas em ciclos → SUSPEITO. Distribuidores e coletores reais."""
    g = _make_cycle_graph()
    cycles = find_cycles(g)
    accounts = {a.account_id: a for a in compute_centrality(g, cycles)}

    # Contas em ciclo → sempre SUSPEITO
    assert accounts["C001"].hub_type == "SUSPEITO"
    assert accounts["C002"].hub_type == "SUSPEITO"
    assert accounts["C003"].hub_type == "SUSPEITO"

    # C004: out=1, in=0 → grau baixo, sem ciclo → NORMAL
    assert accounts["C004"].hub_type == "NORMAL"
    # C005: out=0, in=1 → só recebe → COLETOR
    assert accounts["C005"].hub_type == "COLETOR"

    # Distribuidor real: conta que envia para 3+ destinos sem receber
    g2 = Graph()
    g2.add_edge("HUB", "D1", amount=100.0, transaction_type="TRANSFER")
    g2.add_edge("HUB", "D2", amount=100.0, transaction_type="TRANSFER")
    g2.add_edge("HUB", "D3", amount=100.0, transaction_type="TRANSFER")
    g2.add_edge("SRC", "HUB", amount=300.0, transaction_type="TRANSFER")
    ac2 = {a.account_id: a for a in compute_centrality(g2, find_cycles(g2))}
    # HUB: out=3, in=1 → ratio=3 → DISTRIBUIDOR
    assert ac2["HUB"].hub_type == "DISTRIBUIDOR"


# ---------------------------------------------------------------------------
# 5. Ordenação por risk_score desc
# ---------------------------------------------------------------------------
def test_ordenacao_por_risk_score() -> None:
    """Lista retornada deve estar ordenada por risk_score decrescente."""
    g = _make_cycle_graph()
    cycles = find_cycles(g)
    accounts = compute_centrality(g, cycles)

    scores = [a.risk_score for a in accounts]
    assert scores == sorted(scores, reverse=True), (
        f"Lista fora de ordem: {scores}"
    )


# ---------------------------------------------------------------------------
# 6. Grafo vazio
# ---------------------------------------------------------------------------
def test_grafo_vazio_retorna_lista_vazia() -> None:
    """Grafo sem vértices retorna lista vazia sem erros."""
    g = Graph()
    cycles = find_cycles(g)
    accounts = compute_centrality(g, cycles)
    assert accounts == []
