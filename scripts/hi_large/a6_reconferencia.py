"""Reconferência independente das partições e das associações, relendo as partições.

Não usa os conjuntos guardados pela primeira passada (``positivos.parquet``,
``padroes_casados.parquet`` nem as contas acumuladas em memória):

* tabela por partição (arquivo, bytes, linhas, positivos, primeiro e último minuto),
  com checagem de dia repetido, de sobreposição e da soma de linhas;
* contas: todas as chaves ``banco-conta`` das partições contra o cadastro;
* padrões: as linhas de ``HI-Large_Patterns.txt`` contra os positivos lidos agora.

Grava ``a6_reconferencia.json`` e a tabela ``docs/ml/hi_large/PARTICOES.md``.

Uso::

    python scripts/hi_large/a6_reconferencia.py --dados <pasta do HI-Large>
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

import comum
from src.ml.ingestao import ler_padroes

PARTICOES = comum.TRABALHO / "particoes"
DIA0 = pd.Timestamp("2022-08-01")
MIN_DIA0 = int((DIA0 - pd.Timestamp("1970-01-01")) // pd.Timedelta(minutes=1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dados")
    ap.add_argument("--prefixo", default="HI-Large")
    a = ap.parse_args()
    pasta = comum.pasta_dados(a.dados)
    nomes = comum.nomes_arquivos(a.prefixo)
    perfil = comum.ler_json("a_perfil.json")
    linhas: List[Dict[str, Any]] = []
    contas: set = set()
    positivos: List[pd.DataFrame] = []
    for arq in sorted(PARTICOES.glob("dia=*.parquet")):
        d = int(arq.stem.split("=")[1])
        t = pq.read_table(arq)
        m = t["minuto"].to_numpy()
        y = t["rotulo"].to_numpy()
        for b, c in (("banco_origem", "conta_origem"), ("banco_destino", "conta_destino")):
            k = pc.binary_join_element_wise(pc.cast(t[b], pa.string()), t[c], "-")
            contas.update(pc.unique(k).to_pylist())
        pos = t.filter(pc.equal(t["rotulo"], 1)).select(
            ["linha", "minuto", "banco_origem", "conta_origem", "banco_destino", "conta_destino", "valor_pago", "formato"]).to_pandas()
        positivos.append(pos)
        linhas.append({"indice": d, "data": str((DIA0 + pd.Timedelta(days=d)).date()), "arquivo": arq.name,
                       "bytes": arq.stat().st_size, "linhas": int(t.num_rows), "positivos": int(y.sum()),
                       "dia_do_primeiro_minuto": int((m.min() - MIN_DIA0) // 1440),
                       "dia_do_ultimo_minuto": int((m.max() - MIN_DIA0) // 1440)})
        del t
    tab = pd.DataFrame(linhas)
    mediana = float(tab["linhas"].median())
    tab["periodo"] = np.where(tab["linhas"] < 0.01 * mediana, "cauda", "principal")
    saida: Dict[str, Any] = {"gerado_em_utc": comum.agora(), "script": Path(__file__).name}
    saida["particoes"] = {
        "arquivos": int(len(tab)), "dias_distintos": int(tab["indice"].nunique()),
        "arquivos_com_dia_repetido": int(tab["indice"].duplicated().sum()),
        "arquivos_com_minutos_de_outro_dia": int(((tab["dia_do_primeiro_minuto"] != tab["indice"])
                                                  | (tab["dia_do_ultimo_minuto"] != tab["indice"])).sum()),
        "dias_sem_arquivo_entre_o_primeiro_e_o_ultimo": int(tab["indice"].max() - tab["indice"].min() + 1 - len(tab)),
        "linhas_somadas": int(tab["linhas"].sum()), "linhas_no_perfil": perfil["transacoes"]["linhas"],
        "positivos_somados": int(tab["positivos"].sum()),
        "principal": {"dias": int((tab["periodo"] == "principal").sum()),
                      "linhas": int(tab.loc[tab["periodo"] == "principal", "linhas"].sum())},
        "cauda": {"dias": int((tab["periodo"] == "cauda").sum()),
                  "linhas": int(tab.loc[tab["periodo"] == "cauda", "linhas"].sum())},
        "mediana_linhas_por_dia": mediana,
    }
    # Contas
    cad = pd.read_csv(pasta / nomes["contas"], dtype=str, usecols=["Bank ID", "Account Number"])
    chaves_cad = set(cad["Bank ID"].astype("int64").astype(str) + "-" + cad["Account Number"].str.strip())
    saida["contas"] = {"chaves_nas_transacoes": len(contas), "chaves_no_cadastro": len(chaves_cad),
                       "chaves_repetidas_no_cadastro": int(len(cad) - len(chaves_cad)),
                       "transacoes_sem_cadastro": len(contas - chaves_cad),
                       "cadastradas_sem_transacao": len(chaves_cad - contas)}
    del contas, chaves_cad, cad
    # Padrões
    pos = pd.concat(positivos, ignore_index=True)
    pp = ler_padroes(pasta / nomes["padroes"])
    pp["valor_cent"] = np.round(pp["valor_pago"].to_numpy() * 100).astype(np.int64)
    pp["formato"] = pp["Payment Format"].astype(str)
    pos["conta_origem_txt"] = pos["banco_origem"].astype(str) + "-" + pos["conta_origem"]
    pos["conta_destino_txt"] = pos["banco_destino"].astype(str) + "-" + pos["conta_destino"]
    pos["valor_cent"] = np.round(pos["valor_pago"].to_numpy() * 100).astype(np.int64)
    ch = ["minuto", "conta_origem_txt", "conta_destino_txt", "valor_cent", "formato"]
    casado = pp.merge(pos[ch + ["linha"]].drop_duplicates(ch), on=ch, how="left")
    em_padrao = set(casado["linha"].dropna().astype(np.int64))
    saida["padroes"] = {"tentativas": int(pp["tentativa"].nunique()), "linhas": int(len(pp)),
                        "rotulo_nas_linhas": {str(k): int(v) for k, v in pp["Is Laundering"].value_counts().items()},
                        "linhas_casadas_com_positivos": int(casado["linha"].notna().sum()),
                        "linhas_sem_positivo": int(casado["linha"].isna().sum()),
                        "positivos_lidos_das_particoes": int(len(pos)),
                        "positivos_em_algum_padrao": len(em_padrao),
                        "positivos_sem_padrao": int(len(pos) - len(em_padrao)),
                        "fracao_sem_padrao": float((len(pos) - len(em_padrao)) / len(pos))}
    print(comum.salvar_json(saida, "a6_reconferencia.json"))

    # Tabela legível (só os números usam ponto como separador de milhar)
    def n(x) -> str:
        return f"{x:,}".replace(",", ".")
    destino = comum.RAIZ / "docs" / "ml" / "hi_large" / "PARTICOES.md"
    partes = ["# Partições do HI-Large por dia",
              "",
              "Gerado por `scripts/hi_large/a6_reconferencia.py` a partir dos arquivos em "
              "`artefatos_ml/hi_large/particoes/`, que o git ignora. Há uma partição por dia com transações. "
              "**Período**: `principal` ou `cauda`, que tem menos de 1% do volume mediano diário "
              f"({n(int(mediana))} transações).",
              "",
              "| Índice | Data | Arquivo | Bytes | Linhas | Positivos | Período |",
              "|---|---|---|---|---|---|---|"]
    for r in tab.itertuples(index=False):
        partes.append(f"| {r.indice} | {r.data} | `{r.arquivo}` | {n(r.bytes)} | {n(r.linhas)} | {n(r.positivos)} | {r.periodo} |")
    p = saida["particoes"]
    partes += ["", f"**Total:** {p['arquivos']} arquivos, {n(p['linhas_somadas'])} linhas e {n(p['positivos_somados'])} positivos. "
               f"Há {p['arquivos_com_dia_repetido']} dias repetidos, {p['arquivos_com_minutos_de_outro_dia']} arquivos com minutos "
               f"de outro dia e {p['dias_sem_arquivo_entre_o_primeiro_e_o_ultimo']} dias sem arquivo entre o primeiro e o último.", ""]
    destino.write_text("\n".join(partes), encoding="utf-8")
    print(destino)


if __name__ == "__main__":
    main()
