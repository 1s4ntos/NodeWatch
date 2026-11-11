"""Processamento de eventos: registro durável, fila limitada, um trabalhador e estado persistido.

Camadas (cada uma testável sozinha):

1. **ingestão** — :func:`src.ml.eventos.montar_evento` valida envelope e dados;
   :meth:`ServicoEventos.aceitar` grava o evento no registro durável
   (:mod:`src.ml.registro_eventos`) e só então o põe na fila (limitada; cheia =
   recusa explícita, nunca descarte silencioso);
2. **preparação de atributos** — rede: as medições já chegam em ``rede_v1``;
   financeiro: :class:`src.ml.incremental.EstadoFinanceiro` (estado por conta);
3. **inferência** — cabeças do artefato carregado uma vez por processo
   (nada é reajustado);
4. **persistência** — registro durável de eventos + instantâneo atômico do
   estado; CSVs de saída são projeções reconstruíveis a partir dos dois;
5. **apresentação** — CSVs ``previsao_rede_v1``/``previsao_lavagem_v1`` em
   ``artefatos_ml/previsoes`` (abertos pela seção Machine Learning), CSV de
   recusas e o resumo de :meth:`ServicoEventos.status`.

Política (detalhes em docs/ml/EVENTOS.md, seção 4):

* **aceitação durável** — a API só confirma depois do fsync no registro;
* **identidade** — mesma chave natural e mesmo conteúdo = retransmissão
  (nada é refeito); conteúdo diferente = ``conflito``;
* **lote** — preparação (registro) → aplicação → confirmação (escrita das
  saídas, cursores). Falha: reconstrução a partir do instantâneo e do
  registro até o evento anterior, nova tentativa; depois de ``tentativas``,
  o evento que falha fica **bloqueado** e identificado, sem avançar além dele;
* **minuto financeiro** — fecha por evento posterior (tempo do evento menos o
  atraso permitido), pelo relógio só para eventos novos (fim do minuto +
  atraso + carência), pelo fim do replay ou por comando explícito. Toda
  decisão de fechamento fica gravada no registro, para a reconstrução ser
  idêntica;
* **reinício** — nada é retomado sozinho: :meth:`ServicoEventos.recuperar` é
  uma ação explícita que carrega o instantâneo e reaplica o registro.
"""

from __future__ import annotations

import json
import os
import queue
import tempfile
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
from src.ml.registro_eventos import RegistroDuravel

TOLERANCIA_SINAL_S = 480.0
MAX_RECENTES = 200
MAX_LATENCIAS = 5_000
MAX_IDS_REDE = 200_000
MAX_INDICE = 1_000_000  # identidades lembradas para retransmissão/conflito
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
    # Ociosidade não fecha minutos: só depois desse tempo sem eventos o relógio é
    # consultado, e um minuto de eventos novos só fecha quando o relógio passa do
    # fim dele + atraso permitido + carência.
    fechar_ocioso_s: float = 5.0
    carencia_relogio_s: float = 2.0
    salvar_a_cada_s: float = 120.0
    salvar_a_cada_eventos: int = 100_000
    tolerancia_sinal_s: float = TOLERANCIA_SINAL_S
    lote_maximo: int = 2_000
    tentativas: int = 3


class ErroEstado(RuntimeError):
    """Operação recusada pelo estado do serviço (recuperação pendente, bloqueio)."""


class ServicoEventos:
    """Recebe eventos, mantém o estado e grava previsões. Um trabalhador por processo.

    Ciclo de cada lote: **preparação** (evento gravado no registro durável) →
    **aplicação** (estado, previsões em memória) → **confirmação** (CSVs
    escritos, cursores e ``aplicado_ate`` avançados). Se a aplicação ou a
    escrita falhar, o serviço é reconstruído a partir do último instantâneo e do
    registro até o evento anterior ao lote e o lote é repetido. Depois de
    ``tentativas`` falhas, o processamento fica **bloqueado** com os eventos
    identificados, sem avançar além deles.
    """

    def __init__(self, modelo, pasta_saida: Path, pasta_estado: Optional[Path],
                 config: Optional[Configuracao] = None, rotulo: str = "",
                 relogio: Optional[Callable[[], float]] = None,
                 autorizado: Optional[Callable[[], bool]] = None):
        self.modelo = modelo
        self.config = config or Configuracao()
        self.pasta_saida = Path(pasta_saida)
        self.pasta_estado = Path(pasta_estado) if pasta_estado else Path(tempfile.mkdtemp(prefix="nodewatch_eventos_"))
        self.pasta_estado.mkdir(parents=True, exist_ok=True)
        self.rotulo = rotulo
        self.relogio: Callable[[], float] = relogio or ev.agora
        self.autorizado: Callable[[], bool] = autorizado or (lambda: True)
        self.cab_rede = modelo.cabeca("estado_rede")
        self.cab_lav = modelo.cabeca("lavagem")
        self.prep = modelo.codificadores["financeiro"]
        self.trava = threading.RLock()  # estado, saídas e contadores do trabalhador
        self._trava_ingestao = threading.Lock()  # registro, índice e contadores da API
        self._ultimo_status: Dict[str, Any] = {}
        self.fila: "queue.Queue[ev.Evento]" = queue.Queue(maxsize=self.config.capacidade_fila)
        self._parar = threading.Event()
        self._trabalhador: Optional[threading.Thread] = None
        self._ultimo_evento = 0.0
        self._ultimo_salvo = time.monotonic()
        self._reconstruindo = False
        self.registro = RegistroDuravel(self.pasta_estado / f"registro{rotulo}")
        self._zerar()
        if self._arquivo_estado().is_file() and not self._arquivo_meta().is_file():
            # Instantâneo de antes do registro durável (sem aplicado_ate): não serve de base de
            # recuperação. É preservado com outro nome, sem nunca ser carregado.
            os.replace(self._arquivo_estado(), self._arquivo_estado().with_suffix(".legado.pkl"))
        meta = self._ler_meta()
        if meta:  # depois de podar o registro, a sequência continua de onde o instantâneo parou
            self.registro.ultima_seq = max(self.registro.ultima_seq, int(meta.get("aplicado_ate", 0)))
        self.inspecao = self.inspecionar()
        self.aberto = not self.inspecao["precisa_recuperar"]
        self.restaurado: Optional[Dict[str, Any]] = None

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
        self.cont_operacao: Counter = Counter()  # falhas e instantâneos (sobrevivem às reconstruções)
        self.replay_processado: Dict[str, int] = {}
        self.modos_vistos: Dict[str, float] = {}
        self.ultima_atualizacao: Optional[float] = None
        self._pendentes: Dict[Tuple[str, str], List[pd.DataFrame]] = {}
        self.aplicado_ate = 0
        self.indice: "OrderedDict[str, Tuple[str, int]]" = OrderedDict()
        self.descartados: set = set()
        self.bloqueio: Optional[Dict[str, Any]] = None
        self._desde_salvo = 0
        self._sujo = False

    def eh_conta(self, chave: str) -> bool:
        return chave in self.estado.indice

    def _exigir_aberto(self) -> None:
        if not self.aberto:
            raise ErroEstado("Há estado anterior não recuperado (instantâneo e/ou eventos aceitos no registro). "
                             "Recupere explicitamente antes de processar.")

    # -- ingestão (preparação: registro durável) --------------------------------
    def proxima_sequencia(self) -> int:
        """Compatibilidade: a sequência agora é a do registro, atribuída ao aceitar."""
        return 0

    def aceitar(self, eventos: Sequence[ev.Evento], sincronizar: bool = True, bloquear: bool = False,
                timeout: Optional[float] = None, enfileirar: bool = True) -> Dict[str, List[Any]]:
        """Grava no registro durável e (opcionalmente) enfileira.

        Identidade: mesma chave natural e mesmo conteúdo = ``duplicado`` (retransmissão,
        nada é gravado de novo); mesma chave com conteúdo diferente = ``conflito``.
        Com ``sincronizar``, só retorna depois do fsync: é a aceitação durável.
        """
        self._exigir_aberto()
        res: Dict[str, List[Any]] = {"aceitos": [], "duplicados": [], "conflitos": [], "fila_cheia": []}
        if bloquear and enfileirar:
            fim = None if timeout is None else time.monotonic() + timeout
            while self.fila.qsize() + len(eventos) > self.fila.maxsize:
                if fim is not None and time.monotonic() > fim:
                    res["fila_cheia"] = list(eventos)
                    return res
                time.sleep(0.005)
        with self._trava_ingestao:
            novos: List[ev.Evento] = []
            no_lote: Dict[str, str] = {}
            for e in eventos:
                if e.tipo == "controle":
                    novos.append(e)
                    continue
                h = e.conteudo_hash()
                anterior = self.indice.get(e.chave_natural)
                h_ant = anterior[0] if anterior else no_lote.get(e.chave_natural)
                if h_ant is None:
                    no_lote[e.chave_natural] = h
                    novos.append(e)
                elif h_ant == h:
                    res["duplicados"].append((e, anterior[1] if anterior else None))
                else:
                    res["conflitos"].append(e)
            if enfileirar and not bloquear:
                livre = self.fila.maxsize - self.fila.qsize()
                if len(novos) > livre:
                    res["fila_cheia"] = novos[livre:]
                    novos = novos[:livre]
            if novos:
                seqs = self.registro.anexar([e.para_registro() for e in novos], sincronizar)
                for e, s in zip(novos, seqs):
                    e.sequencia = s
                    if e.tipo != "controle":
                        self.indice[e.chave_natural] = (e.conteudo_hash(), s)
                while len(self.indice) > MAX_INDICE:
                    self.indice.popitem(last=False)
                if enfileirar:
                    for e in novos:
                        self.fila.put_nowait(e)
            res["aceitos"] = novos
        return res

    def submeter(self, brutos: Sequence[Any], origem: str = "api", modo: str = "novo_evento"
                 ) -> Dict[str, Any]:
        """Valida e aceita eventos da API. Nunca bloqueia: fila cheia = recusa.

        Um evento em ``aceitos`` já está no registro durável (fsync): não some se o
        processo cair antes do próximo instantâneo.
        """
        recebido = ev.agora()
        recusados: List[Dict[str, Any]] = []
        validos: List[ev.Evento] = []
        for i, b in enumerate(brutos):
            try:
                validos.append(ev.montar_evento(b, recebido, origem, modo, self.eh_conta))
            except ev.ErroEvento as exc:
                recusados.append({"posicao": i, "id_evento": exc.id_evento, "motivo": "invalido",
                                  "problemas": exc.problemas})
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
        r = self.aceitar(validos, sincronizar=True)
        for e in r["conflitos"]:
            recusados.append({"posicao": None, "id_evento": e.id_evento, "motivo": "conflito",
                              "problemas": ["a mesma identidade já foi aceita com conteúdo diferente"]})
        for e in r["fila_cheia"]:
            recusados.append({"posicao": None, "id_evento": e.id_evento, "motivo": "fila_cheia",
                              "problemas": [f"fila com {self.fila.maxsize} eventos pendentes; tente de novo"]})
        ja = [{"id_evento": e.id_evento, "seq": s} for e, s in r["duplicados"]]
        with self._trava_ingestao:
            self.cont_api["recebidos"] += len(brutos)
            self.cont_api["aceitos_duraveis"] += len(r["aceitos"])
            self.cont_api["retransmissoes"] += len(ja)
            for x in recusados:
                self.cont_api[f"recusados_{x['motivo']}"] += 1
                self.rejeicoes_api.append(dict(x, em=ev.iso(recebido)))
        return {"aceitos": len(r["aceitos"]), "ids_aceitos": [{"id_evento": e.id_evento, "seq": e.sequencia}
                                                             for e in r["aceitos"]][:1000],
                "ja_aceitos": ja[:1000], "recusados": recusados, "pendentes_na_fila": self.fila.qsize(),
                "aceitacao": "durável: gravado e sincronizado no registro antes desta resposta"}

    def enfileirar(self, e: ev.Evento, timeout: Optional[float] = None) -> None:
        """Para produtores internos (replay): espera vaga na fila. Retransmissão é ignorada."""
        self.enfileirar_varios([e], timeout)

    def enfileirar_varios(self, eventos: Sequence[ev.Evento], timeout: Optional[float] = None) -> None:
        r = self.aceitar(eventos, sincronizar=False, bloquear=True, timeout=timeout)
        if r["fila_cheia"]:
            raise queue.Full
        if r["conflitos"]:
            raise ErroEstado(f"identidade repetida com conteúdo diferente: {r['conflitos'][0].id_evento}")

    # -- trabalhador -------------------------------------------------------------
    def iniciar(self) -> None:
        self._exigir_aberto()
        if self._trabalhador and self._trabalhador.is_alive():
            return
        self._parar.clear()
        self._trabalhador = threading.Thread(target=self._laco, name="nodewatch-eventos", daemon=True)
        self._trabalhador.start()

    def parar(self, salvar: bool = True, timeout: float = 30.0) -> None:
        self._parar.set()
        if self._trabalhador:
            self._trabalhador.join(timeout)
        if salvar and self.aberto:
            self.salvar_estado()

    def ativo(self) -> bool:
        return bool(self._trabalhador and self._trabalhador.is_alive())

    def _laco(self) -> None:
        while not self._parar.is_set():
            if self.bloqueio or not self.autorizado():
                time.sleep(0.25)  # pausado: os eventos aceitos esperam no registro e na fila
                continue
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

    def _limite_pelo_relogio(self) -> Optional[int]:
        """Até que minuto (exclusivo) o relógio permite fechar.

        Só minutos com eventos ``novo_evento``: replay e simulação têm o próprio
        tempo e só fecham por evento posterior, fim do replay ou comando.
        """
        agora = self.relogio()
        limite = None
        for m in sorted(self.estado.aberto):
            if {tx["_evento"].modo for tx in self.estado.aberto[m]} != {"novo_evento"}:
                break
            fim_seguro = (m + 1 + self.config.atraso_permitido_min) * 60 + self.config.carencia_relogio_s
            if agora < fim_seguro:
                break
            limite = m + 1
        return limite

    def _ocioso(self) -> None:
        with self.trava:
            if not self.aberto or self.bloqueio or not self.autorizado():
                return
            if self.estado.aberto and time.monotonic() - self._ultimo_evento >= self.config.fechar_ocioso_s:
                limite = self._limite_pelo_relogio()
                if limite is not None:
                    ctrl = ev.controle("fechar_ate", "relogio", "novo_evento", minuto=int(limite))
                    self.aceitar([ctrl], sincronizar=True, enfileirar=False)
                    self._aplicar_com_tentativas([ctrl])
            salvar = (time.monotonic() - self._ultimo_salvo >= self.config.salvar_a_cada_s
                      or self._desde_salvo >= self.config.salvar_a_cada_eventos)
            if self._sujo and salvar:
                self.salvar_estado()

    def fechar_minutos(self, origem: str = "comando", modo: str = "novo_evento") -> Dict[str, Any]:
        """Fechamento forçado (comando explícito): grava o comando e fecha todos os minutos abertos."""
        with self.trava:
            abertos = self.estado.minutos_abertos()
            ctrl = ev.controle("fechar", origem, modo)
            self.aceitar([ctrl], sincronizar=True, enfileirar=False)
            ok = self._aplicar_com_tentativas([ctrl])
            return {"ok": ok, "minutos_fechados": len(abertos),
                    "efeito": "transações desses minutos que chegarem depois serão recusadas como atrasadas"}

    def esperar_fila_vazia(self, timeout: float = 60.0) -> bool:
        """True quando a fila esvaziou. False no prazo ou se o trabalhador não vai consumi-la
        (sessão inativa ou bloqueio): os eventos aceitos seguem no registro."""
        fim = time.monotonic() + timeout
        while time.monotonic() < fim:
            if self.fila.unfinished_tasks == 0:
                return True
            if self.bloqueio or not self.autorizado() or not self.ativo():
                return False
            time.sleep(0.01)
        return False

    # -- processamento (aplicação e confirmação) ---------------------------------
    def processar(self, lote: List[ev.Evento], da_fila: bool = True) -> bool:
        """Aplica um lote. Eventos que ainda não estão no registro (laboratório, testes)
        são gravados nele primeiro. Devolve False se o lote ficou bloqueado."""
        n_fila = len(lote)
        try:
            with self.trava:
                self._exigir_aberto()
                if self.bloqueio:
                    raise ErroEstado("Processamento bloqueado por falha; repita ou descarte os eventos bloqueados.")
                fora = [e for e in lote if not e.sequencia]
                if fora:
                    r = self.aceitar(fora, sincronizar=True, enfileirar=False)
                    for e, _ in r["duplicados"]:
                        self._rejeitar(e, "duplicada", "mesma identidade e conteúdo já aceitos")
                    for e in r["conflitos"]:
                        self._rejeitar(e, "conflito", "mesma identidade já aceita com conteúdo diferente")
                    if r["duplicados"] or r["conflitos"]:
                        self._escrever_pendentes()
                    lote = [e for e in lote if e.sequencia]
                if not lote:
                    return True
                self._ultimo_evento = time.monotonic()
                return self._aplicar_com_tentativas(lote)
        finally:
            if da_fila:
                for _ in range(n_fila):
                    self.fila.task_done()

    def _aplicar_com_tentativas(self, lote: List[ev.Evento], isolar: bool = True) -> bool:
        erro: Optional[BaseException] = None
        for tentativa in range(1, self.config.tentativas + 1):
            try:
                self._aplicar(lote)
                return True
            except Exception as exc:  # falha no meio: desfaz reconstruindo e tenta de novo
                erro = exc
                self._registrar_falha(lote, exc, tentativa)
                try:
                    self._reconstruir(ate=min(e.sequencia for e in lote) - 1)
                except Exception as exc2:
                    self._bloquear(lote, [], exc2)
                    return False
        if isolar and len(lote) > 1:
            # Aplicar um a um, na mesma ordem, dá o mesmo resultado: isola o evento que falha
            # e confirma os anteriores a ele.
            for i, e in enumerate(lote):
                if not self._aplicar_com_tentativas([e], isolar=False):
                    self.bloqueio["restantes"] = lote[i + 1:]
                    return False
            return True
        self._bloquear(lote, [], erro)
        return False

    def _registrar_falha(self, lote: List[ev.Evento], exc: BaseException, tentativa: int) -> None:
        self.cont_operacao["falhas"] += 1
        self.falhas.append({"em": ev.iso(ev.agora()), "tentativa": tentativa, "eventos": len(lote),
                            "seqs": [lote[0].sequencia, lote[-1].sequencia],
                            "erro": f"{type(exc).__name__}: {exc}"})

    def _bloquear(self, falhos: List[ev.Evento], restantes: List[ev.Evento], exc: Optional[BaseException]) -> None:
        self.bloqueio = {
            "em": ev.iso(ev.agora()), "erro": f"{type(exc).__name__}: {exc}" if exc else "",
            "seqs": [e.sequencia for e in falhos], "ids": [e.id_evento for e in falhos][:50],
            "eventos": falhos, "restantes": restantes,
            "leitura": ("Os eventos continuam no registro durável e não foram confirmados; nada depois deles "
                        "foi aplicado. Repita depois de corrigir a causa ou descarte os eventos que falharam "
                        "(o descarte fica gravado no registro). Se a falha vier do fechamento de um minuto "
                        "anterior, descartar o evento que o disparou não resolve."),
        }

    def _situacao_bloqueio(self) -> Optional[Dict[str, Any]]:
        if not self.bloqueio:
            return None
        return {k: v for k, v in self.bloqueio.items() if k not in ("eventos", "restantes")} | {
            "eventos_pendentes_depois": len(self.bloqueio["restantes"])}

    def repetir_bloqueados(self) -> bool:
        with self.trava:
            if not self.bloqueio:
                return True
            lote = self.bloqueio["eventos"] + self.bloqueio["restantes"]
            self.bloqueio = None
            self._reconstruir(ate=min(e.sequencia for e in lote) - 1)
            return self._aplicar_com_tentativas(lote)

    def descartar_bloqueados(self, origem: str = "comando") -> Dict[str, Any]:
        """Descarte explícito dos eventos que falharam: grava um comando no registro e segue."""
        with self.trava:
            if not self.bloqueio:
                return {"descartados": 0}
            falhos, restantes = self.bloqueio["eventos"], self.bloqueio["restantes"]
            self.bloqueio = None
            seqs = [e.sequencia for e in falhos if e.tipo != "controle"]
            ctrl = ev.controle("descartar", origem, "novo_evento", seqs=seqs)
            self.aceitar([ctrl], sincronizar=True, enfileirar=False)
            self.descartados.update(seqs)
            self._reconstruir(ate=min(e.sequencia for e in falhos) - 1)
            ok = self._aplicar_com_tentativas(falhos + restantes + [ctrl])
            return {"descartados": len(seqs), "ok": ok}

    def _aplicar(self, lote: List[ev.Evento]) -> None:
        """Aplica e confirma. Rede e vínculos antes das transações de cada lote."""
        self._pendentes = {}
        lote = [e for e in lote if e.sequencia > self.aplicado_ate]  # já aplicados: nada a fazer
        if not lote:
            return
        por_tipo: Dict[str, List[ev.Evento]] = {"medicao_rede": [], "vinculo": [], "transacao": [], "controle": []}
        for e in lote:
            if e.sequencia in self.descartados:
                self._rejeitar(e, "descartado", "descartado explicitamente depois de falhas repetidas")
                continue
            por_tipo[e.tipo].append(e)
            if e.tipo != "controle" and e.modo in ev.MODOS and not self._reconstruindo:
                self.modos_vistos[e.modo] = ev.agora()
        self._processar_rede(por_tipo["medicao_rede"])
        for e in por_tipo["vinculo"]:
            if self.vinculos.adicionar(e.dados):
                self.cont["vinculos"] += 1
            else:
                self._rejeitar(e, "duplicada", "vínculo já registrado")
        self._processar_transacoes(por_tipo["transacao"])
        for e in por_tipo["controle"]:
            acao = e.dados.get("acao")
            if acao == "fechar":
                self._fechar(None)
            elif acao == "fechar_ate":
                self._fechar(int(e.dados["minuto"]))
            elif acao == "descartar":
                self.descartados.update(e.dados.get("seqs", []))
        self._escrever_pendentes()  # confirmação: só depois da escrita os cursores avançam
        for e in lote:
            r = e.controle.get("replay")
            if r:
                self.replay_processado[r] = e.controle["posicao"]
        self.aplicado_ate = max(e.sequencia for e in lote)
        self.ultima_atualizacao = ev.agora()
        self._sujo = True
        self._desde_salvo += len(lote)

    def _guardar(self, dominio: str, saida: pd.DataFrame) -> None:
        for modo, parte in saida.groupby("modo_evento", sort=True):
            self._pendentes.setdefault((dominio, modo), []).append(parte)
        if not self._reconstruindo and dominio in self.recentes:
            self.recentes[dominio].extend(saida.tail(MAX_RECENTES).to_dict("records"))

    def _escrever_pendentes(self) -> None:
        """Uma escrita por arquivo e por lote (não por minuto)."""
        for (dominio, modo), partes in sorted(self._pendentes.items()):
            self._saida(dominio, modo).anexar(pd.concat(partes, ignore_index=True))
        self._pendentes = {}

    def _rejeitar(self, e: ev.Evento, motivo: str, detalhe: str) -> None:
        self.rejeitados[motivo] += 1
        linha = {"seq": e.sequencia, "id_evento": e.id_evento, "tipo": e.tipo, "origem_evento": e.origem,
                 "modo_evento": e.modo, "motivo": motivo, "detalhe": detalhe,
                 "recebido_em_utc": ev.iso(e.recebido_em)}
        self._pendentes.setdefault(("recusas", e.modo if e.modo in ev.MODOS else "novo_evento"), []).append(
            pd.DataFrame([linha]))
        if not self._reconstruindo:
            self.recentes["rejeicoes"].append({"id_evento": e.id_evento, "motivo": motivo, "problemas": [detalhe],
                                               "em": ev.iso(ev.agora())})

    def _nome_saida(self, dominio: str, modo: str) -> str:
        return f"{PREFIXO_SAIDA}{modo}{self.rotulo}_{dominio}.csv"

    def _saida(self, dominio: str, modo: str) -> SaidaCSV:
        chave = f"{dominio}:{modo}"
        if chave not in self.saidas:
            rel = {"tarefa": {"rede": "estado_rede", "lavagem": "lavagem"}.get(dominio, dominio),
                   "gerado_por": "processamento de eventos (src/ml/servico_eventos.py)",
                   "modo": modo, "modo_rotulo": ev.ROTULO_MODO.get(modo, modo),
                   "projecao": "reconstruível a partir do instantâneo e do registro durável de eventos",
                   "aviso": AVISO_LAVAGEM if dominio == "lavagem" else
                   "Previsão do estado da próxima medição; não é fraude." if dominio == "rede" else
                   "Eventos aceitos que não geraram previsão, com o motivo."}
            self.saidas[chave] = SaidaCSV(self.pasta_saida / self._nome_saida(dominio, modo), rel)
        return self.saidas[chave]

    def _processar_rede(self, eventos: List[ev.Evento]) -> None:
        novos = []
        for e in eventos:
            if e.chave_natural in self.ids_rede:
                self._rejeitar(e, "duplicada", "medição já recebida (id_fluxo + timestamp)")
                continue
            novos.append(e)
        if not novos:
            return
        df = pd.DataFrame([e.dados for e in novos])
        df.insert(0, "linha_origem", [e.sequencia for e in novos])
        df.insert(0, "arquivo_origem", [e.origem for e in novos])
        saida, _ = tabela_previsoes_rede(self.cab_rede, df)
        processado = ev.agora()
        self._anotar(saida, novos, processado)
        for e in novos:  # só depois de prever: uma falha não deixa a medição marcada como vista
            self.ids_rede[e.chave_natural] = None
        while len(self.ids_rede) > MAX_IDS_REDE:
            self.ids_rede.popitem(last=False)
        self.sinais.adicionar(saida)
        self._guardar("rede", saida)
        self.cont["previsoes_rede"] += len(saida)
        if not self._reconstruindo:
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
                self._rejeitar(e, r.motivo, r.detalhe)
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
        if not self._reconstruindo:
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

    def _arquivo_meta(self) -> Path:
        return self.pasta_estado / f"estado_eventos{self.rotulo}.meta.json"

    def _ler_meta(self) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(self._arquivo_meta().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def inspecionar(self) -> Dict[str, Any]:
        """O que existe para recuperar, sem carregar o estado (barato; não processa nada)."""
        meta = self._ler_meta() if self._arquivo_estado().is_file() else None
        base = int(meta.get("aplicado_ate", 0)) if meta else 0
        pendentes = self.registro.contar_depois(base)
        return {"instantaneo": meta, "eventos_aceitos_nao_aplicados": pendentes,
                "precisa_recuperar": bool(meta) or pendentes > 0}

    def salvar_estado(self) -> Optional[Dict[str, Any]]:
        """Instantâneo atômico. Uma falha aqui não altera estado nem registro (o anterior continua válido)."""
        with self.trava:
            if not self.aberto:
                return None
            inicio = time.perf_counter()
            with self._trava_ingestao:
                indice = OrderedDict(self.indice)
            extra = {
                "vinculos": self.vinculos, "sinais": self.sinais, "ids_rede": self.ids_rede,
                "contadores": dict(self.cont), "rejeitados": dict(self.rejeitados),
                "replay_processado": dict(self.replay_processado),
                "saidas": {k: (str(s.caminho), s.relatorio, s.marca()) for k, s in self.saidas.items()},
                "versoes": self._versoes(), "aplicado_ate": self.aplicado_ate, "indice": indice,
                "descartados": set(self.descartados),
            }
            try:
                self.registro.sincronizar()
                meta = self.estado.salvar(self._arquivo_estado(), extra)
            except Exception as exc:
                self.cont_operacao["falhas_instantaneo"] += 1
                self.falhas.append({"em": ev.iso(ev.agora()), "etapa": "instantaneo",
                                    "erro": f"{type(exc).__name__}: {exc}"})
                return None
            meta.pop("extra", None)
            meta.update(aplicado_ate=self.aplicado_ate, versoes=self._versoes(),
                        replay_processado={k: v + 1 for k, v in self.replay_processado.items()},
                        segundos=round(time.perf_counter() - inicio, 3))
            tmp = self._arquivo_meta().with_suffix(".tmp")
            tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self._arquivo_meta())
            try:  # inofensivo se falhar: a recuperação ignora o que o instantâneo já cobre
                self.registro.podar(self.aplicado_ate)
            except OSError as exc:
                self.falhas.append({"em": ev.iso(ev.agora()), "etapa": "poda do registro",
                                    "erro": f"{type(exc).__name__}: {exc}"})
            self._ultimo_salvo = time.monotonic()
            self._sujo = False
            self._desde_salvo = 0
            self.cont_operacao["instantaneos"] += 1
            self.ultimo_instantaneo = meta
            return meta

    def _carregar_instantaneo(self) -> Optional[Dict[str, Any]]:
        """Volta ao último instantâneo (ou ao vazio) e devolve as saídas ao tamanho dele."""
        guardar = {k: getattr(self, k) for k in ("cont_api", "rejeicoes_api", "falhas", "cont_operacao",
                                                 "latencias", "recentes", "modos_vistos")}
        meta = None
        self._zerar()
        for k, v in guardar.items():
            setattr(self, k, v)
        if self._arquivo_estado().is_file():
            try:
                estado, meta = EstadoFinanceiro.carregar(self._arquivo_estado(), self.prep)
            except (ValueError, OSError, EOFError, KeyError) as exc:
                raise ErroEstado(f"instantâneo ilegível ou incompatível: {exc}") from exc
            extra = meta.get("extra", {})
            if extra.get("versoes") != self._versoes():
                raise ErroEstado("instantâneo de outra versão do modelo; descarte o estado para recomeçar")
            self.estado = estado
            self.vinculos, self.sinais, self.ids_rede = extra["vinculos"], extra["sinais"], extra["ids_rede"]
            self.cont = Counter(extra["contadores"])
            self.rejeitados = Counter(extra["rejeitados"])
            self.replay_processado = dict(extra["replay_processado"])
            self.aplicado_ate = int(extra.get("aplicado_ate", 0))
            self.indice = OrderedDict(extra.get("indice", {}))
            self.descartados = set(extra.get("descartados", set()))
            for chave, (caminho_saida, rel, marca) in extra["saidas"].items():
                s = SaidaCSV(Path(caminho_saida), rel, continuar=True)
                s.voltar_para(tuple(marca))
                self.saidas[chave] = s
        # saídas criadas depois do instantâneo são refeitas a partir do registro
        conhecidas = {s.caminho.name for s in self.saidas.values()}
        for modo in ev.MODOS:
            for dominio in ("rede", "lavagem", "recusas"):
                p = self.pasta_saida / self._nome_saida(dominio, modo)
                if p.name not in conhecidas and p.is_file():
                    p.unlink()
                    p.with_suffix(".relatorio.json").unlink(missing_ok=True)
        # o índice de identidades cobre também o que foi aceito depois do instantâneo
        for r in self.registro.ler_depois(self.aplicado_ate):
            if r.get("tipo") == "controle":
                if (r.get("dados") or {}).get("acao") == "descartar":
                    self.descartados.update(r["dados"].get("seqs", []))
                continue
            self.indice[r["chave_natural"]] = (r["hash"], r["seq"])
        return meta

    def _reconstruir(self, ate: int) -> int:
        """Estado e saídas exatamente como depois do evento ``ate``: instantâneo + registro."""
        self._carregar_instantaneo()
        lote: List[ev.Evento] = []
        n = 0
        self._reconstruindo = True
        try:
            for r in self.registro.ler_depois(self.aplicado_ate):
                if r["seq"] > ate:
                    break
                lote.append(ev.Evento.de_registro(r))
                if len(lote) >= self.config.lote_maximo:
                    self._aplicar(lote)
                    n += len(lote)
                    lote = []
            if lote:
                self._aplicar(lote)
                n += len(lote)
        finally:
            self._reconstruindo = False
        return n

    def recuperar(self) -> Dict[str, Any]:
        """Ação explícita: carrega o instantâneo e reaplica os eventos aceitos depois dele.

        Nunca é chamada sozinha (abrir a interface ou consultar o status não recupera
        nada). Reaplicar não duplica: as saídas voltam ao tamanho do instantâneo antes.
        """
        with self.trava:
            inicio = time.perf_counter()
            self.aberto = True
            meta = self._carregar_instantaneo()
            pendentes = [ev.Evento.de_registro(r) for r in self.registro.ler_depois(self.aplicado_ate)]
            ok = True
            self._reconstruindo = True
            try:
                for i in range(0, len(pendentes), self.config.lote_maximo):
                    if not self._aplicar_com_tentativas(pendentes[i:i + self.config.lote_maximo]):
                        resto = pendentes[i + self.config.lote_maximo:]
                        self.bloqueio["restantes"] = self.bloqueio["restantes"] + resto
                        ok = False
                        break
            finally:
                self._reconstruindo = False
            self.inspecao = {"instantaneo": None, "eventos_aceitos_nao_aplicados": 0, "precisa_recuperar": False}
            self.restaurado = {
                "restaurado": True, "instantaneo": bool(meta),
                "salvo_em": (meta or {}).get("salvo_em"), "eventos_reaplicados": len(pendentes),
                "ok": ok, "segundos": round(time.perf_counter() - inicio, 3),
                "replay_processado": {k: v + 1 for k, v in self.replay_processado.items()},
            }
            if ok and pendentes:
                self.salvar_estado()
            return self.restaurado

    def descartar(self) -> Dict[str, Any]:
        """Volta ao estado vazio e apaga instantâneo, registro e saídas deste serviço."""
        with self.trava:
            removidos = []
            nomes = {s.caminho.name for s in self.saidas.values()} | {
                self._nome_saida(d, m) for m in ev.MODOS for d in ("rede", "lavagem", "recusas")}
            for nome in sorted(nomes):
                for p in (self.pasta_saida / nome, (self.pasta_saida / nome).with_suffix(".relatorio.json")):
                    if p.is_file() and p.name.startswith(PREFIXO_SAIDA):
                        p.unlink()
                        removidos.append(p.name)
            for p in (self._arquivo_estado(), self._arquivo_meta()):
                if p.is_file():
                    p.unlink()
                    removidos.append(p.name)
            self.registro.apagar_tudo()
            while True:
                try:
                    self.fila.get_nowait()
                    self.fila.task_done()
                except queue.Empty:
                    break
            self._zerar()
            self.aberto = True
            self.inspecao = self.inspecionar()
            return {"removidos": removidos}

    def _versoes(self) -> Dict[str, str]:
        return {"estado_rede": self.cab_rede.metadados.get("versao", ""),
                "lavagem": self.cab_lav.metadados.get("versao", "")}

    def consultar(self, chave_natural: str) -> Dict[str, Any]:
        """Situação de um evento pela identidade: pendente, aplicado, descartado ou bloqueado."""
        with self._trava_ingestao:
            item = self.indice.get(chave_natural)
        if item is None:
            return {"chave_natural": chave_natural, "situacao": "desconhecido"}
        seq = item[1]
        bloqueados = {e.sequencia for e in (self.bloqueio or {}).get("eventos", [])}
        situacao = ("bloqueado" if seq in bloqueados else "descartado" if seq in self.descartados
                    else "aplicado" if seq <= self.aplicado_ate else "aceito_pendente")
        return {"chave_natural": chave_natural, "seq": seq, "situacao": situacao,
                "leitura": "aplicado = o evento entrou no estado (previsão gravada ou recusa registrada, "
                           "ou transação num minuto ainda aberto)"}

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
                "aberto": self.aberto,
                "recuperacao": self.inspecao,
                "bloqueio": self._situacao_bloqueio(),
                "autorizado": self.autorizado(),
                "api": api,
                "trabalhador_ativo": self.ativo(),
                "modos": modos,
                "ultima_atualizacao_utc": ev.iso(self.ultima_atualizacao),
                "fila": {"pendentes": self.fila.qsize(), "capacidade": self.fila.maxsize},
                "registro": {"ultima_seq": self.registro.ultima_seq, "aplicado_ate": self.aplicado_ate},
                "contadores": dict(self.cont) | dict(self.cont_operacao),
                "rejeitados": dict(self.rejeitados),
                "falhas": list(self.falhas)[-5:],
                "latencia_ms": {k: _percentis(v) for k, v in self.latencias.items()},
                "financeiro": self.estado.cobertura(),
                "vinculos": len(self.vinculos),
                "fluxos_com_sinal": len(self.sinais.por_fluxo),
                "saidas": [{"id": f"app:artefatos_ml/previsoes/{s.caminho.name}", "arquivo": s.caminho.name,
                            "linhas": s.linhas, "dominio": k.split(":")[0], "modo": k.split(":")[1]}
                           for k, s in sorted(self.saidas.items())
                           if s.caminho.parent.name == "previsoes" and not k.startswith("recusas:")],
                "versoes": self._versoes(),
                "replay_processado": {k: v + 1 for k, v in self.replay_processado.items()},
                "configuracao": {
                    "capacidade_fila": self.config.capacidade_fila,
                    "atraso_permitido_min": self.config.atraso_permitido_min,
                    "fechar_ocioso_s": self.config.fechar_ocioso_s,
                    "carencia_relogio_s": self.config.carencia_relogio_s,
                    "tolerancia_sinal_s": self.config.tolerancia_sinal_s,
                    "tentativas": self.config.tentativas,
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
