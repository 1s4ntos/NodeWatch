"""Leitura de transações financeiras em CSV (formato PaySim simplificado).

Formato esperado do CSV (cabeçalho obrigatório):

    step,type,amount,nameOrig,nameDest,isFraud
    1,TRANSFER,1000.00,C001,C002,0
    1,TRANSFER,1500.00,C002,C003,0
    1,TRANSFER,2000.00,C003,C001,1

Apenas as colunas ``nameOrig``, ``nameDest`` e ``amount`` são obrigatórias.
``type`` e ``isFraud`` são opcionais — quando ausentes, recebem valores
neutros (``None`` e ``False``).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Union

from src.grafo.graph import Graph


REQUIRED_COLUMNS = {"nameOrig", "nameDest", "amount"}


class CsvFormatError(ValueError):
    """Erro de formato/estrutura do CSV de transações."""


def load_graph_from_csv(path: Union[str, Path]) -> Graph:
    """Lê um CSV de transações e devolve um :class:`Graph` populado.

    Args:
        path: caminho para um arquivo ``.csv`` no formato PaySim simplificado.

    Returns:
        Um :class:`Graph` com vértices = contas e arestas = transações.

    Raises:
        FileNotFoundError: se o arquivo não existir.
        CsvFormatError: se faltarem colunas obrigatórias ou o cabeçalho for
            inválido.
    """
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Arquivo CSV não encontrado: {csv_path}")

    graph = Graph()

    with csv_path.open(mode="r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)

        if reader.fieldnames is None:
            raise CsvFormatError(
                "CSV vazio ou sem cabeçalho. Esperado: "
                "step,type,amount,nameOrig,nameDest,isFraud"
            )

        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise CsvFormatError(
                "Colunas obrigatórias ausentes no CSV: "
                f"{sorted(missing)}. Cabeçalho recebido: {reader.fieldnames}"
            )

        for line_number, row in enumerate(reader, start=2):
            # line_number=2 porque a linha 1 é o cabeçalho
            source = (row.get("nameOrig") or "").strip()
            target = (row.get("nameDest") or "").strip()
            if not source or not target:
                # Linha incompleta — pulamos com aviso silencioso.
                continue

            try:
                amount = float(row.get("amount") or 0.0)
            except ValueError as exc:
                raise CsvFormatError(
                    f"Valor inválido em 'amount' na linha {line_number}: "
                    f"{row.get('amount')!r}"
                ) from exc

            transaction_type = (row.get("type") or "").strip() or None
            is_fraud = _parse_bool(row.get("isFraud"))

            graph.add_edge(
                source=source,
                target=target,
                amount=amount,
                transaction_type=transaction_type,
                is_fraud=is_fraud,
            )

    return graph


def _parse_bool(raw: object) -> bool:
    """Converte representações comuns de booleano em ``bool``.

    Aceita: ``"1"``, ``"true"``, ``"True"`` -> ``True``; resto -> ``False``.
    """
    if raw is None:
        return False
    text = str(raw).strip().lower()
    return text in {"1", "true", "yes", "y", "sim"}
