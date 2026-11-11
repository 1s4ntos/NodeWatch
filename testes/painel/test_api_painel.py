"""API do painel: fluxo completo, legendas, métricas históricas × contagens atuais, logs e assistente."""

from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path

import pytest

pytest.importorskip("flask")

from src import api_painel  # noqa: E402
from src.sentinel_ai import app  # noqa: E402
from testes.painel.conftest import CENARIO, PADROES, abrir_cliente, escrever  # noqa: E402

INTERFACE = Path(__file__).resolve().parents[2] / "interface"


@pytest.fixture
def cliente(tmp_path, fabrica_modelo):
    yield abrir_cliente(tmp_path, fabrica_modelo())  # com sessão ativa, como a página aberta
    api_painel._ctx.clear()  # as rotas reais se reconfiguram sozinhas no próximo uso


def _enviar(cliente, conteudo: bytes, nome: str = "cenario.csv", padroes: bytes = None):
    dados = {"arquivo": (io.BytesIO(conteudo), nome)}
    if padroes is not None:
        dados["padroes"] = (io.BytesIO(padroes), "padroes.txt")
    r = cliente.post("/api/painel/datasets", data=dados, content_type="multipart/form-data")
    if r.status_code != 201:
        return r, r.get_json()
    did = r.get_json()["id"]
    for _ in range(200):
        reg = cliente.get(f"/api/painel/datasets/{did}").get_json()
        if reg["status"] != "validando":
            return r, reg
        time.sleep(0.02)
    raise AssertionError("validação não terminou")


def _analisar(cliente, did: str) -> dict:
    r = cliente.post("/api/painel/analises", json={"dataset_id": did})
    assert r.status_code == 201, r.get_json()
    aid = r.get_json()["id"]
    for _ in range(400):
        m = cliente.get(f"/api/painel/analises/{aid}").get_json()
        if m["status"] != "em_andamento":
            return m
        time.sleep(0.02)
    raise AssertionError("análise não terminou")


def _cenario(tmp_path) -> bytes:
    return escrever(tmp_path / "c.csv", CENARIO, com_rotulo=True).read_bytes()


@pytest.fixture
def analise(cliente, tmp_path):
    _, reg = _enviar(cliente, _cenario(tmp_path), padroes=PADROES.encode("utf-8"))
    assert reg["status"] == "valido", reg
    return _analisar(cliente, reg["id"])


# -- página e ausência de efeitos ao abrir ---------------------------------------------
def test_pagina_inicial_e_o_painel_e_a_interface_anterior_fica_em_legado(cliente):
    r = cliente.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and 'lang="pt-BR"' in html and "painel-app.js" in html and "babel" not in html.lower().replace("sem babel", "")
    for arq in ("painel.css", "painel-base.js", "painel-grafo.js", "painel-secoes.js", "painel-app.js"):
        assert cliente.get(f"/assets/{arq}").status_code == 200, arq
    legado = cliente.get("/legado")
    assert legado.status_code == 200 and "Machine Learning" in legado.get_data(as_text=True)


def test_abrir_a_pagina_e_consultar_nao_inicia_nada(cliente, tmp_path):
    for rota in ("/", "/api/painel/estado", "/api/painel/datasets", "/api/painel/analises",
                 "/api/painel/operacao/desempenho", "/api/painel/operacao/logs", "/api/painel/operacao/metricas"):
        assert cliente.get(rota).status_code == 200, rota
    est = cliente.get("/api/painel/estado").get_json()
    assert est["analise_em_andamento"] is None and cliente.get("/api/painel/analises").get_json()["analises"] == []
    assert list((tmp_path / "artefatos_ml" / "painel" / "analises").iterdir()) == []
    _enviar(cliente, _cenario(tmp_path))  # enviar e validar também não analisa
    assert cliente.get("/api/painel/analises").get_json()["analises"] == []


# -- envio pela API ---------------------------------------------------------------------
def test_envio_valido_e_invalidos_pela_api(cliente, tmp_path):
    r, reg = _enviar(cliente, _cenario(tmp_path), nome="../../x/meu cenário.csv")
    assert r.status_code == 201 and reg["status"] == "valido" and reg["nome"] == "meu cenário.csv"
    assert reg["validacao"]["linhas"]["validas"] == 13 and str(tmp_path) not in json.dumps(reg)
    r, reg = _enviar(cliente, b"a,b\n1,2\n", nome="colunas.csv")
    assert r.status_code == 201 and reg["status"] == "invalido" and reg["erro"]["problemas"][0]["como_corrigir"]
    r, corpo = _enviar(cliente, b"x", nome="planilha.xlsx")
    assert r.status_code == 415 and corpo["problemas"][0]["problema"] and corpo["acao"]
    r = cliente.post("/api/painel/datasets", data={}, content_type="multipart/form-data")
    assert r.status_code == 400 and "arquivo" in r.get_json()["problemas"][0]["problema"]
    assert cliente.get("/api/painel/datasets/..%2F..%2Fsegredo").status_code == 404
    assert cliente.post("/api/painel/analises", json={"dataset_id": reg["id"] if "id" in reg else "ds-000000000000"}).status_code in (404, 409)
    assert cliente.post("/api/painel/analises", json={}).status_code == 400


# -- fluxo completo -----------------------------------------------------------------------
def test_fluxo_completo_pela_api(cliente, analise):
    aid = analise["id"]
    assert analise["status"] == "concluida" and analise["contagens"]["pontuadas"] == 13 and analise["contagens"]["alertas"] == 5
    assert [e["status"] for e in analise["etapas"]] == ["concluida"] * 6 and analise["descricao_status"].startswith("Concluída")
    base = f"/api/painel/analises/{aid}"
    visao = cliente.get(base + "/visao").get_json()
    assert visao["registros"]["recorte"] == 13 and visao["alertas"]["n"] == 5 and visao["analise"]["parcial"] is False
    pag = cliente.get(base + "/transacoes?alerta=sim&ordenar=score&direcao=desc&tamanho=2").get_json()
    assert pag["total"] == 5 and pag["paginas"] == 3 and len(pag["linhas"]) == 2 and pag["linhas"][0]["posicao"] == 1
    det = cliente.get(f"{base}/transacoes/{pag['linhas'][0]['id_exibicao']}").get_json()
    t = det["transacao"]
    assert t["alerta"] and t["faixa"] == "alta" and 0 <= t["score_bruto"] <= 1 and t["historico_incompleto"] is True
    assert det["modelo"]["versao"] == "teste-painel-v1" and det["modelo"]["limiar_alerta"] == 0.5
    assert det["rotulo_disponivel"] and det["tipologias_disponiveis"] and "não há integração bancária" in det["aviso_faixas"]
    assert isinstance(t["motivos"], list)
    assert cliente.get(base + "/transacoes/999").status_code == 404
    # grafo: foco pelo filtro de origem, pelo de destino ou pela conta escolhida
    por_origem = cliente.get(base + "/grafo?conta_origem=A").get_json()
    assert por_origem["foco"] == "1-A" and por_origem["escolha"] == "filtro Conta de origem"
    por_destino = cliente.get(base + "/grafo?conta_destino=2-E").get_json()
    assert por_destino["foco"] == "2-E" and por_destino["escolha"] == "filtro Conta de destino"
    escolhida = cliente.get(base + "/grafo?conta=1-B&conta_origem=A").get_json()
    assert escolhida["foco"] == "1-B" and escolhida["escolha"] == "conta selecionada"
    assert cliente.get(base + "/grafo").get_json()["sem_foco"] is True
    assert cliente.get(base + "/grafo?conta=nao-existe").get_json()["sem_foco"] is True
    # filtro inválido: 400 com o campo; página fora da faixa cai na última
    r = cliente.get(base + "/visao?score_min=2000")
    assert r.status_code == 400 and r.get_json()["campo"] == "score_min" and r.get_json()["acao"]
    assert cliente.get(base + "/transacoes?tamanho=5000").status_code == 400
    assert cliente.get(base + "/transacoes?pagina=99&tamanho=10").get_json()["pagina"] == 2
    # histórico
    lista = cliente.get("/api/painel/analises").get_json()
    assert [(a["id"], a["status"], a["registros"], a["alertas"]) for a in lista["analises"]] == [(aid, "concluida", 13, 5)]
    assert lista["retencao"]["max_analises"] == 20 and "mais recentes" in lista["retencao"]["leitura"]
    assert cliente.get("/api/painel/analises/an-inexistente/visao").status_code == 404


def test_conta_ambigua_pede_o_banco(cliente, tmp_path):
    from testes.painel.conftest import D, linha
    linhas = [linha(f"{D} 10:00", 1, "MESMA", 9, "Z", 10), linha(f"{D} 10:01", 2, "MESMA", 9, "Z", 10)]
    _, reg = _enviar(cliente, escrever(tmp_path / "amb.csv", linhas).read_bytes())
    m = _analisar(cliente, reg["id"])
    g = cliente.get(f"/api/painel/analises/{m['id']}/grafo?conta_origem=MESMA").get_json()
    assert g["ambiguo"] is True and g["candidatas"] == ["1-MESMA", "2-MESMA"]


def test_cancelar_pela_api_e_segunda_analise_e_recusada(tmp_path, fabrica_modelo):
    from testes.painel.conftest import D, Portao, linha
    portao = Portao()
    cliente = abrir_cliente(tmp_path, fabrica_modelo(portao.em(2)), bloco=5)
    try:
        linhas = [linha(f"{D} 10:{i:02d}", 1, f"C{i}", 2, "K", 100 + i) for i in range(30)]
        _, reg = _enviar(cliente, escrever(tmp_path / "m.csv", linhas).read_bytes())
        aid = cliente.post("/api/painel/analises", json={"dataset_id": reg["id"]}).get_json()["id"]
        assert portao.chegou.wait(30)
        assert cliente.get("/api/painel/estado").get_json()["analise_em_andamento"] == aid
        ocupada = cliente.post("/api/painel/analises", json={"dataset_id": reg["id"]})
        assert ocupada.status_code == 409 and "andamento" in ocupada.get_json()["erro"]
        assert cliente.get(f"/api/painel/analises/{aid}/visao").status_code == 409  # ainda sem resultados
        assert cliente.post(f"/api/painel/analises/{aid}/cancelar").get_json()["cancelamento_solicitado"] is True
        portao.liberar.set()
        for _ in range(400):
            m = cliente.get(f"/api/painel/analises/{aid}").get_json()
            if m["status"] != "em_andamento":
                break
            time.sleep(0.02)
        assert m["status"] == "cancelada" and m["resultados"]["parciais"] and m["resultados"]["pontuadas"] == 10
        visao = cliente.get(f"/api/painel/analises/{aid}/visao").get_json()
        assert visao["registros"]["dataset"] == 10 and visao["analise"]["parcial"] is True
    finally:
        portao.liberar.set()
        api_painel._ctx.clear()


# -- legendas ---------------------------------------------------------------------------------
def test_legendas_de_cores_setas_scores_icones_estados_e_filtros(cliente):
    est = cliente.get("/api/painel/estado").get_json()
    assert [(f["id"], f["de"], f["ate"]) for f in est["faixas"]] == [("baixa", 0, 300), ("intermediaria", 301, 700), ("alta", 701, 1000)]
    assert all(f["recomendacao"] for f in est["faixas"]) and "não prova" in est["aviso_faixas"]
    assert [t["tipologia"] for t in est["tipologias"]] == ["BIPARTITE", "CYCLE", "FAN-IN", "FAN-OUT", "GATHER-SCATTER", "RANDOM",
                                                         "SCATTER-GATHER", "STACK", "padrao_nao_identificado"]
    assert all(t["descricao"] for t in est["tipologias"])
    assert set(est["status_analise"]) == {"em_andamento", "concluida", "cancelada", "parcial", "erro"}
    assert "ordem alfabética" in est["regra_contas"] and est["assistente"]["servico_externo"] is False
    secoes = (INTERFACE / "assets" / "painel-secoes.js").read_text(encoding="utf-8")
    grafo = (INTERFACE / "assets" / "painel-grafo.js").read_text(encoding="utf-8")
    app_js = (INTERFACE / "assets" / "painel-app.js").read_text(encoding="utf-8")
    for texto in ("Legenda geral", "Score e faixas", "Cores e ícones", "Estados da análise", "Estados do dataset",
                  "faixa vermelha no início da linha", "⚠ Sim", "Contorno amarelo", "ID de exibição", "Não informado",
                  "Sessão da interface", "Traço tracejado", "Como ler o score", "Limiar original do modelo",
                  "registradas no dataset, não previstas"):
        assert texto in secoes, texto
    for texto in ("Legenda do grafo", "Conta em foco", "Conta ligada a alerta", "aponta da conta de", "Caminho com alerta",
                  "Aresta agrupada", "Valor, moeda e horário", "nunca são somadas", "Limites ativos", "Disposição", "exibindo ",
                  "Traço tracejado", "sem ordem temporal confirmada", "Ordem no tempo", "horários compatíveis"):
        assert texto in grafo, texto
    # cada filtro tem rótulo e uma linha de ajuda; os filtros removidos não voltam
    campos = re.findall(r"\{ id: '(\w+)', rotulo: '([^']+)', tipo: '[\w-]+'.*?ajuda: '([^']+)' \}", secoes)
    assert [c[0] for c in campos] == ["de", "ate", "moeda", "alerta", "valor_min", "banco_origem", "banco_destino",
                                      "conta_origem", "conta_destino", "score_min", "score_max"]
    assert all(rotulo and len(ajuda) > 15 for _, rotulo, ajuda in campos)
    for removido in ("motivo", "busca", "amostra", "valor_max"):
        assert f"id: '{removido}'" not in secoes
    # botão hambúrguer acessível e regiões com estado anunciado
    assert "'aria-expanded': lateral" in app_js and "'aria-controls': 'painel-operacional'" in app_js
    assert "'aria-live': 'polite'" in secoes and "role: 'tablist'" in secoes and "role: 'status'" in secoes


def test_interface_nao_traz_dados_de_exemplo_gravados(cliente):
    for arq in ("painel.html", "assets/painel-base.js", "assets/painel-grafo.js", "assets/painel-secoes.js", "assets/painel-app.js"):
        texto = (INTERFACE / arq).read_text(encoding="utf-8")
        assert not re.search(r"\b(C00\d|nameOrig|isFraud|Math\.random)\b", texto), arq  # nada de amostra nem de progresso simulado
        assert "setTimeout(() => irPara" in texto or "setTimeout" not in texto, arq   # só o ajuste de foco usa temporizador único


# -- painel operacional -----------------------------------------------------------------------------
def test_desempenho_informa_operacao_unidade_e_escopo(cliente, analise):
    cliente.get(f"/api/painel/analises/{analise['id']}/visao")
    cliente.get(f"/api/painel/analises/{analise['id']}/transacoes")
    d = cliente.get("/api/painel/operacao/desempenho").get_json()
    assert d["memoria"]["processo"]["escopo"] == "processo do NodeWatch" and d["memoria"]["maquina"]["escopo"] == "máquina"
    assert d["memoria"]["processo"]["bytes"] > 0 and 0 < d["memoria"]["maquina"]["percentual"] <= 100
    assert d["cpu"]["nucleos_logicos"] >= 1 and "percentual" in d["cpu"]["leitura"] and "processo_pct" in d["cpu"]
    operacoes = {l["operacao"]: l for l in d["latencias"]}
    assert {"visão geral do recorte", "página da tabela"} <= set(operacoes)
    assert all(l["unidade"] == "ms" and l["ultima_ms"] >= 0 and "servidor" in l["leitura"] for l in d["latencias"])
    a = d["analise"]
    assert a["id"] == analise["id"] and a["qual"] == "última análise encerrada" and a["duracao_total_s"] > 0
    assert a["pico_memoria_bytes"] > 0 and "processo do NodeWatch" in a["pico_escopo"]
    # duas vazões, cada uma com o numerador, o denominador e a fórmula; a da análise inteira nunca passa a da pontuação
    assert a["vazao_total_por_s"] == pytest.approx(a["transacoes_pontuadas"] / a["duracao_total_s"])
    assert a["vazao_pontuacao_por_s"] == pytest.approx(a["transacoes_pontuadas"] / a["tempo_pontuacao_s"])
    assert a["vazao_total_por_s"] <= a["vazao_pontuacao_por_s"] and a["tempo_pontuacao_s"] <= a["duracao_total_s"]
    assert "duração total" in a["vazao_total_formula"] and "atributos" in a["vazao_pontuacao_formula"]


def test_logs_do_sistema_e_de_ml_separados_e_sem_dados_sensiveis(cliente, analise):
    sistema = cliente.get("/api/painel/operacao/logs?tipo=sistema").get_json()["entradas"]
    ml = cliente.get("/api/painel/operacao/logs?tipo=ml").get_json()["entradas"]
    assert {"envio", "validacao_inicio", "validacao_fim", "analise_inicio", "analise_fim"} <= {e["evento"] for e in sistema}
    assert {"modelo_carregado", "pontuacao_medida"} <= {e["evento"] for e in ml}
    assert not {e["evento"] for e in sistema} & {e["evento"] for e in ml}
    carregado = next(e for e in ml if e["evento"] == "modelo_carregado")["contexto"]
    assert carregado["versao"] == "teste-painel-v1" and carregado["limiar_alerta"] == 0.5
    medido = next(e for e in ml if e["evento"] == "pontuacao_medida")["contexto"]
    assert medido["transacoes"] == 13 and medido["tempo_inferencia_s"] >= 0
    assert any(e["nivel"] == "aviso" for e in ml)  # avisos de atributos (histórico incompleto, formato não informado)
    assert all(e["quando"].endswith("Z") and e["mensagem"] for e in sistema + ml)
    tudo = json.dumps(sistema + ml, ensure_ascii=False)
    for sensivel in ("1-A", "2-E", "80000", "Temp", ":\\\\", "/Users/"):  # contas, valores e caminhos não vão para o log
        assert sensivel not in tudo, sensivel
    assert cliente.get("/api/painel/operacao/logs?tipo=outro").status_code == 400


def test_metricas_historicas_separadas_das_contagens_atuais(cliente, analise, tmp_path):
    # sem avaliação registrada no servidor: a tela diz isso; nada é emprestado da análise atual
    m = cliente.get(f"/api/painel/operacao/metricas?analise={analise['id']}").get_json()
    assert m["historicas"]["disponivel"] is False and m["historicas"]["motivo"]
    # com rótulo no dataset: métricas DESTE dataset, calculadas à parte e identificadas
    dd = m["do_dataset"]
    assert dd["disponivel"] and (dd["verdadeiros_positivos"], dd["falsos_positivos"], dd["falsos_negativos"]) == (4, 1, 0)
    assert dd["precisao"] == pytest.approx(0.8) and dd["recall"] == 1.0 and dd["f1"] == pytest.approx(8 / 9)
    assert 0 < dd["average_precision"] <= 1 and "rótulo do próprio dataset" in dd["origem"]
    assert set(m["legendas"]) == {"precisao", "recall", "f1", "average_precision"}
    # avaliação histórica presente: vem com origem, data, conjunto e ressalva, e continua separada
    res = tmp_path / "artefatos_ml" / "resultados"
    res.mkdir(parents=True)
    (res / "avaliacao_lavagem.json").write_text(json.dumps({
        "tarefa": "lavagem", "versao": "lavagem-historica", "escolhido": {"limiar_alerta": 0.09},
        "teste": {"modelo": {"n": 1000, "positivos": 10, "precisao": 0.6, "recall": 0.4, "f1": 0.48,
                             "average_precision": 0.46, "limiar": 0.09}}}), encoding="utf-8")
    (tmp_path / "artefatos_ml" / "metadados_modelo.json").write_text(json.dumps({
        "tarefas": {"lavagem": "treinada"}, "metadados": {},
        "cabecas": {"lavagem": {"familia": "random_forest", "limiar_alerta": 0.09, "metadados": {
            "versao": "lavagem-historica", "limites": {"validacao_ate": "2022-09-09", "teste_ate": "2022-09-11"}}}}}),
        encoding="utf-8")
    m = cliente.get(f"/api/painel/operacao/metricas?analise={analise['id']}").get_json()
    hi = m["historicas"]
    assert hi["disponivel"] and hi["versao_modelo"] == "lavagem-historica" and hi["origem"].endswith("avaliacao_lavagem.json")
    assert hi["arquivo_gravado_em"] and "não é uma avaliação inédita" in hi["ressalva"]
    teste = hi["conjuntos"][0]
    assert (teste["precisao"], teste["recall"], teste["f1"], teste["average_precision"]) == (0.6, 0.4, 0.48, 0.46)
    assert teste["transacoes"] == 1000 and "2022-09-09" in teste["periodo"]
    assert m["do_dataset"]["precisao"] == pytest.approx(0.8)  # não se confunde com a histórica (0,6)


def test_sem_rotulo_nao_ha_metricas_do_dataset(cliente, tmp_path):
    _, reg = _enviar(cliente, escrever(tmp_path / "sem.csv", [l.rsplit(",", 1)[0] for l in CENARIO]).read_bytes())
    m = _analisar(cliente, reg["id"])
    dd = cliente.get(f"/api/painel/operacao/metricas?analise={m['id']}").get_json()["do_dataset"]
    assert dd["disponivel"] is False and "não tem rótulo" in dd["motivo"] and "precisao" not in dd
    visao = cliente.get(f"/api/painel/analises/{m['id']}/visao").get_json()
    assert visao["rotulo"]["disponivel"] is False and visao["alertas"]["n"] == 5  # contagens atuais continuam lá
    sem_analise = cliente.get("/api/painel/operacao/metricas").get_json()["do_dataset"]
    assert sem_analise["disponivel"] is False


# -- assistente ------------------------------------------------------------------------------------------
def test_assistente_responde_so_com_base_verificavel(cliente, analise):
    def perguntar(texto, **extra):
        return cliente.post("/api/painel/assistente", json={"pergunta": texto, "analise_id": analise["id"], **extra}).get_json()

    r = perguntar("quantos alertas no recorte?")
    assert r["tipo"] == "fato" and "5 transações com alerta" in r["resposta"] and "13" in r["resposta"] and r["base"]
    r = perguntar("quantos alertas no recorte?", filtros={"moeda": "Euro"})
    assert "1 transação com alerta entre as 2" in r["resposta"]
    assert "2024-01-05 09:00" in perguntar("qual é o período?")["resposta"]
    assert perguntar("o que é FAN-IN?")["tipo"] == "glossario"
    assert "0–300" in perguntar("explique as faixas")["resposta"]
    assert perguntar("como cancelar a análise?")["tipo"] == "ajuda"
    for conclusiva in ("essa conta cometeu fraude?", "houve lavagem de dinheiro aqui?", "posso bloquear o cliente?"):
        r = perguntar(conclusiva)
        assert r["tipo"] == "limite" and "Não concluo" in r["resposta"]
    r = perguntar("qual a previsão do tempo amanhã?")
    assert r["tipo"] == "desconhecido" and r["base"] == [] and "Não tenho base" in r["resposta"]
    assert all(perguntar(p)["modo"] == "local (sem serviço externo)" for p in ("score", ""))
    sem = cliente.post("/api/painel/assistente", json={"pergunta": "quantos alertas?"}).get_json()
    assert "Nenhuma análise está aberta" in sem["resposta"]
