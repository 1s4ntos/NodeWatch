"""Auditoria dos dados, refeita a cada execução.

As funções devolvem dicionários serializáveis em JSON. ``para_markdown``
gera um resumo legível. Nada aqui altera rótulos ou dados: divergências são
apenas relatadas.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from src.ml.esquemas import CLASSES_REDE, FEATURES_REDE, SPLITS
from src.ml.ingestao import DadosHISmall, verificar_splits
from src.ml.preparacao import MINUTOS_DIA, SENTINELAS_REDE, atribuir_split_financeiro, minuto_de

_INSTANTANEAS = ("razao_rtt_p95", "razao_rtt_p99", "razao_jitter_p95", "amplitude_rtt_rel")


def _contagem(s: pd.Series) -> Dict[str, Any]:
    vc = s.value_counts()
    total = int(vc.sum())
    return {str(k): {"n": int(v), "pct": round(100 * v / total, 4)} for k, v in vc.items()}


def _quantis(s: pd.Series, qs=(0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 0.999, 1)) -> Dict[str, float]:
    return {str(q): float(v) for q, v in s.quantile(list(qs)).items()}


def regra_classe_atual(df: pd.DataFrame) -> np.ndarray:
    """Regra que reproduz ``classe_atual`` a partir da medição atual (auditoria)."""
    falha = (df["rtt_ausente"] == 1) | (df["razao_rtt_p99"] > 1) | (df["perda_pct"] >= 50)
    risco = ~falha & ((df["razao_rtt_p95"] > 1) | (df["razao_jitter_p95"] > 1) | (df["perda_pct"] > 0))
    return np.where(falha, "FALHA", np.where(risco, "RISCO", "OK"))


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
def auditar_rede(df: pd.DataFrame, multiplo_consecutivo: float = 2.0) -> Dict[str, Any]:
    s = df.sort_values(["id_fluxo", "timestamp"], kind="stable").reset_index(drop=True)
    feats = [c for c in FEATURES_REDE if c in s]
    a: Dict[str, Any] = {
        "linhas": int(len(s)),
        "colunas_dados": int(len([c for c in s.columns if c not in ("arquivo_origem", "linha_origem")])),
        "fluxos": int(s["id_fluxo"].nunique()),
        "anchors": int(s["anchor_id"].nunique()),
        "probes": int(s["probe_id"].nunique()),
        "id_fluxo_igual_probe_anchor": float(
            (s["id_fluxo"] == s["probe_id"].astype(str) + "_" + s["anchor_id"].astype(str)).mean()
        ),
    }
    num = s[feats].to_numpy(dtype="float64")
    a["nan"] = int(np.isnan(num).sum())
    a["inf"] = int(np.isinf(num).sum())
    a["duplicatas_id_fluxo_timestamp"] = int(s.duplicated(["id_fluxo", "timestamp"]).sum())
    for col in ("alvo", "split", "classe_atual"):
        if col in s:
            a[f"distribuicao_{col}"] = _contagem(s[col])
    if "split" in s and "alvo" in s:
        a["alvo_por_split"] = {
            sp: _contagem(s.loc[s["split"] == sp, "alvo"]) for sp in SPLITS if (s["split"] == sp).any()
        }

    # Intervalos entre medições do mesmo fluxo (e do mesmo split, se houver).
    grupo = ["id_fluxo", "split"] if "split" in s else ["id_fluxo"]
    dt = s.groupby(grupo)["timestamp"].diff()
    mediana = float(dt.median())
    a["intervalo_s"] = {
        "quantis": _quantis(dt.dropna()),
        "mediana": mediana,
        "acima_2x_mediana": int((dt > 2 * mediana).sum()),
        "acima_3600": int((dt > 3600).sum()),
    }
    limite_consec = multiplo_consecutivo * mediana
    a["limite_consecutivo_s"] = limite_consec

    # Alvo vs classe_atual da próxima observação.
    if "alvo" in s and "classe_atual" in s:
        prox = s.groupby("id_fluxo")["classe_atual"].shift(-1)
        m = prox.notna()
        a["alvo_vs_proxima_classe"] = {
            "pares": int(m.sum()), "iguais": int((s["alvo"][m] == prox[m]).sum()),
        }
        a["alvo_vs_proxima_classe"]["taxa"] = (
            a["alvo_vs_proxima_classe"]["iguais"] / max(a["alvo_vs_proxima_classe"]["pares"], 1)
        )
        prox_g = s.groupby(grupo)["classe_atual"].shift(-1)
        dt_prox = -s.groupby(grupo)["timestamp"].diff(-1)
        m2 = prox_g.notna()
        div = m2 & (s["alvo"] != prox_g)
        exemplos = s.loc[div, ["id_fluxo", "timestamp"] + (["split"] if "split" in s else [])
                         + ["classe_atual", "alvo"]].assign(
            proxima_classe=prox_g[div], proximo_intervalo_s=dt_prox[div])
        a["divergencias_dentro_do_split"] = {
            "pares": int(m2.sum()),
            "divergencias": int(div.sum()),
            "seguidas_de_lacuna": int((dt_prox[div] > limite_consec).sum()),
            "exemplos": json.loads(exemplos.head(50).to_json(orient="records")),
        }
        a["regra_classe_atual_reproduz"] = float((regra_classe_atual(s) == s["classe_atual"]).mean())

    # Splits, lacunas e necessidade de expurgo pelo horizonte (1 medição).
    if "split" in s:
        sp = verificar_splits(s)
        a["splits"] = sp
        horizonte = float(dt.quantile(0.999))
        menor_lacuna = min((v["min"] for v in sp["lacunas_s"].values()), default=float("inf"))
        a["horizonte"] = {
            "definicao": "próxima medição do mesmo fluxo",
            "intervalo_p999_s": horizonte,
            "menor_lacuna_entre_splits_s": menor_lacuna,
            "expurgo_necessario": bool(menor_lacuna <= horizonte),
        }

    # Sentinelas por coluna.
    sent: Dict[str, Any] = {}
    for col, valor in SENTINELAS_REDE.items():
        if col not in s:
            continue
        msk = s[col] == valor
        info: Dict[str, Any] = {"valor": valor, "n": int(msk.sum())}
        if "rtt_ausente" in s:
            ra = s["rtt_ausente"] == 1
            info["com_rtt_ausente"] = int((msk & ra).sum())
            if col in _INSTANTANEAS:
                info["coincide_com_rtt_ausente"] = bool((msk == ra).all())
        sent[col] = info
    a["sentinelas"] = sent
    a["negativos_nao_sentinela"] = {
        c: int(((s[c] < 0) & (s[c] != SENTINELAS_REDE.get(c, np.nan))).sum()) for c in feats
        if ((s[c] < 0) & (s[c] != SENTINELAS_REDE.get(c, np.nan))).any()
    }
    a["constantes"] = [c for c in feats if s[c].nunique() <= 1]

    # Janelas: conferência com rolagem para trás (e, por contraste, para frente).
    a["janelas"] = _conferir_janelas(s)

    # Referência dos percentis: fração acima de p95/p99 com RTT presente.
    if "split" in s:
        pres = s[s["rtt_ausente"] == 0]
        a["fracao_acima_referencia"] = {
            col: {sp: float((pres.loc[pres["split"] == sp, col] > 1).mean())
                  for sp in SPLITS if (pres["split"] == sp).any()}
            for col in ("razao_rtt_p95", "razao_rtt_p99", "razao_jitter_p95")
        }
    return a


def _conferir_janelas(s: pd.DataFrame) -> Dict[str, Any]:
    def rolar(col: str, k: int, func: str, para_frente: bool = False) -> pd.Series:
        base = s.iloc[::-1] if para_frente else s
        janela = base.groupby("id_fluxo", sort=False)[col].rolling(k, min_periods=1)
        r = getattr(janela, func)()
        return r.reset_index(level=0, drop=True).reindex(s.index)

    acima = (s["razao_rtt_p95"] > 1).astype(float)
    s = s.assign(_acima=acima)
    g = s.groupby("id_fluxo", sort=False)
    saida: Dict[str, Any] = {}
    for k in (3, 6, 12):
        perda = rolar("perda_pct", k, "mean")
        jitter = rolar("razao_jitter_p95", k, "max")
        rtt = rolar("razao_rtt_p95", k, "max")
        n_acima = g["_acima"].rolling(k, min_periods=1).sum().reset_index(level=0, drop=True).reindex(s.index)
        n_acima = n_acima.where(rtt != -1, -1)
        jitter_fr = rolar("razao_jitter_p95", k, "max", para_frente=True)
        saida[f"w{k}"] = {
            "perda_media_para_tras": float(np.isclose(perda, s[f"perda_media_w{k}"], atol=1e-3).mean()),
            "jitter_max_para_tras": float(np.isclose(jitter, s[f"jitter_p95_max_w{k}"], rtol=1e-4, atol=1e-5).mean()),
            "rtt_max_para_tras": float(np.isclose(rtt, s[f"rtt_p95_max_w{k}"], rtol=1e-4, atol=1e-5).mean()),
            "n_acima_para_tras": float(np.isclose(n_acima, s[f"n_rtt_acima_p95_w{k}"]).mean()),
            "jitter_max_para_frente": float(np.isclose(jitter_fr, s[f"jitter_p95_max_w{k}"], rtol=1e-4, atol=1e-5).mean()),
        }
    return saida


# ---------------------------------------------------------------------------
# Financeiro
# ---------------------------------------------------------------------------
def auditar_financeiro(
    dados: DadosHISmall,
    cfg_fin: Dict[str, Any],
    contas: Optional[pd.DataFrame] = None,
    padroes_casados: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    t = dados.trans
    y = t["rotulo"].to_numpy() if "rotulo" in t else None
    dia = pd.to_datetime(t["minuto"].to_numpy() // MINUTOS_DIA, unit="D").strftime("%Y-%m-%d")
    a: Dict[str, Any] = {
        "arquivo": dados.arquivo,
        "sha256": dados.sha256,
        "leitura": dados.relatorio,
        "periodo": [str(pd.to_datetime(t["minuto"].min(), unit="m")),
                    str(pd.to_datetime(t["minuto"].max(), unit="m"))],
    }
    if y is not None:
        a["positivos"] = int(y.sum())
        a["taxa_positivos"] = float(y.mean())
        por_dia = pd.DataFrame({"dia": dia, "y": y}).groupby("dia")["y"].agg(["count", "sum"])
        a["por_dia"] = {d: {"n": int(r["count"]), "positivos": int(r["sum"]),
                            "taxa": float(r["sum"] / r["count"])} for d, r in por_dia.iterrows()}
        volume_mediano = float(por_dia["count"].median())
        a["dias_com_volume_abaixo_1pct_da_mediana"] = [
            d for d, r in por_dia.iterrows() if r["count"] < 0.01 * volume_mediano
        ]
        fmt = pd.DataFrame({"f": t["formato"].astype(str), "y": y}).groupby("f")["y"].agg(["count", "sum"])
        a["formato"] = {f: {"n": int(r["count"]), "positivos": int(r["sum"]),
                            "taxa": float(r["sum"] / r["count"])} for f, r in fmt.iterrows()}
    auto = (t["conta_origem"] == t["conta_destino"]).to_numpy()
    a["auto_transferencias"] = {"n": int(auto.sum()), "positivos": int(y[auto].sum()) if y is not None else None}
    a["moeda_pagamento_diferente_recebimento"] = int(
        (t["moeda_pagamento"].astype(str) != t["moeda_recebimento"].astype(str)).sum())
    a["mesmo_banco"] = int((t["banco_origem"] == t["banco_destino"]).sum())

    split = atribuir_split_financeiro(t["minuto"].to_numpy(), cfg_fin)
    a["splits"] = {}
    for sp in ("treino", "validacao", "teste", "cauda", "fora"):
        msk = split == sp
        a["splits"][sp] = {"n": int(msk.sum()), "positivos": int(y[msk].sum()) if y is not None else None}
    a["limites"] = {k: cfg_fin[k] for k in ("inicio", "treino_ate", "validacao_ate", "teste_ate", "inicio_cauda")}

    if contas is not None and y is not None:
        a["contas"] = _auditar_contas(dados, contas, split)
    if padroes_casados is not None and y is not None:
        a["padroes"] = _auditar_padroes(dados, padroes_casados, split)
    return a


def _ap(y: np.ndarray, score: np.ndarray) -> float:
    from sklearn.metrics import average_precision_score
    return float(average_precision_score(y, score)) if y.sum() else float("nan")


def _auditar_contas(dados: DadosHISmall, contas: pd.DataFrame, split: np.ndarray) -> Dict[str, Any]:
    """Procura atributos de conta que revelem a resposta (medido só no treino).

    Critério: um atributo é ``suspeito`` se, codificado pela taxa de lavagem
    do treino, tiver AP na validação >= 0,5 ou algum valor com lift >= 50 e
    suporte >= 100 transações no treino. Suspeitos não podem virar atributo.
    """
    indice = pd.Index(dados.nomes_contas)
    cod = indice.get_indexer(contas["conta"])
    cobertas = cod >= 0
    tipo = np.full(len(indice), "sem_cadastro", dtype=object)
    tipo[cod[cobertas]] = contas.loc[cobertas, "tipo_entidade"].to_numpy()
    n_por_entidade = contas.groupby("Entity ID")["conta"].transform("count").to_numpy()
    n_contas_ent = np.zeros(len(indice), dtype=np.int64)
    n_contas_ent[cod[cobertas]] = n_por_entidade[cobertas]
    nome_suspeito = contas["Entity Name"].str.contains("launder|fraud|illicit", case=False, na=False)

    t = dados.trans
    y = t["rotulo"].to_numpy()
    o = t["conta_origem"].to_numpy()
    d = t["conta_destino"].to_numpy()
    candidatos = {
        "tipo_entidade_origem": tipo[o],
        "tipo_entidade_destino": tipo[d],
        "n_contas_entidade_origem": np.minimum(n_contas_ent[o], 20).astype(str),
        "n_contas_entidade_destino": np.minimum(n_contas_ent[d], 20).astype(str),
    }
    tr, va = split == "treino", split == "validacao"
    base = float(y[tr].mean())
    resultado: Dict[str, Any] = {}
    for nome, valores in candidatos.items():
        df = pd.DataFrame({"v": valores[tr], "y": y[tr]}).groupby("v")["y"].agg(["count", "mean"])
        taxa = df["mean"].to_dict()
        lift = (df["mean"] / base).where(df["count"] >= 100)
        score_va = pd.Series(valores[va]).map(taxa).fillna(base).to_numpy()
        ap_va = _ap(y[va], score_va)
        suspeito = bool(ap_va >= 0.5 or (lift.max() >= 50 if lift.notna().any() else False))
        resultado[nome] = {
            "ap_validacao": ap_va,
            "lift_max_suporte_100": float(lift.max()) if lift.notna().any() else None,
            "suspeito_de_revelar_resposta": suspeito,
            "taxas_treino": {str(k): {"n": int(df.loc[k, "count"]), "taxa": float(df.loc[k, "mean"])}
                             for k in df.index[:30]},
        }
    return {
        "linhas_arquivo": int(len(contas)),
        "contas_das_transacoes_com_cadastro": float(np.isin(np.arange(len(indice)), cod[cobertas]).mean()),
        "tipos_entidade": _contagem(contas["tipo_entidade"]),
        "nomes_com_termo_suspeito": int(nome_suspeito.sum()),
        "atributos": resultado,
        "base_treino": base,
    }


def _auditar_padroes(dados: DadosHISmall, casados: pd.DataFrame, split: np.ndarray) -> Dict[str, Any]:
    t = dados.trans
    y = t["rotulo"].to_numpy()
    ok = casados["id_transacao"].notna()
    ids = casados.loc[ok, "id_transacao"].astype(np.int64).to_numpy()
    r: Dict[str, Any] = {
        "tentativas": int(casados["tentativa"].nunique()),
        "linhas": int(len(casados)),
        "linhas_casadas": int(ok.sum()),
        "linhas_casadas_com_rotulo_1": int(y[ids].sum()),
        "positivos_sem_padrao": int(y.sum() - len(np.intersect1d(np.flatnonzero(y == 1), ids))),
        "por_tipo": {
            tp: {"tentativas": int(g["tentativa"].nunique()), "linhas": int(len(g))}
            for tp, g in casados.groupby("tipo_padrao")
        },
    }
    sp = pd.Series(split[ids], index=casados.index[ok])
    por_tent = pd.DataFrame({"tentativa": casados.loc[ok, "tentativa"], "split": sp})
    n_splits = por_tent.groupby("tentativa")["split"].nunique()
    r["tentativas_em_mais_de_um_split"] = int((n_splits > 1).sum())
    ordem = {"treino": 0, "validacao": 1, "teste": 2, "cauda": 3, "fora": -1}
    inicio = por_tent.assign(o=por_tent["split"].map(ordem)).groupby("tentativa")["o"].min()
    for alvo_sp in ("validacao", "teste"):
        linhas = por_tent[por_tent["split"] == alvo_sp]
        if len(linhas):
            anteriores = (linhas["tentativa"].map(inicio) < ordem[alvo_sp]).mean()
            r[f"fracao_linhas_{alvo_sp}_de_tentativas_iniciadas_antes"] = float(anteriores)
    return r


# ---------------------------------------------------------------------------
# Saída
# ---------------------------------------------------------------------------
def salvar(auditoria: Dict[str, Any], pasta: Path, nome: str) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{nome}.json"
    destino.write_text(json.dumps(auditoria, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (pasta / f"{nome}.md").write_text(para_markdown(auditoria, nome), encoding="utf-8")
    return destino


def para_markdown(a: Dict[str, Any], titulo: str) -> str:
    linhas: List[str] = [f"# {titulo}", ""]

    def emitir(chave: str, valor: Any, nivel: int = 0) -> None:
        pref = "  " * nivel + "- "
        if isinstance(valor, dict):
            linhas.append(f"{pref}**{chave}**")
            for k, v in list(valor.items())[:40]:
                emitir(str(k), v, nivel + 1)
        elif isinstance(valor, list) and valor and isinstance(valor[0], dict):
            linhas.append(f"{pref}**{chave}**: {len(valor)} item(ns); primeiros: "
                          + json.dumps(valor[:3], ensure_ascii=False, default=str))
        else:
            linhas.append(f"{pref}{chave}: {valor}")

    for k, v in a.items():
        emitir(k, v)
    return "\n".join(linhas) + "\n"
