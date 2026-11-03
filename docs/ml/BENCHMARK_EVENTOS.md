# Benchmark do processamento de eventos

Gerado por `python scripts/benchmark_eventos.py`. Os números valem **para esta máquina e esta execução**; não são promessa de desempenho do sistema. Latências em ms (p50 / p95 / p99).

Ambiente: Windows-11-10.0.26200-SP0, 20 CPUs lógicas, Python 3.14.0, numpy 2.5.4, pandas 3.1.0, scikit-learn 1.9.1. Execução: 2026-11-03T03:37:06+00:00.

## Modelo

| medida | valor |
|---|---|
| carga em processo novo (inclui importar bibliotecas) | p50 1.961 ms |
| leitura do joblib no mesmo processo | 620 ms e 596 ms |
| tamanho do artefato | 36,9 MB |

## Rede (`estado_rede`)

| medida | p50 / p95 / p99 (ms) | observação |
|---|---|---|
| primeira previsão após carregar | 62,34 | inclui aquecimento |
| uma medição, só o modelo | 18,86 / 22,42 / 24,48 | `CabecaClassificacao.probabilidades` |
| uma medição, com a tabela de saída | 23,83 / 27,15 / 28,60 | `tabela_previsoes_rede` |
| lote de 10 | 25,19 / 28,59 / 29,60 | 397 linhas/s no p50 |
| lote de 100 | 31,27 / 33,90 / 35,83 | 3.198 linhas/s no p50 |
| lote de 1000 | 49,22 / 52,00 / 53,25 | 20.316 linhas/s no p50 |
| serviço, uma medição por vez (chegada → previsão gravada) | 31,77 / 41,48 / 42,76 | fila + trabalhador + CSV |
| serviço, vazão máxima | — | 15.605 eventos/s (46105 medições em 3,0 s); latência sob saturação 2.668,24 / 2.791,78 / 2.861,95 |

## Financeiro (`lavagem`, estado incremental)

Histórico: 4.868.912 transações do HI-Small anteriores a 10/09/2022; dia reproduzido: 208.325 transações de 10/09/2022 em 1.440 minutos.

| medida | valor |
|---|---|
| leitura do HI-Small (.zip) | 8,4 s |
| carga inicial do estado (vetorizada) | 4,5 s |
| memória do processo (working set) antes / depois da carga do estado | 1.554 / 1.029 MB (o Windows devolve páginas liberadas depois da leitura do .zip, então a diferença não mede o estado; o tamanho do instantâneo é a melhor aproximação) |
| pico de memória do processo no benchmark | 2.775 MB (inclui histórico, lote e força bruta) |
| instantâneo após a carga: gravar / restaurar / tamanho | 0,3 s / 0,5 s / 166,1 MB |
| instantâneo no fim do dia: gravar / tamanho | 0,7 s / 242,3 MB |
| transações por minuto no dia | p50 135, p99 628, máx. 664 |
| atributos por minuto fechado (ms) | 2,99 / 4,42 / 7,69 |
| atributos + score por minuto fechado (ms) | 15,41 / 20,43 / 24,45 |
| custo por transação (minuto ÷ transações, ms) | 0,12 / 0,15 / 0,17 |
| vazão do dia (atributos + score) | 9.163 transações/s (22,7 s no total) |
| mesmo dia em lote (`atributos_financeiros`, caminho da CLI) | 9,7 s |
| caminho antigo: UMA transação nova relendo o histórico | 8,6 s, 7,0 s |

### Crescimento do estado ao longo do dia

| minuto (UTC) | contas | pares | eventos nas janelas de 72 h | memória (MB) |
|---|---|---|---|---|
| 2022-09-10T00:00:00Z | 515.088 | 996.797 | 1.620.653 | 1.165 |
| 2022-09-10T06:00:00Z | 515.088 | 1.007.097 | 1.552.238 | 1.178 |
| 2022-09-10T12:00:00Z | 515.088 | 1.010.260 | 1.483.748 | 1.196 |
| 2022-09-10T18:00:00Z | 515.088 | 1.012.537 | 1.413.716 | 1.187 |
| 2022-09-10T23:59Z | 515.088 | 1.015.069 | 1.345.904 | 1.208 |

### Equivalência no dia 10/09/2022

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

Efeito nos scores: diferença absoluta máxima 5.55e-17 (3947 linhas com score diferente); alertas (limiar 0.0910): 328 no incremental, 328 no lote, 0 mudam de lado.

O dia 10/09/2022 pertence ao período de teste. Aqui ele só mede tempo e equivalência numérica; nada foi ajustado com ele.
