"""Reprodução dos treinos X11 (rodada 1) e X25 (Emenda 2) numa pasta isolada.

Refaz a mesma grade, com o mesmo código de treino (``c_treinar_avaliar.ajustar``),
as mesmas entradas gravadas, a mesma semente e o mesmo número de threads, e
compara cada modelo reproduzido com o original:

* SHA-256 do arquivo ``.joblib`` (mesmo ``joblib.dump(..., compress=3)``);
* configuração aprendida (coeficientes, árvores, iterações, booster);
* previsões na **validação purgada de 07 e 08/08**, divisão já usada na escolha.
  Essa comparação serve só para conferir a reprodução do treino; não escolhe
  nem ajusta nada.

Não lê os dias 13 a 23/08, não altera ``modelos/``, ``escolhas*.json``,
``preparador_L.joblib``, ``consultas.json``, o artefato de produção nem os
resultados existentes: os hashes desses arquivos são conferidos antes e depois.

Grava os modelos em ``artefatos_ml/hi_large/reproducao_treinos/<execução>/`` e
o resumo em ``resultados/g_reproducao_treinos.json``.

Uso::

    python scripts/hi_large/g_reproduzir_treinos.py [--execucoes X11 X25]
"""

from __future__ import annotations

import argparse
import base64
import gc
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

import comum
import c_treinar_avaliar as c
from src.ml.avaliacao import limiar_max_f1
from src.ml.modelos import ModeloUnificado

SAIDA = comum.TRABALHO / "reproducao_treinos"
EXECUCOES = {
    "X11": {"descricao": "rodada 1: grade nas fontes L e S+L (HI-Small do lote antigo)",
            "fontes": {"L": None, "S+L": "hismall_treino_S_lote_antigo.parquet"},
            "prefixo": "", "validacao": "c_validacao.json", "escolhas": "escolhas.json"},
    "X25": {"descricao": "Emenda 2: grade na fonte S+L (HI-Small do lote corrigido)",
            "fontes": {"S+L": "hismall_treino_S.parquet"},
            "prefixo": "corrigido__", "validacao": "c_validacao_emenda2.json", "escolhas": "escolhas_emenda2.json"},
}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 22), b""):
            h.update(bloco)
    return h.hexdigest()


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(comum.RAIZ)).replace("\\", "/")
    except ValueError:
        return str(p)


def mtime_utc(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")


def protegidos() -> Dict[str, str]:
    arqs = (list((comum.TRABALHO / "modelos").glob("*.joblib")) + list(comum.TRABALHO.glob("escolhas*.json"))
            + [comum.TRABALHO / "preparador_L.joblib", comum.TRABALHO / "consultas.json",
               comum.RAIZ / "artefatos_ml" / "modelo_unificado.joblib"] + list(comum.RESULTADOS.glob("*.json")))
    return {str(p.relative_to(comum.RAIZ)).replace("\\", "/"): sha(p) for p in sorted(arqs)
            if p.name != "g_reproducao_treinos.json"}


def insumos(cols: List[str]) -> Dict[str, Any]:
    arqs = [comum.TRABALHO / "atributos_L" / f"dia={d:03d}.parquet" for d in range(0, 8)]
    arqs += [comum.TRABALHO / f for f in ("hismall_treino_S_lote_antigo.parquet", "hismall_treino_S.parquet",
                                          "padroes_casados.parquet")]
    arqs += [comum.RAIZ / "artefatos_ml" / "modelo_unificado.joblib"]
    codigo = [comum.RAIZ / "scripts" / "hi_large" / n for n in ("c_treinar_avaliar.py", "comum.py", Path(__file__).name)]
    codigo += [comum.RAIZ / "src" / "ml" / n for n in ("modelos.py", "preparacao.py", "avaliacao.py")]
    xgb_dir = Path(os.environ.get("NODEWATCH_XGBOOST", ""))
    dll = xgb_dir / "xgboost" / "lib" / "xgboost.dll"
    record = next(iter(xgb_dir.glob("xgboost-*.dist-info/RECORD")), None) if str(xgb_dir) not in ("", ".") else None
    sp = comum.RAIZ / ".venv" / "Lib" / "site-packages"
    corte = datetime(2026, 11, 9, tzinfo=timezone.utc).timestamp()
    import joblib as jl
    import scipy
    return {
        "arquivos": [{"arquivo": str(p.relative_to(comum.RAIZ)).replace("\\", "/"), "sha256": sha(p),
                      "bytes": p.stat().st_size, "modificado_em_utc": mtime_utc(p)} for p in arqs],
        "codigo": [{"arquivo": str(p.relative_to(comum.RAIZ)).replace("\\", "/"), "sha256": sha(p)} for p in codigo],
        "colunas": cols,
        "ambiente": comum.ambiente(),
        "joblib": jl.__version__, "scipy": scipy.__version__,
        "semente": comum.SEMENTE, "threads": comum.THREADS,
        "xgboost": {"pasta": "definida por NODEWATCH_XGBOOST (diretório temporário fora do projeto; caminho local não registrado)" if dll.is_file() else None,
                    "dll_sha256_base64": base64.urlsafe_b64encode(bytes.fromhex(sha(dll))).decode().rstrip("=")
                    if dll.is_file() else None,
                    "dll_no_RECORD": [l for l in record.read_text(encoding="utf-8").splitlines() if "xgboost.dll" in l]
                    if record else None},
        "pacotes_do_venv_alterados_desde_09_11": sorted(p.name for p in sp.glob("*.dist-info")
                                                         if p.stat().st_mtime >= corte),
    }


def carregar_hismall(arquivo: str, cols: List[str]):
    # O mesmo que c.carregar_hismall_treino, mas com o arquivo indicado.
    df = pd.read_parquet(comum.TRABALHO / arquivo)
    return df[cols].astype(np.float32), df[[k for k in df.columns if k.startswith("_")]]


def comparar_configuracao(orig: Any, rep: Any) -> Dict[str, Any]:
    """Compara o que foi aprendido, passo a passo do pipeline."""
    saida: Dict[str, Any] = {}
    vt_o, vt_r = orig.named_steps["constantes"], rep.named_steps["constantes"]
    saida["colunas_mantidas_iguais"] = bool(np.array_equal(vt_o.get_support(), vt_r.get_support()))
    eo, er = orig.steps[-1][1], rep.steps[-1][1]
    po, pr = eo.get_params(), er.get_params()
    saida["parametros_iguais"] = {k: po[k] for k in po if repr(po[k]) != repr(pr.get(k))} or True
    nome = type(eo).__name__
    saida["estimador"] = nome
    if nome == "LogisticRegression":
        saida["coef_max_dif_abs"] = float(np.max(np.abs(eo.coef_ - er.coef_)))
        saida["intercept_dif_abs"] = float(np.max(np.abs(eo.intercept_ - er.intercept_)))
        saida["n_iter"] = [np.atleast_1d(eo.n_iter_).tolist(), np.atleast_1d(er.n_iter_).tolist()]
        for passo in ("imputacao", "escala"):
            a, b = orig.named_steps[passo], rep.named_steps[passo]
            attr = "statistics_" if passo == "imputacao" else "mean_"
            saida[f"{passo}_igual"] = bool(np.array_equal(getattr(a, attr), getattr(b, attr)))
    elif nome == "RandomForestClassifier":
        saida["arvores"] = [len(eo.estimators_), len(er.estimators_)]
        iguais = 0
        for a, b in zip(eo.estimators_, er.estimators_):
            ta, tb = a.tree_, b.tree_
            if (ta.node_count == tb.node_count and np.array_equal(ta.feature, tb.feature)
                    and np.array_equal(ta.threshold, tb.threshold) and np.array_equal(ta.value, tb.value)):
                iguais += 1
        saida["arvores_identicas"] = iguais
    elif nome == "HistGradientBoostingClassifier":
        saida["n_iter"] = [int(eo.n_iter_), int(er.n_iter_)]
        iguais = 0
        for la, lb in zip(eo._predictors, er._predictors):
            if all(np.array_equal(pa.nodes, pb.nodes) for pa, pb in zip(la, lb)):
                iguais += 1
        saida["iteracoes_identicas"] = iguais
    elif nome == "XGBClassifier":
        saida["best_iteration"] = [int(eo.best_iteration), int(er.best_iteration)]
        bo, br = bytes(eo.get_booster().save_raw("ubj")), bytes(er.get_booster().save_raw("ubj"))
        saida["booster_bytes_iguais"] = bo == br
        saida["booster_sha256"] = [hashlib.sha256(bo).hexdigest(), hashlib.sha256(br).hexdigest()]
    return saida


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execucoes", nargs="+", default=["X11", "X25"], choices=sorted(EXECUCOES))
    a = ap.parse_args()
    if not c.xgb_disponivel():
        raise SystemExit("XGBoost indisponível: defina NODEWATCH_XGBOOST (os treinos originais o usaram).")
    antes = protegidos()
    modelo = ModeloUnificado.carregar(comum.RAIZ / "artefatos_ml")  # só para a ordem das colunas
    cols = list(modelo.codificadores["financeiro"].colunas)
    del modelo
    saida: Dict[str, Any] = {"gerado_em_utc": comum.agora(), "script": Path(__file__).name,
                             "aviso": ("Reprodução de treinos. A validação de 07 e 08/08 só confere a reprodução; "
                                       "nenhum modelo, parâmetro ou limiar foi escolhido ou ajustado aqui, e os "
                                       "dias 13 a 23/08 não foram lidos."),
                             "insumos": insumos(cols), "execucoes": {}}
    pasta_L = comum.TRABALHO / "atributos_L"
    Xtr_L, mtr_L = c.carregar(pasta_L, range(0, 6), cols)
    Xva_tudo, mva_tudo = c.carregar(pasta_L, c.DIAS["validacao"], cols)
    manter = c.manter_purgado(mva_tudo, c.inicio_periodo("validacao"))
    Xva = Xva_tudo.loc[manter].reset_index(drop=True)
    yva = mva_tudo["_rotulo"].to_numpy()[manter]
    del Xva_tudo, mva_tudo
    ytr_L, wtr_L = mtr_L["_rotulo"].to_numpy(), mtr_L["_peso"].to_numpy()
    saida["validacao_purgada"] = {"linhas": int(len(yva)), "positivos": int(yva.sum())}
    comum.log(f"treino L {len(Xtr_L):,} linhas; validação purgada {len(Xva):,} ({int(yva.sum()):,} positivos)")
    for ex in a.execucoes:
        cfg = EXECUCOES[ex]
        destino = SAIDA / ex
        destino.mkdir(parents=True, exist_ok=True)
        assert destino.resolve() != (comum.TRABALHO / "modelos").resolve()
        registro = comum.ler_json(cfg["validacao"])
        escolhas = json.loads((comum.TRABALHO / cfg["escolhas"]).read_text(encoding="utf-8"))
        res_ex: Dict[str, Any] = {"descricao": cfg["descricao"], "fontes": {}}
        for fonte, arq_hs in cfg["fontes"].items():
            if arq_hs is None:
                Xtr, ytr, wtr = Xtr_L, ytr_L, wtr_L
            else:
                Xs, ms = carregar_hismall(arq_hs, cols)
                Xtr = pd.concat([Xs, Xtr_L], ignore_index=True)
                ytr = np.concatenate([ms["_rotulo"].to_numpy(), ytr_L])
                wtr = np.concatenate([ms["_peso"].to_numpy(), wtr_L])
                del Xs, ms
            res_f: Dict[str, Any] = {"treino": {"linhas": int(len(Xtr)), "positivos": int(ytr.sum()),
                                                "amostra_hismall": arq_hs}, "candidatos": {}}
            ap_rep: Dict[str, float] = {}
            for familia, params in c.GRADE:
                n = c.nome(familia, params)
                arquivo = f"{cfg['prefixo']}{fonte.replace('+', '_')}__{n}.joblib".replace(" ", "")
                original = comum.TRABALHO / "modelos" / arquivo
                reg = registro["fontes"][fonte]["candidatos"][n]
                comum.log(f"{ex} {fonte}: {n}")
                pipe, info = c.ajustar(familia, params, Xtr, ytr, wtr, Xva, yva)
                caminho = destino / arquivo
                joblib.dump(pipe, caminho, compress=3)
                sha_rep, sha_orig = sha(caminho), sha(original)
                orig = joblib.load(original)
                s_rep, _ = c.pontuar(pipe, Xva)
                s_orig, _ = c.pontuar(orig, Xva)
                ap_r, ap_o = float(average_precision_score(yva, s_rep)), float(average_precision_score(yva, s_orig))
                lim_r, lim_o = limiar_max_f1(yva, s_rep), limiar_max_f1(yva, s_orig)
                ap_rep[n] = ap_r
                linha = {
                    "arquivo_original": f"artefatos_ml/hi_large/modelos/{arquivo}",
                    "arquivo_reproduzido": rel(caminho),
                    "sha256_original": sha_orig, "sha256_reproduzido": sha_rep,
                    "sha256_registrado": reg["modelo"]["sha256"],
                    "arquivo_identico": sha_orig == sha_rep,
                    "treino_s": {"registrado": reg.get("treino_s"), "reproducao": info["treino_s"]},
                    "previsoes_validacao": {
                        "max_dif_abs": float(np.max(np.abs(s_rep - s_orig))),
                        "linhas_com_diferenca": int((s_rep != s_orig).sum()),
                        "ap_registrada": reg["ap_validacao"], "ap_original_agora": ap_o, "ap_reproducao": ap_r,
                        "limiar_registrado": reg["limiar"]["limiar"], "limiar_original_agora": lim_o["limiar"],
                        "limiar_reproducao": lim_r["limiar"]},
                }
                if "arvores_usadas" in info:
                    linha["arvores_xgboost"] = {"registrado": reg.get("arvores_usadas"), "reproducao": info["arvores_usadas"]}
                if not linha["arquivo_identico"]:
                    linha["configuracao_aprendida"] = comparar_configuracao(orig, pipe)
                res_f["candidatos"][n] = linha
                comum.log(f"   idêntico={linha['arquivo_identico']}; máx dif. de score {linha['previsoes_validacao']['max_dif_abs']:.3g}; "
                          f"AP {ap_r:.4f} (registrada {reg['ap_validacao']:.4f}); treino {info['treino_s']} s")
                del pipe, orig, s_rep, s_orig
                gc.collect()
            escolhido_rep = max(ap_rep, key=ap_rep.get)
            res_f["conferencia_da_escolha"] = {
                "registrado": registro["fontes"][fonte]["escolhido"], "pela_reproducao": escolhido_rep,
                "igual": escolhido_rep == registro["fontes"][fonte]["escolhido"],
                "escolhas_json": escolhas["fontes"].get(fonte)}
            res_ex["fontes"][fonte] = res_f
            if arq_hs is not None:
                del Xtr, ytr, wtr
            gc.collect()
        saida["execucoes"][ex] = res_ex
    depois = protegidos()
    saida["arquivos_protegidos"] = {"conferidos": len(antes), "alterados": sorted(k for k in antes if antes[k] != depois.get(k)),
                                    "novos_ou_removidos": sorted(set(antes) ^ set(depois))}
    saida["pico_memoria_mb"] = comum.memoria_processo_mb()
    print(comum.salvar_json(saida, "g_reproducao_treinos.json"))


if __name__ == "__main__":
    main()
