"""API da seção "Machine Learning" do painel (Flask Blueprint ``/api/ml``).

Só lê previsões e resultados já produzidos por ``src/ml``: nenhuma rota treina,
reajusta ou grava modelos. Arquivos importados ficam apenas na memória do
servidor local e somem quando ele é reiniciado.

Rotas:
    GET    /api/ml/status                      dependências, modelo e limites
    GET    /api/ml/fontes                      arquivos de previsão disponíveis
    POST   /api/ml/importar                    importa um CSV de previsões
    DELETE /api/ml/fontes/<id>                 descarta um arquivo importado
    GET    /api/ml/fontes/<id>                 descrição do arquivo (período, campos...)
    GET    /api/ml/fontes/<id>/resumo          indicadores e gráficos (aceita filtros)
    GET    /api/ml/fontes/<id>/registros       página da tabela (filtros, ordenação)
    GET    /api/ml/fontes/<id>/registros/<n>   detalhes de um registro
    GET    /api/ml/fontes/<id>/exportar        CSV dos registros filtrados
    GET    /api/ml/avaliacao                   avaliação oficial (validação e teste)

A seção não depende do Gemini nem do chat Sentinel AI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from flask import Blueprint, Response, jsonify, request

_RAIZ = Path(__file__).resolve().parent.parent

try:  # pandas/numpy/scikit-learn vêm de requirements-ml.txt
    from src.ml import exploracao as _ex
    _ERRO_DEPENDENCIAS: Optional[str] = None
except ImportError as exc:  # pragma: no cover - depende do ambiente
    _ex = None
    _ERRO_DEPENDENCIAS = str(exc)

bp = Blueprint("ml", __name__, url_prefix="/api/ml")
_repositorio = None


def repositorio():
    global _repositorio
    if _repositorio is None:
        _repositorio = _ex.RepositorioFontes(_RAIZ)
    return _repositorio


def configurar(raiz: Path) -> None:
    """Troca a raiz das fontes (usado pelos testes)."""
    global _repositorio
    _repositorio = _ex.RepositorioFontes(Path(raiz))


def _json(dados: Any, status: int = 200):
    return jsonify(_ex.para_json(dados) if _ex else dados), status


def _protegido(func: Callable) -> Callable:
    """Converte os erros previstos em respostas com mensagem e ação."""

    def envolvida(*args, **kwargs):
        if _ex is None:
            return jsonify({
                "erro": "dependências de ML ausentes",
                "problemas": [_ERRO_DEPENDENCIAS],
                "acao": "Instale as dependências com `python -m pip install -r requirements-ml.txt` e reinicie o servidor.",
            }), 503
        try:
            return func(*args, **kwargs)
        except _ex.ErroContrato as exc:
            return _json(exc.para_dict(), 422)
        except _ex.ErroFiltro as exc:
            return _json({"erro": "parâmetro inválido", "problemas": [str(exc)],
                          "acao": "Ajuste os filtros e tente de novo."}, 400)
        except KeyError:
            return _json({"erro": "fonte não encontrada",
                          "problemas": ["o arquivo pedido não está entre as fontes da aplicação "
                                        "(ou foi importado antes de o servidor reiniciar)"],
                          "acao": "Atualize a lista de arquivos e selecione outro."}, 404)

    envolvida.__name__ = func.__name__
    return envolvida


def _filtros(prev):
    return _ex.filtros_de_parametros(request.args, prev.dominio)


@bp.app_errorhandler(413)
def muito_grande(_erro):
    limite = _ex.LIMITE_IMPORTACAO_BYTES / 1e6 if _ex else 64
    return jsonify({"erro": "arquivo grande demais",
                    "problemas": [f"o envio passou do limite de importação ({limite:.0f} MB)"],
                    "acao": "Gere o arquivo com a CLI numa das pastas previstas (por exemplo, "
                            "artefatos_ml/previsoes/) e selecione-o na lista de arquivos da aplicação."}), 413


@bp.get("/status")
def status():
    base: Dict[str, Any] = {
        "servico": "NodeWatch ML (somente leitura)",
        "dependencias_ok": _ex is not None,
        "erro_dependencias": _ERRO_DEPENDENCIAS,
    }
    if _ex is None:
        return jsonify(base)
    base.update({
        "modelo": _ex.modelo_resumo(_RAIZ if _repositorio is None else repositorio().raiz),
        "limites": {
            "importacao_bytes": _ex.LIMITE_IMPORTACAO_BYTES,
            "exportacao_linhas": _ex.LIMITE_EXPORTACAO_LINHAS,
            "pagina_max": _ex.TAMANHO_PAGINA_MAX,
            "importados_em_memoria": _ex.MAX_IMPORTADOS,
        },
        "pastas_previstas": [{"pasta": p, "procedencia": d} for p, d in _ex.PASTAS_PREVISOES],
        "contratos": {d: _ex.CONTRATOS[d].id for d in _ex.DOMINIOS},
    })
    return _json(base)


@bp.get("/fontes")
@_protegido
def fontes():
    return _json({"fontes": repositorio().listar()})


@bp.post("/importar")
@_protegido
def importar():
    arquivo = request.files.get("arquivo")
    if arquivo is None or not arquivo.filename:
        return _json({"erro": "nenhum arquivo enviado", "problemas": ["o formulário não trouxe o campo 'arquivo'"],
                      "acao": "Escolha um arquivo CSV de previsões."}, 400)
    dominio = request.form.get("dominio") or None
    if dominio not in (None, *_ex.DOMINIOS):
        raise _ex.ErroFiltro("domínio inválido: use 'rede' ou 'lavagem'.")
    conteudo = arquivo.read(_ex.LIMITE_IMPORTACAO_BYTES + 1)
    prev = repositorio().importar(conteudo, arquivo.filename,
                                  amostra_declarada=request.form.get("amostra") == "1", dominio=dominio)
    return _json(prev.descricao(), 201)


@bp.delete("/fontes/<path:fonte_id>")
@_protegido
def remover(fonte_id: str):
    if not repositorio().remover_importado(fonte_id):
        raise KeyError(fonte_id)
    return _json({"removido": fonte_id})


@bp.get("/fontes/<path:fonte_id>")
@_protegido
def descrever(fonte_id: str):
    return _json(repositorio().obter(fonte_id).descricao())


@bp.get("/fontes/<path:fonte_id>/resumo")
@_protegido
def resumo(fonte_id: str):
    prev = repositorio().obter(fonte_id)
    f = _filtros(prev)
    dados = _ex.resumo(prev, _ex.mascara(prev, f))
    dados["filtros_ativos"] = f.ativos()
    return _json(dados)


@bp.get("/fontes/<path:fonte_id>/registros")
@_protegido
def registros(fonte_id: str):
    prev = repositorio().obter(fonte_id)
    try:
        numero = int(request.args.get("pagina", "1"))
        tamanho = int(request.args.get("tamanho", "50"))
    except ValueError:
        raise _ex.ErroFiltro("Página e tamanho precisam ser números inteiros.") from None
    dados = _ex.pagina(prev, _ex.mascara(prev, _filtros(prev)), request.args.get("ordenar", ""),
                       request.args.get("direcao", "asc"), numero, tamanho)
    return _json(dados)


@bp.get("/fontes/<path:fonte_id>/registros/<int:linha>")
@_protegido
def detalhe(fonte_id: str, linha: int):
    repo = repositorio()
    return _json(_ex.registro(repo.obter(fonte_id), linha, repo.raiz, repo.cache_entradas))


@bp.get("/fontes/<path:fonte_id>/exportar")
@_protegido
def exportar(fonte_id: str):
    prev = repositorio().obter(fonte_id)
    f = _filtros(prev)
    conteudo, nome, meta = _ex.exportar(prev, _ex.mascara(prev, f))
    resposta = Response(conteudo, mimetype="text/csv; charset=utf-8")
    resposta.headers["Content-Disposition"] = f'attachment; filename="{nome}"'
    resposta.headers["X-NodeWatch-Registros"] = str(meta["registros"])
    resposta.headers["X-NodeWatch-Fonte"] = meta["arquivo"]
    resposta.headers["X-NodeWatch-Periodo"] = f"{meta['periodo']['inicio']}/{meta['periodo']['fim']}"
    resposta.headers["Access-Control-Expose-Headers"] = (
        "Content-Disposition, X-NodeWatch-Registros, X-NodeWatch-Fonte, X-NodeWatch-Periodo")
    return resposta


@bp.get("/avaliacao")
@_protegido
def avaliacao():
    return _json(_ex.avaliacao_oficial(repositorio().raiz))
