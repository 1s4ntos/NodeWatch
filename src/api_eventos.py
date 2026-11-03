"""API de eventos e de previsão sob demanda (Flask Blueprint, prefixo ``/api/ml``).

Complementa ``src/api_ml.py`` (exploração, só leitura). Aqui o modelo salvo é
carregado **uma vez por processo** e usado para gerar previsões novas; nada é
treinado nem reajustado.

Rotas:
    GET  /api/ml/eventos/status           fila, trabalhador, estado, latências, replays
    GET  /api/ml/eventos/contratos        envelope e esquemas aceitos
    POST /api/ml/eventos                  ingestão (``{"eventos": [...]}``; até 5.000 por pedido)
    POST /api/ml/eventos/fechar           fecha os minutos financeiros abertos
    GET  /api/ml/eventos/recentes         últimas previsões (``dominio=rede|lavagem|rejeicoes``)
    POST /api/ml/eventos/replay           replay histórico (``fonte``, ``acao``, ``eventos_por_segundo``)
    POST /api/ml/eventos/salvar           grava o instantâneo do estado
    POST /api/ml/eventos/descartar        para tudo e volta ao estado vazio
    GET  /api/ml/eventos/laboratorio      último relatório do laboratório de simulação
    POST /api/ml/eventos/laboratorio      executa o laboratório (SIMULAÇÃO)
    POST /api/ml/prever/rede              previsão síncrona de medições ``rede_v1`` (JSON, até 1.000)
    POST /api/ml/prever/rede/csv          previsões de um CSV ``rede_v1`` → ``artefatos_ml/previsoes``
"""

from __future__ import annotations

import json
import os
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

bp = Blueprint("ml_eventos", __name__, url_prefix="/api/ml")
_trava = threading.Lock()
_ctx: Dict[str, Any] = {"raiz": _RAIZ, "modelo": None, "servico": None, "replays": {}, "erro": None,
                        "config": None, "laboratorio": None}


def configurar(raiz: Path, modelo=None, config=None) -> None:
    """Troca raiz/modelo (testes). Para o serviço atual, se houver."""
    with _trava:
        _encerrar_sem_trava()
        _ctx.update(raiz=Path(raiz), modelo=modelo, servico=None, replays={}, erro=None, config=config,
                    laboratorio=None)


def _encerrar_sem_trava() -> None:
    for r in _ctx["replays"].values():
        r.parar()
    if _ctx["servico"] is not None:
        _ctx["servico"].parar(salvar=True)


def encerrar() -> None:
    with _trava:
        _encerrar_sem_trava()


def _servico():
    """Serviço único do processo (modelo carregado uma vez)."""
    with _trava:
        if _ctx["servico"] is None:
            from src.ml.modelos import ModeloUnificado
            from src.ml.servico_eventos import Configuracao, ServicoEventos

            modelo = _ctx["modelo"]
            if modelo is None:
                modelo = ModeloUnificado.carregar(_ctx["raiz"] / "artefatos_ml")
                _ctx["modelo"] = modelo
            cfg = _ctx["config"] or Configuracao(
                atraso_permitido_min=int(os.environ.get("NODEWATCH_ATRASO_MIN", "0")))
            _ctx["servico"] = ServicoEventos(modelo, _ctx["raiz"] / "artefatos_ml" / "previsoes",
                                             _ctx["raiz"] / "artefatos_ml" / "estado_eventos", cfg)
            _ctx["servico"].iniciar()
        return _ctx["servico"]


def _json(dados: Any, status: int = 200):
    from src.ml.exploracao import para_json
    return jsonify(para_json(dados)), status


def _protegido(func: Callable) -> Callable:
    def envolvido(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as exc:
            return _json({"erro": "Modelo ou arquivo não encontrado.", "detalhe": str(exc),
                          "acao": "Treine com `python -m src.ml.cli treinar --tarefa todas` ou confira o caminho."}, 503)
        except ImportError as exc:
            return _json({"erro": "Dependências de ML ausentes.", "detalhe": str(exc),
                          "acao": "Instale requirements-ml.txt."}, 503)
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
                              "mensagem": f"{n} eventos deste arquivo já estão no estado restaurado; iniciar "
                                          "continua de onde parou (para refazer do zero, descarte o estado)"}
    return _json({
        "servico": st,
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


@bp.post("/eventos")
@_protegido
def ingerir():
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
    r = _servico().submeter(brutos, origem, modo)
    cheia = any(x["motivo"] == "fila_cheia" for x in r["recusados"])
    resp = _json(r, 429 if cheia else 202)
    if cheia:
        resp[0].headers["Retry-After"] = "1"
    return resp


@bp.post("/eventos/fechar")
@_protegido
def fechar():
    from src.ml import eventos as ev
    import queue
    s = _servico()
    try:
        s.enfileirar(ev.Evento("controle:fechar", "controle:fechar", "controle", "-", 0.0, ev.agora(), "api",
                               "novo_evento", {"acao": "fechar"}), timeout=5)
    except queue.Full:
        return _json({"erro": "Fila cheia.", "acao": "Tente de novo em alguns segundos."}, 429)
    return _json({"ok": True})


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
    corpo = request.get_json(silent=True) or {}
    fonte, acao = corpo.get("fonte"), corpo.get("acao")
    if fonte not in ("rede", "financeiro") or acao not in ("iniciar", "pausar", "retomar", "parar"):
        return _json({"erro": "Use fonte rede|financeiro e acao iniciar|pausar|retomar|parar."}, 400)
    s = _servico()
    arquivo = _fontes_replay()[fonte]
    if arquivo is None:
        return _json({"erro": f"Arquivo de exemplo de {fonte} não encontrado.",
                      "acao": "Gere com `python -m src.ml.cli exemplos`."}, 404)
    r = _ctx["replays"].get(fonte)
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
    elif acao == "pausar":
        r.pausar()
    elif acao == "retomar":
        r.iniciar()
    else:
        r.parar()
    return _json(r.status())


@bp.post("/eventos/salvar")
@_protegido
def salvar():
    return _json(_servico().salvar_estado() or {})


@bp.post("/eventos/descartar")
@_protegido
def descartar():
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
    s = _servico()
    _ctx["laboratorio"] = executar_laboratorio(s.modelo, _ctx["raiz"])
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

    corpo = request.get_json(silent=True)
    medicoes = corpo.get("medicoes") if isinstance(corpo, dict) else corpo
    if isinstance(medicoes, dict):
        medicoes = [medicoes]
    if not isinstance(medicoes, list) or not medicoes:
        return _json({"erro": 'Envie {"medicoes": [...]} com medições rede_v1 já preparadas.'}, 400)
    if len(medicoes) > MAX_MEDICOES_SINCRONAS:
        return _json({"erro": f"Até {MAX_MEDICOES_SINCRONAS} medições por pedido; para mais, use o CSV."}, 413)
    s = _servico()
    recebido = ev.agora()
    linhas, recusadas = [], []
    for i, m in enumerate(medicoes):
        try:
            linhas.append(ev.normalizar_medicao_rede(m if isinstance(m, dict) else {}))
        except ev.ErroEvento as exc:
            recusadas.append({"posicao": i, "problemas": exc.problemas})
    if linhas:
        df = pd.DataFrame(linhas)
        exigir = ["classe_atual"] if s.cab_rede.usa_classe_atual else []
        boas, ruins = ev.validar_lote_rede(df, exigir)
        recusadas += [{"posicao": None, "id": f"{df.iloc[i]['id_fluxo']}@{df.iloc[i]['timestamp']}",
                       "problemas": p} for i, p in ruins]
        df = boas.reset_index(drop=True)
    else:
        df = pd.DataFrame()
    previsoes = []
    if len(df):
        df.insert(0, "linha_origem", range(len(df)))
        df.insert(0, "arquivo_origem", "api:prever/rede")
        saida, _ = tabela_previsoes_rede(s.cab_rede, df)
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
    else:
        tempo_ms = 0.0
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

    arquivo = request.files.get("arquivo")
    if arquivo is None or not arquivo.filename:
        return _json({"erro": "Envie o CSV no campo 'arquivo'."}, 400)
    conteudo = arquivo.read()
    if len(conteudo) > LIMITE_IMPORTACAO_BYTES:
        return _json({"erro": f"Arquivo maior que {LIMITE_IMPORTACAO_BYTES / 1e6:.0f} MB.",
                      "acao": "Use a CLI: python -m src.ml.cli prever --tarefa estado_rede ..."}, 413)
    base = _NOME.sub("_", Path(arquivo.filename).stem)[:60].strip("_") or "entrada"
    s = _servico()
    with tempfile.TemporaryDirectory() as tmp:
        entrada = Path(tmp) / f"{base}.csv"
        entrada.write_bytes(conteudo)
        try:
            saida, rel = prever_rede(s.modelo, [entrada])
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
