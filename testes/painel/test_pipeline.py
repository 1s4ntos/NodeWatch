"""Progresso real, cancelamento, análise parcial, erro, manifesto e reabertura do histórico."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pandas as pd
import pytest

from src.painel import armazenamento as arm
from src.painel import pipeline as pl
from src.painel.datasets import ErroDataset
from src.painel.util import gravar_json_atomico, ler_json
from testes.painel.conftest import D, Ambiente, Portao, escrever, linha

ETAPAS = ["leitura", "ordenacao", "tipologias", "pontuacao", "indices", "manifesto"]


def _muitas(n: int = 30):
    """n transações em minutos diferentes (cada bloco de teste fecha na virada do minuto)."""
    return [linha(f"{D} {10 + i // 60:02d}:{i % 60:02d}", 1, f"C{i % 7}", 2, f"K{i % 5}", 1_000 + i) for i in range(n)]


def test_abrir_o_painel_nao_inicia_analise(ambiente, cenario):
    ambiente.enviar(cenario["dados"])  # enviar e validar também não analisa
    assert ambiente.analises.listar() == [] and ambiente.analises.em_andamento() is None
    assert ambiente.cargas_do_modelo == 0
    assert list((ambiente.raiz / pl.PASTA).iterdir()) == []


def test_analise_so_comeca_com_dataset_valido(ambiente, tmp_path):
    reg = ambiente.enviar(escrever(tmp_path / "ruim.csv", [linha("ontem", 1, "A", 1, "B", 1)]))
    assert reg["status"] == "invalido"
    with pytest.raises(ErroDataset):
        ambiente.analises.iniciar(reg["id"])
    assert ambiente.analises.listar() == []


def test_analise_completa_registra_etapas_reais_e_manifesto(ambiente, cenario):
    m = ambiente.analisar(cenario["dados"], cenario["padroes"])
    assert m["status"] == "concluida" and [e["id"] for e in m["etapas"]] == ETAPAS
    assert all(e["status"] == "concluida" and e["duracao_s"] is not None for e in m["etapas"])
    leitura, pontuacao = m["etapas"][0], m["etapas"][3]
    tamanho = cenario["dados"].stat().st_size
    assert leitura["progresso"]["unidade"] == "bytes" and leitura["progresso"]["feito"] == leitura["progresso"]["total"] == tamanho
    assert pontuacao["progresso"]["unidade"] == "transações" and pontuacao["progresso"]["feito"] == pontuacao["progresso"]["total"] == 13
    assert "estimativa_restante_s" not in pontuacao["progresso"]  # etapa encerrada não carrega estimativa
    # manifesto gravado: id, dataset, hash, data, status, etapas, duração, modelo, limiar, contagens e erros
    em_disco = json.loads((ambiente.raiz / pl.PASTA / m["id"] / "manifesto.json").read_text(encoding="utf-8"))
    for chave in ("id", "dataset", "criada_em", "status", "etapas", "duracao_s", "modelo", "contagens", "erros",
                  "conversao_score", "retencao"):
        assert chave in em_disco, chave
    assert em_disco["dataset"]["sha256"] and len(em_disco["dataset"]["sha256"]) == 64
    assert em_disco["modelo"] == {"versao": "teste-painel-v1", "familia": "regra_de_teste", "limiar_alerta": 0.5,
                                  "treinado_ate": "2020-01-01", "fonte": "regra fixa de teste", "aviso": None}
    assert em_disco["conversao_score"]["limiar_bruto"] == 0.5
    c = em_disco["contagens"]
    assert (c["lidas"], c["validas"], c["recusadas"], c["pontuadas"], c["alertas"]) == (13, 13, 0, 13, 5)
    assert c["por_faixa"] == {"baixa": 7, "intermediaria": 1, "alta": 5}
    assert em_disco["resultados"] == {"disponiveis": True, "parciais": False, "pontuadas": 13, "de": 13}
    assert em_disco["desempenho"]["transacoes_pontuadas"] == 13 and em_disco["desempenho"]["tempo_inferencia_s"] >= 0
    assert not list((ambiente.raiz / pl.PASTA / m["id"]).glob("*.tmp"))  # escrita atômica não deixa sobras
    assert ambiente.cargas_do_modelo == 1


def test_etapa_de_tipologias_e_pulada_sem_arquivo_de_padroes(ambiente, cenario):
    m = ambiente.analisar(cenario["dados"])
    assert m["etapas"][2]["status"] == "pulada" and m["tipologias"]["disponivel"] is False
    assert "não tem tipologias" in m["tipologias"]["motivo"]


def test_progresso_medido_durante_a_execucao(tmp_path, fabrica_modelo):
    portao = Portao()
    amb = Ambiente(tmp_path, fabrica_modelo(portao.em(3)), bloco=5)
    reg = amb.enviar(escrever(tmp_path / "muitas.csv", _muitas(30)))
    m = amb.analises.iniciar(reg["id"])
    assert portao.chegou.wait(30)
    vivo = amb.analises.obter(m["id"])  # terceiro bloco em curso: dois já gravados
    etapas = {e["id"]: e for e in vivo["etapas"]}
    assert vivo["status"] == "em_andamento" and etapas["leitura"]["status"] == "concluida"
    assert etapas["pontuacao"]["status"] == "em_andamento" and etapas["indices"]["status"] == "pendente"
    assert etapas["pontuacao"]["progresso"]["feito"] == 10 and etapas["pontuacao"]["progresso"]["total"] == 30
    assert vivo["contagens"]["pontuadas"] == 10
    portao.liberar.set()
    assert amb.analises.esperar(m["id"], 60)["status"] == "concluida"


def test_estimativa_so_aparece_com_base_medida(ambiente, cenario, monkeypatch):
    m = ambiente.analisar(cenario["dados"])
    vivo = ambiente.analises._manifestos[m["id"]]
    chave = m["id"] + "pontuacao"
    ambiente.analises._inicio_etapa[chave] = time.monotonic() - 0.5   # pouco tempo: sem base
    ambiente.analises._progresso(vivo, "pontuacao", 100, 1_000)
    assert "estimativa_restante_s" not in ambiente.analises._etapa(vivo, "pontuacao")["progresso"]
    ambiente.analises._inicio_etapa[chave] = time.monotonic() - 10.0  # 10 s observados
    ambiente.analises._progresso(vivo, "pontuacao", 0, 1_000)         # nada feito ainda: sem base
    assert "estimativa_restante_s" not in ambiente.analises._etapa(vivo, "pontuacao")["progresso"]
    ambiente.analises._progresso(vivo, "pontuacao", 250, 1_000)
    p = ambiente.analises._etapa(vivo, "pontuacao")["progresso"]
    assert p["estimativa_restante_s"] == pytest.approx(30.0, rel=0.05)  # 750 restantes ÷ 25 por segundo
    assert p["vazao_por_s"] == pytest.approx(25.0, rel=0.05) and "vazão observada" in p["base_estimativa"]
    ambiente.analises._progresso(vivo, "pontuacao", 1_000, 1_000)     # terminou: sem estimativa
    assert "estimativa_restante_s" not in ambiente.analises._etapa(vivo, "pontuacao")["progresso"]


def test_cancelamento_em_ponto_seguro_mantem_o_parcial(tmp_path, fabrica_modelo):
    portao = Portao()
    amb = Ambiente(tmp_path, fabrica_modelo(portao.em(3)), bloco=5)
    reg = amb.enviar(escrever(tmp_path / "muitas.csv", _muitas(30)))
    m = amb.analises.iniciar(reg["id"])
    assert portao.chegou.wait(30)
    pedido = amb.analises.cancelar(m["id"])
    assert pedido["cancelamento_solicitado"] and pedido["status"] == "em_andamento"
    portao.liberar.set()                      # o bloco em curso termina; o cancelamento vale no ponto seguro seguinte
    fim = amb.analises.esperar(m["id"], 60)
    assert fim["status"] == "cancelada" and "pedido" in fim["motivo"]
    assert fim["resultados"] == {"disponiveis": True, "parciais": True, "pontuadas": 15, "de": 30}
    assert "15 de 30" in fim["motivo"]
    etapas = {e["id"]: e["status"] for e in fim["etapas"]}
    assert etapas["pontuacao"] == "cancelada" and etapas["indices"] == "concluida"
    con = amb.analises.conexao(m["id"])
    try:  # o parcial é consultável e contém as primeiras transações em ordem cronológica
        pag = arm.pagina(con, arm.Filtros(), 1, 50)
        assert [x["id_exibicao"] for x in pag["linhas"]] == list(range(1, 16))
    finally:
        con.close()
    assert amb.analises.em_andamento() is None
    eventos = [e["evento"] for e in amb.registro.listar("sistema")]
    assert "analise_cancelamento" in eventos and "analise_fim" in eventos


def test_cancelamento_antes_de_pontuar_nao_deixa_resultados(tmp_path, fabrica_modelo, monkeypatch):
    amb = Ambiente(tmp_path, fabrica_modelo(), bloco=5)
    reg = amb.enviar(escrever(tmp_path / "muitas.csv", _muitas(30)))
    original = pl.GerenciadorAnalises._abrir_etapa

    def cancelar_na_ordenacao(self, m, eid):
        if eid == "ordenacao":
            self._cancelar[m["id"]].set()
        return original(self, m, eid)

    monkeypatch.setattr(pl.GerenciadorAnalises, "_abrir_etapa", cancelar_na_ordenacao)
    fim = amb.analises.esperar(amb.analises.iniciar(reg["id"])["id"], 60)
    assert fim["status"] == "cancelada" and fim["resultados"]["disponiveis"] is False
    with pytest.raises(pl.SemResultados):
        amb.analises.conexao(fim["id"])


def test_erro_no_modelo_informa_causa_acao_e_guarda_o_parcial(tmp_path, fabrica_modelo):
    def falhar(chamada: int) -> None:
        if chamada == 3:
            raise RuntimeError("falha simulada na inferência")

    amb = Ambiente(tmp_path, fabrica_modelo(falhar), bloco=5)
    fim = amb.analisar(escrever(tmp_path / "muitas.csv", _muitas(30)))
    assert fim["status"] == "erro"
    erro = fim["erros"][-1]
    assert erro["etapa"] == "pontuacao" and "falha simulada" in erro["causa"] and erro["acao"]
    assert fim["resultados"] == {"disponiveis": True, "parciais": True, "pontuadas": 10, "de": 30}
    assert any(e["evento"] == "analise_fim" and e["nivel"] == "erro" for e in amb.registro.listar("sistema"))


def test_erro_quando_o_modelo_nao_existe(tmp_path):
    def sem_modelo():
        raise FileNotFoundError("modelo_unificado.joblib")

    amb = Ambiente(tmp_path, None)
    amb.analises.obter_modelo = sem_modelo
    fim = amb.analisar(escrever(tmp_path / "muitas.csv", _muitas(6)))
    assert fim["status"] == "erro" and fim["resultados"]["disponiveis"] is False
    # a orientação aponta o instalador do modelo distribuído (e, como alternativa, o treino pela CLI)
    acao = fim["erros"][-1]["acao"]
    assert "FileNotFoundError" in fim["erros"][-1]["causa"] and "src.ml.provisionamento" in acao and "treinar" in acao


def test_erro_de_modelo_mostra_a_acao_do_instalador(tmp_path):
    from src.ml.provisionamento import ErroModelo

    def corrompido():
        raise ErroModelo("modelos/modelo_unificado.joblib não confere com o SHA-256 do manifesto.",
                         "Rode python -m src.ml.provisionamento (com internet) para baixar o modelo.")

    amb = Ambiente(tmp_path, None)
    amb.analises.obter_modelo = corrompido
    fim = amb.analisar(escrever(tmp_path / "muitas.csv", _muitas(6)))
    assert fim["status"] == "erro" and "SHA-256" in fim["erros"][-1]["causa"]
    assert fim["erros"][-1]["acao"].startswith("Rode python -m src.ml.provisionamento")


def test_uma_analise_por_vez(tmp_path, fabrica_modelo):
    portao = Portao()
    amb = Ambiente(tmp_path, fabrica_modelo(portao.em(1)), bloco=5)
    reg = amb.enviar(escrever(tmp_path / "muitas.csv", _muitas(12)))
    m = amb.analises.iniciar(reg["id"])
    assert portao.chegou.wait(30)
    with pytest.raises(pl.ErroAnaliseOcupada):
        amb.analises.iniciar(reg["id"])
    portao.liberar.set()
    assert amb.analises.esperar(m["id"], 60)["status"] == "concluida"


def test_reabrir_analise_do_historico_sem_reprocessar(ambiente, cenario, fabrica_modelo):
    m = ambiente.analisar(cenario["dados"], cenario["padroes"])
    db = ambiente.analises.caminho_db(m["id"])
    antes = (db.stat().st_mtime_ns, db.stat().st_size)

    def proibido():
        raise AssertionError("reabrir uma análise não pode carregar o modelo")

    outro = pl.GerenciadorAnalises(ambiente.raiz, ambiente.datasets, proibido, ambiente.registro)  # "servidor reiniciado"
    lista = outro.listar()
    assert [(a["id"], a["status"], a["registros"], a["alertas"]) for a in lista] == [(m["id"], "concluida", 13, 5)]
    assert lista[0]["dataset"]["nome"] == "cenario.csv" and lista[0]["criada_em"] == m["criada_em"]
    con = outro.conexao(m["id"])
    try:
        v = arm.visao_geral(con, arm.Filtros(), 13, True, True)
        assert v["registros"]["recorte"] == 13 and v["alertas"]["n"] == 5
    finally:
        con.close()
    assert (db.stat().st_mtime_ns, db.stat().st_size) == antes  # nada foi regravado
    assert outro.em_andamento() is None


def test_analise_interrompida_por_reinicio_vira_parcial(ambiente, cenario):
    m = ambiente.analisar(cenario["dados"])
    pasta = ambiente.raiz / pl.PASTA
    # simula a queda: manifesto "em andamento" e banco com 4 linhas gravadas, sem índices
    interrompida = dict(ler_json(pasta / m["id"] / "manifesto.json"), id="an-interrompida", status="em_andamento")
    interrompida["etapas"][3]["status"] = "em_andamento"
    (pasta / "an-interrompida").mkdir()
    con = arm.conectar(ambiente.analises.caminho_db(m["id"]))
    linhas = pd.read_sql_query("SELECT * FROM transacoes WHERE id_exibicao <= 4", con)
    con.close()
    g = arm.Gravador(pasta / "an-interrompida" / "resultados.sqlite")
    g.inserir(linhas)
    g.fechar()                                   # sem finalizar: é o estado deixado por uma queda
    gravar_json_atomico(pasta / "an-interrompida" / "manifesto.json", interrompida)
    sem_nada = dict(interrompida, id="an-sem-nada")
    gravar_json_atomico(pasta / "an-sem-nada" / "manifesto.json", sem_nada)

    novo = pl.GerenciadorAnalises(ambiente.raiz, ambiente.datasets, lambda: None, ambiente.registro)
    parcial = novo.obter("an-interrompida")
    assert parcial["status"] == "parcial" and parcial["resultados"] == {"disponiveis": True, "parciais": True,
                                                                        "pontuadas": 4, "de": 13}
    assert "reiniciado" in parcial["motivo"] and parcial["etapas"][3]["status"] == "interrompida"
    con = novo.conexao("an-interrompida")
    try:
        assert arm.pagina(con, arm.Filtros(), 1, 10)["total"] == 4
        assert con.execute("SELECT valor FROM meta WHERE chave = 'finalizado'").fetchone()[0] == "1"
    finally:
        con.close()
    erro = novo.obter("an-sem-nada")
    assert erro["status"] == "erro" and erro["resultados"]["disponiveis"] is False and erro["erros"][-1]["acao"]
    assert ler_json(pasta / "an-interrompida" / "manifesto.json")["status"] == "parcial"  # ficou gravado


def test_retencao_das_analises(tmp_path, fabrica_modelo, cenario):
    amb = Ambiente(tmp_path, fabrica_modelo(), max_analises=2)
    reg = amb.enviar(cenario["dados"])
    ids = []
    for _ in range(3):
        m = amb.analises.iniciar(reg["id"])
        ids.append(amb.analises.esperar(m["id"], 60)["id"])
    assert [a["id"] for a in amb.analises.listar()] == [ids[2], ids[1]]
    assert not (amb.raiz / pl.PASTA / ids[0]).exists() and (amb.raiz / pl.PASTA / ids[2]).exists()
    assert any(e["evento"] == "retencao" for e in amb.registro.listar("sistema"))


def test_escrita_atomica_do_manifesto_com_leitura_concorrente(tmp_path):
    alvo = tmp_path / "manifesto.json"
    gravar_json_atomico(alvo, {"n": 0, "texto": "x" * 50_000})
    parar = threading.Event()
    falhas = []

    def leitor():
        while not parar.is_set():
            try:
                dados = json.loads(alvo.read_text(encoding="utf-8"))
                assert len(dados["texto"]) == 50_000
            except PermissionError:
                continue      # no Windows, a troca do arquivo pode negar uma leitura por um instante
            except Exception as exc:  # JSON pela metade seria um ValueError aqui
                falhas.append(exc)

    t = threading.Thread(target=leitor)
    t.start()
    try:
        for i in range(1, 150):
            gravar_json_atomico(alvo, {"n": i, "texto": "x" * 50_000})
    finally:
        parar.set()
        t.join()
    assert falhas == [] and ler_json(alvo)["n"] == 149
    assert [p.name for p in tmp_path.iterdir()] == ["manifesto.json"]
