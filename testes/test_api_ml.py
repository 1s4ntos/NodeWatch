"""Testes da API da seção Machine Learning (src/api_ml.py) e da preservação do painel.

Os arquivos usados são SINTÉTICOS, criados só para os testes.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

pytest.importorskip("flask")
pytest.importorskip("pandas")

from src import api_ml  # noqa: E402
from src.sentinel_ai import app  # noqa: E402
from testes.ml.test_exploracao import csv_lavagem, csv_rede  # noqa: E402


@pytest.fixture
def cliente(tmp_path: Path):
    exemplos = tmp_path / "artefatos_ml" / "exemplos"
    exemplos.mkdir(parents=True)
    (exemplos / "previsoes_rede_exemplo.csv").write_text(csv_rede(n=12), encoding="utf-8")
    (exemplos / "previsoes_lavagem_exemplo.csv").write_text(csv_lavagem(n=10), encoding="utf-8")
    api_ml.configurar(tmp_path)
    app.config["TESTING"] = True
    yield app.test_client()
    api_ml.configurar(Path(api_ml._RAIZ))


REDE = "app:artefatos_ml/exemplos/previsoes_rede_exemplo.csv"


def test_painel_e_rotas_existentes_continuam_funcionando(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and b"NodeWatch" in r.data
    assert cliente.get("/health").get_json()["status"] == "ok"
    assert cliente.get("/assets/vendor/react-18.3.1.production.min.js").status_code == 200


def test_status_funciona_sem_chave_do_gemini(cliente, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = cliente.get("/api/ml/status").get_json()
    assert r["dependencias_ok"] is True
    assert r["contratos"] == {"rede": "previsao_rede_v1", "lavagem": "previsao_lavagem_v1"}


def test_fluxo_fontes_resumo_registros_detalhe_e_exportacao(cliente):
    fontes = cliente.get("/api/ml/fontes").get_json()["fontes"]
    assert {f["dominio"] for f in fontes} == {"rede", "lavagem"}
    r = cliente.get(f"/api/ml/fontes/{REDE}/resumo?classes=RISCO,FALHA&alerta=sim").get_json()
    assert r["total_filtrado"] == 8 and r["filtros_ativos"] == {"alerta": True, "classes": ["RISCO", "FALHA"]}
    pag = cliente.get(f"/api/ml/fontes/{REDE}/registros?classes=RISCO,FALHA&alerta=sim&tamanho=3&pagina=2"
                      "&ordenar=score_alerta_rede&direcao=desc").get_json()
    assert pag["total"] == 8 and pag["pagina"] == 2 and len(pag["linhas"]) == 3
    linha = pag["linhas"][0]["_linha"]
    det = cliente.get(f"/api/ml/fontes/{REDE}/registros/{linha}").get_json()
    assert det["_linha"] == linha and det["entrada"]["disponivel"] is False  # sem arquivo de entrada
    exp = cliente.get(f"/api/ml/fontes/{REDE}/exportar?classes=RISCO,FALHA&alerta=sim")
    assert exp.status_code == 200
    assert exp.headers["X-NodeWatch-Registros"] == "8"
    assert "previsoes_rede_exemplo" in exp.headers["Content-Disposition"]
    assert exp.data.decode().count("\n") == 9  # cabeçalho + 8 registros


def test_importacao_valida_invalida_e_descarte(cliente):
    ok = cliente.post("/api/ml/importar", content_type="multipart/form-data",
                      data={"arquivo": (io.BytesIO(csv_lavagem(n=6).encode()), "teste_lavagem.csv"), "amostra": "1"})
    assert ok.status_code == 201
    d = ok.get_json()
    assert d["dominio"] == "lavagem" and d["conjunto"]["tipo"] == "amostra" and d["origem"] == "importado"
    assert cliente.get(f"/api/ml/fontes/{d['id']}/resumo").get_json()["total_arquivo"] == 6
    ruim = cliente.post("/api/ml/importar", content_type="multipart/form-data",
                        data={"arquivo": (io.BytesIO(b"a,b\n1,2\n"), "ruim.csv")})
    assert ruim.status_code == 422
    corpo = ruim.get_json()
    assert corpo["problemas"] and corpo["acao"]
    assert cliente.delete(f"/api/ml/fontes/{d['id']}").status_code == 200
    assert cliente.get(f"/api/ml/fontes/{d['id']}/resumo").status_code == 404


def test_erros_de_parametro_e_fonte_desconhecida(cliente):
    r = cliente.get(f"/api/ml/fontes/{REDE}/resumo?inicio=ontem")
    assert r.status_code == 400 and "data" in r.get_json()["problemas"][0]
    assert cliente.get("/api/ml/fontes/app:../src/main.py/resumo").status_code == 404
    assert cliente.get(f"/api/ml/fontes/{REDE}/registros?tamanho=5000").status_code == 400


def test_avaliacao_sem_resultados_informa_ausencia(cliente):
    a = cliente.get("/api/ml/avaliacao").get_json()
    assert a["rede"]["disponivel"] is False and a["rede"]["motivo"]
    assert a["modelo"]["disponivel"] is False
