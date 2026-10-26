"""Contratos versionados dos dados (esquemas) e sua validação.

Cada esquema descreve as colunas, tipos, domínios, sentinelas e o significado
de cada campo. O significado traz um ``status``:

* ``verificado`` — conferido nos dados por ``src.ml.auditoria`` (a auditoria
  refaz a conferência a cada execução);
* ``inferido``   — deduzido do nome e da distribuição; a construção original
  da coluna não está documentada.

Esquemas:

* ``rede_v1``       — telemetria por fluxo (``dataset_final.csv``);
* ``hismall_v1``    — transações brutas do IBM AML HI-Small;
* ``transacao_v1``  — PROPOSTA de contrato financeiro genérico (a validar);
* ``vinculo_v1``    — PROPOSTA de tabela que liga transação a fluxo de rede.

A validação nunca preenche colunas ausentes: coluna obrigatória faltando,
tipo incompatível, NaN/inf ou valor fora do domínio geram :class:`ErroEsquema`
com a lista completa de problemas.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

CLASSES_REDE = ("OK", "RISCO", "FALHA")
SPLITS = ("treino", "validacao", "teste")


class ErroEsquema(ValueError):
    """Dados incompatíveis com o esquema. ``problemas`` lista cada falha."""

    def __init__(self, esquema: str, problemas: Sequence[str]):
        self.problemas = list(problemas)
        texto = "\n  - ".join(self.problemas)
        super().__init__(f"Dados incompatíveis com o esquema {esquema}:\n  - {texto}")


@dataclass(frozen=True)
class Coluna:
    nome: str
    tipo: str                      # "int", "float", "str", "cat", "datahora"
    papel: str                     # "id", "tempo", "controle", "alvo", "feature", "contexto"
    descricao: str
    unidade: str = ""
    status: str = "inferido"
    obrigatoria_treino: bool = True
    obrigatoria_inferencia: bool = True
    dominio: Optional[Tuple[Any, ...]] = None
    faixa: Optional[Tuple[float, float]] = None
    sentinela: Optional[float] = None
    significado_sentinela: str = ""


@dataclass(frozen=True)
class Esquema:
    nome: str
    versao: str
    descricao: str
    colunas: Tuple[Coluna, ...]
    proposta: bool = False
    observacoes: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def id(self) -> str:
        return f"{self.nome}_{self.versao}"

    def coluna(self, nome: str) -> Coluna:
        for c in self.colunas:
            if c.nome == nome:
                return c
        raise KeyError(nome)

    def nomes(self, papel: Optional[str] = None) -> List[str]:
        return [c.nome for c in self.colunas if papel is None or c.papel == papel]

    def sentinelas(self) -> Dict[str, float]:
        return {c.nome: c.sentinela for c in self.colunas if c.sentinela is not None}

    def para_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["id"] = self.id
        return d

    # ------------------------------------------------------------------
    def validar(
        self,
        df: pd.DataFrame,
        modo: str = "treino",
        exigir: Sequence[str] = (),
        ignorar_ausentes: Sequence[str] = (),
    ) -> None:
        """Valida ``df``; levanta :class:`ErroEsquema` se houver problemas.

        Args:
            modo: ``"treino"`` ou ``"inferencia"`` (decide quais colunas são
                obrigatórias).
            exigir: colunas obrigatórias adicionais (ex.: ``classe_atual``
                quando o modelo escolhido depende dela).
            ignorar_ausentes: colunas que podem faltar mesmo sendo obrigatórias.
        """
        if modo not in ("treino", "inferencia"):
            raise ValueError(f"modo inválido: {modo}")
        problemas: List[str] = []
        presentes = set(df.columns)
        for c in self.colunas:
            obrig = c.obrigatoria_treino if modo == "treino" else c.obrigatoria_inferencia
            if c.nome in exigir:
                obrig = True
            if c.nome not in presentes:
                if obrig and c.nome not in ignorar_ausentes:
                    problemas.append(f"coluna obrigatória ausente: {c.nome}")
                continue
            problemas.extend(_validar_coluna(df[c.nome], c))
        if len(df) == 0:
            problemas.append("nenhuma linha")
        if problemas:
            raise ErroEsquema(self.id, problemas)


def _validar_coluna(s: pd.Series, c: Coluna) -> List[str]:
    p: List[str] = []
    if c.tipo in ("int", "float"):
        if not pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            conv = pd.to_numeric(s, errors="coerce")
            ruins = int(conv.isna().sum() - s.isna().sum())
            if ruins:
                return [f"{c.nome}: {ruins} valor(es) não numérico(s)"]
            s = conv
        valores = s.to_numpy(dtype="float64", na_value=np.nan)
        n_nan = int(np.isnan(valores).sum())
        n_inf = int(np.isinf(valores).sum())
        if n_nan:
            p.append(f"{c.nome}: {n_nan} valor(es) ausente(s) (NaN)")
        if n_inf:
            p.append(f"{c.nome}: {n_inf} valor(es) infinito(s)")
        finitos = valores[np.isfinite(valores)]
        if c.tipo == "int" and finitos.size and not np.all(np.equal(np.mod(finitos, 1), 0)):
            p.append(f"{c.nome}: esperado inteiro, há valores fracionários")
        if c.faixa is not None and finitos.size:
            lo, hi = c.faixa
            fora = (finitos < lo) | (finitos > hi)
            if c.sentinela is not None:
                fora &= finitos != c.sentinela
            if fora.any():
                p.append(f"{c.nome}: {int(fora.sum())} valor(es) fora da faixa [{lo}, {hi}]")
        if c.dominio is not None and finitos.size:
            fora = ~np.isin(finitos, np.asarray(c.dominio, dtype="float64"))
            if fora.any():
                p.append(f"{c.nome}: {int(fora.sum())} valor(es) fora do domínio {c.dominio}")
    elif c.tipo in ("str", "cat"):
        n_nan = int(s.isna().sum())
        if n_nan:
            p.append(f"{c.nome}: {n_nan} valor(es) ausente(s)")
        if c.dominio is not None:
            fora = ~s.dropna().astype(str).isin([str(v) for v in c.dominio])
            if fora.any():
                exemplos = sorted(s.dropna().astype(str)[fora].unique())[:5]
                p.append(f"{c.nome}: {int(fora.sum())} valor(es) fora do domínio {c.dominio}: {exemplos}")
    elif c.tipo == "datahora":
        conv = pd.to_datetime(s, errors="coerce")
        ruins = int(conv.isna().sum())
        if ruins:
            p.append(f"{c.nome}: {ruins} data(s)/hora(s) inválida(s) ou ausente(s)")
    return p


# ---------------------------------------------------------------------------
# rede_v1
# ---------------------------------------------------------------------------
_SEM_RTT = "sem RTT na medição (ocorre exatamente quando rtt_ausente = 1)"
_SEM_RTT_JANELA = "nenhuma medição da janela teve RTT"


def _janela(k: int) -> Tuple[Coluna, ...]:
    return (
        Coluna(f"perda_media_w{k}", "float", "feature",
               f"Média de perda_pct nas últimas {k} medições do fluxo, incluindo a atual.",
               "%", "verificado", faixa=(0, 100)),
        Coluna(f"rtt_p95_max_w{k}", "float", "feature",
               f"Máximo de razao_rtt_p95 nas últimas {k} medições, incluindo a atual.",
               "adimensional", "verificado", faixa=(0, 1e6), sentinela=-1,
               significado_sentinela=_SEM_RTT_JANELA),
        Coluna(f"jitter_p95_max_w{k}", "float", "feature",
               f"Máximo de razao_jitter_p95 nas últimas {k} medições, incluindo a atual.",
               "adimensional", "verificado", faixa=(0, 1e6), sentinela=-1,
               significado_sentinela=_SEM_RTT_JANELA),
        Coluna(f"n_rtt_acima_p95_w{k}", "int", "feature",
               f"Quantidade, entre as últimas {k} medições, com razao_rtt_p95 > 1.",
               "contagem", "verificado", faixa=(0, k), sentinela=-1,
               significado_sentinela=_SEM_RTT_JANELA),
    )


ESQUEMA_REDE_V1 = Esquema(
    nome="rede",
    versao="v1",
    descricao=(
        "Uma linha por medição de um fluxo sonda→âncora. O alvo é o estado da "
        "PRÓXIMA medição do mesmo fluxo (intervalo mediano de 240 s, irregular)."
    ),
    colunas=(
        Coluna("id_fluxo", "str", "id", "Fluxo = '<probe_id>_<anchor_id>'.", status="verificado"),
        Coluna("anchor_id", "int", "id", "Âncora de destino das medições.", status="verificado"),
        Coluna("probe_id", "int", "id", "Sonda de origem das medições.", status="verificado"),
        Coluna("timestamp", "int", "tempo", "Instante da medição (época Unix, UTC presumido).",
               "s", "inferido", faixa=(0, 4e9)),
        Coluna("split", "cat", "controle", "Período temporal: treino, validacao ou teste.",
               status="verificado", obrigatoria_inferencia=False, dominio=SPLITS),
        Coluna("classe_atual", "cat", "contexto",
               "Estado da medição atual. Reproduzido a 99,94% por limiares sobre perda_pct, "
               "razao_rtt_p95/p99 e razao_jitter_p95; disponível no instante da previsão.",
               status="verificado", obrigatoria_inferencia=False, dominio=CLASSES_REDE),
        Coluna("alvo", "cat", "alvo",
               "Estado da próxima medição do fluxo (coincide com a classe_atual seguinte "
               "em 99,98% dos pares).", status="verificado", obrigatoria_inferencia=False,
               dominio=CLASSES_REDE),
        Coluna("perda_pct", "float", "feature", "Perda de pacotes na medição.", "%",
               "inferido", faixa=(0, 100)),
        Coluna("rtt_ausente", "int", "feature", "1 se a medição não obteve RTT (perda total).",
               "indicador", "verificado", dominio=(0, 1)),
        Coluna("razao_rtt_p95", "float", "feature",
               "RTT da medição dividido pelo p95 de referência do fluxo. O período de "
               "referência do percentil não está documentado.", "adimensional", "inferido",
               faixa=(0, 1e6), sentinela=-1, significado_sentinela=_SEM_RTT),
        Coluna("razao_rtt_p99", "float", "feature",
               "RTT da medição dividido pelo p99 de referência do fluxo.", "adimensional",
               "inferido", faixa=(0, 1e6), sentinela=-1, significado_sentinela=_SEM_RTT),
        Coluna("razao_jitter_p95", "float", "feature",
               "Jitter da medição dividido pelo p95 de referência do jitter do fluxo.",
               "adimensional", "inferido", faixa=(0, 1e7), sentinela=-1,
               significado_sentinela=_SEM_RTT),
        Coluna("amplitude_rtt_rel", "float", "feature",
               "Amplitude do RTT na medição relativa ao RTT típico.", "adimensional",
               "inferido", faixa=(0, 1e6), sentinela=-1, significado_sentinela=_SEM_RTT),
        Coluna("delta_ttl_clip", "int", "feature",
               "Variação do TTL em relação à medição anterior, recortada. Valores "
               "negativos são legítimos (não é sentinela).", "saltos", "inferido",
               faixa=(-64, 64)),
        Coluna("ttl_reset", "int", "feature", "Indicador de reinício de TTL (constante 0 no "
               "arquivo atual; removido no treino por variância nula).", "indicador",
               "inferido", dominio=(0, 1)),
        *_janela(3),
        *_janela(6),
        *_janela(12),
        Coluna("perdas_consecutivas", "int", "feature",
               "Medições consecutivas com perda até a atual (máximo observado 99, "
               "possivelmente recortado).", "contagem", "inferido", faixa=(0, 1e6)),
    ),
    observacoes=(
        "As janelas w3/w6/w12 são contadas em linhas (medições), não em tempo.",
        "Linhas removidas da série bruta deixam lacunas: o alvo de uma linha antes de "
        "uma lacuna pode se referir a uma medição que não está no arquivo.",
    ),
)

FEATURES_REDE: Tuple[str, ...] = tuple(ESQUEMA_REDE_V1.nomes("feature"))
# Nunca entram nos preditores da rede.
PROIBIDAS_REDE = frozenset({"alvo", "split", "id_fluxo", "anchor_id", "probe_id", "timestamp"})

# ---------------------------------------------------------------------------
# hismall_v1 (transações brutas do IBM AML HI-Small)
# ---------------------------------------------------------------------------
COLUNAS_HISMALL = (
    "Timestamp", "From Bank", "Account", "To Bank", "Account.1", "Amount Received",
    "Receiving Currency", "Amount Paid", "Payment Currency", "Payment Format", "Is Laundering",
)

ESQUEMA_HISMALL_V1 = Esquema(
    nome="hismall",
    versao="v1",
    descricao=(
        "Transações sintéticas do IBM AML (AMLworld), conjunto HI-Small. A coluna "
        "'Account' aparece duas vezes no cabeçalho original (origem e destino)."
    ),
    colunas=(
        Coluna("Timestamp", "datahora", "tempo", "Data e hora da transação (resolução de minuto, "
               "fuso não documentado).", status="verificado"),
        Coluna("From Bank", "int", "id", "Banco de origem.", status="verificado"),
        Coluna("Account", "str", "id", "Conta de origem (única dentro do banco).", status="verificado"),
        Coluna("To Bank", "int", "id", "Banco de destino.", status="verificado"),
        Coluna("Account.1", "str", "id", "Conta de destino.", status="verificado"),
        Coluna("Amount Received", "float", "feature", "Valor recebido, na moeda de recebimento.",
               "moeda", "verificado", faixa=(0, 1e15)),
        Coluna("Receiving Currency", "cat", "feature", "Moeda de recebimento.", status="verificado"),
        Coluna("Amount Paid", "float", "feature", "Valor pago, na moeda de pagamento.",
               "moeda", "verificado", faixa=(0, 1e15)),
        Coluna("Payment Currency", "cat", "feature", "Moeda de pagamento.", status="verificado"),
        Coluna("Payment Format", "cat", "feature", "Meio de pagamento (ACH, Wire, Cheque, ...).",
               status="verificado"),
        Coluna("Is Laundering", "int", "alvo", "1 = transação faz parte de lavagem segundo o "
               "simulador (verdade sintética, sem data de confirmação).", status="verificado",
               obrigatoria_inferencia=False, dominio=(0, 1)),
    ),
)

# ---------------------------------------------------------------------------
# PROPOSTAS de integração (a validar com quem fornecer os dados)
# ---------------------------------------------------------------------------
ROTULOS_FRAUDE = ("fraude_confirmada", "legitima_confirmada", "sem_conclusao")

ESQUEMA_TRANSACAO_V1 = Esquema(
    nome="transacao",
    versao="v1",
    proposta=True,
    descricao="Contrato financeiro mínimo PROPOSTO para transações vinculáveis à rede.",
    colunas=(
        Coluna("id_transacao", "str", "id", "Identificador único e estável da transação."),
        Coluna("timestamp_transacao", "datahora", "tempo", "Instante da transação, em UTC."),
        Coluna("timestamp_disponivel", "datahora", "tempo",
               "Instante em que a transação fica disponível para análise (>= timestamp_transacao)."),
        Coluna("conta_origem", "str", "id", "Conta de origem."),
        Coluna("conta_destino", "str", "id", "Conta de destino."),
        Coluna("valor", "float", "feature", "Valor na moeda informada.", "moeda", faixa=(0, 1e15)),
        Coluna("moeda", "cat", "feature", "Código da moeda (ISO 4217 recomendado)."),
        Coluna("formato_pagamento", "cat", "feature", "Meio de pagamento.",
               obrigatoria_treino=False, obrigatoria_inferencia=False),
        Coluna("chave_tecnica", "str", "id",
               "Sessão, dispositivo ou nó que permita o vínculo com a rede (só se existir "
               "e tiver significado verificável).", obrigatoria_treino=False,
               obrigatoria_inferencia=False),
        Coluna("rotulo_fraude", "cat", "alvo", "fraude_confirmada, legitima_confirmada ou "
               "sem_conclusao. Ausência de confirmação NÃO é legitimidade.",
               obrigatoria_inferencia=False, dominio=ROTULOS_FRAUDE),
        Coluna("origem_rotulo", "str", "controle", "Fonte da evidência do rótulo.",
               obrigatoria_inferencia=False),
        Coluna("timestamp_confirmacao", "datahora", "controle",
               "Quando o rótulo ficou disponível (necessário para respeitar o atraso).",
               obrigatoria_treino=False, obrigatoria_inferencia=False),
    ),
)

ESQUEMA_VINCULO_V1 = Esquema(
    nome="vinculo",
    versao="v1",
    proposta=True,
    descricao=(
        "Tabela PROPOSTA que liga uma transação (ou sua chave técnica) a um fluxo de rede "
        "monitorado, com validade no tempo. Proximidade de horário NÃO é vínculo."
    ),
    colunas=(
        Coluna("chave", "str", "id", "id_transacao ou chave_tecnica (ver tipo_chave)."),
        Coluna("tipo_chave", "cat", "controle", "'id_transacao' ou 'chave_tecnica'.",
               dominio=("id_transacao", "chave_tecnica")),
        Coluna("id_fluxo", "str", "id", "Fluxo de rede vinculado (formato rede_v1)."),
        Coluna("valido_de", "datahora", "tempo", "Início da validade do vínculo (UTC)."),
        Coluna("valido_ate", "datahora", "tempo", "Fim da validade do vínculo (UTC, exclusivo)."),
        Coluna("fonte_vinculo", "str", "controle", "Origem documentada da associação."),
    ),
)

ESQUEMAS = {e.id: e for e in (ESQUEMA_REDE_V1, ESQUEMA_HISMALL_V1, ESQUEMA_TRANSACAO_V1,
                              ESQUEMA_VINCULO_V1)}
