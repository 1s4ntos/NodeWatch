"""Score do painel: escala inteira de 0 a 1000 e faixas de recomendação.

O que o modelo devolve
    A cabeça ``lavagem`` devolve ``predict_proba`` da classe 1 de uma floresta
    aleatória treinada com subamostragem de negativos. É um número em [0, 1],
    mas **não é probabilidade calibrada**: na avaliação oficial, as transações
    com valor entre 0,1 e 0,2 foram lavagem em 65% dos casos, e o limiar de
    alerta escolhido na validação é cerca de 0,09. Multiplicar por 1000
    colocaria todo alerta na faixa "baixa" e sugeriria uma probabilidade que
    o modelo não entrega.

Conversão usada (ordinal, ancorada no limiar)
    O único ponto de operação validado do modelo é o limiar de alerta. A
    escala 0–1000 é linear por partes, com esse ponto como âncora::

        bruto = 0        → 0
        bruto → limiar⁻  → 700   (maior score sem alerta)
        bruto = limiar   → 701   (menor score com alerta)
        bruto = 1        → 1000

    Consequências, todas testadas:
      * é monótona: quem tem bruto maior nunca fica com score menor;
      * ``score >= 701`` equivale exatamente a ``bruto >= limiar`` (alerta);
      * a faixa intermediária (301–700) é o trecho logo abaixo do limiar: de
        cerca de 43% (300/701) a 100% do limiar;
      * o score depende do limiar: scores de versões de modelo com limiares
        diferentes não são comparáveis entre si. O limiar e a versão ficam
        gravados no manifesto de cada análise.

    O score é uma **ordem de prioridade**, não uma probabilidade. O valor
    bruto fica guardado em cada transação e aparece nos detalhes.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

SCORE_MIN = 0
SCORE_MAX = 1000
CORTE_BAIXA = 300        # 0–300
CORTE_INTERMEDIARIA = 700  # 301–700; 701–1000 = alta
SCORE_ALERTA = CORTE_INTERMEDIARIA + 1

FAIXAS: List[Dict[str, Any]] = [
    {"id": "baixa", "nome": "Baixa", "de": 0, "ate": CORTE_BAIXA,
     "recomendacao": "sugestão de aprovação automática"},
    {"id": "intermediaria", "nome": "Intermediária", "de": CORTE_BAIXA + 1, "ate": CORTE_INTERMEDIARIA,
     "recomendacao": "área cinzenta: sugestão de análise manual"},
    {"id": "alta", "nome": "Alta", "de": SCORE_ALERTA, "ate": SCORE_MAX,
     "recomendacao": "sugestão de recusa ou bloqueio (gera alerta)"},
]

AVISO_FAIXAS = (
    "As faixas são recomendações de uma análise offline. O NodeWatch não bloqueia, não aprova e não paga "
    "nada: não há integração bancária. Score alto é sinal para investigação, não prova de lavagem."
)


def converter(bruto: Any, limiar: float) -> np.ndarray:
    """Score bruto do modelo (0–1) → inteiro de 0 a 1000, ancorado em ``limiar``."""
    if not (0.0 < float(limiar) < 1.0):
        raise ValueError(f"limiar de alerta fora de (0, 1): {limiar!r}")
    b = np.asarray(bruto, dtype=np.float64)
    if b.size and (np.isnan(b).any() or (b < 0).any() or (b > 1).any()):
        raise ValueError("score bruto fora de [0, 1] ou ausente")
    abaixo = np.minimum(np.floor(b / limiar * SCORE_ALERTA), CORTE_INTERMEDIARIA)
    acima = SCORE_ALERTA + np.floor((b - limiar) / (1.0 - limiar) * (SCORE_MAX - SCORE_ALERTA))
    return np.where(b >= limiar, np.minimum(acima, SCORE_MAX), abaixo).astype(np.int64)


def faixa(score: int) -> str:
    """Identificador da faixa (``baixa``, ``intermediaria`` ou ``alta``) de um score inteiro."""
    s = int(score)
    if not SCORE_MIN <= s <= SCORE_MAX:
        raise ValueError(f"score fora de 0–1000: {score!r}")
    if s <= CORTE_BAIXA:
        return "baixa"
    if s <= CORTE_INTERMEDIARIA:
        return "intermediaria"
    return "alta"


def descricao_conversao(limiar: float) -> Dict[str, Any]:
    """Parâmetros da conversão, gravados no manifesto e mostrados na legenda."""
    return {
        "escala": [SCORE_MIN, SCORE_MAX],
        "tipo": "linear por partes, ancorada no limiar de alerta do modelo",
        "limiar_bruto": float(limiar),
        "ancoras": [{"bruto": 0.0, "score": 0}, {"bruto": float(limiar), "score": SCORE_ALERTA},
                    {"bruto": 1.0, "score": SCORE_MAX}],
        "bruto_no_inicio_da_intermediaria": float(limiar) * (CORTE_BAIXA + 1) / SCORE_ALERTA,
        # a que trecho do score original (0–1) cada faixa corresponde: [de, até) — a alta inclui o 1
        "faixas_no_score_original": [
            {"id": "baixa", "de": 0.0, "ate": float(limiar) * (CORTE_BAIXA + 1) / SCORE_ALERTA},
            {"id": "intermediaria", "de": float(limiar) * (CORTE_BAIXA + 1) / SCORE_ALERTA, "ate": float(limiar)},
            {"id": "alta", "de": float(limiar), "ate": 1.0},
        ],
        "calibrado": False,
        "natureza": ("O score original do modelo (0 a 1) não é probabilidade calibrada. A escala de 0 a 1000 é um "
                     "índice de prioridade obtido dele; não é probabilidade de lavagem nem de fraude."),
        "leitura": ("O score de 0 a 1000 ordena as transações por prioridade; não é probabilidade. "
                    f"Score {SCORE_ALERTA} ou mais equivale ao limiar de alerta do modelo."),
    }
