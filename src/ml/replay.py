"""Replay histórico: reenvia um arquivo existente, em ordem cronológica, como eventos.

É sempre rotulado ``replay_historico``: os eventos vêm de um arquivo antigo, não
de uma fonte conectada. O replay é separado da API de eventos novos: produz
:class:`~src.ml.eventos.Evento` diretamente (o arquivo inteiro é validado uma
vez ao preparar) e espera vaga na fila em vez de ser recusado.

* **ordem** — por instante (estável: empates mantêm a ordem do arquivo);
* **pausa** — só na virada do minuto, para não deixar meio minuto
  financeiro aberto;
* **retomada** — continua da última posição processada pelo trabalhador,
  sem reenviar o que já entrou no estado. Os eventos passam pelo registro
  durável como os da API; a fonte de verdade do replay continua sendo o
  arquivo, por isso o replay não precisa de fsync por evento;
* **sessão** — se o serviço deixar de estar autorizado (sessão responsável
  expirada ou encerrada), o replay pausa na virada do minuto e só continua
  por ação explícita;
* **histórico financeiro** — opcionalmente, antes do primeiro evento, o estado
  é montado com as transações do HI-Small anteriores ao início do arquivo
  (``--historico`` da CLI). Sem isso, as contas começam sem passado e as
  previsões das primeiras 72 h saem com ``historico_incompleto``.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from src.ml import eventos as ev
from src.ml.ingestao import ler_hismall, ler_rede
from src.ml.servico_eventos import ServicoEventos

FONTES = ("rede", "financeiro")


class ReplayHistorico:
    def __init__(self, servico: ServicoEventos, fonte: str, arquivo: Path,
                 eventos_por_segundo: float = 0.0, historico: Optional[Path] = None):
        if fonte not in FONTES:
            raise ValueError(f"fonte inválida: {fonte}")
        self.servico = servico
        self.fonte = fonte
        self.arquivo = Path(arquivo)
        self.eventos_por_segundo = float(eventos_por_segundo)
        self.historico = Path(historico) if historico else None
        self.chave = f"{fonte}:{self.arquivo.name}"
        self.situacao = "parado"
        self.mensagem = ""
        self.total = 0
        self.enviados = 0
        self.inicio_em: Optional[float] = None
        self.carga: Optional[Dict[str, Any]] = None
        self._df: Optional[pd.DataFrame] = None
        self._nomes: Optional[np.ndarray] = None
        self._pausar = threading.Event()
        self._parar = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- controle --------------------------------------------------------------
    def iniciar(self) -> None:
        if self._thread and self._thread.is_alive():
            self._pausar.clear()
            return
        self._pausar.clear()
        self._parar.clear()
        self.servico.iniciar()
        self._thread = threading.Thread(target=self._executar, name=f"replay-{self.fonte}", daemon=True)
        self._thread.start()

    def pausar(self) -> None:
        self._pausar.set()

    def parar(self, timeout: float = 10.0) -> None:
        self._parar.set()
        self._pausar.clear()
        if self._thread:
            self._thread.join(timeout)

    def processados(self) -> int:
        return self.servico.replay_processado.get(self.chave, -1) + 1

    def status(self) -> Dict[str, Any]:
        proc = self.processados()
        return {
            "fonte": self.fonte, "arquivo": self.arquivo.name, "chave": self.chave,
            "modo": "replay_historico", "rotulo": "Replay histórico (arquivo existente, não é fonte ao vivo)",
            "situacao": self.situacao, "mensagem": self.mensagem,
            "total": self.total, "enviados": self.enviados, "processados": proc,
            "progresso": (proc / self.total) if self.total else 0.0,
            "eventos_por_segundo": self.eventos_por_segundo or None,
            "historico": str(self.historico.name) if self.historico else None,
            "carga_inicial": self.carga,
        }

    # -- execução --------------------------------------------------------------
    def _executar(self) -> None:
        try:
            if self._df is None:
                self.situacao = "preparando"
                self._preparar()
            inicio = self.processados()  # retoma de onde o trabalhador parou
            if self.fonte == "financeiro" and self.historico and inicio == 0:
                self._carregar_historico()
            self.situacao = "rodando"
            self.inicio_em = time.monotonic()
            self.enviados = inicio
            self._produzir(inicio)
            if self._parar.is_set():
                self.situacao = "parado"
                return
            if self.fonte == "financeiro":
                # Fecha o último minuto do arquivo. O replay de rede não envia isso: não tem
                # minutos abertos e fecharia, no meio, o minuto de um replay financeiro simultâneo.
                self.servico.enfileirar(ev.controle("fechar", f"replay:{self.arquivo.name}", "replay_historico"))
            self.servico.esperar_fila_vazia(timeout=600)
            self.servico.salvar_estado()
            self.situacao = "concluido"
        except Exception as exc:  # pragma: no cover - mostrado na interface
            self.situacao = "erro"
            self.mensagem = f"{type(exc).__name__}: {exc}"

    def _preparar(self) -> None:
        if self.fonte == "rede":
            exigir = ["classe_atual"] if self.servico.cab_rede.usa_classe_atual else []
            df, _ = ler_rede([self.arquivo], modo="inferencia", exigir=exigir)
            df = df.drop(columns=[c for c in ("alvo", "split") if c in df])
            self._df = df.sort_values(["timestamp", "linha_origem"], kind="stable").reset_index(drop=True)
        else:
            dados = ler_hismall(self.arquivo, exigir_rotulo=False)
            self._df = dados.trans.sort_values("minuto", kind="stable").reset_index(drop=True)
            self._nomes = dados.nomes_contas
        self.total = int(len(self._df))
        self.mensagem = f"{self.total} eventos em ordem cronológica"

    def _carregar_historico(self) -> None:
        estado = self.servico.estado
        if estado.transacoes_incorporadas or estado.aberto:
            self.mensagem = "estado financeiro já tem dados; carga inicial não refeita"
            return
        self.situacao = "carregando_historico"
        self.mensagem = f"lendo {self.historico.name} (pode levar cerca de 1 min)"
        hist = ler_hismall(self.historico, exigir_rotulo=False)
        primeiro = int(self._df["minuto"].min())
        trans = hist.trans.loc[hist.trans["minuto"] < primeiro].reset_index(drop=True)
        with self.servico.trava:
            self.carga = estado.carregar_historico(trans, hist.nomes_contas,
                                                   f"{self.historico.name}, antes de {ev.iso(primeiro * 60)}")
            # A carga não passa pelo registro: o instantâneo vira a base da recuperação.
            self.servico.salvar_estado()
        self.mensagem = f"histórico carregado: {self.carga['transacoes']} transações"

    def _eventos(self, ini: int, fim: int):
        df = self._df.iloc[ini:fim]
        origem = f"replay:{self.arquivo.name}"
        recebido = ev.agora()
        if self.fonte == "rede":
            colunas = [c for c in df.columns if c not in ("arquivo_origem", "linha_origem")]
            for pos, linha, dados in zip(range(ini, fim), df["linha_origem"].tolist(),
                                         df[colunas].to_dict("records")):
                dados["timestamp"] = int(dados["timestamp"])
                natural = f"rede:{dados['id_fluxo']}@{dados['timestamp']}"
                e = ev.Evento(natural, natural, "medicao_rede", "rede_v1", float(dados["timestamp"]), recebido,
                              origem, "replay_historico", dados, controle={"replay": self.chave, "posicao": pos})
                yield e, None
            return
        nomes = self._nomes
        for pos, r in zip(range(ini, fim), df.itertuples(index=False)):
            ident = f"{self.arquivo.name}#{int(r.id_transacao)}"
            t = float(r.minuto * 60)
            dados = {
                "id_transacao": ident, "epoca": t, "minuto": int(r.minuto), "timestamp_disponivel": t,
                "banco_origem": str(int(r.banco_origem)), "banco_destino": str(int(r.banco_destino)),
                "conta_origem": str(nomes[r.conta_origem]), "conta_destino": str(nomes[r.conta_destino]),
                "valor_pago": float(r.valor_pago), "valor_recebido": float(r.valor_recebido),
                "moeda_pagamento": str(r.moeda_pagamento), "moeda_recebimento": str(r.moeda_recebimento),
                "formato": str(r.formato),
            }
            e = ev.Evento(f"tx:{ident}", f"tx:{ident}", "transacao", "transacao_hismall_v1", t, recebido,
                          origem, "replay_historico", dados, controle={"replay": self.chave, "posicao": pos})
            yield e, int(r.minuto)

    def _produzir(self, inicio: int) -> None:
        bloco = 500
        pos = inicio
        minuto_atual = None
        enviados_desde = 0
        t0 = time.monotonic()
        grupo: list = []

        def despachar() -> None:
            nonlocal grupo
            while grupo and not self._parar.is_set():
                try:
                    self.servico.enfileirar_varios(grupo, timeout=0.5)
                    grupo = []
                except queue.Full:  # fila cheia: o replay espera
                    continue

        while pos < self.total and not self._parar.is_set():
            for e, minuto in self._eventos(pos, min(pos + bloco, self.total)):
                virou = minuto is None or minuto != minuto_atual
                if virou and (self._pausar.is_set() or not self.servico.autorizado()):
                    despachar()
                    if not self.servico.autorizado():
                        self._pausar.set()
                        self.mensagem = "pausado: a sessão responsável não está ativa; retome explicitamente"
                    self.situacao = "pausando"  # esvazia a fila e grava o instantâneo
                    # Sem sessão o trabalhador não consome: o que está na fila continua no registro.
                    self.servico.esperar_fila_vazia(timeout=600)
                    self.servico.salvar_estado()
                    self.situacao = "pausado"
                    while self._pausar.is_set() and not self._parar.is_set():
                        time.sleep(0.1)
                    self.situacao = "rodando"
                    t0, enviados_desde = time.monotonic(), 0
                if self._parar.is_set():
                    return
                minuto_atual = minuto
                e.recebido_em = ev.agora()
                grupo.append(e)
                if len(grupo) >= 200 or self.eventos_por_segundo > 0:
                    despachar()
                pos += 1
                self.enviados = pos
                enviados_desde += 1
                if self.eventos_por_segundo > 0:
                    atraso = enviados_desde / self.eventos_por_segundo - (time.monotonic() - t0)
                    if atraso > 0:
                        time.sleep(atraso)
        despachar()
