"""Descreve a estrutura de cada tipo de padrão de lavagem (arquivo da IBM).

Lê apenas o arquivo de padrões (ex.: HI-Small_Patterns.txt) e, para cada tipo
(FAN-OUT, STACK, BIPARTITE, ...), resume como são as tentativas: quantas
transações e contas, qual o maior grau de saída/entrada, em quantos pedaços
desconexos se dividem, qual a profundidade (maior caminho), quanto duram e
quantas moedas e formatos de pagamento usam.

Uso (a partir da raiz do projeto):
    python scripts/caracterizar_padroes.py -p dados/HI-Small_Patterns.txt

Serve para decidir, com dados, se um padrão tem uma estrutura que um detector
de grafo consegue reconhecer (ex.: uma conta central com muitos destinos) ou se
ele é feito de transferências isoladas, indistinguíveis de atividade normal
pela estrutura (nesse caso, só atributos e ML ajudam).

As medianas descrevem o tipo de padrão; "mín–máx" mostra a variação entre
tentativas. "Profundidade" é o maior caminho em número de transações; tentativas
que contêm ciclo aparecem na coluna "% com ciclo" e ficam fora da profundidade.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

PASTA_SCRIPTS = Path(__file__).resolve().parent
if str(PASTA_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PASTA_SCRIPTS))

from analise_por_padrao import RE_FIM, RE_INICIO  # noqa: E402


class Linha(NamedTuple):
    data: datetime
    origem: str
    destino: str
    moeda: str
    formato: str


def ler_tentativas(caminho: Path) -> list[tuple[str, list[Linha]]]:
    """Devolve [(nome_do_padrao, [Linha, ...]), ...] — uma entrada por tentativa."""
    tentativas: list[tuple[str, list[Linha]]] = []
    nome = None
    linhas: list[Linha] = []
    with caminho.open("r", encoding="utf-8", errors="replace") as f:
        for bruta in f:
            texto = bruta.strip()
            if not texto:
                continue
            m = RE_INICIO.match(texto)
            if m:
                nome, linhas = m.group(1).strip().upper(), []
                continue
            if RE_FIM.match(texto):
                if nome is not None:
                    tentativas.append((nome, linhas))
                nome, linhas = None, []
                continue
            if nome is None:
                continue
            c = next(csv.reader([texto]))
            if len(c) < 10:
                continue
            try:
                data = datetime.strptime(c[0].strip(), "%Y/%m/%d %H:%M")
            except ValueError:
                continue
            linhas.append(Linha(
                data=data,
                origem=f"{c[1].strip()}-{c[2].strip()}",
                destino=f"{c[3].strip()}-{c[4].strip()}",
                moeda=c[8].strip(),
                formato=c[9].strip(),
            ))
    return tentativas


def _componentes(arestas: set[tuple[str, str]]) -> int:
    """Número de componentes fracamente conectados (união-busca)."""
    pai: dict[str, str] = {}

    def achar(x: str) -> str:
        pai.setdefault(x, x)
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    for a, b in arestas:
        ra, rb = achar(a), achar(b)
        if ra != rb:
            pai[ra] = rb
    return len({achar(x) for x in list(pai)})


def _profundidade(arestas: set[tuple[str, str]]) -> int | None:
    """Maior caminho (em transações); ``None`` se houver ciclo (Kahn)."""
    adj: dict[str, list[str]] = defaultdict(list)
    grau: dict[str, int] = defaultdict(int)
    for a, b in arestas:
        adj[a].append(b)
        grau[b] += 1
        grau.setdefault(a, grau.get(a, 0))
    nivel = {v: 0 for v, g in grau.items() if g == 0}
    fila = list(nivel)
    visitados = 0
    while fila:
        v = fila.pop()
        visitados += 1
        for w in adj.get(v, ()):
            nivel[w] = max(nivel.get(w, 0), nivel[v] + 1)
            grau[w] -= 1
            if grau[w] == 0:
                fila.append(w)
    if visitados < len(grau):
        return None
    return max(nivel.values(), default=0)


def descrever(linhas: list[Linha]) -> dict:
    arestas = {(l.origem, l.destino) for l in linhas if l.origem != l.destino}
    saida: dict[str, set] = defaultdict(set)
    entrada: dict[str, set] = defaultdict(set)
    for a, b in arestas:
        saida[a].add(b)
        entrada[b].add(a)
    contas = {c for par in arestas for c in par}
    datas = [l.data for l in linhas]
    return {
        "transacoes": len(linhas),
        "contas": len(contas),
        "grau_saida": max((len(v) for v in saida.values()), default=0),
        "grau_entrada": max((len(v) for v in entrada.values()), default=0),
        "componentes": _componentes(arestas),
        "profundidade": _profundidade(arestas),
        "duracao_h": (max(datas) - min(datas)).total_seconds() / 3600 if datas else 0.0,
        "moedas": len({l.moeda for l in linhas}),
        "formatos": len({l.formato for l in linhas}),
    }


def _med(valores) -> str:
    valores = list(valores)
    if not valores:
        return "-"
    m = statistics.median(valores)
    return f"{m:.0f}" if float(m).is_integer() else f"{m:.1f}"


def _faixa(valores) -> str:
    valores = list(valores)
    return f"{min(valores)}–{max(valores)}" if valores else "-"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--patterns", "-p", required=True, type=Path)
    args = parser.parse_args()

    if not args.patterns.exists():
        print(f"[ERRO] Arquivo não encontrado: {args.patterns}", file=sys.stderr)
        return 1

    tentativas = ler_tentativas(args.patterns)
    if not tentativas:
        print("[ERRO] Nenhuma tentativa encontrada no arquivo.", file=sys.stderr)
        return 1

    por_tipo: dict[str, list[dict]] = defaultdict(list)
    for nome, linhas in tentativas:
        por_tipo[nome].append(descrever(linhas))

    print(f"Tentativas: {len(tentativas):,} | tipos: {len(por_tipo)}\n")
    print("ESTRUTURA (mediana por tentativa; entre parênteses, mín–máx de transações)")
    cab = (f"{'Padrão':<16}{'Tent.':>6}{'Transações':>16}{'Contas':>8}{'Saída máx':>11}"
           f"{'Entrada máx':>13}{'Pedaços':>9}{'Profund.':>10}{'% c/ ciclo':>12}")
    print(cab)
    print("-" * len(cab))
    for nome in sorted(por_tipo, key=lambda n: -len(por_tipo[n])):
        d = por_tipo[nome]
        tx = f"{_med(x['transacoes'] for x in d)} ({_faixa(x['transacoes'] for x in d)})"
        prof = [x["profundidade"] for x in d if x["profundidade"] is not None]
        ciclo = sum(1 for x in d if x["profundidade"] is None) / len(d)
        print(f"{nome:<16}{len(d):>6}{tx:>16}{_med(x['contas'] for x in d):>8}"
              f"{_med(x['grau_saida'] for x in d):>11}{_med(x['grau_entrada'] for x in d):>13}"
              f"{_med(x['componentes'] for x in d):>9}{_med(prof):>10}{ciclo:>12.0%}")

    print("\nATRIBUTOS (mediana por tentativa)")
    cab2 = f"{'Padrão':<16}{'Duração (h)':>13}{'Moedas':>8}{'Formatos':>10}"
    print(cab2)
    print("-" * len(cab2))
    for nome in sorted(por_tipo, key=lambda n: -len(por_tipo[n])):
        d = por_tipo[nome]
        print(f"{nome:<16}{_med(x['duracao_h'] for x in d):>13}"
              f"{_med(x['moedas'] for x in d):>8}{_med(x['formatos'] for x in d):>10}")

    # Teto de revocação POR TENTATIVA para cada k: uma tentativa só pode ser
    # detectada por um detector de fan com limiar k se tiver grau >= k.
    print("\nTETO POR TENTATIVA: % das tentativas com grau máximo >= k")
    print("(um detector de fan com limiar k não pode pegar tentativas com grau menor que k,")
    print(" mesmo com janela de tempo ideal; para os padrões mistos usa max(saída, entrada))")
    ks = (4, 5, 6, 8, 10)
    cab3 = f"{'Padrão':<16}" + "".join(f"{'k>=' + str(k):>8}" for k in ks)
    print(cab3)
    print("-" * len(cab3))
    for nome in ("FAN-OUT", "FAN-IN", "GATHER-SCATTER", "SCATTER-GATHER"):
        d = por_tipo.get(nome)
        if not d:
            continue
        graus = [x["grau_saida"] if nome == "FAN-OUT" else
                 x["grau_entrada"] if nome == "FAN-IN" else
                 max(x["grau_saida"], x["grau_entrada"]) for x in d]
        print(f"{nome:<16}" + "".join(f"{sum(1 for g in graus if g >= k) / len(graus):>8.0%}" for k in ks))

    print("\nComo ler: 'Saída máx'/'Entrada máx' = maior número de contas distintas que uma\n"
          "mesma conta alimenta/recebe; 'Pedaços' = grupos de contas sem ligação entre si.\n"
          "Muitos pedaços com grau máx 1 indicam transferências isoladas, que um detector\n"
          "estrutural não separa de atividade normal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())