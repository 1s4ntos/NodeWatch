"""Linha de comando do módulo de ML.

Exemplos (a partir da raiz do projeto, com o .venv ativo)::

    python -m src.ml.cli auditar --fonte rede
    python -m src.ml.cli treinar --tarefa todas
    python -m src.ml.cli avaliar --tarefa todas
    python -m src.ml.cli prever --tarefa estado_rede --entrada novo.csv --saida previsoes.csv
    python -m src.ml.cli prever --tarefa lavagem --entrada trans.csv --historico HI-Small_Trans.zip --saida p.csv
    python -m src.ml.cli exemplos
    python -m src.ml.cli tarefas
    python -m src.ml.cli relatorio
    python -m src.ml.cli documentar
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from src.ml import auditoria, experimentos
from src.ml.config import carregar_config, pasta_artefatos
from src.ml.modelos import FusaoIndisponivel, ModeloUnificado

TAREFAS_TREINO = ("estado_rede", "lavagem", "fusao_rede_transacao", "todas")


def _cmd_auditar(cfg, args) -> int:
    pasta = pasta_artefatos(cfg) / "auditoria"
    if args.fonte in ("rede", "todas"):
        from src.ml.ingestao import ler_rede
        df, rel = ler_rede(cfg["rede"]["arquivos"], modo="treino", conflitos=cfg["rede"]["conflitos"])
        a = auditoria.auditar_rede(df, cfg["rede"]["multiplo_intervalo_consecutivo"])
        a["ingestao"] = rel
        print("auditoria de rede:", auditoria.salvar(a, pasta, "auditoria_rede"))
    if args.fonte in ("financeiro", "todas"):
        dados, contas, casados, pendentes = experimentos._carregar_financeiro(cfg)
        a = auditoria.auditar_financeiro(dados, cfg["financeiro"], contas, casados)
        a["arquivos_pendentes"] = pendentes
        print("auditoria financeira:", auditoria.salvar(a, pasta, "auditoria_financeiro"))
    return 0


def _cmd_treinar(cfg, args) -> int:
    if args.tarefa in ("estado_rede", "todas"):
        experimentos.treinar_estado_rede(cfg)
    if args.tarefa in ("lavagem", "todas"):
        experimentos.treinar_lavagem(cfg)
    if args.tarefa in ("fusao_rede_transacao", "todas"):
        modelo = ModeloUnificado.carregar_ou_novo(pasta_artefatos(cfg))
        try:
            modelo.cabecas["fusao_rede_transacao"].treinar()
        except FusaoIndisponivel as exc:
            print(exc)
            if args.tarefa == "fusao_rede_transacao":
                return 2
    return 0


def _cmd_avaliar(cfg, args) -> int:
    if args.tarefa in ("estado_rede", "todas"):
        experimentos.avaliar_estado_rede(cfg)
    if args.tarefa in ("lavagem", "todas"):
        experimentos.avaliar_lavagem(cfg)
    return 0


def _cmd_prever(cfg, args) -> int:
    modelo = ModeloUnificado.carregar(pasta_artefatos(cfg))
    if args.tarefa.startswith("estado_rede"):
        saida, rel = modelo.prever(args.tarefa, args.entrada)
    elif args.tarefa == "lavagem":
        if len(args.entrada) != 1:
            raise SystemExit("A tarefa lavagem aceita um arquivo de entrada por vez.")
        saida, rel = modelo.prever("lavagem", args.entrada[0], historico=args.historico)
    else:
        modelo.cabeca(args.tarefa)
        return 2
    destino = Path(args.saida)
    destino.parent.mkdir(parents=True, exist_ok=True)
    saida.to_csv(destino, index=False)
    destino.with_suffix(".relatorio.json").write_text(
        json.dumps(rel, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"{len(saida)} previsões em {destino}")
    deriva = rel.get("deriva", {}).get("colunas_psi_acima_0_25")
    if deriva:
        print(f"Atenção: mudança de distribuição (PSI >= 0,25) em {deriva}")
    return 0


def _cmd_exemplos(cfg, args) -> int:
    pasta = pasta_artefatos(cfg) / "exemplos"
    modelo = ModeloUnificado.carregar(pasta_artefatos(cfg))
    tarefas = modelo.tarefas_disponiveis()
    if tarefas.get("estado_rede") == "treinada":
        entrada = experimentos.gerar_exemplo_rede(cfg)
        saida, rel = modelo.prever("estado_rede", [entrada])
        saida.to_csv(pasta / "previsoes_rede_exemplo.csv", index=False)
        (pasta / "previsoes_rede_exemplo.relatorio.json").write_text(
            json.dumps(rel, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"rede: {len(saida)} previsões a partir de {entrada.name}")
    if tarefas.get("lavagem") == "treinada":
        entrada = experimentos.gerar_exemplo_lavagem(cfg)
        saida, rel = modelo.prever("lavagem", entrada, historico=cfg["financeiro"]["transacoes"])
        saida.to_csv(pasta / "previsoes_lavagem_exemplo.csv", index=False)
        (pasta / "previsoes_lavagem_exemplo.relatorio.json").write_text(
            json.dumps(rel, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"lavagem: {len(saida)} previsões a partir de {entrada.name}")
    return 0


def _cmd_tarefas(cfg, args) -> int:
    modelo = ModeloUnificado.carregar_ou_novo(pasta_artefatos(cfg))
    for nome, status in modelo.tarefas_disponiveis().items():
        print(f"{nome}: {status}")
    fusao = modelo.cabecas.get("fusao_rede_transacao")
    if fusao is not None and fusao.status != "treinada":
        print("\nfusao_rede_transacao —", fusao.motivo)
        for r in fusao.requisitos:
            print("  pendente:", r)
    return 0


def _cmd_relatorio(cfg, args) -> int:
    from src.ml.relatorio import gerar_relatorio
    print("relatório:", gerar_relatorio(pasta_artefatos(cfg), Path(cfg["geral"]["pasta_docs"])))
    return 0


def _cmd_documentar(cfg, args) -> int:
    from src.ml.relatorio import escrever_documentacao
    for p in escrever_documentacao(Path(cfg["geral"]["pasta_docs"])):
        print(p)
    return 0


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m src.ml.cli", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="arquivo TOML (padrão: ml_config.local.toml ou ml_config.exemplo.toml)")
    sub = p.add_subparsers(dest="comando", required=True)
    a = sub.add_parser("auditar", help="audita os dados e grava JSON/MD em artefatos_ml/auditoria")
    a.add_argument("--fonte", choices=("rede", "financeiro", "todas"), default="todas")
    a.set_defaults(func=_cmd_auditar)
    t = sub.add_parser("treinar", help="ajusta no treino e escolhe na validação")
    t.add_argument("--tarefa", choices=TAREFAS_TREINO, default="todas")
    t.set_defaults(func=_cmd_treinar)
    v = sub.add_parser("avaliar", help="avaliação final no teste com o artefato congelado")
    v.add_argument("--tarefa", choices=("estado_rede", "lavagem", "todas"), default="todas")
    v.set_defaults(func=_cmd_avaliar)
    pr = sub.add_parser("prever", help="inferência em arquivos novos (sem reajuste)")
    pr.add_argument("--tarefa", required=True,
                    choices=("estado_rede", "estado_rede__com_classe_atual", "lavagem", "fusao_rede_transacao"))
    pr.add_argument("--entrada", nargs="+", required=True)
    pr.add_argument("--historico", help="(lavagem) transações anteriores para o histórico das contas")
    pr.add_argument("--saida", required=True)
    pr.set_defaults(func=_cmd_prever)
    e = sub.add_parser("exemplos", help="gera entradas derivadas sem rótulo e suas previsões")
    e.set_defaults(func=_cmd_exemplos)
    ta = sub.add_parser("tarefas", help="lista as cabeças do modelo unificado e seu status")
    ta.set_defaults(func=_cmd_tarefas)
    r = sub.add_parser("relatorio", help="gera docs/ml/RELATORIO_ML.md a partir dos resultados salvos")
    r.set_defaults(func=_cmd_relatorio)
    d = sub.add_parser("documentar", help="gera o dicionário de dados e os esquemas em docs/ml")
    d.set_defaults(func=_cmd_documentar)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = construir_parser().parse_args(argv)
    cfg = carregar_config(args.config)
    try:
        return args.func(cfg, args)
    except FusaoIndisponivel as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
