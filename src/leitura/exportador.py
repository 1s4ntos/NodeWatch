"""Exportação de análises para JSON persistido em dados/analises/.

Responsável por serializar o resultado completo de uma análise — ciclos,
centralidade, SCCs e metadados — em um arquivo JSON estruturado, seguindo
a especificação definida no item 5 das regras do projeto.

Fluxo
-----
    análise concluída → build_analysis_dict() → save_analysis() → JSON em disco
                                                               → path retornado

Nomenclatura automática
-----------------------
    analise_AAAA-MM-DD_HHhMM.json
    Ex: analise_2026-05-14_14h32.json

O analista pode passar um nome personalizado — o módulo garante que:
    * Espaços são substituídos por _
    * A extensão .json é sempre mantida
    * Não sobrescreve arquivos existentes sem confirmação (sufixo _2, _3...)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.grafo.graph import Graph

if TYPE_CHECKING:
    from src.algoritmos.cycle_detection import CycleResult
    from src.algoritmos.centralidade import AccountCentrality
    from src.algoritmos.scc import SCCResult

# Pasta padrão de saída — relativa à raiz do projeto
_ANALISES_DIR = Path("dados/analises")
_VERSAO_SISTEMA = "0.4"


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def build_analysis_dict(
    graph: Graph,
    cycles: List[CycleResult],
    accounts: List[AccountCentrality],
    sccs: List[SCCResult],
    csv_path: str = "exemplo_transacoes.csv",
    nome_analise: Optional[str] = None,
    incluir_vertices: bool = True,
    incluir_arestas: bool = True,
    incluir_top_contas: bool = True,
    incluir_distribuicao: bool = True,
    incluir_scc: bool = True,
) -> Dict[str, Any]:
    """Monta o dicionário completo da análise para serialização.

    As seções `metadata`, `estatisticas` e `ciclos` são sempre incluídas.
    As demais são opcionais conforme os parâmetros `incluir_*`.

    Args:
        graph:               grafo analisado.
        cycles:              resultado de find_cycles().
        accounts:            resultado de compute_centrality().
        sccs:                resultado de find_scc().
        csv_path:            nome do arquivo CSV de origem.
        nome_analise:        nome personalizado (gerado automaticamente se None).
        incluir_vertices:    inclui seção `vertices` com risk score.
        incluir_arestas:     inclui seção `arestas` com todas as transações.
        incluir_top_contas:  inclui seção `top_contas` (top 10 por risco).
        incluir_distribuicao:inclui histograma de valores e steps.
        incluir_scc:         inclui seção `scc` com grupos de risco.

    Returns:
        Dicionário pronto para json.dumps().
    """
    now = datetime.now()
    nome = nome_analise or _auto_name(now)

    # --- Seções obrigatórias ---
    result: Dict[str, Any] = {
        "metadata": _build_metadata(now, csv_path, nome),
        "estatisticas": _build_estatisticas(graph, cycles),
        "ciclos": _build_ciclos(cycles, graph),
    }

    # --- Seções opcionais ---
    if incluir_vertices:
        result["vertices"] = _build_vertices(accounts)

    if incluir_arestas:
        result["arestas"] = _build_arestas(graph)

    if incluir_top_contas:
        result["top_contas"] = _build_top_contas(accounts)

    if incluir_distribuicao:
        result["distribuicao"] = _build_distribuicao(graph)

    if incluir_scc:
        result["scc"] = _build_scc(sccs)

    return result


def save_analysis(
    data: Dict[str, Any],
    nome: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """Salva o dicionário de análise como JSON em dados/analises/.

    Garante que:
        * O nome não contém espaços.
        * A extensão .json é sempre mantida.
        * Não sobrescreve — adiciona sufixo _2, _3... se necessário.

    Args:
        data:       dicionário retornado por build_analysis_dict().
        nome:       nome do arquivo sem extensão (usa metadata se None).
        output_dir: pasta de destino (usa _ANALISES_DIR se None).

    Returns:
        Path do arquivo salvo.
    """
    directory = output_dir or _ANALISES_DIR
    directory.mkdir(parents=True, exist_ok=True)

    base_name = _sanitize_name(nome or data["metadata"]["nome_analise"])
    final_path = _resolve_path(directory, base_name)

    with open(final_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return final_path


# ---------------------------------------------------------------------------
# Construtores internos de cada seção
# ---------------------------------------------------------------------------

def _build_metadata(
    now: datetime,
    csv_path: str,
    nome: str,
) -> Dict[str, Any]:
    return {
        "versao_sistema": _VERSAO_SISTEMA,
        "data_analise": now.isoformat(timespec="seconds"),
        "arquivo_origem": Path(csv_path).name,
        "nome_analise": nome,
    }


def _build_estatisticas(
    graph: Graph,
    cycles: List[CycleResult],
) -> Dict[str, Any]:
    edges = graph.edges()
    volume_total = sum(e.amount for e in edges)
    volume_risco = sum(c.total_value for c in cycles if c.category == "CICLO")
    fraudes = sum(1 for e in edges if e.is_fraud)
    ciclos_layering = sum(1 for c in cycles if c.category == "CICLO")
    anomalias = sum(1 for c in cycles if c.category == "ANOMALIA")

    return {
        "total_vertices": graph.vertex_count(),
        "total_arestas": graph.edge_count(),
        "total_ciclos": ciclos_layering,
        "total_anomalias": anomalias,
        "volume_total": round(volume_total, 2),
        "volume_em_risco": round(volume_risco, 2),
        "fraudes_rotuladas": fraudes,
    }


def _build_ciclos(
    cycles: List[CycleResult],
    graph: Graph,
) -> List[Dict[str, Any]]:
    """Serializa cada ciclo com suas arestas detalhadas."""
    # Mapa de arestas para busca rápida por par (src, dst)
    edge_map: Dict[tuple, List] = {}
    for edge in graph.edges():
        key = (edge.source, edge.target)
        edge_map.setdefault(key, []).append(edge)

    result = []
    for idx, cycle in enumerate(cycles, start=1):
        # Tipo predominante — mais frequente nas arestas do ciclo
        tipos = []
        arestas_detalhadas = []
        path = cycle.path

        for i in range(len(path) - 1):
            src, dst = path[i], path[i + 1]
            candidates = edge_map.get((src, dst), [])
            if candidates:
                e = candidates[0]
                t = (e.transaction_type or "").upper()
                tipos.append(t)
                arestas_detalhadas.append({
                    "origem":  src,
                    "destino": dst,
                    "valor":   round(e.amount, 2),
                    "tipo":    t or "DESCONHECIDO",
                    "step":    0,   # step não está no Edge atual
                })

        tipo_predominante = max(set(tipos), key=tipos.count) if tipos else "DESCONHECIDO"

        result.append({
            "id":               idx,
            "categoria":        cycle.category,
            "prioridade":       cycle.priority,
            "caminho":          cycle.path,
            "total_movimentado": round(cycle.total_value, 2),
            "perda":            round(cycle.loss, 2),
            "intermediarios":   cycle.intermediaries,
            "tipo_predominante": tipo_predominante,
            "arestas":          arestas_detalhadas,
        })

    return result


def _build_vertices(accounts: List[AccountCentrality]) -> List[Dict[str, Any]]:
    return [
        {
            "id":                a.account_id,
            "risk_score":        a.risk_score,
            "ciclos_participantes": a.cycle_count,
            "hub_type":          a.hub_type,
            "in_degree":         a.in_degree,
            "out_degree":        a.out_degree,
            "volume_enviado":    round(a.volume_out, 2),
            "volume_recebido":   round(a.volume_in, 2),
        }
        for a in accounts
    ]


def _build_arestas(graph: Graph) -> List[Dict[str, Any]]:
    return [
        {
            "origem":   e.source,
            "destino":  e.target,
            "valor":    round(e.amount, 2),
            "tipo":     (e.transaction_type or "DESCONHECIDO").upper(),
            "is_fraud": e.is_fraud,
        }
        for e in graph.edges()
    ]


def _build_top_contas(
    accounts: List[AccountCentrality],
    top_n: int = 10,
) -> List[Dict[str, Any]]:
    return [
        {
            "id":          a.account_id,
            "risk_score":  a.risk_score,
            "ciclos":      a.cycle_count,
            "hub_type":    a.hub_type,
            "volume_out":  round(a.volume_out, 2),
        }
        for a in accounts[:top_n]
    ]


def _build_distribuicao(graph: Graph) -> Dict[str, Any]:
    edges = graph.edges()
    buckets = [
        {"faixa": "< 1k",    "min": 0,      "max": 1_000,    "quantidade": 0},
        {"faixa": "1k–5k",   "min": 1_000,  "max": 5_000,    "quantidade": 0},
        {"faixa": "5k–10k",  "min": 5_000,  "max": 10_000,   "quantidade": 0},
        {"faixa": "10k–25k", "min": 10_000, "max": 25_000,   "quantidade": 0},
        {"faixa": "> 25k",   "min": 25_000, "max": float("inf"), "quantidade": 0},
    ]
    step_dist: Dict[int, Dict[str, int]] = {}

    for e in edges:
        for b in buckets:
            if b["min"] <= e.amount < b["max"]:
                b["quantidade"] += 1
                break

    return {
        "por_valor": [
            {"faixa": b["faixa"], "quantidade": b["quantidade"]}
            for b in buckets
        ],
    }


def _build_scc(sccs: List[SCCResult]) -> List[Dict[str, Any]]:
    return [
        {
            "id":              s.component_id,
            "suspeito":        s.is_suspicious,
            "contas":          s.vertices,
            "tamanho":         s.size,
            "volume_interno":  round(s.internal_volume, 2),
            "arestas_internas": s.internal_edges,
        }
        for s in sccs
    ]


# ---------------------------------------------------------------------------
# Utilitários de nomenclatura
# ---------------------------------------------------------------------------

def _auto_name(now: datetime) -> str:
    """Gera nome automático: analise_AAAA-MM-DD_HHhMM."""
    return now.strftime("analise_%Y-%m-%d_%Hh%M")


def _sanitize_name(name: str) -> str:
    """Remove espaços e caracteres inválidos, garante extensão .json."""
    clean = re.sub(r"[^\w\-.]", "_", name.strip())
    clean = re.sub(r"_+", "_", clean)
    if not clean.endswith(".json"):
        clean += ".json"
    return clean


def _resolve_path(directory: Path, filename: str) -> Path:
    """Resolve conflito de nome adicionando sufixo _2, _3... se necessário."""
    stem = filename.replace(".json", "")
    candidate = directory / filename
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}.json"
        counter += 1
    return candidate
