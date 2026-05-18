"""Centralidade de Grau para redes de transações financeiras.

A centralidade de grau mede quantas transações entram e saem de cada conta.
Em redes financeiras, contas com grau de saída alto são potenciais
distribuidoras (hubs de envio), e contas com grau de entrada alto são
potenciais coletoras — ambos os perfis são relevantes para análise de risco.

Regras de negócio aplicadas
----------------------------
* RN04 — Contas que aparecem em múltiplos ciclos recebem risco acumulado:
  risk_score += 15 pontos por ciclo adicional, teto em 100.

Complexidade
------------
* Tempo:  O(V + E) — percorre a lista de adjacência uma vez.
* Espaço: O(V)     — armazena um registro por vértice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, TYPE_CHECKING

from src.grafo.graph import Graph

if TYPE_CHECKING:
    from src.algoritmos.cycle_detection import CycleResult


# ---------------------------------------------------------------------------
# Score de risco base por tipo predominante de transação enviada
# ---------------------------------------------------------------------------
_TIPO_RISCO_BASE: Dict[str, int] = {
    "TRANSFER": 40,
    "CASH_OUT": 30,
    "PAYMENT":  15,
    "CASH_IN":  10,
    "DEBIT":    10,
}
_RISCO_POR_CICLO = 15   # RN04 — pontos adicionais por ciclo
_RISCO_TETO      = 100  # RN04 — score máximo


@dataclass
class AccountCentrality:
    """Métricas de centralidade e risco de uma conta.

    Atributos:
        account_id:      identificador da conta.
        in_degree:       número de transações recebidas (grau de entrada).
        out_degree:      número de transações enviadas (grau de saída).
        degree:          grau total (in + out).
        volume_in:       soma dos valores recebidos.
        volume_out:      soma dos valores enviados.
        cycle_count:     número de ciclos em que a conta participa.
        risk_score:      score de risco composto (0–100).
        hub_type:        classificação — "DISTRIBUIDOR", "COLETOR",
                         "INTERMEDIÁRIO", "SUSPEITO" ou "NORMAL".
        types_sent:      tipos de transação enviados por esta conta.
    """
    account_id:  str
    in_degree:   int   = 0
    out_degree:  int   = 0
    degree:      int   = 0
    volume_in:   float = 0.0
    volume_out:  float = 0.0
    cycle_count: int   = 0
    risk_score:  int   = 0
    hub_type:    str   = "NORMAL"
    types_sent:  List[str] = field(default_factory=list)


def compute_centrality(
    graph: Graph,
    cycles: List[CycleResult],
) -> List[AccountCentrality]:
    """Calcula centralidade de grau e score de risco para todas as contas.

    Args:
        graph:  multigrafo direcionado com as transações.
        cycles: lista de CycleResult retornada por find_cycles().

    Returns:
        Lista de AccountCentrality ordenada por risk_score desc.

    Complexidade: O(V + E + C×P) onde C = número de ciclos e
    P = tamanho médio do caminho por ciclo.
    """
    # --- Inicializa registros para todos os vértices --- O(V)
    records: Dict[str, AccountCentrality] = {
        v: AccountCentrality(account_id=v)
        for v in graph.vertices()
    }

    # --- Percorre arestas: computa graus e volumes --- O(E)
    for edge in graph.edges():
        src = edge.source
        dst = edge.target

        # grau de saída da origem
        if src in records:
            records[src].out_degree += 1
            records[src].volume_out += edge.amount
            t = (edge.transaction_type or "").upper()
            if t:
                records[src].types_sent.append(t)

        # grau de entrada do destino
        if dst in records:
            records[dst].in_degree += 1
            records[dst].volume_in += edge.amount

    # grau total
    for rec in records.values():
        rec.degree = rec.in_degree + rec.out_degree

    # --- Conta participação em ciclos por conta --- O(C × P)
    for cycle in cycles:
        # path = [v0, v1, ..., vn, v0] — v0 aparece duas vezes
        unique_accounts = set(cycle.path[:-1])
        for account in unique_accounts:
            if account in records:
                records[account].cycle_count += 1

    # --- Calcula risk_score e hub_type --- O(V)
    for rec in records.values():
        rec.risk_score = _compute_risk_score(rec)
        rec.hub_type   = _classify_hub(rec)

    # --- Ordena por risk_score desc, depois por degree desc ---
    return sorted(
        records.values(),
        key=lambda r: (r.risk_score, r.degree),
        reverse=True,
    )


def _compute_risk_score(rec: AccountCentrality) -> int:
    """Calcula o score de risco composto de uma conta (0–100).

    Fórmula (RN04):
        base  = risco pelo tipo de transação predominante enviado
        extra = cycle_count × _RISCO_POR_CICLO
        score = min(base + extra, _RISCO_TETO)

    Contas sem transações enviadas partem de score 0.
    """
    if not rec.types_sent:
        base = 0
    else:
        # tipo mais frequente enviado pela conta
        tipo_predominante = max(
            set(rec.types_sent),
            key=rec.types_sent.count,
        )
        base = _TIPO_RISCO_BASE.get(tipo_predominante, 10)

    extra = rec.cycle_count * _RISCO_POR_CICLO
    return min(base + extra, _RISCO_TETO)


def _classify_hub(rec: AccountCentrality) -> str:
    """Classifica a conta com base no perfil de grau e ciclos.

    Categorias:
        SUSPEITO      — participa de ao menos 1 ciclo detectado.
        DISTRIBUIDOR  — out_degree >> in_degree (envia muito, recebe pouco).
        COLETOR       — in_degree >> out_degree (recebe muito, envia pouco).
        INTERMEDIÁRIO — grau alto e equilibrado entre entrada e saída.
        NORMAL        — baixo grau, sem participação em ciclos.
    """
    if rec.cycle_count > 0:
        return "SUSPEITO"
    if rec.out_degree == 0 and rec.in_degree == 0:
        return "NORMAL"
    ratio = rec.out_degree / max(rec.in_degree, 1)
    if ratio >= 3:
        return "DISTRIBUIDOR"
    if ratio <= 0.33:
        return "COLETOR"
    if rec.degree >= 4:
        return "INTERMEDIÁRIO"
    return "NORMAL"


def centrality_summary(accounts: List[AccountCentrality]) -> str:
    """Formata um resumo de centralidade para exibição na CLI."""
    lines = [
        "-" * 60,
        "Centralidade de Grau — Top contas por risco",
        "-" * 60,
        f"  {'Conta':<10} {'In':>4} {'Out':>4} {'Ciclos':>6} "
        f"{'Score':>6}  Tipo",
    ]
    for acc in accounts[:10]:  # exibe top 10
        lines.append(
            f"  {acc.account_id:<10} {acc.in_degree:>4} {acc.out_degree:>4} "
            f"{acc.cycle_count:>6} {acc.risk_score:>6}  {acc.hub_type}"
        )
    lines.append("-" * 60)
    return "\n".join(lines)
