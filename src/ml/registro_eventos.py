"""Registro durável de eventos (write-ahead log) do processamento de eventos.

Todo evento aceito — da API, de um replay, do laboratório ou um comando de
controle (fechar minutos, descartar eventos bloqueados) — é gravado aqui, com
uma sequência crescente, **antes** de ser aplicado ao estado. Assim:

* a API só confirma a aceitação depois do ``fsync`` (aceitação durável);
* o estado e os CSVs de saída são **projeções** reconstruíveis: instantâneo +
  eventos do registro posteriores a ele, reaplicados na mesma ordem;
* uma falha no meio de um lote é desfeita reconstruindo a partir do
  instantâneo, sem copiar o estado inteiro a cada evento.

Formato: arquivos ``wal_<primeira_seq>.jsonl`` (uma linha JSON por evento). Uma
linha final incompleta (queda durante a escrita) é ignorada: o evento dela não
foi confirmado ao produtor. Depois de um instantâneo bem-sucedido, o segmento
corrente é encerrado e os segmentos inteiramente anteriores ao instantâneo são
apagados.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

PREFIXO = "wal_"


def _nativo(v: Any) -> Any:
    item = getattr(v, "item", None)
    return item() if callable(item) else str(v)


def serializar(registro: Dict[str, Any]) -> str:
    return json.dumps(registro, ensure_ascii=False, separators=(",", ":"), default=_nativo)


class RegistroDuravel:
    def __init__(self, pasta: Path):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self._trava = threading.Lock()
        self.ultima_seq = 0
        for _, ultima in self._segmentos_com_fim():
            self.ultima_seq = max(self.ultima_seq, ultima)
        self._atual: Optional[Path] = None

    # -- leitura ---------------------------------------------------------------
    def _segmentos(self) -> List[Path]:
        return sorted(self.pasta.glob(f"{PREFIXO}*.jsonl"), key=lambda p: int(p.stem[len(PREFIXO):]))

    @staticmethod
    def _linhas(caminho: Path) -> Iterator[Dict[str, Any]]:
        with open(caminho, "r", encoding="utf-8") as fh:
            for linha in fh:
                if not linha.endswith("\n"):
                    return  # escrita interrompida: não confirmada
                try:
                    yield json.loads(linha)
                except json.JSONDecodeError:
                    return

    def _segmentos_com_fim(self) -> List[Tuple[Path, int]]:
        saida = []
        for seg in self._segmentos():
            ultima = 0
            for r in self._linhas(seg):
                ultima = r["seq"]
            saida.append((seg, ultima))
        return saida

    def ler_depois(self, seq: int) -> Iterator[Dict[str, Any]]:
        """Registros com ``seq`` maior que a informada, em ordem."""
        for seg in self._segmentos():
            for r in self._linhas(seg):
                if r["seq"] > seq:
                    yield r

    def contar_depois(self, seq: int) -> int:
        return sum(1 for r in self.ler_depois(seq) if r.get("tipo") != "controle")

    # -- escrita ---------------------------------------------------------------
    def anexar(self, registros: List[Dict[str, Any]], sincronizar: bool = True) -> List[int]:
        """Atribui sequências e grava. Com ``sincronizar``, só retorna depois do fsync."""
        if not registros:
            return []
        with self._trava:
            if self._atual is None:
                self._atual = self.pasta / f"{PREFIXO}{self.ultima_seq + 1:012d}.jsonl"
            seqs = []
            linhas = []
            for r in registros:
                self.ultima_seq += 1
                r["seq"] = self.ultima_seq
                seqs.append(self.ultima_seq)
                linhas.append(serializar(r) + "\n")
            with open(self._atual, "a", encoding="utf-8", newline="\n") as fh:
                fh.write("".join(linhas))
                fh.flush()
                if sincronizar:
                    os.fsync(fh.fileno())
            return seqs

    def sincronizar(self) -> None:
        with self._trava:
            if self._atual is not None and self._atual.is_file():
                with open(self._atual, "a", encoding="utf-8") as fh:
                    fh.flush()
                    os.fsync(fh.fileno())

    def podar(self, ate_seq: int) -> int:
        """Depois de um instantâneo que cobre ``ate_seq``: encerra o segmento corrente e
        apaga os segmentos cujos eventos são todos <= ``ate_seq``."""
        with self._trava:
            self._atual = None
            removidos = 0
            for seg, ultima in self._segmentos_com_fim():
                if ultima <= ate_seq:
                    seg.unlink()
                    removidos += 1
            return removidos

    def apagar_tudo(self) -> None:
        with self._trava:
            for seg in self._segmentos():
                seg.unlink()
            self._atual = None
            self.ultima_seq = 0
