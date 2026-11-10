"""Equivalência em dados REAIS do HI-Large: estado incremental × cálculo em lote.

Recalcula, pelo caminho em lote do NodeWatch (``atributos_financeiros``, o
mesmo do treino), os atributos das transações do dia 2 (02/08/2022) gravadas
em ``atributos_S``, com os dias 1 e 2 como histórico, e compara com o que o
``EstadoFinanceiro`` gravou.

Cobre: arquivo fora de ordem (as partições vêm de um CSV não cronológico),
virada de dia (o estado atravessa a meia-noite) e tentativas que atravessam
dias (todos os positivos do dia entram na comparação). A ordem do arquivo
(``linha``) desempata o mesmo minuto nos dois caminhos.

Uso::

    python scripts/hi_large/b3_equivalencia.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

import comum
from src.ml.modelos import ModeloUnificado
from src.ml.preparacao import atributos_financeiros

PARTICOES = comum.TRABALHO / "particoes"


def main() -> None:
    saida: Dict[str, Any] = {"gerado_em_utc": comum.agora(), "script": Path(__file__).name,
                             "ambiente": comum.ambiente(), "tempos": {}}
    prep = ModeloUnificado.carregar(comum.RAIZ / "artefatos_ml").codificadores["financeiro"]
    with comum.medir(saida["tempos"], "leitura"):
        tab = pa.concat_tables([pq.read_table(PARTICOES / f"dia={d:03d}.parquet") for d in (0, 1)])
        tab = tab.take(pc.sort_indices(tab, [("linha", "ascending")]))  # ordem do arquivo
        n = tab.num_rows
        chaves = pa.concat_arrays([
            pc.binary_join_element_wise(pc.cast(tab["banco_origem"], pa.string()), tab["conta_origem"], "-").combine_chunks(),
            pc.binary_join_element_wise(pc.cast(tab["banco_destino"], pa.string()), tab["conta_destino"], "-").combine_chunks(),
        ]).dictionary_encode()
        cod = chaves.indices.to_numpy(zero_copy_only=False).astype(np.int32)
        del chaves

        def cat(col: str) -> pd.Categorical:
            d = tab[col].combine_chunks().dictionary_encode()
            return pd.Categorical.from_codes(d.indices.to_numpy(zero_copy_only=False).astype(np.int32),
                                             categories=pd.Index(d.dictionary.to_pylist(), dtype=str))

        trans = pd.DataFrame({
            "id_transacao": tab["linha"].to_numpy(), "minuto": tab["minuto"].to_numpy(),
            "banco_origem": tab["banco_origem"].to_numpy().astype(np.int64), "conta_origem": cod[:n],
            "banco_destino": tab["banco_destino"].to_numpy().astype(np.int64), "conta_destino": cod[n:],
            "valor_recebido": tab["valor_recebido"].to_numpy(), "moeda_recebimento": cat("moeda_recebimento"),
            "valor_pago": tab["valor_pago"].to_numpy(), "moeda_pagamento": cat("moeda_pagamento"),
            "formato": cat("formato"), "rotulo": tab["rotulo"].to_numpy(),
        })
        del tab
    gravado = pd.read_parquet(comum.TRABALHO / "atributos_S" / "dia=001.parquet")
    pos = pd.Index(trans["id_transacao"].to_numpy()).get_indexer(gravado["_linha"].to_numpy())
    if (pos < 0).any():
        raise SystemExit("linhas gravadas fora da partição")
    with comum.medir(saida["tempos"], "lote"):
        lote = atributos_financeiros(trans, pos, prep)[prep.colunas]
    obtido = gravado[prep.colunas]
    a = obtido.to_numpy(dtype=np.float64)
    b = lote.to_numpy(dtype=np.float64)
    iguais = (np.isnan(a) & np.isnan(b)) | np.isclose(a, b, rtol=1e-5, atol=1e-3)
    rel = np.where(np.isfinite(a) & np.isfinite(b), np.abs(a - b) / np.maximum(np.abs(b), 1e-9), 0.0)
    saida["comparacao"] = {
        "historico_transacoes": int(n), "linhas_comparadas": int(len(gravado)),
        "positivos_comparados": int(gravado["_rotulo"].sum()),
        "colunas": len(prep.colunas),
        "colunas_identicas_exatamente": int((a == b).all(axis=0).sum() + ((np.isnan(a) & np.isnan(b)) | (a == b)).all(axis=0).sum() - (a == b).all(axis=0).sum()),
        "linhas_divergentes_por_coluna_rtol_1e5_atol_1e3": {c: int((~iguais[:, i]).sum()) for i, c in enumerate(prep.colunas)
                                                             if (~iguais[:, i]).any()},
        "maior_diferenca_relativa_por_coluna": {c: float(rel[:, i].max()) for i, c in enumerate(prep.colunas) if rel[:, i].max() > 0},
        "tolerancia": "rtol 1e-5, atol 1e-3 (mesma de testes/ml/referencia_financeira.py)",
    }
    # Quem está certo onde diverge? Força bruta (testes/ml/referencia_financeira.py) em 300 linhas:
    # as 200 de maior diferença na razão saída/entrada e 100 sorteadas.
    from testes.ml.referencia_financeira import atributos_referencia
    j = prep.colunas.index("razao_saida_entrada_24h")
    piores = np.argsort(-rel[:, j])[:200]
    sorteadas = np.random.default_rng(comum.SEMENTE).choice(len(gravado), 100, replace=False)
    sel = np.unique(np.r_[piores, sorteadas])
    with comum.medir(saida["tempos"], "forca_bruta"):
        ref = atributos_referencia(trans, pos[sel], prep.cambio, prep.formatos, prep.moedas)[prep.colunas]
    r = ref.to_numpy(dtype=np.float64)

    def erro(x: np.ndarray) -> Dict[str, float]:
        e = np.where(np.isfinite(x) & np.isfinite(r), np.abs(x - r) / np.maximum(np.abs(r), 1e-9), 0.0)
        return {c: float(e[:, i].max()) for i, c in enumerate(prep.colunas) if e[:, i].max() > 1e-6}

    saida["forca_bruta"] = {
        "linhas": int(len(sel)),
        "maior_erro_relativo_incremental": erro(a[sel]),
        "maior_erro_relativo_lote": erro(b[sel]),
        "leitura": "colunas omitidas têm erro relativo <= 1e-6",
    }
    saida["pico_memoria_mb"] = comum.memoria_processo_mb()
    print(comum.salvar_json(saida, "b3_equivalencia.json"))


if __name__ == "__main__":
    main()
