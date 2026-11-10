"""Auditoria de fechamento da avaliação do HI-Large. Só lê; não pontua modelos nem consulta períodos.

Não carrega modelos para prever, não grava atributos e não altera ``consultas.json``.
Grava ``e_auditoria.json`` com:

* ``sobreposicao``: contas, tentativas e tipos de padrão em comum entre treino,
  validação e os testes finais (13 a 16/08 e 17 a 23/08), antes e depois da purga;
* ``bootstrap``: como os intervalos foram calculados e quantos grupos e positivos
  por grupo existem nos períodos avaliados;
* ``criterio_emenda3``: hash da emenda, ordem dos horários, hashes dos modelos
  congelados e o critério recalculado a partir do JSON da consulta;
* ``artefato_producao``: hash, tamanho e data do artefato do sistema;
* ``consistencia``: números dos JSON procurados no texto dos documentos;
* ``inventario``: hash de resultados, modelos, escolhas e código, mais o ambiente.

Uso::

    python scripts/hi_large/e_auditoria.py --dados <pasta do HI-Large>
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

import comum

DOCS = comum.RAIZ / "docs" / "ml" / "hi_large"
R = comum.RESULTADOS
DIA0 = pd.Timestamp("2022-08-01")
EPOCA_DIA0 = int((DIA0 - pd.Timestamp("1970-01-01")) // pd.Timedelta(minutes=1))
DIVISOES = {"treino": range(0, 6), "validacao": range(6, 8), "teste": range(8, 10), "reserva": range(10, 12),
            "final2": range(12, 16), "final3": range(16, 23)}
AVALIADAS = ("validacao", "teste", "reserva", "final2", "final3")


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 22), b""):
            h.update(bloco)
    return h.hexdigest()


def mtime_utc(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 1. Sobreposição de contas, tentativas e padrões
# ---------------------------------------------------------------------------
def sobreposicao(pasta_dados: Path) -> Dict[str, Any]:
    cad = pd.read_csv(pasta_dados / comum.nomes_arquivos()["contas"], dtype=str, usecols=["Bank ID", "Account Number"])
    indice = pd.Index(cad["Bank ID"].astype("int64").astype(str) + "-" + cad["Account Number"].str.strip())
    n_contas = len(indice)
    del cad
    pp = pd.read_parquet(comum.TRABALHO / "padroes_casados.parquet", columns=["tentativa", "minuto", "linha", "tipo_padrao"])
    inicio_tent = pp.groupby("tentativa")["minuto"].min()
    tent_da_linha = pd.Series(pp["tentativa"].to_numpy(), index=pp["linha"].astype(np.int64).to_numpy())
    inicio_da_linha = pd.Series(inicio_tent.reindex(pp["tentativa"]).to_numpy(), index=tent_da_linha.index)

    ativa = {d: np.zeros(n_contas, dtype=bool) for d in DIVISOES}
    positiva = {d: np.zeros(n_contas, dtype=bool) for d in DIVISOES}
    pos_linhas: Dict[str, pd.DataFrame] = {}
    for div, dias in DIVISOES.items():
        partes = []
        for d in dias:
            t = pq.read_table(comum.TRABALHO / "particoes" / f"dia={d:03d}.parquet",
                              columns=["linha", "minuto", "banco_origem", "conta_origem", "banco_destino",
                                       "conta_destino", "rotulo"])
            ko = pc.binary_join_element_wise(pc.cast(t["banco_origem"], pa.string()), t["conta_origem"], "-")
            kd = pc.binary_join_element_wise(pc.cast(t["banco_destino"], pa.string()), t["conta_destino"], "-")
            for k in (ko, kd):
                u = indice.get_indexer(pc.unique(k).to_pylist())
                assert (u >= 0).all(), "conta sem cadastro"
                ativa[div][u] = True
            m = pc.equal(t["rotulo"], 1)
            pos = pd.DataFrame({"linha": t["linha"].filter(m).to_numpy(), "minuto": t["minuto"].filter(m).to_numpy(),
                                "o": indice.get_indexer(ko.filter(m).to_pylist()),
                                "d": indice.get_indexer(kd.filter(m).to_pylist())})
            partes.append(pos)
            for col in ("o", "d"):
                positiva[div][pos[col].to_numpy()] = True
            del t, ko, kd
        pl = pd.concat(partes, ignore_index=True)
        pl["tentativa"] = tent_da_linha.reindex(pl["linha"].to_numpy()).to_numpy()
        pl["inicio_tentativa"] = inicio_da_linha.reindex(pl["linha"].to_numpy()).to_numpy()
        inicio_div = EPOCA_DIA0 + dias[0] * 1440
        pl["grupo"] = np.where(pl["tentativa"].isna(), "sem_padrao",
                               np.where(pl["inicio_tentativa"] < inicio_div, "iniciada_antes", "nova"))
        pos_linhas[div] = pl
        comum.log(f"{div}: {int(ativa[div].sum()):,} contas ativas; {len(pl):,} positivos")

    def par(a: np.ndarray, b: np.ndarray) -> Dict[str, Any]:
        n = int((a & b).sum())
        return {"em_comum": n, "fracao_da_segunda": n / max(int(b.sum()), 1)}

    saida: Dict[str, Any] = {
        "contas_ativas": {d: int(v.sum()) for d, v in ativa.items()},
        "contas_em_transacoes_positivas": {d: int(v.sum()) for d, v in positiva.items()},
        "intersecoes_contas_ativas": {}, "intersecoes_contas_positivas": {},
        "positivos_avaliados_com_conta_vista_antes": {}, "tentativas": {}, "tipos_de_padrao": {},
    }
    for a_, b_ in (("treino", "validacao"), ("treino", "final2"), ("treino", "final3"), ("validacao", "final2"),
                   ("validacao", "final3"), ("final2", "final3")):
        saida["intersecoes_contas_ativas"][f"{a_}∩{b_}"] = par(ativa[a_], ativa[b_])
        saida["intersecoes_contas_positivas"][f"{a_}∩{b_}"] = par(positiva[a_], positiva[b_])

    # Positivos avaliados (depois da purga) cuja conta de origem ou destino já esteve em positivo do treino.
    treino_pos = positiva["treino"]
    treino_ativa = ativa["treino"]
    anteriores_pos = treino_pos | positiva["validacao"]
    for div in AVALIADAS:
        pl = pos_linhas[div]
        aval = pl[pl["grupo"] != "iniciada_antes"]
        conta_pos_treino = treino_pos[aval["o"].to_numpy()] | treino_pos[aval["d"].to_numpy()]
        conta_ativa_treino = treino_ativa[aval["o"].to_numpy()] | treino_ativa[aval["d"].to_numpy()]
        por_grupo = {}
        for g in ("nova", "sem_padrao"):
            sel = (aval["grupo"] == g).to_numpy()
            por_grupo[g] = {"positivos": int(sel.sum()),
                            "com_conta_em_positivo_do_treino": int((conta_pos_treino & sel).sum())}
        saida["positivos_avaliados_com_conta_vista_antes"][div] = {
            "positivos_avaliados": int(len(aval)),
            "com_conta_em_positivo_do_treino": int(conta_pos_treino.sum()),
            "fracao_com_conta_em_positivo_do_treino": float(conta_pos_treino.mean()),
            "com_conta_ativa_no_treino": int(conta_ativa_treino.sum()),
            "com_conta_em_positivo_do_treino_ou_validacao": int(
                (anteriores_pos[aval["o"].to_numpy()] | anteriores_pos[aval["d"].to_numpy()]).sum()),
            "por_grupo": por_grupo,
        }

    # Tentativas: em quais divisões cada uma tem eventos.
    dia_ev = (pp["minuto"].to_numpy() - EPOCA_DIA0) // 1440
    div_do_dia = {d: nome for nome, dias in DIVISOES.items() for d in dias}
    ev = pd.DataFrame({"tentativa": pp["tentativa"].to_numpy(), "div": [div_do_dia.get(int(x)) for x in dia_ev]})
    ev = ev.dropna().drop_duplicates()
    conj = ev.groupby("tentativa")["div"].agg(set)
    for a_, b_ in (("treino", "validacao"), ("treino", "final2"), ("treino", "final3"), ("validacao", "final2"),
                   ("validacao", "final3"), ("final2", "final3")):
        saida["tentativas"][f"com_eventos_em_{a_}_e_{b_}"] = int(conj.apply(lambda s: a_ in s and b_ in s).sum())
    for div in AVALIADAS:
        pl = pos_linhas[div]
        aval_tent = pl.loc[pl["grupo"] == "nova", "tentativa"].dropna().unique()
        anteriores = [n for n, ds in DIVISOES.items() if ds[0] < DIVISOES[div][0]]
        n_com_antes = int(sum(any(x in conj.get(t, set()) for x in anteriores) for t in aval_tent))
        saida["tentativas"][div] = {
            "tentativas_com_positivos_avaliados": int(len(aval_tent)),
            "dessas_com_evento_em_divisao_anterior": n_com_antes,
            "tentativas_retiradas_pela_purga": int(pl.loc[pl["grupo"] == "iniciada_antes", "tentativa"].nunique()),
            "positivos_retirados_pela_purga": int((pl["grupo"] == "iniciada_antes").sum()),
        }
    tipo = pd.Series(pp["tipo_padrao"].to_numpy(), index=pp["linha"].astype(np.int64).to_numpy())
    for div in DIVISOES:
        pl = pos_linhas[div]
        aval = pl if div == "treino" else pl[pl["grupo"] != "iniciada_antes"]
        saida["tipos_de_padrao"][div] = tipo.reindex(aval["linha"].to_numpy()).dropna().value_counts().to_dict()
    saida["_pos_linhas"] = pos_linhas
    return saida


# ---------------------------------------------------------------------------
# 2. Bootstrap: método e estrutura de dependência dos períodos avaliados
# ---------------------------------------------------------------------------
def bootstrap(pos_linhas: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    import c_treinar_avaliar as c
    fonte = inspect.getsource(c.bootstrap_pareado)
    saida: Dict[str, Any] = {
        "funcao": "c_treinar_avaliar.bootstrap_pareado",
        "sha256_do_codigo_da_funcao": hashlib.sha256(fonte.encode("utf-8")).hexdigest(),
        "pareado": "sim: as duas pontuações recebem os mesmos pesos em cada reamostra",
        "unidade_de_reamostragem": "conta de origem (pesos de Poisson com média 1 por conta)",
        "reamostras": 1000, "semente": comum.SEMENTE, "intervalo": "percentis 2,5 e 97,5",
        "nao_agrupa_por": ["conta de destino", "tentativa (que envolve várias contas)", "dia"],
    }
    for div in ("final2", "final3"):
        pl = pos_linhas[div]
        aval = pl[pl["grupo"] != "iniciada_antes"]
        por_conta = aval.groupby("o").size().sort_values(ascending=False)
        tent = aval.dropna(subset=["tentativa"])
        contas_por_tent = tent.groupby("tentativa")["o"].nunique()
        saida[div] = {
            "positivos_avaliados": int(len(aval)),
            "contas_de_origem_com_positivo": int(len(por_conta)),
            "maximo_de_positivos_numa_conta_de_origem": int(por_conta.iloc[0]),
            "fracao_dos_positivos_nas_10_contas_com_mais_positivos": float(por_conta.iloc[:10].sum() / len(aval)),
            "tentativas_avaliadas": int(len(contas_por_tent)),
            "tentativas_com_positivos_em_mais_de_uma_conta_de_origem": int((contas_por_tent > 1).sum()),
            "dias": len(DIVISOES[div]),
        }
    return saida


# ---------------------------------------------------------------------------
# 3. Critério da Emenda 3
# ---------------------------------------------------------------------------
def criterio_emenda3() -> Dict[str, Any]:
    emenda = DOCS / "EMENDA_3_SEGUNDO_TESTE_FINAL.md"
    reg = (comum.TRABALHO / "emenda3_registro.sha256").read_text(encoding="utf-8").split()
    d = comum.ler_json("d_teste_final3.json")
    texto = emenda.read_text(encoding="utf-8")
    shas_na_emenda = re.findall(r"`([0-9a-f]{64})`", texto)
    arquivos = re.findall(r"`((?:corrigido__S_L__|L__)[^`]+\.joblib)`", texto)
    modelos = {a: {"sha256_agora": sha(comum.TRABALHO / "modelos" / a)} for a in arquivos}
    for a, s in zip(arquivos, shas_na_emenda[1:]):
        modelos[a]["sha256_na_emenda"] = s
        modelos[a]["igual"] = modelos[a]["sha256_agora"] == s
    atributos_final3 = sorted((comum.TRABALHO).glob("atributos_*_final3/dia=*.parquet"))
    primeiro_atributo = min(datetime.fromtimestamp(p.stat().st_ctime, tz=timezone.utc) for p in atributos_final3)
    s_ap = d["modelos"]["S|modelo atual, limiar do artefato"]["ap_por_dia"]
    recalc = {}
    for rotulo, cr in d["criterio_emenda3"].items():
        chave = [k for k, m in d["modelos"].items() if m.get("papel_emenda3") == cr["papel"]
                 and abs(m["average_precision"] - cr["ap"]) < 1e-15][0]
        apd = d["modelos"][chave]["ap_por_dia"]
        b = d["bootstrap_escolhido_menos_atual"][chave]
        acima = sum(apd[k] > s_ap[k] for k in s_ap)
        recalc[rotulo] = {"papel": cr["papel"], "dias_acima": acima, "ic95": b["ic95"],
                          "atendido_recalculado": bool(b["diferenca_ap"] > 0 and b["ic95"][0] > 0 and acima >= 5),
                          "atendido_no_json": cr["atendido"], "limiar": d["modelos"][chave]["limiar"]}
    return {
        "emenda_sha256_agora": sha(emenda), "emenda_sha256_registrado": reg[0], "registrada_em": reg[2].split("=")[1],
        "emenda_sha256_na_consulta": d["protocolo_sha256"]["EMENDA_3"],
        "hash_igual_nos_tres": len({sha(emenda), reg[0], d["protocolo_sha256"]["EMENDA_3"]}) == 1,
        "consulta_iniciada_em": d["gerado_em_utc"],
        "primeiro_arquivo_de_atributos_final3_criado_em": primeiro_atributo.isoformat(timespec="seconds"),
        "consultas": json.loads((comum.TRABALHO / "consultas.json").read_text(encoding="utf-8")),
        "dias_avaliados": d["dias"], "artefato_sha256_na_emenda": shas_na_emenda[0],
        "artefato_sha256_na_consulta": d.get("artefato_sha256"), "modelos_congelados": modelos,
        "criterio_recalculado": recalc,
    }


# ---------------------------------------------------------------------------
# 4. Artefato de produção e consistência dos documentos
# ---------------------------------------------------------------------------
def artefato() -> Dict[str, Any]:
    p = comum.RAIZ / "artefatos_ml" / "modelo_unificado.joblib"
    meta = json.loads((comum.RAIZ / "artefatos_ml" / "metadados_modelo.json").read_text(encoding="utf-8"))
    escritas = []
    for s in sorted((comum.RAIZ / "scripts" / "hi_large").glob("*.py")):
        t = s.read_text(encoding="utf-8")
        if re.search(r"modelo_unificado\.joblib|ModeloUnificado\.salvar|\.salvar\(comum\.RAIZ", t) and "salvar" in t \
                and re.search(r"\.salvar\(", t):
            escritas.append(s.name)
    return {"arquivo": "artefatos_ml/modelo_unificado.joblib", "sha256": sha(p), "bytes": p.stat().st_size,
            "modificado_em_utc": mtime_utc(p), "metadados_modificado_em_utc": mtime_utc(
                comum.RAIZ / "artefatos_ml" / "metadados_modelo.json"),
            "versao_lavagem": json.dumps(meta, ensure_ascii=False).count("lavagem-20261102T083253Z") > 0,
            "scripts_hi_large_que_chamam_salvar_em_ModeloUnificado": escritas}


def br(x: float, casas: int, sinal: bool = False) -> str:
    s = f"{abs(x):.{casas}f}".replace(".", ",")
    if sinal:
        return ("+" if x >= 0 else "−") + s
    return ("−" if x < 0 else "") + s


def consistencia() -> Dict[str, Any]:
    rel = (DOCS / "RELATORIO_HI_LARGE.md").read_text(encoding="utf-8")
    reg_p = DOCS / "REGISTRO_EXPERIMENTOS_E_TREINOS.md"
    reg = reg_p.read_text(encoding="utf-8") if reg_p.is_file() else ""
    leia = (comum.RAIZ / "docs" / "ml" / "README.md").read_text(encoding="utf-8")
    checks: List[Dict[str, Any]] = []

    def conferir(rotulo: str, valor: str, docs: Dict[str, str]) -> None:
        for nome, texto in docs.items():
            checks.append({"item": rotulo, "valor": valor, "documento": nome, "encontrado": valor in texto})

    ambos = {"RELATORIO": rel, "REGISTRO": reg}
    for arq, periodo in (("d_teste_final2.json", "final2"), ("d_teste_final3.json", "final3")):
        d = comum.ler_json(arq)
        conferir(f"{periodo}: linhas avaliadas", f"{d['n']:,}".replace(",", "."), ambos)
        conferir(f"{periodo}: positivos avaliados", f"{d['positivos']:,}".replace(",", "."), ambos)
        for chave, m in d["modelos"].items():
            conferir(f"{periodo}: AP {chave}", br(m["average_precision"], 4), ambos)
        for chave, b in d["bootstrap_escolhido_menos_atual"].items():
            conferir(f"{periodo}: diferença {chave}", br(b["diferenca_ap"], 4, True), ambos)
            conferir(f"{periodo}: IC {chave}", f"[{br(b['ic95'][0], 4, True)}; {br(b['ic95'][1], 4, True)}]", ambos)
    rf = comum.ler_json("d_teste_final2_rf_descritivo.json")
    for chave, b in rf["bootstrap_escolhido_menos_atual"].items():
        conferir(f"final2 florestas: diferença {chave}", br(b["diferenca_ap"], 4, True), ambos)
    conferir("README: AP 0,115 e 0,098 não devem aparecer como melhora", "0,115 contra 0,098", {"README_ml": leia})
    return {"verificacoes": checks, "faltando": [c for c in checks if not c["encontrado"]
                                                    and not c["item"].startswith("README")],
            "readme_com_frase_antiga": any(c["encontrado"] for c in checks if c["item"].startswith("README"))}


# ---------------------------------------------------------------------------
# 5. Inventário
# ---------------------------------------------------------------------------
def inventario() -> Dict[str, Any]:
    def lista(pasta: Path, padrao: str) -> List[Dict[str, Any]]:
        return [{"arquivo": p.name, "sha256": sha(p), "bytes": p.stat().st_size, "modificado_em_utc": mtime_utc(p)}
                for p in sorted(pasta.glob(padrao))]
    resultados = lista(R, "*.json") + lista(R, "*.xml")
    for r in resultados:
        if not r["arquivo"].endswith(".json"):
            continue
        try:
            j = json.loads((R / r["arquivo"]).read_text(encoding="utf-8"))
            r["gerado_em_utc"] = j.get("gerado_em_utc")
            r["script"] = j.get("script") or j.get("etapa")
        except Exception:
            r["gerado_em_utc"] = None
    codigo = []
    for padrao in ("src/ml/*.py", "scripts/hi_large/*.py", "testes/ml/test_hi_large_avaliacao.py",
                   "testes/ml/referencia_financeira.py", "testes/ml/conftest.py"):
        codigo += [{"arquivo": str(p.relative_to(comum.RAIZ)).replace("\\", "/"), "sha256": sha(p)}
                   for p in sorted(comum.RAIZ.glob(padrao))]

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=comum.RAIZ, capture_output=True, text=True).stdout.strip()
    xgb = Path(__import__("os").environ.get("NODEWATCH_XGBOOST", ""))
    info_xgb: Dict[str, Any] = {"pasta": "definida por NODEWATCH_XGBOOST (diretório temporário fora do projeto; caminho local não registrado)" if str(xgb) not in ("", ".") else None}
    dist = list(xgb.glob("xgboost-*.dist-info")) if info_xgb["pasta"] else []
    if dist:
        wheel = (dist[0] / "WHEEL").read_text(encoding="utf-8")
        record = (dist[0] / "RECORD").read_text(encoding="utf-8")
        info_xgb.update({"dist_info": dist[0].name, "wheel_tag": re.findall(r"Tag: (\S+)", wheel),
                         "biblioteca_no_RECORD": [l for l in record.splitlines() if l.endswith(tuple("0123456789"))
                                                  and "xgboost.dll" in l],
                         "instalado_em_utc": mtime_utc(dist[0] / "RECORD")})
    return {
        "resultados": resultados,
        "modelos": lista(comum.TRABALHO / "modelos", "*.joblib"),
        "modelos_reproduzidos": [dict(r, arquivo=f"{p}/{r['arquivo']}") for p in ("X11", "X25")
                                 for r in lista(comum.TRABALHO / "reproducao_treinos" / p, "*.joblib")],
        "trabalho": lista(comum.TRABALHO, "*.json") + lista(comum.TRABALHO, "*.sha256") + lista(comum.TRABALHO, "*.joblib")
        + lista(comum.TRABALHO, "*.parquet"),
        "documentos": lista(DOCS, "*.md"),
        "codigo": codigo,
        "git": {"branch": git("rev-parse", "--abbrev-ref", "HEAD"), "head": git("rev-parse", "HEAD"),
                "alteracoes_locais": len(git("status", "--porcelain").splitlines())},
        "ambiente": comum.ambiente(),
        "xgboost_temporario": info_xgb,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dados")
    ap.add_argument("--so-documentos", action="store_true", help="refaz só consistência e inventário")
    a = ap.parse_args()
    anterior = R / "e_auditoria.json"
    saida: Dict[str, Any] = json.loads(anterior.read_text(encoding="utf-8")) if (a.so_documentos and anterior.is_file()) else {}
    if a.so_documentos:
        # Guarda quando as seções que leem as partições foram calculadas.
        saida.setdefault("passada_completa_em_utc", saida.get("gerado_em_utc"))
    else:
        saida["passada_completa_em_utc"] = comum.agora()
    saida.update({"gerado_em_utc": comum.agora(), "script": Path(__file__).name,
                  "aviso": "Só leitura: nenhum modelo foi pontuado e nenhum período foi consultado."})
    if not a.so_documentos:
        sob = sobreposicao(comum.pasta_dados(a.dados))
        pos_linhas = sob.pop("_pos_linhas")
        saida["sobreposicao"] = sob
        saida["bootstrap"] = bootstrap(pos_linhas)
        saida["criterio_emenda3"] = criterio_emenda3()
        saida["artefato_producao"] = artefato()
    saida["consistencia"] = consistencia()
    saida["inventario"] = inventario()
    print(comum.salvar_json(saida, "e_auditoria.json"))


if __name__ == "__main__":
    main()
