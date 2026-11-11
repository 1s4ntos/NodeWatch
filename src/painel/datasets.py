"""Datasets do painel: envio seguro, catálogo e validação no servidor.

Envio
    * limite de tamanho (``LIMITE_BYTES``) conferido durante a gravação;
    * o nome enviado pelo navegador é **só um rótulo**: é sanitizado e guardado
      no registro; no disco o arquivo sempre se chama ``dados.csv``/``dados.zip``
      dentro de uma pasta com identificador gerado pelo servidor;
    * tudo fica em ``artefatos_ml/painel/datasets`` (pasta ignorada pelo git);
    * nenhuma rota aceita caminho: datasets "do servidor" são descobertos em
      pastas fixas e identificados por um código derivado do caminho relativo.

Validação (antes de qualquer análise)
    Formato, codificação, colunas obrigatórias, tipos, datas e valores. O
    resultado traz nome, tamanho, linhas, período, colunas reconhecidas, moedas
    e formatos de pagamento. Cada problema indica **coluna**, **linha de
    exemplo** e **como corrigir**. Linhas com problema não são corrigidas nem
    preenchidas: ficam fora da análise e são contadas.

Reaproveita a detecção de formato e a leitura de datas de ``src.ml.analises``.
Só transações financeiras são analisáveis aqui; a análise de rede está
temporariamente fora desta interface.
"""

from __future__ import annotations

import collections
import hashlib
import json
import re
import secrets
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.ml.analises import CAMPOS_PT, FORMATOS, _tempo, detectar_formato
from src.ml.esquemas import COLUNAS_HISMALL
from src.ml.ingestao import _normalizar_cabecalho
from src.painel import tipologias as tp
from src.painel.util import agora_iso, gravar_json_atomico, ler_json, minuto_iso

LIMITE_BYTES = 256_000_000
LIMITE_PADROES_BYTES = 32_000_000
LIMITE_DESCOMPACTADO_BYTES = 2_000_000_000
EXTENSOES = (".csv", ".zip")
EXTENSOES_PADROES = (".txt", ".csv")
MAX_ENVIADOS = 10
LINHAS_POR_BLOCO = 200_000
MAX_EXTRAS = 20
MAX_CATEGORIAS = 60
PASTA = Path("artefatos_ml") / "painel" / "datasets"
# Pastas fixas (relativas à raiz) onde o servidor procura datasets já disponíveis.
PASTAS_SERVIDOR: Tuple[Tuple[str, str], ...] = (
    ("dados", "pasta dados/ do projeto"),
    ("docs/exemplos", "exemplos inventados do repositório"),
    ("artefatos_ml/exemplos", "exemplos gerados por `python -m src.ml.cli exemplos`"),
)
NAO_INFORMADO = "Não informado"
_VAZIOS = {"", "unknown", "desconhecido", "n/a", "na", "null", "none", "nan", "-"}

MAPA_HISMALL = {"Timestamp": "ts", "From Bank": "banco_o", "Account": "conta_o", "To Bank": "banco_d",
                "Account.1": "conta_d", "Amount Received": "valor_rec", "Receiving Currency": "moeda_rec",
                "Amount Paid": "valor_pag", "Payment Currency": "moeda_pag", "Payment Format": "formato",
                "Is Laundering": "rotulo"}
MAPA_PT = {"id_transacao": "id", "timestamp": "ts", "banco_origem": "banco_o", "conta_origem": "conta_o",
           "banco_destino": "banco_d", "conta_destino": "conta_d", "valor_recebido": "valor_rec",
           "moeda_recebimento": "moeda_rec", "valor_pago": "valor_pag", "moeda_pagamento": "moeda_pag",
           "formato": "formato", "rotulo": "rotulo"}
PAPEIS = {"id": "identificador original da transação", "ts": "data e hora", "banco_o": "banco de origem",
          "conta_o": "conta de origem", "banco_d": "banco de destino", "conta_d": "conta de destino",
          "valor_rec": "valor recebido", "moeda_rec": "moeda de recebimento", "valor_pag": "valor pago",
          "moeda_pag": "moeda de pagamento", "formato": "formato de pagamento",
          "rotulo": "rótulo do dataset (lavagem: 1 = sim, 0 = não)"}
NOMES_FORMATO = {"hismall_v1": "IBM AML (cabeçalho original em inglês)",
                 "transacao_hismall_v1": "transações com colunas em português"}


class Cancelado(Exception):
    """A operação foi interrompida num ponto seguro a pedido do usuário."""


class ErroDataset(ValueError):
    """Dataset recusado como um todo. ``problemas`` segue o formato da validação."""

    def __init__(self, problemas: List[Dict[str, Any]], status: int = 422):
        self.problemas = problemas
        self.status = status
        super().__init__("; ".join(p["problema"] for p in problemas))


def problema(texto: str, como_corrigir: str, coluna: Optional[str] = None, linha: Optional[int] = None,
             valor: Optional[str] = None, linhas: Optional[int] = None) -> Dict[str, Any]:
    return {"coluna": coluna, "linha_exemplo": linha, "valor_exemplo": valor, "linhas_afetadas": linhas,
            "problema": texto, "como_corrigir": como_corrigir}


def nome_seguro(nome: Optional[str], padrao: str = "dataset.csv") -> str:
    """Rótulo de exibição: só o nome base, sem separadores de pasta nem caracteres de controle."""
    base = re.split(r"[\\/]", str(nome or ""))[-1]
    base = re.sub(r"[^\w.\- ()\[\]]+", "_", base, flags=re.UNICODE).strip(" ._")
    base = re.sub(r"_{2,}", "_", base)
    if not base or set(base) <= {"."}:
        return padrao
    if len(base) > 80:
        raiz, _, ext = base.rpartition(".")
        base = (raiz[:74] + "." + ext[:5]) if raiz else base[:80]
    return base


def sem_informacao(serie: pd.Series) -> pd.Series:
    """Categorias ausentes ou desconhecidas (vazio, 'Unknown', 'N/A'…) → tratadas como 'Não informado'."""
    return serie.str.strip().str.lower().isin(_VAZIOS)


# ---------------------------------------------------------------------------
# Leitura e validação em blocos
# ---------------------------------------------------------------------------
class _Leitor:
    """Abre CSV ou ZIP (um CSV dentro) e informa bytes lidos e total para o progresso."""

    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self._zip: Optional[zipfile.ZipFile] = None
        self.fh: Optional[BinaryIO] = None
        self.total = 0

    def __enter__(self) -> "_Leitor":
        if self.caminho.suffix.lower() == ".zip":
            try:
                self._zip = zipfile.ZipFile(self.caminho)
            except zipfile.BadZipFile:
                raise ErroDataset([problema("o arquivo .zip está corrompido ou não é um ZIP",
                                            "Compacte de novo o CSV ou envie o CSV direto.")]) from None
            csvs = [m for m in self._zip.infolist() if not m.is_dir() and m.filename.lower().endswith(".csv")]
            if len(csvs) != 1:
                self._zip.close()
                raise ErroDataset([problema(f"o ZIP precisa conter exatamente 1 arquivo CSV; contém {len(csvs)}",
                                            "Deixe um único CSV dentro do ZIP.")])
            if csvs[0].file_size > LIMITE_DESCOMPACTADO_BYTES:
                self._zip.close()
                raise ErroDataset([problema(
                    f"o CSV dentro do ZIP tem {csvs[0].file_size / 1e6:.0f} MB descompactado; o limite é "
                    f"{LIMITE_DESCOMPACTADO_BYTES / 1e6:.0f} MB", "Divida o arquivo por período.")], 413)
            self.total = csvs[0].file_size
            self.fh = self._zip.open(csvs[0])
        else:
            self.total = self.caminho.stat().st_size
            self.fh = open(self.caminho, "rb")
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            if self.fh:
                self.fh.close()
        finally:
            if self._zip:
                self._zip.close()

    def lidos(self) -> int:
        try:
            return min(int(self.fh.tell()), self.total)
        except (OSError, ValueError, AttributeError):
            return 0


def ler_cabecalho(caminho: Path) -> Tuple[List[str], str]:
    """Colunas do cabeçalho (repetidas ganham sufixo ``.1``) e a linha bruta."""
    with _Leitor(caminho) as leitor:
        bruta = leitor.fh.readline(1_000_000)
    if not bruta.strip():
        raise ErroDataset([problema("o arquivo está vazio", "Envie um CSV com cabeçalho e ao menos uma linha.",
                                    linha=1)])
    try:
        linha = bruta.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ErroDataset([problema("o arquivo não está codificado em UTF-8",
                                    "Salve o arquivo como CSV UTF-8 (no Excel: 'CSV UTF-8 (delimitado por vírgulas)').",
                                    linha=1)]) from None
    return _normalizar_cabecalho(linha), linha.strip()


def identificar(caminho: Path) -> Dict[str, Any]:
    """Formato do arquivo; levanta :class:`ErroDataset` com a explicação quando não é analisável aqui."""
    colunas, bruta = ler_cabecalho(caminho)
    if len(colunas) == 1 and (";" in bruta or "\t" in bruta):
        sep = "ponto e vírgula" if ";" in bruta else "tabulação"
        raise ErroDataset([problema(f"o cabeçalho usa {sep} como separador", "Exporte o CSV com vírgula como "
                                    "separador de colunas e ponto como separador decimal.", linha=1)])
    info = detectar_formato(colunas)
    if info.get("dominio") == "lavagem" and info.get("analisavel"):
        return {"formato": info["formato"], "colunas": colunas}
    if info.get("dominio") == "rede":
        raise ErroDataset([problema("o arquivo contém medições de rede, não transações financeiras",
                                    "A análise de rede está temporariamente fora desta interface. Envie um "
                                    "dataset de transações.", linha=1)])
    if info.get("formato") and not info.get("analisavel"):
        raise ErroDataset([problema(info.get("leitura", "formato reconhecido, mas não analisável"),
                                    "Envie o dataset de transações (não o arquivo de previsões nem o CSV do "
                                    "grafo antigo).", linha=1)])
    faltando = info.get("faltando", {})
    probs = []
    for fmt in ("hismall_v1", "transacao_hismall_v1"):
        faltam = faltando.get(fmt) or []
        esperado = FORMATOS[fmt]["cabecalho"].replace("Account.1", "Account")
        if fmt == "hismall_v1":
            faltam = [("Account (2ª ocorrência: conta de destino)" if c == "Account.1" else c) for c in faltam]
        probs.append(problema(
            f"para o formato {NOMES_FORMATO[fmt]} faltam {len(faltam)} coluna(s) obrigatória(s): "
            + ", ".join(faltam), f"Inclua as colunas que faltam. Cabeçalho esperado: {esperado}",
            coluna=faltam[0] if faltam else None, linha=1))
    probs.sort(key=lambda p: len(p["problema"]))
    raise ErroDataset(probs)


class _Problemas:
    """Agrupa problemas de linha por (coluna, problema), guardando um exemplo de cada."""

    def __init__(self) -> None:
        self.itens: "collections.OrderedDict[Tuple[str, str], Dict[str, Any]]" = collections.OrderedDict()

    def marcar(self, mascara: np.ndarray, coluna: str, texto: str, como: str, linhas: np.ndarray,
               valores: pd.Series) -> None:
        n = int(mascara.sum())
        if not n:
            return
        chave = (coluna, texto)
        if chave not in self.itens:
            i = int(np.flatnonzero(mascara)[0])
            self.itens[chave] = problema(texto, como, coluna, int(linhas[i]), str(valores.iloc[i])[:60], 0)
        self.itens[chave]["linhas_afetadas"] += n

    def lista(self) -> List[Dict[str, Any]]:
        return sorted(self.itens.values(), key=lambda p: -p["linhas_afetadas"])


def ler_validando(caminho: Path, formato: str, colunas: List[str],
                  progresso: Optional[Callable[[int, int, int], None]] = None,
                  cancelar: Optional[Callable[[], bool]] = None) -> Iterator[Tuple[pd.DataFrame, Dict[str, Any]]]:
    """Gera ``(linhas_validas, info_do_bloco)`` por bloco do arquivo.

    ``linhas_validas`` tem: ``linha`` (número da linha no arquivo; o cabeçalho é
    a linha 1), ``id_original``, ``minuto``, bancos, contas, ``no_origem`` e
    ``no_destino`` (``banco-conta``), valores, moedas, ``formato`` (vazio quando
    não informado), ``rotulo`` e ``extras`` (JSON das colunas fora do contrato),
    estes dois quando existirem.
    """
    hismall = formato == "hismall_v1"
    mapa = MAPA_HISMALL if hismall else MAPA_PT
    original = {v: k for k, v in mapa.items()}
    if hismall:
        original["conta_d"] = "Account (2ª ocorrência)"
    extras_cols = [c for c in colunas if c not in mapa][:MAX_EXTRAS]
    kw: Dict[str, Any] = {"header": None, "skiprows": 1, "names": colunas} if hismall else {}
    probs = _Problemas()
    vistos: set = set()
    lidas = 0
    fmt_data = ("AAAA/MM/DD HH:MM (por exemplo 2022/09/01 00:20)" if hismall else
                "ISO 8601 (2022-09-01T00:20:00Z), AAAA/MM/DD HH:MM ou época em segundos")
    with _Leitor(caminho) as leitor:
        try:
            blocos = pd.read_csv(leitor.fh, dtype=str, keep_default_na=False, na_filter=False,
                                 chunksize=LINHAS_POR_BLOCO, encoding="utf-8-sig", index_col=False, **kw)
            for bloco in blocos:
                if cancelar and cancelar():
                    raise Cancelado()
                bloco = bloco.fillna("")
                linhas = np.arange(lidas, lidas + len(bloco), dtype=np.int64) + 2
                lidas += len(bloco)
                extras = bloco[extras_cols] if extras_cols else None
                b = bloco.rename(columns=mapa)
                b = b[[c for c in dict.fromkeys(mapa.values()) if c in b.columns]].apply(lambda s: s.str.strip())
                ruim = np.zeros(len(b), dtype=bool)

                def marcar(mascara: Any, campo: str, texto: str, como: str) -> None:
                    m = np.asarray(mascara, dtype=bool) & ~ruim
                    probs.marcar(m, original[campo], texto, como, linhas, b[campo])
                    ruim[m] = True

                t = _tempo(b["ts"], hismall)
                marcar(t.isna().to_numpy(), "ts", "data e hora ausente ou em formato não aceito", f"Use {fmt_data}.")
                for c in ("banco_o", "banco_d"):
                    marcar(~b[c].str.fullmatch(r"\d{1,18}").to_numpy(), c, f"{PAPEIS[c]} não é um número inteiro",
                           "Informe o código numérico do banco (só dígitos).")
                for c in ("conta_o", "conta_d", "moeda_pag", "moeda_rec"):
                    marcar((b[c] == "").to_numpy(), c, f"{PAPEIS[c]} em branco", "Preencha o campo; ele é obrigatório.")
                valores = {}
                for c in ("valor_pag", "valor_rec"):
                    v = pd.to_numeric(b[c], errors="coerce")
                    marcar(v.isna().to_numpy(), c, f"{PAPEIS[c]} ausente ou não numérico",
                           "Use número com ponto decimal e sem separador de milhar (por exemplo 1234.56).")
                    marcar(~(np.isfinite(v.fillna(0)) & (v.fillna(0) >= 0) & (v.fillna(0) <= 1e15)).to_numpy(), c,
                           f"{PAPEIS[c]} negativo ou fora da faixa aceita", "Informe um valor entre 0 e 1e15.")
                    valores[c] = v
                rot = None
                if "rotulo" in b:
                    rot = pd.to_numeric(b["rotulo"], errors="coerce")
                    marcar(~rot.isin([0, 1]).to_numpy(), "rotulo", "rótulo diferente de 0 e 1",
                           "Use 1 para lavagem e 0 para os demais, ou remova a coluna.")
                if "id" in b:
                    marcar((b["id"] == "").to_numpy(), "id", "identificador da transação em branco",
                           "Preencha um identificador único por linha.")
                    codigos = pd.util.hash_array(b["id"].to_numpy(dtype=object), categorize=False)
                    repetido = pd.Series(codigos).duplicated().to_numpy() | np.fromiter(
                        (int(h) in vistos for h in codigos), dtype=bool, count=len(codigos))
                    marcar(repetido, "id", "identificador da transação repetido",
                           "Cada linha precisa de um identificador diferente; remova as duplicatas.")
                    vistos.update(int(h) for h in codigos[~ruim])
                ok = ~ruim
                v = b[ok]
                banco_o = v["banco_o"].astype(np.int64).astype(str)
                banco_d = v["banco_d"].astype(np.int64).astype(str)
                # Texto fica no tipo de string do pandas (compacto); nada vira objeto Python por linha aqui.
                validas = pd.DataFrame({
                    "linha": linhas[ok],
                    "id_original": v["id"] if "id" in v else None,
                    "minuto": ((t[ok] - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(minutes=1)).to_numpy(dtype=np.int64),
                    "banco_origem": banco_o, "conta_origem": v["conta_o"], "no_origem": banco_o + "-" + v["conta_o"],
                    "banco_destino": banco_d, "conta_destino": v["conta_d"], "no_destino": banco_d + "-" + v["conta_d"],
                    "valor_pago": valores["valor_pag"][ok].to_numpy(dtype=np.float64),
                    "moeda_pagamento": v["moeda_pag"],
                    "valor_recebido": valores["valor_rec"][ok].to_numpy(dtype=np.float64),
                    "moeda_recebimento": v["moeda_rec"],
                    "formato": v["formato"].mask(sem_informacao(v["formato"]), ""),
                }, index=v.index).reset_index(drop=True)
                if rot is not None:
                    validas["rotulo"] = rot[ok].to_numpy().astype(np.int8)
                if extras is not None:
                    validas["extras"] = [json.dumps(r, ensure_ascii=False) for r in extras[ok].to_dict("records")]
                if progresso:
                    progresso(leitor.lidos(), leitor.total, lidas)
                yield validas, {"lidas": lidas, "problemas": probs, "bytes_total": leitor.total,
                                "extras": extras_cols}
        except UnicodeDecodeError as exc:
            raise ErroDataset([problema(
                "o arquivo tem bytes que não são UTF-8", "Salve o arquivo como CSV UTF-8 e envie de novo.",
                linha=None, valor=f"posição {exc.start} do bloco lido")]) from None
        except pd.errors.EmptyDataError:
            raise ErroDataset([problema("o arquivo não tem linhas de dados", "Envie um CSV com cabeçalho e ao "
                                        "menos uma transação.", linha=2)]) from None
        except pd.errors.ParserError as exc:
            texto = str(exc).splitlines()[0]
            m = re.search(r"line (\d+)", texto)
            raise ErroDataset([problema(
                f"CSV malformado: {texto}", "Confira a linha indicada: número de colunas diferente do cabeçalho "
                "ou aspas sem fechar.", linha=int(m.group(1)) if m else None)]) from None
    if lidas == 0:
        raise ErroDataset([problema("o arquivo não tem linhas de dados", "Envie um CSV com cabeçalho e ao menos "
                                    "uma transação.", linha=2)])


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 22), b""):
            h.update(bloco)
    return h.hexdigest()


def validar_arquivo(caminho: Path, caminho_padroes: Optional[Path] = None,
                    progresso: Optional[Callable[[int, int, int], None]] = None,
                    cancelar: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """Valida o arquivo inteiro e devolve o resumo mostrado ao analista (não guarda as linhas)."""
    inicio = time.monotonic()
    ident = identificar(caminho)
    formato, colunas = ident["formato"], ident["colunas"]
    mapa = MAPA_HISMALL if formato == "hismall_v1" else MAPA_PT
    cont = {c: collections.Counter() for c in ("moeda_pagamento", "moeda_recebimento", "formato")}
    contas: set = set()
    validas = positivos = 0
    tmin: Optional[int] = None
    tmax: Optional[int] = None
    info: Dict[str, Any] = {"lidas": 0, "problemas": _Problemas(), "extras": []}
    ordenado = True
    for bloco, info in ler_validando(caminho, formato, colunas, progresso, cancelar):
        if bloco.empty:
            continue
        validas += len(bloco)
        m = bloco["minuto"]
        ordenado = ordenado and bool(m.is_monotonic_increasing) and (tmax is None or int(m.iloc[0]) >= tmax)
        tmin = int(m.min()) if tmin is None else min(tmin, int(m.min()))
        tmax = int(m.max()) if tmax is None else max(tmax, int(m.max()))
        for c in cont:
            cont[c].update(bloco[c].value_counts().to_dict())
        contas.update(pd.unique(bloco["no_origem"]))
        contas.update(pd.unique(bloco["no_destino"]))
        if "rotulo" in bloco:
            positivos += int(bloco["rotulo"].sum())
    problemas = info["problemas"].lista()
    lidas = int(info["lidas"])
    recusadas = lidas - validas
    tem_rotulo = "rotulo" in mapa.values() and any(mapa.get(c) == "rotulo" for c in colunas)

    def categorias(c: collections.Counter) -> List[Dict[str, Any]]:
        itens = [{"valor": k if k != "" else NAO_INFORMADO, "n": int(n)} for k, n in c.most_common(MAX_CATEGORIAS)]
        return itens

    avisos: List[str] = []
    sem_formato = int(cont["formato"].get("", 0))
    if sem_formato:
        avisos.append(f"{sem_formato} transação(ões) sem formato de pagamento: aparecem como \"{NAO_INFORMADO}\".")
    if not ordenado:
        avisos.append("As linhas não estão em ordem cronológica no arquivo: a análise ordena por data e hora "
                      "(empates pela ordem da linha).")
    if tmin is not None and tmax is not None and tmax - tmin < 72 * 60:
        avisos.append("O dataset cobre menos de 72 horas. O modelo usa o histórico das contas dentro do próprio "
                      "dataset; com pouco histórico, tende a gerar menos alertas.")
    saida: Dict[str, Any] = {
        "formato": formato, "formato_nome": NOMES_FORMATO[formato], "sha256": sha256_arquivo(caminho),
        "linhas": {"lidas": lidas, "validas": validas, "recusadas": recusadas},
        "periodo": ({"inicio": minuto_iso(tmin), "fim": minuto_iso(tmax),
                     "fuso": "horário do dataset (fuso não documentado; exibido sem conversão)"}
                    if tmin is not None else None),
        "colunas": [{"original": ("Account (2ª ocorrência)" if c == "Account.1" else c),
                     "papel": PAPEIS[mapa[c]]} for c in colunas if c in mapa],
        "colunas_nao_reconhecidas": [c for c in colunas if c not in mapa],
        "moedas_pagamento": categorias(cont["moeda_pagamento"]),
        "moedas_recebimento": categorias(cont["moeda_recebimento"]),
        "formatos_pagamento": categorias(cont["formato"]),
        "contas_distintas": len(contas),
        "rotulo": ({"disponivel": True, "coluna": next(c for c in colunas if mapa.get(c) == "rotulo"),
                    "positivos": positivos} if tem_rotulo else
                   {"disponivel": False, "motivo": "o dataset não tem coluna de rótulo (Is Laundering ou rotulo)"}),
        "problemas": problemas, "avisos": avisos,
        "duracao_s": round(time.monotonic() - inicio, 3), "validado_em": agora_iso(),
    }
    if caminho_padroes is not None and Path(caminho_padroes).is_file():
        try:
            saida["tipologias"] = {"disponivel": True, "origem": "registrada no dataset (arquivo de padrões)",
                                   **tp.resumo_arquivo(tp.ler_arquivo_padroes(Path(caminho_padroes)))}
        except tp.ErroPadroes as exc:
            saida["tipologias"] = {"disponivel": False, "motivo": f"arquivo de padrões recusado: {exc}"}
            saida["avisos"].append(f"O arquivo de padrões não pôde ser lido ({exc}); a análise seguirá sem tipologias.")
    else:
        saida["tipologias"] = {"disponivel": False,
                               "motivo": "nenhum arquivo de padrões (tipologias) acompanha este dataset"}
    if validas == 0:
        raise ErroDataset([problema(f"nenhuma das {lidas} linhas é válida", "Corrija os problemas listados abaixo "
                                    "e envie de novo.")] + problemas)
    return saida


# ---------------------------------------------------------------------------
# Repositório (enviados + disponíveis no servidor)
# ---------------------------------------------------------------------------
class RepositorioDatasets:
    """Guarda os datasets enviados e descobre os já disponíveis no servidor."""

    def __init__(self, raiz: Path, registro: Any = None, config_financeiro: Optional[Dict[str, Any]] = None):
        self.raiz = Path(raiz)
        self.pasta = self.raiz / PASTA
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.registro = registro
        self.config_financeiro = config_financeiro or {}
        self._trava = threading.RLock()
        self._threads: Dict[str, threading.Thread] = {}
        self._progresso: Dict[str, Dict[str, int]] = {}
        for arq in self.pasta.glob("*/dataset.json"):  # validação interrompida por queda do servidor
            reg = ler_json(arq)
            if reg and reg.get("status") == "validando":
                reg.update(status="erro", erro={"problemas": [problema(
                    "a validação foi interrompida (o servidor reiniciou)", "Use Validar de novo.")]})
                gravar_json_atomico(arq, reg)

    # -- registro em disco ----------------------------------------------------
    def _arq(self, did: str) -> Path:
        base = "_servidor" if did.startswith("srv-") else did
        return self.pasta / base / (f"{did}.json" if did.startswith("srv-") else "dataset.json")

    def _gravar(self, reg: Dict[str, Any]) -> None:
        gravar_json_atomico(self._arq(reg["id"]), reg)

    def _log(self, evento: str, mensagem: str, nivel: str = "info", **ctx: Any) -> None:
        if self.registro is not None:
            self.registro.sistema(evento, mensagem, nivel, **ctx)

    # -- datasets do servidor ---------------------------------------------------
    def _descobrir(self) -> Dict[str, Dict[str, Any]]:
        achados: Dict[str, Dict[str, Any]] = {}
        for pasta, procedencia in PASTAS_SERVIDOR:
            base = self.raiz / pasta
            if not base.is_dir():
                continue
            for caminho in sorted(base.iterdir()):
                if caminho.is_file() and caminho.suffix.lower() in EXTENSOES:
                    rel = f"{pasta}/{caminho.name}"
                    did = "srv-" + hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]
                    achados[did] = {"caminho": caminho, "procedencia": procedencia, "padroes": None}
        trans = self.config_financeiro.get("transacoes")
        if trans and Path(trans).is_file() and Path(trans).suffix.lower() in EXTENSOES:
            did = "srv-" + hashlib.sha1(b"config:financeiro.transacoes").hexdigest()[:12]
            pad = self.config_financeiro.get("padroes")
            achados[did] = {"caminho": Path(trans), "procedencia": "configurado em ml_config.local.toml",
                            "padroes": Path(pad) if pad and Path(pad).is_file() else None}
        return achados

    def _registro_servidor(self, did: str, info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        caminho: Path = info["caminho"]
        st = caminho.stat()
        assinatura = [st.st_size, st.st_mtime_ns]
        reg = ler_json(self._arq(did))
        if reg and reg.get("assinatura") == assinatura:
            return reg
        try:  # só lista o que tem cabeçalho de transações; o resto não é dataset deste painel
            identificar(caminho)
        except (ErroDataset, OSError):
            return None
        return {"id": did, "origem": "servidor", "nome": caminho.name, "bytes": st.st_size,
                "procedencia": info["procedencia"], "assinatura": assinatura, "status": "nao_validado",
                "padroes": ({"nome": info["padroes"].name, "bytes": info["padroes"].stat().st_size}
                            if info["padroes"] else None),
                "validacao": None}

    # -- consulta ---------------------------------------------------------------
    def listar(self) -> List[Dict[str, Any]]:
        with self._trava:
            saida = []
            for arq in self.pasta.glob("*/dataset.json"):
                reg = ler_json(arq)
                if reg:
                    saida.append(self._com_progresso(reg))
            saida.sort(key=lambda r: r.get("ordem", 0), reverse=True)
            for did, info in self._descobrir().items():
                reg = self._registro_servidor(did, info)
                if reg:
                    saida.append(self._com_progresso(reg))
            return saida

    def _com_progresso(self, reg: Dict[str, Any]) -> Dict[str, Any]:
        reg = dict(reg)
        reg.pop("assinatura", None)
        if reg.get("status") == "validando":
            reg["progresso"] = dict(self._progresso.get(reg["id"], {}))
        return reg

    def obter(self, did: str) -> Dict[str, Any]:
        with self._trava:
            if not re.fullmatch(r"(srv-[0-9a-f]{12}|ds-[0-9a-f]{12})", did or ""):
                raise KeyError(did)
            if did.startswith("srv-"):
                info = self._descobrir().get(did)
                reg = self._registro_servidor(did, info) if info else None
            else:
                reg = ler_json(self._arq(did))
            if not reg:
                raise KeyError(did)
            return self._com_progresso(reg)

    def caminhos(self, did: str) -> Tuple[Path, Optional[Path]]:
        """Arquivo de dados e de padrões no disco (uso interno; nunca vem do cliente)."""
        if did.startswith("srv-"):
            info = self._descobrir().get(did)
            if not info:
                raise KeyError(did)
            return info["caminho"], info["padroes"]
        d = self.pasta / did
        dados = next((p for p in (d / "dados.csv", d / "dados.zip") if p.is_file()), None)
        if dados is None:
            raise KeyError(did)
        pad = d / "padroes.txt"
        return dados, pad if pad.is_file() else None

    # -- envio ---------------------------------------------------------------------
    @staticmethod
    def _salvar(origem: BinaryIO, destino: Path, limite: int, o_que: str) -> int:
        total = 0
        with open(destino, "wb") as fh:
            while True:
                bloco = origem.read(1 << 20)
                if not bloco:
                    break
                total += len(bloco)
                if total > limite:
                    raise ErroDataset([problema(
                        f"{o_que} passa do limite de {limite / 1e6:.0f} MB",
                        "Divida o arquivo por período, ou compacte o CSV em um ZIP.")], 413)
                fh.write(bloco)
        return total

    def enviar(self, arquivo: BinaryIO, nome: Optional[str], padroes: Optional[BinaryIO] = None,
               nome_padroes: Optional[str] = None, validar: bool = True,
               ativa: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
        """Grava o envio com nome interno fixo e inicia a validação em segundo plano."""
        rotulo = nome_seguro(nome)
        ext = Path(rotulo).suffix.lower()
        if ext not in EXTENSOES:
            self._log("envio_recusado", "Envio recusado: extensão não aceita", "aviso", extensao=ext or "(nenhuma)")
            raise ErroDataset([problema(f"extensão '{ext or '(nenhuma)'}' não aceita",
                                        "Envie um arquivo .csv ou um .zip contendo um único CSV.")], 415)
        did = "ds-" + secrets.token_hex(6)
        d = self.pasta / did
        d.mkdir(parents=True)
        try:
            n = self._salvar(arquivo, d / f"dados{ext}", LIMITE_BYTES, "o dataset")
            if n == 0:
                raise ErroDataset([problema("o arquivo está vazio", "Envie um CSV com cabeçalho e dados.", linha=1)])
            reg: Dict[str, Any] = {"id": did, "origem": "enviado", "nome": rotulo, "bytes": n,
                                   "enviado_em": agora_iso(), "ordem": time.time_ns(), "status": "validando",
                                   "padroes": None,
                                   "validacao": None}
            if padroes is not None:
                rotulo_p = nome_seguro(nome_padroes, "padroes.txt")
                if Path(rotulo_p).suffix.lower() not in EXTENSOES_PADROES:
                    raise ErroDataset([problema("o arquivo de padrões precisa ser .txt",
                                                "Envie o arquivo de padrões do dataset (por exemplo "
                                                "HI-Small_Patterns.txt) ou deixe o campo vazio.")], 415)
                np_ = self._salvar(padroes, d / "padroes.txt", LIMITE_PADROES_BYTES, "o arquivo de padrões")
                if np_:
                    reg["padroes"] = {"nome": rotulo_p, "bytes": np_}
                else:
                    (d / "padroes.txt").unlink()
        except ErroDataset as exc:
            shutil.rmtree(d, ignore_errors=True)
            self._log("envio_recusado", f"Envio recusado: {exc.problemas[0]['problema']}", "aviso", nome=rotulo)
            raise
        except Exception:
            shutil.rmtree(d, ignore_errors=True)
            raise
        with self._trava:
            self._gravar(reg)
        self._log("envio", "Dataset enviado", dataset=did, nome=rotulo, bytes=n,
                  com_padroes=reg["padroes"] is not None)
        self._aplicar_retencao(manter=did)
        if validar:
            self.validar(did, ativa=ativa)
        return self.obter(did)

    def _aplicar_retencao(self, manter: str) -> None:
        with self._trava:
            regs = [r for r in (ler_json(a) for a in self.pasta.glob("ds-*/dataset.json")) if r]
            regs.sort(key=lambda r: r.get("ordem", 0), reverse=True)
            for reg in regs[MAX_ENVIADOS:]:
                if reg["id"] != manter and reg.get("status") != "validando" and not reg.get("em_uso"):
                    shutil.rmtree(self.pasta / reg["id"], ignore_errors=True)
                    self._log("retencao", "Dataset enviado mais antigo removido pelo limite de retenção",
                              dataset=reg["id"], limite=MAX_ENVIADOS)

    def marcar_uso(self, did: str, em_uso: bool) -> None:
        if did.startswith("srv-"):
            return
        with self._trava:
            reg = ler_json(self._arq(did))
            if reg:
                reg["em_uso"] = bool(em_uso)
                self._gravar(reg)

    # -- validação -------------------------------------------------------------------
    def validar(self, did: str, esperar: bool = False, ativa: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
        """Inicia a validação em segundo plano (ou espera por ela, nos testes).

        ``ativa`` informa se a sessão da interface que pediu a validação continua ativa;
        se deixar de estar, a validação para no fim do bloco em leitura.
        """
        with self._trava:
            reg = self.obter(did)
            t = self._threads.get(did)
            if t is None or not t.is_alive():
                if did.startswith("srv-"):
                    info = self._descobrir()[did]
                    st = info["caminho"].stat()
                    reg["assinatura"] = [st.st_size, st.st_mtime_ns]
                reg.update(status="validando", validacao=None)
                reg.pop("erro", None)
                reg.pop("progresso", None)
                self._gravar(reg)
                self._progresso[did] = {"bytes_lidos": 0, "bytes_total": 0, "linhas_lidas": 0}
                t = threading.Thread(target=self._validar, args=(did, ativa), name=f"validar-{did}", daemon=True)
                self._threads[did] = t
                t.start()
        if esperar:
            t.join()
        return self.obter(did)

    def _validar(self, did: str, ativa: Optional[Callable[[], bool]] = None) -> None:
        def progresso(lidos: int, total: int, linhas: int) -> None:
            self._progresso[did] = {"bytes_lidos": int(lidos), "bytes_total": int(total), "linhas_lidas": int(linhas)}

        self._log("validacao_inicio", "Validação iniciada", dataset=did)
        reg = ler_json(self._arq(did)) or {}
        try:
            dados, pad = self.caminhos(did)
            val = validar_arquivo(dados, pad, progresso, (lambda: not ativa()) if ativa else None)
            status = "valido_com_recusas" if val["linhas"]["recusadas"] else "valido"
            reg.update(status=status, validacao=val)
            self._log("validacao_fim", "Validação concluída", dataset=did, situacao=status,
                      linhas_lidas=val["linhas"]["lidas"], linhas_validas=val["linhas"]["validas"],
                      linhas_recusadas=val["linhas"]["recusadas"], formato=val["formato"],
                      duracao_s=val["duracao_s"])
        except Cancelado:
            reg.update(status="erro", validacao=None, erro={"problemas": [problema(
                "a validação parou porque a sessão da interface expirou ou foi encerrada",
                "Com a página aberta, use Validar este dataset de novo.")]})
            self._log("validacao_interrompida", "Validação interrompida: a sessão da interface expirou", "aviso",
                      dataset=did)
        except ErroDataset as exc:
            reg.update(status="invalido", validacao=None, erro={"problemas": exc.problemas})
            self._log("validacao_fim", f"Dataset inválido: {exc.problemas[0]['problema']}", "aviso", dataset=did,
                      situacao="invalido", problemas=len(exc.problemas))
        except Exception as exc:  # erro inesperado: visível na tela, sem derrubar o servidor
            reg.update(status="erro", validacao=None, erro={"problemas": [problema(
                f"erro inesperado ao validar ({type(exc).__name__})", "Tente de novo; se persistir, confira o "
                "arquivo e os logs do sistema.")]})
            self._log("validacao_erro", f"Erro ao validar: {type(exc).__name__}", "erro", dataset=did)
        with self._trava:
            self._gravar(reg)
            self._progresso.pop(did, None)
