"""Análise de datasets novos (src/ml/analises.py): aceite, isolamento, sessão e interrupções.

Dados SINTÉTICOS (``gerar_transacoes``/``gerar_rede``) e ``modelo_minimo``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.ml import analises as an
from src.ml.ingestao import ler_hismall
from src.ml.preparacao import atributos_financeiros
from src.ml.previsao import pontuar_lavagem
from src.ml.sessoes import GerenciadorSessoes
from testes.ml.conftest import gerar_rede, gerar_transacoes, gravar_hismall, nomes_contas


class Relogio:
    t = 2_000_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def ambiente(tmp_path, modelo_minimo):
    rel = Relogio()
    sessoes = GerenciadorSessoes(relogio=rel)
    am = an.GerenciadorAnalises(tmp_path, lambda: modelo_minimo, sessoes.ativa)
    return am, sessoes, rel, tmp_path


def _hismall(pasta: Path, nome: str, semente: int, n: int = 3_000, contas: int = 60, deslocar_dias: int = 0,
             com_rotulo: bool = False) -> Path:
    t = gerar_transacoes(n, contas, semente)
    t["minuto"] += deslocar_dias * 1440
    caminho = gravar_hismall(t, nomes_contas(contas), pasta / nome)
    if com_rotulo:
        df = pd.read_csv(caminho, dtype=str)
        linhas = [l for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]
        linhas[0] += ",Is Laundering"
        linhas[1:] = [l + f",{r}" for l, r in zip(linhas[1:], t["rotulo"])]
        caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        assert len(df) == n
    return caminho


def _pt(pasta: Path, nome: str, semente: int, n: int = 2_500) -> Path:
    """Mesmo conteúdo em transacao_hismall_v1 (nomes em português, ISO 8601), contas próprias."""
    t = gerar_transacoes(n, 50, semente)
    t["minuto"] += 30 * 1440  # outro período
    df = pd.DataFrame({
        "id_transacao": [f"pt-{i}" for i in range(n)],
        "timestamp": pd.to_datetime(t["minuto"], unit="m", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "banco_origem": t["banco_origem"] + 900, "conta_origem": [f"P{c:05d}" for c in t["conta_origem"]],
        "banco_destino": t["banco_destino"] + 900, "conta_destino": [f"P{c:05d}" for c in t["conta_destino"]],
        "valor_pago": t["valor_pago"].round(2), "moeda_pagamento": t["moeda_pagamento"].astype(str),
        "valor_recebido": t["valor_recebido"].round(2), "moeda_recebimento": t["moeda_recebimento"].astype(str),
        "formato": t["formato"].astype(str),
    })
    caminho = pasta / nome
    df.to_csv(caminho, index=False)
    return caminho


def _analisar(am, sessoes, caminho: Path, historico: Path = None):
    s = sessoes.abrir()
    meta = am.criar(caminho.read_bytes(), caminho.name,
                    historico.read_bytes() if historico else None, historico.name if historico else None)
    assert meta["situacao"] == "pronta", meta
    am.iniciar(meta["id"], s.id)
    return am.esperar(meta["id"]), s


def _esperado(modelo, caminho: Path, historico: Path = None) -> pd.Series:
    """Referência em lote (caminho da CLI): atributos_financeiros + pontuar_lavagem."""
    from src.ml.previsao import _concatenar
    cab, prep = modelo.cabeca("lavagem"), modelo.codificadores["financeiro"]
    dados = ler_hismall(caminho, exigir_rotulo=False)
    if historico:
        h = ler_hismall(historico, exigir_rotulo=False)
        h.trans = h.trans[h.trans["minuto"] < dados.trans["minuto"].min()].reset_index(drop=True)
        trans, consulta, _ = _concatenar(h, dados)
    else:
        trans, consulta = dados.trans, np.arange(len(dados.trans))
    X = atributos_financeiros(trans, consulta, prep)
    s, _ = pontuar_lavagem(cab, prep, X, trans["formato"].iloc[consulta])
    return pd.Series(s, index=dados.trans["id_transacao"].to_numpy())


def _saida(am, meta) -> pd.DataFrame:
    return pd.read_csv(am._saida(meta))


# ---------------------------------------------------------------------------
def test_dois_datasets_diferentes_sem_contaminacao(ambiente, modelo_minimo):
    am, sessoes, _, pasta = ambiente
    a = _hismall(pasta, "banco_a_setembro.csv", semente=11)
    b = _hismall(pasta, "outro_nome.csv", semente=12, contas=70, deslocar_dias=40)
    ma, _ = _analisar(am, sessoes, a)
    mb, _ = _analisar(am, sessoes, b)
    for meta, arq in ((ma, a), (mb, b)):
        assert meta["situacao"] == "concluida" and meta["progresso"]["processadas"] == 3_000
        out = _saida(am, meta).set_index("linha_origem").sort_index()
        esperado = _esperado(modelo_minimo, arq)
        assert np.allclose(out["score_lavagem"].to_numpy(), esperado.loc[out.index].to_numpy())
    assert ma["dataset"]["sha256"] != mb["dataset"]["sha256"] and ma["id"] != mb["id"]
    assert ma["modelo_usado"]["versao"] == "teste-lavagem"


def test_formato_em_portugues_e_aceito_com_identidade_propria(ambiente):
    am, sessoes, _, pasta = ambiente
    meta, _ = _analisar(am, sessoes, _pt(pasta, "transacoes_pt.csv", semente=13))
    assert meta["deteccao"]["formato"] == "transacao_hismall_v1" and meta["situacao"] == "concluida"
    out = _saida(am, meta)
    assert len(out) == 2_500 and out["id_transacao"].str.startswith("pt-").all() and out["id_transacao"].is_unique


def test_sem_rotulos_metricas_indisponiveis_com_rotulos_avaliacao_separada(ambiente):
    am, sessoes, _, pasta = ambiente
    sem, _ = _analisar(am, sessoes, _hismall(pasta, "sem.csv", semente=14))
    com, _ = _analisar(am, sessoes, _hismall(pasta, "com.csv", semente=14, com_rotulo=True))
    assert not sem["avaliacao"]["disponivel"] and "indisponíveis" in sem["avaliacao"]["motivo"]
    assert com["avaliacao"]["disponivel"] and com["avaliacao"]["positivos"] > 0
    # o rótulo não entra nos preditores: mesmos scores com e sem a coluna
    assert np.allclose(_saida(am, sem)["score_lavagem"], _saida(am, com)["score_lavagem"])
    assert "Is Laundering" in _saida(am, com) and "Is Laundering" not in _saida(am, sem)


def test_csv_de_previsoes_e_grafo_nao_viram_analise(ambiente):
    am, _, _, pasta = ambiente
    prev = pasta / "previsoes.csv"
    prev.write_text("arquivo_origem,linha_origem,id_fluxo,timestamp_previsao,classe_prevista,prob_OK,prob_RISCO,"
                    "prob_FALHA,score_alerta_rede,alerta_rede\nx,0,1_2,1,OK,1,0,0,0,False\n", encoding="utf-8")
    m = am.criar(prev.read_bytes(), prev.name)
    assert m["situacao"] == "invalida" and m["deteccao"]["formato"] == "previsao_rede_v1"
    assert "Explorar previsões" in m["deteccao"]["leitura"]
    grafo = pasta / "grafo.csv"
    grafo.write_text("step,type,amount,nameOrig,nameDest,isFraud\n1,TRANSFER,10,C1,C2,0\n", encoding="utf-8")
    g = am.criar(grafo.read_bytes(), grafo.name)
    assert g["situacao"] == "invalida" and "grafos" in g["deteccao"]["possiveis"][0]
    assert "moeda_pagamento" in g["deteccao"]["faltando"]["transacao_hismall_v1"]


def test_arquivo_incompleto_ou_com_linhas_ruins_informa_o_que_falta(ambiente):
    am, sessoes, _, pasta = ambiente
    sem_coluna = pasta / "sem_coluna.csv"
    df = pd.read_csv(_pt(pasta, "base.csv", semente=15, n=50), dtype=str)
    df.drop(columns=["moeda_recebimento"]).to_csv(sem_coluna, index=False)
    m = am.criar(sem_coluna.read_bytes(), sem_coluna.name)
    assert m["situacao"] == "invalida" and m["deteccao"]["faltando"]["transacao_hismall_v1"] == ["moeda_recebimento"]
    ruins = pasta / "ruins.csv"
    df.loc[3, "valor_pago"] = "-5"
    df.loc[7, "timestamp"] = "ontem"
    df.loc[9, "id_transacao"] = df.loc[8, "id_transacao"]
    df.to_csv(ruins, index=False)
    meta, _ = _analisar(am, sessoes, ruins)
    p = meta["progresso"]
    assert p["lidas"] == 50 and p["recusadas"] == 3 and p["validas"] == 47 and p["processadas"] == 47
    assert set(meta["recusas"]) == {"valor pago ausente, negativo ou não numérico", "data/hora inválida",
                                    "id_transacao repetido"}
    assert len(_saida(am, meta)) == 47  # nada foi preenchido


def test_mais_linhas_que_o_bloco_preserva_o_historico(ambiente, modelo_minimo, monkeypatch):
    am, sessoes, _, pasta = ambiente
    monkeypatch.setattr(an, "BLOCO_FINANCEIRO", 97)
    arq = _hismall(pasta, "grande.csv", semente=16)
    meta, _ = _analisar(am, sessoes, arq)
    out = _saida(am, meta).set_index("linha_origem").sort_index()
    assert meta["progresso"]["processadas"] == 3_000 and len(out) == 3_000
    assert np.allclose(out["score_lavagem"], _esperado(modelo_minimo, arq).loc[out.index])


def test_historico_explicito_tem_cobertura_e_equivale_ao_lote(ambiente, modelo_minimo):
    am, sessoes, _, pasta = ambiente
    t = gerar_transacoes(3_000, 60, 17)
    corte = int(t["minuto"].iloc[2_000])
    hist = gravar_hismall(t[t["minuto"] < corte].reset_index(drop=True), nomes_contas(60), pasta / "hist.csv")
    dia = gravar_hismall(t[t["minuto"] >= corte].reset_index(drop=True), nomes_contas(60), pasta / "dia.csv")
    meta, _ = _analisar(am, sessoes, dia, hist)
    cob = meta["historico"]["cobertura"]
    assert cob["transacoes"] == int((t["minuto"] < corte).sum()) and meta["historico"]["ignoradas_no_periodo"] == 0
    out = _saida(am, meta).set_index("linha_origem").sort_index()
    assert np.allclose(out["score_lavagem"], _esperado(modelo_minimo, dia, hist).loc[out.index])


def _interromper_no(am, n: int, acao):
    original = am._ponto_seguro
    chamadas = {"n": 0}

    def ponto(aid):
        chamadas["n"] += 1
        if chamadas["n"] == n:
            acao(aid)
        return original(aid)

    am._ponto_seguro = ponto


def test_pausa_parcial_e_retomada_explicita(ambiente, modelo_minimo, monkeypatch):
    am, sessoes, _, pasta = ambiente
    monkeypatch.setattr(an, "BLOCO_FINANCEIRO", 200)
    arq = _hismall(pasta, "pausa.csv", semente=18)
    s = sessoes.abrir()
    meta = am.criar(arq.read_bytes(), arq.name)
    _interromper_no(am, 4, lambda aid: am.pedir(aid, "pausar", s.id))
    am.iniciar(meta["id"], s.id)
    meta = am.esperar(meta["id"])
    assert meta["situacao"] == "pausada" and 0 < meta["progresso"]["processadas"] < 3_000
    rel = am._saida(meta).with_suffix(".relatorio.json").read_text(encoding="utf-8")
    assert '"situacao": "pausada"' in rel  # a exploração mostra como parcial
    from src.ml.exploracao import RepositorioFontes
    fonte = [f for f in RepositorioFontes(pasta).listar() if f["nome_arquivo"] == am._saida(meta).name][0]
    assert fonte["conjunto"]["tipo"] == "parcial"
    am._ponto_seguro = an.GerenciadorAnalises._ponto_seguro.__get__(am)
    am.iniciar(meta["id"], s.id)  # retomada explícita
    meta = am.esperar(meta["id"])
    out = _saida(am, meta)
    assert meta["situacao"] == "concluida" and len(out) == 3_000 and out["linha_origem"].is_unique
    out = out.set_index("linha_origem").sort_index()
    assert np.allclose(out["score_lavagem"], _esperado(modelo_minimo, arq).loc[out.index])


def test_cancelamento_mantem_parcial_identificado(ambiente, monkeypatch):
    am, sessoes, _, pasta = ambiente
    monkeypatch.setattr(an, "BLOCO_FINANCEIRO", 200)
    arq = _hismall(pasta, "cancela.csv", semente=19)
    s = sessoes.abrir()
    meta = am.criar(arq.read_bytes(), arq.name)
    _interromper_no(am, 3, lambda aid: am.pedir(aid, "cancelar", s.id))
    am.iniciar(meta["id"], s.id)
    meta = am.esperar(meta["id"])
    assert meta["situacao"] == "cancelada" and len(_saida(am, meta)) == meta["progresso"]["processadas"] < 3_000
    with pytest.raises(an.ErroAnalise):
        am.iniciar(meta["id"], s.id)


def test_expiracao_da_sessao_pausa_e_reinicio_nao_retoma_sozinho(ambiente, modelo_minimo, monkeypatch):
    am, sessoes, relogio, pasta = ambiente
    monkeypatch.setattr(an, "BLOCO_FINANCEIRO", 200)
    arq = _hismall(pasta, "expira.csv", semente=20)
    s = sessoes.abrir()
    meta = am.criar(arq.read_bytes(), arq.name)

    def expirar(_aid):
        relogio.t += sessoes.ttl_s + 1  # a aba sumiu: nenhum pulso dentro do prazo

    _interromper_no(am, 3, expirar)
    am.iniciar(meta["id"], s.id)
    meta = am.esperar(meta["id"])
    assert meta["situacao"] == "pausada" and "sessão" in meta["motivo"]
    with pytest.raises(PermissionError):
        am.iniciar(meta["id"], s.id)  # a sessão expirada não volta
    # reinício do servidor: nada é retomado sozinho
    am2 = an.GerenciadorAnalises(pasta, lambda: modelo_minimo, sessoes.ativa)
    assert am2.obter(meta["id"])["situacao"] == "pausada"
    nova = sessoes.abrir()  # outra aba (ou a reaberta) retoma explicitamente e assume
    am2.iniciar(meta["id"], nova.id)
    meta = am2.esperar(meta["id"])
    assert meta["situacao"] == "concluida" and len(_saida(am2, meta)) == 3_000


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_queda_no_meio_vira_interrompida_e_retoma_do_checkpoint(ambiente, modelo_minimo, monkeypatch):
    am, sessoes, _, pasta = ambiente
    monkeypatch.setattr(an, "BLOCO_FINANCEIRO", 200)
    monkeypatch.setattr(an, "CHECKPOINT_S", 0.0)  # checkpoint a cada bloco
    arq = _hismall(pasta, "queda.csv", semente=21)
    s = sessoes.abrir()
    meta = am.criar(arq.read_bytes(), arq.name)

    class Queda(BaseException):
        pass

    def cair(_aid):
        raise Queda()  # o processo morre: nada além do checkpoint chega ao disco

    _interromper_no(am, 6, cair)
    am.iniciar(meta["id"], s.id)
    am._threads[meta["id"]].join(30)
    am2 = an.GerenciadorAnalises(pasta, lambda: modelo_minimo, sessoes.ativa)  # servidor reiniciado
    m2 = am2.obter(meta["id"])
    assert m2["situacao"] == "interrompida" and m2["checkpoint"]["cursor"] > 0
    am2.iniciar(meta["id"], s.id)
    m2 = am2.esperar(meta["id"])
    out = _saida(am2, m2)
    assert m2["situacao"] == "concluida" and len(out) == 3_000 and out["linha_origem"].is_unique
    out = out.set_index("linha_origem").sort_index()
    assert np.allclose(out["score_lavagem"], _esperado(modelo_minimo, arq).loc[out.index])


def test_dataset_de_rede_com_alvo_e_deriva(ambiente):
    am, sessoes, _, pasta = ambiente
    arq = pasta / "medicoes.csv"
    gerar_rede(n_fluxos=3).drop(columns=["split"]).to_csv(arq, index=False)
    meta, _ = _analisar(am, sessoes, arq)
    assert meta["deteccao"]["formato"] == "rede_v1" and meta["situacao"] == "concluida"
    assert meta["avaliacao"]["disponivel"] and "macro_f1" in meta["avaliacao"]
    assert "psi" in meta["dominio_indicadores"] and len(_saida(am, meta)) == 3 * 260
