"""Perfil dos três arquivos do HI-Large e partição das transações por dia.

Lê ``HI-Large_Trans.csv`` uma única vez, em blocos (sem carregar o arquivo na
memória), e:

* grava uma partição Parquet por dia em ``artefatos_ml/hi_large/particoes/``;
* conta linhas, ausentes, tipos, período, ordem temporal, valores, bancos,
  contas, formatos, moedas e rótulos por dia;
* guarda as chaves das transações positivas para casar com os padrões;
* calcula o SHA-256 dos três arquivos em paralelo.

Depois confere duplicatas exatas por dia, o arquivo de contas e o arquivo de
padrões (casamento com as transações e tentativas que atravessam partições).
Nenhum dado bruto vai para o relatório: só contagens e estatísticas.

Uso (da raiz do NodeWatch)::

    python scripts/hi_large/a_perfil_particionar.py --dados <pasta do HI-Large>
"""

from __future__ import annotations

import argparse
import hashlib
import re
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv
import pyarrow.parquet as pq

import comum
from src.ml.esquemas import COLUNAS_HISMALL
from src.ml.ingestao import ler_padroes

PARTICOES = comum.TRABALHO / "particoes"
DIA0 = pd.Timestamp("2022-08-01")
_EPOCA = pd.Timestamp("1970-01-01")
MIN_DIA0 = int((DIA0 - _EPOCA) // pd.Timedelta(minutes=1))
ESQUEMA_PARTICAO = pa.schema([
    ("linha", pa.int64()), ("minuto", pa.int64()),
    ("banco_origem", pa.int64()), ("conta_origem", pa.string()),
    ("banco_destino", pa.int64()), ("conta_destino", pa.string()),
    ("valor_recebido", pa.float64()), ("moeda_recebimento", pa.string()),
    ("valor_pago", pa.float64()), ("moeda_pagamento", pa.string()),
    ("formato", pa.string()), ("rotulo", pa.int8()),
])


def sha256(caminho: Path, destino: Dict[str, str]) -> None:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 23), b""):
            h.update(bloco)
    destino[caminho.name] = h.hexdigest()


def _contar(acum: Counter, chaves: pa.Array, pesos: np.ndarray | None = None) -> None:
    vc = pc.value_counts(chaves) if pesos is None else None
    if vc is not None:
        for item in vc.to_pylist():
            acum[item["values"]] += item["counts"]


def perfil_transacoes(arquivo: Path) -> Dict[str, Any]:
    PARTICOES.mkdir(parents=True, exist_ok=True)
    for antigo in PARTICOES.glob("dia=*.parquet"):
        antigo.unlink()
    with open(arquivo, "rb") as fh:
        cabecalho = fh.readline().decode("utf-8-sig").strip()
    tipos = {"Timestamp": pa.timestamp("s"), "From Bank": pa.string(), "Account": pa.string(),
             "To Bank": pa.string(), "Account.1": pa.string(), "Amount Received": pa.float64(),
             "Receiving Currency": pa.string(), "Amount Paid": pa.float64(), "Payment Currency": pa.string(),
             "Payment Format": pa.string(), "Is Laundering": pa.int8()}
    leitor = pcsv.open_csv(
        arquivo,
        read_options=pcsv.ReadOptions(column_names=list(COLUNAS_HISMALL), skip_rows=1, block_size=1 << 26),
        convert_options=pcsv.ConvertOptions(column_types=tipos, timestamp_parsers=["%Y/%m/%d %H:%M"],
                                            strings_can_be_null=False),
    )
    escritores: Dict[int, pq.ParquetWriter] = {}
    r: Dict[str, Any] = {
        "cabecalho": cabecalho.split(","), "linhas": 0, "ausentes": Counter(), "segundos_nao_zero": 0,
        "fora_de_ordem": 0, "maior_recuo_min": 0, "por_dia": defaultdict(lambda: [0, 0]),
        "formato": defaultdict(lambda: [0, 0]), "moeda_pagamento": defaultdict(lambda: [0, 0]),
        "moeda_recebimento": Counter(), "par_moedas_diferentes": Counter(),
        "valores": {"pago_min": np.inf, "pago_max": -np.inf, "rec_min": np.inf, "rec_max": -np.inf,
                    "pago_negativo": 0, "pago_zero": 0, "rec_negativo": 0, "nao_finitos": 0,
                    "mesma_moeda_valor_diferente": 0},
        "rotulo_fora_01": 0, "auto_transferencias": [0, 0], "mesmo_banco": [0, 0],
        "conta_nao_hex": 0, "conta_comprimento": Counter(), "banco_nao_numerico": 0,
    }
    bancos_txt: set = set()
    contas: set = set()
    positivos: List[pd.DataFrame] = []
    ultimo_minuto = None
    t0 = time.perf_counter()
    for lote in leitor:
        n = lote.num_rows
        base = r["linhas"]
        for nome in lote.schema.names:
            if lote.column(nome).null_count:
                r["ausentes"][nome] += lote.column(nome).null_count
        seg = pc.cast(lote.column("Timestamp"), pa.int64()).to_numpy(zero_copy_only=False)
        r["segundos_nao_zero"] += int((seg % 60 != 0).sum())
        minuto = seg // 60
        if ultimo_minuto is not None:
            anterior = np.concatenate([[ultimo_minuto], minuto[:-1]])
        else:
            anterior = np.concatenate([[minuto[0]], minuto[:-1]])
        recuo = anterior - minuto
        r["fora_de_ordem"] += int((recuo > 0).sum())
        r["maior_recuo_min"] = max(r["maior_recuo_min"], int(recuo.max(initial=0)))
        ultimo_minuto = int(minuto[-1])
        dia = (minuto - MIN_DIA0) // 1440
        y = lote.column("Is Laundering").to_numpy(zero_copy_only=False).astype(np.int8)
        r["rotulo_fora_01"] += int((~np.isin(y, (0, 1))).sum())

        bo_txt, bd_txt = lote.column("From Bank"), lote.column("To Bank")
        for col in (bo_txt, bd_txt):
            bancos_txt.update(pc.unique(col).to_pylist())
            r["banco_nao_numerico"] += int(pc.sum(pc.invert(pc.match_substring_regex(col, r"^[0-9]+$"))).as_py() or 0)
        bo = pc.cast(bo_txt, pa.int64())
        bd = pc.cast(bd_txt, pa.int64())
        co, cd = lote.column("Account"), lote.column("Account.1")
        for col in (co, cd):
            r["conta_nao_hex"] += int(pc.sum(pc.invert(pc.match_substring_regex(col, r"^[0-9A-F]+$"))).as_py() or 0)
            for item in pc.value_counts(pc.utf8_length(col)).to_pylist():
                r["conta_comprimento"][item["values"]] += item["counts"]
        ko = pc.binary_join_element_wise(pc.cast(bo, pa.string()), co, "-")
        kd = pc.binary_join_element_wise(pc.cast(bd, pa.string()), cd, "-")
        contas.update(pc.unique(pa.concat_arrays([ko.combine_chunks() if hasattr(ko, "combine_chunks") else ko,
                                                  kd.combine_chunks() if hasattr(kd, "combine_chunks") else kd])).to_pylist())
        auto = pc.equal(ko, kd).to_numpy(zero_copy_only=False)
        mb = pc.equal(bo, bd).to_numpy(zero_copy_only=False)
        r["auto_transferencias"][0] += int(auto.sum())
        r["auto_transferencias"][1] += int((auto & (y == 1)).sum())
        r["mesmo_banco"][0] += int(mb.sum())
        r["mesmo_banco"][1] += int((mb & (y == 1)).sum())

        vp = lote.column("Amount Paid").to_numpy(zero_copy_only=False)
        vr = lote.column("Amount Received").to_numpy(zero_copy_only=False)
        v = r["valores"]
        v["nao_finitos"] += int((~np.isfinite(vp)).sum() + (~np.isfinite(vr)).sum())
        v["pago_min"] = min(v["pago_min"], float(np.nanmin(vp)))
        v["pago_max"] = max(v["pago_max"], float(np.nanmax(vp)))
        v["rec_min"] = min(v["rec_min"], float(np.nanmin(vr)))
        v["rec_max"] = max(v["rec_max"], float(np.nanmax(vr)))
        v["pago_negativo"] += int((vp < 0).sum())
        v["pago_zero"] += int((vp == 0).sum())
        v["rec_negativo"] += int((vr < 0).sum())
        mp, mr = lote.column("Payment Currency"), lote.column("Receiving Currency")
        mesma = pc.equal(mp, mr).to_numpy(zero_copy_only=False)
        v["mesma_moeda_valor_diferente"] += int((mesma & (np.abs(vp - vr) > 1e-9 * np.maximum(1, np.abs(vp)))).sum())
        fmt = lote.column("Payment Format")
        df_cat = pd.DataFrame({"dia": dia, "y": y, "fmt": fmt.to_numpy(zero_copy_only=False),
                               "mp": mp.to_numpy(zero_copy_only=False), "mr": mr.to_numpy(zero_copy_only=False)})
        for chave, g in df_cat.groupby("dia")["y"]:
            r["por_dia"][int(chave)][0] += len(g)
            r["por_dia"][int(chave)][1] += int(g.sum())
        for chave, g in df_cat.groupby("fmt")["y"]:
            r["formato"][chave][0] += len(g)
            r["formato"][chave][1] += int(g.sum())
        for chave, g in df_cat.groupby("mp")["y"]:
            r["moeda_pagamento"][chave][0] += len(g)
            r["moeda_pagamento"][chave][1] += int(g.sum())
        for chave, k in df_cat["mr"].value_counts().items():
            r["moeda_recebimento"][chave] += int(k)
        dif = df_cat[~mesma]
        for (a, b), k in dif.groupby(["mp", "mr"]).size().items():
            r["par_moedas_diferentes"][f"{a} -> {b}"] += int(k)

        tab = pa.table({
            "linha": pa.array(np.arange(base, base + n, dtype=np.int64)), "minuto": pa.array(minuto),
            "banco_origem": bo, "conta_origem": co, "banco_destino": bd, "conta_destino": cd,
            "valor_recebido": lote.column("Amount Received"), "moeda_recebimento": mr,
            "valor_pago": lote.column("Amount Paid"), "moeda_pagamento": mp, "formato": fmt,
            "rotulo": pa.array(y),
        }, schema=ESQUEMA_PARTICAO)
        pos = np.flatnonzero(y == 1)
        if len(pos):
            positivos.append(tab.take(pa.array(pos)).select(
                ["linha", "minuto", "banco_origem", "conta_origem", "banco_destino", "conta_destino",
                 "valor_pago", "formato"]).to_pandas())
        for d in np.unique(dia):
            sel = tab.filter(pa.array(dia == d))
            w = escritores.get(int(d))
            if w is None:
                w = pq.ParquetWriter(PARTICOES / f"dia={int(d):03d}.parquet", ESQUEMA_PARTICAO, compression="zstd")
                escritores[int(d)] = w
            w.write_table(sel)
        r["linhas"] += n
        if r["linhas"] // 10_000_000 != (r["linhas"] - n) // 10_000_000:
            comum.log(f"{r['linhas']:,} linhas; {time.perf_counter() - t0:.0f} s; "
                      f"pico {comum.memoria_processo_mb()} MB")
    for w in escritores.values():
        w.close()
    r["segundos_leitura_e_particao"] = round(time.perf_counter() - t0, 1)
    # Bancos: a identidade do NodeWatch usa o banco numérico; confere se zeros à esquerda fundem códigos.
    por_inteiro: Dict[int, set] = defaultdict(set)
    for b in bancos_txt:
        por_inteiro[int(b)].add(b)
    fundidos = {k: sorted(v) for k, v in por_inteiro.items() if len(v) > 1}
    r["bancos"] = {"textos_distintos": len(bancos_txt), "inteiros_distintos": len(por_inteiro),
                   "codigos_fundidos_pelo_inteiro": len(fundidos),
                   "exemplos_fundidos": dict(list(sorted(fundidos.items()))[:10]),
                   "com_zero_a_esquerda": sum(1 for b in bancos_txt if len(b) > 1 and b.startswith("0"))}
    r["contas_distintas_banco_conta"] = len(contas)
    dias = sorted(r["por_dia"])
    r["por_dia"] = {str((DIA0 + pd.Timedelta(days=d)).date()): {"n": v[0], "positivos": v[1]}
                    for d, v in sorted(r["por_dia"].items())}
    r["periodo"] = {"primeiro_dia": str((DIA0 + pd.Timedelta(days=dias[0])).date()),
                    "ultimo_dia": str((DIA0 + pd.Timedelta(days=dias[-1])).date()), "dias": len(dias)}
    for k in ("formato", "moeda_pagamento"):
        r[k] = {a: {"n": b[0], "positivos": b[1]} for a, b in sorted(r[k].items())}
    for k in ("ausentes", "moeda_recebimento", "par_moedas_diferentes", "conta_comprimento"):
        r[k] = dict(sorted(r[k].items(), key=lambda kv: str(kv[0])))
    r["positivos_total"] = int(sum(len(p) for p in positivos))
    pos = pd.concat(positivos, ignore_index=True) if positivos else pd.DataFrame()
    pos.to_parquet(comum.TRABALHO / "positivos.parquet", index=False)
    return r, contas


def duplicatas_por_dia() -> Dict[str, Any]:
    saida = {}
    total = 0
    for arq in sorted(PARTICOES.glob("dia=*.parquet")):
        df = pq.read_table(arq, columns=[c for c in ESQUEMA_PARTICAO.names if c != "linha"]).to_pandas()
        k = int(df.duplicated().sum())
        total += k
        saida[arq.stem.split("=")[1]] = k
        del df
    return {"total": total, "por_dia_indice": saida}


def perfil_contas(arquivo: Path, contas_tx: set) -> Dict[str, Any]:
    tab = pcsv.read_csv(arquivo, convert_options=pcsv.ConvertOptions(
        column_types={c: pa.string() for c in ("Bank Name", "Bank ID", "Account Number", "Entity ID", "Entity Name")}))
    nomes = tab.schema.names
    df = tab.to_pandas()
    del tab
    r: Dict[str, Any] = {"linhas": len(df), "colunas": nomes,
                         "ausentes": {c: int(df[c].isna().sum() + (df[c].astype(str).str.strip() == "").sum())
                                      for c in nomes}}
    ok = df["Bank ID"].str.fullmatch(r"[0-9]+")
    r["bank_id_nao_numerico"] = int((~ok).sum())
    r["bank_id_com_zero_a_esquerda"] = int((df["Bank ID"].str.len().gt(1) & df["Bank ID"].str.startswith("0")).sum())
    df = df[ok]
    df["conta"] = df["Bank ID"].astype(np.int64).astype(str) + "-" + df["Account Number"].str.strip()
    r["chaves_duplicadas_banco_conta"] = int(df["conta"].duplicated().sum())
    r["linhas_duplicadas"] = int(df.duplicated(subset=["Bank Name", "Bank ID", "Account Number", "Entity ID",
                                                       "Entity Name"]).sum())
    r["entidades_distintas"] = int(df["Entity ID"].nunique())
    por_ent = df.groupby("Entity ID").size()
    r["contas_por_entidade"] = {"mediana": float(por_ent.median()), "max": int(por_ent.max()),
                                "entidades_com_mais_de_uma_conta": int((por_ent > 1).sum())}
    tipo = df["Entity Name"].str.extract(r"^(.*?)\s*#\s*\d+\s*$", expand=False).fillna("outro")
    r["tipo_entidade"] = {k: int(v) for k, v in tipo.value_counts().items()}
    banco_nome = df.groupby("conta")["Bank ID"].first()
    r["bancos_distintos"] = int(df["Bank ID"].astype(np.int64).nunique())
    chaves = set(df["conta"])
    r["contas_das_transacoes"] = len(contas_tx)
    r["contas_das_transacoes_sem_cadastro"] = len(contas_tx - chaves)
    r["contas_cadastradas_sem_transacao"] = len(chaves - contas_tx)
    del banco_nome
    return r


def perfil_padroes(arquivo: Path) -> Dict[str, Any]:
    pp = ler_padroes(arquivo)
    pos = pd.read_parquet(comum.TRABALHO / "positivos.parquet")
    r: Dict[str, Any] = {"tentativas": int(pp["tentativa"].nunique()), "linhas": len(pp)}
    r["rotulo_nas_linhas"] = {str(k): int(v) for k, v in pp["Is Laundering"].value_counts().items()}
    r["linhas_por_tipo"] = {k: int(v) for k, v in pp.groupby("tipo_padrao").size().items()}
    r["tentativas_por_tipo"] = {k: int(v) for k, v in pp.groupby("tipo_padrao")["tentativa"].nunique().items()}
    pp["valor_cent"] = np.round(pp["valor_pago"].to_numpy() * 100).astype(np.int64)
    pos["conta_origem_txt"] = pos["banco_origem"].astype(str) + "-" + pos["conta_origem"]
    pos["conta_destino_txt"] = pos["banco_destino"].astype(str) + "-" + pos["conta_destino"]
    pos["valor_cent"] = np.round(pos["valor_pago"].to_numpy() * 100).astype(np.int64)
    pp["formato"] = pp["Payment Format"].astype(str)
    chaves = ["minuto", "conta_origem_txt", "conta_destino_txt", "valor_cent", "formato"]
    r["linhas_de_padrao_repetidas_entre_tentativas"] = int(pp.duplicated(chaves).sum())
    casado = pp.merge(pos[chaves + ["linha"]].drop_duplicates(chaves), on=chaves, how="left")
    r["linhas_de_padrao_casadas_com_positivos"] = int(casado["linha"].notna().sum())
    r["linhas_de_padrao_sem_positivo"] = int(casado["linha"].isna().sum())
    em_padrao = set(casado["linha"].dropna().astype(np.int64))
    r["positivos_total"] = len(pos)
    r["positivos_em_algum_padrao"] = len(em_padrao)
    r["positivos_sem_padrao"] = int(len(pos) - len(em_padrao))
    # Duração das tentativas e travessia das partições do plano (por minuto).
    g = pp.groupby("tentativa")["minuto"].agg(["min", "max"])
    dur_h = (g["max"] - g["min"]) / 60
    r["duracao_tentativa_horas"] = {q: float(dur_h.quantile(q)) for q in (0.5, 0.9, 0.99)} | {"max": float(dur_h.max())}
    lim = {"treino": (0, 6), "validacao": (6, 8), "teste": (8, 10), "reserva": (10, 12)}
    dia_ini = (g["min"] - MIN_DIA0) // 1440
    dia_fim = (g["max"] - MIN_DIA0) // 1440
    def part(dia):  # noqa: E306
        return np.select([dia < 6, dia < 8, dia < 10, dia < 12], ["treino", "validacao", "teste", "reserva"], "depois")
    p_ini, p_fim = part(dia_ini.to_numpy()), part(dia_fim.to_numpy())
    janela = (dia_ini < 12) | (dia_fim < 12)
    r["tentativas_na_janela_de_12_dias"] = int(janela.sum())
    r["tentativas_que_atravessam_particoes"] = int(((p_ini != p_fim) & janela).sum())
    r["tentativas_iniciadas_antes_de_2022_08_01"] = int((dia_ini < 0).sum())
    pp.drop(columns=["Timestamp", "From Bank", "Account", "To Bank", "Account.1", "Amount Received",
                     "Amount Paid"], errors="ignore").assign(linha=casado["linha"]).to_parquet(
        comum.TRABALHO / "padroes_casados.parquet", index=False)
    return r


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dados")
    ap.add_argument("--prefixo", default="HI-Large", help="prefixo dos arquivos IBM AML (padrão: HI-Large)")
    a = ap.parse_args()
    pasta = comum.pasta_dados(a.dados)
    comum.TRABALHO.mkdir(parents=True, exist_ok=True)
    arquivos = {k: pasta / v for k, v in comum.nomes_arquivos(a.prefixo).items()}
    saida: Dict[str, Any] = {"gerado_em_utc": comum.agora(), "script": Path(__file__).name,
                             "plano_sha256": hashlib.sha256(comum.PLANO.read_bytes()).hexdigest(),
                             "ambiente": comum.ambiente(), "tempos": {}}
    saida["arquivos"] = {k: {"nome": p.name, "bytes": p.stat().st_size} for k, p in arquivos.items()}
    hashes: Dict[str, str] = {}
    fios = [threading.Thread(target=sha256, args=(p, hashes)) for p in arquivos.values()]
    for f in fios:
        f.start()
    comum.log("lendo e particionando as transações")
    with comum.medir(saida["tempos"], "transacoes"):
        saida["transacoes"], contas_tx = perfil_transacoes(arquivos["transacoes"])
    comum.log("duplicatas por dia")
    with comum.medir(saida["tempos"], "duplicatas"):
        saida["transacoes"]["duplicatas_exatas"] = duplicatas_por_dia()
    comum.log("contas")
    with comum.medir(saida["tempos"], "contas"):
        saida["contas"] = perfil_contas(arquivos["contas"], contas_tx)
    del contas_tx
    comum.log("padrões")
    with comum.medir(saida["tempos"], "padroes"):
        saida["padroes"] = perfil_padroes(arquivos["padroes"])
    for f in fios:
        f.join()
    for k, p in arquivos.items():
        saida["arquivos"][k]["sha256"] = hashes.get(p.name)
    saida["pico_memoria_mb"] = comum.memoria_processo_mb()
    print(comum.salvar_json(saida, "a_perfil.json"))


if __name__ == "__main__":
    main()
