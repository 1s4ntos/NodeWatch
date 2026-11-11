"""Análise de datasets novos (área "Analisar dataset" da interface).

Fluxo: o usuário seleciona um arquivo → o servidor **valida** (formato, colunas,
tipos, datas, valores) e mostra o que é possível analisar → só a ação
**Analisar dataset**, com uma sessão ativa, gera previsões com o modelo salvo.

Formatos aceitos (independentes de nome, caminho, datas, contas ou tamanho):

* ``hismall_v1`` — transações no formato original do IBM AML (cabeçalho
  ``Timestamp,From Bank,Account,To Bank,Account,...``, ``Account`` repetido:
  o 1º é a origem e o 2º o destino); ``Is Laundering`` opcional;
* ``transacao_hismall_v1`` — os mesmos campos com nomes em português
  (``id_transacao,timestamp,banco_origem,...``); ``rotulo`` opcional;
* ``rede_v1`` — medições com os atributos de rede já preparados; ``alvo``
  opcional.

Reconhecidos, mas não analisáveis aqui: CSV de previsões (vai para "Explorar
previsões") e o CSV do grafo (``step,type,amount,nameOrig,nameDest``), que
não tem banco, moeda nem data absoluta: nada disso é inventado.

Cada análise tem identidade, pasta e estado financeiro **próprios** (nunca
mistura histórico de outro arquivo). Um histórico anterior compatível pode ser
informado; ele é cortado antes do primeiro minuto do dataset e a cobertura é
registrada. Os rótulos, quando existem, só servem para uma avaliação separada:
não entram nos preditores e não disparam treino.

Processamento: o arquivo é lido e validado em blocos, ordenado por minuto
(ordenação estável; ``linha_origem`` guarda a linha original) e pontuado em
blocos alinhados ao minuto, com o mesmo estado incremental do processamento
de eventos (mesmos 49 atributos, sem reajustar nada). Pontos seguros de
interrupção: o fim de cada bloco. Checkpoint (estado + cursor + tamanho da
saída) a cada 30 s e em toda pausa, cancelamento ou expiração da sessão.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.ml import eventos as ev
from src.ml.esquemas import COLUNAS_HISMALL, ESQUEMA_REDE_V1, FEATURES_REDE, CLASSES_REDE
from src.ml.incremental import EstadoFinanceiro
from src.ml.ingestao import _abrir_binario, _normalizar_cabecalho
from src.ml.previsao import AVISO_LAVAGEM, _deriva, pontuar_lavagem, tabela_previsoes_rede

LIMITE_BYTES = 256_000_000
LIMITE_HISTORICO_BYTES = 512_000_000
BLOCO_FINANCEIRO = 20_000
BLOCO_REDE = 20_000
LEITURA_EM_BLOCOS = 250_000
CHECKPOINT_S = 30.0
PASTA_RESULTADOS = Path("artefatos_ml") / "analises"

CAMPOS_PT = ("id_transacao", "timestamp", "banco_origem", "conta_origem", "banco_destino", "conta_destino",
             "valor_pago", "moeda_pagamento", "valor_recebido", "moeda_recebimento", "formato")
CAMPOS_GRAFO = ("step", "type", "amount", "nameOrig", "nameDest")
OBRIGATORIAS_REDE = ("id_fluxo", "anchor_id", "probe_id", "timestamp", *FEATURES_REDE)

FORMATOS: Dict[str, Dict[str, Any]] = {
    "hismall_v1": {
        "dominio": "lavagem", "nome": "Transações no formato original do IBM AML (HI-Small)",
        "cabecalho": ",".join(COLUNAS_HISMALL[:-1]),
        "rotulo": "Is Laundering (opcional; 0 ou 1)",
        "regras": ["Timestamp em AAAA/MM/DD HH:MM (UTC presumido; resolução de minuto)",
                   "From Bank/To Bank numéricos; a conta é identificada por banco-conta",
                   "a 1ª coluna Account é a origem e a 2ª, o destino",
                   "valores numéricos >= 0; moedas e formato não vazios",
                   "moedas e formatos fora dos do treino são aceitos, mas sinalizados"],
    },
    "transacao_hismall_v1": {
        "dominio": "lavagem", "nome": "Transações com nomes de colunas em português",
        "cabecalho": ",".join(CAMPOS_PT),
        "rotulo": "rotulo (opcional; 0 ou 1)",
        "regras": ["timestamp em ISO 8601, AAAA/MM/DD HH:MM ou época (s); sem fuso = UTC",
                   "id_transacao único e estável (repetido = recusado)",
                   "demais regras iguais às do formato hismall_v1"],
    },
    "rede_v1": {
        "dominio": "rede", "nome": "Medições de rede com atributos já preparados",
        "cabecalho": ",".join(OBRIGATORIAS_REDE),
        "rotulo": "alvo (opcional; OK, RISCO ou FALHA da próxima medição)",
        "regras": ["os 21 atributos rede_v1 precisam vir prontos (telemetria bruta não é aceita: "
                   "a referência p95/p99 por fluxo não está documentada)",
                   "faixas, domínios e sentinelas -1 conforme docs/ml/DICIONARIO_DADOS.md",
                   "chave id_fluxo + timestamp repetida = recusada"],
    },
}


class ErroAnalise(ValueError):
    def __init__(self, problemas: List[str], acao: str = ""):
        self.problemas = list(problemas)
        self.acao = acao
        super().__init__("; ".join(self.problemas))


# ---------------------------------------------------------------------------
# Detecção de formato
# ---------------------------------------------------------------------------
def ler_cabecalho(caminho: Path) -> List[str]:
    with _abrir_binario(caminho) as fh:
        linha = fh.readline().decode("utf-8-sig", errors="replace")
    return _normalizar_cabecalho(linha)


def detectar_formato(colunas: List[str]) -> Dict[str, Any]:
    """Formato e análises possíveis; o que falta para as demais. Nunca completa colunas."""
    from src.ml.exploracao import detectar_dominio
    cols = set(colunas)
    previsao = detectar_dominio(colunas)
    if previsao:
        return {"formato": f"previsao_{previsao}_v1", "dominio": None, "analisavel": False,
                "possiveis": [f"Explorar previsões ({'rede' if previsao == 'rede' else 'financeira'})"],
                "faltando": {}, "leitura": "É um arquivo de PREVISÕES já calculadas, não de dados novos. "
                                          "Abra-o em Explorar previsões (Importar CSV)."}
    if colunas[:len(COLUNAS_HISMALL) - 1] == list(COLUNAS_HISMALL[:-1]) and \
            len(colunas) in (len(COLUNAS_HISMALL) - 1, len(COLUNAS_HISMALL)) and \
            (len(colunas) == len(COLUNAS_HISMALL) - 1 or colunas[-1] == COLUNAS_HISMALL[-1]):
        return {"formato": "hismall_v1", "dominio": "lavagem", "analisavel": True,
                "possiveis": ["Lavagem (score, alertas, motivos verificáveis)"],
                "rotulos": "Is Laundering" in cols, "faltando": {}}
    if set(CAMPOS_PT) <= cols:
        return {"formato": "transacao_hismall_v1", "dominio": "lavagem", "analisavel": True,
                "possiveis": ["Lavagem (score, alertas, motivos verificáveis)"],
                "rotulos": "rotulo" in cols, "faltando": {}}
    if set(OBRIGATORIAS_REDE) <= cols:
        return {"formato": "rede_v1", "dominio": "rede", "analisavel": True,
                "possiveis": ["Estado da próxima medição de rede (classe, score, alerta, deriva)"],
                "rotulos": "alvo" in cols, "faltando": {}}
    faltando = {
        "hismall_v1": [c for c in COLUNAS_HISMALL[:-1] if c not in cols],
        "transacao_hismall_v1": [c for c in CAMPOS_PT if c not in cols],
        "rede_v1": [c for c in OBRIGATORIAS_REDE if c not in cols],
    }
    if set(CAMPOS_GRAFO) <= cols:
        return {"formato": "csv_grafo_nodewatch", "dominio": None, "analisavel": False,
                "possiveis": ["Análise de grafos (ciclos, SCC, fan-in/out) pela CLI do NodeWatch"],
                "faltando": {"transacao_hismall_v1": faltando["transacao_hismall_v1"]},
                "leitura": ("Serve para a análise de grafos, mas não para o modelo financeiro: não tem bancos, "
                            "moedas, valor recebido nem data absoluta (step é relativo). Esses campos não são "
                            "inventados.")}
    melhor = min(faltando, key=lambda k: len(faltando[k]) / len(FORMATOS[k]["cabecalho"].split(",")))
    return {"formato": None, "dominio": None, "analisavel": False, "possiveis": [], "faltando": faltando,
            "mais_proximo": melhor,
            "leitura": f"Nenhum contrato atendido. O mais próximo é {melhor}; faltam: "
                       f"{', '.join(faltando[melhor][:12])}{' …' if len(faltando[melhor]) > 12 else ''}."}


# ---------------------------------------------------------------------------
# Leitura financeira (validação por linha, mesmas derivações do leitor do HI-Small)
# ---------------------------------------------------------------------------
@dataclass
class LeituraFinanceira:
    trans: pd.DataFrame           # mesmo formato de DadosHISmall.trans, só linhas válidas, ordem do arquivo
    nomes_contas: np.ndarray
    ids: np.ndarray               # identidade de cada linha válida (texto)
    rotulos: Optional[np.ndarray]
    lidas: int
    recusadas: Dict[str, int]
    exemplos_recusa: List[Dict[str, Any]]


_FMT_HISMALL = "%Y/%m/%d %H:%M"
_EPOCA = pd.Timestamp(0, tz="UTC")


def _tempo(serie: pd.Series, so_hismall: bool) -> pd.Series:
    t = pd.to_datetime(serie, format=_FMT_HISMALL, errors="coerce", utc=True)
    if so_hismall:
        return t
    faltam = t.isna() & (serie != "")
    if faltam.any():
        iso = pd.to_datetime(serie[faltam], format="ISO8601", errors="coerce", utc=True)
        num = pd.to_numeric(serie[faltam], errors="coerce")
        epoca = pd.to_datetime(num.where((num >= 0) & (num <= 4e9)), unit="s", utc=True)
        t.loc[faltam] = iso.fillna(epoca)
    return t


def ler_financeiro(caminho: Path, formato: str, limite_exemplos: int = 20) -> LeituraFinanceira:
    """Lê em blocos, valida cada linha e devolve só as válidas, com o motivo das recusadas."""
    if formato == "hismall_v1":
        cab = ler_cabecalho(caminho)
        nomes = cab
        mapa = {"Timestamp": "ts", "From Bank": "banco_o", "Account": "conta_o", "To Bank": "banco_d",
                "Account.1": "conta_d", "Amount Received": "valor_rec", "Receiving Currency": "moeda_rec",
                "Amount Paid": "valor_pag", "Payment Currency": "moeda_pag", "Payment Format": "formato",
                "Is Laundering": "rotulo"}
        leitor_kw = {"header": None, "skiprows": 1, "names": nomes}
    else:
        mapa = {"id_transacao": "id", "timestamp": "ts", "banco_origem": "banco_o", "conta_origem": "conta_o",
                "banco_destino": "banco_d", "conta_destino": "conta_d", "valor_recebido": "valor_rec",
                "moeda_recebimento": "moeda_rec", "valor_pago": "valor_pag", "moeda_pagamento": "moeda_pag",
                "formato": "formato", "rotulo": "rotulo"}
        leitor_kw = {}
    partes, recusadas, exemplos = [], {}, []
    lidas = 0
    with _abrir_binario(caminho) as fh:
        for bloco in pd.read_csv(fh, dtype=str, keep_default_na=False, chunksize=LEITURA_EM_BLOCOS, **leitor_kw):
            bloco = bloco.rename(columns=mapa)
            bloco = bloco[[c for c in dict.fromkeys(mapa.values()) if c in bloco.columns]]
            bloco = bloco.apply(lambda s: s.str.strip())
            linha = np.arange(lidas, lidas + len(bloco), dtype=np.int64)
            lidas += len(bloco)
            motivo = pd.Series("", index=bloco.index, dtype=object)

            def marcar(mascara: pd.Series, texto: str) -> None:
                vazio = (motivo == "") & mascara
                motivo[vazio] = texto

            t = _tempo(bloco["ts"], formato == "hismall_v1")
            marcar(t.isna(), "data/hora inválida")
            for c, nome in (("banco_o", "banco de origem"), ("banco_d", "banco de destino")):
                marcar(~bloco[c].str.fullmatch(r"\d+"), f"{nome} não numérico")
            for c, nome in (("conta_o", "conta de origem"), ("conta_d", "conta de destino"),
                            ("moeda_pag", "moeda de pagamento"), ("moeda_rec", "moeda de recebimento"),
                            ("formato", "formato de pagamento")):
                marcar(bloco[c] == "", f"{nome} vazia")
            valores = {}
            for c, nome in (("valor_pag", "valor pago"), ("valor_rec", "valor recebido")):
                v = pd.to_numeric(bloco[c], errors="coerce")
                marcar(~(np.isfinite(v) & (v >= 0) & (v <= 1e15)), f"{nome} ausente, negativo ou não numérico")
                valores[c] = v
            rot = None
            if "rotulo" in bloco:
                rot = pd.to_numeric(bloco["rotulo"], errors="coerce")
                marcar(~rot.isin([0, 1]), "rótulo fora de {0, 1}")
            if "id" in bloco:
                marcar(bloco["id"] == "", "id_transacao vazio")
            ok = (motivo == "").to_numpy()
            for m, n in motivo[~ok].value_counts().items():
                recusadas[m] = recusadas.get(m, 0) + int(n)
            for i in np.flatnonzero(~ok)[:max(0, limite_exemplos - len(exemplos))]:
                exemplos.append({"linha": int(linha[i]) + 2, "motivo": motivo.iloc[i]})  # +2: cabeçalho e base 1
            b = bloco[ok]
            parte = pd.DataFrame({
                "linha": linha[ok],
                "id": b["id"].to_numpy() if "id" in b else linha[ok].astype(str),
                "minuto": ((t[ok] - _EPOCA) // pd.Timedelta(minutes=1)).to_numpy(dtype=np.int64),
                "banco_origem": b["banco_o"].astype(np.int64).to_numpy().astype(np.int32),
                "nome_o": (b["banco_o"].astype(np.int64).astype(str) + "-" + b["conta_o"]).to_numpy(),
                "banco_destino": b["banco_d"].astype(np.int64).to_numpy().astype(np.int32),
                "nome_d": (b["banco_d"].astype(np.int64).astype(str) + "-" + b["conta_d"]).to_numpy(),
                "valor_recebido": valores["valor_rec"][ok].to_numpy(dtype=np.float64),
                "moeda_recebimento": b["moeda_rec"].to_numpy(),
                "valor_pago": valores["valor_pag"][ok].to_numpy(dtype=np.float64),
                "moeda_pagamento": b["moeda_pag"].to_numpy(),
                "formato": b["formato"].to_numpy(),
            })
            if rot is not None:
                parte["rotulo"] = rot[ok].to_numpy().astype(np.int8)
            partes.append(parte)
    if not partes or not sum(len(p) for p in partes):
        raise ErroAnalise([f"nenhuma linha válida entre {lidas} lidas"] +
                          [f"{m}: {n}" for m, n in sorted(recusadas.items(), key=lambda x: -x[1])[:5]],
                          "Confira o formato das colunas (datas, bancos numéricos, valores).")
    df = pd.concat(partes, ignore_index=True)
    codigos, nomes_contas = pd.factorize(np.concatenate([df["nome_o"].to_numpy(), df["nome_d"].to_numpy()]))
    n = len(df)
    trans = pd.DataFrame({
        "id_transacao": df["linha"].to_numpy(),
        "minuto": df["minuto"].to_numpy(),
        "banco_origem": df["banco_origem"].to_numpy(),
        "conta_origem": codigos[:n].astype(np.int32),
        "banco_destino": df["banco_destino"].to_numpy(),
        "conta_destino": codigos[n:].astype(np.int32),
        "valor_recebido": df["valor_recebido"].to_numpy(),
        "moeda_recebimento": pd.Categorical(df["moeda_recebimento"]),
        "valor_pago": df["valor_pago"].to_numpy(),
        "moeda_pagamento": pd.Categorical(df["moeda_pagamento"]),
        "formato": pd.Categorical(df["formato"]),
    })
    rotulos = df["rotulo"].to_numpy() if "rotulo" in df else None
    return LeituraFinanceira(trans, np.asarray(nomes_contas, dtype=object), df["id"].to_numpy(dtype=object),
                             rotulos, lidas, recusadas, exemplos)


def ler_rede_validando(caminho: Path, limite_exemplos: int = 20) -> Tuple[pd.DataFrame, int, Dict[str, int], List[Dict]]:
    """CSV rede_v1 → linhas válidas (com ``linha_origem``), recusando linha a linha."""
    df = pd.read_csv(caminho, dtype={"id_fluxo": str, "classe_atual": str, "alvo": str, "split": str})
    lidas = len(df)
    df.insert(0, "linha_origem", np.arange(lidas, dtype=np.int64))
    recusadas: Dict[str, int] = {}
    exemplos: List[Dict] = []
    boas = []
    for ini in range(0, lidas, 5_000):
        parte = df.iloc[ini:ini + 5_000]
        validas, ruins = ev.validar_lote_rede(parte.drop(columns=["linha_origem"]))
        boas.append(parte.loc[validas.index])
        for i, probs in ruins:
            m = probs[0].split(":")[0] + ": fora do contrato"
            recusadas[m] = recusadas.get(m, 0) + 1
            if len(exemplos) < limite_exemplos:
                exemplos.append({"linha": int(parte.iloc[i]["linha_origem"]) + 2, "motivo": "; ".join(probs)})
    df = pd.concat(boas, ignore_index=True) if boas else df.iloc[:0]
    dup = df.duplicated(["id_fluxo", "timestamp"], keep="first")
    if dup.any():
        recusadas["chave id_fluxo + timestamp repetida"] = int(dup.sum())
        df = df[~dup].reset_index(drop=True)
    df["timestamp"] = df["timestamp"].astype(np.int64)
    if df.empty:
        raise ErroAnalise([f"nenhuma linha válida entre {lidas} lidas"], "Confira as faixas e domínios de rede_v1.")
    return df, lidas, recusadas, exemplos


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 22), b""):
            h.update(bloco)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Análises (jobs)
# ---------------------------------------------------------------------------
SITUACOES_ATIVAS = ("executando", "pausando", "cancelando")


class GerenciadorAnalises:
    """Cria, valida, executa e controla análises. Uma em execução por vez."""

    def __init__(self, raiz: Path, obter_modelo: Callable[[], Any], sessao_ativa: Callable[[Optional[str]], bool]):
        self.raiz = Path(raiz)
        self.pasta = self.raiz / PASTA_RESULTADOS
        self.pasta_jobs = self.pasta / ".jobs"
        self.pasta_jobs.mkdir(parents=True, exist_ok=True)
        self.obter_modelo = obter_modelo
        self.sessao_ativa = sessao_ativa
        self._trava = threading.RLock()
        self._threads: Dict[str, threading.Thread] = {}
        self._pedidos: Dict[str, str] = {}  # id → "pausar" | "cancelar"
        self.metas: Dict[str, Dict[str, Any]] = {}
        for arq in sorted(self.pasta_jobs.glob("*/meta.json")):
            try:
                meta = json.loads(arq.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if meta.get("situacao") in SITUACOES_ATIVAS + ("preparando",):
                # o processo anterior caiu no meio: nunca retoma sozinho
                meta["situacao"] = "interrompida"
                meta["motivo"] = "servidor reiniciado durante a execução; retome explicitamente"
                self._gravar_meta(meta)
            self.metas[meta["id"]] = meta

    # -- persistência de metadados -------------------------------------------
    def _dir(self, aid: str) -> Path:
        return self.pasta_jobs / aid

    def _gravar_meta(self, meta: Dict[str, Any]) -> None:
        d = self._dir(meta["id"])
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "meta.json.tmp"
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        os.replace(tmp, d / "meta.json")

    def listar(self) -> List[Dict[str, Any]]:
        with self._trava:
            return sorted((dict(m) for m in self.metas.values()), key=lambda m: m["criada_em"], reverse=True)

    def obter(self, aid: str) -> Dict[str, Any]:
        with self._trava:
            if aid not in self.metas:
                raise KeyError(aid)
            return dict(self.metas[aid])

    # -- criação e validação --------------------------------------------------
    def criar(self, conteudo: bytes, nome: str, historico: Optional[bytes] = None,
              nome_historico: Optional[str] = None) -> Dict[str, Any]:
        if len(conteudo) > LIMITE_BYTES:
            raise ErroAnalise([f"arquivo com {len(conteudo) / 1e6:.0f} MB; o limite é {LIMITE_BYTES / 1e6:.0f} MB"],
                              "Divida o arquivo em períodos e analise cada um, informando o anterior como histórico.")
        if historico is not None and len(historico) > LIMITE_HISTORICO_BYTES:
            raise ErroAnalise([f"histórico acima de {LIMITE_HISTORICO_BYTES / 1e6:.0f} MB"])
        nome = Path(nome or "dataset.csv").name
        sufixo = ".zip" if nome.lower().endswith(".zip") else ".csv"
        aid = time.strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)
        d = self._dir(aid)
        d.mkdir(parents=True)
        entrada = d / f"entrada{sufixo}"
        entrada.write_bytes(conteudo)
        try:
            info = detectar_formato(ler_cabecalho(entrada))
            meta: Dict[str, Any] = {
                "id": aid, "criada_em": ev.agora(), "criada_em_utc": ev.iso(ev.agora()),
                "dataset": {"nome": nome, "bytes": len(conteudo), "sha256": sha256(entrada)},
                "deteccao": info, "situacao": "invalida", "motivo": "", "sessao_dona": None,
                "progresso": {"lidas": 0, "validas": 0, "recusadas": 0, "processadas": 0},
                "limites": {"bytes": LIMITE_BYTES, "bloco": BLOCO_FINANCEIRO,
                            "leitura": "o arquivo inteiro é analisado; nada é amostrado"},
            }
            if info.get("analisavel"):
                meta.update(self._validar(entrada, info))
                meta["situacao"] = "pronta"
                if historico is not None:
                    if info["dominio"] != "lavagem":
                        raise ErroAnalise(["histórico só se aplica a transações financeiras"])
                    hnome = Path(nome_historico or "historico.csv").name
                    harq = d / ("historico.zip" if hnome.lower().endswith(".zip") else "historico.csv")
                    harq.write_bytes(historico)
                    hinfo = detectar_formato(ler_cabecalho(harq))
                    if hinfo.get("dominio") != "lavagem":
                        raise ErroAnalise(["o histórico não segue um formato de transações aceito"] +
                                          ([hinfo["leitura"]] if hinfo.get("leitura") else []))
                    meta["historico"] = {"nome": hnome, "bytes": len(historico), "sha256": sha256(harq),
                                         "formato": hinfo["formato"], "arquivo": harq.name}
            else:
                meta["motivo"] = info.get("leitura", "formato não analisável")
        except ErroAnalise:
            shutil.rmtree(d, ignore_errors=True)
            raise
        with self._trava:
            self.metas[aid] = meta
            self._gravar_meta(meta)
        return dict(meta)

    def _validar(self, entrada: Path, info: Dict[str, Any]) -> Dict[str, Any]:
        modelo = self.obter_modelo()
        if info["dominio"] == "lavagem":
            lf = ler_financeiro(entrada, info["formato"])
            prep = modelo.codificadores["financeiro"]
            moedas = pd.Series(lf.trans["moeda_pagamento"].astype(str))
            formatos = pd.Series(lf.trans["formato"].astype(str))
            dup = int(pd.Series(lf.ids).duplicated().sum())
            minutos = lf.trans["minuto"]
            return {
                "progresso": {"lidas": lf.lidas, "validas": int(len(lf.trans)) - dup,
                              "recusadas": int(sum(lf.recusadas.values())) + dup, "processadas": 0},
                "recusas": dict(lf.recusadas, **({"id_transacao repetido": dup} if dup else {})),
                "exemplos_recusa": lf.exemplos_recusa,
                "resumo": {
                    "periodo_utc": [ev.iso(int(minutos.min()) * 60), ev.iso(int(minutos.max()) * 60)],
                    "contas": int(len(lf.nomes_contas)), "rotulos": lf.rotulos is not None,
                    "ordenado_no_arquivo": bool(minutos.is_monotonic_increasing),
                },
                "dominio_indicadores": {
                    "moedas_fora_do_treino": sorted(set(moedas.unique()) - set(prep.moedas)),
                    "fracao_sem_taxa_de_cambio": float((~moedas.isin(list(prep.cambio))).mean()),
                    "formatos_fora_do_treino": sorted(set(formatos.unique()) - set(prep.formatos)),
                },
            }
        df, lidas, recusadas, exemplos = ler_rede_validando(entrada)
        return {
            "progresso": {"lidas": lidas, "validas": int(len(df)), "recusadas": int(sum(recusadas.values())),
                          "processadas": 0},
            "recusas": recusadas, "exemplos_recusa": exemplos,
            "resumo": {"periodo_utc": [ev.iso(int(df["timestamp"].min())), ev.iso(int(df["timestamp"].max()))],
                       "fluxos": int(df["id_fluxo"].nunique()), "rotulos": "alvo" in df},
            "dominio_indicadores": {},
        }

    # -- controle -------------------------------------------------------------
    def iniciar(self, aid: str, sessao: str) -> Dict[str, Any]:
        """Ação explícita "Analisar dataset" (ou retomar): exige sessão ativa e assume a análise."""
        if not self.sessao_ativa(sessao):
            raise PermissionError("sessão inativa: abra a interface para analisar")
        with self._trava:
            meta = self.metas.get(aid)
            if meta is None:
                raise KeyError(aid)
            if meta["situacao"] not in ("pronta", "pausada", "interrompida", "erro"):
                raise ErroAnalise([f"análise {meta['situacao']}: não pode ser iniciada"])
            ocupada = [m["id"] for m in self.metas.values() if m["situacao"] in SITUACOES_ATIVAS]
            if ocupada:
                raise ErroAnalise([f"a análise {ocupada[0]} está em execução"], "Pause-a ou espere terminar.")
            meta.update(situacao="executando", motivo="", sessao_dona=sessao,
                        execucoes=meta.get("execucoes", 0) + 1)
            meta.setdefault("inicio_utc", ev.iso(ev.agora()))
            self._gravar_meta(meta)
            self._pedidos.pop(aid, None)
            t = threading.Thread(target=self._executar, args=(aid,), name=f"analise-{aid}", daemon=True)
            self._threads[aid] = t
            t.start()
            return dict(meta)

    def pedir(self, aid: str, acao: str, sessao: str) -> Dict[str, Any]:
        """Pausar ou cancelar (qualquer sessão ativa pode pedir); efeito no próximo ponto seguro."""
        if not self.sessao_ativa(sessao):
            raise PermissionError("sessão inativa")
        with self._trava:
            meta = self.metas[aid]
            if acao == "cancelar" and meta["situacao"] in ("pronta", "pausada", "interrompida", "erro"):
                meta.update(situacao="cancelada", motivo="cancelada antes de terminar; resultados parciais mantidos")
                self._gravar_meta(meta)
                self._atualizar_relatorio(meta)
            elif meta["situacao"] == "executando":
                self._pedidos[aid] = acao
                meta["situacao"] = "pausando" if acao == "pausar" else "cancelando"
                self._gravar_meta(meta)
            return dict(meta)

    def esperar(self, aid: str, timeout: float = 120.0) -> Dict[str, Any]:
        t = self._threads.get(aid)
        if t:
            t.join(timeout)
        return self.obter(aid)

    # -- execução -------------------------------------------------------------
    def _ponto_seguro(self, aid: str) -> Optional[Tuple[str, str]]:
        meta = self.metas[aid]
        pedido = self._pedidos.get(aid)
        if pedido == "cancelar":
            return "cancelada", "cancelada pelo usuário; resultados parciais mantidos e identificados"
        if pedido == "pausar":
            return "pausada", "pausada pelo usuário"
        if not self.sessao_ativa(meta.get("sessao_dona")):
            return "pausada", "a sessão responsável expirou ou foi encerrada; retome explicitamente"
        return None

    def _executar(self, aid: str) -> None:
        meta = self.metas[aid]
        try:
            if meta["deteccao"]["dominio"] == "lavagem":
                fim = self._executar_financeiro(aid)
            else:
                fim = self._executar_rede(aid)
        except Exception as exc:  # erro visível na interface; checkpoint anterior preservado
            fim = ("erro", f"{type(exc).__name__}: {exc}")
        with self._trava:
            meta["situacao"], meta["motivo"] = fim
            if fim[0] == "concluida":
                meta["fim_utc"] = ev.iso(ev.agora())
            self._pedidos.pop(aid, None)
            self._gravar_meta(meta)
            self._atualizar_relatorio(meta)

    def _saida(self, meta: Dict[str, Any]) -> Path:
        base = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(meta["dataset"]["nome"]).stem)[:40].strip("_") or "dataset"
        dominio = meta["deteccao"]["dominio"]
        return self.pasta / f"{meta['id']}_{base}__previsoes_{dominio}.csv"

    def _anexar(self, caminho: Path, df: pd.DataFrame) -> None:
        novo = not caminho.is_file() or caminho.stat().st_size == 0
        df.to_csv(caminho, mode="w" if novo else "a", header=novo, index=False, encoding="utf-8",
                  lineterminator="\n")

    def _retomar_saida(self, meta: Dict[str, Any], caminho: Path) -> None:
        marca = meta.get("checkpoint", {}).get("bytes_saida", 0)
        if caminho.is_file() and caminho.stat().st_size > marca:
            with open(caminho, "r+b") as fh:  # o que foi escrito depois do checkpoint é refeito
                fh.truncate(marca)
        if marca == 0 and caminho.is_file():
            caminho.unlink()

    def _checkpoint(self, meta: Dict[str, Any], caminho: Path, cursor: int, estado: Optional[EstadoFinanceiro]) -> None:
        if estado is not None:
            estado.salvar(self._dir(meta["id"]) / "estado.pkl", {"analise": meta["id"]})
        meta["checkpoint"] = {"cursor": cursor, "bytes_saida": caminho.stat().st_size if caminho.is_file() else 0,
                              "em_utc": ev.iso(ev.agora()), "processadas": meta["progresso"]["processadas"],
                              "acumulado": copy.deepcopy(meta.get("acumulado"))}
        with self._trava:
            self._gravar_meta(meta)
            self._atualizar_relatorio(meta)

    def _modelo_usado(self, cab) -> Dict[str, Any]:
        return {"versao": cab.metadados.get("versao", ""), "limiar": cab.limiar_alerta,
                "treinado_ate": cab.metadados.get("treinado_ate") or cab.metadados.get("treinado_ate_utc")}

    def _executar_financeiro(self, aid: str) -> Tuple[str, str]:
        meta = self.metas[aid]
        modelo = self.obter_modelo()
        cab, prep = modelo.cabeca("lavagem"), modelo.codificadores["financeiro"]
        meta["modelo_usado"] = self._modelo_usado(cab)
        d = self._dir(aid)
        entrada = next(d.glob("entrada.*"))
        lf = ler_financeiro(entrada, meta["deteccao"]["formato"])
        ordem = np.argsort(lf.trans["minuto"].to_numpy(), kind="stable")  # mantém a ordem do arquivo no minuto
        trans = lf.trans.iloc[ordem].reset_index(drop=True)
        ids = lf.ids[ordem]
        rotulos = lf.rotulos[ordem] if lf.rotulos is not None else None
        caminho = self._saida(meta)
        cursor = int(meta.get("checkpoint", {}).get("cursor", 0))
        arq_estado = d / "estado.pkl"
        if cursor and arq_estado.is_file():
            estado, _ = EstadoFinanceiro.carregar(arq_estado, prep)
            self._retomar_saida(meta, caminho)
        else:
            cursor = 0
            self._retomar_saida({"checkpoint": {}}, caminho)
            estado = EstadoFinanceiro(prep)
            if meta.get("historico"):
                hinfo = meta["historico"]
                hl = ler_financeiro(d / hinfo["arquivo"], hinfo["formato"])
                primeiro = int(trans["minuto"].min())
                antes = hl.trans["minuto"] < primeiro
                meta["historico"].update(linhas_validas=int(len(hl.trans)), ignoradas_no_periodo=int((~antes).sum()))
                if antes.any():
                    hist = hl.trans[antes].reset_index(drop=True)
                    meta["historico"]["cobertura"] = estado.carregar_historico(hist, hl.nomes_contas, hinfo["nome"])
                else:
                    meta["historico"]["cobertura"] = None
                    meta["historico"]["aviso"] = "nenhuma transação do histórico é anterior ao dataset"
        nomes = lf.nomes_contas
        n = len(trans)
        minutos = trans["minuto"].to_numpy()
        quantis = {c: prep.quantis[f"{c}_p99"] for c in ("n_env_origem_24h", "orig_distintas_destino",
                                                          "dest_distintos_origem") if f"{c}_p99" in prep.quantis}
        # Contadores coerentes com o cursor: o que veio depois do checkpoint será refeito.
        salvo = meta.get("checkpoint", {}).get("acumulado") if cursor else None
        ind = meta["acumulado"] = copy.deepcopy(salvo) if salvo else {
            "acima_p99": {c: 0 for c in quantis}, "historico_incompleto": 0, "pontuadas": 0,
            "recusadas_no_estado": {}}
        meta["progresso"]["processadas"] = ind["pontuadas"]
        ultimo_ck = time.monotonic()
        while cursor < n:
            parada = self._ponto_seguro(aid)
            if parada:
                self._checkpoint(meta, caminho, cursor, estado)
                return parada
            fim = min(cursor + BLOCO_FINANCEIRO, n)
            while fim < n and minutos[fim] == minutos[fim - 1]:  # bloco termina na virada do minuto
                fim += 1
            bloco = trans.iloc[cursor:fim]
            for pos, r in zip(range(cursor, fim), bloco.itertuples(index=False)):
                t = float(r.minuto * 60)
                tx = {"id_transacao": str(ids[pos]), "epoca": t, "minuto": int(r.minuto), "timestamp_disponivel": t,
                      "banco_origem": str(r.banco_origem), "banco_destino": str(r.banco_destino),
                      "conta_origem": str(nomes[r.conta_origem]), "conta_destino": str(nomes[r.conta_destino]),
                      "valor_pago": float(r.valor_pago), "valor_recebido": float(r.valor_recebido),
                      "moeda_pagamento": str(r.moeda_pagamento), "moeda_recebimento": str(r.moeda_recebimento),
                      "formato": str(r.formato), "_pos": pos}
                rej = estado.receber(tx)
                if rej is not None:
                    ind["recusadas_no_estado"][rej.motivo] = ind["recusadas_no_estado"].get(rej.motivo, 0) + 1
            fechados = estado.fechar_ate(None)
            if fechados:
                txs = [tx for mf in fechados for tx in mf.transacoes]
                X = pd.concat([mf.X for mf in fechados], ignore_index=True)
                inc = np.concatenate([mf.historico_incompleto for mf in fechados])
                score, motivos = pontuar_lavagem(cab, prep, X, pd.Series([tx["formato"] for tx in txs]))
                pos = np.array([tx["_pos"] for tx in txs])
                saida = pd.DataFrame({
                    "arquivo_origem": meta["dataset"]["nome"],
                    "linha_origem": trans["id_transacao"].to_numpy()[pos],
                    "id_transacao": [tx["id_transacao"] for tx in txs],
                    "timestamp_transacao": pd.to_datetime(minutos[pos], unit="m").strftime("%Y-%m-%d %H:%M:%S"),
                    "conta_origem": [tx["conta_origem"] for tx in txs],
                    "conta_destino": [tx["conta_destino"] for tx in txs],
                    "valor_pago": [tx["valor_pago"] for tx in txs],
                    "moeda_pagamento": [tx["moeda_pagamento"] for tx in txs],
                    "formato": [tx["formato"] for tx in txs],
                    "score_lavagem": score,
                    "alerta_lavagem": score >= cab.limiar_alerta,
                    "limiar_alerta": cab.limiar_alerta,
                    "motivos_verificaveis": motivos,
                    "historico_incompleto": inc,
                    "sinais_utilizados": "financeiro",
                    "cobertura_vinculo": "sem_vinculo",
                    "pontuacao_fraude_financeira": "indisponivel",
                    "versao_modelo": cab.metadados.get("versao", ""),
                    "tipo_saida": "previsao",
                })
                if rotulos is not None:  # referência para avaliação separada; não entra no modelo
                    saida["Is Laundering"] = rotulos[pos]
                self._anexar(caminho, saida)
                for c, q in quantis.items():
                    ind["acima_p99"][c] += int((X[c].to_numpy() > q).sum())
                ind["historico_incompleto"] += int(inc.sum())
                ind["pontuadas"] += len(txs)
            cursor = fim
            meta["progresso"]["processadas"] = ind["pontuadas"]
            if time.monotonic() - ultimo_ck >= CHECKPOINT_S:
                self._checkpoint(meta, caminho, cursor, estado)
                ultimo_ck = time.monotonic()
        self._checkpoint(meta, caminho, cursor, estado)
        meta["avaliacao"] = self._avaliar_lavagem(caminho, cab.limiar_alerta, rotulos is not None)
        meta["dominio_indicadores"]["acima_do_p99_do_treino"] = {
            c: {"fracao": v / max(ind["pontuadas"], 1), "referencia": 0.01} for c, v in ind["acima_p99"].items()}
        meta["dominio_indicadores"]["fracao_historico_incompleto"] = ind["historico_incompleto"] / max(ind["pontuadas"], 1)
        return "concluida", ""

    def _executar_rede(self, aid: str) -> Tuple[str, str]:
        meta = self.metas[aid]
        modelo = self.obter_modelo()
        cab = modelo.cabeca("estado_rede")
        meta["modelo_usado"] = self._modelo_usado(cab)
        entrada = next(self._dir(aid).glob("entrada.*"))
        df, _, _, _ = ler_rede_validando(entrada)
        caminho = self._saida(meta)
        cursor = int(meta.get("checkpoint", {}).get("cursor", 0))
        self._retomar_saida(meta if cursor else {"checkpoint": {}}, caminho)
        ultimo_ck = time.monotonic()
        n = len(df)
        while cursor < n:
            parada = self._ponto_seguro(aid)
            if parada:
                self._checkpoint(meta, caminho, cursor, None)
                return parada
            parte = df.iloc[cursor:cursor + BLOCO_REDE].copy()
            parte.insert(0, "arquivo_origem", meta["dataset"]["nome"])
            saida, _ = tabela_previsoes_rede(cab, parte)
            if "alvo" in parte:
                saida["alvo"] = parte["alvo"].to_numpy()
            self._anexar(caminho, saida)
            cursor += len(parte)
            meta["progresso"]["processadas"] = cursor
            if time.monotonic() - ultimo_ck >= CHECKPOINT_S:
                self._checkpoint(meta, caminho, cursor, None)
                ultimo_ck = time.monotonic()
        self._checkpoint(meta, caminho, cursor, None)
        from src.ml.preparacao import matriz_rede
        amostra = df.iloc[:200_000]
        deriva = _deriva(matriz_rede(amostra, cab.usa_classe_atual), cab.metadados.get("referencia_psi", {}),
                         cab.metadados.get("taxa_sentinela_treino", {}))
        meta["dominio_indicadores"] = {"psi_acima_0_25": deriva["colunas_psi_acima_0_25"],
                                       "psi": {k: v for k, v in deriva["psi"].items() if v is not None},
                                       "leitura": deriva["leitura"]}
        meta["avaliacao"] = self._avaliar_rede(caminho, "alvo" in df)
        return "concluida", ""

    # -- avaliação separada (só com rótulos do arquivo) ------------------------
    @staticmethod
    def _avaliar_lavagem(caminho: Path, limiar: float, com_rotulo: bool) -> Dict[str, Any]:
        if not com_rotulo:
            return {"disponivel": False, "motivo": "o arquivo não tem rótulos (Is Laundering/rotulo): precisão, "
                                                   "recall e demais métricas supervisionadas ficam indisponíveis"}
        from sklearn.metrics import average_precision_score
        out = pd.read_csv(caminho, usecols=["score_lavagem", "Is Laundering"])
        y, s = out["Is Laundering"].to_numpy(), out["score_lavagem"].to_numpy()
        alerta = s >= limiar
        tp = int((alerta & (y == 1)).sum())
        return {"disponivel": True, "linhas": int(len(y)), "positivos": int(y.sum()), "alertas": int(alerta.sum()),
                "precisao": tp / max(int(alerta.sum()), 1), "recall": tp / max(int(y.sum()), 1),
                "average_precision": float(average_precision_score(y, s)) if 0 < y.sum() < len(y) else None,
                "leitura": "Avaliação separada com os rótulos do próprio arquivo, no limiar oficial. Não ajusta "
                           "nada e não substitui a avaliação oficial; outra população pode ter outro desempenho."}

    @staticmethod
    def _avaliar_rede(caminho: Path, com_rotulo: bool) -> Dict[str, Any]:
        if not com_rotulo:
            return {"disponivel": False, "motivo": "o arquivo não tem a coluna alvo: métricas supervisionadas "
                                                   "indisponíveis"}
        from sklearn.metrics import f1_score
        out = pd.read_csv(caminho, usecols=["classe_prevista", "alerta_rede", "alvo"], dtype=str)
        y, p = out["alvo"], out["classe_prevista"]
        alerta = out["alerta_rede"].str.lower() == "true"
        ruim = y != "OK"
        tp = int((alerta & ruim).sum())
        return {"disponivel": True, "linhas": int(len(y)), "acuracia": float((y == p).mean()),
                "macro_f1": float(f1_score(y, p, labels=list(CLASSES_REDE), average="macro", zero_division=0)),
                "precisao_alerta": tp / max(int(alerta.sum()), 1), "recall_alerta": tp / max(int(ruim.sum()), 1),
                "leitura": "Avaliação separada com o alvo do próprio arquivo, no limiar oficial."}

    def _atualizar_relatorio(self, meta: Dict[str, Any]) -> None:
        caminho = self._saida(meta) if meta.get("deteccao", {}).get("dominio") else None
        if not caminho or not caminho.is_file():
            return
        with open(caminho, "rb") as fh:
            linhas = max(sum(1 for _ in fh) - 1, 0)
        rel = {"tarefa": "lavagem" if meta["deteccao"]["dominio"] == "lavagem" else "estado_rede",
               "gerado_por": "Analisar dataset (interface)", "situacao": meta["situacao"],
               "linhas_previstas": linhas, "dataset": meta["dataset"], "modelo_usado": meta.get("modelo_usado"),
               "aviso": AVISO_LAVAGEM if meta["deteccao"]["dominio"] == "lavagem" else
               "Previsão do estado da próxima medição; não é fraude."}
        caminho.with_suffix(".relatorio.json").write_text(json.dumps(rel, ensure_ascii=False, indent=1, default=str),
                                                          encoding="utf-8")


def formatos_suportados() -> Dict[str, Any]:
    return {"formatos": FORMATOS, "limites": {"bytes": LIMITE_BYTES, "historico_bytes": LIMITE_HISTORICO_BYTES,
                                              "bloco_linhas": BLOCO_FINANCEIRO},
            "nao_analisaveis": {
                "previsao_rede_v1 / previsao_lavagem_v1": "previsões já calculadas: use Explorar previsões",
                "csv_grafo_nodewatch (step,type,amount,nameOrig,nameDest)":
                    "análise de grafos; falta banco, moeda, valor recebido e data absoluta para o modelo"}}
