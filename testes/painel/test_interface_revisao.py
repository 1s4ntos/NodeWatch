"""Regressões da revisão de aceitação (interface): telas estreitas, carregamento inicial e página aberta como arquivo.

Os três defeitos foram reproduzidos no Chrome; aqui fica a garantia de que as regras que os corrigem continuam no lugar.
A verificação visual em si (320, 390, 768, 1280 e 1440 px) é feita no navegador e está em docs/ui/PAINEL_ANALISTA.md.
"""

from __future__ import annotations

import re
from pathlib import Path

INTERFACE = Path(__file__).resolve().parents[2] / "interface"
CSS = (INTERFACE / "assets" / "painel.css").read_text(encoding="utf-8")


def _regras(seletor_contem: str) -> list:
    return [corpo for sel, corpo in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS) if seletor_contem in sel]


def test_grades_de_varias_colunas_nunca_exigem_mais_que_a_largura_disponivel():
    # em 320 px, "minmax(320px, 1fr)" mais o recuo alargava a página inteira
    fixos = re.findall(r"repeat\(auto-fit, minmax\((\d+px), 1fr\)\)", CSS)
    assert fixos == [], f"colunas com mínimo fixo: {fixos}"
    assert len(re.findall(r"repeat\(auto-fit, minmax\(min\(\d+px, 100%\), 1fr\)\)", CSS)) >= 5


def test_grades_de_uma_coluna_usam_a_largura_disponivel_e_nao_a_do_conteudo():
    # o seletor de dataset com opções longas (72 caracteres) alargava main e as seções até 634 px numa tela de 320 px
    corpos = _regras("main, .secao .corpo")
    assert corpos and "grid-template-columns: minmax(0, 1fr)" in corpos[0]
    seletores = next(sel for sel, _ in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS) if "main, .secao .corpo" in sel)
    for item in ("main", ".secao .corpo", ".grade", ".etapas", ".contas", ".escala", "dialog .corpo"):
        assert item in seletores, item
    assert any("min-width: 0" in c for c in _regras(".grade > *"))
    controles = _regras('input[type="text"]')
    assert any("max-width: 100%" in c and "min-width: 0" in c for c in controles)


def test_rotulos_da_escala_do_score_quebram_linha_em_tela_estreita():
    estreita = CSS[CSS.index("@media (max-width: 720px)"):]
    assert ".escala .faixas > div {" in estreita and "white-space: normal" in estreita.split(".escala .faixas > div {")[1].split("}")[0]


def test_assistente_fica_no_topo_e_nao_cobre_o_conteudo():
    # o botão flutuante cobria botões e linhas ao rolar; agora o botão mora no topo fixo e o painel abre abaixo dele
    app = (INTERFACE / "assets" / "painel-app.js").read_text(encoding="utf-8")
    acoes = app[app.index("className: 'acoes'"):app.index("h(PainelLateral")]
    assert "h(Assistente," in acoes and app.count("h(Assistente,") == 1
    assert not any("position: fixed" in c for c in _regras(".assistente"))
    estreita = CSS[CSS.index("@media (max-width: 720px)"):]
    assert ".assistente .abrir .rotulo-longo { display: none; }" in estreita
    secoes = (INTERFACE / "assets" / "painel-secoes.js").read_text(encoding="utf-8")
    assert "'rotulo-longo' }, 'Assistente de dúvidas'" in secoes and "'rotulo-curto' }, 'Dúvidas'" in secoes


def test_pagina_mostra_carregamento_antes_de_montar():
    html = (INTERFACE / "painel.html").read_text(encoding="utf-8")
    raiz = html[html.index('<div id="raiz">'):html.index("</div>", html.index('<div id="raiz">'))]
    assert 'role="status"' in raiz and "Abrindo o painel" in raiz


def test_painel_aberto_como_arquivo_explica_como_abrir_em_vez_de_acusar_o_servidor():
    app = (INTERFACE / "assets" / "painel-app.js").read_text(encoding="utf-8")
    assert "location.protocol === 'file:'" in app and "não abre como arquivo" in app and "http://127.0.0.1:5000/" in app
    assert app.index("location.protocol === 'file:'") < app.index("sessao.iniciar().then")  # nem tenta abrir sessão


def test_arquivo_acima_do_limite_e_recusado_na_tela_antes_do_envio():
    # acima do limite o servidor recusa logo no início e fecha a conexão; o navegador, ainda enviando, só via
    # "Servidor do NodeWatch indisponível". A tela confere o tamanho antes e explica o limite, sem enviar nada.
    secoes = (INTERFACE / "assets" / "painel-secoes.js").read_text(encoding="utf-8")
    envio = secoes[secoes.index("const enviar = async ev"):secoes.index("const validar = async")]
    assert "arq.size > lim.envio_bytes" in envio and "pad.size > lim.padroes_bytes" in envio
    assert envio.index("arq.size > lim.envio_bytes") < envio.index("api('/datasets'") and "Nada foi enviado." in envio


def test_recusa_por_tamanho_no_painel_usa_o_texto_do_painel(tmp_path):
    # a recusa do Flask (413) antes de ler o corpo tinha o texto da interface antiga ("limite de importação (64 MB)", CLI)
    import io

    from src.sentinel_ai import app
    from testes.painel.conftest import abrir_cliente

    (tmp_path / "artefatos_ml").mkdir()
    cli = abrir_cliente(tmp_path, None)
    original = app.config["MAX_CONTENT_LENGTH"]
    app.config["MAX_CONTENT_LENGTH"] = 1000
    try:
        r = cli.post("/api/painel/datasets", data={"arquivo": (io.BytesIO(b"x" * 5000), "grande.csv")},
                     content_type="multipart/form-data")
    finally:
        app.config["MAX_CONTENT_LENGTH"] = original
    corpo = r.get_json()
    assert r.status_code == 413 and "limite do painel (256 MB" in corpo["problemas"][0]
    assert "CLI" not in corpo["acao"] and "64 MB" not in corpo["problemas"][0]
