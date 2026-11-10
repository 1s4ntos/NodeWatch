"""Ferramentas da avaliação do HI-Large (``scripts/hi_large``), com dados SINTÉTICOS.

Verificam o que os experimentos assumem:

* a partição por dia aceita um CSV fora de ordem no tempo e guarda a linha original;
* bancos com zeros à esquerda diferentes viram a mesma conta, como no NodeWatch;
* partição + ``EstadoFinanceiro`` dá os mesmos atributos do cálculo em lote;
* padrões casam com positivos pela chave completa, e o resto é contado;
* a amostra do treino é fixa e mantém todos os positivos;
* a AP ponderada do bootstrap é a do scikit-learn, e o teste não é reconsultado;
* os períodos de avaliação não se sobrepõem entre si nem ao treino;
* o carregamento por dia mantém a ordem, e a conferência de reprodução acusa diferenças.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import average_precision_score

from src.ml.incremental import EstadoFinanceiro
from src.ml.preparacao import PreparadorFinanceiro, atributos_financeiros
from testes.ml.conftest import gerar_transacoes
from testes.ml.referencia_financeira import colunas_divergentes

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hi_large"))
import a_perfil_particionar as perfil  # noqa: E402
import b_atributos as atributos  # noqa: E402
import c_treinar_avaliar as avaliacao  # noqa: E402
import comum  # noqa: E402

CABECALHO = ("Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,"
             "Amount Paid,Payment Currency,Payment Format,Is Laundering")


def _texto_banco(b: int, i: int) -> str:
    # Banco 2 aparece com dois preenchimentos diferentes ("002" e "0002"), como no HI-Large.
    return f"{b:04d}" if b == 2 and i % 2 else f"{b:03d}"


@pytest.fixture()
def cenario(tmp_path, monkeypatch):
    monkeypatch.setattr(comum, "TRABALHO", tmp_path / "trabalho")
    monkeypatch.setattr(perfil, "PARTICOES", tmp_path / "trabalho" / "particoes")
    monkeypatch.setattr(atributos, "PARTICOES", tmp_path / "trabalho" / "particoes")
    comum.TRABALHO.mkdir(parents=True)
    trans = gerar_transacoes(2_500, 60, semente=3)
    trans["minuto"] = trans["minuto"] - 27_000_000 + perfil.MIN_DIA0
    rng = np.random.default_rng(7)
    ordem = rng.permutation(len(trans))  # arquivo fora de ordem no tempo
    trans = trans.iloc[ordem].reset_index(drop=True)
    contas = [f"8{c:08X}" for c in range(60)]
    linhas = [CABECALHO]
    for i, r in enumerate(trans.itertuples(index=False)):
        ts = pd.Timestamp("1970-01-01") + pd.Timedelta(minutes=int(r.minuto))
        linhas.append(",".join([
            ts.strftime("%Y/%m/%d %H:%M"), _texto_banco(int(r.banco_origem), i), contas[r.conta_origem],
            _texto_banco(int(r.banco_destino), i + 1), contas[r.conta_destino],
            f"{r.valor_recebido:.6f}", str(r.moeda_recebimento), f"{r.valor_pago:.2f}", str(r.moeda_pagamento),
            str(r.formato), str(int(r.rotulo))]))
    arquivo = tmp_path / "HI-Large_Trans.csv"
    arquivo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    # Valores como foram gravados no CSV (o cálculo em lote deve ver exatamente os mesmos números).
    trans["valor_pago"] = trans["valor_pago"].round(2)
    trans["valor_recebido"] = trans["valor_recebido"].round(6)
    return trans, arquivo, contas


def test_particao_aceita_arquivo_fora_de_ordem_e_funde_zeros_a_esquerda(cenario) -> None:
    trans, arquivo, _ = cenario
    r, contas_tx = perfil.perfil_transacoes(arquivo)
    assert r["linhas"] == len(trans)
    assert r["fora_de_ordem"] > 0
    assert sum(d["n"] for d in r["por_dia"].values()) == len(trans)
    assert r["positivos_total"] == int(trans["rotulo"].sum())
    assert r["bancos"]["codigos_fundidos_pelo_inteiro"] == 1
    esperadas = {f"{b}-8{c:08X}" for b, c in zip(np.r_[trans["banco_origem"], trans["banco_destino"]],
                                                    np.r_[trans["conta_origem"], trans["conta_destino"]])}
    assert contas_tx == esperadas
    lidas = pd.concat([pd.read_parquet(p) for p in sorted(perfil.PARTICOES.glob("dia=*.parquet"))])
    assert sorted(lidas["linha"]) == list(range(len(trans)))
    for p in perfil.PARTICOES.glob("dia=*.parquet"):
        dia = int(p.stem.split("=")[1])
        m = pd.read_parquet(p, columns=["minuto"])["minuto"]
        assert ((m - perfil.MIN_DIA0) // 1440 == dia).all()


def test_particao_mais_estado_incremental_igual_ao_lote(cenario) -> None:
    trans, arquivo, _ = cenario
    perfil.perfil_transacoes(arquivo)
    prep = PreparadorFinanceiro.ajustar(trans)
    # Lote: a ordem do arquivo desempata o mesmo minuto, como a coluna `linha` na partição.
    lote = atributos_financeiros(trans, np.arange(len(trans)), prep)
    prep.colunas = list(lote.columns)
    estado = EstadoFinanceiro(prep)
    partes = []
    for p in sorted(atributos.PARTICOES.glob("dia=*.parquet")):
        dia = int(p.stem.split("=")[1])
        df = atributos.ler_dia(dia)
        manter = np.ones(len(df), dtype=bool)
        partes += [t.to_pandas() for t in atributos.processar_dia(estado, df, manter, dia, "validacao", lote_saida=500)]
    obtido = pd.concat(partes).set_index("_linha").sort_index()
    assert list(obtido.index) == list(range(len(trans)))
    assert colunas_divergentes(obtido[prep.colunas], lote) == {}
    assert (obtido["_rotulo"].to_numpy() == trans["rotulo"].to_numpy()).all()


def test_amostra_do_treino_e_fixa_e_mantem_todos_os_positivos() -> None:
    y = (np.arange(10_000) % 97 == 0).astype(np.int8)
    a = atributos.amostra_treino(y, 3, "treino")
    assert (a == atributos.amostra_treino(y, 3, "treino")).all()
    assert a[y == 1].all()
    assert 0.17 < a[y == 0].mean() < 0.23
    assert atributos.amostra_treino(y, 3, "validacao").all()
    assert not (a == atributos.amostra_treino(y, 4, "treino")).all()


def test_padroes_casam_pela_chave_completa(cenario, tmp_path) -> None:
    trans, arquivo, contas = cenario
    perfil.perfil_transacoes(arquivo)
    pos = trans[trans["rotulo"] == 1].head(3)
    linhas = ["BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 3-degree Fan-Out"]
    for r in pos.itertuples(index=False):
        ts = pd.Timestamp("1970-01-01") + pd.Timedelta(minutes=int(r.minuto))
        linhas.append(f"{ts:%Y/%m/%d %H:%M},{int(r.banco_origem):03d},{contas[r.conta_origem]},"
                      f"{int(r.banco_destino):03d},{contas[r.conta_destino]},{r.valor_recebido:.2f},"
                      f"{r.moeda_recebimento},{r.valor_pago:.2f},{r.moeda_pagamento},{r.formato},1")
    linhas.append("2022/08/02 10:00,001,800000001,003,800000003,10.00,Euro,10.00,Euro,ACH,1")  # não existe
    linhas += ["END LAUNDERING ATTEMPT - FAN-OUT", ""]
    arq = tmp_path / "HI-Large_Patterns.txt"
    arq.write_text("\n".join(linhas), encoding="utf-8")
    r = perfil.perfil_padroes(arq)
    assert r["tentativas"] == 1 and r["linhas"] == 4
    assert r["linhas_de_padrao_casadas_com_positivos"] == 3
    assert r["linhas_de_padrao_sem_positivo"] == 1
    assert r["positivos_sem_padrao"] == int(trans["rotulo"].sum()) - 3


def test_contas_sem_cadastro_e_chaves_duplicadas(tmp_path) -> None:
    arq = tmp_path / "HI-Large_accounts.csv"
    arq.write_text("Bank Name,Bank ID,Account Number,Entity ID,Entity Name\n"
                   "Banco A,10,800000001,E1,Corporation #1\n"
                   "Banco A,010,800000001,E1,Corporation #1\n"   # mesmo banco numérico: chave repetida
                   "Banco B,20,800000002,E2,Individual #2\n", encoding="utf-8")
    r = perfil.perfil_contas(arq, {"10-800000001", "30-800000003"})
    assert r["chaves_duplicadas_banco_conta"] == 1
    assert r["contas_das_transacoes_sem_cadastro"] == 1
    assert r["contas_cadastradas_sem_transacao"] == 1
    assert r["tipo_entidade"] == {"Corporation": 2, "Individual": 1}


def test_ap_ponderada_e_bootstrap() -> None:
    rng = np.random.default_rng(0)
    y = (rng.random(4_000) < 0.05).astype(int)
    s = np.round(rng.random(4_000) + y * 0.3, 2)  # com empates
    ordem, ys, fim = avaliacao._preparar_ap(y, s)
    assert avaliacao._ap_peso(ys, fim, np.ones(len(y))) == pytest.approx(average_precision_score(y, s), abs=1e-12)
    w = rng.integers(0, 3, len(y)).astype(float)
    assert avaliacao._ap_peso(ys, fim, w[ordem]) == pytest.approx(average_precision_score(y, s, sample_weight=w), abs=1e-12)
    grupo = rng.integers(0, 300, len(y))
    igual = avaliacao.bootstrap_pareado(y, s, s, grupo, b=50)
    assert igual["diferenca_ap"] == 0 and igual["ic95"] == [0.0, 0.0]
    melhor = avaliacao.bootstrap_pareado(y, s + y, s, grupo, b=50)
    assert melhor["fracao_maior_que_zero"] == 1.0


def test_periodo_de_avaliacao_so_e_consultado_uma_vez(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(avaliacao, "CONSULTAS", tmp_path / "consultas.json")
    assert avaliacao._consultar("teste", forcar=False) == 1
    with pytest.raises(SystemExit):
        avaliacao._consultar("teste", forcar=False)
    assert avaliacao._consultar("teste", forcar=True) == 2


def test_purga_tira_so_a_continuacao_de_tentativas_anteriores(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(comum, "TRABALHO", tmp_path)
    # Tentativa 0 começa no minuto 100 (antes do período) e continua no 500; a 1 começa no período.
    pd.DataFrame({"tentativa": [0, 0, 1, 1], "minuto": [100, 500, 600, 700],
                  "linha": [10, 11, 12, 13]}).to_parquet(tmp_path / "padroes_casados.parquet")
    meta = pd.DataFrame({"_linha": [11, 12, 13, 20, 21], "_rotulo": [1, 1, 1, 1, 0]})
    manter = avaliacao.manter_purgado(meta, inicio=550)
    # sai só a continuação (linha 11); ficam a tentativa nova, o positivo sem padrão e o negativo
    assert manter.tolist() == [False, True, True, True, True]


# ---------------------------------------------------------------------------
# Precisão das somas em USD com valores na escala do HI-Large (até 8·10^12)
# ---------------------------------------------------------------------------
def _cenario_valores_enormes():
    from testes.ml.conftest import transacoes_normalizadas
    from testes.ml.test_referencia_financeira import _prep, _trans
    # 3.000 recebimentos de 10^13 na conta 1, que tem código baixo e entra antes nas somas
    # acumuladas do lote; depois a conta 200 recebe 12,34 e envia 5,00.
    linhas = [(m, 5 + m % 40, 1, 1e13, "US Dollar") for m in range(3000)]
    linhas += [(3001, 300, 200, 12.34, "US Dollar"), (3002, 200, 301, 5.0, "US Dollar")]
    t = _trans(linhas)
    t["id_transacao"] = np.arange(len(t))
    t["valor_recebido"] = t["valor_pago"]
    prep = _prep()
    nomes = np.array([f"{c % 3}-C{c}" for c in range(400)], dtype=object)
    return t, prep, transacoes_normalizadas(t, nomes)


def test_estado_incremental_mantem_a_soma_exata_com_valores_enormes() -> None:
    from testes.ml.referencia_financeira import atributos_referencia
    t, prep, txs = _cenario_valores_enormes()
    q = [len(t) - 1]
    prep.colunas = list(atributos_financeiros(t, np.array(q), prep).columns)
    estado = EstadoFinanceiro(prep)
    for tx in txs:
        assert estado.receber(tx) is None
    ultimo = estado.fechar_ate(None)[-1].X.iloc[-1]
    ref = atributos_referencia(t, q, prep.cambio, prep.formatos, prep.moedas).iloc[0]
    assert ref["soma_rec_origem_usd_24h"] == pytest.approx(12.34)
    for col in ("soma_rec_origem_usd_24h", "razao_saida_entrada_24h"):
        assert ultimo[col] == pytest.approx(ref[col], rel=1e-6)


def test_lote_mantem_a_soma_exata_com_valores_enormes() -> None:
    # Regressão do defeito encontrado no HI-Large: com uma soma acumulada única sobre todas as
    # contas, a soma desta janela (12,34) saía com erro de alguns por cento.
    from testes.ml.referencia_financeira import atributos_referencia
    t, prep, _ = _cenario_valores_enormes()
    q = [len(t) - 1]
    lote = atributos_financeiros(t, np.array(q), prep).iloc[0]
    ref = atributos_referencia(t, q, prep.cambio, prep.formatos, prep.moedas).iloc[0]
    assert lote["soma_rec_origem_usd_24h"] == pytest.approx(ref["soma_rec_origem_usd_24h"], rel=1e-5)


def test_indice_soma_so_dentro_da_conta_nas_bordas() -> None:
    from src.ml.preparacao import _IndiceEventos
    # Conta 1: minutos 1, 3 e 10 (valores 1, 2, 4); conta 2: minuto 5 (100); conta 3: minuto 4 (1000, último bloco).
    idx = _IndiceEventos(np.array([2, 1, 1, 3, 1]), np.array([5, 1, 3, 4, 10]),
                         {"v": np.array([100.0, 1.0, 2.0, 1000.0, 4.0])})
    chave, t = np.array([1, 1, 1, 2, 3, 9]), np.array([4, 11, 1, 6, 5, 1])
    lo, hi = idx.limites(chave, t, None)
    assert idx.soma("v", lo, hi).tolist() == [3.0, 7.0, 0.0, 100.0, 1000.0, 0.0]
    lo, hi = idx.limites(chave, t, 3)  # janela [t-3, t): começa no meio do bloco da conta 1
    assert idx.soma("v", lo, hi).tolist() == [3.0, 4.0, 0.0, 100.0, 1000.0, 0.0]


def test_periodos_de_avaliacao_nao_se_sobrepoem() -> None:
    dias = [d for periodo in avaliacao.DIAS.values() for d in periodo]
    assert len(dias) == len(set(dias))
    assert not set(dias) & set(atributos.DIAS_TREINO)
    assert avaliacao.DIAS["teste_final3"] == tuple(range(16, 23))
    assert {atributos.PARTICAO[d] for d in avaliacao.DIAS["teste_final3"]} == {"teste_final3"}


def test_carregar_por_dia_preserva_ordem_e_separa_metadados(tmp_path) -> None:
    for d, linhas in ((3, [7, 5]), (4, [9])):
        pd.DataFrame({"a": np.arange(len(linhas), dtype=np.float64) + d, "b": 1.5,
                      "_linha": linhas, "_rotulo": [0] * len(linhas)}).to_parquet(tmp_path / f"dia={d:03d}.parquet")
    X, meta = avaliacao.carregar(tmp_path, (3, 4), ["a", "b"])
    assert X.dtypes.tolist() == [np.float32, np.float32]
    assert X["a"].tolist() == [3.0, 4.0, 4.0]
    assert meta["_linha"].tolist() == [7, 5, 9] and list(meta.columns) == ["_linha", "_rotulo"]


def test_conferencia_de_reproducao_aceita_nan_e_acusa_diferenca() -> None:
    import b6_conferir_final2 as b6
    a = pd.DataFrame({"_linha": [1, 2, 3], "x": [0.5, np.nan, 2.0], "y": [1, 2, 3]})
    assert b6.iguais(a, a.iloc[::-1])["identico"]
    b = a.copy()
    b.loc[2, "x"] = 2.0 + 1e-12
    r = b6.iguais(a, b)
    assert not r["identico"] and r["colunas_diferentes"] == ["x"]


def test_comparacao_de_reproducao_acusa_coeficientes_diferentes() -> None:
    import g_reproduzir_treinos as repro
    from sklearn.linear_model import LogisticRegression
    from src.ml.preparacao import montar_pipeline_financeiro
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(200, 3)), columns=["a", "b", "c"])
    y = (X["a"] + rng.normal(size=200) > 0).astype(int).to_numpy()

    def ajustado(C: float):
        return montar_pipeline_financeiro(LogisticRegression(C=C, max_iter=500), True).fit(X, y)
    igual = repro.comparar_configuracao(ajustado(1.0), ajustado(1.0))
    assert igual["coef_max_dif_abs"] == 0.0 and igual["parametros_iguais"] is True
    dif = repro.comparar_configuracao(ajustado(1.0), ajustado(0.01))
    assert dif["coef_max_dif_abs"] > 0 and "C" in dif["parametros_iguais"]
