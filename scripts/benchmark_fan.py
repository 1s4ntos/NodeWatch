"""Avalia o detector de fan-out/fan-in variando seus parâmetros (IBM AML).

Para cada combinação de parâmetros mostra quantas contas/transações o detector
sinaliza, a precisão e a revocação contra o rótulo do dataset, e a revocação
dos padrões FAN-OUT e FAN-IN do arquivo de padrões da IBM.

Uso (a partir da raiz do projeto):
    python scripts/benchmark_fan.py \
        -i dados/ibm_50k.csv -p dados/HI-Small_Patterns.txt

Parâmetros opcionais (listas, separadas por espaço):
    --k 5 8 10 15            mínimo de contas distintas na janela
    --janela 24 72 168       largura da janela, em horas
    --max-hub 0 100 30       ignora contas com mais contrapartes no período
                             (0 = sem filtro)
    --combinar               ao final, compara por padrão: SCC/ciclos, fan e a
                             união dos dois, usando a melhor configuração

Como ler:
  * Precisão   = das transações sinalizadas, quantas estão rotuladas como lavagem.
  * Rev. rót.  = das transações rotuladas como lavagem, quantas foram sinalizadas.
  * Rev. FAN-OUT / FAN-IN = das transações desses padrões (arquivo de padrões)
    presentes no recorte, quantas foram sinalizadas (por par de contas).

Atenção: se o CSV foi gerado com --modo ilicitas, a proporção de lavagem é
muito maior que a real e a PRECISÃO aparece otimista. Para estimar a precisão
em condições realistas, use um recorte que preserve a proporção original.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA_SCRIPTS = Path(__file__).resolve().parent
for p in (str(RAIZ), str(PASTA_SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from analise_por_padrao import ler_padroes  # noqa: E402
from src.algoritmos.fan_detection import find_fan_patterns  # noqa: E402
from src.algoritmos.scc import find_scc  # noqa: E402
from src.leitura.file_reader import load_graph_from_csv  # noqa: E402


def _pares_sinalizados(resultados) -> set:
    """Pares (origem, destino) de todas as transações dentro das janelas."""
    return {(e.source, e.target) for r in resultados for e in r.edges}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--input", "-i", required=True, type=Path)
    parser.add_argument("--patterns", "-p", required=True, type=Path)
    parser.add_argument("--k", type=int, nargs="+", default=[5, 8, 10, 15])
    parser.add_argument("--janela", type=int, nargs="+", default=[24, 72, 168])
    parser.add_argument("--max-hub", type=int, nargs="+", default=[0, 100, 30])
    parser.add_argument("--combinar", action="store_true",
                        help="Compara SCC/ciclos, fan e a união dos dois por padrão.")
    args = parser.parse_args()

    for arq in (args.input, args.patterns):
        if not arq.exists():
            print(f"[ERRO] Arquivo não encontrado: {arq}", file=sys.stderr)
            return 1

    grafo = load_graph_from_csv(args.input)
    arestas = grafo.edges()
    rotuladas = [e for e in arestas if e.is_fraud]
    if not rotuladas:
        print("[ERRO] Nenhuma transação rotulada como lavagem no CSV.", file=sys.stderr)
        return 1

    tentativas = ler_padroes(args.patterns)
    existentes = {(e.source, e.target) for e in arestas}
    pares_por_padrao: dict[str, set] = defaultdict(set)
    for nome, pares in tentativas:
        for par in pares:
            if par[0] != par[1] and par in existentes:
                pares_por_padrao[nome].add(par)

    print(f"Arquivo: {args.input}")
    print(f"Transações: {len(arestas):,} | rotuladas como lavagem: {len(rotuladas):,} "
          f"({len(rotuladas) / len(arestas):.1%})")
    print("Pares FAN-OUT / FAN-IN presentes no recorte: "
          f"{len(pares_por_padrao.get('FAN-OUT', ())):,} / {len(pares_por_padrao.get('FAN-IN', ())):,}\n")

    cab = (f"{'k':>3}{'Janela':>8}{'Hub≤':>6}{'Contas':>8}{'Transações':>12}"
           f"{'Precisão':>10}{'Rev.rót.':>10}{'Rev.FANOUT':>12}{'Rev.FANIN':>11}{'F1':>7}")
    print(cab)
    print("-" * len(cab))

    melhor = None
    for hub in args.max_hub:
        for janela in args.janela:
            for k in args.k:
                res = find_fan_patterns(
                    grafo, min_counterparts=k, window_steps=janela,
                    max_total_counterparts=hub or None)
                pares = _pares_sinalizados(res)
                sinalizadas = {id(e): e for r in res for e in r.edges}
                n = len(sinalizadas)
                tp = sum(1 for e in sinalizadas.values() if e.is_fraud)
                prec = tp / n if n else 0.0
                rev = tp / len(rotuladas)
                f1 = 2 * prec * rev / (prec + rev) if (prec + rev) else 0.0

                def rev_padrao(nome: str) -> str:
                    alvo = pares_por_padrao.get(nome, set())
                    return f"{len(alvo & pares) / len(alvo):.0%}" if alvo else "-"

                print(f"{k:>3}{janela:>7}h{(hub or 'sem'):>6}{len({r.account for r in res}):>8,}"
                      f"{n:>12,}{prec:>10.1%}{rev:>10.1%}{rev_padrao('FAN-OUT'):>12}"
                      f"{rev_padrao('FAN-IN'):>11}{f1:>7.3f}")
                if melhor is None or f1 > melhor[0]:
                    melhor = (f1, k, janela, hub, pares)

    if melhor and melhor[0] > 0:
        f1, k, janela, hub, pares = melhor
        print(f"\nMelhor F1 ({f1:.3f}): k={k}, janela={janela}h, hub≤{hub or 'sem filtro'}")
        print("Revocação por padrão com essa configuração (por par de contas):")
        for nome in sorted(pares_por_padrao, key=lambda n: -len(pares_por_padrao[n])):
            alvo = pares_por_padrao[nome]
            print(f"  {nome:<16}{len(alvo & pares):>6,} de {len(alvo):>6,}  ({len(alvo & pares) / len(alvo):.0%})")
    else:
        print("\nNenhuma configuração sinalizou transações rotuladas.")

    if args.combinar and melhor and melhor[0] > 0:
        _combinar(grafo, rotuladas, pares_por_padrao, melhor[4])
    return 0


def _combinar(grafo, rotuladas, pares_por_padrao, pares_fan) -> None:
    """Compara SCC/ciclos, fan e a união dos dois (por par de contas)."""
    suspeitos = [c for c in find_scc(grafo) if c.is_suspicious]
    membro = {v: c.component_id for c in suspeitos for v in c.vertices}
    pares_scc = {
        (e.source, e.target) for e in grafo.edges()
        if e.source in membro and membro.get(e.target) == membro[e.source]
    }
    uniao = pares_scc | pares_fan

    print("\nCombinação dos detectores (melhor configuração do fan):")
    cab = f"  {'Padrão':<16}{'SCC/ciclos':>12}{'Fan':>8}{'União':>8}"
    print(cab)
    print("  " + "-" * (len(cab) - 2))
    for nome in sorted(pares_por_padrao, key=lambda n: -len(pares_por_padrao[n])):
        alvo = pares_por_padrao[nome]
        f = lambda conj: f"{len(alvo & conj) / len(alvo):.0%}"  # noqa: E731
        print(f"  {nome:<16}{f(pares_scc):>12}{f(pares_fan):>8}{f(uniao):>8}")

    print("\n  Sobre todas as transações rotuladas (por par de contas):")
    todas = grafo.edges()
    for nome, conj in (("SCC/ciclos", pares_scc), ("Fan", pares_fan), ("União", uniao)):
        sinal = [e for e in todas if (e.source, e.target) in conj]
        tp = sum(1 for e in sinal if e.is_fraud)
        prec = tp / len(sinal) if sinal else 0.0
        print(f"    {nome:<12} sinalizadas={len(sinal):>7,}  precisão={prec:>6.1%}  "
              f"revocação={tp / len(rotuladas):>6.1%}")


if __name__ == "__main__":
    raise SystemExit(main())