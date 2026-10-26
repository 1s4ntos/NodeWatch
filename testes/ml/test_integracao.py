"""Testes da fusão bloqueada e do adaptador temporal rede ↔ transação."""

from __future__ import annotations

import pandas as pd
import pytest

from src.ml.integracao import adaptar_csv_nodewatch, associar_sinais_rede
from src.ml.modelos import CabecaFusao, FusaoIndisponivel, ModeloUnificado


def _tx():
    return pd.DataFrame({
        "id_transacao": ["t1", "t2"],
        "timestamp_disponivel": pd.to_datetime([1_000, 5_000], unit="s", utc=True),
    })


def _vinculo():
    return pd.DataFrame({
        "chave": ["t1"], "tipo_chave": ["id_transacao"], "id_fluxo": ["100_10"],
        "valido_de": pd.to_datetime([0], unit="s", utc=True),
        "valido_ate": pd.to_datetime([10_000], unit="s", utc=True),
        "fonte_vinculo": ["tabela de sessões (exemplo)"],
    })


def _previsoes(**extra):
    df = pd.DataFrame({
        "id_fluxo": ["100_10", "100_10"],
        "timestamp_previsao": [900, 1_100],
        "score_alerta_rede": [0.2, 0.9],
    })
    for k, v in extra.items():
        df[k] = v
    return df


def test_fusao_fica_indisponivel_e_lista_pendencias() -> None:
    modelo = ModeloUnificado()
    assert modelo.tarefas_disponiveis()["fusao_rede_transacao"] == "indisponivel"
    with pytest.raises(FusaoIndisponivel) as exc:
        modelo.cabecas["fusao_rede_transacao"].treinar()
    assert len(exc.value.faltando) == len(CabecaFusao().requisitos)
    with pytest.raises(FusaoIndisponivel):
        modelo.prever("fusao_rede_transacao")


def test_sem_vinculo_nenhum_sinal_e_associado() -> None:
    sinais, rel = associar_sinais_rede(_tx(), None, _previsoes())
    assert (sinais["cobertura_vinculo"] == "sem_vinculo").all()
    assert sinais["score_alerta_rede_max"].isna().all()


def test_asof_usa_so_sinal_ja_emitido() -> None:
    sinais, rel = associar_sinais_rede(_tx(), _vinculo(), _previsoes(), tolerancia_s=480)
    t1 = sinais.set_index("id_transacao").loc["t1"]
    assert t1["score_alerta_rede_max"] == pytest.approx(0.2)   # não o 0.9 emitido depois
    assert t1["idade_sinal_s_min"] == pytest.approx(100)
    assert t1["cobertura_vinculo"] == "com_sinal"
    assert sinais.set_index("id_transacao").loc["t2", "cobertura_vinculo"] == "sem_vinculo"
    assert sinais["id_transacao"].tolist() == ["t1", "t2"]      # ordem de entrada


def test_tolerancia_e_modelo_treinado_depois_descartam_sinal() -> None:
    sinais, _ = associar_sinais_rede(_tx(), _vinculo(), _previsoes(), tolerancia_s=50)
    assert sinais.set_index("id_transacao").loc["t1", "cobertura_vinculo"] == "vinculo_sem_sinal_recente"
    futuro = _previsoes(modelo_rede_treinado_ate=pd.Timestamp(2_000, unit="s", tz="UTC"))
    sinais, rel = associar_sinais_rede(_tx(), _vinculo(), futuro, tolerancia_s=480)
    assert rel["sinais_descartados_modelo_treinado_depois"] == 1
    assert sinais.set_index("id_transacao").loc["t1", "cobertura_vinculo"] == "vinculo_sem_sinal_recente"


def test_adaptador_csv_nodewatch_marca_moeda_ausente() -> None:
    df = pd.DataFrame({"step": [0, 2], "type": ["TRANSFER", "CASH_OUT"], "amount": [10.0, 20.0],
                       "nameOrig": ["A", "B"], "nameDest": ["B", "C"], "isFraud": [0, 1]})
    t = adaptar_csv_nodewatch(df, inicio="2022-09-01")
    assert t["moeda"].isna().all()
    assert (t["timestamp_transacao"].diff().dropna() == pd.Timedelta(hours=2)).all()
