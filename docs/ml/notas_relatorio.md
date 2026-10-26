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
