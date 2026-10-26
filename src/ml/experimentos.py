"""Orquestração: treino (seleção na validação) e avaliação final (teste).

Protocolo das duas tarefas:

1. auditoria dos dados (refeita a cada execução);
2. ajuste de cada configuração da grade SÓ no treino;
3. escolha da configuração e do limiar SÓ na validação;
4. o artefato é salvo (procedimento congelado);
5. ``avaliar_*`` usa o teste uma vez, com o artefato salvo, sem reajustes —
   exceto a análise de grupos inéditos, que reajusta a configuração já
   congelada em subconjuntos do treino, sem nova busca.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score
from sklearn.model_selection import GroupKFold

from src.ml import auditoria
from src.ml.avaliacao import (
    brier_multiclasse,
    calibracao_binaria,
    curva_limiares,
    falsos_alertas,
    limiar_max_f1,
    metricas_binarias,
    metricas_eventos,
    metricas_multiclasse,
    recall_por_grupo,
    referencia_psi,
)
from src.ml.config import pasta_artefatos
from src.ml.esquemas import CLASSES_REDE, FEATURES_REDE
from src.ml.ingestao import (
    ErroDados,
    casar_padroes,
    ler_contas,
    ler_hismall,
    ler_padroes,
    ler_rede,
    verificar_splits,
)
from src.ml.modelos import (
    CabecaClassificacao,
    ModeloUnificado,
    baseline_majoritaria,
    grade_financeira,
    grade_rede,
    recriar_estimador,
)
from src.ml.preparacao import (
    INDICADORES_REDE,
    MINUTOS_DIA,
    SENTINELAS_REDE,
    PreparadorFinanceiro,
    amostrar_treino_financeiro,
    atribuir_split_financeiro,
    atributos_financeiros,
    matriz_rede,
    montar_pipeline_financeiro,
    montar_pipeline_rede,
)


def _agora() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _salvar_json(obj: Any, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return destino


def _log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def _proba(pipe: Any, X: pd.DataFrame, classes: List[Any], lote: int = 250_000) -> np.ndarray:
    ordem = list(pipe.classes_)
    idx = [ordem.index(c) for c in classes]
    return np.vstack([pipe.predict_proba(X.iloc[i:i + lote])[:, idx] for i in range(0, len(X), lote)])


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
def _dados_rede(cfg: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    arquivos = cfg["rede"]["arquivos"]
    if not arquivos:
        raise ValueError("Configure [rede].arquivos no ml_config.local.toml.")
    df, rel = ler_rede(arquivos, modo="treino", conflitos=cfg["rede"]["conflitos"])
    sp = verificar_splits(df)
    if sp["problemas"]:
        raise ErroDados("Divisão temporal inválida: " + "; ".join(sp["problemas"]))
    s = df.sort_values(["id_fluxo", "timestamp"], kind="stable").reset_index(drop=True)
    return s, rel


def treinar_estado_rede(cfg: Dict[str, Any]) -> Dict[str, Any]:
    semente, n_jobs = cfg["geral"]["semente"], cfg["geral"]["n_jobs"]
    pasta = pasta_artefatos(cfg)
    _log("rede: lendo e auditando dados")
    s, rel = _dados_rede(cfg)
    aud = auditoria.auditar_rede(s, cfg["rede"]["multiplo_intervalo_consecutivo"])
    auditoria.salvar(aud, pasta / "auditoria", "auditoria_rede")

    tr = (s["split"] == "treino").to_numpy()
    va = (s["split"] == "validacao").to_numpy()
    Xtr, ytr = matriz_rede(s[tr]), s.loc[tr, "alvo"].to_numpy(dtype=object)
    Xva, yva = matriz_rede(s[va]), s.loc[va, "alvo"].to_numpy(dtype=object)
    mediana = float(s[tr].groupby("id_fluxo")["timestamp"].diff().median())

    resultados: List[Dict[str, Any]] = []
    maj = baseline_majoritaria(ytr)
    resultados.append({"nome": "majoritaria", "familia": "baseline", "params": {"classe": str(maj.classes_[np.argmax(maj.class_prior_)])},
                       "validacao": metricas_multiclasse(yva, maj.predict(np.zeros((len(yva), 1))))})
    resultados.append({"nome": "persistencia", "familia": "baseline", "params": {},
                       "validacao": metricas_multiclasse(yva, s.loc[va, "classe_atual"].to_numpy(dtype=object))})

    melhor = None
    for cand in grade_rede(cfg["rede"]["grade"], semente, n_jobs):
        t0 = time.perf_counter()
        pipe = montar_pipeline_rede(cand.fabrica(), cand.linear).fit(Xtr, ytr)
        proba = _proba(pipe, Xva, list(CLASSES_REDE))
        m = metricas_multiclasse(yva, np.asarray(CLASSES_REDE, dtype=object)[np.argmax(proba, axis=1)])
        m["segundos"] = round(time.perf_counter() - t0, 1)
        resultados.append({"nome": cand.nome, "familia": cand.familia, "params": cand.params, "validacao": m})
        _log(f"rede: {cand.nome} macro-F1 val={m['macro_f1']:.4f} ({m['segundos']} s)")
        chave = (round(m["macro_f1"], 6), m["por_classe"]["FALHA"]["recall"])
        if melhor is None or chave > melhor[0]:
            melhor = (chave, cand, pipe, proba)
    _, cand, pipe, proba_va = melhor

    nao_ok_va = yva != "OK"
    score_va = proba_va[:, 1] + proba_va[:, 2]
    lim = limiar_max_f1(nao_ok_va, score_va)
    versao = f"estado_rede-{_agora()}"
    ts_fim_treino = int(s.loc[tr, "timestamp"].max())
    referencia = {}
    for col in FEATURES_REDE:
        v = Xtr[col].to_numpy(dtype=float)
        if col in SENTINELAS_REDE:
            v = v[v != SENTINELAS_REDE[col]]
        referencia[col] = referencia_psi(v)
    meta_comum = {
        "treinado_ate_utc": datetime.fromtimestamp(ts_fim_treino, timezone.utc).isoformat(),
        "arquivos": rel["arquivos"],
        "ingestao": {k: v for k, v in rel.items() if k != "arquivos"},
        "semente": semente,
        "mediana_intervalo_treino_s": mediana,
        "multiplo_intervalo_consecutivo": cfg["rede"]["multiplo_intervalo_consecutivo"],
        "classe_majoritaria_treino": resultados[0]["params"]["classe"],
        "n_treino": int(tr.sum()),
        "n_validacao": int(va.sum()),
        "distribuicao_treino": {str(k): int(v) for k, v in pd.Series(ytr).value_counts().items()},
        "referencia_psi": referencia,
        "taxa_sentinela_treino": {c: float((Xtr[c] == v).mean()) for c, v in SENTINELAS_REDE.items()},
        "indicadores_ausencia": INDICADORES_REDE,
        "colunas_removidas_no_treino": [c for c, keep in zip(
            pipe.named_steps["constantes"].feature_names_in_, pipe.named_steps["constantes"].get_support()) if not keep],
    }
    cab = CabecaClassificacao(
        "estado_rede", pipe, list(CLASSES_REDE), list(Xtr.columns), cand.familia, cand.params,
        lim["limiar"], usa_classe_atual=False,
        metadados={**meta_comum, "versao": versao,
                   "criterio_selecao": "maior macro-F1 na validação; desempate pelo recall de FALHA",
                   "criterio_limiar": "limiar de score_alerta_rede = P(RISCO)+P(FALHA) com maior F1 "
                                      "da classe não-OK na validação",
                   "limiar_validacao": lim, "validacao": melhor[0]},
    )

    _log("rede: variante comparativa com classe_atual")
    Xtr2, Xva2 = matriz_rede(s[tr], True), matriz_rede(s[va], True)
    pipe2 = montar_pipeline_rede(recriar_estimador(cand.familia, cand.params, semente, n_jobs), cand.linear).fit(Xtr2, ytr)
    proba2 = _proba(pipe2, Xva2, list(CLASSES_REDE))
    m2 = metricas_multiclasse(yva, np.asarray(CLASSES_REDE, dtype=object)[np.argmax(proba2, axis=1)])
    lim2 = limiar_max_f1(nao_ok_va, proba2[:, 1] + proba2[:, 2])
    cab2 = CabecaClassificacao(
        "estado_rede__com_classe_atual", pipe2, list(CLASSES_REDE), list(Xtr2.columns), cand.familia,
        cand.params, lim2["limiar"], usa_classe_atual=True,
        metadados={**meta_comum, "versao": f"estado_rede__com_classe_atual-{_agora()}", "comparativa": True,
                   "nota": "Mesma configuração do modelo principal, com classe_atual em one-hot. "
                           "classe_atual sai da medição atual (disponível no instante da previsão).",
                   "limiar_validacao": lim2},
    )

    modelo = ModeloUnificado.carregar_ou_novo(pasta)
    modelo.registrar("estado_rede", cab, "rede", {
        "esquema": "rede_v1", "preditores": list(FEATURES_REDE), "sentinelas": SENTINELAS_REDE,
        "indicadores": INDICADORES_REDE,
    })
    modelo.cabecas["estado_rede__com_classe_atual"] = cab2
    modelo.salvar(pasta)
    rel_treino = {
        "tarefa": "estado_rede",
        "versao": versao,
        "escolhido": {"nome": cand.nome, "familia": cand.familia, "params": cand.params},
        "limiar": lim,
        "grade_validacao": resultados,
        "variante_com_classe_atual_validacao": m2,
        "auditoria_resumo": {k: aud[k] for k in ("linhas", "fluxos", "nan", "inf", "duplicatas_id_fluxo_timestamp")},
    }
    _salvar_json(rel_treino, pasta / "resultados" / "treino_estado_rede.json")
    _log(f"rede: escolhido {cand.nome}; limiar {lim['limiar']:.3f}")
    return rel_treino


def avaliar_estado_rede(cfg: Dict[str, Any]) -> Dict[str, Any]:
    pasta = pasta_artefatos(cfg)
    modelo = ModeloUnificado.carregar(pasta)
    cab = modelo.cabeca("estado_rede")
    cab2 = modelo.cabecas.get("estado_rede__com_classe_atual")
    s, rel = _dados_rede(cfg)
    hashes_treino = sorted(a["sha256"] for a in cab.metadados["arquivos"])
    if sorted(a["sha256"] for a in rel["arquivos"]) != hashes_treino:
        raise ErroDados("Os arquivos de rede mudaram desde o treino; treine novamente antes de avaliar.")
    med = cab.metadados["mediana_intervalo_treino_s"]
    limite = cab.metadados["multiplo_intervalo_consecutivo"] * med
    classes = np.asarray(CLASSES_REDE, dtype=object)

    def blocos(mask: np.ndarray) -> Dict[str, Any]:
        sub = s[mask].reset_index(drop=True)
        y = sub["alvo"].to_numpy(dtype=object)
        nao_ok = y != "OK"
        proba = cab.probabilidades(matriz_rede(sub))
        pred = classes[np.argmax(proba, axis=1)]
        score = proba[:, 1] + proba[:, 2]
        pers = sub["classe_atual"].to_numpy(dtype=object)
        maj = np.full(len(y), cab.metadados["classe_majoritaria_treino"], dtype=object)
        out: Dict[str, Any] = {
            "modelo": metricas_multiclasse(y, pred),
            "persistencia": metricas_multiclasse(y, pers),
            "majoritaria": metricas_multiclasse(y, maj),
            "eventos": {
                "modelo": metricas_eventos(sub, pred, limite),
                "persistencia": metricas_eventos(sub, pers, limite),
            },
            "alertas": {
                "modelo": falsos_alertas(sub, score >= cab.limiar_alerta, nao_ok, med),
                "persistencia": falsos_alertas(sub, pers != "OK", nao_ok, med),
            },
            "calibracao_nao_ok": calibracao_binaria(nao_ok, score),
            "brier_multiclasse": brier_multiclasse(y, proba, CLASSES_REDE),
            "curva_limiares": curva_limiares(sub, score, nao_ok, med),
        }
        if cab2 is not None:
            p2 = cab2.probabilidades(matriz_rede(sub, True))
            pred2 = classes[np.argmax(p2, axis=1)]
            out["com_classe_atual"] = metricas_multiclasse(y, pred2)
            out["eventos"]["com_classe_atual"] = metricas_eventos(sub, pred2, limite)
            out["alertas"]["com_classe_atual"] = falsos_alertas(sub, p2[:, 1] + p2[:, 2] >= cab2.limiar_alerta, nao_ok, med)
        return out

    _log("rede: avaliando validação (referência) e teste (final)")
    resultado: Dict[str, Any] = {
        "tarefa": "estado_rede", "versao": cab.metadados["versao"],
        "escolhido": {"familia": cab.familia, "params": cab.params, "limiar_alerta": cab.limiar_alerta},
        "validacao": blocos((s["split"] == "validacao").to_numpy()),
        "teste": blocos((s["split"] == "teste").to_numpy()),
    }
    resultado["grupos_ineditos"] = _grupos_ineditos(cfg, s, cab)
    _salvar_json(resultado, pasta / "resultados" / "avaliacao_estado_rede.json")
    return resultado


def _grupos_ineditos(cfg: Dict[str, Any], s: pd.DataFrame, cab: CabecaClassificacao) -> Dict[str, Any]:
    """Treina a configuração congelada sem alguns grupos e testa nesses grupos.

    O ajuste usa só o período de treino dos grupos mantidos; a avaliação usa
    só o período de teste dos grupos retirados (futuro e inédito).
    """
    semente, n_jobs = cfg["geral"]["semente"], cfg["geral"]["n_jobs"]
    k = cfg["rede"]["folds_grupos"]
    classes = np.asarray(CLASSES_REDE, dtype=object)
    saida: Dict[str, Any] = {}
    tr = (s["split"] == "treino").to_numpy()
    te = (s["split"] == "teste").to_numpy()
    for chave in ("id_fluxo", "anchor_id"):
        grupos = s[chave].astype(str).to_numpy()
        unicos = np.unique(grupos)
        folds = []
        for i, (_, idx_fora) in enumerate(GroupKFold(n_splits=k).split(unicos, groups=unicos)):
            fora = np.isin(grupos, unicos[idx_fora])
            m_tr, m_te = tr & ~fora, te & fora
            pipe = montar_pipeline_rede(recriar_estimador(cab.familia, cab.params, semente, n_jobs),
                                        cab.familia == "logistica")
            pipe.fit(matriz_rede(s[m_tr]), s.loc[m_tr, "alvo"].to_numpy(dtype=object))
            y = s.loc[m_te, "alvo"].to_numpy(dtype=object)
            proba = _proba(pipe, matriz_rede(s[m_te]), list(CLASSES_REDE))
            mm = metricas_multiclasse(y, classes[np.argmax(proba, axis=1)])
            mp = metricas_multiclasse(y, s.loc[m_te, "classe_atual"].to_numpy(dtype=object))
            folds.append({"fold": i, "grupos_retirados": int(len(idx_fora)), "linhas_teste": int(m_te.sum()),
                          "macro_f1": mm["macro_f1"], "macro_f1_persistencia": mp["macro_f1"],
                          "recall": {c: mm["por_classe"][c]["recall"] for c in CLASSES_REDE},
                          "balanced_accuracy": mm["balanced_accuracy"]})
            _log(f"rede: grupos inéditos por {chave}, fold {i}: macro-F1={mm['macro_f1']:.4f}")
        mf = np.array([f["macro_f1"] for f in folds])
        mp = np.array([f["macro_f1_persistencia"] for f in folds])
        saida[chave] = {"folds": folds, "macro_f1_media": float(mf.mean()), "macro_f1_dp": float(mf.std(ddof=1)),
                        "macro_f1_persistencia_media": float(mp.mean()), "n_grupos": int(len(unicos))}
    return saida


# ---------------------------------------------------------------------------
# Financeiro (HI-Small)
# ---------------------------------------------------------------------------
def _opcional(caminho: str) -> Optional[Path]:
    return Path(caminho) if caminho and Path(caminho).is_file() else None


def _carregar_financeiro(cfg: Dict[str, Any]):
    fin = cfg["financeiro"]
    if not fin["transacoes"]:
        raise ValueError("Configure [financeiro].transacoes no ml_config.local.toml.")
    _log("lavagem: lendo transações")
    dados = ler_hismall(fin["transacoes"])
    p_contas, p_padroes = _opcional(fin["contas"]), _opcional(fin["padroes"])
    contas = ler_contas(p_contas) if p_contas else None
    casados = casar_padroes(dados, ler_padroes(p_padroes)) if p_padroes else None
    pendentes = [n for n, p in (("contas", p_contas), ("padroes", p_padroes)) if p is None]
    return dados, contas, casados, pendentes


def treinar_lavagem(cfg: Dict[str, Any]) -> Dict[str, Any]:
    fin = cfg["financeiro"]
    semente, n_jobs = cfg["geral"]["semente"], cfg["geral"]["n_jobs"]
    pasta = pasta_artefatos(cfg)
    dados, contas, casados, pendentes = _carregar_financeiro(cfg)
    _log("lavagem: auditando")
    aud = auditoria.auditar_financeiro(dados, fin, contas, casados)
    aud["arquivos_pendentes"] = pendentes
    auditoria.salvar(aud, pasta / "auditoria", "auditoria_financeiro")

    t = dados.trans
    y = t["rotulo"].to_numpy()
    split = atribuir_split_financeiro(t["minuto"].to_numpy(), fin)
    idx = {sp: np.flatnonzero(split == sp) for sp in ("treino", "validacao", "teste", "cauda")}
    prep = PreparadorFinanceiro.ajustar(t.iloc[idx["treino"]])
    rel_amostra, pesos = amostrar_treino_financeiro(y[idx["treino"]], fin["fracao_negativos_treino"], semente)
    idx_tr = idx["treino"][rel_amostra]
    consulta = np.concatenate([idx_tr, idx["validacao"], idx["teste"], idx["cauda"]])
    _log(f"lavagem: calculando atributos point-in-time de {len(consulta):,} transações")
    t0 = time.perf_counter()
    X = atributos_financeiros(t, consulta, prep)
    prep.colunas = list(X.columns)
    _log(f"lavagem: {X.shape[1]} atributos em {time.perf_counter() - t0:.0f} s")
    cortes = np.cumsum([len(idx_tr), len(idx["validacao"]), len(idx["teste"])])
    Xtr, Xva = X.iloc[:cortes[0]], X.iloc[cortes[0]:cortes[1]]
    ytr, yva = y[idx_tr], y[idx["validacao"]]
    prep.registrar_quantis(Xtr)

    cache = pasta / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    for nome, ini, fim, ids in (("teste", cortes[1], cortes[2], idx["teste"]),
                                ("cauda", cortes[2], len(X), idx["cauda"])):
        bloco = X.iloc[ini:fim].reset_index(drop=True).copy()
        bloco["_id_transacao"] = t["id_transacao"].to_numpy()[ids]
        bloco["_minuto"] = t["minuto"].to_numpy()[ids]
        bloco["_formato"] = t["formato"].astype(str).to_numpy()[ids]
        bloco["_rotulo"] = y[ids]
        bloco.to_parquet(cache / f"financeiro_{nome}.parquet", index=False)
    _salvar_json({"sha256": dados.sha256, "colunas": prep.colunas}, cache / "financeiro_cache.json")
    del X

    resultados: List[Dict[str, Any]] = []
    base_va = np.full(len(yva), prep.taxa_base)
    resultados.append({"nome": "prevalencia", "familia": "baseline", "params": {},
                       "validacao": {"average_precision": float(average_precision_score(yva, base_va))}})
    formato_va = t["formato"].astype(str).to_numpy()[idx["validacao"]]
    score_fmt = pd.Series(formato_va).map(prep.taxa_formato).fillna(prep.taxa_base).to_numpy()
    lim_fmt = limiar_max_f1(yva, score_fmt)
    resultados.append({"nome": "taxa_do_formato", "familia": "baseline", "params": {},
                       "validacao": {"average_precision": float(average_precision_score(yva, score_fmt)),
                                     **{f"{k}_no_limiar": v for k, v in lim_fmt.items()}}})
    melhor = None
    for cand in grade_financeira(fin["grade"], semente, n_jobs):
        t0 = time.perf_counter()
        pipe = montar_pipeline_financeiro(cand.fabrica(), cand.linear)
        pipe.fit(Xtr, ytr, modelo__sample_weight=pesos)
        s_va = _proba(pipe, Xva, [0, 1], fin["tamanho_lote_previsao"])[:, 1]
        ap = float(average_precision_score(yva, s_va))
        lim = limiar_max_f1(yva, s_va)
        m = {"average_precision": ap, **{f"{k}_no_limiar": v for k, v in lim.items()},
             "segundos": round(time.perf_counter() - t0, 1)}
        resultados.append({"nome": cand.nome, "familia": cand.familia, "params": cand.params, "validacao": m})
        _log(f"lavagem: {cand.nome} AP val={ap:.4f} ({m['segundos']} s)")
        if melhor is None or ap > melhor[0]:
            melhor = (ap, cand, pipe, s_va, lim)
    ap, cand, pipe, s_va, lim = melhor

    versao = f"lavagem-{_agora()}"
    cab = CabecaClassificacao(
        "lavagem", pipe, [0, 1], prep.colunas, cand.familia, cand.params, lim["limiar"],
        metadados={
            "versao": versao,
            "fonte": "IBM AML HI-Small (sintético); alvo = Is Laundering",
            "arquivo": dados.arquivo, "sha256": dados.sha256,
            "treinado_ate": fin["treino_ate"],
            "limites": {k: fin[k] for k in ("inicio", "treino_ate", "validacao_ate", "teste_ate", "inicio_cauda")},
            "criterio_selecao": "maior average precision na validação (distribuição original)",
            "criterio_limiar": "maior F1 da classe lavagem na validação (sem custos fornecidos)",
            "limiar_validacao": lim, "ap_validacao": ap,
            "fracao_negativos_treino": fin["fracao_negativos_treino"],
            "n_treino_ajuste": int(len(idx_tr)), "positivos_treino": int(ytr.sum()),
            "n_treino_periodo": int(len(idx["treino"])),
            "semente": semente,
            "limiar_baseline_formato": lim_fmt["limiar"],
            "arquivos_pendentes": pendentes,
            "aviso": "Pontuação de lavagem; não é fraude confirmada nem probabilidade calibrada.",
        },
    )
    modelo = ModeloUnificado.carregar_ou_novo(pasta)
    modelo.registrar("lavagem", cab, "financeiro", prep)
    modelo.salvar(pasta)
    rel = {
        "tarefa": "lavagem", "versao": versao,
        "escolhido": {"nome": cand.nome, "familia": cand.familia, "params": cand.params},
        "limiar": lim, "grade_validacao": resultados,
        "atributos": prep.colunas, "cambio": prep.cambio, "info_cambio": prep.info_cambio,
        "arquivos_pendentes": pendentes,
        "splits": aud["splits"],
    }
    _salvar_json(rel, pasta / "resultados" / "treino_lavagem.json")
    _log(f"lavagem: escolhido {cand.nome}; limiar {lim['limiar']:.4f}")
    return rel


def avaliar_lavagem(cfg: Dict[str, Any]) -> Dict[str, Any]:
    pasta = pasta_artefatos(cfg)
    modelo = ModeloUnificado.carregar(pasta)
    cab = modelo.cabeca("lavagem")
    prep: PreparadorFinanceiro = modelo.codificadores["financeiro"]
    info = json.loads((pasta / "cache" / "financeiro_cache.json").read_text(encoding="utf-8"))
    if info["sha256"] != cab.metadados["sha256"]:
        raise ErroDados("Cache de atributos não corresponde ao arquivo usado no treino; treine novamente.")
    resultado: Dict[str, Any] = {"tarefa": "lavagem", "versao": cab.metadados["versao"],
                                 "escolhido": {"familia": cab.familia, "params": cab.params,
                                               "limiar_alerta": cab.limiar_alerta}}
    for nome in ("teste", "cauda"):
        bloco = pd.read_parquet(pasta / "cache" / f"financeiro_{nome}.parquet")
        if bloco.empty:
            continue
        y = bloco["_rotulo"].to_numpy()
        dia = pd.to_datetime(bloco["_minuto"].to_numpy() // MINUTOS_DIA, unit="D").strftime("%Y-%m-%d").to_numpy()
        score = cab.probabilidades(bloco[prep.colunas])[:, 1]
        r: Dict[str, Any] = {"modelo": metricas_binarias(y, score, cab.limiar_alerta, dia)}
        r["baseline_prevalencia"] = metricas_binarias(y, np.full(len(y), prep.taxa_base), prep.taxa_base)
        s_fmt = pd.Series(bloco["_formato"]).map(prep.taxa_formato).fillna(prep.taxa_base).to_numpy()
        r["baseline_formato"] = metricas_binarias(y, s_fmt, cab.metadados["limiar_baseline_formato"], dia)
        if nome == "teste":
            r["calibracao"] = calibracao_binaria(y, score)
            r["padroes"] = _avaliar_por_padrao(cfg, bloco, score >= cab.limiar_alerta)
        resultado[nome] = r
        _log(f"lavagem: {nome} AP={r['modelo']['average_precision']} F1={r['modelo']['f1']:.4f}")
    _salvar_json(resultado, pasta / "resultados" / "avaliacao_lavagem.json")
    return resultado


def _avaliar_por_padrao(cfg: Dict[str, Any], bloco: pd.DataFrame, alerta: np.ndarray) -> Dict[str, Any]:
    fin = cfg["financeiro"]
    p_padroes = _opcional(fin["padroes"])
    if p_padroes is None:
        return {"status": "pendente", "motivo": "HI-Small_Patterns.txt não disponível"}
    dados = ler_hismall(fin["transacoes"])
    casados = casar_padroes(dados, ler_padroes(p_padroes)).dropna(subset=["id_transacao"])
    casados["id_transacao"] = casados["id_transacao"].astype(np.int64)
    inicio = casados.groupby("tentativa")["minuto"].transform("min")
    from src.ml.preparacao import minuto_de
    casados["ja_iniciada_antes_do_teste"] = inicio < minuto_de(fin["validacao_ate"])
    pos = bloco[bloco["_rotulo"] == 1][["_id_transacao"]].assign(alerta=alerta[bloco["_rotulo"].to_numpy() == 1])
    m = pos.merge(casados.drop_duplicates("id_transacao")[["id_transacao", "tipo_padrao", "ja_iniciada_antes_do_teste"]],
                  left_on="_id_transacao", right_on="id_transacao", how="left")
    m["tipo_padrao"] = m["tipo_padrao"].fillna("sem_padrao")
    m["ja_iniciada_antes_do_teste"] = m["ja_iniciada_antes_do_teste"].map({True: "iniciada_antes", False: "nova"}).fillna("sem_padrao")
    return {
        "recall_por_tipo": recall_por_grupo(m["tipo_padrao"], m["alerta"]),
        "recall_por_inicio_da_tentativa": recall_por_grupo(m["ja_iniciada_antes_do_teste"], m["alerta"]),
    }


# ---------------------------------------------------------------------------
# Exemplos de inferência
# ---------------------------------------------------------------------------
def gerar_exemplo_rede(cfg: Dict[str, Any]) -> Path:
    """CSV derivado: linhas do teste sem ``alvo``/``split``, embaralhadas.

    Não substitui dados novos: serve para demonstrar a inferência sem rótulos.
    O CSV original não é alterado.
    """
    s, _ = _dados_rede(cfg)
    te = s[s["split"] == "teste"].drop(columns=["alvo", "split", "arquivo_origem", "linha_origem"])
    te = te.sample(frac=1.0, random_state=cfg["geral"]["semente"]).reset_index(drop=True)
    destino = pasta_artefatos(cfg) / "exemplos" / "rede_teste_sem_rotulos.csv"
    destino.parent.mkdir(parents=True, exist_ok=True)
    te.to_csv(destino, index=False)
    return destino


def gerar_exemplo_lavagem(cfg: Dict[str, Any], dia: str = "2022-09-10") -> Path:
    """Transações de um dia do teste no formato HI-Small, sem ``Is Laundering``."""
    from src.ml.preparacao import minuto_de
    dados = ler_hismall(cfg["financeiro"]["transacoes"])
    t = dados.trans
    ini = minuto_de(dia)
    sel = t[(t["minuto"] >= ini) & (t["minuto"] < ini + MINUTOS_DIA)]
    origem = dados.nomes_contas[sel["conta_origem"].to_numpy()]
    destino_c = dados.nomes_contas[sel["conta_destino"].to_numpy()]
    saida = pd.DataFrame({
        "Timestamp": pd.to_datetime(sel["minuto"].to_numpy(), unit="m").strftime("%Y/%m/%d %H:%M"),
        "From Bank": sel["banco_origem"].to_numpy(),
        "Account": [c.split("-", 1)[1] for c in origem],
        "To Bank": sel["banco_destino"].to_numpy(),
        "Account.1": [c.split("-", 1)[1] for c in destino_c],
        "Amount Received": sel["valor_recebido"].to_numpy(),
        "Receiving Currency": sel["moeda_recebimento"].astype(str).to_numpy(),
        "Amount Paid": sel["valor_pago"].to_numpy(),
        "Payment Currency": sel["moeda_pagamento"].astype(str).to_numpy(),
        "Payment Format": sel["formato"].astype(str).to_numpy(),
    })
    destino = pasta_artefatos(cfg) / "exemplos" / f"hismall_{dia}_sem_rotulo.csv"
    destino.parent.mkdir(parents=True, exist_ok=True)
    saida.to_csv(destino, index=False, header=[c if c != "Account.1" else "Account" for c in saida.columns])
    return destino
