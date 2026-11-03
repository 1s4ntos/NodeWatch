"""Atributos financeiros incrementais (estado por conta, sem reconstruir o histórico).

Calcula, transação a transação, os mesmos 49 atributos de
:func:`src.ml.preparacao.atributos_financeiros`, mas a partir de um estado
mantido em memória, em vez de reler e reindexar o histórico inteiro a cada
transação nova. O :class:`~src.ml.preparacao.PreparadorFinanceiro` salvo no
artefato é usado como está (câmbio, formatos, moedas e colunas); nada é
reajustado.

Semântica (igual à do cálculo em lote):

* janelas ``[t - w, t)``, em minutos inteiros; transações do mesmo minuto não
  se enxergam;
* cada minuto é **fechado** de uma vez: todas as transações dele são
  pontuadas contra o estado anterior e só depois incorporadas;
* um minuto fechado não reabre. Transação de minuto já fechado é
  rejeitada como ``atrasada`` (ou ``duplicada``, se o id já foi visto) e não
  entra no estado: incorporá-la mudaria atributos já emitidos.

Estado mantido (por conta ``banco-conta``):

* envios: total, contagens em 6/24/72 h, soma em USD em 24 h, soma e soma dos
  quadrados do log-valor (deslocado pelo primeiro envio da conta) e minuto
  do último envio;
* recebimentos: contagens em 24/72 h, soma em USD em 24 h e minuto do último
  recebimento;
* pares origem→destino já vistos (com contagem) e contrapartes distintas.

As janelas usam um registro de eventos ordenado por minuto, com um cursor por
janela: quando o relógio avança, os eventos que saem da janela são
descontados. As somas em USD usam soma compensada (Neumaier), sem as somas
acumuladas globais do lote.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import tempfile
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from src.ml.preparacao import _SEM_HISTORICO_MIN, _VAR_MIN_Z, PreparadorFinanceiro

VERSAO_ESTADO = "estado_financeiro_v1"
JANELAS_ENVIO = (6 * 60, 24 * 60, 72 * 60)
JANELAS_RECEBIMENTO = (24 * 60, 72 * 60)
JANELA_SOMA = 24 * 60
MAX_IDS_RECENTES = 500_000  # só para classificar rejeições como duplicada ou atrasada
_PAR = 1 << 32


def assinatura_preparador(prep: PreparadorFinanceiro) -> str:
    """Hash dos parâmetros que definem os atributos (o estado depende deles)."""
    dados = {"cambio": prep.cambio, "formatos": prep.formatos, "moedas": prep.moedas,
             "colunas": prep.colunas}
    return hashlib.sha256(json.dumps(dados, sort_keys=True).encode()).hexdigest()[:16]


@dataclass
class Rejeicao:
    id_transacao: str
    motivo: str  # duplicada | atrasada | invalida
    detalhe: str
    minuto: Optional[int] = None


@dataclass
class MinutoFechado:
    """Atributos de todas as transações de um minuto, na ordem de chegada."""

    minuto: int
    X: pd.DataFrame
    transacoes: List[Dict[str, Any]]
    historico_incompleto: np.ndarray


class _Registro:
    """Eventos (minuto, conta, valor) em ordem de minuto, com um cursor por janela."""

    def __init__(self, janelas: Sequence[int]):
        self.m = np.empty(1024, dtype=np.int64)
        self.c = np.empty(1024, dtype=np.int64)
        self.v = np.empty(1024, dtype=np.float64)
        self.n = 0
        self.cursor = {w: 0 for w in janelas}

    def anexar(self, m: np.ndarray, c: np.ndarray, v: np.ndarray) -> None:
        k = len(m)
        if self.n + k > len(self.m):
            cap = max(2 * len(self.m), self.n + k)
            for nome in ("m", "c", "v"):
                antigo = getattr(self, nome)
                novo = np.empty(cap, dtype=antigo.dtype)
                novo[:self.n] = antigo[:self.n]
                setattr(self, nome, novo)
        self.m[self.n:self.n + k] = m
        self.c[self.n:self.n + k] = c
        self.v[self.n:self.n + k] = v
        self.n += k

    def sair(self, w: int, limite: int) -> Tuple[np.ndarray, np.ndarray]:
        """Avança o cursor de ``w`` até o primeiro evento com minuto >= ``limite``."""
        ini = self.cursor[w]
        fim = ini + int(np.searchsorted(self.m[ini:self.n], limite, side="left"))
        self.cursor[w] = fim
        return self.c[ini:fim], self.v[ini:fim]

    def compactar(self) -> None:
        corte = min(self.cursor.values())
        if corte < 65_536 or corte < self.n // 2:
            return
        resto = self.n - corte
        for nome in ("m", "c", "v"):
            arr = getattr(self, nome)
            arr[:resto] = arr[corte:self.n]
        self.n = resto
        self.cursor = {w: p - corte for w, p in self.cursor.items()}

    def ativos(self) -> int:
        return self.n - min(self.cursor.values())


_INT = ("env_tot", "env_n360", "env_n1440", "env_n4320", "rec_n1440", "rec_n4320", "n_dest", "n_orig")
_FLOAT = ("env_s24", "env_c24", "rec_s24", "rec_c24", "env_s1", "env_s2")
_NAN = ("env_ref", "ult_env", "ult_rec")


class EstadoFinanceiro:
    """Estado por conta e a lógica de fechar minutos (sem fila, sem modelo)."""

    def __init__(self, prep: PreparadorFinanceiro):
        self.prep = prep
        self.assinatura = assinatura_preparador(prep)
        self.indice: Dict[str, int] = {}
        self.nomes: List[str] = []
        self.cap = 0
        self.a: Dict[str, np.ndarray] = {}
        self._crescer(1024)
        self.pares: Dict[int, int] = {}
        self.env = _Registro(JANELAS_ENVIO)
        self.rec = _Registro(JANELAS_RECEBIMENTO)
        self.ultimo_fechado: Optional[int] = None  # último minuto incorporado
        self.inicio_observacao: Optional[int] = None  # primeiro minuto do estado
        self.transacoes_incorporadas = 0
        self.carga_inicial: Optional[Dict[str, Any]] = None
        self.aberto: Dict[int, List[Dict[str, Any]]] = {}  # minutos ainda não fechados
        self.ids_abertos: set = set()
        self.ids_recentes: "OrderedDict[str, None]" = OrderedDict()
        self.max_visto: Optional[int] = None

    # -- contas ------------------------------------------------------------
    def _crescer(self, cap: int) -> None:
        for nome in _INT:
            self.a[nome] = _estender(self.a.get(nome), cap, np.int64, 0)
        for nome in _FLOAT:
            self.a[nome] = _estender(self.a.get(nome), cap, np.float64, 0.0)
        for nome in _NAN:
            self.a[nome] = _estender(self.a.get(nome), cap, np.float64, np.nan)
        self.cap = cap

    def codigo(self, nome: str) -> int:
        c = self.indice.get(nome)
        if c is None:
            c = len(self.nomes)
            self.indice[nome] = c
            self.nomes.append(nome)
            if c >= self.cap:
                self._crescer(2 * self.cap)
        return c

    # -- recepção e fechamento -----------------------------------------------
    def receber(self, tx: Dict[str, Any]) -> Optional[Rejeicao]:
        """Coloca uma transação normalizada no minuto aberto dela.

        ``tx`` vem de :func:`src.ml.eventos.normalizar_transacao`.
        """
        ident, m = tx["id_transacao"], tx["minuto"]
        if ident in self.ids_abertos or ident in self.ids_recentes:
            return Rejeicao(ident, "duplicada", "id_transacao já recebido", m)
        if self.ultimo_fechado is not None and m <= self.ultimo_fechado:
            return Rejeicao(ident, "atrasada",
                            f"minuto {m} já fechado (último fechado: {self.ultimo_fechado}); "
                            "não entra no estado nem é pontuada", m)
        self.aberto.setdefault(m, []).append(tx)
        self.ids_abertos.add(ident)
        self.max_visto = m if self.max_visto is None else max(self.max_visto, m)
        return None

    def minutos_abertos(self) -> List[int]:
        return sorted(self.aberto)

    def pendentes(self) -> int:
        return sum(len(v) for v in self.aberto.values())

    def fechar_ate(self, limite: Optional[int]) -> List[MinutoFechado]:
        """Fecha, em ordem, os minutos abertos ``< limite`` (todos, se ``None``)."""
        saida = []
        for m in sorted(self.aberto):
            if limite is not None and m >= limite:
                break
            grupo = self.aberto.pop(m)
            saida.append(self._fechar(m, grupo))
            for tx in grupo:
                self.ids_abertos.discard(tx["id_transacao"])
                self.ids_recentes[tx["id_transacao"]] = None
            while len(self.ids_recentes) > MAX_IDS_RECENTES:
                self.ids_recentes.popitem(last=False)
        return saida

    def _fechar(self, t: int, grupo: List[Dict[str, Any]]) -> MinutoFechado:
        if self.inicio_observacao is None:
            self.inicio_observacao = t
        self._expirar(t)
        o = np.fromiter((self.codigo(x["conta_origem"]) for x in grupo), dtype=np.int64, count=len(grupo))
        d = np.fromiter((self.codigo(x["conta_destino"]) for x in grupo), dtype=np.int64, count=len(grupo))
        usd = np.array([x["valor_pago"] * self.prep.cambio.get(x["moeda_pagamento"], math.nan)
                        for x in grupo], dtype=np.float64)
        X = self._atributos(t, grupo, o, d, usd)
        self._incorporar(t, o, d, usd)
        self.ultimo_fechado = t
        incompleto = np.full(len(grupo), (t - self.inicio_observacao) < 72 * 60)
        return MinutoFechado(t, X, grupo, incompleto)

    # -- janelas -------------------------------------------------------------
    def _expirar(self, t: int) -> None:
        a = self.a
        for reg, prefixo, janelas, soma, comp in (
            (self.env, "env", JANELAS_ENVIO, "env_s24", "env_c24"),
            (self.rec, "rec", JANELAS_RECEBIMENTO, "rec_s24", "rec_c24"),
        ):
            for w in janelas:
                cod, val = reg.sair(w, t - w)
                if not len(cod):
                    continue
                cont = a[f"{prefixo}_n{w}"]
                np.subtract.at(cont, cod, 1)
                if w == JANELA_SOMA:
                    _somar(a[soma], a[comp], cod, -val)
                    vazias = cod[cont[cod] == 0]
                    a[soma][vazias] = 0.0
                    a[comp][vazias] = 0.0
            reg.compactar()

    # -- atributos (estado ANTES do minuto t) --------------------------------
    def _atributos(self, t: int, grupo: List[Dict[str, Any]], o: np.ndarray, d: np.ndarray,
                   usd: np.ndarray) -> pd.DataFrame:
        a = self.a
        usd_ok = np.isfinite(usd)
        usd0 = np.where(usd_ok, usd, 0.0)
        logv = np.log1p(usd0)
        X: Dict[str, np.ndarray] = {}
        X["log_valor_usd"] = np.where(usd_ok, logv, np.nan)
        X["sem_taxa_cambio"] = (~usd_ok).astype(np.float32)
        X["moeda_diferente"] = np.array([x["moeda_pagamento"] != x["moeda_recebimento"] for x in grupo],
                                        dtype=np.float32)
        X["mesmo_banco"] = np.array([x["banco_origem"] == x["banco_destino"] for x in grupo], dtype=np.float32)
        X["auto_transferencia"] = (o == d).astype(np.float32)

        for w in JANELAS_ENVIO:
            X[f"n_env_origem_{w // 60}h"] = a[f"env_n{w}"][o].astype(np.float32)
            if w == JANELA_SOMA:
                X["soma_env_origem_usd_24h"] = a["env_s24"][o] + a["env_c24"][o]
        n_prev = a["env_tot"][o].astype(np.float64)
        X["n_env_origem_total"] = n_prev
        with np.errstate(invalid="ignore", divide="ignore"):
            media = a["env_s1"][o] / n_prev
            var = np.maximum(a["env_s2"][o] / n_prev - media ** 2, 0.0)
            z = ((logv - a["env_ref"][o]) - media) / np.sqrt(var + _VAR_MIN_Z)
        X["z_valor_origem"] = np.where(n_prev >= 2, z, 0.0)
        X["min_desde_env_origem"] = t - a["ult_env"][o]
        X["n_env_destino_24h"] = a["env_n1440"][d].astype(np.float32)

        X["n_rec_origem_24h"] = a["rec_n1440"][o].astype(np.float32)
        soma_rec_o = a["rec_s24"][o] + a["rec_c24"][o]
        X["soma_rec_origem_usd_24h"] = soma_rec_o
        X["razao_saida_entrada_24h"] = X["soma_env_origem_usd_24h"] / (soma_rec_o + 1.0)
        X["min_desde_rec_origem"] = t - a["ult_rec"][o]
        for w in JANELAS_RECEBIMENTO:
            X[f"n_rec_destino_{w // 60}h"] = a[f"rec_n{w}"][d].astype(np.float32)
        X["min_desde_rec_destino"] = t - a["ult_rec"][d]

        previas = np.array([self.pares.get(int(oi) * _PAR + int(di), 0) for oi, di in zip(o, d)],
                           dtype=np.float32)
        X["par_novo"] = (previas == 0).astype(np.float32)
        X["n_par_previas"] = previas
        X["dest_distintos_origem"] = a["n_dest"][o].astype(np.float32)
        X["orig_distintas_destino"] = a["n_orig"][d].astype(np.float32)

        for col in ("min_desde_env_origem", "min_desde_rec_origem", "min_desde_rec_destino"):
            v = X[col]
            X[f"sem_historico_{col[10:]}"] = np.isnan(v).astype(np.float32)
            X[col] = np.where(np.isnan(v), _SEM_HISTORICO_MIN, np.minimum(v, _SEM_HISTORICO_MIN))

        formato = np.array([x["formato"] for x in grupo], dtype=object)
        for f in self.prep.formatos:
            X[f"formato_{f}"] = (formato == f).astype(np.float32)
        moeda = np.array([x["moeda_pagamento"] for x in grupo], dtype=object)
        for m in self.prep.moedas:
            X[f"moeda_{m}"] = (moeda == m).astype(np.float32)

        saida = pd.DataFrame({k: np.asarray(v, dtype=np.float32) for k, v in X.items()})
        if self.prep.colunas:
            saida = saida.reindex(columns=self.prep.colunas, fill_value=np.float32(0))
        return saida

    # -- incorporação ----------------------------------------------------------
    def _incorporar(self, t: int, o: np.ndarray, d: np.ndarray, usd: np.ndarray) -> None:
        a = self.a
        usd0 = np.where(np.isfinite(usd), usd, 0.0)
        logv = np.log1p(usd0)
        ref = a["env_ref"]
        for i, oi in enumerate(o.tolist()):  # 1º envio da conta, na ordem de chegada
            if math.isnan(ref[oi]):
                ref[oi] = logv[i]
        logc = logv - ref[o]
        np.add.at(a["env_tot"], o, 1)
        np.add.at(a["env_s1"], o, logc)
        np.add.at(a["env_s2"], o, logc * logc)
        for w in JANELAS_ENVIO:
            np.add.at(a[f"env_n{w}"], o, 1)
        _somar(a["env_s24"], a["env_c24"], o, usd0)
        a["ult_env"][o] = t
        for w in JANELAS_RECEBIMENTO:
            np.add.at(a[f"rec_n{w}"], d, 1)
        _somar(a["rec_s24"], a["rec_c24"], d, usd0)
        a["ult_rec"][d] = t
        minutos = np.full(len(o), t, dtype=np.int64)
        self.env.anexar(minutos, o, usd0)
        self.rec.anexar(minutos, d, usd0)
        for oi, di in zip(o.tolist(), d.tolist()):
            chave = oi * _PAR + di
            antes = self.pares.get(chave, 0)
            if antes == 0:
                a["n_dest"][oi] += 1
                a["n_orig"][di] += 1
            self.pares[chave] = antes + 1
        self.transacoes_incorporadas += len(o)

    # -- carga inicial em bloco -------------------------------------------------
    def carregar_historico(self, trans: pd.DataFrame, nomes_contas: np.ndarray,
                           descricao: str = "") -> Dict[str, Any]:
        """Monta o estado a partir de um histórico (formato ``DadosHISmall.trans``).

        Equivale a fechar, em ordem, todos os minutos do histórico, mas em
        operações vetorizadas. Só é permitido com o estado vazio.
        """
        if self.transacoes_incorporadas or self.aberto:
            raise RuntimeError("A carga inicial só pode ser feita com o estado vazio.")
        if trans.empty:
            raise ValueError("Histórico vazio.")
        mapa = np.fromiter((self.codigo(str(n)) for n in nomes_contas), dtype=np.int64, count=len(nomes_contas))
        minuto = trans["minuto"].to_numpy(dtype=np.int64)
        o = mapa[trans["conta_origem"].to_numpy()]
        d = mapa[trans["conta_destino"].to_numpy()]
        taxa = trans["moeda_pagamento"].astype(str).map(self.prep.cambio).to_numpy(dtype=np.float64)
        usd = trans["valor_pago"].to_numpy(dtype=np.float64) * taxa
        usd0 = np.where(np.isfinite(usd), usd, 0.0)
        logv = np.log1p(usd0)
        a, n = self.a, len(self.nomes)
        ultimo = int(minuto.max())
        proximo = ultimo + 1

        ordem = np.lexsort((minuto, o))  # estável: empate no minuto mantém a ordem do arquivo
        primeiros = np.unique(o[ordem], return_index=True)
        a["env_ref"][primeiros[0]] = logv[ordem][primeiros[1]]
        logc = logv - a["env_ref"][o]
        a["env_tot"][:n] = np.bincount(o, minlength=n)
        a["env_s1"][:n] = np.bincount(o, weights=logc, minlength=n)
        a["env_s2"][:n] = np.bincount(o, weights=logc * logc, minlength=n)
        a["ult_env"][:n] = _maximo_por(o, minuto, n)
        a["ult_rec"][:n] = _maximo_por(d, minuto, n)

        ordem_t = np.argsort(minuto, kind="stable")
        recentes = ordem_t[minuto[ordem_t] >= proximo - max(JANELAS_ENVIO)]
        for reg, contas, prefixo, janelas, soma in (
            (self.env, o, "env", JANELAS_ENVIO, "env_s24"),
            (self.rec, d, "rec", JANELAS_RECEBIMENTO, "rec_s24"),
        ):
            reg.anexar(minuto[recentes], contas[recentes], usd0[recentes])
            for w in janelas:
                ini = int(np.searchsorted(reg.m[:reg.n], proximo - w, side="left"))
                reg.cursor[w] = ini
                cod = reg.c[ini:reg.n]
                a[f"{prefixo}_n{w}"][:n] = np.bincount(cod, minlength=n)
                if w == JANELA_SOMA:
                    a[soma][:n] = np.bincount(cod, weights=reg.v[ini:reg.n], minlength=n)

        chaves = o * _PAR + d
        unicas, contagem = np.unique(chaves, return_counts=True)
        self.pares = dict(zip(unicas.tolist(), contagem.tolist()))
        a["n_dest"][:n] = np.bincount(unicas // _PAR, minlength=n)
        a["n_orig"][:n] = np.bincount(unicas % _PAR, minlength=n)

        self.ultimo_fechado = ultimo
        self.inicio_observacao = int(minuto.min())
        self.transacoes_incorporadas = int(len(trans))
        self.carga_inicial = {
            "descricao": descricao,
            "transacoes": int(len(trans)),
            "contas": int(len(nomes_contas)),
            "inicio_minuto": self.inicio_observacao,
            "fim_minuto": ultimo,
            "inicio_utc": _minuto_iso(self.inicio_observacao),
            "fim_utc": _minuto_iso(ultimo),
        }
        return self.carga_inicial

    # -- persistência -----------------------------------------------------------
    def cobertura(self) -> Dict[str, Any]:
        return {
            "inicio_observacao_utc": _minuto_iso(self.inicio_observacao),
            "ultimo_minuto_fechado_utc": _minuto_iso(self.ultimo_fechado),
            "transacoes_incorporadas": int(self.transacoes_incorporadas),
            "contas": len(self.nomes),
            "pares": len(self.pares),
            "eventos_nas_janelas": {"envios": self.env.ativos(), "recebimentos": self.rec.ativos()},
            "pendentes_em_minutos_abertos": self.pendentes(),
            "minutos_abertos": len(self.aberto),
            "carga_inicial": self.carga_inicial,
            "leitura": ("Atributos de contas com menos de 72 h de observação ficam marcados com "
                        "historico_incompleto: o estado só conhece o que veio da carga inicial e "
                        "dos eventos recebidos."),
        }

    def salvar(self, caminho: Path, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Grava o estado inteiro (escrita atômica). Só carregue arquivos gerados por você."""
        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "versao_estado": VERSAO_ESTADO,
            "assinatura_preparador": self.assinatura,
            "salvo_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ultimo_minuto_fechado": self.ultimo_fechado,
            "extra": extra or {},
        }
        corpo = {k: v for k, v in self.__dict__.items() if k != "prep"}
        fd, tmp = tempfile.mkstemp(dir=caminho.parent, suffix=".tmp")
        with os.fdopen(fd, "wb") as fh:
            pickle.dump({"meta": meta, "estado": corpo}, fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, caminho)
        meta["bytes"] = caminho.stat().st_size
        return meta

    @classmethod
    def carregar(cls, caminho: Path, prep: PreparadorFinanceiro) -> Tuple["EstadoFinanceiro", Dict[str, Any]]:
        with open(caminho, "rb") as fh:
            dados = pickle.load(fh)
        meta = dados["meta"]
        if meta.get("versao_estado") != VERSAO_ESTADO:
            raise ValueError(f"Estado {meta.get('versao_estado')} incompatível com {VERSAO_ESTADO}.")
        if meta.get("assinatura_preparador") != assinatura_preparador(prep):
            raise ValueError("O estado foi gerado com outro preparador financeiro (outro artefato).")
        estado = cls.__new__(cls)
        estado.__dict__.update(dados["estado"])
        estado.prep = prep
        return estado, meta


def _estender(arr: Optional[np.ndarray], cap: int, dtype, vazio) -> np.ndarray:
    novo = np.full(cap, vazio, dtype=dtype)
    if arr is not None:
        novo[:len(arr)] = arr
    return novo


def _somar(soma: np.ndarray, comp: np.ndarray, idx: Iterable[int], valores: np.ndarray) -> None:
    """Soma compensada (Neumaier) por conta: o erro não cresce com o histórico."""
    for i, x in zip(np.asarray(idx).tolist(), np.asarray(valores).tolist()):
        s = soma[i]
        t = s + x
        if abs(s) >= abs(x):
            comp[i] += (s - t) + x
        else:
            comp[i] += (x - t) + s
        soma[i] = t


def _maximo_por(chave: np.ndarray, valor: np.ndarray, n: int) -> np.ndarray:
    saida = np.full(n, -np.inf)
    np.maximum.at(saida, chave, valor.astype(np.float64))
    saida[np.isinf(saida)] = np.nan
    return saida


def _minuto_iso(m: Optional[int]) -> Optional[str]:
    if m is None:
        return None
    return datetime.fromtimestamp(int(m) * 60, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
