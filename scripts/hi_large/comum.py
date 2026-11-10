"""Utilitários dos experimentos com o IBM AML HI-Large (só leitura do NodeWatch).

Os scripts desta pasta não alteram o modelo do sistema. Gravam:

* dados grandes e intermediários em ``artefatos_ml/hi_large/`` (ignorado pelo git);
* resultados pequenos, em JSON, em ``docs/ml/hi_large/resultados/``.

O diretório com ``HI-Large_Trans.csv``, ``HI-Large_Patterns.txt`` e
``HI-Large_accounts.csv`` vem de ``--dados`` ou da variável ``NODEWATCH_HI_LARGE``.
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

TRABALHO = RAIZ / "artefatos_ml" / "hi_large"
RESULTADOS = RAIZ / "docs" / "ml" / "hi_large" / "resultados"
PLANO = RAIZ / "docs" / "ml" / "hi_large" / "PLANO_AVALIACAO.md"
SEMENTE = 42
THREADS = 4
ARQUIVOS = {"transacoes": "HI-Large_Trans.csv", "padroes": "HI-Large_Patterns.txt",
            "contas": "HI-Large_accounts.csv"}


def nomes_arquivos(prefixo: str = "HI-Large") -> dict:
    """Nomes dos três arquivos do IBM AML para um prefixo (HI-Large, HI-Medium, LI-Large...)."""
    return {"transacoes": f"{prefixo}_Trans.csv", "padroes": f"{prefixo}_Patterns.txt",
            "contas": f"{prefixo}_accounts.csv"}


def pasta_dados(indicada: Optional[str]) -> Path:
    p = Path(indicada or os.environ.get("NODEWATCH_HI_LARGE", ""))
    if not str(p) or not p.is_dir():
        raise SystemExit("Informe a pasta do HI-Large com --dados ou NODEWATCH_HI_LARGE.")
    return p


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:  # pragma: no cover - só informativo
        return ""


def ambiente() -> Dict[str, Any]:
    import numpy, pandas, pyarrow, sklearn  # noqa: E401
    versoes = {"python": platform.python_version(), "numpy": numpy.__version__, "pandas": pandas.__version__,
               "pyarrow": pyarrow.__version__, "scikit-learn": sklearn.__version__}
    try:
        import xgboost
        versoes["xgboost"] = xgboost.__version__
    except Exception:
        versoes["xgboost"] = None
    info: Dict[str, Any] = {"sistema": platform.platform(), "processador": platform.processor(),
                            "nucleos_logicos": os.cpu_count(), "threads": THREADS, "versoes": versoes}
    try:
        import ctypes

        class _Mem(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = _Mem()
        m.dwLength = ctypes.sizeof(_Mem)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        info["ram_total_gb"] = round(m.ullTotalPhys / 2**30, 2)
        info["ram_disponivel_gb"] = round(m.ullAvailPhys / 2**30, 2)
    except Exception:
        pass
    info["nodewatch"] = {"branch": _git("rev-parse", "--abbrev-ref", "HEAD"), "commit": _git("rev-parse", "HEAD"),
                         "alteracoes_locais": len(_git("status", "--porcelain").splitlines())}
    return info


def memoria_processo_mb() -> Optional[float]:
    """Pico de memória do processo (maior entre conjunto de trabalho e privada), em MB."""
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        c = _PMC()
        c.cb = ctypes.sizeof(_PMC)
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return None
        return round(max(c.PeakWorkingSetSize, c.PeakPagefileUsage) / 2**20, 1)
    except Exception:
        return None


@contextlib.contextmanager
def medir(destino: Dict[str, Any], nome: str) -> Iterator[None]:
    t0, c0 = time.perf_counter(), time.process_time()
    yield
    destino[nome] = {"segundos": round(time.perf_counter() - t0, 2), "cpu_s": round(time.process_time() - c0, 2)}


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _nativo(v: Any) -> Any:
    import numpy as np
    if isinstance(v, dict):
        return {str(k): _nativo(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_nativo(x) for x in v]
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, np.ndarray):
        return _nativo(v.tolist())
    return v


def salvar_json(obj: Dict[str, Any], nome: str) -> Path:
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    caminho = RESULTADOS / nome
    caminho.write_text(json.dumps(_nativo(obj), ensure_ascii=False, indent=1), encoding="utf-8")
    return caminho


def ler_json(nome: str) -> Dict[str, Any]:
    return json.loads((RESULTADOS / nome).read_text(encoding="utf-8"))
