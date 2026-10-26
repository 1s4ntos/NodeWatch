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

O arquivo de padrões serve só para auditoria e para o recall por tipo de padrão. Ele **nunca** vira atributo, porque é a própria resposta.

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
- `pytest testes/ml` roda os testes do módulo, todos com dados sintéticos.

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
src/ml/relatorio.py    relatório e dicionário gerados dos resultados
src/ml/cli.py          linha de comando
```

O artefato `joblib` executa código ao ser carregado. Carregue apenas artefatos gerados por você.
