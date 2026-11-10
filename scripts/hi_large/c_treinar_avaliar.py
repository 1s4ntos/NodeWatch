"""Treino, escolha na validação e avaliação única (teste, reserva) no HI-Large.

Etapas, em ordem (cada uma grava um JSON em ``docs/ml/hi_large/resultados``):

``validacao``  treina a grade nas fontes L e S+L, escolhe pela AP na
               validação do HI-Large, fixa limiares e regras, mede latência e
               congela tudo em ``artefatos_ml/hi_large/escolhas.json``.
``teste``      avalia uma única vez nos dias 9 e 10 (recusa repetir).
``reserva``    confirma uma única vez nos dias 11 e 12, só com os escolhidos.
``hismall``    aplica os escolhidos ao teste do HI-Small (já consultado antes;
               só descritivo).
``final2``     Emenda 2: teste final novo, dias 13 a 16 (``final2_rf``: florestas, descritivo).
``final3``     Emenda 3: segundo teste final, dias 17 a 23, com os modelos congelados.

O XGBoost é opcional: entra se ``NODEWATCH_XGBOOST`` apontar para a pasta de
um ``pip install --target`` (fora do ``.venv``).

Uso::

    python scripts/hi_large/c_treinar_avaliar.py --etapa validacao
"""

from __future__ import annotations

import argparse
import copy
import gc
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.metrics import average_precision_score

import comum
from src.ml.avaliacao import limiar_max_f1, metricas_binarias, recall_por_grupo
from src.ml.modelos import ModeloUnificado, _copia_uma_thread, recriar_estimador
from src.ml.preparacao import PreparadorFinanceiro, montar_pipeline_financeiro

if os.environ.get("NODEWATCH_XGBOOST"):
    sys.path.append(os.environ["NODEWATCH_XGBOOST"])

ESCOLHAS = comum.TRABALHO / "escolhas.json"
ESCOLHAS_EMENDA2 = comum.TRABALHO / "escolhas_emenda2.json"  # S+L refeita com o lote corrigido
CONSULTAS = comum.TRABALHO / "consultas.json"
MODELOS = comum.TRABALHO / "modelos"
DIAS = {"validacao": (6, 7), "teste": (8, 9), "reserva": (10, 11), "teste_final2": (12, 13, 14, 15),
        "teste_final3": tuple(range(16, 23))}  # Emenda 3: 17 a 23/08/2022
ARTEFATO_SHA256_EMENDA3 = "28a13a1873f4896a0ede445070cf5adff907b88007e3f25ab4ca5cf6dbcdb4aa"
_EPOCA_DIA0 = int((pd.Timestamp("2022-08-01") - pd.Timestamp("1970-01-01")) // pd.Timedelta(minutes=1))

GRADE: List[Tuple[str, Dict[str, Any]]] = [
    ("logistica", {"C": 0.1}),
    ("logistica", {"C": 1.0}),
    ("random_forest", {"n_estimators": 100, "min_samples_leaf": 50, "max_samples": 0.5}),
    ("random_forest", {"n_estimators": 200, "min_samples_leaf": 10, "max_samples": 0.5}),
    ("hist_gradient_boosting", {"max_iter": 300, "learning_rate": 0.1, "max_leaf_nodes": 31, "l2_regularization": 1.0}),
    ("hist_gradient_boosting", {"max_iter": 300, "learning_rate": 0.1, "max_leaf_nodes": 63, "l2_regularization": 1.0}),
    ("xgboost", {"max_depth": 6, "min_child_weight": 10}),
    ("xgboost", {"max_depth": 8, "min_child_weight": 10}),
]


def nome(familia: str, params: Dict[str, Any]) -> str:
    return f"{familia}[" + ",".join(f"{k}={v}" for k, v in params.items()) + "]"


def xgb_disponivel() -> Optional[str]:
    try:
        import xgboost
        return xgboost.__version__
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------
def pasta_atributos(fonte: str, sufixo: str = "") -> Path:
    """Atributos com o preparador da fonte: L se existir passada própria, senão S (preparadores iguais)."""
    s = f"_{sufixo}" if sufixo else ""
    pl = comum.TRABALHO / f"atributos_L{s}"
    return pl if fonte == "L" and any(pl.glob("dia=*.parquet")) else comum.TRABALHO / f"atributos_S{s}"


def carregar(pasta: Path, dias, colunas: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    # Separa atributos (float32) e metadados dia a dia, para não ter duas cópias do período na memória.
    xs, ms = [], []
    for d in dias:
        df = pq.read_table(pasta / f"dia={d:03d}.parquet").to_pandas()
        ms.append(df[[c for c in df.columns if c.startswith("_")]].copy())
        xs.append(df[colunas].astype(np.float32))
        del df
    X = pd.concat(xs, ignore_index=True)
    del xs
    meta = pd.concat(ms, ignore_index=True)
    return X, meta


def carregar_hismall_treino(colunas: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_parquet(comum.TRABALHO / "hismall_treino_S.parquet")
    return df[colunas].astype(np.float32), df[[c for c in df.columns if c.startswith("_")]]


EMENDA = comum.RAIZ / "docs" / "ml" / "hi_large" / "EMENDA_1_PURGA_POR_TENTATIVA.md"
EMENDA2 = comum.RAIZ / "docs" / "ml" / "hi_large" / "EMENDA_2_LOTE_CORRIGIDO_E_TESTE_FINAL.md"
EMENDA3 = comum.RAIZ / "docs" / "ml" / "hi_large" / "EMENDA_3_SEGUNDO_TESTE_FINAL.md"


def inicio_periodo(periodo: str) -> int:
    return _EPOCA_DIA0 + DIAS[periodo][0] * 1440


def manter_purgado(meta: pd.DataFrame, inicio: int) -> np.ndarray:
    """Emenda 1: tira os positivos de tentativas iniciadas antes do período avaliado.

    Negativos e positivos sem padrão ficam. Os padrões só decidem quais linhas
    são avaliadas; nunca viram atributo.
    """
    pp = pd.read_parquet(comum.TRABALHO / "padroes_casados.parquet", columns=["tentativa", "minuto", "linha"])
    ini = pp["tentativa"].map(pp.groupby("tentativa")["minuto"].min())
    comeco = pd.Series(ini.to_numpy(), index=pp["linha"].astype(np.int64).to_numpy())
    c = meta["_linha"].map(comeco)
    continuacao = (meta["_rotulo"].to_numpy() == 1) & c.notna().to_numpy() & (c.to_numpy() < inicio)
    return ~continuacao


def hashes_protocolo() -> Dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (comum.PLANO, EMENDA)}


def grupos_padrao(meta: pd.DataFrame, inicio_periodo: int) -> Tuple[pd.Series, pd.Series]:
    """Tipo de padrão e se a tentativa começou antes do período (positivos sem padrão: sem_padrao)."""
    pp = pd.read_parquet(comum.TRABALHO / "padroes_casados.parquet", columns=["tentativa", "tipo_padrao", "minuto", "linha"])
    ini = pp.groupby("tentativa")["minuto"].min()
    pp = pp.dropna(subset=["linha"])
    pp["linha"] = pp["linha"].astype(np.int64)
    pp["inicio"] = pp["tentativa"].map(ini)
    pp = pp.set_index("linha")
    tipo = meta["_linha"].map(pp["tipo_padrao"]).fillna("sem_padrao").astype(str)
    comeco = meta["_linha"].map(pp["inicio"])
    tentativa = np.where(comeco.isna(), "sem_padrao", np.where(comeco < inicio_periodo, "iniciada_antes", "nova"))
    return tipo, pd.Series(tentativa, index=meta.index)


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
def criar_xgb(params: Dict[str, Any], n_arvores: Optional[int] = None):
    import xgboost as xgb
    kw: Dict[str, Any] = dict(tree_method="hist", device="cpu", n_jobs=comum.THREADS, learning_rate=0.1,
                              max_bin=256, subsample=1.0, colsample_bytree=1.0, reg_lambda=1.0,
                              random_state=comum.SEMENTE, n_estimators=n_arvores or 1000,
                              objective="binary:logistic", eval_metric="aucpr")
    if n_arvores is None:
        kw["early_stopping_rounds"] = 50
    kw.update(params)
    return xgb.XGBClassifier(**kw)


def ajustar(familia: str, params: Dict[str, Any], Xtr, ytr, wtr, Xva, yva) -> Tuple[Any, Dict[str, Any]]:
    info: Dict[str, Any] = {}
    pipe = montar_pipeline_financeiro(None, familia == "logistica")
    pre = pipe[:-1]
    t0 = time.perf_counter()
    Ztr = pre.fit_transform(Xtr)
    if familia == "xgboost":
        est = criar_xgb(params)
        est.fit(Ztr, ytr, sample_weight=wtr, eval_set=[(pre.transform(Xva), yva)], verbose=False)
        info["arvores_usadas"] = int(est.best_iteration + 1)
    else:
        est = recriar_estimador(familia, params, comum.SEMENTE, comum.THREADS)
        est.fit(Ztr, ytr, sample_weight=wtr)
        if familia == "logistica":
            info["n_iter"] = np.atleast_1d(est.n_iter_).tolist()
    info["treino_s"] = round(time.perf_counter() - t0, 1)
    pipe.steps[-1] = ("modelo", est)
    return pipe, info


def pontuar(pipe: Any, X: pd.DataFrame, lote: int = 250_000) -> Tuple[np.ndarray, float]:
    t0 = time.perf_counter()
    idx = list(pipe.classes_).index(1)
    s = np.concatenate([pipe.predict_proba(X.iloc[i:i + lote])[:, idx] for i in range(0, len(X), lote)])
    return s, len(X) / max(time.perf_counter() - t0, 1e-9)


def latencia_uma_linha(pipe: Any, X: pd.DataFrame, n: int = 200) -> Dict[str, float]:
    p1 = _copia_uma_thread(pipe)
    linhas = X.sample(n, random_state=comum.SEMENTE)
    for i in range(10):
        p1.predict_proba(linhas.iloc[i:i + 1])
    ts = []
    for i in range(n):
        t0 = time.perf_counter()
        p1.predict_proba(linhas.iloc[i:i + 1])
        ts.append((time.perf_counter() - t0) * 1000)
    return {"mediana_ms": float(np.median(ts)), "p99_ms": float(np.percentile(ts, 99)), "n": n}


def salvar_modelo(pipe: Any, arquivo: str) -> Dict[str, Any]:
    MODELOS.mkdir(parents=True, exist_ok=True)
    caminho = MODELOS / arquivo
    joblib.dump(pipe, caminho, compress=3)
    return {"arquivo": arquivo, "bytes": caminho.stat().st_size,
            "sha256": hashlib.sha256(caminho.read_bytes()).hexdigest()}


def carregar_modelo(info: Dict[str, Any]) -> Any:
    caminho = MODELOS / info["arquivo"]
    if hashlib.sha256(caminho.read_bytes()).hexdigest() != info["sha256"]:
        raise SystemExit(f"{caminho.name} mudou depois de congelado.")
    return joblib.load(caminho)


# ---------------------------------------------------------------------------
# Regras explícitas (mesmas definições da auditoria de 02/11/2026)
# ---------------------------------------------------------------------------
def flags(X: pd.DataFrame, formato: np.ndarray, prep: PreparadorFinanceiro) -> Dict[str, np.ndarray]:
    fator = pd.Series(formato).map(prep.taxa_formato).fillna(0).to_numpy() / prep.taxa_base
    q = prep.quantis
    return {
        "formato_risco_5x": fator >= 5,
        "par_novo": X["par_novo"].to_numpy() == 1,
        "envios_24h_acima_p99": X["n_env_origem_24h"].to_numpy() > q["n_env_origem_24h_p99"],
        "fan_in_acima_p99": X["orig_distintas_destino"].to_numpy() > q["orig_distintas_destino_p99"],
        "fan_out_acima_p99": X["dest_distintos_origem"].to_numpy() > q["dest_distintos_origem_p99"],
        "valor_atipico_z3": np.abs(X["z_valor_origem"].to_numpy()) > 3,
        "repasse_menos_60min": X["min_desde_rec_origem"].to_numpy() < 60,
        "moedas_diferentes": X["moeda_diferente"].to_numpy() == 1,
    }


def conjuncoes(fl: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    fan = fl["fan_in_acima_p99"] | fl["fan_out_acima_p99"]
    return {
        "formato_risco & par_novo": fl["formato_risco_5x"] & fl["par_novo"],
        "formato_risco & repasse<60min": fl["formato_risco_5x"] & fl["repasse_menos_60min"],
        "formato_risco & (fan>p99 | repasse<60min)": fl["formato_risco_5x"] & (fan | fl["repasse_menos_60min"]),
        "formato_risco & par_novo & (fan>p99 | repasse<60min)":
            fl["formato_risco_5x"] & fl["par_novo"] & (fan | fl["repasse_menos_60min"]),
    }


def decisao(y: np.ndarray, alerta: np.ndarray) -> Dict[str, Any]:
    y = y.astype(bool)
    tp, fp, fn = int((alerta & y).sum()), int((alerta & ~y).sum()), int((~alerta & y).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"alertas": tp + fp, "verdadeiros_positivos": tp, "falsos_positivos": fp, "falsos_negativos": fn,
            "verdadeiros_negativos": int(len(y) - tp - fp - fn), "precisao": p, "recall": r,
            "f1": 2 * p * r / (p + r) if p + r else 0.0, "falsos_alertas_por_10k": fp / len(y) * 10_000}


# ---------------------------------------------------------------------------
# AP ponderada (bootstrap pareado por conta de origem)
# ---------------------------------------------------------------------------
def _preparar_ap(y: np.ndarray, s: np.ndarray):
    ordem = np.argsort(-s, kind="mergesort")
    ss = s[ordem]
    fim = np.r_[np.flatnonzero(np.diff(ss) != 0), len(ss) - 1]
    return ordem, y[ordem].astype(np.float64), fim


def _ap_peso(ys: np.ndarray, fim: np.ndarray, w: np.ndarray) -> float:
    tp = np.cumsum(w * ys)[fim]
    tot = np.cumsum(w)[fim]
    rec = tp / tp[-1]
    prec = np.divide(tp, tot, out=np.zeros_like(tp), where=tot > 0)
    return float(np.sum(np.diff(np.r_[0.0, rec]) * prec))


def bootstrap_pareado(y: np.ndarray, sa: np.ndarray, sb: np.ndarray, grupo: np.ndarray, b: int = 1000) -> Dict[str, Any]:
    """Diferença de AP (a − b), reamostrando contas de origem inteiras (pesos de Poisson)."""
    _, inv = np.unique(grupo, return_inverse=True)
    oa, ya, fa = _preparar_ap(y, sa)
    ob, yb, fb = _preparar_ap(y, sb)
    base = _ap_peso(ya, fa, np.ones(len(y))) - _ap_peso(yb, fb, np.ones(len(y)))
    assert abs(_ap_peso(ya, fa, np.ones(len(y))) - average_precision_score(y, sa)) < 1e-9
    rng = np.random.default_rng(comum.SEMENTE)
    difs = np.empty(b)
    ga, gb = inv[oa], inv[ob]
    for i in range(b):
        W = rng.poisson(1.0, inv.max() + 1).astype(np.float64)
        difs[i] = _ap_peso(ya, fa, W[ga]) - _ap_peso(yb, fb, W[gb])
    return {"diferenca_ap": base, "ic95": [float(np.percentile(difs, 2.5)), float(np.percentile(difs, 97.5))],
            "fracao_maior_que_zero": float((difs > 0).mean()), "reamostras": b,
            "metodo": "bootstrap de Poisson pareado, agrupado por conta de origem"}


# ---------------------------------------------------------------------------
# Etapas
# ---------------------------------------------------------------------------
def etapa_validacao(emenda2: bool = False) -> None:
    """Sem ``emenda2``: fontes L e S+L (escolhas.json). Com ``emenda2``: só S+L, com a amostra do
    HI-Small recalculada pelo lote corrigido; congela em escolhas_emenda2.json e não toca no resto."""
    fontes = ("S+L",) if emenda2 else ("L", "S+L")
    arq_escolhas = ESCOLHAS_EMENDA2 if emenda2 else ESCOLHAS
    prefixo = "corrigido__" if emenda2 else ""
    saida: Dict[str, Any] = {"gerado_em_utc": comum.agora(), "etapa": "validacao", "ambiente": comum.ambiente(),
                             "xgboost": xgb_disponivel(), "fontes": {}}
    modelo = ModeloUnificado.carregar(comum.RAIZ / "artefatos_ml")
    cab_s = modelo.cabeca("lavagem")
    ps: PreparadorFinanceiro = modelo.codificadores["financeiro"]
    pl: PreparadorFinanceiro = joblib.load(comum.TRABALHO / "preparador_L.joblib")
    cols = list(ps.colunas)
    if list(pl.colunas) != cols:
        raise SystemExit("As colunas de P_L e P_S diferem; alinhe antes de combinar as fontes.")
    pasta_L = pasta_atributos("L")
    saida["atributos_L_de"] = pasta_L.name
    Xtr_L, mtr_L = carregar(pasta_L, range(0, 6), cols)
    pl.registrar_quantis(Xtr_L)
    joblib.dump(pl, comum.TRABALHO / "preparador_L.joblib")
    Xva_tudo, mva_tudo = carregar(pasta_L, DIAS["validacao"], cols)
    manter = manter_purgado(mva_tudo, inicio_periodo("validacao"))
    yva_tudo = mva_tudo["_rotulo"].to_numpy()
    Xva, mva = Xva_tudo.loc[manter].reset_index(drop=True), mva_tudo.loc[manter].reset_index(drop=True)
    yva = mva["_rotulo"].to_numpy()
    saida["protocolo_sha256"] = hashes_protocolo()
    saida["validacao"] = {"n": int(len(yva)), "positivos": int(yva.sum()), "prevalencia": float(yva.mean()),
                          "sem_purga": {"n": int(len(yva_tudo)), "positivos": int(yva_tudo.sum())},
                          "positivos_retirados_pela_purga": int(yva_tudo.sum() - yva.sum())}
    comum.log(f"treino L {len(Xtr_L):,} linhas ({int(mtr_L['_rotulo'].sum()):,} positivos); validação {len(Xva):,}")

    # Modelo atual congelado (S) na validação do HI-Large, com os atributos do próprio preparador.
    pasta_S = comum.TRABALHO / "atributos_S"
    Xva_S = Xva if pasta_S == pasta_L else carregar(pasta_S, DIAS["validacao"], cols)[0].loc[manter].reset_index(drop=True)
    t0 = time.perf_counter()
    s_S = cab_s.probabilidades(Xva_S)[:, list(cab_s.classes).index(1)]
    saida["modelo_atual_S"] = {
        "versao": cab_s.metadados.get("versao"), "ap_validacao": float(average_precision_score(yva, s_S)),
        "limiar_artefato": cab_s.limiar_alerta,
        "no_limiar_do_artefato": decisao(yva, s_S >= cab_s.limiar_alerta),
        "limiar_recalculado_na_validacao_hilarge": limiar_max_f1(yva, s_S),
        "pontuacao_linhas_por_s": round(len(yva) / (time.perf_counter() - t0)),
        "latencia_uma_linha": latencia_uma_linha(cab_s.pipeline, Xva_S)}
    if Xva_S is not Xva:
        del Xva_S

    # Referências: prevalência, taxa do formato e regras (preparador e quantis do treino do HI-Large).
    fmt_va = mva["_formato"].to_numpy()
    taxa = pd.Series(fmt_va).map(pl.taxa_formato).fillna(pl.taxa_base).to_numpy()
    fl = flags(Xva, fmt_va, pl)
    motivos = np.sum(np.stack(list(fl.values())), axis=0)
    f1_k = {k: decisao(yva, motivos >= k)["f1"] for k in range(1, 9)}
    k_best = max(f1_k, key=f1_k.get)
    conj = {n: decisao(yva, a) for n, a in conjuncoes(fl).items()}
    conj_best = max(conj, key=lambda n: conj[n]["f1"])
    saida["referencias"] = {
        "prevalencia_ap": float(yva.mean()),
        "taxa_formato": {"ap": float(average_precision_score(yva, taxa)), "limiar": limiar_max_f1(yva, taxa)},
        "F2_motivos": {"ap": float(average_precision_score(yva, motivos)), "f1_por_k": f1_k, "k": k_best},
        "F3_conjuncoes": conj, "F3_escolhida": conj_best,
        "frequencia_flags_positivos": {n: float(v[yva == 1].mean()) for n, v in fl.items()},
        "frequencia_flags_negativos": {n: float(v[yva == 0].mean()) for n, v in fl.items()},
        "quantis_p99_treino_L": pl.quantis, "taxa_formato_treino_L": pl.taxa_formato, "taxa_base_treino_L": pl.taxa_base,
    }
    del fl, motivos, taxa

    escolhas: Dict[str, Any] = {"congelado_em_utc": None, "modelo_atual_S": {
        "limiar_artefato": cab_s.limiar_alerta,
        "limiar_validacao_hilarge": saida["modelo_atual_S"]["limiar_recalculado_na_validacao_hilarge"]["limiar"]},
        "referencias": {"taxa_formato_limiar": saida["referencias"]["taxa_formato"]["limiar"]["limiar"],
                        "F2_k": k_best, "F3": conj_best}, "fontes": {}, "candidatos": {}}
    ytr_L, wtr_L = mtr_L["_rotulo"].to_numpy(), mtr_L["_peso"].to_numpy()
    for fonte in fontes:
        if fonte == "L":
            Xtr, ytr, wtr = Xtr_L, ytr_L, wtr_L
        else:
            Xs, ms = carregar_hismall_treino(cols)
            Xtr = pd.concat([Xs, Xtr_L], ignore_index=True)
            ytr = np.concatenate([ms["_rotulo"].to_numpy(), ytr_L])
            wtr = np.concatenate([ms["_peso"].to_numpy(), wtr_L])
            del Xs, ms
        res: Dict[str, Any] = {"treino": {"linhas": int(len(Xtr)), "positivos": int(ytr.sum())}, "candidatos": {}}
        melhor = None
        for familia, params in GRADE:
            if familia == "xgboost" and not saida["xgboost"]:
                res["candidatos"][nome(familia, params)] = {"status": "não avaliado: XGBoost indisponível"}
                continue
            comum.log(f"{fonte}: {nome(familia, params)}")
            pipe, info = ajustar(familia, params, Xtr, ytr, wtr, Xva, yva)
            s_tudo, vazao = pontuar(pipe, Xva_tudo)
            s_va = s_tudo[manter]
            ap = float(average_precision_score(yva, s_va))
            ap_sem_purga = float(average_precision_score(yva_tudo, s_tudo))
            lim = limiar_max_f1(yva, s_va)
            arq = salvar_modelo(pipe, f"{prefixo}{fonte.replace('+', '_')}__{nome(familia, params)}.joblib".replace(" ", ""))
            res["candidatos"][nome(familia, params)] = {
                "familia": familia, "params": params, **info, "ap_validacao": ap,
                "ap_validacao_sem_purga": ap_sem_purga, "limiar": lim,
                "pontuacao_linhas_por_s": round(vazao), "modelo": arq,
                "pico_memoria_mb": comum.memoria_processo_mb()}
            escolhas["candidatos"][f"{fonte}|{nome(familia, params)}"] = {"modelo": arq, "limiar": lim["limiar"]}
            comum.log(f"   AP val {ap:.4f}; treino {info['treino_s']} s")
            if melhor is None or ap > melhor[0]:
                melhor = (ap, nome(familia, params))
            del pipe, s_va, s_tudo
            gc.collect()
        res["escolhido"] = melhor[1]
        chave = f"{fonte}|{melhor[1]}"
        pipe = carregar_modelo(escolhas["candidatos"][chave]["modelo"])
        res["latencia_uma_linha_escolhido"] = latencia_uma_linha(pipe, Xva)
        del pipe
        escolhas["fontes"][fonte] = chave
        saida["fontes"][fonte] = res
        if fonte == "S+L":
            del Xtr
        gc.collect()
    escolhas["congelado_em_utc"] = comum.agora()
    if emenda2:
        saida["amostra_hismall"] = "hismall_treino_S.parquet recalculado com o lote corrigido (Emenda 2)"
    arq_escolhas.write_text(json.dumps(escolhas, ensure_ascii=False, indent=1), encoding="utf-8")
    saida["escolhas_sha256"] = hashlib.sha256(arq_escolhas.read_bytes()).hexdigest()
    print(comum.salvar_json(saida, "c_validacao_emenda2.json" if emenda2 else "c_validacao.json"))


def _consultar(periodo: str, forcar: bool) -> int:
    c = json.loads(CONSULTAS.read_text(encoding="utf-8")) if CONSULTAS.is_file() else {}
    if c.get(periodo) and not forcar:
        raise SystemExit(f"O período {periodo} já foi consultado {c[periodo]} vez(es); use --forcar para repetir, "
                         "e declare isso no relatório.")
    c[periodo] = c.get(periodo, 0) + 1
    CONSULTAS.write_text(json.dumps(c, indent=1), encoding="utf-8")
    return c[periodo]


RF_PRODUCAO = "random_forest[n_estimators=100,min_samples_leaf=50,max_samples=0.5]"


def avaliar_periodo(periodo: str, so_escolhidos: bool, forcar: bool, rf_descritivo: bool = False) -> None:
    """``rf_descritivo``: no teste final 2, avalia só as florestas de produção de L e de S+L
    (mesmo tipo do modelo atual), DEPOIS da consulta principal; não decide nada."""
    escolhas = json.loads(ESCOLHAS.read_text(encoding="utf-8"))
    final2 = periodo == "teste_final2"
    if final2:
        # Emenda 2: S (artefato), L escolhido, S+L refeita (lote corrigido) e, só descritiva, a S+L antiga.
        e2 = json.loads(ESCOLHAS_EMENDA2.read_text(encoding="utf-8"))
        chave_sl = e2["fontes"]["S+L"]
        escolhas["candidatos"][f"corrigido|{chave_sl}"] = e2["candidatos"][chave_sl]
        escolhas["fontes"] = {"L": escolhas["fontes"]["L"], "S+L corrigida": f"corrigido|{chave_sl}",
                              "S+L antiga (descritiva)": escolhas["fontes"]["S+L"]}
        if rf_descritivo:
            escolhas["candidatos"][f"corrigido|S+L|{RF_PRODUCAO}"] = e2["candidatos"][f"S+L|{RF_PRODUCAO}"]
            escolhas["fontes"] = {"L": f"L|{RF_PRODUCAO}", "S+L corrigida": f"corrigido|S+L|{RF_PRODUCAO}"}
    final3 = periodo == "teste_final3"
    papeis: Dict[str, str] = {}
    escolhidos_validacao: set = set()
    if final3:
        # Emenda 3: só modelos congelados; nada é retreinado nem escolhido aqui.
        sha_artefato = hashlib.sha256((comum.RAIZ / "artefatos_ml" / "modelo_unificado.joblib").read_bytes()).hexdigest()
        if sha_artefato != ARTEFATO_SHA256_EMENDA3:
            raise SystemExit("O artefato atual mudou depois da Emenda 3.")
        conf = comum.ler_json("b6_conferencia_final3.json")
        for prep_, r in conf["preparadores"].items():
            ok = r["dia_reproduzido"]["identico"] and all(
                x["gravadas"] == x["linhas_da_particao"] and x["positivos_gravados"] == x["positivos_na_particao"]
                and x["linha_repetida"] == 0 and x["fora_da_particao"] == 0 for x in r["dias_novos"].values())
            if not ok or sorted(int(d) for d in r["dias_novos"]) != list(DIAS[periodo]):
                raise SystemExit(f"Conferência dos atributos do preparador {prep_} falhou; a consulta não é feita (Emenda 3).")
        e2 = json.loads(ESCOLHAS_EMENDA2.read_text(encoding="utf-8"))
        sl_xgb, sl_rf, l_xgb, l_rf = e2["fontes"]["S+L"], f"S+L|{RF_PRODUCAO}", escolhas["fontes"]["L"], f"L|{RF_PRODUCAO}"
        escolhas["candidatos"][f"corrigido|{sl_xgb}"] = e2["candidatos"][sl_xgb]
        escolhas["candidatos"][f"corrigido|{sl_rf}"] = e2["candidatos"][sl_rf]
        escolhas["fontes"] = {"S+L corrigida, XGBoost (principal)": f"corrigido|{sl_xgb}",
                              "S+L corrigida, floresta (secundária)": f"corrigido|{sl_rf}",
                              "L, XGBoost (descritivo)": l_xgb, "L, floresta (descritivo)": l_rf}
        papeis = {f"corrigido|{sl_xgb}": "principal", f"corrigido|{sl_rf}": "secundaria",
                  l_xgb: "descritivo", l_rf: "descritivo"}
        escolhidos_validacao = {f"corrigido|{sl_xgb}", l_xgb}
    n_consulta = _consultar(periodo + ("_rf_descritivo" if rf_descritivo else ""), forcar)
    tempos: Dict[str, float] = {}
    t_inicio = time.perf_counter()
    modelo = ModeloUnificado.carregar(comum.RAIZ / "artefatos_ml")
    cab_s = modelo.cabeca("lavagem")
    ps: PreparadorFinanceiro = modelo.codificadores["financeiro"]
    pl: PreparadorFinanceiro = joblib.load(comum.TRABALHO / "preparador_L.joblib")
    cols = list(ps.colunas)
    sufixo = "final2" if final2 else ("final3" if final3 else "")
    pasta_L = pasta_atributos("L", sufixo)
    pasta_S = comum.TRABALHO / (f"atributos_S_{sufixo}" if sufixo else "atributos_S")
    # Modelo atual primeiro, com os atributos do próprio preparador; depois libera a memória.
    t0 = time.perf_counter()
    Xs, meta_s = carregar(pasta_S, DIAS[periodo], cols)
    tempos["carregar_atributos_S"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    s_atual = cab_s.probabilidades(Xs)[:, list(cab_s.classes).index(1)]
    tempos["pontuar_modelo_atual_S"] = time.perf_counter() - t0
    linhas_s = meta_s["_linha"].to_numpy()
    del Xs, meta_s
    gc.collect()
    t0 = time.perf_counter()
    X, meta = carregar(pasta_L, DIAS[periodo], cols)
    tempos["carregar_atributos_L"] = time.perf_counter() - t0
    if not np.array_equal(linhas_s, meta["_linha"].to_numpy()):
        raise SystemExit("As linhas dos atributos S e L não estão na mesma ordem.")
    del linhas_s
    inicio = inicio_periodo(periodo)
    manter = manter_purgado(meta, inicio)
    y_tudo = meta["_rotulo"].to_numpy()
    tipo_tudo, tentativa_tudo = grupos_padrao(meta, inicio)
    y, dia = y_tudo[manter], meta["_dia"].to_numpy()[manter]
    tipo = tipo_tudo[manter].reset_index(drop=True)
    pos = y == 1
    saida: Dict[str, Any] = {"gerado_em_utc": comum.agora(), "etapa": periodo, "consulta_numero": n_consulta,
                             "dias": [str((pd.Timestamp("2022-08-01") + pd.Timedelta(days=d)).date()) for d in DIAS[periodo]],
                             "protocolo_sha256": hashes_protocolo(),
                             "n": int(len(y)), "positivos": int(y.sum()), "prevalencia": float(y.mean()),
                             "sem_purga": {"n": int(len(y_tudo)), "positivos": int(y_tudo.sum()),
                                           "prevalencia": float(y_tudo.mean())},
                             "positivos_retirados_pela_purga": int(y_tudo.sum() - y.sum()),
                             "positivos_por_grupo_sem_purga": {
                                 "tipo": tipo_tudo[y_tudo == 1].value_counts().to_dict(),
                                 "tentativa": tentativa_tudo[y_tudo == 1].value_counts().to_dict()},
                             "modelos": {}}
    scores: Dict[str, np.ndarray] = {}

    def registrar(chave: str, s_tudo: np.ndarray, limiar: float, extra: Optional[Dict[str, Any]] = None) -> None:
        s = s_tudo[manter]
        m = metricas_binarias(y, s, limiar, dia=dia)
        m.pop("curva_pr_resumida", None)
        m["verdadeiros_negativos"] = int(m["n"] - m["verdadeiros_positivos"] - m["falsos_positivos"] - m["falsos_negativos"])
        m["alertas"] = m["verdadeiros_positivos"] + m["falsos_positivos"]
        m["ap_por_dia"] = {str(d): float(average_precision_score(y[dia == d], s[dia == d])) for d in np.unique(dia)}
        alerta = pd.Series(s >= limiar)
        m["recall_por_tipo"] = recall_por_grupo(tipo[pos], alerta[pos])
        a_tudo = pd.Series(s_tudo >= limiar)
        pt = y_tudo == 1
        sp = metricas_binarias(y_tudo, s_tudo, limiar)
        m["sem_purga"] = {k: sp[k] for k in ("n", "positivos", "average_precision", "precisao", "recall", "f1",
                                             "verdadeiros_positivos", "falsos_positivos", "falsos_negativos")}
        m["sem_purga"]["recall_por_tentativa"] = recall_por_grupo(tentativa_tudo[pt], a_tudo[pt])
        m.update(extra or {})
        saida["modelos"][chave] = m

    s = s_atual
    scores["S"] = s
    registrar("S|modelo atual, limiar do artefato", s, escolhas["modelo_atual_S"]["limiar_artefato"])
    registrar("S|modelo atual, limiar recalculado na validação do HI-Large", s,
              escolhas["modelo_atual_S"]["limiar_validacao_hilarge"])
    fmt = meta["_formato"].to_numpy()
    taxa = pd.Series(fmt).map(pl.taxa_formato).fillna(pl.taxa_base).to_numpy()
    registrar("referência|taxa do formato (treino L)", taxa, escolhas["referencias"]["taxa_formato_limiar"])
    if not so_escolhidos:
        fl = {n: v[manter] for n, v in flags(X, fmt, pl).items()}
        motivos = np.sum(np.stack(list(fl.values())), axis=0)
        k = escolhas["referencias"]["F2_k"]
        saida["regras"] = {"F2_motivos_ap": float(average_precision_score(y, motivos)),
                           f"F2_motivos>={k}": decisao(y, motivos >= k),
                           f"F3_{escolhas['referencias']['F3']}": decisao(y, conjuncoes(fl)[escolhas["referencias"]["F3"]])}
        del fl, motivos
    chaves = list(escolhas["fontes"].values()) if so_escolhidos else list(escolhas["candidatos"])
    for chave in chaves:
        info = escolhas["candidatos"][chave]
        pipe = carregar_modelo(info["modelo"])
        s, vazao = pontuar(pipe, X)
        tempos[f"pontuar|{chave}"] = len(X) / vazao
        escolhido = chave in escolhas["fontes"].values()
        extra = {"escolhido_na_validacao": escolhido, "pontuacao_linhas_por_s": round(vazao)}
        if final3:
            extra = {"papel_emenda3": papeis[chave], "escolhido_na_validacao": chave in escolhidos_validacao,
                     "pontuacao_linhas_por_s": round(vazao)}
        registrar(chave, s, info["limiar"], extra)
        if escolhido:
            scores[chave] = s
        del pipe
        gc.collect()
    grupo = meta["_conta_origem"].to_numpy()[manter]
    t0 = time.perf_counter()
    saida["bootstrap_escolhido_menos_atual"] = {
        chave: bootstrap_pareado(y, scores[chave][manter], scores["S"][manter], grupo)
        for chave in escolhas["fontes"].values()}
    if {"S+L", "L"} <= set(escolhas["fontes"]):
        a, b = escolhas["fontes"]["S+L"], escolhas["fontes"]["L"]
        saida["bootstrap_SL_menos_L"] = bootstrap_pareado(y, scores[a][manter], scores[b][manter], grupo)
    if final2:
        a, b = escolhas["fontes"]["S+L corrigida"], escolhas["fontes"]["L"]
        saida["bootstrap_SL_corrigida_menos_L"] = bootstrap_pareado(y, scores[a][manter], scores[b][manter], grupo)
        saida["protocolo_sha256"]["EMENDA_2"] = hashlib.sha256(
            (comum.RAIZ / "docs/ml/hi_large/EMENDA_2_LOTE_CORRIGIDO_E_TESTE_FINAL.md").read_bytes()).hexdigest()
    tempos["bootstrap"] = time.perf_counter() - t0
    if final3:
        ap_dia_s = saida["modelos"]["S|modelo atual, limiar do artefato"]["ap_por_dia"]
        criterio: Dict[str, Any] = {}
        for rotulo, chave in escolhas["fontes"].items():
            b = saida["bootstrap_escolhido_menos_atual"][chave]
            apd = saida["modelos"][chave]["ap_por_dia"]
            acima = int(sum(apd[d] > ap_dia_s[d] for d in ap_dia_s))
            criterio[rotulo] = {"papel": papeis[chave], "ap": saida["modelos"][chave]["average_precision"],
                                "ap_atual": saida["modelos"]["S|modelo atual, limiar do artefato"]["average_precision"],
                                "diferenca_ap": b["diferenca_ap"], "ic95": b["ic95"],
                                "dias_com_ap_maior": acima, "dias": len(ap_dia_s),
                                "atendido": bool(b["diferenca_ap"] > 0 and b["ic95"][0] > 0 and acima >= 5)}
        saida["criterio_emenda3"] = criterio
        saida["protocolo_sha256"]["EMENDA_2"] = hashlib.sha256(EMENDA2.read_bytes()).hexdigest()
        saida["protocolo_sha256"]["EMENDA_3"] = hashlib.sha256(EMENDA3.read_bytes()).hexdigest()
        saida["artefato_sha256"] = sha_artefato
    tempos["total"] = time.perf_counter() - t_inicio
    saida["tempos_s"] = {k: round(v, 1) for k, v in tempos.items()}
    saida["ambiente"] = comum.ambiente()
    saida["pico_memoria_mb"] = comum.memoria_processo_mb()
    if rf_descritivo:
        saida["aviso"] = ("Avaliação descritiva adicional, feita depois da consulta principal do teste final 2, "
                          "só com as florestas de produção (mesmo tipo do modelo atual). Não decide nada.")
    print(comum.salvar_json(saida, f"d_{periodo}" + ("_rf_descritivo" if rf_descritivo else "") + ".json"))


def etapa_hismall() -> None:
    escolhas = json.loads(ESCOLHAS.read_text(encoding="utf-8"))
    if ESCOLHAS_EMENDA2.is_file():
        e2 = json.loads(ESCOLHAS_EMENDA2.read_text(encoding="utf-8"))
        chave_sl = e2["fontes"]["S+L"]
        escolhas["candidatos"][f"corrigido|{chave_sl}"] = e2["candidatos"][chave_sl]
        escolhas["fontes"]["S+L"] = f"corrigido|{chave_sl}"
    pl: PreparadorFinanceiro = joblib.load(comum.TRABALHO / "preparador_L.joblib")
    modelo = ModeloUnificado.carregar(comum.RAIZ / "artefatos_ml")
    cab_s = modelo.cabeca("lavagem")
    df = pd.read_parquet(comum.TRABALHO / "hismall_teste_L.parquet")
    X = df[list(pl.colunas)].astype(np.float32)
    y, dia = df["_rotulo"].to_numpy(), df["_dia"].to_numpy()
    tipo = df["_tipo_padrao"] if "_tipo_padrao" in df else pd.Series("desconhecido", index=df.index)
    pos = y == 1
    saida: Dict[str, Any] = {"gerado_em_utc": comum.agora(), "etapa": "hismall",
                             "aviso": "teste do HI-Small já consultado antes; resultado só descritivo",
                             "n": int(len(y)), "positivos": int(y.sum()), "modelos": {}}
    cache = comum.RAIZ / "artefatos_ml" / "cache" / "financeiro_teste.parquet"
    if cache.is_file():
        c = pd.read_parquet(cache)
        s = cab_s.probabilidades(c[list(cab_s.colunas_entrada)])[:, 1]
        m = metricas_binarias(c["_rotulo"].to_numpy(), s, cab_s.limiar_alerta)
        m.pop("curva_pr_resumida", None)
        saida["modelos"]["S|modelo atual (cache do NodeWatch, lote antigo; com o lote corrigido, ver b4_correcao_lote.json)"] = m
    for fonte, chave in escolhas["fontes"].items():
        info = escolhas["candidatos"][chave]
        pipe = carregar_modelo(info["modelo"])
        s, _ = pontuar(pipe, X)
        m = metricas_binarias(y, s, info["limiar"], dia=dia)
        m.pop("curva_pr_resumida", None)
        m["recall_por_tipo"] = recall_por_grupo(tipo[pos], pd.Series(s >= info["limiar"])[pos])
        saida["modelos"][chave] = m
    print(comum.salvar_json(saida, "f_hismall.json"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--etapa", choices=("validacao", "teste", "reserva", "hismall", "final2", "final2_rf", "final3"),
                    required=True)
    ap.add_argument("--emenda2", action="store_true", help="com --etapa validacao: refaz só a S+L (Emenda 2)")
    ap.add_argument("--forcar", action="store_true", help="repete um período já consultado (fica registrado)")
    a = ap.parse_args()
    if a.etapa == "validacao":
        etapa_validacao(emenda2=a.emenda2)
    elif a.etapa == "final2":
        avaliar_periodo("teste_final2", so_escolhidos=True, forcar=a.forcar)
    elif a.etapa == "final2_rf":
        avaliar_periodo("teste_final2", so_escolhidos=True, forcar=a.forcar, rf_descritivo=True)
    elif a.etapa == "final3":
        avaliar_periodo("teste_final3", so_escolhidos=True, forcar=a.forcar)
    elif a.etapa == "teste":
        avaliar_periodo("teste", so_escolhidos=False, forcar=a.forcar)
    elif a.etapa == "reserva":
        avaliar_periodo("reserva", so_escolhidos=True, forcar=a.forcar)
    else:
        etapa_hismall()


if __name__ == "__main__":
    main()
