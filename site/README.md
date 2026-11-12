# Site de apresentação do NodeWatch

Esta pasta é o site estático da amostra tecnológica: uma página única em HTML, CSS e JavaScript, sem dependências externas, cookies ou analytics. Tudo o que a página precisa está aqui dentro, com caminhos relativos. Por isso, a pasta pode ser publicada sozinha, sem o resto do repositório.

## Conteúdo

```
site/
├── index.html                 página única (8 seções)
├── README.md                  este arquivo
└── assets/
    ├── css/site.css           estilos
    ├── js/site.js             menu, ampliação das capturas, vídeo sob demanda, link ativo
    └── img/
        ├── logo.png                 logo do cabeçalho e do rodapé
        ├── favicon.ico              ícone da aba
        ├── apple-touch-icon.png     ícone ao salvar na tela inicial
        ├── og-image.jpg             imagem de compartilhamento (1200×630)
        ├── IMG-07-capa-video.jpg    capa do vídeo
        └── tela-*.jpg               capturas reais do painel (4 arquivos)
```

Ficam fora desta pasta, de propósito: o código do aplicativo, modelos, datasets, `.env`, `.venv`, análises locais e o inicializador do Windows (`Inicializador Rápido/`, na raiz do repositório). A página só explica o inicializador e aponta para ele no GitHub.

Os únicos endereços externos são links:

- o repositório e o ZIP no GitHub;
- o relatório de ML;
- a pasta do inicializador;
- `youtube-nocookie.com`, usado só se o vídeo for um link do YouTube e só depois do clique.

## Visualizar no computador

Na raiz do repositório:

```bash
python -m http.server 8000 --directory site
```

Depois abra `http://127.0.0.1:8000`. Abrir o `index.html` com dois cliques também funciona, mas o servidor local reproduz melhor a publicação.

## Publicar

Envie o **conteúdo** desta pasta para qualquer hospedagem estática. O `index.html` deve ficar na raiz do endereço publicado.

- **GitHub Pages:** pela interface, o Pages só publica a raiz do repositório ou a pasta `docs/`. Para publicar `site/`, use uma das opções:
  - escolha "GitHub Actions" como fonte, com um fluxo que envie `site/` como artefato;
  - ou copie o conteúdo de `site/` para a raiz de uma branch ou repositório próprio do Pages.
- **Outras hospedagens:** Netlify, Cloudflare Pages ou similares aceitam a pasta como está; basta indicar `site` como diretório de publicação.

Antes de divulgar o QR code:

1. Defina o endereço final e troque `[URL_SITE]` no rodapé.
2. Troque o `og:image` do `index.html` por uma URL absoluta, como `https://…/assets/img/og-image.jpg`. Algumas redes não leem caminho relativo.
3. Preencha os marcadores que ainda aparecem na página: `[EVENTO]`, `[DATA]`, `[URL_VIDEO]`, `[TRANSCRICAO]` e `[PAPEL]`.

## Vídeo

No `index.html`, troque `data-video="[URL_VIDEO]"`:

- por um arquivo `.mp4` ou `.webm` (por exemplo, `assets/video/pitch.mp4`, colocado dentro desta pasta);
- ou por um link do YouTube.

A legenda vai em `data-legenda`, como arquivo `.vtt`. O player só é criado depois do clique.

## Imagens

As imagens desta pasta já estão prontas, e publicar não depende de nada fora dela. Para **regerá-las**, rode `python scripts/site/preparar_imagens.py` na raiz do repositório (precisa de Pillow). O script lê os originais fora desta pasta, `docs/ui/capturas/` e `interface/NodeWatchlogo_transparente.png`, sem alterá-los, e grava as cópias otimizadas em `site/assets/img/`.

O registro de fontes, as divergências com o briefing e a auditoria do conteúdo estão em `docs/site/README.md`.
