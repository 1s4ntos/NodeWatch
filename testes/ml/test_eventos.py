"""Contrato de eventos, serviço (fila + trabalhador), replay, reinício e vínculos.

Usa o ``modelo_minimo`` do conftest (treinado em dados SINTÉTICOS).
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.ml import eventos as ev
from src.ml.esquemas import FEATURES_REDE
from src.ml.preparacao import atributos_financeiros
from src.ml.previsao import pontuar_lavagem, tabela_previsoes_rede
from src.ml.replay import ReplayHistorico
from src.ml.servico_eventos import Configuracao, ServicoEventos
from testes.ml.conftest import gerar_rede, gerar_transacoes, gravar_hismall, nomes_contas

T0 = 1_790_000_000.0


def _tx_bruta(ident: str = "t1", ts="2022/09/10 05:31", **extra) -> dict:
    dados = {"id_transacao": ident, "timestamp": ts, "banco_origem": 12, "conta_origem": "8010D4440",
             "banco_destino": "137218", "conta_destino": "80EB2C3F0", "valor_pago": 1380.75,
             "moeda_pagamento": "Swiss Franc", "valor_recebido": 1380.75, "moeda_recebimento": "Swiss Franc",
             "formato": "ACH", **extra}
    return {"tipo": "transacao", "versao_esquema": "transacao_hismall_v1", "dados": dados}


def _medicoes(n_fluxos: int = 3) -> pd.DataFrame:
    rede = gerar_rede(n_fluxos=n_fluxos, por_split=(60, 0, 0))
    return rede.drop(columns=["split", "alvo"])


def _ev_rede(linha: dict, modo: str = "novo_evento") -> dict:
    return {"tipo": "medicao_rede", "modo": modo, "dados": linha}


# ---------------------------------------------------------------------------
# contrato
# ---------------------------------------------------------------------------
def test_transacao_valida_tem_identidade_estavel_e_conta_banco_conta() -> None:
    e = ev.montar_evento(_tx_bruta(), recebido_em=T0)
    assert e.id_evento == e.chave_natural == "tx:t1"
    assert e.dados["conta_origem"] == "12-8010D4440" and e.dados["minuto"] == int(e.ocorrido_em // 60)
    assert e.modo == "novo_evento" and e.recebido_em == T0
    iso = ev.montar_evento(_tx_bruta(ts="2022-09-10T05:31:00Z"), T0)
    assert iso.ocorrido_em == e.ocorrido_em


@pytest.mark.parametrize("bruto, trecho", [
    ({"tipo": "pagamento", "dados": {}}, "tipo inválido"),
    (dict(_tx_bruta(), versao_esquema="transacao_v9"), "não suportada"),
    (dict(_tx_bruta(), modo="ao_vivo"), "modo inválido"),
    ({"tipo": "transacao", "dados": {"id_transacao": "x"}}, "campo obrigatório ausente"),
    (_tx_bruta(valor_pago=-1), "valor_pago"),
    (_tx_bruta(timestamp_disponivel="2022/09/10 05:00"), "anterior"),
])
def test_eventos_invalidos_sao_recusados_com_motivo(bruto, trecho) -> None:
    with pytest.raises(ev.ErroEvento) as exc:
        ev.montar_evento(bruto, T0)
    assert any(trecho in p for p in exc.value.problemas)


def test_telemetria_bruta_nao_vira_rede_v1() -> None:
    with pytest.raises(ev.ErroEvento, match="p95/p99"):
        ev.montar_evento({"tipo": "medicao_rede", "dados": {"id_fluxo": "1_2", "timestamp": 1, "rtt_ms": 40}}, T0)


def test_lote_rede_isola_linhas_invalidas() -> None:
    df = _medicoes(1).head(5).copy()
    df.loc[2, "perda_pct"] = 150.0
    boas, ruins = ev.validar_lote_rede(df)
    assert len(boas) == 4 and [i for i, _ in ruins] == [2]


@pytest.mark.parametrize("dados, trecho", [
    ({"chave": "12-8010D4440A", "tipo_chave": "chave_tecnica", "id_fluxo": "1_2"}, "conta bancária"),
    ({"chave": "s1", "tipo_chave": "conta", "id_fluxo": "1_2"}, "fora do domínio"),
    ({"chave": "s1", "tipo_chave": "chave_tecnica", "id_fluxo": "ancora7"}, "formato"),
    ({"chave": "s1", "tipo_chave": "chave_tecnica", "id_fluxo": "1_2", "valido_ate": T0 - 10}, "anterior"),
])
def test_regras_de_vinculo(dados, trecho) -> None:
    base = {"valido_de": T0, "valido_ate": T0 + 60, "fonte_vinculo": "teste"}
    with pytest.raises(ev.ErroEvento) as exc:
        ev.montar_evento({"tipo": "vinculo", "dados": {**base, **dados}}, T0)
    assert any(trecho in p for p in exc.value.problemas)


# ---------------------------------------------------------------------------
# serviço
# ---------------------------------------------------------------------------
def _servico(modelo, tmp_path: Path, **cfg) -> ServicoEventos:
    return ServicoEventos(modelo, tmp_path / "previsoes", tmp_path / "estado", Configuracao(**cfg))


def test_rede_por_eventos_igual_a_previsao_em_lote(modelo_minimo, tmp_path: Path) -> None:
    med = _medicoes()
    s = _servico(modelo_minimo, tmp_path)
    s.iniciar()
    r = s.submeter([_ev_rede(x) for x in med.to_dict("records")])
    assert r["aceitos"] == len(med) and r["recusados"] == []
    assert s.esperar_fila_vazia(30)
    dup = s.submeter([_ev_rede(med.iloc[0].to_dict())])
    assert s.esperar_fila_vazia(30)
    s.parar()
    out = pd.read_csv(tmp_path / "previsoes" / "eventos_novo_evento_rede.csv")
    assert len(out) == len(med) and dup["aceitos"] == 1 and s.rejeitados["duplicada"] == 1
    lote, _ = tabela_previsoes_rede(modelo_minimo.cabeca("estado_rede"),
                                    med.assign(arquivo_origem="x", linha_origem=range(len(med))))
    j = out.merge(lote, on=["id_fluxo", "timestamp_previsao"], suffixes=("", "_lote"))
    assert len(j) == len(med)
    assert np.allclose(j["score_alerta_rede"], j["score_alerta_rede_lote"])
    assert set(["id_evento", "recebido_em_utc", "processado_em_utc", "modo_evento"]) <= set(out.columns)


def test_financeiro_por_eventos_igual_ao_lote(modelo_minimo, tmp_path: Path) -> None:
    trans = gerar_transacoes(1_500, 60, semente=3)
    nomes = nomes_contas(60)
    caminho = gravar_hismall(trans, nomes, tmp_path / "hismall.csv")
    s = _servico(modelo_minimo, tmp_path)
    r = ReplayHistorico(s, "financeiro", caminho)
    r.iniciar()
    _esperar(r)
    s.parar()
    out = pd.read_csv(tmp_path / "previsoes" / "eventos_replay_historico_lavagem.csv")
    assert len(out) == len(trans) and out["id_transacao"].is_unique
    from src.ml.ingestao import ler_hismall
    dados = ler_hismall(caminho, exigir_rotulo=False)
    prep = modelo_minimo.codificadores["financeiro"]
    X = atributos_financeiros(dados.trans, np.arange(len(dados.trans)), prep)
    score, _ = pontuar_lavagem(modelo_minimo.cabeca("lavagem"), prep, X, dados.trans["formato"])
    esperado = pd.Series(score, index=[f"hismall.csv#{i}" for i in dados.trans["id_transacao"]])
    assert np.allclose(out.set_index("id_transacao")["score_lavagem"], esperado.loc[out["id_transacao"]], atol=1e-12)
    assert (out["cobertura_vinculo"] == "sem_vinculo").all()


def _esperar(replay: ReplayHistorico, situacoes=("concluido", "erro"), timeout: float = 60) -> None:
    fim = time.monotonic() + timeout
    while replay.situacao not in situacoes and time.monotonic() < fim:
        time.sleep(0.02)
    assert replay.situacao in situacoes, replay.status()
    assert replay.situacao != "erro", replay.mensagem


def test_fila_cheia_recusa_sem_descartar_em_silencio(modelo_minimo, tmp_path: Path) -> None:
    s = _servico(modelo_minimo, tmp_path, capacidade_fila=2)  # sem trabalhador: nada sai da fila
    med = _medicoes(1).head(3)
    r = s.submeter([_ev_rede(x) for x in med.to_dict("records")])
    assert r["aceitos"] == 2 and [x["motivo"] for x in r["recusados"]] == ["fila_cheia"]
    assert s.cont_api["recusados_fila_cheia"] == 1


def test_minuto_aberto_fecha_quando_ocioso(modelo_minimo, tmp_path: Path) -> None:
    s = _servico(modelo_minimo, tmp_path, fechar_ocioso_s=0.2)
    s.iniciar()
    s.submeter([_tx_bruta("a"), _tx_bruta("b")])
    fim = time.monotonic() + 10
    while s.cont["previsoes_lavagem"] < 2 and time.monotonic() < fim:
        time.sleep(0.05)
    s.parar(salvar=False)
    assert s.cont["previsoes_lavagem"] == 2 and not s.estado.aberto


def test_replay_pausa_reinicia_processo_e_nao_duplica(modelo_minimo, tmp_path: Path) -> None:
    trans = gerar_transacoes(2_000, 60, semente=4)
    nomes = nomes_contas(60)
    caminho = gravar_hismall(trans, nomes, tmp_path / "hismall.csv")

    # execução sem interrupção
    ref_dir = tmp_path / "ref"
    s0 = _servico(modelo_minimo, ref_dir)
    r0 = ReplayHistorico(s0, "financeiro", caminho)
    r0.iniciar()
    _esperar(r0)
    s0.parar()
    referencia = pd.read_csv(ref_dir / "previsoes" / "eventos_replay_historico_lavagem.csv")

    # pausa no meio, "queda" do processo e retomada a partir do instantâneo
    s1 = _servico(modelo_minimo, tmp_path)
    r1 = ReplayHistorico(s1, "financeiro", caminho, eventos_por_segundo=4_000)
    r1.iniciar()
    while r1.enviados < 700:
        time.sleep(0.01)
    r1.pausar()
    _esperar(r1, ("pausado",))  # pausar grava o instantâneo
    no_instantaneo = s1.replay_processado[r1.chave] + 1
    r1.eventos_por_segundo = 1_000  # devagar o bastante para "cair" antes do fim (~1,3 s)
    r1.iniciar()  # segue processando e escrevendo...
    while s1.replay_processado.get(r1.chave, 0) < no_instantaneo + 150:
        time.sleep(0.01)
    r1.parar()
    s1.parar(salvar=False)  # ...e o processo "cai" sem gravar de novo
    escritas = len(pd.read_csv(tmp_path / "previsoes" / "eventos_replay_historico_lavagem.csv"))
    assert escritas > no_instantaneo
    # as linhas escritas depois do instantâneo são descartadas e refeitas
    s2 = _servico(modelo_minimo, tmp_path)
    assert s2.replay_processado[r1.chave] + 1 == no_instantaneo
    assert s2.restaurado and s2.restaurado["restaurado"]
    r2 = ReplayHistorico(s2, "financeiro", caminho)
    assert 0 < r2.processados() < len(trans)
    r2.iniciar()
    _esperar(r2)
    s2.parar()
    retomado = pd.read_csv(tmp_path / "previsoes" / "eventos_replay_historico_lavagem.csv")
    assert len(retomado) == len(trans) and retomado["id_transacao"].is_unique
    a = referencia.set_index("id_transacao")["score_lavagem"]
    b = retomado.set_index("id_transacao")["score_lavagem"]
    assert np.allclose(a.sort_index(), b.sort_index())


def test_replays_simultaneos_nao_fecham_minutos_um_do_outro(modelo_minimo, tmp_path: Path) -> None:
    """O fim do replay de rede não pode fechar o minuto que o replay financeiro ainda envia."""
    trans = gerar_transacoes(3_000, 60, semente=6)
    trans["minuto"] = np.sort(np.random.default_rng(6).integers(0, 60, len(trans))) + 27_000_000  # ~50 por minuto
    hismall = gravar_hismall(trans, nomes_contas(60), tmp_path / "hismall.csv")
    rede_csv = tmp_path / "rede.csv"
    medicoes = _medicoes(2)
    medicoes.to_csv(rede_csv, index=False)
    s = _servico(modelo_minimo, tmp_path)
    fin = ReplayHistorico(s, "financeiro", hismall, eventos_por_segundo=3_000)
    rede = ReplayHistorico(s, "rede", rede_csv)
    fin.iniciar()
    while fin.enviados < 300:
        time.sleep(0.01)
    rede.iniciar()  # termina bem antes do financeiro
    _esperar(rede)
    _esperar(fin)
    s.parar(salvar=False)
    assert s.rejeitados.get("atrasada", 0) == 0
    assert s.cont["previsoes_lavagem"] == len(trans) and s.cont["previsoes_rede"] == len(medicoes)


def test_rede_e_vinculos_so_valem_no_instante_da_decisao(modelo_minimo, tmp_path: Path) -> None:
    med = _medicoes(1)
    fluxo = med["id_fluxo"].iloc[0]
    ts = med["timestamp"].to_numpy(dtype=float)
    s = _servico(modelo_minimo, tmp_path)
    s.processar([ev.montar_evento(_ev_rede(x), T0) for x in med.to_dict("records")], da_fila=False)

    def vinc(chave, de, ate, declarado):
        return {"tipo": "vinculo", "dados": {"chave": chave, "tipo_chave": "id_transacao", "id_fluxo": fluxo,
                                             "valido_de": de, "valido_ate": ate, "fonte_vinculo": "teste",
                                             "declarado_em": declarado}}

    casos = {
        "ok": (ts[10] + 30, vinc("ok", ts[0], ts[-1], ts[0])),
        "vencido": (ts[20] + 30, vinc("vencido", ts[0], ts[20], ts[0])),
        "declarado_depois": (ts[30] + 30, vinc("declarado_depois", ts[0], ts[-1], ts[30] + 60)),
        "futuro": (ts[40] - 5, vinc("futuro", ts[0], ts[-1], ts[0])),
    }
    lote = []
    for ident, (t, v) in casos.items():
        lote.append(ev.montar_evento(v, t))
        lote.append(ev.montar_evento(_tx_bruta(ident, ts=t), t))
    s.processar(sorted(lote, key=lambda e: e.ocorrido_em), da_fila=False)
    s.processar([ev.Evento("c", "c", "controle", "-", 0, 0, "t", "novo_evento", {"acao": "fechar"})], da_fila=False)
    out = pd.read_csv(tmp_path / "previsoes" / "eventos_novo_evento_lavagem.csv").set_index("id_transacao")
    assert out.loc["ok", "cobertura_vinculo"] == "com_sinal"
    assert out.loc["ok", "idade_sinal_rede_s"] == pytest.approx(30.0)
    assert out.loc["vencido", "cobertura_vinculo"] == "sem_vinculo"
    assert out.loc["declarado_depois", "cobertura_vinculo"] == "sem_vinculo"
    # 5 s antes de uma medição: usa a anterior (nunca a futura)
    assert out.loc["futuro", "idade_sinal_rede_s"] == pytest.approx(ts[40] - 5 - ts[39])
    assert (out["sinais_utilizados"] == "financeiro").all()  # a fusão continua indisponível


def test_laboratorio_de_simulacao_confere_todos_os_casos(modelo_minimo, tmp_path: Path) -> None:
    from src.ml.simulacao import executar_laboratorio
    exemplos = tmp_path / "artefatos_ml" / "exemplos"
    exemplos.mkdir(parents=True)
    gerar_rede(n_fluxos=4).drop(columns=["split", "alvo"]).to_csv(exemplos / "rede_teste_sem_rotulos.csv", index=False)
    rel = executar_laboratorio(modelo_minimo, tmp_path)
    assert rel["todos_ok"], [c for c in rel["casos"] + rel["rejeicoes"] if not c["ok"]]
    assert "SIMULAÇÃO" in rel["aviso"]
    assert rel["conclusao"]["validacao_preditiva"].startswith("pendente")
    assert (tmp_path / "artefatos_ml" / "simulacao" / "laboratorio.json").is_file()
    assert not (tmp_path / "artefatos_ml" / "previsoes").exists()  # não se mistura às previsões reais


def test_descartar_apaga_so_as_saidas_de_eventos(modelo_minimo, tmp_path: Path) -> None:
    (tmp_path / "previsoes").mkdir()
    alheio = tmp_path / "previsoes" / "minhas_previsoes.csv"
    alheio.write_text("x\n1\n", encoding="utf-8")
    s = _servico(modelo_minimo, tmp_path)
    s.processar([ev.montar_evento(_ev_rede(_medicoes(1).iloc[0].to_dict()), T0)], da_fila=False)
    s.salvar_estado()
    r = s.descartar()
    assert "eventos_novo_evento_rede.csv" in r["removidos"] and alheio.is_file()
    assert s.estado.transacoes_incorporadas == 0 and s.cont["previsoes_rede"] == 0
