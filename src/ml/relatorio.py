"""Geração dos documentos a partir dos resultados salvos.

* ``docs/ml/RELATORIO_ML.md`` — só números lidos de ``artefatos_ml/resultados``
  e ``artefatos_ml/auditoria`` (nada é digitado à mão), mais o texto de
  ``docs/ml/notas_relatorio.md``, se existir;
* ``docs/ml/DICIONARIO_DADOS.md`` e ``docs/ml/esquemas/*.json`` — gerados
  dos esquemas versionados.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.ml.esquemas import CLASSES_REDE, ESQUEMAS, Esquema


def _ler(p: Path) -> Optional[Dict[str, Any]]:
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _f(v: Any, casas: int = 4) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "sim" if v else "não"
    if isinstance(v, int):
        return f"{v:,}".replace(",", ".")
    if isinstance(v, float):
        return f"{v:.{casas}f}".replace(".", ",")
    return str(v)


def _tabela(cabecalho: Sequence[str], linhas: Iterable[Sequence[Any]]) -> str:
    out = ["| " + " | ".join(cabecalho) + " |", "|" + "|".join([" --- "] * len(cabecalho)) + "|"]
    for l in linhas:
        out.append("| " + " | ".join(_f(x) if not isinstance(x, str) else x for x in l) + " |")
    return "\n".join(out)


def _matriz(m: List[List[int]], classes: Sequence[str]) -> str:
    return _tabela(["real \\ previsto", *classes], [[c, *m[i]] for i, c in enumerate(classes)])


# ---------------------------------------------------------------------------
def dicionario_markdown() -> str:
    partes = ["# Dicionário de dados e contratos", "",
              "Gerado de `src/ml/esquemas.py` (`python -m src.ml.cli documentar`). "
              "`verificado` = conferido nos dados pela auditoria; `inferido` = deduzido do nome e da "
              "distribuição, sem documentação da construção original.", ""]
    for esq in ESQUEMAS.values():
        partes += _esquema_md(esq)
    return "\n".join(partes) + "\n"


def _esquema_md(e: Esquema) -> List[str]:
    titulo = f"## `{e.id}`" + (" — PROPOSTA a validar" if e.proposta else "")
    linhas = [titulo, "", e.descricao, ""]
    linhas.append(_tabela(
        ["coluna", "tipo", "papel", "unidade", "sentinela", "obrig. treino", "obrig. inferência", "status", "descrição"],
        [[f"`{c.nome}`", c.tipo, c.papel, c.unidade or "—",
          (f"{c.sentinela:g}: {c.significado_sentinela}" if c.sentinela is not None else "—"),
          "sim" if c.obrigatoria_treino else "não", "sim" if c.obrigatoria_inferencia else "não",
          c.status, c.descricao] for c in e.colunas]))
    for o in e.observacoes:
        linhas.append(f"\n- {o}")
    linhas.append("")
    return linhas


def escrever_documentacao(pasta_docs: Path) -> List[Path]:
    pasta_docs.mkdir(parents=True, exist_ok=True)
    escritos = []
    d = pasta_docs / "DICIONARIO_DADOS.md"
    d.write_text(dicionario_markdown(), encoding="utf-8")
    escritos.append(d)
    pe = pasta_docs / "esquemas"
    pe.mkdir(exist_ok=True)
    for nome, esq in ESQUEMAS.items():
        p = pe / f"{nome}.json"
        p.write_text(json.dumps(esq.para_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        escritos.append(p)
    return escritos


# ---------------------------------------------------------------------------
def _secao_rede(art: Path) -> List[str]:
    treino = _ler(art / "resultados" / "treino_estado_rede.json")
    aval = _ler(art / "resultados" / "avaliacao_estado_rede.json")
    aud = _ler(art / "auditoria" / "auditoria_rede.json")
    out = ["## 1. Tarefa `estado_rede` — estado da próxima medição", ""]
    if aud:
        dv = aud.get("divergencias_dentro_do_split", {})
        hz = aud.get("horizonte", {})
        out += ["### 1.1 Auditoria (refeita nesta execução)", "", _tabela(["item", "valor"], [
            ["linhas", aud["linhas"]], ["fluxos", aud["fluxos"]], ["NaN / inf", f"{aud['nan']} / {aud['inf']}"],
            ["duplicatas id_fluxo+timestamp", aud["duplicatas_id_fluxo_timestamp"]],
            ["alvo = classe_atual seguinte", _f(aud.get("alvo_vs_proxima_classe", {}).get("taxa"), 6)],
            ["divergências dentro do split (seguidas de lacuna)",
             f"{dv.get('divergencias')} de {_f(dv.get('pares'))} ({dv.get('seguidas_de_lacuna')})"],
            ["regra de limiares reproduz classe_atual", _f(aud.get("regra_classe_atual_reproduz"), 4)],
            ["intervalo mediano (s)", _f(aud["intervalo_s"]["mediana"], 0)],
            ["menor lacuna entre splits (s) / p99,9 do intervalo (s)",
             f"{_f(hz.get('menor_lacuna_entre_splits_s'), 0)} / {_f(hz.get('intervalo_p999_s'), 0)}"],
            ["expurgo necessário pelo horizonte", _f(hz.get("expurgo_necessario"))],
            ["colunas constantes", ", ".join(aud.get("constantes", [])) or "—"],
        ]), ""]
        jan = aud.get("janelas", {})
        if jan:
            out += ["Conferência das janelas (fração de linhas que coincide com a rolagem para trás, "
                    "por medições; a última coluna é o contraste olhando para frente):", "",
                    _tabela(["janela", "perda média", "rtt máx", "jitter máx", "n acima p95", "jitter máx (para frente)"],
                            [[k, v["perda_media_para_tras"], v["rtt_max_para_tras"], v["jitter_max_para_tras"],
                              v["n_acima_para_tras"], v["jitter_max_para_frente"]] for k, v in jan.items()]), ""]
    if treino:
        out += ["### 1.2 Seleção na validação (ajuste só no treino)", "",
                f"Escolhido: **{treino['escolhido']['nome']}**; limiar de `score_alerta_rede` = "
                f"{_f(treino['limiar']['limiar'])} (máximo F1 de não-OK na validação).", "",
                _tabela(["configuração", "macro-F1", "recall RISCO", "recall FALHA", "balanced acc.", "s"],
                        [[r["nome"], r["validacao"]["macro_f1"], r["validacao"]["por_classe"]["RISCO"]["recall"],
                          r["validacao"]["por_classe"]["FALHA"]["recall"], r["validacao"]["balanced_accuracy"],
                          r["validacao"].get("segundos")] for r in treino["grade_validacao"]]), ""]
    if aval:
        te = aval["teste"]
        nomes = [("majoritaria", "majoritária (treino)"), ("persistencia", "persistência"),
                 ("modelo", "modelo escolhido"), ("com_classe_atual", "modelo + classe_atual")]
        presentes = [(k, n) for k, n in nomes if k in te]
        out += ["### 1.3 Teste (avaliação única, artefato congelado)", "",
                _tabela(["referência", "macro-F1", "balanced acc.", "acurácia", "F1 OK", "F1 RISCO", "F1 FALHA",
                         "recall RISCO", "recall FALHA"],
                        [[n, te[k]["macro_f1"], te[k]["balanced_accuracy"], te[k]["acuracia"],
                          *[te[k]["por_classe"][c]["f1"] for c in CLASSES_REDE],
                          te[k]["por_classe"]["RISCO"]["recall"], te[k]["por_classe"]["FALHA"]["recall"]]
                         for k, n in presentes]), "",
                "Matriz de confusão do modelo (teste):", "", _matriz(te["modelo"]["matriz_confusao"], CLASSES_REDE), "",
                "Matriz de confusão da persistência (teste):", "",
                _matriz(te["persistencia"]["matriz_confusao"], CLASSES_REDE), ""]
        ev = te["eventos"]
        out += ["Inícios de evento e transições (teste):", "",
                _tabela(["referência", "inícios não-OK", "detectados", "inícios FALHA detectados",
                         "transições", "acurácia nas transições"],
                        [[n, ev[k]["inicios_nao_ok"]["n"], ev[k]["inicios_nao_ok"]["taxa_deteccao"],
                          ev[k]["inicios_FALHA"]["taxa_deteccao"], ev[k].get("transicoes", {}).get("n"),
                          ev[k].get("transicoes", {}).get("acuracia")]
                         for k, n in presentes if k in ev]), ""]
        al = te["alertas"]
        out += ["Alertas (teste; tempo observado ≈ linhas × intervalo mediano):", "",
                _tabela(["referência", "alertas", "corretos", "falsos", "não alertados", "falsos por fluxo-hora",
                         "mediana por fluxo", "p90 por fluxo"],
                        [[n, al[k]["alertas"], al[k]["alertas_corretos"], al[k]["falsos_alertas"],
                          al[k]["eventos_nao_alertados"], al[k]["falsos_por_fluxo_hora"],
                          al[k]["por_fluxo"]["mediana"], al[k]["por_fluxo"]["p90"]] for k, n in presentes if k in al]), ""]
        cal = te["calibracao_nao_ok"]
        out += [f"Calibração de P(não OK) no teste: Brier {_f(cal['brier'])}, ECE {_f(cal['ece'])}; "
                f"Brier multiclasse {_f(te['brier_multiclasse'])}.", "",
                _tabela(["faixa de prob.", "n", "prob. média", "frequência observada"],
                        [[f"{_f(c['de'], 1)}–{_f(c['ate'], 1)}", c["n"], c["prob_media"], c["frequencia_observada"]]
                         for c in cal["caixas"]]), ""]
        out += ["Troca entre recall e falsos alertas (`score_alerta_rede`):", "",
                _tabela(["limiar", "precisão val.", "recall val.", "falsos/fluxo-h val.",
                         "precisão teste", "recall teste", "falsos/fluxo-h teste"],
                        [[a["limiar"], a["precisao"], a["recall"], a["falsos_por_fluxo_hora"],
                          b["precisao"], b["recall"], b["falsos_por_fluxo_hora"]]
                         for a, b in zip(aval["validacao"]["curva_limiares"], te["curva_limiares"])]), ""]
        gi = aval.get("grupos_ineditos", {})
        if gi:
            out += ["Grupos inéditos (treino sem os grupos, teste só neles, no período de teste):", "",
                    _tabela(["agrupamento", "grupos", "macro-F1 média", "desvio-padrão", "persistência (média)"],
                            [[k, v["n_grupos"], v["macro_f1_media"], v["macro_f1_dp"], v["macro_f1_persistencia_media"]]
                             for k, v in gi.items()]), ""]
    return out


def _secao_lavagem(art: Path) -> List[str]:
    treino = _ler(art / "resultados" / "treino_lavagem.json")
    aval = _ler(art / "resultados" / "avaliacao_lavagem.json")
    aud = _ler(art / "auditoria" / "auditoria_financeiro.json")
    out = ["## 2. Tarefa `lavagem` — IBM AML HI-Small (sintético)", ""]
    if aud:
        sp = aud["splits"]
        out += ["### 2.1 Auditoria", "", _tabela(["item", "valor"], [
            ["transações / positivos", f"{_f(aud['leitura']['linhas'])} / {_f(aud.get('positivos'))}"],
            ["período", " a ".join(aud["periodo"])],
            ["contas distintas", aud["leitura"]["contas_distintas"]],
            ["duplicatas exatas", aud["leitura"]["duplicatas_exatas"]],
            ["auto-transferências (positivos)", f"{_f(aud['auto_transferencias']['n'])} ({aud['auto_transferencias']['positivos']})"],
            ["moeda de pagamento ≠ recebimento", aud["moeda_pagamento_diferente_recebimento"]],
            ["dias com volume < 1% da mediana", ", ".join(aud.get("dias_com_volume_abaixo_1pct_da_mediana", [])) or "—"],
            ["arquivos pendentes", ", ".join(aud.get("arquivos_pendentes", [])) or "—"],
        ]), "", _tabela(["split", "transações", "positivos", "taxa"],
                        [[k, v["n"], v["positivos"], (v["positivos"] / v["n"]) if v["n"] else None]
                         for k, v in sp.items()]), "",
            _tabela(["formato", "transações", "positivos", "taxa"],
                    [[k, v["n"], v["positivos"], v["taxa"]] for k, v in aud.get("formato", {}).items()]), ""]
        if "contas" in aud:
            out += ["Atributos de conta (vazamento):", "",
                    _tabela(["atributo", "AP validação", "lift máx.", "suspeito"],
                            [[k, v["ap_validacao"], v["lift_max_suporte_100"], v["suspeito_de_revelar_resposta"]]
                             for k, v in aud["contas"]["atributos"].items()]), ""]
        if "padroes" in aud:
            p = aud["padroes"]
            out += [f"Padrões: {p['tentativas']} tentativas, {p['linhas_casadas']} de {p['linhas']} linhas casadas "
                    f"com transações; {p['positivos_sem_padrao']} positivos sem padrão; "
                    f"{p['tentativas_em_mais_de_um_split']} tentativas atravessam splits.", ""]
    if treino:
        out += ["### 2.2 Seleção na validação", "",
                f"Escolhido: **{treino['escolhido']['nome']}**; limiar {_f(treino['limiar']['limiar'], 6)} "
                f"(máximo F1 na validação). {len(treino['atributos'])} atributos.", "",
                _tabela(["configuração", "AP validação", "F1 no limiar", "precisão", "recall", "s"],
                        [[r["nome"], r["validacao"]["average_precision"], r["validacao"].get("f1_no_limiar"),
                          r["validacao"].get("precisao_no_limiar"), r["validacao"].get("recall_no_limiar"),
                          r["validacao"].get("segundos")] for r in treino["grade_validacao"]]), ""]
    if aval:
        for nome in ("teste", "cauda"):
            if nome not in aval:
                continue
            b = aval[nome]
            titulo = "### 2.3 Teste (artefato congelado)" if nome == "teste" else \
                "### 2.4 Cauda do gerador (fora das métricas principais)"
            out += [titulo, "", _tabela(
                ["referência", "AP", "precisão", "recall", "F1", "falsos/10 mil", "VP", "FP", "FN"],
                [[n, b[k]["average_precision"], b[k]["precisao"], b[k]["recall"], b[k]["f1"],
                  b[k]["falsos_alertas_por_10k"], b[k]["verdadeiros_positivos"], b[k]["falsos_positivos"],
                  b[k]["falsos_negativos"]]
                 for k, n in (("baseline_prevalencia", "prevalência"), ("baseline_formato", "taxa do formato"),
                              ("modelo", "modelo escolhido"))]), ""]
            if nome == "teste":
                pdia = b["modelo"].get("por_dia_topk", {})
                if pdia:
                    ks = [k for k in next(iter(pdia.values())) if k.startswith("recall@")]
                    out += ["Capacidade de investigação (top-k por dia):", "", _tabela(
                        ["dia", "transações", "positivos", *ks],
                        [[d, v["n"], v["positivos"], *[v[k] for k in ks]] for d, v in pdia.items()]), ""]
                cal = b.get("calibracao")
                if cal:
                    out += [f"Calibração do score no teste: Brier {_f(cal['brier'], 6)}, ECE {_f(cal['ece'], 6)}.", ""]
                pad = b.get("padroes", {})
                if pad.get("recall_por_tipo"):
                    out += ["Recall por tipo de padrão (positivos do teste, no limiar):", "", _tabela(
                        ["tipo", "positivos", "detectados", "recall"],
                        [[k, v["n"], v["detectados"], v["recall"]] for k, v in pad["recall_por_tipo"].items()]), "",
                        _tabela(["tentativa", "positivos", "detectados", "recall"],
                                [[k, v["n"], v["detectados"], v["recall"]]
                                 for k, v in pad["recall_por_inicio_da_tentativa"].items()]), ""]
                elif pad:
                    out += [f"Recall por padrão: {pad.get('status')} ({pad.get('motivo')}).", ""]
    return out


def gerar_relatorio(pasta_artefatos: Path, pasta_docs: Path) -> Path:
    art = Path(pasta_artefatos)
    meta = _ler(art / "metadados_modelo.json") or {}
    linhas = ["# Relatório de ML — NodeWatch", "",
              "Gerado por `python -m src.ml.cli relatorio` a partir de `artefatos_ml/`. Todos os números "
              "abaixo foram calculados na execução registrada; nenhum foi digitado à mão.", ""]
    v = meta.get("metadados", {}).get("versoes", {})
    if v:
        linhas += ["Ambiente: " + ", ".join(f"{k} {val}" for k, val in v.items()) + ".", ""]
    tarefas = meta.get("tarefas", {})
    if tarefas:
        linhas += [_tabela(["cabeça do modelo unificado", "status"], [[k, s] for k, s in tarefas.items()]), ""]
    linhas += _secao_rede(art)
    linhas += _secao_lavagem(art)
    fusao = meta.get("cabecas", {}).get("fusao_rede_transacao", {})
    linhas += ["## 3. Fusão rede ↔ transação", "", f"Status: **{fusao.get('status', 'indisponivel')}**. "
               + fusao.get("motivo", ""), "", "Entradas necessárias:", ""]
    linhas += [f"- {r}" for r in fusao.get("requisitos", [])] + [""]
    notas = Path(pasta_docs) / "notas_relatorio.md"
    if notas.is_file():
        linhas += [notas.read_text(encoding="utf-8")]
    destino = Path(pasta_docs) / "RELATORIO_ML.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return destino
