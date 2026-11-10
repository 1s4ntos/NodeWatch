"""Efeito da correção das somas por conta no cálculo em lote (``atributos_financeiros``).

No teste do HI-Small (09 e 10/09/2022, 862.792 transações, histórico de 5,08 M),
compara a versão anterior do lote (``git show <ref>:src/ml/preparacao.py``) com
a corrigida:

* diferença dos 49 atributos;
* erro contra a força bruta em 300 linhas (as 200 de maior diferença e 100 sorteadas);
* scores e alertas do modelo atual, sem retreino;
* tempo de cálculo dos atributos.

Uso::

    python scripts/hi_large/b4_correcao_lote.py [--ref HEAD]
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

import numpy as np
from sklearn.metrics import average_precision_score

import comum
from src.ml.config import carregar_config
from src.ml.experimentos import _carregar_financeiro
from src.ml.modelos import ModeloUnificado
from src.ml.preparacao import atribuir_split_financeiro, atributos_financeiros
from testes.ml.referencia_financeira import atributos_referencia


def modulo_anterior(ref: str):
    fonte = subprocess.run(["git", "show", f"{ref}:src/ml/preparacao.py"], cwd=comum.RAIZ,
                           capture_output=True, text=True, encoding="utf-8", check=True).stdout
    pasta = comum.TRABALHO / "preparacao_anterior"
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / "preparacao_anterior.py"
    arq.write_text(fonte, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("preparacao_anterior", arq)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses procuram o módulo em sys.modules
    spec.loader.exec_module(mod)
    return mod


def erro_relativo(x: np.ndarray, r: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(x) & np.isfinite(r), np.abs(x - r) / np.maximum(np.abs(r), 1e-9), 0.0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", default="HEAD", help="versão git do cálculo anterior")
    a = ap.parse_args()
    saida: Dict[str, Any] = {"gerado_em_utc": comum.agora(), "script": Path(__file__).name,
                             "ref_anterior": a.ref, "ambiente": comum.ambiente(), "tempos": {}}
    anterior = modulo_anterior(a.ref)
    cfg = carregar_config()
    modelo = ModeloUnificado.carregar(comum.RAIZ / "artefatos_ml")
    cab, prep = modelo.cabeca("lavagem"), modelo.codificadores["financeiro"]
    dados, _, _, _ = _carregar_financeiro(cfg)
    t = dados.trans
    idx = np.flatnonzero(atribuir_split_financeiro(t["minuto"].to_numpy(), cfg["financeiro"]) == "teste")
    y = t["rotulo"].to_numpy()[idx]

    tempos = {"anterior": [], "corrigido": []}
    for rodada in range(2):
        for nome, f in (("anterior", anterior.atributos_financeiros), ("corrigido", atributos_financeiros)):
            t0 = time.perf_counter()
            X = f(t, idx, prep)[prep.colunas]
            tempos[nome].append(round(time.perf_counter() - t0, 2))
            if rodada == 0:
                if nome == "anterior":
                    Xa = X
                else:
                    Xc = X
    saida["tempos"]["atributos_teste_hismall_s"] = tempos

    A, C = Xa.to_numpy(dtype=np.float64), Xc.to_numpy(dtype=np.float64)
    rel = erro_relativo(A, C)
    saida["anterior_x_corrigido"] = {
        "linhas": int(len(idx)),
        "colunas_identicas": int(((A == C) | (np.isnan(A) & np.isnan(C))).all(axis=0).sum()),
        "linhas_com_diferenca_relativa_acima_1e6": {c: int((rel[:, i] > 1e-6).sum())
                                                     for i, c in enumerate(prep.colunas) if (rel[:, i] > 1e-6).any()},
        "maior_diferenca_relativa": {c: float(rel[:, i].max()) for i, c in enumerate(prep.colunas) if rel[:, i].max() > 0},
    }
    j = prep.colunas.index("razao_saida_entrada_24h")
    sel = np.unique(np.r_[np.argsort(-rel[:, j])[:200],
                          np.random.default_rng(comum.SEMENTE).choice(len(idx), 100, replace=False)])
    with comum.medir(saida["tempos"], "forca_bruta"):
        R = atributos_referencia(t, idx[sel], prep.cambio, prep.formatos, prep.moedas)[prep.colunas].to_numpy(dtype=np.float64)

    def maior(x):
        e = erro_relativo(x, R)
        return {c: float(e[:, i].max()) for i, c in enumerate(prep.colunas) if e[:, i].max() > 1e-6}

    saida["forca_bruta"] = {"linhas": int(len(sel)), "maior_erro_relativo_anterior": maior(A[sel]),
                            "maior_erro_relativo_corrigido": maior(C[sel]),
                            "leitura": "colunas omitidas têm erro relativo <= 1e-6"}

    sa = cab.probabilidades(Xa)[:, 1]
    sc = cab.probabilidades(Xc)[:, 1]
    lim = cab.limiar_alerta
    saida["modelo_atual"] = {
        "versao": cab.metadados.get("versao"), "limiar": lim,
        "maior_diferenca_de_score": float(np.abs(sa - sc).max()),
        "linhas_com_score_diferente": int((sa != sc).sum()),
        "alertas_anterior": int((sa >= lim).sum()), "alertas_corrigido": int((sc >= lim).sum()),
        "alertas_que_mudam_de_lado": int(((sa >= lim) != (sc >= lim)).sum()),
        "ap_anterior": float(average_precision_score(y, sa)), "ap_corrigido": float(average_precision_score(y, sc)),
        "aviso": "o teste do HI-Small já foi consultado; aqui só se mede o efeito da correção, sem escolher nada",
    }
    saida["pico_memoria_mb"] = comum.memoria_processo_mb()
    print(comum.salvar_json(saida, "b4_correcao_lote.json"))


if __name__ == "__main__":
    main()
