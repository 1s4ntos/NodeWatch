"""Compara transações de lavagem e normais de uma conta de origem (IBM AML).

Serve para decidir com dados quais sinais separam a lavagem da atividade normal
de uma conta de alto volume, antes de implementar qualquer detector.

Uso (a partir da raiz do projeto):
    python scripts/explorar_conta.py -i dados/HI-Small_Trans.csv --conta 070-100428660

A conta usa o formato "BANCO-CONTA", o mesmo dos CSVs convertidos
(ex.: 070-100428660 = banco 070, conta 100428660).

O que é comparado (transações em que a conta é a ORIGEM):
  * taxa de lavagem por formato de pagamento;
  * valores (mediana e percentil 90) de lavagem x normais;
  * fração de transações cujo destino aparece uma única vez para essa origem;
  * quantidade de destinos distintos.
Não é um teste estatístico: é uma exploração descritiva.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

PASTA_SCRIPTS = Path(__file__).resolve().parent
if str(PASTA_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PASTA_SCRIPTS))

from converter_ibm_aml import _ler  # noqa: E402


def _quantis(valores: list[float]) -> tuple[float, float]:
    """Mediana e percentil 90 (0.0 se não houver dados)."""
    if not valores:
        return 0.0, 0.0
    if len(valores) == 1:
        return valores[0], valores[0]
    p90 = statistics.quantiles(valores, n=10, method="inclusive")[-1]
    return statistics.median(valores), p90


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--input", "-i", required=True, type=Path, help="Arquivo original da IBM (ex.: HI-Small_Trans.csv).")
    parser.add_argument("--conta", "-c", required=True, help='Conta de origem no formato "BANCO-CONTA".')
    args = parser.parse_args()

    try:
        linhas = [t for t in _ler(args.input) if t.origem == args.conta]
    except (FileNotFoundError, ValueError) as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        return 1

    if not linhas:
        print(f"Nenhuma transação com origem {args.conta}.")
        return 1

    lav = [t for t in linhas if t.ilicita]
    norm = [t for t in linhas if not t.ilicita]

    print(f"Conta de origem: {args.conta}")
    print(f"  Transações como origem : {len(linhas):,}")
    print(f"  Rotuladas como lavagem : {len(lav):,} ({len(lav) / len(linhas):.2%})")
    print(f"  Destinos distintos     : {len({t.destino for t in linhas}):,}")

    # Formato de pagamento
    por_formato: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [total, lavagem]
    for t in linhas:
        por_formato[t.formato][0] += 1
        por_formato[t.formato][1] += t.ilicita
    print("\nPor formato de pagamento:")
    print(f"  {'Formato':<14}{'Total':>10}{'Lavagem':>10}{'Taxa':>9}")
    for fmt, (tot, l) in sorted(por_formato.items(), key=lambda kv: -kv[1][0]):
        print(f"  {fmt:<14}{tot:>10,}{l:>10,}{l / tot:>9.2%}")

    # Valores
    def valores(grupo):
        out = []
        for t in grupo:
            try:
                out.append(float(t.valor))
            except ValueError:
                continue
        return out

    med_l, p90_l = _quantis(valores(lav))
    med_n, p90_n = _quantis(valores(norm))
    print("\nValores (Amount Paid):")
    print(f"  {'Grupo':<10}{'Mediana':>16}{'Percentil 90':>18}")
    print(f"  {'Lavagem':<10}{med_l:>16,.2f}{p90_l:>18,.2f}")
    print(f"  {'Normal':<10}{med_n:>16,.2f}{p90_n:>18,.2f}")

    # Destino de ocorrência única para esta origem
    cont_destinos = Counter(t.destino for t in linhas)

    def frac_unico(grupo):
        if not grupo:
            return 0.0
        return sum(1 for t in grupo if cont_destinos[t.destino] == 1) / len(grupo)

    print("\nDestino que aparece UMA única vez com esta origem:")
    print(f"  Lavagem: {frac_unico(lav):.1%}   |   Normal: {frac_unico(norm):.1%}")
    print("\n(Exploração descritiva; diferenças grandes sugerem um sinal, "
          "mas ainda precisam ser testadas no benchmark.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
