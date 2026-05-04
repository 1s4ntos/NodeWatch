# E1 — Proposta e Definição do Projeto

> **Disciplina:** Teoria dos Grafos  
> **Prazo:** 16 de março de 2026  
> **Peso:** 10% da nota final  

---

## Identificação do Grupo

| Campo | Preenchimento |
|-------|---------------|
| Nome do projeto | Sistema de Detecção de Fraudes em Transações Financeiras |
| Integrante 1 | Caio Winkler Marangoni — 39968545 |
| Integrante 2 | Guilherme Lombardi — 38054264 |
| Integrante 3 | Ryan dos Santos Veloso — 37732005 |
| Domínio de aplicação | Sistemas financeiros / detecção de fraudes |

---

## 1. Contexto e Motivação

> Descreva o problema do mundo real que será abordado. Por que ele é relevante?  
> *Orientação: 2 a 3 parágrafos. Seja específico — evite generalizações.*

O cenário atual de transações financeiras digitais apresenta um desafio de escalabilidade para sistemas de monitoramento convencionais. O volume massivo de operações P2P (person-to-person) cria brechas para táticas de ocultação de patrimônio, como o "smurfing" (fragmentação de depósitos), que visam burlar limites de conformidade e detecção manual.

O problema reside na identificação de fluxos indiretos que, isoladamente, parecem legítimos, mas que revelam padrões de lavagem de dinheiro quando mapeados estruturalmente. A análise puramente relacional (tabelas) falha ao tentar identificar conexões de muitos saltos devido à alta complexidade computacional de sucessivos *joins*.

Neste projeto, o foco será a análise *post-hoc* de transações suspeitas, utilizando grafos para reduzir a complexidade da busca por ciclos e caminhos ocultos entre contas.

---

## 2. Objetivo Geral

> O que o sistema deve ser capaz de fazer ao final?  
> *Orientação: 1 frase clara e objetiva. Ex.: "O sistema deve calcular a rota de menor custo entre dois pontos em um mapa urbano."*

O sistema deve ser capaz de analisar transações financeiras e identificar padrões suspeitos associados a possíveis fraudes utilizando modelagem em grafos.

---

## 3. Objetivos Específicos

> Desmembre o objetivo geral em metas mensuráveis.  
> *Orientação: liste entre 3 e 5 itens. Cada item deve ser verificável — use verbos como "implementar", "calcular", "exibir", "carregar".*

- [ ] Implementar a modelagem de transações utilizando o dataset sintético **PaySim** para garantir verossimilhança nos testes.
- [ ] Modelar a rede como um **Multigrafo Direcionado**, permitindo a persistência de múltiplas transações entre os mesmos vértices.
- [ ] Desenvolver algoritmos de detecção de ciclos baseados em DFS para identificar fluxos fechados de capital.
- [ ] Aplicar métricas de centralidade para ranquear contas com comportamento atípico de "hub" financeiro.
- [ ] Exibir visualmente a rede, destacando arestas que compõem padrões de fraude confirmados pelo dataset.
---

## 4. Público-Alvo / Caso de Uso Principal

> Para quem ou em qual cenário o sistema seria utilizado?  
> *Orientação: descreva um cenário concreto de uso. Ex.: "Um entregador de aplicativo que precisa otimizar a sequência de entregas em um bairro."*

O sistema é destinado a instituições financeiras e equipes de análise de risco, sendo aplicado no monitoramento de transações bancárias. Um cenário de uso envolve analistas que necessitam identificar rapidamente padrões suspeitos em grandes volumes de dados financeiros, auxiliando na detecção de possíveis fraudes e atividades ilícitas.

---

## 5. Justificativa Técnica — Por que Grafos?

> Por que a modelagem em grafo é a abordagem mais adequada para este problema?  
> *Orientação: explique quais elementos do problema mapeiam naturalmente para vértices e arestas. Mencione se há pesos, direção, ou restrições que reforçam a escolha.*

A modelagem em grafos é a abordagem mais adequada pois permite representar relações complexas de forma nativa. Enquanto sistemas tradicionais sofrem com latência ao processar múltiplos saltos entre contas, a estrutura de grafos permite percorrer essas conexões em tempo linear $O(V + E)$.

Diferente de um grafo simples, utilizaremos um **Multigrafo Ponderado**. Isso é fundamental porque o peso (valor da transação) e a frequência (múltiplas arestas) são metadados críticos: dez transferências de R$ 1.000 entre as mesmas contas em um curto intervalo são muito mais suspeitas do que uma única transferência de R$ 10.000.as.

---

## 6. Tipo de Grafo

> Especifique as características do grafo que o problema requer.

| Característica | Escolha | Justificativa breve |
|----------------|---------|---------------------|
| Tipo de Grafo | Multigrafo Dirigido | Permite representar cada transação individual como uma aresta entre contas. |
| Ponderação | Ponderado | O peso da aresta será o valor (`amount`) da transação presente no PaySim. |
| Conectividade | Geral (SCCs) | Focaremos em Componentes Fortemente Conectados para achar núcleos de fraude. |
| Representação | Lista de Adjacência | Mais eficiente para a memória em grafos esparsos como redes financeiras. |
---

## 7. Diagrama Conceitual

> Insira aqui ao menos uma figura que ilustre o domínio do problema.  
> *Pode ser uma imagem exportada do Draw.io, Excalidraw, foto de esboço à mão etc.*  

![Diagrama de Grafos](<ciclo_suspeito_de_transacoes.png>).

**Legenda:** 
Os vértices representam contas bancárias e as arestas direcionadas representam transferências financeiras entre contas. O sentido da aresta indica o fluxo do dinheiro.
---

## Checklist de Entrega

Antes de submeter, confirme:

- [x] Texto entre 300 e 600 palavras (seções 1 a 5)
- [x] Todos os campos da tabela de identificação preenchidos
- [x] Tipo de grafo especificado com justificativa
- [x] Diagrama presente e referenciado no texto
- [x] Arquivo nomeado como `E1_DetecçãoFraudesEmTransaçõesFinanceirasGrupo4_Grafos.docx` (versão Word) ou PR aberto (versão GitHub)

---

*Teoria dos Grafos — Profa. Dra. Andréa Ono Sakai*
