# Diário de Sprint 2 — Implementação do DFA/CEP
**Período:** Semana 2
**Grupo / tema:** Grupo 1 — Pré-filtragem via DFA/CEP para redução de complexidade em busca de SCC (Kosaraju)

**Equipe:**
**Scrum Master do Sprint:**
**Repositório GitHub:** (link)

> Esta sprint **implementa exatamente** a especificação formal do DFA definida na Sprint 1. **Não se muda** o conjunto de estados, o alfabeto ou a função de transição sem justificar e registrar a mudança. **Não há** integração com o DFS/Kosaraju nem benchmark de desempenho — isso é Sprint 3.

### Contrato desta sprint

| | Artefato | Origem / destino |
|---|---|---|
| **Entra** | Especificação formal do DFA (Q, Σ, δ, q0, F) + diagrama | Sprint 1 — **implementar exatamente esta especificação** |
| **Entra** | Dataset de teste selecionado | Sprint 1 |
| **Sai** | Código do autômato (tabela de transição ou motor CEP) | Sprint 3 (integração) |
| **Sai** | Testes unitários (casos aceitos/rejeitados) | Sprint 3 e 4 |
| **Sai** | Baseline sem filtro (DFS/Kosaraju "puro" já rodando e registrado) | Sprint 3 (comparação) |

**Não sai daqui:** integração do filtro no pipeline, medições comparativas, análise de complexidade.

- [ ] Confirmei que o código implementa a especificação da Sprint 1 sem alterações não documentadas

---

## 1. Implementação do autômato

- [ ] Estrutura de dados da tabela de transição (ou motor CEP) implementada
- [ ] Função de decisão (aceitar/rejeitar) implementada conforme F (estados de aceitação)
- [ ] Código organizado em módulo separado, reutilizável na Sprint 3
- [ ] Nome de estados/transições no código rastreável até o diagrama da Sprint 1

**Linguagem/framework usado e estrutura do código:**
**Evidências (link do repositório/commit):**

## 2. Testes unitários

- [ ] Casos de teste cobrindo: sequências aceitas, sequências rejeitadas, sequência vazia, sequência com símbolo fora do alfabeto
- [ ] Casos de borda dos exemplos manuais da Sprint 1 reproduzidos no código
- [ ] Todos os testes passando; falhas documentadas e corrigidas

**Tabela de casos de teste automatizados:**

| Caso | Entrada | Esperado | Resultado obtido | Passou? |
|---|---|---|---|---|

## 3. Validação da linguagem reconhecida

- [ ] Comparação entre a linguagem formal descrita na Sprint 1 e o comportamento observado no código
- [ ] Divergências encontradas documentadas e corrigidas (no código ou, se necessário, na especificação — com justificativa)

**Divergências encontradas e como foram resolvidas:**

## 4. Baseline sem filtro

- [ ] DFS/Kosaraju "puro" (sem o pré-filtro) rodando sobre o dataset de teste da Sprint 1
- [ ] Métricas do baseline registradas: nº de nós/arestas processados, tempo de execução, SCCs encontradas
- [ ] Esses números serão o "antes" no comparativo da Sprint 3

**Métricas do baseline sem filtro:**

## 5. Scrum

- [ ] Atualizações semanais no board
- [ ] Board refletindo o estado real

**Link do board:**

## 6. Diário de bordo (retrospectiva individual)

| Integrante | O que fiz nesta Sprint | Dificuldades | O que pretendo manter/ajustar |
|---|---|---|---|
| | | | |

---

## Rubrica de avaliação — Sprint 2 (nota de 0 a 4,0)

| Critério | Peso | O que caracteriza nota máxima | Nota atribuída | Observações |
|---|---|---|---|---|
| Implementação do autômato | 1,5 | Código fiel à especificação da Sprint 1, organizado e reutilizável | | |
| Testes unitários e validação da linguagem | 1,0 | Cobertura de casos aceitos/rejeitados/borda; divergências resolvidas | | |
| Baseline sem filtro preparado | 1,0 | DFS/Kosaraju puro rodando, métricas registradas | | |
| Scrum + diário de bordo | 0,5 | Board com histórico; diário reflexivo de todos | | |
| **Nota final da Sprint 2** | **4,0** | | **___ / 4,0** | |
