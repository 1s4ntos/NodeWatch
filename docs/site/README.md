# Site de apresentação

O site estático da amostra tecnológica fica em [`site/`](../../site/) (`index.html` + `assets/`). O conteúdo segue o briefing `ESPECIFICACAO_SITE.md`, que fica fora do repositório, com os ajustes listados abaixo.

Para publicar, envie **só** a pasta `site/`, por exemplo no GitHub Pages. Todos os caminhos são relativos.

- **Sem dependências:** HTML, CSS e JS puros, sem fontes externas, analytics ou cookies.
- **Tamanho:** cerca de 540 KB com as quatro capturas, abaixo do limite de 1 MB.

## Regra de conteúdo

A página só apresenta como disponível o que está implementado e pode ser usado no fluxo atual:

- o **painel do analista**, em `http://127.0.0.1:5000/`;
- a **linha de comando** documentada no README (`python src/main.py`).

Não entram como recurso disponível:

- funções que existem só em scripts;
- o laboratório de simulação;
- endpoints internos;
- a interface antiga (`/legado`);
- planos futuros.

## Imagens

`python scripts/site/preparar_imagens.py` (na raiz, precisa de Pillow) gera em `site/assets/img/`:

- recortes 16:10 de capturas reais do painel atual, em `docs/ui/capturas/` (os originais não são alterados):
  - `depois_desktop_topo.jpg` → `tela-dataset.jpg`;
  - `depois_desktop_visao.jpg` → `tela-visao.jpg`;
  - `depois_desktop_grafo.jpg` → `tela-contas.jpg`;
  - `depois_desktop_sequencia.jpg` → `tela-grafo.jpg`;
- `IMG-07-capa-video.jpg` (a captura do grafo com o logo) e `og-image.jpg` (1200×630);
- `logo.png`, `favicon.ico` e `apple-touch-icon.png`, feitos de `interface/NodeWatchlogo_transparente.png` (IMG-08).

Todas as cópias têm no máximo 1280 px e 150 KB.

O diagrama IMG-06 (tabela → grafo → alerta) é SVG dentro do `index.html`.

As capturas são de uma análise do HI-Small de 01/09/2022 a 03/09/2022. Esses dias estão no treino do modelo (`treino_ate = 2022-09-07` em `src/ml/config.py`), e a página avisa que os alertas da tela não medem desempenho.

## Vídeo

- **Endereço:** em `site/index.html`, troque `data-video="[URL_VIDEO]"` por um `.mp4`/`.webm` ou por um link do YouTube, que é aberto por `youtube-nocookie.com`.
- **Legenda:** vai em `data-legenda`, como arquivo `.vtt`.
- **Comportamento:** o player só é criado depois do clique. Sem endereço, a seção mostra a capa e "Vídeo em breve".

## Marcadores na página

| Marcador | Onde | O que falta |
|---|---|---|
| `[EVENTO]` `[DATA]` | Selo do topo e rodapé | Nome e data da amostra |
| `[URL_VIDEO]` | Player (S2) | Vídeo pitch e legenda `.vtt` |
| `[TRANSCRICAO]` | "Ler transcrição" (S2) | Texto do vídeo |
| `[PAPEL]` ×5 | Equipe (S8) | Papel de cada integrante |
| `[CONFIRMAR_VINCULO]` | Cartão da Julia (S8) | Se ela aparece como integrante atual ou como colaboradora histórica |
| `[CONFIRMAR_MODELO]` | "Rode no seu computador" (S7) | Num clone novo, o Analisar falha: o modelo fica em `artefatos_ml/`, pasta ignorada pelo Git, e o treino exige o HI-Small |
| `[URL_SITE]` | Rodapé | Endereço final; usar também em `og:image` (URL absoluta) e no QR code |

## Auditoria de funcionalidades (11/11/2026, `main` `8e1ab2e`)

### Removido da página

| Item | Onde estava | Situação no código |
|---|---|---|
| Cartão "Fan-out e fan-in" e selo "Em integração" | S5 | O detector `find_fan_patterns` só roda por scripts (`scripts/benchmark_fan.py`). O painel mostra as tipologias registradas no arquivo de padrões, não o detector. |
| Selos "Disponível" dos cartões de técnica | S5 | DFS e SCC não estão no painel (`src/painel` não importa `src/algoritmos`). Os selos deram lugar ao lugar onde cada técnica roda. |
| "Em integração: detector de fan-out/fan-in no painel" | S7 | Mesmo motivo do cartão |
| "Planejado: fila de alertas com registro de decisão, painel de supervisão, fusão rede+transação" | S7 | Não implementados. A falta de fusão continua na FAQ de S6. |
| Da lista "Disponível hoje": painel de ML, eventos (replay e API), exportação JSON/CSV, assistente Sentinel AI, "risco por conta" | S7 | Só na interface antiga (`/legado`) ou como endpoint (`/api/ml/eventos`). O Sentinel AI é o chat com Gemini do `/legado`. "Risco por conta" não existe no painel ("não existe score por conta", `PAINEL_ANALISTA.md`). |
| Nota "A seção de Machine Learning funciona sem chave. O assistente Sentinel AI usa a API do Google Gemini…" | S7 | Fala da interface antiga. Trocada por "O painel funciona sem chave de API." |
| Nota sobre as colunas `step, type, …` em `/legado` | S7 | Recurso da interface antiga |
| FAQ "É em tempo real?": "reproduz arquivos (replay), recebe eventos pela API e tem um laboratório de simulação" | S6 | Replay, ingestão por API e laboratório ficam no `/legado`. A resposta agora descreve o painel. |
| Vazão "11.204/s no replay pelo serviço" | S6 | Mede o serviço de eventos, que não está no fluxo atual. Ficou só a vazão em lote. |
| "sempre mostrando o motivo de cada alerta" (subtítulo e meta descrição) e "Alerta com o motivo" (passo 3) | S1, `<head>`, S3 | Os "motivos verificáveis" são fatos de regra fixa, podem faltar e não explicam o modelo (`src/ml/preparacao.py`, `COMO_FUNCIONA` 8.6). O passo virou "Alerta para investigação". |
| Quatro espaços de captura da interface antiga (Grafos C001–C003, Análise financeira, Análise de rede, Avaliação) e o aviso das "200 linhas / 16 transações" | S4 | Telas do `/legado`. Trocadas por capturas reais do painel atual, com legendas e alt-texts que descrevem o que cada uma mostra. |

### Mantido, com a implementação confirmada

| Na página | Onde está no código |
|---|---|
| Envio e validação de CSV/ZIP; escolha de dataset do servidor | `src/painel/datasets.py`; `docs/ui/PAINEL_ANALISTA.md` (Fluxo, Datasets) |
| Análise só depois do clique, com progresso e cancelamento | `src/painel/pipeline.py` (`GerenciadorAnalises`) |
| Score de 0 a 1000 por transação, com limiar | `src/painel/score.py`; `PAINEL_ANALISTA.md` (Score) |
| Filtros, contas de maior risco, grafo da conta em foco, tabela com detalhes, análises recentes | `src/painel/armazenamento.py`, `interface/assets/painel-*.js`; `PAINEL_ANALISTA.md` |
| Assistente de dúvidas local, sem chave | `src/painel/assistente.py` |
| Formatos IBM AML e em português; exemplo `docs/exemplos/transacoes_inventadas.csv` | `src/painel/datasets.py` (`detectar_formato`); `PAINEL_ANALISTA.md` (Datasets) |
| Ciclos (DFS), SCC (Kosaraju) e centralidade na linha de comando | `src/main.py`, `src/algoritmos/`; executado em 11/11 com `dados/exemplo_transacoes.csv`: 3 ciclos, 3 SCCs suspeitos e a tabela de centralidade |
| Random Forest; o painel usa só o modelo de lavagem | `src/painel/pipeline.py` (`pontuar_lavagem`); `RELATORIO_ML.md` |
| Python 3.12 ou mais novo, testado no 3.14 | `README.md`, `Inicializador Rápido/README.md`, guias, `start_presentation.*`, `numpy==2.5.4` |

### Limitações que continuam na página

- **Dados e teste:** os dados são sintéticos, o período de teste foi reusado e os resultados não representam dados reais (faixa de aviso em S6).
- **Lavagem sem padrão conhecido:** o modelo recupera só 1,9% desses casos (cartão em S6).
- **Modelo de rede:** o ganho quase some em fluxos inéditos (cartão em S6).
- **Tempo real:** não há fonte ao vivo; o painel analisa arquivos depois do clique (FAQ de S6).
- **Fusão:** não há fusão entre rede e transação (FAQ de S6).
- **Decisão humana:** o sistema indica padrões, e a decisão é do analista (S3 e rodapé).
- **Sequência no grafo:** horário compatível não prova que é o mesmo dinheiro (legenda em S4).
- **Capturas:** os alertas das telas vêm do período de treino (aviso em S4).
- **Vazão:** foi medida numa máquina de teste e não é garantia (S6).
- **Modelo treinado:** não vem no repositório (`[CONFIRMAR_MODELO]` em S7).

## Registro de fontes dos números

| Na página | Fonte |
|---|---|
| AP 0,46; acaso 0,001 | `docs/ml/RELATORIO_ML.md`: 0,464; prevalência 0,0011 |
| macro-F1 0,75 × 0,71 | `docs/ml/RELATORIO_ML.md`: 0,750 × 0,711; inéditos 0,681 × 0,674 |
| 1,9% (≈ 39%) | `docs/ml/RELATORIO_ML.md`: 0,019 nos 371 positivos sem padrão |
| 17.981 transações/s em lote | `docs/ml/BENCHMARK_EVENTOS.md`, "vazão em lote (atributos + score, sem serviço)": dia 10/09/2022 do HI-Small; Windows 11, 20 CPUs, Python 3.14.0, 06/11/2026 |
| Até 10 contas; score de 0 a 1000 | `docs/ui/PAINEL_ANALISTA.md` |
| 01/09/2022 a 03/09/2022 | Capturas `docs/ui/capturas/depois_desktop_visao.jpg` (período coberto) |
| Repositório público | HTTP 200 em 11/11/2026 |
| Teoria dos Grafos; Profa. Dra. Andrea Ono Sakai | `README.md`, linha 3 |

## Divergências com o briefing

1. **Vazão:** o briefing aprova "9.163/s", número que saiu de `BENCHMARK_EVENTOS.md`. A página mostra só a vazão em lote atual.
2. **Python:** o briefing diz 3.11+; a página diz 3.12+, testado no 3.14.
3. **Formato do CSV:** a página descreve o formato do painel em `/`, não as colunas da interface antiga.
4. **Recursos removidos:** fan-out/fan-in, os itens "Planejado", os recursos do `/legado` e as capturas da interface antiga saíram por pedido do usuário em 11/11/2026 (ver "Auditoria").
5. **Textos oficiais alterados:**
   - o subtítulo de S1 perdeu "sempre mostrando o motivo de cada alerta";
   - o passo 3 de S3 virou "Alerta para investigação";
   - a resposta da FAQ "É em tempo real?" mudou;
   - o título de S2 virou "O projeto", também por pedido do usuário.
6. **Julia e modelo:** dependem da equipe (ver "Marcadores na página").
