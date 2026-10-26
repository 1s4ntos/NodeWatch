"""Preparação dos dados: transformadores da rede e atributos financeiros.

Rede
    :class:`SentinelaParaNaN` troca os ``-1`` documentados por ausente (só nas
    colunas em que o ``-1`` é sentinela; ``delta_ttl_clip`` negativo é valor
    legítimo) e cria um indicador por janela sem RTT. Imputação, remoção de
    constantes, log e escala são ajustados só no treino, dentro do pipeline.

Financeiro (HI-Small)
    :func:`atributos_financeiros` calcula, para cada transação consultada,
    atributos que usam SOMENTE transações de minutos estritamente anteriores
    (janela ``[t - w, t)``). Como o horário tem resolução de minuto,
    transações do mesmo minuto não se enxergam: a ordem dentro do minuto não
    é confiável. O rótulo de transações passadas nunca vira atributo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.feature_selection import VarianceThreshold
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from src.ml.esquemas import CLASSES_REDE, ESQUEMA_REDE_V1, FEATURES_REDE, PROIBIDAS_REDE

# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
SENTINELAS_REDE: Dict[str, float] = ESQUEMA_REDE_V1.sentinelas()
# As razões instantâneas já têm indicador próprio (rtt_ausente); as janelas
# ganham um indicador por largura.
INDICADORES_REDE: Dict[str, str] = {f"sem_rtt_w{k}": f"rtt_p95_max_w{k}" for k in (3, 6, 12)}


def log_com_sinal(x):
    """sign(x)·log1p(|x|): reduz caudas longas (ex.: jitter até 10.809×)."""
    return np.sign(x) * np.log1p(np.abs(x))


class SentinelaParaNaN(BaseEstimator, TransformerMixin):
    """Converte sentinelas em NaN e acrescenta indicadores de ausência."""

    def __init__(self, sentinelas: Optional[Dict[str, float]] = None,
                 indicadores: Optional[Dict[str, str]] = None):
        self.sentinelas = sentinelas
        self.indicadores = indicadores

    def fit(self, X, y=None):
        X = self._df(X)
        self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        self.n_features_in_ = X.shape[1]
        return self

    def _df(self, X) -> pd.DataFrame:
        if isinstance(X, pd.DataFrame):
            return X
        nomes = getattr(self, "feature_names_in_", None)
        return pd.DataFrame(np.asarray(X), columns=nomes)

    def transform(self, X):
        X = self._df(X)
        esperadas = list(self.feature_names_in_)
        if list(X.columns) != esperadas:
            raise ValueError(f"Colunas diferentes das do treino: {list(X.columns)} != {esperadas}")
        saida = X.astype("float64")
        sent = self.sentinelas or {}
        for nome, origem in (self.indicadores or {}).items():
            if origem in saida:
                saida[nome] = (saida[origem] == sent.get(origem, np.nan)).astype("float64")
        for col, valor in sent.items():
            if col in saida:
                saida[col] = saida[col].mask(saida[col] == valor)
        return saida

    def get_feature_names_out(self, input_features=None):
        nomes = list(self.feature_names_in_)
        nomes += [n for n, o in (self.indicadores or {}).items() if o in nomes]
        return np.asarray(nomes, dtype=object)


def matriz_rede(df: pd.DataFrame, usar_classe_atual: bool = False) -> pd.DataFrame:
    """Seleciona os preditores da rede, na ordem fixa do esquema.

    ``alvo``, ``split`` e identificadores nunca entram. ``classe_atual`` só
    entra (em one-hot) na variante comparativa.
    """
    colunas = list(FEATURES_REDE)
    proibidas = PROIBIDAS_REDE.intersection(colunas)
    if proibidas:  # proteção contra edição indevida do esquema
        raise ValueError(f"Colunas proibidas entre os preditores: {sorted(proibidas)}")
    faltam = [c for c in colunas if c not in df.columns]
    if faltam:
        raise ValueError(f"Preditores ausentes: {faltam}")
    X = df[colunas].astype("float64")
    if usar_classe_atual:
        if "classe_atual" not in df:
            raise ValueError("O modelo usa classe_atual, mas a coluna não foi fornecida.")
        for classe in CLASSES_REDE[1:]:
            X[f"classe_atual_{classe}"] = (df["classe_atual"] == classe).astype("float64").to_numpy()
    return X


def montar_pipeline_rede(estimador: Any, linear: bool) -> Pipeline:
    passos: List[Tuple[str, Any]] = [
        ("sentinelas", SentinelaParaNaN(SENTINELAS_REDE, INDICADORES_REDE)),
        ("constantes", VarianceThreshold(0.0)),
    ]
    if linear:
        passos += [
            ("imputacao", SimpleImputer(strategy="median")),
            ("log", FunctionTransformer(log_com_sinal, feature_names_out="one-to-one")),
            ("escala", StandardScaler()),
        ]
    passos.append(("modelo", estimador))
    return Pipeline(passos).set_output(transform="pandas")


# ---------------------------------------------------------------------------
# Financeiro — divisão temporal
# ---------------------------------------------------------------------------
MINUTOS_DIA = 1440
_EPOCA = pd.Timestamp("1970-01-01")


def minuto_de(data: str) -> int:
    return int((pd.Timestamp(data) - _EPOCA) // pd.Timedelta(minutes=1))


def atribuir_split_financeiro(minuto: np.ndarray, cfg_fin: Dict[str, Any]) -> np.ndarray:
    """Devolve ``treino``/``validacao``/``teste``/``cauda``/``fora`` por transação."""
    ini = minuto_de(cfg_fin["inicio"])
    tr = minuto_de(cfg_fin["treino_ate"])
    va = minuto_de(cfg_fin["validacao_ate"])
    te = minuto_de(cfg_fin["teste_ate"])
    cauda = minuto_de(cfg_fin["inicio_cauda"])
    if not ini < tr < va <= te <= cauda:
        raise ValueError("Limites temporais do financeiro fora de ordem.")
    saida = np.full(len(minuto), "fora", dtype=object)
    saida[(minuto >= ini) & (minuto < tr)] = "treino"
    saida[(minuto >= tr) & (minuto < va)] = "validacao"
    saida[(minuto >= va) & (minuto < te)] = "teste"
    saida[minuto >= cauda] = "cauda"
    return saida


# ---------------------------------------------------------------------------
# Financeiro — câmbio e atributos point-in-time
# ---------------------------------------------------------------------------
def estimar_cambio(trans: pd.DataFrame, moeda_base: str = "US Dollar") -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Estima ``moeda -> unidades da moeda base por unidade`` a partir dos pares
    pagamento≠recebimento (mediana de valor_recebido/valor_pago).

    Use só transações do treino. Moedas sem caminho até a base ficam de fora
    (os valores delas viram ausentes, com indicador).
    """
    m = (
        (trans["moeda_pagamento"].astype(str) != trans["moeda_recebimento"].astype(str))
        & (trans["valor_pago"] > 0) & (trans["valor_recebido"] > 0)
    )
    pares = pd.DataFrame({
        "pag": trans.loc[m, "moeda_pagamento"].astype(str).to_numpy(),
        "rec": trans.loc[m, "moeda_recebimento"].astype(str).to_numpy(),
        "q": (trans.loc[m, "valor_recebido"] / trans.loc[m, "valor_pago"]).to_numpy(),
    })
    med = pares.groupby(["pag", "rec"])["q"].agg(["median", "count"]).reset_index()
    taxa: Dict[str, float] = {moeda_base: 1.0}
    mudou = True
    while mudou:
        mudou = False
        for pag, rec, q, _ in med.itertuples(index=False):
            if pag in taxa and rec not in taxa:
                taxa[rec] = taxa[pag] / q
                mudou = True
            elif rec in taxa and pag not in taxa:
                taxa[pag] = taxa[rec] * q
                mudou = True
    todas = set(trans["moeda_pagamento"].astype(str).unique())
    info = {
        "moeda_base": moeda_base,
        "pares_usados": int(len(med)),
        "transacoes_usadas": int(m.sum()),
        "moedas_sem_taxa": sorted(todas - set(taxa)),
    }
    return taxa, info


_M = np.int64(1 << 26)  # separa chave e minuto no índice composto
_SEM_HISTORICO_MIN = 14_400.0  # 10 dias: teto para "minutos desde o último evento"


class _IndiceEventos:
    """Eventos ordenados por (chave, minuto) para consultas em ``[t - w, t)``."""

    def __init__(self, chave: np.ndarray, minuto: np.ndarray,
                 valores: Optional[Dict[str, np.ndarray]] = None):
        ordem = np.lexsort((minuto, chave))
        self.comp = chave[ordem].astype(np.int64) * _M + minuto[ordem].astype(np.int64)
        self.acum = {
            nome: np.concatenate([[0.0], np.cumsum(v[ordem], dtype=np.float64)])
            for nome, v in (valores or {}).items()
        }

    def limites(self, chave: np.ndarray, minuto: np.ndarray, w: Optional[int]):
        base = chave.astype(np.int64) * _M
        hi = np.searchsorted(self.comp, base + minuto, side="left")
        if w is None:
            lo = np.searchsorted(self.comp, base, side="left")
        else:
            lo = np.searchsorted(self.comp, base + np.maximum(minuto - w, 0), side="left")
        return lo, hi

    def soma(self, nome: str, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
        a = self.acum[nome]
        return a[hi] - a[lo]

    def minutos_desde_ultimo(self, chave: np.ndarray, minuto: np.ndarray) -> np.ndarray:
        lo, hi = self.limites(chave, minuto, None)
        saida = np.full(len(chave), np.nan)
        tem = hi > lo
        saida[tem] = minuto[tem] - (self.comp[hi[tem] - 1] % _M)
        return saida


@dataclass
class PreparadorFinanceiro:
    """Parâmetros aprendidos no treino para os atributos financeiros."""

    cambio: Dict[str, float]
    info_cambio: Dict[str, Any]
    formatos: List[str]
    moedas: List[str]
    taxa_formato: Dict[str, float]
    taxa_base: float
    colunas: List[str] = field(default_factory=list)
    quantis: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def ajustar(cls, trans_treino: pd.DataFrame, moeda_base: str = "US Dollar") -> "PreparadorFinanceiro":
        cambio, info = estimar_cambio(trans_treino, moeda_base)
        formatos = sorted(trans_treino["formato"].astype(str).unique())
        moedas = sorted(trans_treino["moeda_pagamento"].astype(str).unique())
        taxa_formato: Dict[str, float] = {}
        taxa_base = float("nan")
        if "rotulo" in trans_treino:
            g = trans_treino.groupby(trans_treino["formato"].astype(str), observed=True)["rotulo"].mean()
            taxa_formato = {k: float(v) for k, v in g.items()}
            taxa_base = float(trans_treino["rotulo"].mean())
        return cls(cambio, info, formatos, moedas, taxa_formato, taxa_base)

    def registrar_quantis(self, X_treino: pd.DataFrame) -> None:
        for col in ("n_env_origem_24h", "orig_distintas_destino", "dest_distintos_origem",
                    "soma_env_origem_usd_24h", "n_rec_destino_24h"):
            if col in X_treino:
                self.quantis[f"{col}_p99"] = float(np.nanquantile(X_treino[col], 0.99))

    def motivos(self, X: pd.DataFrame, formato: pd.Series) -> List[str]:
        """Fatos verificáveis sobre a transação (não são explicação do modelo)."""
        n = len(X)
        partes: List[List[str]] = [[] for _ in range(n)]

        def marcar(mask: np.ndarray, texto: str) -> None:
            for i in np.flatnonzero(mask):
                partes[i].append(texto)

        if self.taxa_formato and self.taxa_base > 0:
            fator = formato.astype(str).map(self.taxa_formato).fillna(0).to_numpy() / self.taxa_base
            marcar(fator >= 5, "formato com taxa de lavagem no treino >= 5x a média")
        marcar(X["par_novo"].to_numpy() == 1, "primeira transação entre origem e destino")
        for col, texto in (
            ("n_env_origem_24h", "envios da origem em 24 h acima do p99 do treino"),
            ("orig_distintas_destino", "destino com mais origens distintas que o p99 do treino"),
            ("dest_distintos_origem", "origem com mais destinos distintos que o p99 do treino"),
        ):
            q = self.quantis.get(f"{col}_p99")
            if q is not None:
                marcar(X[col].to_numpy() > q, texto)
        marcar(np.abs(X["z_valor_origem"].to_numpy()) > 3, "valor atípico para a origem (|z| > 3)")
        marcar(X["min_desde_rec_origem"].to_numpy() < 60, "origem recebeu fundos há menos de 60 min")
        marcar(X["moeda_diferente"].to_numpy() == 1, "moedas de pagamento e recebimento diferentes")
        return ["; ".join(p) for p in partes]


def atributos_financeiros(
    trans: pd.DataFrame,
    consulta: np.ndarray,
    prep: PreparadorFinanceiro,
) -> pd.DataFrame:
    """Atributos point-in-time das linhas ``consulta`` (posições em ``trans``).

    O histórico é ``trans`` inteiro, mas cada linha só enxerga transações de
    minutos estritamente anteriores ao seu. Acrescentar transações futuras ou
    do mesmo minuto não altera o resultado (ver testes).
    """
    consulta = np.asarray(consulta, dtype=np.int64)
    minuto_abs = trans["minuto"].to_numpy(dtype=np.int64)
    minuto = minuto_abs - minuto_abs.min()
    o_all = trans["conta_origem"].to_numpy(dtype=np.int64)
    d_all = trans["conta_destino"].to_numpy(dtype=np.int64)
    taxa = trans["moeda_pagamento"].astype(str).map(prep.cambio).to_numpy(dtype=np.float64)
    usd = trans["valor_pago"].to_numpy(dtype=np.float64) * taxa
    usd_ok = np.isfinite(usd)
    usd0 = np.where(usd_ok, usd, 0.0)
    logv = np.log1p(usd0)

    t = minuto[consulta]
    o = o_all[consulta]
    d = d_all[consulta]
    X: Dict[str, np.ndarray] = {}
    X["log_valor_usd"] = np.where(usd_ok[consulta], logv[consulta], np.nan)
    X["sem_taxa_cambio"] = (~usd_ok[consulta]).astype(np.float32)
    X["moeda_diferente"] = (
        trans["moeda_pagamento"].astype(str).to_numpy()[consulta]
        != trans["moeda_recebimento"].astype(str).to_numpy()[consulta]
    ).astype(np.float32)
    X["mesmo_banco"] = (trans["banco_origem"].to_numpy()[consulta]
                        == trans["banco_destino"].to_numpy()[consulta]).astype(np.float32)
    X["auto_transferencia"] = (o == d).astype(np.float32)

    # Envios, indexados pela conta que envia.
    env = _IndiceEventos(o_all, minuto, {"usd": usd0, "log": logv, "log2": logv * logv})
    for horas in (6, 24, 72):
        lo, hi = env.limites(o, t, horas * 60)
        X[f"n_env_origem_{horas}h"] = (hi - lo).astype(np.float32)
        if horas == 24:
            X["soma_env_origem_usd_24h"] = env.soma("usd", lo, hi)
    lo, hi = env.limites(o, t, None)
    n_prev = (hi - lo).astype(np.float64)
    X["n_env_origem_total"] = n_prev
    with np.errstate(invalid="ignore", divide="ignore"):
        media = env.soma("log", lo, hi) / n_prev
        var = np.maximum(env.soma("log2", lo, hi) / n_prev - media ** 2, 0.0)
        z = (logv[consulta] - media) / np.sqrt(var + 1e-6)
    X["z_valor_origem"] = np.where(n_prev >= 2, z, 0.0)
    X["min_desde_env_origem"] = env.minutos_desde_ultimo(o, t)
    lo, hi = env.limites(d, t, 24 * 60)
    X["n_env_destino_24h"] = (hi - lo).astype(np.float32)
    del env

    # Recebimentos, indexados pela conta que recebe.
    rec = _IndiceEventos(d_all, minuto, {"usd": usd0})
    lo, hi = rec.limites(o, t, 24 * 60)
    X["n_rec_origem_24h"] = (hi - lo).astype(np.float32)
    soma_rec_o = rec.soma("usd", lo, hi)
    X["soma_rec_origem_usd_24h"] = soma_rec_o
    X["razao_saida_entrada_24h"] = X["soma_env_origem_usd_24h"] / (soma_rec_o + 1.0)
    X["min_desde_rec_origem"] = rec.minutos_desde_ultimo(o, t)
    for horas in (24, 72):
        lo, hi = rec.limites(d, t, horas * 60)
        X[f"n_rec_destino_{horas}h"] = (hi - lo).astype(np.float32)
    X["min_desde_rec_destino"] = rec.minutos_desde_ultimo(d, t)
    del rec

    # Pares origem→destino: novidade e contrapartes distintas acumuladas.
    par, _ = pd.factorize(o_all * np.int64(1 << 31) + d_all)
    par = par.astype(np.int64)
    primeira = pd.Series(minuto).groupby(par).min()
    prim_par = primeira.to_numpy()          # índice = código do par (0..n-1)
    par_o = pd.Series(o_all).groupby(par).first().to_numpy()
    par_d = pd.Series(d_all).groupby(par).first().to_numpy()
    X["par_novo"] = (prim_par[par[consulta]] >= t).astype(np.float32)
    idx_par = _IndiceEventos(par, minuto)
    lo, hi = idx_par.limites(par[consulta], t, None)
    X["n_par_previas"] = (hi - lo).astype(np.float32)
    del idx_par
    distintos = _IndiceEventos(par_o, prim_par)
    lo, hi = distintos.limites(o, t, None)
    X["dest_distintos_origem"] = (hi - lo).astype(np.float32)
    distintos = _IndiceEventos(par_d, prim_par)
    lo, hi = distintos.limites(d, t, None)
    X["orig_distintas_destino"] = (hi - lo).astype(np.float32)
    del distintos

    for col in ("min_desde_env_origem", "min_desde_rec_origem", "min_desde_rec_destino"):
        v = X[col]
        X[f"sem_historico_{col[10:]}"] = np.isnan(v).astype(np.float32)
        X[col] = np.where(np.isnan(v), _SEM_HISTORICO_MIN, np.minimum(v, _SEM_HISTORICO_MIN))

    formato = trans["formato"].astype(str).to_numpy()[consulta]
    for f in prep.formatos:
        X[f"formato_{f}"] = (formato == f).astype(np.float32)
    moeda = trans["moeda_pagamento"].astype(str).to_numpy()[consulta]
    for m in prep.moedas:
        X[f"moeda_{m}"] = (moeda == m).astype(np.float32)

    saida = pd.DataFrame({k: np.asarray(v, dtype=np.float32) for k, v in X.items()})
    if prep.colunas:
        saida = saida.reindex(columns=prep.colunas, fill_value=np.float32(0))
    return saida


def montar_pipeline_financeiro(estimador: Any, linear: bool) -> Pipeline:
    passos: List[Tuple[str, Any]] = [("constantes", VarianceThreshold(0.0))]
    if linear:
        passos += [
            ("imputacao", SimpleImputer(strategy="median")),
            ("log", FunctionTransformer(log_com_sinal, feature_names_out="one-to-one")),
            ("escala", StandardScaler()),
        ]
    passos.append(("modelo", estimador))
    return Pipeline(passos).set_output(transform="pandas")


def amostrar_treino_financeiro(y: np.ndarray, fracao_negativos: float, semente: int) -> Tuple[np.ndarray, np.ndarray]:
    """Mantém todos os positivos e uma fração dos negativos DO TREINO.

    Returns:
        ``(indices, pesos)``: posições escolhidas e peso amostral (negativos
        recebem ``1/fracao`` para preservar a prevalência efetiva).
    """
    rng = np.random.default_rng(semente)
    pos = np.flatnonzero(y == 1)
    neg = np.flatnonzero(y == 0)
    if not 0 < fracao_negativos <= 1:
        raise ValueError("fracao_negativos_treino deve estar em (0, 1].")
    k = int(round(len(neg) * fracao_negativos))
    neg_esc = np.sort(rng.choice(neg, size=k, replace=False)) if k < len(neg) else neg
    idx = np.sort(np.concatenate([pos, neg_esc]))
    pesos = np.where(y[idx] == 1, 1.0, 1.0 / fracao_negativos)
    return idx, pesos
