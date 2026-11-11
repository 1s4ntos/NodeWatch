"""Envio seguro e validação de datasets válidos e inválidos (colunas, tipos, datas, valores)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from src.painel import datasets as ds
from testes.painel.conftest import CABECALHO, CENARIO, D, escrever, linha


def _problema(lista, coluna):
    achados = [p for p in lista if p["coluna"] == coluna]
    assert achados, f"sem problema para a coluna {coluna}: {lista}"
    return achados[0]


# -- envio seguro ------------------------------------------------------------
@pytest.mark.parametrize("enviado, esperado", [
    ("../../etc/passwd.csv", "passwd.csv"), (r"C:\Users\ana\Desktop\dados julho.csv", "dados julho.csv"),
    ("..", "dataset.csv"), ("", "dataset.csv"), ("a<b>:c|d?.csv", "a_b_c_d_.csv"), ("x" * 200 + ".csv", "x" * 74 + ".csv"),
])
def test_nome_do_arquivo_e_sanitizado(enviado, esperado):
    assert ds.nome_seguro(enviado) == esperado


def test_envio_grava_com_nome_interno_fixo_em_pasta_ignorada(ambiente, cenario):
    reg = ambiente.enviar(cenario["dados"], nome="../../fora/meus dados.csv")
    assert reg["nome"] == "meus dados.csv" and reg["id"].startswith("ds-")
    pasta = ambiente.raiz / "artefatos_ml" / "painel" / "datasets" / reg["id"]
    assert sorted(p.name for p in pasta.iterdir()) == ["dados.csv", "dataset.json"]
    assert not (ambiente.raiz / "fora").exists() and not (ambiente.raiz.parent / "fora").exists()
    # a pasta de dados está no .gitignore do projeto
    gitignore = (Path(__file__).resolve().parents[2] / ".gitignore").read_text(encoding="utf-8")
    assert "artefatos_ml/" in gitignore


def test_identificador_nao_aceita_caminho(ambiente):
    for ruim in ("../x", "ds-..%2F..", "C:/Windows", "srv-zzzzzzzzzzzz", ""):
        with pytest.raises(KeyError):
            ambiente.datasets.obter(ruim)


def test_extensao_nao_aceita(ambiente):
    with pytest.raises(ds.ErroDataset) as exc:
        ambiente.datasets.enviar(io.BytesIO(b"x"), "planilha.xlsx")
    assert exc.value.status == 415 and "csv" in exc.value.problemas[0]["como_corrigir"]


def test_limite_de_tamanho_no_envio(ambiente, monkeypatch):
    monkeypatch.setattr(ds, "LIMITE_BYTES", 1_000)
    with pytest.raises(ds.ErroDataset) as exc:
        ambiente.datasets.enviar(io.BytesIO(b"a" * 5_000), "grande.csv")
    assert exc.value.status == 413
    assert list((ambiente.raiz / ds.PASTA).glob("ds-*")) == []  # nada fica gravado


def test_arquivo_vazio(ambiente):
    with pytest.raises(ds.ErroDataset):
        ambiente.datasets.enviar(io.BytesIO(b""), "vazio.csv")


def test_retencao_dos_enviados(ambiente, cenario, monkeypatch):
    monkeypatch.setattr(ds, "MAX_ENVIADOS", 2)
    ids = [ambiente.enviar(cenario["dados"], nome=f"d{i}.csv")["id"] for i in range(4)]
    restantes = {r["id"] for r in ambiente.datasets.listar() if r["origem"] == "enviado"}
    assert len(restantes) == 2 and ids[-1] in restantes


# -- datasets válidos ----------------------------------------------------------
def test_validacao_do_formato_ibm(ambiente, cenario):
    reg = ambiente.enviar(cenario["dados"], cenario["padroes"])
    v = reg["validacao"]
    assert reg["status"] == "valido" and v["formato"] == "hismall_v1"
    assert v["linhas"] == {"lidas": 13, "validas": 13, "recusadas": 0}
    assert v["periodo"]["inicio"] == "2024-01-05T09:00" and v["periodo"]["fim"] == "2024-01-05T11:30"
    assert {m["valor"]: m["n"] for m in v["moedas_pagamento"]} == {"US Dollar": 10, "Euro": 2, "Yen": 1}
    formatos = {m["valor"]: m["n"] for m in v["formatos_pagamento"]}
    assert formatos == {"Wire": 5, "ACH": 3, "Cash": 2, "Cheque": 1, ds.NAO_INFORMADO: 2}
    assert v["rotulo"] == {"disponivel": True, "coluna": "Is Laundering", "positivos": 4}
    assert v["tipologias"]["disponivel"] and v["tipologias"]["tentativas"] == 3
    assert [c["original"] for c in v["colunas"]][:5] == ["Timestamp", "From Bank", "Account", "To Bank", "Account (2ª ocorrência)"]
    assert v["contas_distintas"] == 10 and len(v["sha256"]) == 64 and reg["bytes"] == cenario["dados"].stat().st_size
    assert any("ordem cronológica" in a for a in v["avisos"])


def test_validacao_do_formato_em_portugues_com_coluna_extra(ambiente, tmp_path):
    df = pd.DataFrame({
        "id_transacao": ["t1", "t2", "t3"], "timestamp": ["2024-03-01T08:00:00Z", "2024/03/01 08:05", "1709280600"],
        "banco_origem": [10, 10, 11], "conta_origem": ["P1", "P1", "P2"], "banco_destino": [11, 12, 10],
        "conta_destino": ["P2", "P3", "P1"], "valor_pago": [10.5, 20, 30], "moeda_pagamento": ["Real"] * 3,
        "valor_recebido": [10.5, 20, 30], "moeda_recebimento": ["Real"] * 3, "formato": ["Pix", "Pix", "TED"],
        "canal": ["app", "web", "app"],
    })
    caminho = tmp_path / "pt.csv"
    df.to_csv(caminho, index=False)
    reg = ambiente.enviar(caminho)
    v = reg["validacao"]
    assert reg["status"] == "valido" and v["formato"] == "transacao_hismall_v1"
    assert v["colunas_nao_reconhecidas"] == ["canal"] and v["rotulo"]["disponivel"] is False
    assert v["tipologias"]["disponivel"] is False and "arquivo de padrões" in v["tipologias"]["motivo"]
    assert v["periodo"]["inicio"] == "2024-03-01T08:00" and v["periodo"]["fim"] == "2024-03-01T08:10"


def test_zip_com_um_csv(ambiente, cenario, tmp_path):
    z = tmp_path / "cenario.zip"
    with zipfile.ZipFile(z, "w") as arq:
        arq.write(cenario["dados"], "qualquer/nome.csv")
    assert ambiente.enviar(z)["validacao"]["linhas"]["validas"] == 13
    dois = tmp_path / "dois.zip"
    with zipfile.ZipFile(dois, "w") as arq:
        arq.write(cenario["dados"], "a.csv")
        arq.write(cenario["dados"], "b.csv")
    reg = ambiente.enviar(dois)
    assert reg["status"] == "invalido" and "exatamente 1" in reg["erro"]["problemas"][0]["problema"]


# -- datasets inválidos -----------------------------------------------------------
def test_colunas_obrigatorias_ausentes(ambiente, tmp_path):
    caminho = tmp_path / "faltam.csv"
    caminho.write_text("Timestamp,From Bank,Account,Amount Paid\n2024/01/05 10:00,1,A,10\n", encoding="utf-8")
    reg = ambiente.enviar(caminho)
    assert reg["status"] == "invalido" and reg["validacao"] is None
    p = reg["erro"]["problemas"][0]  # o formato mais próximo vem primeiro
    assert "To Bank" in p["problema"] and "Payment Format" in p["problema"] and p["linha_exemplo"] == 1
    assert "Cabeçalho esperado" in p["como_corrigir"] and "Account.1" not in p["como_corrigir"]


def test_codificacao_diferente_de_utf8(ambiente, tmp_path):
    caminho = tmp_path / "latin1.csv"
    caminho.write_bytes((CABECALHO + "\n" + linha(f"{D} 10:00", 1, "A", 1, "B", 10, moeda="Dólar")).encode("latin-1"))
    reg = ambiente.enviar(caminho)
    assert reg["status"] == "invalido"
    assert "UTF-8" in reg["erro"]["problemas"][0]["problema"] and "UTF-8" in reg["erro"]["problemas"][0]["como_corrigir"]


def test_separador_ponto_e_virgula(ambiente, tmp_path):
    caminho = tmp_path / "pv.csv"
    caminho.write_text(CABECALHO.replace(",", ";") + "\n" + CENARIO[0].replace(",", ";") + "\n", encoding="utf-8")
    reg = ambiente.enviar(caminho)
    assert reg["status"] == "invalido" and "ponto e vírgula" in reg["erro"]["problemas"][0]["problema"]


def test_medicoes_de_rede_nao_sao_analisaveis_aqui(ambiente, tmp_path):
    from testes.ml.conftest import gerar_rede
    caminho = tmp_path / "rede.csv"
    gerar_rede(n_fluxos=2).drop(columns=["split"]).to_csv(caminho, index=False)
    reg = ambiente.enviar(caminho)
    assert reg["status"] == "invalido" and "rede" in reg["erro"]["problemas"][0]["problema"]


def test_tipos_datas_e_valores_invalidos_indicam_coluna_linha_e_correcao(ambiente, tmp_path):
    linhas = [
        linha(f"{D} 10:00", 1, "A", 1, "B", 10, rotulo=0),          # linha 2: válida
        linha("05/01/2024 10:00", 1, "A", 1, "B", 10, rotulo=0),    # linha 3: data
        linha(f"{D} 10:01", "ITAU", "A", 1, "B", 10, rotulo=0),     # linha 4: banco não numérico
        linha(f"{D} 10:02", 1, "", 1, "B", 10, rotulo=0),           # linha 5: conta vazia
        linha(f"{D} 10:03", 1, "A", 1, "B", -5, rotulo=0),          # linha 6: valor negativo
        f"{D} 10:04,1,A,1,B,dez,US Dollar,10.00,US Dollar,Wire,0",  # linha 7: valor recebido não numérico
        linha(f"{D} 10:05", 1, "A", 1, "B", 10, rotulo=7),          # linha 8: rótulo inválido
        linha(f"{D} 10:06", 1, "A", 1, "B", 10, moeda="", rotulo=0, moeda_rec="US Dollar"),  # linha 9: moeda vazia
        linha(f"{D} 10:07", 1, "A", 1, "B", 12, rotulo=0),          # linha 10: válida
    ]
    reg = ambiente.enviar(escrever(tmp_path / "ruins.csv", linhas, com_rotulo=True))
    v = reg["validacao"]
    assert reg["status"] == "valido_com_recusas" and v["linhas"] == {"lidas": 9, "validas": 2, "recusadas": 7}
    esperado = {"Timestamp": (3, "05/01/2024 10:00", "AAAA/MM/DD"), "From Bank": (4, "ITAU", "numérico"),
                "Account": (5, "", "Preencha"), "Amount Paid": (6, "-5.00", "entre 0"),
                "Amount Received": (7, "dez", "ponto decimal"), "Is Laundering": (8, "7", "1 para lavagem"),
                "Payment Currency": (9, "", "Preencha")}
    for coluna, (n_linha, valor, dica) in esperado.items():
        p = _problema(v["problemas"], coluna)
        assert (p["linha_exemplo"], p["valor_exemplo"], p["linhas_afetadas"]) == (n_linha, valor, 1), p
        assert dica in p["como_corrigir"], p
    assert sum(p["linhas_afetadas"] for p in v["problemas"]) == 7


def test_todas_as_linhas_invalidas_torna_o_dataset_invalido(ambiente, tmp_path):
    linhas = [linha("ontem", 1, "A", 1, "B", 10), linha(f"{D} 10:00", 1, "A", 1, "B", -1)]
    reg = ambiente.enviar(escrever(tmp_path / "tudo_ruim.csv", linhas))
    assert reg["status"] == "invalido"
    textos = [p["problema"] for p in reg["erro"]["problemas"]]
    assert any("nenhuma das 2 linhas" in t for t in textos) and any("data e hora" in t for t in textos)


def test_identificador_repetido_e_recusado(ambiente, tmp_path):
    df = pd.DataFrame({
        "id_transacao": ["t1", "t1", "t2"], "timestamp": ["2024-03-01T08:00:00Z"] * 3, "banco_origem": [1] * 3,
        "conta_origem": ["A"] * 3, "banco_destino": [2] * 3, "conta_destino": ["B"] * 3, "valor_pago": [1, 2, 3],
        "moeda_pagamento": ["Real"] * 3, "valor_recebido": [1, 2, 3], "moeda_recebimento": ["Real"] * 3,
        "formato": ["Pix"] * 3})
    caminho = tmp_path / "rep.csv"
    df.to_csv(caminho, index=False)
    v = ambiente.enviar(caminho)["validacao"]
    p = _problema(v["problemas"], "id_transacao")
    assert v["linhas"]["recusadas"] == 1 and p["linha_exemplo"] == 3 and "repetido" in p["problema"]


def test_arquivo_de_padroes_ilegivel_nao_inventa_tipologias(ambiente, cenario, tmp_path):
    ruim = tmp_path / "padroes_ruins.txt"
    ruim.write_text("isto não é um arquivo de padrões\n", encoding="utf-8")
    v = ambiente.enviar(cenario["dados"], ruim)["validacao"]
    assert v["tipologias"]["disponivel"] is False and "recusado" in v["tipologias"]["motivo"]


# -- datasets já disponíveis no servidor --------------------------------------------
def test_datasets_do_servidor_sao_descobertos_em_pastas_fixas(ambiente, cenario):
    pasta = ambiente.raiz / "dados"
    pasta.mkdir()
    (pasta / "transacoes_marco.csv").write_bytes(cenario["dados"].read_bytes())
    (pasta / "grafo_antigo.csv").write_text("step,type,amount,nameOrig,nameDest\n1,TRANSFER,1,C1,C2\n", encoding="utf-8")
    (pasta / "notas.txt").write_text("não é dataset", encoding="utf-8")
    servidor = [r for r in ambiente.datasets.listar() if r["origem"] == "servidor"]
    assert [r["nome"] for r in servidor] == ["transacoes_marco.csv"]  # só o que tem cabeçalho de transações
    reg = servidor[0]
    assert reg["status"] == "nao_validado" and reg["id"].startswith("srv-") and "caminho" not in reg
    assert str(ambiente.raiz) not in str(reg)
    validado = ambiente.datasets.validar(reg["id"], esperar=True)
    assert validado["status"] == "valido" and validado["validacao"]["linhas"]["validas"] == 13
    assert ambiente.datasets.obter(reg["id"])["status"] == "valido"  # o resultado fica guardado
