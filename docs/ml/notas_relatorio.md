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
