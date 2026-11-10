"""Conferência dos atributos de um teste final (Emendas 2 e 3), sem recalcular nada.

* Dia reproduzido: a passada refeita do dia 1 precisa reproduzir, coluna por
  coluna, um dia que já existia em outra pasta.
  - Emenda 2 (padrão): ``atributos_*_final2`` × ``atributos_*``, dia 12/08 (índice 11).
  - Emenda 3: ``atributos_*_final3`` × ``atributos_*_final2``, dia 16/08 (índice 15).
* Dias novos: cada dia tem todas as linhas e todos os positivos da partição, sem
  ``_linha`` repetida nem fora da partição.

Grava ``b6_conferencia_<sufixo>.json``.

Uso::

    python scripts/hi_large/b6_conferir_final2.py
    python scripts/hi_large/b6_conferir_final2.py --sufixo final3 --anterior final2 --dia-repro 15 --dias 16-22
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import comum


def iguais(a: pd.DataFrame, b: pd.DataFrame) -> Dict[str, Any]:
    a = a.sort_values("_linha", kind="stable").reset_index(drop=True)
    b = b.sort_values("_linha", kind="stable").reset_index(drop=True)
    diferentes = []
    maior = 0.0
    for c in a.columns:
        x, y = a[c].to_numpy(), b[c].to_numpy()
        if x.dtype.kind == "f" or y.dtype.kind == "f":
            x, y = x.astype(np.float64), y.astype(np.float64)
            ok = (x == y) | (np.isnan(x) & np.isnan(y))
            if (~ok).any():
                diferentes.append(c)
                d = np.abs(x - y)[~ok]
                maior = max(maior, float(np.nanmax(d)) if np.isfinite(d).any() else float("inf"))
        elif not np.array_equal(x, y):
            diferentes.append(c)
    return {"linhas": [int(len(a)), int(len(b))], "colunas": [list(a.columns) == list(b.columns), int(a.shape[1])],
            "colunas_diferentes": diferentes, "maior_diferenca_absoluta": maior,
            "identico": len(a) == len(b) and list(a.columns) == list(b.columns) and not diferentes}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sufixo", default="final2", help="pasta conferida: atributos_<preparador>_<sufixo>")
    ap.add_argument("--anterior", default="", help="sufixo da pasta com o dia a reproduzir (vazio: atributos_<preparador>)")
    ap.add_argument("--dia-repro", type=int, default=11, help="índice do dia que precisa ser idêntico")
    ap.add_argument("--dias", default="12-15", help="índices dos dias novos, como 12-15")
    a = ap.parse_args()
    ini, fim = (int(x) for x in a.dias.split("-"))
    saida: Dict[str, Any] = {"gerado_em_utc": comum.agora(), "script": Path(__file__).name, "sufixo": a.sufixo,
                             "anterior": a.anterior or "(primeira passada)", "preparadores": {}}
    for prep in ("S", "L"):
        orig = comum.TRABALHO / (f"atributos_{prep}_{a.anterior}" if a.anterior else f"atributos_{prep}")
        novo = comum.TRABALHO / f"atributos_{prep}_{a.sufixo}"
        rep = iguais(pd.read_parquet(orig / f"dia={a.dia_repro:03d}.parquet"),
                     pd.read_parquet(novo / f"dia={a.dia_repro:03d}.parquet"))
        rep["data"] = str((pd.Timestamp("2022-08-01") + pd.Timedelta(days=a.dia_repro)).date())
        r: Dict[str, Any] = {"dia_reproduzido": rep, "dias_novos": {}}
        for d in range(ini, fim + 1):
            part = pq.read_table(comum.TRABALHO / "particoes" / f"dia={d:03d}.parquet", columns=["linha", "rotulo"])
            linhas = part["linha"].to_numpy()
            g = pd.read_parquet(novo / f"dia={d:03d}.parquet", columns=["_linha", "_rotulo"])
            gl = g["_linha"].to_numpy()
            r["dias_novos"][str(d)] = {
                "data": str((pd.Timestamp("2022-08-01") + pd.Timedelta(days=d)).date()),
                "gravadas": int(len(g)), "linhas_da_particao": int(len(linhas)),
                "linha_repetida": int(len(gl) - len(np.unique(gl))),
                "fora_da_particao": int((~np.isin(gl, linhas)).sum()),
                "positivos_gravados": int(g["_rotulo"].sum()), "positivos_na_particao": int(part["rotulo"].to_numpy().sum()),
            }
        saida["preparadores"][prep] = r
        comum.log(f"{prep}: dia {rep['data']} idêntico = {rep['identico']}")
    print(comum.salvar_json(saida, f"b6_conferencia_{a.sufixo}.json"))


if __name__ == "__main__":
    main()
