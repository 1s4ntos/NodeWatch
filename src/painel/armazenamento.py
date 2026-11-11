"""Resultados por transação em SQLite (um arquivo por análise).

Por que SQLite (biblioteca padrão) e não JSON
    A tabela, os indicadores, as contas e o grafo precisam **filtrar, ordenar
    e paginar no servidor** sem carregar a análise inteira em memória nem no
    navegador. Um JSON obrigaria a ler e percorrer tudo a cada filtro (uma
    análise de 5 milhões de transações passa de 1 GB em JSON). O SQLite grava
    em blocos durante a pontuação (resultado parcial consultável), tem índices
    nos campos filtráveis e não exige serviço nem dependência nova. O
    manifesto da análise continua em JSON (``pipeline.py``).

Identidade
    ``id_exibicao`` (chave primária) é a posição cronológica da transação no
    dataset inteiro: ordenação por data e hora e, em horários iguais, pela
    ordem original da linha. Não muda com filtros, ordenação ou página.

Filtros
    Um único conjunto de filtros (``Filtros``) gera o mesmo ``WHERE`` para os
    indicadores, a tabela e as contas. O grafo usa os mesmos filtros, menos os
    de conta, que escolhem a conta em foco.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from src.painel import score as sc
from src.painel import tipologias as tp
from src.painel.datasets import NAO_INFORMADO
from src.painel.util import minuto_iso

TAMANHO_PAGINA_PADRAO = 50
TAMANHO_PAGINA_MAX = 200
MAX_CONTAS_RISCO = 10
GRAFO_PROFUNDIDADE_PADRAO = 2
GRAFO_PROFUNDIDADE_MAX = 3
GRAFO_MAX_NOS = 30
GRAFO_MAX_ARESTAS = 60
GRAFO_FRONTEIRA = 300
_LOTE_IN = 400

REGRA_CONTAS = (
    "Ordenação: 1º, quantidade de transações com alerta em que a conta participa (como origem ou destino) no "
    "recorte; 2º, maior score entre essas transações; 3º, em empate, ordem alfabética da conta. Só entram contas "
    "com ao menos um alerta. Não existe score por conta: os números são contagens de transações."
)

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS transacoes (
  id_exibicao INTEGER PRIMARY KEY,
  linha_arquivo INTEGER NOT NULL,
  id_original TEXT,
  minuto INTEGER NOT NULL,
  banco_origem TEXT NOT NULL, conta_origem TEXT NOT NULL, no_origem TEXT NOT NULL,
  banco_destino TEXT NOT NULL, conta_destino TEXT NOT NULL, no_destino TEXT NOT NULL,
  valor_pago REAL NOT NULL, moeda_pagamento TEXT NOT NULL,
  valor_recebido REAL NOT NULL, moeda_recebimento TEXT NOT NULL,
  formato TEXT NOT NULL,
  score INTEGER NOT NULL, score_bruto REAL NOT NULL, alerta INTEGER NOT NULL,
  motivos TEXT NOT NULL, historico_incompleto INTEGER NOT NULL,
  rotulo INTEGER, tipologias TEXT NOT NULL, tentativas TEXT NOT NULL, extras TEXT
);
CREATE TABLE IF NOT EXISTS tipologia_tx (
  tipologia TEXT NOT NULL, id_exibicao INTEGER NOT NULL, PRIMARY KEY (tipologia, id_exibicao)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);
"""
_INDICES = (
    # ix_resumo cobre a consulta da visão geral (e os filtros de score, período, moeda e valor) sem ler a tabela
    ("ix_resumo", "score, formato, minuto, rotulo, tipologias, moeda_pagamento, valor_pago"),
    ("ix_minuto", "minuto"), ("ix_no_origem", "no_origem"), ("ix_no_destino", "no_destino"),
    ("ix_conta_origem", "conta_origem"), ("ix_conta_destino", "conta_destino"),
    ("ix_banco_origem", "banco_origem"), ("ix_banco_destino", "banco_destino"),
    ("ix_moeda", "moeda_pagamento"), ("ix_valor", "valor_pago"),
)
_COLUNAS = ("id_exibicao", "linha_arquivo", "id_original", "minuto", "banco_origem", "conta_origem", "no_origem",
            "banco_destino", "conta_destino", "no_destino", "valor_pago", "moeda_pagamento", "valor_recebido",
            "moeda_recebimento", "formato", "score", "score_bruto", "alerta", "motivos", "historico_incompleto",
            "rotulo", "tipologias", "tentativas", "extras")
ORDENACOES = {"id_exibicao": "id_exibicao", "score": "score", "valor_pago": "valor_pago"}


class ErroFiltro(ValueError):
    """Filtro inválido: ``campo`` identifica o controle da tela."""

    def __init__(self, campo: str, mensagem: str):
        self.campo = campo
        self.mensagem = mensagem
        super().__init__(f"{campo}: {mensagem}")


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
@dataclass
class Filtros:
    de: Optional[int] = None            # minuto (inclusive)
    ate: Optional[int] = None           # minuto (inclusive)
    moeda: str = ""
    alerta: Optional[bool] = None
    valor_min: Optional[float] = None
    banco_origem: str = ""
    banco_destino: str = ""
    conta_origem: str = ""
    conta_destino: str = ""
    score_min: Optional[int] = None
    score_max: Optional[int] = None

    def where(self, incluir_contas: bool = True, prefixo: str = "", incluir_valor: bool = True) -> Tuple[str, List[Any]]:
        p = prefixo
        partes: List[str] = []
        args: List[Any] = []
        if self.de is not None:
            partes.append(f"{p}minuto >= ?"); args.append(self.de)
        if self.ate is not None:
            partes.append(f"{p}minuto <= ?"); args.append(self.ate)
        if self.moeda:
            partes.append(f"{p}moeda_pagamento = ?"); args.append(self.moeda)
        if self.alerta is True:
            partes.append(f"{p}score >= {sc.SCORE_ALERTA}")
        elif self.alerta is False:
            partes.append(f"{p}score < {sc.SCORE_ALERTA}")
        if incluir_valor and self.valor_min is not None:
            # "+": o valor mínimo quase não restringe (o padrão é 1), então não deve guiar a escolha do índice
            partes.append(f"+{p}valor_pago >= ?"); args.append(self.valor_min)
        if self.banco_origem:
            partes.append(f"{p}banco_origem = ?"); args.append(self.banco_origem)
        if self.banco_destino:
            partes.append(f"{p}banco_destino = ?"); args.append(self.banco_destino)
        if incluir_contas and self.conta_origem:
            partes.append(f"({p}no_origem = ? OR {p}conta_origem = ?)"); args += [self.conta_origem] * 2
        if incluir_contas and self.conta_destino:
            partes.append(f"({p}no_destino = ? OR {p}conta_destino = ?)"); args += [self.conta_destino] * 2
        if self.score_min is not None:
            partes.append(f"{p}score >= ?"); args.append(self.score_min)
        if self.score_max is not None:
            partes.append(f"{p}score <= ?"); args.append(self.score_max)
        return (" AND ".join(partes) or "1=1"), args

    def ativos(self) -> Dict[str, Any]:
        saida: Dict[str, Any] = {}
        for k, v in self.__dict__.items():
            if v in (None, ""):
                continue
            if k in ("de", "ate"):
                saida[k] = minuto_iso(v)
            elif k == "alerta":
                saida[k] = "sim" if v else "nao"
            else:
                saida[k] = v
        return saida


def _data(params: Mapping[str, str], chave: str, rotulo: str) -> Optional[int]:
    v = (params.get(chave) or "").strip()
    if not v:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            d = datetime.strptime(v, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        minuto = int(d.timestamp() // 60)
        if fmt in ("%Y-%m-%d", "%d/%m/%Y") and chave == "ate":
            minuto += 1439  # só a data no campo "até": vale o dia inteiro
        return minuto
    raise ErroFiltro(chave, f"{rotulo}: '{v}' não é data e hora válida (use dia/mês/ano hora:minuto).")


def _inteiro(params: Mapping[str, str], chave: str, rotulo: str) -> Optional[int]:
    v = (params.get(chave) or "").strip()
    if not v:
        return None
    if not re.fullmatch(r"\d{1,4}", v) or not sc.SCORE_MIN <= int(v) <= sc.SCORE_MAX:
        raise ErroFiltro(chave, f"{rotulo}: use um número inteiro de 0 a 1000.")
    return int(v)


def filtros_de_parametros(params: Mapping[str, str]) -> Filtros:
    """Converte os parâmetros da requisição; levanta :class:`ErroFiltro` com o campo e a correção."""
    alerta_txt = (params.get("alerta") or "").strip().lower()
    if alerta_txt not in ("", "todos", "sim", "nao"):
        raise ErroFiltro("alerta", "Alerta: use Todos, Com alerta ou Sem alerta.")
    valor_txt = (params.get("valor_min") or "").strip().replace(",", ".")
    valor: Optional[float] = None
    if valor_txt:
        try:
            valor = float(valor_txt)
        except ValueError:
            raise ErroFiltro("valor_min", "Valor mínimo: informe um número.") from None
        if not math.isfinite(valor) or valor < 1:
            raise ErroFiltro("valor_min", "Valor mínimo: o menor valor aceito é 1 unidade da moeda.")
    f = Filtros(
        de=_data(params, "de", "De"), ate=_data(params, "ate", "Até"),
        moeda=(params.get("moeda") or "").strip(),
        alerta=None if alerta_txt in ("", "todos") else alerta_txt == "sim",
        valor_min=valor,
        banco_origem=(params.get("banco_origem") or "").strip(),
        banco_destino=(params.get("banco_destino") or "").strip(),
        conta_origem=(params.get("conta_origem") or "").strip(),
        conta_destino=(params.get("conta_destino") or "").strip(),
        score_min=_inteiro(params, "score_min", "Score mínimo"),
        score_max=_inteiro(params, "score_max", "Score máximo"),
    )
    if f.de is not None and f.ate is not None and f.de > f.ate:
        raise ErroFiltro("ate", "Até: precisa ser igual ou posterior a De.")
    if f.score_min is not None and f.score_max is not None and f.score_min > f.score_max:
        raise ErroFiltro("score_max", "Score máximo: precisa ser maior ou igual ao score mínimo.")
    for campo in ("banco_origem", "banco_destino"):
        v = getattr(f, campo)
        if v:
            if not re.fullmatch(r"\d{1,18}", v):
                raise ErroFiltro(campo, "Banco: informe o código numérico do banco (só dígitos).")
            setattr(f, campo, str(int(v)))
    return f


# ---------------------------------------------------------------------------
# Conexão e gravação
# ---------------------------------------------------------------------------
def conectar(caminho: Path, leitura: bool = True) -> sqlite3.Connection:
    caminho = Path(caminho)
    if leitura:
        if not caminho.is_file():
            raise FileNotFoundError(str(caminho))
        con = sqlite3.connect(caminho.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    else:
        con = sqlite3.connect(str(caminho), timeout=30)
    con.row_factory = sqlite3.Row
    return con


class Gravador:
    """Grava os resultados em blocos, na ordem cronológica, e finaliza com índices."""

    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.con = conectar(self.caminho, leitura=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.executescript(_ESQUEMA)
        self.con.commit()
        self.gravadas = 0

    def inserir(self, bloco: pd.DataFrame) -> int:
        """``bloco`` traz as colunas de ``_COLUNAS`` (``rotulo`` e ``extras`` opcionais)."""
        n = len(bloco)
        if not n:
            return 0
        cols = []
        for c in _COLUNAS:
            if c in bloco:
                valores = bloco[c].tolist()
            else:
                valores = [None] * n
            cols.append(valores)
        self.con.executemany(f"INSERT INTO transacoes ({','.join(_COLUNAS)}) VALUES ({','.join('?' * len(_COLUNAS))})",
                             zip(*cols))
        pares = [(t, int(i)) for i, tipos in zip(bloco["id_exibicao"].tolist(), bloco["tipologias"].tolist()) if tipos
                 for t in tipos.split(tp.SEPARADOR)]
        if pares:
            self.con.executemany("INSERT OR IGNORE INTO tipologia_tx (tipologia, id_exibicao) VALUES (?, ?)", pares)
        self.con.commit()
        self.gravadas += n
        return n

    def finalizar(self, progresso: Optional[Callable[[int, int], None]] = None) -> None:
        _finalizar(self.con, progresso)
        self.con.close()

    def fechar(self) -> None:
        try:
            self.con.close()
        except sqlite3.Error:
            pass


def _finalizar(con: sqlite3.Connection, progresso: Optional[Callable[[int, int], None]] = None) -> None:
    total = len(_INDICES) + 1
    for i, (nome, coluna) in enumerate(_INDICES):
        con.execute(f"CREATE INDEX IF NOT EXISTS {nome} ON transacoes({coluna})")
        con.commit()
        if progresso:
            progresso(i + 1, total)
    con.execute("ANALYZE")
    con.execute("INSERT OR REPLACE INTO meta (chave, valor) VALUES ('finalizado', '1')")
    con.commit()
    con.execute("PRAGMA journal_mode=DELETE")  # arquivo único: leitores abrem só para leitura
    if progresso:
        progresso(total, total)


def garantir_finalizado(caminho: Path) -> None:
    """Análise interrompida sem finalizar (queda do servidor): cria os índices antes de consultar."""
    con = conectar(caminho, leitura=False)
    try:
        con.executescript(_ESQUEMA)
        feito = con.execute("SELECT valor FROM meta WHERE chave = 'finalizado'").fetchone()
        if not feito:
            _finalizar(con)
    finally:
        con.close()


def garantir_indices(caminho: Path) -> List[str]:
    """Cria os índices que faltarem num resultado gravado por uma versão anterior (devolve os criados).

    Só acrescenta índices; não altera nenhuma linha de resultado.
    """
    con = conectar(caminho)
    try:
        existentes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    finally:
        con.close()
    faltam = [(nome, coluna) for nome, coluna in _INDICES if nome not in existentes]
    if faltam:
        con = conectar(caminho, leitura=False)
        try:
            for nome, coluna in faltam:
                con.execute(f"CREATE INDEX IF NOT EXISTS {nome} ON transacoes({coluna})")
            con.commit()
        finally:
            con.close()
    return [nome for nome, _ in faltam]


def contagens_gerais(con: sqlite3.Connection) -> Dict[str, Any]:
    """Totais gravados no manifesto ao fim da análise (dataset inteiro, sem filtros)."""
    r = con.execute(
        f"SELECT COUNT(*) n, COALESCE(SUM(score >= {sc.SCORE_ALERTA}), 0) alertas, "
        f"COALESCE(SUM(score <= {sc.CORTE_BAIXA}), 0) baixa, MIN(minuto) ini, MAX(minuto) fim, "
        "COALESCE(SUM(historico_incompleto), 0) incompleto, COALESCE(SUM(rotulo = 1), 0) rotulados, "
        "COALESCE(SUM(tipologias <> ''), 0) com_tipologia FROM transacoes").fetchone()
    n, alertas, baixa = int(r["n"]), int(r["alertas"]), int(r["baixa"])
    return {
        "pontuadas": n, "alertas": alertas,
        "por_faixa": {"baixa": baixa, "intermediaria": n - baixa - alertas, "alta": alertas},
        "periodo": {"inicio": minuto_iso(r["ini"]), "fim": minuto_iso(r["fim"])} if n else None,
        "historico_incompleto": int(r["incompleto"]), "rotuladas_lavagem": int(r["rotulados"]),
        "com_tipologia": int(r["com_tipologia"]),
        "moedas": [x[0] for x in con.execute(
            "SELECT moeda_pagamento FROM transacoes GROUP BY 1 ORDER BY COUNT(*) DESC, 1 LIMIT 200")],
    }


# ---------------------------------------------------------------------------
# Visão geral do recorte
# ---------------------------------------------------------------------------
def _mediana(pares: Sequence[Tuple[int, int]], n: int) -> Optional[float]:
    """Mediana de valores inteiros dados como (valor, quantidade) em ordem crescente."""
    if not n:
        return None
    alvo1, alvo2 = (n - 1) // 2, n // 2
    acumulado, v1 = 0, None
    for valor, qtd in pares:
        acumulado += qtd
        if v1 is None and acumulado > alvo1:
            v1 = valor
        if acumulado > alvo2:
            return (v1 + valor) / 2
    return None


def visao_geral(con: sqlite3.Connection, f: Filtros, total_dataset: int, tem_tipologias: bool,
                tem_rotulo: bool, motivo_sem_tipologias: str = "") -> Dict[str, Any]:
    where, args = f.where()
    # Uma única passada (coberta por ix_resumo quando os filtros permitem) dá scores, formatos, rótulos e tipologias.
    linhas = con.execute(
        "SELECT score, formato, COUNT(*) n, MIN(minuto) ini, MAX(minuto) fim, COALESCE(SUM(rotulo = 1), 0) pos, "
        f"SUM(tipologias = '') sem FROM transacoes WHERE {where} GROUP BY score, formato ORDER BY score", args).fetchall()
    por_score: Dict[int, int] = {}
    por_formato: Dict[str, List[int]] = {}
    rotuladas = rotuladas_alerta = sem_tip = sem_tip_alerta = 0
    for r in linhas:
        valor, q, com_alerta = int(r["score"]), int(r["n"]), int(r["score"]) >= sc.SCORE_ALERTA
        por_score[valor] = por_score.get(valor, 0) + q
        fmt = por_formato.setdefault(r["formato"], [0, 0])
        fmt[0] += q
        fmt[1] += q if com_alerta else 0
        rotuladas += int(r["pos"])
        rotuladas_alerta += int(r["pos"]) if com_alerta else 0
        sem_tip += int(r["sem"])
        sem_tip_alerta += int(r["sem"]) if com_alerta else 0
    pares = sorted(por_score.items())
    n = sum(q for _, q in pares)
    por_faixa = {fx["id"]: 0 for fx in sc.FAIXAS}
    for valor, q in pares:
        por_faixa[sc.faixa(valor)] += q
    alertas = por_faixa["alta"]
    saida: Dict[str, Any] = {
        "registros": {"recorte": n, "dataset": int(total_dataset),
                      "legenda": "Transações que passam pelos filtros (recorte) e total de transações "
                                 "pontuadas do dataset."},
        "alertas": {"n": alertas, "proporcao": alertas / n if n else None,
                    "legenda": f"Transações do recorte com score {sc.SCORE_ALERTA} ou mais (faixa alta). "
                               "Alerta é sinal para investigação, não confirmação de lavagem."},
        "periodo": ({"inicio": minuto_iso(min(r["ini"] for r in linhas)),
                     "fim": minuto_iso(max(r["fim"] for r in linhas)),
                     "legenda": "Primeira e última data e hora entre as transações do recorte (horário do dataset)."}
                    if n else None),
        "score": ({"min": pares[0][0], "mediana": _mediana(pares, n), "max": pares[-1][0],
                   "legenda": "Menor, mediano e maior score (0 a 1000) entre as transações do recorte."}
                  if n else None),
        "faixas": [{**fx, "n": por_faixa[fx["id"]], "proporcao": por_faixa[fx["id"]] / n if n else None}
                   for fx in sc.FAIXAS],
        "filtros_ativos": f.ativos(),
    }
    # Formato de pagamento: % sobre as N transações do recorte; vazio = "Não informado"
    formatos = sorted(por_formato.items(), key=lambda kv: (-kv[1][0], kv[0]))
    saida["formatos"] = {
        "denominador": n,
        "legenda": (f"% das {n:,} transações do recorte".replace(",", ".") if n
                    else "Nenhuma transação no recorte."),
        "itens": [{"formato": nome or NAO_INFORMADO, "nao_informado": nome == "", "n": q, "alertas": a,
                   "proporcao": q / n} for nome, (q, a) in formatos],
    }
    # Rótulo do dataset: separado da previsão
    if tem_rotulo:
        saida["rotulo"] = {"disponivel": True, "rotuladas_lavagem": rotuladas,
                           "rotuladas_com_alerta": rotuladas_alerta,
                           "legenda": "Rótulo verdadeiro registrado no dataset (não é previsão): transações "
                                      "marcadas como lavagem no recorte e quantas delas receberam alerta."}
    else:
        saida["rotulo"] = {"disponivel": False, "motivo": "Este dataset não tem rótulo de lavagem."}
    # Tipologias registradas no dataset
    if tem_tipologias:
        where_t, args_t = f.where(prefixo="t.")
        contagem = {r["tipologia"]: (int(r["n"]), int(r["a"])) for r in con.execute(
            f"SELECT x.tipologia, COUNT(*) n, COALESCE(SUM(t.score >= {sc.SCORE_ALERTA}), 0) a FROM tipologia_tx x "
            f"JOIN transacoes t ON t.id_exibicao = x.id_exibicao WHERE {where_t} GROUP BY x.tipologia", args_t)}
        nomes = list(tp.TIPOLOGIAS) + sorted(set(contagem) - set(tp.TIPOLOGIAS))
        itens = [{"tipologia": t, "descricao": tp.DESCRICOES.get(t, "tipologia registrada no arquivo de padrões"),
                  "n": contagem.get(t, (0, 0))[0], "alertas": contagem.get(t, (0, 0))[1]} for t in nomes]
        itens.append({"tipologia": tp.NAO_IDENTIFICADO, "descricao": tp.DESCRICOES[tp.NAO_IDENTIFICADO],
                      "n": sem_tip, "alertas": sem_tip_alerta})
        saida["tipologias"] = {
            "disponivel": True, "origem": "registrada no dataset (arquivo de padrões); não é previsão do modelo",
            "itens": itens,
            "legenda": "Transações do recorte em cada tipologia registrada no dataset e quantas delas têm alerta. "
                       "Uma transação com mais de uma tipologia conta em cada uma, por isso a soma pode passar do "
                       f"total. \"{tp.NAO_IDENTIFICADO}\" reúne as transações sem tipologia registrada, o que "
                       "inclui as transações comuns.",
        }
    else:
        saida["tipologias"] = {"disponivel": False,
                               "motivo": motivo_sem_tipologias or "Este dataset não tem tipologias registradas."}
    saida["valor_minimo"] = fora_do_valor_minimo(con, f)
    saida["contas_risco"] = contas_de_maior_risco(con, f)
    return saida


def fora_do_valor_minimo(con: sqlite3.Connection, f: Filtros) -> Dict[str, Any]:
    """Impacto do filtro de valor mínimo: transações que passam nos demais filtros, mas ficam fora por valor.

    O valor é comparado na moeda de pagamento de cada transação, sem conversão. Por isso moedas de valor
    unitário alto (Bitcoin, por exemplo) são as mais afetadas por um mínimo de 1 unidade.
    """
    if f.valor_min is None:
        return {"aplicado": None, "fora": 0, "por_moeda": [],
                "legenda": "Sem valor mínimo: nenhuma transação fica fora por valor."}
    where, args = f.where(incluir_valor=False)
    linhas = con.execute(f"SELECT moeda_pagamento m, COUNT(*) n, COALESCE(SUM(score >= {sc.SCORE_ALERTA}), 0) a "
                         f"FROM transacoes WHERE {where} AND valor_pago < ? GROUP BY 1 ORDER BY n DESC, m",
                         args + [f.valor_min]).fetchall()
    fora = sum(int(r["n"]) for r in linhas)
    return {"aplicado": f.valor_min, "fora": fora, "alertas_fora": sum(int(r["a"]) for r in linhas),
            "por_moeda": [{"moeda": r["m"], "n": int(r["n"]), "alertas": int(r["a"])} for r in linhas[:8]],
            "legenda": ("Transações que passam nos outros filtros, mas têm valor pago abaixo do mínimo, na moeda "
                        "de cada uma (sem conversão). Para vê-las, apague o campo Valor mínimo e aplique.")}


def contas_de_maior_risco(con: sqlite3.Connection, f: Filtros, limite: int = MAX_CONTAS_RISCO) -> Dict[str, Any]:
    where, args = f.where()
    linhas = con.execute(
        f"WITH f AS MATERIALIZED (SELECT no_origem, no_destino, score FROM transacoes WHERE {where} "
        f"AND score >= {sc.SCORE_ALERTA}) "
        "SELECT conta, COUNT(*) alertas, MAX(score) maior_score, SUM(origem) como_origem, SUM(1 - origem) como_destino "
        "FROM (SELECT no_origem conta, score, 1 origem FROM f "
        "      UNION ALL SELECT no_destino, score, 0 FROM f WHERE no_destino <> no_origem) "
        "GROUP BY conta ORDER BY alertas DESC, maior_score DESC, conta ASC LIMIT ?", args + [int(limite)]).fetchall()
    contas = []
    for r in linhas:
        env = con.execute(f"SELECT COUNT(*) FROM transacoes WHERE {where} AND no_origem = ?",
                          args + [r["conta"]]).fetchone()[0]
        rec = con.execute(f"SELECT COUNT(*) FROM transacoes WHERE {where} AND no_destino = ? AND no_origem <> ?",
                          args + [r["conta"], r["conta"]]).fetchone()[0]
        banco, _, numero = r["conta"].partition("-")
        contas.append({"conta": r["conta"], "banco": banco, "numero": numero, "alertas": int(r["alertas"]),
                       "maior_score": int(r["maior_score"]), "alertas_como_origem": int(r["como_origem"]),
                       "alertas_como_destino": int(r["como_destino"]), "transacoes_no_recorte": int(env) + int(rec)})
    return {"regra": REGRA_CONTAS, "limite": int(limite), "contas": contas}


# ---------------------------------------------------------------------------
# Tabela e detalhes
# ---------------------------------------------------------------------------
def _linha(r: sqlite3.Row, completo: bool = False) -> Dict[str, Any]:
    d = {
        "id_exibicao": int(r["id_exibicao"]), "data_hora": minuto_iso(r["minuto"]),
        "banco_origem": r["banco_origem"], "conta_origem": r["conta_origem"], "no_origem": r["no_origem"],
        "banco_destino": r["banco_destino"], "conta_destino": r["conta_destino"], "no_destino": r["no_destino"],
        "valor_pago": r["valor_pago"], "moeda_pagamento": r["moeda_pagamento"],
        "valor_recebido": r["valor_recebido"], "moeda_recebimento": r["moeda_recebimento"],
        "formato": r["formato"] or NAO_INFORMADO, "score": int(r["score"]), "faixa": sc.faixa(r["score"]),
        "alerta": bool(r["alerta"]), "rotulo": None if r["rotulo"] is None else int(r["rotulo"]),
        "tipologias": r["tipologias"].split(tp.SEPARADOR) if r["tipologias"] else [],
        "linha_arquivo": int(r["linha_arquivo"]), "id_original": r["id_original"],
        "extras": json.loads(r["extras"]) if r["extras"] else {},
    }
    if completo:
        d.update(score_bruto=float(r["score_bruto"]), historico_incompleto=bool(r["historico_incompleto"]),
                 motivos=[m.strip() for m in r["motivos"].split(";") if m.strip()],
                 tentativas=[int(x) for x in r["tentativas"].split(tp.SEPARADOR)] if r["tentativas"] else [])
    return d


def pagina(con: sqlite3.Connection, f: Filtros, numero: int = 1, tamanho: int = TAMANHO_PAGINA_PADRAO,
           ordenar: str = "id_exibicao", direcao: str = "asc") -> Dict[str, Any]:
    if ordenar not in ORDENACOES:
        raise ErroFiltro("ordenar", f"Ordenação desconhecida: use {', '.join(ORDENACOES)}.")
    if direcao not in ("asc", "desc"):
        raise ErroFiltro("direcao", "Direção: use asc ou desc.")
    if not 1 <= int(tamanho) <= TAMANHO_PAGINA_MAX:
        raise ErroFiltro("tamanho", f"Tamanho da página: de 1 a {TAMANHO_PAGINA_MAX}.")
    where, args = f.where()
    total = int(con.execute(f"SELECT COUNT(*) FROM transacoes WHERE {where}", args).fetchone()[0])
    paginas = max(1, math.ceil(total / tamanho))
    numero = min(max(1, int(numero)), paginas)
    deslocamento = (numero - 1) * tamanho
    ordem = f"{ORDENACOES[ordenar]} {direcao.upper()}" + ("" if ordenar == "id_exibicao" else ", id_exibicao ASC")
    linhas = con.execute(f"SELECT * FROM transacoes WHERE {where} ORDER BY {ordem} LIMIT ? OFFSET ?",
                         args + [int(tamanho), deslocamento]).fetchall()
    itens = []
    for i, r in enumerate(linhas):
        d = _linha(r)
        d["posicao"] = deslocamento + i + 1
        itens.append(d)
    return {"total": total, "pagina": numero, "paginas": paginas, "tamanho": int(tamanho), "ordenar": ordenar,
            "direcao": direcao, "linhas": itens, "filtros_ativos": f.ativos()}


def detalhe(con: sqlite3.Connection, id_exibicao: int) -> Dict[str, Any]:
    r = con.execute("SELECT * FROM transacoes WHERE id_exibicao = ?", (int(id_exibicao),)).fetchone()
    if r is None:
        raise KeyError(id_exibicao)
    return _linha(r, completo=True)


# ---------------------------------------------------------------------------
# Grafo da conta em foco
# ---------------------------------------------------------------------------
DISPOSICOES: Dict[str, Dict[str, str]] = {
    "CYCLE": {"id": "circular", "nome": "circular (o caminho volta à conta inicial)"},
    "FAN-OUT": {"id": "leque_saida", "nome": "leque de saída (uma conta envia para várias)"},
    "FAN-IN": {"id": "leque_entrada", "nome": "leque de entrada (várias contas enviam para uma)"},
}
DISPOSICAO_CAMADAS = {"id": "camadas", "nome": "camadas da esquerda para a direita (quem envia → quem recebe)"}


def disposicao_para(tipologia: str) -> Dict[str, str]:
    """Disposição do grafo decidida **só** pela tipologia registrada (nunca pela aparência)."""
    return dict(DISPOSICOES.get(tipologia, DISPOSICAO_CAMADAS))


def rotulos_sem_colisao(ids: Iterable[str], largura: int = 16) -> Dict[str, str]:
    """Abrevia ``banco-conta`` sem que duas contas diferentes fiquem com o mesmo rótulo."""
    ids = list(dict.fromkeys(ids))

    def abreviar(texto: str, n: int) -> str:
        if len(texto) <= n:
            return texto
        cabeca = max(1, (n - 1) * 2 // 3)
        return texto[:cabeca] + "…" + texto[len(texto) - (n - 1 - cabeca):]

    n = largura
    while True:
        rot = {i: abreviar(i, n) for i in ids}
        if len(set(rot.values())) == len(ids) or n >= max((len(i) for i in ids), default=0):
            return rot if len(set(rot.values())) == len(ids) else {i: i for i in ids}
        n += 2


def resolver_conta(con: sqlite3.Connection, texto: str) -> List[str]:
    """Contas (``banco-conta``) que correspondem ao texto: o identificador completo ou só o número da conta."""
    texto = (texto or "").strip()
    if not texto:
        return []
    achadas = [r[0] for r in con.execute(
        "SELECT no FROM (SELECT no_origem no FROM transacoes WHERE no_origem = ?1 OR conta_origem = ?1 "
        "UNION SELECT no_destino FROM transacoes WHERE no_destino = ?1 OR conta_destino = ?1) ORDER BY no LIMIT 21",
        (texto,))]
    return achadas


def _arestas(con: sqlite3.Connection, where: str, args: List[Any], coluna: str, contas: Sequence[str]) -> List[sqlite3.Row]:
    saida: List[sqlite3.Row] = []
    contas = list(contas)
    for i in range(0, len(contas), _LOTE_IN):
        lote = contas[i:i + _LOTE_IN]
        saida += con.execute(
            f"SELECT no_origem o, no_destino d, moeda_pagamento moeda, COUNT(*) n, SUM(valor_pago) total, "
            f"SUM(score >= {sc.SCORE_ALERTA}) alertas, MAX(score) maior_score, MIN(minuto) primeiro, "
            f"MAX(minuto) ultimo FROM transacoes WHERE {where} AND {coluna} IN ({','.join('?' * len(lote))}) "
            "GROUP BY 1, 2, 3", args + lote).fetchall()
    return saida


def _tipologias_das(con: sqlite3.Connection, where: str, args: List[Any], coluna: str,
                    contas: Sequence[str], destino: Dict[int, Tuple[str, str, str, str]]) -> None:
    contas = list(contas)
    for i in range(0, len(contas), _LOTE_IN):
        lote = contas[i:i + _LOTE_IN]
        for r in con.execute(
                f"SELECT id_exibicao, tipologias, no_origem, no_destino, moeda_pagamento FROM transacoes WHERE {where} "
                f"AND tipologias <> '' AND {coluna} IN ({','.join('?' * len(lote))})", args + lote):
            destino[int(r[0])] = (r[1], r[2], r[3], r[4])


def grafo(con: sqlite3.Connection, f: Filtros, foco: str, profundidade: int = GRAFO_PROFUNDIDADE_PADRAO,
          max_nos: int = GRAFO_MAX_NOS, max_arestas: int = GRAFO_MAX_ARESTAS, fronteira: int = GRAFO_FRONTEIRA,
          tem_tipologias: bool = False) -> Dict[str, Any]:
    """Transações enviadas e recebidas pela conta em foco, com cadeias até ``profundidade`` saltos.

    A jusante segue quem recebeu (foco → B → C); a montante, quem enviou
    (X → Y → foco). Arestas agrupam transações de mesma origem, destino e
    moeda (moedas diferentes nunca são somadas). Os totais usam todas as
    transações relacionadas do recorte; o desenho respeita ``max_nos`` e
    ``max_arestas``. Cada aresta desenhada recebe ``ordem`` (direta,
    sequência com horários compatíveis, simultânea ou sem ordem confirmada):
    ver :func:`_ordem_temporal`.
    """
    profundidade = max(1, min(int(profundidade), GRAFO_PROFUNDIDADE_MAX))
    where, args = f.where(incluir_contas=False)
    limites = {"profundidade": profundidade, "profundidade_max": GRAFO_PROFUNDIDADE_MAX, "max_nos": int(max_nos),
               "max_arestas": int(max_arestas), "fronteira_por_salto": int(fronteira), "fronteira_truncada": False}
    recorte = int(con.execute(f"SELECT COUNT(*) FROM transacoes WHERE {where}", args).fetchone()[0])
    base: Dict[str, Any] = {"foco": foco, "limites": limites, "filtros_ativos": f.ativos(),
                            "nota_filtros": "O grafo usa os filtros de período, moeda, alerta, valor, bancos e "
                                            "score. Os filtros de conta escolhem a conta em foco."}
    nivel: Dict[str, int] = {foco: 0}
    arestas: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    tipadas: Dict[int, Tuple[str, str, str, str]] = {}
    for sentido, coluna, outro in ((1, "no_origem", "d"), (-1, "no_destino", "o")):
        atual = [foco]
        vistos = {foco}  # por sentido: uma conta pode receber do foco e também enviar a ele
        for salto in range(1, profundidade + 1):
            if not atual:
                break
            linhas = _arestas(con, where, args, coluna, atual)
            if tem_tipologias:
                _tipologias_das(con, where, args, coluna, atual, tipadas)
            proximos: Dict[str, Tuple[int, int]] = {}
            for r in linhas:
                chave = (r["o"], r["d"], r["moeda"])
                if chave not in arestas:
                    arestas[chave] = {"origem": r["o"], "destino": r["d"], "moeda": r["moeda"], "n": int(r["n"]),
                                      "total": float(r["total"]), "alertas": int(r["alertas"]),
                                      "maior_score": int(r["maior_score"]), "primeiro": minuto_iso(r["primeiro"]),
                                      "ultimo": minuto_iso(r["ultimo"]), "salto": salto, "sentido": sentido,
                                      "tipologias": []}
                vizinho = r[outro]
                if vizinho not in vistos:
                    a, q = proximos.get(vizinho, (0, 0))
                    proximos[vizinho] = (a + int(r["alertas"]), q + int(r["n"]))
            ordenados = sorted(proximos, key=lambda c: (-proximos[c][0], -proximos[c][1], c))
            if len(ordenados) > fronteira and salto < profundidade:
                limites["fronteira_truncada"] = True
                expandir = ordenados[:fronteira]
            else:
                expandir = ordenados
            for c in ordenados:
                vistos.add(c)
                nivel.setdefault(c, sentido * salto)
            atual = expandir
    if not arestas:
        return {**base, "vazio": True, "nos": [], "arestas": [],
                "motivo": "A conta em foco não tem transações no recorte atual (confira os filtros).",
                "totais": {"transacoes_recorte": recorte, "relacionadas": 0, "exibidas": 0, "vertices": 0,
                           "arestas": 0, "arestas_relacionadas": 0, "alertas_relacionadas": 0, "por_moeda": []},
                "tipologias": _tipologias_grafo({}, tem_tipologias),
                "ordem_temporal": {"contagem": {k: 0 for k in ("direta", "sequencia", "simultanea", "sem_ordem")},
                                   "resumo": "", "sequencias": [], "sequencias_total": 0}}
    # tipologias por aresta (só entre transações relacionadas) e contagem geral
    contagem_tipos: Dict[str, int] = {}
    for tipos, o, d, moeda in tipadas.values():
        if (o, d, moeda) not in arestas:
            continue
        for t in tipos.split(tp.SEPARADOR):
            contagem_tipos[t] = contagem_tipos.get(t, 0) + 1
            if t not in arestas[(o, d, moeda)]["tipologias"]:
                arestas[(o, d, moeda)]["tipologias"].append(t)
    relacionadas = sum(a["n"] for a in arestas.values())
    com_tipologia = sum(1 for tipos, o, d, moeda in tipadas.values() if (o, d, moeda) in arestas)
    por_moeda: Dict[str, Dict[str, Any]] = {}
    for a in arestas.values():
        m = por_moeda.setdefault(a["moeda"], {"moeda": a["moeda"], "total": 0.0, "n": 0})
        m["total"] += a["total"]
        m["n"] += a["n"]
    # escolha do que desenhar: do foco para fora, alertas primeiro
    def distancia(a: Dict[str, Any]) -> int:
        return min(abs(nivel.get(a["origem"], 99)), abs(nivel.get(a["destino"], 99)))

    candidatas = sorted(arestas.values(), key=lambda a: (distancia(a), -a["alertas"], -a["n"], -a["total"],
                                                         a["origem"], a["destino"], a["moeda"]))
    nos_desenhados: Dict[str, None] = {foco: None}
    desenhadas: List[Dict[str, Any]] = []
    for a in candidatas:
        if len(desenhadas) >= max_arestas:
            break
        o_dentro, d_dentro = a["origem"] in nos_desenhados, a["destino"] in nos_desenhados
        if not (o_dentro or d_dentro):
            continue
        novos = (0 if o_dentro else 1) + (0 if d_dentro else 1)
        if len(nos_desenhados) + novos > max_nos:
            continue
        nos_desenhados[a["origem"]] = None
        nos_desenhados[a["destino"]] = None
        desenhadas.append(a)
    ordem = _ordem_temporal(con, where, args, foco, desenhadas)
    rotulos = rotulos_sem_colisao(nos_desenhados)
    alertas_no: Dict[str, int] = {}
    for a in arestas.values():
        if a["alertas"]:
            for c in {a["origem"], a["destino"]}:
                alertas_no[c] = alertas_no.get(c, 0) + a["alertas"]
    nos = []
    for c in nos_desenhados:
        banco, _, numero = c.partition("-")
        nv = nivel.get(c, 0)
        tipo = "foco" if c == foco else ("recebeu" if nv > 0 else "enviou")
        nos.append({"id": c, "rotulo": rotulos[c], "banco": banco, "conta": numero, "nivel": nv, "tipo": tipo,
                    "alerta": alertas_no.get(c, 0) > 0, "alertas_relacionados": alertas_no.get(c, 0)})
    exibidas = sum(a["n"] for a in desenhadas)
    return {
        **base, "vazio": False, "nos": nos,
        "arestas": [{**a, "agrupada": a["n"] > 1, "alerta": a["alertas"] > 0} for a in desenhadas],
        "totais": {"transacoes_recorte": recorte, "relacionadas": relacionadas, "exibidas": exibidas,
                   "vertices": len(nos), "arestas": len(desenhadas), "arestas_relacionadas": len(arestas),
                   "contas_relacionadas": len(nivel), "alertas_relacionadas": sum(a["alertas"] for a in arestas.values()),
                   "por_moeda": sorted(por_moeda.values(), key=lambda m: (-m["n"], m["moeda"])),
                   "com_tipologia": com_tipologia},
        "tipologias": _tipologias_grafo(contagem_tipos, tem_tipologias),
        "ordem_temporal": ordem,
    }


# ---------------------------------------------------------------------------
# Ordem temporal das cadeias
# ---------------------------------------------------------------------------
ORDEM_TEXTO = {
    "direta": "transação direta da conta em foco",
    "sequencia": "sequência com horários compatíveis",
    "simultanea": "mesmo minuto da transação anterior: ordem não confirmada",
    "sem_ordem": "relação do recorte sem ordem temporal confirmada",
}
MAX_SEQUENCIAS = 12


def _transacao_limite(con: sqlite3.Connection, where: str, args: List[Any], a: Dict[str, Any], comparacao: str,
                      minuto: Optional[int], primeira: bool) -> Optional[sqlite3.Row]:
    """Primeira (ou última) transação da aresta que respeita ``minuto`` (``>`` a jusante, ``<`` a montante)."""
    extra, extra_args = ("", [])
    if minuto is not None:
        extra, extra_args = f" AND minuto {comparacao} ?", [minuto]
    direcao = "ASC" if primeira else "DESC"
    return con.execute(
        f"SELECT id_exibicao, minuto, valor_pago, score FROM transacoes WHERE {where} AND no_origem = ? AND "
        f"no_destino = ? AND moeda_pagamento = ?{extra} ORDER BY minuto {direcao}, id_exibicao {direcao} LIMIT 1",
        args + [a["origem"], a["destino"], a["moeda"]] + extra_args).fetchone()


def _mesmo_minuto(con: sqlite3.Connection, where: str, args: List[Any], a: Dict[str, Any], minuto: int) -> bool:
    return con.execute(
        f"SELECT 1 FROM transacoes WHERE {where} AND no_origem = ? AND no_destino = ? AND moeda_pagamento = ? "
        "AND minuto = ? LIMIT 1", args + [a["origem"], a["destino"], a["moeda"], minuto]).fetchone() is not None


def _passo(a: Dict[str, Any], r: sqlite3.Row) -> Dict[str, Any]:
    return {"origem": a["origem"], "destino": a["destino"], "moeda": a["moeda"], "valor": float(r["valor_pago"]),
            "data_hora": minuto_iso(r["minuto"]), "id_exibicao": int(r["id_exibicao"]),
            "alerta": int(r["score"]) >= sc.SCORE_ALERTA, "minuto": int(r["minuto"])}


def _ordem_temporal(con: sqlite3.Connection, where: str, args: List[Any], foco: str,
                    desenhadas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Marca em cada aresta desenhada se ela forma, com a anterior, uma sequência com horários compatíveis.

    A jusante (foco → B → C): B → C só é "sequência" se houver uma transação dela em minuto **posterior** à
    chegada mais cedo do dinheiro em B. A montante (X → Y → foco): X → Y só é "sequência" se houver uma
    transação dela em minuto **anterior** à saída mais tarde de Y rumo ao foco. A resolução do dataset é de
    um minuto: transações no mesmo minuto ficam como "ordem não confirmada", nunca como sequência.
    Arestas ligadas diretamente ao foco são "diretas" (não afirmam cadeia).
    """
    chegada: Dict[str, int] = {}            # a jusante: minuto mais cedo em que o dinheiro chegou à conta
    partida: Dict[str, int] = {}            # a montante: minuto mais tarde em que saiu rumo ao foco
    anterior: Dict[str, Dict[str, Any]] = {}   # conta → passo que a alcançou (a jusante)
    seguinte: Dict[str, Dict[str, Any]] = {}   # conta → passo que ela deu rumo ao foco (a montante)
    retornos: List[Dict[str, Any]] = []        # passos a jusante que devolvem o dinheiro à conta em foco
    for a in sorted(desenhadas, key=lambda x: (x["salto"], x["origem"], x["destino"], x["moeda"])):
        if a["origem"] == a["destino"]:
            a["ordem"] = "direta" if a["origem"] == foco else "sem_ordem"
            continue
        if a["sentido"] == 1:
            base = None if a["origem"] == foco else chegada.get(a["origem"])
            if a["origem"] != foco and base is None:
                a["ordem"] = "sem_ordem"
                continue
            r = _transacao_limite(con, where, args, a, ">", base, primeira=True)
            if r is None:
                a["ordem"] = "simultanea" if _mesmo_minuto(con, where, args, a, base) else "sem_ordem"
                continue
            a["ordem"] = "direta" if a["origem"] == foco else "sequencia"
            a["passo"] = _passo(a, r)
            if a["destino"] == foco and a["ordem"] == "sequencia":
                retornos.append(a["passo"])  # foco → … → B → foco: a cadeia termina onde começou
            if a["destino"] != foco and (a["destino"] not in chegada or r["minuto"] < chegada[a["destino"]]):
                chegada[a["destino"]] = int(r["minuto"])
                anterior[a["destino"]] = a["passo"]
        else:
            base = None if a["destino"] == foco else partida.get(a["destino"])
            if a["destino"] != foco and base is None:
                a["ordem"] = "sem_ordem"
                continue
            r = _transacao_limite(con, where, args, a, "<", base, primeira=False)
            if r is None:
                a["ordem"] = "simultanea" if _mesmo_minuto(con, where, args, a, base) else "sem_ordem"
                continue
            a["ordem"] = "direta" if a["destino"] == foco else "sequencia"
            a["passo"] = _passo(a, r)
            if a["origem"] != foco and (a["origem"] not in partida or r["minuto"] > partida[a["origem"]]):
                partida[a["origem"]] = int(r["minuto"])
                seguinte[a["origem"]] = a["passo"]
    for a in desenhadas:
        a["ordem_texto"] = ORDEM_TEXTO[a["ordem"]]
    # sequências confirmadas, com dois passos ou mais, do começo ao fim
    sequencias: List[Dict[str, Any]] = []
    finais = [c for c in anterior if c not in {p["origem"] for p in anterior.values()}]
    for conta in finais:
        passos, atual = [], conta
        while atual in anterior and len(passos) < 10:
            passos.append(anterior[atual])
            atual = anterior[atual]["origem"]
        if len(passos) >= 2 and atual == foco:
            sequencias.append({"sentido": "a_jusante", "passos": passos[::-1]})
    for volta in retornos:  # o passo de volta é posterior à chegada em volta["origem"] (conferido acima)
        passos, atual = [volta], volta["origem"]
        while atual in anterior and len(passos) < 10:
            passos.append(anterior[atual])
            atual = anterior[atual]["origem"]
        if len(passos) >= 2 and atual == foco:
            sequencias.append({"sentido": "volta_ao_foco", "passos": passos[::-1]})
    inicios = [c for c in seguinte if c not in {p["destino"] for p in seguinte.values()}]
    for conta in inicios:
        passos, atual = [], conta
        while atual in seguinte and len(passos) < 10:
            passos.append(seguinte[atual])
            atual = seguinte[atual]["destino"]
        if len(passos) >= 2 and atual == foco:
            sequencias.append({"sentido": "a_montante", "passos": passos})
    for seq in sequencias:
        seq["alerta"] = any(x["alerta"] for x in seq["passos"])
        seq["inicio"], seq["fim"] = seq["passos"][0]["data_hora"], seq["passos"][-1]["data_hora"]
        for x in seq["passos"]:
            x.pop("minuto", None)
    for a in desenhadas:
        if "passo" in a:
            a["passo"].pop("minuto", None)
    sequencias.sort(key=lambda q: (not q["alerta"], -len(q["passos"]), q["inicio"]))
    contagem = {k: sum(1 for a in desenhadas if a["ordem"] == k) for k in ORDEM_TEXTO}
    indiretas = contagem["sequencia"] + contagem["simultanea"] + contagem["sem_ordem"]
    if not indiretas:
        resumo = "Só há transações diretas da conta em foco: o desenho não afirma nenhuma cadeia."
    elif contagem["sequencia"] == indiretas:
        resumo = "Todas as relações indiretas desenhadas têm horários compatíveis com uma sequência."
    elif contagem["sequencia"]:
        resumo = ("Parte das relações indiretas tem horários compatíveis com uma sequência; as demais são relações "
                  "do recorte sem ordem temporal confirmada e aparecem tracejadas.")
    else:
        resumo = ("Relações do recorte sem ordem temporal confirmada: nenhuma relação indireta desenhada tem "
                  "horário compatível com uma sequência a partir da conta em foco.")
    return {"contagem": contagem, "resumo": resumo, "sequencias": sequencias[:MAX_SEQUENCIAS],
            "sequencias_total": len(sequencias), "textos": ORDEM_TEXTO,
            "regra": ("Uma relação indireta só é marcada como sequência quando existe transação em minuto "
                      "posterior à chegada do dinheiro na conta intermediária (ou anterior à saída, no caminho "
                      "até o foco). O dataset tem resolução de um minuto: transações no mesmo minuto não têm "
                      "ordem confirmada. Horário compatível não prova que é o mesmo dinheiro.")}


def _tipologias_grafo(contagem: Dict[str, int], tem_tipologias: bool) -> Dict[str, Any]:
    if contagem:
        predominante = sorted(contagem, key=lambda t: (-contagem[t], t))[0]
        origem = "tipologia registrada no dataset mais frequente entre as transações relacionadas"
    else:
        predominante = tp.NAO_IDENTIFICADO
        origem = ("nenhuma transação relacionada tem tipologia registrada" if tem_tipologias
                  else "o dataset não tem tipologias registradas")
    return {"disponivel": bool(tem_tipologias), "contagem": dict(sorted(contagem.items(), key=lambda kv: (-kv[1], kv[0]))),
            "predominante": predominante, "origem": origem, "disposicao": disposicao_para(predominante)}
