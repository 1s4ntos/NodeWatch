# FraudGraph · Documentação da Interface (v0.4 — C v2)

> Painel operacional para detecção de fraudes financeiras baseada em ciclos (Teoria dos Grafos).
> Esta documentação cobre a versão **C v2** do dashboard, redesenhada após auditoria heurística.

---

## 1. Visão Geral do Produto

### Objetivo
O **FraudGraph** é um painel analítico que modela transações financeiras como um **multigrafo direcionado ponderado** e aplica busca em profundidade (DFS) para identificar **ciclos de capital** — assinatura clássica de operações de lavagem de dinheiro, em que recursos saem de uma conta de origem, transitam por intermediárias, e retornam à origem (frequentemente com perdas marginais consistentes com taxas operacionais de camuflagem).

A interface materializa três tarefas críticas:

1. **Detectar** anomalias topológicas (ciclos) em conjuntos de transações.
2. **Contextualizar** cada ciclo: contas envolvidas, valores movimentados, duração, score de risco.
3. **Priorizar** a fila de revisão humana via ranking de contas por risco.

### Usuário-alvo
- **Analista de risco / investigador de fraudes** em instituição financeira ou fintech.
- Sessões longas (1–4h) em monitor wide; familiaridade com terminologia de grafos não é assumida, mas tabular numéricos e identificadores de conta são esperados.
- Problema resolvido: substituir o cruzamento manual de extratos por uma visão topológica que evidencia **circuitos de capital invisíveis em listagens lineares**.

---

## 2. Arquitetura da Informação e Layout

### Estrutura geral

```
┌──────────────────────────────────────────────────────────────┐
│  TOPBAR · brand · status · CTA Re-analisar                   │
├──────────────────────────────────────────────────────────────┤
│  ALERT BANNER · única instância de alarme proeminente        │
├──────────────────────────────────────────────────────────────┤
│  KPI STRIP · 4 cards (Vértices · Arestas · Volume · Em risco)│
├──────────────────────────────────────────┬───────────────────┤
│                                          │                   │
│   GRAFO DE TRANSAÇÕES (hero ~60%)        │  CICLO            │
│                                          │  SELECIONADO      │
│   • toggle "Valores nas arestas"         │  (~40%)           │
│   • seletor de layout                    │                   │
│                                          │  Timeline +       │
│                                          │  stats (Total,    │
│                                          │  Perda, Duração)  │
├──────────────────────────────────────────┴───────────────────┤
│  RANKING DE RISCO · top 5 contas (cards horizontais)         │
├──────────────────────────────────────────────────────────────┤
│  ▸ Tabela de transações       (collapsed by default)         │
│  ▸ Distribuição & valores     (collapsed by default)         │
│  ▸ Log de execução            (collapsed by default)         │
└──────────────────────────────────────────────────────────────┘
```

### Fluxo de leitura — padrão Z

1. **Z-1 (canto superior esquerdo)**: brand + status — orientação do sistema.
2. **Z-1 → Z-2 (varredura horizontal superior)**: Alert banner + CTA "Revisar ciclos".
3. **Z-2 → Z-3 (diagonal descendente)**: KPIs neutros → KPI "Em risco" (vermelho) → grafo (foco visual principal).
4. **Z-3 → Z-4 (varredura horizontal inferior)**: ciclo selecionado → ranking de risco → seções colapsáveis.

A diagonal **macro → micro** vai do *resumo agregado* (alert + KPI) para o *detalhe forense* (timeline + tabela bruta).

---

## 3. Anatomia dos Componentes

### 3.1 Alert Banner
Faixa única na cor de risco (`#ef5552`) imediatamente abaixo da topbar.
- **Função**: responder em <2 s "o que aconteceu?".
- **Elementos**: ícone de alerta · headline (`N ciclos suspeitos detectados`) · sublinha contextual (volume + contas envolvidas) · CTA primário (`Revisar ciclos →`).
- **Regra**: orçamento de alarme — esta é a **única** instância vermelha de gradient/borda no topo da tela. Demais sinais de risco usam cor sem fundo.

### 3.2 KPI Cards
Strip horizontal de 4 cards com padding generoso (`20px 24px`), tipografia tabular monospace (36 px / weight 600).

| Card             | Significado                               | Cor        |
|------------------|-------------------------------------------|------------|
| Vértices         | nº de contas únicas                       | neutra     |
| Arestas          | nº de transações observadas               | neutra     |
| Volume total     | soma `BRL` movimentada                    | neutra     |
| **Em risco**     | volume contido nos ciclos detectados      | **danger** |

Apenas o KPI crítico ("Em risco") usa borda + gradient vermelho — separa o que **demanda ação** do que é **referência estatística**.

### 3.3 Grafo de Transações (hero)
Visualização SVG dos vértices (contas) e arestas (transações).

**Cabeçalho do painel** contém:
- **Toggle `Valores nas arestas`** (switch). Estado padrão **oculto** — arestas de ciclo aparecem limpas, apenas com setas direcionais. Quando ligado, renderiza pills `R$x.xk` no centro de cada aresta de ciclo. Lógica:
  ```jsx
  {showAmounts && (
    <g>
      <rect …/>
      <text>{fmtAmount(edge.amount)}</text>
    </g>
  )}
  ```
- **Seletor de layout**: `Force` · `Hierárquico` · `Circular`.

**Convenções visuais**:
- Arestas normais — `stroke: muted`, `opacity: 0.35`, sem rótulo.
- Arestas de ciclo — `stroke: danger`, `width: 2.25`, halo translúcido.
- Vértices em ciclo — preenchimento `dangerBg`, glow gaussiano, label em `danger`.
- Vértices normais — outline cinza, opacidade reduzida.

### 3.4 Ciclo Selecionado (timeline lateral)
Painel à direita do grafo. Cabeçalho com pills `#1` `#2` para alternar ciclo ativo.

**Anatomia da timeline**:
- Header: caminho monoespaçado (`C001 → C002 → C003 → C001`).
- Lista vertical alternando **nó** (avatar circular vermelho com ID + risk score) e **aresta** (caixa com valor, tipo, step).
- Rótulos semânticos por posição: `Origem` · `Intermediária N` · `Retorno à origem`.
- Footer: três stats — `Total` (vermelho), `Perda` (amber, diferença entre 1ª e última aresta), `Duração` (neutra).

### 3.5 Ranking de Risco
Linha horizontal com top 5 contas ordenadas por `risk score (0–100)`. Cada card:
- Borda esquerda colorida por **tier** (`≥80` danger · `≥40` amber · resto success).
- ID monospace + score grande.
- Volume movimentado abaixo.
- Mini-barra horizontal de progresso (4 px).

Substitui a lista vertical empilhada da v1 — densidade equivalente em ⅕ do espaço vertical.

### 3.6 Tabela de Transações
Colapsada por padrão (`<details>`). Quando expandida: 7 colunas — `step` · `tipo` · `amount` · `origem` · `destino` · `fraude` · `flags`.

**Lógica da coluna `FLAGS`** (semântica composicional):

```jsx
<td>
  <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
    {inCycle  && <span className="pill amber">EM CICLO</span>}
    {isFraud  && <span className="pill danger">LABELED</span>}
  </span>
</td>
```

| Cenário                                  | Render                          |
|------------------------------------------|---------------------------------|
| Transação fora de ciclo, sem label       | *(célula vazia)*                |
| Transação dentro de ciclo, sem label     | `EM CICLO` (amber)              |
| Transação labelada `isFraud=1` fora ciclo| `LABELED` (danger)              |
| **Transação que fecha o ciclo (fraude)** | `EM CICLO` + `LABELED` *lado a lado* |

A composição preserva **rastreabilidade**: o analista vê tanto a pertinência ao grupo de anomalias quanto a confirmação supervisionada.

---

## 4. Linguagem Visual e Semântica

### 4.1 Tema — Dark Mode
- Fundo principal `#131820` (azul-acinzentado quente, evita preto puro `#000`).
- Painéis em `#1a2030`, hierarquia secundária em `#161c28`.
- Justificativa: redução de **fadiga visual em sessões longas** (1–4 h), redução de glare em ambiente low-light de SOC, e maior contraste relativo dos elementos vermelhos sem que se tornem agressivos.

### 4.2 Paleta semântica (WCAG AA+)

| Token         | Hex       | Uso                                              | Contraste |
|---------------|-----------|--------------------------------------------------|-----------|
| `text`        | `#e6e9ef` | corpo                                            | 14.2:1 ✓ AAA |
| `textMuted`   | `#a4abbd` | labels secundários                               | 7.8:1 ✓ AAA  |
| `danger`      | `#ef5552` | **apenas** ciclos confirmados + `isFraud=1`      | 5.4:1 ✓ AA   |
| `amber`       | `#e6a82f` | "em ciclo, sem label" · "atenção, requer revisão"| 9.1:1 ✓ AAA  |
| `primary`     | `#4d8eef` | interativo, seleção, links                       | 5.6:1 ✓ AA   |
| `success`     | `#4cb96b` | health checks, status `ok`                       | 7.2:1 ✓ AAA  |

**Regra de orçamento de cor**: máximo 5 instâncias `danger` simultâneas no viewport. Tudo que é "anômalo, mas não confirmado" usa `amber`. Status neutros (`online`, `ok`, contagens) não consomem o orçamento.

### 4.3 Tipografia
- **Inter** — corpo (14 px / 1.5).
- **JetBrains Mono** — IDs de conta, valores monetários, timestamps de log, headers de KPI.
- KPI value: 36 px / weight 600 / `tabular-nums` / `letter-spacing: -0.02em`.
- Panel title: 12 px / weight 600 / `letter-spacing: 0.08em` / `uppercase`.

---

## 5. Interações e Comportamentos

### 5.1 Progressive Disclosure
Três seções secundárias usam `<details>` HTML nativo (colapsadas por padrão):

- **Tabela de transações** — registro bruto, consultado em ~20% das sessões.
- **Distribuição & valores** — barras horizontais de buckets monetários e steps temporais.
- **Log de execução** — diagnóstico do algoritmo (DFS, tempo, tamanho do grafo).

A escolha de `<details>` (em vez de modal/tab) preserva o **scroll mental** — o analista pode expandir, ler, e o grafo+timeline continuam à vista contextual ao rolar para cima.

### 5.2 Estados interativos

| Componente                | Estados                                           |
|---------------------------|---------------------------------------------------|
| Toggle `Valores nas arestas` | `off` (default) · `on` (rótulos visíveis)      |
| Pills de ciclo (`#1` `#2`)| `idle` · `active` (preenchimento `primarySoft`)   |
| Seletor de layout         | `idle` · `active`                                 |
| `<details>` collapsibles  | `closed` (default) · `open`                       |
| KPI "Em risco"            | gradient + borda danger sempre — sem hover state  |
| Hover em ciclo (timeline) | dim arestas dos demais ciclos para `opacity: 0.25`|

### 5.3 Padrões de feedback
- **Confirmação de ação** (re-análise) → CTA primário no canto superior direito.
- **Status do sistema** — dot verde + texto `online` na topbar.
- **Carregamento** — herdado do framework Streamlit (spinner nativo); UI da v0.4 não introduz spinner próprio.

---

## 6. Anexos técnicos

- **Stack**: React 18 (UMD) · Babel standalone · SVG inline (sem D3). 
- **Fontes**: Google Fonts — Inter, JetBrains Mono, Crimson Pro.
- **Acessibilidade**: targets ≥ 32 px, contraste documentado, `aria-pressed` no toggle, semântica nativa em `<details>`/`<summary>`.
- **Compatibilidade alvo**: Chromium 110+, Firefox 110+, Safari 16+ — desktop ≥ 1280 px.

---

*Documento mantido em `docs/ui/fraudgraph-v0.4.md`.
Última atualização: maio/2026.
Repositório: `github.com/1s4ntos/Sistema-de-Detec-o-de-Fraudes`.*
