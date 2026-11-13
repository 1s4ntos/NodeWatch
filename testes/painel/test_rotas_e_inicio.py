"""Rotas e instruções de acesso: / é o painel do analista; /legado é a interface antiga; NODEWATCH_ORIGENS=null é exceção."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

from src import sentinel_ai  # noqa: E402
from src.sentinel_ai import app, linhas_de_inicio  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
EXTERNA = "https://site-externo.example"


@pytest.fixture
def cliente():
    app.config["TESTING"] = True
    return app.test_client()


# -- o que cada rota serve ----------------------------------------------------------------
def test_raiz_serve_o_painel_do_analista(cliente):
    r = cliente.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "<title>NodeWatch — Painel do analista</title>" in html and "assets/painel-app.js" in html
    assert html == (RAIZ / "interface" / "painel.html").read_text(encoding="utf-8")
    assert "Grafos (demonstração)" not in html and "babel" not in html.lower().replace("sem babel", "")


def test_legado_serve_a_interface_antiga(cliente):
    r = cliente.get("/legado")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert html == (RAIZ / "interface" / "index.html").read_text(encoding="utf-8")
    assert "<SecaoML" in html and "'#grafos'" in html and "SentinelChat" in html   # ML antigo, grafos e chat
    assert "painel-app.js" not in html


def test_enderecos_antigos_com_hash_levam_a_interface_antiga():
    html = (RAIZ / "interface" / "painel.html").read_text(encoding="utf-8")
    assert "if (/^#\\/?(ml|grafos)(\\/|$)/.test(location.hash)) location.replace('/legado' + location.hash);" in html


def test_docstrings_das_rotas_dizem_qual_e_a_atual_e_qual_e_a_antiga():
    assert "interface atual" in sentinel_ai.index.__doc__ and "endereço a usar" in sentinel_ai.index.__doc__
    assert "Interface ANTIGA" in sentinel_ai.legado.__doc__ and "Não é o painel do analista" in sentinel_ai.legado.__doc__


# -- mensagens de início ------------------------------------------------------------------
def test_inicio_mostra_o_painel_novo_primeiro_e_marca_a_interface_antiga():
    linhas = linhas_de_inicio("127.0.0.1", 5000, [])
    texto = "\n".join(linhas)
    painel = next(i for i, l in enumerate(linhas) if "Painel do analista" in l)
    antiga = next(i for i, l in enumerate(linhas) if "Interface antiga" in l)
    assert linhas[painel].strip() == ">> Painel do analista (use este): http://127.0.0.1:5000/"
    assert painel < antiga and "nao e o painel do analista" in linhas[antiga]
    # as mensagens de início seguem o resto do arquivo: sem acentos, para não corromper em terminais e logs cp1252
    assert all(l.isascii() for l in linhas)
    assert all("/legado" in l for l in linhas if "#ml" in l)          # nada de "/#ml" na raiz
    assert "http://127.0.0.1:5000/legado " in texto and "Origens extras" not in texto and "[AVISO]" not in texto


def test_inicio_avisa_do_risco_quando_null_esta_liberada():
    linhas = linhas_de_inicio("127.0.0.1", 5000, ["null"])
    texto = "\n".join(linhas)
    assert all(l.isascii() for l in linhas) and all(l.isascii() for l in linhas_de_inicio("0.0.0.0", 5000, []))
    assert "Origens extras liberadas (NODEWATCH_ORIGENS): null" in texto
    assert "iframes sandbox de qualquer site" in texto and "reinicie o servidor sem NODEWATCH_ORIGENS" in texto
    assert "iframes" not in "\n".join(linhas_de_inicio("127.0.0.1", 5000, ["http://a.test"]))


def test_inicio_usa_as_linhas_testadas_e_o_aviso_da_chave_cita_so_o_chat():
    fonte = (RAIZ / "src" / "sentinel_ai.py").read_text(encoding="utf-8")
    principal = fonte[fonte.index('if __name__ == "__main__":'):]
    assert 'print("\\n".join(linhas_de_inicio()))' in principal
    assert "Assistente de duvidas do painel" in principal and "chat da interface antiga" in principal
    assert "funciona sem chave e o assistente responde no modo local" in principal
    assert "Legado:" not in principal and "5000/#ml" not in fonte


@pytest.mark.parametrize("script", ["start_presentation.ps1", "start_presentation.sh"])
def test_scripts_de_apresentacao_mostram_o_endereco_certo(script):
    texto = (RAIZ / script).read_text(encoding="utf-8-sig")
    assert "Painel do analista: http://127.0.0.1:5000/" in texto
    assert "Interface antiga (grafos, ML antigo, chat): http://127.0.0.1:5000/legado" in texto
    assert "5000/#ml" not in texto


# -- documentação --------------------------------------------------------------------------
def test_documentacao_indica_o_painel_em_raiz_e_legado_como_antiga():
    painel = (RAIZ / "docs" / "ui" / "PAINEL_ANALISTA.md").read_text(encoding="utf-8")
    assert "| `http://127.0.0.1:5000/` | **Painel do analista** (interface atual)" in painel
    assert "| `http://127.0.0.1:5000/legado` | **Interface antiga**, só para consulta" in painel
    assert "O jeito recomendado é `http://127.0.0.1:5000/legado`" not in painel
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    assert "| `http://127.0.0.1:5000/` | **Painel do analista** (interface atual)" in readme
    assert "| `http://127.0.0.1:5000/legado` | **Interface antiga**" in readme
    assert "Em `http://127.0.0.1:5000/#ml" not in readme
    chat = (RAIZ / "docs" / "SENTINEL_AI.md").read_text(encoding="utf-8")
    assert "Dashboard: `http://127.0.0.1:5000/`" not in chat and "interface antiga: `http://127.0.0.1:5000/legado`" in chat


def test_documentacao_trata_null_como_excecao_temporaria_com_o_risco():
    painel = (RAIZ / "docs" / "ui" / "PAINEL_ANALISTA.md").read_text(encoding="utf-8")
    trecho = painel[painel.index("**Exceção: abrir a interface antiga como arquivo do disco.**"):painel.index("## Fluxo de uso")]
    assert "Não é um modo normal de acesso" in trecho and "**temporariamente**" in trecho
    assert "iframe" in trecho and "sandbox" in trecho and "**Para desligar:**" in trecho and "Remove-Item Env:NODEWATCH_ORIGENS" in trecho
    assert "vem **desligada**" in painel


# -- origens: padrão e com null ligada ------------------------------------------------------
def test_padrao_sem_origens_extras_recusa_null_e_externa(cliente):
    assert sentinel_ai.ORIGENS_EXTRAS == [] or os.environ.get("NODEWATCH_ORIGENS")
    if os.environ.get("NODEWATCH_ORIGENS"):
        pytest.skip("NODEWATCH_ORIGENS definida no ambiente deste teste")
    for origem in ("null", EXTERNA):
        for metodo, rota in (("get", "/api/painel/estado"), ("get", "/api/ml/status"), ("post", "/api/painel/sessao")):
            r = getattr(cliente, metodo)(rota, headers={"Origin": origem}, json={} if metodo == "post" else None)
            assert r.status_code == 403 and "Access-Control-Allow-Origin" not in r.headers, (origem, rota)
    pre = cliente.options("/api/painel/analises", headers={"Origin": "null", "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 403 and "Access-Control-Allow-Origin" not in pre.headers
    assert cliente.get("/api/painel/estado").status_code == 200        # a própria página (sem Origin) continua aceita


_COM_NULL = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from src import sentinel_ai
c = sentinel_ai.app.test_client()
def ver(metodo, rota, origem, **kw):
    r = getattr(c, metodo)(rota, headers={"Origin": origem, **kw.pop("headers", {})}, **kw)
    return [r.status_code, r.headers.get("Access-Control-Allow-Origin")]
print(json.dumps({
    "extras": sentinel_ai.ORIGENS_EXTRAS,
    "null_get": ver("get", "/api/ml/status", "null"),
    "null_pre": ver("options", "/api/ml/sessao", "null", headers={"Access-Control-Request-Method": "POST"}),
    "externa_get": ver("get", "/api/ml/status", "https://site-externo.example"),
    "externa_post": ver("post", "/api/painel/sessao", "https://site-externo.example", json={}),
    "externa_pre": ver("options", "/api/painel/analises", "https://site-externo.example", headers={"Access-Control-Request-Method": "POST"}),
    "sem_origem": [c.get("/api/painel/estado").status_code, None],   # a própria página / scripts locais
    "curinga": [k for k, v in c.get("/api/ml/status", headers={"Origin": "null"}).headers.items() if v == "*"],
    "aviso": "iframes sandbox" in "\n".join(sentinel_ai.linhas_de_inicio()),
}))
"""


def test_com_null_ligada_so_null_passa_e_externa_continua_recusada():
    """Processo separado: NODEWATCH_ORIGENS é lida na importação do servidor."""
    env = dict(os.environ, NODEWATCH_ORIGENS="null")
    saida = subprocess.run([sys.executable, "-c", _COM_NULL, str(RAIZ)], capture_output=True, text=True, env=env,
                           cwd=RAIZ, timeout=120, encoding="utf-8")
    assert saida.returncode == 0, saida.stderr[-2000:]
    r = json.loads(saida.stdout.strip().splitlines()[-1])
    assert r["extras"] == ["null"] and r["aviso"] is True
    assert r["null_get"] == [200, "null"] and r["null_pre"] == [200, "null"]
    assert r["externa_get"] == [403, None] and r["externa_post"] == [403, None] and r["externa_pre"] == [403, None]
    assert r["sem_origem"][0] == 200 and r["curinga"] == []


def test_curinga_nunca_e_aceito_na_variavel():
    env = dict(os.environ, NODEWATCH_ORIGENS="*")
    codigo = ("import sys, json; sys.path.insert(0, sys.argv[1]); from src import sentinel_ai as s; "
              "c = s.app.test_client(); r = c.get('/api/ml/status', headers={'Origin': 'https://site-externo.example'}); "
              "print(json.dumps([s.ORIGENS_EXTRAS, r.status_code, r.headers.get('Access-Control-Allow-Origin')]))")
    saida = subprocess.run([sys.executable, "-c", codigo, str(RAIZ)], capture_output=True, text=True, env=env, cwd=RAIZ,
                           timeout=120, encoding="utf-8")
    assert saida.returncode == 0, saida.stderr[-2000:]
    assert json.loads(saida.stdout.strip().splitlines()[-1]) == [[], 403, None]


DOCS_CORRIGIDOS = ("docs/ml/EVENTOS.md", "docs/ml/ANALISE_DATASETS.md", "docs/ml/README.md", "docs/ui/README-INTERFACE.md",
                   "docs/COMO_FUNCIONA_O_NODEWATCH.md", "docs/APRESENTACAO_NODEWATCH.md", "scripts/produtor_eventos_exemplo.py")


@pytest.mark.parametrize("arquivo", DOCS_CORRIGIDOS)
def test_documentos_nao_mandam_para_a_raiz_com_hash_antigo(arquivo):
    caminho = RAIZ / arquivo
    if not caminho.is_file():
        pytest.skip(f"{arquivo} não existe nesta cópia")
    texto = caminho.read_text(encoding="utf-8")
    assert "5000/#" not in texto, arquivo                       # áreas antigas: /legado#ml…
    assert "5000/legado#ml" in texto or "5000/`" in texto, arquivo


def test_interface_antiga_se_identifica_e_aponta_para_o_painel(cliente):
    html = cliente.get("/legado").get_data(as_text=True)
    faixa = html[html.index('<div role="note" aria-label="Interface antiga do NodeWatch"'):]
    faixa = faixa[:faixa.index("</div>")]
    assert "Interface antiga do NodeWatch" in faixa and "Abrir o painel do analista" in faixa
    assert "href={window.NODEWATCH_API + '/'}" in faixa          # funciona também aberta como arquivo
    assert html.index('role="note" aria-label="Interface antiga do NodeWatch"') < html.index("{/* TOPBAR */}")
