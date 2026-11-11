"""Tipologias de lavagem **registradas no dataset** (arquivo de padrões).

Origem (conferida no código e nos dados): no IBM AML, as tipologias não saem
do modelo. Elas vêm de um arquivo de texto que acompanha as transações
(``HI-Small_Patterns.txt``), escrito pelo simulador, com blocos::

    BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 16-degree Fan-Out
    2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,2848.96,Euro,ACH,1
    END LAUNDERING ATTEMPT - FAN-OUT

Cada linha de um bloco é uma transação daquela tentativa. Aqui o arquivo é
lido com o mesmo formato de ``src.ml.ingestao.ler_padroes`` e cada linha é
casada com a transação do dataset pela chave (minuto, conta de origem, conta
de destino, valor pago em centavos, moeda de pagamento e formato).

Por isso a interface chama a tipologia de **"registrada no dataset"**: é
rótulo, nunca previsão. Um dataset sem arquivo de padrões **não tem**
tipologias (a tela diz isso em vez de mostrar zeros). Uma transação pode
estar em mais de uma tentativa e, portanto, em mais de uma tipologia.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from src.ml.ingestao import RE_FIM_PADRAO, RE_INICIO_PADRAO

TIPOLOGIAS: Tuple[str, ...] = ("BIPARTITE", "CYCLE", "FAN-IN", "FAN-OUT", "GATHER-SCATTER", "RANDOM",
                               "SCATTER-GATHER", "STACK")
NAO_IDENTIFICADO = "padrao_nao_identificado"
SEPARADOR = "|"

DESCRICOES: Dict[str, str] = {
    "BIPARTITE": "um grupo de contas envia para outro grupo de contas",
    "CYCLE": "o dinheiro passa por várias contas e volta à conta inicial",
    "FAN-IN": "várias contas enviam para uma mesma conta",
    "FAN-OUT": "uma conta envia para várias contas",
    "GATHER-SCATTER": "várias contas enviam para uma conta, que depois distribui para várias",
    "RANDOM": "cadeia de transferências sem forma fixa",
    "SCATTER-GATHER": "uma conta distribui para várias, que depois enviam para uma mesma conta",
    "STACK": "duas camadas bipartidas em sequência (grupo → grupo → grupo)",
    NAO_IDENTIFICADO: "transação sem tipologia registrada no dataset",
}


class ErroPadroes(ValueError):
    """Arquivo de padrões ilegível ou sem nenhuma tentativa."""


def normalizar_tipo(texto: str) -> str:
    return re.sub(r"[\s_]+", "-", str(texto).strip().upper())


def ler_arquivo_padroes(caminho: Path) -> pd.DataFrame:
    """Uma linha por transação listada: ``tentativa``, ``tipologia`` e as chaves de casamento."""
    linhas: List[List[Any]] = []
    tentativa, tipo = 0, None
    try:
        with open(caminho, "r", encoding="utf-8-sig") as fh:
            for bruta in fh:
                texto = bruta.strip()
                if not texto:
                    continue
                m = RE_INICIO_PADRAO.match(texto)
                if m:
                    tentativa += 1
                    tipo = normalizar_tipo(m.group(1))
                    continue
                if RE_FIM_PADRAO.match(texto):
                    tipo = None
                    continue
                if tipo is None:
                    continue
                campos = [c.strip() for c in texto.split(",")]
                if len(campos) < 10:
                    continue
                linhas.append([tentativa, tipo] + campos[:10])
    except UnicodeDecodeError:
        raise ErroPadroes("o arquivo de padrões não está em UTF-8") from None
    if tentativa == 0:
        raise ErroPadroes("nenhum bloco 'BEGIN LAUNDERING ATTEMPT - <TIPO>' encontrado no arquivo de padrões")
    df = pd.DataFrame(linhas, columns=["tentativa", "tipologia", "ts", "banco_o", "conta_o", "banco_d", "conta_d",
                                       "valor_rec", "moeda_rec", "valor_pag", "moeda_pag", "formato"])
    if df.empty:
        return df.assign(minuto=pd.Series(dtype=np.int64), chave=pd.Series(dtype=object))
    t = pd.to_datetime(df["ts"], format="%Y/%m/%d %H:%M", errors="coerce", utc=True)
    bo, bd = pd.to_numeric(df["banco_o"], errors="coerce"), pd.to_numeric(df["banco_d"], errors="coerce")
    valor = pd.to_numeric(df["valor_pag"], errors="coerce")
    ok = t.notna() & bo.notna() & bd.notna() & valor.notna()
    df, t, bo, bd, valor = df[ok], t[ok], bo[ok], bd[ok], valor[ok]
    minuto = ((t - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(minutes=1)).astype(np.int64)
    df = df.assign(minuto=minuto.to_numpy())
    df["chave"] = _chave(minuto.to_numpy(), bo.astype(np.int64).astype(str) + "-" + df["conta_o"],
                         bd.astype(np.int64).astype(str) + "-" + df["conta_d"], valor.to_numpy(),
                         df["moeda_pag"], df["formato"])
    return df.reset_index(drop=True)


def _chave(minuto, no_o, no_d, valor, moeda, formato) -> np.ndarray:
    cent = np.round(np.asarray(valor, dtype=np.float64) * 100).astype(np.int64)
    partes = [pd.Series(np.asarray(minuto)).astype(str), pd.Series(np.asarray(no_o, dtype=object)).astype(str),
              pd.Series(np.asarray(no_d, dtype=object)).astype(str), pd.Series(cent).astype(str),
              pd.Series(np.asarray(moeda, dtype=object)).astype(str),
              pd.Series(np.asarray(formato, dtype=object)).astype(str)]
    saida = partes[0]
    for p in partes[1:]:
        saida = saida + "\x1f" + p
    return saida.to_numpy(dtype=object)


def resumo_arquivo(padroes: pd.DataFrame) -> Dict[str, Any]:
    por_tipo = padroes.groupby("tipologia")["tentativa"].nunique() if len(padroes) else pd.Series(dtype=int)
    return {"tentativas": int(padroes["tentativa"].nunique()) if len(padroes) else 0,
            "transacoes_listadas": int(len(padroes)),
            "tentativas_por_tipologia": {str(k): int(v) for k, v in por_tipo.items()},
            "tipologias_fora_das_8": sorted(set(por_tipo.index) - set(TIPOLOGIAS))}


def casar(padroes: pd.DataFrame, trans: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """Associa as linhas do arquivo de padrões às transações (já em ordem cronológica).

    ``trans`` precisa de ``minuto``, ``no_origem``, ``no_destino``, ``valor_pago``,
    ``moeda_pagamento`` e ``formato``. Devolve, alinhados a ``trans``:
    ``tipologias`` (texto ``A|B`` ou vazio) e ``tentativas`` (texto ``3|17`` ou vazio).

    Regra para transações idênticas: dentro de uma tentativa, a j-ésima linha
    com a mesma chave casa com a j-ésima transação com aquela chave (a última,
    se faltar). Linhas sem transação correspondente são contadas e ignoradas.
    """
    n = len(trans)
    tipos: List[set] = [set() for _ in range(n)]
    tents: List[set] = [set() for _ in range(n)]
    info = {"transacoes_listadas": int(len(padroes)), "casadas": 0, "sem_correspondencia": 0}
    if n and len(padroes):
        candidatas = np.flatnonzero(trans["minuto"].isin(pd.unique(padroes["minuto"])).to_numpy())
        sub = trans.iloc[candidatas]
        chave_t = _chave(sub["minuto"].to_numpy(), sub["no_origem"].to_numpy(dtype=object),
                         sub["no_destino"].to_numpy(dtype=object), sub["valor_pago"].to_numpy(),
                         sub["moeda_pagamento"].to_numpy(dtype=object), sub["formato"].to_numpy(dtype=object))
        interessa = set(padroes["chave"])
        posicoes: Dict[str, List[int]] = {}
        for k in np.flatnonzero(pd.Series(chave_t).isin(interessa).to_numpy()):
            posicoes.setdefault(chave_t[k], []).append(int(candidatas[k]))
        ordem = padroes.groupby(["tentativa", "chave"]).cumcount().to_numpy()
        for chave, tipo, tent, j in zip(padroes["chave"], padroes["tipologia"], padroes["tentativa"], ordem):
            alvo = posicoes.get(chave)
            if not alvo:
                info["sem_correspondencia"] += 1
                continue
            i = alvo[min(int(j), len(alvo) - 1)]
            tipos[i].add(tipo)
            tents[i].add(int(tent))
            info["casadas"] += 1
    saida_t = np.array([SEPARADOR.join(sorted(s)) for s in tipos], dtype=object)
    saida_n = np.array([SEPARADOR.join(str(x) for x in sorted(s)) for s in tents], dtype=object)
    info["transacoes_com_tipologia"] = int((saida_t != "").sum())
    info["transacoes_com_mais_de_uma"] = int(sum(1 for s in tipos if len(s) > 1))
    return saida_t, saida_n, info
