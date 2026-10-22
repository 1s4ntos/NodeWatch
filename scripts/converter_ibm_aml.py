"""Converte o dataset IBM AML (Kaggle) para o formato lido pelo NodeWatch.

Entrada (colunas do arquivo da IBM, ex.: HI-Small_Trans.csv):
    Timestamp, From Bank, Account, To Bank, Account, Amount Received,
    Receiving Currency, Amount Paid, Payment Currency, Payment Format,
    Is Laundering
(a coluna "Account" aparece duas vezes: a primeira é a conta de origem e a
segunda a de destino; versões lidas pelo pandas chamam a segunda de
"Account.1", e este script aceita as duas formas)

Saída (formato esperado por src/leitura/file_reader.py):
    step,type,amount,nameOrig,nameDest,isFraud

Uso (a partir da raiz do projeto):

    # Recorte simples: as N primeiras linhas do arquivo
    python scripts/converter_ibm_aml.py -i dados/HI-Small_Trans.csv \
        -o dados/ibm_inicio_20k.csv --max-linhas 20000

    # Recorte que GARANTE exemplos de lavagem (recomendado para avaliar)
    python scripts/converter_ibm_aml.py -i dados/HI-Small_Trans.csv \
        -o dados/ibm_ilicitas_20k.csv --modo ilicitas \
        --max-ilicitas 200 --max-linhas 20000

    # Recorte de VALIDAÇÃO: usa outras sementes (pula as 3000 primeiras
    # transações de lavagem), para não avaliar nos mesmos dados em que os
    # parâmetros foram escolhidos
    python scripts/converter_ibm_aml.py -i dados/HI-Small_Trans.csv \
        -o dados/ibm_val_50k.csv --modo ilicitas \
        --pular-ilicitas 3000 --max-ilicitas 1000 --max-linhas 50000

Modos de recorte:
  inicio    Pega as N primeiras linhas. Simples, mas as primeiras linhas do
            arquivo podem ter pouquíssimas (ou nenhuma) transação de lavagem,
            o que torna precisão/revocação sem sentido.
  ilicitas  Lê o arquivo todo, escolhe as primeiras --max-ilicitas transações
            de lavagem, coleta as contas envolvidas e grava (1) todas essas
            transações de lavagem e (2) as demais transações que tocam
            essas contas, até o limite --max-linhas. Assim a "vizinhança"
            das contas suspeitas fica completa e há ruído legítimo ao redor.
            Com --pular-ilicitas N, ignora as N primeiras transações de
            lavagem do arquivo antes de escolher as sementes; isso gera um
            recorte diferente (e mais tardio no tempo) para validação. As
            vizinhanças de sementes diferentes ainda podem se sobrepor.

Autotransferências (conta -> ela mesma, comuns em "Reinvestment" e em
pagamentos internos) são REMOVIDAS por padrão, porque no dataset da IBM a
grande maioria é legítima e elas escondem os ciclos entre contas diferentes.
Use --manter-autotransferencias para mantê-las (o NodeWatch as classifica
como "ANOMALIA", não como "CICLO").

O mapeamento de "Payment Format" para os tipos do NodeWatch (TRANSFER,
CASH_OUT, PAYMENT, CASH_IN, DEBIT) é uma ESCOLHA de modelagem, definida em
``MAPA_TIPOS``. Ajuste se quiser outro critério de prioridade.

O arquivo é lido linha a linha (streaming): não carrega os milhões de
linhas na memória.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterator, NamedTuple

COLUNAS_ENTRADA = {
    "Timestamp",
    "From Bank",
    "To Bank",
    "Amount Paid",
    "Payment Format",
    "Is Laundering",
}
NOMES_CONTA = ("Account", "Account.1")

# O NodeWatch dá prioridade de risco por tipo (cycle_detection.py, RN03).
# Tipos desconhecidos caem em BAIXO, então é preciso traduzir.
MAPA_TIPOS = {
    "ACH": "TRANSFER",
    "Wire": "TRANSFER",
    "Bitcoin": "TRANSFER",
    "Cash": "CASH_OUT",
    "Cheque": "PAYMENT",
    "Credit Card": "PAYMENT",
    "Reinvestment": "CASH_IN",
}
TIPO_PADRAO = "PAYMENT"

FORMATOS_DATA = ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


class Transacao(NamedTuple):
    data: datetime
    origem: str
    destino: str
    valor: str
    formato: str
    ilicita: int


def _parse_data(texto: str) -> datetime:
    for formato in FORMATOS_DATA:
        try:
            return datetime.strptime(texto.strip(), formato)
        except ValueError:
            continue
    raise ValueError(f"Formato de data não reconhecido: {texto!r}")


def _ler(entrada: Path) -> Iterator[Transacao]:
    """Lê o arquivo da IBM linha a linha, tratando o cabeçalho duplicado."""
    if not entrada.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {entrada}")

    with entrada.open("r", encoding="utf-8", newline="") as fin:
        leitor = csv.reader(fin)
        cabecalho = next(leitor, None)
        if not cabecalho:
            raise ValueError("Arquivo vazio ou sem cabeçalho.")
        cabecalho = [c.strip() for c in cabecalho]
        faltando = COLUNAS_ENTRADA - set(cabecalho)
        pos_contas = [i for i, c in enumerate(cabecalho) if c in NOMES_CONTA]
        if faltando or len(pos_contas) != 2:
            raise ValueError(
                f"Colunas ausentes: {sorted(faltando)}; colunas de conta "
                f"encontradas: {len(pos_contas)} (esperado: 2). "
                f"Cabeçalho recebido: {cabecalho}"
            )
        i_data = cabecalho.index("Timestamp")
        i_banco_o = cabecalho.index("From Bank")
        i_banco_d = cabecalho.index("To Bank")
        i_valor = cabecalho.index("Amount Paid")
        i_formato = cabecalho.index("Payment Format")
        i_rotulo = cabecalho.index("Is Laundering")
        i_conta_o, i_conta_d = pos_contas

        for linha in leitor:
            if not linha:
                continue
            yield Transacao(
                data=_parse_data(linha[i_data]),
                origem=f"{linha[i_banco_o].strip()}-{linha[i_conta_o].strip()}",
                destino=f"{linha[i_banco_d].strip()}-{linha[i_conta_d].strip()}",
                valor=linha[i_valor].strip(),
                formato=linha[i_formato].strip(),
                ilicita=1 if linha[i_rotulo].strip() == "1" else 0,
            )


def converter(
    entrada: Path,
    saida: Path,
    max_linhas: int | None,
    modo: str = "inicio",
    max_ilicitas: int = 200,
    manter_auto: bool = False,
    pular_ilicitas: int = 0,
) -> dict:
    # --- Passo A: data base e (no modo ilicitas) contas suspeitas -----------
    primeira_data: datetime | None = None
    contas_alvo: set[str] = set()
    ilicitas_escolhidas = 0

    if modo == "ilicitas":
        candidatas_vistas = 0
        for t in _ler(entrada):
            if primeira_data is None:
                primeira_data = t.data
            if t.ilicita and (t.origem != t.destino or manter_auto):
                candidatas_vistas += 1
                if candidatas_vistas <= pular_ilicitas:
                    continue  # reservadas para outro recorte
                contas_alvo.add(t.origem)
                contas_alvo.add(t.destino)
                ilicitas_escolhidas += 1
                if ilicitas_escolhidas >= max_ilicitas:
                    break  # sementes completas; não precisa ler o resto
        if not contas_alvo:
            raise ValueError("Nenhuma transação de lavagem encontrada no arquivo.")
    else:
        for t in _ler(entrada):
            primeira_data = t.data
            break

    if primeira_data is None:
        raise ValueError("Arquivo sem transações.")

    # --- Passo B: gravação ---------------------------------------------------
    stats = {
        "linhas": 0,
        "ilicitas": 0,
        "autotransferencias_removidas": 0,
        "contas": set(),
        "tipos_nao_mapeados": set(),
    }

    def _linha_saida(t: Transacao) -> list:
        step = int((t.data - primeira_data).total_seconds() // 3600)
        if t.formato not in MAPA_TIPOS:
            stats["tipos_nao_mapeados"].add(t.formato)
        tipo = MAPA_TIPOS.get(t.formato, TIPO_PADRAO)
        return [step, tipo, t.valor, t.origem, t.destino, t.ilicita]

    def _registrar(t: Transacao) -> None:
        stats["linhas"] += 1
        stats["ilicitas"] += t.ilicita
        stats["contas"].add(t.origem)
        stats["contas"].add(t.destino)

    with saida.open("w", encoding="utf-8", newline="") as fout:
        escritor = csv.writer(fout)
        escritor.writerow(["step", "type", "amount", "nameOrig", "nameDest", "isFraud"])

        if modo == "inicio":
            for t in _ler(entrada):
                if max_linhas is not None and stats["linhas"] >= max_linhas:
                    break
                if t.origem == t.destino and not manter_auto:
                    stats["autotransferencias_removidas"] += 1
                    continue
                escritor.writerow(_linha_saida(t))
                _registrar(t)
        else:
            # Prioridade: todas as transações de lavagem das contas-alvo;
            # depois, as demais que tocam essas contas, até o limite.
            vizinhas = []
            for t in _ler(entrada):
                if t.origem == t.destino and not manter_auto:
                    stats["autotransferencias_removidas"] += 1
                    continue
                if t.origem in contas_alvo or t.destino in contas_alvo:
                    if t.ilicita:
                        escritor.writerow(_linha_saida(t))
                        _registrar(t)
                    else:
                        vizinhas.append(t)
            for t in vizinhas:
                if max_linhas is not None and stats["linhas"] >= max_linhas:
                    break
                escritor.writerow(_linha_saida(t))
                _registrar(t)

    stats["contas"] = len(stats["contas"])
    stats["tipos_nao_mapeados"] = sorted(stats["tipos_nao_mapeados"])
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--input", "-i", required=True, type=Path)
    parser.add_argument("--output", "-o", required=True, type=Path)
    parser.add_argument("--max-linhas", type=int, default=None,
                        help="Limite de linhas no arquivo de saída.")
    parser.add_argument("--modo", choices=["inicio", "ilicitas"], default="inicio",
                        help="Estratégia de recorte (veja a documentação do script).")
    parser.add_argument("--max-ilicitas", type=int, default=200,
                        help="Modo ilicitas: quantas transações de lavagem usar como semente.")
    parser.add_argument("--pular-ilicitas", type=int, default=0,
                        help="Modo ilicitas: ignora as N primeiras transações de lavagem "
                             "antes de escolher as sementes (recorte de validação).")
    parser.add_argument("--manter-autotransferencias", action="store_true",
                        help="Não remover transações de uma conta para ela mesma.")
    args = parser.parse_args()

    try:
        r = converter(args.input, args.output, args.max_linhas, args.modo,
                      args.max_ilicitas, args.manter_autotransferencias,
                      args.pular_ilicitas)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        return 1

    print(f"Arquivo gerado: {args.output}  (modo: {args.modo})")
    print(f"  Transações convertidas        : {r['linhas']:,}")
    print(f"  Marcadas como lavagem         : {r['ilicitas']:,}")
    print(f"  Contas distintas              : {r['contas']:,}")
    print(f"  Autotransferências removidas  : {r['autotransferencias_removidas']:,}")
    if r["ilicitas"] == 0:
        print("  AVISO: nenhuma transação de lavagem no recorte; use --modo ilicitas.")
    if r["tipos_nao_mapeados"]:
        print(f"  AVISO: formatos sem mapeamento (usaram {TIPO_PADRAO}): "
              f"{r['tipos_nao_mapeados']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())