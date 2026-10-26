"""Testes do contrato, da ingestão e do modelo de estado de rede."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.ml import experimentos
from src.ml.esquemas import ESQUEMA_REDE_V1, FEATURES_REDE, PROIBIDAS_REDE, ErroEsquema
from src.ml.ingestao import ErroDados, ler_rede, verificar_splits
from src.ml.modelos import ModeloUnificado
from src.ml.preparacao import matriz_rede
from testes.ml.conftest import gerar_rede


# ---------------------------------------------------------------------------
# Preditores e esquema
# ---------------------------------------------------------------------------
def test_preditores_nunca_incluem_alvo_split_ou_ids() -> None:
    df = gerar_rede(n_fluxos=2, por_split=(20, 5, 5))
    X = matriz_rede(df)
    assert list(X.columns) == list(FEATURES_REDE)
    assert not PROIBIDAS_REDE.intersection(X.columns)
    assert "classe_atual" not in X.columns
    X2 = matriz_rede(df, usar_classe_atual=True)
    assert set(X2.columns) - set(FEATURES_REDE) == {"classe_atual_RISCO", "classe_atual_FALHA"}


def test_coluna_ausente_e_rejeitada_sem_preencher_com_zero(tmp_path: Path) -> None:
    df = gerar_rede(n_fluxos=1, por_split=(10, 3, 3)).drop(columns="perda_pct")
    p = tmp_path / "sem_coluna.csv"
    df.to_csv(p, index=False)
    with pytest.raises(ErroEsquema, match="coluna obrigatória ausente: perda_pct"):
        ler_rede([p])
    with pytest.raises(ErroEsquema, match="perda_pct"):
        ler_rede([p], modo="inferencia")


@pytest.mark.parametrize("coluna, valor, trecho", [
    ("perda_pct", "abc", "não numérico"),
    ("razao_rtt_p95", np.nan, "NaN"),
    ("razao_jitter_p95", np.inf, "infinito"),
    ("rtt_ausente", 2, "fora do domínio"),
    ("alvo", "CAOS", "fora do domínio"),
    ("n_rtt_acima_p95_w3", 1.5, "inteiro"),
])
def test_valores_invalidos_sao_rejeitados(coluna, valor, trecho) -> None:
    df = gerar_rede(n_fluxos=1, por_split=(10, 3, 3))
    df[coluna] = df[coluna].astype(object)
    df.loc[0, coluna] = valor
    with pytest.raises(ErroEsquema, match=trecho):
        ESQUEMA_REDE_V1.validar(df)


def test_sentinela_menos_um_e_aceita_e_delta_ttl_negativo_tambem() -> None:
    df = gerar_rede(n_fluxos=1, por_split=(10, 3, 3))
    df.loc[0, "razao_rtt_p95"] = -1
    df.loc[1, "delta_ttl_clip"] = -16
    ESQUEMA_REDE_V1.validar(df)


def test_inferencia_dispensa_alvo_split_e_classe_atual(tmp_path: Path) -> None:
    df = gerar_rede(n_fluxos=2, por_split=(10, 3, 3)).drop(columns=["alvo", "split", "classe_atual"])
    p = tmp_path / "sem_rotulos.csv"
    df.to_csv(p, index=False)
    lido, _ = ler_rede([p], modo="inferencia")
    assert len(lido) == len(df)
    with pytest.raises(ErroEsquema, match="classe_atual"):
        ler_rede([p], modo="inferencia", exigir=["classe_atual"])


# ---------------------------------------------------------------------------
# Vários arquivos
# ---------------------------------------------------------------------------
def test_varios_csvs_registram_origem_e_removem_duplicata_identica(tmp_path: Path) -> None:
    df = gerar_rede(n_fluxos=2, por_split=(10, 3, 3))
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    df.iloc[:20].to_csv(a, index=False)
    df.iloc[15:].to_csv(b, index=False)       # 5 linhas repetidas
    lido, rel = ler_rede([a, b])
    assert rel["duplicatas_removidas"] == 5
    assert len(lido) == len(df)
    assert set(lido["arquivo_origem"]) == {"a.csv", "b.csv"}
    assert {r["caminho"] for r in rel["arquivos"]} == {str(a), str(b)}


def test_rotulo_conflitante_gera_erro_ou_e_excluido(tmp_path: Path) -> None:
    df = gerar_rede(n_fluxos=1, por_split=(10, 3, 3))
    outro = df.iloc[[0]].copy()
    outro["alvo"] = "FALHA" if df.loc[0, "alvo"] != "FALHA" else "OK"
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    df.to_csv(a, index=False)
    outro.to_csv(b, index=False)
    with pytest.raises(ErroDados, match="valores diferentes"):
        ler_rede([a, b])
    lido, rel = ler_rede([a, b], conflitos="excluir")
    assert rel["chaves_conflitantes"] == 1
    assert len(lido) == len(df) - 1


def test_cabecalho_diferente_e_rejeitado(tmp_path: Path) -> None:
    df = gerar_rede(n_fluxos=1, por_split=(10, 3, 3))
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    df.to_csv(a, index=False)
    df[list(reversed(df.columns))].to_csv(b, index=False)
    with pytest.raises(ErroEsquema, match="cabeçalho"):
        ler_rede([a, b])


def test_sobreposicao_temporal_entre_splits_e_detectada() -> None:
    df = gerar_rede(n_fluxos=2, por_split=(10, 3, 3))
    ok = verificar_splits(df)
    assert ok["problemas"] == []
    ruim = df.copy()
    ruim.loc[ruim.index[0], "split"] = "teste"   # primeira medição do treino marcada como teste
    assert verificar_splits(ruim)["problemas"]


# ---------------------------------------------------------------------------
# Treino, persistência e inferência
# ---------------------------------------------------------------------------
@pytest.fixture
def modelo_treinado(cfg_rede: dict) -> dict:
    experimentos.treinar_estado_rede(cfg_rede)
    return cfg_rede


def test_previsao_preserva_ordem_e_identidade_e_dispensa_rotulos(modelo_treinado: dict, tmp_path: Path) -> None:
    cfg = modelo_treinado
    df = gerar_rede().drop(columns=["alvo", "split"])
    entrada = df.sample(frac=1.0, random_state=3).reset_index(drop=True)
    p = tmp_path / "nova.csv"
    entrada.to_csv(p, index=False)
    modelo = ModeloUnificado.carregar(Path(cfg["geral"]["pasta_artefatos"]))
    saida, rel = modelo.prever("estado_rede", [p])
    assert len(saida) == len(entrada)
    assert saida["linha_origem"].tolist() == list(range(len(entrada)))
    assert saida["id_fluxo"].tolist() == entrada["id_fluxo"].tolist()
    assert saida["timestamp_previsao"].tolist() == entrada["timestamp"].tolist()
    probs = saida[["prob_OK", "prob_RISCO", "prob_FALHA"]].to_numpy()
    assert np.allclose(probs.sum(axis=1), 1.0)
    assert np.allclose(saida["score_alerta_rede"], probs[:, 1] + probs[:, 2])
    assert (saida["tipo_saida"] == "previsao").all()
    assert rel["rotulos_presentes"] is False


def test_previsoes_identicas_apos_salvar_e_carregar(modelo_treinado: dict, csv_rede: Path) -> None:
    pasta = Path(modelo_treinado["geral"]["pasta_artefatos"])
    m1 = ModeloUnificado.carregar(pasta)
    s1, _ = m1.prever("estado_rede", [csv_rede])
    m1.salvar(pasta / "copia")
    m2 = ModeloUnificado.carregar(pasta / "copia")
    s2, _ = m2.prever("estado_rede", [csv_rede])
    cols = ["prob_OK", "prob_RISCO", "prob_FALHA", "classe_prevista", "alerta_rede"]
    pd.testing.assert_frame_equal(s1[cols], s2[cols])
    assert (pasta / "metadados_modelo.json").is_file()
    assert (pasta / "esquemas" / "rede_v1.json").is_file()


def test_classe_atual_so_e_exigida_pela_variante_que_a_usa(modelo_treinado: dict, tmp_path: Path) -> None:
    df = gerar_rede(n_fluxos=2, por_split=(10, 3, 3)).drop(columns=["alvo", "split", "classe_atual"])
    p = tmp_path / "sem_classe.csv"
    df.to_csv(p, index=False)
    modelo = ModeloUnificado.carregar(Path(modelo_treinado["geral"]["pasta_artefatos"]))
    saida, _ = modelo.prever("estado_rede", [p])
    assert len(saida) == len(df)
    with pytest.raises(ErroEsquema, match="classe_atual"):
        modelo.prever("estado_rede__com_classe_atual", [p])


def test_avaliacao_final_roda_com_artefato_congelado(modelo_treinado: dict) -> None:
    r = experimentos.avaliar_estado_rede(modelo_treinado)
    teste = r["teste"]
    for chave in ("modelo", "persistencia", "majoritaria"):
        assert 0.0 <= teste[chave]["macro_f1"] <= 1.0
    assert teste["modelo"]["n"] == teste["persistencia"]["n"]
    assert set(r["grupos_ineditos"]) == {"id_fluxo", "anchor_id"}
    assert teste["alertas"]["modelo"]["falsos_alertas"] >= 0
