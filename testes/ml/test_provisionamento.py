"""Instalação do modelo distribuído (src/ml/provisionamento.py) numa máquina limpa e nos casos de falha.

Cada teste monta uma "cópia do repositório" numa pasta temporária: ``modelos/`` com um modelo pequeno
(o mesmo dos outros testes, não o do projeto) e o manifesto, e ``artefatos_ml/`` vazia, como num clone novo.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.ml import provisionamento as pv


@pytest.fixture
def repo(tmp_path: Path, modelo_minimo) -> Path:
    """Cópia limpa: modelo e manifesto em modelos/, nada instalado em artefatos_ml/."""
    modelo_minimo.salvar(tmp_path / "artefatos_ml")
    pv.preparar_distribuicao(tmp_path, url="file:///nao/existe/modelo.joblib")
    shutil.rmtree(tmp_path / "artefatos_ml")
    return tmp_path


def _manifesto(repo: Path) -> dict:
    return json.loads((repo / "modelos" / pv.NOME_MANIFESTO).read_text(encoding="utf-8"))


def _gravar_manifesto(repo: Path, m: dict) -> None:
    (repo / "modelos" / pv.NOME_MANIFESTO).write_text(json.dumps(m), encoding="utf-8")


def _instalado(repo: Path) -> Path:
    return repo / "artefatos_ml" / pv.NOME_MODELO


def test_maquina_limpa_instala_valida_e_segunda_execucao_nao_reinstala(repo: Path):
    r = pv.garantir_modelo(repo, baixar_se_preciso=False, avisar=lambda _: None)
    assert r["origem"] == "copiado" and r["versao"] == "teste-lavagem"
    assert _instalado(repo).is_file() and (repo / "artefatos_ml" / pv.NOME_METADADOS).is_file()
    assert pv.sha256(_instalado(repo)) == _manifesto(repo)["sha256"]
    antes = _instalado(repo).stat().st_mtime_ns
    r2 = pv.garantir_modelo(repo, baixar_se_preciso=False, avisar=lambda _: None)
    assert r2["origem"] == "ja_instalado" and _instalado(repo).stat().st_mtime_ns == antes
    assert pv.ultimo_erro() is None


def test_modelo_distribuido_corrompido_e_recusado_sem_deixar_nada_instalado(repo: Path):
    arq = repo / "modelos" / pv.NOME_MODELO
    dados = bytearray(arq.read_bytes())
    dados[len(dados) // 2] ^= 0xFF
    arq.write_bytes(bytes(dados))
    with pytest.raises(pv.ErroModelo) as e:
        pv.garantir_modelo(repo, baixar_se_preciso=False, avisar=lambda _: None)
    assert "SHA-256" in e.value.causa and "provisionamento" in e.value.acao
    assert not _instalado(repo).exists()
    assert pv.ultimo_erro() is e.value


def test_modelo_ausente_e_baixado_conferindo_o_sha(repo: Path, tmp_path_factory, monkeypatch):
    espelho = tmp_path_factory.mktemp("espelho") / pv.NOME_MODELO
    shutil.move(repo / "modelos" / pv.NOME_MODELO, espelho)  # como num clone sem o arquivo
    monkeypatch.setenv(pv.VAR_URL, espelho.as_uri())
    avisos: list = []
    r = pv.garantir_modelo(repo, avisar=avisos.append)
    assert r["origem"] == "baixado" and _instalado(repo).is_file()
    assert (repo / "modelos" / pv.NOME_MODELO).is_file()  # a fonte foi restaurada
    assert any("100%" in a for a in avisos)               # progresso mostrado
    assert not list((repo / "modelos").glob("*.baixando"))


def test_ponteiro_do_git_lfs_e_tratado_como_ausente(repo: Path, tmp_path_factory, monkeypatch):
    arq = repo / "modelos" / pv.NOME_MODELO
    espelho = tmp_path_factory.mktemp("espelho") / pv.NOME_MODELO
    shutil.copyfile(arq, espelho)
    arq.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1\n", encoding="ascii")
    monkeypatch.setenv(pv.VAR_URL, espelho.as_uri())
    assert pv.garantir_modelo(repo, avisar=lambda _: None)["origem"] == "baixado"


def test_falha_de_download_explica_e_nao_deixa_arquivo_parcial(repo: Path, monkeypatch):
    (repo / "modelos" / pv.NOME_MODELO).unlink()
    monkeypatch.setenv(pv.VAR_URL, (repo / "nao_existe.joblib").as_uri())
    with pytest.raises(pv.ErroModelo) as e:
        pv.garantir_modelo(repo, avisar=lambda _: None)
    assert "Falha ao baixar" in e.value.causa and "internet" in e.value.acao
    assert not _instalado(repo).exists() and not list((repo / "modelos").glob("*.baixando"))


def test_download_com_conteudo_errado_e_recusado(repo: Path, tmp_path_factory, monkeypatch):
    (repo / "modelos" / pv.NOME_MODELO).unlink()
    falso = tmp_path_factory.mktemp("espelho") / "falso.joblib"
    falso.write_bytes(b"0" * 1000)
    monkeypatch.setenv(pv.VAR_URL, falso.as_uri())
    with pytest.raises(pv.ErroModelo) as e:
        pv.garantir_modelo(repo, avisar=lambda _: None)
    assert "não confere" in e.value.causa
    assert not (repo / "modelos" / pv.NOME_MODELO).exists() and not _instalado(repo).exists()


def test_versao_incompativel_do_scikit_learn_e_recusada(repo: Path):
    m = _manifesto(repo)
    m["dependencias"]["scikit-learn"] = "0.0.1"
    _gravar_manifesto(repo, m)
    with pytest.raises(pv.ErroModelo) as e:
        pv.garantir_modelo(repo, baixar_se_preciso=False, avisar=lambda _: None)
    assert "scikit-learn" in e.value.causa and "requirements-ml.txt" in e.value.acao
    assert not _instalado(repo).exists()


def test_dependencias_ausentes_sao_explicadas(repo: Path, monkeypatch):
    real = pv.importlib.import_module

    def falha(nome, *a, **k):
        if nome == "sklearn":
            raise ImportError("sem sklearn")
        return real(nome, *a, **k)

    monkeypatch.setattr(pv.importlib, "import_module", falha)
    with pytest.raises(pv.ErroModelo) as e:
        pv.garantir_modelo(repo, baixar_se_preciso=False, avisar=lambda _: None)
    assert "scikit-learn" in e.value.causa and "pip install" in e.value.acao


def test_manifesto_ausente_indica_copia_incompleta(repo: Path):
    (repo / "modelos" / pv.NOME_MANIFESTO).unlink()
    with pytest.raises(pv.ErroModelo) as e:
        pv.garantir_modelo(repo, avisar=lambda _: None)
    assert "incompleta" in e.value.causa


def test_modelo_proprio_da_maquina_e_mantido(repo: Path, modelo_minimo):
    pv.garantir_modelo(repo, baixar_se_preciso=False, avisar=lambda _: None)
    modelo_minimo.metadados["marca"] = "treinado aqui"
    modelo_minimo.salvar(repo / "artefatos_ml")          # outro SHA-256: modelo treinado pela CLI
    sha = pv.sha256(_instalado(repo))
    r = pv.garantir_modelo(repo, baixar_se_preciso=False, avisar=lambda _: None)
    assert r["origem"] == "local_proprio" and pv.sha256(_instalado(repo)) == sha


def test_modelo_instalado_corrompido_nao_e_sobrescrito_e_explica_como_voltar(repo: Path):
    _instalado(repo).parent.mkdir(parents=True)
    _instalado(repo).write_bytes(b"isto nao e um modelo")
    with pytest.raises(pv.ErroModelo) as e:
        pv.garantir_modelo(repo, baixar_se_preciso=False, avisar=lambda _: None)
    assert "não pôde ser carregado" in e.value.causa and "renomeie ou apague" in e.value.acao
    assert _instalado(repo).read_bytes() == b"isto nao e um modelo"


def test_distribuicao_nao_leva_caminhos_da_maquina(tmp_path: Path, modelo_minimo):
    modelo_minimo.cabeca("lavagem").metadados["arquivo"] = r"C:\Users\alguem\dados\HI-Small_Trans.zip"
    modelo_minimo.salvar(tmp_path / "artefatos_ml")
    m = pv.preparar_distribuicao(tmp_path)
    assert b"alguem" not in (tmp_path / "modelos" / pv.NOME_MODELO).read_bytes()
    assert "alguem" not in (tmp_path / "modelos" / pv.NOME_METADADOS).read_text(encoding="utf-8")
    assert m["sha256"] == pv.sha256(tmp_path / "modelos" / pv.NOME_MODELO) and m["lavagem"]["colunas"] > 0


def test_painel_nao_libera_analise_so_com_metadados(repo: Path):
    """Regressão: numa cópia limpa havia metadados versionados (docs/ml/resultados) sem o .joblib,
    o painel dizia "modelo disponível" e a análise falhava ao começar."""
    from src import api_painel
    from src.sentinel_ai import app

    docs = repo / "docs" / "ml" / "resultados"
    docs.mkdir(parents=True)
    shutil.copyfile(repo / "modelos" / pv.NOME_METADADOS, docs / pv.NOME_METADADOS)
    api_painel.configurar(repo)
    app.config["TESTING"] = True
    estado = app.test_client().get("/api/painel/estado").get_json()
    assert estado["modelo"]["disponivel"] is False and "provisionamento" in estado["modelo"]["motivo"]
    pv.garantir_modelo(repo, baixar_se_preciso=False, avisar=lambda _: None)
    estado = app.test_client().get("/api/painel/estado").get_json()
    assert estado["modelo"]["disponivel"] is True and estado["modelo"]["versao"]


def test_manifesto_do_repositorio_confere_com_o_modelo_distribuido():
    """O manifesto versionado descreve exatamente o arquivo versionado (falha se alguém trocar um sem o outro)."""
    m = pv.ler_manifesto(pv.RAIZ)
    arq = pv.RAIZ / pv.PASTA_DISTRIBUIDA / pv.NOME_MODELO
    assert arq.stat().st_size == m["bytes"] and pv.sha256(arq) == m["sha256"]
    assert pv.sha256(pv.RAIZ / pv.PASTA_DISTRIBUIDA / pv.NOME_METADADOS) == m["sha256_metadados"]
    assert m["lavagem"]["colunas"] == 49 and m["download"]["url"].startswith("https://")
