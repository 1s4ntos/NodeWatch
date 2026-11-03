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
