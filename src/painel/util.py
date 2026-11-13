"""Utilidades pequenas do painel: JSON com escrita atômica e datas."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_contador = 0
_trava = threading.Lock()


def agora_iso() -> str:
    """Instante atual em UTC, ISO 8601 com sufixo Z."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def minuto_iso(minuto: Optional[int]) -> Optional[str]:
    """Minuto desde 1970 → ``AAAA-MM-DDTHH:MM`` (horário do dataset, sem conversão de fuso)."""
    if minuto is None:
        return None
    return datetime.fromtimestamp(int(minuto) * 60, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M")


def _substituir(tmp: Path, destino: Path, tentativas: int = 40) -> None:
    """``os.replace`` com novas tentativas: no Windows a troca é negada enquanto outro processo lê o destino."""
    for i in range(tentativas):
        try:
            os.replace(tmp, destino)
            return
        except PermissionError:
            if i == tentativas - 1:
                raise
            time.sleep(0.005 * (i + 1))


def gravar_json_atomico(caminho: Path, dados: Any) -> None:
    """Grava em arquivo temporário na mesma pasta e renomeia: leitores nunca veem JSON pela metade."""
    global _contador
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with _trava:
        _contador += 1
        n = _contador
    tmp = caminho.with_name(f".{caminho.name}.{os.getpid()}.{n}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(dados, fh, ensure_ascii=False, indent=1, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        _substituir(tmp, caminho)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def ler_json(caminho: Path) -> Optional[Any]:
    try:
        with open(caminho, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def id_exibicao_texto(n: int, total: int) -> str:
    """ID de exibição como a tela mostra (painel-base.js, ``idExibicao``): TX- e ao menos 6 dígitos."""
    return "TX-" + str(int(n)).zfill(max(6, len(str(int(total or 0)))))
