"""Contrato de eventos (``evento_v1``): envelope, identidade e validação por tipo.

Todo evento que entra no processamento tem o mesmo envelope::

    {
      "tipo": "transacao" | "medicao_rede" | "vinculo",
      "versao_esquema": "transacao_hismall_v1" | "rede_v1" | "vinculo_v1",
      "id_evento": "opcional; se ausente, vem da chave natural",
      "origem": "quem produziu (ex.: produtor_exemplo, replay:arquivo.csv)",
      "modo": "novo_evento" | "replay_historico" | "simulacao",
      "dados": { ...campos do esquema do tipo... }
    }

O servidor acrescenta ``recebido_em`` (relógio do servidor, UTC) e uma
``sequencia`` de chegada. ``ocorrido_em`` vem dos dados: o instante da
transação, o ``timestamp`` da medição ou o ``declarado_em`` do vínculo.

Identidade estável (usada para descartar duplicatas):

* transação: ``tx:<id_transacao>``;
* medição de rede: ``rede:<id_fluxo>@<timestamp>`` (a chave de ``rede_v1``);
* vínculo: ``vinc:`` + hash de chave, tipo, fluxo e validade.

Medições de rede entram **com os atributos já preparados** (``rede_v1``). A
telemetria bruta (RTT em ms, jitter, perda por pacote) não é aceita: as razões
dependem de um p95/p99 de referência por fluxo cujo período não está
documentado, e inventar essa referência mudaria o significado dos atributos.
Se um extrator causal for criado, ele terá um esquema novo (``rede_v2``).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from src.ml.esquemas import ESQUEMA_REDE_V1, ESQUEMA_VINCULO_V1, ErroEsquema, FEATURES_REDE

VERSAO_ENVELOPE = "evento_v1"
ESQUEMA_POR_TIPO = {
    "transacao": "transacao_hismall_v1",
    "medicao_rede": "rede_v1",
    "vinculo": "vinculo_v1",
}
MODOS = ("novo_evento", "replay_historico", "simulacao")
ROTULO_MODO = {
    "novo_evento": "Novo evento (API de ingestão)",
    "replay_historico": "Replay histórico",
    "simulacao": "Simulação",
}
CAMPOS_TRANSACAO = (
    "id_transacao", "timestamp", "banco_origem", "conta_origem", "banco_destino", "conta_destino",
    "valor_pago", "moeda_pagamento", "valor_recebido", "moeda_recebimento", "formato",
)
CAMPOS_TRANSACAO_OPCIONAIS = ("timestamp_disponivel", "chave_tecnica")
# Indícios de telemetria bruta: sem a referência p95/p99 por fluxo, não viram rede_v1.
_TELEMETRIA_BRUTA = ("rtt_ms", "rtt", "jitter_ms", "jitter", "latencia_ms", "perda_pacotes")
_FLUXO = re.compile(r"^\d+_\d+$")
_CONTA = re.compile(r"^\d+-[0-9A-F]{8,}$")  # formato banco-conta do HI-Small


class ErroEvento(ValueError):
    def __init__(self, problemas: Sequence[str], id_evento: str = ""):
        self.problemas = list(problemas)
        self.id_evento = id_evento
        super().__init__("; ".join(self.problemas))


@dataclass
class Evento:
    id_evento: str
    chave_natural: str
    tipo: str
    versao_esquema: str
    ocorrido_em: float  # época, s (UTC)
    recebido_em: float
    origem: str
    modo: str
    dados: Dict[str, Any]
    sequencia: int = 0
    controle: Dict[str, Any] = field(default_factory=dict)

    def conteudo_hash(self) -> str:
        """Hash do conteúdo (tipo, versão e dados normalizados). Mesma identidade com
        hash diferente é conflito; com o mesmo hash, é retransmissão."""
        corpo = json.dumps({"tipo": self.tipo, "versao_esquema": self.versao_esquema, "dados": self.dados},
                           sort_keys=True, ensure_ascii=False, default=_nativo)
        return hashlib.sha256(corpo.encode("utf-8")).hexdigest()[:32]

    def para_registro(self) -> Dict[str, Any]:
        return {"tipo": self.tipo, "versao_esquema": self.versao_esquema, "id_evento": self.id_evento,
                "chave_natural": self.chave_natural, "hash": self.conteudo_hash(),
                "ocorrido_em": self.ocorrido_em, "recebido_em": self.recebido_em, "origem": self.origem,
                "modo": self.modo, "dados": self.dados, "controle": self.controle}

    @classmethod
    def de_registro(cls, r: Dict[str, Any]) -> "Evento":
        return cls(r["id_evento"], r["chave_natural"], r["tipo"], r["versao_esquema"], r["ocorrido_em"],
                   r["recebido_em"], r["origem"], r["modo"], r["dados"], sequencia=r["seq"],
                   controle=r.get("controle") or {})

    def resumo(self) -> Dict[str, Any]:
        return {"id_evento": self.id_evento, "tipo": self.tipo, "versao_esquema": self.versao_esquema,
                "ocorrido_em_utc": iso(self.ocorrido_em), "recebido_em_utc": iso(self.recebido_em),
                "origem": self.origem, "modo": self.modo}


def _nativo(v: Any) -> Any:
    item = getattr(v, "item", None)
    return item() if callable(item) else str(v)


def controle(acao: str, origem: str, modo: str, **dados: Any) -> Evento:
    """Comando de controle gravado no registro (fechar minutos, descartar eventos)."""
    return Evento(f"controle:{acao}", f"controle:{acao}", "controle", "-", 0.0, agora(), origem, modo,
                  {"acao": acao, **dados})


def iso(epoca: Optional[float]) -> Optional[str]:
    if epoca is None or (isinstance(epoca, float) and math.isnan(epoca)):
        return None
    return datetime.fromtimestamp(float(epoca), tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def agora() -> float:
    return datetime.now(timezone.utc).timestamp()


def epoca(valor: Any, campo: str) -> float:
    """Época (s, UTC) de número, ``AAAA/MM/DD HH:MM`` (HI-Small) ou ISO 8601.

    Texto sem fuso é tratado como UTC, como na leitura do HI-Small.
    """
    if isinstance(valor, bool) or valor is None:
        raise ErroEvento([f"{campo}: ausente ou inválido"])
    if isinstance(valor, (int, float, np.integer, np.floating)):
        v = float(valor)
        if not math.isfinite(v) or v < 0 or v > 4e9:
            raise ErroEvento([f"{campo}: época fora da faixa [0, 4e9]"])
        return v
    texto = str(valor).strip()
    for fmt in ("%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(texto, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    try:
        ts = pd.Timestamp(texto)
    except (ValueError, TypeError):
        raise ErroEvento([f"{campo}: data/hora não reconhecida ({texto!r})"]) from None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return float(ts.tz_convert("UTC").timestamp())


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def montar_evento(bruto: Any, recebido_em: float, origem_padrao: str = "api",
                  modo_padrao: str = "novo_evento", eh_conta: Optional[Callable[[str], bool]] = None) -> Evento:
    """Valida o envelope e os dados; devolve o evento normalizado ou levanta :class:`ErroEvento`."""
    if not isinstance(bruto, dict):
        raise ErroEvento(["o evento deve ser um objeto JSON"])
    problemas: List[str] = []
    tipo = bruto.get("tipo")
    if tipo not in ESQUEMA_POR_TIPO:
        raise ErroEvento([f"tipo inválido: {tipo!r} (use {sorted(ESQUEMA_POR_TIPO)})"], str(bruto.get("id_evento", "")))
    versao = bruto.get("versao_esquema", ESQUEMA_POR_TIPO[tipo])
    if versao != ESQUEMA_POR_TIPO[tipo]:
        problemas.append(f"versao_esquema {versao!r} não suportada para {tipo} (esperado "
                         f"{ESQUEMA_POR_TIPO[tipo]!r})")
    modo = bruto.get("modo", modo_padrao)
    if modo not in MODOS:
        problemas.append(f"modo inválido: {modo!r} (use {list(MODOS)})")
    origem = str(bruto.get("origem") or origem_padrao)[:120]
    dados = bruto.get("dados")
    if not isinstance(dados, dict):
        problemas.append("dados: deve ser um objeto JSON")
    if problemas:
        raise ErroEvento(problemas, str(bruto.get("id_evento", "")))
    if tipo == "transacao":
        norm = normalizar_transacao(dados)
        natural, ocorrido = f"tx:{norm['id_transacao']}", norm["epoca"]
    elif tipo == "medicao_rede":
        norm = normalizar_medicao_rede(dados)
        natural, ocorrido = f"rede:{norm['id_fluxo']}@{norm['timestamp']}", float(norm["timestamp"])
    else:
        norm = normalizar_vinculo(dados, recebido_em, eh_conta)
        natural, ocorrido = norm["id_vinculo"], norm["disponivel_em"]
    ident = str(bruto.get("id_evento") or natural)[:200]
    return Evento(ident, natural, tipo, versao, ocorrido, recebido_em, origem, modo, norm)


# ---------------------------------------------------------------------------
# transacao_hismall_v1 — entrada da cabeça "lavagem"
# ---------------------------------------------------------------------------
def normalizar_transacao(d: Dict[str, Any]) -> Dict[str, Any]:
    """Campos do HI-Small (nomes em português) → transação pronta para o estado.

    A conta é identificada por ``banco-conta``, como na leitura do HI-Small: o
    mesmo número de conta em bancos diferentes são contas diferentes.
    """
    problemas = [f"campo obrigatório ausente: {c}" for c in CAMPOS_TRANSACAO if d.get(c) in (None, "")]
    if problemas:
        raise ErroEvento(problemas, str(d.get("id_transacao", "")))
    ident = str(d["id_transacao"])[:120]
    try:
        t = epoca(d["timestamp"], "timestamp")
        disp = epoca(d["timestamp_disponivel"], "timestamp_disponivel") if d.get("timestamp_disponivel") not in (None, "") else t
    except ErroEvento as exc:
        raise ErroEvento(exc.problemas, ident) from None
    if disp < t:
        problemas.append("timestamp_disponivel anterior a timestamp")
    valores = {}
    for c in ("valor_pago", "valor_recebido"):
        try:
            v = float(d[c])
        except (TypeError, ValueError):
            problemas.append(f"{c}: não numérico")
            continue
        if not math.isfinite(v) or v < 0 or v > 1e15:
            problemas.append(f"{c}: fora da faixa [0, 1e15]")
        valores[c] = v
    bancos = {}
    for c in ("banco_origem", "banco_destino"):
        texto = str(d[c]).strip()
        if not texto.isdigit():
            problemas.append(f"{c}: esperado código numérico de banco")
        bancos[c] = str(int(texto)) if texto.isdigit() else texto
    if problemas:
        raise ErroEvento(problemas, ident)
    saida = {
        "id_transacao": ident,
        "epoca": t,
        "minuto": int(t // 60),
        "timestamp_disponivel": disp,
        "banco_origem": bancos["banco_origem"],
        "banco_destino": bancos["banco_destino"],
        "conta_origem": f"{bancos['banco_origem']}-{str(d['conta_origem']).strip()}",
        "conta_destino": f"{bancos['banco_destino']}-{str(d['conta_destino']).strip()}",
        "valor_pago": valores["valor_pago"],
        "valor_recebido": valores["valor_recebido"],
        "moeda_pagamento": str(d["moeda_pagamento"]).strip(),
        "moeda_recebimento": str(d["moeda_recebimento"]).strip(),
        "formato": str(d["formato"]).strip(),
    }
    if d.get("chave_tecnica") not in (None, ""):
        saida["chave_tecnica"] = str(d["chave_tecnica"])[:200]
    return saida


# ---------------------------------------------------------------------------
# rede_v1 — medições com atributos já preparados
# ---------------------------------------------------------------------------
def normalizar_medicao_rede(d: Dict[str, Any]) -> Dict[str, Any]:
    """Confere a presença das chaves; a validação completa é feita em lote por :func:`validar_lote_rede`."""
    brutos = [c for c in _TELEMETRIA_BRUTA if c in d]
    faltam = [c for c in ("id_fluxo", "anchor_id", "probe_id", "timestamp", *FEATURES_REDE) if c not in d]
    if faltam and brutos:
        raise ErroEvento([
            f"telemetria bruta ({', '.join(brutos)}) não é aceita: as razões de rede_v1 dependem "
            "de um p95/p99 de referência por fluxo que não está documentado. Envie a medição "
            f"com os {len(FEATURES_REDE)} atributos de rede_v1 já preparados."
        ], str(d.get("id_fluxo", "")))
    if faltam:
        raise ErroEvento([f"atributos de rede_v1 ausentes: {faltam[:8]}{' ...' if len(faltam) > 8 else ''}"],
                         str(d.get("id_fluxo", "")))
    reservadas = [c for c in ("arquivo_origem", "linha_origem", "alvo", "split") if c in d]
    if reservadas:
        raise ErroEvento([f"colunas não aceitas em eventos: {reservadas}"], str(d.get("id_fluxo", "")))
    saida = dict(d)
    try:
        saida["timestamp"] = int(float(d["timestamp"]))
    except (TypeError, ValueError):
        raise ErroEvento(["timestamp: esperado época em segundos"], str(d.get("id_fluxo", ""))) from None
    saida["id_fluxo"] = str(d["id_fluxo"])
    return saida


def validar_lote_rede(df: pd.DataFrame, exigir: Sequence[str] = ()) -> Tuple[pd.DataFrame, List[Tuple[int, List[str]]]]:
    """Valida ``rede_v1`` em lote; se o lote falhar, isola as linhas com problema.

    Returns:
        ``(df_validas, [(posição, problemas), ...])``.
    """
    try:
        ESQUEMA_REDE_V1.validar(df, modo="inferencia", exigir=exigir)
        return df, []
    except ErroEsquema:
        pass
    ruins: List[Tuple[int, List[str]]] = []
    boas = []
    for i in range(len(df)):
        try:
            ESQUEMA_REDE_V1.validar(df.iloc[[i]], modo="inferencia", exigir=exigir)
            boas.append(i)
        except ErroEsquema as exc:
            ruins.append((i, list(exc.problemas)))
    return df.iloc[boas], ruins


# ---------------------------------------------------------------------------
# vinculo_v1 — transação ou chave técnica → fluxo de rede
# ---------------------------------------------------------------------------
def normalizar_vinculo(d: Dict[str, Any], recebido_em: float,
                       eh_conta: Optional[Callable[[str], bool]] = None) -> Dict[str, Any]:
    """Valida um vínculo. ``disponivel_em`` = ``declarado_em`` (se houver) ou a chegada.

    Regras além do esquema ``vinculo_v1``:

    * o fluxo segue ``<probe_id>_<anchor_id>``;
    * ``valido_de < valido_ate``;
    * a chave técnica é sessão, dispositivo ou nó. Uma conta bancária
      (``banco-conta``) não é chave técnica nem âncora/sonda de rede.
    """
    df = pd.DataFrame([{k: d.get(k) for k in ESQUEMA_VINCULO_V1.nomes()}])
    try:
        ESQUEMA_VINCULO_V1.validar(df)
    except ErroEsquema as exc:
        raise ErroEvento(exc.problemas, str(d.get("chave", ""))) from None
    problemas: List[str] = []
    chave, tipo, fluxo = str(d["chave"]), str(d["tipo_chave"]), str(d["id_fluxo"])
    if not _FLUXO.match(fluxo):
        problemas.append(f"id_fluxo {fluxo!r} fora do formato '<probe_id>_<anchor_id>'")
    try:
        de, ate = epoca(d["valido_de"], "valido_de"), epoca(d["valido_ate"], "valido_ate")
        declarado = epoca(d["declarado_em"], "declarado_em") if d.get("declarado_em") not in (None, "") else recebido_em
    except ErroEvento as exc:
        raise ErroEvento(exc.problemas, chave) from None
    if de >= ate:
        problemas.append("valido_de deve ser anterior a valido_ate")
    if tipo == "chave_tecnica" and (_CONTA.match(chave) or (eh_conta is not None and eh_conta(chave))):
        problemas.append("a chave técnica parece uma conta bancária (banco-conta); vínculos ligam "
                         "transação, sessão, dispositivo ou nó a um fluxo, não contas a sondas/âncoras")
    if not str(d.get("fonte_vinculo", "")).strip():
        problemas.append("fonte_vinculo vazia: informe a origem documentada do vínculo")
    if problemas:
        raise ErroEvento(problemas, chave)
    h = hashlib.sha1(f"{chave}|{tipo}|{fluxo}|{de}|{ate}".encode()).hexdigest()[:16]
    return {"id_vinculo": f"vinc:{h}", "chave": chave, "tipo_chave": tipo, "id_fluxo": fluxo,
            "valido_de": de, "valido_ate": ate, "fonte_vinculo": str(d["fonte_vinculo"])[:200],
            "disponivel_em": declarado}


def descricao_contratos() -> Dict[str, Any]:
    """Resumo dos contratos aceitos (para a API e a interface)."""
    return {
        "envelope": VERSAO_ENVELOPE,
        "tipos": ESQUEMA_POR_TIPO,
        "modos": {m: ROTULO_MODO[m] for m in MODOS},
        "transacao_hismall_v1": {"obrigatorios": list(CAMPOS_TRANSACAO),
                                 "opcionais": list(CAMPOS_TRANSACAO_OPCIONAIS)},
        "rede_v1": {"obrigatorios": ["id_fluxo", "anchor_id", "probe_id", "timestamp", *FEATURES_REDE],
                    "opcionais": ["classe_atual"],
                    "nao_aceito": "telemetria bruta (sem referência p95/p99 documentada)"},
        "vinculo_v1": {"obrigatorios": ESQUEMA_VINCULO_V1.nomes(), "opcionais": ["declarado_em"]},
    }
