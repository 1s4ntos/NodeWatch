"""Assistente de dúvidas do painel: respostas locais e verificáveis.

O chatbot da versão antiga (``SentinelChat`` + ``POST /api/chat``, commit
12232ad) enviava um retrato da tela a um modelo de linguagem externo (Gemini
ou Anthropic) e respondia em texto livre sobre ciclos e DFS. Aquela base não
é verificável para este painel e mandaria dados do dataset para fora.

Este assistente não usa serviço externo e não gera texto livre. Ele responde
só com:

* **glossário e legendas** (os mesmos textos da tela);
* **ajuda de uso** (como enviar, filtrar, abrir o grafo, cancelar);
* **fatos da análise ativa**, lidos dos resultados gravados com os filtros
  atuais (quantos alertas, período, scores, contas, formatos, tipologias).

Ele **não conclui se houve fraude ou lavagem**: perguntas assim recebem essa
explicação. Pergunta fora da base → ele diz que não sabe e lista o que sabe.
"""

from __future__ import annotations

import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.painel import score as sc
from src.painel.util import id_exibicao_texto
from src.painel import tipologias as tp

LIMITE_PERGUNTA = 300


def _normalizar(texto: str) -> str:
    sem = unicodedata.normalize("NFD", str(texto).lower())
    return "".join(c for c in sem if unicodedata.category(c) != "Mn")


def _n(v: Any) -> str:
    return f"{int(v):,}".replace(",", ".")


GLOSSARIO: List[Tuple[Tuple[str, ...], str, str]] = [
    (("score", "pontuacao"), "Score",
     "Número inteiro de 0 a 1000 que ordena as transações por prioridade de investigação. Vem do modelo de "
     f"lavagem e é ancorado no limiar de alerta: {sc.SCORE_ALERTA} ou mais gera alerta. Não é probabilidade."),
    (("faixa", "baixa", "intermediaria", "alta", "cinzenta"), "Faixas do score",
     "0–300: baixa, sugestão de aprovação automática. 301–700: intermediária, área cinzenta para análise manual. "
     "701–1000: alta, sugestão de recusa ou bloqueio. " + sc.AVISO_FAIXAS),
    (("alerta",), "Alerta",
     f"Transação com score {sc.SCORE_ALERTA} ou mais. É um sinal para investigação, não uma confirmação de lavagem."),
    (("limiar",), "Limiar",
     "Valor do score bruto do modelo a partir do qual há alerta. Foi escolhido na validação do modelo (maior F1) "
     f"e corresponde ao score {sc.SCORE_ALERTA} na escala do painel."),
    (("recorte",), "Recorte", "O conjunto de transações que passa pelos filtros aplicados. Indicadores, tabela, "
     "contas e grafo usam o mesmo recorte."),
    (("id de exibicao", "id exibicao", "identificador"), "ID de exibição",
     "Número da transação na ordem cronológica do dataset inteiro (empates pela ordem da linha). Não muda com "
     "filtros, ordenação ou página. O identificador original do arquivo aparece nos detalhes."),
    (("posicao",), "Posição", "Lugar da linha na lista atual (com os filtros e a ordenação escolhidos), a partir "
     "de 1. Muda quando o filtro ou a ordenação muda; o ID de exibição não."),
    (("rotulo",), "Rótulo do dataset", "Marcação de lavagem que já vem no arquivo (coluna Is Laundering ou "
     "rotulo). É mostrada separada da previsão do modelo e nunca entra no cálculo do score."),
    (("motivo",), "Motivos verificáveis", "Fatos conferíveis sobre a transação (por exemplo, primeira transação "
     "entre as duas contas), calculados com regras fixas. Só aparecem em transações com alerta e não explicam a "
     "decisão do modelo."),
    (("tipologia", "padrao"), "Tipologias", "Formas de movimentação registradas no arquivo de padrões do dataset: "
     + ", ".join(tp.TIPOLOGIAS) + f" e {tp.NAO_IDENTIFICADO} (sem tipologia registrada). São rótulos do dataset, "
     "não previsões do modelo."),
    (("vertice", "no do grafo"), "Vértice", "Uma conta no grafo. A conta em foco tem contorno duplo; contas "
     "ligadas a alertas aparecem em vermelho com a palavra 'alerta'."),
    (("aresta", "seta"), "Aresta", "Uma ou mais transações entre duas contas, na mesma moeda. A seta aponta da "
     "conta de origem para a de destino. Arestas agrupadas mostram a quantidade e o total na moeda."),
    (("grafo",), "Grafo", "Mostra as transações enviadas e recebidas pela conta em foco e as cadeias a partir "
     "dela, até o número de saltos escolhido, com limites de vértices e arestas informados na legenda."),
    (("historico incompleto", "72"), "Histórico incompleto", "A transação foi pontuada com menos de 72 horas de "
     "histórico observado no próprio dataset. Nessas, o modelo tende a gerar menos alertas."),
    (("nao informado",), "Não informado", "Categoria usada quando o formato de pagamento está vazio ou "
     "desconhecido no arquivo."),
    (("parcial",), "Análise parcial", "A análise foi interrompida sem pedido (por exemplo, o servidor reiniciou). "
     "Valem só as transações já pontuadas, as primeiras em ordem cronológica."),
    (("precisao",), "Precisão", "Entre as transações com alerta, a fração que é lavagem segundo o rótulo."),
    (("recall", "revocacao"), "Recall", "Entre as transações rotuladas como lavagem, a fração que recebeu alerta."),
    (("f1",), "F1", "Média harmônica entre precisão e recall."),
    (("average precision", "ap "), "Average Precision", "Resumo da curva precisão × recall em todos os limiares; "
     "mede a qualidade da ordenação pelo score."),
]
for _t in tp.TIPOLOGIAS:
    GLOSSARIO.insert(0, ((_normalizar(_t), _normalizar(_t).replace("-", " ")), f"Tipologia {_t}",
                         f"{_t}: {tp.DESCRICOES[_t]}. É registrada no dataset (arquivo de padrões), não prevista."))

AJUDA: List[Tuple[Tuple[str, ...], str, str]] = [
    (("enviar", "upload", "carregar", "escolher dataset", "subir"), "Enviar ou escolher um dataset",
     "Em 'Dataset e análise', escolha um arquivo .csv (ou .zip com um CSV) e clique em Enviar e validar, ou "
     "selecione um dataset já disponível na lista. A análise só começa quando você clica em Analisar."),
    (("cancelar", "parar"), "Cancelar a análise", "Durante o processamento, use Cancelar análise. A análise para "
     "no fim do bloco atual e o que já foi pontuado continua consultável como resultado parcial."),
    (("filtrar", "filtro"), "Filtros", "Preencha os filtros e clique em Aplicar filtros. Indicadores, contas, "
     "grafo e tabela são atualizados juntos. O valor mínimo começa em 1 (na moeda de cada transação); "
     "apague o campo para incluir valores menores. Voltar aos filtros iniciais desfaz os demais filtros."),
    (("coluna",), "Colunas da tabela", "Use o botão Colunas, acima da tabela, para exibir ou ocultar colunas, "
     "inclusive as colunas originais do dataset."),
    (("ver grafo", "abrir grafo", "conta em foco"), "Abrir o grafo de uma conta", "Selecione uma conta em 'Contas "
     "de maior risco', ou preencha o filtro Conta de origem ou Conta de destino e aplique."),
    (("sessao", "expira", "pulso", "fechar a aba", "fechei a aba"), "Sessão da interface",
     "Enviar, validar e analisar exigem a sessão desta página, que é renovada sozinha enquanto a página está "
     "aberta (mesmo minimizada ou em outra aba). Sem sinal por cerca de dois minutos e meio, a sessão expira e a "
     "análise para num ponto seguro, ficando parcial. Nada é retomado sozinho."),
    (("historico de analise", "analises recentes", "reabrir"), "Análises recentes", "A lista 'Análises recentes' "
     "abre os resultados gravados de análises anteriores, sem reprocessar."),
    (("legenda",), "Legenda", "O botão Legenda, no topo, reúne o significado de cores, ícones, setas, estados e "
     "termos usados em todas as áreas."),
]

_CONCLUSAO = ("fraude", "fraudador", "culpad", "crime", "criminos", "lavou", "e lavagem", "houve lavagem",
              "esta lavando", "suspeito mesmo", "posso bloquear", "devo bloquear", "devo denunciar")

O_QUE_SEI = ("Posso responder sobre: termos da tela (score, faixas, alerta, limiar, recorte, ID de exibição, "
             "rótulo, tipologias, grafo), como usar o painel (enviar, filtrar, colunas, cancelar, análises "
             "recentes) e fatos da análise ativa com os filtros atuais (quantas transações e alertas, período, "
             "scores, contas de maior risco, formatos, tipologias, modelo).")


_POR_QUE = ("por que", "porque", "por q", "motivo", "classific", "suspeit", "influenc", "caracteristic")


def _sobre_transacao(t: Dict[str, Any], manifesto: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Fatos gravados sobre a transação em foco, sem atribuir a decisão a atributos (o modelo não grava isso)."""
    mod = (manifesto or {}).get("modelo") or {}
    limiar = mod.get("limiar_alerta")
    tx = id_exibicao_texto(t['id_exibicao'], ((manifesto or {}).get('contagens') or {}).get('pontuadas', 0))
    partes = [f"Transação {tx}: score {t['score']} de 1000 (score original {t['score_bruto']:.4f})"
              + (f"; o limiar de alerta é {limiar:.4f} no score original, que equivale a {sc.SCORE_ALERTA}" if limiar else "")
              + f". {'Tem alerta' if t['alerta'] else 'Não tem alerta'} (faixa {t['faixa']})."]
    if t.get("motivos"):
        partes.append("Motivos verificáveis (fatos conferidos com regras fixas, não a explicação do modelo): "
                      + "; ".join(t["motivos"]) + ".")
    elif t["alerta"]:
        partes.append("Não há motivo verificável registrado para esta transação.")
    else:
        partes.append("Motivos verificáveis só são calculados para transações com alerta.")
    if t.get("historico_incompleto"):
        partes.append("O histórico das contas estava incompleto (menos de 72 h observadas), o que tende a baixar o score.")
    partes.append("O modelo é uma floresta aleatória e não grava quanto cada atributo pesou nesta decisão; por isso "
                  "não é possível dizer exatamente por que ela recebeu esse score.")
    return {"tipo": "fato", "base": ["detalhes gravados da transação", "manifesto da análise"],
            "resposta": " ".join(partes)}


def responder(pergunta: str, manifesto: Optional[Dict[str, Any]],
              visao: Optional[Callable[[], Dict[str, Any]]], transacao: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resposta com a base usada. ``visao`` calcula os indicadores do recorte só se for preciso; ``transacao`` é
    a transação aberta nos detalhes, quando o usuário pergunta sobre ela."""
    p = _normalizar(pergunta)[:LIMITE_PERGUNTA].strip()
    if not p:
        return {"tipo": "ajuda", "resposta": O_QUE_SEI, "base": ["ajuda do painel"]}
    if any(t in p for t in _CONCLUSAO):
        return {"tipo": "limite", "base": ["limites do assistente"],
                "resposta": "Não concluo se houve fraude ou lavagem. O score e os alertas são sinais para "
                            "investigação; a decisão é do analista. Posso mostrar os números da análise e explicar "
                            "os termos da tela."}
    if transacao and any(t in p for t in _POR_QUE + ("score", "alerta", "esta transac", "essa transac")):
        return _sobre_transacao(transacao, manifesto)
    fato = _fato(p, manifesto, visao)
    if fato:
        return fato
    for chaves, titulo, texto in AJUDA:
        if any(c in p for c in chaves):
            return {"tipo": "ajuda", "titulo": titulo, "resposta": texto, "base": ["ajuda do painel"]}
    for chaves, titulo, texto in GLOSSARIO:
        if any(c in p for c in chaves):
            return {"tipo": "glossario", "titulo": titulo, "resposta": texto, "base": ["glossário e legendas do painel"]}
    return {"tipo": "desconhecido", "base": [],
            "resposta": "Não tenho base verificável para responder a isso. " + O_QUE_SEI}


_RESUMO = ("risco", "identific", "encontr", "resultado", "resum", "interpret", "aconteceu", "machine learning",
           "o que a ml", "o que o modelo")


def _resumo(manifesto: Dict[str, Any], v: Dict[str, Any], base: List[str]) -> Dict[str, Any]:
    """O que a análise registrou, só com números gravados (sem interpretar além deles)."""
    n, a = v["registros"]["recorte"], v["alertas"]["n"]
    partes = [f"No recorte há {_n(n)} transações pontuadas pelo modelo; {_n(a)} "
              f"{'tem' if a == 1 else 'têm'} alerta (score {sc.SCORE_ALERTA} ou mais)."]
    if v.get("score"):
        partes.append(f"Score mínimo {v['score']['min']}, mediano {v['score']['mediana']:g} e máximo {v['score']['max']}.")
    contas = (v.get("contas_risco") or {}).get("contas") or []
    if contas:
        partes.append("Contas com mais transações em alerta: " + "; ".join(
            f"{c['conta']} ({c['alertas']}, maior score {c['maior_score']})" for c in contas[:3]) + ".")
    partes.append("São sinais para investigação, não conclusão. O modo local não interpreta além desses números; "
                  "para uma leitura comentada, autorize o Sentinel AI no assistente (se estiver disponível).")
    return {"tipo": "fato", "base": base, "resposta": " ".join(partes)}


def _fato(p: str, manifesto: Optional[Dict[str, Any]], visao: Optional[Callable[[], Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    quantitativa = any(t in p for t in ("quant", "qual ", "quais", "numero de", "total de", "maior", "menor",
                                        "mediano", "mediana", "periodo", "quando", "status", "situacao", "versao")
                       + _RESUMO)
    if not quantitativa:
        return None
    if manifesto is None:
        return {"tipo": "fato", "base": [], "resposta": "Nenhuma análise está aberta. Abra ou conclua uma análise "
                                                         "para eu consultar os números."}
    base = [f"análise {manifesto['id']} ({manifesto['dataset']['nome']})"]
    if any(t in p for t in ("status", "situacao", "estado da analise")):
        return {"tipo": "fato", "base": base,
                "resposta": f"Situação da análise: {manifesto.get('descricao_status') or manifesto['status']}"}
    if any(t in p for t in ("modelo", "versao", "limiar")):
        mod = manifesto.get("modelo")
        if not mod:
            return {"tipo": "fato", "base": base, "resposta": "A análise ainda não carregou o modelo."}
        return {"tipo": "fato", "base": base + ["manifesto da análise"],
                "resposta": f"Modelo {mod['versao']} ({mod.get('familia') or 'família não informada'}), limiar de "
                            f"alerta {mod['limiar_alerta']:.4f} no score bruto, que equivale a {sc.SCORE_ALERTA} "
                            "na escala de 0 a 1000."}
    if visao is None or not manifesto.get("resultados", {}).get("disponiveis"):
        return {"tipo": "fato", "base": base, "resposta": "Esta análise ainda não tem resultados gravados."}
    v = visao()
    base = base + ["resultados gravados, com os filtros atuais"]
    n = v["registros"]["recorte"]
    if any(t in p for t in _RESUMO):
        return _resumo(manifesto, v, base)
    if "alerta" in p and "conta" not in p:
        return {"tipo": "fato", "base": base,
                "resposta": (f"Há {_n(v['alertas']['n'])} "
                             f"{'transação' if v['alertas']['n'] == 1 else 'transações'} com alerta entre as "
                             f"{_n(n)} do recorte.")}
    if "conta" in p:
        contas = v["contas_risco"]["contas"]
        if not contas:
            return {"tipo": "fato", "base": base, "resposta": "Nenhuma conta tem transação com alerta no recorte."}
        lista = "; ".join(f"{c['conta']} ({c['alertas']} com alerta, maior score {c['maior_score']})" for c in contas[:5])
        return {"tipo": "fato", "base": base, "resposta": f"Contas com mais transações em alerta no recorte: {lista}. "
                                                         "A regra de ordenação está no painel de contas."}
    if any(t in p for t in ("periodo", "quando", "data")):
        per = v["periodo"]
        return {"tipo": "fato", "base": base,
                "resposta": (f"O recorte vai de {per['inicio'].replace('T', ' ')} a {per['fim'].replace('T', ' ')} "
                             "(horário do dataset).") if per else "O recorte está vazio."}
    if "score" in p or "median" in p:
        s = v["score"]
        return {"tipo": "fato", "base": base,
                "resposta": (f"Score mínimo {s['min']}, mediano {s['mediana']:g} e máximo {s['max']} no recorte.")
                if s else "O recorte está vazio."}
    if "formato" in p:
        itens = v["formatos"]["itens"]
        lista = "; ".join(f"{i['formato']}: {_n(i['n'])} ({i['proporcao'] * 100:.1f}%)" for i in itens[:8])
        return {"tipo": "fato", "base": base,
                "resposta": f"Formatos de pagamento, em % das {_n(n)} transações do recorte: {lista}." if itens
                else "O recorte está vazio."}
    if "tipologia" in p or "padrao" in p:
        t = v["tipologias"]
        if not t["disponivel"]:
            return {"tipo": "fato", "base": base, "resposta": t["motivo"]}
        lista = "; ".join(f"{i['tipologia']}: {_n(i['n'])}" for i in t["itens"])
        return {"tipo": "fato", "base": base, "resposta": f"Tipologias registradas no dataset, no recorte: {lista}."}
    if any(t in p for t in ("transac", "registro", "linha")):
        return {"tipo": "fato", "base": base,
                "resposta": f"O recorte tem {_n(n)} transações; o dataset analisado tem {_n(v['registros']['dataset'])}."}
    return None
