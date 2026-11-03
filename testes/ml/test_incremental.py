"""Motor financeiro incremental: equivalência com o lote e regras de tempo.

Todos os dados são SINTÉTICOS (``conftest.gerar_transacoes``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.ml import preparacao
from src.ml.incremental import EstadoFinanceiro
from src.ml.preparacao import PreparadorFinanceiro, atributos_financeiros
from testes.ml.conftest import gerar_transacoes, nomes_contas, transacoes_normalizadas
from testes.ml.referencia_financeira import atributos_referencia, colunas_divergentes

NOMES = nomes_contas(80)


@pytest.fixture(scope="module")
def dados():
    trans = gerar_transacoes(4_000, 80, semente=1)
    prep = PreparadorFinanceiro.ajustar(trans)
    lote = atributos_financeiros(trans, np.arange(len(trans)), prep)
    prep.colunas = list(lote.columns)
    return trans, prep, lote


def _processar(estado: EstadoFinanceiro, txs, fechar_cada: int = 0) -> pd.DataFrame:
    partes = []
    for i, tx in enumerate(txs, start=1):
        assert estado.receber(tx) is None
        if fechar_cada and i % fechar_cada == 0:
            partes += estado.fechar_ate(estado.max_visto)
    partes += estado.fechar_ate(None)
    return _juntar(partes)


def _juntar(partes) -> pd.DataFrame:
    df = pd.concat([p.X.assign(_id=[int(t["id_transacao"]) for t in p.transacoes]) for p in partes])
    return df.set_index("_id").sort_index()


def test_incremental_do_zero_igual_ao_lote(dados) -> None:
    trans, prep, lote = dados
    inc = _processar(EstadoFinanceiro(prep), transacoes_normalizadas(trans, NOMES))
    assert list(inc.columns) == list(lote.columns)
    pd.testing.assert_frame_equal(inc, lote.set_axis(trans["id_transacao"].to_numpy()), check_names=False,
                                  check_index_type=False, rtol=1e-6, atol=1e-6)


def test_carga_inicial_mais_incremental_igual_ao_lote_com_historico(dados) -> None:
    trans, prep, lote = dados
    corte = int(trans["minuto"].iloc[2_500])
    hist, resto = trans[trans["minuto"] < corte], trans[trans["minuto"] >= corte]
    estado = EstadoFinanceiro(prep)
    info = estado.carregar_historico(hist.reset_index(drop=True), NOMES, "sintético")
    assert info["transacoes"] == len(hist) and estado.ultimo_fechado == int(hist["minuto"].max())
    inc = _processar(estado, transacoes_normalizadas(resto, NOMES))
    esperado = lote.loc[resto.index].set_axis(resto["id_transacao"].to_numpy())
    pd.testing.assert_frame_equal(inc, esperado, check_names=False, check_index_type=False, rtol=1e-6, atol=1e-6)


def test_incremental_confere_com_forca_bruta_inclusive_razao(dados) -> None:
    trans, prep, _ = dados
    inc = _processar(EstadoFinanceiro(prep), transacoes_normalizadas(trans, NOMES))
    amostra = np.linspace(0, len(trans) - 1, 300).astype(int)
    ref = atributos_referencia(trans, amostra, prep.cambio, prep.formatos, prep.moedas)
    obtido = inc.loc[trans["id_transacao"].to_numpy()[amostra]].reset_index(drop=True)
    assert colunas_divergentes(obtido[ref.columns], ref) == {}


def _tx(ident: str, minuto: int, origem: str = "1-A", destino: str = "2-B", valor: float = 100.0) -> dict:
    t = float(minuto * 60)
    return {"id_transacao": ident, "epoca": t, "minuto": minuto, "timestamp_disponivel": t,
            "banco_origem": origem.split("-")[0], "banco_destino": destino.split("-")[0],
            "conta_origem": origem, "conta_destino": destino, "valor_pago": valor, "valor_recebido": valor,
            "moeda_pagamento": "US Dollar", "moeda_recebimento": "US Dollar", "formato": "ACH"}


def test_bordas_das_janelas_e_mesmo_minuto(dados) -> None:
    """Janela [t - w, t): o evento em t - w conta; em t - w - 1 não; o do mesmo minuto não."""
    _, prep, _ = dados
    base = 28_000_000
    t = base + 24 * 60 + 1
    estado = EstadoFinanceiro(prep)
    eventos = [_tx("velho", base), _tx("borda", base + 1), _tx("perto", t - 1),
               _tx("mesmo_a", t), _tx("mesmo_b", t, valor=7.0)]
    res = {}
    for e in eventos:
        estado.receber(e)
    for p in estado.fechar_ate(None):
        for tx, (_, linha) in zip(p.transacoes, p.X.iterrows()):
            res[tx["id_transacao"]] = linha
    assert res["mesmo_a"]["n_env_origem_24h"] == 2          # "borda" (t - 24h) e "perto"; "velho" ficou fora
    assert res["mesmo_a"]["n_env_origem_72h"] == 3
    assert res["mesmo_a"]["soma_env_origem_usd_24h"] == pytest.approx(200.0)
    assert res["mesmo_b"]["n_env_origem_24h"] == 2          # não enxerga "mesmo_a"
    assert res["mesmo_a"]["n_par_previas"] == 3 and res["mesmo_a"]["par_novo"] == 0
    assert res["velho"]["par_novo"] == 1 and res["velho"]["sem_historico_env_origem"] == 1


def test_tamanho_dos_lotes_nao_muda_o_resultado(dados) -> None:
    trans, prep, _ = dados
    txs = transacoes_normalizadas(trans, NOMES)
    a = _processar(EstadoFinanceiro(prep), txs, fechar_cada=0)
    b = _processar(EstadoFinanceiro(prep), txs, fechar_cada=1)
    c = _processar(EstadoFinanceiro(prep), txs, fechar_cada=97)
    pd.testing.assert_frame_equal(a, b)
    pd.testing.assert_frame_equal(a, c)


def test_instantaneo_restaurado_continua_igual(dados, tmp_path: Path) -> None:
    trans, prep, _ = dados
    txs = transacoes_normalizadas(trans, NOMES)
    inteiro = _processar(EstadoFinanceiro(prep), txs)
    estado = EstadoFinanceiro(prep)
    meio = len(txs) // 2
    partes = []
    for tx in txs[:meio]:
        estado.receber(tx)
    partes += estado.fechar_ate(estado.max_visto)  # o último minuto fica aberto no instantâneo
    assert estado.aberto
    estado.salvar(tmp_path / "estado.pkl")
    restaurado, meta = EstadoFinanceiro.carregar(tmp_path / "estado.pkl", prep)
    assert meta["ultimo_minuto_fechado"] == estado.ultimo_fechado
    for tx in txs[meio:]:
        assert restaurado.receber(tx) is None
    partes += restaurado.fechar_ate(None)
    pd.testing.assert_frame_equal(_juntar(partes), inteiro)


def test_instantaneo_de_outro_preparador_e_recusado(dados, tmp_path: Path) -> None:
    trans, prep, _ = dados
    estado = EstadoFinanceiro(prep)
    estado.salvar(tmp_path / "e.pkl")
    outro = PreparadorFinanceiro.ajustar(trans.iloc[:500])
    with pytest.raises(ValueError, match="outro preparador"):
        EstadoFinanceiro.carregar(tmp_path / "e.pkl", outro)


def test_duplicadas_e_atrasadas_nao_entram_no_estado(dados) -> None:
    _, prep, _ = dados
    estado = EstadoFinanceiro(prep)
    assert estado.receber(_tx("a", 100)) is None
    assert estado.receber(_tx("a", 100)).motivo == "duplicada"   # ainda no minuto aberto
    assert estado.receber(_tx("b", 101)) is None
    estado.fechar_ate(101)
    assert estado.receber(_tx("a", 102)).motivo == "duplicada"   # minuto já fechado, id conhecido
    r = estado.receber(_tx("c", 100))
    assert r.motivo == "atrasada"
    assert estado.transacoes_incorporadas == 1
    estado.fechar_ate(None)
    assert estado.transacoes_incorporadas == 2
    assert estado.a["env_tot"][estado.indice["1-A"]] == 2


def test_carga_inicial_so_com_estado_vazio(dados) -> None:
    trans, prep, _ = dados
    estado = EstadoFinanceiro(prep)
    estado.receber(_tx("x", 50))
    with pytest.raises(RuntimeError):
        estado.carregar_historico(trans, NOMES)


def test_nao_reconstroi_o_historico_por_transacao(dados, monkeypatch) -> None:
    """O caminho incremental não usa o cálculo em lote nem reindexa o histórico."""
    trans, prep, _ = dados
    corte = int(trans["minuto"].iloc[3_000])
    estado = EstadoFinanceiro(prep)
    estado.carregar_historico(trans[trans["minuto"] < corte].reset_index(drop=True), NOMES)

    def proibido(*a, **k):
        raise AssertionError("reconstrução do histórico no caminho incremental")

    monkeypatch.setattr(preparacao, "atributos_financeiros", proibido)
    monkeypatch.setattr(preparacao._IndiceEventos, "__init__", proibido)
    _processar(estado, transacoes_normalizadas(trans[trans["minuto"] >= corte], NOMES))
    # o registro das janelas guarda só as últimas 72 h, não o histórico inteiro
    assert trans["minuto"].max() - trans["minuto"].min() > 72 * 60
    reg = estado.env
    ativos = reg.m[min(reg.cursor.values()):reg.n]
    assert ativos.min() >= estado.ultimo_fechado - 72 * 60
    assert reg.ativos() < len(trans)
