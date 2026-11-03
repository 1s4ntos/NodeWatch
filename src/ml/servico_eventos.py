"""Processamento de eventos: fila limitada, um trabalhador e estado persistido.

Camadas (cada uma testável sozinha):

1. **ingestão** — :func:`src.ml.eventos.montar_evento` valida envelope e dados;
   :meth:`ServicoEventos.submeter` põe na fila (limitada; cheia = recusa
   explícita, nunca descarte silencioso);
2. **preparação de atributos** — rede: as medições já chegam em ``rede_v1``;
   financeiro: :class:`src.ml.incremental.EstadoFinanceiro` (estado por conta);
3. **inferência** — cabeças do artefato carregado uma vez por processo
   (nada é reajustado);
4. **persistência do estado** — instantâneo atômico do estado financeiro,
   dos sinais de rede, dos vínculos, dos cursores de replay e do tamanho das
   saídas;
5. **apresentação** — CSVs ``previsao_rede_v1``/``previsao_lavagem_v1`` em
   ``artefatos_ml/previsoes`` (abertos pela seção Machine Learning) e o
   resumo de :meth:`ServicoEventos.status`.

Regras de entrega:

* **duplicatas** — mesma chave natural: a segunda é recusada (``duplicada``);
* **atrasos** — transação de minuto já fechado é recusada (``atrasada``) e não
  entra no estado; ``atraso_permitido_min`` segura minutos abertos por mais
  tempo; sem eventos por ``fechar_ocioso_s`` segundos, os minutos abertos de
  eventos novos são fechados;
* **fila cheia** — a API recusa com ``fila_cheia`` (HTTP 429); o replay espera;
* **reinício** — o estado salvo é restaurado, as saídas voltam ao tamanho
  registrado nele e o replay continua da posição salva; o que foi
  processado depois do instantâneo é refeito sem duplicar.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections import Counter, OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from src.ml import eventos as ev
from src.ml.incremental import EstadoFinanceiro, MinutoFechado
from src.ml.integracao import associar_sinais_rede
from src.ml.previsao import AVISO_LAVAGEM, pontuar_lavagem, tabela_previsoes_rede

TOLERANCIA_SINAL_S = 480.0
MAX_RECENTES = 200
MAX_LATENCIAS = 5_000
MAX_IDS_REDE = 200_000
PREFIXO_SAIDA = "eventos_"
AVISO_FUSAO = ("Fusão rede+transação indisponível: o sinal de rede vinculado é exibido ao lado do "
               "score financeiro, sem combiná-los. Não há dados reais relacionados para treinar "
               "nem validar a fusão.")


class FilaCheia(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Saídas
# ---------------------------------------------------------------------------
class SaidaCSV:
    """CSV de previsões que só cresce, com o relatório ``.relatorio.json`` ao lado."""

    def __init__(self, caminho: Path, relatorio: Dict[str, Any], continuar: bool = False):
        """``continuar=False`` recomeça o arquivo: sem estado restaurado, as linhas
        antigas não pertencem a esta sessão e poderiam se repetir."""
        self.caminho = Path(caminho)
        self.relatorio = dict(relatorio)
        self.colunas: Optional[List[str]] = None
        self.linhas = 0
        if not continuar and self.caminho.is_file():
            self.caminho.unlink()
            self.caminho.with_suffix(".relatorio.json").unlink(missing_ok=True)
        if self.caminho.is_file() and self.caminho.stat().st_size:
            with open(self.caminho, encoding="utf-8") as fh:
                self.colunas = fh.readline().rstrip("\n").split(",")
                self.linhas = sum(1 for _ in fh)

    def anexar(self, df: pd.DataFrame) -> None:
        if df.empty:
            return
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        if self.colunas is None:
            self.colunas = list(df.columns)
            df.to_csv(self.caminho, index=False, encoding="utf-8", lineterminator="\n")
        else:
            df.reindex(columns=self.colunas).to_csv(self.caminho, mode="a", header=False, index=False,
                                                    encoding="utf-8", lineterminator="\n")
        self.linhas += len(df)
        self._gravar_relatorio()

    def _gravar_relatorio(self) -> None:
        rel = dict(self.relatorio, linhas_previstas=self.linhas,
                   atualizado_em=ev.iso(ev.agora()))
        tmp = self.caminho.with_suffix(".relatorio.json.tmp")
        tmp.write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.caminho.with_suffix(".relatorio.json"))

    def marca(self) -> Tuple[int, int]:
        return (self.caminho.stat().st_size if self.caminho.is_file() else 0, self.linhas)

    def voltar_para(self, marca: Tuple[int, int]) -> None:
        """Descarta o que foi escrito depois do instantâneo (será refeito)."""
        tamanho, linhas = marca
        if self.caminho.is_file() and self.caminho.stat().st_size > tamanho:
            with open(self.caminho, "r+b") as fh:
                fh.truncate(tamanho)
        self.linhas = linhas
        if tamanho == 0:
            self.colunas = None
        if self.caminho.is_file():
            self._gravar_relatorio()


# ---------------------------------------------------------------------------
# Vínculos e sinais de rede (disponíveis no instante da decisão)
# ---------------------------------------------------------------------------
class RegistroVinculos:
    def __init__(self) -> None:
        self.por_chave: Dict[str, List[Dict[str, Any]]] = {}
        self.ids: set = set()

    def adicionar(self, v: Dict[str, Any]) -> bool:
        if v["id_vinculo"] in self.ids:
            return False
        self.ids.add(v["id_vinculo"])
        self.por_chave.setdefault(v["chave"], []).append(v)
        return True

    def __len__(self) -> int:
        return len(self.ids)

    def tabela(self, chaves: Sequence[str]) -> pd.DataFrame:
        linhas = [v for c in set(chaves) for v in self.por_chave.get(c, [])]
        if not linhas:
            return pd.DataFrame()
        df = pd.DataFrame(linhas)
        for c in ("valido_de", "valido_ate", "disponivel_em"):
            df[c] = pd.to_datetime(df[c], unit="s", utc=True)
        return df[["chave", "tipo_chave", "id_fluxo", "valido_de", "valido_ate", "fonte_vinculo", "disponivel_em"]]


class SinaisRede:
    """Últimas previsões de rede por fluxo (o suficiente para a tolerância)."""

    def __init__(self, maximo_por_fluxo: int = 64):
        self.maximo = maximo_por_fluxo
        self.por_fluxo: Dict[str, Deque[Tuple[int, float, bool, str]]] = {}

    def adicionar(self, saida: pd.DataFrame) -> None:
        for f, t, s, a, ate in zip(saida["id_fluxo"].astype(str), saida["timestamp_previsao"].astype(np.int64),
                                   saida["score_alerta_rede"].astype(float), saida["alerta_rede"].astype(bool),
                                   saida["modelo_rede_treinado_ate"].astype(str)):
            dq = self.por_fluxo.setdefault(f, deque(maxlen=self.maximo))
            dq.append((int(t), float(s), bool(a), ate))

    def tabela(self, fluxos: Sequence[str]) -> pd.DataFrame:
        linhas = [(f, *x) for f in set(fluxos) for x in self.por_fluxo.get(f, ())]
        if not linhas:
            return pd.DataFrame()
        df = pd.DataFrame(linhas, columns=["id_fluxo", "timestamp_previsao", "score_alerta_rede",
                                           "alerta_rede", "modelo_rede_treinado_ate"])
        df["modelo_rede_treinado_ate"] = df["modelo_rede_treinado_ate"].replace("", None)
        return df


# ---------------------------------------------------------------------------
# Serviço
# ---------------------------------------------------------------------------
@dataclass
class Configuracao:
    capacidade_fila: int = 20_000
    atraso_permitido_min: int = 0
    fechar_ocioso_s: float = 5.0
    salvar_a_cada_s: float = 120.0
    tolerancia_sinal_s: float = TOLERANCIA_SINAL_S
    lote_maximo: int = 2_000


class ServicoEventos:
    """Recebe eventos, mantém o estado e grava previsões. Um trabalhador por processo."""

    def __init__(self, modelo, pasta_saida: Path, pasta_estado: Optional[Path],
                 config: Optional[Configuracao] = None, rotulo: str = ""):
        self.modelo = modelo
        self.config = config or Configuracao()
        self.pasta_saida = Path(pasta_saida)
        self.pasta_estado = Path(pasta_estado) if pasta_estado else None
        self.rotulo = rotulo
        self.cab_rede = modelo.cabeca("estado_rede")
        self.cab_lav = modelo.cabeca("lavagem")
        self.prep = modelo.codificadores["financeiro"]
        self.trava = threading.RLock()  # estado, saídas e contadores do trabalhador
        self._trava_ingestao = threading.Lock()  # sequência e contadores da API (nunca espera o trabalhador)
        self._ultimo_status: Dict[str, Any] = {}
        self.fila: "queue.Queue[ev.Evento]" = queue.Queue(maxsize=self.config.capacidade_fila)
        self._parar = threading.Event()
        self._trabalhador: Optional[threading.Thread] = None
        self._sequencia = 0
        self._ultimo_evento = 0.0
        self._ultimo_salvo = time.monotonic()
        self._sujo = False
        self._zerar()
        self.restaurado: Optional[Dict[str, Any]] = None
        if self.pasta_estado is not None:
            self.restaurado = self.restaurar()

    # -- estado em memória -----------------------------------------------------
    def _zerar(self) -> None:
        self.estado = EstadoFinanceiro(self.prep)
        self.vinculos = RegistroVinculos()
        self.sinais = SinaisRede()
        self.ids_rede: "OrderedDict[str, None]" = OrderedDict()
        self.saidas: Dict[str, SaidaCSV] = {}
        self.cont: Counter = Counter()
        self.cont_api: Counter = Counter()
        self.rejeicoes_api: Deque[Dict[str, Any]] = deque(maxlen=MAX_RECENTES)
        self.rejeitados: Counter = Counter()
        self.recentes = {"rede": deque(maxlen=MAX_RECENTES), "lavagem": deque(maxlen=MAX_RECENTES),
                         "rejeicoes": deque(maxlen=MAX_RECENTES)}
        self.latencias = {"rede": deque(maxlen=MAX_LATENCIAS), "lavagem": deque(maxlen=MAX_LATENCIAS)}
        self.falhas: Deque[Dict[str, Any]] = deque(maxlen=50)
        self.replay_processado: Dict[str, int] = {}
        self.modos_vistos: Dict[str, float] = {}
        self.ultima_atualizacao: Optional[float] = None
        self._pendentes: Dict[Tuple[str, str], List[pd.DataFrame]] = {}

    def eh_conta(self, chave: str) -> bool:
        return chave in self.estado.indice

    # -- ingestão --------------------------------------------------------------
    def proxima_sequencia(self) -> int:
        with self._trava_ingestao:
            self._sequencia += 1
            return self._sequencia

    def submeter(self, brutos: Sequence[Any], origem: str = "api", modo: str = "novo_evento"
                 ) -> Dict[str, Any]:
        """Valida e enfileira eventos da API. Nunca bloqueia: fila cheia = recusa."""
        recebido = ev.agora()
        aceitos, recusados = [], []
        validos: List[ev.Evento] = []
        for i, b in enumerate(brutos):
            try:
                e = ev.montar_evento(b, recebido, origem, modo, self.eh_conta)
                validos.append(e)
            except ev.ErroEvento as exc:
                recusados.append({"posicao": i, "id_evento": exc.id_evento, "motivo": "invalido",
                                  "problemas": exc.problemas})
        # medições de rede: validação completa do esquema, em lote
        rede = [e for e in validos if e.tipo == "medicao_rede"]
        if rede:
            df = pd.DataFrame([e.dados for e in rede])
            exigir = ["classe_atual"] if self.cab_rede.usa_classe_atual else []
            _, ruins = ev.validar_lote_rede(df, exigir)
            ruins_ids = {id(rede[i]) for i, _ in ruins}
            for i, probs in ruins:
                recusados.append({"posicao": None, "id_evento": rede[i].id_evento, "motivo": "invalido",
                                  "problemas": probs})
            validos = [e for e in validos if id(e) not in ruins_ids]
        for e in validos:
            e.sequencia = self.proxima_sequencia()
            try:
                self.fila.put_nowait(e)
                aceitos.append(e.id_evento)
            except queue.Full:
                recusados.append({"posicao": None, "id_evento": e.id_evento, "motivo": "fila_cheia",
                                  "problemas": [f"fila com {self.fila.maxsize} eventos pendentes; tente de novo"]})
        with self._trava_ingestao:
            self.cont_api["recebidos"] += len(brutos)
            for r in recusados:
                self.cont_api[f"recusados_{r['motivo']}"] += 1
                self.rejeicoes_api.append(dict(r, em=ev.iso(recebido)))
        return {"aceitos": len(aceitos), "recusados": recusados, "ids_aceitos": aceitos[:1000],
                "pendentes_na_fila": self.fila.qsize()}

    def enfileirar(self, e: ev.Evento, timeout: Optional[float] = None) -> None:
        """Para produtores internos (replay): espera vaga na fila."""
        self.fila.put(e, timeout=timeout)

    # -- trabalhador -------------------------------------------------------------
    def iniciar(self) -> None:
        if self._trabalhador and self._trabalhador.is_alive():
            return
        self._parar.clear()
        self._trabalhador = threading.Thread(target=self._laco, name="nodewatch-eventos", daemon=True)
        self._trabalhador.start()

    def parar(self, salvar: bool = True, timeout: float = 30.0) -> None:
        self._parar.set()
        if self._trabalhador:
            self._trabalhador.join(timeout)
        if salvar and self.pasta_estado is not None:
            self.salvar_estado()

    def ativo(self) -> bool:
        return bool(self._trabalhador and self._trabalhador.is_alive())

    def _laco(self) -> None:
        while not self._parar.is_set():
            try:
                primeiro = self.fila.get(timeout=0.25)
            except queue.Empty:
                self._ocioso()
                continue
            lote = [primeiro]
            while len(lote) < self.config.lote_maximo:
                try:
                    lote.append(self.fila.get_nowait())
                except queue.Empty:
                    break
            self.processar(lote)

    def _ocioso(self) -> None:
        with self.trava:
            pouco = time.monotonic() - self._ultimo_evento
            if self.estado.aberto and pouco >= self.config.fechar_ocioso_s:
                self._fechar(None)
            if (self._sujo and self.pasta_estado is not None
                    and time.monotonic() - self._ultimo_salvo >= self.config.salvar_a_cada_s):
                self.salvar_estado()

    def esperar_fila_vazia(self, timeout: float = 60.0) -> bool:
        fim = time.monotonic() + timeout
        while time.monotonic() < fim:
            if self.fila.unfinished_tasks == 0:
                return True
            time.sleep(0.01)
        return False

    # -- processamento -----------------------------------------------------------
    def processar(self, lote: List[ev.Evento], da_fila: bool = True) -> None:
        """Processa um lote em ordem segura: rede e vínculos antes das transações.

        ``da_fila=False`` para lotes processados direto (laboratório, testes).
        """
        with self.trava:
            self._ultimo_evento = time.monotonic()
            try:
                por_tipo: Dict[str, List[ev.Evento]] = {"medicao_rede": [], "vinculo": [], "transacao": [],
                                                       "controle": []}
                for e in lote:
                    por_tipo[e.tipo].append(e)
                    if e.tipo != "controle" and e.modo in ev.MODOS:
                        self.modos_vistos[e.modo] = ev.agora()
                self._processar_rede(por_tipo["medicao_rede"])
                for e in por_tipo["vinculo"]:
                    if self.vinculos.adicionar(e.dados):
                        self.cont["vinculos"] += 1
                    else:
                        self._rejeitar(e.id_evento, "duplicada", "vínculo já registrado")
                self._processar_transacoes(por_tipo["transacao"])
                for e in por_tipo["controle"]:
                    if e.dados.get("acao") == "fechar":
                        self._fechar(None)
                self._escrever_pendentes()
                for e in lote:
                    r = e.controle.get("replay")
                    if r:
                        self.replay_processado[r] = max(self.replay_processado.get(r, -1), e.controle["posicao"])
                self.ultima_atualizacao = ev.agora()
                self._sujo = True
            except Exception as exc:  # um lote ruim não derruba o trabalhador
                self._pendentes.clear()
                self.cont["falhas"] += len(lote)
                self.falhas.append({"em": ev.iso(ev.agora()), "eventos": len(lote),
                                    "erro": f"{type(exc).__name__}: {exc}"})
            finally:
                if da_fila:
                    for _ in lote:
                        self.fila.task_done()

    def _guardar(self, dominio: str, saida: pd.DataFrame) -> None:
        for modo, parte in saida.groupby("modo_evento", sort=True):
            self._pendentes.setdefault((dominio, modo), []).append(parte)
        self.recentes[dominio].extend(saida.tail(MAX_RECENTES).to_dict("records"))

    def _escrever_pendentes(self) -> None:
        """Uma escrita por arquivo e por lote (não por minuto)."""
        for (dominio, modo), partes in self._pendentes.items():
            self._saida(dominio, modo).anexar(pd.concat(partes, ignore_index=True))
        self._pendentes.clear()

    def _rejeitar(self, ident: str, motivo: str, detalhe: str) -> None:
        self.rejeitados[motivo] += 1
        self.recentes["rejeicoes"].append({"id_evento": ident, "motivo": motivo, "problemas": [detalhe],
                                           "em": ev.iso(ev.agora())})

    def _saida(self, dominio: str, modo: str) -> SaidaCSV:
        chave = f"{dominio}:{modo}"
        if chave not in self.saidas:
            nome = f"{PREFIXO_SAIDA}{modo}{self.rotulo}_{dominio}.csv"
            rel = {"tarefa": "estado_rede" if dominio == "rede" else "lavagem",
                   "gerado_por": "processamento de eventos (src/ml/servico_eventos.py)",
                   "modo": modo, "modo_rotulo": ev.ROTULO_MODO.get(modo, modo),
                   "aviso": AVISO_LAVAGEM if dominio == "lavagem" else
                   "Previsão do estado da próxima medição; não é fraude."}
            self.saidas[chave] = SaidaCSV(self.pasta_saida / nome, rel)
        return self.saidas[chave]

    def _processar_rede(self, eventos: List[ev.Evento]) -> None:
        novos = []
        for e in eventos:
            if e.chave_natural in self.ids_rede:
                self._rejeitar(e.id_evento, "duplicada", "medição já recebida (id_fluxo + timestamp)")
                continue
            self.ids_rede[e.chave_natural] = None
            novos.append(e)
        while len(self.ids_rede) > MAX_IDS_REDE:
            self.ids_rede.popitem(last=False)
        if not novos:
            return
        df = pd.DataFrame([e.dados for e in novos])
        df.insert(0, "linha_origem", [e.sequencia for e in novos])
        df.insert(0, "arquivo_origem", [e.origem for e in novos])
        saida, _ = tabela_previsoes_rede(self.cab_rede, df)
        processado = ev.agora()
        self._anotar(saida, novos, processado)
        self.sinais.adicionar(saida)
        self._guardar("rede", saida)
        self.cont["previsoes_rede"] += len(saida)
        self.latencias["rede"].extend(1000 * (processado - e.recebido_em) for e in novos)

    @staticmethod
    def _anotar(saida: pd.DataFrame, eventos: List[ev.Evento], processado: float) -> None:
        saida["id_evento"] = [e.id_evento for e in eventos]
        saida["origem_evento"] = [e.origem for e in eventos]
        saida["modo_evento"] = [e.modo for e in eventos]
        saida["ocorrido_em_utc"] = [ev.iso(e.ocorrido_em) for e in eventos]
        saida["recebido_em_utc"] = [ev.iso(e.recebido_em) for e in eventos]
        saida["processado_em_utc"] = ev.iso(processado)

    def _processar_transacoes(self, eventos: List[ev.Evento]) -> None:
        if not eventos:
            return
        for e in eventos:
            tx = dict(e.dados, _evento=e)
            r = self.estado.receber(tx)
            if r is not None:
                self._rejeitar(e.id_evento, r.motivo, r.detalhe)
        if self.estado.max_visto is not None:
            self._fechar(self.estado.max_visto - self.config.atraso_permitido_min)

    def _fechar(self, limite: Optional[int]) -> None:
        fechados = self.estado.fechar_ate(limite)
        if fechados:
            self._pontuar(fechados)

    def _pontuar(self, fechados: List[MinutoFechado]) -> None:
        """Pontua de uma vez todos os minutos fechados neste lote.

        Os atributos de cada minuto já foram calculados contra o estado anterior
        a ele; juntar os minutos só evita uma chamada ao modelo por minuto.
        """
        txs = [tx for mf in fechados for tx in mf.transacoes]
        X = pd.concat([mf.X for mf in fechados], ignore_index=True) if len(fechados) > 1 else fechados[0].X
        incompleto = np.concatenate([mf.historico_incompleto for mf in fechados])
        eventos = [tx["_evento"] for tx in txs]
        score, motivos = pontuar_lavagem(self.cab_lav, self.prep, X, pd.Series([tx["formato"] for tx in txs]))
        sinais = self._sinais_para(txs)
        processado = ev.agora()
        saida = pd.DataFrame({
            "arquivo_origem": [e.origem for e in eventos],
            "linha_origem": [e.sequencia for e in eventos],
            "id_transacao": [tx["id_transacao"] for tx in txs],
            "timestamp_transacao": pd.to_datetime([tx["minuto"] for tx in txs], unit="m").strftime("%Y-%m-%d %H:%M:%S"),
            "conta_origem": [tx["conta_origem"] for tx in txs],
            "conta_destino": [tx["conta_destino"] for tx in txs],
            "valor_pago": [tx["valor_pago"] for tx in txs],
            "moeda_pagamento": [tx["moeda_pagamento"] for tx in txs],
            "formato": [tx["formato"] for tx in txs],
            "score_lavagem": score,
            "alerta_lavagem": score >= self.cab_lav.limiar_alerta,
            "limiar_alerta": self.cab_lav.limiar_alerta,
            "motivos_verificaveis": motivos,
            "historico_incompleto": incompleto,
            "sinais_utilizados": "financeiro",
            "cobertura_vinculo": sinais["cobertura_vinculo"].to_numpy(),
            "n_fluxos_vinculados": sinais["n_fluxos_vinculados"].to_numpy(),
            "score_alerta_rede_vinculado": sinais["score_alerta_rede_max"].to_numpy(),
            "idade_sinal_rede_s": sinais["idade_sinal_s_min"].to_numpy(),
            "pontuacao_fraude_financeira": "indisponivel",
            "versao_modelo": self.cab_lav.metadados.get("versao", ""),
            "tipo_saida": "previsao",
        })
        self._anotar(saida, eventos, processado)
        self._guardar("lavagem", saida)
        self.cont["previsoes_lavagem"] += len(saida)
        self.latencias["lavagem"].extend(1000 * (processado - e.recebido_em) for e in eventos)

    def _sinais_para(self, txs: List[Dict[str, Any]]) -> pd.DataFrame:
        if not len(self.vinculos):  # sem nenhum vínculo registrado: mesmo resultado, sem junções
            self.cont["cobertura_sem_vinculo"] += len(txs)
            n = len(txs)
            return pd.DataFrame({"cobertura_vinculo": np.full(n, "sem_vinculo", dtype=object),
                                 "n_fluxos_vinculados": np.zeros(n, dtype=int),
                                 "score_alerta_rede_max": np.full(n, np.nan),
                                 "idade_sinal_s_min": np.full(n, np.nan)})
        transacoes = pd.DataFrame({
            "id_transacao": [tx["id_transacao"] for tx in txs],
            "timestamp_disponivel": pd.to_datetime([tx["timestamp_disponivel"] for tx in txs], unit="s", utc=True),
        })
        chaves = [tx["id_transacao"] for tx in txs]
        if any("chave_tecnica" in tx for tx in txs):
            transacoes["chave_tecnica"] = [tx.get("chave_tecnica", "") for tx in txs]
            chaves += [tx["chave_tecnica"] for tx in txs if tx.get("chave_tecnica")]
        vinc = self.vinculos.tabela(chaves) if len(self.vinculos) else pd.DataFrame()
        if not vinc.empty and "chave_tecnica" not in transacoes and (vinc["tipo_chave"] == "chave_tecnica").any():
            vinc = vinc[vinc["tipo_chave"] != "chave_tecnica"]
        prev = self.sinais.tabela(vinc["id_fluxo"].tolist()) if not vinc.empty else None
        sinais, rel = associar_sinais_rede(transacoes, vinc if not vinc.empty else None, prev,
                                           self.config.tolerancia_sinal_s)
        for k, v in rel.get("cobertura", {}).items():
            self.cont[f"cobertura_{k}"] += v
        return sinais

    # -- persistência ----------------------------------------------------------
    def _arquivo_estado(self) -> Path:
        return self.pasta_estado / f"estado_eventos{self.rotulo}.pkl"

    def salvar_estado(self) -> Optional[Dict[str, Any]]:
        if self.pasta_estado is None:
            return None
        with self.trava:
            inicio = time.perf_counter()
            extra = {
                "vinculos": self.vinculos, "sinais": self.sinais, "ids_rede": self.ids_rede,
                "contadores": dict(self.cont), "rejeitados": dict(self.rejeitados),
                "replay_processado": dict(self.replay_processado),
                "saidas": {k: (str(s.caminho), s.relatorio, s.marca()) for k, s in self.saidas.items()},
                "versoes": self._versoes(), "sequencia": self._sequencia,
            }
            meta = self.estado.salvar(self._arquivo_estado(), extra)
            meta.pop("extra", None)
            meta["segundos"] = round(time.perf_counter() - inicio, 3)
            self._ultimo_salvo = time.monotonic()
            self._sujo = False
            self.cont["instantaneos"] += 1
            self.ultimo_instantaneo = meta
            return meta

    def restaurar(self) -> Optional[Dict[str, Any]]:
        caminho = self._arquivo_estado()
        if not caminho.is_file():
            return None
        try:
            estado, meta = EstadoFinanceiro.carregar(caminho, self.prep)
        except (ValueError, OSError, EOFError, KeyError) as exc:
            return {"restaurado": False, "motivo": f"instantâneo ignorado: {exc}"}
        extra = meta.get("extra", {})
        if extra.get("versoes") != self._versoes():
            return {"restaurado": False, "motivo": "instantâneo de outra versão do modelo; ignorado"}
        with self.trava:
            self.estado = estado
            self.vinculos = extra["vinculos"]
            self.sinais = extra["sinais"]
            self.ids_rede = extra["ids_rede"]
            self.cont = Counter(extra["contadores"])
            self.rejeitados = Counter(extra["rejeitados"])
            self.replay_processado = dict(extra["replay_processado"])
            self._sequencia = int(extra.get("sequencia", 0))
            for chave, (caminho_saida, rel, marca) in extra["saidas"].items():
                s = SaidaCSV(Path(caminho_saida), rel, continuar=True)
                s.voltar_para(tuple(marca))
                self.saidas[chave] = s
        return {"restaurado": True, "salvo_em": meta.get("salvo_em"),
                "ultimo_minuto_fechado": meta.get("ultimo_minuto_fechado"),
                "replay_processado": self.replay_processado}

    def descartar(self) -> Dict[str, Any]:
        """Volta ao estado vazio e apaga o instantâneo e as saídas deste serviço."""
        with self.trava:
            removidos = []
            for s in self.saidas.values():
                for p in (s.caminho, s.caminho.with_suffix(".relatorio.json")):
                    if p.is_file() and p.name.startswith(PREFIXO_SAIDA):
                        p.unlink()
                        removidos.append(p.name)
            if self.pasta_estado is not None and self._arquivo_estado().is_file():
                self._arquivo_estado().unlink()
                removidos.append(self._arquivo_estado().name)
            while True:
                try:
                    self.fila.get_nowait()
                    self.fila.task_done()
                except queue.Empty:
                    break
            self._zerar()
            return {"removidos": removidos}

    def _versoes(self) -> Dict[str, str]:
        return {"estado_rede": self.cab_rede.metadados.get("versao", ""),
                "lavagem": self.cab_lav.metadados.get("versao", "")}

    # -- leitura ---------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        """Resumo para a interface. Não espera mais que 0,2 s pelo trabalhador
        (durante a carga do histórico, devolve o último resumo com ``ocupado``)."""
        with self._trava_ingestao:
            api = {"contadores": dict(self.cont_api), "rejeicoes": list(self.rejeicoes_api)[-20:]}
        if not self.trava.acquire(timeout=0.2):
            return dict(self._ultimo_status, ocupado=True, api=api, fila={
                "pendentes": self.fila.qsize(), "capacidade": self.fila.maxsize})
        try:
            agora = ev.agora()
            modos = [{"modo": m, "rotulo": ev.ROTULO_MODO[m], "ultimo_evento_utc": ev.iso(t),
                      "recente": agora - t < 60} for m, t in sorted(self.modos_vistos.items())]
            self._ultimo_status = {
                "ocupado": False,
                "api": api,
                "trabalhador_ativo": self.ativo(),
                "modos": modos,
                "ultima_atualizacao_utc": ev.iso(self.ultima_atualizacao),
                "fila": {"pendentes": self.fila.qsize(), "capacidade": self.fila.maxsize},
                "contadores": dict(self.cont),
                "rejeitados": dict(self.rejeitados),
                "falhas": list(self.falhas)[-5:],
                "latencia_ms": {k: _percentis(v) for k, v in self.latencias.items()},
                "financeiro": self.estado.cobertura(),
                "vinculos": len(self.vinculos),
                "fluxos_com_sinal": len(self.sinais.por_fluxo),
                "saidas": [{"id": f"app:artefatos_ml/previsoes/{s.caminho.name}", "arquivo": s.caminho.name,
                            "linhas": s.linhas, "dominio": k.split(":")[0], "modo": k.split(":")[1]}
                           for k, s in sorted(self.saidas.items())
                           if s.caminho.parent.name == "previsoes"],
                "versoes": self._versoes(),
                "replay_processado": {k: v + 1 for k, v in self.replay_processado.items()},
                "configuracao": {
                    "capacidade_fila": self.config.capacidade_fila,
                    "atraso_permitido_min": self.config.atraso_permitido_min,
                    "fechar_ocioso_s": self.config.fechar_ocioso_s,
                    "tolerancia_sinal_s": self.config.tolerancia_sinal_s,
                },
                "instantaneo": getattr(self, "ultimo_instantaneo", None),
                "restaurado": self.restaurado,
                "fusao": {
                    "integracao_tecnica": "pronta (vínculos validados e sinais disponíveis no instante da decisão)",
                    "cenario_simulado": "laboratório de simulação disponível",
                    "validacao_preditiva": "pendente: faltam dados reais relacionados",
                    "aviso": AVISO_FUSAO,
                },
            }
            return self._ultimo_status
        finally:
            self.trava.release()


def _percentis(valores: Sequence[float]) -> Dict[str, Any]:
    if not valores:
        return {"n": 0}
    a = np.asarray(valores, dtype=float)
    return {"n": int(a.size), "p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)),
            "p99": float(np.percentile(a, 99)), "max": float(a.max())}
