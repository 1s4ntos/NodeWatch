# Modelo de ML distribuído com o repositório

Esta pasta guarda o **modelo treinado** que o painel do analista usa, para que qualquer pessoa que clone o repositório consiga executar uma análise nova sem treinar nada e sem o dataset.

| Arquivo | O que é |
|---|---|
| `modelo_unificado.joblib` | O `ModeloUnificado` (`src/ml/modelos.py`): cabeça `lavagem` (Random Forest), preparador `financeiro` (câmbio, categorias, colunas) e as cabeças de rede |
| `metadados_modelo.json` | Resumo legível do modelo: hiperparâmetros, colunas, limiar, períodos, critérios de escolha |
| `MANIFESTO_MODELO.json` | SHA-256 e tamanho do modelo, versões das bibliotecas com que foi salvo, origem e licença dos dados, endereço de download |

## Como ele chega ao `artefatos_ml/`

Na primeira execução, `python -m src.ml.provisionamento` (chamado também ao iniciar `python src/sentinel_ai.py` e pelo Inicializador Rápido):

1. confere se scikit-learn, NumPy, pandas e joblib estão instalados e compatíveis com o manifesto (scikit-learn **igual**; os demais na mesma versão principal);
2. confere o SHA-256 de `modelos/modelo_unificado.joblib`; se o arquivo faltar ou não bater, baixa a versão do manifesto (ou de `NODEWATCH_MODELO_URL`) e confere de novo;
3. copia o modelo e os metadados para `artefatos_ml/` de forma atômica;
4. carrega o modelo e faz uma previsão de teste.

Um modelo treinado na própria máquina (`python -m src.ml.cli treinar`) fica em `artefatos_ml/` e **nunca é sobrescrito**: o comando só o valida.

## Versão

| | |
|---|---|
| Versão da cabeça `lavagem` | `lavagem-20261102T083253Z` |
| Algoritmo | Random Forest (scikit-learn): 100 árvores, folha mínima 50, 50% da amostra por árvore |
| Atributos | 49 (*point-in-time*) |
| Limiar de alerta | 0,0910 (máximo F1 na validação) |
| Treinado com | transações de 01 a 06/09/2022 do IBM AML HI-Small |
| Bibliotecas | Python 3.14.0, scikit-learn 1.9.1, NumPy 2.5.4, pandas 3.1.0, joblib 1.6.0 |
| SHA-256 do modelo | ver `MANIFESTO_MODELO.json` |

Os resultados de treino e de avaliação deste modelo estão em `docs/ml/resultados/` e no manual `docs/MANUAL_TECNICO_E_ESTUDO_NODEWATCH.md`.

**Diferença em relação ao arquivo do treino original:** os metadados internos tinham o caminho absoluto dos arquivos de dados na máquina de quem treinou; aqui ficou só o nome do arquivo. Nada do que o modelo calcula mudou: com uma thread, as previsões são idênticas bit a bit às do original; com várias threads, a diferença (≈ 3e-16) é a mesma que o original tem consigo mesmo, e os alertas são os mesmos.

## Origem dos dados e licença

- **Dados de treino:** *IBM Transactions for Anti Money Laundering (AML)*, arquivo HI-Small (sintético, gerado por simulador), publicado em <https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml>.
- **Licença dos dados:** CDLA-Sharing-1.0 (<https://cdla.dev/sharing-1-0/>).
- **Licença do modelo:** o modelo é um *Result* (saída do uso computacional dos dados). A seção 3.5 da CDLA-Sharing-1.0 diz que o acordo não impõe obrigações ou restrições ao uso ou à publicação de *Results*. O modelo guarda limiares e contagens agregadas das árvores, não linhas do dataset. **Os dados em si não estão no repositório.**
- **Citação pedida pelos autores do dataset:** Altman et al., *Realistic Synthetic Financial Transactions for Anti-Money Laundering Models*, arXiv:2306.16424 (NeurIPS 2023).

## Treinar de novo (opcional)

Não é preciso para usar o painel. Para reproduzir o treino:

1. Baixe `HI-Small_Trans.csv`, `HI-Small_Patterns.txt` e `HI-Small_accounts.csv` do endereço acima.
2. `copy ml_config.exemplo.toml ml_config.local.toml` e aponte `[financeiro].transacoes`, `contas` e `padroes` para os arquivos.
3. `python -m src.ml.cli treinar --tarefa lavagem` e depois `python -m src.ml.cli avaliar --tarefa lavagem`.

O novo modelo vai para `artefatos_ml/` e passa a ser usado. Para distribuí-lo, um mantenedor roda `python -m src.ml.provisionamento --preparar-distribuicao` (copia para esta pasta, sem caminhos da máquina, e regrava o manifesto), roda os testes e faz commit dos três arquivos juntos. O teste `test_manifesto_do_repositorio_confere_com_o_modelo_distribuido` falha se o modelo e o manifesto não corresponderem.

> **Segurança:** arquivos `joblib` executam código ao serem carregados. O NodeWatch só carrega o modelo depois de conferir o SHA-256 com o manifesto versionado. Não substitua este arquivo por um de origem desconhecida.
