# Benchmark do processamento de eventos

Gerado por `python scripts/benchmark_eventos.py`, em execução isolada, com o servidor parado. Os números valem **para esta máquina e esta execução**; não são promessa de desempenho do sistema. O registro durável com fsync está ligado em todas as medições da API. Latências em ms (p50 / p95 / p99).

Ambiente: Windows-11-10.0.26200-SP0, 20 CPUs lógicas, Python 3.14.0, numpy 2.5.4, pandas 3.1.0, scikit-learn 1.9.1. Execução: 2026-11-06T09:47:31+00:00.

## O que cada medida é (e não é)

| medida | inclui | não inclui |
|---|---|---|
| **Aceitação HTTP** | pedido local, validação, gravação e fsync no registro, resposta 202 | previsão; a resposta só garante que o evento não se perde |
| **HTTP até a previsão gravada** | o anterior + fila, modelo e CSV | atualização visual do navegador (consulta periódica de 2 s por padrão) |
| **Processamento interno** | chegada ao serviço até a previsão gravada, sem HTTP | rede, parsing do pedido HTTP |
| **Modelo isolado** | `predict_proba` de uma linha | fila, registro, CSV, HTTP |
| **Vazão em lote** | eventos pré-normalizados em grupos, em processo, sem fsync por evento | HTTP e validação do pedido; **não é capacidade da API** |
| **Custo amortizado por transação** | tempo do minuto fechado ÷ transações do minuto | a espera pelo fechamento do minuto |
| **Espera pelo fechamento do minuto** | tempo até o minuto da transação poder fechar | é política, não custo: para eventos novos dura até o fim do minuto + atraso + carência |
| **RAM do estado** | working set de um processo novo depois de restaurar menos antes | histórico lido, previsões em memória |
| **Instantâneo** | tamanho em disco do arquivo | RAM: são medidas distintas, sem equivalência |

## Registro durável

| gravar 1 evento | p50 / p95 / p99 (ms) |
|---|---|
| com fsync (API) | 0,27 / 0,36 / 0,48 |
| sem fsync (replay: a fonte é o arquivo) | 0,15 / 0,22 / 0,29 |

## HTTP real (servidor local, sessão ativa, rede)

| medida | p50 / p95 / p99 (ms) |
|---|---|
| aceitação durável de 1 medição | 27,17 / 30,87 / 33,75 |
| 1 medição, do pedido até a previsão gravada | 46,03 / 52,34 / 69,13 |
| aceitação durável de um pedido com 100 medições (1 fsync) | 22,10 / 42,11 / 61,48 |

Um pedido por vez, sem carga concorrente. Não foi medida a capacidade HTTP sob carga.

## Modelo

| medida | valor |
|---|---|
| carga em processo novo (inclui importar bibliotecas) | p50 1.671 ms |
| leitura do joblib no mesmo processo | 382 ms e 378 ms |
| tamanho do artefato em disco | 36,9 MB |

## Rede (`estado_rede`), em processo

| medida | p50 / p95 / p99 (ms) | observação |
|---|---|---|
| primeira previsão após carregar | 34,54 | inclui aquecimento |
| modelo isolado, 1 medição | 18,92 / 21,89 / 25,91 | `CabecaClassificacao.probabilidades`; varia com a frequência da CPU |
| 1 medição com a tabela de saída | 23,20 / 28,94 / 32,34 | `tabela_previsoes_rede` |
| lote de 10 | 24,60 / 27,22 / 28,94 | 406 linhas/s no p50 (modelo, sem serviço) |
| lote de 100 | 31,24 / 36,98 / 47,77 | 3.201 linhas/s no p50 (modelo, sem serviço) |
| lote de 1000 | 49,20 / 51,29 / 56,44 | 20.327 linhas/s no p50 (modelo, sem serviço) |
| processamento interno, 1 medição por vez | 34,03 / 44,73 / 48,83 | `submeter` com fsync + fila + modelo + CSV, sem HTTP |
| vazão em lote do trabalhador | — | 10.199 eventos/s (46105 medições em 4,5 s); eventos pré-normalizados, em processo, sem HTTP e sem fsync por evento |
| latência durante essa vazão | 1.336,34 / 1.389,02 / 1.397,97 | a fila saturada domina: esse p99 não combina com a latência de carga baixa |

Recuperação só pelo registro, sem instantâneo: 46105 eventos reaplicados em 2,3 s (19.754 eventos/s); 46105 linhas na saída.

## Financeiro (`lavagem`, estado incremental)

Histórico: 4.868.912 transações do HI-Small anteriores a 10/09/2022; dia reproduzido: 208.325 transações de 10/09/2022 em 1.440 minutos.

| medida | valor | tipo |
|---|---|---|
| leitura do HI-Small (.zip) | 6,1 s | carga |
| carga inicial do estado (vetorizada) | 2,8 s | carga |
| atributos de um minuto fechado | 1,77 / 2,19 / 4,94 ms | por minuto |
| atributos + score de um minuto fechado | 7,80 / 8,81 / 13,09 ms | por minuto; sem a espera para fechar, HTTP nem persistência |
| custo amortizado por transação | 0,06 / 0,07 / 0,07 ms | minuto ÷ transações; o minuto tem p50 de 135 transações |
| vazão em lote (atributos + score, sem serviço) | 17.981 transações/s | 11,6 s no dia |
| replay pelo serviço, velocidade máxima | 11.204 transações/s | registro + fila + modelo + CSV; 18,6 s, inclui ler o arquivo |
| chegada → previsão gravada nesse replay | 2.370,78 / 2.466,85 / 2.471,75 ms | fila saturada |
| chegada → previsão gravada a 2.000 eventos/s | 43,59 / 74,44 / 81,19 ms | inclui a espera pelo minuto, no tempo do replay |
| mesmo dia em lote (`atributos_financeiros`, CLI) | 6,0 s | só atributos |
| caminho antigo: UMA transação nova relendo o histórico | 5,6 s, 5,4 s | por transação |

**Espera pelo fechamento do minuto (eventos novos).** Não é custo de processamento, e por isso não entra no custo por minuto: uma transação fica no minuto aberto até chegar um evento de minuto posterior ou até o relógio passar do fim do minuto + atraso permitido + carência (padrão: até cerca de 62 s). Em uma API com eventos do minuto corrente, a previsão financeira leva, portanto, da ordem de um minuto.

### RAM e disco (medidas distintas)

| medida | valor |
|---|---|
| RAM do estado com o histórico, restaurado em processo novo | 285 MB (300 → 585 MB de working set) |
| instantâneo em disco depois da carga: tamanho / gravar / restaurar | 166,1 MB / 0,2 s / 0,3 s |
| instantâneo em disco no fim do dia: tamanho / gravar | 242,3 MB / 0,3 s |
| pico de working set do processo deste benchmark | 2.785 MB (inclui histórico, lote e força bruta; não é o custo do serviço) |

### Crescimento do estado ao longo do dia

| minuto (UTC) | contas | pares | eventos nas janelas de 72 h | working set (MB) |
|---|---|---|---|---|
| 2022-09-10T00:00:00Z | 515.088 | 996.797 | 1.620.653 | 1.171 |
| 2022-09-10T06:00:00Z | 515.088 | 1.007.097 | 1.552.238 | 1.183 |
| 2022-09-10T12:00:00Z | 515.088 | 1.010.260 | 1.483.748 | 1.184 |
| 2022-09-10T18:00:00Z | 515.088 | 1.012.537 | 1.413.716 | 1.193 |
| 2022-09-10T23:59Z | 515.088 | 1.015.069 | 1.345.904 | 1.213 |

### Equivalência no dia 10/09/2022

> **Medição de 06/11/2026, anterior à correção do lote.** Em 09/11/2026, as somas acumuladas do cálculo em lote passaram a recomeçar em cada conta, e as diferenças abaixo deixaram de existir: o lote corrigido fica abaixo de 1e-6 de erro contra a força bruta (`docs/ml/hi_large/RELATORIO_HI_LARGE.md`, seção 3.4).

Incremental × lote. 208.325 linhas: 45 de 49 colunas idênticas.

| coluna | dif. absoluta máx. | dif. relativa máx. | linhas com dif. relativa > 1e-6 |
|---|---|---|---|
| `soma_env_origem_usd_24h` | 2 | 0.000582 | 4651 |
| `z_valor_origem` | 1.53e-05 | 2.28e-07 | 0 |
| `soma_rec_origem_usd_24h` | 0.5 | 0.000163 | 2470 |
| `razao_saida_entrada_24h` | 111 | 0.000582 | 5104 |

Força bruta (`testes/ml/referencia_financeira.py`) em 350 linhas (as 150 com maior diferença de razão entre lote e incremental, entre 5104 divergentes, mais 200 aleatórias):

- incremental: maior erro relativo por coluna acima de 1e-6 = nenhum;
- lote: {'soma_env_origem_usd_24h': 0.0005820838602195862, 'soma_rec_origem_usd_24h': 0.00016304850578308105, 'razao_saida_entrada_24h': 0.0005820838602195862};
- `razao_saida_entrada_24h`: erro relativo máximo 0 no incremental e 0.000582 no lote.

Efeito nos scores: diferença absoluta máxima 8.33e-17 (3502 linhas com score diferente); alertas (limiar 0.0910): 328 no incremental, 328 no lote, 0 mudam de lado.

O dia 10/09/2022 pertence ao período de teste. Aqui ele só mede tempo e equivalência numérica; nada foi ajustado com ele. Qualidade preditiva continua sendo a da avaliação oficial.

## Execuções anteriores

As medições de 03/11/2026 (cerca de 15,6 mil eventos/s no trabalhador; 32 ms em baixa carga) são **históricas**: foram feitas antes do registro durável e não valem para esta versão. Entre execuções há variação grande sem mudança de código: atributos + score por minuto fechado tiveram p50 de 15,4 ms em 03/11/2026 e de 7,8 ms em 06/11/2026.
