"""API de eventos, sessões, análise de datasets e previsão sob demanda (Blueprint ``/api/ml``).

Complementa ``src/api_ml.py`` (exploração, só leitura). Aqui o modelo salvo é
carregado **uma vez por processo** e usado para gerar previsões novas; nada é
treinado nem reajustado.

**Autorização por sessão.** Toda rota que processa registros novos exige o
cabeçalho ``X-NodeWatch-Sessao`` com uma sessão ativa da interface (aberta por
``POST /api/ml/sessao`` e renovada por pulsos). Sem ela: HTTP 403, nada roda em
segundo plano. Iniciar o servidor, abrir a interface ou consultar status não
inicia nem retoma processamento.

Rotas:
    POST /api/ml/sessao                         abre uma sessão (uma por aba)
    POST /api/ml/sessao/pulso                   renova a sessão
    POST /api/ml/sessao/encerrar                encerra a sessão (o trabalho dela pausa)
    GET  /api/ml/sessao                         situação da sessão
    GET  /api/ml/eventos/status                 estado, fila, registro, bloqueio, replays (sem efeitos)
    GET  /api/ml/eventos/contratos              envelope e esquemas aceitos
    POST /api/ml/eventos/iniciar                [sessão] recupera (se preciso) e assume o processamento
    POST /api/ml/eventos/pausar                 [sessão] para de consumir a fila (eventos aceitos ficam)
    POST /api/ml/eventos                        [sessão responsável] ingestão durável (até 5.000)
    GET  /api/ml/eventos/consulta?id=tx:...     situação de um evento pela identidade
    POST /api/ml/eventos/fechar                 [sessão] fecha os minutos financeiros abertos (forçado)
    GET  /api/ml/eventos/recentes               últimas previsões (``dominio=rede|lavagem|rejeicoes``)
    POST /api/ml/eventos/replay                 [sessão] replay histórico (iniciar|pausar|retomar|parar)
    POST /api/ml/eventos/salvar                 [sessão] grava o instantâneo
    POST /api/ml/eventos/bloqueio/repetir       [sessão] repete os eventos bloqueados por falha
    POST /api/ml/eventos/bloqueio/descartar     [sessão] descarta-os (fica gravado no registro)
    POST /api/ml/eventos/descartar              [sessão] apaga estado, registro e saídas de eventos
    GET  /api/ml/eventos/laboratorio            último relatório do laboratório de simulação
    POST /api/ml/eventos/laboratorio            [sessão] executa o laboratório (SIMULAÇÃO)
    POST /api/ml/prever/rede                    [sessão] previsão síncrona de medições ``rede_v1``
    POST /api/ml/prever/rede/csv                [sessão] previsões de um CSV ``rede_v1``
    GET  /api/ml/analises                       análises de datasets e formatos aceitos
    POST /api/ml/analises                       [sessão] seleciona e valida um dataset (não analisa)
    GET  /api/ml/analises/<id>                  progresso e resultados de uma análise
    POST /api/ml/analises/<id>/<acao>           [sessão] iniciar | retomar | pausar | cancelar
"""

from __future__ import annotations

import json
import queue
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from flask import Blueprint, jsonify, request

_RAIZ = Path(__file__).resolve().parent.parent
MAX_EVENTOS_POR_PEDIDO = 5_000
MAX_MEDICOES_SINCRONAS = 1_000
VELOCIDADES = (0, 20, 100, 500, 2000)
CABECALHO_SESSAO = "X-NodeWatch-Sessao"

bp = Blueprint("ml_eventos", __name__, url_prefix="/api/ml")
_trava = threading.Lock()
_ctx: Dict[str, Any] = {}


def _novo_ctx(raiz: Path, modelo=None, config=None, sessoes=None) -> Dict[str, Any]:
    from src.ml.sessoes import GerenciadorSessoes
    return {"raiz": Path(raiz), "modelo": modelo, "servico": None, "replays": {}, "config": config,
            "laboratorio": None, "sessoes": sessoes or GerenciadorSessoes(), "responsavel": None,
            "analises": None}


def configurar(raiz: Path, modelo=None, config=None, sessoes=None) -> None:
    """Troca raiz/modelo/sessões (testes). Para o serviço atual, se houver."""
    with _trava:
        if _ctx:
            _encerrar_sem_trava()
        _ctx.clear()
        _ctx.update(_novo_ctx(raiz, modelo, config, sessoes))


def _encerrar_sem_trava() -> None:
    for r in _ctx.get("replays", {}).values():
        r.parar()
    if _ctx.get("servico") is not None:
        _ctx["servico"].parar(salvar=True)


def encerrar() -> None:
    with _trava:
        if _ctx:
            _encerrar_sem_trava()


def sessoes():
    if not _ctx:
        configurar(_RAIZ)
    return _ctx["sessoes"]


def _modelo():
    if not _ctx:
        configurar(_RAIZ)
    with _trava:
        if _ctx["modelo"] is None:
            from src.ml.modelos import NOME_ARTEFATO, ModeloUnificado
            from src.ml import provisionamento
            pasta = _ctx["raiz"] / "artefatos_ml"
            # Instalação limpa: o modelo vem de modelos/ (versionado) e é verificado antes de carregar.
            if not (pasta / NOME_ARTEFATO).is_file() and \
                    (_ctx["raiz"] / provisionamento.PASTA_DISTRIBUIDA / provisionamento.NOME_MANIFESTO).is_file():
                provisionamento.garantir_modelo(_ctx["raiz"])
            _ctx["modelo"] = ModeloUnificado.carregar(pasta)
        return _ctx["modelo"]


def _servico():
    """Serviço único do processo. Criá-lo não processa nem recupera nada."""
    modelo = _modelo()
    with _trava:
        if _ctx["servico"] is None:
            import os
            from src.ml.servico_eventos import Configuracao, ServicoEventos
            cfg = _ctx["config"] or Configuracao(
                atraso_permitido_min=int(os.environ.get("NODEWATCH_ATRASO_MIN", "0")))
            _ctx["servico"] = ServicoEventos(
                modelo, _ctx["raiz"] / "artefatos_ml" / "previsoes", _ctx["raiz"] / "artefatos_ml" / "estado_eventos",
                cfg, autorizado=lambda: _ctx["sessoes"].ativa(_ctx["responsavel"]))
        return _ctx["servico"]


def analises():
    if not _ctx:
        configurar(_RAIZ)
    with _trava:
        if _ctx["analises"] is None:
            from src.ml.analises import GerenciadorAnalises
            _ctx["analises"] = GerenciadorAnalises(_ctx["raiz"], _modelo, _ctx["sessoes"].ativa)
        return _ctx["analises"]


def _json(dados: Any, status: int = 200):
    from src.ml.exploracao import para_json
    return jsonify(para_json(dados)), status


class SemSessao(PermissionError):
    pass


def _sessao() -> str:
    """Sessão ativa do pedido; sem ela, nada é processado."""
    sid = request.headers.get(CABECALHO_SESSAO, "")
    if not sessoes().ativa(sid):
        raise SemSessao(sid)
    return sid


def _protegido(func: Callable) -> Callable:
    def envolvido(*args, **kwargs):
        from src.ml.analises import ErroAnalise
        from src.ml.servico_eventos import ErroEstado
        try:
            return func(*args, **kwargs)
        except SemSessao:
            return _json({"erro": "Sessão da interface ausente, expirada ou encerrada.",
                          "acao": "Abra o NodeWatch no navegador (a página cria e renova a sessão) e use a ação "
                                  "de lá; produtores externos enviam o cabeçalho X-NodeWatch-Sessao da sessão "
                                  "responsável. Nenhum processamento foi iniciado."}, 403)
        except PermissionError as exc:
            return _json({"erro": str(exc), "acao": "Use uma sessão ativa da interface."}, 403)
        except ErroEstado as exc:
            return _json({"erro": str(exc), "acao": "Veja o status em Eventos e use Recuperar/Retomar."}, 409)
        except ErroAnalise as exc:
            return _json({"erro": "Dataset não aceito.", "problemas": exc.problemas, "acao": exc.acao}, 422)
        except FileNotFoundError as exc:
            return _json({"erro": "Modelo ou arquivo não encontrado.", "detalhe": str(exc),
                          "acao": "Treine com `python -m src.ml.cli treinar --tarefa todas` ou confira o caminho."}, 503)
        except ImportError as exc:
            return _json({"erro": "Dependências de ML ausentes.", "detalhe": str(exc),
                          "acao": "Instale requirements-ml.txt."}, 503)
        except KeyError as exc:
            return _json({"erro": f"Não encontrado: {exc}"}, 404)
        except ValueError as exc:
            problemas = getattr(exc, "problemas", None) or [str(exc)]
            return _json({"erro": "Entrada inválida.", "problemas": problemas}, 422)
    envolvido.__name__ = func.__name__
    return envolvido


def _historico_configurado() -> Optional[Path]:
    try:
        from src.ml.config import carregar_config
        caminho = carregar_config()["financeiro"].get("transacoes")
    except Exception:  # sem config local
        return None
    return Path(caminho) if caminho and Path(caminho).is_file() else None


def _fontes_replay() -> Dict[str, Optional[Path]]:
    exemplos = _ctx["raiz"] / "artefatos_ml" / "exemplos"
    rede = exemplos / "rede_teste_sem_rotulos.csv"
    fin = exemplos / "hismall_2022-09-10_sem_rotulo.csv"
    return {"rede": rede if rede.is_file() else None, "financeiro": fin if fin.is_file() else None}


def _assumir(sid: str):
    """Ação explícita: recupera o estado anterior (se houver) e torna ``sid`` a sessão responsável."""
    s = _servico()
    if not s.aberto:
        s.recuperar()
    _ctx["responsavel"] = sid
    s.iniciar()
    return s


# ---------------------------------------------------------------------------
# Sessões
# ---------------------------------------------------------------------------
@bp.post("/sessao")
def sessao_abrir():
    corpo = request.get_json(silent=True) or {}
    s = sessoes().abrir(str(corpo.get("rotulo", "")))
    return _json({"sessao": sessoes().resumo(s.id), "politica": sessoes().politica(), "cabecalho": CABECALHO_SESSAO})


@bp.post("/sessao/pulso")
def sessao_pulso():
    sid = request.headers.get(CABECALHO_SESSAO, "")
    if not sessoes().pulso(sid):
        return _json({"ativa": False, "sessao": sessoes().resumo(sid),
                      "acao": "A sessão expirou ou foi encerrada; a página abre outra. Trabalhos dela ficam "
                              "pausados até serem retomados explicitamente."}, 410)
    return _json({"ativa": True, "sessao": sessoes().resumo(sid)})


@bp.post("/sessao/encerrar")
def sessao_encerrar():
    sid = request.headers.get(CABECALHO_SESSAO, "")
    ok = sessoes().encerrar(sid)
    return _json({"encerrada": ok, "efeito": "o que esta sessão processava para no próximo ponto seguro "
                                            "(checkpoint gravado; resultados ficam parciais até nova retomada)"})


@bp.get("/sessao")
def sessao_ver():
    sid = request.headers.get(CABECALHO_SESSAO, "")
    return _json({"sessao": sessoes().resumo(sid), "politica": sessoes().politica(),
                  "responsavel_eventos": _ctx.get("responsavel") == sid})


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------
@bp.get("/eventos/status")
@_protegido
def status():
    s = _servico()
    fontes = _fontes_replay()
    hist = _historico_configurado()
    st = s.status()
    replays = {k: r.status() for k, r in _ctx["replays"].items()}
    for fonte, arquivo in fontes.items():  # replay restaurado de um instantâneo, ainda sem objeto
        n = (st.get("replay_processado") or {}).get(f"{fonte}:{arquivo.name}" if arquivo else "")
        if fonte not in replays and n:
            replays[fonte] = {"fonte": fonte, "arquivo": arquivo.name, "situacao": "parado", "processados": n,
                              "total": None, "progresso": None, "modo": "replay_historico",
                              "mensagem": f"{n} eventos deste arquivo já estão no estado; iniciar continua de "
                                          "onde parou (para refazer do zero, descarte o estado)"}
    sid = request.headers.get(CABECALHO_SESSAO, "")
    resp = _ctx["responsavel"]
    return _json({
        "servico": st,
        "responsavel": {"definida": bool(resp), "ativa": sessoes().ativa(resp), "e_esta_sessao": bool(resp and resp == sid)},
        "replays": replays,
        "fontes_replay": {k: (v.name if v else None) for k, v in fontes.items()},
        "historico_financeiro": {"disponivel": hist is not None, "arquivo": hist.name if hist else None,
                                 "leitura": "transações do HI-Small anteriores ao início do replay (ml_config.local.toml)"},
        "velocidades": VELOCIDADES,
        "laboratorio_disponivel": fontes["rede"] is not None,
    })


@bp.get("/eventos/contratos")
def contratos():
    from src.ml.eventos import descricao_contratos
    return _json(descricao_contratos())


@bp.post("/eventos/iniciar")
@_protegido
def iniciar_eventos():
    sid = _sessao()
    s = _assumir(sid)
    return _json({"ok": True, "restaurado": s.restaurado, "responsavel": "esta sessão"})


@bp.post("/eventos/pausar")
@_protegido
def pausar_eventos():
    _sessao()
    for r in _ctx["replays"].values():
        r.pausar()
    _ctx["responsavel"] = None
    return _json({"ok": True, "efeito": "o trabalhador para de consumir; eventos aceitos continuam no registro"})


@bp.post("/eventos")
@_protegido
def ingerir():
    sid = _sessao()
    s = _servico()
    if _ctx["responsavel"] != sid or not s.ativo():
        return _json({"erro": "O processamento de eventos não está iniciado por esta sessão.",
                      "acao": "Na área Eventos, use Iniciar processamento (ou Assumir) e envie com o cabeçalho "
                              "da sessão responsável."}, 409)
    corpo = request.get_json(silent=True)
    if isinstance(corpo, dict):
        brutos = corpo.get("eventos")
        origem, modo = str(corpo.get("origem") or "api"), str(corpo.get("modo") or "novo_evento")
    else:
        brutos, origem, modo = corpo, "api", "novo_evento"
    if not isinstance(brutos, list) or not brutos:
        return _json({"erro": "Corpo inválido.", "acao": 'Envie JSON {"eventos": [...]} com ao menos um evento.'}, 400)
    if len(brutos) > MAX_EVENTOS_POR_PEDIDO:
        return _json({"erro": f"Mais de {MAX_EVENTOS_POR_PEDIDO} eventos num pedido.",
                      "acao": "Divida em pedidos menores."}, 413)
    r = s.submeter(brutos, origem, modo)
    cheia = any(x["motivo"] == "fila_cheia" for x in r["recusados"])
    resp = _json(r, 429 if cheia else 202)
    if cheia:
        resp[0].headers["Retry-After"] = "1"
    return resp


@bp.get("/eventos/consulta")
@_protegido
def consultar():
    ident = request.args.get("id", "")
    return _json(_servico().consultar(ident))


@bp.post("/eventos/fechar")
@_protegido
def fechar():
    _sessao()
    return _json(_servico().fechar_minutos(origem="interface"))


@bp.get("/eventos/recentes")
@_protegido
def recentes():
    dominio = request.args.get("dominio", "lavagem")
    n = max(1, min(int(request.args.get("n", 50)), 200))
    s = _servico()
    if dominio not in ("rede", "lavagem", "rejeicoes"):
        return _json({"erro": "dominio deve ser rede, lavagem ou rejeicoes"}, 400)
    with s.trava:
        linhas = list(s.recentes[dominio])[-n:]
    if dominio == "rejeicoes":
        with s._trava_ingestao:
            linhas = (linhas + list(s.rejeicoes_api))[-n:]
    return _json({"dominio": dominio, "linhas": list(reversed(linhas))})


@bp.post("/eventos/replay")
@_protegido
def replay():
    from src.ml.replay import ReplayHistorico
    sid = _sessao()
    corpo = request.get_json(silent=True) or {}
    fonte, acao = corpo.get("fonte"), corpo.get("acao")
    if fonte not in ("rede", "financeiro") or acao not in ("iniciar", "pausar", "retomar", "parar"):
        return _json({"erro": "Use fonte rede|financeiro e acao iniciar|pausar|retomar|parar."}, 400)
    arquivo = _fontes_replay()[fonte]
    if arquivo is None:
        return _json({"erro": f"Arquivo de exemplo de {fonte} não encontrado.",
                      "acao": "Gere com `python -m src.ml.cli exemplos`."}, 404)
    r = _ctx["replays"].get(fonte)
    if acao in ("iniciar", "retomar"):
        s = _assumir(sid)  # ação explícita: esta sessão passa a ser a responsável
        if acao == "iniciar":
            vel = float(corpo.get("eventos_por_segundo") or 0)
            if vel < 0 or vel > 100_000:
                return _json({"erro": "eventos_por_segundo deve estar entre 0 (máximo) e 100000."}, 400)
            historico = _historico_configurado() if (fonte == "financeiro" and corpo.get("usar_historico")) else None
            if r is not None and r._thread and r._thread.is_alive():
                r.eventos_por_segundo = vel
                r.iniciar()
            else:
                r = ReplayHistorico(s, fonte, arquivo, vel, historico)
                _ctx["replays"][fonte] = r
                r.iniciar()
        elif r is None:
            return _json({"erro": "Nenhum replay desta fonte."}, 409)
        else:
            r.iniciar()
    elif r is None:
        return _json({"erro": "Nenhum replay desta fonte."}, 409)
    elif acao == "pausar":
        r.pausar()
    else:
        r.parar()
    return _json(r.status())


@bp.post("/eventos/salvar")
@_protegido
def salvar():
    _sessao()
    return _json(_servico().salvar_estado() or {})


@bp.post("/eventos/bloqueio/<acao>")
@_protegido
def bloqueio(acao: str):
    _sessao()
    s = _servico()
    if acao == "repetir":
        return _json({"ok": s.repetir_bloqueados()})
    if acao == "descartar":
        return _json(s.descartar_bloqueados(origem="interface"))
    return _json({"erro": "acao deve ser repetir ou descartar"}, 400)


@bp.post("/eventos/descartar")
@_protegido
def descartar():
    _sessao()
    s = _servico()
    for r in _ctx["replays"].values():
        r.parar()
    _ctx["replays"] = {}
    return _json(s.descartar())


@bp.get("/eventos/laboratorio")
@_protegido
def laboratorio_ultimo():
    caminho = _ctx["raiz"] / "artefatos_ml" / "simulacao" / "laboratorio.json"
    if _ctx["laboratorio"] is None and caminho.is_file():
        _ctx["laboratorio"] = json.loads(caminho.read_text(encoding="utf-8"))
    return _json({"relatorio": _ctx["laboratorio"]})


@bp.post("/eventos/laboratorio")
@_protegido
def laboratorio_executar():
    from src.ml.simulacao import executar_laboratorio
    _sessao()
    _ctx["laboratorio"] = executar_laboratorio(_modelo(), _ctx["raiz"])
    return _json({"relatorio": _ctx["laboratorio"]})


# ---------------------------------------------------------------------------
# Previsão de rede sob demanda
# ---------------------------------------------------------------------------
@bp.post("/prever/rede")
@_protegido
def prever_rede_json():
    import pandas as pd

    from src.ml import eventos as ev
    from src.ml.previsao import tabela_previsoes_rede

    _sessao()
    corpo = request.get_json(silent=True)
    medicoes = corpo.get("medicoes") if isinstance(corpo, dict) else corpo
    if isinstance(medicoes, dict):
        medicoes = [medicoes]
    if not isinstance(medicoes, list) or not medicoes:
        return _json({"erro": 'Envie {"medicoes": [...]} com medições rede_v1 já preparadas.'}, 400)
    if len(medicoes) > MAX_MEDICOES_SINCRONAS:
        return _json({"erro": f"Até {MAX_MEDICOES_SINCRONAS} medições por pedido; para mais, use o CSV."}, 413)
    cab = _modelo().cabeca("estado_rede")
    recebido = ev.agora()
    linhas, recusadas = [], []
    for i, m in enumerate(medicoes):
        try:
            linhas.append(ev.normalizar_medicao_rede(m if isinstance(m, dict) else {}))
        except ev.ErroEvento as exc:
            recusadas.append({"posicao": i, "problemas": exc.problemas})
    if linhas:
        df = pd.DataFrame(linhas)
        exigir = ["classe_atual"] if cab.usa_classe_atual else []
        boas, ruins = ev.validar_lote_rede(df, exigir)
        recusadas += [{"posicao": None, "id": f"{df.iloc[i]['id_fluxo']}@{df.iloc[i]['timestamp']}",
                       "problemas": p} for i, p in ruins]
        df = boas.reset_index(drop=True)
    else:
        df = pd.DataFrame()
    previsoes = []
    tempo_ms = 0.0
    if len(df):
        df.insert(0, "linha_origem", range(len(df)))
        df.insert(0, "arquivo_origem", "api:prever/rede")
        saida, _ = tabela_previsoes_rede(cab, df)
        processado = ev.agora()
        for r in saida.to_dict("records"):
            previsoes.append({
                "id": f"{r['id_fluxo']}@{r['timestamp_previsao']}",
                "id_fluxo": r["id_fluxo"],
                "instante_medicao_utc": ev.iso(r["timestamp_previsao"]),
                "processado_em_utc": ev.iso(processado),
                "horizonte": r["horizonte"],
                "classe_prevista": r["classe_prevista"],
                "probabilidades": {c: r[f"prob_{c}"] for c in ("OK", "RISCO", "FALHA")},
                "score_alerta_rede": r["score_alerta_rede"],
                "alerta_rede": bool(r["alerta_rede"]),
                "limiar_alerta": r["limiar_alerta"],
                "versao_modelo": r["versao_modelo"],
            })
        tempo_ms = 1000 * (processado - recebido)
    return _json({"previsoes": previsoes, "recusadas": recusadas, "tempo_servidor_ms": tempo_ms,
                  "aviso": "Estado previsto da próxima medição do fluxo; não é fraude."},
                 200 if previsoes or not recusadas else 422)


_NOME = re.compile(r"[^A-Za-z0-9_-]+")


@bp.post("/prever/rede/csv")
@_protegido
def prever_rede_csv():
    from src.ml.esquemas import ErroEsquema
    from src.ml.exploracao import LIMITE_IMPORTACAO_BYTES
    from src.ml.previsao import prever_rede

    _sessao()
    arquivo = request.files.get("arquivo")
    if arquivo is None or not arquivo.filename:
        return _json({"erro": "Envie o CSV no campo 'arquivo'."}, 400)
    conteudo = arquivo.read()
    if len(conteudo) > LIMITE_IMPORTACAO_BYTES:
        return _json({"erro": f"Arquivo maior que {LIMITE_IMPORTACAO_BYTES / 1e6:.0f} MB.",
                      "acao": "Use Analisar dataset (até 256 MB) ou a CLI."}, 413)
    base = _NOME.sub("_", Path(arquivo.filename).stem)[:60].strip("_") or "entrada"
    with tempfile.TemporaryDirectory() as tmp:
        entrada = Path(tmp) / f"{base}.csv"
        entrada.write_bytes(conteudo)
        try:
            saida, rel = prever_rede(_modelo(), [entrada])
        except ErroEsquema as exc:
            return _json({"erro": "O CSV não segue rede_v1.", "problemas": exc.problemas,
                          "acao": "Confira as colunas em docs/ml/DICIONARIO_DADOS.md (seção rede_v1)."}, 422)
    for a in rel["ingestao"]["arquivos"]:
        a["caminho"] = Path(a["caminho"]).name
    rel["gerado_por"] = "interface: Gerar previsões de rede a partir de CSV"
    pasta = _ctx["raiz"] / "artefatos_ml" / "previsoes"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{base}_previsoes_rede.csv"
    saida.to_csv(destino, index=False, encoding="utf-8", lineterminator="\n")
    destino.with_suffix(".relatorio.json").write_text(json.dumps(rel, ensure_ascii=False, indent=1, default=str),
                                                      encoding="utf-8")
    return _json({"fonte_id": f"app:artefatos_ml/previsoes/{destino.name}", "arquivo": destino.name,
                  "linhas_previstas": rel["linhas_previstas"],
                  "colunas_psi_acima_0_25": rel["deriva"].get("colunas_psi_acima_0_25", [])}, 201)


# ---------------------------------------------------------------------------
# Análise de datasets novos
# ---------------------------------------------------------------------------
def _resumo_analise(meta: Dict[str, Any]) -> Dict[str, Any]:
    from src.ml.analises import PASTA_RESULTADOS
    m = dict(meta)
    dono = m.get("sessao_dona")
    m["sessao_dona_ativa"] = sessoes().ativa(dono)
    m["e_desta_sessao"] = bool(dono and dono == request.headers.get(CABECALHO_SESSAO, ""))
    m.pop("sessao_dona", None)  # o identificador de outra aba não é exposto
    am = analises()
    if m.get("deteccao", {}).get("dominio"):
        nome = am._saida(meta).name
        if (am.pasta / nome).is_file():
            m["fonte_id"] = f"app:{PASTA_RESULTADOS.as_posix()}/{nome}"
    return m


@bp.get("/analises")
@_protegido
def analises_listar():
    from src.ml.analises import formatos_suportados
    return _json({"analises": [_resumo_analise(m) for m in analises().listar()], **formatos_suportados(),
                  "politica_sessao": sessoes().politica()})


@bp.post("/analises")
@_protegido
def analises_criar():
    _sessao()
    arquivo = request.files.get("arquivo")
    if arquivo is None or not arquivo.filename:
        return _json({"erro": "Selecione um arquivo (campo 'arquivo')."}, 400)
    hist = request.files.get("historico")
    meta = analises().criar(arquivo.read(), arquivo.filename,
                            hist.read() if hist and hist.filename else None, hist.filename if hist else None)
    return _json(_resumo_analise(meta), 201)


@bp.get("/analises/<aid>")
@_protegido
def analises_ver(aid: str):
    return _json(_resumo_analise(analises().obter(aid)))


@bp.post("/analises/<aid>/<acao>")
@_protegido
def analises_acao(aid: str, acao: str):
    sid = _sessao()
    am = analises()
    if acao in ("iniciar", "retomar"):
        return _json(_resumo_analise(am.iniciar(aid, sid)))
    if acao in ("pausar", "cancelar"):
        return _json(_resumo_analise(am.pedir(aid, acao, sid)))
    return _json({"erro": "acao deve ser iniciar, retomar, pausar ou cancelar"}, 400)
