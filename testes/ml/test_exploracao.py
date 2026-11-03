"""Testes da exploração de previsões (src/ml/exploracao.py).

Todos os dados aqui são SINTÉTICOS, criados só para os testes: não representam
previsões nem resultados reais do NodeWatch.
"""

from __future__ import annotations

import io
import json
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.ml import exploracao as ex

_PROBS = {"OK": ("0.80", "0.15", "0.05"), "RISCO": ("0.20", "0.70", "0.10"), "FALHA": ("0.10", "0.20", "0.70")}


def csv_rede(n: int = 12, com_alvo: bool = False, sem_opcionais: bool = False) -> str:
    """Previsões de rede sintéticas no formato de `cli prever --tarefa estado_rede`."""
    linhas = []
    for i in range(n):
        classe = ("OK", "RISCO", "FALHA")[i % 3]
        p_ok, p_risco, p_falha = _PROBS[classe]
        score = float(p_risco) + float(p_falha)
        linha = {
            "arquivo_origem": "entrada_teste.csv", "linha_origem": str(i),
            "id_fluxo": f"{100 + i % 4}_200", "anchor_id": "200", "probe_id": str(100 + i % 4),
            "timestamp_previsao": str(1_791_156_000 + 240 * i), "horizonte": "proxima_medicao",
            "classe_prevista": classe, "prob_OK": p_ok, "prob_RISCO": p_risco, "prob_FALHA": p_falha,
            "score_alerta_rede": f"{score:.2f}", "alerta_rede": str(score >= 0.3),
            "limiar_alerta": "0.3", "versao_modelo": "estado_rede-TESTE", "tipo_saida": "previsao",
        }
        if sem_opcionais:
            for k in ("anchor_id", "probe_id", "horizonte", "limiar_alerta", "versao_modelo", "tipo_saida"):
                linha.pop(k)
        if com_alvo:
            linha["alvo"] = ("OK", "RISCO", "FALHA", "OK")[i % 4]
        linhas.append(linha)
    return pd.DataFrame(linhas).to_csv(index=False)


def csv_lavagem(n: int = 10, com_rotulo: bool = False) -> str:
    """Previsões de lavagem sintéticas no formato de `cli prever --tarefa lavagem`."""
    linhas = []
    for i in range(n):
        score = (0.01, 0.2, 0.05, 0.5, 0.0)[i % 5]
        alerta = score >= 0.09
        linha = {
            "arquivo_origem": "entrada_teste_hismall.csv", "linha_origem": str(i), "id_transacao": str(i),
            "timestamp_transacao": f"2022-09-10 {i % 24:02d}:00:00",
            "conta_origem": f"{10 + i % 3}-A{i % 5}", "conta_destino": f"{20 + i % 2}-B{i % 4}",
            "valor_pago": "100.50" if i % 2 else "2500", "moeda_pagamento": ("US Dollar", "Euro")[i % 2],
            "formato": ("ACH", "Wire")[i % 2], "score_lavagem": str(score), "alerta_lavagem": str(alerta),
            "limiar_alerta": "0.09",
            "motivos_verificaveis": "primeira transação entre origem e destino" if alerta else "",
            "historico_incompleto": "False", "sinais_utilizados": "financeiro", "cobertura_vinculo": "sem_vinculo",
            "pontuacao_fraude_financeira": "indisponivel", "versao_modelo": "lavagem-TESTE", "tipo_saida": "previsao",
        }
        if com_rotulo:
            linha["Is Laundering"] = str(int(i % 5 in (1, 3, 4)))
        linhas.append(linha)
    return pd.DataFrame(linhas).to_csv(index=False)


def carregar(texto: str, nome: str = "teste.csv", conjunto=None, dominio=None) -> ex.Previsoes:
    return ex.carregar_previsoes(texto.encode("utf-8"), nome, "teste", "importado",
                                 conjunto or {"tipo": "desconhecido"}, dominio=dominio)


def filtros(prev, **kw):
    return ex.filtros_de_parametros({k: str(v) for k, v in kw.items()}, prev.dominio)


# ---------------------------------------------------------------------------
def test_le_previsoes_de_rede_e_de_lavagem():
    rede = carregar(csv_rede())
    lav = carregar(csv_lavagem())
    assert (rede.dominio, rede.n) == ("rede", 12)
    assert (lav.dominio, lav.n) == ("lavagem", 10)
    assert rede.periodo()["inicio"] < rede.periodo()["fim"]
    assert rede.descricao()["modelo"]["versoes"] == ["estado_rede-TESTE"]
    assert rede.descricao()["modelo"]["limiar"] == pytest.approx(0.3)
    papeis = {c["nome"]: c["papel"] for c in lav.campos()}
    assert papeis["score_lavagem"] == "previsao" and papeis["valor_pago"] == "observado"
    assert papeis["motivos_verificaveis"] == "previsao"


def test_rejeita_esquema_invalido_listando_problemas_e_acao():
    df = pd.read_csv(io.StringIO(csv_rede()), dtype=str, keep_default_na=False)
    df = df.drop(columns=["prob_OK"])
    df.loc[0, "classe_prevista"] = "TALVEZ"
    df.loc[1, "score_alerta_rede"] = "1.7"
    with pytest.raises(ex.ErroContrato) as erro:
        carregar(df.to_csv(index=False))
    texto = " | ".join(erro.value.problemas)
    assert "coluna obrigatória ausente: prob_OK" in texto
    assert "classe_prevista" in texto and "TALVEZ" in texto
    assert "score_alerta_rede" in texto and "fora da faixa" in texto
    assert "cli prever" in erro.value.acao


def test_rejeita_probabilidades_incoerentes_e_arquivo_que_nao_e_previsao():
    df = pd.read_csv(io.StringIO(csv_rede()), dtype=str, keep_default_na=False)
    df.loc[0, "prob_OK"] = "0.50"
    with pytest.raises(ex.ErroContrato, match="diferente de 1"):
        carregar(df.to_csv(index=False))
    entrada = "id_fluxo,timestamp,perda_pct,alvo\n1_2,1791156000,0.0,OK\n"
    with pytest.raises(ex.ErroContrato) as erro:
        carregar(entrada)
    assert "não são previsões" in erro.value.acao
    with pytest.raises(ex.ErroContrato):
        carregar("")


def test_campos_opcionais_e_rotulos_ausentes_ficam_indisponiveis_com_motivo():
    prev = carregar(csv_rede(sem_opcionais=True))
    d = prev.descricao()
    assert d["modelo"]["versoes"] == [] and "versao_modelo" in d["modelo"]["motivo_ausencia"]
    assert d["rotulos"]["disponivel"] is False and "alvo" in d["rotulos"]["motivo"]
    r = ex.resumo(prev, np.ones(prev.n, bool))
    assert r["rotulos"]["disponivel"] is False and r["rotulos"]["motivo"]
    assert r["alertas"]["n"] == 8  # RISCO e FALHA têm score 0,8; OK tem 0,2


def test_rotulos_presentes_geram_metricas_exploratorias():
    rede = carregar(csv_rede(com_alvo=True))
    r = ex.resumo(rede, np.ones(rede.n, bool))["rotulos"]
    assert r["disponivel"] and r["tipo"] == "exploratoria"
    assert sum(map(sum, r["matriz_confusao"])) == rede.n
    lav = carregar(csv_lavagem(com_rotulo=True))
    r = ex.resumo(lav, np.ones(lav.n, bool))["rotulos"]
    m = r["matriz_confusao"]
    assert m["vp"] + m["fp"] + m["fn"] + m["vn"] == lav.n
    assert r["positivos"] == 6 and r["average_precision"] is not None


def test_filtros_combinados_equivalem_a_selecao_manual():
    prev = carregar(csv_rede(n=40))
    f = filtros(prev, classes="RISCO,FALHA", alerta="sim", score_min="0.5", fluxo="101",
                inicio="2026-10-04T23:30", fim="2026-10-05T01:00")
    m = ex.mascara(prev, f)
    b = prev.bruto
    t = pd.to_datetime(pd.to_numeric(b["timestamp_previsao"]), unit="s")
    esperado = (b["classe_prevista"].isin(["RISCO", "FALHA"]) & (b["alerta_rede"] == "True")
                & (pd.to_numeric(b["score_alerta_rede"]) >= 0.5) & b["id_fluxo"].str.contains("101")
                & (t >= pd.Timestamp("2026-10-04T23:30")) & (t < pd.Timestamp("2026-10-05T01:01")))
    assert m.sum() > 0
    assert np.array_equal(m, esperado.to_numpy())


def test_contagens_e_graficos_usam_todos_os_registros_filtrados_nao_a_pagina():
    prev = carregar(csv_rede(n=60))
    m = ex.mascara(prev, filtros(prev, alerta="sim"))
    r = ex.resumo(prev, m)
    pag = ex.pagina(prev, m, numero=1, tamanho=5)
    total = int(m.sum())
    assert len(pag["linhas"]) == 5 and pag["total"] == total == r["total_filtrado"]
    assert sum(k["n"] for k in r["classes"]) == total
    assert sum(p["total"] for p in r["serie_temporal"]["pontos"]) == total
    assert sum(r["histograma_score"]["contagens"]) == total
    assert r["alertas"]["n"] == sum(k["alertas"] for k in r["classes"]) == total


def test_ordenacao_preserva_identidade_e_desempata_pela_posicao():
    prev = carregar(csv_rede(n=30))
    m = np.ones(prev.n, bool)
    pag = ex.pagina(prev, m, ordenar="score_alerta_rede", direcao="desc", numero=1, tamanho=30)
    scores = [float(l["score_alerta_rede"]) for l in pag["linhas"]]
    assert scores == sorted(scores, reverse=True)
    for linha in pag["linhas"]:
        original = prev.bruto.iloc[linha["_linha"]].to_dict()
        assert {k: v for k, v in linha.items() if k != "_linha"} == original
    empatados = [l["_linha"] for l in pag["linhas"] if l["score_alerta_rede"] == pag["linhas"][0]["score_alerta_rede"]]
    assert empatados == sorted(empatados)
    with pytest.raises(ex.ErroFiltro):
        ex.pagina(prev, m, ordenar="coluna_inexistente")


def test_exportacao_respeita_filtros_e_preserva_valores_originais():
    prev = carregar(csv_lavagem(n=20), nome="previsoes_teste.csv")
    m = ex.mascara(prev, filtros(prev, moedas="Euro", alerta="sim"))
    conteudo, nome, meta = ex.exportar(prev, m)
    exportado = pd.read_csv(io.BytesIO(conteudo), dtype=str, keep_default_na=False)
    esperado = prev.bruto[m].reset_index(drop=True)
    assert exportado.equals(esperado)
    assert list(exportado.columns) == list(prev.bruto.columns)
    assert set(exportado["valor_pago"]) == {"100.50"}  # zero à direita preservado
    assert meta["registros"] == int(m.sum()) and "previsoes_teste" in nome and "20220910" in nome
    with pytest.raises(ex.ErroFiltro):
        ex.exportar(prev, np.zeros(prev.n, bool))


def test_valores_de_moedas_diferentes_nao_sao_somados():
    prev = carregar(csv_lavagem(n=10))
    r = ex.resumo(prev, np.ones(prev.n, bool))
    por_moeda = {x["moeda"]: x for x in r["por_moeda"]}
    assert set(por_moeda) == {"US Dollar", "Euro"}
    assert por_moeda["Euro"]["soma_valor"] == pytest.approx(5 * 100.50)
    assert por_moeda["US Dollar"]["soma_valor"] == pytest.approx(5 * 2500)
    assert "soma_valor" not in r  # nenhum total misturando moedas


def test_filtros_invalidos_geram_mensagem():
    prev = carregar(csv_rede())
    with pytest.raises(ex.ErroFiltro, match="data"):
        filtros(prev, inicio="ontem")
    with pytest.raises(ex.ErroFiltro, match="mínimo"):
        filtros(prev, score_min="0.9", score_max="0.1")
    with pytest.raises(ex.ErroFiltro, match="Classes"):
        filtros(prev, classes="TALVEZ")
