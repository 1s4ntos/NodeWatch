"""Configuração dos experimentos de ML.

A configuração vem de um arquivo TOML (``ml_config.local.toml`` na raiz do
projeto, se existir; senão ``ml_config.exemplo.toml``), sobreposto aos valores
padrão deste módulo. Caminhos relativos são resolvidos a partir da pasta do
arquivo de configuração.

Os valores padrão abaixo são os usados no treino documentado em
``docs/ml/RELATORIO_ML.md``; mudar qualquer um deles muda o experimento e deve
ser registrado.
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any, Dict, Optional, Union

RAIZ_PROJETO = Path(__file__).resolve().parents[2]

PADRAO: Dict[str, Any] = {
    "geral": {
        "semente": 42,
        "pasta_artefatos": "artefatos_ml",
        "pasta_docs": "docs/ml",
        # Limita processos paralelos: o RandomForest replica dados por processo.
        "n_jobs": 4,
    },
    "rede": {
        # Um ou mais CSVs no formato rede_v1.
        "arquivos": [],
        # Duplicatas por id_fluxo+timestamp com valores diferentes: "erro" ou "excluir".
        "conflitos": "erro",
        # Dois registros do mesmo fluxo são "consecutivos" se o intervalo for no
        # máximo este múltiplo da mediana dos intervalos do treino.
        "multiplo_intervalo_consecutivo": 2.0,
        # Grade de configurações: "completa" (relatório) ou "rapida" (testes).
        "grade": "completa",
        "folds_grupos": 5,
    },
    "financeiro": {
        "transacoes": "",          # HI-Small_Trans.csv ou .zip
        "contas": "",              # HI-Small_accounts.csv (opcional)
        "padroes": "",             # HI-Small_Patterns.txt (opcional, só auditoria/avaliação)
        # Divisão temporal por dia (limites exclusivos, horário dos dados).
        "inicio": "2022-09-01",
        "treino_ate": "2022-09-07",
        "validacao_ate": "2022-09-09",
        "teste_ate": "2022-09-11",
        # A partir desta data o gerador quase não produz atividade normal
        # (base de 58-73% de lavagem): é reportada à parte, fora das métricas.
        "inicio_cauda": "2022-09-11",
        # Fração de negativos do TREINO mantida no ajuste (com peso 1/fração).
        # Validação e teste nunca são subamostrados.
        "fracao_negativos_treino": 0.2,
        "grade": "completa",
        "tamanho_lote_previsao": 250_000,
    },
    "integracao": {
        # Tolerância do merge_asof entre transação e sinal de rede (segundos).
        "tolerancia_s": 480,
    },
}


def _mesclar(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    saida = copy.deepcopy(base)
    for chave, valor in extra.items():
        if isinstance(valor, dict) and isinstance(saida.get(chave), dict):
            saida[chave] = _mesclar(saida[chave], valor)
        else:
            saida[chave] = valor
    return saida


def localizar_config(caminho: Optional[Union[str, Path]] = None) -> Optional[Path]:
    """Devolve o arquivo de configuração a usar (ou ``None`` se não houver)."""
    if caminho:
        p = Path(caminho)
        if not p.is_file():
            raise FileNotFoundError(f"Arquivo de configuração não encontrado: {p}")
        return p
    for nome in ("ml_config.local.toml", "ml_config.exemplo.toml"):
        p = RAIZ_PROJETO / nome
        if p.is_file():
            return p
    return None


def carregar_config(caminho: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Carrega a configuração (padrões + TOML) com caminhos já resolvidos."""
    arquivo = localizar_config(caminho)
    cfg = copy.deepcopy(PADRAO)
    base = RAIZ_PROJETO
    if arquivo is not None:
        with arquivo.open("rb") as fh:
            cfg = _mesclar(cfg, tomllib.load(fh))
        base = arquivo.resolve().parent
    cfg["_arquivo_config"] = str(arquivo) if arquivo else None

    def resolver(valor: str) -> str:
        if not valor:
            return valor
        p = Path(valor)
        return str(p if p.is_absolute() else (base / p).resolve())

    cfg["geral"]["pasta_artefatos"] = resolver(cfg["geral"]["pasta_artefatos"])
    cfg["geral"]["pasta_docs"] = resolver(cfg["geral"]["pasta_docs"])
    cfg["rede"]["arquivos"] = [resolver(a) for a in cfg["rede"]["arquivos"]]
    for chave in ("transacoes", "contas", "padroes"):
        cfg["financeiro"][chave] = resolver(cfg["financeiro"][chave])
    return cfg


def pasta_artefatos(cfg: Dict[str, Any]) -> Path:
    p = Path(cfg["geral"]["pasta_artefatos"])
    p.mkdir(parents=True, exist_ok=True)
    return p
