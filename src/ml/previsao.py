"""Inferência com o artefato salvo (nada é reajustado aqui).

As saídas preservam a identidade (``arquivo_origem``, ``linha_origem``) e a
ordem dos registros de entrada, e trazem ``tipo_saida = "previsao"``: uma
previsão nunca é apresentada como evento ou fraude confirmada.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from src.ml.avaliacao import psi
from src.ml.esquemas import CLASSES_REDE
from src.ml.ingestao import DadosHISmall, ler_hismall, ler_rede
from src.ml.preparacao import SENTINELAS_REDE, atributos_financeiros, matriz_rede

Caminho = Union[str, Path]
AVISO_LAVAGEM = (
    "Pontuação de lavagem aprendida no IBM AML HI-Small (sintético). Não é probabilidade "
    "nem confirmação de fraude; sem sinais de rede (nenhum vínculo disponível)."
)


def _deriva(X: pd.DataFrame, referencias: Dict[str, Any], sentinelas_treino: Dict[str, float]) -> Dict[str, Any]:
    saida: Dict[str, Any] = {"psi": {}, "taxa_sentinela": {}}
    for col, ref in referencias.items():
        if col in X:
            valores = X[col].to_numpy(dtype=float)
            sent = SENTINELAS_REDE.get(col)
            if sent is not None:
                valores = valores[valores != sent]
            saida["psi"][col] = psi(ref, valores)
    for col, taxa_treino in sentinelas_treino.items():
        if col in X:
            saida["taxa_sentinela"][col] = {
                "entrada": float((X[col] == SENTINELAS_REDE[col]).mean()), "treino": taxa_treino,
            }
    alto = {c: v for c, v in saida["psi"].items() if v is not None and v >= 0.25}
    saida["colunas_psi_acima_0_25"] = sorted(alto)
    saida["leitura"] = ("PSI >= 0,25 indica mudança relevante de distribuição em relação ao treino; "
                        "o desempenho medido no teste pode não valer para esta entrada.")
    return saida


def prever_rede(modelo, caminhos: Sequence[Caminho], tarefa: str = "estado_rede") -> Tuple[pd.DataFrame, Dict[str, Any]]:
    cab = modelo.cabeca(tarefa)
    exigir = ["classe_atual"] if cab.usa_classe_atual else []
    df, rel = ler_rede(list(caminhos), modo="inferencia", exigir=exigir)
    X = matriz_rede(df, cab.usa_classe_atual)
    proba = cab.probabilidades(X)
    classes = np.asarray(cab.classes, dtype=object)
    score = proba[:, classes.tolist().index("RISCO")] + proba[:, classes.tolist().index("FALHA")]
    saida = pd.DataFrame({
        "arquivo_origem": df["arquivo_origem"].to_numpy(),
        "linha_origem": df["linha_origem"].to_numpy(),
        "id_fluxo": df["id_fluxo"].to_numpy(),
        "anchor_id": df["anchor_id"].to_numpy(),
        "probe_id": df["probe_id"].to_numpy(),
        "timestamp_previsao": df["timestamp"].to_numpy(),
        "horizonte": "proxima_medicao",
        "classe_prevista": classes[np.argmax(proba, axis=1)],
    })
    for i, c in enumerate(classes):
        saida[f"prob_{c}"] = proba[:, i]
    saida["score_alerta_rede"] = score
    saida["alerta_rede"] = score >= cab.limiar_alerta
    saida["limiar_alerta"] = cab.limiar_alerta
    saida["versao_modelo"] = cab.metadados.get("versao", "")
    saida["modelo_rede_treinado_ate"] = cab.metadados.get("treinado_ate_utc", "")
    saida["tipo_saida"] = "previsao"
    relatorio = {
        "tarefa": tarefa,
        "ingestao": rel,
        "linhas_previstas": int(len(saida)),
        "cobertura": float(len(saida) / max(rel["linhas_lidas"], 1)),
        "rotulos_presentes": bool("alvo" in df),
        "deriva": _deriva(X, cab.metadados.get("referencia_psi", {}),
                          cab.metadados.get("taxa_sentinela_treino", {})),
    }
    return saida, relatorio


def _concatenar(historico: DadosHISmall, alvo: DadosHISmall) -> Tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Junta histórico + transações a pontuar com códigos de conta unificados."""
    nomes = np.concatenate([historico.nomes_contas, alvo.nomes_contas])
    codigos, unicos = pd.factorize(nomes)
    th = historico.trans.copy()
    ta = alvo.trans.copy()
    for col in ("conta_origem", "conta_destino"):
        th[col] = codigos[th[col].to_numpy()].astype(np.int32)
        ta[col] = codigos[len(historico.nomes_contas) + ta[col].to_numpy()].astype(np.int32)
    comb = pd.concat([th.drop(columns="rotulo", errors="ignore"),
                      ta.drop(columns="rotulo", errors="ignore")], ignore_index=True)
    for col in ("moeda_pagamento", "moeda_recebimento", "formato"):
        comb[col] = comb[col].astype(str)
    consulta = np.arange(len(th), len(comb))
    return comb, consulta, np.asarray(unicos, dtype=object)


def prever_lavagem(modelo, caminho: Caminho, historico: Optional[Caminho] = None,
                   lote: int = 500_000) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Pontua transações no formato HI-Small (rótulo opcional).

    Os atributos dependem do histórico das contas: forneça em ``historico``
    as transações anteriores (>= 72 h) ou aceite que as primeiras horas do
    arquivo tenham histórico incompleto (coluna ``historico_incompleto``).
    """
    cab = modelo.cabeca("lavagem")
    prep = modelo.codificadores["financeiro"]
    dados = ler_hismall(caminho, exigir_rotulo=False)
    if historico:
        # Só o que veio antes da primeira transação a pontuar: o histórico pode ser
        # o arquivo original completo sem duplicar nem antecipar transações.
        hist = ler_hismall(historico, exigir_rotulo=False)
        hist.trans = hist.trans.loc[hist.trans["minuto"] < dados.trans["minuto"].min()].reset_index(drop=True)
        trans, consulta, nomes = _concatenar(hist, dados)
    else:
        trans, consulta, nomes = dados.trans, np.arange(len(dados.trans)), dados.nomes_contas
    inicio_hist = int(trans["minuto"].min())
    scores, motivos = [], []
    for i in range(0, len(consulta), lote):
        q = consulta[i:i + lote]
        X = atributos_financeiros(trans, q, prep)
        s = cab.probabilidades(X)[:, list(cab.classes).index(1)]
        scores.append(s)
        m = np.asarray(prep.motivos(X, trans["formato"].iloc[q].reset_index(drop=True)), dtype=object)
        m[s < cab.limiar_alerta] = ""
        motivos.append(m)
    score = np.concatenate(scores) if scores else np.empty(0)
    t = trans.iloc[consulta]
    saida = pd.DataFrame({
        "arquivo_origem": Path(dados.arquivo).name,
        "linha_origem": dados.trans["id_transacao"].to_numpy(),
        "id_transacao": dados.trans["id_transacao"].astype(str).to_numpy(),
        "timestamp_transacao": pd.to_datetime(t["minuto"].to_numpy(), unit="m"),
        "conta_origem": nomes[t["conta_origem"].to_numpy()],
        "conta_destino": nomes[t["conta_destino"].to_numpy()],
        "valor_pago": t["valor_pago"].to_numpy(),
        "moeda_pagamento": t["moeda_pagamento"].astype(str).to_numpy(),
        "formato": t["formato"].astype(str).to_numpy(),
        "score_lavagem": score,
        "alerta_lavagem": score >= cab.limiar_alerta,
        "limiar_alerta": cab.limiar_alerta,
        "motivos_verificaveis": np.concatenate(motivos) if motivos else np.empty(0, dtype=object),
        "historico_incompleto": (t["minuto"].to_numpy() - inicio_hist) < 72 * 60,
        "sinais_utilizados": "financeiro",
        "cobertura_vinculo": "sem_vinculo",
        "pontuacao_fraude_financeira": "indisponivel",
        "versao_modelo": cab.metadados.get("versao", ""),
        "tipo_saida": "previsao",
    })
    relatorio = {
        "tarefa": "lavagem",
        "arquivo": dados.arquivo,
        "sha256": dados.sha256,
        "historico": str(historico) if historico else None,
        "linhas_previstas": int(len(saida)),
        "fracao_historico_incompleto": float(saida["historico_incompleto"].mean()) if len(saida) else None,
        "aviso": AVISO_LAVAGEM,
    }
    return saida, relatorio
