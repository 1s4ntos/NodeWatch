"""Gera docs/ml/COMO_FUNCIONA_O_NODEWATCH.pdf a partir da fonte HTML.

Uso (da raiz do projeto)::

    python docs/ml/gerar_pdf_como_funciona.py
    python docs/ml/gerar_pdf_como_funciona.py --png pasta_paginas   # também salva cada página em PNG

Requisitos: Google Chrome ou Microsoft Edge (impressão em modo headless) e
``pymupdf`` (``pip install pymupdf``), usado para ler o PDF gerado.

Passos:

1. imprime o HTML em PDF com o navegador (A4; margens, cabeçalho e números de
   página vêm do CSS ``@page``);
2. localiza a página de cada título (h1/h2) pelo tamanho da fonte e grava os
   números no sumário da própria fonte HTML;
3. imprime de novo e repete até os números ficarem estáveis;
4. grava os marcadores do PDF (índice lateral do leitor) com os mesmos títulos;
5. confere se há texto fora das margens ou páginas vazias.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

PASTA = Path(__file__).resolve().parent
FONTE = PASTA / "COMO_FUNCIONA_O_NODEWATCH.html"
DESTINO = PASTA / "COMO_FUNCIONA_O_NODEWATCH.pdf"
MARGEM_LATERAL_PT = 18 / 25.4 * 72  # 18 mm, igual ao @page
TAMANHO_MIN_TITULO = 12.0           # h2 = 12,5 pt; entradas do sumário < 11 pt

_CANDIDATOS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def achar_navegador(indicado: Optional[str]) -> str:
    if indicado:
        return indicado
    for nome in ("chrome", "google-chrome", "chromium", "msedge"):
        caminho = shutil.which(nome)
        if caminho:
            return caminho
    for caminho in _CANDIDATOS:
        if os.path.isfile(caminho):
            return caminho
    raise SystemExit("Chrome ou Edge não encontrado; informe o executável com --navegador.")


def imprimir(navegador: str, fonte: Path, destino: Path) -> None:
    with tempfile.TemporaryDirectory() as perfil:
        cmd = [
            navegador, "--headless=new", "--disable-gpu", "--no-first-run",
            f"--user-data-dir={perfil}", "--no-pdf-header-footer",
            f"--print-to-pdf={destino}",
            fonte.resolve().as_uri(),
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    if not destino.is_file() or destino.stat().st_size == 0:
        raise SystemExit("O navegador não gerou o PDF.")


def titulos_da_fonte(texto: str) -> Dict[str, str]:
    """``{id: texto do título}`` para os h1/h2 com id ``s…``."""
    saida: Dict[str, str] = {}
    for _, ident, conteudo in re.findall(r'<h([12]) id="(s[\d-]+)">(.*?)</h\1>', texto, flags=re.S):
        limpo = html.unescape(re.sub(r"<[^>]+>", "", conteudo))
        saida[ident] = " ".join(limpo.split())
    return saida


def paginas_dos_titulos(pdf: Path, titulos: Dict[str, str]) -> Dict[str, int]:
    import pymupdf

    procurados = {texto: ident for ident, texto in titulos.items()}
    achados: Dict[str, int] = {}
    with pymupdf.open(pdf) as doc:
        for indice, pagina in enumerate(doc):
            for bloco in pagina.get_text("dict")["blocks"]:
                for linha in bloco.get("lines", []):
                    spans = linha["spans"]
                    if not spans or max(s["size"] for s in spans) < TAMANHO_MIN_TITULO:
                        continue
                    texto = " ".join("".join(s["text"] for s in spans).replace("\xa0", " ").split())
                    ident = procurados.get(texto)
                    if ident and ident not in achados:
                        achados[ident] = indice + 1  # a capa é a página 1
    faltando = sorted(set(titulos) - set(achados))
    if faltando:
        raise SystemExit(f"Títulos não encontrados no PDF: {faltando}")
    return achados


def gravar_sumario(texto: str, paginas: Dict[str, int]) -> str:
    return re.sub(r'(<span class="pg" data-ref="(s[\d-]+)">)[^<]*(</span>)',
                  lambda m: f"{m.group(1)}{paginas[m.group(2)]}{m.group(3)}", texto)


def gravar_marcadores(pdf: Path, titulos: Dict[str, str], paginas: Dict[str, int]) -> None:
    """Marcadores do PDF: h1 no nível 1 e h2 no nível 2, na ordem do documento.

    O esboço gerado pelo próprio navegador repetia o texto de alguns títulos.
    """
    import pymupdf

    marcadores = [[1, "Sumário", 2]]  # o sumário vem logo depois da capa
    for ident, texto in titulos.items():
        marcadores.append([1 if "-" not in ident else 2, texto, paginas[ident]])
    with pymupdf.open(pdf) as doc:
        doc.set_toc(marcadores)
        doc.saveIncr()


def conferir(pdf: Path) -> List[str]:
    import pymupdf

    problemas: List[str] = []
    with pymupdf.open(pdf) as doc:
        for indice, pagina in enumerate(doc, start=1):
            largura = pagina.rect.width
            palavras = pagina.get_text("words")
            if not palavras and not pagina.get_drawings():
                problemas.append(f"página {indice}: vazia")
            for x0, _, x1, _, palavra, *_ in palavras:
                if x1 > largura - MARGEM_LATERAL_PT + 2 or x0 < MARGEM_LATERAL_PT - 2:
                    problemas.append(f"página {indice}: texto fora da margem ({palavra!r})")
                    break
    return problemas


def salvar_png(pdf: Path, pasta: Path, dpi: int) -> None:
    import pymupdf

    pasta.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf) as doc:
        for indice, pagina in enumerate(doc, start=1):
            pagina.get_pixmap(dpi=dpi).save(pasta / f"pagina_{indice:02d}.png")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--navegador", help="executável do Chrome ou do Edge")
    p.add_argument("--png", type=Path, help="pasta para salvar cada página em PNG")
    p.add_argument("--dpi", type=int, default=110)
    args = p.parse_args(argv)

    navegador = achar_navegador(args.navegador)
    texto = FONTE.read_text(encoding="utf-8")
    titulos = titulos_da_fonte(texto)
    anteriores: Dict[str, int] = {}
    for rodada in range(1, 5):
        imprimir(navegador, FONTE, DESTINO)
        paginas = paginas_dos_titulos(DESTINO, titulos)
        if paginas == anteriores:
            break
        texto = gravar_sumario(texto, paginas)
        FONTE.write_text(texto, encoding="utf-8")
        anteriores = paginas
    else:
        raise SystemExit("Os números do sumário não estabilizaram.")
    gravar_marcadores(DESTINO, titulos, paginas)

    import pymupdf

    with pymupdf.open(DESTINO) as doc:
        total = doc.page_count
    print(f"{DESTINO.name}: {total} páginas (sumário estável na rodada {rodada})")
    problemas = conferir(DESTINO)
    for problema in problemas:
        print("ATENÇÃO:", problema)
    if args.png:
        salvar_png(DESTINO, args.png, args.dpi)
        print(f"PNGs em {args.png}")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
