"""Dados e modelo de teste do painel do analista.

Tudo aqui é SINTÉTICO e pequeno. O modelo de teste (``ModeloDeTeste``) usa o
preparador real do ``modelo_minimo`` (mesmos atributos e motivos), mas a
"probabilidade" é uma regra fixa sobre o valor em dólar, para os testes
saberem de antemão quem recebe alerta:

    score bruto = valor em USD / 100.000 (limitado a 1); limiar = 0,5

Assim, 80.000 USD → alerta; 30.000 USD → faixa intermediária; 10.000 → baixa.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pytest

from src.painel.datasets import RepositorioDatasets
from src.painel.pipeline import GerenciadorAnalises
from src.painel.sistema import Registro
from testes.ml.conftest import modelo_minimo  # noqa: F401  (fixture de sessão reaproveitada)

CABECALHO = ("Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,Amount Paid,"
             "Payment Currency,Payment Format")
LIMIAR_TESTE = 0.5


class CabecaDeTeste:
    tarefa = "lavagem"
    classes = [0, 1]
    familia = "regra_de_teste"
    params: Dict[str, Any] = {}
    limiar_alerta = LIMIAR_TESTE

    def __init__(self, colunas: Sequence[str], ao_pontuar: Optional[Callable[[int], None]] = None):
        self.colunas_entrada = list(colunas)
        self.metadados = {"versao": "teste-painel-v1", "treinado_ate": "2020-01-01", "fonte": "regra fixa de teste"}
        self.ao_pontuar = ao_pontuar
        self.chamadas = 0

    def probabilidades(self, X) -> np.ndarray:
        self.chamadas += 1
        if self.ao_pontuar:
            self.ao_pontuar(self.chamadas)
        usd = np.expm1(np.nan_to_num(X["log_valor_usd"].to_numpy(dtype=np.float64)))
        p = np.clip(usd / 100_000.0, 0.0, 1.0)
        return np.column_stack([1 - p, p])


class ModeloDeTeste:
    def __init__(self, prep: Any, colunas: Sequence[str], ao_pontuar: Optional[Callable[[int], None]] = None):
        self.cab = CabecaDeTeste(colunas, ao_pontuar)
        self.codificadores = {"financeiro": prep}

    def cabeca(self, tarefa: str) -> CabecaDeTeste:
        assert tarefa == "lavagem"
        return self.cab


@pytest.fixture
def fabrica_modelo(modelo_minimo):  # noqa: F811
    prep = modelo_minimo.codificadores["financeiro"]
    colunas = modelo_minimo.cabeca("lavagem").colunas_entrada

    def criar(ao_pontuar: Optional[Callable[[int], None]] = None) -> ModeloDeTeste:
        return ModeloDeTeste(prep, colunas, ao_pontuar)

    return criar


def linha(ts: str, banco_o: Any, conta_o: str, banco_d: Any, conta_d: str, valor: float, moeda: str = "US Dollar",
          formato: str = "Wire", rotulo: Optional[int] = None, moeda_rec: Optional[str] = None) -> str:
    campos = [ts, str(banco_o), conta_o, str(banco_d), conta_d, f"{valor:.2f}", moeda_rec or moeda, f"{valor:.2f}",
              moeda, formato]
    if rotulo is not None:
        campos.append(str(rotulo))
    return ",".join(campos)


def escrever(caminho: Path, linhas: Sequence[str], com_rotulo: bool = False) -> Path:
    cab = CABECALHO + (",Is Laundering" if com_rotulo else "")
    caminho.write_text(cab + "\n" + "\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


D = "2024/01/05"
# Cenário principal: 13 transações, com rótulo. A ordem das linhas NÃO é a cronológica de propósito.
CENARIO: List[str] = [
    linha(f"{D} 10:00", 1, "A", 1, "B", 80_000, rotulo=1),                    # linha 2  alerta  FAN-OUT
    linha(f"{D} 10:00", 1, "A", 1, "C", 90_000, rotulo=1),                    # linha 3  alerta  FAN-OUT
    linha(f"{D} 10:05", 1, "A", 1, "D", 10_000, formato="ACH", rotulo=0),     # linha 4  baixa
    linha(f"{D} 10:10", 1, "B", 2, "E", 85_000, rotulo=1),                    # linha 5  alerta  CYCLE + STACK
    linha(f"{D} 10:10", 1, "B", 2, "E", 85_000, rotulo=1),                    # linha 6  alerta  (idêntica à 5)
    linha(f"{D} 10:20", 2, "E", 1, "A", 30_000, formato="Cheque", rotulo=0),  # linha 7  intermediária
    linha(f"{D} 10:30", 1, "C", 2, "F", 500, moeda="Euro", formato="", rotulo=0),   # linha 8  formato vazio
    linha(f"{D} 10:30", 1, "C", 2, "F", 70_000, moeda="Euro", rotulo=0),      # linha 9  alerta (77.000 USD)
    linha(f"{D} 10:40", 1, "C", 2, "F", 1_000, formato="ACH", rotulo=0),      # linha 10 outra moeda, mesmo par
    linha(f"{D} 09:00", 3, "X", 3, "Y", 100, formato="Cash", rotulo=0),       # linha 11 a mais antiga
    linha(f"{D} 10:00", 3, "Z", 1, "A", 200, formato="Cash", rotulo=0),       # linha 12 empate de horário com 2 e 3
    linha(f"{D} 11:00", 1, "A", 1, "A", 300, formato="ACH", rotulo=0),        # linha 13 autotransferência
    linha(f"{D} 11:30", 1, "D", 2, "G", 1, moeda="Yen", formato="Unknown", rotulo=0),  # linha 14 formato desconhecido
]
# id de exibição esperado → linha do arquivo (ordem por horário; empate pela ordem da linha)
ORDEM_ESPERADA = [11, 2, 3, 12, 4, 5, 6, 7, 8, 9, 10, 13, 14]
LINHAS_COM_ALERTA = {2, 3, 5, 6, 9}

PADROES = f"""BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 2-degree Fan-Out
{D} 10:00,001,A,001,B,80000.00,US Dollar,80000.00,US Dollar,Wire,1
{D} 10:00,001,A,001,C,90000.00,US Dollar,90000.00,US Dollar,Wire,1
END LAUNDERING ATTEMPT - FAN-OUT

BEGIN LAUNDERING ATTEMPT - CYCLE:  Max 3 hops
{D} 10:10,001,B,002,E,85000.00,US Dollar,85000.00,US Dollar,Wire,1
END LAUNDERING ATTEMPT - CYCLE

BEGIN LAUNDERING ATTEMPT - STACK
{D} 10:10,001,B,002,E,85000.00,US Dollar,85000.00,US Dollar,Wire,1
2024/01/09 10:10,001,Q,002,R,1.00,US Dollar,1.00,US Dollar,Wire,1
END LAUNDERING ATTEMPT - STACK
"""


class Ambiente:
    """Repositório de datasets + gerenciador de análises numa pasta temporária."""

    def __init__(self, raiz: Path, modelo: Any, bloco: int = 4, max_analises: int = 20):
        self.raiz = raiz
        self.registro = Registro(raiz / "artefatos_ml" / "painel" / "logs")
        self.datasets = RepositorioDatasets(raiz, self.registro)
        self.cargas_do_modelo = 0

        def obter() -> Any:
            self.cargas_do_modelo += 1
            return modelo

        self.analises = GerenciadorAnalises(raiz, self.datasets, obter, self.registro, bloco, max_analises)

    def enviar(self, caminho: Path, padroes: Optional[Path] = None, nome: Optional[str] = None) -> Dict[str, Any]:
        with open(caminho, "rb") as fh:
            if padroes is not None:
                with open(padroes, "rb") as fp:
                    reg = self.datasets.enviar(fh, nome or caminho.name, fp, padroes.name, validar=False)
            else:
                reg = self.datasets.enviar(fh, nome or caminho.name, validar=False)
        return self.datasets.validar(reg["id"], esperar=True)

    def analisar(self, caminho: Path, padroes: Optional[Path] = None) -> Dict[str, Any]:
        reg = self.enviar(caminho, padroes)
        assert reg["status"] in ("valido", "valido_com_recusas"), reg
        m = self.analises.iniciar(reg["id"])
        return self.analises.esperar(m["id"], 120)


@pytest.fixture
def ambiente(tmp_path: Path, fabrica_modelo) -> Ambiente:
    return Ambiente(tmp_path, fabrica_modelo())


@pytest.fixture
def cenario(tmp_path: Path) -> Dict[str, Path]:
    pasta = tmp_path / "entrada"
    pasta.mkdir()
    dados = escrever(pasta / "cenario.csv", CENARIO, com_rotulo=True)
    padroes = pasta / "cenario_padroes.txt"
    padroes.write_text(PADROES, encoding="utf-8")
    return {"dados": dados, "padroes": padroes}


@pytest.fixture
def analise_cenario(ambiente: Ambiente, cenario: Dict[str, Path]):
    """Cenário analisado com tipologias: ``(ambiente, manifesto, conexão de leitura)``."""
    m = ambiente.analisar(cenario["dados"], cenario["padroes"])
    assert m["status"] == "concluida", m
    con = ambiente.analises.conexao(m["id"])
    yield ambiente, m, con
    con.close()


class Portao:
    """Para o modelo de teste num bloco escolhido, para exercitar cancelamento e concorrência."""

    def __init__(self) -> None:
        self.chegou = threading.Event()
        self.liberar = threading.Event()

    def em(self, bloco: int) -> Callable[[int], None]:
        def gancho(chamada: int) -> None:
            if chamada == bloco:
                self.chegou.set()
                assert self.liberar.wait(30), "o teste não liberou o modelo"
        return gancho


class Relogio:
    """Relógio controlável das sessões: os testes avançam o tempo sem esperar."""

    def __init__(self) -> None:
        self.t = 2_000_000_000.0

    def __call__(self) -> float:
        return self.t

    def avancar(self, segundos: float) -> None:
        self.t += segundos


class ClienteComSessao:
    """Cliente de teste que manda o cabeçalho da sessão, como a página do painel."""

    CABECALHO = "X-NodeWatch-Sessao"

    def __init__(self, bruto: Any, sid: str, relogio: Relogio, sessoes: Any):
        self.bruto, self.sid, self.relogio, self.sessoes = bruto, sid, relogio, sessoes

    def _com(self, kw: Dict[str, Any]) -> Dict[str, Any]:
        cab = dict(kw.pop("headers", None) or {})
        cab.setdefault(self.CABECALHO, self.sid)
        return dict(kw, headers=cab)

    def get(self, *a: Any, **kw: Any):
        return self.bruto.get(*a, **self._com(kw))

    def post(self, *a: Any, **kw: Any):
        return self.bruto.post(*a, **self._com(kw))

    def options(self, *a: Any, **kw: Any):
        return self.bruto.options(*a, **kw)


def abrir_cliente(raiz: Path, modelo: Any, bloco: int = 4, **config: Any) -> ClienteComSessao:
    """Configura a API numa pasta temporária e abre uma sessão (o que a página faz ao carregar)."""
    from src import api_painel
    from src.ml.sessoes import GerenciadorSessoes
    from src.sentinel_ai import app

    relogio = Relogio()
    sessoes = GerenciadorSessoes(relogio=relogio)
    api_painel.configurar(raiz, modelo=modelo, bloco=bloco, sessoes=sessoes, **config)
    app.config["TESTING"] = True
    bruto = app.test_client()
    sid = bruto.post("/api/painel/sessao", json={}).get_json()["sessao"]["id"]
    return ClienteComSessao(bruto, sid, relogio, sessoes)
