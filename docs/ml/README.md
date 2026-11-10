# Módulo de ML do NodeWatch (`src/ml`)

É uma arquitetura única e modular, em scikit-learn: um codificador por fonte de dados e uma cabeça por tarefa, tudo salvo em um único artefato (`artefatos_ml/modelo_unificado.joblib`).

| cabeça | dados | saída | status |
| --- | --- | --- | --- |
| `estado_rede` | `dataset_final.csv` (telemetria por fluxo) | `OK`/`RISCO`/`FALHA` da **próxima medição**, probabilidades e `score_alerta_rede` | treinada |
| `estado_rede__com_classe_atual` | idem, mais `classe_atual` | variante comparativa | treinada |
| `lavagem` | IBM AML HI-Small (sintético) | `score_lavagem`, alerta e motivos verificáveis | treinada |
| `fusao_rede_transacao` | transações vinculadas à telemetria | — | **indisponível** (ver [CONTRATO_INTEGRACAO.md](CONTRATO_INTEGRACAO.md)) |

Cada cabeça disponível foi treinada e avaliada **separadamente**, nos seus próprios dados. As fontes não têm amostras em comum, então o modelo não aprendeu nenhuma relação entre rede e lavagem.

Alguns termos têm significado preciso:
- `score_alerta_rede` é o estado de rede não-OK previsto, e não fraude;
- `score_lavagem` é uma pontuação aprendida em dados sintéticos, e não fraude confirmada.

Resultados: [RELATORIO_ML.md](RELATORIO_ML.md). Dicionário de dados: [DICIONARIO_DADOS.md](DICIONARIO_DADOS.md).

Avaliação do IBM AML **HI-Large** (compatibilidade, protocolo purgado por tentativa e comparação com o modelo atual): [hi_large/RELATORIO_HI_LARGE.md](hi_large/RELATORIO_HI_LARGE.md). Conclusão: o HI-Large é compatível em formato e rótulo, mas não há melhora confirmada. Treinar só com ele fica abaixo do modelo atual. O HI-Small mais o HI-Large com XGBoost superou o atual de 13 a 16/08/2022, mas não se confirmou de 17 a 23/08 (hipótese registrada antes). A floresta com as duas bases ficou acima nos dois períodos, mas é só um resultado exploratório (hipótese secundária). O artefato não foi trocado. Trilha de auditoria de cada execução: [hi_large/REGISTRO_EXPERIMENTOS_E_TREINOS.md](hi_large/REGISTRO_EXPERIMENTOS_E_TREINOS.md).

## Instalação

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-ml.txt
```

As versões fixadas em `requirements-ml.txt` são as usadas no treino documentado: Python 3.14.0, scikit-learn 1.9.1, pandas 3.1.0 e numpy 2.5.4.

## Configuração

1. Copie `ml_config.exemplo.toml` para `ml_config.local.toml`. A cópia é ignorada pelo git.
2. Ajuste os caminhos:
   - `[rede].arquivos`: um ou mais CSVs `rede_v1`;
   - `[financeiro].transacoes`: `HI-Small_Trans.csv` ou o `.zip` que o contém;
   - opcionalmente `contas` e `padroes`.
3. Os arquivos originais nunca são alterados.

O arquivo de padrões serve só para auditoria e para o recall por tipo de padrão. Ele **nunca** vira atributo, porque é a própria resposta. Sem ele, a avaliação da lavagem marca o recall por padrão como pendente. Com ele, a avaliação separa três grupos: as tipologias, os positivos que não pertencem a nenhum padrão e as tentativas iniciadas antes do teste ou novas.

### Dados usados nos resultados versionados

Os dados não estão no repositório; vêm do `.rar` entregue pela professora. Confira os hashes (`sha256sum` ou `Get-FileHash`) antes de comparar resultados:

| Arquivo | SHA-256 | Uso |
|---|---|---|
| `dataset_final.csv` | `125453f154616b6d02587f9577aab14828002ebc31d8ae053771780058d9b997` | Estado de rede |
| `HI-Small_Trans.zip` | `93c9d65156a28596c756bd1395531e231c5950bbbdbfe665500bc866ed595179` | Lavagem |
| `HI-Small_accounts.csv` | `786808526e33cfc441212dd6fccda7edfc24172149bed59c6ef59b186836b014` | Auditoria de contas |
| `HI-Small_Patterns.txt` | `2c546b5ce6009e73851f0139af053cf845f08bf92f3bc82fe1eb937dec2ef39b` | Auditoria e recall por padrão |

## Comandos

Rode da raiz do projeto, com o Python do `.venv`:

```bash
python -m src.ml.cli auditar --fonte todas
```
Audita os dados e grava JSON e MD em `artefatos_ml/auditoria`.

```bash
python -m src.ml.cli treinar --tarefa todas
```
Ajusta cada configuração no treino e escolhe configuração e limiar na validação.

```bash
python -m src.ml.cli avaliar --tarefa todas
```
Avalia uma única vez no teste, com o artefato congelado.

```bash
python -m src.ml.cli prever --tarefa estado_rede --entrada novo.csv --saida previsoes_rede.csv
```
Faz inferência sem `alvo`/`split`. Aceita vários CSVs.

```bash
python -m src.ml.cli prever --tarefa lavagem --entrada transacoes.csv --historico HI-Small_Trans.zip --saida previsoes_lavagem.csv
```
O histórico das contas vem de `--historico`. Desse arquivo só entram transações anteriores à primeira transação a pontuar.

```bash
python -m src.ml.cli exemplos
python -m src.ml.cli relatorio
python -m src.ml.cli documentar
python -m src.ml.cli tarefas
python -m pytest testes/ml
```
- `exemplos` gera entradas derivadas sem rótulo e as previsões delas, em `artefatos_ml/exemplos`.
- `relatorio` gera `docs/ml/RELATORIO_ML.md` a partir dos resultados salvos.
- `documentar` gera o dicionário de dados e `docs/ml/esquemas/*.json`.
- `tarefas` mostra o status das cabeças e o que falta para a fusão.

### Explorar no navegador

`python src/sentinel_ai.py` (com `requirements.txt` e `requirements-ml.txt` instalados) e abra `http://127.0.0.1:5000/#ml`. A seção **Machine Learning** do painel lê as previsões de `artefatos_ml/exemplos`, `artefatos_ml/previsoes`, `artefatos_ml/teste` e `docs/ml/exemplos`, importa CSVs de previsões e mostra a avaliação oficial de `artefatos_ml/resultados`. Não treina nem altera nada e não precisa da chave do Gemini. Detalhes na seção 7 de [`docs/ui/README-INTERFACE.md`](../ui/README-INTERFACE.md).

### Eventos (previsões novas, sem treino)

A área `#ml/eventos` e a API `/api/ml/eventos` recebem transações, medições `rede_v1` e vínculos como eventos, com fila limitada, um trabalhador e estado persistido. O financeiro usa `src/ml/incremental.py`, que calcula os mesmos 49 atributos sem reler o histórico. Há replay histórico, um produtor de exemplo (`scripts/produtor_eventos_exemplo.py`) e um laboratório de simulação da integração rede ↔ transação. Contratos, regras e endpoints: [EVENTOS.md](EVENTOS.md). Desempenho e equivalência: [BENCHMARK_EVENTOS.md](BENCHMARK_EVENTOS.md), gerado por `python scripts/benchmark_eventos.py`.
- `pytest testes/ml` roda os testes do módulo, todos com dados sintéticos. `test_referencia_financeira.py` compara os atributos vetorizados com uma referência por força bruta (`testes/ml/referencia_financeira.py`).

### O que está versionado em `docs/ml`

`artefatos_ml/` é ignorado pelo git. Por isso, depois de `treinar`, `avaliar`, `exemplos` e `relatorio`, uma parte das saídas é copiada para `docs/ml`:

| Em `docs/ml` | Origem |
|---|---|
| `resultados/*.json` | Cópias de `artefatos_ml/resultados/*.json`, de `artefatos_ml/auditoria/auditoria_*.json` e de `artefatos_ml/metadados_modelo.json`, com os caminhos absolutos trocados pelo nome do arquivo |
| `exemplos/previsoes_rede_amostra.csv` | Cabeçalho e 200 primeiras linhas de `artefatos_ml/exemplos/previsoes_rede_exemplo.csv`, gerado por `exemplos` a partir das linhas do teste sem `alvo`/`split`, embaralhadas com a semente 42 |
| `exemplos/previsoes_lavagem_amostra.csv` | Cabeçalho e 200 primeiras linhas de `artefatos_ml/exemplos/previsoes_lavagem_exemplo.csv`, gerado a partir das transações de 10/09/2022 sem rótulo, com o histórico anterior a esse dia (`--historico`) |
| `exemplos/*.relatorio.json` | Relatórios de inferência dessas previsões, com os caminhos absolutos trocados pelo nome |
| `RELATORIO_ML.md` | Gerado por `relatorio`, que acrescenta `notas_relatorio.md` ao final |

As amostras mostram o formato da saída, não uma seleção representativa.

## Protocolo, em resumo

### Rede
- **Divisão temporal:** usa a coluna `split` (treino < validação < teste, com lacunas ≥ 1 h). Os mesmos 135 fluxos aparecem nos três períodos.
- **Fluxos inéditos:** há uma avaliação separada com GroupKFold por `id_fluxo` e por `anchor_id`. Ela treina no período de treino e testa no período de teste dos grupos retirados.
- **Sentinelas:** o `-1` é sentinela só onde a auditoria confirma. Em `delta_ttl_clip`, valores negativos são legítimos.
- **Ajustes:** imputação, remoção de constantes (`ttl_reset`), log e escala são ajustados só no treino.

### Lavagem
- **Divisão temporal por dia:**
  - treino 01–06/09;
  - validação 07–08/09;
  - teste 09–10/09.

  A partir de 11/09 o gerador quase não produz atividade normal (base de 58–73% de lavagem). Esse trecho é reportado à parte, como cauda.
- **Atributos:** cada transação só enxerga transações de minutos **estritamente anteriores**.
- **Câmbio e categorias:** aprendidos no treino.
- **Amostragem:** os negativos do treino são subamostrados (20%) com peso 5. Validação e teste preservam a distribuição original.

### Seleção
- **Configuração:** rede por macro-F1 na validação; lavagem por average precision na validação.
- **Limiar:** máximo F1 na validação. Não houve custos nem capacidade fornecidos.

## Estrutura

```
src/ml/config.py       configuração (TOML + padrões)
src/ml/esquemas.py     contratos versionados e validação
src/ml/ingestao.py     leitura de CSVs de rede, HI-Small, contas e padrões
src/ml/auditoria.py    verificações de dados refeitas a cada execução
src/ml/preparacao.py   sentinelas, pipelines e atributos financeiros point-in-time
src/ml/modelos.py      grades, cabeças, ModeloUnificado, fusão bloqueada
src/ml/avaliacao.py    métricas (classes, eventos, alertas, calibração, PR, top-k)
src/ml/experimentos.py treino/validação/teste e grupos inéditos
src/ml/previsao.py     inferência sem reajuste, deriva (PSI) e motivos
src/ml/integracao.py   contrato e junção temporal rede ↔ transação
src/ml/eventos.py      contrato de eventos (envelope, identidade, validação)
src/ml/incremental.py  estado financeiro incremental (atributos sem reconstruir o histórico)
src/ml/servico_eventos.py  fila limitada, trabalhador, saídas e instantâneo
src/ml/replay.py       replay histórico em ordem cronológica
src/ml/simulacao.py    laboratório de SIMULAÇÃO da integração rede ↔ transação
src/ml/relatorio.py    relatório e dicionário gerados dos resultados
src/ml/cli.py          linha de comando
```

O artefato `joblib` executa código ao ser carregado. Carregue apenas artefatos gerados por você.
