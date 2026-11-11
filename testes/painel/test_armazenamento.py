"""Resultados gravados: filtros sincronizados, denominadores, IDs de exibição, tipologias, contas e grafo."""

from __future__ import annotations

import pandas as pd
import pytest

from src.painel import armazenamento as arm
from src.painel import tipologias as tp
from src.painel.datasets import NAO_INFORMADO
from testes.painel.conftest import D, LINHAS_COM_ALERTA, ORDEM_ESPERADA, Ambiente, escrever, linha


def _f(**params) -> arm.Filtros:
    return arm.filtros_de_parametros({k: str(v) for k, v in params.items()})


def _todas(con) -> pd.DataFrame:
    return pd.DataFrame(arm.pagina(con, arm.Filtros(), 1, 200)["linhas"])


# -- IDs de exibição ---------------------------------------------------------------
def test_ids_de_exibicao_seguem_a_ordem_cronologica_com_desempate_pela_linha(analise_cenario):
    _, _, con = analise_cenario
    t = _todas(con)
    assert t["id_exibicao"].tolist() == list(range(1, 14))
    assert t["linha_arquivo"].tolist() == ORDEM_ESPERADA  # 09:00 primeiro; em 10:00, linhas 2, 3 e 12 nessa ordem
    assert t["data_hora"].is_monotonic_increasing
    assert set(t.loc[t["alerta"], "linha_arquivo"]) == LINHAS_COM_ALERTA


def test_ids_de_exibicao_nao_mudam_com_filtro_ordenacao_ou_pagina(analise_cenario):
    _, _, con = analise_cenario
    por_linha = dict(zip(_todas(con)["linha_arquivo"], _todas(con)["id_exibicao"]))
    filtrada = arm.pagina(con, _f(alerta="sim"), 1, 2, "score", "desc")
    segunda = arm.pagina(con, _f(alerta="sim"), 2, 2, "score", "desc")
    vistos = filtrada["linhas"] + segunda["linhas"]
    assert all(por_linha[x["linha_arquivo"]] == x["id_exibicao"] for x in vistos)
    assert [x["posicao"] for x in vistos] == [1, 2, 3, 4]          # a posição segue a lista atual
    assert [x["id_exibicao"] for x in vistos] != [1, 2, 3, 4]      # o ID não
    assert vistos[0]["score"] >= vistos[1]["score"] >= vistos[2]["score"]
    assert arm.detalhe(con, vistos[0]["id_exibicao"])["linha_arquivo"] == vistos[0]["linha_arquivo"]


def test_id_original_do_arquivo_fica_nos_detalhes(ambiente, tmp_path):
    df = pd.DataFrame({
        "id_transacao": ["ordem-B", "ordem-A"], "timestamp": ["2024-03-01T09:00:00Z", "2024-03-01T08:00:00Z"],
        "banco_origem": [1, 1], "conta_origem": ["A", "A"], "banco_destino": [2, 2], "conta_destino": ["B", "B"],
        "valor_pago": [10, 20], "moeda_pagamento": ["US Dollar"] * 2, "valor_recebido": [10, 20],
        "moeda_recebimento": ["US Dollar"] * 2, "formato": ["Wire"] * 2, "canal": ["app", "web"]})
    caminho = tmp_path / "pt.csv"
    df.to_csv(caminho, index=False)
    m = ambiente.analisar(caminho)
    con = ambiente.analises.conexao(m["id"])
    try:
        d = arm.detalhe(con, 1)
        assert (d["id_original"], d["linha_arquivo"], d["extras"]) == ("ordem-A", 3, {"canal": "web"})
        assert arm.detalhe(con, 2)["id_original"] == "ordem-B"
    finally:
        con.close()


# -- filtros sincronizados -------------------------------------------------------------
FILTROS = [
    {}, {"alerta": "sim"}, {"alerta": "nao"}, {"moeda": "Euro"}, {"valor_min": 1000}, {"banco_origem": 1},
    {"banco_destino": 2}, {"conta_origem": "A"}, {"conta_origem": "1-A"}, {"conta_destino": "2-E"},
    {"score_min": 301, "score_max": 700}, {"score_min": 701}, {"de": "2024-01-05T10:00", "ate": "2024-01-05T10:10"},
    {"de": "2024-01-05T10:30", "alerta": "sim", "moeda": "Euro"}, {"banco_origem": 3, "score_max": 300},
    {"conta_origem": "nao-existe"},
]


def _esperado(t: pd.DataFrame, p: dict) -> pd.DataFrame:
    m = pd.Series(True, index=t.index)
    if "alerta" in p:
        m &= t["alerta"] == (p["alerta"] == "sim")
    if "moeda" in p:
        m &= t["moeda_pagamento"] == p["moeda"]
    if "valor_min" in p:
        m &= t["valor_pago"] >= p["valor_min"]
    if "banco_origem" in p:
        m &= t["banco_origem"] == str(p["banco_origem"])
    if "banco_destino" in p:
        m &= t["banco_destino"] == str(p["banco_destino"])
    if "conta_origem" in p:
        m &= (t["conta_origem"] == p["conta_origem"]) | (t["no_origem"] == p["conta_origem"])
    if "conta_destino" in p:
        m &= (t["conta_destino"] == p["conta_destino"]) | (t["no_destino"] == p["conta_destino"])
    if "score_min" in p:
        m &= t["score"] >= p["score_min"]
    if "score_max" in p:
        m &= t["score"] <= p["score_max"]
    if "de" in p:
        m &= t["data_hora"] >= p["de"]
    if "ate" in p:
        m &= t["data_hora"] <= p["ate"]
    return t[m]


@pytest.mark.parametrize("params", FILTROS, ids=[str(p) or "sem filtro" for p in FILTROS])
def test_filtros_atualizam_juntos_indicadores_tabela_contas_e_grafo(analise_cenario, params):
    _, _, con = analise_cenario
    todas = _todas(con)
    esperado = _esperado(todas, params)
    f = _f(**params)
    visao = arm.visao_geral(con, f, 13, True, True)
    pag = arm.pagina(con, f, 1, 200)
    # indicadores e tabela contam as mesmas transações
    assert visao["registros"] == {"recorte": len(esperado), "dataset": 13, "legenda": visao["registros"]["legenda"]}
    assert pag["total"] == len(esperado) and [x["id_exibicao"] for x in pag["linhas"]] == esperado["id_exibicao"].tolist()
    assert visao["alertas"]["n"] == int(esperado["alerta"].sum())
    assert sum(fx["n"] for fx in visao["faixas"]) == len(esperado)
    if len(esperado):
        assert visao["periodo"]["inicio"] == esperado["data_hora"].min() and visao["periodo"]["fim"] == esperado["data_hora"].max()
        assert visao["score"]["min"] == esperado["score"].min() and visao["score"]["max"] == esperado["score"].max()
        assert visao["score"]["mediana"] == pytest.approx(esperado["score"].median())
    else:
        assert visao["periodo"] is None and visao["score"] is None and visao["alertas"]["proporcao"] is None
    # contas de maior risco: mesmas transações com alerta do recorte
    com_alerta = esperado[esperado["alerta"]]
    participacoes = pd.concat([com_alerta["no_origem"], com_alerta.loc[com_alerta["no_origem"] != com_alerta["no_destino"], "no_destino"]])
    assert {c["conta"]: c["alertas"] for c in visao["contas_risco"]["contas"]} == participacoes.value_counts().to_dict()
    # grafo: mesmos filtros, menos os de conta (que escolhem o foco)
    sem_conta = {k: v for k, v in params.items() if not k.startswith("conta_")}
    g = arm.grafo(con, f, "1-A", 2, tem_tipologias=True)
    assert g["totais"]["transacoes_recorte"] == len(_esperado(todas, sem_conta))
    base = _esperado(todas, sem_conta)
    diretas = base[(base["no_origem"] == "1-A") | (base["no_destino"] == "1-A")]
    assert g["vazio"] == diretas.empty
    assert g["totais"]["relacionadas"] >= len(diretas) and g["totais"]["exibidas"] <= g["totais"]["relacionadas"]


@pytest.mark.parametrize("params, campo", [
    ({"score_min": 1001}, "score_min"), ({"score_max": "7.5"}, "score_max"), ({"score_min": 800, "score_max": 100}, "score_max"),
    ({"valor_min": 0.5}, "valor_min"), ({"valor_min": "abc"}, "valor_min"), ({"alerta": "talvez"}, "alerta"),
    ({"de": "amanhã"}, "de"), ({"de": "2024-01-06T00:00", "ate": "2024-01-05T00:00"}, "ate"), ({"banco_origem": "ITAU"}, "banco_origem"),
])
def test_filtro_invalido_indica_o_campo(params, campo):
    with pytest.raises(arm.ErroFiltro) as exc:
        _f(**params)
    assert exc.value.campo == campo and exc.value.mensagem


def test_valor_minimo_aceita_a_partir_de_1_e_nao_existe_valor_maximo(analise_cenario):
    _, _, con = analise_cenario
    assert arm.pagina(con, _f(valor_min=1), 1, 50)["total"] == 13
    assert arm.pagina(con, _f(valor_min=2), 1, 50)["total"] == 12  # sai a transação de 1 iene
    assert not hasattr(arm.Filtros(), "valor_max") and not hasattr(arm.Filtros(), "motivo") and not hasattr(arm.Filtros(), "busca")


# -- denominadores e "Não informado" ------------------------------------------------------
def test_percentuais_por_formato_usam_o_recorte_como_denominador(analise_cenario):
    _, _, con = analise_cenario
    fm = arm.visao_geral(con, arm.Filtros(), 13, True, True)["formatos"]
    assert fm["denominador"] == 13 and fm["legenda"] == "% das 13 transações do recorte"
    itens = {i["formato"]: i for i in fm["itens"]}
    assert {k: v["n"] for k, v in itens.items()} == {"Wire": 5, "ACH": 3, "Cash": 2, NAO_INFORMADO: 2, "Cheque": 1}
    assert sum(i["n"] for i in fm["itens"]) == 13 and sum(i["proporcao"] for i in fm["itens"]) == pytest.approx(1.0)
    assert all(i["proporcao"] == pytest.approx(i["n"] / 13) for i in fm["itens"])
    assert itens[NAO_INFORMADO]["nao_informado"] is True and itens["Wire"]["nao_informado"] is False  # vazio e "Unknown"
    # com filtro, o denominador passa a ser o recorte filtrado
    euro = arm.visao_geral(con, _f(moeda="Euro"), 13, True, True)["formatos"]
    assert euro["denominador"] == 2 and "% das 2 transações" in euro["legenda"]
    assert {i["formato"]: i["proporcao"] for i in euro["itens"]} == {"Wire": 0.5, NAO_INFORMADO: 0.5}
    vazio = arm.visao_geral(con, _f(conta_origem="nao-existe"), 13, True, True)["formatos"]
    assert vazio["denominador"] == 0 and vazio["itens"] == []


def test_rotulo_do_dataset_fica_separado_da_previsao(analise_cenario):
    _, _, con = analise_cenario
    r = arm.visao_geral(con, arm.Filtros(), 13, True, True)["rotulo"]
    assert (r["disponivel"], r["rotuladas_lavagem"], r["rotuladas_com_alerta"]) == (True, 4, 4)
    assert "não é previsão" in r["legenda"]
    sem = arm.visao_geral(con, arm.Filtros(), 13, True, False)["rotulo"]
    assert sem == {"disponivel": False, "motivo": "Este dataset não tem rótulo de lavagem."}
    d = arm.detalhe(con, 2)  # linha 2: rótulo 1 e alerta, cada um em seu campo
    assert d["rotulo"] == 1 and d["alerta"] is True and d["faixa"] == "alta"


# -- tipologias ----------------------------------------------------------------------------
def test_tipologias_nenhuma_uma_e_varias(analise_cenario):
    _, m, con = analise_cenario
    t = _todas(con).set_index("linha_arquivo")["tipologias"]
    assert t[2] == ["FAN-OUT"] and t[3] == ["FAN-OUT"]      # uma
    assert t[5] == ["CYCLE", "STACK"]                        # várias
    assert t[6] == [] and t[4] == []                         # nenhuma (a 6 é idêntica à 5: só a primeira casa)
    tip = arm.visao_geral(con, arm.Filtros(), 13, True, True)["tipologias"]
    contagem = {i["tipologia"]: (i["n"], i["alertas"]) for i in tip["itens"]}
    assert list(contagem) == [*tp.TIPOLOGIAS, tp.NAO_IDENTIFICADO]  # as 8 + não identificado, zeradas inclusive
    assert contagem == {"BIPARTITE": (0, 0), "CYCLE": (1, 1), "FAN-IN": (0, 0), "FAN-OUT": (2, 2), "GATHER-SCATTER": (0, 0),
                        "RANDOM": (0, 0), "SCATTER-GATHER": (0, 0), "STACK": (1, 1), tp.NAO_IDENTIFICADO: (10, 2)}
    # a transação com duas tipologias conta em cada uma: a soma (14) passa do total (13)
    assert sum(n for n, _ in contagem.values()) == 14 and "conta em cada uma" in tip["legenda"]
    assert "registrada no dataset" in tip["origem"] and "não é previsão" in tip["origem"]
    d = arm.detalhe(con, int(_todas(con).set_index("linha_arquivo")["id_exibicao"][5]))
    assert d["tipologias"] == ["CYCLE", "STACK"] and d["tentativas"] == [2, 3]
    assert m["tipologias"]["casamento"] == {"transacoes_listadas": 5, "casadas": 4, "sem_correspondencia": 1,
                                            "transacoes_com_tipologia": 3, "transacoes_com_mais_de_uma": 1}
    # com filtro, as zeradas continuam na lista
    filtrado = arm.visao_geral(con, _f(conta_origem="1-B"), 13, True, True)["tipologias"]
    assert {i["tipologia"]: i["n"] for i in filtrado["itens"]} == {
        **{t_: 0 for t_ in tp.TIPOLOGIAS}, "CYCLE": 1, "STACK": 1, tp.NAO_IDENTIFICADO: 1}


def test_dataset_sem_tipologias_diz_isso_em_vez_de_zeros(ambiente, cenario):
    m = ambiente.analisar(cenario["dados"])  # sem arquivo de padrões
    con = ambiente.analises.conexao(m["id"])
    try:
        tip = arm.visao_geral(con, arm.Filtros(), 13, m["tipologias"]["disponivel"], True, m["tipologias"]["motivo"])["tipologias"]
        assert tip["disponivel"] is False and "itens" not in tip and "não tem tipologias" in tip["motivo"]
        g = arm.grafo(con, arm.Filtros(), "1-A", 2, tem_tipologias=False)
        assert g["tipologias"]["predominante"] == tp.NAO_IDENTIFICADO and g["tipologias"]["disponivel"] is False
        assert g["tipologias"]["disposicao"]["id"] == "camadas" and "não tem tipologias" in g["tipologias"]["origem"]
    finally:
        con.close()


# -- contas de maior risco ---------------------------------------------------------------------
def test_top_10_e_regra_de_ordenacao(tmp_path, fabrica_modelo):
    linhas = [linha(f"{D} 10:{i:02d}", 1, f"O{i:02d}", 9, "HUB", 60_000 + 2_000 * i) for i in range(1, 13)]
    linhas += [linha(f"{D} 11:00", 1, "P", 1, "Q", 55_000), linha(f"{D} 11:01", 1, "P", 1, "Q", 55_000)]
    linhas += [linha(f"{D} 11:10", 1, "P", 1, "R", 100), linha(f"{D} 11:11", 2, "S", 2, "T", 100)]  # sem alerta
    amb = Ambiente(tmp_path, fabrica_modelo(), bloco=50)
    m = amb.analisar(escrever(tmp_path / "contas.csv", linhas))
    con = amb.analises.conexao(m["id"])
    try:
        cr = arm.visao_geral(con, arm.Filtros(), 16, False, False)["contas_risco"]
        contas = cr["contas"]
        assert cr["limite"] == 10 and len(contas) == 10                      # 15 contas têm alerta; entram 10
        assert [c["conta"] for c in contas] == ["9-HUB", "1-P", "1-Q"] + [f"1-O{i:02d}" for i in range(12, 5, -1)]
        assert [c["alertas"] for c in contas] == [12, 2, 2] + [1] * 7        # 1º critério: quantidade de alertas
        assert contas[1]["maior_score"] == contas[2]["maior_score"]          # empate total → ordem alfabética
        scores = [c["maior_score"] for c in contas[3:]]
        assert scores == sorted(scores, reverse=True) and len(set(scores)) == 7  # 2º critério: maior score
        hub, p = contas[0], contas[1]
        assert (hub["alertas_como_origem"], hub["alertas_como_destino"], hub["transacoes_no_recorte"]) == (0, 12, 12)
        assert (p["alertas_como_origem"], p["alertas_como_destino"], p["transacoes_no_recorte"]) == (2, 0, 3)
        assert "score por conta" in cr["regra"] and "ordem alfabética" in cr["regra"]
        assert all("score" not in k or k == "maior_score" for k in contas[0])  # nenhum score por conta inventado
        assert arm.visao_geral(con, _f(alerta="nao"), 16, False, False)["contas_risco"]["contas"] == []
        so_p = arm.visao_geral(con, _f(conta_origem="P"), 16, False, False)["contas_risco"]["contas"]
        assert [(c["conta"], c["alertas"]) for c in so_p] == [("1-P", 2), ("1-Q", 2)]
    finally:
        con.close()


# -- grafo -----------------------------------------------------------------------------------------
def _arestas(g) -> dict:
    return {(a["origem"], a["destino"], a["moeda"]): a for a in g["arestas"]}


def test_grafo_direcao_valores_e_agrupamento_sem_misturar_moedas(analise_cenario):
    _, _, con = analise_cenario
    g = arm.grafo(con, arm.Filtros(), "1-A", 2, tem_tipologias=True)
    ar = _arestas(g)
    todas = _todas(con)
    # direção: toda aresta corresponde a transações com essa origem e esse destino
    for (o, d, moeda), a in ar.items():
        tx = todas[(todas["no_origem"] == o) & (todas["no_destino"] == d) & (todas["moeda_pagamento"] == moeda)]
        assert len(tx) == a["n"] and tx["valor_pago"].sum() == pytest.approx(a["total"])
        assert a["alertas"] == int(tx["alerta"].sum()) and a["agrupada"] == (a["n"] > 1)
    assert ("1-A", "1-B", "US Dollar") in ar and ("1-B", "1-A", "US Dollar") not in ar
    # aresta individual: valor e moeda da transação
    assert (ar[("1-A", "1-B", "US Dollar")]["n"], ar[("1-A", "1-B", "US Dollar")]["total"]) == (1, 80_000.0)
    # agrupada: mesma origem, destino e moeda → quantidade e total
    assert (ar[("1-B", "2-E", "US Dollar")]["n"], ar[("1-B", "2-E", "US Dollar")]["total"]) == (2, 170_000.0)
    # mesmo par em moedas diferentes: arestas separadas, nunca somadas
    assert (ar[("1-C", "2-F", "Euro")]["n"], ar[("1-C", "2-F", "Euro")]["total"]) == (2, 70_500.0)
    assert (ar[("1-C", "2-F", "US Dollar")]["n"], ar[("1-C", "2-F", "US Dollar")]["total"]) == (1, 1_000.0)
    assert ("1-A", "1-A", "US Dollar") in ar                          # autotransferência
    # totais do recorte, por moeda, sem soma entre moedas
    t = g["totais"]
    assert {m["moeda"]: (m["n"], m["total"]) for m in t["por_moeda"]} == {
        "US Dollar": (9, 381_500.0), "Euro": (2, 70_500.0), "Yen": (1, 1.0)}
    assert (t["transacoes_recorte"], t["relacionadas"], t["exibidas"], t["arestas"], t["vertices"]) == (13, 12, 12, 10, 8)
    assert t["alertas_relacionadas"] == 5
    # vértices: foco, quem recebeu e quem enviou; ligados a alerta marcados
    nos = {n["id"]: n for n in g["nos"]}
    assert nos["1-A"]["tipo"] == "foco" and nos["1-A"]["nivel"] == 0
    assert nos["1-B"]["tipo"] == "recebeu" and nos["2-F"]["nivel"] == 2 and nos["3-Z"]["tipo"] == "enviou"
    assert {k for k, n in nos.items() if n["alerta"]} == {"1-A", "1-B", "1-C", "2-E", "2-F"}
    assert "3-X" not in nos and "3-Y" not in nos                     # sem ligação com a conta em foco


def test_grafo_profundidade_e_cadeias(analise_cenario):
    _, _, con = analise_cenario
    um = arm.grafo(con, arm.Filtros(), "1-A", 1, tem_tipologias=True)
    assert ("1-B", "2-E", "US Dollar") not in _arestas(um)             # A → B → E só aparece com 2 saltos
    assert um["totais"]["relacionadas"] == 6 and um["limites"]["profundidade"] == 1
    dois = arm.grafo(con, arm.Filtros(), "1-A", 2, tem_tipologias=True)
    assert {("1-A", "1-B", "US Dollar"), ("1-B", "2-E", "US Dollar")} <= set(_arestas(dois))
    assert arm.grafo(con, arm.Filtros(), "1-A", 99, tem_tipologias=True)["limites"]["profundidade"] == arm.GRAFO_PROFUNDIDADE_MAX
    # a montante: quem enviou a quem enviou ao foco (X → Y não; B → E → A sim, pelo lado de E)
    e = arm.grafo(con, arm.Filtros(), "2-E", 2, tem_tipologias=True)
    assert {("1-A", "1-B", "US Dollar"), ("1-B", "2-E", "US Dollar"), ("2-E", "1-A", "US Dollar")} <= set(_arestas(e))


def test_grafo_respeita_limites_e_informa_x_de_y(analise_cenario):
    _, _, con = analise_cenario
    g = arm.grafo(con, arm.Filtros(), "1-A", 2, max_nos=4, max_arestas=3, tem_tipologias=True)
    assert len(g["nos"]) <= 4 and len(g["arestas"]) <= 3
    assert g["limites"]["max_nos"] == 4 and g["limites"]["max_arestas"] == 3
    t = g["totais"]
    assert t["exibidas"] == sum(a["n"] for a in g["arestas"]) < t["relacionadas"] == 12   # "exibindo X de Y"
    assert t["arestas"] == len(g["arestas"]) and t["arestas_relacionadas"] == 10 and t["vertices"] == len(g["nos"])
    # os totais continuam vindo do recorte inteiro, não só do que foi desenhado
    assert {m["moeda"]: m["n"] for m in t["por_moeda"]} == {"US Dollar": 9, "Euro": 2, "Yen": 1}
    # prioridade: arestas do foco com alerta entram primeiro; todo vértice desenhado liga-se ao foco
    assert {(a["origem"], a["destino"]) for a in g["arestas"][:2]} == {("1-A", "1-B"), ("1-A", "1-C")}
    ids = {n["id"] for n in g["nos"]}
    assert all(a["origem"] in ids and a["destino"] in ids for a in g["arestas"]) and "1-A" in ids


def test_vertices_arestas_e_linhas_da_tabela_se_correspondem(analise_cenario):
    _, _, con = analise_cenario
    g = arm.grafo(con, arm.Filtros(), "1-A", 2, tem_tipologias=True)
    todas = _todas(con)
    contas_tabela = set(todas["no_origem"]) | set(todas["no_destino"])
    for n in g["nos"]:
        assert n["id"] in contas_tabela and n["id"] == f"{n['banco']}-{n['conta']}"  # mesmo rótulo banco-conta da tabela
    for a in g["arestas"]:
        # o filtro que a tela aplica ao selecionar a aresta devolve exatamente as transações dela
        pag = arm.pagina(con, _f(conta_origem=a["origem"], conta_destino=a["destino"], moeda=a["moeda"]), 1, 50)
        assert pag["total"] == a["n"] and sum(x["valor_pago"] for x in pag["linhas"]) == pytest.approx(a["total"])
        assert {x["moeda_pagamento"] for x in pag["linhas"]} == {a["moeda"]}
        assert [x["data_hora"] for x in pag["linhas"]][0] == a["primeiro"] and [x["data_hora"] for x in pag["linhas"]][-1] == a["ultimo"]
    assert arm.resolver_conta(con, "A") == ["1-A"] and arm.resolver_conta(con, "1-A") == ["1-A"]
    assert arm.resolver_conta(con, "nao-existe") == []


def test_rotulos_abreviados_nao_colidem():
    ids = ["70-8000EBD30AAAAAAAAAAA1", "70-8000EBD30AAAAAAAAAAA2", "70-8000EBD30BBBBBBBBBBA1", "1-A"]
    rot = arm.rotulos_sem_colisao(ids)
    assert len(set(rot.values())) == len(ids) and rot["1-A"] == "1-A"
    iguais_no_meio = ["11-AAAA" + "X" * 30 + "ZZZZ", "11-AAAA" + "Y" * 30 + "ZZZZ"]
    rot = arm.rotulos_sem_colisao(iguais_no_meio, largura=10)
    assert len(set(rot.values())) == 2


def test_disposicao_segue_a_tipologia_registrada_nunca_a_aparencia(analise_cenario):
    _, _, con = analise_cenario
    g = arm.grafo(con, arm.Filtros(), "1-A", 2, tem_tipologias=True)
    tip = g["tipologias"]
    assert tip["contagem"] == {"FAN-OUT": 2, "CYCLE": 1, "STACK": 1} and tip["predominante"] == "FAN-OUT"
    assert tip["disposicao"]["id"] == "leque_saida" and "registrada no dataset" in tip["origem"]
    assert _arestas(g)[("1-B", "2-E", "US Dollar")]["tipologias"] == ["CYCLE", "STACK"]
    assert arm.disposicao_para("CYCLE")["id"] == "circular" and arm.disposicao_para("FAN-IN")["id"] == "leque_entrada"
    for sem_forma in ("STACK", "RANDOM", "BIPARTITE", "GATHER-SCATTER", "SCATTER-GATHER", tp.NAO_IDENTIFICADO):
        assert arm.disposicao_para(sem_forma)["id"] == "camadas"
    # 3-X só envia para 3-Y (um leque de saída "na aparência"), mas sem tipologia registrada fica não identificado
    x = arm.grafo(con, arm.Filtros(), "3-X", 2, tem_tipologias=True)
    assert x["tipologias"]["predominante"] == tp.NAO_IDENTIFICADO and x["tipologias"]["disposicao"]["id"] == "camadas"
    assert x["tipologias"]["contagem"] == {}


def test_grafo_de_conta_sem_transacoes_no_recorte(analise_cenario):
    _, _, con = analise_cenario
    g = arm.grafo(con, _f(moeda="Yen"), "1-A", 2, tem_tipologias=True)
    assert g["vazio"] is True and g["nos"] == [] and g["totais"]["transacoes_recorte"] == 1 and "filtros" in g["motivo"]


def test_mediana_de_scores_agrupados():
    assert arm._mediana([(10, 1), (20, 1), (30, 1)], 3) == 20
    assert arm._mediana([(10, 2), (20, 2)], 4) == 15
    assert arm._mediana([(0, 99), (900, 1)], 100) == 0
    assert arm._mediana([], 0) is None
