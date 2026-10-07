# Diário de Sprint 3 — Integração e benchmark
**Período:** Semanas 3–4
**Grupo / tema:** Grupo 1 — Pré-filtragem via DFA/CEP para redução de complexidade em busca de SCC (Kosaraju)

**Equipe:**
**Scrum Master do Sprint:**
**Repositório GitHub:** (link)

> Autômato formalizado (Sprint 1) e implementado/testado (Sprint 2). Esta sprint **integra** o autômato como filtro antes do DFS/Kosaraju e **mede** o ganho, comparando sempre com o baseline sem filtro da Sprint 2. **Não há** análise formal de complexidade assintótica nem redação do artigo — isso é Sprint 4.

### Contrato desta sprint

| | Artefato | Origem / destino |
|---|---|---|
| **Entra** | Autômato implementado e testado | Sprint 2 — **não reescrever do zero** |
| **Entra** | Baseline sem filtro (métricas) | Sprint 2 |
| **Sai** | Pipeline integrado (autômato como filtro antes do DFS/Kosaraju) | Sprint 4 |
| **Sai** | Medições comparativas (com/sem filtro) | Sprint 4 (análise de complexidade) |
| **Sai** | Checagem de corretude (nenhuma SCC fraudulenta perdida) | Sprint 4 |

**Não sai daqui:** análise formal de complexidade assintótica, atualização do artigo, model card.

- [ ] Confirmei que o autômato usado é exatamente o da Sprint 2 (ou uma versão ajustada e documentada)

---

## 1. Integração do filtro

- [ ] Autômato conectado ao pipeline: cada subgrafo passa primeiro pelo DFA antes de (eventualmente) ir para o DFS/Kosaraju
- [ ] Subgrafos rejeitados são de fato descartados do processamento denso (não só logados)
- [ ] Pipeline documentado (diagrama simples do fluxo: entrada → DFA → Kosaraju/DFS ou descarte)

**Descrição da integração:**
**Evidências (link do commit/notebook):**

## 2. Medições comparativas

- [ ] Nº de nós/arestas processados pelo DFS/Kosaraju, com e sem filtro
- [ ] Tempo de execução, com e sem filtro
- [ ] SCCs encontradas, com e sem filtro
- [ ] Execução repetida (mais de uma rodada) se houver variação de tempo

**Tabela comparativa:**

| Métrica | Sem filtro (baseline S2) | Com filtro (DFA) | Redução (%) |
|---|---|---|---|
| Nós processados | | | |
| Arestas processadas | | | |
| Tempo de execução | | | |
| SCCs encontradas | | | |

**Interpretação dos resultados:**

## 3. Checagem de corretude

- [ ] Todas as SCCs fraudulentas conhecidas (ground truth da Sprint 1) ainda são encontradas com o filtro ativo
- [ ] Se alguma foi perdida: caso analisado, causa identificada, autômato ajustado e re-testado
- [ ] Falsos positivos do filtro (subgrafos aceitos sem padrão suspeito) quantificados

**SCCs perdidas (se houver) e ajustes feitos:**
**Falsos positivos do filtro (quantidade e exemplos):**

## 4. Sprint Review — checkpoint intermediário

**Incremento demonstrado ao PO (docente):**
**Feedback recebido:**

## 5. Scrum

- [ ] Atualizações assíncronas semanais registradas
- [ ] Board refletindo o estado real da Sprint

## 6. Diário de bordo (retrospectiva individual)

| Integrante | O que fiz nesta Sprint | Dificuldades | O que pretendo manter/ajustar |
|---|---|---|---|
| | | | |

---

## Rubrica de avaliação — Sprint 3 (nota de 0 a 4,0)

| Critério | Peso | O que caracteriza nota máxima | Nota atribuída | Observações |
|---|---|---|---|---|
| Integração do filtro | 1,0 | Pipeline funcionando de ponta a ponta, fluxo documentado | | |
| Medições comparativas | 1,5 | Tabela completa, execução repetida, interpretação consistente | | |
| Checagem de corretude | 1,0 | Ground truth conferido; perdas (se houver) investigadas e corrigidas | | |
| Sprint Review / Scrum + diário | 0,5 | Incremento demonstrado; board e diário atualizados | | |
| **Nota final da Sprint 3** | **4,0** | | **___ / 4,0** | |
