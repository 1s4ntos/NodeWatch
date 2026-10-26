# Contrato de integração rede ↔ transações (PROPOSTA a validar)

**Situação atual:** a cabeça `fusao_rede_transacao` do modelo unificado está **indisponível**.

Hoje não existe vínculo verificável entre as transações do IBM AML HI-Small e os fluxos de `dataset_final.csv`:
- não há chave comum;
- os períodos não se sobrepõem: as transações são de 01–18/09/2022 e a telemetria de 28/09–05/10/2026.

Por isso nenhum registro é associado. O modelo também **não aprendeu nenhuma relação entre anomalias de rede e lavagem**.

Este documento define o que precisa existir para treinar e avaliar essa relação. Os esquemas estão em [`esquemas/transacao_v1.json`](esquemas/transacao_v1.json) e [`esquemas/vinculo_v1.json`](esquemas/vinculo_v1.json). O código correspondente está em [`src/ml/integracao.py`](../../src/ml/integracao.py) e na classe `CabecaFusao` de [`src/ml/modelos.py`](../../src/ml/modelos.py).

## 1. Transações (`transacao_v1`)

| campo | obrigatório | observação |
| --- | --- | --- |
| `id_transacao` | sim | Único e estável. |
| `timestamp_transacao` | sim | Em UTC. Se a fonte usar outro fuso, informe qual. |
| `timestamp_disponivel` | sim | Quando a transação pode ser analisada (≥ `timestamp_transacao`). É o instante usado na junção temporal. |
| `conta_origem`, `conta_destino` | sim | Identificadores de conta. Não equivalem a `anchor_id`/`probe_id`. |
| `valor`, `moeda` | sim | Valores em moedas diferentes não são comparáveis sem câmbio. Informe a fonte da taxa e o instante dela. |
| `formato_pagamento` | não | Meio de pagamento. |
| `chave_tecnica` | não | Sessão, dispositivo ou nó. Use só se existir e tiver significado verificável. |
| `rotulo_fraude` | para treino | `fraude_confirmada`, `legitima_confirmada` ou `sem_conclusao`. |
| `origem_rotulo` | para treino | Evidência externa documentada (ex.: chargeback, investigação). |
| `timestamp_confirmacao` | para treino | Quando o rótulo ficou disponível. É necessário para respeitar o atraso. |

Regras:
- **Ausência de confirmação não é legitimidade.** Um caso só conta como `legitima_confirmada` depois de um prazo de maturação documentado. A fonte dos dados precisa definir esse prazo.
- No treino, o rótulo só pode ser usado se `timestamp_confirmacao` for anterior ao fim do período de ajuste.
- Sem rótulos, é possível pontuar anomalias, mas a saída se chama **pontuação de anomalia** e não fraude.

## 2. Vínculo (`vinculo_v1`)

| campo | observação |
| --- | --- |
| `chave` + `tipo_chave` | `id_transacao` ou `chave_tecnica`. |
| `id_fluxo` | Fluxo de rede monitorado, no formato `rede_v1`. |
| `valido_de`, `valido_ate` | Validade do vínculo (UTC). O fim é exclusivo. |
| `fonte_vinculo` | De onde vem a associação: tabela de sessões, inventário de nós etc. |

**Proximidade de horário não é vínculo.** Uma transação só recebe sinais de rede pelos fluxos ligados a ela nesta tabela, dentro da validade.

## 3. Junção temporal

A função `associar_sinais_rede(transacoes, vinculo, previsoes_rede, tolerancia_s=480)` faz a junção:

1. Liga cada transação aos fluxos válidos em `timestamp_disponivel`.
2. Para cada par transação–fluxo, pega a **última previsão de rede emitida até `timestamp_disponivel`** (`merge_asof` para trás) e não mais antiga que a tolerância. O padrão é 480 s, ou 2× o intervalo mediano das medições.
3. Uma previsão emitida em *t* pode servir de sinal em *t*. A medição observada depois de *t* nunca é usada.
4. Descarta previsões feitas por um modelo de rede treinado com dados posteriores à transação (`modelo_rede_treinado_ate > timestamp_disponivel`). O resultado é sempre um sinal fora da amostra no tempo.
5. Agrega por transação:
   - `n_fluxos_vinculados`;
   - `n_fluxos_com_sinal`;
   - `score_alerta_rede_max`;
   - `idade_sinal_s_min`;
   - `cobertura_vinculo`, que vale `sem_vinculo`, `vinculo_sem_sinal_recente`, `com_sinal` ou `com_sinal_ambiguo` (mais de um fluxo).
6. O relatório devolve cobertura, ambiguidades, vínculos fora da validade e sinais descartados.

O `score_alerta_rede` estima o estado de rede não-OK na próxima medição. Ele **não** é uma probabilidade de fraude.

## 4. Como treinar a fusão quando os dados existirem

1. Gerar atributos financeiros point-in-time, como em `src/ml/preparacao.py::atributos_financeiros`.
2. Gerar as previsões de rede de cada período com um modelo treinado só em dados anteriores, por exemplo em janelas cronológicas expansivas.
3. Anexar os sinais com `associar_sinais_rede`.
4. Na mesma divisão temporal e com os mesmos rótulos maduros, comparar o modelo financeiro **sem** e **com** os sinais de rede. A comparação usa:
   - precisão e recall da classe fraude;
   - average precision e curva PR;
   - falsos alertas;
   - recall@k na capacidade de investigação informada.
5. Escolher o limiar na validação, segundo custos e capacidade quando forem fornecidos. Não somar pontuações com pesos arbitrários.

## 5. Adaptadores prontos

- `adaptar_hismall(dados)`: converte o HI-Small para `transacao_v1`.
  - `Is Laundering` vira `rotulo_lavagem`, e não `rotulo_fraude`: é verdade sintética de lavagem, sem data de confirmação.
  - O fuso é assumido como UTC.
- `adaptar_csv_nodewatch(df, inicio)`: converte o CSV do grafo NodeWatch (`step,type,amount,nameOrig,nameDest,isFraud`).
  - `step` é relativo; no conversor da IBM, conta horas desde a primeira linha.
  - A moeda foi descartada pelo conversor e fica ausente.

## 6. Dados que faltam para aprender a relação rede ↔ transação

1. Transações reais ou simuladas **do mesmo período** da telemetria.
2. Tabela de vínculo transação → fluxo, com fonte documentada.
3. Rótulos de fraude com origem e data de confirmação, ou critério documentado de maturação para os legítimos.
4. Custos de erro e capacidade de investigação, para escolher limiares.
