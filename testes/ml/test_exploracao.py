"""Testes da exploração de previsões (src/ml/exploracao.py).

Todos os dados aqui são SINTÉTICOS, criados só para os testes: não representam
previsões nem resultados reais do NodeWatch.
"""

from __future__ import annotations

import io
import json
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.ml import exploracao as ex

_PROBS = {"OK": ("0.80", "0.15", "0.05"), "RISCO": ("0.20", "0.70", "0.10"), "FALHA": ("0.10", "0.20", "0.70")}


def csv_rede(n: int = 12, com_alvo: bool = False, sem_opcionais: bool = False) -> str:
    """Previsões de rede sintéticas no formato de `cli prever --tarefa estado_rede`."""
    linhas = []
    for i in range(n):
        classe = ("OK", "RISCO", "FALHA")[i % 3]
        p_ok, p_risco, p_falha = _PROBS[classe]
        score = float(p_risco) + float(p_falha)
        linha = {
            "arquivo_origem": "entrada_teste.csv", "linha_origem": str(i),
            "id_fluxo": f"{100 + i % 4}_200", "anchor_id": "200", "probe_id": str(100 + i % 4),
            "timestamp_previsao": str(1_791_156_000 + 240 * i), "horizonte": "proxima_medicao",
            "classe_prevista": classe, "prob_OK": p_ok, "prob_RISCO": p_risco, "prob_FALHA": p_falha,
            "score_alerta_rede": f"{score:.2f}", "alerta_rede": str(score >= 0.3),
            "limiar_alerta": "0.3", "versao_modelo": "estado_rede-TESTE", "tipo_saida": "previsao",
        }
        if sem_opcionais:
            for k in ("anchor_id", "probe_id", "horizonte", "limiar_alerta", "versao_modelo", "tipo_saida"):
                linha.pop(k)
        if com_alvo:
            linha["alvo"] = ("OK", "RISCO", "FALHA", "OK")[i % 4]
        linhas.append(linha)
    return pd.DataFrame(linhas).to_csv(index=False)


def csv_lavagem(n: int = 10, com_rotulo: bool = False) -> str:
    """Previsões de lavagem sintéticas no formato de `cli prever --tarefa lavagem`."""
    linhas = []
    for i in range(n):
        score = (0.01, 0.2, 0.05, 0.5, 0.0)[i % 5]
        alerta = score >= 0.09
        linha = {
            "arquivo_origem": "entrada_teste_hismall.csv", "linha_origem": str(i), "id_transacao": str(i),
            "timestamp_transacao": f"2022-09-10 {i % 24:02d}:00:00",
            "conta_origem": f"{10 + i % 3}-A{i % 5}", "conta_destino": f"{20 + i % 2}-B{i % 4}",
            "valor_pago": "100.50" if i % 2 else "2500", "moeda_pagamento": ("US Dollar", "Euro")[i % 2],
            "formato": ("ACH", "Wire")[i % 2], "score_lavagem": str(score), "alerta_lavagem": str(alerta),
            "limiar_alerta": "0.09",
            "motivos_verificaveis": "primeira transação entre origem e destino" if alerta else "",
            "historico_incompleto": "False", "sinais_utilizados": "financeiro", "cobertura_vinculo": "sem_vinculo",
            "pontuacao_fraude_financeira": "indisponivel", "versao_modelo": "lavagem-TESTE", "tipo_saida": "previsao",
        }
        if com_rotulo:
            linha["Is Laundering"] = str(int(i % 5 in (1, 3, 4)))
        linhas.append(linha)
    return pd.DataFrame(linhas).to_csv(index=False)


def carregar(texto: str, nome: str = "teste.csv", conjunto=None, dominio=None) -> ex.Previsoes:
    return ex.carregar_previsoes(texto.encode("utf-8"), nome, "teste", "importado",
                                 conjunto or {"tipo": "desconhecido"}, dominio=dominio)


# ---------------------------------------------------------------------------
def test_le_previsoes_de_rede_e_de_lavagem():
    rede = carregar(csv_rede())
    lav = carregar(csv_lavagem())
    assert (rede.dominio, rede.n) == ("rede", 12)
    assert (lav.dominio, lav.n) == ("lavagem", 10)
    assert rede.periodo()["inicio"] < rede.periodo()["fim"]
    assert rede.descricao()["modelo"]["versoes"] == ["estado_rede-TESTE"]
    assert rede.descricao()["modelo"]["limiar"] == pytest.approx(0.3)
    papeis = {c["nome"]: c["papel"] for c in lav.campos()}
    assert papeis["score_lavagem"] == "previsao" and papeis["valor_pago"] == "observado"
    assert papeis["motivos_verificaveis"] == "previsao"


def test_rejeita_esquema_invalido_listando_problemas_e_acao():
    df = pd.read_csv(io.StringIO(csv_rede()), dtype=str, keep_default_na=False)
    df = df.drop(columns=["prob_OK"])
    df.loc[0, "classe_prevista"] = "TALVEZ"
    df.loc[1, "score_alerta_rede"] = "1.7"
    with pytest.raises(ex.ErroContrato) as erro:
        carregar(df.to_csv(index=False))
    texto = " | ".join(erro.value.problemas)
    assert "coluna obrigatória ausente: prob_OK" in texto
    assert "classe_prevista" in texto and "TALVEZ" in texto
    assert "score_alerta_rede" in texto and "fora da faixa" in texto
    assert "cli prever" in erro.value.acao


def test_rejeita_probabilidades_incoerentes_e_arquivo_que_nao_e_previsao():
    df = pd.read_csv(io.StringIO(csv_rede()), dtype=str, keep_default_na=False)
    df.loc[0, "prob_OK"] = "0.50"
    with pytest.raises(ex.ErroContrato, match="diferente de 1"):
        carregar(df.to_csv(index=False))
    entrada = "id_fluxo,timestamp,perda_pct,alvo\n1_2,1791156000,0.0,OK\n"
    with pytest.raises(ex.ErroContrato) as erro:
        carregar(entrada)
    assert "não são previsões" in erro.value.acao
    with pytest.raises(ex.ErroContrato):
        carregar("")
