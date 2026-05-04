# E2 — Design Técnico, Arquitetura e Backlog

> **Disciplina:** Teoria dos Grafos  
> **Prazo:** 13 de abril de 2026  
> **Peso:** 20% da nota final  

---

## Identificação do Grupo

| Campo | Preenchimento |
|-------|---------------|
| Nome do projeto | |
| Repositório GitHub | |
| Integrante 1 | Caio Winkler Marangoni — 39968545 |
| Integrante 2 | Guilherme Lombardi — 38054264 |
| Integrante 3 | Ryan dos Santos Veloso — 37732005 |

---

## 1. Algoritmos Escolhidos

### 1.1 Algoritmo Principal

| Campo | Resposta |
|-------|----------|
| Nome do algoritmo | Busca em Profundidade (DFS) para detecção de ciclos |
| Categoria | Algoritmo de busca em grafos |
| Complexidade de tempo | O(V + E) |
| Complexidade de espaço | O(V) |
| Problema que resolve | Detecção de ciclos em grafos direcionados |

**Por que este algoritmo foi escolhido?**

O algoritmo de Busca em Profundidade (DFS) foi escolhido como principal devido à sua eficiência na detecção de ciclos em grafos direcionados, característica fundamental para identificar padrões suspeitos em redes de transações financeiras. Em cenários de fraude, ciclos representam fluxos fechados de capital, frequentemente associados a práticas de lavagem de dinheiro, onde valores são transferidos entre múltiplas contas com o objetivo de ocultar sua origem. Do ponto de vista computacional, o algoritmo apresenta complexidade de tempo O(V + E), onde V representa o número de vértices (contas) e E o número de arestas (transações). Essa complexidade linear torna o método escalável para grandes volumes de dados, como os presentes no dataset PaySim. 

A complexidade de espaço é O(V), pois o algoritmo necessita armazenar estruturas auxiliares como o vetor de visitados e a pilha de recursão. Além disso, a abordagem baseada em DFS permite fácil integração com sistemas de visualização, possibilitando destacar ciclos suspeitos diretamente na estrutura do grafo, o que contribui para a interpretabilidade dos resultados.

**Alternativa descartada e motivo:**

| Algoritmo alternativo | Motivo da exclusão |
|----------------------|-------------------|
| Algoritmo de Tarjan (SCC) | Embora identifique componentes fortemente conectados, não foca diretamente na detecção explícita de ciclos individuais, que são mais interpretáveis no contexto de fraude financeira. |

**Limitações no contexto do problema:**

Uma limitação do uso de DFS é a possibilidade de identificar ciclos que não necessariamente representam atividades fraudulentas, gerando falsos positivos. Dessa forma, o algoritmo deve ser complementado por outras métricas, como análise de centralidade e frequência de transações para aumentar a precisão da detecção.

**Referência bibliográfica:**

> CORMEN, Thomas H. et al. Algoritmos: teoria e prática. 3. ed. Rio de Janeiro: Elsevier, 2012.
> BRASIL. Banco Central do Brasil. Relatório de Economia Bancária 2023. Brasília: BCB, 2023.  
> BRASIL. Conselho de Controle de Atividades Financeiras (COAF). Relatório de Atividades 2023. Brasília: COAF, 2024.
---

### 1.2 Algoritmo Adicional 

| Campo | Resposta |
|-------|----------|
| Nome do algoritmo | Centralidade de Grau e Componentes Fortemente Conectados (SCC - Kosaraju) |
| Categoria | Métrica de análise de grafos / Algoritmo de decomposição de grafos |
| Complexidade de tempo | O(V + E) |
| Complexidade de espaço | O(V) |

**Justificativa:**

Os algoritmos adicionais foram escolhidos para complementar a detecção de ciclos realizada pelo DFS, permitindo uma análise mais abrangente da rede de transações financeiras. A centralidade de grau é utilizada para identificar vértices com alto número de conexões, tanto de entrada quanto de saída. No contexto do problema, essas contas podem representar "hubs financeiros", frequentemente associados à distribuição ou coleta de recursos em esquemas fraudulentos.

Já o algoritmo de Componentes Fortemente Conectados (SCC), implementado por meio do algoritmo de Kosaraju, permite identificar subgrafos onde todos os vértices são mutuamente alcançáveis. Esses componentes representam grupos de contas altamente interligadas, podendo indicar redes organizadas de fraude. Ambos os algoritmos possuem complexidade de tempo O(V + E), o que os torna adequados para análise de grandes redes de transações. A combinação dessas abordagens permite detectar não apenas ciclos isolados, mas também padrões estruturais mais complexos, aumentando a capacidade de identificação de comportamentos suspeitos.

**Referência bibliográfica:**

> NEWMAN, M. E. J. Networks: An Introduction. Oxford: Oxford University Press, 2018.
> BRASIL. Conselho de Controle de Atividades Financeiras (COAF). Relatório de Inteligência Financeira 2023. Brasília: COAF, 2024.  
> BANCO CENTRAL DO BRASIL. Relatório de Economia Bancária 2023. Brasília: BCB, 2023.
---

## 2. Arquitetura em Camadas

> Insira o diagrama abaixo. Pode ser exportado do Draw.io, Excalidraw, etc.

![Diagrama de arquitetura](./docs/arquitetura_e2.png)

### Descrição das camadas

| Camada | Responsabilidade | Artefatos principais |
|--------|-----------------|----------------------|
| Apresentação (UI/CLI) | Responsável pela interação com o usuário por meio de uma interface desenvolvida com Streamlit. Permite o carregamento do dataset PaySim, a configuração e execução das análises e a visualização dos resultados, incluindo a exibição gráfica do grafo e indicadores de fraude | Interface Streamlit, componentes de upload, botões de execução, exibição de resultados |
| Aplicação (Service) | Responsável por orquestrar o fluxo do sistema. Recebe as ações da interface, coordena a execução dos algoritmos e gerencia o fluxo de dados entre as camadas. Atua como intermediária entre a interface e a lógica de domínio | Serviços de execução, controladores, funções de orquestração |
| Domínio (Core) | Contém a lógica central do sistema e as regras de negócio. Inclui a modelagem do grafo como multigrafo dirigido e ponderado, além da implementação dos algoritmos de análise: detecção de ciclos via DFS, cálculo de centralidade de grau e identificação de componentes fortemente conectados (SCC) | graph.py, estruturas de dados, módulo algorithms/ (implementação dos algoritmos) |
| Infraestrutura (I/O) | Responsável pelo acesso e manipulação de dados externos. Realiza a leitura do dataset PaySim, tratamento e conversão dos dados para a estrutura utilizada no sistema. Também pode incluir persistência e integração com arquivos.| Leitura de arquivos CSV, parser de dados, carregamento e pré-processamento do dataset | 


---

## 3. Estrutura de Diretórios

```
nome-do-projeto/
├── docs/
│   ├── README.md
│   ├── E1_template.md
│   └── E2_template.md
├── src/
│   ├── core/
│   │   ├── graph.py
│   │   └── edge.py
│   ├── algorithms/
│   │   ├── dfs.py
│   │   ├── centrality.py
│   │   └── scc.py
│   ├── io/
│   │   └── file_reader.py
│   ├── ui/
│   │   └── app.py
│   └── main.py
├── tests/
│   ├── test_graph.py
│   └── test_algorithms.py
├── data/
└── requirements.txt
```

> **Justificativa de desvios**  

Essa separação foi necessária para manter a coerência com a arquitetura em camadas definida, garantindo o desacoplamento entre a interface e a lógica de negócio, além de facilitar a manutenção e evolução do sistema.

---

## 4. Definição do Dataset

**Formato de entrada aceito:**

<!-- JSON / CSV / GraphML / lista de adjacência — descreva a estrutura -->

Arquivo no formato CSV , baseado no dataset PaySim. O sistema utiliza um subconjunto dos atributos do dataset, considerando apenas os campos necessários para modelagem do grafo de transações.

**Atributos utilizados:**

| Campo | Descrição |
|------|----------|
| nameOrig | Conta de origem |
| nameDest | Conta de destino |
| amount | Valor da transação |
| isFraud | Indicador de fraude (para validação) |

**Mapeamento para o grafo:**

- Vértices: contas bancárias (`nameOrig`, `nameDest`)
- Arestas: transações financeiras
- Peso: valor da transação (`amount`)
- Direção: da conta de origem para a conta de destino

**Exemplo de estrutura do arquivo de entrada:**

```csv
step,type,amount,nameOrig,nameDest,isFraud
1,TRANSFER,9839.64,C1231006815,C4011234567,0
1,TRANSFER,1864.28,C1666544295,C4023456789,1
```

**Estratégia de geração aleatória:**

| Parâmetro | Descrição |
|-----------|-----------|
| Número de vértices | definido pelas contas únicas presentes no dataset |
| Densidade | determinada pela quantidade de transações registradas |
| Faixa de pesos | definida pelos valores reais das transações (amount) |

---

## 5. Backlog do Projeto

### 5.1 In-Scope — O que será implementado

| # | Funcionalidade | Prioridade | Critério de aceite |
|---|---------------|------------|-------------------|
| 1 | Leitura do dataset PaySim em formato CSV | Alta | Dado um arquivo CSV válido, quando carregado pelo sistema, então os dados são lidos e armazenados corretamente |
| 2 | Construção do grafo dirigido ponderado a partir dos dados | Alta | Dado o dataset carregado, quando processado, então um grafo com vértices e arestas consistentes é gerado |
| 3 | Detecção de ciclos utilizando DFS | Alta | Dado um grafo de transações, quando executado o algoritmo DFS, então ciclos existentes são identificados corretamente |
| 4 | Cálculo de centralidade de grau | Média | Dado um grafo, quando calculada a centralidade, então os vértices com maior grau são identificados |
| 5 | Identificação de componentes fortemente conectados (SCC) | Média | Dado um grafo, quando executado o algoritmo SCC, então grupos de vértices interconectados são retornados |
| 6 | Interface interativa com Streamlit | Alta | Dado o sistema em execução, quando acessado pelo usuário, então é possível carregar dados e executar análises |
| 7 | Visualização do grafo de transações | Alta | Dado um grafo processado, quando exibido, então sua estrutura é apresentada visualmente |
| 8 | Destaque de padrões suspeitos (ciclos, hubs e grupos) | Alta | Dado o resultado das análises, quando exibido, então elementos suspeitos são visualmente diferenciados |

### 5.2 Out-of-Scope — O que NÃO será feito

| Funcionalidade excluída | Motivo |
|------------------------|--------|
| Integração com sistemas bancários reais | Escopo acadêmico, sem acesso a dados reais |
| Implementação de modelo de IA para detecção automática | Fora do escopo inicial, previsto como evolução futura |
| Armazenamento persistente em banco de dados | Sistema focado em processamento em memória |
| Interface web completa com backend dedicado | Uso de Streamlit já atende aos requisitos do projeto |

---

## Checklist de Entrega

- [X] Big-O de tempo e espaço declarados para cada algoritmo
- [X] Ao menos 1 alternativa descartada com justificativa
- [X] Diagrama de arquitetura com 4 camadas identificadas
- [X] Referência bibliográfica para cada algoritmo (ABNT ou IEEE)
- [X] Backlog com ≥ 5 itens In-Scope e ≥ 3 Out-of-Scope
- [X] Ao menos 3 critérios de aceite no formato "dado / quando / então"
- [X] Exemplo de estrutura de arquivo de entrada presente

---

*Teoria dos Grafos — Profa. Dra. Andréa Ono Sakai*
