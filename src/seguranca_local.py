"""Acesso local ao servidor do NodeWatch: quem pode chamar as rotas ``/api``.

O NodeWatch é uma aplicação local: a página e a API saem do mesmo servidor
(``http://127.0.0.1:5000`` por padrão). Antes, ``CORS(app)`` respondia a
qualquer origem com ``Access-Control-Allow-Origin: *``; com isso, uma página
externa aberta no mesmo navegador podia ler respostas da API e, com pedidos
"simples" (formulário ou upload), até iniciar processamento.

Regras aplicadas a todo pedido (``verificar``):

1. **Host local.** O cabeçalho ``Host`` precisa apontar para este computador
   (``127.0.0.1``, ``localhost``, ``::1`` ou o host configurado). Isso barra
   ataques de *DNS rebinding*, em que um domínio externo passa a resolver
   para 127.0.0.1.
2. **Mesma origem em ``/api``.** Se o navegador informar ``Origin``, ela tem
   de ser a do próprio servidor (mesmo esquema, host e porta do pedido) ou
   uma origem liberada explicitamente em ``NODEWATCH_ORIGENS``. Pedido de
   outra origem recebe 403 antes de qualquer rota rodar, inclusive a
   pré-verificação ``OPTIONS``.
3. **Sem escrita entre sites.** Em ``POST``/``PUT``/``PATCH``/``DELETE`` de
   ``/api``, ``Sec-Fetch-Site`` (enviado pelos navegadores atuais) precisa ser
   ``same-origin`` ou ``none``; ``cross-site`` e ``same-site`` são recusados
   mesmo quando ``Origin`` vem como ``null``.

Pedidos sem ``Origin`` (curl, scripts locais como
``scripts/produtor_eventos_exemplo.py``, testes) continuam aceitos: um site
não consegue forjar a ausência desse cabeçalho num pedido entre origens que
altere dados.

Cabeçalhos CORS só são emitidos para as origens de ``NODEWATCH_ORIGENS``
(lista separada por vírgulas; vazia por padrão). Nunca se usa ``*``.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

HOSTS_LOCAIS = ("127.0.0.1", "localhost", "::1", "[::1]")
METODOS_DE_ESCRITA = ("POST", "PUT", "PATCH", "DELETE")
ORIGENS_PROIBIDAS = ("*",)


def origens_extras(texto: Optional[str]) -> List[str]:
    """Origens liberadas por configuração; ``*`` é ignorado de propósito."""
    itens = [o.strip().rstrip("/") for o in (texto or "").split(",")]
    return [o for o in itens if o and o not in ORIGENS_PROIBIDAS]


def _nome_do_host(host: str) -> str:
    host = (host or "").strip().lower()
    if host.startswith("["):  # IPv6 literal: [::1]:5000
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0] if ":" in host else host


def host_local(host: str, host_configurado: str = "127.0.0.1") -> bool:
    nome = _nome_do_host(host)
    return nome in HOSTS_LOCAIS or nome == (host_configurado or "").lower()


def mesma_origem(origem: str, esquema: str, host: str) -> bool:
    try:
        o = urlsplit(origem)
    except ValueError:
        return False
    return bool(o.scheme and o.netloc) and o.scheme.lower() == esquema.lower() and o.netloc.lower() == host.lower()


def verificar(metodo: str, caminho: str, esquema: str, host: str, origem: Optional[str],
              sec_fetch_site: Optional[str], extras: Iterable[str] = (),
              host_configurado: str = "127.0.0.1") -> Optional[Tuple[int, str, str]]:
    """``None`` se o pedido pode seguir; senão ``(status, erro, ação)``."""
    if not host_local(host, host_configurado):
        return (403, "Pedido recusado: o endereço do servidor não é local.",
                "Abra o NodeWatch pelo endereço local (http://127.0.0.1:5000).")
    if not caminho.startswith("/api/"):
        return None
    if origem and not mesma_origem(origem, esquema, host) and origem.rstrip("/") not in set(extras):
        return (403, "Pedido recusado: veio de outra origem.",
                "A API do NodeWatch só atende a própria página. Para liberar outra origem de propósito, "
                "use a variável NODEWATCH_ORIGENS.")
    if metodo.upper() in METODOS_DE_ESCRITA and (sec_fetch_site or "").lower() in ("cross-site", "same-site"):
        if not (origem and origem.rstrip("/") in set(extras)):
            return (403, "Pedido recusado: escrita vinda de outro site.",
                    "Use a própria página do NodeWatch para enviar arquivos e iniciar análises.")
    return None
