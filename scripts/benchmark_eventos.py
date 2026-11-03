"""Benchmark do processamento de eventos (rede e financeiro incremental).

Uso (da raiz do projeto, com o servidor PARADO para não disputar CPU)::

    python scripts/benchmark_eventos.py            # completo (~10 min; lê o HI-Small inteiro)
    python scripts/benchmark_eventos.py --rapido   # menos repetições e amostra menor

Requer o artefato treinado (``artefatos_ml/modelo_unificado.joblib``), os
exemplos (``python -m src.ml.cli exemplos``) e, para a parte financeira com
histórico, ``[financeiro].transacoes`` em ``ml_config.local.toml``.

Mede, nesta máquina:

* carga do modelo (processo novo vs. já carregado) e a primeira previsão;
* rede: latência de uma medição e de lotes pequenos, ponta a ponta pelo
  serviço (chegada → previsão gravada) e vazão máxima do trabalhador;
* financeiro: carga inicial do histórico, atributos incrementais por minuto,
  vazão, memória e crescimento do estado, instantâneo (gravar/restaurar);
* equivalência no dia 10/09/2022: incremental vs. lote vs. força bruta
  (inclui ``razao_saida_entrada_24h``) e o efeito nos scores e alertas;
* o custo do caminho antigo: recalcular os atributos de UMA transação nova
  relendo o histórico inteiro.

Nada é treinado nem ajustado: o dia 10/09 pertence ao período de teste e é
usado só para medir tempo e equivalência numérica, nunca para escolher
parâmetros. Grava ``artefatos_ml/benchmark/benchmark_eventos.json`` e
``docs/ml/BENCHMARK_EVENTOS.md``.
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.ml import eventos as ev  # noqa: E402
from src.ml.config import carregar_config  # noqa: E402
from src.ml.incremental import EstadoFinanceiro  # noqa: E402
from src.ml.ingestao import ler_hismall, ler_rede  # noqa: E402
from src.ml.modelos import ModeloUnificado  # noqa: E402
from src.ml.preparacao import atributos_financeiros  # noqa: E402
from src.ml.previsao import _concatenar, pontuar_lavagem, tabela_previsoes_rede  # noqa: E402
from src.ml.servico_eventos import Configuracao, ServicoEventos  # noqa: E402

ARTEFATOS = RAIZ / "artefatos_ml"
EXEMPLOS = ARTEFATOS / "exemplos"


# ---------------------------------------------------------------------------
def memoria_mb() -> Dict[str, float]:
    """Memória do processo (Windows: working set; outros: pico de RSS)."""
    if os.name == "nt":
        class _PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        atual = ctypes.windll.kernel32.GetCurrentProcess
        atual.restype = ctypes.c_void_p  # pseudo-handle -1: sem restype, chega truncado em 64 bits
        info = ctypes.windll.psapi.GetProcessMemoryInfo
        info.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PMC), ctypes.c_ulong]
        if not info(atual(), ctypes.byref(pmc), pmc.cb):
            return {"atual_mb": None, "pico_mb": None}
        return {"atual_mb": pmc.WorkingSetSize / 2**20, "pico_mb": pmc.PeakWorkingSetSize / 2**20}
    import resource
    pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (2**20 if sys.platform == "darwin" else 2**10)
    return {"atual_mb": None, "pico_mb": pico}


def percentis(valores) -> Dict[str, Any]:
    a = np.asarray(list(valores), dtype=float)
    if not a.size:
        return {"n": 0}
    return {"n": int(a.size), "p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)),
            "p99": float(np.percentile(a, 99)), "max": float(a.max()), "media": float(a.mean())}


def cronometro(func, *args, **kwargs):
    t = time.perf_counter()
    r = func(*args, **kwargs)
    return r, (time.perf_counter() - t) * 1000


def etapa(nome: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {nome}", flush=True)


# ---------------------------------------------------------------------------
def bench_modelo(rapido: bool) -> Dict[str, Any]:
    etapa("modelo: carga em processo novo")
    codigo = ("import time,sys; sys.path.insert(0, r'%s'); t=time.perf_counter(); "
              "from src.ml.modelos import ModeloUnificado; from pathlib import Path; "
              "ModeloUnificado.carregar(Path(r'%s')); print((time.perf_counter()-t)*1000)") % (RAIZ, ARTEFATOS)
    frio = []
    for _ in range(2 if rapido else 3):
        r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, check=True)
        frio.append(float(r.stdout.strip().splitlines()[-1]))
    modelo, quente = cronometro(ModeloUnificado.carregar, ARTEFATOS)
    _, quente2 = cronometro(ModeloUnificado.carregar, ARTEFATOS)
    return {"processo_novo_ms": percentis(frio),
            "leitura_no_mesmo_processo_ms": [quente, quente2],
            "artefato_mb": (ARTEFATOS / "modelo_unificado.joblib").stat().st_size / 2**20,
            "leitura": "processo novo inclui importar pandas/scikit-learn; no mesmo processo é só a leitura do joblib"}, modelo


def bench_rede(modelo, rapido: bool) -> Dict[str, Any]:
    etapa("rede: latência de inferência direta")
    cab = modelo.cabeca("estado_rede")
    df, _ = ler_rede([EXEMPLOS / "rede_teste_sem_rotulos.csv"], modo="inferencia")
    df = df.drop(columns=[c for c in ("alvo", "split") if c in df])
    rng = np.random.default_rng(0)
    _, primeira = cronometro(tabela_previsoes_rede, cab, df.iloc[[0]])
    n = 150 if rapido else 400
    uma = [cronometro(tabela_previsoes_rede, cab, df.iloc[[int(i)]])[1] for i in rng.integers(0, len(df), n)]
    lotes = {}
    for tam in (10, 100, 1000):
        tempos = []
        for _ in range(10 if rapido else 30):
            ini = int(rng.integers(0, len(df) - tam))
            tempos.append(cronometro(tabela_previsoes_rede, cab, df.iloc[ini:ini + tam])[1])
        p = percentis(tempos)
        p["linhas_por_s_p50"] = tam / (p["p50"] / 1000)
        lotes[str(tam)] = p
    # só o modelo (sem montar a tabela de saída)
    from src.ml.preparacao import matriz_rede
    X1 = matriz_rede(df.iloc[[0]])
    so_modelo = [cronometro(cab.probabilidades, X1)[1] for _ in range(n)]

    etapa("rede: ponta a ponta pelo serviço (carga baixa)")
    with tempfile.TemporaryDirectory() as tmp:
        s = ServicoEventos(modelo, Path(tmp) / "p", None, Configuracao())
        s.iniciar()
        registros = df.to_dict("records")
        for i in range(n):
            linha = {k: v for k, v in registros[i].items() if k not in ("arquivo_origem", "linha_origem")}
            s.submeter([{"tipo": "medicao_rede", "dados": linha}])
            s.esperar_fila_vazia(10)
        baixa = list(s.latencias["rede"])
        s.parar(salvar=False)

    etapa("rede: vazão máxima do trabalhador")
    with tempfile.TemporaryDirectory() as tmp:
        s = ServicoEventos(modelo, Path(tmp) / "p", None, Configuracao(capacidade_fila=50_000))
        evs = []
        agora = ev.agora()
        for i, d in enumerate(df.drop(columns=["arquivo_origem", "linha_origem"]).to_dict("records")):
            d["timestamp"] = int(d["timestamp"])
            nat = f"rede:{d['id_fluxo']}@{d['timestamp']}"
            evs.append(ev.Evento(nat, nat, "medicao_rede", "rede_v1", float(d["timestamp"]), agora, "bench",
                                 "replay_historico", d, sequencia=i))
        t = time.perf_counter()
        s.iniciar()
        for e in evs:
            e.recebido_em = ev.agora()
            s.enfileirar(e)
        s.esperar_fila_vazia(600)
        dur = time.perf_counter() - t
        sob_carga = list(s.latencias["rede"])
        s.parar(salvar=False)
    return {
        "primeira_previsao_ms": primeira,
        "uma_medicao_ms": percentis(uma),
        "uma_medicao_so_modelo_ms": percentis(so_modelo),
        "lotes_ms": lotes,
        "servico_carga_baixa_ms": percentis(baixa),
        "servico_vazao_maxima": {"eventos": len(evs), "segundos": dur, "eventos_por_s": len(evs) / dur,
                                 "latencia_ms_ultimas_5000": percentis(sob_carga)},
        "leitura": ("uma_medicao inclui montar a tabela de saída; servico_carga_baixa é chegada → previsão "
                    "gravada, enviando uma medição por vez; na vazão máxima a latência inclui a espera na fila"),
    }


# ---------------------------------------------------------------------------
def bench_financeiro(modelo, rapido: bool) -> Dict[str, Any]:
    cab, prep = modelo.cabeca("lavagem"), modelo.codificadores["financeiro"]
    cfg = carregar_config()
    zip_hist = cfg["financeiro"].get("transacoes")
    if not zip_hist or not Path(zip_hist).is_file():
        return {"pulado": "sem [financeiro].transacoes em ml_config.local.toml"}
    saida: Dict[str, Any] = {"memoria_inicio": memoria_mb()}

    etapa("financeiro: leitura do dia e do histórico")
    dia, t_dia = cronometro(ler_hismall, EXEMPLOS / "hismall_2022-09-10_sem_rotulo.csv", exigir_rotulo=False)
    hist, t_hist = cronometro(ler_hismall, zip_hist, exigir_rotulo=False)
    primeiro = int(dia.trans["minuto"].min())
    hist.trans = hist.trans.loc[hist.trans["minuto"] < primeiro].reset_index(drop=True)
    saida["leitura_ms"] = {"dia": t_dia, "historico_zip": t_hist}
    saida["transacoes_historico"] = int(len(hist.trans))
    saida["transacoes_dia"] = int(len(dia.trans))

    etapa("financeiro: carga inicial do estado")
    gc.collect()
    m0 = memoria_mb()
    estado = EstadoFinanceiro(prep)
    _, t_carga = cronometro(estado.carregar_historico, hist.trans, hist.nomes_contas, "HI-Small antes de 10/09")
    gc.collect()
    saida["carga_inicial"] = {"ms": t_carga, "memoria_antes": m0, "memoria_depois": memoria_mb(),
                              "cobertura": estado.cobertura()}

    etapa("financeiro: instantâneo (gravar e restaurar)")
    with tempfile.TemporaryDirectory() as tmp:
        caminho = Path(tmp) / "estado.pkl"
        meta, t_salvar = cronometro(estado.salvar, caminho)
        _, t_ler = cronometro(EstadoFinanceiro.carregar, caminho, prep)
        saida["instantaneo_apos_carga"] = {"gravar_ms": t_salvar, "restaurar_ms": t_ler, "mb": meta["bytes"] / 2**20}
    gc.collect()

    etapa("financeiro: dia 10/09 minuto a minuto (incremental)")
    trans = dia.trans.sort_values("minuto", kind="stable")
    nomes = dia.nomes_contas
    txs = [{
        "id_transacao": str(int(r.id_transacao)), "epoca": float(r.minuto * 60), "minuto": int(r.minuto),
        "timestamp_disponivel": float(r.minuto * 60), "banco_origem": str(int(r.banco_origem)),
        "banco_destino": str(int(r.banco_destino)), "conta_origem": str(nomes[r.conta_origem]),
        "conta_destino": str(nomes[r.conta_destino]), "valor_pago": float(r.valor_pago),
        "valor_recebido": float(r.valor_recebido), "moeda_pagamento": str(r.moeda_pagamento),
        "moeda_recebimento": str(r.moeda_recebimento), "formato": str(r.formato),
    } for r in trans.itertuples(index=False)]
    por_minuto: Dict[int, List[dict]] = {}
    for tx in txs:
        por_minuto.setdefault(tx["minuto"], []).append(tx)
    t_atrib, t_total, tamanhos, crescimento = [], [], [], []
    X_inc, ids_inc, score_inc = [], [], []
    inicio = time.perf_counter()
    for k, (m, grupo) in enumerate(sorted(por_minuto.items())):
        t0 = time.perf_counter()
        for tx in grupo:
            estado.receber(tx)
        fechado = estado.fechar_ate(None)[0]
        t1 = time.perf_counter()
        s, _ = pontuar_lavagem(cab, prep, fechado.X, pd.Series([tx["formato"] for tx in grupo]))
        t2 = time.perf_counter()
        t_atrib.append((t1 - t0) * 1000)
        t_total.append((t2 - t0) * 1000)
        tamanhos.append(len(grupo))
        X_inc.append(fechado.X.to_numpy())
        ids_inc += [int(tx["id_transacao"]) for tx in grupo]
        score_inc.append(s)
        if k % 360 == 0:
            cob = estado.cobertura()
            crescimento.append({"minuto_utc": ev.iso(m * 60), "contas": cob["contas"], "pares": cob["pares"],
                                "eventos_nas_janelas": cob["eventos_nas_janelas"]["envios"],
                                "memoria_mb": memoria_mb()["atual_mb"]})
    dur = time.perf_counter() - inicio
    cob = estado.cobertura()
    crescimento.append({"minuto_utc": cob["ultimo_minuto_fechado_utc"], "contas": cob["contas"], "pares": cob["pares"],
                        "eventos_nas_janelas": cob["eventos_nas_janelas"]["envios"],
                        "memoria_mb": memoria_mb()["atual_mb"]})
    ms_por_tx = np.asarray(t_total) / np.asarray(tamanhos)
    saida["incremental_dia"] = {
        "minutos": len(t_total), "transacoes": len(txs), "segundos": dur, "transacoes_por_s": len(txs) / dur,
        "transacoes_por_minuto": percentis(tamanhos),
        "atributos_por_minuto_ms": percentis(t_atrib),
        "atributos_mais_score_por_minuto_ms": percentis(t_total),
        "por_transacao_ms_(minuto/n)": percentis(ms_por_tx),
        "crescimento_do_estado": crescimento,
    }
    with tempfile.TemporaryDirectory() as tmp:
        meta, t_salvar = cronometro(estado.salvar, Path(tmp) / "e.pkl")
        saida["instantaneo_fim_do_dia"] = {"gravar_ms": t_salvar, "mb": meta["bytes"] / 2**20}
    X_inc = pd.DataFrame(np.vstack(X_inc), columns=prep.colunas, index=ids_inc).sort_index()
    score_inc = pd.Series(np.concatenate(score_inc), index=ids_inc).sort_index()
    del estado, txs, por_minuto
    gc.collect()

    etapa("financeiro: o mesmo dia em lote (caminho da CLI)")
    comb, consulta, _ = _concatenar(hist, dia)
    X_lote, t_lote = cronometro(atributos_financeiros, comb, consulta, prep)
    X_lote.index = dia.trans["id_transacao"].to_numpy()
    X_lote = X_lote.sort_index()
    score_lote = pd.Series(pontuar_lavagem(cab, prep, X_lote, dia.trans.set_index("id_transacao")
                                           .loc[X_lote.index, "formato"])[0], index=X_lote.index)
    saida["lote_dia_ms"] = t_lote

    etapa("financeiro: custo de recalcular UMA transação relendo o histórico")
    tempos_uma = []
    for i in (len(consulta) // 3, 2 * len(consulta) // 3)[: 1 if rapido else 2]:
        pos = int(consulta[i])
        parcial = comb.iloc[:pos + 1]
        tempos_uma.append(cronometro(atributos_financeiros, parcial, np.array([pos]), prep)[1])
    saida["caminho_antigo_uma_transacao_ms"] = tempos_uma

    etapa("financeiro: equivalência incremental × lote × força bruta")
    sys.path.insert(0, str(RAIZ))
    from testes.ml.referencia_financeira import atributos_referencia
    a, b = X_inc.to_numpy(np.float64), X_lote.to_numpy(np.float64)
    dif = np.abs(a - b)
    rel = dif / np.maximum(1.0, np.abs(b))
    colunas = {}
    for j, c in enumerate(prep.colunas):
        if dif[:, j].max() > 0:
            colunas[c] = {"max_abs": float(dif[:, j].max()), "max_rel": float(rel[:, j].max()),
                          "linhas_rel_acima_1e-6": int((rel[:, j] > 1e-6).sum())}
    saida["incremental_vs_lote"] = {"linhas": int(len(a)), "colunas_com_diferenca": colunas,
                                    "colunas_identicas": int(len(prep.colunas) - len(colunas))}
    # força bruta: linhas onde a razão diverge + amostra aleatória
    j = prep.colunas.index("razao_saida_entrada_24h")
    divergentes = np.flatnonzero(rel[:, j] > 1e-6)
    piores = divergentes[np.argsort(-rel[divergentes, j])][:150]  # as maiores diferenças lote × incremental
    rng = np.random.default_rng(42)
    aleatorias = rng.choice(len(a), size=60 if rapido else 200, replace=False)
    escolhidas = np.unique(np.concatenate([piores, aleatorias]))
    ids = X_inc.index.to_numpy()[escolhidas]
    pos_comb = pd.Series(consulta, index=dia.trans["id_transacao"].to_numpy()).loc[ids].to_numpy()
    ref = atributos_referencia(comb, pos_comb, prep.cambio, prep.formatos, prep.moedas)
    ref.index = ids
    cols_ref = list(ref.columns)
    inc_s = X_inc.loc[ids, cols_ref].astype(np.float64)
    lote_s = X_lote.loc[ids, cols_ref].astype(np.float64)
    ref32 = ref.astype(np.float32).astype(np.float64)  # a saída do modelo é float32 nos dois caminhos

    def erro(x):
        d = np.abs(x.to_numpy() - ref32.to_numpy()) / np.maximum(1.0, np.abs(ref32.to_numpy()))
        return {c: float(d[:, k].max()) for k, c in enumerate(cols_ref) if d[:, k].max() > 1e-6}

    saida["forca_bruta"] = {
        "linhas_conferidas": int(len(ids)), "linhas_com_razao_divergente_lote_x_incremental": int(len(divergentes)),
        "erro_relativo_max_incremental": erro(inc_s), "erro_relativo_max_lote": erro(lote_s),
        "razao_saida_entrada_24h": {
            "incremental_max_rel": float((np.abs(inc_s["razao_saida_entrada_24h"] - ref32["razao_saida_entrada_24h"])
                                          / np.maximum(1, ref32["razao_saida_entrada_24h"].abs())).max()),
            "lote_max_rel": float((np.abs(lote_s["razao_saida_entrada_24h"] - ref32["razao_saida_entrada_24h"])
                                   / np.maximum(1, ref32["razao_saida_entrada_24h"].abs())).max()),
        },
    }
    lim = cab.limiar_alerta
    ds = (score_inc - score_lote.loc[score_inc.index]).abs()
    al_inc, al_lote = score_inc >= lim, score_lote.loc[score_inc.index] >= lim
    saida["impacto_nos_scores"] = {
        "max_abs": float(ds.max()), "linhas_score_diferente": int((ds > 0).sum()),
        "alertas_incremental": int(al_inc.sum()), "alertas_lote": int(al_lote.sum()),
        "alertas_que_mudam": int((al_inc != al_lote).sum()), "limiar": lim,
    }
    saida["memoria_fim"] = memoria_mb()
    return saida


# ---------------------------------------------------------------------------
def ambiente() -> Dict[str, Any]:
    import sklearn
    return {"quando_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sistema": platform.platform(), "processador": platform.processor(), "cpus_logicas": os.cpu_count(),
            "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__}


def relatorio_md(r: Dict[str, Any]) -> str:
    def f(v, d=1):
        return "—" if v is None else f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def lat(p):
        return f"{f(p['p50'], 2)} / {f(p['p95'], 2)} / {f(p['p99'], 2)}" if p.get("n") else "—"

    a, m, rd, fi = r["ambiente"], r["modelo"], r["rede"], r["financeiro"]
    L = ["# Benchmark do processamento de eventos", "",
         "Gerado por `python scripts/benchmark_eventos.py`. Os números valem **para esta máquina e esta execução**; "
         "não são promessa de desempenho do sistema. Latências em ms (p50 / p95 / p99).", "",
         f"Ambiente: {a['sistema']}, {a['cpus_logicas']} CPUs lógicas, Python {a['python']}, numpy {a['numpy']}, "
         f"pandas {a['pandas']}, scikit-learn {a['scikit_learn']}. Execução: {a['quando_utc']}.", "",
         "## Modelo", "",
         "| medida | valor |", "|---|---|",
         f"| carga em processo novo (inclui importar bibliotecas) | p50 {f(m['processo_novo_ms']['p50'], 0)} ms |",
         f"| leitura do joblib no mesmo processo | {f(m['leitura_no_mesmo_processo_ms'][0], 0)} ms e {f(m['leitura_no_mesmo_processo_ms'][1], 0)} ms |",
         f"| tamanho do artefato | {f(m['artefato_mb'])} MB |", "",
         "## Rede (`estado_rede`)", "",
         "| medida | p50 / p95 / p99 (ms) | observação |", "|---|---|---|",
         f"| primeira previsão após carregar | {f(rd['primeira_previsao_ms'], 2)} | inclui aquecimento |",
         f"| uma medição, só o modelo | {lat(rd['uma_medicao_so_modelo_ms'])} | `CabecaClassificacao.probabilidades` |",
         f"| uma medição, com a tabela de saída | {lat(rd['uma_medicao_ms'])} | `tabela_previsoes_rede` |"]
    for tam, p in rd["lotes_ms"].items():
        L.append(f"| lote de {tam} | {lat(p)} | {f(p['linhas_por_s_p50'], 0)} linhas/s no p50 |")
    L += [f"| serviço, uma medição por vez (chegada → previsão gravada) | {lat(rd['servico_carga_baixa_ms'])} | fila + trabalhador + CSV |",
          f"| serviço, vazão máxima | — | {f(rd['servico_vazao_maxima']['eventos_por_s'], 0)} eventos/s "
          f"({rd['servico_vazao_maxima']['eventos']} medições em {f(rd['servico_vazao_maxima']['segundos'], 1)} s); "
          f"latência sob saturação {lat(rd['servico_vazao_maxima']['latencia_ms_ultimas_5000'])} |", ""]
    if "pulado" in fi:
        L += ["## Financeiro", "", f"Pulado: {fi['pulado']}.", ""]
        return "\n".join(L)
    inc, ca = fi["incremental_dia"], fi["carga_inicial"]
    L += ["## Financeiro (`lavagem`, estado incremental)", "",
          f"Histórico: {fi['transacoes_historico']:,} transações do HI-Small anteriores a 10/09/2022; "
          f"dia reproduzido: {fi['transacoes_dia']:,} transações de 10/09/2022 em {inc['minutos']:,} minutos.".replace(",", "."), "",
          "| medida | valor |", "|---|---|",
          f"| leitura do HI-Small (.zip) | {f(fi['leitura_ms']['historico_zip'] / 1000)} s |",
          f"| carga inicial do estado (vetorizada) | {f(ca['ms'] / 1000)} s |",
          f"| memória do processo (working set) antes / depois da carga do estado | {f(ca['memoria_antes']['atual_mb'], 0)} / {f(ca['memoria_depois']['atual_mb'], 0)} MB "
          f"(o Windows devolve páginas liberadas depois da leitura do .zip, então a diferença não mede o estado; o tamanho do instantâneo é a melhor aproximação) |",
          f"| pico de memória do processo no benchmark | {f(fi['memoria_fim']['pico_mb'], 0)} MB (inclui histórico, lote e força bruta) |",
          f"| instantâneo após a carga: gravar / restaurar / tamanho | {f(fi['instantaneo_apos_carga']['gravar_ms'] / 1000)} s / {f(fi['instantaneo_apos_carga']['restaurar_ms'] / 1000)} s / {f(fi['instantaneo_apos_carga']['mb'])} MB |",
          f"| instantâneo no fim do dia: gravar / tamanho | {f(fi['instantaneo_fim_do_dia']['gravar_ms'] / 1000)} s / {f(fi['instantaneo_fim_do_dia']['mb'])} MB |",
          f"| transações por minuto no dia | p50 {f(inc['transacoes_por_minuto']['p50'], 0)}, p99 {f(inc['transacoes_por_minuto']['p99'], 0)}, máx. {f(inc['transacoes_por_minuto']['max'], 0)} |",
          f"| atributos por minuto fechado (ms) | {lat(inc['atributos_por_minuto_ms'])} |",
          f"| atributos + score por minuto fechado (ms) | {lat(inc['atributos_mais_score_por_minuto_ms'])} |",
          f"| custo por transação (minuto ÷ transações, ms) | {lat(inc['por_transacao_ms_(minuto/n)'])} |",
          f"| vazão do dia (atributos + score) | {f(inc['transacoes_por_s'], 0)} transações/s ({f(inc['segundos'])} s no total) |",
          f"| mesmo dia em lote (`atributos_financeiros`, caminho da CLI) | {f(fi['lote_dia_ms'] / 1000)} s |",
          f"| caminho antigo: UMA transação nova relendo o histórico | {', '.join(f(x / 1000, 1) + ' s' for x in fi['caminho_antigo_uma_transacao_ms'])} |",
          "", "### Crescimento do estado ao longo do dia", "",
          "| minuto (UTC) | contas | pares | eventos nas janelas de 72 h | memória (MB) |", "|---|---|---|---|---|"]
    for c in inc["crescimento_do_estado"]:
        L.append(f"| {c['minuto_utc']} | {c['contas']:,} | {c['pares']:,} | {c['eventos_nas_janelas']:,} | {f(c['memoria_mb'], 0)} |".replace(",", "."))
    eq, fb, im = fi["incremental_vs_lote"], fi["forca_bruta"], fi["impacto_nos_scores"]
    L += ["", "### Equivalência no dia 10/09/2022", "",
          f"Incremental × lote, {eq['linhas']:,} linhas: {eq['colunas_identicas']} de {eq['colunas_identicas'] + len(eq['colunas_com_diferenca'])} colunas idênticas.".replace(",", "."), ""]
    if eq["colunas_com_diferenca"]:
        L += ["| coluna | dif. absoluta máx. | dif. relativa máx. | linhas com dif. relativa > 1e-6 |", "|---|---|---|---|"]
        for c, d in eq["colunas_com_diferenca"].items():
            L.append(f"| `{c}` | {d['max_abs']:.3g} | {d['max_rel']:.3g} | {d['linhas_rel_acima_1e-6']} |")
    rz = fb["razao_saida_entrada_24h"]
    L += ["", f"Força bruta (`testes/ml/referencia_financeira.py`) em {fb['linhas_conferidas']} linhas "
              f"(as 150 com maior diferença de razão entre lote e incremental, entre {fb['linhas_com_razao_divergente_lote_x_incremental']} divergentes, mais 200 aleatórias):", "",
          f"- incremental: maior erro relativo por coluna acima de 1e-6 = {fb['erro_relativo_max_incremental'] or 'nenhum'};",
          f"- lote: {fb['erro_relativo_max_lote'] or 'nenhum'};",
          f"- `razao_saida_entrada_24h`: erro relativo máximo {rz['incremental_max_rel']:.3g} no incremental e {rz['lote_max_rel']:.3g} no lote.", "",
          f"Efeito nos scores: diferença absoluta máxima {im['max_abs']:.3g} ({im['linhas_score_diferente']} linhas com score diferente); "
          f"alertas (limiar {im['limiar']:.4f}): {im['alertas_incremental']} no incremental, {im['alertas_lote']} no lote, "
          f"{im['alertas_que_mudam']} mudam de lado.", "",
          "O dia 10/09/2022 pertence ao período de teste. Aqui ele só mede tempo e equivalência numérica; "
          "nada foi ajustado com ele.", ""]
    return "\n".join(L)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rapido", action="store_true")
    p.add_argument("--sem-financeiro", action="store_true")
    args = p.parse_args()
    r: Dict[str, Any] = {"ambiente": ambiente(), "rapido": args.rapido}
    r["modelo"], modelo = bench_modelo(args.rapido)
    r["rede"] = bench_rede(modelo, args.rapido)
    r["financeiro"] = {"pulado": "--sem-financeiro"} if args.sem_financeiro else bench_financeiro(modelo, args.rapido)
    destino = ARTEFATOS / "benchmark"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "benchmark_eventos.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=float),
                                                    encoding="utf-8")
    (RAIZ / "docs" / "ml" / "BENCHMARK_EVENTOS.md").write_text(relatorio_md(r), encoding="utf-8")
    etapa(f"pronto: {destino / 'benchmark_eventos.json'} e docs/ml/BENCHMARK_EVENTOS.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
