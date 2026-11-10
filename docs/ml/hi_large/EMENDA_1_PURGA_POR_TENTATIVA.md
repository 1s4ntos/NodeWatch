# Emenda 1 ao plano: avaliação purgada por tentativa

Registrada em 09/11/2026, **antes de qualquer treino de modelo e de qualquer métrica de modelo com o HI-Large**. Até este ponto, foram executados:

- o perfil dos três arquivos e a partição por dia;
- o ajuste do preparador do treino do HI-Large (câmbio, categorias e taxa por formato);
- as duas passadas de atributos e os atributos do HI-Small.

Nenhum modelo foi ajustado nem pontuado no HI-Large. O plano original continua valendo, com a mudança abaixo.

## Motivo

1. **As tentativas são longas.** O perfil mostrou que as tentativas do HI-Large duram 27 dias na mediana, contra 3 dias no HI-Small. Das 1.810 tentativas presentes na janela de 12 dias, 1.552 atravessam a fronteira entre partições.
2. **O risco de inflar a avaliação.** Com a divisão só pelo tempo, uma mesma tentativa teria eventos no treino (com rótulo) e na validação, no teste e na reserva. O modelo poderia reconhecer a continuação de um esquema que já viu, e a métrica ficaria otimista.
3. **Particionar não resolve.** Separar o processamento por dia só serve para calcular atributos de um arquivo fora de ordem. Isso não impede, por si só, esse tipo de vazamento.

## Regra

- **Data de início:** cada tentativa do arquivo de padrões recebe a partição do seu **primeiro** evento, que é o seu minuto mínimo.
- **Avaliação purgada (métrica principal):** em validação, teste e reserva, as transações positivas de tentativas iniciadas **antes** do começo do período saem do conjunto avaliado. São a continuação de esquemas que já tinham eventos em partições anteriores.
- **Mantidos:** todos os negativos e os positivos **sem padrão**. Estes não podem ser agrupados por tentativa, porque o arquivo não diz a qual esquema pertencem. A limitação vai declarada.
- **Treino:** fica como está. Os eventos do treino de uma tentativa que continua depois só aparecem no treino, porque a continuação sai das avaliações.
- **Resultado:** nenhuma tentativa com padrão conhecido tem eventos no treino e no conjunto avaliado. A mesma regra vale para validação × teste e para teste × reserva.

## O que muda

- **Escolha e limiar:** a escolha do modelo (AP), a parada antecipada do XGBoost, o limiar de máximo F1 e as regras F2 e F3 usam a validação **purgada**.
- **Decisão:** o critério de melhora do plano é aplicado ao teste **purgado** de cada dia e à reserva **purgada**.
- **Secundário:** as métricas sem purga continuam reportadas, à parte, e o recall por tentativa (iniciada antes × nova) mostra a diferença.
- **Uso dos padrões:** só definem quais linhas são avaliadas. Nunca viram atributo, e os atributos continuam sendo calculados com todas as transações anteriores ao minuto, como na inferência real.
