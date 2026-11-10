# Emenda 3: confirmar a S+L corrigida num segundo período intocado

Registrada em 09/11/2026, **antes** de calcular qualquer atributo, score ou métrica dos dias 17 a 23 de agosto de 2022. Foi escrita **depois** de conhecidos os resultados do teste final 2 (Emenda 2).

## Por que

No teste final 2 (13 a 16/08), a S+L refeita com o lote corrigido (XGBoost, profundidade 6) atendeu o critério da Emenda 2. Esse critério olha um único período. Além disso, a Emenda 2 foi escrita depois da rodada 1, em que a S+L antiga não se confirmou na reserva.

Esta emenda pede uma segunda confirmação, num período novo, com modelos e limiares já congelados.

## O que já se sabe do período

Só o perfil dos dados:

- transações e positivos por dia (`a_perfil.json` e `PARTICOES.md`);
- quantas tentativas têm eventos depois do dia 12 (`a4_tentativas.json`).

Nenhum atributo, score ou métrica foi calculado para esses dias.

## Período

- **Dias:** 17 a 23/08/2022, sete dias seguidos, de quarta a terça, com um fim de semana.
- **Atributos:** o estado incremental refeito do dia 1, com os dois preparadores, em `atributos_S_final3` e `atributos_L_final3`.
- **Conferência antes da consulta:** a passada grava também o dia 16/08, que precisa ser idêntico ao de `atributos_*_final2`. Os dias 17 a 23 precisam ter todas as linhas e todos os positivos da partição. Se alguma conferência falhar, a consulta não é feita.
- **Purga da Emenda 1:** saem os positivos de tentativas iniciadas antes de 17/08/2022.

## Modelos congelados

Nada é retreinado. Os limiares são os da validação de 07 e 08/08. O script confere o SHA-256 de cada arquivo antes de pontuar. Os arquivos ficam em `artefatos_ml/hi_large/modelos/`, salvo o modelo atual.

| Papel | Modelo | Arquivo | SHA-256 | Limiar |
|---|---|---|---|---|
| Comparação | Modelo atual S (`lavagem-20261102T083253Z`) | `artefatos_ml/modelo_unificado.joblib` | `28a13a1873f4896a0ede445070cf5adff907b88007e3f25ab4ca5cf6dbcdb4aa` | 0,0910, do artefato; 0,0862 também é reportado |
| **Hipótese principal** | S+L corrigida, XGBoost profundidade 6 | `corrigido__S_L__xgboost[max_depth=6,min_child_weight=10].joblib` | `999890b9ec9e4b6c229485b794a97093a1e530c3dc72f8f630937ffb6173c09c` | 0,1269 |
| Hipótese secundária | S+L corrigida, floresta de 100 árvores e folha 50 | `corrigido__S_L__random_forest[n_estimators=100,min_samples_leaf=50,max_samples=0.5].joblib` | `85380b56019abc80951eaa1e782919e5d4c3aef40016f339f1b60566f0037134` | 0,0519 |
| Descritivo | L, XGBoost profundidade 8 | `L__xgboost[max_depth=8,min_child_weight=10].joblib` | `3facedae9dd7398c370de475a67137d9a2be274473b97baa7096709ebeeea2b8` | 0,0956 |
| Descritivo | L, floresta de 100 árvores e folha 50 | `L__random_forest[n_estimators=100,min_samples_leaf=50,max_samples=0.5].joblib` | `ed8cef2306f430a53d6fc2642c85059bfcbbf54c334ee3ff54899883953c6618` | 0,0366 |
| Referência | Taxa do formato, do treino L | — | — | 0,0028 |

## Critério

**Principal.** A S+L corrigida com XGBoost **confirma** a melhora se, nos 7 dias purgados:

1. a AP for maior que a do modelo atual, com o intervalo de 95% excluindo zero. O intervalo vem do bootstrap pareado, com 1.000 reamostras de Poisson agrupadas por conta de origem e semente 42;
2. **e** a AP for maior em pelo menos 5 dos 7 dias.

**Secundário.** O mesmo critério para a floresta S+L. Responde se o ganho depende do XGBoost e não muda a conclusão principal.

**Descritivos:** L e a taxa do formato.

**Também reportados:**

- prevalência e AP por dia;
- precisão, recall, F1, matriz de confusão, alertas e falsos alertas por 10 mil, no limiar congelado;
- recall por grupo de positivos;
- AP sem purga;
- tempos.

## O que cada resultado permite concluir

- **Critério principal atendido:** a melhora da S+L corrigida terá aparecido em dois períodos independentes, 13 a 16/08 e 17 a 23/08. Isso sustenta propor a integração ao grupo. Mas **não troca o artefato** automaticamente: a troca exige decidir sobre o XGBoost e levar ao `treinar` o leitor em fluxo e o cálculo incremental.
- **Critério principal não atendido:** a melhora do teste final 2 não se confirma, e a S+L não é recomendada.
- **Em qualquer caso,** o período 17 a 23/08 é consultado **uma única vez** (`consultas.json`: `teste_final3`).

## Limites conhecidos antes

- O período é contíguo ao teste final 2 e fica a 11 dias do fim do treino. Não testa deriva ao longo de meses.
- A variação do treino entre sementes não é medida aqui.
