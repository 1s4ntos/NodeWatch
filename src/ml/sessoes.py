"""Sessões de uso da interface: quem autoriza processamento novo.

Abrir a interface cria uma sessão (uma por aba). A aba renova a sessão com um
**pulso** periódico; sem pulso por ``ttl_s`` segundos, a sessão expira. Uma
análise, um replay ou o processamento de eventos só avançam enquanto a sessão
**responsável** por eles estiver ativa; depois disso, param no próximo ponto
seguro e só continuam por ação explícita de uma sessão ativa.

Prazos (padrões, ver docs/ml/ANALISE_DATASETS.md):

* pulso a cada 15 s com a aba visível. Com a aba em segundo plano, os
  navegadores espaçam os temporizadores (o Chrome chega a 1 por minuto
  depois de alguns minutos oculta), e a aba manda um pulso ao voltar a ficar
  visível;
* ``ttl_s = 150``: uma aba fechada, um navegador que caiu ou uma conexão
  perdida são detectados em até 150 s. Somado ao ponto seguro da operação
  longa (um bloco de linhas ou a virada de um minuto), a interrupção ocorre
  em até cerca de 3 min. A detecção não é instantânea: não há aviso confiável
  de fechamento de janela;
* minimizar ou trocar de aba não encerra a sessão;
* encerrar explicitamente (botão) vale na hora.

Várias abas: cada uma tem a sua sessão. Uma aba vê os trabalhos das outras e
pode pausá-los ou cancelá-los; retomar um trabalho transfere a
responsabilidade para a sessão de quem retomou.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from src.ml.eventos import agora, iso

TTL_S = 150.0
PULSO_S = 15.0


@dataclass
class Sessao:
    id: str
    criada_em: float
    ultimo_pulso: float
    rotulo: str = ""
    encerrada_em: Optional[float] = None
    motivo_fim: str = ""
    pulsos: int = 0

    def resumo(self, ttl: float, relogio: Callable[[], float]) -> Dict[str, object]:
        ativa = self.encerrada_em is None and relogio() - self.ultimo_pulso <= ttl
        return {"id": self.id, "rotulo": self.rotulo, "ativa": ativa, "criada_em_utc": iso(self.criada_em),
                "ultimo_pulso_utc": iso(self.ultimo_pulso),
                "expira_em_utc": iso(self.ultimo_pulso + ttl) if ativa else None,
                "encerrada": self.encerrada_em is not None,
                "motivo_fim": self.motivo_fim or (None if ativa else "sem pulso dentro do prazo (expirada)")}


@dataclass
class GerenciadorSessoes:
    ttl_s: float = TTL_S
    pulso_s: float = PULSO_S
    relogio: Callable[[], float] = agora
    _sessoes: Dict[str, Sessao] = field(default_factory=dict)
    _trava: threading.Lock = field(default_factory=threading.Lock)

    def abrir(self, rotulo: str = "") -> Sessao:
        t = self.relogio()
        s = Sessao(secrets.token_urlsafe(16), t, t, rotulo[:80])
        with self._trava:
            self._sessoes[s.id] = s
            if len(self._sessoes) > 500:  # limpa sessões antigas já inativas
                for sid in [k for k, v in self._sessoes.items() if not self.ativa(k)][:250]:
                    del self._sessoes[sid]
        return s

    def obter(self, sid: Optional[str]) -> Optional[Sessao]:
        return self._sessoes.get(sid or "")

    def ativa(self, sid: Optional[str]) -> bool:
        s = self.obter(sid)
        return bool(s and s.encerrada_em is None and self.relogio() - s.ultimo_pulso <= self.ttl_s)

    def pulso(self, sid: str) -> bool:
        """Renova a sessão. Sessão expirada ou encerrada não volta: a aba abre outra."""
        s = self.obter(sid)
        if not s or not self.ativa(sid):
            return False
        s.ultimo_pulso = self.relogio()
        s.pulsos += 1
        return True

    def encerrar(self, sid: str, motivo: str = "encerrada pela interface") -> bool:
        s = self.obter(sid)
        if not s or s.encerrada_em is not None:
            return False
        s.encerrada_em = self.relogio()
        s.motivo_fim = motivo
        return True

    def resumo(self, sid: Optional[str]) -> Optional[Dict[str, object]]:
        s = self.obter(sid)
        return s.resumo(self.ttl_s, self.relogio) if s else None

    def ativas(self) -> List[str]:
        return [k for k in list(self._sessoes) if self.ativa(k)]

    def politica(self) -> Dict[str, object]:
        return {"ttl_s": self.ttl_s, "pulso_s": self.pulso_s,
                "deteccao_max_s": self.ttl_s,
                "leitura": (f"Sem pulso por {int(self.ttl_s)} s (aba fechada, navegador caído ou conexão "
                            "perdida), a sessão expira e o trabalho dela para no próximo ponto seguro. "
                            "Minimizar ou trocar de aba não encerra a sessão.")}
