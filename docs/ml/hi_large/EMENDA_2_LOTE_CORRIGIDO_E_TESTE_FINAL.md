# Emenda 2: refazer o que dependia do lote antigo e criar um teste final novo

Registrada em 09/11/2026, **antes** de regenerar os dados afetados, de retreinar candidatos e de calcular qualquer atributo ou métrica dos dias 13 a 16 de agosto de 2022.

## O que dependia do cálculo antigo

A correção das somas por conta em `src/ml/preparacao.py` entrou às 05:17 (horário local). Os artefatos com horário anterior que usaram o cálculo em lote são:

| Artefato | Calculado | Usado em |
|---|---|---|
| `hismall_treino_S.parquet`: amostra de treino do HI-Small | Lote antigo, 03:17 | Treino dos 8 candidatos da fonte S+L |
| `hismall_teste_L.parquet`: teste do HI-Small com o preparador L | Lote antigo, 03:18 | `f_hismall.json`, só descritivo |
| `artefatos_ml/cache/financeiro_teste.parquet` | Lote antigo, 02/11 | O modelo atual no teste do HI-Small, só descritivo |

**Não dependem do lote** e continuam válidos:

- os atributos do HI-Large (`atributos_S` e `atributos_L`), que vêm do `EstadoFinanceiro`, incremental;
- os 8 candidatos da fonte L;
- o preparador L.

O modelo atual (`lavagem-20261102T083253Z`) foi treinado com o lote antigo e fica **preservado sem retreino**, como referência.

## O que será feito

1. **Regenerar os dois arquivos do HI-Small com o lote corrigido.** Os antigos ficam guardados com o sufixo `_lote_antigo`. A amostra é a mesma: semente 42, todos os positivos e 20% dos negativos, peso 5.
2. **Refazer a fonte S+L** com a mesma grade de 8 configurações, as mesmas sementes e a mesma escolha pela AP na validação purgada. O limiar sai do máximo F1 na mesma validação. As escolhas congeladas ficam em `escolhas_emenda2.json`, sem alterar `escolhas.json`.
3. **Não refazer a fonte L.**
4. **Não reconsultar** o teste (09 e 10/08) nem a reserva (11 e 12/08). Os resultados de lá ficam como **históricos**, e os de S+L foram obtidos com o lote antigo.

## Teste final novo: dias 13 a 16 de agosto de 2022

- **Período:** 13, 14, 15 e 16/08/2022, que nunca foram usados. Até aqui, só o perfil viu a contagem de transações e de positivos por dia.
- **Atributos:** o estado incremental refeito do dia 1, para os dois preparadores, gravado em `atributos_S_final2` e `atributos_L_final2`. O dia 12 (12/08) também é gravado, só para conferir que a nova passada reproduz o arquivo existente.
- **Purga:** saem os positivos de tentativas iniciadas antes de 13/08/2022, pela regra da Emenda 1.
- **Avaliados uma única vez:**
  - o modelo atual S, no limiar do artefato (0,0910) e no limiar recalculado na validação do HI-Large (0,0862);
  - o escolhido de L (XGBoost, profundidade 8, de `escolhas.json`);
  - o escolhido da S+L refeita (de `escolhas_emenda2.json`);
  - a taxa do formato.
  - Só descritivo: o escolhido da S+L antiga, para mostrar o efeito da correção.
- **Critério de melhora:** o candidato precisa ter AP maior que a do modelo atual em todo o período, com o intervalo de confiança de 95% do bootstrap pareado, agrupado por conta de origem, excluindo zero. Precisa também ter AP maior em pelo menos 3 dos 4 dias.

## Descritivo

`f_hismall` é refeito com os atributos corrigidos. O teste do HI-Small já foi consultado.
