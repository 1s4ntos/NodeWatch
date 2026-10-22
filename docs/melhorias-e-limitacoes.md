# Melhorias, avaliação no dataset IBM AML e limitações

Este documento registra o que foi alterado no NodeWatch nesta etapa, como foi verificado, os resultados da avaliação com o dataset IBM AML (HI-Small), as limitações conhecidas e os pontos que precisam ser definidos antes de treinar um modelo de ML.

> **Como ler os números:** todos os resultados abaixo vêm de execuções locais em recortes do dataset. Valores marcados como *sintético* foram medidos com dados gerados para teste, não com o dataset real. Nenhum resultado deve ser lido como desempenho em produção (veja [Limitações](#limitações)).

## Sumário

1. [Resumo](#resumo)
2. [O que mudou](#o-que-mudou)
3. [Como foi verificado](#como-foi-verificado)
4. [Desempenho](#desempenho)
5. [Como reproduzir a avaliação](#como-reproduzir-a-avaliação)
6. [Resultados](#resultados)
7. [Limitações](#limitações)
8. [Definições necessárias para o ML](#definições-necessárias-para-o-ml)
9. [Próximos passos](#próximos-passos)
10. [Referências](#referências)

---

## Resumo

- O **SCC** e a **detecção de ciclos** foram otimizados sem alterar nenhum resultado (a saída é idêntica à anterior nos grafos de teste). Antes, 20 mil transações levavam 17 s no SCC e 75 s nos ciclos; agora 50 mil transações levam 0,11 s e 0,17 s (recortes diferentes, ver [Desempenho](#desempenho)).
- O grafo passou a guardar o **tempo** das transações (`Edge.step`, opcional), o que permitiu criar um **detector de fan-out e fan-in** por janela de tempo.
- Foram criados scripts para **converter** o dataset da IBM, **avaliar** os detectores e **explorar** os padrões e as contas.
- Em um recorte de 50 mil transações, SCC/ciclos e fan-out/fan-in **somados** sinalizam cerca de **35% das transações rotuladas como lavagem**, com precisão de 65 a 69% nesse recorte. A precisão está inflada pela forma de montar o recorte.
- Três dos oito padrões do dataset (STACK, RANDOM, BIPARTITE) são **pouco cobertos**, e cerca de metade das lavagens rotuladas não pertence a nenhum padrão descrito pela IBM.

## O que mudou

### Código do projeto (`src/`)

| Arquivo | Tipo | Mudança |
|---|---|---|
| `src/algoritmos/scc.py` | alterado | `_enrich_components` passou de O(C × E) para O(V + E), com uma única passagem pelas arestas. Resultado idêntico. |
| `src/algoritmos/cycle_detection.py` | alterado | (1) a DFS só percorre arestas internas a cada SCC; (2) a DFS é iterativa, o que elimina o `RecursionError` em caminhos longos; (3) o mapa de arestas é montado uma vez e reutilizado em todos os ciclos. Conjunto de ciclos e ordem final idênticos. |
| `src/grafo/graph.py` | alterado | `Edge` e `add_edge` ganham o campo opcional `step` (padrão `None`). Código existente não é afetado. |
| `src/leitura/file_reader.py` | alterado | Lê a coluna `step` quando existe. Se faltar ou for inválida, fica `None` (comportamento tolerante, como antes). |
| `src/algoritmos/fan_detection.py` | **novo** | `find_fan_patterns`: detecta contas que enviam para (fan-out) ou recebem de (fan-in) pelo menos *k* contas distintas em uma janela de tempo, com filtro opcional de hubs. |

### Testes (`testes/`)

| Arquivo | Conteúdo |
|---|---|
| `test_escala.py` | 6 testes: ciclo longo (3.000 contas) sem `RecursionError`, volume interno do SCC com arestas entre componentes, self-loop dentro de um SCC, parte acíclica, ciclos em componentes diferentes. |
| `test_fan_detection.py` | 16 testes: fan-out e fan-in, janela de tempo, destinos repetidos, self-loops, filtro de hubs, parâmetros inválidos e leitura de `step`. |

Total: **49 testes** (eram 27).

### Scripts (`scripts/`)

| Script | Função |
|---|---|
| `converter_ibm_aml.py` | Converte o CSV da IBM para o formato do NodeWatch. Modos de recorte `inicio` e `ilicitas`; `--pular-ilicitas` gera um recorte de validação. |
| `benchmark.py` | Mede tempo de leitura, SCC e ciclos (com limite de tempo) e a qualidade contra o rótulo do dataset. |
| `analise_por_padrao.py` | Revocação por tipo de padrão (arquivo de padrões da IBM) e conferência entre o CSV e o arquivo de padrões. |
| `benchmark_fan.py` | Varre os parâmetros do detector de fan; `--combinar` compara SCC/ciclos, fan e a união. |
| `explorar_conta.py` | Compara transações de lavagem e normais de uma conta de origem. |
| `caracterizar_padroes.py` | Descreve a estrutura de cada tipo de padrão e o teto de revocação por tentativa. |

### Não alterado

CLI (`src/main.py`), API e assistente (`src/sentinel_ai.py`), interface web, exportador JSON e centralidade. **O detector de fan ainda não está integrado à CLI nem ao dashboard**; hoje é usado pelos scripts.

## Como foi verificado

- **Equivalência das otimizações:** a saída do SCC (inclusive ordem e valores de volume), o conjunto de ciclos e a ordem final por prioridade e valor foram comparados com o código anterior em **73 grafos** de teste (com self-loops, arestas paralelas e vários tipos de transação), com duas sementes de hash diferentes. Todos idênticos.
- **CLI:** a saída de `main.py --scc --centralidade` ficou idêntica antes e depois da mudança em `Edge`/`file_reader`.
- **Testes novos:** 5 dos 6 testes de `test_escala.py` também passam no código original (descrevem comportamento que já existia); o do ciclo longo falha nele com `RecursionError`, o que confirma a correção.
- **Dados reais:** a avaliação no dataset da IBM foi executada localmente (resultados abaixo).

## Desempenho

| Cenário | Antes | Depois | Origem da medida |
|---|---|---|---|
| 5 mil transações, SCC | 1,11 s | — | dataset IBM (início do arquivo) |
| 20 mil transações, SCC / ciclos | 17,04 s / 74,78 s | — | dataset IBM (início do arquivo) |
| 50 mil transações, SCC / ciclos | — | 0,11 s / 0,17 s | dataset IBM (recorte `ilicitas`) |
| 10 mil transações, SCC | 14,07 s | 0,05 s | *sintético* |
| 1 milhão de transações + ciclo de 5.000 contas | não terminou em 120 s | SCC 20 s, ciclos 30 s | *sintético* |

Os recortes "antes" e "depois" do dataset real são diferentes (início do arquivo × `ilicitas`), então a comparação direta é aproximada; as linhas sintéticas comparam o mesmo grafo antes e depois.

**Limite que permanece:** enumerar *todos* os ciclos dentro de um componente muito grande continua exponencial (regra RN02 do projeto). Em um grafo sintético com um componente de 5.625 contas a etapa de ciclos ainda excedeu 120 s. Para *marcar* transações suspeitas o SCC já basta e é rápido; a enumeração serve para explicar o caminho.

## Como reproduzir a avaliação

Pré-requisito: baixar `HI-Small_Trans.csv` e `HI-Small_Patterns.txt` do dataset "IBM Transactions for Anti Money Laundering (AML)" (Kaggle) para `dados/`. **Não versionar esses arquivos** (veja `.gitignore`).

```bash
# 1) Testes
python -m pytest                                  # esperado: 49 passed

# 2) Recorte de avaliação (contas com lavagem + vizinhança)
python scripts/converter_ibm_aml.py -i dados/HI-Small_Trans.csv -o dados/ibm_50k.csv \
    --modo ilicitas --max-ilicitas 1000 --max-linhas 50000

# 3) Desempenho e qualidade de SCC/ciclos
python scripts/benchmark.py -i dados/ibm_50k.csv --timeout 120

# 4) Revocação por padrão e conferência CSV x padrões
python scripts/analise_por_padrao.py -i dados/ibm_50k.csv -p dados/HI-Small_Patterns.txt

# 5) Detector de fan-out/fan-in e comparação com SCC/ciclos
python scripts/benchmark_fan.py -i dados/ibm_50k.csv -p dados/HI-Small_Patterns.txt \
    --k 5 6 8 --janela 168 240 336 --max-hub 20 30 50 --combinar

# 6) Validação com sementes diferentes (configuração fixa)
python scripts/converter_ibm_aml.py -i dados/HI-Small_Trans.csv -o dados/ibm_val_50k.csv \
    --modo ilicitas --pular-ilicitas 3000 --max-ilicitas 1000 --max-linhas 50000
python scripts/benchmark_fan.py -i dados/ibm_val_50k.csv -p dados/HI-Small_Patterns.txt \
    --k 8 --janela 336 --max-hub 20 --combinar

# 7) Estrutura dos padrões e exploração de contas
python scripts/caracterizar_padroes.py -p dados/HI-Small_Patterns.txt
python scripts/explorar_conta.py -i dados/HI-Small_Trans.csv --conta 070-100428660
```

### Conversão do dataset

- O arquivo original tem a coluna `Account` **duas vezes** (origem e destino); o conversor trata isso por posição.
- Identificador da conta: `BANCO-CONTA` (a conta sozinha não é única entre bancos).
- `step` = horas desde a primeira transação do arquivo.
- `isFraud` = `Is Laundering` (**rótulo de lavagem**, não de fraude em geral).
- Tipos de pagamento mapeados para os do NodeWatch (escolha de modelagem, em `MAPA_TIPOS`): ACH, Wire, Bitcoin → `TRANSFER`; Cash → `CASH_OUT`; Cheque, Credit Card → `PAYMENT`; Reinvestment → `CASH_IN`.
- Autotransferências (conta → ela mesma) são **removidas por padrão** (591.212 no arquivo completo), porque no dataset são majoritariamente legítimas e escondem os ciclos entre contas diferentes. `--manter-autotransferencias` as mantém (o NodeWatch as classifica como `ANOMALIA`).

### Métricas usadas

- **Precisão:** das transações sinalizadas, quantas estão rotuladas como lavagem.
- **Revocação:** das transações rotuladas como lavagem, quantas foram sinalizadas.
- **Por padrão:** calculada **por par de contas** (origem, destino), não por tentativa e sem comparar valor ou horário. Tentativas grandes pesam mais que as pequenas.

## Resultados

Recorte `ilicitas` de 50 mil transações: 24.974 contas, 1.729 transações rotuladas como lavagem (3,5%).

### SCC e ciclos

| Métrica | Valor |
|---|---|
| Componentes suspeitos / maior | 19 / 15 contas |
| Ciclos entre contas | 88 |
| Precisão / revocação (transações) | 92,4% / 16,9% |

SCC e ciclos sinalizam exatamente as mesmas transações (toda aresta dentro de um SCC está em algum ciclo). O SCC basta para marcar; os ciclos servem para explicar.

O teste anterior, com 10 mil transações (818 lavagens), deu 95,8% de precisão e 16,7% de revocação: a revocação é estável ao aumentar o recorte.

### Os padrões do dataset

Estrutura das 370 tentativas de lavagem do arquivo de padrões (`caracterizar_padroes.py`; medianas por tentativa):

| Padrão | Tentativas | Transações | Contas | Grau saída / entrada máx. | Pedaços | Observação |
|---|---|---|---|---|---|---|
| CYCLE | 54 | 4 | 4 | 1 / 1 | 1 | sempre contém ciclo |
| GATHER-SCATTER | 51 | 14 | 15 | 6 / 7 | 1 | 27% contêm ciclo |
| BIPARTITE | 49 | 4 | 8 | 1 / 1 | 4 | transferências isoladas |
| FAN-OUT | 48 | 7 | 8 | 7 / 1 | 1 | sem ciclo |
| SCATTER-GATHER | 44 | 14 | 9 | 7 / 7 | 1 | 30% contêm ciclo |
| STACK | 43 | 10 | 15 | 1 / 1 | 5 | cadeias curtas; 33% contêm ciclo |
| RANDOM | 41 | 3 | 4 | 1 / 1 | 1 | caminho simples |
| FAN-IN | 40 | 8 | 9 | 1 / 8 | 1 | sem ciclo |

BIPARTITE é formado por transferências isoladas entre pares de contas (sem conta central, ciclo ou caminho): **não há estrutura de grafo para detectar**. STACK e RANDOM são cadeias curtas, testáveis por um detector de cadeias (ainda não implementado).

### Detector de fan-out/fan-in

- **Sem filtro de hubs é inutilizável:** sinaliza cerca de 90% das transações, com precisão de 0,2% a 1,7%, porque contas de altíssimo volume contactam muitas contas distintas o tempo todo.
- Com filtro de hubs (≤ 20, 30 ou 50 contrapartes no recorte) e janelas de 168 a 336 h, o F1 fica entre 0,26 e 0,29. **Os parâmetros importam pouco**; o que muda é o equilíbrio entre precisão e revocação (k=8 e hub ≤ 20: ~60% / ~19%; k=5 e hub ≤ 50: ~31% / ~23%).
- Configuração usada nas comparações: `k = 8`, janela de 336 h, hubs ≤ 20.

### União dos detectores e validação

Configuração fixa (k=8, 336 h, hub ≤ 20), duas amostras com sementes diferentes:

| Detector | Recorte 1 (precisão / revocação) | Validação (precisão / revocação) |
|---|---|---|
| SCC/ciclos | 92,4% / 16,9% | 96,3% / 19,9% |
| Fan | 58,2% / 19,1% | 50,0% / 18,0% |
| **União** | **69,3% / 34,6%** | **65,0% / 34,9%** |

Cobertura da união por padrão (por par de contas):

| Padrão | Recorte 1 | Validação |
|---|---|---|
| CYCLE | 92% | 94% |
| FAN-IN | 92% | 94% |
| FAN-OUT | 83% | 90% |
| GATHER-SCATTER | 95% | 79% |
| SCATTER-GATHER | 88% | 78% |
| RANDOM | 44% | 50% |
| BIPARTITE | 15% | 26% |
| STACK | 12% | 16% |

Os resultados gerais se mantêm entre as duas amostras; as porcentagens por padrão variam de 10 a 15 pontos (poucos pares por padrão, entre 80 e 180).

### Lavagens que nenhum padrão descreve

Das 1.729 transações rotuladas, **849 (49%)** têm o par de contas no arquivo de padrões (todas `TRANSFER`) e **880 (51%)** não têm (`PAYMENT` 516, `TRANSFER` 256, `CASH_OUT` 108). O NodeWatch (SCC) sinaliza 34% das primeiras e 1% das segundas.

As 880 se concentram em poucas contas de altíssimo volume (3 origens somam 430). Em duas delas:

| Conta | Transações como origem | Rotuladas como lavagem | Destinos distintos |
|---|---|---|---|
| `070-100428660` | 168.672 | 243 (0,14%) | 14.230 |
| `070-1004286A8` | 103.018 | 158 (0,15%) | 8.846 |

Nas duas, a taxa de lavagem é parecida em todos os formatos de pagamento (0,11% a 0,17%), as medianas de valor de lavagem e normais ficam na mesma faixa e quase nenhum destino é de ocorrência única (0% contra 0,4 a 0,5%). **Com os campos disponíveis, não há sinal que separe a lavagem do uso normal dessas contas.**

## Limitações

**Sobre os dados**

1. **O dataset é sintético** (simulador AMLworld, da IBM). Os resultados não demonstram desempenho em dados reais.
2. **O recorte `ilicitas` é enviesado de propósito:** é montado em torno de contas com lavagem, então tem ~3,5% de lavagem contra ~0,115% no arquivo inteiro (5.166 em 4,49 milhões de transações convertidas). A **precisão aparece otimista**. Estimativa grosseira, assumindo que a taxa de falsos positivos medida (~0,7%) se mantivesse: a precisão do fan no dataset inteiro ficaria perto de 3%. Isso é uma conta de ordem de grandeza, não uma medida.
3. **A validação é parcial:** usa sementes diferentes (outro período), mas as vizinhanças podem se sobrepor e o recorte é montado da mesma forma.
4. **Valores em moedas diferentes:** o conversor usa `Amount Paid` sem a moeda (a coluna de moeda é descartada), e o dataset mistura franco suíço, libra, peso, rupia, rublo etc. Os valores não são comparáveis entre linhas, e o dataset não traz taxas de câmbio.
5. **O rótulo é de lavagem (`Is Laundering`),** e 51% das transações rotuladas não pertencem a nenhum padrão descrito. O motivo dessa diferença não foi determinado.

**Sobre a avaliação**

6. **Revocação por par de contas, não por tentativa.** O teto por tentativa depende de *k*: a mediana do grau máximo é 7 no FAN-OUT e 8 no FAN-IN, então com k=8 ao menos metade das tentativas de FAN-OUT não pode ser detectada, e os 71 a 78% por par do fan (83 a 90% na união) superestimam a revocação por tentativa.
7. **Parâmetros escolhidos no mesmo recorte em que foram avaliados** (36 combinações no primeiro teste); as diferenças entre as melhores são pequenas, então a "melhor" configuração não é significativamente melhor que as vizinhas.
8. **O limite de hubs é relativo ao recorte:** conta as contrapartes dentro do recorte, que são só uma fração das reais. O mesmo valor se comporta diferente em outro tamanho de recorte.
9. **A associação padrão–transação ignora valor e horário** (só o par de contas).

**Sobre os detectores**

10. **Cobertura:** STACK, RANDOM e BIPARTITE são pouco cobertos (a união pega entre 12% e 50% dos pares). Em contas de altíssimo volume nada do que foi medido separa lavagem de uso normal.
11. **Falsos positivos em dados reais:** lojas e folhas de pagamento se parecem com hubs; o filtro de hubs ajuda, mas o valor adequado precisa ser reavaliado em cada base.
12. **A enumeração de ciclos continua exponencial** dentro de componentes muito grandes (veja [Desempenho](#desempenho)).
13. **Autotransferências removidas na conversão** por decisão de modelagem; a comparação com `--manter-autotransferencias` não foi feita.

## Definições necessárias para o ML

Pontos a decidir e documentar **antes** de treinar, porque os dados atuais têm armadilhas:

1. **Unidade de predição:** transação, conta ou tentativa? Os detectores trabalham por conta e janela; o rótulo é por transação.
2. **Rótulo:** é de lavagem, e metade das transações rotuladas não tem padrão. Pode haver um teto de desempenho para modelos que usem só os campos atuais.
3. **Desbalanceamento:** ~0,1% de positivos no dataset inteiro. Usar precisão-revocação, revocação nos *k* maiores escores; não usar acurácia.
4. **Vazamento de dados:** SCC, ciclos e contrapartes calculados no arquivo inteiro usam transações do futuro. Calcular as características apenas com o que existia até cada instante.
5. **Divisão treino/teste:** por **tempo** ou por grupos de contas, não por sorteio de transações (as mesmas contas se repetem entre tentativas).
6. **Não treinar no recorte `ilicitas`:** a distribuição não é a real. Usar um recorte que preserve a proporção original (por exemplo, todas as transações de uma janela de tempo).
7. **Moeda:** manter a moeda como coluna e normalizar os valores (precisa de tabela de câmbio externa) ou usá-la como característica.
8. **Características candidatas já produzidas pelo projeto:** pertencer a ciclo ou SCC (e o tamanho), centralidade, número de contrapartes em janelas de tempo, número total de contrapartes (separa pico de atividade de hub) e valor total.

## Próximos passos

- Dicionário de dados (`docs/dicionario-de-dados.md`): cada coluna, origem, significado e risco de vazamento.
- Normalização de moedas e preservação da moeda na conversão.
- (Opcional) Detector de cadeias para STACK e RANDOM, avaliado com o mesmo benchmark; o resultado, mesmo negativo, entra neste documento.
- Integrar o detector de fan à CLI e ao dashboard.
- Reavaliar com recortes que preservem a proporção real de lavagem.
- Limitar a enumeração de ciclos em componentes grandes (decisão sobre a regra RN02).

## Referências

- Dataset: *IBM Transactions for Anti Money Laundering (AML)*, no Kaggle (versões HI/LI e Small/Medium/Large; usada: HI-Small).
- Artigo do simulador: *Realistic Synthetic Financial Transactions for Anti-Money Laundering Models* (arXiv:2306.16424).
