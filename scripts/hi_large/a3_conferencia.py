"""Conferência das partições e dos atributos gravados (não relê o CSV, exceto para o hash).

* Recalcula o SHA-256 dos três arquivos e compara com ``a_perfil.json``.
* Partições: cada linha do CSV (``linha`` de 0 a N-1) aparece **uma única vez**,
  na partição do seu dia; contagens e positivos por dia batem com o perfil.
* Atributos (``atributos_S`` e ``atributos_L``): linhas gravadas por dia, ``_linha``
  sem repetição e contida na partição, todos os positivos presentes.

Uso::

    python scripts/hi_large/a3_conferencia.py --dados <pasta do HI-Large>
"""

from __future__ import annotations

import argparse
import hashlib
import threading
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import comum

PARTICOES = comum.TRABALHO / "particoes"
DIA0 = pd.Timestamp("2022-08-01")
MIN_DIA0 = int((DIA0 - pd.Timestamp("1970-01-01")) // pd.Timedelta(minutes=1))


def _sha(caminho: Path, destino: Dict[str, str]) -> None:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 23), b""):
            h.update(bloco)
    destino[caminho.name] = h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dados")
    ap.add_argument("--prefixo", default="HI-Large", help="prefixo dos arquivos IBM AML (padrão: HI-Large)")
    ap.add_argument("--sem-hash", action="store_true")
    a = ap.parse_args()
    perfil = comum.ler_json("a_perfil.json")
    saida: Dict[str, Any] = {"gerado_em_utc": comum.agora(), "script": Path(__file__).name}
    hashes: Dict[str, str] = {}
    fios = []
    if not a.sem_hash:
        pasta = comum.pasta_dados(a.dados)
        fios = [threading.Thread(target=_sha, args=(pasta / n, hashes)) for n in comum.nomes_arquivos(a.prefixo).values()]
        for f in fios:
            f.start()

    n_total = perfil["transacoes"]["linhas"]
    visto = np.zeros(n_total, dtype=np.uint8)
    por_dia_perfil = perfil["transacoes"]["por_dia"]
    divergencias = []
    fora_do_dia = 0
    arquivos = sorted(PARTICOES.glob("dia=*.parquet"))
    positivos = 0
    linhas_particao: Dict[int, np.ndarray] = {}
    for arq in arquivos:
        d = int(arq.stem.split("=")[1])
        t = pq.read_table(arq, columns=["linha", "minuto", "rotulo"]).to_pandas()
        linha = t["linha"].to_numpy()
        np.add.at(visto, linha, 1)
        fora_do_dia += int((((t["minuto"].to_numpy() - MIN_DIA0) // 1440) != d).sum())
        data = str((DIA0 + pd.Timedelta(days=d)).date())
        esperado = por_dia_perfil.get(data)
        obtido = {"n": int(len(t)), "positivos": int(t["rotulo"].sum())}
        positivos += obtido["positivos"]
        if esperado != obtido:
            divergencias.append({"dia": data, "perfil": esperado, "particao": obtido})
        if d < 12:
            linhas_particao[d] = np.sort(linha)
    saida["particoes"] = {
        "arquivos": len(arquivos), "dias_no_perfil": len(por_dia_perfil),
        "dias_periodo_principal": sum(1 for v in por_dia_perfil.values() if v["n"] >= 0.01 * np.median(
            [x["n"] for x in por_dia_perfil.values()])),
        "linhas_somadas": int(visto.astype(np.int64).sum()), "linhas_no_csv": n_total,
        "linhas_repetidas_entre_ou_dentro_de_particoes": int((visto > 1).sum()),
        "linhas_ausentes": int((visto == 0).sum()), "linhas_fora_do_dia_da_particao": fora_do_dia,
        "positivos_somados": positivos, "positivos_no_perfil": perfil["transacoes"]["positivos_total"],
        "dias_com_contagem_diferente_do_perfil": divergencias,
    }
    del visto

    atributos: Dict[str, Any] = {}
    for prep in ("S", "L"):
        pasta_at = comum.TRABALHO / f"atributos_{prep}"
        r: Dict[str, Any] = {}
        for d, linhas in linhas_particao.items():
            arq = pasta_at / f"dia={d:03d}.parquet"
            if not arq.is_file():
                r[str(d)] = "ausente"
                continue
            t = pq.read_table(arq, columns=["_linha", "_rotulo", "_dia"]).to_pandas()
            l_at = t["_linha"].to_numpy()
            pos_part = int(pq.read_table(PARTICOES / f"dia={d:03d}.parquet", columns=["rotulo"])
                           .column("rotulo").to_numpy().sum())
            r[str(d)] = {"gravadas": int(len(t)), "linhas_da_particao": int(len(linhas)),
                         "linha_repetida": int(pd.Series(l_at).duplicated().sum()),
                         "fora_da_particao": int((~np.isin(l_at, linhas)).sum()),
                         "dia_errado": int((t["_dia"].to_numpy() != d).sum()),
                         "positivos_gravados": int(t["_rotulo"].sum()), "positivos_na_particao": pos_part}
        atributos[prep] = r
    saida["atributos"] = atributos
    for f in fios:
        f.join()
    if hashes:
        saida["sha256"] = {n: {"agora": h, "perfil": perfil["arquivos"][k]["sha256"],
                               "igual": h == perfil["arquivos"][k]["sha256"]}
                           for k, n in comum.nomes_arquivos(a.prefixo).items() for h in [hashes[n]]}
    print(comum.salvar_json(saida, "a3_conferencia.json"))


if __name__ == "__main__":
    main()
