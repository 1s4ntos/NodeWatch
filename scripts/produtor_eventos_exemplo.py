"""Produtor de exemplo para a API de ingestão de eventos do NodeWatch.

Lê um arquivo existente e envia os registros, em ordem cronológica, para
``POST /api/ml/eventos``. Como os dados vêm de um arquivo antigo, os eventos
saem com ``modo = "replay_historico"`` (use ``--modo novo_evento`` só quando o
produtor estiver ligado a uma fonte que gera eventos agora).

Autorização: o produtor **usa** uma sessão que já existe na interface; ele não abre
nem renova sessões. Abra ``http://127.0.0.1:5000/legado#ml/eventos`` (interface antiga), use *Iniciar
processamento* e copie o comando mostrado na tela, que já traz ``--sessao``. Se a
aba for fechada ou a sessão encerrada, o envio é recusado e o produtor para:
ele não mantém o processamento vivo depois disso.

Uso (com o servidor rodando: ``python src/sentinel_ai.py``)::

    python scripts/produtor_eventos_exemplo.py --sessao <id> --tipo financeiro --limite 2000
    python scripts/produtor_eventos_exemplo.py --sessao <id> --tipo rede --limite 500 --eventos-por-segundo 50

Só usa a biblioteca padrão. Fila cheia (HTTP 429) é respeitada: o produtor
espera e reenvia apenas os eventos recusados por ``fila_cheia``. Retransmitir é
seguro: o que já foi aceito volta em ``ja_aceitos`` e não é refeito.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, List

RAIZ = Path(__file__).resolve().parent.parent
EXEMPLOS = RAIZ / "artefatos_ml" / "exemplos"
NAO_ENVIAR_REDE = {"alvo", "split"}


def transacoes(caminho: Path) -> Iterator[Dict[str, Any]]:
    """CSV do HI-Small (cabeçalho com 'Account' repetido) → eventos ``transacao``."""
    with open(caminho, newline="", encoding="utf-8-sig") as fh:
        leitor = csv.reader(fh)
        next(leitor)
        linhas = [(i, r) for i, r in enumerate(leitor)]
    linhas.sort(key=lambda x: x[1][0])  # 'AAAA/MM/DD HH:MM' ordena como texto; estável
    for i, r in linhas:
        yield {"tipo": "transacao", "versao_esquema": "transacao_hismall_v1", "dados": {
            "id_transacao": f"{caminho.name}#{i}", "timestamp": r[0],
            "banco_origem": r[1], "conta_origem": r[2], "banco_destino": r[3], "conta_destino": r[4],
            "valor_recebido": float(r[5]), "moeda_recebimento": r[6],
            "valor_pago": float(r[7]), "moeda_pagamento": r[8], "formato": r[9]}}


def medicoes(caminho: Path) -> Iterator[Dict[str, Any]]:
    """CSV ``rede_v1`` (atributos já preparados) → eventos ``medicao_rede``."""
    with open(caminho, newline="", encoding="utf-8") as fh:
        linhas = list(csv.DictReader(fh))
    linhas.sort(key=lambda r: int(float(r["timestamp"])))
    for r in linhas:
        dados: Dict[str, Any] = {}
        for k, v in r.items():
            if k in NAO_ENVIAR_REDE:
                continue
            if k in ("id_fluxo", "classe_atual"):
                dados[k] = v
            else:
                dados[k] = float(v) if any(ch in v for ch in ".eE") else int(v)
        yield {"tipo": "medicao_rede", "versao_esquema": "rede_v1", "dados": dados}


class EnvioRecusado(RuntimeError):
    """O servidor recusou o pedido inteiro; repetir não adianta sem uma ação do usuário."""


def enviar(url: str, eventos: List[Dict[str, Any]], origem: str, modo: str, sessao: str) -> Dict[str, Any]:
    corpo = json.dumps({"eventos": eventos, "origem": origem, "modo": modo}).encode()
    req = urllib.request.Request(url, data=corpo, method="POST",
                                 headers={"Content-Type": "application/json", "X-NodeWatch-Sessao": sessao})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return json.loads(exc.read())
        try:
            detalhe = json.loads(exc.read())
        except ValueError:
            detalhe = {}
        rotulo = {403: "sessão ausente, expirada ou encerrada",
                  409: "processamento não iniciado por esta sessão"}.get(exc.code, f"HTTP {exc.code}")
        raise EnvioRecusado(f"{rotulo}. {detalhe.get('erro', '')} {detalhe.get('acao', '')}".strip()) from None
    except urllib.error.URLError as exc:
        raise EnvioRecusado(f"servidor inacessível em {url}: {exc.reason}") from None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sessao", required=True, help="sessão ativa da interface (aparece na área Eventos)")
    p.add_argument("--tipo", choices=("financeiro", "rede"), required=True)
    p.add_argument("--arquivo", type=Path, help="padrão: o exemplo de artefatos_ml/exemplos")
    p.add_argument("--url", default="http://127.0.0.1:5000/api/ml/eventos")
    p.add_argument("--limite", type=int, default=0, help="quantos eventos enviar (0 = todos)")
    p.add_argument("--lote", type=int, default=200)
    p.add_argument("--eventos-por-segundo", type=float, default=0, help="0 = sem limite")
    p.add_argument("--modo", choices=("replay_historico", "novo_evento", "simulacao"), default="replay_historico")
    args = p.parse_args()

    padrao = {"financeiro": EXEMPLOS / "hismall_2022-09-10_sem_rotulo.csv",
              "rede": EXEMPLOS / "rede_teste_sem_rotulos.csv"}[args.tipo]
    arquivo = args.arquivo or padrao
    if not arquivo.is_file():
        print(f"Arquivo não encontrado: {arquivo}. Gere os exemplos com `python -m src.ml.cli exemplos`.")
        return 2
    fonte = transacoes(arquivo) if args.tipo == "financeiro" else medicoes(arquivo)
    origem = f"produtor_exemplo:{arquivo.name}"
    aceitos = recusados = ja_aceitos = 0
    inicio = time.monotonic()
    lote: List[Dict[str, Any]] = []

    def despachar(eventos: List[Dict[str, Any]]) -> None:
        nonlocal aceitos, recusados, ja_aceitos
        pendentes = eventos
        while pendentes:
            r = enviar(args.url, pendentes, origem, args.modo, args.sessao)
            aceitos += r["aceitos"]
            ja_aceitos += len(r.get("ja_aceitos", []))
            cheios = [x for x in r["recusados"] if x["motivo"] == "fila_cheia"]
            outros = [x for x in r["recusados"] if x["motivo"] != "fila_cheia"]
            recusados += len(outros)
            for x in outros[:3]:
                print("recusado:", x.get("id_evento"), "-", "; ".join(x.get("problemas", [])))
            ids = {x["id_evento"] for x in cheios}
            pendentes = [e for e in pendentes if _id(e) in ids]
            if pendentes:
                time.sleep(1.0)

    try:
        for n, evento in enumerate(fonte, start=1):
            lote.append(evento)
            if len(lote) >= args.lote:
                despachar(lote)
                lote = []
            if args.eventos_por_segundo > 0:
                atraso = n / args.eventos_por_segundo - (time.monotonic() - inicio)
                if atraso > 0:
                    time.sleep(atraso)
            if args.limite and n >= args.limite:
                break
        if lote:
            despachar(lote)
    except EnvioRecusado as exc:
        print(f"Envio interrompido depois de {aceitos} aceitos: {exc}")
        print("O que foi aceito continua no registro durável; reenviar depois é seguro. O produtor não "
              "renova sessões: volte à interface e inicie ou assuma o processamento.")
        return 3
    dur = time.monotonic() - inicio
    print(f"{aceitos} aceitos (duráveis), {ja_aceitos} já aceitos antes, {recusados} recusados em {dur:.1f} s "
          f"({origem}, modo {args.modo}).")
    if args.tipo == "financeiro":
        print("Com modo replay_historico, as transações do último minuto ficam abertas até chegar um minuto "
              "posterior ou até usar Fechar minutos abertos. Com novo_evento, o relógio também fecha "
              "depois do fim do minuto + atraso permitido + carência.")
    return 0


def _id(e: Dict[str, Any]) -> str:
    d = e["dados"]
    return f"tx:{d['id_transacao']}" if e["tipo"] == "transacao" else f"rede:{d['id_fluxo']}@{int(d['timestamp'])}"


if __name__ == "__main__":
    sys.exit(main())
