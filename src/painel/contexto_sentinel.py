"""Contexto verificado que o Sentinel AI recebe para responder no "Assistente de dúvidas" do painel.

Tudo aqui é **lido** de onde o painel já lê (nada é estimado, resumido por IA ou inventado):

* ``analise``            manifesto da análise aberta (status, contagens, modelo, avisos);
* ``recorte``            a mesma visão geral que a tela mostra, com os filtros atuais
                         (``armazenamento.visao_geral``), inclusive as contas de maior risco;
* ``alertas_principais`` as transações do recorte com alerta, de maior score (até ``MAX_ALERTAS``);
* ``transacao_em_foco``  a transação aberta nos detalhes, quando o usuário pede ajuda sobre ela;
* ``modelo``             o que o modelo salvo informa sobre si: família, parâmetros, limiar, critérios e as
                         **importâncias globais** (redução média de impureza da floresta), que descrevem o
                         modelo inteiro e **não** a decisão sobre uma transação;
* ``avaliacao_historica`` métricas do teste oficial (docs/ml/resultados), separadas dos números da análise;
* ``limites``            o que o contexto não permite afirmar (para o Sentinel AI dizer, e não inventar).

O que vai para fora: este dicionário segue para o provedor de IA configurado (Gemini por padrão) **só**
quando o usuário autoriza na tela. Ele contém identificadores de contas e valores das transações listadas
(não o arquivo inteiro). Sem autorização, o assistente responde no modo local (src/painel/assistente.py).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from src.painel import armazenamento as arm
from src.painel import score as sc
from src.painel.util import id_exibicao_texto

MAX_ALERTAS = 10
MAX_CONTAS = 10
MAX_ITENS = 12
MAX_IMPORTANCIAS = 12

LIMITES = [
    "O modelo é uma floresta aleatória (Random Forest): não há explicação por transação gravada. Os valores dos "
    "49 atributos de cada transação não ficam salvos; só o score, o alerta e os motivos verificáveis.",
    "Os 'motivos verificáveis' são fatos sobre a transação, conferidos com regras fixas; não são a explicação "
    "da decisão do modelo.",
    "As importâncias globais dizem quais atributos a floresta mais usou no conjunto do treino; não dizem quais "
    "pesaram numa transação específica.",
    "O score (0 a 1000) é ordem de prioridade, não probabilidade; o score original (0 a 1) não é calibrado.",
    "Tipologias e rótulo vêm do arquivo do dataset (simulador), não do modelo, e não entram no cálculo do score.",
    "Horário compatível entre transações no grafo não prova que é o mesmo dinheiro.",
    "Cada análise começa sem histórico anterior ao arquivo: contas com menos de 72 h observadas têm atributos "
    "incompletos (historico_incompleto).",
    "O modelo foi treinado e avaliado em dados sintéticos (IBM AML HI-Small); desempenho em dados reais é desconhecido.",
]

_importancias_cache: Dict[str, List[Dict[str, Any]]] = {}


def importancias_globais(modelo: Any) -> List[Dict[str, Any]]:
    """Importância de cada atributo na floresta (média da redução de impureza), maiores primeiro."""
    cab = modelo.cabeca("lavagem")
    pipe = getattr(cab, "pipeline", None)
    if pipe is None:  # cabeça sem estimador do scikit-learn (não há importâncias para mostrar)
        return []
    chave = str((getattr(cab, "metadados", None) or {}).get("versao")) + str(id(pipe))
    if chave in _importancias_cache:
        return _importancias_cache[chave]
    est = pipe.steps[-1][1] if hasattr(pipe, "steps") else pipe
    if not hasattr(est, "feature_importances_"):
        _importancias_cache[chave] = []
        return []
    nomes = (list(pipe[:-1].get_feature_names_out(cab.colunas_entrada))
             if hasattr(pipe, "steps") and len(pipe.steps) > 1 else list(cab.colunas_entrada))
    pares = sorted(zip(nomes, (float(x) for x in est.feature_importances_)), key=lambda p: -p[1])
    saida = [{"atributo": n, "importancia": round(v, 4)} for n, v in pares[:MAX_IMPORTANCIAS]]
    _importancias_cache[chave] = saida
    return saida


def _cortar(v: Any, n: int = MAX_ITENS) -> Any:
    if isinstance(v, list):
        return [_cortar(x, n) for x in v[:n]]
    if isinstance(v, dict):
        return {k: _cortar(x, n) for k, x in v.items()}
    return v


def _transacao(d: Dict[str, Any], total: int = 0) -> Dict[str, Any]:
    # Só o ID como a tela mostra (TX-…): com o número cru ao lado, a resposta poderia citar outro formato.
    campos = ("data_hora", "no_origem", "no_destino", "valor_pago", "moeda_pagamento",
              "valor_recebido", "moeda_recebimento", "formato", "score", "faixa", "alerta", "score_bruto",
              "motivos", "historico_incompleto", "rotulo", "tipologias")
    saida = {"id_na_tela": id_exibicao_texto(d["id_exibicao"], total)}
    saida.update({k: d[k] for k in campos if k in d})
    return saida


def montar(manifesto: Optional[Dict[str, Any]], conexao: Optional[Callable[[], Any]], filtros: arm.Filtros,
           params_filtros: Dict[str, str], transacao_id: Optional[int], modelo: Any,
           avaliacao: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Contexto do painel para o Sentinel AI; ``conexao`` abre o SQLite da análise (None sem resultados)."""
    ctx: Dict[str, Any] = {
        "tela": "Painel do analista do NodeWatch (nova interface); o assistente se chama 'Assistente de dúvidas'.",
        "escala_do_score": {"faixas": sc.FAIXAS, "score_de_alerta": sc.SCORE_ALERTA, "aviso": sc.AVISO_FAIXAS},
        "regra_contas_de_maior_risco": arm.REGRA_CONTAS,
        "limites": LIMITES,
    }
    if modelo is not None:
        cab = modelo.cabeca("lavagem")
        md = cab.metadados or {}
        ctx["modelo"] = {
            "versao": md.get("versao"), "familia": cab.familia, "parametros": cab.params,
            "atributos": len(cab.colunas_entrada), "limiar_alerta_score_original": cab.limiar_alerta,
            "treinado_ate": md.get("treinado_ate"), "fonte_dos_dados_de_treino": md.get("fonte"),
            "criterio_de_escolha": md.get("criterio_selecao"), "criterio_do_limiar": md.get("criterio_limiar"),
            "aviso": md.get("aviso"),
            "importancias_globais": {
                "o_que_e": "redução média de impureza de cada atributo na floresta, no treino inteiro; descreve o "
                           "modelo, não a decisão sobre uma transação",
                "maiores": importancias_globais(modelo),
            },
        }
    if avaliacao:
        ctx["avaliacao_historica"] = {"o_que_e": "métricas do teste oficial do modelo (dados sintéticos), não desta análise",
                                      **avaliacao}
    if manifesto is None:
        ctx["analise"] = {"aberta": False, "nota": "Nenhuma análise está aberta na tela."}
        return ctx
    m = manifesto
    ctx["analise"] = {
        "aberta": True, "id": m["id"], "dataset": m["dataset"]["nome"], "status": m["status"],
        "descricao_status": m.get("descricao_status"), "contagens": _cortar(m.get("contagens") or {}),
        "modelo_usado": m.get("modelo"), "avisos": (m.get("avisos") or [])[:MAX_ITENS],
        "tipologias_disponiveis": m.get("tipologias", {}).get("disponivel"),
        "rotulo_disponivel": m.get("rotulo", {}).get("disponivel"),
    }
    if conexao is None:
        ctx["recorte"] = {"nota": "Esta análise não tem resultados gravados para consultar."}
        return ctx
    con = conexao()
    try:
        v = arm.visao_geral(con, filtros, m["contagens"]["pontuadas"], m["tipologias"]["disponivel"],
                            m["rotulo"]["disponivel"], m["tipologias"].get("motivo", ""))
        ativos = {k: x for k, x in params_filtros.items() if str(x).strip()}
        contas = (v.get("contas_risco") or {}).get("contas", [])[:MAX_CONTAS]
        recorte = _cortar({k: x for k, x in v.items() if k != "contas_risco"})
        ctx["recorte"] = {"filtros_aplicados": ativos or "nenhum (dataset inteiro, com o valor mínimo padrão)",
                          **recorte, "contas_de_maior_risco": contas}
        p_alerta = dict(params_filtros, alerta="sim")
        top = arm.pagina(con, arm.filtros_de_parametros({k: str(x) for k, x in p_alerta.items()}), 1, MAX_ALERTAS,
                         "score", "desc")
        ctx["alertas_principais"] = {
            "total_com_alerta_no_recorte": top["total"],
            "maiores_scores": [_transacao(arm.detalhe(con, r["id_exibicao"]), m["contagens"]["pontuadas"]) for r in top["linhas"]],
        }
        if transacao_id is not None:
            try:
                ctx["transacao_em_foco"] = {
                    "nota": "Transação aberta pelo usuário nos detalhes; é o assunto principal da pergunta.",
                    **_transacao(arm.detalhe(con, int(transacao_id)), m["contagens"]["pontuadas"])}
            except KeyError:
                ctx["transacao_em_foco"] = {"nota": f"A transação {transacao_id} não existe nesta análise."}
    finally:
        con.close()
    return ctx


def resumo_do_envio(ctx: Dict[str, Any]) -> List[str]:
    """Lista curta, mostrada ao usuário, do que foi enviado ao Sentinel AI."""
    partes = []
    a = ctx.get("analise") or {}
    if a.get("aberta"):
        partes.append(f"análise {a['id']} ({a['dataset']})")
    if "recorte" in ctx and "registros" in ctx["recorte"]:
        partes.append("indicadores do recorte com os filtros atuais e as contas de maior risco")
    if ctx.get("alertas_principais", {}).get("maiores_scores"):
        partes.append(f"{len(ctx['alertas_principais']['maiores_scores'])} transações com alerta de maior score")
    if "transacao_em_foco" in ctx and "id_na_tela" in ctx["transacao_em_foco"]:
        partes.append(f"a transação {ctx['transacao_em_foco']['id_na_tela']} aberta nos detalhes")
    if "modelo" in ctx:
        partes.append("dados do modelo (versão, limiar, importâncias globais)")
    if "avaliacao_historica" in ctx:
        partes.append("métricas do teste oficial do modelo")
    return partes
