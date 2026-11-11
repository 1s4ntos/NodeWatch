"""Ordem temporal das cadeias do grafo, impacto do valor mínimo, legenda do score e fórmulas de vazão."""

from __future__ import annotations

import io
import time
from pathlib import Path

import numpy as np
import pytest

from src import api_painel
from src.painel import armazenamento as arm
from src.painel import score as sc
from testes.painel.conftest import CENARIO, D, PADROES, Ambiente, abrir_cliente, escrever, linha

INTERFACE = Path(__file__).resolve().parents[2] / "interface"

# A → B às 12:00. A partir de B: C antes (11:00), D no mesmo minuto (12:00), E depois (12:30); E → F às 13:00.
# Rumo a A: Y → A às 09:30. Para Y: X antes (09:00), Z no mesmo minuto (09:30), W depois (10:00, 0,25 Bitcoin).
TEMPORAL = [
    linha(f"{D} 12:00", 1, "A", 1, "B", 100), linha(f"{D} 11:00", 1, "B", 1, "C", 50), linha(f"{D} 12:00", 1, "B", 1, "D", 60),
    linha(f"{D} 12:30", 1, "B", 1, "E", 70), linha(f"{D} 13:00", 1, "E", 1, "F", 10), linha(f"{D} 10:00", 1, "C", 1, "G", 5),
    linha(f"{D} 09:30", 1, "Y", 1, "A", 40), linha(f"{D} 09:00", 1, "X", 1, "Y", 30), linha(f"{D} 09:30", 1, "Z", 1, "Y", 20),
    f"{D} 10:00,1,W,1,Y,0.25,Bitcoin,0.25,Bitcoin,Wire",
]


def _f(**params) -> arm.Filtros:
    return arm.filtros_de_parametros({k: str(v) for k, v in params.items()})


@pytest.fixture
def temporal(tmp_path, fabrica_modelo):
    amb = Ambiente(tmp_path, fabrica_modelo(), bloco=50)
    m = amb.analisar(escrever(tmp_path / "temporal.csv", TEMPORAL))
    assert m["status"] == "concluida", m
    con = amb.analises.conexao(m["id"])
    yield amb, m, con
    con.close()


def _ordens(g) -> dict:
    return {(a["origem"], a["destino"]): a["ordem"] for a in g["arestas"]}


# -- ordem temporal -----------------------------------------------------------------------------
def test_so_e_sequencia_o_que_tem_horario_compativel(temporal):
    _, _, con = temporal
    g = arm.grafo(con, arm.Filtros(), "1-A", 3)
    assert _ordens(g) == {
        ("1-A", "1-B"): "direta", ("1-Y", "1-A"): "direta",
        ("1-B", "1-E"): "sequencia", ("1-E", "1-F"): "sequencia", ("1-X", "1-Y"): "sequencia",
        ("1-B", "1-D"): "simultanea", ("1-Z", "1-Y"): "simultanea",         # mesmo minuto: ordem não confirmada
        ("1-B", "1-C"): "sem_ordem", ("1-W", "1-Y"): "sem_ordem",           # fora de ordem
        ("1-C", "1-G"): "sem_ordem",                                        # depende de uma relação não confirmada
    }
    ot = g["ordem_temporal"]
    assert ot["contagem"] == {"direta": 2, "sequencia": 3, "simultanea": 2, "sem_ordem": 3}
    assert "Parte das relações indiretas" in ot["resumo"] and "tracejadas" in ot["resumo"]
    assert "mesmo minuto" in ot["regra"] and "não prova que é o mesmo dinheiro" in ot["regra"]
    textos = {a["ordem"]: a["ordem_texto"] for a in g["arestas"]}
    assert textos["sem_ordem"] == "relação do recorte sem ordem temporal confirmada" and "ordem não confirmada" in textos["simultanea"]


def test_sequencias_trazem_origem_destino_valor_moeda_e_horario(temporal):
    _, _, con = temporal
    seqs = arm.grafo(con, arm.Filtros(), "1-A", 3)["ordem_temporal"]["sequencias"]
    resumo = {s["sentido"]: [(p["origem"], p["destino"], p["valor"], p["moeda"], p["data_hora"]) for p in s["passos"]] for s in seqs}
    assert resumo == {
        "a_jusante": [("1-A", "1-B", 100.0, "US Dollar", "2024-01-05T12:00"), ("1-B", "1-E", 70.0, "US Dollar", "2024-01-05T12:30"),
                      ("1-E", "1-F", 10.0, "US Dollar", "2024-01-05T13:00")],
        "a_montante": [("1-X", "1-Y", 30.0, "US Dollar", "2024-01-05T09:00"), ("1-Y", "1-A", 40.0, "US Dollar", "2024-01-05T09:30")],
    }
    for s in seqs:  # horários estritamente crescentes ao longo da sequência
        horas = [p["data_hora"] for p in s["passos"]]
        assert horas == sorted(horas) and len(set(horas)) == len(horas)
        assert all(arm.detalhe(con, p["id_exibicao"])["no_origem"] == p["origem"] for p in s["passos"])  # passo ↔ linha da tabela


def test_so_relacoes_diretas_ou_sem_ordem_nao_viram_cadeia(temporal):
    _, _, con = temporal
    direto = arm.grafo(con, arm.Filtros(), "1-A", 1)["ordem_temporal"]
    assert direto["contagem"]["sequencia"] == 0 and direto["sequencias"] == [] and "não afirma nenhuma cadeia" in direto["resumo"]
    c = arm.grafo(con, arm.Filtros(), "1-C", 2)        # B → C (11:00) e depois... nada sai de C após receber de B? C → G foi às 10:00
    assert _ordens(c)[("1-C", "1-G")] == "direta" and _ordens(c)[("1-B", "1-C")] == "direta"
    assert _ordens(c)[("1-A", "1-B")] == "sem_ordem"   # A → B (12:00) veio DEPOIS de B → C (11:00): não é etapa anterior
    assert "sem ordem temporal confirmada" in arm.grafo(con, arm.Filtros(), "1-C", 2)["ordem_temporal"]["resumo"].lower()


def test_cenario_principal_tem_tres_sequencias_confirmadas(analise_cenario):
    _, _, con = analise_cenario
    g = arm.grafo(con, arm.Filtros(), "1-A", 2, tem_tipologias=True)
    ordens = _ordens(g)
    assert ordens[("1-A", "1-B")] == "direta" and ordens[("1-B", "2-E")] == "sequencia" and ordens[("2-E", "1-A")] == "direta"
    assert ordens[("1-A", "1-A")] == "direta" and g["ordem_temporal"]["contagem"]["sem_ordem"] == 0
    caminhos = sorted(" → ".join([s["passos"][0]["origem"]] + [p["destino"] for p in s["passos"]]) for s in g["ordem_temporal"]["sequencias"])
    assert caminhos == ["1-A → 1-B → 2-E", "1-A → 1-C → 2-F", "1-A → 1-D → 2-G"]
    com_alerta = {tuple(p["destino"] for p in s["passos"]): s["alerta"] for s in g["ordem_temporal"]["sequencias"]}
    assert com_alerta[("1-B", "2-E")] is True and com_alerta[("1-D", "2-G")] is False
    assert "horários compatíveis" in g["ordem_temporal"]["resumo"]
    # a aresta agrupada continua com total, quantidade e intervalo de horários; os valores individuais vêm da tabela
    be = next(a for a in g["arestas"] if (a["origem"], a["destino"]) == ("1-B", "2-E"))
    assert (be["n"], be["total"], be["primeiro"], be["ultimo"]) == (2, 170_000.0, "2024-01-05T10:10", "2024-01-05T10:10")
    individuais = arm.pagina(con, _f(conta_origem="1-B", conta_destino="2-E", moeda="US Dollar"), 1, 50)["linhas"]
    assert [x["valor_pago"] for x in individuais] == [85_000.0, 85_000.0]


def test_interface_do_grafo_marca_relacoes_sem_ordem_e_mostra_horarios():
    grafo = (INTERFACE / "assets" / "painel-grafo.js").read_text(encoding="utf-8")
    css = (INTERFACE / "assets" / "painel.css").read_text(encoding="utf-8")
    assert "semOrdem(a) ? ' sem-ordem'" in grafo and ".g-aresta.sem-ordem path.traco { stroke-dasharray" in css
    assert "horarioAresta(a)" in grafo and "sem ordem confirmada" in grafo and "Valores individuais desta aresta" in grafo
    assert "não consideram a ordem no tempo" not in grafo            # a frase antiga saiu
    assert "Horário compatível não prova que é o mesmo dinheiro" in grafo


# -- valor mínimo ---------------------------------------------------------------------------------
def test_valor_minimo_padrao_e_impacto_registrado(temporal):
    _, _, con = temporal
    sem = arm.visao_geral(con, arm.Filtros(), 10, False, False)
    assert sem["registros"]["recorte"] == 10 and sem["valor_minimo"]["aplicado"] is None and sem["valor_minimo"]["fora"] == 0
    com = arm.visao_geral(con, _f(valor_min=1), 10, False, False)        # o padrão da tela
    assert com["registros"]["recorte"] == 9
    vm = com["valor_minimo"]
    assert (vm["aplicado"], vm["fora"], vm["alertas_fora"]) == (1.0, 1, 0)
    assert vm["por_moeda"] == [{"moeda": "Bitcoin", "n": 1, "alertas": 0}] and "sem conversão" in vm["legenda"]
    assert com["registros"]["recorte"] + vm["fora"] == sem["registros"]["recorte"]   # nada some sem registro
    # o grafo segue o mesmo filtro: a relação de 0,25 Bitcoin sai do desenho
    assert ("1-W", "1-Y") not in _ordens(arm.grafo(con, _f(valor_min=1), "1-A", 3))
    assert ("1-W", "1-Y") in _ordens(arm.grafo(con, arm.Filtros(), "1-A", 3))


def test_valor_minimo_nao_converte_moedas_e_respeita_os_outros_filtros(analise_cenario):
    _, _, con = analise_cenario
    vm = arm.visao_geral(con, _f(valor_min=1000), 13, True, True)["valor_minimo"]
    assert vm["fora"] == 5 and {m["moeda"]: m["n"] for m in vm["por_moeda"]} == {"US Dollar": 3, "Euro": 1, "Yen": 1}
    assert arm.visao_geral(con, _f(valor_min=1), 13, True, True)["valor_minimo"]["fora"] == 0      # 1 iene passa: é 1 unidade da moeda
    so_euro = arm.visao_geral(con, _f(valor_min=1000, moeda="Euro"), 13, True, True)
    assert so_euro["registros"]["recorte"] == 1 and so_euro["valor_minimo"]["fora"] == 1
    assert not hasattr(arm.Filtros(), "valor_max")


def test_tela_comeca_com_valor_minimo_1_e_avisa_o_que_fica_fora(tmp_path, fabrica_modelo):
    c = abrir_cliente(tmp_path, fabrica_modelo())
    try:
        assert c.get("/api/painel/estado").get_json()["valor_minimo_padrao"] == 1
        app_js = (INTERFACE / "assets" / "painel-app.js").read_text(encoding="utf-8")
        secoes = (INTERFACE / "assets" / "painel-secoes.js").read_text(encoding="utf-8")
        assert "valor_min: String((est && est.valor_minimo_padrao) || 1)" in app_js and "setAplicados(iniciais)" in app_js
        assert "deixa ' + f.plural(v.valor_minimo.fora" in secoes and "Começa em 1" in secoes and "id: 'valor_max'" not in secoes
    finally:
        api_painel._ctx.clear()


# -- score original, limiar e faixas ----------------------------------------------------------------
@pytest.mark.parametrize("limiar", [0.09098389273779739, 0.5, 0.2])
def test_faixas_no_score_original_batem_com_a_conversao(limiar):
    d = sc.descricao_conversao(limiar)
    fx = {f["id"]: f for f in d["faixas_no_score_original"]}
    assert fx["baixa"]["de"] == 0.0 and fx["baixa"]["ate"] == fx["intermediaria"]["de"]
    assert fx["intermediaria"]["ate"] == fx["alta"]["de"] == limiar and fx["alta"]["ate"] == 1.0
    corte = fx["baixa"]["ate"]  # fronteira 300 | 301, a menos do arredondamento de ponto flutuante
    assert sc.converter([corte * (1 - 1e-9)], limiar)[0] == 300 and sc.converter([corte * (1 + 1e-9)], limiar)[0] == 301
    assert sc.converter([np.nextafter(limiar, 0)], limiar)[0] == 700 and sc.converter([limiar], limiar)[0] == 701
    assert d["calibrado"] is False and "não é probabilidade" in d["natureza"]


def test_legenda_do_score_mostra_o_limiar_original_e_a_evidencia(tmp_path, fabrica_modelo):
    import json
    res = tmp_path / "artefatos_ml" / "resultados"
    res.mkdir(parents=True)
    (res / "avaliacao_lavagem.json").write_text(json.dumps({"tarefa": "lavagem", "versao": "v", "teste": {
        "modelo": {"n": 10, "positivos": 1}, "calibracao": {"caixas": [
            {"de": 0.0, "ate": 0.1, "n": 862278, "prob_media": 0.0014, "frequencia_observada": 0.0007},
            {"de": 0.1, "ate": 0.2, "n": 477, "prob_media": 0.136, "frequencia_observada": 0.648}]}}}), encoding="utf-8")
    (tmp_path / "artefatos_ml" / "metadados_modelo.json").write_text(json.dumps({
        "tarefas": {"lavagem": "treinada"}, "metadados": {}, "cabecas": {"lavagem": {
            "familia": "random_forest", "limiar_alerta": 0.09098389273779739, "metadados": {"versao": "v"}}}}), encoding="utf-8")
    c = abrir_cliente(tmp_path, fabrica_modelo())
    try:
        s = c.get("/api/painel/estado").get_json()["score"]
        assert s["calibrado"] is False and s["limiar_original"] == pytest.approx(0.091, abs=1e-4) and s["score_alerta"] == 701
        assert "não é probabilidade calibrada" in s["natureza"] and "nem de fraude" in s["natureza"] and "701" in s["conversao"]
        fx = {f["id"]: (round(f["de"], 4), round(f["ate"], 4)) for f in s["faixas_no_score_original"]}
        assert fx == {"baixa": (0.0, 0.0391), "intermediaria": (0.0391, 0.091), "alta": (0.091, 1.0)}
        ev = s["evidencia_de_nao_calibracao"]
        assert ev["origem"].endswith("avaliacao_lavagem.json") and ev["caixas"][1]["fracao_rotulada_lavagem"] == 0.648
        assert ev["caixas"][1]["score_medio"] == 0.136 and "não é uma probabilidade" in ev["leitura"]
    finally:
        api_painel._ctx.clear()


# -- vazão ------------------------------------------------------------------------------------------
def test_vazoes_do_manifesto_tem_numerador_e_intervalo_explicitos(ambiente, cenario):
    m = ambiente.analisar(cenario["dados"])
    d, n = m["desempenho"], m["contagens"]["pontuadas"]
    assert n == d["transacoes_pontuadas"] == 13 == m["contagens"]["validas"] == m["contagens"]["lidas"]
    pontuacao = d["tempo_atributos_s"] + d["tempo_inferencia_s"] + d["tempo_gravacao_s"]
    assert d["vazao_transacoes_por_s"] == pytest.approx(n / pontuacao, rel=0.25)           # só a etapa de pontuação
    assert d["vazao_total_transacoes_por_s"] == pytest.approx(n / d["duracao_total_s"])    # a análise inteira
    assert d["vazao_total_transacoes_por_s"] <= d["vazao_transacoes_por_s"] and pontuacao <= d["duracao_total_s"]
    assert d["duracao_total_s"] == m["duracao_s"]


# -- a interface anterior não aparece no fluxo novo ----------------------------------------------------
def test_pagina_antiga_nao_esta_ligada_ao_painel():
    html = (INTERFACE / "painel.html").read_text(encoding="utf-8")
    textos = {a: (INTERFACE / "assets" / a).read_text(encoding="utf-8") for a in
              ("painel-base.js", "painel-grafo.js", "painel-secoes.js", "painel-app.js")}
    assert all("legado" not in t.lower() for t in textos.values())               # nenhum link ou menção nos componentes
    assert html.count("/legado") == 2 and "location.replace('/legado' + location.hash)" in html  # só o redirecionamento dos endereços antigos
    assert "href=\"/legado" not in html and "Análise de rede" not in html
    assert all("Análise de rede" not in t and "estado_rede" not in t and "#ml" not in t for t in textos.values())
    assert "nodewatch-logo.png" in textos["painel-app.js"] and "assets/logo" not in textos["painel-app.js"].replace("nodewatch-logo", "")
    for arq in ("nodewatch-logo.png", "nodewatch-simbolo.png"):
        assert (INTERFACE / "assets" / arq).stat().st_size > 5_000
    css = (INTERFACE / "assets" / "painel.css").read_text(encoding="utf-8")
    for texto in (html, css, *textos.values()):                                    # nada vem de CDN nem de fora
        assert "http://" not in texto.replace("http://127.0.0.1", "").replace("http://localhost", "") and "https://" not in texto and "@import" not in texto
    assert "color-scheme: dark" in css and "prefers-reduced-motion: reduce" in css and ":focus-visible" in css


def test_sequencia_que_volta_a_conta_em_foco_e_listada(tmp_path, fabrica_modelo):
    """Regressão: foco → B → foco com horários compatíveis era marcada como sequência, mas não aparecia na lista."""
    linhas = [linha(f"{D} 10:00", 1, "A", 1, "B", 500), linha(f"{D} 10:05", 1, "B", 1, "A", 450),   # ida e volta
              linha(f"{D} 11:00", 1, "A", 1, "C", 300), linha(f"{D} 10:55", 1, "C", 1, "A", 100)]   # "volta" antes da ida
    amb = Ambiente(tmp_path, fabrica_modelo(), bloco=50)
    m = amb.analisar(escrever(tmp_path / "volta.csv", linhas))
    con = amb.analises.conexao(m["id"])
    try:
        g = arm.grafo(con, arm.Filtros(), "1-A", 2)
        assert _ordens(g) == {("1-A", "1-B"): "direta", ("1-B", "1-A"): "sequencia",
                              ("1-A", "1-C"): "direta", ("1-C", "1-A"): "sem_ordem"}
        seqs = g["ordem_temporal"]["sequencias"]
        assert [(s["sentido"], [(x["origem"], x["destino"], x["data_hora"]) for x in s["passos"]]) for s in seqs] == [
            ("volta_ao_foco", [("1-A", "1-B", "2024-01-05T10:00"), ("1-B", "1-A", "2024-01-05T10:05")])]
        assert g["ordem_temporal"]["sequencias_total"] == 1
        assert "sem ordem temporal confirmada" in g["ordem_temporal"]["resumo"]   # a C → A anterior não vira cadeia
    finally:
        con.close()
    js = (INTERFACE / "assets" / "painel-grafo.js").read_text(encoding="utf-8")
    assert "s.sentido === 'volta_ao_foco' ? ', volta à conta em foco'" in js
