"""Métricas de avaliação (funções puras, sem treino).

Definições usadas nos relatórios:

* **Início de evento** — linha cujo ``alvo`` é ``RISCO`` ou ``FALHA`` e cuja
  linha anterior do mesmo fluxo, a no máximo ``limite_consecutivo_s``
  segundos, tem ``alvo == OK``. Um início é *detectado* se a previsão naquela
  linha for diferente de ``OK``.
* **Transição** — linha com ``alvo != classe_atual`` (o estado muda na
  próxima medição); é exatamente onde a persistência erra.
* **Falso alerta** — alerta emitido (``score_alerta_rede >= limiar``) quando a
  próxima medição é ``OK``. A taxa por fluxo-hora usa como tempo observado
  ``linhas × mediana do intervalo``.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_recall_fscore_support,
)

from src.ml.esquemas import CLASSES_REDE


def metricas_multiclasse(y_true: Sequence, y_pred: Sequence,
                         classes: Sequence[str] = CLASSES_REDE) -> Dict[str, Any]:
    y_true = np.asarray(y_true, dtype=object)
    y_pred = np.asarray(y_pred, dtype=object)
    p, r, f, sup = precision_recall_fscore_support(y_true, y_pred, labels=list(classes), zero_division=0)
    return {
        "classes": list(classes),
        "matriz_confusao": confusion_matrix(y_true, y_pred, labels=list(classes)).tolist(),
        "por_classe": {
            c: {"precisao": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "suporte": int(sup[i])}
            for i, c in enumerate(classes)
        },
        "macro_f1": float(f1_score(y_true, y_pred, labels=list(classes), average="macro", zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "acuracia": float(accuracy_score(y_true, y_pred)),
        "n": int(len(y_true)),
    }


def _ordenar(df: pd.DataFrame) -> np.ndarray:
    return np.lexsort((df["timestamp"].to_numpy(), df["id_fluxo"].astype(str).to_numpy()))


def metricas_eventos(df: pd.DataFrame, pred: Sequence, limite_consecutivo_s: float) -> Dict[str, Any]:
    """Inícios de evento e transições (``df`` com id_fluxo, timestamp, alvo[, classe_atual])."""
    ordem = _ordenar(df)
    s = df.iloc[ordem].reset_index(drop=True)
    p = np.asarray(pred, dtype=object)[ordem]
    g = s.groupby("id_fluxo", sort=False)
    anterior = g["alvo"].shift(1)
    dt = g["timestamp"].diff()
    consecutivo = (dt <= limite_consecutivo_s).to_numpy()
    alvo = s["alvo"].to_numpy(dtype=object)
    inicio = consecutivo & (anterior.to_numpy(dtype=object) == "OK") & (alvo != "OK")
    saida: Dict[str, Any] = {"definicao_limite_consecutivo_s": float(limite_consecutivo_s)}
    for nome, msk in (("nao_ok", inicio), ("RISCO", inicio & (alvo == "RISCO")),
                      ("FALHA", inicio & (alvo == "FALHA"))):
        n = int(msk.sum())
        saida[f"inicios_{nome}"] = {
            "n": n,
            "detectados_nao_ok": int((msk & (p != "OK")).sum()),
            "taxa_deteccao": float((msk & (p != "OK")).sum() / n) if n else None,
            "classe_exata": float((msk & (p == alvo)).sum() / n) if n else None,
        }
    if "classe_atual" in s:
        trans = alvo != s["classe_atual"].to_numpy(dtype=object)
        saida["transicoes"] = {
            "n": int(trans.sum()),
            "acuracia": float((p[trans] == alvo[trans]).mean()) if trans.any() else None,
            "macro_f1": float(f1_score(alvo[trans], p[trans], labels=list(CLASSES_REDE),
                                       average="macro", zero_division=0)) if trans.any() else None,
        }
    return saida


def falsos_alertas(df: pd.DataFrame, alerta: np.ndarray, nao_ok: np.ndarray,
                   mediana_intervalo_s: float) -> Dict[str, Any]:
    alerta = np.asarray(alerta, dtype=bool)
    nao_ok = np.asarray(nao_ok, dtype=bool)
    fp = alerta & ~nao_ok
    quadro = pd.DataFrame({"f": df["id_fluxo"].to_numpy(), "fp": fp})
    por = quadro.groupby("f").agg(n=("fp", "size"), fp=("fp", "sum"))
    horas = por["n"] * mediana_intervalo_s / 3600.0
    taxa = por["fp"] / horas
    return {
        "alertas": int(alerta.sum()),
        "alertas_corretos": int((alerta & nao_ok).sum()),
        "falsos_alertas": int(fp.sum()),
        "eventos_nao_alertados": int((~alerta & nao_ok).sum()),
        "horas_observadas_aprox": float(horas.sum()),
        "falsos_por_fluxo_hora": float(fp.sum() / horas.sum()) if horas.sum() else None,
        "por_fluxo": {
            "mediana": float(taxa.median()), "p90": float(taxa.quantile(0.9)), "max": float(taxa.max()),
            "fluxos_sem_falso_alerta": int((por["fp"] == 0).sum()), "fluxos": int(len(por)),
        },
    }


def calibracao_binaria(y: np.ndarray, prob: np.ndarray, n_bins: int = 10) -> Dict[str, Any]:
    y = np.asarray(y, dtype=float)
    prob = np.clip(np.asarray(prob, dtype=float), 0, 1)
    bordas = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(prob, bordas[1:-1]), 0, n_bins - 1)
    caixas = []
    ece = 0.0
    for b in range(n_bins):
        m = idx == b
        if not m.any():
            continue
        pm, fo = float(prob[m].mean()), float(y[m].mean())
        ece += m.mean() * abs(pm - fo)
        caixas.append({"de": float(bordas[b]), "ate": float(bordas[b + 1]), "n": int(m.sum()),
                       "prob_media": pm, "frequencia_observada": fo})
    return {"brier": float(np.mean((prob - y) ** 2)), "ece": float(ece), "caixas": caixas}


def brier_multiclasse(y_true: Sequence, proba: np.ndarray, classes: Sequence[str]) -> float:
    y = np.asarray(y_true, dtype=object)
    alvo = np.stack([(y == c).astype(float) for c in classes], axis=1)
    return float(np.mean(np.sum((proba - alvo) ** 2, axis=1)))


def limiar_max_f1(y: np.ndarray, score: np.ndarray) -> Dict[str, float]:
    """Limiar que maximiza o F1 da classe positiva (critério documentado)."""
    p, r, t = precision_recall_curve(np.asarray(y, dtype=int), np.asarray(score, dtype=float))
    with np.errstate(invalid="ignore", divide="ignore"):
        f1 = np.where(p + r > 0, 2 * p * r / (p + r), 0)
    i = int(np.nanargmax(f1[:-1])) if len(t) else 0
    return {"limiar": float(t[i]) if len(t) else 0.5, "f1": float(f1[i]),
            "precisao": float(p[i]), "recall": float(r[i])}


def curva_limiares(df: pd.DataFrame, score: np.ndarray, nao_ok: np.ndarray,
                   mediana_intervalo_s: float,
                   limiares: Iterable[float] = tuple(np.round(np.arange(0.05, 0.96, 0.05), 2))) -> List[Dict[str, Any]]:
    linhas = []
    for lim in limiares:
        alerta = score >= lim
        tp = int((alerta & nao_ok).sum())
        fa = falsos_alertas(df, alerta, nao_ok, mediana_intervalo_s)
        linhas.append({
            "limiar": float(lim),
            "precisao": float(tp / alerta.sum()) if alerta.sum() else None,
            "recall": float(tp / nao_ok.sum()) if nao_ok.sum() else None,
            "falsos_por_fluxo_hora": fa["falsos_por_fluxo_hora"],
            "alertas": int(alerta.sum()),
        })
    return linhas


def metricas_binarias(y: np.ndarray, score: np.ndarray, limiar: float,
                      dia: Optional[np.ndarray] = None,
                      ks: Sequence[int] = (50, 100, 500, 1000, 5000)) -> Dict[str, Any]:
    y = np.asarray(y, dtype=int)
    score = np.asarray(score, dtype=float)
    pred = score >= limiar
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    saida: Dict[str, Any] = {
        "n": int(len(y)), "positivos": int(y.sum()), "prevalencia": float(y.mean()) if len(y) else None,
        "limiar": float(limiar),
        "verdadeiros_positivos": tp, "falsos_positivos": fp, "falsos_negativos": fn,
        "precisao": prec, "recall": rec,
        "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
        "falsos_alertas_por_10k": fp / len(y) * 10_000 if len(y) else None,
        "average_precision": float(average_precision_score(y, score)) if y.sum() else None,
    }
    if y.sum():
        p, r, t = precision_recall_curve(y, score)
        alvos = np.linspace(0.05, 0.95, 19)
        pontos = []
        for ra in alvos:
            m = r >= ra
            pontos.append({"recall_min": float(ra), "precisao_max": float(p[m].max()) if m.any() else None})
        saida["curva_pr_resumida"] = pontos
    if dia is not None:
        por_dia = {}
        for d in np.unique(dia):
            m = dia == d
            ys, ss = y[m], score[m]
            ordem = np.argsort(-ss, kind="stable")
            linha = {"n": int(m.sum()), "positivos": int(ys.sum())}
            for k in ks:
                topo = ys[ordem[:k]]
                linha[f"recall@{k}"] = float(topo.sum() / ys.sum()) if ys.sum() else None
                linha[f"precisao@{k}"] = float(topo.mean()) if len(topo) else None
            por_dia[str(d)] = linha
        saida["por_dia_topk"] = por_dia
    return saida


def recall_por_grupo(grupo: pd.Series, pred: pd.Series) -> Dict[str, Any]:
    """Recall de positivos por grupo (ex.: tipo de padrão de lavagem)."""
    q = pd.DataFrame({"g": grupo.astype(str), "p": pred.astype(bool)})
    r = q.groupby("g")["p"].agg(["size", "sum"])
    return {g: {"n": int(v["size"]), "detectados": int(v["sum"]), "recall": float(v["sum"] / v["size"])}
            for g, v in r.iterrows()}


def psi(referencia: Dict[str, Any], valores: np.ndarray) -> Optional[float]:
    """Population Stability Index de ``valores`` contra os quantis do treino."""
    bordas = np.asarray(referencia["bordas"], dtype=float)
    esperado = np.asarray(referencia["proporcoes"], dtype=float)
    v = np.asarray(valores, dtype=float)
    v = v[np.isfinite(v)]
    if not len(v) or len(bordas) < 2:
        return None
    idx = np.clip(np.searchsorted(bordas[1:-1], v, side="right"), 0, len(esperado) - 1)
    obs = np.bincount(idx, minlength=len(esperado)) / len(v)
    eps = 1e-6
    return float(np.sum((obs - esperado) * np.log((obs + eps) / (esperado + eps))))


def referencia_psi(valores: np.ndarray, n_bins: int = 10) -> Dict[str, Any]:
    v = np.asarray(valores, dtype=float)
    v = v[np.isfinite(v)]
    bordas = np.unique(np.quantile(v, np.linspace(0, 1, n_bins + 1))) if len(v) else np.array([])
    if len(bordas) < 2:
        return {"bordas": bordas.tolist(), "proporcoes": [1.0]}
    idx = np.clip(np.searchsorted(bordas[1:-1], v, side="right"), 0, len(bordas) - 2)
    prop = np.bincount(idx, minlength=len(bordas) - 1) / len(v)
    return {"bordas": bordas.tolist(), "proporcoes": prop.tolist()}
