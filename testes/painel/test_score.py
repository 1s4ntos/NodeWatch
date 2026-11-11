"""Faixas do score nas fronteiras e conversão do score bruto para a escala 0–1000."""

from __future__ import annotations

import numpy as np
import pytest

from src.painel import score as sc


@pytest.mark.parametrize("valor, esperado", [(0, "baixa"), (300, "baixa"), (301, "intermediaria"),
                                             (700, "intermediaria"), (701, "alta"), (1000, "alta")])
def test_faixas_nas_fronteiras(valor, esperado):
    assert sc.faixa(valor) == esperado


@pytest.mark.parametrize("valor", [-1, 1001])
def test_score_fora_da_escala_e_recusado(valor):
    with pytest.raises(ValueError):
        sc.faixa(valor)


def test_faixas_sem_lacunas_nem_sobreposicao():
    cobertos = [s for fx in sc.FAIXAS for s in range(fx["de"], fx["ate"] + 1)]
    assert cobertos == list(range(0, 1001))  # cada inteiro de 0 a 1000 em exatamente uma faixa
    assert [fx["id"] for fx in sc.FAIXAS] == ["baixa", "intermediaria", "alta"]
    assert all(sc.faixa(s) == fx["id"] for fx in sc.FAIXAS for s in (fx["de"], fx["ate"]))


@pytest.mark.parametrize("limiar", [0.0909838927, 0.2, 0.5, 0.9, 0.001])
def test_conversao_ancorada_no_limiar(limiar):
    abaixo = np.nextafter(limiar, 0.0)
    assert sc.converter([0.0, abaixo, limiar, 1.0], limiar).tolist() == [0, 700, 701, 1000]
    rng = np.random.default_rng(7)
    bruto = np.sort(np.concatenate([rng.random(20_000), [0.0, 1.0, limiar, abaixo]]))
    s = sc.converter(bruto, limiar)
    assert s.dtype.kind == "i" and s.min() >= 0 and s.max() <= 1000
    assert np.all(np.diff(s) >= 0), "a conversão precisa ser monótona"
    # alerta do modelo (bruto >= limiar) é exatamente a faixa alta (score >= 701)
    assert np.array_equal(bruto >= limiar, s >= sc.SCORE_ALERTA)


def test_conversao_nao_e_multiplicacao_por_mil():
    # com o limiar real (~0,09), 0,091 já é alerta: multiplicar por 1000 daria 91, na faixa baixa
    assert sc.converter([0.091], 0.0909838927)[0] >= 701
    assert sc.converter([0.05], 0.0909838927)[0] != 50


@pytest.mark.parametrize("limiar", [0.0, 1.0, -0.1, 1.5])
def test_limiar_invalido(limiar):
    with pytest.raises(ValueError):
        sc.converter([0.1], limiar)


@pytest.mark.parametrize("bruto", [[-0.01], [1.01], [float("nan")]])
def test_bruto_invalido(bruto):
    with pytest.raises(ValueError):
        sc.converter(bruto, 0.5)


def test_descricao_da_conversao_e_aviso():
    d = sc.descricao_conversao(0.25)
    assert d["ancoras"] == [{"bruto": 0.0, "score": 0}, {"bruto": 0.25, "score": 701}, {"bruto": 1.0, "score": 1000}]
    assert "não é probabilidade" in d["leitura"]
    assert "não há integração bancária" in sc.AVISO_FAIXAS and "não prova" in sc.AVISO_FAIXAS
