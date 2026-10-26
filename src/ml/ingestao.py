"""Ingestão e validação dos dados de rede e do IBM AML HI-Small.

Nenhuma função daqui altera os arquivos de entrada. Cada registro lido recebe
``arquivo_origem`` e ``linha_origem`` (posição 0-based dentro do arquivo), o
que permite devolver as previsões na identidade e ordem originais.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from src.ml.esquemas import (
    COLUNAS_HISMALL,
    ESQUEMA_HISMALL_V1,
    ESQUEMA_REDE_V1,
    SPLITS,
    ErroEsquema,
)

Caminho = Union[str, Path]
CHAVE_REDE = ("id_fluxo", "timestamp")
COLUNAS_RASTREIO = ("arquivo_origem", "linha_origem")


class ErroDados(ValueError):
    """Dados válidos no esquema, mas inconsistentes (duplicatas, splits...)."""


def sha256_arquivo(caminho: Caminho, bloco: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for parte in iter(lambda: fh.read(bloco), b""):
            h.update(parte)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
_DTYPES_TEXTO_REDE = {"id_fluxo": str, "split": str, "classe_atual": str, "alvo": str}


def ler_rede(
    caminhos: Sequence[Caminho],
    modo: str = "treino",
    conflitos: str = "erro",
    exigir: Sequence[str] = (),
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Lê um ou mais CSVs ``rede_v1``.

    Em ``modo="treino"``, duplicatas idênticas por ``id_fluxo`` + ``timestamp``
    são removidas (mantém a primeira, na ordem dos arquivos) e duplicatas com
    valores diferentes geram :class:`ErroDados` (``conflitos="erro"``) ou são
    excluídas por completo (``conflitos="excluir"``). Em ``modo="inferencia"``
    nada é removido: as duplicatas só são relatadas, para preservar a
    identidade de cada linha de entrada.

    Returns:
        ``(df, relatorio)``. ``df`` mantém a ordem de leitura.
    """
    if not caminhos:
        raise ValueError("Nenhum arquivo de rede informado.")
    if conflitos not in ("erro", "excluir"):
        raise ValueError(f"conflitos inválido: {conflitos}")
    quadros: List[pd.DataFrame] = []
    arquivos: List[Dict[str, Any]] = []
    cabecalho: Optional[List[str]] = None
    for c in caminhos:
        p = Path(c)
        if not p.is_file():
            raise FileNotFoundError(f"Arquivo de rede não encontrado: {p}")
        df = pd.read_csv(p, dtype=_DTYPES_TEXTO_REDE)
        colunas = list(df.columns)
        faltam_rastreio = [col for col in COLUNAS_RASTREIO if col in colunas]
        if faltam_rastreio:
            raise ErroEsquema(ESQUEMA_REDE_V1.id, [f"coluna reservada no arquivo {p.name}: {faltam_rastreio}"])
        if cabecalho is None:
            cabecalho = colunas
        elif colunas != cabecalho:
            raise ErroEsquema(
                ESQUEMA_REDE_V1.id,
                [f"cabeçalho de {p.name} difere do primeiro arquivo: {colunas} != {cabecalho}"],
            )
        df.insert(0, "linha_origem", np.arange(len(df), dtype=np.int64))
        df.insert(0, "arquivo_origem", p.name)
        quadros.append(df)
        arquivos.append({"caminho": str(p), "linhas": int(len(df)), "sha256": sha256_arquivo(p)})
    if len({a["caminho"] for a in arquivos}) != len(arquivos):
        raise ErroDados("O mesmo arquivo foi informado mais de uma vez.")
    df = pd.concat(quadros, ignore_index=True)
    ESQUEMA_REDE_V1.validar(df, modo=modo, exigir=exigir)
    df["timestamp"] = df["timestamp"].astype(np.int64)

    relatorio: Dict[str, Any] = {"arquivos": arquivos, "linhas_lidas": int(len(df))}
    dup = df.duplicated(list(CHAVE_REDE), keep=False)
    relatorio["linhas_com_chave_repetida"] = int(dup.sum())
    relatorio["duplicatas_removidas"] = 0
    relatorio["chaves_conflitantes"] = 0
    if dup.any():
        valores = [c for c in cabecalho if c not in CHAVE_REDE]
        grupo = df.loc[dup].groupby(list(CHAVE_REDE), sort=False)[valores]
        distintos = grupo.nunique(dropna=False).max(axis=1)
        chaves_conf = distintos[distintos > 1].index
        relatorio["chaves_conflitantes"] = int(len(chaves_conf))
        relatorio["exemplos_conflito"] = [list(map(_nativo, k)) for k in list(chaves_conf)[:10]]
        if modo == "treino":
            if len(chaves_conf) and conflitos == "erro":
                raise ErroDados(
                    f"{len(chaves_conf)} chave(s) id_fluxo+timestamp com valores diferentes "
                    f"entre registros (ex.: {relatorio['exemplos_conflito'][:3]}). "
                    "Corrija a origem ou use conflitos='excluir'."
                )
            idx = pd.MultiIndex.from_frame(df[list(CHAVE_REDE)])
            em_conflito = idx.isin(chaves_conf)
            antes = len(df)
            df = df.loc[~em_conflito]
            relatorio["linhas_excluidas_por_conflito"] = int(antes - len(df))
            antes = len(df)
            df = df.loc[~df.duplicated(list(CHAVE_REDE), keep="first")]
            relatorio["duplicatas_removidas"] = int(antes - len(df))
            df = df.reset_index(drop=True)
    relatorio["linhas_finais"] = int(len(df))
    return df, relatorio


def _nativo(v: Any) -> Any:
    return v.item() if hasattr(v, "item") else v


def verificar_splits(df: pd.DataFrame) -> Dict[str, Any]:
    """Confere se treino < validação < teste no tempo (global e por fluxo)."""
    presentes = [s for s in SPLITS if s in set(df["split"].unique())]
    faixas = df.groupby("split")["timestamp"].agg(["min", "max", "count"])
    saida: Dict[str, Any] = {
        "faixas": {s: {k: int(faixas.loc[s, k]) for k in ("min", "max", "count")} for s in presentes},
        "problemas": [],
        "lacunas_s": {},
    }
    por_fluxo = df.groupby(["id_fluxo", "split"])["timestamp"].agg(["min", "max"]).unstack("split")
    for a, b in zip(presentes, presentes[1:]):
        if faixas.loc[a, "max"] >= faixas.loc[b, "min"]:
            saida["problemas"].append(f"sobreposição global entre {a} e {b}")
        ambos = por_fluxo[("max", a)].notna() & por_fluxo[("min", b)].notna()
        lacuna = (por_fluxo[("min", b)] - por_fluxo[("max", a)])[ambos]
        ruins = int((lacuna <= 0).sum())
        if ruins:
            saida["problemas"].append(f"{ruins} fluxo(s) com {b} antes do fim de {a}")
        saida["lacunas_s"][f"{a}->{b}"] = {
            "min": float(lacuna.min()), "mediana": float(lacuna.median()), "max": float(lacuna.max())
        }
    fluxos_por_split = df.groupby("split")["id_fluxo"].nunique()
    saida["fluxos_por_split"] = {s: int(fluxos_por_split[s]) for s in presentes}
    return saida


# ---------------------------------------------------------------------------
# HI-Small
# ---------------------------------------------------------------------------
@dataclass
class DadosHISmall:
    """Transações do HI-Small em tipos compactos.

    ``trans`` tem uma linha por transação, na ordem do arquivo:
    ``id_transacao`` (= linha 0-based), ``minuto`` (minutos desde a época),
    ``conta_origem``/``conta_destino`` (códigos int32 de ``banco-conta``),
    bancos, valores, moedas e formato (categóricos) e ``rotulo`` (se houver).
    ``nomes_contas[codigo]`` devolve o texto ``banco-conta``.
    """

    trans: pd.DataFrame
    nomes_contas: np.ndarray
    arquivo: str
    sha256: str
    relatorio: Dict[str, Any] = field(default_factory=dict)


@contextlib.contextmanager
def _abrir_binario(caminho: Path) -> Iterator[io.BufferedIOBase]:
    if caminho.suffix.lower() == ".zip":
        with zipfile.ZipFile(caminho) as z:
            membros = [m for m in z.infolist() if not m.is_dir()]
            csvs = [m for m in membros if m.filename.lower().endswith(".csv")]
            if len(csvs) != 1:
                raise ErroDados(f"{caminho.name}: esperado 1 CSV dentro do zip, há {len(csvs)}")
            with z.open(csvs[0]) as fh:
                yield fh
    else:
        with open(caminho, "rb") as fh:
            yield fh


def _normalizar_cabecalho(linha: str) -> List[str]:
    nomes = [n.strip() for n in linha.strip().split(",")]
    vistos: Dict[str, int] = {}
    saida = []
    for n in nomes:
        k = vistos.get(n, 0)
        saida.append(n if k == 0 else f"{n}.{k}")
        vistos[n] = k + 1
    return saida


def ler_hismall(caminho: Caminho, exigir_rotulo: bool = True) -> DadosHISmall:
    """Lê ``HI-Small_Trans.csv`` (ou o ``.zip`` que o contém) com pyarrow."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.csv as pcsv

    p = Path(caminho)
    if not p.is_file():
        raise FileNotFoundError(f"Arquivo de transações não encontrado: {p}")
    with _abrir_binario(p) as fh:
        cabecalho = _normalizar_cabecalho(fh.readline().decode("utf-8-sig"))
    esperado = list(COLUNAS_HISMALL)
    sem_rotulo = esperado[:-1]
    if cabecalho == esperado:
        nomes = esperado
    elif cabecalho == sem_rotulo and not exigir_rotulo:
        nomes = sem_rotulo
    else:
        raise ErroEsquema(ESQUEMA_HISMALL_V1.id, [f"cabeçalho inesperado: {cabecalho}"])

    tipos = {
        "Timestamp": pa.timestamp("s"),
        "From Bank": pa.int64(), "To Bank": pa.int64(),
        "Account": pa.string(), "Account.1": pa.string(),
        "Amount Received": pa.float64(), "Amount Paid": pa.float64(),
        "Receiving Currency": pa.string(), "Payment Currency": pa.string(),
        "Payment Format": pa.string(), "Is Laundering": pa.int8(),
    }
    with _abrir_binario(p) as fh:
        tab = pcsv.read_csv(
            fh,
            read_options=pcsv.ReadOptions(column_names=nomes, skip_rows=1, block_size=1 << 26),
            convert_options=pcsv.ConvertOptions(
                column_types={k: v for k, v in tipos.items() if k in nomes},
                timestamp_parsers=["%Y/%m/%d %H:%M"],
                strings_can_be_null=False,
            ),
        )
    problemas = [f"{n}: {tab[n].null_count} valor(es) ausente(s)" for n in nomes if tab[n].null_count]
    if problemas:
        raise ErroEsquema(ESQUEMA_HISMALL_V1.id, problemas)

    n = tab.num_rows
    contas = pa.concat_arrays([
        pc.binary_join_element_wise(pc.cast(tab["From Bank"], pa.string()), tab["Account"], "-").combine_chunks(),
        pc.binary_join_element_wise(pc.cast(tab["To Bank"], pa.string()), tab["Account.1"], "-").combine_chunks(),
    ]).dictionary_encode()
    codigos = contas.indices.to_numpy(zero_copy_only=False).astype(np.int32)
    nomes_contas = np.asarray(contas.dictionary.to_pylist(), dtype=object)
    del contas

    def categoria(col: str) -> pd.Categorical:
        d = tab[col].combine_chunks().dictionary_encode()
        return pd.Categorical.from_codes(
            d.indices.to_numpy(zero_copy_only=False).astype(np.int32),
            categories=pd.Index(d.dictionary.to_pylist(), dtype=str),
        )

    segundos = tab["Timestamp"].cast(pa.int64()).to_numpy()
    trans = pd.DataFrame({
        "id_transacao": np.arange(n, dtype=np.int64),
        "minuto": (segundos // 60).astype(np.int64),
        "banco_origem": tab["From Bank"].to_numpy().astype(np.int32),
        "conta_origem": codigos[:n],
        "banco_destino": tab["To Bank"].to_numpy().astype(np.int32),
        "conta_destino": codigos[n:],
        "valor_recebido": tab["Amount Received"].to_numpy(),
        "moeda_recebimento": categoria("Receiving Currency"),
        "valor_pago": tab["Amount Paid"].to_numpy(),
        "moeda_pagamento": categoria("Payment Currency"),
        "formato": categoria("Payment Format"),
    })
    if "Is Laundering" in nomes:
        trans["rotulo"] = tab["Is Laundering"].to_numpy().astype(np.int8)
    del tab
    problemas = []
    for col in ("valor_pago", "valor_recebido"):
        v = trans[col].to_numpy()
        if not np.isfinite(v).all():
            problemas.append(f"{col}: valores não finitos")
        if (v < 0).any():
            problemas.append(f"{col}: {int((v < 0).sum())} valor(es) negativo(s)")
    if "rotulo" in trans and not trans["rotulo"].isin([0, 1]).all():
        problemas.append("Is Laundering: valores fora de {0, 1}")
    if problemas:
        raise ErroEsquema(ESQUEMA_HISMALL_V1.id, problemas)
    relatorio = {
        "arquivo": str(p),
        "linhas": int(n),
        "contas_distintas": int(len(nomes_contas)),
        "duplicatas_exatas": int(trans.drop(columns="id_transacao").duplicated().sum()),
    }
    return DadosHISmall(trans, nomes_contas, str(p), sha256_arquivo(p), relatorio)


# ---------------------------------------------------------------------------
# Contas e padrões (auditoria e avaliação; padrões nunca viram atributo)
# ---------------------------------------------------------------------------
COLUNAS_CONTAS = ("Bank Name", "Bank ID", "Account Number", "Entity ID", "Entity Name")
_RE_TIPO_ENTIDADE = re.compile(r"^(.*?)\s*#\s*\d+\s*$")


def ler_contas(caminho: Caminho) -> pd.DataFrame:
    """Lê ``HI-Small_accounts.csv``; a chave ``conta`` segue ``banco-conta``."""
    p = Path(caminho)
    if not p.is_file():
        raise FileNotFoundError(f"Arquivo de contas não encontrado: {p}")
    df = pd.read_csv(p, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    faltam = [c for c in COLUNAS_CONTAS if c not in df.columns]
    if faltam:
        raise ErroEsquema("contas", [f"colunas ausentes: {faltam}; cabeçalho: {list(df.columns)}"])
    banco = pd.to_numeric(df["Bank ID"], errors="coerce")
    if banco.isna().any():
        raise ErroEsquema("contas", [f"Bank ID não numérico em {int(banco.isna().sum())} linha(s)"])
    df["conta"] = banco.astype(np.int64).astype(str) + "-" + df["Account Number"].str.strip()
    df["tipo_entidade"] = df["Entity Name"].str.extract(_RE_TIPO_ENTIDADE, expand=False).fillna("desconhecido")
    return df


RE_INICIO_PADRAO = re.compile(r"BEGIN LAUNDERING ATTEMPT\s*-\s*([^:]+?)\s*(?::(.*))?$", re.IGNORECASE)
RE_FIM_PADRAO = re.compile(r"END LAUNDERING ATTEMPT", re.IGNORECASE)


def ler_padroes(caminho: Caminho) -> pd.DataFrame:
    """Lê ``HI-Small_Patterns.txt`` (mesmo formato de ``scripts/analise_por_padrao.py``).

    Returns:
        Uma linha por transação listada em uma tentativa, com ``tentativa``
        (sequencial), ``tipo_padrao``, ``detalhe`` e as chaves de casamento
        com as transações (minuto, bancos, contas, valor pago, moeda, formato).
    """
    p = Path(caminho)
    if not p.is_file():
        raise FileNotFoundError(f"Arquivo de padrões não encontrado: {p}")
    linhas: List[List[Any]] = []
    tentativa, tipo, detalhe = -1, None, ""
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for bruta in fh:
            texto = bruta.strip()
            if not texto:
                continue
            m = RE_INICIO_PADRAO.match(texto)
            if m:
                tentativa += 1
                tipo, detalhe = m.group(1).strip().upper(), (m.group(2) or "").strip()
                continue
            if RE_FIM_PADRAO.match(texto):
                tipo = None
                continue
            if tipo is None:
                continue
            campos = [c.strip() for c in texto.split(",")]
            if len(campos) < 10:
                continue
            linhas.append([tentativa, tipo, detalhe] + campos[:11])
    colunas = ["tentativa", "tipo_padrao", "detalhe", "Timestamp", "From Bank", "Account",
               "To Bank", "Account.1", "Amount Received", "Receiving Currency", "Amount Paid",
               "Payment Currency", "Payment Format", "Is Laundering"]
    df = pd.DataFrame(linhas, columns=colunas[: 3 + max((len(r) - 3 for r in linhas), default=11)])
    if df.empty:
        return df
    ts = pd.to_datetime(df["Timestamp"], format="%Y/%m/%d %H:%M")
    df["minuto"] = ((ts - pd.Timestamp("1970-01-01")) // pd.Timedelta(minutes=1)).astype(np.int64)
    df["conta_origem_txt"] = pd.to_numeric(df["From Bank"]).astype(np.int64).astype(str) + "-" + df["Account"]
    df["conta_destino_txt"] = pd.to_numeric(df["To Bank"]).astype(np.int64).astype(str) + "-" + df["Account.1"]
    df["valor_pago"] = pd.to_numeric(df["Amount Paid"])
    return df


def casar_padroes(dados: DadosHISmall, padroes: pd.DataFrame) -> pd.DataFrame:
    """Associa cada transação de padrão a ``id_transacao`` (pode não casar)."""
    if padroes.empty:
        return padroes.assign(id_transacao=pd.Series(dtype="Int64"))
    indice = pd.Index(dados.nomes_contas)
    t = dados.trans
    chave_t = pd.DataFrame({
        "minuto": t["minuto"].to_numpy(),
        "conta_origem": t["conta_origem"].to_numpy(),
        "conta_destino": t["conta_destino"].to_numpy(),
        "valor_cent": np.round(t["valor_pago"].to_numpy() * 100).astype(np.int64),
        "formato": t["formato"].astype(str).to_numpy(),
        "id_transacao": t["id_transacao"].to_numpy(),
    })
    pp = padroes.copy()
    pp["conta_origem"] = indice.get_indexer(pp["conta_origem_txt"])
    pp["conta_destino"] = indice.get_indexer(pp["conta_destino_txt"])
    pp["valor_cent"] = np.round(pp["valor_pago"].to_numpy() * 100).astype(np.int64)
    pp["formato"] = pp["Payment Format"].astype(str)
    chaves = ["minuto", "conta_origem", "conta_destino", "valor_cent", "formato"]
    candidatos = chave_t.merge(pp[chaves].drop_duplicates(), on=chaves, how="inner")
    casado = pp.merge(candidatos, on=chaves, how="left")
    # Uma linha de padrão que case com mais de uma transação idêntica fica com a primeira.
    casado = casado.sort_values("id_transacao").drop_duplicates(
        ["tentativa"] + chaves, keep="first"
    )
    return casado
