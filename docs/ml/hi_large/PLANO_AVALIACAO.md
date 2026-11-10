# Plano de avaliação do HI-Large (registrado antes dos experimentos)

Registrado em 09/11/2026, antes de qualquer contagem de rótulos, treino ou métrica com o HI-Large. Até este ponto, só foram vistos o cabeçalho, as primeiras e as últimas linhas dos três arquivos e a contagem de tentativas no arquivo de padrões. O hash deste arquivo fica gravado no resultado do perfil (`resultados/a_perfil.json`). Qualquer desvio é registrado no relatório final como **desvio do plano**.

## Perguntas

1. Os três arquivos do HI-Large são compatíveis com o módulo financeiro em conteúdo, rótulos, período e significado?
2. O modelo atual, treinado no HI-Small e congelado, generaliza para o HI-Large?
3. Treinar com o HI-Large, sozinho ou junto com o HI-Small, melhora a pontuação em dados que não foram usados para ajustar nada?
4. Com a mesma busca e as mesmas divisões, alguma família (logística, Random Forest, HistGradientBoosting, XGBoost) é melhor?

## Dados e divisões

- **HI-Large:** cobre de 2022-08-01 a 2022-11-05. Por limite de memória e tempo nesta máquina, a modelagem usa os **12 primeiros dias corridos**, com estado iniciado vazio no dia 1, às 00:00. Isso reproduz a profundidade de histórico do HI-Small, em que o treino também começa no dia 1.

| Partição | Dias do HI-Large | Papel |
|---|---|---|
| Treino | 1 a 6 (01 a 06/08/2022) | Ajuste dos modelos e do preparador (câmbio, categorias, quantis) |
| Validação | 7 e 8 (07 e 08/08) | Escolha de modelo, hiperparâmetros, parada antecipada e limiar |
| Teste | 9 e 10 (09 e 10/08) | Avaliação única, depois de todas as escolhas |
| Reserva | 11 e 12 (11 e 12/08) | Confirmação única, só dos modelos escolhidos na validação |

- **Regra de cauda**, só por volume: dias com menos de 1% do volume mediano diário saem das métricas, como no HI-Small. A regra não usa rótulos.
- **HI-Small:** divisões atuais do NodeWatch (treino 01 a 06/09, validação 07 e 08/09, teste 09 e 10/09). O teste do HI-Small **já foi consultado** e só serve como descrição.
- Os dias 13 em diante do HI-Large são perfilados, mas não entram na modelagem.

## Atributos e preparadores

- Os 49 atributos *point-in-time* do NodeWatch, calculados pelo `EstadoFinanceiro` (`src/ml/incremental.py`), minuto a minuto. É o mesmo caminho de *Analisar dataset*, com equivalência testada contra o lote e a força bruta.
- **P_S:** o preparador do artefato atual (`lavagem-20261102T083253Z`), usado sem alteração no modelo congelado.
- **P_L:** o preparador ajustado só no treino do HI-Large, com `PreparadorFinanceiro.ajustar` e `registrar_quantis`.
- Se câmbio e categorias de P_S e P_L coincidirem (diferença relativa < 1e-9 e mesmas categorias), uma única passada de atributos atende aos dois. Se não, são duas passadas.
- **Nunca viram atributo:** rótulos, arquivo de padrões, arquivo de contas (entidade, nome, banco) e qualquer agregado calculado com o dataset inteiro.

## Treino e candidatos

- O treino mantém todos os positivos e 20% dos negativos, com semente 42 e peso 5, como no NodeWatch. Validação, teste e reserva mantêm a distribuição original. **Contingência:** se faltar memória, usar 10% dos negativos com peso 10 e registrar o desvio.
- Fontes de treino: **S** (modelo atual congelado, sem retreino), **L** (treino do HI-Large) e **S+L** (treinos do HI-Small e do HI-Large juntos, cada um com os atributos do seu próprio preparador).
- A grade é a mesma para L e S+L:

| Família | Configurações |
|---|---|
| Regressão logística | C ∈ {0,1; 1,0}, `tol=1e-6`, pipeline atual |
| Random Forest | 100 árvores e folha 50 (produção); 200 árvores e folha 10 (melhor da auditoria) |
| HistGradientBoosting | 300 iterações, `lr` 0,1, folhas 31 e 63, L2 1,0 (produção) |
| XGBoost | `hist` em CPU, `lr` 0,1, profundidade {6, 8}, `min_child_weight` 10, parada antecipada de 50 rodadas pela AP na validação, até 1.000 árvores. Só entra se instalar fora do `.venv` |

- **Referências:** prevalência, taxa do formato (do treino) e regras explícitas da auditoria. As regras são F2 (contagem de motivos ≥ k, com k escolhido na validação) e F3 (melhor conjunção na validação).

## Escolha e decisão

- Dentro de cada fonte, o modelo escolhido é o de maior AP na validação do HI-Large. O limiar é o de máximo F1 na validação.
- O modelo congelado S é avaliado no limiar dele (0,0910) e, à parte, com o limiar recalculado na validação do HI-Large.
- **Critério de melhora**, fixado agora: o escolhido de L ou de S+L melhora o módulo se a AP dele superar a do modelo congelado no teste do HI-Large **nos dois dias, separadamente**, e se a vantagem se repetir na reserva. O intervalo de confiança por *bootstrap* pareado, agrupado por conta de origem com 1.000 reamostras, é informação complementar.
- Comparações entre famílias no teste são descritivas. A decisão não é tomada por elas.
- **Generalização entre fontes:** S→L (modelo congelado no teste do HI-Large) e L→S (escolhido de L no teste do HI-Small, já consultado). As duas são reportadas separadamente da avaliação combinada.

## Métricas e medições

- Prevalência, AP, precisão, recall e F1 no limiar da validação, matriz de confusão, número de alertas, falsos positivos por 10 mil e recall@k por dia.
- Recall por tipo de padrão, para positivos sem padrão e por tentativa (iniciada antes do período × nova). O arquivo de padrões serve só para isso.
- Tempos separados: leitura e particionamento, cálculo de atributos, treino de cada candidato e inferência (em lote e de uma linha), com o ambiente registrado.

## Vazamento: verificações previstas

- Atributos só com minutos estritamente anteriores, o que é garantido pelo `EstadoFinanceiro`.
- Preparador e quantis ajustados só no treino.
- Padrões, contas e rótulos fora dos atributos.
- Tentativas que atravessam a fronteira entre partições: o recall das tentativas novas é reportado à parte.
- Identidade das contas por `banco-conta`, com banco numérico, como no NodeWatch. Antes, confere-se se a conversão do banco para número funde códigos distintos.
