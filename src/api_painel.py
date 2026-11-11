"""API do painel do analista (Blueprint ``/api/painel``).

Fluxo: enviar ou escolher um dataset → validar → **Analisar** (ação explícita)
→ acompanhar as etapas → consultar os resultados gravados com filtros.
Abrir a página ou consultar qualquer rota GET não inicia processamento.

**Sessão da interface.** As rotas marcadas com [sessão] processam dados e
exigem o cabeçalho ``X-NodeWatch-Sessao`` com uma sessão ativa, a mesma de
``src/ml/sessoes.py`` usada pelas rotas ``/api/ml`` (em produção, o mesmo
gerenciador). A página abre a sessão, renova-a com pulsos e, sem pulso por
``ttl_s`` segundos, a sessão expira: a análise dela para no próximo ponto
seguro e fica parcial. Nada é retomado sozinho.

**Origem.** Todas as rotas passam por ``src/seguranca_local.py``: só a própria
página (mesma origem) pode chamá-las a partir de um navegador.

Rotas:
    GET  /api/painel/estado                         modelo, limites, legendas, análise em andamento
    POST /api/painel/sessao                         abre uma sessão da interface (uma por aba)
    POST /api/painel/sessao/pulso                   renova a sessão
    POST /api/painel/sessao/encerrar                encerra a sessão (a análise dela para no ponto seguro)
    GET  /api/painel/sessao                         situação da sessão e política de expiração
    GET  /api/painel/datasets                       enviados e disponíveis no servidor
    POST /api/painel/datasets                       [sessão] envia (``arquivo`` e, opcional, ``padroes``) e valida
    GET  /api/painel/datasets/<id>                  situação e resultado da validação
    POST /api/painel/datasets/<id>/validar          [sessão] valida (ou revalida) um dataset
    GET  /api/painel/analises                       análises recentes (manifestos)
    POST /api/painel/analises                       [sessão] inicia a análise de ``{"dataset_id": ...}``
    GET  /api/painel/analises/<id>                  manifesto: etapas, progresso, contagens, erros
    POST /api/painel/analises/<id>/cancelar         [sessão] pede o cancelamento (ponto seguro)
    POST /api/painel/analises/<id>/assumir          [sessão] esta aba passa a ser a responsável pela análise
    GET  /api/painel/analises/<id>/visao            indicadores e contas de maior risco do recorte
    GET  /api/painel/analises/<id>/transacoes       página da tabela (filtros, ordenação)
    GET  /api/painel/analises/<id>/transacoes/<n>   detalhes de uma transação (ID de exibição)
    GET  /api/painel/analises/<id>/grafo            grafo da conta em foco
    GET  /api/painel/operacao/desempenho            latência, RAM, CPU e medidas da análise
    GET  /api/painel/operacao/logs?tipo=sistema|ml  logs
    GET  /api/painel/operacao/metricas              métricas históricas do modelo (+ as do dataset, se houver rótulo)
    POST /api/painel/assistente                     resposta local e verificável

Nenhuma rota recebe caminho de arquivo: datasets e análises são identificados
por códigos gerados pelo servidor.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from flask import Blueprint, jsonify, request

_RAIZ = Path(__file__).resolve().parent.parent
CABECALHO_SESSAO = "X-NodeWatch-Sessao"
VALOR_MINIMO_PADRAO = 1
bp = Blueprint("painel", __name__, url_prefix="/api/painel")
_trava = threading.RLock()
_ctx: Dict[str, Any] = {}


def configurar(raiz: Path, modelo: Any = None, config_financeiro: Optional[Dict[str, Any]] = None,
               bloco: Optional[int] = None, max_analises: Optional[int] = None, sessoes: Any = None) -> None:
    """Define a raiz dos dados e o modelo (os testes usam uma pasta temporária e um modelo pequeno)."""
    from src.painel import pipeline as pl
    from src.painel.datasets import RepositorioDatasets
    from src.painel.sistema import Latencias, MonitorRecursos, Registro

    raiz = Path(raiz)
    if sessoes is None:
        if raiz == _RAIZ:  # o mesmo gerenciador das rotas /api/ml: uma sessão vale nas duas interfaces
            from src import api_eventos
            sessoes = api_eventos.sessoes()
        else:
            from src.ml.sessoes import GerenciadorSessoes
            sessoes = GerenciadorSessoes()
    with _trava:
        registro = Registro(raiz / "artefatos_ml" / "painel" / "logs")
        datasets = RepositorioDatasets(raiz, registro, config_financeiro)

        def obter_modelo() -> Any:
            with _trava:
                if _ctx.get("modelo") is None:
                    if raiz == _RAIZ:  # mesmo modelo já carregado pelas outras rotas, se houver
                        from src import api_eventos
                        _ctx["modelo"] = api_eventos._modelo()
                    else:
                        from src.ml.modelos import ModeloUnificado
                        _ctx["modelo"] = ModeloUnificado.carregar(raiz / "artefatos_ml")
                return _ctx["modelo"]

        analises = pl.GerenciadorAnalises(raiz, datasets, obter_modelo, registro, bloco or pl.BLOCO,
                                          max_analises or pl.MAX_ANALISES, sessao_ativa=sessoes.ativa,
                                          janela_sessao_s=sessoes.ttl_s)
        _ctx.clear()
        _ctx.update(raiz=raiz, modelo=modelo, registro=registro, datasets=datasets, analises=analises,
                    monitor=MonitorRecursos(), latencias=Latencias(), metricas_dataset={}, sessoes=sessoes)


def _c() -> Dict[str, Any]:
    with _trava:
        if not _ctx:
            cfg = None
            try:
                from src.ml.config import carregar_config
                cfg = carregar_config().get("financeiro")
            except Exception:  # sem configuração local: só os datasets enviados e os das pastas fixas
                cfg = None
            configurar(_RAIZ, config_financeiro=cfg)
        return _ctx


def _json(dados: Any, status: int = 200):
    from src.ml.exploracao import para_json
    return jsonify(para_json(dados)), status


def _protegido(operacao: Optional[str] = None) -> Callable:
    """Converte erros previstos em JSON com mensagem e ação; mede a latência da operação."""

    def decorador(func: Callable) -> Callable:
        def envolvida(*args: Any, **kwargs: Any):
            from src.painel.armazenamento import ErroFiltro
            from src.painel.datasets import ErroDataset
            from src.painel.pipeline import ErroAnaliseOcupada, SemResultados, SessaoInativa
            inicio = time.perf_counter()
            try:
                resposta = func(*args, **kwargs)
                if operacao:
                    _c()["latencias"].registrar(operacao, 1000 * (time.perf_counter() - inicio))
                return resposta
            except SessaoInativa:
                return _json({"erro": "Sessão da interface ausente, expirada ou encerrada.", "sessao_inativa": True,
                              "acao": "Mantenha a página do NodeWatch aberta e repita a ação: a página abre e renova "
                                      "a sessão sozinha. Nada foi processado."}, 403)
            except ErroFiltro as exc:
                return _json({"erro": "Filtro inválido.", "campo": exc.campo, "mensagem": exc.mensagem,
                              "acao": "Corrija o campo indicado e aplique de novo."}, 400)
            except ErroDataset as exc:
                return _json({"erro": "Dataset não aceito.", "problemas": exc.problemas,
                              "acao": exc.problemas[0]["como_corrigir"] if exc.problemas else ""}, exc.status)
            except ErroAnaliseOcupada as exc:
                return _json({"erro": "Já existe uma análise em andamento.", "analise": str(exc),
                              "acao": "Espere a análise terminar ou cancele-a antes de iniciar outra."}, 409)
            except SemResultados:
                return _json({"erro": "Esta análise não tem resultados gravados.",
                              "acao": "Abra outra análise ou inicie uma nova."}, 409)
            except KeyError:
                return _json({"erro": "Não encontrado.", "acao": "Atualize a lista e selecione de novo."}, 404)
            except FileNotFoundError:
                return _json({"erro": "Modelo ou resultado não encontrado no servidor.",
                              "acao": "Confira se o modelo foi treinado (`python -m src.ml.cli treinar`)."}, 503)

        envolvida.__name__ = func.__name__
        return envolvida

    return decorador


def _sid() -> str:
    return request.headers.get(CABECALHO_SESSAO, "")


def _sessao() -> str:
    """Sessão ativa do pedido; sem ela, nada é processado."""
    from src.painel.pipeline import SessaoInativa
    sid = _sid()
    if not _c()["sessoes"].ativa(sid):
        raise SessaoInativa(sid)
    return sid


def _filtros():
    from src.painel.armazenamento import filtros_de_parametros
    return filtros_de_parametros(request.args)


# ---------------------------------------------------------------------------
# Estado e legendas
# ---------------------------------------------------------------------------
@bp.get("/estado")
@_protegido()
def estado():
    from src.ml.exploracao import modelo_resumo
    from src.painel import armazenamento as arm
    from src.painel import datasets as ds
    from src.painel import pipeline as pl
    from src.painel import score as sc
    from src.painel import tipologias as tp

    c = _c()
    resumo = modelo_resumo(c["raiz"])
    lav = (resumo.get("cabecas") or {}).get("lavagem") if resumo.get("disponivel") else None
    return _json({
        "servico": "NodeWatch — painel do analista",
        "modelo": ({"disponivel": True, "versao": lav.get("versao"), "familia": lav.get("familia"),
                    "limiar_alerta": lav.get("limiar_alerta"), "treinado_ate": lav.get("treinado_ate"),
                    "aviso": lav.get("aviso")} if lav else
                   {"disponivel": c.get("modelo") is not None,
                    "motivo": None if c.get("modelo") is not None else resumo.get("motivo", "modelo não encontrado")}),
        "analise_em_andamento": c["analises"].em_andamento(),
        "limites": {"envio_bytes": ds.LIMITE_BYTES, "padroes_bytes": ds.LIMITE_PADROES_BYTES,
                    "extensoes": list(ds.EXTENSOES), "datasets_enviados_guardados": ds.MAX_ENVIADOS,
                    "analises_guardadas": c["analises"].max_analises, "pagina_max": arm.TAMANHO_PAGINA_MAX,
                    "contas_risco": arm.MAX_CONTAS_RISCO,
                    "grafo": {"profundidade_padrao": arm.GRAFO_PROFUNDIDADE_PADRAO,
                              "profundidade_max": arm.GRAFO_PROFUNDIDADE_MAX, "max_nos": arm.GRAFO_MAX_NOS,
                              "max_arestas": arm.GRAFO_MAX_ARESTAS}},
        "faixas": sc.FAIXAS, "aviso_faixas": sc.AVISO_FAIXAS, "score_alerta": sc.SCORE_ALERTA,
        "score": _legenda_score(c["raiz"], lav.get("limiar_alerta") if lav else None),
        "valor_minimo_padrao": VALOR_MINIMO_PADRAO,
        "sessao": {**c["sessoes"].politica(), "cabecalho": CABECALHO_SESSAO,
                   "leitura": (f"Enviar, validar e analisar exigem a sessão desta página. Ela é renovada a cada "
                               f"{int(c['sessoes'].pulso_s)} s; sem sinal da aba por {int(c['sessoes'].ttl_s)} s "
                               "(aba fechada, navegador encerrado ou conexão perdida), a sessão expira e a análise "
                               "para num ponto seguro, ficando parcial. Minimizar ou trocar de aba não encerra a "
                               "sessão. Nada é retomado sozinho.")},
        "acesso": {"origens": "somente a própria página (mesma origem)", "cors_curinga": False},
        "tipologias": [{"tipologia": t, "descricao": tp.DESCRICOES[t]} for t in (*tp.TIPOLOGIAS, tp.NAO_IDENTIFICADO)],
        "status_analise": pl.DESCRICAO_STATUS,
        "etapas": [{"id": i, "nome": n} for i, n, _ in pl.ETAPAS],
        "regra_contas": arm.REGRA_CONTAS,
        "assistente": {"modo": "local", "servico_externo": False,
                       "leitura": "Responde com o glossário, a ajuda e os resultados gravados. Não usa serviço "
                                  "externo e não envia dados do dataset para fora deste computador."},
    })


def _legenda_score(raiz: Path, limiar: Optional[float]) -> Dict[str, Any]:
    """Como ler o score: original 0–1 não calibrado → índice 0–1000, com o limiar e a evidência disponível."""
    from src.ml.exploracao import _PASTAS_RESULTADOS, _primeiro
    from src.painel import score as sc
    saida: Dict[str, Any] = {
        "calibrado": False, "limiar_original": limiar, "score_alerta": sc.SCORE_ALERTA,
        "natureza": ("O modelo devolve um score original de 0 a 1 que não é probabilidade calibrada. O painel o "
                     "converte num índice de 0 a 1000, só para ordenar e separar em faixas: não é probabilidade de "
                     "lavagem nem de fraude."),
        "conversao": ("Linear por partes, ancorada no limiar de alerta do modelo: original 0 → 0; limiar → "
                      f"{sc.SCORE_ALERTA}; 1 → {sc.SCORE_MAX}. Por isso alerta e faixa alta são a mesma coisa."),
        "faixas_no_score_original": (sc.descricao_conversao(limiar)["faixas_no_score_original"]
                                     if limiar and 0 < limiar < 1 else None),
        "evidencia_de_nao_calibracao": None,
    }
    aval, fonte = _primeiro(raiz, "avaliacao_lavagem.json", _PASTAS_RESULTADOS)
    caixas = (((aval or {}).get("teste") or {}).get("calibracao") or {}).get("caixas") or []
    exemplos = [{"de": cx["de"], "ate": cx["ate"], "transacoes": cx["n"], "score_medio": cx["prob_media"],
                 "fracao_rotulada_lavagem": cx["frequencia_observada"]} for cx in caixas if cx.get("n")]
    if exemplos:
        saida["evidencia_de_nao_calibracao"] = {
            "origem": fonte, "caixas": exemplos,
            "leitura": "Na avaliação histórica, o score original médio de cada trecho não coincide com a fração "
                       "de transações rotuladas como lavagem: o score ordena bem, mas não é uma probabilidade."}
    return saida


# ---------------------------------------------------------------------------
# Sessão da interface
# ---------------------------------------------------------------------------
@bp.post("/sessao")
@_protegido()
def sessao_abrir():
    c = _c()
    corpo = request.get_json(silent=True) or {}
    s_ = c["sessoes"].abrir(str(corpo.get("rotulo", "painel do analista")))
    c["registro"].sistema("sessao_aberta", "Sessão da interface aberta", janela_s=c["sessoes"].ttl_s)
    return _json({"sessao": c["sessoes"].resumo(s_.id), "politica": c["sessoes"].politica(),
                  "cabecalho": CABECALHO_SESSAO}, 201)


@bp.post("/sessao/pulso")
@_protegido()
def sessao_pulso():
    c = _c()
    sid = _sid()
    if not c["sessoes"].pulso(sid):
        return _json({"ativa": False, "sessao": c["sessoes"].resumo(sid),
                      "acao": "A sessão expirou ou foi encerrada; a página abre outra. Uma análise que dependia "
                              "dela parou num ponto seguro e não é retomada sozinha."}, 410)
    return _json({"ativa": True, "sessao": c["sessoes"].resumo(sid)})


@bp.post("/sessao/encerrar")
@_protegido()
def sessao_encerrar():
    c = _c()
    ok = c["sessoes"].encerrar(_sid())
    if ok:
        c["registro"].sistema("sessao_encerrada", "Sessão da interface encerrada pela página")
    return _json({"encerrada": ok, "efeito": "a análise iniciada por esta sessão para no próximo ponto seguro e "
                                            "fica parcial; nada é retomado sozinho"})


@bp.get("/sessao")
@_protegido()
def sessao_ver():
    c = _c()
    return _json({"sessao": c["sessoes"].resumo(_sid()), "ativa": c["sessoes"].ativa(_sid()),
                  "politica": c["sessoes"].politica()})


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------
@bp.get("/datasets")
@_protegido()
def datasets_listar():
    return _json({"datasets": _c()["datasets"].listar()})


@bp.post("/datasets")
@_protegido()
def datasets_enviar():
    from src.painel.datasets import ErroDataset, problema
    sid = _sessao()
    sessoes = _c()["sessoes"]
    arquivo = request.files.get("arquivo")
    if arquivo is None or not arquivo.filename:
        raise ErroDataset([problema("nenhum arquivo foi enviado", "Escolha um arquivo .csv ou .zip.")], 400)
    padroes = request.files.get("padroes")
    com_padroes = padroes is not None and bool(padroes.filename)
    reg = _c()["datasets"].enviar(arquivo.stream, arquivo.filename, padroes.stream if com_padroes else None,
                                  padroes.filename if com_padroes else None, ativa=lambda: sessoes.ativa(sid))
    return _json(reg, 201)


@bp.get("/datasets/<did>")
@_protegido()
def datasets_ver(did: str):
    return _json(_c()["datasets"].obter(did))


@bp.post("/datasets/<did>/validar")
@_protegido()
def datasets_validar(did: str):
    sid = _sessao()
    sessoes = _c()["sessoes"]
    return _json(_c()["datasets"].validar(did, ativa=lambda: sessoes.ativa(sid)), 202)


# ---------------------------------------------------------------------------
# Análises
# ---------------------------------------------------------------------------
@bp.get("/analises")
@_protegido()
def analises_listar():
    c = _c()
    return _json({"analises": c["analises"].listar(),
                  "retencao": {"max_analises": c["analises"].max_analises,
                               "leitura": f"Ficam guardadas as {c['analises'].max_analises} análises mais recentes; "
                                          "as mais antigas são apagadas quando uma nova começa."}})


@bp.post("/analises")
@_protegido()
def analises_iniciar():
    sid = _sessao()
    corpo = request.get_json(silent=True) or {}
    did = str(corpo.get("dataset_id") or "")
    if not did:
        return _json({"erro": "Informe o dataset.", "acao": "Selecione um dataset válido e clique em Analisar."}, 400)
    m = _c()["analises"].iniciar(did, sid)
    m["sessao"] = {**m.get("sessao", {}), **_c()["analises"].situacao_sessao(m["id"], sid)}
    return _json(m, 201)


@bp.get("/analises/<aid>")
@_protegido()
def analises_ver(aid: str):
    m = _c()["analises"].obter(aid)  # consulta: não inicia, não retoma e não renova sessão
    if m["status"] == "em_andamento":
        m["sessao"] = {**m.get("sessao", {}), **_c()["analises"].situacao_sessao(aid, _sid())}
    return _json(m)


@bp.post("/analises/<aid>/cancelar")
@_protegido()
def analises_cancelar(aid: str):
    return _json(_c()["analises"].cancelar(aid, _sessao()))


@bp.post("/analises/<aid>/assumir")
@_protegido()
def analises_assumir(aid: str):
    sid = _sessao()
    m = _c()["analises"].assumir(aid, sid)
    if m["status"] == "em_andamento":
        m["sessao"] = {**m.get("sessao", {}), **_c()["analises"].situacao_sessao(aid, sid)}
    return _json(m)


def _aberta(aid: str):
    c = _c()
    m = c["analises"].obter(aid)
    return m, c["analises"].conexao(aid)


@bp.get("/analises/<aid>/visao")
@_protegido("visão geral do recorte")
def analises_visao(aid: str):
    from src.painel import armazenamento as arm
    f = _filtros()
    m, con = _aberta(aid)
    try:
        dados = arm.visao_geral(con, f, m["contagens"]["pontuadas"], m["tipologias"]["disponivel"],
                                m["rotulo"]["disponivel"], m["tipologias"].get("motivo", ""))
    finally:
        con.close()
    dados["analise"] = {"id": aid, "status": m["status"], "parcial": m["resultados"]["parciais"]}
    return _json(dados)


@bp.get("/analises/<aid>/transacoes")
@_protegido("página da tabela")
def analises_transacoes(aid: str):
    from src.painel import armazenamento as arm
    f = _filtros()
    try:
        numero = int(request.args.get("pagina", "1"))
        tamanho = int(request.args.get("tamanho", str(arm.TAMANHO_PAGINA_PADRAO)))
    except ValueError:
        raise arm.ErroFiltro("pagina", "Página e tamanho precisam ser números inteiros.") from None
    _, con = _aberta(aid)
    try:
        dados = arm.pagina(con, f, numero, tamanho, request.args.get("ordenar", "id_exibicao"),
                           request.args.get("direcao", "asc"))
    finally:
        con.close()
    return _json(dados)


@bp.get("/analises/<aid>/transacoes/<int:id_exibicao>")
@_protegido("detalhes da transação")
def analises_detalhe(aid: str, id_exibicao: int):
    from src.painel import armazenamento as arm
    from src.painel import score as sc
    m, con = _aberta(aid)
    try:
        d = arm.detalhe(con, id_exibicao)
    finally:
        con.close()
    return _json({"transacao": d, "modelo": m.get("modelo"), "conversao_score": m.get("conversao_score"),
                  "faixas": sc.FAIXAS, "aviso_faixas": sc.AVISO_FAIXAS,
                  "rotulo_disponivel": m["rotulo"]["disponivel"], "tipologias_disponiveis": m["tipologias"]["disponivel"],
                  "motivo_sem_tipologias": m["tipologias"].get("motivo", ""),
                  "dataset": {"nome": m["dataset"]["nome"], "colunas": m["dataset"]["colunas"]}})


@bp.get("/analises/<aid>/grafo")
@_protegido("grafo da conta")
def analises_grafo(aid: str):
    from src.painel import armazenamento as arm
    f = _filtros()
    pedido = (request.args.get("conta") or "").strip()
    origem_escolha = "conta selecionada" if pedido else None
    if not pedido and f.conta_origem:
        pedido, origem_escolha = f.conta_origem, "filtro Conta de origem"
    if not pedido and f.conta_destino:
        pedido, origem_escolha = f.conta_destino, "filtro Conta de destino"
    try:
        profundidade = int(request.args.get("profundidade", str(arm.GRAFO_PROFUNDIDADE_PADRAO)))
    except ValueError:
        raise arm.ErroFiltro("profundidade", "Saltos: informe um número inteiro.") from None
    m, con = _aberta(aid)
    try:
        if not pedido:
            return _json({"sem_foco": True, "motivo": "Nenhuma conta em foco. Selecione uma conta em Contas de "
                          "maior risco ou preencha o filtro Conta de origem ou Conta de destino."})
        candidatas = arm.resolver_conta(con, pedido)
        if not candidatas:
            return _json({"sem_foco": True, "pedido": pedido,
                          "motivo": f"A conta '{pedido}' não aparece nesta análise."})
        if len(candidatas) > 1:
            return _json({"ambiguo": True, "pedido": pedido, "candidatas": candidatas[:20],
                          "motivo": f"'{pedido}' corresponde a mais de uma conta (bancos diferentes). Escolha uma."})
        dados = arm.grafo(con, f, candidatas[0], profundidade, tem_tipologias=m["tipologias"]["disponivel"])
    finally:
        con.close()
    dados["escolha"] = origem_escolha
    return _json(dados)


# ---------------------------------------------------------------------------
# Painel operacional
# ---------------------------------------------------------------------------
def _vazao_pontuacao(m: Dict[str, Any]) -> Optional[float]:
    """Pontuadas ÷ (atributos + inferência + gravação), com os mesmos tempos que a tela mostra."""
    d = m.get("desempenho", {})
    tempo = sum(d.get(k) or 0 for k in ("tempo_atributos_s", "tempo_inferencia_s", "tempo_gravacao_s"))
    pontuadas = m.get("contagens", {}).get("pontuadas") or 0
    return (pontuadas / tempo) if tempo > 0 and pontuadas else d.get("vazao_transacoes_por_s")


@bp.get("/operacao/desempenho")
@_protegido()
def operacao_desempenho():
    c = _c()
    saida = c["monitor"].leitura()
    saida["latencias"] = c["latencias"].resumo()
    lista = c["analises"].listar(50)
    ativa = c["analises"].em_andamento()
    referencia = ativa or next((a["id"] for a in lista if a["status"] != "em_andamento"), None)
    if referencia:
        m = c["analises"].obter(referencia)
        etapa = next((e for e in m["etapas"] if e["status"] == "em_andamento"), None)
        saida["analise"] = {
            "id": m["id"], "dataset": m["dataset"]["nome"], "status": m["status"],
            "qual": "análise em andamento" if ativa else "última análise encerrada",
            "duracao_total_s": m.get("duracao_s"),
            "decorrido_etapa_s": (etapa.get("progresso") or {}).get("decorrido_s") if etapa else None,
            "etapa_atual": etapa["nome"] if etapa else None,
            "vazao_pontuacao_por_s": _vazao_pontuacao(m),
            "vazao_pontuacao_formula": "transações pontuadas ÷ (tempo de atributos + inferência + gravação): "
                                       "só a etapa de pontuação",
            "vazao_total_por_s": ((m["contagens"].get("pontuadas") or 0) / m["duracao_s"]
                                  if m.get("duracao_s") and m["contagens"].get("pontuadas") else None),
            "vazao_total_formula": "transações pontuadas ÷ duração total da análise (leitura, ordenação, "
                                   "tipologias, pontuação, índices e manifesto)",
            "tempo_pontuacao_s": (sum(m.get("desempenho", {}).get(k) or 0 for k in
                                      ("tempo_atributos_s", "tempo_inferencia_s", "tempo_gravacao_s")) or None),
            "pico_memoria_bytes": m.get("desempenho", {}).get("pico_memoria_processo_na_pontuacao_bytes"),
            "pico_escopo": "processo do NodeWatch, durante a etapa de pontuação",
            "tempos": {k: m.get("desempenho", {}).get(k) for k in
                       ("tempo_atributos_s", "tempo_inferencia_s", "tempo_gravacao_s")},
            "transacoes_pontuadas": m["contagens"].get("pontuadas"),
        }
    else:
        saida["analise"] = None
    return _json(saida)


@bp.get("/operacao/logs")
@_protegido()
def operacao_logs():
    tipo = request.args.get("tipo", "sistema")
    if tipo not in ("sistema", "ml"):
        return _json({"erro": "tipo deve ser sistema ou ml"}, 400)
    try:
        limite = int(request.args.get("limite", "200"))
    except ValueError:
        limite = 200
    return _json({"tipo": tipo, "entradas": _c()["registro"].listar(tipo, limite),
                  "privacidade": "Os logs não guardam contas, linhas do dataset, chaves nem caminhos da máquina."})


def _metricas_do_dataset(aid: str) -> Dict[str, Any]:
    """Métricas no dataset da análise aberta, só quando ele tem rótulo (contagens exatas do SQLite)."""
    from src.painel import score as sc
    c = _c()
    m = c["analises"].obter(aid)
    base = {"analise": aid, "dataset": m["dataset"]["nome"]}
    if not m["rotulo"]["disponivel"]:
        return {**base, "disponivel": False,
                "motivo": "O dataset desta análise não tem rótulo: não há precisão, recall, F1 nem Average "
                          "Precision para ele. As métricas históricas acima não são resultado deste dataset."}
    if not m.get("resultados", {}).get("disponiveis"):
        return {**base, "disponivel": False, "motivo": "A análise ainda não tem resultados gravados."}
    chave = (aid, m["status"], m["contagens"].get("pontuadas"))
    if chave in c["metricas_dataset"]:
        return c["metricas_dataset"][chave]
    con = c["analises"].conexao(aid)
    try:
        r = con.execute(f"SELECT COALESCE(SUM(rotulo = 1 AND score >= {sc.SCORE_ALERTA}), 0) vp, "
                        f"COALESCE(SUM(rotulo = 0 AND score >= {sc.SCORE_ALERTA}), 0) fp, "
                        f"COALESCE(SUM(rotulo = 1 AND score < {sc.SCORE_ALERTA}), 0) fn, COUNT(*) n "
                        "FROM transacoes WHERE rotulo IS NOT NULL").fetchone()
        vp, fp, fn, n = int(r["vp"]), int(r["fp"]), int(r["fn"]), int(r["n"])
        ap = None
        if 0 < vp + fn < n:
            import numpy as np
            from sklearn.metrics import average_precision_score
            dados = np.array(con.execute("SELECT rotulo, score_bruto FROM transacoes WHERE rotulo IS NOT NULL").fetchall())
            ap = float(average_precision_score(dados[:, 0], dados[:, 1]))
    finally:
        con.close()
    p = vp / (vp + fp) if vp + fp else None
    rec = vp / (vp + fn) if vp + fn else None
    saida = {**base, "disponivel": True, "transacoes_com_rotulo": n, "rotuladas_lavagem": vp + fn,
             "alertas": vp + fp, "verdadeiros_positivos": vp, "falsos_positivos": fp, "falsos_negativos": fn,
             "precisao": p, "recall": rec,
             "f1": (2 * p * rec / (p + rec)) if p is not None and rec is not None and p + rec > 0 else None,
             "average_precision": ap, "parcial": m["resultados"]["parciais"],
             "origem": "calculado com o rótulo do próprio dataset, sobre as transações pontuadas nesta análise",
             "leitura": "Vale só para este dataset. Não ajusta o modelo e não substitui a avaliação histórica."}
    c["metricas_dataset"] = {chave: saida}
    return saida


@bp.get("/operacao/metricas")
@_protegido()
def operacao_metricas():
    from src.ml.exploracao import _PASTAS_RESULTADOS, avaliacao_oficial
    c = _c()
    oficial = avaliacao_oficial(c["raiz"]).get("lavagem", {})
    historicas: Dict[str, Any]
    if not oficial.get("disponivel"):
        historicas = {"disponivel": False,
                      "motivo": oficial.get("motivo", "Avaliação do modelo não encontrada neste servidor.")}
    else:
        fonte = oficial["fontes"][0]
        caminho = c["raiz"] / fonte
        data = (datetime.fromtimestamp(caminho.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if caminho.is_file() else None)
        from src.ml.exploracao import modelo_resumo
        lav = (modelo_resumo(c["raiz"]).get("cabecas") or {}).get("lavagem") or {}
        limites = lav.get("limites") or {}
        conjuntos = []
        for nome, rotulo, periodo in (
            ("teste", "Teste (período posterior ao treino e à validação)",
             f"de {limites.get('validacao_ate', '?')} até antes de {limites.get('teste_ate', '?')}"),
            ("cauda", "Cauda (transações após o fim do período regular)",
             f"a partir de {limites.get('inicio_cauda', '?')}"),
        ):
            mod = (oficial.get(nome) or {}).get("modelo")
            if mod:
                conjuntos.append({"id": nome, "nome": rotulo, "periodo": periodo, "transacoes": mod.get("n"),
                                  "rotuladas_lavagem": mod.get("positivos"), "precisao": mod.get("precisao"),
                                  "recall": mod.get("recall"), "f1": mod.get("f1"),
                                  "average_precision": mod.get("average_precision"), "limiar": mod.get("limiar")})
        historicas = {"disponivel": True, "versao_modelo": oficial.get("versao"), "origem": fonte,
                      "arquivo_gravado_em": data, "dados": "IBM AML HI-Small (sintético)",
                      "conjuntos": conjuntos,
                      "ressalva": "Medidas na avaliação do modelo, em dados sintéticos do IBM AML HI-Small. O período "
                                  "de teste já foi consultado mais de uma vez; não é uma avaliação inédita. Outro "
                                  "dataset pode ter outro desempenho."}
    aid = request.args.get("analise") or ""
    do_dataset = _metricas_do_dataset(aid) if aid else {
        "disponivel": False, "motivo": "Nenhuma análise aberta."}
    return _json({
        "historicas": historicas, "do_dataset": do_dataset,
        "legendas": {
            "precisao": "Entre as transações com alerta, a fração rotulada como lavagem.",
            "recall": "Entre as transações rotuladas como lavagem, a fração que recebeu alerta.",
            "f1": "Média harmônica entre precisão e recall.",
            "average_precision": "Resumo da curva precisão × recall em todos os limiares (qualidade da ordenação).",
        },
        "pastas_consultadas": list(_PASTAS_RESULTADOS),
    })


# ---------------------------------------------------------------------------
# Assistente local
# ---------------------------------------------------------------------------
@bp.post("/assistente")
@_protegido()
def assistente():
    from src.painel import armazenamento as arm
    from src.painel import assistente as ast
    corpo = request.get_json(silent=True) or {}
    pergunta = str(corpo.get("pergunta") or "")[:ast.LIMITE_PERGUNTA]
    aid = str(corpo.get("analise_id") or "")
    c = _c()
    manifesto = None
    visao = None
    if aid:
        try:
            manifesto = c["analises"].obter(aid)
        except KeyError:
            manifesto = None
    if manifesto and manifesto.get("resultados", {}).get("disponiveis"):
        filtros = arm.filtros_de_parametros({k: str(v) for k, v in (corpo.get("filtros") or {}).items()})

        def visao() -> Dict[str, Any]:
            con = c["analises"].conexao(aid)
            try:
                return arm.visao_geral(con, filtros, manifesto["contagens"]["pontuadas"],
                                       manifesto["tipologias"]["disponivel"], manifesto["rotulo"]["disponivel"],
                                       manifesto["tipologias"].get("motivo", ""))
            finally:
                con.close()

    resposta = ast.responder(pergunta, manifesto, visao)
    resposta["modo"] = "local (sem serviço externo)"
    return _json(resposta)
