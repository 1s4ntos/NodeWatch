"""Prepara as imagens do site de apresentação (pasta `site/`).

Uso, na raiz do repositório (precisa de Pillow: `pip install pillow`):
    python scripts/site/preparar_imagens.py

Entradas (os originais nunca são alterados):
    interface/NodeWatchlogo_transparente.png   logo oficial (IMG-08)
    docs/ui/capturas/depois_desktop_*.jpg      capturas reais do painel do analista

Saídas em `site/assets/img/`:
    logo.png, favicon.ico, apple-touch-icon.png    derivados do logo
    tela-*.jpg              recortes 16:10 das capturas, largura <= 1280, <= 150 KB
    IMG-07-capa-video.jpg   capa do vídeo: a captura do grafo com o logo por cima.
    og-image.jpg            1200x630, feita do mesmo jeito que a capa.

Rode de novo sempre que trocar uma captura.
"""

from __future__ import annotations

import io
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

RAIZ = Path(__file__).resolve().parents[2]
LOGO = RAIZ / "interface" / "NodeWatchlogo_transparente.png"
CAPTURAS_ORIGINAIS = RAIZ / "docs" / "ui" / "capturas"
SAIDA = RAIZ / "site" / "assets" / "img"

# (original, recorte (esq, topo, dir, base) ou None, arquivo no site). Recortes em 16:10.
CAPTURAS = [
    ("depois_desktop_topo.jpg", None, "tela-dataset.jpg"),
    ("depois_desktop_visao.jpg", (0, 0, 1100, 688), "tela-visao.jpg"),
    ("depois_desktop_grafo.jpg", (0, 0, 1100, 688), "tela-contas.jpg"),
    ("depois_desktop_sequencia.jpg", (0, 56, 982, 670), "tela-grafo.jpg"),
]
CAPTURA_DA_CAPA = "tela-grafo.jpg"
LIMITE_BYTES = 150 * 1024
LARGURA_MAX = 1280
FUNDO = (15, 19, 27)


def salvar_jpg(img: Image.Image, destino: Path, limite: int = LIMITE_BYTES) -> None:
    """Salva em JPG progressivo, baixando a qualidade até caber no limite."""
    img = img.convert("RGB")
    dados = b""
    for qualidade in range(86, 44, -4):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=qualidade, optimize=True, progressive=True)
        dados = buf.getvalue()
        if len(dados) <= limite:
            break
    destino.write_bytes(dados)
    aviso = "" if len(dados) <= limite else "  (ACIMA DO LIMITE)"
    print(f"  {destino.name}: {img.size[0]}x{img.size[1]}, {len(dados) // 1024} KB{aviso}")


def recortar_transparente(img: Image.Image) -> Image.Image:
    caixa = img.getchannel("A").point(lambda a: 255 if a > 24 else 0).getbbox()
    return img.crop(caixa) if caixa else img


def preparar_logo() -> Image.Image:
    if not LOGO.exists():
        sys.exit(f"Logo não encontrado: {LOGO}")
    logo = recortar_transparente(Image.open(LOGO).convert("RGBA"))

    # Logo do cabeçalho: 96 px de altura (nítido em telas 3x a 32 px).
    altura = 96
    largura = round(logo.width * altura / logo.height)
    logo.resize((largura, altura), Image.LANCZOS).save(SAIDA / "logo.png", optimize=True)
    print(f"  logo.png: {largura}x{altura}, {(SAIDA / 'logo.png').stat().st_size // 1024} KB")

    # Símbolo hexagonal: as primeiras colunas com tinta, até a primeira faixa vazia.
    alfa = logo.getchannel("A")
    colunas = [alfa.crop((x, 0, x + 1, logo.height)).getbbox() is not None for x in range(logo.width)]
    fim = next((x for x in range(10, logo.width) if not any(colunas[x : x + 12])), logo.width // 4)
    icone = recortar_transparente(logo.crop((0, 0, fim, logo.height)))
    lado = max(icone.size)
    margem = round(lado * 0.06)
    quadro = Image.new("RGBA", (lado + 2 * margem, lado + 2 * margem), (0, 0, 0, 0))
    quadro.paste(icone, ((quadro.width - icone.width) // 2, (quadro.height - icone.height) // 2), icone)
    quadro.save(SAIDA / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    toque = Image.new("RGBA", (180, 180), FUNDO + (255,))
    miolo = quadro.resize((140, 140), Image.LANCZOS)
    toque.paste(miolo, (20, 20), miolo)
    toque.convert("RGB").save(SAIDA / "apple-touch-icon.png", optimize=True)
    print("  favicon.ico, apple-touch-icon.png")
    return logo


def preparar_capturas() -> Image.Image | None:
    capa = None
    for original, recorte, nome in CAPTURAS:
        origem = CAPTURAS_ORIGINAIS / original
        if not origem.exists():
            print(f"  {original}: não encontrado")
            continue
        img = Image.open(origem).convert("RGB")
        if recorte:
            img = img.crop(recorte)
        if img.width > LARGURA_MAX:
            img = img.resize((LARGURA_MAX, round(img.height * LARGURA_MAX / img.width)), Image.LANCZOS)
        salvar_jpg(img, SAIDA / nome)
        if nome == CAPTURA_DA_CAPA:
            capa = img
    return capa


def cobrir(img: Image.Image, tamanho: tuple[int, int]) -> Image.Image:
    """Redimensiona e recorta ao centro para preencher `tamanho`."""
    w, h = tamanho
    escala = max(w / img.width, h / img.height)
    nova = img.resize((math.ceil(img.width * escala), math.ceil(img.height * escala)), Image.LANCZOS)
    x, y = (nova.width - w) // 2, (nova.height - h) // 2
    return nova.crop((x, y, x + w, y + h))


def fundo_provisorio(tamanho: tuple[int, int]) -> Image.Image:
    """Fundo escuro com textura discreta de pontos e linhas (decorativa, não é uma tela)."""
    k = 2  # desenha em 2x e reduz, para suavizar as bordas
    w, h = tamanho[0] * k, tamanho[1] * k
    img = Image.new("RGB", (w, h), FUNDO)
    d = ImageDraw.Draw(img)
    rnd = random.Random(7)
    pontos = [(rnd.uniform(0, w), rnd.uniform(0, h)) for _ in range(60)]
    pontos = [p for p in pontos if not (w * 0.18 < p[0] < w * 0.82 and h * 0.22 < p[1] < h * 0.62)]
    for p in pontos:
        for q in sorted(pontos, key=lambda q: (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2)[1:3]:
            d.line([p, q], fill=(30, 37, 52), width=2 * k)
    for p in pontos:
        r = 5 * k
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=(38, 46, 64))
    return img.resize(tamanho, Image.LANCZOS)


def capa(img01: Image.Image | None, logo: Image.Image, tamanho: tuple[int, int]) -> Image.Image:
    w, h = tamanho
    if img01 is not None:
        base = cobrir(img01, tamanho).filter(ImageFilter.GaussianBlur(1.2))
        base = Image.alpha_composite(base.convert("RGBA"), Image.new("RGBA", tamanho, FUNDO + (150,)))
    else:
        base = fundo_provisorio(tamanho).convert("RGBA")
    largura_logo = round(w * 0.5)
    marca = logo.resize((largura_logo, round(logo.height * largura_logo / logo.width)), Image.LANCZOS)
    # Um pouco acima do centro, para não ficar sob o botão do player.
    base.alpha_composite(marca, ((w - marca.width) // 2, round(h * 0.42 - marca.height / 2)))
    return base.convert("RGB")


def main() -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    print("Logo e ícones")
    logo = preparar_logo()
    print("Capturas")
    img01 = preparar_capturas()
    print("Capa do vídeo e og-image" + ("" if img01 else " (provisórias, sem a captura do grafo)"))
    salvar_jpg(capa(img01, logo, (1280, 720)), SAIDA / "IMG-07-capa-video.jpg")
    salvar_jpg(capa(img01, logo, (1200, 630)), SAIDA / "og-image.jpg")


if __name__ == "__main__":
    main()
