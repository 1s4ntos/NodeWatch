# E3 — MVP: Núcleo Funcional com Primeiras Telas

> **Disciplina:** Teoria dos Grafos
> **Prazo:** 10 de maio de 2026
> **Peso:** 25% da nota final

---

## Identificação do Grupo

| Campo | Preenchimento |
|-------|---------------|
| Nome do projeto | NodeWatch |
| Repositório GitHub | https://github.com/1s4ntos/NodeWatch |
| Integrante 1 | Caio Winkler Marangoni — 39968545 |
| Integrante 2 | Guilherme Lombardi — 38054264 |
| Integrante 3 | Ryan dos Santos Veloso — 37732005 |

---

## 1. Como Executar o MVP

> Instrua como rodar o projeto do zero. Alguém que nunca viu o código deve conseguir executar seguindo estas instruções.

### Opção 1 — Interface visual com Sentinel AI (recomendada)

**Pré-requisitos:** Python 3.11+ e chave de API do Google Gemini ([aistudio.google.com/apikey](https://aistudio.google.com/apikey))

**Via script de apresentação (um comando):**

```powershell
# Windows
.\start_presentation.ps1
```

```bash
# Linux / macOS
chmod +x start_presentation.sh && ./start_presentation.sh
```

O script cria o ambiente virtual, instala dependências, configura o `.env` e inicia o servidor automaticamente.

Acessar em: `http://127.0.0.1:5000/`

**Ou manualmente:**

```bash
git clone https://github.com/1s4ntos/NodeWatch.git
cd NodeWatch
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\Activate.ps1  # Windows
pip install -r requirements.txt
cp .env.example .env
# Editar .env e preencher GEMINI_API_KEY=sua_chave_aqui
python src/sentinel_ai.py
```

### Opção 2 — Interface visual (sem instalação, sem backend)

O `interface/index.html` pode ser aberto com duplo clique no navegador sem nenhuma instalação. Nesse modo o dashboard, grafo, ciclos, exportação JSON e histórico funcionam normalmente. O Sentinel AI não estará disponível pois requer o backend Flask.

### Opção 3 — CLI (linha de comando)

**Pré-requisitos:** Python 3.11 ou superior

**Instalação:**

```bash
git clone https://github.com/1s4ntos/NodeWatch.git
cd NodeWatch
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

**Execução básica:**

```bash
python src/main.py --input dados/exemplo_transacoes.csv
```

**Com todos os algoritmos e exportação:**

```bash
python src/main.py --input dados/exemplo_transacoes.csv --centralidade --scc --export-json
```

**Flags disponíveis:**

| Flag | Descrição |
|------|-----------|
| `--input` / `-i` | Caminho para o CSV (default: `dados/exemplo_transacoes.csv`) |
| `--centralidade` | Exibe tabela de centralidade de grau e risk score |
| `--scc` | Exibe Componentes Fortemente Conectados (Kosaraju) |
| `--export-json` | Exporta análise completa em JSON para `dados/analises/` |
| `--output` / `-o` | Nome personalizado para o arquivo JSON exportado |

**Saída esperada:**

```
============================================================
=== Sistema de Detecção de Fraudes com Grafos ===
============================================================
Arquivo carregado: dados/exemplo_transacoes.csv
Vértices (contas): 15
Arestas (transações): 16
Algoritmo a executar: DFS para detecção de ciclos suspeitos
Complexidade: tempo O(V + E) | espaço O(V)
------------------------------------------------------------
Resultado:
  CICLO 1 [! ALTO]:
    Caminho: C011 -> C012 -> C013 -> C014 -> C011
    Contas envolvidas (4): C011, C012, C013, C014
    Valor total: R$ 30,800.00
    Perda no ciclo: R$ 600.00
  CICLO 2 [! ALTO]:
    Caminho: C001 -> C002 -> C003 -> C001
    Contas envolvidas (3): C001, C002, C003
    Valor total: R$ 29,800.00
    Perda no ciclo: R$ 200.00
  CICLO 3 [! ALTO]:
    Caminho: C006 -> C007 -> C008 -> C006
    Contas envolvidas (3): C006, C007, C008
    Valor total: R$ 8,850.00
    Perda no ciclo: R$ 100.00
------------------------------------------------------------
Ciclos de layering encontrados: 3
Total: 3
```

**Como rodar os testes:**

```bash
pytest testes/ -v
```

---

## 2. Algoritmos Implementados

### 2.1 Algoritmo Principal — DFS para detecção de ciclos

| Campo | Resposta |
|-------|----------|
| Nome do algoritmo | DFS para detecção de ciclos em grafo direcionado |
| Arquivo de implementação | `src/algoritmos/cycle_detection.py` |
| Complexidade de tempo | O(V + E) por travessia DFS |
| Complexidade de espaço | O(V) (pilha de recursão + conjunto `on_path`) |
| Retorno | `List[CycleResult]` com caminho, categoria, prioridade, valor total e perda |

**Regras de negócio aplicadas:**
- **RN02** — Todo ciclo é reportado, sem filtro por valor mínimo
- **RN03** — Prioridade por tipo: TRANSFER=ALTO, CASH_OUT=MÉDIO-ALTO, PAYMENT=MÉDIO
- **RN05** — Self-loops classificados como ANOMALIA (categoria separada)
- **RN06** — Ordenação: prioridade → valor total → número de intermediários

**Trecho do código com comentário de Big-O:**

```python
def find_cycles(graph: Graph) -> List[CycleResult]:
    """Encontra todos os ciclos simples em um grafo direcionado."""
    raw_paths: List[List[str]] = []

    # Pré-computa adjacência única — O(V + E)
    adjacency: Dict[str, Set[str]] = {v: set() for v in graph.vertices()}
    for edge in graph.edges():
        adjacency.setdefault(edge.source, set()).add(edge.target)
        adjacency.setdefault(edge.target, set())

    sorted_vertices = sorted(adjacency.keys())  # O(V log V) auxiliar

    for start in sorted_vertices:
        path: List[str] = [start]
        on_path: Set[str] = {start}
        _dfs_cycles(start, start, adjacency, path, on_path, raw_paths)

    # Enriquece cada ciclo com prioridade, valor e categoria
    results = _enrich_cycles(raw_paths, graph)

    # RN06 — ordenação: prioridade desc → valor desc → intermediários desc
    results.sort(key=lambda r: (r.priority_rank, r.total_value, r.intermediaries), reverse=True)
    return results
```

---

### 2.2 Algoritmo Adicional — Centralidade de Grau

| Campo | Resposta |
|-------|----------|
| Nome do algoritmo | Centralidade de Grau com risk score acumulado |
| Arquivo de implementação | `src/algoritmos/centralidade.py` |
| Complexidade de tempo | O(V + E) |
| Complexidade de espaço | O(V) |
| Retorno | `List[AccountCentrality]` ordenada por risk score desc |

**O que calcula:**
- `in_degree` — número de transações recebidas
- `out_degree` — número de transações enviadas
- `volume_in` / `volume_out` — volumes financeiros
- `risk_score` — base pelo tipo de transação + 15 por ciclo participado, teto 100 (RN04)
- `hub_type` — SUSPEITO, DISTRIBUIDOR, COLETOR, INTERMEDIÁRIO ou NORMAL

---

### 2.3 Algoritmo Adicional — SCC (Kosaraju)

| Campo | Resposta |
|-------|----------|
| Nome do algoritmo | Componentes Fortemente Conectados — Kosaraju |
| Arquivo de implementação | `src/algoritmos/scc.py` |
| Complexidade de tempo | O(V + E) — duas passagens DFS |
| Complexidade de espaço | O(V + E) — grafo transposto + pilha |
| Retorno | `List[SCCResult]` ordenada por suspeitos primeiro, tamanho desc |

**Por que Kosaraju e não Tarjan:** mesma complexidade O(V+E), mas as duas passagens DFS são conceitualmente separadas e mais claras para explicar e depurar.

---

## 3. Estrutura do Repositório

```
NodeWatch/
├── src/
│   ├── sentinel_ai.py              # Backend Flask + Sentinel AI (Google Gemini)
│   ├── main.py                     # CLI com flags --centralidade --scc --export-json
│   ├── grafo/
│   │   └── graph.py                # Multigrafo direcionado ponderado
│   ├── algoritmos/
│   │   ├── cycle_detection.py      # DFS — ciclos com CycleResult tipado
│   │   ├── centralidade.py         # Centralidade de grau + risk score (RN04)
│   │   └── scc.py                  # SCC — algoritmo de Kosaraju
│   └── leitura/
│       ├── file_reader.py          # Leitura e validação do CSV PaySim
│       └── exportador.py           # Exportação de análises em JSON estruturado
├── testes/
│   ├── test_cycle_detection.py     # 7 testes (3 obrigatórios + 4 bônus)
│   ├── test_centralidade.py        # 6 testes
│   ├── test_scc.py                 # 7 testes
│   └── test_exportador.py          # 7 testes
├── dados/
│   ├── exemplo_transacoes.csv      # Dataset PaySim — 16 transações, 5 tipos
│   └── analises/                   # Análises exportadas em JSON (gerado em runtime)
├── interface/
│   ├── index.html                  # Dashboard + Sentinel AI chat (autossuficiente)
│   └── NodeWatchlogo_transparente.png
├── docs/
│   ├── E1_Grupo4.md
│   ├── E2_Grupo4.md
│   ├── E3_Grupo4.md
│   ├── SENTINEL_AI.md              # Documentação técnica do assistente
│   ├── diagramaE1.png
│   ├── diagramaE2.png
│   └── ui/
│       └── README-INTERFACE.md
├── .env.example
├── .gitignore
├── start_presentation.ps1 / .sh
├── run_local.ps1 / .sh
├── README.md
├── README_LOCAL.md
├── README_DEPLOY.md
├── conftest.py
└── requirements.txt
```

**Desvios e evoluções em relação ao E2:**

- Nomes de pastas mantidos em PT-BR (`grafo/`, `algoritmos/`, `leitura/`, `testes/`, `dados/`) — alinhados com a documentação do trabalho.
- Algoritmos adicionais `centralidade.py` e `scc.py` previstos no E2 foram implementados nesta entrega.
- `cycle_detection.py` evoluiu de retornar `List[List[str]]` para `List[CycleResult]` — dataclass tipado com `path`, `category`, `priority`, `total_value`, `loss` e `intermediaries`.
- Adicionado `exportador.py` na camada de infraestrutura para persistência de análises em JSON.
- Adicionado `sentinel_ai.py` — backend Flask que serve o dashboard e integra o Sentinel AI via Google Gemini.
- `dados/analises/` — nova pasta criada em runtime para persistência de análises; mantida no repositório via `.gitkeep`; JSONs ignorados pelo `.gitignore` por conterem dados potencialmente sensíveis.
- Scripts de apresentação adicionados (`start_presentation.sh/.ps1`, `run_local.sh/.ps1`) para inicialização com um único comando.

---

## 4. Telas do MVP

### Tela 1 — Dashboard interativo

Arquivo: `interface/index.html` — serve via Flask (`http://127.0.0.1:5000`) ou duplo clique no navegador.

**Componentes:**

- **Topbar** — nome do sistema, arquivo analisado, botões "Exportar relatório ↗" (PDF) e "Salvar JSON ↓" (exporta análise estruturada)
- **Alert bar** — número de ciclos detectados, volume em risco e contas suspeitas envolvidas
- **KPIs** — total de vértices, arestas, volume total e valor em risco (destacado em vermelho)
- **Grafo interativo** — visualização SVG com três layouts intercambiáveis:
  - *Force* (padrão) — separa visualmente os clusters suspeitos
  - *Hierárquico* — distribui os nós em camadas por ordem alfabética
  - *Circular* — posiciona todos os nós uniformemente em anel
- **Toggle "Valores nas arestas"** — exibe o valor de cada transação de ciclo diretamente sobre as arestas
- **Painel de ciclo selecionado** — badge de prioridade/categoria, caminho completo, timeline com risk score por conta, valor e tipo de cada transação, total, perda e duração em steps
- **Top 5 contas por risco** — cards com score (vermelho ≥ 80, laranja 40–79, verde < 40), volume e barra de risco
- **Tabela de transações** (colapsável) — 16 transações com badges "EM CICLO" e "LABELED"
- **Distribuição & valores** (colapsável) — histograma por faixa de valor e atividade por step temporal com destaque para steps suspeitos
- **Log de execução** (colapsável) — registro dos três algoritmos executados
- **Análises salvas** (colapsável) — histórico de JSONs exportados com nome, data, ciclos e volume
- **Sentinel AI** — chat integrado com dois modos (leiga / técnica); recebe snapshot do estado da interface em tempo real

### Tela 2 — CLI: entrada

```
============================================================
=== Sistema de Detecção de Fraudes com Grafos ===
============================================================
Arquivo carregado: dados/exemplo_transacoes.csv
Vértices (contas): 15
Arestas (transações): 16
Algoritmo a executar: DFS para detecção de ciclos suspeitos
Complexidade: tempo O(V + E) | espaço O(V)
------------------------------------------------------------
```

### Tela 3 — CLI: resultado (DFS)

```
Resultado:
  CICLO 1 [! ALTO]:
    Caminho: C011 -> C012 -> C013 -> C014 -> C011
    Contas envolvidas (4): C011, C012, C013, C014
    Valor total: R$ 30,800.00
    Perda no ciclo: R$ 600.00
  CICLO 2 [! ALTO]:
    Caminho: C001 -> C002 -> C003 -> C001
    Contas envolvidas (3): C001, C002, C003
    Valor total: R$ 29,800.00
    Perda no ciclo: R$ 200.00
  CICLO 3 [! ALTO]:
    Caminho: C006 -> C007 -> C008 -> C006
    Contas envolvidas (3): C006, C007, C008
    Valor total: R$ 8,850.00
    Perda no ciclo: R$ 100.00
------------------------------------------------------------
Ciclos de layering encontrados: 3
Total: 3
```

### Tela 4 — CLI: centralidade de grau (`--centralidade`)

```
------------------------------------------------------------
Centralidade de Grau — Top contas por risco
------------------------------------------------------------
  Conta        In  Out Ciclos  Score  Tipo
  C001          2    2      1     55  SUSPEITO
  C002          2    1      1     55  SUSPEITO
  C003          2    1      1     55  SUSPEITO
  C006          1    1      1     55  SUSPEITO
  C007          1    1      1     55  SUSPEITO
  C008          1    1      1     55  SUSPEITO
  C011          1    1      1     55  SUSPEITO
  C012          1    1      1     55  SUSPEITO
  C013          1    1      1     55  SUSPEITO
  C014          1    1      1     55  SUSPEITO
------------------------------------------------------------
```

### Tela 5 — CLI: SCC (`--scc`)

```
------------------------------------------------------------
Componentes Fortemente Conectados (Kosaraju)
------------------------------------------------------------
  SCCs suspeitos (size > 1): 3
  Vértices isolados:         5

  Grupos de risco:
    SCC #1 — 4 contas | Volume interno: R$ 30,800.00 | Arestas internas: 4
      Contas: C011, C012, C013, C014
    SCC #8 — 3 contas | Volume interno: R$ 30,300.00 | Arestas internas: 4
      Contas: C001, C002, C003
    SCC #5 — 3 contas | Volume interno: R$ 8,850.00 | Arestas internas: 3
      Contas: C006, C007, C008
------------------------------------------------------------
```

---

## 5. Testes Unitários

| Módulo | Arquivo | Testes | Status |
|--------|---------|--------|--------|
| DFS — ciclos | `test_cycle_detection.py` | 7 (3 obrigatórios + 4 bônus) | ✓ Todos passando |
| Centralidade de grau | `test_centralidade.py` | 6 | ✓ Todos passando |
| SCC — Kosaraju | `test_scc.py` | 7 | ✓ Todos passando |
| Exportador JSON | `test_exportador.py` | 7 | ✓ Todos passando |

**Total: 27 testes passando.**

**Como rodar:**

```bash
# Todos os testes
pytest testes/ -v

# Módulo específico
pytest testes/test_cycle_detection.py -v
```

**Resultado:**

```
collected 27 items

testes/test_centralidade.py::test_graus_basicos PASSED
testes/test_centralidade.py::test_volumes PASSED
testes/test_centralidade.py::test_risco_acumulado_por_ciclo PASSED
testes/test_centralidade.py::test_classificacao_hub_type PASSED
testes/test_centralidade.py::test_ordenacao_por_risk_score PASSED
testes/test_centralidade.py::test_grafo_vazio_retorna_lista_vazia PASSED
testes/test_cycle_detection.py::test_caso_base_ciclo_conhecido PASSED
testes/test_cycle_detection.py::test_dag_nao_possui_ciclos PASSED
testes/test_cycle_detection.py::test_grafo_apenas_com_vertices_isolados PASSED
testes/test_cycle_detection.py::test_grafo_completo_executa_e_encontra_ciclos PASSED
testes/test_cycle_detection.py::test_grafo_vazio_retorna_lista_vazia PASSED
testes/test_cycle_detection.py::test_prioridade_por_tipo_transacao PASSED
testes/test_cycle_detection.py::test_self_loop_e_um_ciclo PASSED
testes/test_exportador.py::test_secoes_obrigatorias_sempre_presentes PASSED
testes/test_exportador.py::test_secoes_opcionais_incluidas PASSED
testes/test_exportador.py::test_secoes_opcionais_ausentes PASSED
testes/test_exportador.py::test_save_analysis_cria_arquivo PASSED
testes/test_exportador.py::test_sanitize_name PASSED
testes/test_exportador.py::test_sem_sobrescrita PASSED
testes/test_exportador.py::test_estatisticas_corretas PASSED
testes/test_scc.py::test_ciclo_forma_scc_suspeito PASSED
testes/test_scc.py::test_grafo_vazio_retorna_lista_vazia PASSED
testes/test_scc.py::test_vertices_isolados_sao_sccs_individuais PASSED
testes/test_scc.py::test_dag_nao_tem_scc_suspeito PASSED
testes/test_scc.py::test_volume_interno_calculado_corretamente PASSED
testes/test_scc.py::test_dois_sccs_independentes PASSED
testes/test_scc.py::test_ordenacao_suspeitos_primeiro PASSED

27 passed in 0.XXs
```

---

## 6. Histórico de Commits

| Hash (7 chars) | Mensagem | Autor |
|----------------|----------|-------|
| `c843c30` | feat: cria estrutura base do MVP e arquivos de configuracao | Grupo 4 |
| `98112b5` | feat: implementa multigrafo direcionado ponderado em src/core | Grupo 4 |
| `2673df0` | feat: adiciona leitura de transacoes via CSV no formato PaySim | Grupo 4 |
| `6083338` | feat: implementa DFS para deteccao de ciclos suspeitos | Grupo 4 |
| `73211b8` | feat: cria CLI com telas de entrada e resultado | Grupo 4 |
| `a4cb14e` | test: adiciona testes unitarios para deteccao de ciclos | Grupo 4 |
| `bc67945` | docs: adiciona README e preenche template da E3 | Grupo 4 |
| `99d08aa` | refactor: renomeia pastas para PT-BR | Grupo 4 |
| `4ad65a2` | feat: integrate SCC, centrality, JSON storage and UI updates | Grupo 4 |
| `12232ad` | feat: integrate Sentinel AI fraud analysis assistant | Grupo 4 |

---

## 7. O que está funcionando / O que ainda falta

| Funcionalidade | Status | Observação |
|---------------|--------|------------|
| Multigrafo direcionado ponderado | ✓ Completo | Lista de adjacência com `Edge` tipado |
| DFS — detecção de ciclos | ✓ Completo | Retorna `CycleResult` com prioridade, perda e categoria |
| Centralidade de Grau | ✓ Completo | Risk score acumulado por ciclo (RN04), classificação hub_type |
| SCC — Kosaraju | ✓ Completo | Grupos suspeitos com volume interno e contagem de arestas |
| Leitura CSV (5 tipos) | ✓ Completo | TRANSFER, PAYMENT, CASH_OUT, CASH_IN, DEBIT |
| CLI com flags | ✓ Completo | `--centralidade`, `--scc`, `--export-json`, `--output` |
| Dashboard interativo | ✓ Completo | 3 layouts, badge de prioridade, 3 ciclos, 16 transações |
| Exportação JSON | ✓ Completo | Seções obrigatórias e opcionais, sem sobrescrita, histórico |
| Sentinel AI | ✓ Completo | Backend Flask + Google Gemini, dois modos de linguagem |
| Scripts de apresentação | ✓ Completo | `start_presentation.sh/.ps1` — inicia o sistema com um único comando |
| 27 testes unitários | ✓ Completo | 4 módulos cobertos com isolamento total |
| Upload de CSV externo pela interface | Pendente | Integração interface ↔ backend reservada para entrega futura |
| Análise em tempo real via API bancária | Pendente | Próxima etapa natural do roadmap de produto |

---

## Checklist de Entrega

- [x] Repositório público e acessível
- [x] .gitignore configurado (inclui `.env` e `dados/analises/*.json`)
- [x] README com instruções de execução completas (Python, CLI e interface)
- [x] Algoritmo principal (DFS) executando sem erros com CycleResult tipado
- [x] Algoritmos adicionais (Centralidade e SCC) implementados e testados
- [x] Telas demonstráveis: CLI (5 telas) e dashboard interativo com Sentinel AI
- [x] 27 testes unitários passando — 7 + 6 + 7 + 7
- [x] ≥ 5 commits com prefixos semânticos (feat:, fix:, test:, docs:, refactor:)
- [x] Arquivo de grafo de exemplo em `dados/` com 5 tipos de transação

---

*Teoria dos Grafos — Profa. Dra. Andréa Ono Sakai*
