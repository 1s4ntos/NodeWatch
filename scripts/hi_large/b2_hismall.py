"""Atributos do HI-Small para as comparações com o HI-Large.

* ``hismall_treino_S.parquet``: a mesma amostra de treino do modelo atual
  (todos os positivos + 20% dos negativos, semente 42, peso 5), calculada
  pelo caminho em lote do NodeWatch com o preparador do artefato (P_S).
  Serve à fonte combinada S+L.
* ``hismall_teste_L.parquet``: o teste do HI-Small (09 e 10/09/2022, já
  consultado antes) com o preparador do HI-Large (P_L), para aplicar a ele os
  modelos treinados no HI-Large. Só é gerado se P_L existir.

Lê os caminhos do HI-Small no ``ml_config.local.toml``, como o NodeWatch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import joblib
import numpy as np

import comum
from src.ml.config import carregar_config
from src.ml.experimentos import _carregar_financeiro
from src.ml.modelos import ModeloUnificado
from src.ml.preparacao import amostrar_treino_financeiro, atribuir_split_financeiro, atributos_financeiros


def main() -> None:
    cfg = carregar_config()
    fin = cfg["financeiro"]
    saida: Dict[str, Any] = {"gerado_em_utc": comum.agora(), "script": Path(__file__).name,
                             "ambiente": comum.ambiente(), "tempos": {}}
    modelo = ModeloUnificado.carregar(comum.RAIZ / "artefatos_ml")
    ps = modelo.codificadores["financeiro"]
    with comum.medir(saida["tempos"], "leitura"):
        dados, _contas, casados, _pend = _carregar_financeiro(cfg)
    t = dados.trans
    y = t["rotulo"].to_numpy()
    split = atribuir_split_financeiro(t["minuto"].to_numpy(), fin)
    idx_tr = np.flatnonzero(split == "treino")
    rel, pesos = amostrar_treino_financeiro(y[idx_tr], fin["fracao_negativos_treino"], cfg["geral"]["semente"])
    consulta = idx_tr[rel]
    with comum.medir(saida["tempos"], "atributos_treino_S"):
        X = atributos_financeiros(t, consulta, ps)[ps.colunas]
    X["_rotulo"] = y[consulta].astype(np.int8)
    X["_peso"] = pesos.astype(np.float32)
    X["_formato"] = t["formato"].astype(str).to_numpy()[consulta]
    X.to_parquet(comum.TRABALHO / "hismall_treino_S.parquet", index=False)
    saida["treino_S"] = {"linhas": int(len(X)), "positivos": int(X["_rotulo"].sum()),
                         "sha256_hismall": dados.sha256}
    del X
    arq_pl = comum.TRABALHO / "preparador_L.joblib"
    if arq_pl.is_file():
        pl = joblib.load(arq_pl)
        idx_te = np.flatnonzero(split == "teste")
        with comum.medir(saida["tempos"], "atributos_teste_L"):
            X = atributos_financeiros(t, idx_te, pl)[pl.colunas]
        X["_rotulo"] = y[idx_te].astype(np.int8)
        X["_linha"] = t["id_transacao"].to_numpy()[idx_te]
        X["_dia"] = (t["minuto"].to_numpy()[idx_te] // 1440).astype(np.int32)
        X["_formato"] = t["formato"].astype(str).to_numpy()[idx_te]
        if casados is not None:
            tipo = casados.dropna(subset=["id_transacao"]).set_index("id_transacao")["tipo_padrao"]
            X["_tipo_padrao"] = X["_linha"].map(tipo).fillna("sem_padrao").astype(str)
        X.to_parquet(comum.TRABALHO / "hismall_teste_L.parquet", index=False)
        saida["teste_L"] = {"linhas": int(len(X)), "positivos": int(X["_rotulo"].sum())}
    saida["pico_memoria_mb"] = comum.memoria_processo_mb()
    print(comum.salvar_json(saida, "b2_hismall.json"))


if __name__ == "__main__":
    main()
