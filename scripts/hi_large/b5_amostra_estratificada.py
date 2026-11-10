"""Conferência amostral e estratificada da correção do lote contra a força bruta.

Para cada conjunto, compara o lote ANTERIOR (``git show <ref>``), o lote
CORRIGIDO e, no HI-Large, o estado incremental (atributos gravados) com a
referência por força bruta (``testes/ml/referencia_financeira.py``), em quatro
estratos de 100 linhas (sementes fixas):

* ``divergia_antes``: maior diferença relativa entre o lote anterior e o corrigido na razão;
* ``acumulado_grande``: origens com a maior soma em USD já enviada antes do minuto;
* ``borda_de_janela``: a conta de origem tem evento exatamente em ``t - 1440``
  (início da janela de 24 h, incluído), em ``t - 1`` ou no próprio minuto ``t`` (excluído);
* ``sorteada``.

Conjuntos: HI-Large 02/08/2022 (dia de treino gravado, histórico 01 e 02/08,
entrada na ordem do arquivo, que não é cronológica); HI-Small treino (amostra
do modelo) e HI-Small teste (09 e 10/09/2022). No HI-Large, também confere o
lote corrigido contra o incremental em TODAS as linhas que divergiam antes.

Uso::

    python scripts/hi_large/b5_amostra_estratificada.py [--ref HEAD]
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

import comum
from b4_correcao_lote import erro_relativo, modulo_anterior
from src.ml.config import carregar_config
from src.ml.experimentos import _carregar_financeiro
from src.ml.modelos import ModeloUnificado
from src.ml.preparacao import amostrar_treino_financeiro, atribuir_split_financeiro, atributos_financeiros
from testes.ml.referencia_financeira import atributos_referencia

AFETADAS = ["soma_env_origem_usd_24h", "soma_rec_origem_usd_24h", "razao_saida_entrada_24h", "z_valor_origem"]


def trans_hilarge(dias) -> pd.DataFrame:
    tab = pa.concat_tables([pq.read_table(comum.TRABALHO / "particoes" / f"dia={d:03d}.parquet") for d in dias])
    tab = tab.take(pc.sort_indices(tab, [("linha", "ascending")]))  # ordem do arquivo (não cronológica)
    n = tab.num_rows
    chaves = pa.concat_arrays([
        pc.binary_join_element_wise(pc.cast(tab["banco_origem"], pa.string()), tab["conta_origem"], "-").combine_chunks(),
        pc.binary_join_element_wise(pc.cast(tab["banco_destino"], pa.string()), tab["conta_destino"], "-").combine_chunks(),
    ]).dictionary_encode()
    cod = chaves.indices.to_numpy(zero_copy_only=False).astype(np.int32)

    def cat(col):
        d = tab[col].combine_chunks().dictionary_encode()
        return pd.Categorical.from_codes(d.indices.to_numpy(zero_copy_only=False).astype(np.int32),
                                         categories=pd.Index(d.dictionary.to_pylist(), dtype=str))
    return pd.DataFrame({
        "id_transacao": tab["linha"].to_numpy(), "minuto": tab["minuto"].to_numpy(),
        "banco_origem": tab["banco_origem"].to_numpy(), "conta_origem": cod[:n],
        "banco_destino": tab["banco_destino"].to_numpy(), "conta_destino": cod[n:],
        "valor_recebido": tab["valor_recebido"].to_numpy(), "moeda_recebimento": cat("moeda_recebimento"),
        "valor_pago": tab["valor_pago"].to_numpy(), "moeda_pagamento": cat("moeda_pagamento"),
        "formato": cat("formato"), "rotulo": tab["rotulo"].to_numpy(),
    })


def estratos(t: pd.DataFrame, pos: np.ndarray, rel_razao: np.ndarray, prep, semente: int) -> Dict[str, np.ndarray]:
    rng = np.random.default_rng(semente)
    minuto = t["minuto"].to_numpy(np.int64)
    o_all = t["conta_origem"].to_numpy(np.int64)
    d_all = t["conta_destino"].to_numpy(np.int64)
    usd = t["valor_pago"].to_numpy(np.float64) * t["moeda_pagamento"].astype(str).map(prep.cambio).to_numpy(np.float64)
    usd = np.where(np.isfinite(usd), usd, 0.0)
    # Soma já enviada pela origem antes do minuto da consulta (só para escolher o estrato).
    env = pd.DataFrame({"o": o_all, "m": minuto, "v": usd}).groupby(["o", "m"], sort=True)["v"].sum()
    acum = env.groupby(level=0).cumsum() - env
    chave = pd.MultiIndex.from_arrays([o_all[pos], minuto[pos]])
    hist = acum.reindex(chave).to_numpy()
    # Eventos (envio ou recebimento) da conta de origem por minuto, como chaves inteiras ordenadas.
    def chave(c, m):
        return c.astype(np.int64) * (1 << 32) + m.astype(np.int64)
    ev = np.unique(np.r_[chave(o_all, minuto), chave(d_all, minuto)])

    def tem(k):
        i = np.searchsorted(ev, k)
        return (i < len(ev)) & (ev[np.minimum(i, len(ev) - 1)] == k)
    oq, tq = o_all[pos], minuto[pos]
    borda = tem(chave(oq, tq - 1440)) | tem(chave(oq, tq - 1))  # início exato da janela de 24 h; último minuto incluído
    # Mesmo minuto: outra transação da mesma origem no minuto t (excluída da janela por construção).
    k_env, n_env = np.unique(chave(o_all, minuto), return_counts=True)
    i = np.searchsorted(k_env, chave(oq, tq))
    borda |= n_env[np.minimum(i, len(k_env) - 1)] > 1
    n = len(pos)
    escolhidos: Dict[str, np.ndarray] = {}
    usados = np.zeros(n, dtype=bool)

    def pegar(nome, candidatos_ordenados):
        c = [i for i in candidatos_ordenados if not usados[i]][:100]
        usados[c] = True
        escolhidos[nome] = np.array(c, dtype=np.int64)

    pegar("divergia_antes", np.argsort(-rel_razao, kind="stable"))
    pegar("acumulado_grande", np.argsort(-np.nan_to_num(hist, nan=-1), kind="stable"))
    pegar("borda_de_janela", rng.permutation(np.flatnonzero(borda)))
    pegar("sorteada", rng.permutation(n))
    escolhidos["_contagem_borda_no_conjunto"] = np.array([int(borda.sum())])
    escolhidos["_hist_min_do_estrato_acumulado"] = np.array([float(np.nanmin(hist[escolhidos["acumulado_grande"]]))])
    return escolhidos


def conferir(nome: str, t: pd.DataFrame, pos: np.ndarray, prep, anterior, incremental=None) -> Dict[str, Any]:
    comum.log(f"{nome}: lote anterior e corrigido em {len(pos):,} linhas")
    A = anterior.atributos_financeiros(t, pos, prep)[prep.colunas].to_numpy(np.float64)
    C = atributos_financeiros(t, pos, prep)[prep.colunas].to_numpy(np.float64)
    j = prep.colunas.index("razao_saida_entrada_24h")
    rel_ac = erro_relativo(A, C)
    est = estratos(t, pos, rel_ac[:, j], prep, comum.SEMENTE)
    saida: Dict[str, Any] = {
        "linhas": int(len(pos)), "historico": int(len(t)),
        "fracao_da_entrada_fora_de_ordem": float((np.diff(t["minuto"].to_numpy()) < 0).mean()),
        "linhas_com_borda_de_janela": int(est.pop("_contagem_borda_no_conjunto")[0]),
        "menor_historico_enviado_no_estrato_acumulado_usd": float(est.pop("_hist_min_do_estrato_acumulado")[0]),
        "anterior_x_corrigido_linhas_divergentes": {c: int((rel_ac[:, i] > 1e-6).sum()) for i, c in enumerate(prep.colunas)
                                                    if (rel_ac[:, i] > 1e-6).any()},
        "estratos": {},
    }
    if incremental is not None:
        I = incremental[prep.colunas].to_numpy(np.float64)
        div_antes = (~np.isclose(A, I, rtol=1e-5, atol=1e-3) & ~(np.isnan(A) & np.isnan(I))).any(axis=1)
        ok_depois = (np.isclose(C, I, rtol=1e-5, atol=1e-3) | (np.isnan(C) & np.isnan(I))).all(axis=1)
        saida["incremental"] = {
            "linhas_que_divergiam_do_incremental_antes": int(div_antes.sum()),
            "dessas_iguais_ao_incremental_depois": int((div_antes & ok_depois).sum()),
            "linhas_divergentes_depois_no_total": int((~ok_depois).sum()),
            "maior_diferenca_relativa_corrigido_x_incremental": {
                c: float(erro_relativo(C[:, i:i + 1], I[:, i:i + 1]).max()) for i, c in enumerate(prep.colunas)
                if erro_relativo(C[:, i:i + 1], I[:, i:i + 1]).max() > 0},
        }
    for estrato, idx in est.items():
        R = atributos_referencia(t, pos[idx], prep.cambio, prep.formatos, prep.moedas)[prep.colunas].to_numpy(np.float64)
        def maior(X):
            e = erro_relativo(X[idx], R)
            return {c: float(e[:, i].max()) for i, c in enumerate(prep.colunas) if c in AFETADAS or e[:, i].max() > 1e-6}
        linha = {"linhas": int(len(idx)), "anterior": maior(A), "corrigido": maior(C)}
        if incremental is not None:
            linha["incremental"] = maior(I)
        saida["estratos"][estrato] = linha
        comum.log(f"  {estrato}: corrigido máx {max(linha['corrigido'].values()):.2e}; "
                  f"anterior máx {max(linha['anterior'].values()):.2e}")
    return saida


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", default="HEAD")
    a = ap.parse_args()
    anterior = modulo_anterior(a.ref)
    prep = ModeloUnificado.carregar(comum.RAIZ / "artefatos_ml").codificadores["financeiro"]
    saida: Dict[str, Any] = {"gerado_em_utc": comum.agora(), "script": Path(__file__).name, "ref_anterior": a.ref,
                             "ambiente": comum.ambiente(), "tolerancia": "erro relativo; <= 1e-6 é considerado igual",
                             "conjuntos": {}}
    # HI-Large: 02/08/2022, com o incremental gravado.
    t = trans_hilarge((0, 1))
    grav = pd.read_parquet(comum.TRABALHO / "atributos_S" / "dia=001.parquet")
    pos = pd.Index(t["id_transacao"].to_numpy()).get_indexer(grav["_linha"].to_numpy())
    saida["conjuntos"]["hilarge_02_08_treino"] = conferir("HI-Large 02/08", t, pos, prep, anterior, grav)
    del t, grav
    # HI-Small: amostra de treino do modelo e teste.
    cfg = carregar_config()
    dados, _, _, _ = _carregar_financeiro(cfg)
    t = dados.trans
    split = atribuir_split_financeiro(t["minuto"].to_numpy(), cfg["financeiro"])
    tr = np.flatnonzero(split == "treino")
    rel, _ = amostrar_treino_financeiro(t["rotulo"].to_numpy()[tr], cfg["financeiro"]["fracao_negativos_treino"],
                                        cfg["geral"]["semente"])
    saida["conjuntos"]["hismall_treino_amostra"] = conferir("HI-Small treino", t, tr[rel], prep, anterior)
    saida["conjuntos"]["hismall_teste"] = conferir("HI-Small teste", t, np.flatnonzero(split == "teste"), prep, anterior)
    saida["pico_memoria_mb"] = comum.memoria_processo_mb()
    print(comum.salvar_json(saida, "b5_amostra_estratificada.json"))


if __name__ == "__main__":
    main()
