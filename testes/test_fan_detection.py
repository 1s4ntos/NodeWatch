"""Testes da detecção de fan-out/fan-in e da leitura de ``step``."""

from __future__ import annotations

import pytest

from src.algoritmos.fan_detection import FAN_IN, FAN_OUT, find_fan_patterns
from src.grafo.graph import Graph
from src.leitura.file_reader import load_graph_from_csv


def _grafo_fan_out(destinos: int, passo: int = 1, origem: str = "A") -> Graph:
    g = Graph()
    for i in range(destinos):
        g.add_edge(origem, f"D{i}", amount=100.0, transaction_type="TRANSFER",
                   step=i * passo)
    return g


# ---------------------------------------------------------------------------
# Detecção
# ---------------------------------------------------------------------------
def test_fan_out_basico_e_encontrado() -> None:
    g = _grafo_fan_out(12, passo=2)  # 12 destinos em 22 horas

    res = find_fan_patterns(g, min_counterparts=10, window_steps=48)

    assert len(res) == 1
    r = res[0]
    assert (r.account, r.kind, r.counterparts) == ("A", FAN_OUT, 12)
    assert r.transaction_count == 12
    assert (r.window_start, r.window_end) == (0, 22)
    assert r.total_value == 1200.0


def test_fan_in_basico_e_encontrado() -> None:
    g = Graph()
    for i in range(8):
        g.add_edge(f"S{i}", "HUB", amount=50.0, step=i)

    res = find_fan_patterns(g, min_counterparts=5, window_steps=10)

    assert [(r.account, r.kind, r.counterparts) for r in res] == [("HUB", FAN_IN, 8)]


def test_janela_de_tempo_e_respeitada() -> None:
    # 12 destinos espalhados em 1.100 horas: nenhuma janela de 72h chega a 10
    g = _grafo_fan_out(12, passo=100)

    assert find_fan_patterns(g, min_counterparts=10, window_steps=72) == []
    # com janela ampla o mesmo grafo é detectado
    assert len(find_fan_patterns(g, min_counterparts=10, window_steps=2000)) == 1


def test_destino_repetido_conta_como_uma_contraparte() -> None:
    g = Graph()
    for i in range(30):
        g.add_edge("A", "B", amount=1.0, step=i)  # 30 transações, 1 destino

    assert find_fan_patterns(g, min_counterparts=2, window_steps=100) == []


def test_self_loops_sao_ignorados() -> None:
    g = Graph()
    for i in range(10):
        g.add_edge("A", "A", amount=1.0, step=i)
    g.add_edge("A", "B", amount=1.0, step=0)

    assert find_fan_patterns(g, min_counterparts=2, window_steps=100) == []


def test_filtro_de_hubs_ignora_conta_com_muitas_contrapartes_no_periodo() -> None:
    g = _grafo_fan_out(5, passo=1)               # pico de 5 destinos
    for i in range(5, 60):                       # e muita atividade depois
        g.add_edge("A", f"D{i}", amount=1.0, step=1000 + i * 100)

    com_pico = find_fan_patterns(g, min_counterparts=5, window_steps=10)
    sem_hub = find_fan_patterns(
        g, min_counterparts=5, window_steps=10, max_total_counterparts=20)

    assert [r.account for r in com_pico] == ["A"]
    assert com_pico[0].total_counterparts == 60
    assert sem_hub == []


def test_so_o_tipo_pedido_e_procurado() -> None:
    g = _grafo_fan_out(6)

    assert find_fan_patterns(g, min_counterparts=3, window_steps=10, kinds=[FAN_IN]) == []
    assert len(find_fan_patterns(g, min_counterparts=3, window_steps=10, kinds=[FAN_OUT])) == 1


def test_resultados_ordenados_por_contrapartes() -> None:
    g = _grafo_fan_out(6, origem="P")
    for i in range(9):
        g.add_edge("Q", f"X{i}", amount=1.0, step=i)

    res = find_fan_patterns(g, min_counterparts=5, window_steps=20)

    assert [(r.account, r.counterparts) for r in res] == [("Q", 9), ("P", 6)]


def test_grafo_sem_step_levanta_erro_claro() -> None:
    g = Graph()
    g.add_edge("A", "B", amount=1.0)  # step = None

    with pytest.raises(ValueError, match="step"):
        find_fan_patterns(g)


def test_grafo_vazio_nao_levanta_erro() -> None:
    assert find_fan_patterns(Graph()) == []


@pytest.mark.parametrize("kwargs", [
    {"min_counterparts": 1},
    {"window_steps": -1},
    {"kinds": ["OUTRO"]},
])
def test_parametros_invalidos(kwargs) -> None:
    with pytest.raises(ValueError):
        find_fan_patterns(_grafo_fan_out(3), **kwargs)


# ---------------------------------------------------------------------------
# Leitura de step
# ---------------------------------------------------------------------------
def test_leitor_guarda_step(tmp_path) -> None:
    arq = tmp_path / "t.csv"
    arq.write_text("step,type,amount,nameOrig,nameDest,isFraud\n"
                   "5,TRANSFER,10,A,B,0\n7.0,TRANSFER,20,A,C,1\n")

    g = load_graph_from_csv(arq)

    assert [e.step for e in g.edges()] == [5, 7]


def test_leitor_sem_coluna_step_deixa_none(tmp_path) -> None:
    arq = tmp_path / "t.csv"
    arq.write_text("type,amount,nameOrig,nameDest\nTRANSFER,10,A,B\n")

    assert [e.step for e in load_graph_from_csv(arq).edges()] == [None]


def test_leitor_step_invalido_vira_none(tmp_path) -> None:
    arq = tmp_path / "t.csv"
    arq.write_text("step,type,amount,nameOrig,nameDest\nabc,TRANSFER,10,A,B\n")

    assert [e.step for e in load_graph_from_csv(arq).edges()] == [None]
