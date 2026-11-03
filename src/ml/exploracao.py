"""Exploração de previsões e avaliações já produzidas (nada é treinado aqui).

Alimenta a seção "Machine Learning" do painel (``src/api_ml.py``). Lê os CSVs
gerados por ``python -m src.ml.cli prever``/``exemplos`` e os resultados
oficiais em ``artefatos_ml/resultados`` (ou as cópias de ``docs/ml/resultados``).

Contratos de leitura
    ``previsao_rede_v1`` e ``previsao_lavagem_v1`` reutilizam
    :class:`~src.ml.esquemas.Esquema` e a mesma validação dos dados de treino:
    coluna obrigatória ausente, tipo incompatível, valor fora da faixa ou do
    domínio geram :class:`ErroContrato` com a lista de problemas e a ação
    necessária. Nada é preenchido com zero.

Identidade e valores originais
    O arquivo é lido como texto (``dtype=str``) e guardado intacto; filtros,
    ordenação e gráficos usam colunas derivadas (prefixo ``_``). A exportação
    devolve as colunas originais, sem conversão. ``_linha`` é a posição da
    linha no arquivo (0 = primeira linha de dados) e identifica o registro.

Os dois domínios nunca se misturam: cada fonte tem um único domínio e os
resumos são calculados só sobre as linhas da própria fonte.
"""

from __future__ import annotations

import io
import json
import math
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from src.ml.esquemas import (
    CLASSES_REDE,
    ESQUEMA_HISMALL_V1,
    ESQUEMA_REDE_V1,
    Coluna,
    ErroEsquema,
    Esquema,
)

LIMITE_IMPORTACAO_BYTES = 64_000_000
LIMITE_EXPORTACAO_LINHAS = 300_000
TAMANHO_PAGINA_MAX = 200
MAX_FONTES_EM_MEMORIA = 6
MAX_IMPORTADOS = 4

# Pastas (relativas à raiz do projeto) de onde a aplicação lista previsões.
PASTAS_PREVISOES: Tuple[Tuple[str, str], ...] = (
    ("artefatos_ml/exemplos", "Gerado por `python -m src.ml.cli exemplos` (período de teste)"),
    ("artefatos_ml/previsoes", "Gerado por `python -m src.ml.cli prever`"),
    ("artefatos_ml/teste", "Gerado por `python -m src.ml.cli prever`"),
    ("docs/ml/exemplos", "Versionado no repositório"),
)
# Pastas onde se procuram os arquivos de entrada citados em ``arquivo_origem``.
PASTAS_ENTRADA: Tuple[str, ...] = ("artefatos_ml/exemplos", "artefatos_ml/previsoes", "artefatos_ml/teste")

DOMINIOS = ("rede", "lavagem")
_B = ("True", "False")
_VERDADE = {"true", "1", "sim", "yes", "verdadeiro"}
_FALSO = {"false", "0", "nao", "não", "no", "falso"}


class ErroContrato(ValueError):
    """Arquivo incompatível com o contrato de leitura (mensagem para o usuário)."""

    def __init__(self, problemas: Sequence[str], acao: str, contrato: str = ""):
        self.problemas = list(problemas)
        self.acao = acao
        self.contrato = contrato
        super().__init__("; ".join(self.problemas))

    def para_dict(self) -> Dict[str, Any]:
        return {"erro": "arquivo incompatível", "contrato": self.contrato,
                "problemas": self.problemas, "acao": self.acao}


class ErroFiltro(ValueError):
    """Parâmetro de filtro, ordenação ou exportação inválido."""


# ---------------------------------------------------------------------------
# Contratos de leitura
# ---------------------------------------------------------------------------
ESQUEMA_PREVISAO_REDE = Esquema(
    nome="previsao_rede",
    versao="v1",
    descricao=(
        "Saída de `python -m src.ml.cli prever --tarefa estado_rede`: uma linha por medição, "
        "com o estado previsto para a PRÓXIMA medição do mesmo fluxo."
    ),
    colunas=(
        Coluna("arquivo_origem", "str", "id", "Arquivo de entrada de onde veio a medição.", status="verificado"),
        Coluna("linha_origem", "int", "id", "Posição da medição no arquivo de entrada (0 = primeira linha de dados).",
               status="verificado", faixa=(0, 1e12)),
        Coluna("id_fluxo", "str", "id", "Fluxo sonda→âncora ('<probe_id>_<anchor_id>').", status="verificado"),
        Coluna("anchor_id", "int", "id", "Âncora de destino das medições.", status="verificado",
               obrigatoria_inferencia=False),
        Coluna("probe_id", "int", "id", "Sonda de origem das medições.", status="verificado",
               obrigatoria_inferencia=False),
        Coluna("timestamp_previsao", "int", "tempo",
               "Instante da medição usada na previsão (época Unix, s; fuso presumido UTC).", "s",
               "verificado", faixa=(0, 4e9)),
        Coluna("horizonte", "cat", "controle",
               "Horizonte da previsão: a próxima medição do mesmo fluxo (intervalo mediano de 240 s).",
               status="verificado", obrigatoria_inferencia=False, dominio=("proxima_medicao",)),
        Coluna("classe_prevista", "cat", "previsao",
               "Estado previsto para a próxima medição (classe de maior probabilidade).",
               status="verificado", dominio=CLASSES_REDE),
        Coluna("prob_OK", "float", "previsao", "Probabilidade estimada de OK na próxima medição.",
               status="verificado", faixa=(0, 1)),
        Coluna("prob_RISCO", "float", "previsao", "Probabilidade estimada de RISCO na próxima medição.",
               status="verificado", faixa=(0, 1)),
        Coluna("prob_FALHA", "float", "previsao", "Probabilidade estimada de FALHA na próxima medição.",
               status="verificado", faixa=(0, 1)),
        Coluna("score_alerta_rede", "float", "previsao",
               "P(RISCO) + P(FALHA): chance estimada de a próxima medição não ser OK. Não é probabilidade de fraude.",
               status="verificado", faixa=(0, 1.000001)),
        Coluna("alerta_rede", "cat", "previsao", "True quando score_alerta_rede ≥ limiar_alerta.",
               status="verificado", dominio=_B),
        Coluna("limiar_alerta", "float", "controle", "Limiar oficial do modelo, escolhido na validação.",
               status="verificado", obrigatoria_inferencia=False, faixa=(0, 1)),
        Coluna("versao_modelo", "str", "controle", "Versão do artefato que gerou a previsão.",
               status="verificado", obrigatoria_inferencia=False),
        Coluna("modelo_rede_treinado_ate", "str", "controle", "Fim do período de treino do modelo (UTC).",
               status="verificado", obrigatoria_inferencia=False),
        Coluna("tipo_saida", "cat", "controle", "Sempre 'previsao': a linha é previsão, não evento confirmado.",
               status="verificado", obrigatoria_inferencia=False, dominio=("previsao",)),
        Coluna("classe_atual", "cat", "observado", "Estado observado na medição atual, quando o arquivo traz.",
               obrigatoria_inferencia=False, dominio=CLASSES_REDE),
        Coluna("alvo", "cat", "rotulo",
               "Rótulo de referência: estado real da próxima medição, quando o arquivo traz.",
               obrigatoria_inferencia=False, dominio=CLASSES_REDE),
    ),
)

ESQUEMA_PREVISAO_LAVAGEM = Esquema(
    nome="previsao_lavagem",
    versao="v1",
    descricao=(
        "Saída de `python -m src.ml.cli prever --tarefa lavagem`: uma linha por transação do "
        "IBM AML HI-Small (dados sintéticos), com a pontuação de lavagem."
    ),
    colunas=(
        Coluna("arquivo_origem", "str", "id", "Arquivo de entrada da transação.", status="verificado",
               obrigatoria_inferencia=False),
        Coluna("linha_origem", "int", "id", "Posição da transação no arquivo de entrada.", status="verificado",
               obrigatoria_inferencia=False, faixa=(0, 1e12)),
        Coluna("id_transacao", "str", "id", "Identificador da transação no arquivo de entrada.", status="verificado"),
        Coluna("timestamp_transacao", "datahora", "tempo",
               "Data e hora da transação (resolução de minuto; fuso não documentado, tratado como UTC).",
               status="verificado"),
        Coluna("conta_origem", "str", "id", "Conta de origem, no formato banco-conta.", status="verificado"),
        Coluna("conta_destino", "str", "id", "Conta de destino, no formato banco-conta.", status="verificado"),
        Coluna("valor_pago", "float", "observado", "Valor pago, na moeda de pagamento (sem conversão).", "moeda",
               "verificado", faixa=(0, 1e15)),
        Coluna("moeda_pagamento", "str", "observado", "Moeda de pagamento.", status="verificado"),
        Coluna("formato", "str", "observado", "Formato de pagamento (ACH, Wire, Cheque, ...).", status="verificado",
               obrigatoria_inferencia=False),
        Coluna("score_lavagem", "float", "previsao",
               "Pontuação de lavagem aprendida no HI-Small sintético. Serve para ordenar; não é probabilidade "
               "calibrada nem fraude confirmada.", status="verificado", faixa=(0, 1)),
        Coluna("alerta_lavagem", "cat", "previsao",
               "True quando score_lavagem ≥ limiar_alerta: previsão de lavagem, não confirmação.",
               status="verificado", dominio=_B),
        Coluna("limiar_alerta", "float", "controle", "Limiar oficial (máximo F1 na validação).",
               status="verificado", obrigatoria_inferencia=False, faixa=(0, 1)),
        Coluna("historico_incompleto", "cat", "controle",
               "True quando havia menos de 72 h de histórico antes da transação.",
               status="verificado", obrigatoria_inferencia=False, dominio=_B),
        Coluna("sinais_utilizados", "str", "controle", "Fontes usadas pelo modelo (hoje só 'financeiro').",
               status="verificado", obrigatoria_inferencia=False),
        Coluna("cobertura_vinculo", "str", "controle", "Vínculo com a rede (hoje sempre 'sem_vinculo').",
               status="verificado", obrigatoria_inferencia=False),
        Coluna("pontuacao_fraude_financeira", "str", "controle",
               "Pontuação de fraude ligada à rede (hoje 'indisponivel').", status="verificado",
               obrigatoria_inferencia=False),
        Coluna("versao_modelo", "str", "controle", "Versão do artefato que gerou a previsão.",
               status="verificado", obrigatoria_inferencia=False),
        Coluna("tipo_saida", "cat", "controle", "Sempre 'previsao': a linha é previsão, não confirmação.",
               status="verificado", obrigatoria_inferencia=False, dominio=("previsao",)),
        Coluna("Is Laundering", "int", "rotulo",
               "Rótulo de referência sintético (1 = lavagem segundo o simulador), quando o arquivo traz.",
               obrigatoria_inferencia=False, dominio=(0, 1)),
    ),
)

# Colunas de texto livre (podem ser vazias): só a presença é conferida.
_TEXTO_LIVRE: Dict[str, Dict[str, Tuple[str, str]]] = {
    "rede": {},
    "lavagem": {
        "motivos_verificaveis": (
            "previsao",
            "Fatos verificáveis (regras fixas sobre quantis do treino), preenchidos só nas linhas em "
            "alerta. Não explicam a decisão do modelo.",
        ),
    },
}

CONTRATOS: Dict[str, Esquema] = {"rede": ESQUEMA_PREVISAO_REDE, "lavagem": ESQUEMA_PREVISAO_LAVAGEM}
_COLUNAS_CHAVE = {
    "rede": ("classe_prevista", "score_alerta_rede"),
    "lavagem": ("score_lavagem", "alerta_lavagem"),
}
_COLUNA_ROTULO = {"rede": "alvo", "lavagem": "Is Laundering"}
_ACAO = {
    "rede": ("Use um CSV gerado por `python -m src.ml.cli prever --tarefa estado_rede`, sem renomear nem "
             "remover colunas, ou corrija as colunas listadas."),
    "lavagem": ("Use um CSV gerado por `python -m src.ml.cli prever --tarefa lavagem`, sem renomear nem "
                "remover colunas, ou corrija as colunas listadas."),
}
_NOME_DOMINIO = {"rede": "previsões de rede (estado_rede)", "lavagem": "previsões de lavagem"}


def detectar_dominio(colunas: Iterable[str]) -> Optional[str]:
    cols = set(colunas)
    achados = [d for d, chave in _COLUNAS_CHAVE.items() if set(chave) <= cols]
    return achados[0] if len(achados) == 1 else None


def _normalizar_bool(s: pd.Series) -> pd.Series:
    baixo = s.astype(str).str.strip().str.lower()
    return pd.Series(np.where(baixo.isin(_VERDADE), "True", np.where(baixo.isin(_FALSO), "False", s)),
                     index=s.index)


def _bool(s: pd.Series) -> np.ndarray:
    return (_normalizar_bool(s) == "True").to_numpy()


def validar_previsoes(bruto: pd.DataFrame, dominio: Optional[str] = None) -> str:
    """Confere ``bruto`` (lido como texto) contra o contrato; devolve o domínio."""
    detectado = detectar_dominio(bruto.columns)
    if dominio is None:
        if detectado is None:
            faltam = {d: [c for c in chave if c not in bruto.columns] for d, chave in _COLUNAS_CHAVE.items()}
            raise ErroContrato(
                [f"o arquivo não tem as colunas que identificam previsões de rede ({', '.join(faltam['rede'])}) "
                 f"nem de lavagem ({', '.join(faltam['lavagem'])})",
                 f"colunas encontradas: {', '.join(map(str, bruto.columns[:20]))}"
                 + (" …" if len(bruto.columns) > 20 else "")],
                "Importe um CSV gerado por `python -m src.ml.cli prever` (tarefa estado_rede ou lavagem). "
                "Arquivos de entrada, como dataset_final.csv ou HI-Small_Trans.csv, não são previsões.",
            )
        dominio = detectado
    elif detectado is not None and detectado != dominio:
        raise ErroContrato(
            [f"o arquivo contém {_NOME_DOMINIO[detectado]}, não {_NOME_DOMINIO[dominio]}"],
            f"Abra-o na área {'Análise de rede' if detectado == 'rede' else 'Análise financeira'}.",
        )
    esquema = CONTRATOS[dominio]
    v = bruto.replace({"": np.nan})
    for c in esquema.colunas:
        if c.dominio == _B and c.nome in v:
            v[c.nome] = _normalizar_bool(v[c.nome]).where(v[c.nome].notna())
    problemas: List[str] = []
    try:
        esquema.validar(v, modo="inferencia")
    except ErroEsquema as exc:
        problemas.extend(exc.problemas)
    if not problemas and dominio == "rede":
        probs = v[["prob_OK", "prob_RISCO", "prob_FALHA"]].astype(float)
        soma_ruim = int((probs.sum(axis=1) - 1).abs().gt(1e-3).sum())
        if soma_ruim:
            problemas.append(f"{soma_ruim} linha(s) com prob_OK + prob_RISCO + prob_FALHA diferente de 1")
        score_ruim = int((probs["prob_RISCO"] + probs["prob_FALHA"] - v["score_alerta_rede"].astype(float))
                         .abs().gt(1e-3).sum())
        if score_ruim:
            problemas.append(f"{score_ruim} linha(s) com score_alerta_rede diferente de prob_RISCO + prob_FALHA")
    if problemas:
        raise ErroContrato(problemas, _ACAO[dominio], esquema.id)
    return dominio


def _ler_csv(origem: Union[Path, bytes]) -> pd.DataFrame:
    acao = "Salve o arquivo como CSV em UTF-8, com cabeçalho na primeira linha e vírgula como separador."
    try:
        fonte = io.BytesIO(origem) if isinstance(origem, (bytes, bytearray)) else origem
        return pd.read_csv(fonte, dtype=str, keep_default_na=False, na_filter=False, encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ErroContrato(["o arquivo não está codificado em UTF-8"], acao) from None
    except pd.errors.EmptyDataError:
        raise ErroContrato(["o arquivo está vazio"], acao) from None
    except pd.errors.ParserError as exc:
        raise ErroContrato([f"CSV malformado: {str(exc).splitlines()[0]}"], acao) from None


# ---------------------------------------------------------------------------
# Previsões carregadas
# ---------------------------------------------------------------------------
@dataclass
class Previsoes:
    id: str
    dominio: str
    nome_arquivo: str
    origem: str                         # "aplicacao" ou "importado"
    bruto: pd.DataFrame                 # colunas originais, como texto
    tip: pd.DataFrame                   # colunas derivadas (prefixo _)
    conjunto: Dict[str, Any]
    pasta: Optional[str] = None         # pasta relativa (só fontes da aplicação)
    relatorio: Optional[Dict[str, Any]] = None
    avisos: List[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.bruto)

    @property
    def rotulo(self) -> Optional[str]:
        col = _COLUNA_ROTULO[self.dominio]
        return col if col in self.bruto.columns else None

    def campos(self) -> List[Dict[str, Any]]:
        esquema = CONTRATOS[self.dominio]
        saida = []
        for nome in self.bruto.columns:
            try:
                c = esquema.coluna(nome)
                saida.append({"nome": nome, "papel": c.papel, "descricao": c.descricao, "reconhecido": True})
            except KeyError:
                livre = _TEXTO_LIVRE[self.dominio].get(nome)
                if livre:
                    saida.append({"nome": nome, "papel": livre[0], "descricao": livre[1], "reconhecido": True})
                else:
                    saida.append({"nome": nome, "papel": "desconhecido",
                                  "descricao": "Coluna fora do contrato; exibida sem interpretação.",
                                  "reconhecido": False})
        return saida

    def periodo(self, mascara: Optional[np.ndarray] = None) -> Optional[Dict[str, str]]:
        t = self.tip["_t"] if mascara is None else self.tip["_t"][mascara]
        if t.empty:
            return None
        return {"inicio": _iso(t.min()), "fim": _iso(t.max()), "fuso": _FUSO[self.dominio]}

    def descricao(self) -> Dict[str, Any]:
        versoes = (sorted(set(self.bruto["versao_modelo"]) - {""}) if "versao_modelo" in self.bruto else [])
        limiares = (sorted({float(x) for x in self.bruto["limiar_alerta"] if x != ""})
                    if "limiar_alerta" in self.bruto else [])
        return {
            "id": self.id, "dominio": self.dominio, "nome_arquivo": self.nome_arquivo, "origem": self.origem,
            "pasta": self.pasta, "registros": self.n, "periodo": self.periodo(), "conjunto": self.conjunto,
            "modelo": {
                "versoes": versoes,
                "limiar": limiares[0] if len(limiares) == 1 else None,
                "limiares": limiares,
                "motivo_ausencia": None if versoes else "o arquivo não traz a coluna versao_modelo",
            },
            "rotulos": ({"disponivel": True, "coluna": self.rotulo} if self.rotulo else
                        {"disponivel": False,
                         "motivo": f"o arquivo não traz a coluna de rótulo de referência "
                                   f"'{_COLUNA_ROTULO[self.dominio]}'"}),
            "campos": self.campos(),
            "relatorio": self.relatorio,
            "avisos": self.avisos,
            "contrato": CONTRATOS[self.dominio].id,
        }


_FUSO = {"rede": "UTC (presumido)", "lavagem": "não documentado (tratado como UTC)"}


def _iso(ts: Any) -> Optional[str]:
    if ts is None or pd.isna(ts):
        return None
    return pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


def _derivar(bruto: pd.DataFrame, dominio: str) -> Tuple[pd.DataFrame, List[str]]:
    tip = pd.DataFrame(index=bruto.index)
    tip["_linha"] = np.arange(len(bruto), dtype=np.int64)
    avisos: List[str] = []
    if dominio == "rede":
        tip["_t"] = pd.to_datetime(pd.to_numeric(bruto["timestamp_previsao"]).astype("int64"), unit="s")
        tip["_score"] = pd.to_numeric(bruto["score_alerta_rede"])
        tip["_alerta"] = _bool(bruto["alerta_rede"])
        tip["_classe"] = bruto["classe_prevista"].astype(str)
        tip["_fluxo"] = bruto["id_fluxo"].astype(str)
        for col in ("prob_OK", "prob_RISCO", "prob_FALHA"):
            tip["_" + col] = pd.to_numeric(bruto[col])
        chave = bruto["arquivo_origem"] + "#" + bruto["linha_origem"]
        if chave.duplicated().any():
            avisos.append(f"{int(chave.duplicated().sum())} linha(s) repetem arquivo_origem + linha_origem")
    else:
        tip["_t"] = pd.to_datetime(bruto["timestamp_transacao"])
        tip["_score"] = pd.to_numeric(bruto["score_lavagem"])
        tip["_alerta"] = _bool(bruto["alerta_lavagem"])
        tip["_valor"] = pd.to_numeric(bruto["valor_pago"])
        tip["_moeda"] = bruto["moeda_pagamento"].astype(str)
        tip["_formato"] = bruto["formato"].astype(str) if "formato" in bruto else ""
        for lado, col in (("o", "conta_origem"), ("d", "conta_destino")):
            conta = bruto[col].astype(str)
            tip[f"_conta_{lado}"] = conta
            tip[f"_banco_{lado}"] = np.where(conta.str.contains("-", regex=False),
                                             conta.str.split("-", n=1).str[0], "")
        tip["_motivos"] = (bruto["motivos_verificaveis"].astype(str) if "motivos_verificaveis" in bruto else "")
        if bruto["id_transacao"].duplicated().any():
            avisos.append(f"{int(bruto['id_transacao'].duplicated().sum())} linha(s) repetem id_transacao")
    col_rot = _COLUNA_ROTULO[dominio]
    if col_rot in bruto:
        tip["_rotulo"] = bruto[col_rot].astype(str) if dominio == "rede" else pd.to_numeric(bruto[col_rot]).astype(int)
    if "limiar_alerta" in bruto:
        limiar = pd.to_numeric(bruto["limiar_alerta"].replace("", np.nan))
        incoerente = int(((tip["_score"] >= limiar) != tip["_alerta"]).where(limiar.notna(), False).sum())
        if incoerente:
            avisos.append(f"{incoerente} linha(s) com alerta diferente de 'score ≥ limiar_alerta' "
                          "(o arquivo pode ter sido editado)")
    return tip, avisos


def carregar_previsoes(origem: Union[Path, bytes], nome_arquivo: str, id: str, origem_tipo: str,
                       conjunto: Dict[str, Any], pasta: Optional[str] = None,
                       relatorio: Optional[Dict[str, Any]] = None,
                       dominio: Optional[str] = None) -> Previsoes:
    bruto = _ler_csv(origem)
    dominio = validar_previsoes(bruto, dominio)
    tip, avisos = _derivar(bruto, dominio)
    return Previsoes(id, dominio, nome_arquivo, origem_tipo, bruto, tip, conjunto, pasta, relatorio, avisos)


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
@dataclass
class Filtros:
    inicio: Optional[pd.Timestamp] = None
    fim_exclusivo: Optional[pd.Timestamp] = None
    alerta: Optional[bool] = None
    score_min: Optional[float] = None
    score_max: Optional[float] = None
    busca: str = ""
    classes: Tuple[str, ...] = ()          # rede
    fluxo: str = ""
    anchor: str = ""
    probe: str = ""
    conta_origem: str = ""                 # lavagem
    conta_destino: str = ""
    banco_origem: str = ""
    banco_destino: str = ""
    valor_min: Optional[float] = None
    valor_max: Optional[float] = None
    moedas: Tuple[str, ...] = ()
    formatos: Tuple[str, ...] = ()
    motivo: str = ""

    def ativos(self) -> Dict[str, Any]:
        saida = {}
        for k, v in self.__dict__.items():
            if v in (None, "", ()):
                continue
            saida[k] = _iso(v) if isinstance(v, pd.Timestamp) else (list(v) if isinstance(v, tuple) else v)
        return saida


def _num(params: Mapping[str, str], chave: str, rotulo: str) -> Optional[float]:
    v = (params.get(chave) or "").strip().replace(",", ".")
    if not v:
        return None
    try:
        x = float(v)
    except ValueError:
        raise ErroFiltro(f"{rotulo}: '{params.get(chave)}' não é um número.") from None
    if not math.isfinite(x):
        raise ErroFiltro(f"{rotulo}: use um número finito.")
    return x


def _data(params: Mapping[str, str], chave: str, rotulo: str, fim: bool) -> Optional[pd.Timestamp]:
    v = (params.get(chave) or "").strip()
    if not v:
        return None
    try:
        ts = pd.Timestamp(v)
    except (ValueError, TypeError):
        raise ErroFiltro(f"{rotulo}: '{v}' não é uma data válida (use AAAA-MM-DD ou AAAA-MM-DDTHH:MM).") from None
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    if not fim:
        return ts
    # fim inclusivo: o dia inteiro (só data) ou o minuto inteiro (data e hora)
    return ts + (pd.Timedelta(days=1) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else pd.Timedelta(minutes=1))


def _lista(params: Mapping[str, str], chave: str) -> Tuple[str, ...]:
    v = params.get(chave) or ""
    return tuple(x for x in (p.strip() for p in v.split(",")) if x)


def filtros_de_parametros(params: Mapping[str, str], dominio: str) -> Filtros:
    alerta_txt = (params.get("alerta") or "").strip().lower()
    if alerta_txt not in ("", "sim", "nao"):
        raise ErroFiltro("Alerta: use 'sim', 'nao' ou deixe em branco.")
    f = Filtros(
        inicio=_data(params, "inicio", "Data inicial", fim=False),
        fim_exclusivo=_data(params, "fim", "Data final", fim=True),
        alerta=None if not alerta_txt else alerta_txt == "sim",
        score_min=_num(params, "score_min", "Score mínimo"),
        score_max=_num(params, "score_max", "Score máximo"),
        busca=(params.get("busca") or "").strip(),
    )
    if f.inicio is not None and f.fim_exclusivo is not None and f.inicio >= f.fim_exclusivo:
        raise ErroFiltro("A data inicial precisa ser anterior à final.")
    if f.score_min is not None and f.score_max is not None and f.score_min > f.score_max:
        raise ErroFiltro("O score mínimo é maior que o máximo.")
    if dominio == "rede":
        classes = _lista(params, "classes")
        invalidas = [c for c in classes if c not in CLASSES_REDE]
        if invalidas:
            raise ErroFiltro(f"Classes desconhecidas: {invalidas}. Use OK, RISCO ou FALHA.")
        f.classes = classes
        f.fluxo = (params.get("fluxo") or "").strip()
        f.anchor = (params.get("anchor") or "").strip()
        f.probe = (params.get("probe") or "").strip()
    else:
        f.conta_origem = (params.get("conta_origem") or "").strip()
        f.conta_destino = (params.get("conta_destino") or "").strip()
        f.banco_origem = (params.get("banco_origem") or "").strip()
        f.banco_destino = (params.get("banco_destino") or "").strip()
        f.valor_min = _num(params, "valor_min", "Valor mínimo")
        f.valor_max = _num(params, "valor_max", "Valor máximo")
        if f.valor_min is not None and f.valor_max is not None and f.valor_min > f.valor_max:
            raise ErroFiltro("O valor mínimo é maior que o máximo.")
        f.moedas = _lista(params, "moedas")
        f.formatos = _lista(params, "formatos")
        f.motivo = (params.get("motivo") or "").strip()
    return f


def _contem(s: pd.Series, texto: str) -> np.ndarray:
    return s.str.contains(texto, case=False, regex=False, na=False).to_numpy()


def mascara(prev: Previsoes, f: Filtros) -> np.ndarray:
    t = prev.tip
    m = np.ones(prev.n, dtype=bool)
    if f.inicio is not None:
        m &= (t["_t"] >= f.inicio).to_numpy()
    if f.fim_exclusivo is not None:
        m &= (t["_t"] < f.fim_exclusivo).to_numpy()
    if f.alerta is not None:
        m &= t["_alerta"].to_numpy() == f.alerta
    if f.score_min is not None:
        m &= (t["_score"] >= f.score_min).to_numpy()
    if f.score_max is not None:
        m &= (t["_score"] <= f.score_max).to_numpy()
    b = prev.bruto
    if prev.dominio == "rede":
        if f.classes:
            m &= t["_classe"].isin(f.classes).to_numpy()
        if f.fluxo:
            m &= _contem(t["_fluxo"], f.fluxo)
        if f.anchor and "anchor_id" in b:
            m &= (b["anchor_id"] == f.anchor).to_numpy()
        if f.probe and "probe_id" in b:
            m &= (b["probe_id"] == f.probe).to_numpy()
        campos_busca = [c for c in ("id_fluxo", "anchor_id", "probe_id", "linha_origem", "arquivo_origem") if c in b]
    else:
        if f.conta_origem:
            m &= _contem(t["_conta_o"], f.conta_origem)
        if f.conta_destino:
            m &= _contem(t["_conta_d"], f.conta_destino)
        if f.banco_origem:
            m &= (t["_banco_o"] == f.banco_origem).to_numpy()
        if f.banco_destino:
            m &= (t["_banco_d"] == f.banco_destino).to_numpy()
        if f.valor_min is not None:
            m &= (t["_valor"] >= f.valor_min).to_numpy()
        if f.valor_max is not None:
            m &= (t["_valor"] <= f.valor_max).to_numpy()
        if f.moedas:
            m &= t["_moeda"].isin(f.moedas).to_numpy()
        if f.formatos:
            m &= t["_formato"].isin(f.formatos).to_numpy()
        if f.motivo:
            m &= _contem(t["_motivos"], f.motivo)
        campos_busca = [c for c in ("id_transacao", "conta_origem", "conta_destino", "linha_origem") if c in b]
    if f.busca:
        achou = np.zeros(prev.n, dtype=bool)
        for c in campos_busca:
            achou |= _contem(b[c], f.busca)
        m &= achou
    return m


# ---------------------------------------------------------------------------
# Resumos, página, registro e exportação
# ---------------------------------------------------------------------------
def _serie_temporal(t: pd.Series, alerta: np.ndarray) -> Dict[str, Any]:
    if t.empty:
        return {"granularidade": None, "pontos": []}
    span = t.max() - t.min()
    freq, nome = ("h", "hora") if span <= pd.Timedelta(days=3) else ("D", "dia")
    base = t.dt.floor(freq)
    if freq == "D" and span > pd.Timedelta(days=400):
        base, nome = t.dt.to_period("M").dt.to_timestamp(), "mês"
    tot = base.value_counts().sort_index()
    ale = base[alerta].value_counts()
    if nome != "mês":
        tot = tot.reindex(pd.date_range(tot.index.min(), tot.index.max(), freq=freq), fill_value=0)
    pontos = [{"inicio": _iso(k), "total": int(v), "alertas": int(ale.get(k, 0))} for k, v in tot.items()]
    return {"granularidade": nome, "pontos": pontos}


def _histograma(score: np.ndarray, alerta: np.ndarray, n_caixas: int = 20) -> Dict[str, Any]:
    bordas = np.linspace(0.0, 1.0, n_caixas + 1)
    idx = np.clip(np.digitize(score, bordas[1:-1], right=False), 0, n_caixas - 1)
    contagens = np.bincount(idx, minlength=n_caixas)
    alertas = np.bincount(idx[alerta], minlength=n_caixas)
    return {"bordas": [round(float(b), 4) for b in bordas], "contagens": contagens.tolist(),
            "alertas": alertas.tolist()}


def _prf(vp: int, fp: int, fn: int) -> Dict[str, Optional[float]]:
    p = vp / (vp + fp) if vp + fp else None
    r = vp / (vp + fn) if vp + fn else None
    f1 = 2 * p * r / (p + r) if p is not None and r is not None and p + r > 0 else None
    return {"precisao": p, "recall": r, "f1": f1}


def _metricas_rotulos(prev: Previsoes, m: np.ndarray) -> Dict[str, Any]:
    if prev.rotulo is None:
        return {"disponivel": False,
                "motivo": f"O arquivo não traz rótulos de referência ('{_COLUNA_ROTULO[prev.dominio]}'). "
                          "Veja a avaliação oficial do experimento."}
    t = prev.tip[m]
    if t.empty:
        return {"disponivel": False, "motivo": "Nenhum registro após os filtros."}
    if prev.dominio == "rede":
        y, p = t["_rotulo"].to_numpy(), t["_classe"].to_numpy()
        matriz = [[int(((y == r) & (p == q)).sum()) for q in CLASSES_REDE] for r in CLASSES_REDE]
        por_classe = {}
        for i, k in enumerate(CLASSES_REDE):
            vp = matriz[i][i]
            fp = sum(matriz[j][i] for j in range(3)) - vp
            fn = sum(matriz[i]) - vp
            por_classe[k] = {**_prf(vp, fp, fn), "suporte": int(sum(matriz[i]))}
        f1s = [v["f1"] or 0.0 for v in por_classe.values() if v["suporte"] > 0]
        nao_ok, ale = y != "OK", t["_alerta"].to_numpy()
        return {
            "disponivel": True, "tipo": "exploratoria", "n": int(len(t)),
            "classes": list(CLASSES_REDE), "matriz_confusao": matriz, "por_classe": por_classe,
            "macro_f1": float(np.mean(f1s)) if f1s else None,
            "alerta_nao_ok": {**_prf(int((ale & nao_ok).sum()), int((ale & ~nao_ok).sum()),
                                     int((~ale & nao_ok).sum())), "positivos": int(nao_ok.sum())},
        }
    y, ale = t["_rotulo"].to_numpy() == 1, t["_alerta"].to_numpy()
    vp, fp, fn = int((ale & y).sum()), int((ale & ~y).sum()), int((~ale & y).sum())
    ap = None
    if 0 < y.sum() < len(y):
        from sklearn.metrics import average_precision_score
        ap = float(average_precision_score(y, t["_score"].to_numpy()))
    return {"disponivel": True, "tipo": "exploratoria", "n": int(len(t)), "positivos": int(y.sum()),
            "matriz_confusao": {"vp": vp, "fp": fp, "fn": fn, "vn": int(len(t) - vp - fp - fn)},
            **_prf(vp, fp, fn), "average_precision": ap}


def resumo(prev: Previsoes, m: np.ndarray) -> Dict[str, Any]:
    t = prev.tip[m]
    alerta = t["_alerta"].to_numpy()
    k = int(m.sum())
    saida: Dict[str, Any] = {
        "fonte": prev.id, "dominio": prev.dominio,
        "total_arquivo": prev.n, "total_filtrado": k,
        "periodo_filtrado": prev.periodo(m),
        "alertas": {"n": int(alerta.sum()), "proporcao": float(alerta.mean()) if k else None},
        "score": ({"min": float(t["_score"].min()), "mediana": float(t["_score"].median()),
                   "max": float(t["_score"].max())} if k else None),
        "histograma_score": _histograma(t["_score"].to_numpy(), alerta),
        "serie_temporal": _serie_temporal(t["_t"], alerta),
        "rotulos": _metricas_rotulos(prev, m),
        "conjunto": prev.conjunto,
    }
    if prev.dominio == "rede":
        saida["classes"] = [{"classe": c, "n": int((t["_classe"] == c).sum()),
                             "alertas": int(((t["_classe"] == c) & t["_alerta"]).sum())} for c in CLASSES_REDE]
        saida["fluxos_distintos"] = int(t["_fluxo"].nunique())
    else:
        g = t.groupby("_moeda", sort=True)
        saida["por_moeda"] = [{"moeda": moeda, "n": int(len(gg)), "alertas": int(gg["_alerta"].sum()),
                               "soma_valor": float(gg["_valor"].sum())} for moeda, gg in g]
        gf = t.groupby("_formato", sort=True)
        saida["por_formato"] = [{"formato": fmt or "(vazio)", "n": int(len(gg)),
                                 "alertas": int(gg["_alerta"].sum())} for fmt, gg in gf]
        saida["contas_origem_distintas"] = int(t["_conta_o"].nunique())
        saida["contas_destino_distintas"] = int(t["_conta_d"].nunique())
    return saida


_ORDENACAO_NUMERICA = {
    "rede": {"linha_origem", "anchor_id", "probe_id", "prob_OK", "prob_RISCO", "prob_FALHA",
             "score_alerta_rede", "limiar_alerta"},
    "lavagem": {"linha_origem", "valor_pago", "score_lavagem", "limiar_alerta", "Is Laundering"},
}
_ORDENACAO_TEMPO = {"rede": "timestamp_previsao", "lavagem": "timestamp_transacao"}


def pagina(prev: Previsoes, m: np.ndarray, ordenar: str = "", direcao: str = "asc",
           numero: int = 1, tamanho: int = 50) -> Dict[str, Any]:
    if direcao not in ("asc", "desc"):
        raise ErroFiltro("Direção de ordenação: use 'asc' ou 'desc'.")
    if not 1 <= tamanho <= TAMANHO_PAGINA_MAX:
        raise ErroFiltro(f"Tamanho da página: entre 1 e {TAMANHO_PAGINA_MAX}.")
    idx = np.flatnonzero(m)
    if ordenar:
        if ordenar not in prev.bruto.columns and ordenar != "_linha":
            raise ErroFiltro(f"Coluna de ordenação desconhecida: {ordenar}.")
        if ordenar == "_linha":
            chave = prev.tip["_linha"]
        elif ordenar == _ORDENACAO_TEMPO[prev.dominio]:
            chave = prev.tip["_t"]
        elif ordenar in _ORDENACAO_NUMERICA[prev.dominio]:
            chave = pd.to_numeric(prev.bruto[ordenar].replace("", np.nan), errors="coerce")
        else:
            chave = prev.bruto[ordenar]
        quadro = pd.DataFrame({"k": chave.to_numpy()[idx], "l": idx})
        # ordenação estável; empate pela posição original, sempre crescente
        quadro = quadro.sort_values(["k", "l"], ascending=[direcao == "asc", True], kind="mergesort",
                                    na_position="last")
        idx = quadro["l"].to_numpy()
    total = len(idx)
    paginas = max(1, math.ceil(total / tamanho))
    numero = min(max(1, numero), paginas)
    sel = idx[(numero - 1) * tamanho: numero * tamanho]
    linhas = prev.bruto.iloc[sel].to_dict(orient="records")
    for pos, linha in zip(sel, linhas):
        linha["_linha"] = int(pos)
    return {"fonte": prev.id, "total": total, "pagina": numero, "tamanho": tamanho, "paginas": paginas,
            "ordenar": ordenar, "direcao": direcao, "colunas": list(prev.bruto.columns), "linhas": linhas}


def exportar(prev: Previsoes, m: np.ndarray) -> Tuple[bytes, str, Dict[str, Any]]:
    k = int(m.sum())
    if k == 0:
        raise ErroFiltro("Nenhum registro para exportar com os filtros atuais.")
    if k > LIMITE_EXPORTACAO_LINHAS:
        raise ErroFiltro(f"A exportação aceita até {LIMITE_EXPORTACAO_LINHAS:,} registros; "
                         f"há {k:,}. Restrinja os filtros.".replace(",", "."))
    per = prev.periodo(m)
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(prev.nome_arquivo).stem)[:60]
    trecho = lambda s: s.replace("-", "").replace(":", "")[:13]  # noqa: E731
    nome = f"nodewatch_ml_{prev.dominio}_{stem}_{trecho(per['inicio'])}_{trecho(per['fim'])}_{k}reg.csv"
    conteudo = prev.bruto[m].to_csv(index=False, lineterminator="\n").encode("utf-8")
    return conteudo, nome, {"fonte": prev.id, "arquivo": prev.nome_arquivo, "registros": k, "periodo": per}


# ---------------------------------------------------------------------------
# Repositório de fontes
# ---------------------------------------------------------------------------
def _contar_linhas(caminho: Path) -> int:
    n, ultimo = 0, b"\n"
    with caminho.open("rb") as fh:
        while True:
            bloco = fh.read(1 << 20)
            if not bloco:
                break
            n += bloco.count(b"\n")
            ultimo = bloco[-1:]
    return max(0, n - 1 + (0 if ultimo == b"\n" else 1))


def _cabecalho(caminho: Path) -> List[str]:
    with caminho.open("r", encoding="utf-8-sig", errors="replace") as fh:
        primeira = fh.readline().strip()
    return [c.strip().strip('"') for c in primeira.split(",")]


def _sanitizar_relatorio(rel: Dict[str, Any]) -> Dict[str, Any]:
    """Resumo do ``.relatorio.json`` sem caminhos absolutos da máquina."""
    nome = lambda c: Path(str(c).replace("\\", "/")).name if c else None  # noqa: E731
    saida: Dict[str, Any] = {"linhas_previstas": rel.get("linhas_previstas")}
    if "cobertura" in rel:
        saida["cobertura"] = rel["cobertura"]
    if "rotulos_presentes" in rel:
        saida["rotulos_presentes"] = rel["rotulos_presentes"]
    ingestao = rel.get("ingestao") or {}
    if ingestao.get("arquivos"):
        saida["entradas"] = [{"arquivo": nome(a.get("caminho")), "linhas": a.get("linhas"), "sha256": a.get("sha256")}
                             for a in ingestao["arquivos"]]
    if rel.get("arquivo"):
        saida["entradas"] = [{"arquivo": nome(rel["arquivo"]), "linhas": rel.get("linhas_previstas"),
                              "sha256": rel.get("sha256")}]
    if "historico" in rel:
        saida["historico"] = nome(rel["historico"])
    if "fracao_historico_incompleto" in rel:
        saida["fracao_historico_incompleto"] = rel["fracao_historico_incompleto"]
    deriva = rel.get("deriva") or {}
    if deriva:
        saida["deriva_psi_acima_0_25"] = deriva.get("colunas_psi_acima_0_25", [])
    if rel.get("aviso"):
        saida["aviso"] = rel["aviso"]
    return saida


class RepositorioFontes:
    """Fontes da aplicação (pastas previstas) e arquivos importados (só em memória)."""

    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)
        self._trava = threading.RLock()
        self._carregadas: "OrderedDict[str, Tuple[Tuple[int, int], Previsoes]]" = OrderedDict()
        self._importados: "OrderedDict[str, Previsoes]" = OrderedDict()
        self._contagens: Dict[str, Tuple[Tuple[int, int], int]] = {}
        self._contador = 0
        self.cache_entradas: "OrderedDict[str, pd.DataFrame]" = OrderedDict()

    # -- fontes da aplicação ---------------------------------------------
    def _descobrir(self) -> Dict[str, Dict[str, Any]]:
        fontes: Dict[str, Dict[str, Any]] = {}
        for pasta, procedencia in PASTAS_PREVISOES:
            base = self.raiz / pasta
            if not base.is_dir():
                continue
            for caminho in sorted(base.glob("*.csv")):
                try:
                    dominio = detectar_dominio(_cabecalho(caminho))
                except OSError:
                    continue
                if dominio is None:
                    continue
                rel = f"{pasta}/{caminho.name}"
                fontes["app:" + rel] = {"caminho": caminho, "pasta": pasta, "dominio": dominio,
                                        "procedencia": procedencia}
        return fontes

    def _conjunto(self, caminho: Path, n: int) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        stem = caminho.stem
        if stem.endswith("_amostra"):
            base = stem[: -len("_amostra")] + "_exemplo"
            rel = self._ler_relatorio(caminho.with_name(base + ".relatorio.json"))
            total = rel.get("linhas_previstas") if rel else None
            return ({"tipo": "amostra", "linhas_arquivo": n, "linhas_conjunto": total,
                     "motivo": f"amostra versionada: cabeçalho e primeiras {n} linhas de {base}.csv "
                               "(docs/ml/README.md)"}, rel)
        rel = self._ler_relatorio(caminho.with_suffix(".relatorio.json"))
        total = rel.get("linhas_previstas") if rel else None
        if total is None:
            return ({"tipo": "desconhecido", "linhas_arquivo": n, "linhas_conjunto": None,
                     "motivo": "não há relatório da execução (.relatorio.json) para confirmar se o arquivo está completo"},
                    rel)
        if total == n:
            return ({"tipo": "completo", "linhas_arquivo": n, "linhas_conjunto": total,
                     "motivo": "todas as linhas previstas na execução registrada em .relatorio.json"}, rel)
        return ({"tipo": "amostra", "linhas_arquivo": n, "linhas_conjunto": total,
                 "motivo": f"o relatório da execução registra {total} previsões; o arquivo tem {n}"}, rel)

    @staticmethod
    def _ler_relatorio(caminho: Path) -> Optional[Dict[str, Any]]:
        if not caminho.is_file():
            return None
        try:
            return _sanitizar_relatorio(json.loads(caminho.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None

    def _linhas(self, caminho: Path) -> int:
        st = caminho.stat()
        assinatura = (st.st_size, st.st_mtime_ns)
        guardado = self._contagens.get(str(caminho))
        if guardado and guardado[0] == assinatura:
            return guardado[1]
        n = _contar_linhas(caminho)
        self._contagens[str(caminho)] = (assinatura, n)
        return n

    def listar(self) -> List[Dict[str, Any]]:
        with self._trava:
            saida = []
            for fid, info in self._descobrir().items():
                n = self._linhas(info["caminho"])
                conjunto, rel = self._conjunto(info["caminho"], n)
                saida.append({"id": fid, "dominio": info["dominio"], "nome_arquivo": info["caminho"].name,
                              "pasta": info["pasta"], "procedencia": info["procedencia"], "origem": "aplicacao",
                              "registros": n, "conjunto": conjunto, "tamanho_bytes": info["caminho"].stat().st_size})
            for prev in self._importados.values():
                saida.append({"id": prev.id, "dominio": prev.dominio, "nome_arquivo": prev.nome_arquivo,
                              "pasta": None, "procedencia": "Importado nesta sessão (só em memória)",
                              "origem": "importado", "registros": prev.n, "conjunto": prev.conjunto,
                              "tamanho_bytes": None})
            return saida

    def obter(self, fonte_id: str) -> Previsoes:
        with self._trava:
            if fonte_id in self._importados:
                self._importados.move_to_end(fonte_id)
                return self._importados[fonte_id]
            fontes = self._descobrir()
            if fonte_id not in fontes:
                raise KeyError(fonte_id)
            info = fontes[fonte_id]
            st = info["caminho"].stat()
            assinatura = (st.st_size, st.st_mtime_ns)
            guardado = self._carregadas.get(fonte_id)
            if guardado and guardado[0] == assinatura:
                self._carregadas.move_to_end(fonte_id)
                return guardado[1]
            n = self._linhas(info["caminho"])
            conjunto, rel = self._conjunto(info["caminho"], n)
            prev = carregar_previsoes(info["caminho"], info["caminho"].name, fonte_id, "aplicacao", conjunto,
                                      info["pasta"], rel, info["dominio"])
            prev.conjunto["linhas_arquivo"] = prev.n
            self._carregadas[fonte_id] = (assinatura, prev)
            while len(self._carregadas) > MAX_FONTES_EM_MEMORIA:
                self._carregadas.popitem(last=False)
            return prev

    def importar(self, conteudo: bytes, nome_arquivo: str, amostra_declarada: bool = False,
                 dominio: Optional[str] = None) -> Previsoes:
        if len(conteudo) > LIMITE_IMPORTACAO_BYTES:
            raise ErroContrato([f"o arquivo tem {len(conteudo) / 1e6:.1f} MB; o limite de importação é "
                                f"{LIMITE_IMPORTACAO_BYTES / 1e6:.0f} MB"],
                               "Gere o arquivo com a CLI numa das pastas previstas (por exemplo, "
                               "artefatos_ml/previsoes/) e selecione-o na lista de arquivos da aplicação.")
        nome = Path(nome_arquivo or "importado.csv").name
        if not nome.lower().endswith(".csv"):
            raise ErroContrato([f"'{nome}' não tem extensão .csv"], "Importe um arquivo CSV de previsões.")
        if amostra_declarada:
            conjunto = {"tipo": "amostra", "linhas_conjunto": None,
                        "motivo": "declarado como amostra na importação"}
        elif "amostra" in nome.lower():
            conjunto = {"tipo": "amostra", "linhas_conjunto": None, "motivo": "o nome do arquivo indica amostra"}
        else:
            conjunto = {"tipo": "desconhecido", "linhas_conjunto": None,
                        "motivo": "arquivo importado sem relatório da execução; os indicadores valem só "
                                  "para as linhas deste arquivo"}
        with self._trava:
            self._contador += 1
            fid = f"imp-{self._contador}"
        prev = carregar_previsoes(bytes(conteudo), nome, fid, "importado", conjunto, None, None, dominio)
        prev.conjunto["linhas_arquivo"] = prev.n
        with self._trava:
            self._importados[fid] = prev
            while len(self._importados) > MAX_IMPORTADOS:
                self._importados.popitem(last=False)
        return prev

    def remover_importado(self, fonte_id: str) -> bool:
        with self._trava:
            return self._importados.pop(fonte_id, None) is not None
