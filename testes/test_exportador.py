"""Testes unitários — Exportador JSON (E4).

Casos cobertos:
  1. build_analysis_dict() — estrutura obrigatória sempre presente.
  2. Seções opcionais presentes quando incluir_* = True.
  3. Seções ausentes quando incluir_* = False.
  4. save_analysis() — arquivo criado em disco corretamente.
  5. Nomenclatura — nome sanitizado e extensão .json garantida.
  6. Sem sobrescrita — sufixo _2 adicionado quando arquivo já existe.
  7. Estatísticas — valores calculados corretamente.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from src.algoritmos.centralidade import compute_centrality
from src.algoritmos.cycle_detection import find_cycles
from src.algoritmos.scc import find_scc
from src.grafo.graph import Graph
from src.leitura.exportador import (
    _sanitize_name,
    build_analysis_dict,
    save_analysis,
)


def _make_full_graph() -> Graph:
    """Grafo com ciclo, para testes completos."""
    g = Graph()
    g.add_edge("C001", "C002", amount=10000.0, transaction_type="TRANSFER")
    g.add_edge("C002", "C003", amount=10000.0, transaction_type="TRANSFER")
    g.add_edge("C003", "C001", amount=9800.0,  transaction_type="TRANSFER", is_fraud=True)
    g.add_edge("C004", "C005", amount=200.0,   transaction_type="PAYMENT")
    return g


def _run_all(g: Graph):
    cycles   = find_cycles(g)
    accounts = compute_centrality(g, cycles)
    sccs     = find_scc(g)
    return cycles, accounts, sccs


# ---------------------------------------------------------------------------
# 1. Estrutura obrigatória sempre presente
# ---------------------------------------------------------------------------
def test_secoes_obrigatorias_sempre_presentes() -> None:
    g = _make_full_graph()
    cycles, accounts, sccs = _run_all(g)

    data = build_analysis_dict(g, cycles, accounts, sccs,
                               incluir_vertices=False,
                               incluir_arestas=False,
                               incluir_top_contas=False,
                               incluir_distribuicao=False,
                               incluir_scc=False)

    assert "metadata"    in data
    assert "estatisticas" in data
    assert "ciclos"      in data
    assert "vertices"    not in data
    assert "arestas"     not in data


# ---------------------------------------------------------------------------
# 2. Seções opcionais incluídas quando True
# ---------------------------------------------------------------------------
def test_secoes_opcionais_incluidas() -> None:
    g = _make_full_graph()
    cycles, accounts, sccs = _run_all(g)

    data = build_analysis_dict(g, cycles, accounts, sccs)

    assert "vertices"     in data
    assert "arestas"      in data
    assert "top_contas"   in data
    assert "distribuicao" in data
    assert "scc"          in data


# ---------------------------------------------------------------------------
# 3. Seções opcionais ausentes quando False
# ---------------------------------------------------------------------------
def test_secoes_opcionais_ausentes() -> None:
    g = _make_full_graph()
    cycles, accounts, sccs = _run_all(g)

    data = build_analysis_dict(
        g, cycles, accounts, sccs,
        incluir_vertices=False,
        incluir_arestas=False,
        incluir_top_contas=False,
        incluir_distribuicao=False,
        incluir_scc=False,
    )

    assert "vertices"     not in data
    assert "arestas"      not in data
    assert "top_contas"   not in data
    assert "distribuicao" not in data
    assert "scc"          not in data


# ---------------------------------------------------------------------------
# 4. save_analysis() — arquivo criado em disco
# ---------------------------------------------------------------------------
def test_save_analysis_cria_arquivo() -> None:
    g = _make_full_graph()
    cycles, accounts, sccs = _run_all(g)
    data = build_analysis_dict(g, cycles, accounts, sccs)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = save_analysis(data, nome="teste_salvar", output_dir=Path(tmpdir))

        assert path.exists()
        assert path.suffix == ".json"

        with open(path) as f:
            loaded = json.load(f)
        assert "metadata" in loaded
        assert "ciclos"   in loaded


# ---------------------------------------------------------------------------
# 5. Nome sanitizado e extensão garantida
# ---------------------------------------------------------------------------
def test_sanitize_name() -> None:
    assert _sanitize_name("minha analise")    == "minha_analise.json"
    assert _sanitize_name("teste.json")       == "teste.json"
    assert _sanitize_name("análise 2026/05")  == "análise_2026_05.json"
    assert _sanitize_name("  espaços  ")      == "espaços.json"


# ---------------------------------------------------------------------------
# 6. Sem sobrescrita — sufixo _2 adicionado
# ---------------------------------------------------------------------------
def test_sem_sobrescrita() -> None:
    g = _make_full_graph()
    cycles, accounts, sccs = _run_all(g)
    data = build_analysis_dict(g, cycles, accounts, sccs)

    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir)
        path1 = save_analysis(data, nome="duplicado", output_dir=p)
        path2 = save_analysis(data, nome="duplicado", output_dir=p)

        assert path1 != path2
        assert path1.exists()
        assert path2.exists()
        assert "duplicado_2" in path2.name


# ---------------------------------------------------------------------------
# 7. Estatísticas calculadas corretamente
# ---------------------------------------------------------------------------
def test_estatisticas_corretas() -> None:
    g = _make_full_graph()
    cycles, accounts, sccs = _run_all(g)
    data = build_analysis_dict(g, cycles, accounts, sccs)

    stats = data["estatisticas"]
    assert stats["total_vertices"] == 5
    assert stats["total_arestas"]  == 4
    assert stats["total_ciclos"]   == 1
    assert abs(stats["volume_total"] - 30000.0) < 0.01
    assert stats["fraudes_rotuladas"] == 1