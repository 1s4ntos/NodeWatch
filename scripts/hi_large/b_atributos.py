"""Atributos point-in-time do HI-Large (dias 1 a 12) com o ``EstadoFinanceiro``.

Usa o mesmo caminho de *Analisar dataset* (``src/ml/analises.py``): cada
transação vira um evento, o estado fecha um minuto de cada vez, e as
transações de um minuto são pontuadas contra o estado anterior a ele. O estado
começa vazio no dia 1 às 00:00 (como o treino do HI-Small, que começa no dia 1).

``--preparador S`` usa o preparador do artefato atual (câmbio, categorias e
colunas do HI-Small), sem alteração. ``--preparador L`` ajusta um preparador
novo só com o treino do HI-Large (dias 1 a 6), pelo mesmo método do NodeWatch.

Treino (dias 1 a 6): grava todos os positivos e 20% dos negativos (semente
fixa por dia, igual nas duas passadas), com peso 5 nos negativos. Validação,
teste e reserva (dias 7 a 12): grava tudo.

Uso::

    python scripts/hi_large/b_atributos.py --preparador S
    python scripts/hi_large/b_atributos.py --preparador L
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List

import joblib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import comum
from src.ml.incremental import EstadoFinanceiro
from src.ml.modelos import ModeloUnificado
from src.ml.preparacao import PreparadorFinanceiro

PARTICOES = comum.TRABALHO / "particoes"
DIAS_TREINO = range(0, 6)
PARTICAO = {**{d: "treino" for d in range(0, 6)}, 6: "validacao", 7: "validacao", 8: "teste", 9: "teste",
            10: "reserva", 11: "reserva", **{d: "teste_final2" for d in range(12, 16)},  # dias 13 a 16: Emenda 2
            **{d: "teste_final3" for d in range(16, 23)}}  # dias 17 a 23: Emenda 3
FRACAO_NEG = 0.2
BLOCO = 20_000


def ler_dia(dia: int, colunas=None) -> pd.DataFrame:
    tab = pq.read_table(PARTICOES / f"dia={dia:03d}.parquet", columns=colunas,
                        read_dictionary=[c for c in ("moeda_pagamento", "moeda_recebimento", "formato")
                                         if colunas is None or c in colunas])
    df = tab.to_pandas()
    return df.sort_values(["minuto", "linha"], kind="stable").reset_index(drop=True) if "linha" in df else df


def ajustar_preparador_L() -> PreparadorFinanceiro:
    cols = ["moeda_pagamento", "moeda_recebimento", "valor_pago", "valor_recebido", "formato", "rotulo"]
    partes = [pq.read_table(PARTICOES / f"dia={d:03d}.parquet", columns=cols,
                            read_dictionary=["moeda_pagamento", "moeda_recebimento", "formato"]).to_pandas()
              for d in DIAS_TREINO]
    treino = pd.concat(partes, ignore_index=True)
    for c in ("moeda_pagamento", "moeda_recebimento", "formato"):
        treino[c] = treino[c].astype(str).astype("category")
    prep = PreparadorFinanceiro.ajustar(treino)
    prep.info_cambio["n_treino"] = int(len(treino))
    return prep


def comparar_preparadores(ps: PreparadorFinanceiro, pl: PreparadorFinanceiro) -> Dict[str, Any]:
    moedas = sorted(set(ps.cambio) | set(pl.cambio))
    dif = {m: (abs(pl.cambio[m] / ps.cambio[m] - 1) if m in ps.cambio and m in pl.cambio else None) for m in moedas}
    validas = [v for v in dif.values() if v is not None]
    return {
        "cambio_S": ps.cambio, "cambio_L": pl.cambio, "diferenca_relativa": dif,
        "maior_diferenca_relativa": max(validas) if validas else None,
        "moedas_so_em_S": sorted(set(ps.cambio) - set(pl.cambio)),
        "moedas_so_em_L": sorted(set(pl.cambio) - set(ps.cambio)),
        "formatos_iguais": ps.formatos == pl.formatos, "formatos_S": ps.formatos, "formatos_L": pl.formatos,
        "moedas_iguais": ps.moedas == pl.moedas, "moedas_S": ps.moedas, "moedas_L": pl.moedas,
        "taxa_formato_S": ps.taxa_formato, "taxa_formato_L": pl.taxa_formato,
        "taxa_base_S": ps.taxa_base, "taxa_base_L": pl.taxa_base,
    }


def processar_dia(estado: EstadoFinanceiro, df: pd.DataFrame, manter: np.ndarray, dia: int,
                  particao: str, lote_saida: int = 250_000) -> Iterator[pa.Table]:
    """Passa as transações de um dia (ordenadas por minuto e linha) pelo estado.

    Mesmo laço de ``src/ml/analises.py``: blocos que terminam na virada do
    minuto, ``receber`` por transação e ``fechar_ate(None)`` no fim do bloco.
    Devolve tabelas com os 49 atributos e os metadados (``_*``) das linhas em
    ``manter``.
    """
    prep = estado.prep
    minutos = df["minuto"].to_numpy()
    linhas, rotulos = df["linha"].to_numpy(), df["rotulo"].to_numpy()
    formatos = df["formato"].astype(str).to_numpy()
    acum: List[pd.DataFrame] = []
    n_acum, cursor, n = 0, 0, len(df)
    while cursor < n:
        fim = min(cursor + BLOCO, n)
        while fim < n and minutos[fim] == minutos[fim - 1]:
            fim += 1
        for pos, r in zip(range(cursor, fim), df.iloc[cursor:fim].itertuples(index=False)):
            t = float(r.minuto * 60)
            rej = estado.receber({
                "id_transacao": str(r.linha), "epoca": t, "minuto": int(r.minuto), "timestamp_disponivel": t,
                "banco_origem": str(r.banco_origem), "banco_destino": str(r.banco_destino),
                "conta_origem": f"{r.banco_origem}-{r.conta_origem}",
                "conta_destino": f"{r.banco_destino}-{r.conta_destino}",
                "valor_pago": float(r.valor_pago), "valor_recebido": float(r.valor_recebido),
                "moeda_pagamento": str(r.moeda_pagamento), "moeda_recebimento": str(r.moeda_recebimento),
                "formato": str(r.formato), "_pos": pos})
            if rej is not None:
                raise RuntimeError(f"transação recusada pelo estado: {rej}")
        fechados = estado.fechar_ate(None)
        if not prep.colunas and fechados:
            prep.colunas = list(fechados[0].X.columns)
        for mf in fechados:
            pos = np.array([tx["_pos"] for tx in mf.transacoes])
            sel = manter[pos]
            if not sel.any():
                continue
            X = mf.X.loc[sel].reset_index(drop=True)
            p = pos[sel]
            X["_linha"] = linhas[p]
            X["_minuto"] = minutos[p]
            X["_dia"] = np.int16(dia)
            X["_rotulo"] = rotulos[p].astype(np.int8)
            X["_formato"] = formatos[p]
            X["_conta_origem"] = np.array([estado.indice[tx["conta_origem"]] for tx in mf.transacoes],
                                          dtype=np.int32)[sel]
            X["_historico_incompleto"] = mf.historico_incompleto[sel]
            neg_treino = (particao == "treino") & (X["_rotulo"].to_numpy() == 0)
            X["_peso"] = np.where(neg_treino, np.float32(1 / FRACAO_NEG), np.float32(1.0)).astype(np.float32)
            acum.append(X)
            n_acum += len(X)
        cursor = fim
        if acum and (n_acum >= lote_saida or cursor >= n):
            yield pa.Table.from_pandas(pd.concat(acum, ignore_index=True), preserve_index=False)
            acum, n_acum = [], 0


def amostra_treino(rotulo: np.ndarray, dia: int, particao: str) -> np.ndarray:
    """Todos os positivos e uma fração fixa dos negativos no treino (semente por dia); tudo nos demais."""
    if particao != "treino":
        return np.ones(len(rotulo), dtype=bool)
    u = np.random.default_rng([comum.SEMENTE, dia]).random(len(rotulo))
    return (rotulo == 1) | (u < FRACAO_NEG)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preparador", choices=("S", "L"), required=True)
    ap.add_argument("--dias", type=int, default=12)
    ap.add_argument("--gravar-a-partir", type=int, default=0,
                    help="só grava os dias a partir deste índice (o estado passa por todos desde o dia 1)")
    ap.add_argument("--sufixo", default="", help="pasta de saída atributos_<preparador>_<sufixo> (Emenda 2: final2; Emenda 3: final3)")
    ap.add_argument("--so-ajustar", action="store_true",
                    help="com --preparador L: só ajusta e compara o preparador, sem calcular atributos")
    a = ap.parse_args()
    saida: Dict[str, Any] = {"gerado_em_utc": comum.agora(), "script": Path(__file__).name,
                             "preparador": a.preparador, "ambiente": comum.ambiente(), "por_dia": {}}
    modelo = ModeloUnificado.carregar(comum.RAIZ / "artefatos_ml")
    ps: PreparadorFinanceiro = modelo.codificadores["financeiro"]
    saida["artefato"] = modelo.cabeca("lavagem").metadados.get("versao")
    if a.preparador == "S":
        prep = ps
    elif a.sufixo:
        # Passada nova (Emenda 2): usa o preparador L já ajustado e salvo (com os quantis), sem reajustar.
        prep = joblib.load(comum.TRABALHO / "preparador_L.joblib")
        saida["preparador_L_reaproveitado"] = True
    else:
        t0 = time.perf_counter()
        prep = ajustar_preparador_L()
        prep.colunas = list(ps.colunas) if (prep.formatos == ps.formatos and prep.moedas == ps.moedas) else []
        saida["ajuste_preparador_s"] = round(time.perf_counter() - t0, 1)
        saida["comparacao_preparadores"] = comparar_preparadores(ps, prep)
        if a.so_ajustar:
            joblib.dump(prep, comum.TRABALHO / "preparador_L.joblib")
            print(comum.salvar_json(saida, "b_preparador_L.json"))
            return
    destino = comum.TRABALHO / (f"atributos_{a.preparador}" + (f"_{a.sufixo}" if a.sufixo else ""))
    destino.mkdir(parents=True, exist_ok=True)
    for antigo in destino.glob("dia=*.parquet"):
        antigo.unlink()
    estado = EstadoFinanceiro(prep)
    t_total = time.perf_counter()
    for dia in range(a.dias):
        t0 = time.perf_counter()
        df = ler_dia(dia)
        t_leitura = time.perf_counter() - t0
        particao = PARTICAO[dia]
        manter = amostra_treino(df["rotulo"].to_numpy(), dia, particao)
        if dia < a.gravar_a_partir:
            manter = np.zeros(len(df), dtype=bool)  # o estado avança, mas nada é gravado
        escritor = None
        t1 = time.perf_counter()
        for tab in processar_dia(estado, df, manter, dia, particao):
            if escritor is None:
                escritor = pq.ParquetWriter(destino / f"dia={dia:03d}.parquet", tab.schema, compression="zstd")
            escritor.write_table(tab)
        t_estado = time.perf_counter() - t1
        n = len(df)
        if escritor is not None:
            escritor.close()
        cob = estado.cobertura()
        saida["por_dia"][str(dia)] = {
            "particao": particao, "transacoes": int(n), "gravadas": int(manter.sum()),
            "positivos": int(df["rotulo"].sum()), "leitura_s": round(t_leitura, 1),
            "estado_e_atributos_s": round(t_estado, 1), "transacoes_por_s": round(n / max(t_estado, 1e-9)),
            "contas": cob["contas"], "pares": cob["pares"], "eventos_nas_janelas": cob["eventos_nas_janelas"],
            "pico_memoria_mb": comum.memoria_processo_mb()}
        comum.log(f"dia {dia + 1}: {n:,} transações em {t_estado:.0f} s; contas {cob['contas']:,}; "
                  f"pares {cob['pares']:,}; pico {comum.memoria_processo_mb()} MB")
        del df
    saida["total_s"] = round(time.perf_counter() - t_total, 1)
    saida["colunas"] = list(prep.colunas)
    if a.preparador == "L" and not a.sufixo:
        joblib.dump(prep, comum.TRABALHO / "preparador_L.joblib")
    nome = f"b_atributos_{a.preparador}" + (f"_{a.sufixo}" if a.sufixo else "")
    print(comum.salvar_json(saida, f"{nome}.json"))


if __name__ == "__main__":
    main()
