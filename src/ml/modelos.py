"""Arquitetura única: codificadores por fonte, cabeças por tarefa.

``ModeloUnificado`` é o único artefato salvo. Ele reúne:

* ``codificadores`` — ``rede`` (preditores do esquema ``rede_v1``) e
  ``financeiro`` (:class:`~src.ml.preparacao.PreparadorFinanceiro`);
* ``cabecas`` — ``estado_rede`` (3 classes), ``lavagem`` (binária) e
  ``fusao_rede_transacao`` (bloqueada sem vínculo verificável).

As cabeças disponíveis hoje são treinadas e avaliadas separadamente, cada uma
nos seus próprios dados: as duas fontes não têm amostras em comum, então
nenhum componente compartilhado aprenderia a relação entre elas.

Segurança: arquivos ``joblib`` executam código ao serem carregados. Carregue
apenas artefatos gerados por você.
"""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from src.ml import VERSAO_MODULO
from src.ml.esquemas import CLASSES_REDE, ESQUEMAS

NOME_ARTEFATO = "modelo_unificado.joblib"


@dataclass
class Candidato:
    nome: str
    familia: str
    linear: bool
    params: Dict[str, Any]
    fabrica: Callable[[], Any]


def _lr(semente: int, **kw) -> Callable[[], Any]:
    return lambda: LogisticRegression(max_iter=3000, random_state=semente, **kw)


def _rf(semente: int, n_jobs: int, **kw) -> Callable[[], Any]:
    return lambda: RandomForestClassifier(random_state=semente, n_jobs=n_jobs, max_features="sqrt", **kw)


def _hgb(semente: int, **kw) -> Callable[[], Any]:
    return lambda: HistGradientBoostingClassifier(random_state=semente, early_stopping=False, **kw)


def recriar_estimador(familia: str, params: Dict[str, Any], semente: int, n_jobs: int) -> Any:
    """Novo estimador (não ajustado) com a configuração escolhida."""
    if familia == "logistica":
        return _lr(semente, **params)()
    if familia == "random_forest":
        return _rf(semente, n_jobs, **params)()
    if familia == "hist_gradient_boosting":
        return _hgb(semente, **params)()
    raise ValueError(f"família desconhecida: {familia}")


def _montar(familia: str, linear: bool, fabrica_de: Callable[..., Callable[[], Any]],
            params: Dict[str, Any], *args) -> Candidato:
    rotulo = ",".join(f"{k}={v}" for k, v in params.items())
    return Candidato(f"{familia}[{rotulo}]", familia, linear, params, fabrica_de(*args, **params))


def grade_rede(tipo: str, semente: int, n_jobs: int) -> List[Candidato]:
    """Busca pequena e documentada (treino → macro-F1 na validação)."""
    if tipo == "rapida":
        return [
            _montar("logistica", True, _lr, {"C": 1.0, "class_weight": None}, semente),
            _montar("hist_gradient_boosting", False, _hgb, {"max_iter": 30, "class_weight": None}, semente),
            _montar("random_forest", False, _rf, {"n_estimators": 10, "min_samples_leaf": 20,
                                                  "max_samples": 0.5, "class_weight": None}, semente, n_jobs),
        ]
    c: List[Candidato] = []
    for C in (0.1, 1.0):
        for cw in (None, "balanced"):
            c.append(_montar("logistica", True, _lr, {"C": C, "class_weight": cw}, semente))
    for folha in (20, 100):
        for cw in (None, "balanced_subsample"):
            c.append(_montar("random_forest", False, _rf, {
                "n_estimators": 150, "min_samples_leaf": folha, "max_samples": 0.5, "class_weight": cw,
            }, semente, n_jobs))
    for folhas in (31, 63):
        for cw in (None, "balanced"):
            c.append(_montar("hist_gradient_boosting", False, _hgb, {
                "max_iter": 200, "learning_rate": 0.1, "max_leaf_nodes": folhas, "class_weight": cw,
            }, semente))
    return c


def grade_financeira(tipo: str, semente: int, n_jobs: int) -> List[Candidato]:
    """Busca pequena (treino subamostrado com pesos → AP na validação)."""
    if tipo == "rapida":
        return [
            _montar("logistica", True, _lr, {"C": 1.0}, semente),
            _montar("hist_gradient_boosting", False, _hgb, {"max_iter": 30}, semente),
        ]
    c: List[Candidato] = []
    for C in (0.1, 1.0):
        c.append(_montar("logistica", True, _lr, {"C": C}, semente))
    c.append(_montar("random_forest", False, _rf, {
        "n_estimators": 100, "min_samples_leaf": 50, "max_samples": 0.5,
    }, semente, n_jobs))
    for folhas in (31, 63):
        c.append(_montar("hist_gradient_boosting", False, _hgb, {
            "max_iter": 300, "learning_rate": 0.1, "max_leaf_nodes": folhas, "l2_regularization": 1.0,
        }, semente))
    return c


# ---------------------------------------------------------------------------
# Cabeças
# ---------------------------------------------------------------------------
@dataclass
class CabecaClassificacao:
    """Uma tarefa supervisionada: pipeline ajustado + contrato de entrada/saída."""

    tarefa: str
    pipeline: Any
    classes: List[Any]
    colunas_entrada: List[str]
    familia: str
    params: Dict[str, Any]
    limiar_alerta: float
    usa_classe_atual: bool = False
    metadados: Dict[str, Any] = field(default_factory=dict)

    status: str = "treinada"

    def probabilidades(self, X: pd.DataFrame, lote: int = 250_000) -> np.ndarray:
        """Probabilidades na ordem de ``self.classes`` (lotes limitam a memória)."""
        if list(X.columns) != self.colunas_entrada:
            raise ValueError("Colunas de entrada diferentes das usadas no treino.")
        ordem_modelo = list(self.pipeline.classes_)
        idx = [ordem_modelo.index(c) for c in self.classes]
        partes = [self.pipeline.predict_proba(X.iloc[i:i + lote])[:, idx] for i in range(0, len(X), lote)]
        return np.vstack(partes) if partes else np.empty((0, len(self.classes)))


class FusaoIndisponivel(RuntimeError):
    """A fusão rede↔transação não pode ser treinada com os dados atuais."""

    def __init__(self, faltando: Sequence[str]):
        self.faltando = list(faltando)
        lista = "\n  - ".join(self.faltando)
        super().__init__(
            "A cabeça fusao_rede_transacao está indisponível. Entradas pendentes:\n  - " + lista
        )


@dataclass
class CabecaFusao:
    """Lugar reservado para o modelo financeiro com sinais de rede.

    Treinar exige transações com ``timestamp_disponivel``, uma tabela de
    vínculo válida no tempo, telemetria do mesmo período e rótulos com data de
    confirmação. Sem isso, :meth:`verificar_requisitos` lista o que falta e
    :meth:`treinar` levanta :class:`FusaoIndisponivel`.
    """

    tarefa: str = "fusao_rede_transacao"
    status: str = "indisponivel"
    motivo: str = (
        "Não há vínculo verificável entre as transações do HI-Small (setembro de 2022) e os "
        "fluxos de dataset_final.csv (setembro-outubro de 2026): não há chave comum nem "
        "sobreposição temporal."
    )
    requisitos: List[str] = field(default_factory=lambda: [
        "transações no esquema transacao_v1 com timestamp_disponivel",
        "tabela vinculo_v1 (transação ou chave técnica → id_fluxo, com validade e fonte documentada)",
        "telemetria rede_v1 do mesmo período das transações",
        "previsões de rede fora da amostra (modelo de rede treinado antes de cada transação)",
        "rotulo_fraude com origem_rotulo e timestamp_confirmacao",
    ])

    def verificar_requisitos(self, transacoes: Optional[pd.DataFrame] = None,
                             vinculo: Optional[pd.DataFrame] = None,
                             previsoes_rede: Optional[pd.DataFrame] = None) -> List[str]:
        faltando: List[str] = []
        if transacoes is None or "timestamp_disponivel" not in transacoes:
            faltando.append(self.requisitos[0])
        if vinculo is None or vinculo.empty:
            faltando.append(self.requisitos[1])
        if previsoes_rede is None or previsoes_rede.empty:
            faltando.append(self.requisitos[2])
        if previsoes_rede is None or "modelo_rede_treinado_ate" not in previsoes_rede:
            faltando.append(self.requisitos[3])
        if transacoes is None or not {"rotulo_fraude", "origem_rotulo", "timestamp_confirmacao"} <= set(transacoes):
            faltando.append(self.requisitos[4])
        return faltando

    def treinar(self, transacoes: Optional[pd.DataFrame] = None,
                vinculo: Optional[pd.DataFrame] = None,
                previsoes_rede: Optional[pd.DataFrame] = None) -> None:
        faltando = self.verificar_requisitos(transacoes, vinculo, previsoes_rede)
        if faltando:
            raise FusaoIndisponivel(faltando)
        raise NotImplementedError(
            "Com dados vinculados disponíveis: gerar atributos financeiros, anexar sinais de rede "
            "com src.ml.integracao.associar_sinais_rede e comparar, na mesma divisão temporal, o "
            "modelo financeiro com e sem esses sinais."
        )


# ---------------------------------------------------------------------------
# Modelo unificado
# ---------------------------------------------------------------------------
def versoes() -> Dict[str, str]:
    return {
        "modulo_ml": VERSAO_MODULO,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scikit-learn": sklearn.__version__,
        "joblib": joblib.__version__,
    }


@dataclass
class ModeloUnificado:
    codificadores: Dict[str, Any] = field(default_factory=dict)
    cabecas: Dict[str, Any] = field(default_factory=lambda: {"fusao_rede_transacao": CabecaFusao()})
    metadados: Dict[str, Any] = field(default_factory=dict)

    def tarefas_disponiveis(self) -> Dict[str, str]:
        return {nome: getattr(c, "status", "desconhecido") for nome, c in self.cabecas.items()}

    def cabeca(self, tarefa: str) -> Any:
        if tarefa not in self.cabecas:
            raise KeyError(f"Tarefa '{tarefa}' não treinada. Disponíveis: {self.tarefas_disponiveis()}")
        c = self.cabecas[tarefa]
        if getattr(c, "status", "") != "treinada":
            if isinstance(c, CabecaFusao):
                raise FusaoIndisponivel(c.requisitos)
            raise RuntimeError(f"Tarefa '{tarefa}' com status {c.status}.")
        return c

    def registrar(self, tarefa: str, cabeca: Any, codificador_nome: str, codificador: Any) -> None:
        self.cabecas[tarefa] = cabeca
        self.codificadores[codificador_nome] = codificador
        self.metadados.setdefault("historico", []).append({
            "tarefa": tarefa, "registrada_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    def prever(self, tarefa: str, *args, **kwargs):
        from src.ml import previsao
        if tarefa.startswith("estado_rede"):
            return previsao.prever_rede(self, *args, tarefa=tarefa, **kwargs)
        if tarefa == "lavagem":
            return previsao.prever_lavagem(self, *args, **kwargs)
        self.cabeca(tarefa)  # levanta o erro adequado
        raise KeyError(tarefa)

    # ------------------------------------------------------------------
    def salvar(self, pasta: Path) -> Path:
        pasta = Path(pasta)
        pasta.mkdir(parents=True, exist_ok=True)
        self.metadados["versoes"] = versoes()
        self.metadados["salvo_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        destino = pasta / NOME_ARTEFATO
        joblib.dump(self, destino, compress=3)
        resumo = {
            "artefato": NOME_ARTEFATO,
            "tarefas": self.tarefas_disponiveis(),
            "metadados": self.metadados,
            "cabecas": {
                nome: (
                    {"familia": c.familia, "params": c.params, "classes": [str(x) for x in c.classes],
                     "colunas_entrada": c.colunas_entrada, "limiar_alerta": c.limiar_alerta,
                     "usa_classe_atual": c.usa_classe_atual, "metadados": c.metadados}
                    if isinstance(c, CabecaClassificacao)
                    else {"status": c.status, "motivo": c.motivo, "requisitos": c.requisitos}
                )
                for nome, c in self.cabecas.items()
            },
        }
        (pasta / "metadados_modelo.json").write_text(
            json.dumps(resumo, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        pasta_esq = pasta / "esquemas"
        pasta_esq.mkdir(exist_ok=True)
        for nome, esq in ESQUEMAS.items():
            (pasta_esq / f"{nome}.json").write_text(
                json.dumps(esq.para_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return destino

    @staticmethod
    def carregar(pasta: Path) -> "ModeloUnificado":
        caminho = Path(pasta) / NOME_ARTEFATO
        if not caminho.is_file():
            raise FileNotFoundError(f"Artefato não encontrado: {caminho}. Rode 'treinar' antes.")
        modelo = joblib.load(caminho)
        if not isinstance(modelo, ModeloUnificado):
            raise TypeError(f"{caminho} não contém um ModeloUnificado.")
        salvo = modelo.metadados.get("versoes", {}).get("scikit-learn")
        if salvo and salvo != sklearn.__version__:
            import warnings
            warnings.warn(f"Artefato salvo com scikit-learn {salvo}; ambiente atual {sklearn.__version__}.")
        return modelo

    @staticmethod
    def carregar_ou_novo(pasta: Path) -> "ModeloUnificado":
        try:
            return ModeloUnificado.carregar(pasta)
        except FileNotFoundError:
            return ModeloUnificado()


def baseline_majoritaria(y_treino: Sequence) -> DummyClassifier:
    return DummyClassifier(strategy="most_frequent").fit(np.zeros((len(y_treino), 1)), y_treino)


def proba_persistencia(classe_atual: Sequence, classes: Sequence[str] = CLASSES_REDE) -> np.ndarray:
    c = np.asarray(classe_atual, dtype=object)
    return np.stack([(c == k).astype(float) for k in classes], axis=1)
