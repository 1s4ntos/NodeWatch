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
| logistica[C=0.1,class_weight=None] | 0,5899 | 0,2924 | 0,3798 | 0,5535 | 3,2000 |
| logistica[C=0.1,class_weight=balanced] | 0,5179 | 0,2155 | 0,7696 | 0,6226 | 3,6000 |
| logistica[C=1.0,class_weight=None] | 0,5897 | 0,2921 | 0,3798 | 0,5535 | 2,9000 |
| logistica[C=1.0,class_weight=balanced] | 0,5179 | 0,2152 | 0,7696 | 0,6225 | 3,9000 |
| random_forest[n_estimators=150,min_samples_leaf=20,max_samples=0.5,class_weight=None] | 0,7628 | 0,3964 | 0,7383 | 0,7090 | 12,8000 |
| random_forest[n_estimators=150,min_samples_leaf=20,max_samples=0.5,class_weight=balanced_subsample] | 0,7298 | 0,5573 | 0,7831 | 0,7597 | 12,3000 |
| random_forest[n_estimators=150,min_samples_leaf=100,max_samples=0.5,class_weight=None] | 0,7561 | 0,3844 | 0,7240 | 0,7004 | 10,8000 |
| random_forest[n_estimators=150,min_samples_leaf=100,max_samples=0.5,class_weight=balanced_subsample] | 0,6950 | 0,5791 | 0,7952 | 0,7601 | 10,3000 |
| hist_gradient_boosting[max_iter=200,learning_rate=0.1,max_leaf_nodes=31,class_weight=None] | 0,7618 | 0,4192 | 0,7240 | 0,7109 | 4,0000 |
| hist_gradient_boosting[max_iter=200,learning_rate=0.1,max_leaf_nodes=31,class_weight=balanced] | 0,6985 | 0,5845 | 0,7909 | 0,7600 | 3,9000 |
| hist_gradient_boosting[max_iter=200,learning_rate=0.1,max_leaf_nodes=63,class_weight=None] | 0,7563 | 0,4170 | 0,7077 | 0,7045 | 5,2000 |
| hist_gradient_boosting[max_iter=200,learning_rate=0.1,max_leaf_nodes=63,class_weight=balanced] | 0,7136 | 0,5766 | 0,7760 | 0,7564 | 5,3000 |

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
| arquivos pendentes | — |

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

Atributos de conta (vazamento):

| atributo | AP validação | lift máx. | suspeito |
| --- | --- | --- | --- |
| tipo_entidade_origem | 0,0012 | 1,7682 | não |
| tipo_entidade_destino | 0,0011 | 1,1434 | não |
| n_contas_entidade_origem | 0,0012 | 3,0034 | não |
| n_contas_entidade_destino | 0,0017 | 3,2608 | não |

Padrões: 370 tentativas, 3209 de 3209 linhas casadas com transações; 1968 positivos sem padrão; 206 tentativas atravessam splits.

### 2.2 Seleção na validação

Escolhido: **random_forest[n_estimators=100,min_samples_leaf=50,max_samples=0.5]**; limiar 0,090984 (máximo F1 na validação). 49 atributos.

| configuração | AP validação | F1 no limiar | precisão | recall | s |
| --- | --- | --- | --- | --- | --- |
| prevalencia | 0,0011 | — | — | — | — |
| taxa_do_formato | 0,0068 | 0,0151 | 0,0076 | 0,8591 | — |
| logistica[C=0.1] | 0,1895 | 0,2897 | 0,2282 | 0,3967 | 5,0000 |
| logistica[C=1.0] | 0,1870 | 0,2862 | 0,2298 | 0,3793 | 4,8000 |
| random_forest[n_estimators=100,min_samples_leaf=50,max_samples=0.5] | 0,4990 | 0,5183 | 0,6384 | 0,4363 | 27,8000 |
| hist_gradient_boosting[max_iter=300,learning_rate=0.1,max_leaf_nodes=31,l2_regularization=1.0] | 0,4449 | 0,5017 | 0,6211 | 0,4208 | 11,9000 |
| hist_gradient_boosting[max_iter=300,learning_rate=0.1,max_leaf_nodes=63,l2_regularization=1.0] | 0,4276 | 0,4967 | 0,6461 | 0,4035 | 14,0000 |

### 2.3 Teste (artefato congelado)

| referência | AP | precisão | recall | F1 | falsos/10 mil | VP | FP | FN |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| prevalência | 0,0011 | 0,0011 | 1,0000 | 0,0022 | 9988,9197 | 956 | 861.836 | 0 |
| taxa do formato | 0,0064 | 0,0070 | 0,8724 | 0,0139 | 1371,8370 | 834 | 118.361 | 122 |
| modelo escolhido | 0,4640 | 0,6274 | 0,4069 | 0,4937 | 2,6774 | 389 | 231 | 567 |

Capacidade de investigação (top-k por dia):

| dia | transações | positivos | recall@50 | recall@100 | recall@500 | recall@1000 | recall@5000 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2022-09-09 | 654.467 | 514 | 0,0973 | 0,1829 | 0,4397 | 0,5389 | 0,7121 |
| 2022-09-10 | 208.325 | 442 | 0,1086 | 0,2104 | 0,5000 | 0,6154 | 0,8303 |

Calibração do score no teste: Brier 0,000967, ECE 0,000964.

Recall por tipo de padrão (positivos do teste, no limiar):

| tipo | positivos | detectados | recall |
| --- | --- | --- | --- |
| BIPARTITE | 44 | 24 | 0,5455 |
| CYCLE | 55 | 33 | 0,6000 |
| FAN-IN | 57 | 39 | 0,6842 |
| FAN-OUT | 65 | 47 | 0,7231 |
| GATHER-SCATTER | 127 | 85 | 0,6693 |
| RANDOM | 43 | 24 | 0,5581 |
| SCATTER-GATHER | 110 | 74 | 0,6727 |
| STACK | 84 | 56 | 0,6667 |
| sem_padrao | 371 | 7 | 0,0189 |

| tentativa | positivos | detectados | recall |
| --- | --- | --- | --- |
| iniciada_antes | 375 | 272 | 0,7253 |
| nova | 210 | 110 | 0,5238 |
| sem_padrao | 371 | 7 | 0,0189 |

### 2.4 Cauda do gerador (fora das métricas principais)

| referência | AP | precisão | recall | F1 | falsos/10 mil | VP | FP | FN |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| prevalência | 0,5912 | 0,5912 | 1,0000 | 0,7431 | 4088,4477 | 655 | 453 | 0 |
| taxa do formato | 0,5912 | 0,5912 | 1,0000 | 0,7431 | 4088,4477 | 655 | 453 | 0 |
| modelo escolhido | 0,9690 | 0,9607 | 0,7847 | 0,8639 | 189,5307 | 514 | 21 | 141 |

## 3. Fusão rede ↔ transação

Status: **indisponivel**. Não há vínculo verificável entre as transações do HI-Small (setembro de 2022) e os fluxos de dataset_final.csv (setembro-outubro de 2026): não há chave comum nem sobreposição temporal.

Entradas necessárias:

- transações no esquema transacao_v1 com timestamp_disponivel
- tabela vinculo_v1 (transação ou chave técnica → id_fluxo, com validade e fonte documentada)
- telemetria rede_v1 do mesmo período das transações
- previsões de rede fora da amostra (modelo de rede treinado antes de cada transação)
- rotulo_fraude com origem_rotulo e timestamp_confirmacao

## 4. Leitura dos resultados (execução de 02/11/2026)

Esta execução incorpora as correções da auditoria de 02/11/2026 (seção 6). Na rede, o modelo e as métricas são idênticos aos de 26/10. Na lavagem, os números mudaram porque o atributo `z_valor_origem` foi corrigido e o modelo foi retreinado.

### Rede
- **Ganho sobre a persistência.** No teste, o modelo escolhido (Random Forest, ajustado só no treino) tem macro-F1 0,750, contra 0,711 da persistência e 0,311 da classe majoritária. A acurácia de 0,928 vem acompanhada de 0,873 da majoritária, que só prevê `OK`. O ganho vem principalmente de **menos falsos alertas**: 947, contra 2.238 da persistência (0,31 × 0,73 por fluxo-hora). O F1 de `RISCO` e de `FALHA` também sobe. Em troca, o recall de `RISCO` cai (0,418 × 0,507), e por isso a balanced accuracy fica um pouco abaixo da persistência (0,702 × 0,711).
- **O modelo quase não antecipa o início de eventos.** Dos 2.229 inícios OK → não-OK, só 4,5% são previstos (19% nos inícios de `FALHA`). A persistência fica em 0% por construção. A maior parte do acerto vem de estados que continuam e de eventos que terminam: nas transições, o modelo acerta 42%.
- **`classe_atual` não acrescenta nada (0,752 × 0,750).** Isso é coerente com a auditoria: ela é derivada dos próprios atributos da medição atual.
- **Fluxos e âncoras inéditos.** O ganho quase desaparece: macro-F1 0,681 ± 0,073 contra 0,674 da persistência por fluxo, e 0,699 ± 0,083 contra 0,694 por âncora. A vantagem do modelo depende de ter visto o fluxo no treino.
- **Calibração.** P(não OK) tem ECE 0,010 e Brier 0,055, com leve subconfiança entre 0,5 e 0,9.
- **Referência externa.** A Random Forest do notebook da professora registrou macro-F1 de teste de cerca de 0,755, com reajuste em treino+validação. É da mesma ordem dos 0,750 obtidos aqui com ajuste só no treino.

### Lavagem
- **Desempenho.** No teste, a AP é 0,464, contra 0,0064 do baseline "taxa do formato" e 0,0011 da prevalência. No limiar congelado (0,0910), a precisão é 0,627, o recall 0,407 e o F1 0,494, com 231 falsos positivos em 862.792 transações (2,7 por 10 mil).
- **Capacidade de investigação.** Investigando 1.000 alertas por dia, o recall seria de 0,54 e 0,62 nos dois dias do teste.
- **Leve queda no tempo.** A AP cai de 0,499 na validação para 0,464 no teste.
- **Não linearidade.** A regressão logística fica em 0,19, então a interação entre histórico de contas e formato pesa.
- **Recall por grupo.** O recall global esconde três grupos muito diferentes:
  - nas 8 tipologias de `HI-Small_Patterns.txt`, vai de 0,55 (BIPARTITE) a 0,72 (FAN-OUT);
  - nos 371 positivos do teste que não pertencem a nenhum padrão (39%), é de 0,019;
  - nas tentativas iniciadas antes do teste é de 0,73, e nas tentativas novas, 0,52.
- **Cauda.** A AP de 0,969 na cauda é inflada pela base de 59% de lavagem e não representa operação.

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
- **Contas.** Nenhum atributo de conta revela a resposta. O tipo de entidade e o número de contas da entidade têm AP de validação de 0,0011 a 0,0017, contra prevalência de 0,0011, e lift máximo de 3,3. Contas e padrões nunca entram como atributo.
- **Padrões e episódios.**
  - 1.968 dos 5.177 positivos não aparecem em `HI-Small_Patterns.txt`.
  - 206 das 370 tentativas atravessam a fronteira entre períodos. 64% das linhas de padrão do teste vêm de tentativas iniciadas no treino ou na validação, o que torna o recall nessas linhas otimista. Por isso o relatório separa as tentativas novas.
- **Arquivos.** Transações, contas e padrões foram extraídos do `.rar` da professora. SHA-256:

  | Arquivo | SHA-256 |
  |---|---|
  | `HI-Small_Trans.zip` | `93c9d651…5179` |
  | `HI-Small_accounts.csv` | `78680852…b014` |
  | `HI-Small_Patterns.txt` | `2c546b5c…f39b` |
- **Câmbio.** É estimado no treino pela mediana das razões recebido/pago entre moedas diferentes. O fuso dos dados é desconhecido e assumido como UTC.

### Fusão
- Não há vínculo entre as fontes (sem chave comum e sem sobreposição temporal). Nenhuma métrica de fraude ligada à rede foi produzida. O que falta está listado em `CONTRATO_INTEGRACAO.md`.

## 6. Auditoria de 02/11/2026: correções e reuso do teste

Uma auditoria independente comparou a implementação com referências, regras explícitas e alternativas (XGBoost, Random Forest ajustada, HistGradientBoosting). Correções aplicadas:

| Correção | Onde | Evidência | Efeito |
|---|---|---|---|
| `z_valor_origem`: piso de 0,01 na variância do log-valor e somas deslocadas por conta | `src/ml/preparacao.py` (`_VAR_MIN_Z`) | Com variância ≈ 0 no histórico, \|z\| chegava a 1.939, e o cancelamento em E[x²] − E[x]² divergia da força bruta em 4 de 2.000 transações reais | AP de validação da lavagem 0,495 → 0,499 |
| Regressão logística com `tol=1e-6` | `src/ml/modelos.py` (`_lr`) | Com `tol=1e-4`, o lbfgs parava em 17 iterações na lavagem | AP de validação 0,165 → 0,19 (continua candidata derrotada) |
| Previsões de menos de 1.000 linhas com 1 thread | `src/ml/modelos.py` (`CabecaClassificacao.probabilidades`) | RF da rede, 1 linha: 27,7 ms com `n_jobs=4` e 8,8 ms com 1 | Resultado idêntico; treino e lotes grandes inalterados |
| Recall por tipologia e por tentativa nova | Contas e padrões disponíveis no `ml_config.local.toml` | O recall global misturava tipologias (cerca de 70%) com positivos sem padrão (cerca de 2%) | Seção 4 acima |
| Testes de força bruta dos atributos | `testes/ml/test_referencia_financeira.py` | — | O motor vetorizado é conferido contra filtros diretos |

**Reuso do teste.** O treino continua sem ler rótulos do teste, e a escolha continua na validação. Mas o teste já foi consultado em três momentos:
- na avaliação de 26/10;
- na comparação de 9 candidatos feita pela auditoria;
- nesta reavaliação.

Além disso, o protocolo foi desenhado depois de olhar a distribuição de rótulos de todos os dias. Por isso os números de teste não são uma avaliação inédita. Antes de trocar o modelo de qualquer tarefa, é preciso congelar o candidato pela validação e medi-lo uma única vez num período novo:
- **rede:** telemetria posterior a 05/10/2026;
- **lavagem:** uma replicação declarada, por exemplo o HI-Medium, já que o HI-Small não tem outro período limpo.

**Divergência corrigida em 09/11/2026.** As somas em USD do cálculo em lote vinham de prefixos acumulados sobre todo o histórico e perdiam precisão por cancelamento. No teste do HI-Small, a força bruta mostrou até 5,0% de erro em `soma_env_origem_usd_24h` e `razao_saida_entrada_24h`; no HI-Large, até 27%. Agora as somas acumuladas recomeçam em cada conta (`src/ml/preparacao.py`, `_IndiceEventos`): o erro contra a força bruta fica abaixo de 1e-6 nas 49 colunas, e o lote coincide com o cálculo incremental. O modelo atual não foi retreinado. Recalculado com o lote corrigido, o teste do HI-Small dá score com diferença máxima de 8·10⁻¹⁷, os mesmos 620 alertas e a mesma AP (0,4640). Detalhes em `docs/ml/hi_large/RELATORIO_HI_LARGE.md`, seção 3.4.

**Alternativas medidas pela auditoria** (não adotadas):
- **Rede:** XGBoost, HistGradientBoosting e RF com 50 árvores empatam com a RF atual (diferença de macro-F1 dentro do bootstrap por fluxo), mas são de 3 a 20× menores.
- **Lavagem:** o XGBoost teve AP maior que a RF, mesmo com o mesmo número de tentativas de busca. Fica como candidato para a confirmação acima.

