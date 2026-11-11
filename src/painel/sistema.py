"""Medidas de desempenho e logs do painel (sem dependências novas).

Desempenho
    Memória e CPU são lidas do sistema operacional pela biblioteca padrão
    (``ctypes`` no Windows, ``/proc`` no Linux). Onde a leitura não existe, o
    valor volta ``None`` e a tela mostra "indisponível": nada é estimado.
    Cada medida diz se é do **processo do NodeWatch** ou da **máquina**.

Logs
    Dois registros separados, em memória e em ``artefatos_ml/painel/logs``:
    ``sistema`` (envios, validações, início, fim, cancelamento, erros) e
    ``ml`` (modelo carregado, limiar, transações pontuadas, tempo de
    inferência, avisos de atributos e de esquema). Os registros levam data e
    contexto, mas nunca contas, linhas do dataset, chaves ou caminhos da
    máquina: o filtro abaixo descarta campos com esses nomes.
"""

from __future__ import annotations

import collections
import ctypes
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from src.painel.util import agora_iso

MAX_ENTRADAS = 500
MAX_BYTES_LOG = 2_000_000
_PROIBIDOS = ("conta", "senha", "chave", "token", "key", "secret", "caminho", "path", "cpf", "cnpj", "email")


# ---------------------------------------------------------------------------
# Memória e CPU
# ---------------------------------------------------------------------------
class _ContadoresMemoria(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


class _MemoriaMaquina(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memoria_processo() -> Dict[str, Optional[int]]:
    """Memória residente do processo do NodeWatch, em bytes (atual e pico)."""
    try:
        if sys.platform == "win32":
            c = _ContadoresMemoria()
            c.cb = ctypes.sizeof(c)
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
            if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return {"bytes": int(c.WorkingSetSize), "pico_bytes": int(c.PeakWorkingSetSize)}
        elif os.path.isfile("/proc/self/status"):
            campos = {}
            with open("/proc/self/status", encoding="ascii", errors="replace") as fh:
                for linha in fh:
                    if linha.startswith(("VmRSS:", "VmHWM:")):
                        nome, valor = linha.split(":", 1)
                        campos[nome] = int(valor.split()[0]) * 1024
            if "VmRSS" in campos:
                return {"bytes": campos["VmRSS"], "pico_bytes": campos.get("VmHWM")}
    except (OSError, ValueError, AttributeError):
        pass
    return {"bytes": None, "pico_bytes": None}


def memoria_maquina() -> Dict[str, Optional[int]]:
    """Memória física da máquina, em bytes (total e em uso)."""
    try:
        if sys.platform == "win32":
            m = _MemoriaMaquina()
            m.dwLength = ctypes.sizeof(m)
            if ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx(ctypes.byref(m)):
                return {"total_bytes": int(m.ullTotalPhys), "em_uso_bytes": int(m.ullTotalPhys - m.ullAvailPhys)}
        elif os.path.isfile("/proc/meminfo"):
            campos = {}
            with open("/proc/meminfo", encoding="ascii", errors="replace") as fh:
                for linha in fh:
                    nome, valor = linha.split(":", 1)
                    campos[nome] = int(valor.split()[0]) * 1024
            if "MemTotal" in campos and "MemAvailable" in campos:
                return {"total_bytes": campos["MemTotal"], "em_uso_bytes": campos["MemTotal"] - campos["MemAvailable"]}
    except (OSError, ValueError, AttributeError):
        pass
    return {"total_bytes": None, "em_uso_bytes": None}


def _tempos_cpu_maquina() -> Optional[tuple]:
    """(ocupado, total) acumulados da máquina, em unidades arbitrárias; ``None`` se não houver leitura."""
    try:
        if sys.platform == "win32":
            ocioso, nucleo, usuario = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
            if ctypes.WinDLL("kernel32", use_last_error=True).GetSystemTimes(
                    ctypes.byref(ocioso), ctypes.byref(nucleo), ctypes.byref(usuario)):
                total = nucleo.value + usuario.value  # o tempo de núcleo já inclui o ocioso
                return total - ocioso.value, total
        elif os.path.isfile("/proc/stat"):
            with open("/proc/stat", encoding="ascii", errors="replace") as fh:
                partes = [int(x) for x in fh.readline().split()[1:]]
            total = sum(partes)
            return total - partes[3] - (partes[4] if len(partes) > 4 else 0), total
    except (OSError, ValueError, AttributeError, IndexError):
        pass
    return None


class MonitorRecursos:
    """CPU precisa de duas leituras: guarda a anterior e mede o intervalo entre elas."""

    INTERVALO_MIN_S = 0.5

    def __init__(self) -> None:
        self._trava = threading.Lock()
        self._anterior: Optional[Dict[str, Any]] = None
        self._ultimo: Dict[str, Any] = {"processo_pct": None, "maquina_pct": None, "janela_s": None}

    def _amostra(self) -> Dict[str, Any]:
        return {"relogio": time.monotonic(), "processo": time.process_time(), "maquina": _tempos_cpu_maquina()}

    def cpu(self) -> Dict[str, Any]:
        nucleos = os.cpu_count() or 1
        with self._trava:
            atual = self._amostra()
            if self._anterior is None:
                self._anterior = atual
                time.sleep(0.2)  # primeira leitura: janela curta, informada em janela_s
                atual = self._amostra()
            ant = self._anterior
            janela = atual["relogio"] - ant["relogio"]
            if janela >= self.INTERVALO_MIN_S or self._ultimo["janela_s"] is None:
                proc = 100.0 * (atual["processo"] - ant["processo"]) / (janela * nucleos) if janela > 0 else None
                maq = None
                if atual["maquina"] and ant["maquina"] and atual["maquina"][1] > ant["maquina"][1]:
                    maq = 100.0 * (atual["maquina"][0] - ant["maquina"][0]) / (atual["maquina"][1] - ant["maquina"][1])
                self._ultimo = {"processo_pct": None if proc is None else max(0.0, min(100.0, proc)),
                                "maquina_pct": None if maq is None else max(0.0, min(100.0, maq)),
                                "janela_s": round(janela, 2)}
                self._anterior = atual
            return {**self._ultimo, "nucleos_logicos": nucleos,
                    "leitura": "percentual da capacidade total da máquina (todos os núcleos lógicos), "
                               "medido no intervalo entre duas leituras"}

    def leitura(self) -> Dict[str, Any]:
        proc, maq = memoria_processo(), memoria_maquina()
        pct_proc = (100.0 * proc["bytes"] / maq["total_bytes"]
                    if proc["bytes"] is not None and maq["total_bytes"] else None)
        pct_maq = (100.0 * maq["em_uso_bytes"] / maq["total_bytes"]
                   if maq["em_uso_bytes"] is not None and maq["total_bytes"] else None)
        return {
            "medido_em": agora_iso(),
            "memoria": {
                "processo": {"escopo": "processo do NodeWatch", "bytes": proc["bytes"], "pico_bytes": proc["pico_bytes"],
                             "percentual_da_maquina": pct_proc},
                "maquina": {"escopo": "máquina", "em_uso_bytes": maq["em_uso_bytes"], "total_bytes": maq["total_bytes"],
                            "percentual": pct_maq},
            },
            "cpu": self.cpu(),
        }


# ---------------------------------------------------------------------------
# Latência das consultas do painel
# ---------------------------------------------------------------------------
class Latencias:
    """Duração, medida no servidor, das últimas consultas de cada operação (ms)."""

    def __init__(self, n: int = 50) -> None:
        self._n = n
        self._trava = threading.Lock()
        self._dados: Dict[str, Deque[float]] = {}
        self._ultima: Dict[str, str] = {}

    def registrar(self, operacao: str, ms: float) -> None:
        with self._trava:
            self._dados.setdefault(operacao, collections.deque(maxlen=self._n)).append(float(ms))
            self._ultima[operacao] = agora_iso()

    def resumo(self) -> List[Dict[str, Any]]:
        with self._trava:
            return [{"operacao": op, "ultima_ms": v[-1], "mediana_ms": statistics.median(v), "maxima_ms": max(v),
                     "amostras": len(v), "medido_em": self._ultima[op], "unidade": "ms",
                     "leitura": "tempo de processamento da consulta no servidor (não inclui rede nem o navegador)"}
                    for op, v in sorted(self._dados.items()) if v]


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------
def _limpar_contexto(contexto: Dict[str, Any]) -> Dict[str, Any]:
    saida: Dict[str, Any] = {}
    for k, v in contexto.items():
        nome = str(k).lower()
        if v is None or any(p in nome for p in _PROIBIDOS):
            continue
        if isinstance(v, (int, float, bool)) or v is None:
            saida[str(k)] = v
        elif isinstance(v, (list, tuple)):
            saida[str(k)] = [str(x)[:80] for x in list(v)[:20]]
        elif isinstance(v, dict):
            saida[str(k)] = {str(a)[:60]: (b if isinstance(b, (int, float, bool)) or b is None else str(b)[:120])
                             for a, b in list(v.items())[:20]}
        else:
            saida[str(k)] = str(v)[:300]
    return saida


class Registro:
    """Logs do sistema e de ML: memória (últimas entradas) e arquivo JSONL com rotação simples."""

    TIPOS = ("sistema", "ml")

    def __init__(self, pasta: Optional[Path]) -> None:
        self.pasta = Path(pasta) if pasta else None
        self._trava = threading.Lock()
        self._mem: Dict[str, Deque[Dict[str, Any]]] = {t: collections.deque(maxlen=MAX_ENTRADAS) for t in self.TIPOS}
        if self.pasta:
            self.pasta.mkdir(parents=True, exist_ok=True)
            for t in self.TIPOS:
                arq = self.pasta / f"{t}.jsonl"
                if arq.is_file():
                    try:
                        linhas = arq.read_text(encoding="utf-8").splitlines()[-MAX_ENTRADAS:]
                    except OSError:
                        linhas = []
                    for linha in linhas:
                        try:
                            self._mem[t].append(json.loads(linha))
                        except ValueError:
                            continue

    def _gravar(self, tipo: str, nivel: str, evento: str, mensagem: str, contexto: Dict[str, Any]) -> Dict[str, Any]:
        entrada = {"quando": agora_iso(), "nivel": nivel, "evento": evento, "mensagem": str(mensagem)[:500],
                   "contexto": _limpar_contexto(contexto)}
        with self._trava:
            self._mem[tipo].append(entrada)
            if self.pasta:
                arq = self.pasta / f"{tipo}.jsonl"
                try:
                    if arq.is_file() and arq.stat().st_size > MAX_BYTES_LOG:
                        os.replace(arq, arq.with_suffix(".jsonl.1"))
                    with open(arq, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(entrada, ensure_ascii=False, default=str) + "\n")
                except OSError:
                    pass
        return entrada

    def sistema(self, evento: str, mensagem: str, nivel: str = "info", **contexto: Any) -> Dict[str, Any]:
        return self._gravar("sistema", nivel, evento, mensagem, contexto)

    def ml(self, evento: str, mensagem: str, nivel: str = "info", **contexto: Any) -> Dict[str, Any]:
        return self._gravar("ml", nivel, evento, mensagem, contexto)

    def listar(self, tipo: str, limite: int = 200) -> List[Dict[str, Any]]:
        if tipo not in self.TIPOS:
            raise KeyError(tipo)
        with self._trava:
            return list(self._mem[tipo])[-max(1, min(int(limite), MAX_ENTRADAS)):][::-1]
