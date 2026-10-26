# Dicionário de dados e contratos

Gerado de `src/ml/esquemas.py` (`python -m src.ml.cli documentar`). `verificado` = conferido nos dados pela auditoria; `inferido` = deduzido do nome e da distribuição, sem documentação da construção original.

## `rede_v1`

Uma linha por medição de um fluxo sonda→âncora. O alvo é o estado da PRÓXIMA medição do mesmo fluxo (intervalo mediano de 240 s, irregular).

| coluna | tipo | papel | unidade | sentinela | obrig. treino | obrig. inferência | status | descrição |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `id_fluxo` | str | id | — | — | sim | sim | verificado | Fluxo = '<probe_id>_<anchor_id>'. |
| `anchor_id` | int | id | — | — | sim | sim | verificado | Âncora de destino das medições. |
| `probe_id` | int | id | — | — | sim | sim | verificado | Sonda de origem das medições. |
| `timestamp` | int | tempo | s | — | sim | sim | inferido | Instante da medição (época Unix, UTC presumido). |
| `split` | cat | controle | — | — | sim | não | verificado | Período temporal: treino, validacao ou teste. |
| `classe_atual` | cat | contexto | — | — | sim | não | verificado | Estado da medição atual. Reproduzido a 99,94% por limiares sobre perda_pct, razao_rtt_p95/p99 e razao_jitter_p95; disponível no instante da previsão. |
| `alvo` | cat | alvo | — | — | sim | não | verificado | Estado da próxima medição do fluxo (coincide com a classe_atual seguinte em 99,98% dos pares). |
| `perda_pct` | float | feature | % | — | sim | sim | inferido | Perda de pacotes na medição. |
| `rtt_ausente` | int | feature | indicador | — | sim | sim | verificado | 1 se a medição não obteve RTT (perda total). |
| `razao_rtt_p95` | float | feature | adimensional | -1: sem RTT na medição (ocorre exatamente quando rtt_ausente = 1) | sim | sim | inferido | RTT da medição dividido pelo p95 de referência do fluxo. O período de referência do percentil não está documentado. |
| `razao_rtt_p99` | float | feature | adimensional | -1: sem RTT na medição (ocorre exatamente quando rtt_ausente = 1) | sim | sim | inferido | RTT da medição dividido pelo p99 de referência do fluxo. |
| `razao_jitter_p95` | float | feature | adimensional | -1: sem RTT na medição (ocorre exatamente quando rtt_ausente = 1) | sim | sim | inferido | Jitter da medição dividido pelo p95 de referência do jitter do fluxo. |
| `amplitude_rtt_rel` | float | feature | adimensional | -1: sem RTT na medição (ocorre exatamente quando rtt_ausente = 1) | sim | sim | inferido | Amplitude do RTT na medição relativa ao RTT típico. |
| `delta_ttl_clip` | int | feature | saltos | — | sim | sim | inferido | Variação do TTL em relação à medição anterior, recortada. Valores negativos são legítimos (não é sentinela). |
| `ttl_reset` | int | feature | indicador | — | sim | sim | inferido | Indicador de reinício de TTL (constante 0 no arquivo atual; removido no treino por variância nula). |
| `perda_media_w3` | float | feature | % | — | sim | sim | verificado | Média de perda_pct nas últimas 3 medições do fluxo, incluindo a atual. |
| `rtt_p95_max_w3` | float | feature | adimensional | -1: nenhuma medição da janela teve RTT | sim | sim | verificado | Máximo de razao_rtt_p95 nas últimas 3 medições, incluindo a atual. |
| `jitter_p95_max_w3` | float | feature | adimensional | -1: nenhuma medição da janela teve RTT | sim | sim | verificado | Máximo de razao_jitter_p95 nas últimas 3 medições, incluindo a atual. |
| `n_rtt_acima_p95_w3` | int | feature | contagem | -1: nenhuma medição da janela teve RTT | sim | sim | verificado | Quantidade, entre as últimas 3 medições, com razao_rtt_p95 > 1. |
| `perda_media_w6` | float | feature | % | — | sim | sim | verificado | Média de perda_pct nas últimas 6 medições do fluxo, incluindo a atual. |
| `rtt_p95_max_w6` | float | feature | adimensional | -1: nenhuma medição da janela teve RTT | sim | sim | verificado | Máximo de razao_rtt_p95 nas últimas 6 medições, incluindo a atual. |
| `jitter_p95_max_w6` | float | feature | adimensional | -1: nenhuma medição da janela teve RTT | sim | sim | verificado | Máximo de razao_jitter_p95 nas últimas 6 medições, incluindo a atual. |
| `n_rtt_acima_p95_w6` | int | feature | contagem | -1: nenhuma medição da janela teve RTT | sim | sim | verificado | Quantidade, entre as últimas 6 medições, com razao_rtt_p95 > 1. |
| `perda_media_w12` | float | feature | % | — | sim | sim | verificado | Média de perda_pct nas últimas 12 medições do fluxo, incluindo a atual. |
| `rtt_p95_max_w12` | float | feature | adimensional | -1: nenhuma medição da janela teve RTT | sim | sim | verificado | Máximo de razao_rtt_p95 nas últimas 12 medições, incluindo a atual. |
| `jitter_p95_max_w12` | float | feature | adimensional | -1: nenhuma medição da janela teve RTT | sim | sim | verificado | Máximo de razao_jitter_p95 nas últimas 12 medições, incluindo a atual. |
| `n_rtt_acima_p95_w12` | int | feature | contagem | -1: nenhuma medição da janela teve RTT | sim | sim | verificado | Quantidade, entre as últimas 12 medições, com razao_rtt_p95 > 1. |
| `perdas_consecutivas` | int | feature | contagem | — | sim | sim | inferido | Medições consecutivas com perda até a atual (máximo observado 99, possivelmente recortado). |

- As janelas w3/w6/w12 são contadas em linhas (medições), não em tempo.

- Linhas removidas da série bruta deixam lacunas: o alvo de uma linha antes de uma lacuna pode se referir a uma medição que não está no arquivo.

## `hismall_v1`

Transações sintéticas do IBM AML (AMLworld), conjunto HI-Small. A coluna 'Account' aparece duas vezes no cabeçalho original (origem e destino).

| coluna | tipo | papel | unidade | sentinela | obrig. treino | obrig. inferência | status | descrição |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `Timestamp` | datahora | tempo | — | — | sim | sim | verificado | Data e hora da transação (resolução de minuto, fuso não documentado). |
| `From Bank` | int | id | — | — | sim | sim | verificado | Banco de origem. |
| `Account` | str | id | — | — | sim | sim | verificado | Conta de origem (única dentro do banco). |
| `To Bank` | int | id | — | — | sim | sim | verificado | Banco de destino. |
| `Account.1` | str | id | — | — | sim | sim | verificado | Conta de destino. |
| `Amount Received` | float | feature | moeda | — | sim | sim | verificado | Valor recebido, na moeda de recebimento. |
| `Receiving Currency` | cat | feature | — | — | sim | sim | verificado | Moeda de recebimento. |
| `Amount Paid` | float | feature | moeda | — | sim | sim | verificado | Valor pago, na moeda de pagamento. |
| `Payment Currency` | cat | feature | — | — | sim | sim | verificado | Moeda de pagamento. |
| `Payment Format` | cat | feature | — | — | sim | sim | verificado | Meio de pagamento (ACH, Wire, Cheque, ...). |
| `Is Laundering` | int | alvo | — | — | sim | não | verificado | 1 = transação faz parte de lavagem segundo o simulador (verdade sintética, sem data de confirmação). |

## `transacao_v1` — PROPOSTA a validar

Contrato financeiro mínimo PROPOSTO para transações vinculáveis à rede.

| coluna | tipo | papel | unidade | sentinela | obrig. treino | obrig. inferência | status | descrição |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `id_transacao` | str | id | — | — | sim | sim | inferido | Identificador único e estável da transação. |
| `timestamp_transacao` | datahora | tempo | — | — | sim | sim | inferido | Instante da transação, em UTC. |
| `timestamp_disponivel` | datahora | tempo | — | — | sim | sim | inferido | Instante em que a transação fica disponível para análise (>= timestamp_transacao). |
| `conta_origem` | str | id | — | — | sim | sim | inferido | Conta de origem. |
| `conta_destino` | str | id | — | — | sim | sim | inferido | Conta de destino. |
| `valor` | float | feature | moeda | — | sim | sim | inferido | Valor na moeda informada. |
| `moeda` | cat | feature | — | — | sim | sim | inferido | Código da moeda (ISO 4217 recomendado). |
| `formato_pagamento` | cat | feature | — | — | não | não | inferido | Meio de pagamento. |
| `chave_tecnica` | str | id | — | — | não | não | inferido | Sessão, dispositivo ou nó que permita o vínculo com a rede (só se existir e tiver significado verificável). |
| `rotulo_fraude` | cat | alvo | — | — | sim | não | inferido | fraude_confirmada, legitima_confirmada ou sem_conclusao. Ausência de confirmação NÃO é legitimidade. |
| `origem_rotulo` | str | controle | — | — | sim | não | inferido | Fonte da evidência do rótulo. |
| `timestamp_confirmacao` | datahora | controle | — | — | não | não | inferido | Quando o rótulo ficou disponível (necessário para respeitar o atraso). |

## `vinculo_v1` — PROPOSTA a validar

Tabela PROPOSTA que liga uma transação (ou sua chave técnica) a um fluxo de rede monitorado, com validade no tempo. Proximidade de horário NÃO é vínculo.

| coluna | tipo | papel | unidade | sentinela | obrig. treino | obrig. inferência | status | descrição |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `chave` | str | id | — | — | sim | sim | inferido | id_transacao ou chave_tecnica (ver tipo_chave). |
| `tipo_chave` | cat | controle | — | — | sim | sim | inferido | 'id_transacao' ou 'chave_tecnica'. |
| `id_fluxo` | str | id | — | — | sim | sim | inferido | Fluxo de rede vinculado (formato rede_v1). |
| `valido_de` | datahora | tempo | — | — | sim | sim | inferido | Início da validade do vínculo (UTC). |
| `valido_ate` | datahora | tempo | — | — | sim | sim | inferido | Fim da validade do vínculo (UTC, exclusivo). |
| `fonte_vinculo` | str | controle | — | — | sim | sim | inferido | Origem documentada da associação. |

