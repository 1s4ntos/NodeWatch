"""Testes dos atributos financeiros point-in-time, da leitura do HI-Small e dos padrões."""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.ml.esquemas import ErroEsquema
from src.ml.ingestao import casar_padroes, ler_hismall, ler_padroes
from src.ml.preparacao import (
    PreparadorFinanceiro,
    amostrar_treino_financeiro,
    atributos_financeiros,
    estimar_cambio,
)
from testes.ml.conftest import gerar_transacoes

_CSV_HISMALL = """Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,Amount Paid,Payment Currency,Payment Format,Is Laundering
2022/09/01 00:20,010,8000EBD30,010,8000EBD30,3195403.00,US Dollar,3195403.00,US Dollar,Reinvestment,0
2022/09/01 00:20,03208,8000F4580,001,8000F5340,0.01,US Dollar,0.01,US Dollar,Cheque,0
2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,2848.96,Euro,ACH,1
2022/09/02 10:00,012,80011F990,010,8000EBD30,100.00,Euro,110.00,US Dollar,ACH,1
"""

_PADROES = """BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 16-degree Fan-Out
2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,2848.96,Euro,ACH,1
END LAUNDERING ATTEMPT - FAN-OUT

BEGIN LAUNDERING ATTEMPT - CYCLE:  Max 4 hops
2022/09/02 10:00,012,80011F990,010,8000EBD30,100.00,Euro,110.00,US Dollar,ACH,1
END LAUNDERING ATTEMPT - CYCLE
"""


def _prep(trans: pd.DataFrame) -> PreparadorFinanceiro:
    return PreparadorFinanceiro.ajustar(trans)


def test_atributos_nao_mudam_com_transacoes_futuras() -> None:
    t = gerar_transacoes()
    prep = _prep(t)
    corte = 2_000
    prefixo = t.iloc[:corte].reset_index(drop=True)
    consulta = np.arange(corte)
    a = atributos_financeiros(prefixo, consulta, prep)
    b = atributos_financeiros(t, consulta, prep)
    pd.testing.assert_frame_equal(a, b)


def test_transacoes_do_mesmo_minuto_nao_se_enxergam() -> None:
    t = gerar_transacoes()
    prep = _prep(t)
    alvo = 1_500
    base = atributos_financeiros(t, np.array([alvo]), prep)
    # Mais transações da mesma origem para o mesmo destino, no mesmo minuto.
    extra = pd.concat([t.iloc[[alvo]]] * 5, ignore_index=True)
    extra["id_transacao"] = np.arange(len(t), len(t) + 5)
    t2 = pd.concat([t, extra], ignore_index=True)
    depois = atributos_financeiros(t2, np.array([alvo]), prep)
    pd.testing.assert_frame_equal(base, depois)


def test_contagens_usam_somente_o_passado() -> None:
    t = gerar_transacoes(n=6, n_contas=3)
    t["minuto"] = np.array([0, 10, 20, 20, 30, 2000], dtype=np.int64) + 27_000_000
    t["conta_origem"] = np.array([0, 0, 0, 0, 0, 0], dtype=np.int32)
    t["conta_destino"] = np.array([1, 2, 1, 2, 1, 1], dtype=np.int32)
    X = atributos_financeiros(t, np.arange(6), _prep(t))
    assert X["n_env_origem_total"].tolist() == [0, 1, 2, 2, 4, 5]
    assert X["n_env_origem_24h"].tolist() == [0, 1, 2, 2, 4, 0]   # a última fica 1970 min depois
    assert X["par_novo"].tolist() == [1, 1, 0, 0, 0, 0]
    assert X["dest_distintos_origem"].tolist() == [0, 1, 2, 2, 2, 2]
    assert X["sem_historico_env_origem"].tolist() == [1, 0, 0, 0, 0, 0]


def test_cambio_recupera_taxas_conhecidas() -> None:
    t = gerar_transacoes(n=5_000)
    taxa, info = estimar_cambio(t)
    assert taxa["US Dollar"] == 1.0
    assert taxa["Euro"] == pytest.approx(1.1, rel=1e-6)
    assert taxa["Yen"] == pytest.approx(0.007, rel=1e-6)
    assert info["moedas_sem_taxa"] == []


def test_amostragem_mantem_positivos_e_compensa_negativos() -> None:
    y = np.array([0] * 1000 + [1] * 10)
    idx, w = amostrar_treino_financeiro(y, 0.2, semente=1)
    assert (y[idx] == 1).sum() == 10
    assert (y[idx] == 0).sum() == 200
    assert np.allclose(w[y[idx] == 0], 5.0) and np.allclose(w[y[idx] == 1], 1.0)


def test_leitura_hismall_csv_e_zip_com_cabecalho_duplicado(tmp_path: Path) -> None:
    csv = tmp_path / "HI-Small_Trans.csv"
    csv.write_text(_CSV_HISMALL, encoding="utf-8")
    z = tmp_path / "HI-Small_Trans.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(csv, "HI-Small_Trans.csv")
    for caminho in (csv, z):
        d = ler_hismall(caminho)
        assert len(d.trans) == 4
        assert d.trans["rotulo"].tolist() == [0, 0, 1, 1]
        assert d.nomes_contas[d.trans.loc[1, "conta_origem"]] == "3208-8000F4580"
        # a mesma conta como origem e destino recebe o mesmo código
        assert d.trans.loc[0, "conta_origem"] == d.trans.loc[0, "conta_destino"]
        assert d.trans.loc[2, "conta_destino"] == d.trans.loc[3, "conta_origem"]


def test_leitura_hismall_rejeita_cabecalho_errado(tmp_path: Path) -> None:
    p = tmp_path / "ruim.csv"
    p.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ErroEsquema, match="cabeçalho"):
        ler_hismall(p)


def test_padroes_sao_lidos_e_casados_mas_nao_viram_atributo(tmp_path: Path) -> None:
    csv = tmp_path / "t.csv"
    csv.write_text(_CSV_HISMALL, encoding="utf-8")
    pad = tmp_path / "p.txt"
    pad.write_text(_PADROES, encoding="utf-8")
    dados = ler_hismall(csv)
    padroes = ler_padroes(pad)
    assert padroes["tipo_padrao"].tolist() == ["FAN-OUT", "CYCLE"]
    casados = casar_padroes(dados, padroes)
    assert sorted(casados["id_transacao"].astype(int).tolist()) == [2, 3]
    prep = PreparadorFinanceiro.ajustar(dados.trans)
    X = atributos_financeiros(dados.trans, np.arange(4), prep)
    assert not [c for c in X.columns if "padrao" in c or "tentativa" in c or "rotulo" in c]
