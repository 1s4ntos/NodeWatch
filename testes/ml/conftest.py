"""Dados sintéticos pequenos para os testes do módulo de ML."""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.ml.auditoria import regra_classe_atual
from src.ml.config import PADRAO
from src.ml.esquemas import FEATURES_REDE, SPLITS


def gerar_rede(n_fluxos: int = 6, por_split=(160, 50, 50), semente: int = 0) -> pd.DataFrame:
    """Telemetria sintética coerente com o esquema rede_v1.

    ``classe_atual`` segue a regra da auditoria e ``alvo`` é a classe_atual da
    medição seguinte, como no dataset real.
    """
    rng = np.random.default_rng(semente)
    linhas = []
    for f in range(n_fluxos):
        probe, anchor = 100 + f, 10 + f % 3
        t = 1_790_000_000 + 13 * f
        estado = 0.0
        for split, n in zip(SPLITS, por_split):
            t += 3_700
            for _ in range(n):
                t += 240 + int(rng.integers(-8, 9))
                estado = 0.85 * estado + rng.normal(0, 0.35)
                ruim = estado > 0.6
                perda = float(rng.choice([0.0, 33.3333, 100.0], p=[0.6, 0.3, 0.1])) if ruim else 0.0
                ausente = int(perda == 100.0)
                razao = -1.0 if ausente else float(np.clip(0.9 + 0.2 * estado + rng.normal(0, 0.05), 0.3, 5))
                linhas.append({
                    "id_fluxo": f"{probe}_{anchor}", "anchor_id": anchor, "probe_id": probe,
                    "timestamp": t, "split": split, "perda_pct": perda, "rtt_ausente": ausente,
                    "razao_rtt_p95": razao,
                    "razao_rtt_p99": -1.0 if ausente else razao * 0.93,
                    "razao_jitter_p95": -1.0 if ausente else float(abs(rng.normal(0.4 + 0.5 * ruim, 0.3))),
                    "amplitude_rtt_rel": -1.0 if ausente else float(abs(rng.normal(0.01, 0.01))),
                    "delta_ttl_clip": int(rng.choice([-2, -1, 0, 0, 0, 1, 2])),
                    "ttl_reset": 0,
                })
    df = pd.DataFrame(linhas)
    g = df.groupby("id_fluxo", sort=False)
    for k in (3, 6, 12):
        df[f"perda_media_w{k}"] = g["perda_pct"].transform(lambda s: s.rolling(k, min_periods=1).mean())
        rtt = g["razao_rtt_p95"].transform(lambda s: s.rolling(k, min_periods=1).max())
        df[f"rtt_p95_max_w{k}"] = rtt
        df[f"jitter_p95_max_w{k}"] = g["razao_jitter_p95"].transform(lambda s: s.rolling(k, min_periods=1).max())
        acima = (df["razao_rtt_p95"] > 1).astype(float)
        n = acima.groupby(df["id_fluxo"]).transform(lambda s: s.rolling(k, min_periods=1).sum())
        df[f"n_rtt_acima_p95_w{k}"] = np.where(rtt == -1, -1, n).astype(int)
    perda = (df["perda_pct"] > 0).astype(int)
    df["perdas_consecutivas"] = perda.groupby((perda == 0).cumsum()).cumsum().astype(int)
    df["classe_atual"] = regra_classe_atual(df)
    prox = df.groupby("id_fluxo")["classe_atual"].shift(-1)
    df["alvo"] = prox.fillna(df["classe_atual"])
    colunas = ["id_fluxo", "anchor_id", "probe_id", "timestamp", "split", "classe_atual",
               *FEATURES_REDE, "alvo"]
    return df[colunas]


def gerar_transacoes(n: int = 3_000, n_contas: int = 120, semente: int = 0) -> pd.DataFrame:
    """Transações no formato interno de ``DadosHISmall.trans``."""
    rng = np.random.default_rng(semente)
    minuto = np.sort(rng.integers(0, 6 * 1440, size=n)) + 27_000_000
    o = rng.integers(0, n_contas, size=n)
    d = rng.integers(0, n_contas, size=n)
    moedas = np.array(["US Dollar", "Euro", "Yen"])
    mp = moedas[rng.integers(0, 3, size=n)]
    troca = rng.random(n) < 0.2
    mr = np.where(troca, moedas[rng.integers(0, 3, size=n)], mp)
    taxa = {"US Dollar": 1.0, "Euro": 1.1, "Yen": 0.007}
    valor_pago = np.round(rng.lognormal(6, 1.5, size=n), 2)
    usd = valor_pago * np.vectorize(taxa.get)(mp)
    valor_rec = usd / np.vectorize(taxa.get)(mr)
    formato = np.array(["ACH", "Wire", "Cheque"])[rng.integers(0, 3, size=n)]
    rotulo = ((formato == "ACH") & (rng.random(n) < 0.1)).astype(np.int8)
    return pd.DataFrame({
        "id_transacao": np.arange(n, dtype=np.int64),
        "minuto": minuto.astype(np.int64),
        "banco_origem": (o % 5).astype(np.int32), "conta_origem": o.astype(np.int32),
        "banco_destino": (d % 5).astype(np.int32), "conta_destino": d.astype(np.int32),
        "valor_recebido": valor_rec, "moeda_recebimento": pd.Categorical(mr),
        "valor_pago": valor_pago, "moeda_pagamento": pd.Categorical(mp),
        "formato": pd.Categorical(formato), "rotulo": rotulo,
    })


@pytest.fixture
def csv_rede(tmp_path: Path) -> Path:
    caminho = tmp_path / "rede.csv"
    gerar_rede().to_csv(caminho, index=False)
    return caminho


@pytest.fixture
def cfg_rede(tmp_path: Path, csv_rede: Path) -> dict:
    cfg = copy.deepcopy(PADRAO)
    cfg["geral"]["pasta_artefatos"] = str(tmp_path / "artefatos")
    cfg["geral"]["n_jobs"] = 1
    cfg["rede"]["arquivos"] = [str(csv_rede)]
    cfg["rede"]["grade"] = "rapida"
    cfg["rede"]["folds_grupos"] = 2
    return cfg


def nomes_contas(n: int = 120) -> np.ndarray:
    """Nomes ``banco-conta`` para os códigos de :func:`gerar_transacoes` (banco = código % 5)."""
    return np.array([f"{i % 5}-C{i:04d}" for i in range(n)], dtype=object)


def transacoes_normalizadas(trans: pd.DataFrame, nomes: np.ndarray, prefixo: str = "") -> list:
    """Linhas de ``DadosHISmall.trans`` no formato de :func:`src.ml.eventos.normalizar_transacao`."""
    saida = []
    for r in trans.itertuples(index=False):
        t = float(r.minuto * 60)
        saida.append({
            "id_transacao": f"{prefixo}{int(r.id_transacao)}", "epoca": t, "minuto": int(r.minuto),
            "timestamp_disponivel": t, "banco_origem": str(int(r.banco_origem)),
            "banco_destino": str(int(r.banco_destino)), "conta_origem": str(nomes[r.conta_origem]),
            "conta_destino": str(nomes[r.conta_destino]), "valor_pago": float(r.valor_pago),
            "valor_recebido": float(r.valor_recebido), "moeda_pagamento": str(r.moeda_pagamento),
            "moeda_recebimento": str(r.moeda_recebimento), "formato": str(r.formato),
        })
    return saida


def gravar_hismall(trans: pd.DataFrame, nomes: np.ndarray, caminho: Path) -> Path:
    """Escreve transações sintéticas no formato do CSV original do HI-Small (sem rótulo)."""
    contas_o = [str(nomes[c]).split("-", 1) for c in trans["conta_origem"]]
    contas_d = [str(nomes[c]).split("-", 1) for c in trans["conta_destino"]]
    df = pd.DataFrame({
        "Timestamp": pd.to_datetime(trans["minuto"], unit="m").dt.strftime("%Y/%m/%d %H:%M"),
        "From Bank": [b for b, _ in contas_o], "Account": [c for _, c in contas_o],
        "To Bank": [b for b, _ in contas_d], "Account.1": [c for _, c in contas_d],
        "Amount Received": trans["valor_recebido"].round(2), "Receiving Currency": trans["moeda_recebimento"],
        "Amount Paid": trans["valor_pago"].round(2), "Payment Currency": trans["moeda_pagamento"],
        "Payment Format": trans["formato"],
    })
    texto = df.to_csv(index=False).replace("Account.1", "Account", 1)
    caminho.write_text(texto, encoding="utf-8")
    return caminho


@pytest.fixture(scope="session")
def modelo_minimo():
    """ModeloUnificado pequeno (florestas de 15 árvores) treinado em dados sintéticos.

    Serve só para testar o processamento de eventos: não é o modelo do projeto.
    """
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.pipeline import Pipeline

    from src.ml.esquemas import CLASSES_REDE
    from src.ml.modelos import CabecaClassificacao, ModeloUnificado
    from src.ml.preparacao import PreparadorFinanceiro, atributos_financeiros, matriz_rede

    rede = gerar_rede()
    Xr = matriz_rede(rede)
    rf_r = RandomForestClassifier(n_estimators=15, random_state=0, n_jobs=2).fit(Xr, rede["alvo"])
    cab_r = CabecaClassificacao("estado_rede", Pipeline([("modelo", rf_r)]), list(CLASSES_REDE), list(Xr.columns),
                                "random_forest", {}, 0.3,
                                metadados={"versao": "teste-rede", "treinado_ate_utc": "2020-01-01T00:00:00"})
    trans = gerar_transacoes()
    prep = PreparadorFinanceiro.ajustar(trans)
    Xf = atributos_financeiros(trans, np.arange(len(trans)), prep)
    prep.colunas = list(Xf.columns)
    prep.registrar_quantis(Xf)
    rf_f = RandomForestClassifier(n_estimators=15, random_state=0, n_jobs=2).fit(Xf, trans["rotulo"])
    cab_f = CabecaClassificacao("lavagem", Pipeline([("modelo", rf_f)]), [0, 1], list(Xf.columns),
                                "random_forest", {}, 0.2, metadados={"versao": "teste-lavagem"})
    modelo = ModeloUnificado()
    modelo.registrar("estado_rede", cab_r, "rede", None)
    modelo.registrar("lavagem", cab_f, "financeiro", prep)
    return modelo
