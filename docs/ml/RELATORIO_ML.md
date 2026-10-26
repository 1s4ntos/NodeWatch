# Relatório de ML — NodeWatch

Gerado por `python -m src.ml.cli relatorio` a partir de `artefatos_ml/`. Todos os números abaixo foram calculados na execução registrada; nenhum foi digitado à mão.

Ambiente: modulo_ml 0.1.0, python 3.14.0, numpy 2.5.4, pandas 3.1.0, scikit-learn 1.9.1, joblib 1.6.0.

| cabeça do modelo unificado | status |
| --- | --- |
| fusao_rede_transacao | indisponivel |
| estado_rede | treinada |
| estado_rede__com_classe_atual | treinada |
| lavagem | treinada |

## 1. Tarefa `estado_rede` — estado da próxima medição

### 1.1 Auditoria (refeita nesta execução)

| item | valor |
| --- | --- |
| linhas | 333.954 |
| fluxos | 135 |
| NaN / inf | 0 / 0 |
| duplicatas id_fluxo+timestamp | 0 |
| alvo = classe_atual seguinte | 0,999826 |
| divergências dentro do split (seguidas de lacuna) | 6 de 333.549 (6) |
| regra de limiares reproduz classe_atual | 0,9994 |
| intervalo mediano (s) | 240 |
| menor lacuna entre splits (s) / p99,9 do intervalo (s) | 3605 / 484 |
| expurgo necessário pelo horizonte | não |
| colunas constantes | ttl_reset |

Conferência das janelas (fração de linhas que coincide com a rolagem para trás, por medições; a última coluna é o contraste olhando para frente):

| janela | perda média | rtt máx | jitter máx | n acima p95 | jitter máx (para frente) |
| --- | --- | --- | --- | --- | --- |
| w3 | 1,0000 | 0,9991 | 0,9989 | 0,9997 | 0,2050 |
| w6 | 0,9999 | 0,9976 | 0,9973 | 0,9991 | 0,0915 |
| w12 | 0,9995 | 0,9947 | 0,9943 | 0,9976 | 0,0442 |

### 1.2 Seleção na validação (ajuste só no treino)

Escolhido: **random_forest[n_estimators=150,min_samples_leaf=20,max_samples=0.5,class_weight=None]**; limiar de `score_alerta_rede` = 0,3173 (máximo F1 de não-OK na validação).

| configuração | macro-F1 | recall RISCO | recall FALHA | balanced acc. | s |
| --- | --- | --- | --- | --- | --- |
| majoritaria | 0,3124 | 0,0000 | 0,0000 | 0,3333 | — |
| persistencia | 0,7106 | 0,4826 | 0,7055 | 0,7109 | — |
| logistica[C=0.1,class_weight=None] | 0,5900 | 0,2924 | 0,3805 | 0,5538 | 2,2000 |
| logistica[C=0.1,class_weight=balanced] | 0,5179 | 0,2152 | 0,7696 | 0,6225 | 2,4000 |
| logistica[C=1.0,class_weight=None] | 0,5897 | 0,2921 | 0,3798 | 0,5535 | 1,9000 |
| logistica[C=1.0,class_weight=balanced] | 0,5180 | 0,2155 | 0,7696 | 0,6226 | 2,5000 |
| random_forest[n_estimators=150,min_samples_leaf=20,max_samples=0.5,class_weight=None] | 0,7628 | 0,3964 | 0,7383 | 0,7090 | 12,8000 |
| random_forest[n_estimators=150,min_samples_leaf=20,max_samples=0.5,class_weight=balanced_subsample] | 0,7298 | 0,5573 | 0,7831 | 0,7597 | 12,1000 |
| random_forest[n_estimators=150,min_samples_leaf=100,max_samples=0.5,class_weight=None] | 0,7561 | 0,3844 | 0,7240 | 0,7004 | 11,1000 |
| random_forest[n_estimators=150,min_samples_leaf=100,max_samples=0.5,class_weight=balanced_subsample] | 0,6950 | 0,5791 | 0,7952 | 0,7601 | 10,7000 |
| hist_gradient_boosting[max_iter=200,learning_rate=0.1,max_leaf_nodes=31,class_weight=None] | 0,7618 | 0,4192 | 0,7240 | 0,7109 | 4,1000 |
| hist_gradient_boosting[max_iter=200,learning_rate=0.1,max_leaf_nodes=31,class_weight=balanced] | 0,6985 | 0,5845 | 0,7909 | 0,7600 | 4,3000 |
| hist_gradient_boosting[max_iter=200,learning_rate=0.1,max_leaf_nodes=63,class_weight=None] | 0,7563 | 0,4170 | 0,7077 | 0,7045 | 5,6000 |
| hist_gradient_boosting[max_iter=200,learning_rate=0.1,max_leaf_nodes=63,class_weight=balanced] | 0,7136 | 0,5766 | 0,7760 | 0,7564 | 5,8000 |

### 1.3 Teste (avaliação única, artefato congelado)

| referência | macro-F1 | balanced acc. | acurácia | F1 OK | F1 RISCO | F1 FALHA | recall RISCO | recall FALHA |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| majoritária (treino) | 0,3107 | 0,3333 | 0,8730 | 0,9322 | 0,0000 | 0,0000 | 0,0000 | 0,0000 |
| persistência | 0,7108 | 0,7106 | 0,8942 | 0,9445 | 0,5064 | 0,6815 | 0,5070 | 0,6806 |
| modelo escolhido | 0,7499 | 0,7023 | 0,9276 | 0,9638 | 0,5579 | 0,7279 | 0,4180 | 0,6968 |
| modelo + classe_atual | 0,7522 | 0,7064 | 0,9280 | 0,9641 | 0,5629 | 0,7295 | 0,4245 | 0,7032 |

Matriz de confusão do modelo (teste):

| real \ previsto | OK | RISCO | FALHA |
| --- | --- | --- | --- |
| OK | 39.925 | 201 | 124 |
| RISCO | 2.400 | 1.856 | 184 |
| FALHA | 273 | 156 | 986 |

Matriz de confusão da persistência (teste):

| real \ previsto | OK | RISCO | FALHA |
| --- | --- | --- | --- |
| OK | 38.012 | 1.999 | 239 |
| RISCO | 1.980 | 2.251 | 209 |
| FALHA | 252 | 200 | 963 |

Inícios de evento e transições (teste):

| referência | inícios não-OK | detectados | inícios FALHA detectados | transições | acurácia nas transições |
| --- | --- | --- | --- | --- | --- |
| persistência | 2.229 | 0,0000 | 0,0000 | 4.879 | 0,0000 |
| modelo escolhido | 2.229 | 0,0449 | 0,1905 | 4.879 | 0,4243 |
| modelo + classe_atual | 2.229 | 0,0422 | 0,1944 | 4.879 | 0,4185 |

Alertas (teste; tempo observado ≈ linhas × intervalo mediano):

| referência | alertas | corretos | falsos | não alertados | falsos por fluxo-hora | mediana por fluxo | p90 por fluxo |
| --- | --- | --- | --- | --- | --- | --- | --- |
| persistência | 5.861 | 3.623 | 2.238 | 2.232 | 0,7281 | 0,6541 | 1,0933 |
| modelo escolhido | 4.621 | 3.674 | 947 | 2.181 | 0,3081 | 0,0439 | 0,6989 |
| modelo + classe_atual | 4.696 | 3.713 | 983 | 2.142 | 0,3198 | 0,0439 | 0,6818 |

Calibração de P(não OK) no teste: Brier 0,0548, ECE 0,0097; Brier multiclasse 0,1216.

| faixa de prob. | n | prob. média | frequência observada |
| --- | --- | --- | --- |
| 0,0–0,1 | 36.593 | 0,0464 | 0,0419 |
| 0,1–0,2 | 3.942 | 0,1316 | 0,1065 |
| 0,2–0,3 | 831 | 0,2439 | 0,2286 |
| 0,3–0,4 | 595 | 0,3483 | 0,3412 |
| 0,4–0,5 | 530 | 0,4467 | 0,4925 |
| 0,5–0,6 | 275 | 0,5477 | 0,6291 |
| 0,6–0,7 | 320 | 0,6554 | 0,7156 |
| 0,7–0,8 | 496 | 0,7518 | 0,8185 |
| 0,8–0,9 | 505 | 0,8510 | 0,9010 |
| 0,9–1,0 | 2.018 | 0,9642 | 0,9841 |

Troca entre recall e falsos alertas (`score_alerta_rede`):

| limiar | precisão val. | recall val. | falsos/fluxo-h val. | precisão teste | recall teste | falsos/fluxo-h teste |
| --- | --- | --- | --- | --- | --- | --- |
| 0,0500 | 0,1975 | 0,8885 | 6,3952 | 0,2101 | 0,9011 | 6,4545 |
| 0,1000 | 0,4290 | 0,7235 | 1,7059 | 0,4545 | 0,7383 | 1,6882 |
| 0,1500 | 0,5942 | 0,6672 | 0,8073 | 0,6224 | 0,6905 | 0,7981 |
| 0,2000 | 0,6715 | 0,6452 | 0,5592 | 0,7007 | 0,6666 | 0,5423 |
| 0,2500 | 0,7207 | 0,6240 | 0,4285 | 0,7489 | 0,6500 | 0,4151 |
| 0,3000 | 0,7617 | 0,6020 | 0,3336 | 0,7835 | 0,6342 | 0,3338 |
| 0,3500 | 0,7923 | 0,5829 | 0,2707 | 0,8171 | 0,6174 | 0,2632 |
| 0,4000 | 0,8257 | 0,5627 | 0,2104 | 0,8470 | 0,5995 | 0,2063 |
| 0,4500 | 0,8587 | 0,5434 | 0,1584 | 0,8776 | 0,5768 | 0,1532 |
| 0,5000 | 0,8858 | 0,5240 | 0,1197 | 0,8990 | 0,5549 | 0,1188 |
| 0,5500 | 0,9045 | 0,5126 | 0,0958 | 0,9105 | 0,5389 | 0,1009 |
| 0,6000 | 0,9150 | 0,4960 | 0,0816 | 0,9212 | 0,5254 | 0,0856 |
| 0,6500 | 0,9253 | 0,4781 | 0,0684 | 0,9316 | 0,5095 | 0,0713 |
| 0,7000 | 0,9340 | 0,4565 | 0,0571 | 0,9430 | 0,4863 | 0,0560 |
| 0,7500 | 0,9432 | 0,4322 | 0,0461 | 0,9554 | 0,4541 | 0,0403 |
| 0,8000 | 0,9610 | 0,3954 | 0,0284 | 0,9675 | 0,4169 | 0,0267 |
| 0,8500 | 0,9788 | 0,3617 | 0,0139 | 0,9789 | 0,3804 | 0,0156 |
| 0,9000 | 0,9849 | 0,3326 | 0,0090 | 0,9841 | 0,3392 | 0,0104 |
| 0,9500 | 0,9912 | 0,2670 | 0,0042 | 0,9929 | 0,2377 | 0,0033 |

Grupos inéditos (treino sem os grupos, teste só neles, no período de teste):

| agrupamento | grupos | macro-F1 média | desvio-padrão | persistência (média) |
| --- | --- | --- | --- | --- |
| id_fluxo | 135 | 0,6807 | 0,0729 | 0,6738 |
| anchor_id | 30 | 0,6994 | 0,0828 | 0,6936 |

## 2. Tarefa `lavagem` — IBM AML HI-Small (sintético)

### 2.1 Auditoria

| item | valor |
| --- | --- |
| transações / positivos | 5.078.345 / 5.177 |
| período | 2022-09-01 00:00:00 a 2022-09-18 16:18:00 |
| contas distintas | 515.088 |
| duplicatas exatas | 9 |
| auto-transferências (positivos) | 591.212 (11) |
| moeda de pagamento ≠ recebimento | 72.170 |
| dias com volume < 1% da mediana | 2022-09-11, 2022-09-12, 2022-09-13, 2022-09-14, 2022-09-15, 2022-09-16, 2022-09-17, 2022-09-18 |
| arquivos pendentes | contas, padroes |

| split | transações | positivos | taxa |
| --- | --- | --- | --- |
| treino | 3.248.921 | 2.530 | 0,0008 |
| validacao | 965.524 | 1.036 | 0,0011 |
| teste | 862.792 | 956 | 0,0011 |
| cauda | 1.108 | 655 | 0,5912 |
| fora | 0 | 0 | — |

| formato | transações | positivos | taxa |
| --- | --- | --- | --- |
| ACH | 600.797 | 4.483 | 0,0075 |
| Bitcoin | 146.091 | 56 | 0,0004 |
| Cash | 490.891 | 108 | 0,0002 |
| Cheque | 1.864.331 | 324 | 0,0002 |
| Credit Card | 1.323.324 | 206 | 0,0002 |
| Reinvestment | 481.056 | 0 | 0,0000 |
| Wire | 171.855 | 0 | 0,0000 |

### 2.2 Seleção na validação

Escolhido: **random_forest[n_estimators=100,min_samples_leaf=50,max_samples=0.5]**; limiar 0,080790 (máximo F1 na validação). 49 atributos.

| configuração | AP validação | F1 no limiar | precisão | recall | s |
| --- | --- | --- | --- | --- | --- |
| prevalencia | 0,0011 | — | — | — | — |
| taxa_do_formato | 0,0068 | 0,0151 | 0,0076 | 0,8591 | — |
| logistica[C=0.1] | 0,1647 | 0,2562 | 0,1907 | 0,3900 | 3,7000 |
| logistica[C=1.0] | 0,1650 | 0,2573 | 0,1918 | 0,3909 | 3,5000 |
| random_forest[n_estimators=100,min_samples_leaf=50,max_samples=0.5] | 0,4950 | 0,5055 | 0,5520 | 0,4662 | 28,6000 |
| hist_gradient_boosting[max_iter=300,learning_rate=0.1,max_leaf_nodes=31,l2_regularization=1.0] | 0,4497 | 0,5177 | 0,6677 | 0,4228 | 10,7000 |
| hist_gradient_boosting[max_iter=300,learning_rate=0.1,max_leaf_nodes=63,l2_regularization=1.0] | 0,4290 | 0,4930 | 0,5911 | 0,4228 | 15,5000 |

### 2.3 Teste (artefato congelado)

| referência | AP | precisão | recall | F1 | falsos/10 mil | VP | FP | FN |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| prevalência | 0,0011 | 0,0011 | 1,0000 | 0,0022 | 9988,9197 | 956 | 861.836 | 0 |
| taxa do formato | 0,0064 | 0,0070 | 0,8724 | 0,0139 | 1371,8370 | 834 | 118.361 | 122 |
| modelo escolhido | 0,4610 | 0,5214 | 0,4456 | 0,4805 | 4,5318 | 426 | 391 | 530 |

Capacidade de investigação (top-k por dia):

| dia | transações | positivos | recall@50 | recall@100 | recall@500 | recall@1000 | recall@5000 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2022-09-09 | 654.467 | 514 | 0,0973 | 0,1848 | 0,4455 | 0,5409 | 0,6984 |
| 2022-09-10 | 208.325 | 442 | 0,1086 | 0,2127 | 0,5000 | 0,6109 | 0,8281 |

Calibração do score no teste: Brier 0,000967, ECE 0,000998.

Recall por padrão: pendente (HI-Small_Patterns.txt não disponível).

### 2.4 Cauda do gerador (fora das métricas principais)

| referência | AP | precisão | recall | F1 | falsos/10 mil | VP | FP | FN |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| prevalência | 0,5912 | 0,5912 | 1,0000 | 0,7431 | 4088,4477 | 655 | 453 | 0 |
| taxa do formato | 0,5912 | 0,5912 | 1,0000 | 0,7431 | 4088,4477 | 655 | 453 | 0 |
| modelo escolhido | 0,9679 | 0,9427 | 0,8290 | 0,8822 | 297,8339 | 543 | 33 | 112 |

## 3. Fusão rede ↔ transação

Status: **indisponivel**. Não há vínculo verificável entre as transações do HI-Small (setembro de 2022) e os fluxos de dataset_final.csv (setembro-outubro de 2026): não há chave comum nem sobreposição temporal.

Entradas necessárias:

- transações no esquema transacao_v1 com timestamp_disponivel
- tabela vinculo_v1 (transação ou chave técnica → id_fluxo, com validade e fonte documentada)
- telemetria rede_v1 do mesmo período das transações
- previsões de rede fora da amostra (modelo de rede treinado antes de cada transação)
- rotulo_fraude com origem_rotulo e timestamp_confirmacao

## 4. Leitura dos resultados (execução de 26/10/2026)

### Rede
- **Ganho sobre a persistência.** No teste, o modelo escolhido (Random Forest, ajustado só no treino) tem macro-F1 0,750, contra 0,711 da persistência e 0,311 da classe majoritária. A acurácia de 0,928 vem acompanhada de 0,873 da majoritária, que só prevê `OK`. O ganho vem principalmente de **menos falsos alertas**: 947, contra 2.238 da persistência (0,31 × 0,73 por fluxo-hora). O F1 de `RISCO` e de `FALHA` também sobe. Em troca, o recall de `RISCO` cai (0,418 × 0,507), e por isso a balanced accuracy fica um pouco abaixo da persistência (0,702 × 0,711).
- **O modelo quase não antecipa o início de eventos.** Dos 2.229 inícios OK → não-OK, só 4,5% são previstos (19% nos inícios de `FALHA`). A persistência fica em 0% por construção. A maior parte do acerto vem de estados que continuam e de eventos que terminam: nas transições, o modelo acerta 42%.
- **`classe_atual` não acrescenta nada (0,752 × 0,750).** Isso é coerente com a auditoria: ela é derivada dos próprios atributos da medição atual.
- **Fluxos e âncoras inéditos.** O ganho quase desaparece: macro-F1 0,681 ± 0,073 contra 0,674 da persistência por fluxo, e 0,699 ± 0,083 contra 0,694 por âncora. A vantagem do modelo depende de ter visto o fluxo no treino.
- **Calibração.** P(não OK) tem ECE 0,010 e Brier 0,055, com leve subconfiança entre 0,5 e 0,9.
- **Referência externa.** A Random Forest do notebook da professora registrou macro-F1 de teste de cerca de 0,755, com reajuste em treino+validação. É da mesma ordem dos 0,750 obtidos aqui com ajuste só no treino.

### Lavagem
- **Desempenho.** No teste, a AP é 0,461, contra 0,0064 do baseline "taxa do formato" e 0,0011 da prevalência. No limiar congelado (0,0808), a precisão é 0,521, o recall 0,446 e o F1 0,480, com 391 falsos positivos em 862.792 transações (4,5 por 10 mil).
- **Capacidade de investigação.** Investigando 1.000 alertas por dia, o recall seria de 0,54 e 0,61 nos dois dias do teste.
- **Leve queda no tempo.** A AP cai de 0,495 na validação para 0,461 no teste.
- **Não linearidade.** A regressão logística fica em 0,165, então a interação entre histórico de contas e formato pesa.
- **Cauda.** A AP de 0,968 na cauda é inflada pela base de 59% de lavagem e não representa operação.

## 5. Limitações e decisões documentadas

### Rede
- **Origem das features não documentada.** O período de referência dos percentis p95/p99 usados nas razões é desconhecido. No treino, 7,5% das medições com RTT ficam acima do "p95". A auditoria confirmou nos dados que as janelas `w3/w6/w12` olham só para trás (contadas em medições) e que os `-1` coincidem com ausência de RTT. Mesmo assim, não dá para afirmar que a construção original esteja livre de vazamento: o código que gerou o CSV não foi fornecido.
- **Horizonte.** O alvo é a próxima medição do fluxo (mediana de 240 s, irregular), e não "4 minutos". As 6 divergências entre `alvo` e a `classe_atual` seguinte estão todas antes de lacunas na série. Foram mantidas sem alteração.
- **Expurgo.** Nenhum foi aplicado: a menor lacuna entre splits (3.605 s) é muito maior que o horizonte (p99,9 = 484 s).
- **Mesmos fluxos nos três períodos.** As métricas do teste medem o futuro de fluxos conhecidos. Para fluxos e âncoras inéditos, vale a análise de grupos (seção 1.3).
- **Probabilidades.** O `score_alerta_rede` estima o estado não-OK na próxima medição; a calibração está reportada acima. Não é probabilidade de fraude.
- **Tempo observado.** "Falsos por fluxo-hora" usa o tempo aproximado de linhas × intervalo mediano.

### Lavagem (HI-Small)
- **Dados sintéticos.** `Is Laundering` é verdade sintética de lavagem, sem data de confirmação. O desempenho não se transfere automaticamente para dados reais, e lavagem não é sinônimo de fraude.
- **Cauda do gerador.** De 11/09 em diante só há 1.108 transações, com 58–73% de lavagem. Elas ficam fora das métricas principais (seção 2.4) para não premiar um artefato do tempo.
- **Formato de pagamento.** ACH concentra cerca de 87% da lavagem, e Wire/Reinvestment não têm nenhum caso. O baseline "taxa do formato" mostra quanto do desempenho vem só desse sinal, que pode ser artefato do gerador.
- **Atraso de rótulo.** Rótulos do treino são tratados como conhecidos ao fim do treino, e tentativas de lavagem podem atravessar a fronteira entre períodos. Rótulos passados nunca entram como atributo. Sem `HI-Small_Patterns.txt`, não foi possível medir a fração de tentativas que atravessam períodos.
- **Contas e padrões.** `HI-Small_accounts.csv` e `HI-Small_Patterns.txt` não estavam extraídos nesta execução, então a auditoria de vazamento em contas e o recall por padrão ficaram pendentes. As transações foram lidas de uma cópia byte a byte do `HI-Small_Trans.zip` armazenado no `.rar` da professora, com CRC conferido.
- **Câmbio.** É estimado no treino pela mediana das razões recebido/pago entre moedas diferentes. O fuso dos dados é desconhecido e assumido como UTC.

### Fusão
- Não há vínculo entre as fontes (sem chave comum e sem sobreposição temporal). Nenhuma métrica de fraude ligada à rede foi produzida. O que falta está listado em `CONTRATO_INTEGRACAO.md`.

