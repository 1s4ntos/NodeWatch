"""Gera docs/COMO_FUNCIONA_O_NODEWATCH.pdf a partir do Markdown (fonte principal).

Uso (da raiz do projeto)::

    python docs/gerar_pdf_como_funciona.py
    python docs/gerar_pdf_como_funciona.py --png pasta_paginas   # também salva cada página em PNG

Requisitos: Chrome ou Edge (impressão headless) e ``pip install markdown pymupdf``.
Nenhum dos dois faz parte das dependências de execução do NodeWatch.

Passos: converte o Markdown em HTML (figuras SVG embutidas), imprime em A4,
localiza a página de cada título, preenche o sumário, imprime de novo até os
números estabilizarem, grava os marcadores e confere margens e páginas vazias.
"""

from __future__ import annotations

import argparse
import html as html_mod
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PASTA = Path(__file__).resolve().parent
FONTE = PASTA / "COMO_FUNCIONA_O_NODEWATCH.md"
DESTINO = PASTA / "COMO_FUNCIONA_O_NODEWATCH.pdf"
MARGEM_PT = 18 / 25.4 * 72
CANDIDATOS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]
CSS = """
@page { size: A4; margin: 20mm 18mm 18mm 18mm;
  @top-right { content: "Como funciona o NodeWatch"; font: 8pt "Segoe UI", Arial, sans-serif; color: #7a8290; }
  @bottom-center { content: counter(page); font: 9pt "Segoe UI", Arial, sans-serif; color: #4a5260; } }
@page :first { @top-right { content: none; } @bottom-center { content: none; } }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Segoe UI", Arial, Helvetica, sans-serif; font-size: 10.2pt; line-height: 1.45; color: #1c2330; margin: 0; }
h1, h2, h3, h4 { font-weight: 600; color: #14213a; line-height: 1.25; break-after: avoid; }
h1 { font-size: 17pt; margin: 22pt 0 10pt; padding-bottom: 4pt; border-bottom: 2px solid #2c5d9e; break-before: page; }
h1[id^="s-18-"] { break-before: auto; }
h1.parte { font-size: 22pt; color: #2c5d9e; border: none; margin-top: 60mm; }
h2 { font-size: 12.5pt; margin: 16pt 0 6pt; }
h3 { font-size: 10.8pt; margin: 12pt 0 4pt; }
p { margin: 0 0 7pt; orphans: 3; widows: 3; }
ul, ol { margin: 0 0 7pt; padding-left: 18pt; }
li { margin-bottom: 2.5pt; }
code { font-family: Consolas, "Cascadia Mono", "Courier New", monospace; font-size: 0.9em; background: #f3f4f6; padding: 0 2px; border-radius: 2px; overflow-wrap: anywhere; }
pre { font-family: Consolas, "Cascadia Mono", "Courier New", monospace; font-size: 8.3pt; line-height: 1.35; background: #f3f4f6;
  border: 1px solid #e1e4e8; border-radius: 3px; padding: 6pt 8pt; margin: 0 0 8pt; white-space: pre-wrap; word-break: break-word; break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 1em; }
table { width: 100%; border-collapse: collapse; margin: 4pt 0 9pt; font-size: 8.7pt; line-height: 1.32; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th, td { border: 1px solid #c9d1dc; padding: 3pt 4.5pt; text-align: left; vertical-align: top; overflow-wrap: break-word; }
td:first-child code { overflow-wrap: normal; }
th { background: #e9eef5; font-weight: 600; overflow-wrap: normal; }
img { width: 100%; height: auto; display: block; margin: 6pt 0 3pt; break-inside: avoid; }
blockquote { border-left: 3px solid #2c5d9e; background: #edf3fb; padding: 5pt 8pt; margin: 6pt 0 9pt; break-inside: avoid; font-size: 9.6pt; }
blockquote p:last-child { margin-bottom: 0; }
em.legenda, p.legenda { font-size: 8.6pt; color: #4a5260; }
.capa { height: 222mm; display: flex; flex-direction: column; justify-content: space-between; border-top: 6px solid #2c5d9e; padding-top: 26mm; }
.capa .rotulo { font-size: 10pt; letter-spacing: .08em; text-transform: uppercase; color: #2c5d9e; font-weight: 600; }
.capa .titulo { font-size: 30pt; font-weight: 600; color: #14213a; margin: 6pt 0 8pt; }
.capa .sub { font-size: 13.5pt; color: #4a5260; max-width: 150mm; }
.capa .ficha { font-size: 9.6pt; border-top: 1px solid #c9d1dc; padding-top: 8pt; }
.capa .ficha p { margin: 0 0 2pt; }
.sumario { break-before: page; break-after: page; }
.sumario .tit { font-size: 17pt; font-weight: 600; color: #14213a; border-bottom: 2px solid #2c5d9e; padding-bottom: 4pt; margin-bottom: 8pt; }
.sumario a { color: inherit; text-decoration: none; display: flex; align-items: baseline; }
.sumario a .pt { flex: 1; border-bottom: 1px dotted #a9b1bc; margin: 0 4pt; }
.sumario .n1 { font-weight: 600; margin-top: 5pt; font-size: 10pt; }
.sumario .n2 { padding-left: 12pt; font-size: 9.2pt; }
.sumario .n0 { font-weight: 700; color: #2c5d9e; margin-top: 10pt; font-size: 10.5pt; }
"""


def achar_navegador(indicado: Optional[str]) -> str:
    if indicado:
        return indicado
    for nome in ("chrome", "google-chrome", "chromium", "msedge"):
        caminho = shutil.which(nome)
        if caminho:
            return caminho
    for caminho in CANDIDATOS:
        if os.path.isfile(caminho):
            return caminho
    raise SystemExit("Chrome ou Edge não encontrado; informe o executável com --navegador.")


def imprimir(navegador: str, fonte: Path, destino: Path) -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as perfil:
        subprocess.run([navegador, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={perfil}",
                        "--no-pdf-header-footer", f"--print-to-pdf={destino}", fonte.resolve().as_uri()],
                       check=True, capture_output=True, timeout=240)
    if not destino.is_file() or destino.stat().st_size == 0:
        raise SystemExit("O navegador não gerou o PDF.")


def _limpo(trecho: str) -> str:
    return " ".join(html_mod.unescape(re.sub(r"<[^>]+>", "", trecho)).split())


def para_html(texto: str) -> Tuple[str, List[Tuple[int, str, str]]]:
    import markdown

    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "toc"], extension_configs={
        "toc": {"slugify": lambda v, s: "s-" + re.sub(r"[^a-z0-9]+", "-", v.lower()).strip("-")}})
    corpo = md.convert(texto)

    def embutir(m: re.Match) -> str:  # figuras SVG embutidas, com o título como legenda
        svg = (PASTA / m.group(2)).read_text(encoding="utf-8")
        return f'<div style="break-inside:avoid;margin:6pt 0 10pt">{svg}<p class="legenda">{m.group(1)}</p></div>'

    corpo = re.sub(r'<p><img alt="([^"]*)" src="([^"]+\.svg)"\s*/?></p>', embutir, corpo)
    corpo = re.sub(r"<svg ", '<svg style="width:100%;height:auto;display:block" ', corpo)
    corpo = re.sub(r'<h1 id="(s-parte-[^"]*)">', r'<h1 class="parte" id="\1">', corpo)
    titulos = [(int(n), ident, _limpo(t)) for n, ident, t in
               re.findall(r'<h([12])[^>]* id="([^"]+)"[^>]*>(.*?)</h\1>', corpo, flags=re.S)]
    return corpo, titulos


def montar(corpo: str, titulos, paginas: Dict[str, int], capa: str) -> str:
    linhas = []
    for nivel, ident, titulo in titulos:
        classe = "n0" if ident.startswith("s-parte-") else f"n{nivel}"
        linhas.append(f'<div class="{classe}"><a href="#{ident}"><span>{html_mod.escape(titulo)}</span>'
                      f'<span class="pt"></span><span>{paginas.get(ident, "")}</span></a></div>')
    sumario = f'<div class="sumario"><div class="tit">Sumário</div>{"".join(linhas)}</div>'
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Como funciona o NodeWatch</title>'
            f"<style>{CSS}</style></head><body>{capa}{sumario}{corpo}</body></html>")


def paginas_dos_titulos(pdf: Path, titulos) -> Dict[str, int]:
    import pymupdf

    sem_espaco = lambda t: re.sub(r"\s+", "", t)  # noqa: E731
    pendentes = list(titulos)
    achados: Dict[str, int] = {}
    with pymupdf.open(pdf) as doc:
        inicio = 2  # capa e sumário: o corpo começa depois do sumário
        for i in range(1, doc.page_count):
            if pendentes and any(sem_espaco(pendentes[0][2]) in sem_espaco(" ".join(s["text"] for s in l["spans"]))
                                 and max(s["size"] for s in l["spans"]) >= 12
                                 for b in doc[i].get_text("dict")["blocks"] for l in b.get("lines", [])):
                inicio = i
                break
        for i in range(inicio, doc.page_count):
            linhas = [" ".join(s["text"] for s in l["spans"]) for b in doc[i].get_text("dict")["blocks"]
                      for l in b.get("lines", []) if l["spans"] and max(s["size"] for s in l["spans"]) >= 12]
            bloco = sem_espaco(" ".join(linhas))
            while pendentes and sem_espaco(pendentes[0][2]) in bloco:
                achados[pendentes.pop(0)[1]] = i + 1
    if pendentes:
        raise SystemExit(f"Títulos não encontrados no PDF: {[p[2] for p in pendentes][:5]}")
    return achados


def conferir(pdf: Path) -> List[str]:
    import pymupdf

    problemas: List[str] = []
    with pymupdf.open(pdf) as doc:
        for n, pagina in enumerate(doc, start=1):
            palavras = pagina.get_text("words")
            if len(palavras) < 3 and not pagina.get_drawings():
                problemas.append(f"página {n}: vazia")
            for x0, _, x1, _, palavra, *_ in palavras:
                if x1 > pagina.rect.width - MARGEM_PT + 2 or x0 < MARGEM_PT - 2:
                    problemas.append(f"página {n}: texto fora da margem ({palavra!r})")
                    break
    return problemas


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--navegador")
    p.add_argument("--png", type=Path)
    p.add_argument("--dpi", type=int, default=80)
    a = p.parse_args(argv)
    import pymupdf

    texto = FONTE.read_text(encoding="utf-8")
    # A capa vem do bloco de metadados no início do Markdown (entre <!--capa e -->).
    m = re.search(r"<!--capa\n(.*?)-->", texto, flags=re.S)
    campos = dict(l.split(": ", 1) for l in m.group(1).strip().splitlines())
    capa = (f'<div class="capa"><div><div class="rotulo">{campos["rotulo"]}</div><div class="titulo">{campos["titulo"]}</div>'
            f'<div class="sub">{campos["sub"]}</div></div><div class="ficha">'
            + "".join(f"<p><strong>{k}:</strong> {v}</p>" for k, v in campos.items() if k not in ("rotulo", "titulo", "sub"))
            + "</div></div>")
    # o título do documento no Markdown não se repete: a capa já o traz
    corpo_md = re.sub(r"^# Como funciona o NodeWatch\n", "", texto[m.end():], count=1, flags=re.M)
    corpo, titulos = para_html(corpo_md)
    navegador = achar_navegador(a.navegador)
    paginas: Dict[str, int] = {}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        htmlp = Path(tmp) / "manual.html"
        pdf = Path(tmp) / "manual.pdf"
        for rodada in range(1, 6):
            htmlp.write_text(montar(corpo, titulos, paginas, capa), encoding="utf-8")
            imprimir(navegador, htmlp, pdf)
            novas = paginas_dos_titulos(pdf, titulos)
            if novas == paginas:
                break
            paginas = novas
        else:
            raise SystemExit("Os números do sumário não estabilizaram.")
        marcadores = [[1, "Sumário", 2]] + [[n, t, paginas[i]] for n, i, t in titulos]
        with pymupdf.open(pdf) as doc:
            doc.set_toc(marcadores)
            doc.save(DESTINO, garbage=3, deflate=True)
    with pymupdf.open(DESTINO) as doc:
        print(f"{DESTINO.name}: {doc.page_count} páginas (sumário estável na rodada {rodada})")
        if a.png:
            a.png.mkdir(parents=True, exist_ok=True)
            for n, pg in enumerate(doc, start=1):
                pg.get_pixmap(dpi=a.dpi).save(a.png / f"pagina_{n:02d}.png")
    problemas = conferir(DESTINO)
    for x in problemas:
        print("ATENÇÃO:", x)
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
