# Diário de Sprint 4 — Análise de complexidade e redação final
**Período:** Semana 5
**Grupo / tema:** Grupo 1 — Pré-filtragem via DFA/CEP para redução de complexidade em busca de SCC (Kosaraju)

**Equipe:**
**Scrum Master do Sprint:**
**Repositório GitHub:** (link)

> Autômato integrado e benchmarkado na Sprint 3. Esta sprint **fecha o projeto**: análise formal de complexidade, confronto com os números empíricos, atualização do artigo/documentação metodológica e apresentação final. **Não há** sprint seguinte — esta é a entrega.

### Contrato desta sprint

| | Artefato | Origem / destino |
|---|---|---|
| **Entra** | Medições comparativas e checagem de corretude | Sprint 3 — **não gerar novos números sem justificar** |
| **Sai** | Análise formal de complexidade assintótica (pior caso), teórica vs. empírica | Entrega final |
| **Sai** | Atualização da seção metodológica/resultados do artigo (e PRISMA, se aplicável) | Entrega final |
| **Sai** | Ficha técnica do autômato + apresentação final | Entrega final / mostra |

**Não há sprint seguinte.**

- [ ] Confirmei que os números usados na análise são os da Sprint 3 (não refeitos sem registrar o porquê)

---

## 1. Análise de complexidade assintótica

- [ ] Complexidade do DFS/Kosaraju no pior caso, sem filtro, formalizada (notação O)
- [ ] Complexidade do DFA (processar o alfabeto de entrada) formalizada
- [ ] Complexidade do pipeline completo (DFA + Kosaraju/DFS condicional) formalizada
- [ ] Comparação explícita: em que condições o filtro reduz a complexidade no pior caso, e em que condições não ajuda

**Análise formal (com notação O):**

## 2. Comparação teórica x empírica

- [ ] Números da Sprint 3 confrontados com a análise teórica desta sprint
- [ ] Convergências e divergências discutidas (a redução observada bate com o esperado teoricamente?)

**Discussão teórica x empírica:**

## 3. Atualização do artigo / documentação metodológica

- [ ] Seção de metodologia do artigo atualizada com a especificação formal do DFA
- [ ] Seção de resultados atualizada com o benchmark e a análise de complexidade
- [ ] Revisão PRISMA atualizada, se aplicável ao escopo do grupo

**Trechos/links atualizados no artigo:**

## 4. Ficha técnica do autômato (model card simplificado)

| Campo | Conteúdo |
|---|---|
| Pergunta de pesquisa | |
| Especificação do DFA (Q, Σ, δ, q0, F) — link | |
| Dataset de teste usado | |
| Resultado do benchmark (resumo) | |
| Limitações conhecidas | |
| Como reproduzir (repositório/commit) | |

## 5. Apresentação final

- [ ] Roteiro da apresentação definido (problema → autômato → integração → resultados → conclusão)
- [ ] Material de apoio pronto (slides ou diagrama)

## 6. Scrum

- [ ] Atualizações assíncronas semanais registradas
- [ ] Board refletindo o backlog, em andamento e concluído

## 7. Diário de bordo (retrospectiva individual)

| Integrante | O que fiz nesta Sprint | Dificuldades | O que pretendo manter/ajustar |
|---|---|---|---|
| | | | |

---

## Rubrica de avaliação — Sprint 4 (nota de 0 a 4,0)

| Critério | Peso | O que caracteriza nota máxima | Nota atribuída | Observações |
|---|---|---|---|---|
| Análise de complexidade assintótica | 1,5 | Notação O correta para DFA, DFS/Kosaraju e pipeline completo; comparação clara | | |
| Comparação teórica x empírica | 1,0 | Confronto explícito com os dados da Sprint 3; divergências discutidas | | |
| Atualização do artigo e ficha técnica | 1,0 | Metodologia e resultados atualizados; ficha técnica completa | | |
| Apresentação final / Scrum + diário | 0,5 | Roteiro claro; board e diário atualizados | | |
| **Nota final da Sprint 4** | **4,0** | | **___ / 4,0** | |
