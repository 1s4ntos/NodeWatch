# RFC: Proposta de Projeto — Grupo 1

| Campo | Valor |
|---|---|
| **Título** | Pré-filtragem via Autômato Finito Determinístico (DFA/CEP) para redução de complexidade em busca de SCC (Kosaraju) — detecção de fraude em tempo real |
| **Trilha** | Extensão de sistema existente — camada de Autômatos Finitos (DFA/CEP) sobre grafo de transações |
| **Equipe** | Grupo 1 |
| **Autores** | |
| **Status** | Rascunho |
| **Data** | |
| **Sprint de referência** | 1 |

> Este RFC formaliza a incorporação de Autômatos Finitos Determinísticos (DFA), operando como Complex Event Processing (CEP), ao sistema de detecção de fraude já existente (arquitetura híbrida, revisão PRISMA 2020, artigo científico). **O algoritmo denso de grafo (DFS/Kosaraju) já está definido** — o que este projeto decide é o **desenho formal do autômato** (alfabeto, estados, transições) que atua como pré-filtro. Não é escopo redesenhar o modelo de ML nem a arquitetura de detecção downstream.

---

## 1. Resumo (TL;DR)

O projeto formaliza e implementa um DFA/CEP que pré-filtra o grafo de transações antes da busca de Componentes Fortemente Conectados (Kosaraju/DFS), com o objetivo de reduzir o número de nós/arestas processados no pior caso, sem descartar SCCs fraudulentas reais, e mede empiricamente esse ganho para o artigo científico do grupo.

---

## 2. Contexto e motivação

A arquitetura híbrida de detecção de fraude já processa grafos de transações com algoritmos densos (DFS, Kosaraju) para achar SCCs suspeitas — computacionalmente caros em grafos grandes. A hipótese de pesquisa é que uma camada leve, baseada em autômato finito, consegue descartar previamente subgrafos "obviamente não suspeitos", reduzindo a complexidade assintótica no pior caso sem perder verdadeiros positivos (fraudes).

---

## 3. Problema formal e pergunta de pesquisa

| Pergunta | Resposta |
|---|---|
| Pergunta de pesquisa | Em que medida um DFA/CEP como pré-filtro reduz o nº de nós/arestas processados pelo DFS/Kosaraju, sem descartar SCCs fraudulentas relevantes? |
| Linguagem regular reconhecida pelo autômato | Sequência de eventos de transação que caracteriza um padrão suspeito preliminar (ex.: sequência de transações de alto valor entre poucos nós, em curto intervalo de tempo) — **a definir formalmente na Sprint 1** |
| Alfabeto de entrada (Σ) | Eventos de transação categorizados (tipo, faixa de valor, canal, intervalo de tempo etc.) |
| Decisão do autômato | Aceitar → subgrafo segue para DFS/Kosaraju; Rejeitar → subgrafo é descartado do processamento denso |

---

## 4. Escopo

| Pergunta | Resposta |
|---|---|
| Dentro do escopo | Formalizar o DFA (5-tupla), implementar como filtro de pré-processamento, medir impacto em nº de nós/arestas antes do Kosaraju/DFS, benchmark comparativo com/sem filtro, checar preservação de corretude (nenhuma SCC fraudulenta conhecida é descartada) |
| Fora de escopo | Re-treinar/alterar o modelo de ML de fraude, mudar a arquitetura de detecção downstream, deploy em produção/tempo real, otimizar o próprio Kosaraju/DFS |

> O algoritmo de grafo (DFS/Kosaraju) **não muda** — o produto do grupo é o autômato e a prova de que ele ajuda.

---

## 5. Usuários e decisão apoiada

O pipeline de detecção de fraude (equipe de engenharia de dados do sistema já existente) usa o filtro para decidir **quais subgrafos valem o custo de rodar Kosaraju/DFS completo**, em vez de aplicar a busca densa a todo o grafo.

---

## 6. Dados e fontes

| Fonte | O que fornece | Papel no projeto |
|---|---|---|
| Dataset de transações já usado no artigo (real ou sintético) | Grafo dirigido de transações | Entrada para o autômato e para o DFS/Kosaraju |
| SCCs fraudulentas conhecidas (ground truth do artigo) | Casos positivos de referência | Validação de que o filtro não perde fraudes reais |

---

## 7. Custo dos erros do filtro

| Tipo de erro | O que significa | Custo/consequência |
|---|---|---|
| Falso negativo (DFA rejeita subgrafo que continha SCC fraudulenta real) | Fraude não é detectada | Alto — é o erro que o projeto mais quer evitar |
| Falso positivo (DFA aceita subgrafo sem padrão suspeito) | Custo computacional extra no Kosaraju/DFS | Baixo/médio — só reduz o ganho de desempenho |

O autômato deve ser desenhado de forma **conservadora** (tende a aceitar em caso de dúvida), já que o falso negativo é o erro mais grave.

---

## 8. Abordagem proposta (visão de alto nível)

grafo bruto de transações → definição formal da linguagem regular do padrão suspeito → construção do DFA (5-tupla + diagrama de estados) → implementação do DFA/CEP sobre o stream de eventos → integração como filtro antes do DFS/Kosaraju → medição comparativa (nós/arestas processados, tempo, SCCs encontradas) com e sem filtro → análise de complexidade assintótica no pior caso (teórica vs. empírica) → atualização da seção metodológica do artigo.

Não há escolha de algoritmo de ML nem redesenho do pipeline de detecção neste projeto — o entregável é o autômato e sua avaliação.

---

## 9. Riscos e limitações conhecidas

- Dataset de teste pequeno demais para conclusões estatísticas robustas
- Autômato mal calibrado descartando SCCs fraudulentas válidas
- Complexidade de rodar CEP sobre stream real dentro do prazo
- Tempo curto para uma prova formal (não só empírica) da redução assintótica

---

## 10. Critérios de sucesso

- Autômato formalmente especificado (5-tupla Q, Σ, δ, q0, F) e diagramado
- Filtro implementado, testado e integrado antes do DFS/Kosaraju
- Benchmark demonstrando redução mensurável de nós/arestas processados
- Nenhuma SCC fraudulenta conhecida (ground truth) perdida no teste
- Seção metodológica/resultados do artigo atualizada com os achados

---

## 11. Alternativas consideradas *(opcional)*

Outras formas de pré-filtragem (ex.: heurísticas ad hoc, amostragem aleatória) avaliadas e descartadas por não terem garantias formais equivalentes às de um autômato.

---

## 12. Perguntas em aberto

- O limiar exato do que conta como "padrão suspeito preliminar" (depende da EDA do grafo na Sprint 1/2)
- Se o ganho de desempenho compensa a complexidade de manter o CEP em stream (avaliar no benchmark da Sprint 3)

---

## 13. Cronograma e contrato entre sprints

| Sprint | Período | Produz (sai) | A próxima sprint é obrigada a usar |
|---|---|---|---|
| 1 | Semana 1 | Definição formal do DFA (5-tupla), diagrama de estados, linguagem regular do padrão suspeito, dataset de teste selecionado | Essa especificação formal, sem alterações |
| 2 | Semana 2 | Implementação do DFA/CEP, testes unitários (casos aceitos/rejeitados), validação da linguagem reconhecida | O autômato implementado e já testado |
| 3 | Semanas 3–4 | Pipeline integrado (DFA como filtro antes do DFS/Kosaraju), medições comparativas (nós/arestas, tempo, SCCs), checagem de corretude | Os resultados experimentais desta sprint |
| 4 | Semana 5 | Análise formal de complexidade (pior caso, teórica vs. empírica), atualização do artigo (metodologia + resultados), apresentação final | — (entrega final) |

---

## 14. Histórico de revisões

| Versão | Data | Autor | O que mudou |
|---|---|---|---|
| v0.1 | | | Primeira versão do RFC (Sprint 1) |
| | | | |
