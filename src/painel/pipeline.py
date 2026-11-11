"""Execução da análise: etapas reais, progresso medido, cancelamento e manifesto.

Etapas (todas medidas; nenhuma é simulada):

1. ``leitura``     leitura e validação do arquivo, em blocos (bytes lidos / total);
2. ``ordenacao``   ordenação cronológica e atribuição dos IDs de exibição;
3. ``tipologias``  casamento com o arquivo de padrões (pulada se não houver);
4. ``pontuacao``   por blocos: preparação de atributos (estado incremental por
                   conta), inferência com o modelo salvo e gravação no SQLite
                   (transações pontuadas / total);
5. ``indices``     índices dos campos filtráveis e contagens gerais;
6. ``manifesto``   gravação final do manifesto.

A estimativa de tempo restante só existe quando há base medida (ao menos
``ESTIMATIVA_MIN_S`` segundos de etapa e algum progresso): restante = o que
falta ÷ vazão observada. Fora disso o campo não é enviado.

Cancelamento: o pedido é atendido no próximo ponto seguro (entre blocos de
leitura ou de pontuação). O que já foi pontuado fica gravado e consultável.

Sessão da interface: quando o gerenciador recebe ``sessao_ativa`` (é o caso da
API), a análise só começa com uma sessão ativa e só avança enquanto a sessão
que a iniciou (ou a que a assumiu) continuar ativa. Nos mesmos pontos seguros
do cancelamento, se a sessão expirou ou foi encerrada, a análise para, guarda
o que já pontuou e fica ``parcial``. Ela nunca é retomada sozinha: reabrir a
interface só mostra o que ficou gravado.

Estados do manifesto: ``em_andamento``, ``concluida``, ``cancelada`` (a pedido
do analista), ``parcial`` (interrompida sem pedido: sessão da interface
expirada ou servidor reiniciado; vale o que foi processado) e ``erro`` (com
causa e ação sugerida).

Persistência: ``artefatos_ml/painel/analises/<id>/manifesto.json`` (escrita
atômica) e ``resultados.sqlite``. Retenção: as ``MAX_ANALISES`` análises mais
recentes; as mais antigas são removidas quando uma nova começa.

Uma análise por vez. Nada é treinado nem reajustado: a pontuação reusa
``EstadoFinanceiro`` e ``pontuar_lavagem`` (os mesmos do processamento de
eventos e da área "Analisar dataset" anterior).
"""

from __future__ import annotations

import copy
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from src.ml.incremental import EstadoFinanceiro
from src.ml.previsao import pontuar_lavagem
from src.painel import armazenamento as arm
from src.painel import score as sc
from src.painel import tipologias as tp
from src.painel.datasets import Cancelado, ErroDataset, RepositorioDatasets, identificar, ler_validando
from src.painel.sistema import memoria_processo
from src.painel.util import agora_iso, gravar_json_atomico, ler_json

PASTA = Path("artefatos_ml") / "painel" / "analises"
MAX_ANALISES = 20
BLOCO = 20_000
ESTIMATIVA_MIN_S = 3.0
GRAVAR_MANIFESTO_A_CADA_S = 2.0
STATUS_FINAIS = ("concluida", "cancelada", "parcial", "erro")
ETAPAS = (
    ("leitura", "Leitura e validação do arquivo", "bytes"),
    ("ordenacao", "Ordenação cronológica e IDs de exibição", None),
    ("tipologias", "Tipologias registradas no dataset", None),
    ("pontuacao", "Atributos, inferência e gravação (em blocos)", "transações"),
    ("indices", "Índices e contagens gerais", "passos"),
    ("manifesto", "Gravação do manifesto", None),
)
DESCRICAO_STATUS = {
    "em_andamento": "Em andamento: a análise está sendo processada.",
    "concluida": "Concluída: todas as transações válidas foram pontuadas.",
    "cancelada": "Cancelada: interrompida a pedido; vale só o que foi processado até o cancelamento.",
    "parcial": ("Parcial: interrompida sem pedido (sessão da interface expirada ou servidor reiniciado); "
                "vale só o que foi processado."),
    "erro": "Erro: a análise parou por uma falha; veja a causa e a ação sugerida.",
}


class ErroAnaliseOcupada(RuntimeError):
    """Já existe uma análise em andamento."""


class SessaoInativa(PermissionError):
    """A ação exige uma sessão ativa da interface."""


class SemResultados(LookupError):
    """A análise não tem resultados gravados para consultar."""


def _n(valor: Any) -> str:
    """Inteiro com separador de milhar no padrão brasileiro (1.234.567)."""
    return f"{int(valor):,}".replace(",", ".")


def _acao_para(exc: BaseException) -> str:
    if isinstance(exc, FileNotFoundError):
        return "Confira se o modelo foi treinado (`python -m src.ml.cli treinar --tarefa todas`) e se o arquivo existe."
    if isinstance(exc, MemoryError):
        return "Falta memória para este arquivo: divida o dataset por período e analise cada parte."
    if isinstance(exc, ImportError):
        return "Instale as dependências de ML: `python -m pip install -r requirements-ml.txt`."
    return "Tente de novo. Se o erro se repetir, valide o dataset outra vez e consulte os logs do sistema."


class GerenciadorAnalises:
    def __init__(self, raiz: Path, datasets: RepositorioDatasets, obter_modelo: Callable[[], Any],
                 registro: Any = None, bloco: int = BLOCO, max_analises: int = MAX_ANALISES,
                 sessao_ativa: Optional[Callable[[Optional[str]], bool]] = None, janela_sessao_s: Optional[float] = None):
        self.raiz = Path(raiz)
        self.pasta = self.raiz / PASTA
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.datasets = datasets
        self.obter_modelo = obter_modelo
        self.registro = registro
        self.bloco = int(bloco)
        self.max_analises = int(max_analises)
        self.sessao_ativa = sessao_ativa          # None = sem controle de sessão (uso direto, fora da API)
        self.janela_sessao_s = janela_sessao_s
        self._donos: Dict[str, Optional[str]] = {}  # análise → sessão responsável (só em memória)
        self._parada: Dict[str, str] = {}
        self._indices_conferidos: set = set()
        self._trava = threading.RLock()
        self._manifestos: Dict[str, Dict[str, Any]] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._cancelar: Dict[str, threading.Event] = {}
        self._inicio_etapa: Dict[str, float] = {}
        self._ultima_gravacao: Dict[str, float] = {}
        for arq in sorted(self.pasta.glob("*/manifesto.json")):
            m = ler_json(arq)
            if not m or "id" not in m:
                continue
            if m.get("status") == "em_andamento":  # o processo anterior caiu no meio
                self._recuperar(m)
            self._manifestos[m["id"]] = m

    # -- utilidades -----------------------------------------------------------
    def _dir(self, aid: str) -> Path:
        return self.pasta / aid

    def caminho_db(self, aid: str) -> Path:
        return self._dir(aid) / "resultados.sqlite"

    def _log(self, evento: str, mensagem: str, nivel: str = "info", **ctx: Any) -> None:
        if self.registro is not None:
            self.registro.sistema(evento, mensagem, nivel, **ctx)

    def _log_ml(self, evento: str, mensagem: str, nivel: str = "info", **ctx: Any) -> None:
        if self.registro is not None:
            self.registro.ml(evento, mensagem, nivel, **ctx)

    def _gravar(self, m: Dict[str, Any]) -> None:
        with self._trava:
            gravar_json_atomico(self._dir(m["id"]) / "manifesto.json", m)
            self._ultima_gravacao[m["id"]] = time.monotonic()

    def _recuperar(self, m: Dict[str, Any]) -> None:
        db = self.caminho_db(m["id"])
        pontuadas = 0
        if db.is_file():
            try:
                arm.garantir_finalizado(db)
                con = arm.conectar(db)
                try:
                    cont = arm.contagens_gerais(con)
                finally:
                    con.close()
                pontuadas = cont["pontuadas"]
                m.setdefault("contagens", {}).update(cont)
            except Exception:  # banco ilegível: trata como sem resultados
                pontuadas = 0
        for e in m.get("etapas", []):
            if e["status"] == "em_andamento":
                e["status"] = "interrompida"
        if pontuadas:
            m["status"] = "parcial"
            m["resultados"] = {"disponiveis": True, "parciais": True, "pontuadas": pontuadas,
                               "de": m.get("contagens", {}).get("validas")}
            m["motivo"] = ("O servidor foi reiniciado durante a análise. Vale o que foi processado: "
                           f"{_n(pontuadas)} transações pontuadas.")
        else:
            m["status"] = "erro"
            m["resultados"] = {"disponiveis": False, "parciais": False, "pontuadas": 0}
            m["erros"] = m.get("erros", []) + [{
                "quando": agora_iso(), "causa": "O servidor foi reiniciado antes de a análise pontuar transações.",
                "acao": "Inicie a análise de novo."}]
        m["concluida_em"] = agora_iso()
        gravar_json_atomico(self._dir(m["id"]) / "manifesto.json", m)
        self._log("analise_interrompida", "Análise interrompida por reinício do servidor", "aviso",
                  analise=m["id"], situacao=m["status"], pontuadas=pontuadas)

    def _retencao(self) -> None:
        with self._trava:
            finais = sorted((m for m in self._manifestos.values() if m["status"] in STATUS_FINAIS),
                            key=lambda m: (m.get("ordem", 0), m["criada_em"]), reverse=True)
            for m in finais[max(0, self.max_analises - 1):]:
                shutil.rmtree(self._dir(m["id"]), ignore_errors=True)
                self._manifestos.pop(m["id"], None)
                self._log("retencao", "Análise mais antiga removida pelo limite de retenção", analise=m["id"],
                          limite=self.max_analises)

    # -- consulta ---------------------------------------------------------------
    def em_andamento(self) -> Optional[str]:
        with self._trava:
            return next((m["id"] for m in self._manifestos.values() if m["status"] == "em_andamento"), None)

    def obter(self, aid: str) -> Dict[str, Any]:
        with self._trava:
            if aid not in self._manifestos:
                raise KeyError(aid)
            m = copy.deepcopy(self._manifestos[aid])
        m["descricao_status"] = DESCRICAO_STATUS.get(m["status"], "")
        return m

    def listar(self, limite: int = MAX_ANALISES) -> List[Dict[str, Any]]:
        with self._trava:
            ms = sorted(self._manifestos.values(), key=lambda m: (m.get("ordem", 0), m["criada_em"]), reverse=True)[:max(1, int(limite))]
            return [{"id": m["id"], "dataset": {"nome": m["dataset"]["nome"], "id": m["dataset"]["id"]},
                     "criada_em": m["criada_em"], "status": m["status"],
                     "descricao_status": DESCRICAO_STATUS.get(m["status"], ""),
                     "registros": m.get("contagens", {}).get("pontuadas"),
                     "alertas": m.get("contagens", {}).get("alertas"),
                     "duracao_s": m.get("duracao_s"),
                     "resultados": m.get("resultados", {"disponiveis": False})} for m in ms]

    def situacao_sessao(self, aid: str, sessao: Optional[str]) -> Dict[str, Any]:
        """Relação entre a análise e a sessão de quem consulta (não altera nada)."""
        if self.sessao_ativa is None:
            return {"exigida": False}
        dona = self._donos.get(aid)
        return {"exigida": True, "desta_sessao": bool(dona and dona == sessao),
                "responsavel_ativa": bool(self.sessao_ativa(dona)), "janela_s": self.janela_sessao_s}

    def assumir(self, aid: str, sessao: Optional[str]) -> Dict[str, Any]:
        """Ação explícita: outra aba ativa passa a ser a responsável por uma análise em andamento."""
        if self.sessao_ativa is not None and not self.sessao_ativa(sessao):
            raise SessaoInativa("sessão inativa")
        with self._trava:
            m = self._manifestos.get(aid)
            if m is None:
                raise KeyError(aid)
            if m["status"] == "em_andamento":
                self._donos[aid] = sessao
                self._log("analise_assumida", "Análise assumida por outra sessão ativa da interface", analise=aid)
        return self.obter(aid)

    def conexao(self, aid: str):
        """Conexão só de leitura com os resultados gravados (não reprocessa nada)."""
        m = self.obter(aid)
        if not m.get("resultados", {}).get("disponiveis"):
            raise SemResultados(aid)
        with self._trava:
            if aid not in self._indices_conferidos:  # resultado gravado por versão anterior: completa os índices
                criados = arm.garantir_indices(self.caminho_db(aid))
                self._indices_conferidos.add(aid)
                if criados:
                    self._log("indices_atualizados", "Índices acrescentados a uma análise gravada por versão anterior",
                              analise=aid, indices=criados)
        return arm.conectar(self.caminho_db(aid))

    def esperar(self, aid: str, timeout: float = 300.0) -> Dict[str, Any]:
        t = self._threads.get(aid)
        if t:
            t.join(timeout)
        return self.obter(aid)

    # -- controle -----------------------------------------------------------------
    def iniciar(self, dataset_id: str, sessao: Optional[str] = None) -> Dict[str, Any]:
        """Ação explícita "Analisar": exige sessão ativa, dataset válido e nenhuma outra análise em andamento."""
        if self.sessao_ativa is not None and not self.sessao_ativa(sessao):
            raise SessaoInativa("sessão inativa")
        reg = self.datasets.obter(dataset_id)
        if reg["status"] not in ("valido", "valido_com_recusas"):
            raise ErroDataset([{"coluna": None, "linha_exemplo": None, "valor_exemplo": None, "linhas_afetadas": None,
                                "problema": "o dataset ainda não foi validado ou é inválido",
                                "como_corrigir": "Valide o dataset e corrija os problemas antes de analisar."}], 409)
        with self._trava:
            ocupada = self.em_andamento()
            if ocupada:
                raise ErroAnaliseOcupada(ocupada)
            self._retencao()
            aid = "an-" + time.strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)
            val = reg["validacao"]
            m: Dict[str, Any] = {
                "id": aid, "criada_em": agora_iso(), "ordem": time.time_ns(), "iniciada_em": agora_iso(),
                "concluida_em": None,
                "status": "em_andamento", "motivo": "",
                "dataset": {"id": reg["id"], "nome": reg["nome"], "origem": reg["origem"], "bytes": reg["bytes"],
                            "sha256": val["sha256"], "formato": val["formato"], "formato_nome": val["formato_nome"],
                            "colunas": val["colunas"], "colunas_nao_reconhecidas": val["colunas_nao_reconhecidas"],
                            "padroes": reg.get("padroes")},
                "etapas": [{"id": i, "nome": n, "unidade": u, "status": "pendente", "inicio": None, "fim": None,
                            "duracao_s": None, "progresso": None, "detalhe": ""} for i, n, u in ETAPAS],
                "duracao_s": None, "modelo": None, "conversao_score": None, "faixas": sc.FAIXAS,
                "contagens": {"lidas": 0, "validas": 0, "recusadas": 0, "pontuadas": 0, "alertas": 0},
                "resultados": {"disponiveis": False, "parciais": False, "pontuadas": 0},
                "tipologias": {"disponivel": False, "motivo": val["tipologias"].get("motivo", "")},
                "rotulo": {"disponivel": bool(val["rotulo"]["disponivel"])},
                "desempenho": {}, "avisos": [], "erros": [], "cancelamento_solicitado": False,
                "retencao": {"max_analises": self.max_analises},
                "sessao": {"exigida": self.sessao_ativa is not None, "janela_s": self.janela_sessao_s,
                           "leitura": ("A análise só avança enquanto a sessão da interface que a iniciou estiver "
                                       "ativa; sem sinal da aba, ela para num ponto seguro e não é retomada sozinha.")
                           if self.sessao_ativa is not None else "Sem controle de sessão (uso direto)."},
            }
            self._dir(aid).mkdir(parents=True)
            self._manifestos[aid] = m
            self._cancelar[aid] = threading.Event()
            self._donos[aid] = sessao
            self._gravar(m)
            self.datasets.marcar_uso(dataset_id, True)
            t = threading.Thread(target=self._executar, args=(aid,), name=f"painel-{aid}", daemon=True)
            self._threads[aid] = t
            t.start()
        self._log("analise_inicio", "Análise iniciada", analise=aid, dataset=reg["id"], nome=reg["nome"])
        return self.obter(aid)

    def cancelar(self, aid: str, sessao: Optional[str] = None) -> Dict[str, Any]:
        """Qualquer sessão ativa pode cancelar; o efeito vem no próximo ponto seguro."""
        if self.sessao_ativa is not None and not self.sessao_ativa(sessao):
            raise SessaoInativa("sessão inativa")
        with self._trava:
            m = self._manifestos.get(aid)
            if m is None:
                raise KeyError(aid)
            if m["status"] == "em_andamento" and aid in self._cancelar:
                self._cancelar[aid].set()
                m["cancelamento_solicitado"] = True
                self._log("analise_cancelamento", "Cancelamento solicitado", analise=aid)
        return self.obter(aid)

    def _interromper(self, aid: str) -> bool:
        """Ponto seguro: há pedido de cancelamento, ou a sessão responsável deixou de estar ativa?"""
        if self._cancelar[aid].is_set():
            self._parada[aid] = "cancelada"
            return True
        if self.sessao_ativa is not None and not self.sessao_ativa(self._donos.get(aid)):
            self._parada[aid] = "sessao"
            return True
        return False

    # -- etapas ---------------------------------------------------------------------
    def _etapa(self, m: Dict[str, Any], eid: str) -> Dict[str, Any]:
        return next(e for e in m["etapas"] if e["id"] == eid)

    def _abrir_etapa(self, m: Dict[str, Any], eid: str) -> Dict[str, Any]:
        with self._trava:
            e = self._etapa(m, eid)
            e.update(status="em_andamento", inicio=agora_iso())
            self._inicio_etapa[m["id"] + eid] = time.monotonic()
            self._gravar(m)
        return e

    def _fechar_etapa(self, m: Dict[str, Any], eid: str, status: str = "concluida", detalhe: str = "") -> None:
        with self._trava:
            e = self._etapa(m, eid)
            ini = self._inicio_etapa.get(m["id"] + eid)
            e.update(status=status, fim=agora_iso(),
                     duracao_s=round(time.monotonic() - ini, 3) if ini is not None else None)
            if detalhe:
                e["detalhe"] = detalhe
            if e.get("progresso"):
                e["progresso"].pop("estimativa_restante_s", None)
            self._gravar(m)

    def _progresso(self, m: Dict[str, Any], eid: str, feito: float, total: float, extra: Optional[Dict] = None) -> None:
        """Atualiza o progresso medido; a estimativa só aparece com base observada."""
        with self._trava:
            e = self._etapa(m, eid)
            decorrido = time.monotonic() - self._inicio_etapa.get(m["id"] + eid, time.monotonic())
            p: Dict[str, Any] = {"feito": int(feito), "total": int(total), "unidade": e["unidade"],
                                 "fracao": (feito / total) if total else None, "decorrido_s": round(decorrido, 1)}
            if decorrido >= ESTIMATIVA_MIN_S and 0 < feito < total:
                vazao = feito / decorrido
                p["vazao_por_s"] = vazao
                p["estimativa_restante_s"] = round((total - feito) / vazao, 1)
                p["base_estimativa"] = (f"vazão observada nesta etapa: {vazao:,.0f} {e['unidade']}/s em "
                                        f"{decorrido:.0f} s").replace(",", ".")
            if extra:
                p.update(extra)
            e["progresso"] = p
            if time.monotonic() - self._ultima_gravacao.get(m["id"], 0) >= GRAVAR_MANIFESTO_A_CADA_S:
                self._gravar(m)

    # -- execução -------------------------------------------------------------------
    def _executar(self, aid: str) -> None:
        m = self._manifestos[aid]
        inicio = time.monotonic()
        gravador: Optional[arm.Gravador] = None
        etapa_atual = "leitura"
        status, motivo = "concluida", ""
        try:
            dados, padroes = self.datasets.caminhos(m["dataset"]["id"])
            # 1. leitura e validação
            self._abrir_etapa(m, "leitura")
            ident = identificar(dados)
            partes, info = [], {"lidas": 0}
            for bloco, info in ler_validando(
                    dados, ident["formato"], ident["colunas"],
                    progresso=lambda lidos, total, linhas: self._progresso(m, "leitura", lidos, total,
                                                                           {"linhas_lidas": int(linhas)}),
                    cancelar=lambda: self._interromper(aid)):
                partes.append(bloco)
            df = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
            del partes
            lidas, validas = int(info["lidas"]), int(len(df))
            m["contagens"].update(lidas=lidas, validas=validas, recusadas=lidas - validas)
            if validas == 0:
                raise ErroDataset([{"coluna": None, "linha_exemplo": None, "valor_exemplo": None,
                                    "linhas_afetadas": lidas, "problema": "nenhuma linha válida no arquivo",
                                    "como_corrigir": "Valide o dataset de novo e corrija os problemas listados."}])
            self._fechar_etapa(m, "leitura", detalhe=f"{_n(lidas)} linhas lidas, {_n(validas)} válidas, "
                                                     f"{_n(lidas - validas)} recusadas")
            # 2. ordenação cronológica e IDs de exibição (empate: ordem original da linha)
            etapa_atual = "ordenacao"
            self._abrir_etapa(m, "ordenacao")
            ordem = np.lexsort((df["linha"].to_numpy(), df["minuto"].to_numpy()))
            df = df.iloc[ordem].reset_index(drop=True)
            df["id_exibicao"] = np.arange(1, len(df) + 1, dtype=np.int64)
            self._fechar_etapa(m, "ordenacao", detalhe=f"IDs de 1 a {_n(len(df))}, por data e hora; empates pela "
                                                       "ordem da linha")
            # 3. tipologias registradas (arquivo de padrões)
            etapa_atual = "tipologias"
            if self._interromper(aid):
                raise Cancelado()
            if padroes is not None:
                self._abrir_etapa(m, "tipologias")
                try:
                    pad = tp.ler_arquivo_padroes(padroes)
                    tipos, tents, casamento = tp.casar(pad, df)
                    df["tipologias"], df["tentativas"] = tipos, tents
                    m["tipologias"] = {"disponivel": True,
                                       "origem": "registrada no dataset (arquivo de padrões); não é previsão",
                                       "arquivo": m["dataset"]["padroes"], **tp.resumo_arquivo(pad),
                                       "casamento": casamento}
                    self._fechar_etapa(m, "tipologias", detalhe=f"{_n(casamento['transacoes_com_tipologia'])} "
                                       f"transações com tipologia; {_n(casamento['sem_correspondencia'])} linhas do "
                                       "arquivo de padrões sem transação correspondente")
                except tp.ErroPadroes as exc:
                    df["tipologias"], df["tentativas"] = "", ""
                    m["tipologias"] = {"disponivel": False, "motivo": f"Arquivo de padrões recusado: {exc}."}
                    m["avisos"].append(f"Tipologias indisponíveis: {exc}.")
                    self._fechar_etapa(m, "tipologias", "pulada", f"arquivo de padrões recusado: {exc}")
            else:
                df["tipologias"], df["tentativas"] = "", ""
                m["tipologias"] = {"disponivel": False, "motivo": "Este dataset não tem tipologias registradas: "
                                   "nenhum arquivo de padrões foi enviado com ele."}
                with self._trava:
                    self._etapa(m, "tipologias").update(status="pulada", detalhe="sem arquivo de padrões")
            # 4. pontuação em blocos
            etapa_atual = "pontuacao"
            self._abrir_etapa(m, "pontuacao")
            gravador = arm.Gravador(self.caminho_db(aid))
            self._pontuar(m, df, gravador)
            self._fechar_etapa(m, "pontuacao", detalhe=self._etapa(m, "pontuacao")["detalhe"])
        except Cancelado:
            if self._parada.get(aid) == "sessao":
                status = "parcial"
                motivo = ("A sessão da interface responsável por esta análise expirou ou foi encerrada"
                          + (f" (sem sinal da aba por mais de {int(self.janela_sessao_s)} s)" if self.janela_sessao_s else "")
                          + ". A análise parou num ponto seguro e não é retomada sozinha: inicie de novo se "
                            "precisar do resultado completo.")
                m["interrupcao"] = "sessao_expirada"
                self._log("analise_sessao_expirada", "Análise interrompida: a sessão da interface expirou", "aviso",
                          analise=aid, etapa=etapa_atual)
                self._fechar_etapa(m, etapa_atual, "interrompida")
            else:
                status, motivo = "cancelada", "Cancelada a pedido do analista."
                self._fechar_etapa(m, etapa_atual, "cancelada")
        except ErroDataset as exc:
            status = "erro"
            p = exc.problemas[0]
            m["erros"].append({"quando": agora_iso(), "etapa": etapa_atual, "causa": p["problema"],
                               "acao": p["como_corrigir"], "coluna": p.get("coluna"), "linha": p.get("linha_exemplo")})
            self._fechar_etapa(m, etapa_atual, "erro")
        except Exception as exc:  # erro visível na tela, com causa e ação
            status = "erro"
            m["erros"].append({"quando": agora_iso(), "etapa": etapa_atual,
                               "causa": f"{type(exc).__name__}: {str(exc)[:300]}", "acao": _acao_para(exc)})
            self._fechar_etapa(m, etapa_atual, "erro")
        # 5 e 6: o que foi gravado fica consultável, mesmo em cancelamento ou erro
        try:
            if gravador is not None and gravador.gravadas > 0:
                self._abrir_etapa(m, "indices")
                gravador.finalizar(lambda feito, total: self._progresso(m, "indices", feito, total))
                gravador = None
                con = arm.conectar(self.caminho_db(aid))
                try:
                    m["contagens"].update(arm.contagens_gerais(con))
                finally:
                    con.close()
                self._fechar_etapa(m, "indices")
                parcial = m["contagens"]["pontuadas"] < m["contagens"]["validas"]
                m["resultados"] = {"disponiveis": True, "parciais": parcial,
                                   "pontuadas": m["contagens"]["pontuadas"], "de": m["contagens"]["validas"]}
                if status != "concluida" and parcial:
                    motivo = (motivo + " " if motivo else "") + (
                        f"Resultado parcial: {_n(m['contagens']['pontuadas'])} de {_n(m['contagens']['validas'])} "
                        "transações válidas foram pontuadas (as primeiras, em ordem cronológica).")
        except Exception as exc:
            status = "erro"
            m["erros"].append({"quando": agora_iso(), "etapa": "indices",
                               "causa": f"{type(exc).__name__}: {str(exc)[:300]}", "acao": _acao_para(exc)})
        finally:
            if gravador is not None:
                gravador.fechar()
        # O log de fim e a liberação do dataset vêm antes de o status mudar: quem lê "concluída" já encontra tudo.
        duracao = round(time.monotonic() - inicio, 3)
        self.datasets.marcar_uso(m["dataset"]["id"], False)
        nivel = "info" if status == "concluida" else ("aviso" if status == "cancelada" else "erro")
        self._log("analise_fim", f"Análise {DESCRICAO_STATUS[status].split(':')[0].lower()}", nivel, analise=aid,
                  situacao=status, pontuadas=m["contagens"]["pontuadas"], alertas=m["contagens"].get("alertas", 0),
                  duracao_s=duracao, causa=m["erros"][-1]["causa"] if status == "erro" and m["erros"] else None)
        with self._trava:
            self._abrir_etapa(m, "manifesto")
            m["motivo"] = motivo
            m["concluida_em"] = agora_iso()
            m["duracao_s"] = duracao
            pontuadas = m["contagens"].get("pontuadas", 0)
            m["desempenho"].update(
                duracao_total_s=duracao, pico_memoria_processo_bytes=memoria_processo()["pico_bytes"],
                # pontuadas ÷ duração total (leitura, ordenação, tipologias, pontuação, índices e manifesto)
                vazao_total_transacoes_por_s=(pontuadas / duracao) if duracao > 0 and pontuadas else None)
            e = self._etapa(m, "manifesto")
            e.update(status="concluida", fim=agora_iso(), duracao_s=0.0)
            m["status"] = status
            self._gravar(m)

    def _pontuar(self, m: Dict[str, Any], df: pd.DataFrame, gravador: arm.Gravador) -> None:
        modelo = self.obter_modelo()
        cab, prep = modelo.cabeca("lavagem"), modelo.codificadores["financeiro"]
        limiar = float(cab.limiar_alerta)
        md = cab.metadados or {}
        m["modelo"] = {"versao": md.get("versao", ""), "familia": getattr(cab, "familia", None),
                       "limiar_alerta": limiar, "treinado_ate": md.get("treinado_ate") or md.get("treinado_ate_utc"),
                       "fonte": md.get("fonte"), "aviso": md.get("aviso")}
        m["conversao_score"] = sc.descricao_conversao(limiar)
        self._log_ml("modelo_carregado", "Modelo de lavagem carregado para a análise", analise=m["id"],
                     versao=m["modelo"]["versao"], familia=m["modelo"]["familia"], limiar_alerta=limiar,
                     treinado_ate=m["modelo"]["treinado_ate"], atributos=len(cab.colunas_entrada))
        # avisos de esquema e de atributos (nada é corrigido nem inventado)
        moedas = set(pd.unique(df["moeda_pagamento"]))
        formatos = set(pd.unique(df["formato"])) - {""}
        fora_m, fora_f = sorted(moedas - set(prep.moedas)), sorted(formatos - set(prep.formatos))
        sem_taxa = int((~df["moeda_pagamento"].isin(list(prep.cambio))).sum())
        sem_formato = int((df["formato"] == "").sum())
        for cond, evento, texto, ctx in (
            (fora_m, "moedas_fora_do_treino", "Moedas de pagamento que o modelo não viu no treino", {"valores": fora_m}),
            (fora_f, "formatos_fora_do_treino", "Formatos de pagamento que o modelo não viu no treino", {"valores": fora_f}),
            (sem_taxa, "sem_taxa_de_cambio", "Transações em moeda sem taxa de câmbio aprendida (valor em USD ausente)",
             {"transacoes": sem_taxa}),
            (sem_formato, "formato_nao_informado", "Transações sem formato de pagamento", {"transacoes": sem_formato}),
        ):
            if cond:
                self._log_ml(evento, texto, "aviso", analise=m["id"], **ctx)
                m["avisos"].append(texto + ": " + (", ".join(ctx["valores"][:10]) if "valores" in ctx
                                                  else str(ctx["transacoes"])) + ".")
        estado = EstadoFinanceiro(prep)
        n = len(df)
        minutos = df["minuto"].to_numpy()
        campos = ("banco_origem", "banco_destino", "no_origem", "no_destino", "valor_pago", "valor_recebido",
                  "moeda_pagamento", "moeda_recebimento", "formato")
        t = {"atr": 0.0, "inf": 0.0, "grav": 0.0}
        pico = memoria_processo()["bytes"] or 0
        alertas = incompleto = cursor = 0
        self._progresso(m, "pontuacao", 0, n)
        try:
            while cursor < n:
                if self._interromper(m["id"]):
                    raise Cancelado()
                fim = min(cursor + self.bloco, n)
                while fim < n and minutos[fim] == minutos[fim - 1]:  # o bloco termina na virada do minuto
                    fim += 1
                t0 = time.perf_counter()
                parte = df.iloc[cursor:fim]
                col = {c: parte[c].tolist() for c in campos}  # só o bloco vira objeto Python
                for i, pos in enumerate(range(cursor, fim)):
                    minuto = int(minutos[pos])
                    epoca = float(minuto * 60)
                    estado.receber({
                        "id_transacao": str(pos), "epoca": epoca, "minuto": minuto, "timestamp_disponivel": epoca,
                        "banco_origem": col["banco_origem"][i], "banco_destino": col["banco_destino"][i],
                        "conta_origem": col["no_origem"][i], "conta_destino": col["no_destino"][i],
                        "valor_pago": col["valor_pago"][i], "valor_recebido": col["valor_recebido"][i],
                        "moeda_pagamento": col["moeda_pagamento"][i], "moeda_recebimento": col["moeda_recebimento"][i],
                        "formato": col["formato"][i], "_pos": pos})
                fechados = estado.fechar_ate(None)
                t1 = time.perf_counter()
                txs = [tx for mf in fechados for tx in mf.transacoes]
                X = pd.concat([mf.X for mf in fechados], ignore_index=True)
                inc = np.concatenate([mf.historico_incompleto for mf in fechados])
                bruto, motivos = pontuar_lavagem(cab, prep, X, pd.Series([tx["formato"] for tx in txs]))
                t2 = time.perf_counter()
                pos = np.array([tx["_pos"] for tx in txs], dtype=np.int64)
                saida = df.iloc[pos].rename(columns={"linha": "linha_arquivo"}).copy()
                saida["score_bruto"] = bruto
                saida["score"] = sc.converter(bruto, limiar)
                saida["alerta"] = (bruto >= limiar).astype(np.int8)
                saida["motivos"] = motivos
                saida["historico_incompleto"] = inc.astype(np.int8)
                gravador.inserir(saida)
                t3 = time.perf_counter()
                t["atr"] += t1 - t0
                t["inf"] += t2 - t1
                t["grav"] += t3 - t2
                alertas += int(saida["alerta"].sum())
                incompleto += int(inc.sum())
                cursor = fim
                pico = max(pico, memoria_processo()["bytes"] or 0)
                with self._trava:
                    m["contagens"].update(pontuadas=gravador.gravadas, alertas=alertas)
                self._progresso(m, "pontuacao", gravador.gravadas, n, {"alertas_ate_agora": alertas})
        finally:  # também em cancelamento ou erro: registra o que foi medido até aqui
            self._fechar_pontuacao(m, gravador, t, alertas, incompleto, pico, limiar)

    def _fechar_pontuacao(self, m: Dict[str, Any], gravador: arm.Gravador, t: Dict[str, float], alertas: int,
                          incompleto: int, pico: int, limiar: float) -> None:
        total = t["atr"] + t["inf"] + t["grav"]
        m["desempenho"].update(
            transacoes_pontuadas=gravador.gravadas, tempo_atributos_s=round(t["atr"], 3),
            tempo_inferencia_s=round(t["inf"], 3), tempo_gravacao_s=round(t["grav"], 3),
            # pontuadas ÷ (atributos + inferência + gravação): só a etapa de pontuação
            vazao_transacoes_por_s=(gravador.gravadas / total) if total > 0 else None,
            pico_memoria_processo_na_pontuacao_bytes=pico or None, tamanho_do_bloco=self.bloco)
        self._etapa(m, "pontuacao")["detalhe"] = (
            f"atributos {t['atr']:.1f} s, inferência {t['inf']:.1f} s, gravação {t['grav']:.1f} s")
        if incompleto:
            texto = (f"{_n(incompleto)} transações foram pontuadas com menos de 72 h de histórico observado no próprio "
                     "dataset (início do período): os atributos de contagem ficam subestimados e o modelo tende a "
                     "gerar menos alertas nelas")
            m["avisos"].append(texto + ".")
            self._log_ml("historico_incompleto", texto, "aviso", analise=m["id"], transacoes=incompleto)
        self._log_ml("pontuacao_medida", "Transações pontuadas", analise=m["id"], versao=m["modelo"]["versao"],
                     transacoes=gravador.gravadas, alertas=alertas, tempo_inferencia_s=round(t["inf"], 3),
                     tempo_atributos_s=round(t["atr"], 3), limiar_alerta=limiar)
