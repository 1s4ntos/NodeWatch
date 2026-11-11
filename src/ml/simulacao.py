"""Laboratório de SIMULAÇÃO da integração rede ↔ transação.

Não existe, hoje, nenhum dado real que ligue transações a fluxos de rede. Este
laboratório verifica só a **integração técnica**: se vínculos e sinais de rede
são tratados com as regras de tempo corretas. Não mede qualidade preditiva.

O cenário é controlado:

* **rede** — medições reais de ``rede_teste_sem_rotulos.csv`` (três fluxos, uma
  hora), com seus instantes originais, pontuadas pelo modelo real;
* **transações** — SINTÉTICAS, de contas simuladas (banco ``990001``), criadas
  em instantes escolhidos em relação às medições. O score de lavagem delas
  não tem significado (contas sem histórico, fora do HI-Small);
* **vínculos** — declarados pelo próprio laboratório
  (``fonte_vinculo = "simulacao:laboratorio"``).

Cada caso tem um resultado esperado conhecido de antemão; o relatório compara
o esperado com o obtido. Nada aqui altera datas do HI-Small nem associa
transações reais à rede.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.ml import eventos as ev
from src.ml.ingestao import ler_rede
from src.ml.servico_eventos import Configuracao, ServicoEventos

ORIGEM = "simulacao:laboratorio"
AVISO = ("SIMULAÇÃO. Medições de rede reais; transações e vínculos sintéticos, criados pelo "
         "laboratório. Verifica a integração técnica (regras de tempo e de vínculo), não a "
         "capacidade preditiva. Os scores de lavagem das contas simuladas não têm significado.")


def _tx(ident: str, t: float, chave_tecnica: Optional[str] = None) -> Dict[str, Any]:
    dados = {
        "id_transacao": ident, "timestamp": t,
        "banco_origem": "990001", "conta_origem": f"SIMO{ident[-3:]}",
        "banco_destino": "990002", "conta_destino": f"SIMD{ident[-3:]}",
        "valor_pago": 1000.0, "moeda_pagamento": "US Dollar",
        "valor_recebido": 1000.0, "moeda_recebimento": "US Dollar", "formato": "ACH",
    }
    if chave_tecnica:
        dados["chave_tecnica"] = chave_tecnica
    return {"tipo": "transacao", "origem": ORIGEM, "modo": "simulacao", "dados": dados}


def _vinc(chave: str, tipo: str, fluxo: str, de: float, ate: float, declarado: float) -> Dict[str, Any]:
    return {"tipo": "vinculo", "origem": ORIGEM, "modo": "simulacao", "dados": {
        "chave": chave, "tipo_chave": tipo, "id_fluxo": fluxo, "valido_de": de, "valido_ate": ate,
        "fonte_vinculo": ORIGEM, "declarado_em": declarado}}


def montar_cenario(rede: pd.DataFrame, tolerancia_s: float) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Escolhe três fluxos e monta eventos + casos com o resultado esperado."""
    rede = rede.sort_values(["timestamp", "linha_origem"], kind="stable")
    t0 = int(rede["timestamp"].min()) + 3600
    janela = rede[(rede["timestamp"] >= t0) & (rede["timestamp"] < t0 + 3600)]
    contagem = janela.groupby("id_fluxo").size()
    fluxos = sorted(contagem[contagem >= 14].index)[:3]  # ~15 medições por hora (uma a cada ~240 s)
    if len(fluxos) < 3:
        raise ValueError("O arquivo de rede não tem três fluxos com medições suficientes na janela.")
    A, B, C = fluxos
    med = janela[janela["id_fluxo"].isin(fluxos)]
    ts = {f: med.loc[med["id_fluxo"] == f, "timestamp"].to_numpy(dtype=float) for f in fluxos}
    fim = t0 + 3600.0

    def ultimo_antes(f: str, t: float) -> float:
        anteriores = ts[f][ts[f] <= t]
        return float(anteriores.max()) if len(anteriores) else float("nan")

    eventos: List[Dict[str, Any]] = []
    for linha in med.drop(columns=["arquivo_origem", "linha_origem"]).to_dict("records"):
        eventos.append({"tipo": "medicao_rede", "origem": ORIGEM, "modo": "simulacao", "dados": linha})

    casos: List[Dict[str, Any]] = []

    def caso(ident: str, descricao: str, esperado: str, t: float, vinculos: List[Dict[str, Any]],
             chave_tecnica: Optional[str] = None, fluxo_sinal: Optional[str] = None) -> None:
        eventos.extend(vinculos)
        eventos.append(_tx(ident, t, chave_tecnica))
        sinal = ultimo_antes(fluxo_sinal, t) if fluxo_sinal else float("nan")
        casos.append({"id_transacao": ident, "descricao": descricao, "esperado": esperado,
                      "instante_utc": ev.iso(t), "sinal_esperado_em_utc": ev.iso(sinal) if sinal == sinal else None})

    a = ts[A]
    caso("sim-tx-001", f"Vínculo válido com {A}; medição {A} há 30 s", "com_sinal", a[5] + 30,
         [_vinc("sim-tx-001", "id_transacao", A, t0, fim, t0)], fluxo_sinal=A)
    caso("sim-tx-002", f"Vínculo válido com {A}, mas antes da primeira medição enviada do fluxo",
         "vinculo_sem_sinal_recente", a[0] - 120, [_vinc("sim-tx-002", "id_transacao", A, a[0] - 600, fim, a[0] - 600)])
    caso("sim-tx-003", "Vínculo vencido antes da transação", "sem_vinculo", a[8] + 30,
         [_vinc("sim-tx-003", "id_transacao", A, t0, a[8], t0)])
    caso("sim-tx-004", "Vínculo declarado 60 s depois da decisão (não pode ser usado)", "sem_vinculo", a[10] + 30,
         [_vinc("sim-tx-004", "id_transacao", A, t0, fim, a[10] + 90)])
    t5 = a[11] + 20
    while not (t5 - ultimo_antes(B, t5) <= tolerancia_s):
        t5 += 30
    caso("sim-tx-005", f"Sessão vinculada a {A} e {B}, ambos com sinal recente", "com_sinal_ambiguo", t5,
         [_vinc("sessao-lab-01", "chave_tecnica", A, t0, fim, t0),
          _vinc("sessao-lab-01", "chave_tecnica", B, t0, fim, t0)], chave_tecnica="sessao-lab-01")
    caso("sim-tx-006", f"Transação 5 s antes de uma medição de {A}: usa a anterior, nunca a futura",
         "com_sinal", a[13] - 5, [_vinc("sim-tx-006", "id_transacao", A, t0, fim, t0)], fluxo_sinal=A)
    c_ultimo = float(ts[C].max())
    caso("sim-tx-007", f"Última medição de {C} há mais de {int(tolerancia_s)} s", "vinculo_sem_sinal_recente",
         c_ultimo + tolerancia_s + 120, [_vinc("sim-tx-007", "id_transacao", C, t0, fim + 3600, t0)])
    caso("sim-tx-008", "Transação sem nenhum vínculo", "sem_vinculo", a[3] + 10, [])
    return eventos, casos


def rejeicoes_esperadas(t: float, fluxo: str) -> List[Tuple[str, Dict[str, Any], str]]:
    return [
        ("Conta bancária (banco-conta) usada como chave técnica", _vinc("990001-ABCDEF012", "chave_tecnica", fluxo,
                                                                         t, t + 3600, t), "invalido"),
        ("Medição com telemetria bruta (sem atributos rede_v1)",
         {"tipo": "medicao_rede", "origem": ORIGEM, "modo": "simulacao",
          "dados": {"id_fluxo": fluxo, "timestamp": int(t), "rtt_ms": 41.2, "jitter_ms": 3.1}}, "invalido"),
        ("Vínculo com validade invertida", _vinc("sim-tx-x", "id_transacao", fluxo, t + 10, t, t), "invalido"),
    ]


def executar_laboratorio(modelo, raiz: Path, arquivo_rede: Optional[Path] = None) -> Dict[str, Any]:
    raiz = Path(raiz)
    arquivo_rede = arquivo_rede or raiz / "artefatos_ml" / "exemplos" / "rede_teste_sem_rotulos.csv"
    pasta = raiz / "artefatos_ml" / "simulacao"
    rede, _ = ler_rede([arquivo_rede], modo="inferencia")
    rede = rede.drop(columns=[c for c in ("alvo", "split") if c in rede])
    cfg = Configuracao()
    servico = ServicoEventos(modelo, pasta, None, cfg, rotulo="_laboratorio")
    servico.descartar()
    eventos_brutos, casos = montar_cenario(rede, cfg.tolerancia_sinal_s)

    recebidos: List[ev.Evento] = []
    for b in eventos_brutos:
        ocorrido = b["dados"].get("declarado_em") or b["dados"].get("timestamp")
        e = ev.montar_evento(b, float(ocorrido), ORIGEM, "simulacao", servico.eh_conta)
        recebidos.append(e)
    recebidos.sort(key=lambda e: (e.ocorrido_em, e.tipo != "medicao_rede"))
    for e in recebidos:  # um por vez, na ordem do tempo simulado
        servico.processar([e], da_fila=False)
    servico.processar([ev.Evento("controle", "controle", "controle", "-", 0, 0, ORIGEM, "simulacao",
                                 {"acao": "fechar"})], da_fila=False)

    saida = servico.saidas["lavagem:simulacao"].caminho
    obtido = pd.read_csv(saida).set_index("id_transacao")
    for c in casos:
        linha = obtido.loc[c["id_transacao"]]
        c["obtido"] = linha["cobertura_vinculo"]
        c["ok"] = c["obtido"] == c["esperado"]
        c["n_fluxos_vinculados"] = int(linha["n_fluxos_vinculados"])
        idade = linha["idade_sinal_rede_s"]
        c["idade_sinal_s"] = None if pd.isna(idade) else float(idade)
        c["score_alerta_rede_vinculado"] = None if pd.isna(linha["score_alerta_rede_vinculado"]) else float(
            linha["score_alerta_rede_vinculado"])
        if c.get("sinal_esperado_em_utc") and c["idade_sinal_s"] is not None:
            esperado_idade = (pd.Timestamp(c["instante_utc"]) - pd.Timestamp(c["sinal_esperado_em_utc"])).total_seconds()
            c["idade_confere"] = abs(esperado_idade - c["idade_sinal_s"]) < 1e-6
            c["ok"] = c["ok"] and c["idade_confere"]

    # rejeições esperadas (pela validação de entrada) e regras de entrega
    t_ref = float(rede["timestamp"].min()) + 3600
    fluxo = str(rede["id_fluxo"].iloc[0])
    rejeicoes = []
    for descricao, bruto, esperado in rejeicoes_esperadas(t_ref, fluxo):
        try:
            ev.montar_evento(bruto, t_ref, ORIGEM, "simulacao", servico.eh_conta)
            obtido_r, detalhe = "aceito", ""
        except ev.ErroEvento as exc:
            obtido_r, detalhe = "invalido", "; ".join(exc.problemas)
        rejeicoes.append({"descricao": descricao, "esperado": esperado, "obtido": obtido_r,
                          "ok": obtido_r == esperado, "detalhe": detalhe})
    repetida = next(e for e in recebidos if e.tipo == "transacao")
    r = servico.estado.receber(dict(repetida.dados, _evento=repetida))
    rejeicoes.append({"descricao": "Mesma transação enviada de novo", "esperado": "duplicada",
                      "obtido": r.motivo if r else "aceito", "ok": bool(r and r.motivo == "duplicada"),
                      "detalhe": r.detalhe if r else ""})
    atrasada = dict(repetida.dados, id_transacao="sim-tx-atrasada", _evento=repetida)
    r = servico.estado.receber(atrasada)
    rejeicoes.append({"descricao": "Transação nova de um minuto já fechado", "esperado": "atrasada",
                      "obtido": r.motivo if r else "aceito", "ok": bool(r and r.motivo == "atrasada"),
                      "detalhe": r.detalhe if r else ""})

    relatorio = {
        "aviso": AVISO,
        "gerado_em": ev.iso(ev.agora()),
        "arquivo_rede": Path(arquivo_rede).name,
        "tolerancia_sinal_s": cfg.tolerancia_sinal_s,
        "casos": casos,
        "rejeicoes": rejeicoes,
        "todos_ok": all(c["ok"] for c in casos) and all(r["ok"] for r in rejeicoes),
        "medicoes_de_rede": int(sum(e.tipo == "medicao_rede" for e in recebidos)),
        "saidas": [s.caminho.name for s in servico.saidas.values()],
        "conclusao": {
            "integracao_tecnica": "verificada neste cenário" if all(c["ok"] for c in casos) else "com divergências",
            "cenario_simulado": "sim — transações e vínculos sintéticos",
            "validacao_preditiva": "pendente: não há transações reais vinculadas a fluxos de rede",
        },
    }
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "laboratorio.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=1, default=str),
                                            encoding="utf-8")
    return relatorio
