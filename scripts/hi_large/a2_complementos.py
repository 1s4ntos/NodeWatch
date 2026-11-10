"""Conferências complementares do perfil (rápidas; não leem as transações de novo).

* Bancos cujo código só difere por zeros à esquerda: o arquivo de contas mostra
  um único nome de banco por número? Isso sustenta a identidade ``banco-conta``
  com banco numérico, usada pelo NodeWatch.
* Duração das tentativas de lavagem no HI-Small, para comparar com o HI-Large.
* Prevalência do período principal (sem a cauda) e da janela de 12 dias.

Uso::

    python scripts/hi_large/a2_complementos.py --dados <pasta do HI-Large>
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path
from typing import Any, Dict

import pandas as pd

import comum
from src.ml.config import carregar_config
from src.ml.ingestao import ler_padroes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dados")
    ap.add_argument("--prefixo", default="HI-Large", help="prefixo dos arquivos IBM AML (padrão: HI-Large)")
    a = ap.parse_args()
    pasta = comum.pasta_dados(a.dados)
    perfil = comum.ler_json("a_perfil.json")
    t = perfil["transacoes"]
    saida: Dict[str, Any] = {"gerado_em_utc": comum.agora(), "script": Path(__file__).name}

    # Bancos fundidos pelo número: nomes de banco no cadastro de contas.
    fundidos = {int(k) for k in t["bancos"]["exemplos_fundidos"]}
    contas = pd.read_csv(pasta / comum.nomes_arquivos(a.prefixo)["contas"], dtype=str, usecols=["Bank Name", "Bank ID"])
    contas["banco"] = contas["Bank ID"].astype("int64")
    nomes = contas.groupby("banco")["Bank Name"].nunique()
    saida["bancos"] = {
        "numeros_com_mais_de_um_nome_no_cadastro": int((nomes > 1).sum()),
        "numeros_distintos_no_cadastro": int(len(nomes)),
        "exemplos_fundidos_verificados": {str(b): int(nomes.get(b, 0)) for b in sorted(fundidos)},
        "nota": ("O relatório de perfil guarda só 10 exemplos dos códigos fundidos; o total é "
                 f"{t['bancos']['codigos_fundidos_pelo_inteiro']}."),
    }

    # Cauda e prevalência.
    por_dia = t["por_dia"]
    mediana = statistics.median(v["n"] for v in por_dia.values())
    cauda = {d: v for d, v in por_dia.items() if v["n"] < 0.01 * mediana}
    principal = {d: v for d, v in por_dia.items() if d not in cauda}
    janela = dict(list(sorted(principal.items()))[:12])

    def resumo(dias: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        n = sum(v["n"] for v in dias.values())
        p = sum(v["positivos"] for v in dias.values())
        return {"dias": len(dias), "primeiro": min(dias), "ultimo": max(dias), "transacoes": n, "positivos": p,
                "prevalencia": p / n if n else None}

    saida["periodos"] = {"mediana_transacoes_por_dia": mediana, "principal": resumo(principal),
                         "cauda": resumo(cauda), "janela_12_dias": resumo(janela)}
    for nome, dias in (("treino", range(0, 6)), ("validacao", range(6, 8)), ("teste", range(8, 10)),
                       ("reserva", range(10, 12))):
        saida["periodos"][f"janela_{nome}"] = resumo({d: janela[d] for i, d in enumerate(sorted(janela)) if i in dias})

    # Duração das tentativas no HI-Small (mesmo cálculo do perfil do HI-Large).
    cfg = carregar_config()
    if cfg["financeiro"].get("padroes"):
        pp = ler_padroes(cfg["financeiro"]["padroes"])
        g = pp.groupby("tentativa")["minuto"].agg(["min", "max"])
        dur = (g["max"] - g["min"]) / 60
        saida["hismall_duracao_tentativa_horas"] = {q: float(dur.quantile(q)) for q in (0.5, 0.9, 0.99)} | {
            "max": float(dur.max()), "tentativas": int(len(g))}
    saida["hilarge_duracao_tentativa_horas"] = perfil["padroes"]["duracao_tentativa_horas"]

    # Contas em comum com o HI-Small: mesma chave banco-conta, mesma entidade?
    if cfg["financeiro"].get("contas"):
        def chaves(caminho) -> pd.DataFrame:
            df = pd.read_csv(caminho, dtype=str, usecols=["Bank ID", "Account Number", "Entity Name"])
            df["conta"] = df["Bank ID"].astype("int64").astype(str) + "-" + df["Account Number"].str.strip()
            return df.set_index("conta")["Entity Name"]
        hs, hl = chaves(cfg["financeiro"]["contas"]), chaves(pasta / comum.nomes_arquivos(a.prefixo)["contas"])
        comuns = hs.index.intersection(hl.index)
        saida["contas_em_comum_com_hismall"] = {
            "contas_hismall": int(len(hs)), "contas_hilarge": int(len(hl)), "chaves_em_comum": int(len(comuns)),
            "em_comum_com_mesmo_nome_de_entidade": int((hs.loc[comuns] == hl.loc[comuns]).sum()),
        }
    print(comum.salvar_json(saida, "a2_complementos.json"))


if __name__ == "__main__":
    main()
