"""Revocação do NodeWatch por tipo de padrão de lavagem (dataset IBM AML).

Cruza o arquivo de padrões da IBM (ex.: HI-Small_Patterns.txt) com um CSV já
convertido pelo scripts/converter_ibm_aml.py e mostra, para cada tipo de
padrão (CYCLE, FAN-OUT, FAN-IN, ...), quantas transações de lavagem aquele
padrão tem no recorte e quantas o NodeWatch sinalizou (via SCC e via ciclos).

Uso (a partir da raiz do projeto):
    python scripts/analise_por_padrao.py \
        --input dados/ibm_ilicitas_10k.csv \
        --patterns dados/HI-Small_Patterns.txt \
        --timeout 120

Formato esperado do arquivo de padrões:
    BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 16-degree Fan-Out
    2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,...,ACH,1
    ...
    END LAUNDERING ATTEMPT - FAN-OUT

Limitação: a transação do padrão é associada à do recorte pelo par
(conta de origem, conta de destino), sem comparar valor nem horário. Se duas
contas trocam várias transações, todas contam como o mesmo par.
"""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import re
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA_SCRIPTS = Path(__file__).resolve().parent
for p in (str(RAIZ), str(PASTA_SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from benchmark import _worker_ciclos  # noqa: E402
from src.algoritmos.scc import find_scc  # noqa: E402
from src.leitura.file_reader import load_graph_from_csv  # noqa: E402

RE_INICIO = re.compile(r"BEGIN LAUNDERING ATTEMPT\s*-\s*([^:]+?)\s*(?::.*)?$", re.IGNORECASE)
RE_FIM = re.compile(r"END LAUNDERING ATTEMPT", re.IGNORECASE)


def ler_padroes(caminho: Path):
    """Devolve lista de (nome_do_padrao, [(origem, destino), ...]) por tentativa."""
    tentativas = []
    nome = None
    pares: list[tuple[str, str]] = []
    with caminho.open("r", encoding="utf-8", errors="replace") as f:
        for bruta in f:
            linha = bruta.strip()
            if not linha:
                continue
            m = RE_INICIO.match(linha)
            if m:
                nome = m.group(1).strip().upper()
                pares = []
                continue
            if RE_FIM.match(linha):
                if nome is not None:
                    tentativas.append((nome, pares))
                nome, pares = None, []
                continue
            if nome is None:
                continue
            campos = next(csv.reader([linha]))
            if len(campos) < 5:
                continue
            origem = f"{campos[1].strip()}-{campos[2].strip()}"
            destino = f"{campos[3].strip()}-{campos[4].strip()}"
            pares.append((origem, destino))
    return tentativas


def tem_ciclo(pares: list[tuple[str, str]]) -> bool:
    """True se as transações (sem autotransferências) formam algum ciclo.

    Usa a ordenação topológica de Kahn: se sobrar vértice sem poder ser
    removido, existe ciclo.
    """
    adj: dict[str, set[str]] = defaultdict(set)
    grau: dict[str, int] = defaultdict(int)
    for a, b in set(pares):
        if a == b:
            continue
        if b not in adj[a]:
            adj[a].add(b)
            grau[b] += 1
            grau.setdefault(a, grau.get(a, 0))
    pilha = [v for v, g in grau.items() if g == 0]
    removidos = 0
    while pilha:
        v = pilha.pop()
        removidos += 1
        for w in adj.get(v, ()):
            grau[w] -= 1
            if grau[w] == 0:
                pilha.append(w)
    return removidos < len(grau)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--input", "-i", required=True, type=Path, help="CSV convertido (formato NodeWatch).")
    parser.add_argument("--patterns", "-p", required=True, type=Path, help="Arquivo *_Patterns.txt da IBM.")
    parser.add_argument("--timeout", type=int, default=120, help="Segundos para a DFS de ciclos.")
    args = parser.parse_args()

    for arq in (args.input, args.patterns):
        if not arq.exists():
            print(f"[ERRO] Arquivo não encontrado: {arq}", file=sys.stderr)
            return 1

    grafo = load_graph_from_csv(args.input)
    existentes = {(e.source, e.target) for e in grafo.edges()}

    # Pares sinalizados pelo SCC
    suspeitos = [s for s in find_scc(grafo) if s.is_suspicious]
    membro = {v: s.component_id for s in suspeitos for v in s.vertices}
    pares_scc = {
        (e.source, e.target)
        for e in grafo.edges()
        if e.source in membro and membro.get(e.target) == membro[e.source]
    }

    # Pares sinalizados pela DFS de ciclos (com timeout)
    fila: mp.Queue = mp.Queue()
    proc = mp.Process(target=_worker_ciclos, args=(str(args.input), fila))
    proc.start()
    proc.join(args.timeout)
    pares_ciclos: set | None = None
    if proc.is_alive():
        proc.terminate()
        proc.join()
        print(f"[AVISO] DFS de ciclos passou de {args.timeout}s; coluna 'Ciclos' omitida.")
    else:
        try:
            status, dado, _qtd, pares = fila.get(timeout=5)
            if status == "ok":
                pares_ciclos = pares
            else:
                print(f"[AVISO] DFS de ciclos falhou: {dado}")
        except Exception:  # noqa: BLE001
            print("[AVISO] DFS de ciclos terminou sem resultado.")

    # Cruzamento por padrão
    tentativas = ler_padroes(args.patterns)
    if not tentativas:
        print("[ERRO] Nenhuma tentativa de lavagem encontrada no arquivo de padrões.", file=sys.stderr)
        return 1

    tot = defaultdict(lambda: {"tentativas": 0, "no_recorte": 0, "scc": 0, "ciclos": 0})
    for nome, pares in tentativas:
        t = tot[nome]
        t["tentativas"] += 1
        for par in pares:
            if par[0] == par[1] or par not in existentes:
                continue  # autotransferência removida ou fora do recorte
            t["no_recorte"] += 1
            t["scc"] += par in pares_scc
            if pares_ciclos is not None:
                t["ciclos"] += par in pares_ciclos

    # Conferência: as transações rotuladas como lavagem no CSV aparecem no
    # arquivo de padrões? (se não aparecem, não entram na tabela por padrão)
    pares_padroes = {par for _n, pares in tentativas for par in pares}
    rotuladas = [e for e in grafo.edges() if e.is_fraud]
    casadas = [e for e in rotuladas if (e.source, e.target) in pares_padroes]
    nao_casadas = [e for e in rotuladas if (e.source, e.target) not in pares_padroes]
    total_padroes = sum(len(pares) for _n, pares in tentativas)

    print()
    print("Conferência entre o CSV e o arquivo de padrões:")
    print(f"  Transações rotuladas como lavagem no CSV         : {len(rotuladas):,}")
    print(f"    com o par de contas presente nos padrões       : {len(casadas):,}")
    print(f"    SEM correspondência nos padrões                : {len(nao_casadas):,}")
    print(f"  Transações listadas no arquivo de padrões (total): {total_padroes:,}")
    if nao_casadas:
        print("  Exemplos sem correspondência (origem -> destino, tipo):")
        for e in nao_casadas[:5]:
            print(f"    {e.source} -> {e.target}  [{e.transaction_type}]")

    # Quem são as sem correspondência, e quanto o NodeWatch sinaliza em cada grupo
    def _tipos(arestas):
        c: dict[str, int] = defaultdict(int)
        for e in arestas:
            c[(e.transaction_type or "?").upper()] += 1
        return ", ".join(f"{k}={v:,}" for k, v in sorted(c.items(), key=lambda kv: -kv[1]))

    print("  Tipos de transação  - com correspondência :", _tipos(casadas) or "-")
    print("  Tipos de transação  - sem correspondência :", _tipos(nao_casadas) or "-")
    por_origem: dict[str, int] = defaultdict(int)
    for e in nao_casadas:
        por_origem[e.source] += 1
    topo = sorted(por_origem.items(), key=lambda kv: -kv[1])[:3]
    if topo:
        print(f"  Contas de origem distintas nas sem correspondência: {len(por_origem):,}")
        print("  Origens mais frequentes: " + "; ".join(f"{k} ({v}x)" for k, v in topo))

    def _sinalizadas(arestas, pares):
        return sum(1 for e in arestas if (e.source, e.target) in pares)

    sc_c, sc_n = _sinalizadas(casadas, pares_scc), _sinalizadas(nao_casadas, pares_scc)
    print("  Sinalizadas pelo NodeWatch (SCC):")
    print(f"    com correspondência : {sc_c:,} de {len(casadas):,}"
          f" ({sc_c / len(casadas):.0%})" if casadas else "    com correspondência : -")
    print(f"    sem correspondência : {sc_n:,} de {len(nao_casadas):,}"
          f" ({sc_n / len(nao_casadas):.0%})" if nao_casadas else "    sem correspondência : -")

    print()
    print(f"Tentativas de lavagem no arquivo de padrões: {len(tentativas):,}")
    print("Transações de lavagem presentes no recorte, por tipo de padrão:\n")
    cab = f"{'Padrão':<18}{'Tentativas':>11}{'No recorte':>12}{'SCC':>10}{'Ciclos':>10}"
    print(cab)
    print("-" * len(cab))

    def pct(a: int, b: int) -> str:
        return f"{a / b:.0%}" if b else "-"

    for nome in sorted(tot, key=lambda n: -tot[n]["no_recorte"]):
        t = tot[nome]
        ciclos = pct(t["ciclos"], t["no_recorte"]) if pares_ciclos is not None else "n/d"
        print(f"{nome:<18}{t['tentativas']:>11,}{t['no_recorte']:>12,}"
              f"{pct(t['scc'], t['no_recorte']):>10}{ciclos:>10}")
    print("\nSCC e Ciclos = % das transações do padrão, presentes no recorte, que o "
          "NodeWatch sinalizou.")

    # Teste independente do recorte: o formato do próprio padrão contém ciclo?
    intr = defaultdict(lambda: [0, 0])  # nome -> [tentativas, com ciclo próprio]
    for nome, pares in tentativas:
        intr[nome][0] += 1
        intr[nome][1] += tem_ciclo(pares)
    print("\nTeste do formato do padrão (independente do recorte):")
    print("% das tentativas cujas PRÓPRIAS transações já formam um ciclo.\n")
    cab2 = f"{'Padrão':<18}{'Tentativas':>11}{'Com ciclo próprio':>20}"
    print(cab2)
    print("-" * len(cab2))
    for nome in sorted(intr, key=lambda n: -intr[n][1] / max(intr[n][0], 1)):
        t, c = intr[nome]
        print(f"{nome:<18}{t:>11,}{pct(c, t):>20}")
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())