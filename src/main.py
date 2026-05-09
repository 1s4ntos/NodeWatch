"""Interface de linha de comando (CLI) do MVP — entrega E3.

Fluxo executado:
    arquivo CSV  ->  leitor PaySim  ->  Grafo  ->  DFS de ciclos  ->  saída
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Sequence

# Permite executar tanto via ``python -m src.main`` quanto ``python src/main.py``
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.algoritmos.cycle_detection import find_cycles  # noqa: E402
from src.grafo.graph import Graph  # noqa: E402
from src.leitura.file_reader import CsvFormatError, load_graph_from_csv  # noqa: E402


DEFAULT_INPUT = "dados/exemplo_transacoes.csv"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deteccao-fraudes",
        description=(
            "MVP — Detecção de Fraudes em Transações Financeiras via Grafos. "
            "Carrega um CSV no formato PaySim, monta um multigrafo direcionado "
            "ponderado e executa DFS para identificar ciclos suspeitos."
        ),
    )
    parser.add_argument(
        "--input",
        "-i",
        default=DEFAULT_INPUT,
        help=(
            "Caminho para o CSV de transações no formato PaySim "
            f"(default: {DEFAULT_INPUT})."
        ),
    )
    return parser


def _print_input_screen(input_path: Path, graph: Graph) -> None:
    """Tela de Entrada — confirma o que foi carregado."""
    print("=" * 60)
    print("=== Sistema de Detecção de Fraudes com Grafos ===")
    print("=" * 60)
    print(f"Arquivo carregado: {input_path}")
    print(f"Vértices (contas): {graph.vertex_count()}")
    print(f"Arestas (transações): {graph.edge_count()}")
    print("Algoritmo a executar: DFS para detecção de ciclos suspeitos")
    print("Complexidade: tempo O(V + E) | espaço O(V)")
    print("-" * 60)


def _print_result_screen(cycles: List[List[str]]) -> None:
    """Tela de Resultado — exibe ciclos encontrados de forma legível."""
    print("Resultado:")
    if not cycles:
        print("  Nenhum ciclo suspeito foi encontrado nas transações.")
        print("-" * 60)
        print("Total de ciclos encontrados: 0")
        return

    for index, cycle in enumerate(cycles, start=1):
        path_repr = " -> ".join(cycle)
        contas = sorted(set(cycle))
        print(f"  Ciclo suspeito {index}:")
        print(f"    Caminho: {path_repr}")
        print(f"    Contas envolvidas ({len(contas)}): {', '.join(contas)}")

    print("-" * 60)
    print(f"Total de ciclos encontrados: {len(cycles)}")


def run(argv: Sequence[str] | None = None) -> int:
    """Executa o pipeline completo do MVP. Retorna o exit code (0 = ok)."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    try:
        graph = load_graph_from_csv(input_path)
    except FileNotFoundError as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        print(
            f"Dica: confirme o caminho ou rode com --input {DEFAULT_INPUT}",
            file=sys.stderr,
        )
        return 2
    except CsvFormatError as exc:
        print(f"[ERRO] CSV inválido: {exc}", file=sys.stderr)
        return 3

    _print_input_screen(input_path, graph)
    cycles = find_cycles(graph)
    _print_result_screen(cycles)
    return 0


def main() -> None:  # pragma: no cover - thin wrapper
    raise SystemExit(run())


if __name__ == "__main__":  # pragma: no cover - thin wrapper
    main()
