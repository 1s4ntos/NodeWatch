# Diário de Sprint 1 — Formalização do autômato
**Período:** Semana 1
**Grupo / tema:** Grupo 1 — Pré-filtragem via DFA/CEP para redução de complexidade em busca de SCC (Kosaraju)

**Equipe:**
**Integrantes:**
**Scrum Master do Sprint:**
**Repositório GitHub:** (link)

> Esta sprint **só formaliza o problema e o autômato** (pergunta de pesquisa, alfabeto, diagrama de estados, linguagem reconhecida) e seleciona o dataset de teste. **Não há** implementação de código, integração com o DFS/Kosaraju nem benchmark — isso é Sprint 2 e 3. O algoritmo de grafo (DFS/Kosaraju) **não é escolhido nem alterado** aqui: ele já existe no sistema.

### Contrato desta sprint

| | Artefato | Quem usa depois |
|---|---|---|
| **Entra** | RFC do Grupo 1 (nada de sprint anterior) | — |
| **Sai** | Canvas de kickoff + pergunta de pesquisa fechada | Sprint 2, 3 e 4 |
| **Sai** | Especificação formal do DFA (5-tupla Q, Σ, δ, q0, F) + diagrama de estados | Sprint 2 **é obrigada a implementar exatamente esta especificação** |
| **Sai** | Dataset de teste selecionado (grafo de transações + SCCs fraudulentas conhecidas / ground truth) | Sprint 3 (benchmark) |
| **Sai** | Repositório, board, este diário | Sprints seguintes |

**Não sai daqui:** código do autômato, integração com DFS/Kosaraju, medições de desempenho.

---

## 1. Canvas de kickoff

| Pergunta | Resposta |
|---|---|
| Qual é a pergunta de pesquisa? | Em que medida a integração de um DFA/CEP como camada de pré-filtragem reduz o volume de nós e arestas processados pelo algoritmo de Kosaraju/DFS, mantendo em zero a taxa de exclusão de Componentes Fortemente Conectados (SCCs) e ciclos verdadeiramente fraudulentos? |
| Qual é o alfabeto de entrada (Σ) do autômato (categorias de eventos de transação)? | Σ = {NORM}, {HIGH_VAL}, {RAPID_SEQ}.{NORM}: Transação de valor e canal habituais (ex.: PAYMENT, DEBIT, CASH_IN com amount dentro da média histórica). {HIGH_VAL}: Transação de alto valor ou de canal crítico para layering (ex.: TRANSFER ou CASH_OUT excedendo o limiar atípico). {RAPID_SEQ}: Transação realizada em janela de tempo curta em relação ao evento anterior (step <= 1h) entre nós da mesma vizinhança no grafo.  |
| O que o autômato decide ao aceitar/rejeitar um subgrafo? | Aceitar (Estado de Aceitação "F" atingido): A sequência de eventos forma um padrão suspeito de layering ou smurfing; a janela de transações/subgrafo é encaminhada para processamento denso via Kosaraju/DFS no NodeWatch. Rejeitar: A sequência é classificada como fluxo transacional normal; o subgrafo é descartado antes do cálculo de ciclos e componentes. |
| Qual é o custo de um falso negativo (SCC fraudulenta descartada) e de um falso positivo (subgrafo aceito sem padrão suspeito)? | Falso Negativo (FN): Custo CRÍTICO / ALTO. A rejeição incorreta de um subgrafo pelo autômato impede que uma rede de fraude real seja analisada pelo Kosaraju/DFS, resultando em perda financeira irreversível. Falso Positivo (FP): Custo BAIXO / MÉDIO. A aceitação incorreta força a execução do Kosaraju/DFS em um subgrafo sem fraude, gerando apenas overhead computacional descartável. Conexão com o Desenho do Autômato: Devido à assimetria dos custos, a função de transição δ e os estados de aceitação (F) do DFA foram projetados sob uma filosofia conservadora. Diante de ambiguidades na sequência de eventos de entrada, o autômato transita por padrão para o estado de aceitação, garantindo recall de $100 sobre as SCCs fraudulentas (eliminação de FNs) em troca de um volume tolerável de FPs. |
| Justificativa: por que um DFA/CEP é uma abordagem formal adequada para este pré-filtro? | Porque permite filtrar eventos em tempo real com complexidade temporal O(1) por evento recebido no stream, evitando a execução do algoritmo denso O(V+E) do Kosaraju/DFS em 100% do grafo global. Além disso, a teoria de autômatos oferece garantias matemáticas formais de reconhecimento de linguagens regulares que heurísticas genéricas não oferecem.|

- [x] Pergunta de pesquisa escrita sem ambiguidade
- [x] Alfabeto de entrada definido e justificado
- [x] Custo de FN/FP explicitado e ligado ao desenho do autômato (conservador em caso de dúvida)

## 2. Especificação formal do DFA

- [x] Conjunto de estados (Q) definido, com significado de cada estado
- [x] Alfabeto (Σ) coerente com o canva da seção 1
- [x] Função de transição (δ) completa (tabela de transição)
- [x] Estado inicial (q0) e estados de aceitação (F) definidos
- [x] Diagrama de estados desenhado
- [x] Linguagem regular / expressão regular reconhecida pelo autômato descrita em português e formalmente

**Tabela de transição (δ):**

| Estado | Símbolo de entrada | Próximo estado |
|---|---|---|
| q0 | NORM | q0 |
| q0 | HIGH_VAL | q1 |
| q0 | RAPID_SEQ | q1 |
| q1 | NORM | q0 |
| q1 | HIGH_VAL | q2 |
| q1 | RAPID_SEQ | q2 |
| q2 | NORM | q1 |
| q2 | HIGH_VAL | q3 |
| q2 | RAPID_SEQ | q3 |
| q3 | NORM | q3 |
| q3 | HIGH_VAL | q3 |
| q3 | RAPID_SEQ | q3 |


**Q =** {q0,q1,q2,q3} - Conjunto finito de estados.
**Σ =** {NORM,HIGH_VAL,RAPID_SEQ} - Alfabeto de entrada.
**q0 =** Estado inicial.
**F =** {q3} - Conjunto de estados de aceitação.
δ: Q x Σ -> Q: Função de transição total de estados.

**Linguagem reconhecida (descrição formal):**
A linguagem reconhecida pelo autômato, L(M), é constituída por todas as sequências de eventos de transações financeiras que contenham uma densidade crítica de operações atípicas (operações de valor elevado ou em rajada temporal curta). Concretamente, aceita qualquer sequência na qual ocorram três eventos críticos (HIGH_VAL ou RAPID_SEQ) acumulados com no máximo uma transação comum (NORM) de amortecimento intermediária entre eles. Uma vez atingido esse padrão de layering ou smurfing, a sequência é aceita e marcada para processamento pelo algoritmo de Kosaraju/DFS.

**Evidências (diagrama, link do documento/commit):**

## 3. Seleção do dataset de teste

- [x] Dataset (grafo de transações) identificado e sua origem documentada
- [x] SCCs fraudulentas conhecidas (ground truth) listadas ou localizadas no dataset
- [x] Tamanho do grafo (nós/arestas) registrado, para dimensionar o benchmark da Sprint 3

**Origem do dataset e N (nós/arestas):**
Origem e Fonte: Dataset sintético PaySim (base simulada de transações financeiras P2P e mobile money). Para a fase de desenvolvimento e validação do filtro, utiliza-se o arquivo estruturado dados/exemplo_transacoes.csv.

Atributos Utilizados: step (tempo em horas), type (tipo da operação: TRANSFER, PAYMENT, CASH_OUT, CASH_IN, DEBIT), amount (valor em R$), nameOrig (vértice origem), nameDest (vértice destino) e isFraud (rótulo binário).

Tamanho do Grafo de Referência (MVP Base):
*Vértices (V / Contas): 15 contas bancárias.
*Arestas (E / Transações): 16 transações financeiras mapeadas como multigrafo dirigido. 

Dimensionamento para o Benchmark da Sprint 3: O pipeline da Sprint 3 utilizará uma escala expandida da base PaySim variando de 1.000 a 10.000+ arestas, permitindo medir empiricamente o tempo de execução e a redução percentual no processamento de nós/arestas antes e depois da adição do autômato.

**Ground truth de SCCs fraudulentas (onde estão, quantas são):**

Mapeamento e Deteção: O ground truth é delimitado pela junção dos rótulos isFraud = 1 do dataset com o mapeamento estrutural dos ciclos de layering/smurfing validados pelo algoritmo de Kosaraju no NodeWatch.

Distribuição e Quantidade no Grafo de Teste (3 SCCs Suspeitas Conhecidas):

SCC #1 (Grupo de Risco 1 — 4 contas):
*Contas envolvidas: C011, C012, C013, C014.  
*Métricas: 4 arestas internas, Volume interno total de R$ 30.800,00.   
*Padrão: Ciclo fechado de layering de prioridade alta (C011 -> C012 -> C013 -> C014 -> C011). 

SCC #2 / #8 (Grupo de Risco 2 — 3 contas):
*Contas envolvidas: C001, C002, C003.   
*Métricas: 4 arestas internas, Volume interno total de R$ 30.300,00.   
*Padrão: Ciclo de transferências sucessivas e concentradas (C001 -> C002 -> C003 -> C001).   

SCC #3 / #5 (Grupo de Risco 3 — 3 contas):
*Contas envolvidas: C006, C007, C008.   
*Métricas: 3 arestas internas, Volume interno total de R$ 8.850,00.   
*Padrão: Estrutura cíclica de menor volume (C006 -> C007 -> C008 -> C006).   

*Vértices Isolados/Legítimos: 5 contas fora de estruturas fortemente conectadas.   
*Critério de Validação do Autômato: O autômato deve obrigatoriamente aceitar qualquer subgrafo que englobe as 10 contas pertencentes a estas 3 SCCs fraudulentas conhecidas, garantindo taxa zero de falsos negativos (FN = 0) no benchmark.

## 4. Prova de conceito manual

- [x] Autômato executado "na mão" (sem código) em pelo menos 3 exemplos: 1 caso claramente aceito, 1 claramente rejeitado, 1 caso de borda
- [x] Resultado de cada caso confrontado com a expectativa (o desenho do autômato faz sentido?)

**Tabela de casos manuais:**

| Caso | Sequência de entrada | Estado final | Aceito/Rejeitado | Esperado? |
|---|---|---|---|---|
|1. Padrão Suspeito (Layering/Smurfing)|[NORM, HIGH_VAL, HIGH_VAL, RAPID_SEQ]|q3|Aceito|Sim,Acúmulo claro de eventos críticos.|
|2. Fluxo Comercial Legítimo |[NORM, NORM, HIGH_VAL, NORM, NORM, HIGH_VAL]|q1|Rejeitado|Sim,Transações isoladas de alto valor espaçadas no tempo|
|3. Caso de Borda (Resfriamento Intermediário)|[HIGH_VAL, RAPID_SEQ, NORM, RAPID_SEQ]|q2|Rejeitado| Sim, Transação comum intercalada reduz o estado de alerta.|


## 5. Scrum

- [x] Papéis definidos (Product Owner = docente; Scrum Master do sprint; Development Team)
- [x] Board criado (GitHub Projects ou Trello) com To do / Doing / Done
- [x] Backlog inicial com pelo menos 3 user stories

**User stories do backlog inicial:**
1. Especificação Formal do DFA (Pré-Filtro CEP) - História: Como analista de engenharia do sistema NodeWatch, eu quero uma especificação formal do DFA (5-tupla Q, Σ, δ, q0, F, diagrama de estados e tabela de transição δ), para que o motor de filtragem reconheça sequências de layering/smurfing de forma previsível e sem ambiguidades.

Critérios de Aceite:
*Tabela de transição δ preenchida para todas as combinações Q x Σ
*Diagrama de estados vetorial atualizado na documentação.
*Validação da prova de conceito manual em pelo menos 3 casos (aceito, rejeitado e borda).

2. Implementação do Módulo de Filtragem DFA/CEP sobre Stream PaySim - História: Como desenvolvedor do sistema, eu quero implementar a classe Python do autômato determinístico integrada à camada de infraestrutura/leitura de CSV, para que as transações do dataset PaySim sejam avaliadas em tempo real (O(1) por evento) antes da construção completa do grafo em memória.

Critérios de Aceite:
*Módulo Python implementado em src/algoritmos/automato.py ou src/leitura/.
*Suporte aos símbolos NORM, HIGH_VAL e RAPID_SEQ mapeados a partir de amount, type e step.
*Bateria de testes unitários automatizados em testes/test_automato.py cobrindo transições e estados de aceitação.

3. Pipeline de Integração e Benchmark Comparativo (DFA + Kosaraju/DFS) - Como pesquisador do projeto, eu quero conectar a saída do filtro DFA à execução dos algoritmos de Kosaraju e DFS no NodeWatch, para que seja possível medir a redução percentual no volume de nós/arestas processados e validar se a taxa de falsos negativos permanece zerada (FN = 0). 

Critérios de Aceite:

*Pipeline integrado executando a comparação automática (com filtro vs. sem filtro).
*Relatório de benchmark gerado com contagem de nós, arestas, tempo de execução e SCCs preservadas.
*Confirmação de que as 3 SCCs fraudulentas do ground truth continuam sendo 100% detectadas.

**Link do board:**

## 6. Diário de bordo (retrospectiva individual)

| Integrante | O que fiz nesta Sprint | Dificuldades | O que pretendo manter/ajustar |
|---|---|---|---|
|Guilherme Lombardi|Atuou como Scrum Master na Sprint 1; liderou a especificação formal do DFA (5-tupla, tabela de transições $\delta$, diagrama e linguagem regular) e a definição do Canvas de Kickoff|Equilibrar as regras do autômato de forma conservadora para zerar falsos negativos sem gerar um volume excessivo de falsos positivos.|Manter: Liderança ativa na condução das etapas formais da documentação. Ajustar: Refinar o detalhamento técnico das tarefas de código da Sprint 2. |
|Caio Winkler Marangoni|Realizou a análise do dataset PaySim, correlacionando os atributos de entrada (type, amount, step) ao alfabeto Σ e catalogando as 3 SCCs do ground truth.|Definir os limiares numéricos exatos para classificar transações como HIGH_VAL ou RAPID_SEQ sem ambiguidades.|Manter: Rigor na validação e preparação das bases de teste. Ajustar: Documentar os scripts auxiliares de leitura de dados no repositório. |
|Ryan dos Santos Veloso|Conduziu a prova de conceito manual ("na mão") nos 3 cenários do autômato (aceito, rejeitado e borda) e estruturou o board no GitHub Projects.|Rastrear o resfriamento de estado no caso de borda para confirmar se a transição refletia a regra conservadora.|Manter: Foco no isolamento e mapeamento de casos de teste.
Ajustar: Antecipar a estrutura dos testes unitários automatizados em PyTest para a próxima sprint.|
|Guilherme Liborio|Avaliou a arquitetura em 4 camadas do NodeWatch para planejar o encaixe da nova camada de CEP/DFA antes da execução do Kosaraju/DFS.|Mapear o ponto de interceptação do stream sem afetar o desempenho da estrutura de multigrafo já existente.|Manter: Visão sistêmica da arquitetura do NodeWatch. Ajustar: Realizar alinhamentos técnicos focados antes da escrita do código na Sprint 2.|

## 7. Evidências gerais

- Link do canvas/RFC atualizado:
- Link da especificação formal do DFA:
- Link de commits desta Sprint:
- Link do board atualizado:

---

## Rubrica de avaliação — Sprint 1 (nota de 0 a 4,0)

| Critério | Peso | O que caracteriza nota máxima | Nota atribuída | Observações |
|---|---|---|---|---|
| Canvas e pergunta de pesquisa | 0,5 | Pergunta sem ambiguidade; alfabeto e custo de FN/FP explícitos | | |
| Especificação formal do DFA | 1,5 | 5-tupla completa, diagrama de estados, linguagem reconhecida bem descrita | | |
| Dataset de teste selecionado | 1,0 | Origem documentada, ground truth localizado, N registrado | | |
| Scrum + diário de bordo | 1,0 | Papéis, board, backlog e diário reflexivo de todos | | |
| **Nota final da Sprint 1** | **4,0** | | **___ / 4,0** | |
