"""Contrato e adaptadores da integração rede ↔ transações.

Hoje não existe vínculo verificável entre as fontes. Este módulo deixa pronto
o caminho para quando existir:

1. adaptar as transações ao esquema proposto ``transacao_v1``;
2. ligar cada transação a fluxos de rede por uma tabela ``vinculo_v1``
   (nunca pela proximidade de horários);
3. anexar, por ``merge_asof`` para trás, a última previsão de rede emitida
   até o instante em que a transação fica disponível, dentro da tolerância.

Uma previsão emitida em ``t`` pode ser usada em ``t``; a medição observada
depois de ``t`` não. Previsões de um modelo de rede treinado com dados
posteriores à transação são descartadas (ficam fora da amostra no tempo).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from src.ml.esquemas import ESQUEMA_VINCULO_V1, ErroEsquema
from src.ml.ingestao import DadosHISmall

COBERTURA = ("sem_vinculo", "vinculo_sem_sinal_recente", "com_sinal", "com_sinal_ambiguo")


def _utc(s: pd.Series) -> pd.Series:
    s = pd.to_datetime(s, utc=True)
    return s


def adaptar_hismall(dados: DadosHISmall) -> pd.DataFrame:
    """HI-Small → ``transacao_v1`` (proposto).

    ``Is Laundering`` vira ``rotulo_lavagem``: é verdade sintética de lavagem,
    não ``rotulo_fraude``, e não tem data de confirmação. O fuso dos dados não
    é documentado; assume-se UTC e ``timestamp_disponivel = timestamp_transacao``.
    """
    t = dados.trans
    ts = pd.to_datetime(t["minuto"].to_numpy(), unit="m", utc=True)
    saida = pd.DataFrame({
        "id_transacao": t["id_transacao"].astype(str).to_numpy(),
        "timestamp_transacao": ts,
        "timestamp_disponivel": ts,
        "conta_origem": dados.nomes_contas[t["conta_origem"].to_numpy()],
        "conta_destino": dados.nomes_contas[t["conta_destino"].to_numpy()],
        "valor": t["valor_pago"].to_numpy(),
        "moeda": t["moeda_pagamento"].astype(str).to_numpy(),
        "formato_pagamento": t["formato"].astype(str).to_numpy(),
    })
    if "rotulo" in t:
        saida["rotulo_lavagem"] = t["rotulo"].to_numpy()
        saida["origem_rotulo"] = "simulador IBM AMLworld (HI-Small)"
    return saida


def adaptar_csv_nodewatch(df: pd.DataFrame, inicio: str, unidade_step: str = "h") -> pd.DataFrame:
    """CSV do NodeWatch (``step,type,amount,nameOrig,nameDest,isFraud``) → ``transacao_v1``.

    ``step`` é relativo (no conversor da IBM: horas desde a primeira linha); o
    instante absoluto depende de ``inicio``. O conversor descarta a moeda, por
    isso ``moeda`` fica ausente e valores de moedas diferentes não são
    comparáveis.
    """
    faltam = [c for c in ("step", "amount", "nameOrig", "nameDest") if c not in df]
    if faltam:
        raise ErroEsquema("csv_nodewatch", [f"colunas ausentes: {faltam}"])
    ts = pd.Timestamp(inicio, tz="UTC") + pd.to_timedelta(pd.to_numeric(df["step"]), unit=unidade_step)
    saida = pd.DataFrame({
        "id_transacao": np.arange(len(df)).astype(str),
        "timestamp_transacao": ts,
        "timestamp_disponivel": ts,
        "conta_origem": df["nameOrig"].astype(str).to_numpy(),
        "conta_destino": df["nameDest"].astype(str).to_numpy(),
        "valor": pd.to_numeric(df["amount"]).to_numpy(),
        "moeda": pd.Series([None] * len(df), dtype="object"),
        "formato_pagamento": df["type"].astype(str).to_numpy() if "type" in df else None,
    })
    if "isFraud" in df:
        saida["rotulo_origem_nodewatch"] = pd.to_numeric(df["isFraud"]).to_numpy()
    return saida


def associar_sinais_rede(
    transacoes: pd.DataFrame,
    vinculo: Optional[pd.DataFrame],
    previsoes_rede: Optional[pd.DataFrame],
    tolerancia_s: float = 480,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Anexa a cada transação o último sinal de rede disponível nos fluxos vinculados.

    Args:
        transacoes: ``id_transacao``, ``timestamp_disponivel`` e, se o vínculo
            usar chave técnica, ``chave_tecnica``.
        vinculo: tabela ``vinculo_v1``.
        previsoes_rede: saída de ``prever --tarefa estado_rede`` com
            ``id_fluxo``, ``timestamp_previsao`` (época, s), ``score_alerta_rede``
            e, de preferência, ``modelo_rede_treinado_ate`` (UTC).
        tolerancia_s: idade máxima do sinal.

    Returns:
        ``(sinais, relatorio)``: uma linha por transação, na ordem de entrada,
        com ``cobertura_vinculo`` em :data:`COBERTURA`.
    """
    tx = transacoes[["id_transacao", "timestamp_disponivel"]
                    + (["chave_tecnica"] if "chave_tecnica" in transacoes else [])].copy()
    tx["id_transacao"] = tx["id_transacao"].astype(str)
    tx["_t"] = _utc(tx["timestamp_disponivel"])
    base = tx[["id_transacao"]].copy()
    relatorio: Dict[str, Any] = {"transacoes": int(len(tx)), "tolerancia_s": float(tolerancia_s)}

    if vinculo is None or vinculo.empty:
        base["n_fluxos_vinculados"] = 0
        base["n_fluxos_com_sinal"] = 0
        base["score_alerta_rede_max"] = np.nan
        base["idade_sinal_s_min"] = np.nan
        base["cobertura_vinculo"] = "sem_vinculo"
        relatorio["cobertura"] = {"sem_vinculo": int(len(base))}
        relatorio["aviso"] = "Sem tabela de vínculo: nenhum sinal de rede foi associado."
        return base, relatorio

    ESQUEMA_VINCULO_V1.validar(vinculo)
    v = vinculo.copy()
    v["chave"] = v["chave"].astype(str)
    v["valido_de"] = _utc(v["valido_de"])
    v["valido_ate"] = _utc(v["valido_ate"])
    pares = [tx.merge(v[v["tipo_chave"] == "id_transacao"], left_on="id_transacao", right_on="chave")]
    por_chave = v[v["tipo_chave"] == "chave_tecnica"]
    if len(por_chave):
        if "chave_tecnica" not in tx:
            raise ErroEsquema("transacao_v1", ["vínculo por chave_tecnica, mas a coluna não existe"])
        tx["chave_tecnica"] = tx["chave_tecnica"].astype(str)
        pares.append(tx.merge(por_chave, left_on="chave_tecnica", right_on="chave"))
    p = pd.concat(pares, ignore_index=True)
    validos = (p["valido_de"] <= p["_t"]) & (p["_t"] < p["valido_ate"])
    relatorio["vinculos_fora_da_validade"] = int((~validos).sum())
    p = p.loc[validos, ["id_transacao", "_t", "id_fluxo"]].drop_duplicates()
    p["id_fluxo"] = p["id_fluxo"].astype(str)

    sinais = pd.DataFrame(columns=["id_transacao", "id_fluxo", "score_alerta_rede", "idade_s"])
    if previsoes_rede is not None and not previsoes_rede.empty and len(p):
        pr = previsoes_rede[["id_fluxo", "timestamp_previsao", "score_alerta_rede"]
                            + (["modelo_rede_treinado_ate"] if "modelo_rede_treinado_ate" in previsoes_rede else [])].copy()
        pr["id_fluxo"] = pr["id_fluxo"].astype(str)
        pr["_tp"] = pd.to_datetime(pr["timestamp_previsao"], unit="s", utc=True)
        pr = pr.sort_values("_tp")
        p = p.sort_values("_t")
        junto = pd.merge_asof(p, pr, left_on="_t", right_on="_tp", by="id_fluxo",
                              direction="backward", allow_exact_matches=True,
                              tolerance=pd.Timedelta(seconds=tolerancia_s))
        futuro = pd.Series(False, index=junto.index)
        if "modelo_rede_treinado_ate" in junto:
            futuro = _utc(junto["modelo_rede_treinado_ate"]) > junto["_t"]
            junto.loc[futuro, "score_alerta_rede"] = np.nan
        relatorio["sinais_descartados_modelo_treinado_depois"] = int(futuro.sum())
        junto["idade_s"] = (junto["_t"] - junto["_tp"]).dt.total_seconds()
        sinais = junto[["id_transacao", "id_fluxo", "score_alerta_rede", "idade_s"]]

    agg = p.groupby("id_transacao").agg(n_fluxos_vinculados=("id_fluxo", "nunique"))
    if len(sinais):
        com = sinais.dropna(subset=["score_alerta_rede"]).groupby("id_transacao").agg(
            n_fluxos_com_sinal=("id_fluxo", "nunique"),
            score_alerta_rede_max=("score_alerta_rede", "max"),
            idade_sinal_s_min=("idade_s", "min"),
        )
        agg = agg.join(com, how="left")
    saida = base.merge(agg, left_on="id_transacao", right_index=True, how="left")
    saida["n_fluxos_vinculados"] = saida["n_fluxos_vinculados"].fillna(0).astype(int)
    if "n_fluxos_com_sinal" not in saida:
        saida["n_fluxos_com_sinal"] = 0
        saida["score_alerta_rede_max"] = np.nan
        saida["idade_sinal_s_min"] = np.nan
    saida["n_fluxos_com_sinal"] = saida["n_fluxos_com_sinal"].fillna(0).astype(int)
    saida["cobertura_vinculo"] = np.select(
        [saida["n_fluxos_vinculados"] == 0, saida["n_fluxos_com_sinal"] == 0,
         saida["n_fluxos_vinculados"] > 1],
        ["sem_vinculo", "vinculo_sem_sinal_recente", "com_sinal_ambiguo"],
        default="com_sinal",
    )
    relatorio["cobertura"] = {k: int(v) for k, v in saida["cobertura_vinculo"].value_counts().items()}
    return saida.reset_index(drop=True), relatorio
