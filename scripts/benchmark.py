"""Mede tempo e qualidade do NodeWatch em um CSV (formato NodeWatch).

Uso (a partir da raiz do projeto):
    python scripts/benchmark.py --input dados/ibm_hi_small_50k.csv --timeout 120

O que é medido:
1. Tempo para ler o CSV e montar o grafo.
2. Tempo do SCC (Kosaraju) e quantos componentes suspeitos existem.
3. Tempo da detecção de ciclos (DFS), com limite de tempo (--timeout), porque
   enumerar todos os ciclos simples pode crescer de forma exponencial.
4. Qualidade, comparando com o rótulo isFraud do dataset (nível de transação):
   uma transação é "sinalizada" se pertence a um ciclo encontrado (ou, no caso
   do SCC, se origem e destino estão no mesmo componente suspeito).

Atenção ao interpretar: no dataset da IBM, o rótulo cobre toda a cadeia de
lavagem, e nem toda cadeia forma um ciclo. Por isso uma revocação baixa não
significa, sozinha, que o algoritmo está errado; ela mostra quanto da lavagem
é do tipo "ciclo".
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src.algoritmos.cycle_detection import find_cycles  # noqa: E402
from src.algoritmos.scc import find_scc  # noqa: E402
from src.leitura.file_reader import load_graph_from_csv  # noqa: E402


def _worker_ciclos(caminho: str, fila) -> None:
    """Roda em processo separado para poder ser interrompido pelo timeout."""
    try:
        sys.setrecursionlimit(20000)
        grafo = load_graph_from_csv(caminho)
        t0 = time.perf_counter()
        ciclos = find_cycles(grafo)
        dt = time.perf_counter() - t0
        pares = set()
        n_ciclos = 0
        n_anomalias = 0
        for c in ciclos:
            if c.category != "CICLO":
                n_anomalias += 1  # autotransferência (conta -> ela mesma)
                continue
            n_ciclos += 1
            for a, b in zip(c.path, c.path[1:]):
                pares.add((a, b))
        fila.put(("ok", dt, (n_ciclos, n_anomalias), pares))
    except RecursionError:
        fila.put(("erro", "RecursionError: caminho de DFS muito profundo", (0, 0), set()))
    except Exception as exc:  # noqa: BLE001
        fila.put(("erro", f"{type(exc).__name__}: {exc}", (0, 0), set()))


def _metricas(grafo, pares_sinalizados) -> dict:
    tp = fp = fn = tn = 0
    for e in grafo.edges():
        previsto = (e.source, e.target) in pares_sinalizados
        real = e.is_fraud
        if previsto and real:
            tp += 1
        elif previsto and not real:
            fp += 1
        elif not previsto and real:
            fn += 1
        else:
            tn += 1
    precisao = tp / (tp + fp) if (tp + fp) else 0.0
    revocacao = tp / (tp + fn) if (tp + fn) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precisao": precisao, "revocacao": revocacao}


def _imprimir_metricas(nome: str, m: dict) -> None:
    print(f"  [{nome}]")
    print(f"    Verdadeiros positivos : {m['tp']:,}")
    print(f"    Falsos positivos      : {m['fp']:,}")
    print(f"    Fraudes não detectadas: {m['fn']:,}")
    print(f"    Precisão  : {m['precisao']:.1%}  (dos sinalizados, quantos eram fraude)")
    print(f"    Revocação : {m['revocacao']:.1%}  (das fraudes, quantas foram sinalizadas)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--input", "-i", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=120, help="Segundos para a DFS de ciclos.")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"[ERRO] Arquivo não encontrado: {args.input}", file=sys.stderr)
        return 1

    print("=" * 60)
    print(f"Arquivo: {args.input}")
    print("=" * 60)

    # 1) Leitura
    t0 = time.perf_counter()
    grafo = load_graph_from_csv(args.input)
    t_leitura = time.perf_counter() - t0
    n_fraudes = sum(1 for e in grafo.edges() if e.is_fraud)
    print(f"1) Leitura: {t_leitura:.2f}s | contas={grafo.vertex_count():,} "
          f"| transações={grafo.edge_count():,} | rotuladas fraude={n_fraudes:,}")
    if n_fraudes < 20:
        print("   AVISO: poucas transações de lavagem no recorte; precisão/revocação "
              "não são confiáveis. Gere o CSV com --modo ilicitas.")

    # 2) SCC
    t0 = time.perf_counter()
    sccs = find_scc(grafo)
    t_scc = time.perf_counter() - t0
    suspeitos = [s for s in sccs if s.is_suspicious]
    maior = max((s.size for s in suspeitos), default=0)
    print(f"2) SCC: {t_scc:.2f}s | componentes suspeitos={len(suspeitos):,} | maior={maior:,} contas")

    membro = {}
    for s in suspeitos:
        for v in s.vertices:
            membro[v] = s.component_id
    pares_scc = {
        (e.source, e.target)
        for e in grafo.edges()
        if e.source in membro and membro.get(e.target) == membro[e.source]
    }

    # 3) Ciclos com timeout
    print(f"3) Ciclos (DFS), limite de {args.timeout}s ...")
    fila: mp.Queue = mp.Queue()
    proc = mp.Process(target=_worker_ciclos, args=(str(args.input), fila))
    proc.start()
    proc.join(args.timeout)
    pares_ciclos = None
    if proc.is_alive():
        proc.terminate()
        proc.join()
        print(f"   TEMPO ESGOTADO após {args.timeout}s. A enumeração de ciclos não "
              "escala para este tamanho; use um recorte menor ou limite a DFS.")
    else:
        try:
            status, dado, qtd, pares = fila.get(timeout=5)
        except Exception:  # noqa: BLE001
            status, dado, qtd, pares = "erro", "processo terminou sem resultado", (0, 0), set()
        if status == "ok":
            print(f"   Concluído em {dado:.2f}s | ciclos entre contas (CICLO)={qtd[0]:,} "
                  f"| autotransferências (ANOMALIA)={qtd[1]:,}")
            pares_ciclos = pares
        else:
            print(f"   ERRO: {dado}")

    # 4) Qualidade
    print("4) Qualidade (comparando com o rótulo do dataset):")
    _imprimir_metricas("SCC", _metricas(grafo, pares_scc))
    if pares_ciclos is not None:
        _imprimir_metricas("Ciclos", _metricas(grafo, pares_ciclos))
    else:
        print("  [Ciclos] indisponível (veja o passo 3)")
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
