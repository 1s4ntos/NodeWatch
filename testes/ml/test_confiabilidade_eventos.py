"""Reproduções dos problemas de confiabilidade do processamento de eventos.

Cada teste descreve um cenário que falhava na versão 9095451 (ver
docs/ml/REVISAO_CONFIABILIDADE_EVENTOS.md, com a saída da execução antiga) e
só usa a interface pública do serviço: eventos montados por
``montar_evento``, ``submeter``/``processar``, ``_ocioso``, ``salvar_estado``
e um serviço novo sobre a mesma pasta para simular o reinício.

A comprovação de gravação é sempre o CSV de saída em disco, nunca contadores
ou a lista de recentes. Dados SINTÉTICOS (``modelo_minimo``).
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import pytest

from src.ml import eventos as ev
from src.ml import servico_eventos as se
from src.ml.servico_eventos import Configuracao, ServicoEventos


def _iso(texto: str) -> float:
    return ev.epoca(texto, "t")


def _tx(ident: str, quando: str, conta: str = "A1") -> dict:
    return {"tipo": "transacao", "modo": "novo_evento", "dados": {
        "id_transacao": ident, "timestamp": quando, "banco_origem": 1, "conta_origem": conta,
        "banco_destino": 2, "conta_destino": "B2", "valor_pago": 100.0, "moeda_pagamento": "US Dollar",
        "valor_recebido": 100.0, "moeda_recebimento": "US Dollar", "formato": "ACH"}}


def _servico(modelo, pasta: Path) -> ServicoEventos:
    return ServicoEventos(modelo, pasta / "previsoes", pasta / "estado", Configuracao(fechar_ocioso_s=5.0))


def _reabrir(modelo, pasta: Path) -> ServicoEventos:
    """Serviço novo sobre a mesma pasta (reinício do processo), recuperado explicitamente."""
    s = _servico(modelo, pasta)
    recuperar = getattr(s, "recuperar", None)  # não existia na versão antiga (restaurava no construtor)
    if recuperar:
        recuperar()
    return s


def _lavagem(pasta: Path) -> pd.DataFrame:
    caminho = pasta / "previsoes" / "eventos_novo_evento_lavagem.csv"
    return pd.read_csv(caminho) if caminho.is_file() else pd.DataFrame(columns=["id_transacao"])


def _evento(bruto: dict, recebido: float) -> ev.Evento:
    return ev.montar_evento(bruto, recebido)


def _parar_sem_salvar(s: ServicoEventos) -> None:
    """Queda do processo: o trabalhador para e nada mais é gravado."""
    s._parar.set()
    if s._trabalhador:
        s._trabalhador.join(10)


# ---------------------------------------------------------------------------
# 1. Previsão fechada por ociosidade precisa ser gravada
# ---------------------------------------------------------------------------
def test_fechamento_por_ociosidade_grava_a_previsao_e_sobrevive_ao_reinicio(modelo_minimo, tmp_path):
    s = _servico(modelo_minimo, tmp_path)
    s.processar([_evento(_tx("t1", "2026-11-03T12:00:05Z"), _iso("2026-11-03T12:00:05Z"))], da_fila=False)
    # nenhum outro lote chega; o relógio passa do fim do minuto (e da pausa de 5 s)
    s._ultimo_evento = time.monotonic() - 60
    s.relogio = lambda: _iso("2026-11-03T12:02:00Z")
    s._ocioso()
    gravado = _lavagem(tmp_path)
    assert list(gravado["id_transacao"]) == ["t1"], "a previsão fechada por ociosidade não foi gravada"
    s.salvar_estado()
    s2 = _reabrir(modelo_minimo, tmp_path)
    assert list(_lavagem(tmp_path)["id_transacao"]) == ["t1"]
    assert s2.estado.transacoes_incorporadas == 1 and not s2.estado.aberto


# ---------------------------------------------------------------------------
# 2. Evento novo da API não pode sumir por falta de instantâneo
# ---------------------------------------------------------------------------
def test_evento_da_api_sobrevive_a_queda_sem_novo_instantaneo(modelo_minimo, tmp_path):
    s = _servico(modelo_minimo, tmp_path)
    s.salvar_estado()  # instantâneo S (vazio)
    s.iniciar()
    r = s.submeter([_tx("t1", "2026-11-03T12:00:05Z"), _tx("t2", "2026-11-03T12:01:10Z")])
    assert r["aceitos"] == 2
    assert s.esperar_fila_vazia(20)
    assert list(_lavagem(tmp_path)["id_transacao"]) == ["t1"]  # t2 continua no minuto aberto
    _parar_sem_salvar(s)

    s2 = _reabrir(modelo_minimo, tmp_path)
    saida = _lavagem(tmp_path)
    assert list(saida["id_transacao"]) == ["t1"], "a previsão aceita pela API sumiu na restauração"
    assert s2.estado.transacoes_incorporadas == 1
    assert sum(len(v) for v in s2.estado.aberto.values()) == 1  # t2 aceito e ainda aberto
    # o produtor retransmite tudo: nada é aplicado ou previsto duas vezes
    s2.iniciar()
    s2.submeter([_tx("t1", "2026-11-03T12:00:05Z"), _tx("t2", "2026-11-03T12:01:10Z"),
                 _tx("t3", "2026-11-03T12:02:00Z")])
    assert s2.esperar_fila_vazia(20)
    s2.parar(salvar=False)
    ids = list(_lavagem(tmp_path)["id_transacao"])
    assert ids == ["t1", "t2"] and s2.estado.transacoes_incorporadas == 2


# ---------------------------------------------------------------------------
# 3. Falha depois de aplicar parte do lote
# ---------------------------------------------------------------------------
def test_falha_na_pontuacao_nao_perde_nem_duplica_a_transacao(modelo_minimo, tmp_path, monkeypatch):
    s = _servico(modelo_minimo, tmp_path)
    original = se.pontuar_lavagem
    falhas = {"n": 0}

    def falha_uma_vez(*a, **k):
        if falhas["n"] == 0:
            falhas["n"] += 1
            raise RuntimeError("falha temporária na pontuação")
        return original(*a, **k)

    monkeypatch.setattr(se, "pontuar_lavagem", falha_uma_vez)
    lote = [_evento(_tx("t1", "2026-11-03T12:00:05Z"), _iso("2026-11-03T12:00:05Z")),
            _evento(_tx("t2", "2026-11-03T12:01:10Z"), _iso("2026-11-03T12:01:10Z"))]
    s.processar(lote, da_fila=False)
    if not list(_lavagem(tmp_path)["id_transacao"]):
        # o produtor tenta de novo depois do erro
        s.processar([_evento(_tx("t1", "2026-11-03T12:00:05Z"), _iso("2026-11-03T12:00:05Z"))], da_fila=False)
    assert list(_lavagem(tmp_path)["id_transacao"]) == ["t1"], "t1 incorporada sem previsão recuperável"
    assert s.estado.a["env_tot"][s.estado.indice["1-A1"]] == 1  # uma única atualização lógica


def test_falha_na_previsao_de_rede_nao_marca_a_medicao_como_vista(modelo_minimo, tmp_path, monkeypatch):
    from testes.ml.conftest import gerar_rede
    medicao = gerar_rede(n_fluxos=1, por_split=(20, 0, 0)).drop(columns=["split", "alvo"]).iloc[15].to_dict()
    s = _servico(modelo_minimo, tmp_path)
    original = se.tabela_previsoes_rede
    falhas = {"n": 0}

    def falha_uma_vez(*a, **k):
        if falhas["n"] == 0:
            falhas["n"] += 1
            raise RuntimeError("falha temporária no modelo de rede")
        return original(*a, **k)

    monkeypatch.setattr(se, "tabela_previsoes_rede", falha_uma_vez)
    bruto = {"tipo": "medicao_rede", "modo": "novo_evento", "dados": medicao}
    s.processar([_evento(bruto, 1.0)], da_fila=False)
    caminho = tmp_path / "previsoes" / "eventos_novo_evento_rede.csv"
    if not caminho.is_file():
        s.processar([_evento(bruto, 2.0)], da_fila=False)  # retransmissão
    assert caminho.is_file() and len(pd.read_csv(caminho)) == 1


# ---------------------------------------------------------------------------
# 4. Ociosidade não é fim do minuto
# ---------------------------------------------------------------------------
def test_pausa_dentro_do_minuto_nao_torna_a_proxima_transacao_atrasada(modelo_minimo, tmp_path):
    s = _servico(modelo_minimo, tmp_path)
    s.processar([_evento(_tx("t1", "2026-11-03T12:00:05Z"), _iso("2026-11-03T12:00:05Z"))], da_fila=False)
    s._ultimo_evento = time.monotonic() - 6        # pausa maior que 5 s (relógio antigo)
    s.relogio = lambda: _iso("2026-11-03T12:00:11Z")  # relógio de processamento ainda no mesmo minuto
    s._ocioso()
    s.processar([_evento(_tx("t2", "2026-11-03T12:00:20Z"), _iso("2026-11-03T12:00:20Z"))], da_fila=False)
    assert s.rejeitados.get("atrasada", 0) == 0, "a pausa fechou o minuto corrente"
    assert sum(len(v) for v in s.estado.aberto.values()) == 2


# ===========================================================================
# Cenários de falha da versão corrigida (não existiam na antiga)
# ===========================================================================
def _tx_ev(ident: str, quando: str, conta: str = "A1") -> ev.Evento:
    return _evento(_tx(ident, quando, conta), _iso(quando))


def _contagem(pasta: Path) -> dict:
    return _lavagem(pasta)["id_transacao"].value_counts().to_dict()


def _falha(excecao):
    def levantar(*a, **k):
        raise excecao
    return levantar


class _FalhaNaEscrita:
    """Faz SaidaCSV.anexar falhar nas chamadas indicadas (contadas a partir de 1)."""

    def __init__(self, monkeypatch, chamadas, dominio=None):
        self.n, self.chamadas, self.dominio = 0, set(chamadas), dominio
        original = se.SaidaCSV.anexar
        falha = self

        def anexar(saida, df):
            if falha.dominio is None or saida.caminho.name.endswith(f"_{falha.dominio}.csv"):
                falha.n += 1
                if falha.n in falha.chamadas:
                    raise OSError("disco indisponível (injetado)")
            return original(saida, df)

        monkeypatch.setattr(se.SaidaCSV, "anexar", anexar)


def test_falha_na_escrita_da_saida_e_repetida_sem_duplicar(modelo_minimo, tmp_path, monkeypatch):
    s = _servico(modelo_minimo, tmp_path)
    _FalhaNaEscrita(monkeypatch, {1}, "lavagem")
    assert s.processar([_tx_ev("t1", "2026-11-03T12:00:05Z"), _tx_ev("t2", "2026-11-03T12:01:10Z")], da_fila=False)
    assert _contagem(tmp_path) == {"t1": 1}
    assert s.estado.transacoes_incorporadas == 1 and s.cont_operacao["falhas"] == 1


def test_falha_depois_de_saida_parcial_do_lote(modelo_minimo, tmp_path, monkeypatch):
    """A saída de rede do lote é escrita; a de lavagem falha: a repetição não duplica a rede."""
    from testes.ml.conftest import gerar_rede
    med = gerar_rede(n_fluxos=1, por_split=(5, 0, 0)).drop(columns=["split", "alvo"])
    s = _servico(modelo_minimo, tmp_path)
    _FalhaNaEscrita(monkeypatch, {1}, "lavagem")
    lote = [_evento({"tipo": "medicao_rede", "modo": "novo_evento", "dados": m}, 1.0) for m in med.to_dict("records")]
    lote += [_tx_ev("t1", "2026-11-03T12:00:05Z"), _tx_ev("t2", "2026-11-03T12:01:10Z")]
    assert s.processar(lote, da_fila=False)
    rede = pd.read_csv(tmp_path / "previsoes" / "eventos_novo_evento_rede.csv")
    assert len(rede) == 5 and rede["timestamp_previsao"].is_unique
    assert _contagem(tmp_path) == {"t1": 1}


def test_falha_persistente_bloqueia_sem_avancar_e_pode_ser_repetida(modelo_minimo, tmp_path, monkeypatch):
    s = _servico(modelo_minimo, tmp_path)
    s.processar([_tx_ev("t0", "2026-11-03T11:59:00Z")], da_fila=False)
    original = se.pontuar_lavagem
    quebrado = {"sim": True}

    def pontuar(*a, **k):
        if quebrado["sim"]:
            raise RuntimeError("modelo indisponível (injetado)")
        return original(*a, **k)

    monkeypatch.setattr(se, "pontuar_lavagem", pontuar)
    ok = s.processar([_tx_ev("t1", "2026-11-03T12:00:05Z"), _tx_ev("t2", "2026-11-03T12:01:10Z")], da_fila=False)
    assert not ok and s.bloqueio
    # o evento que falhou (o que fechou o minuto de t0) fica identificado; nada depois dele é confirmado
    assert s.bloqueio["ids"] == ["tx:t1"] and s.aplicado_ate < s.bloqueio["seqs"][0]
    assert s.consultar("tx:t1")["situacao"] == "bloqueado"
    assert s.consultar("tx:t2")["situacao"] == "aceito_pendente"
    assert list(_lavagem(tmp_path)["id_transacao"]) == []
    with pytest.raises(se.ErroEstado):
        s.processar([_tx_ev("t3", "2026-11-03T12:02:00Z")], da_fila=False)
    quebrado["sim"] = False
    assert s.repetir_bloqueados()
    assert _contagem(tmp_path) == {"t0": 1, "t1": 1} and s.estado.transacoes_incorporadas == 2


def test_falha_persistente_sobrevive_a_queda_e_volta_bloqueada(modelo_minimo, tmp_path, monkeypatch):
    s = _servico(modelo_minimo, tmp_path)
    monkeypatch.setattr(se, "pontuar_lavagem", _falha(RuntimeError("modelo indisponível (injetado)")))
    assert not s.processar([_tx_ev("t1", "2026-11-03T12:00:05Z"), _tx_ev("t2", "2026-11-03T12:01:10Z")],
                           da_fila=False)
    _parar_sem_salvar(s)
    s2 = _reabrir(modelo_minimo, tmp_path)  # a causa continua: volta bloqueado, sem perder nada
    assert s2.bloqueio and s2.bloqueio["ids"] == ["tx:t2"] and not s2.restaurado["ok"]
    monkeypatch.undo()
    assert s2.repetir_bloqueados()
    assert _contagem(tmp_path) == {"t1": 1}


def test_descarte_explicito_fica_registrado_e_sobrevive_ao_reinicio(modelo_minimo, tmp_path, monkeypatch):
    from testes.ml.conftest import gerar_rede
    medicao = gerar_rede(n_fluxos=1, por_split=(20, 0, 0)).drop(columns=["split", "alvo"]).iloc[15].to_dict()
    s = _servico(modelo_minimo, tmp_path)
    monkeypatch.setattr(se, "tabela_previsoes_rede", _falha(ValueError("medição que o modelo não aceita")))
    ruim = _evento({"tipo": "medicao_rede", "modo": "novo_evento", "dados": medicao}, 1.0)
    assert not s.processar([ruim, _tx_ev("t1", "2026-11-03T12:00:05Z")], da_fila=False)
    assert s.bloqueio["ids"] == [ruim.id_evento] and len(s.bloqueio["restantes"]) == 1
    assert s.descartar_bloqueados() == {"descartados": 1, "ok": True}
    assert sum(len(v) for v in s.estado.aberto.values()) == 1  # t1 seguiu
    recusas = pd.read_csv(tmp_path / "previsoes" / "eventos_novo_evento_recusas.csv")
    assert list(recusas["motivo"]) == ["descartado"]
    _parar_sem_salvar(s)
    s2 = _reabrir(modelo_minimo, tmp_path)  # a falha continua, mas o descarte também está no registro
    assert not s2.bloqueio and s2.consultar(ruim.chave_natural)["situacao"] == "descartado"
    assert len(pd.read_csv(tmp_path / "previsoes" / "eventos_novo_evento_recusas.csv")) == 1


def test_falha_ao_gravar_o_instantaneo_mantem_o_anterior_e_o_registro(modelo_minimo, tmp_path, monkeypatch):
    from src.ml import incremental
    s = _servico(modelo_minimo, tmp_path)
    s.processar([_tx_ev("t1", "2026-11-03T12:00:05Z"), _tx_ev("t2", "2026-11-03T12:01:10Z")], da_fila=False)
    assert s.salvar_estado()
    s.processar([_tx_ev("t3", "2026-11-03T12:02:10Z")], da_fila=False)
    monkeypatch.setattr(incremental.EstadoFinanceiro, "salvar", _falha(OSError("disco cheio (injetado)")))
    assert s.salvar_estado() is None and s.cont_operacao["falhas_instantaneo"] == 1
    monkeypatch.undo()
    _parar_sem_salvar(s)
    s2 = _reabrir(modelo_minimo, tmp_path)
    assert _contagem(tmp_path) == {"t1": 1, "t2": 1}
    assert s2.estado.transacoes_incorporadas == 2 and s2.restaurado["eventos_reaplicados"] == 1


def test_reinicio_entre_as_etapas_de_confirmacao(modelo_minimo, tmp_path, monkeypatch):
    """Quedas: depois de gravar no registro e antes de aplicar; com linha final incompleta;
    depois de gravar o instantâneo e antes de podar o registro."""
    s = _servico(modelo_minimo, tmp_path)
    s.processar([_tx_ev("t1", "2026-11-03T12:00:05Z")], da_fila=False)
    s.salvar_estado()
    s.aceitar([_tx_ev("t2", "2026-11-03T12:01:10Z")], sincronizar=True, enfileirar=False)  # aceito, não aplicado
    seg = sorted((tmp_path / "estado" / "registro").glob("wal_*.jsonl"))[-1]
    with open(seg, "a", encoding="utf-8") as fh:  # escrita interrompida (não confirmada ao produtor)
        fh.write('{"seq": 999, "tipo": "transacao", "dados": {"id_trans')
    _parar_sem_salvar(s)
    s2 = _reabrir(modelo_minimo, tmp_path)
    assert _contagem(tmp_path) == {"t1": 1} and s2.estado.transacoes_incorporadas == 1
    assert s2.consultar("tx:t2")["situacao"] == "aplicado"
    monkeypatch.setattr(s2.registro, "podar", _falha(OSError("queda antes de podar")))
    assert s2.salvar_estado()
    _parar_sem_salvar(s2)
    monkeypatch.undo()
    s3 = _reabrir(modelo_minimo, tmp_path)
    assert s3.restaurado["eventos_reaplicados"] == 0 and _contagem(tmp_path) == {"t1": 1}
    assert s3.estado.transacoes_incorporadas == 1 and sum(len(v) for v in s3.estado.aberto.values()) == 1


def test_identidade_repetida_com_conteudo_diferente_e_conflito(modelo_minimo, tmp_path):
    s = _servico(modelo_minimo, tmp_path)
    r1 = s.submeter([_tx("t1", "2026-11-03T12:00:05Z")])
    r2 = s.submeter([_tx("t1", "2026-11-03T12:00:05Z")])
    outro = _tx("t1", "2026-11-03T12:00:05Z")
    outro["dados"]["valor_pago"] = 999.0
    r3 = s.submeter([outro])
    assert r1["aceitos"] == 1 and r2["aceitos"] == 0 and r2["ja_aceitos"][0]["seq"] == r1["ids_aceitos"][0]["seq"]
    assert r3["aceitos"] == 0 and r3["recusados"][0]["motivo"] == "conflito"
    reg = next(s.registro.ler_depois(0))  # origem, modo, versão e identidade ficam no registro
    assert (reg["origem"], reg["modo"], reg["versao_esquema"], reg["chave_natural"]) == \
        ("api", "novo_evento", "transacao_hismall_v1", "tx:t1")


def test_relogio_fecha_so_depois_do_fim_do_minuto_mais_atraso(modelo_minimo, tmp_path):
    cfg = Configuracao(fechar_ocioso_s=0.0, atraso_permitido_min=1, carencia_relogio_s=2.0)
    s = ServicoEventos(modelo_minimo, tmp_path / "previsoes", tmp_path / "estado", cfg)
    s.processar([_tx_ev("t1", "2026-11-03T12:00:05Z")], da_fila=False)
    for agora, fechado in (("2026-11-03T12:01:30Z", False),   # o minuto acabou, mas há 1 min de atraso permitido
                           ("2026-11-03T12:02:01Z", False),   # ainda dentro da carência
                           ("2026-11-03T12:02:03Z", True)):
        s.relogio = lambda a=agora: _iso(a)
        s._ocioso()
        assert (not s.estado.aberto) == fechado, agora
    assert _contagem(tmp_path) == {"t1": 1}
    _parar_sem_salvar(s)  # o fechamento pelo relógio ficou no registro: a reconstrução é idêntica
    s2 = _reabrir(modelo_minimo, tmp_path)
    assert not s2.estado.aberto and _contagem(tmp_path) == {"t1": 1}


def test_relogio_nunca_fecha_minutos_de_replay(modelo_minimo, tmp_path):
    s = _servico(modelo_minimo, tmp_path)
    bruto = _tx("r1", "2022-09-10T05:31:00Z")
    bruto["modo"] = "replay_historico"
    s.processar([_evento(bruto, _iso("2026-11-03T12:00:00Z"))], da_fila=False)
    s._ultimo_evento = time.monotonic() - 3600
    s.relogio = lambda: _iso("2026-11-03T12:00:00Z")  # 4 anos depois do evento
    s._ocioso()
    assert s.estado.aberto  # só fecha por evento posterior, fim do replay ou comando
    r = s.fechar_minutos()
    assert r["minutos_fechados"] == 1 and not s.estado.aberto


def test_esperar_fila_nao_trava_sem_sessao(modelo_minimo, tmp_path):
    """Sem sessão o trabalhador não consome; o replay pausado não pode esperar o prazo inteiro."""
    autorizado = {"sim": True}
    s = ServicoEventos(modelo_minimo, tmp_path / "previsoes", tmp_path / "estado", Configuracao(),
                       autorizado=lambda: autorizado["sim"])
    s.iniciar()
    autorizado["sim"] = False
    time.sleep(0.3)  # o laço já está na espera por autorização
    s.submeter([_tx("t1", "2026-11-03T12:00:05Z")])
    inicio = time.monotonic()
    assert s.esperar_fila_vazia(30) is False and time.monotonic() - inicio < 5
    assert s.fila.qsize() == 1  # não foi consumido, e está no registro
    assert next(s.registro.ler_depois(0))["chave_natural"] == "tx:t1"
    autorizado["sim"] = True
    assert s.esperar_fila_vazia(20)
    s.parar(salvar=False)
    assert sum(len(v) for v in s.estado.aberto.values()) == 1


def test_instantaneo_antigo_sem_registro_nao_e_carregado(modelo_minimo, tmp_path):
    (tmp_path / "estado").mkdir()
    antigo = tmp_path / "estado" / "estado_eventos.pkl"
    antigo.write_bytes(b"instantaneo de antes do registro duravel")
    s = _servico(modelo_minimo, tmp_path)
    assert s.aberto and not antigo.exists()
    assert (tmp_path / "estado" / "estado_eventos.legado.pkl").is_file()
