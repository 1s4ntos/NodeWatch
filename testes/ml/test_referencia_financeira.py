"""Motor vetorizado de atributos × referência por força bruta, e ajustes da auditoria de 02/11/2026."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.ml.preparacao import PreparadorFinanceiro, atributos_financeiros
from testes.ml.referencia_financeira import atributos_referencia, colunas_divergentes

MOEDAS = ["Euro", "US Dollar", "Yen"]
FORMATOS = ["ACH", "Cheque", "Wire"]
CAMBIO = {"US Dollar": 1.0, "Euro": 1.1}  # Yen sem taxa: exercita sem_taxa_cambio


def _prep() -> PreparadorFinanceiro:
    return PreparadorFinanceiro(CAMBIO, {}, FORMATOS, MOEDAS, {}, float("nan"))


def _trans(linhas) -> pd.DataFrame:
    df = pd.DataFrame(linhas, columns=["minuto", "conta_origem", "conta_destino", "valor_pago", "moeda_pagamento"])
    df["moeda_recebimento"] = df["moeda_pagamento"]
    df["banco_origem"] = df["conta_origem"] % 3
    df["banco_destino"] = df["conta_destino"] % 3
    df["formato"] = "ACH"
    df["minuto"] += 27_000_000
    return df


def test_casos_de_fronteira_com_resultado_conhecido() -> None:
    t = _trans([
        (100, 1, 2, 10.0, "US Dollar"),
        (100, 1, 3, 20.0, "US Dollar"),   # mesmo minuto da anterior: não se enxergam
        (460, 1, 2, 30.0, "US Dollar"),   # exatamente 6 h depois: o minuto 100 entra na janela de 6 h
        (460, 2, 1, 5.0, "Euro"),
        (461, 1, 1, 7.0, "Yen"),          # auto-transferência, moeda sem taxa
    ])
    X = atributos_financeiros(t, np.arange(len(t)), _prep())
    assert X.loc[1, "n_env_origem_total"] == 0 and X.loc[1, "par_novo"] == 1
    assert X.loc[2, "n_env_origem_6h"] == 2 and X.loc[2, "n_par_previas"] == 1
    assert X.loc[2, "dest_distintos_origem"] == 2 and X.loc[2, "min_desde_env_origem"] == 360
    assert X.loc[2, "n_rec_origem_24h"] == 0 and X.loc[2, "sem_historico_rec_origem"] == 1
    assert X.loc[4, "n_env_origem_6h"] == 1 and X.loc[4, "n_env_origem_24h"] == 3
    assert X.loc[4, "n_rec_origem_24h"] == 1 and X.loc[4, "min_desde_rec_origem"] == 1
    assert X.loc[4, "sem_taxa_cambio"] == 1 and math.isnan(X.loc[4, "log_valor_usd"])


@pytest.mark.parametrize("semente", [0, 1, 2])
def test_motor_vetorizado_igual_a_forca_bruta(semente: int) -> None:
    rng = np.random.default_rng(semente)
    n = 400
    t = _trans(list(zip(np.sort(rng.integers(0, 6000, n)), rng.integers(0, 25, n), rng.integers(0, 25, n),
                        np.round(rng.lognormal(6, 2, n), 2), rng.choice(MOEDAS, n))))
    t["formato"] = rng.choice(FORMATOS, n)
    t["moeda_recebimento"] = np.where(rng.random(n) < 0.1, "Euro", t["moeda_pagamento"])
    t = t.sample(frac=1.0, random_state=semente).reset_index(drop=True)  # a ordem do arquivo não importa
    obtido = atributos_financeiros(t, np.arange(n), _prep())
    ref = atributos_referencia(t, range(n), CAMBIO, FORMATOS, MOEDAS)
    assert set(obtido.columns) == set(ref.columns)
    assert colunas_divergentes(obtido, ref) == {}
