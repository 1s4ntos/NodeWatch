# Avaliação do IBM AML HI-Large no módulo financeiro

Esta pasta guarda a avaliação feita para responder se os arquivos `HI-Large_Trans.csv`, `HI-Large_Patterns.txt` e `HI-Large_accounts.csv` melhoram o modelo de lavagem do NodeWatch.

| Arquivo | Conteúdo |
|---|---|
| [`PLANO_AVALIACAO.md`](PLANO_AVALIACAO.md) | Plano registrado **antes** dos experimentos: divisões, candidatos, métricas e critério de decisão |
| [`EMENDA_1_PURGA_POR_TENTATIVA.md`](EMENDA_1_PURGA_POR_TENTATIVA.md) | Emenda registrada antes de qualquer treino: avaliação purgada por tentativa |
| [`EMENDA_2_LOTE_CORRIGIDO_E_TESTE_FINAL.md`](EMENDA_2_LOTE_CORRIGIDO_E_TESTE_FINAL.md) | Emenda registrada depois da correção do lote: refaz a S+L e cria o teste final novo (13 a 16/08) |
| [`EMENDA_3_SEGUNDO_TESTE_FINAL.md`](EMENDA_3_SEGUNDO_TESTE_FINAL.md) | Emenda registrada antes de calcular os dias 17 a 23/08: confirma os modelos congelados num segundo período |
| [`PARTICOES.md`](PARTICOES.md) | Contagens por partição diária (165 arquivos) |
| [`RELATORIO_HI_LARGE.md`](RELATORIO_HI_LARGE.md) | Resultados medidos, interpretação, limitações, decisão e auditoria de fechamento |
| [`REGISTRO_EXPERIMENTOS_E_TREINOS.md`](REGISTRO_EXPERIMENTOS_E_TREINOS.md) | Trilha de auditoria: cada execução, com horário, tipo (treino, escolha, consulta ou conferência), hashes, desfecho e falhas |
| `resultados/*.json` | Resultados brutos de cada etapa, com ambiente e tempos |

O código está em `scripts/hi_large/`, e os testes, em `testes/ml/test_hi_large_avaliacao.py`. Nada disso altera o modelo usado pelo sistema (`artefatos_ml/modelo_unificado.joblib`) nem o caminho de treino do NodeWatch.

## Como reproduzir

Pré-requisitos:

- o `.venv` do NodeWatch (`requirements-ml.txt`);
- o artefato atual em `artefatos_ml/`;
- o HI-Small configurado em `ml_config.local.toml`;
- cerca de 25 GB livres em disco.

O XGBoost é opcional e **não é dependência do NodeWatch**. Esta avaliação usou a versão 3.4.1, instalada num diretório temporário fora do `.venv` (relatório, seção 12.5). Para reproduzir, instale a mesma versão num diretório à parte:

```bash
python -m pip install --target <pasta_xgboost> --no-deps xgboost==3.4.1
```

Rode da raiz do NodeWatch, nesta ordem. Os tempos medidos estão no relatório, seções 5.5 e 6.5: cerca de 12 min para ler e particionar, 3 min para as duplicatas, 11 min por passada de atributos de 12 dias e cerca de 25 min para treinar a grade de cada fonte.

```bash
python scripts/hi_large/a_perfil_particionar.py --dados <pasta com os 3 arquivos do HI-Large>
```

```bash
python scripts/hi_large/a2_complementos.py --dados <mesma pasta>
```

```bash
python scripts/hi_large/a4_tentativas.py
```

Para outra versão do IBM AML com os mesmos três arquivos, como o HI-Medium, acrescente `--prefixo HI-Medium` nos scripts que recebem `--dados`. A janela de modelagem (12 dias a partir de 01/08/2022) está fixa nos scripts `b` e `c`.

Opcional: ajustar só o preparador do HI-Large e compará-lo ao atual (câmbio, moedas e formatos), sem calcular atributos.

```bash
python scripts/hi_large/b_atributos.py --preparador L --so-ajustar
```

```bash
python scripts/hi_large/b_atributos.py --preparador S
```

```bash
python scripts/hi_large/b_atributos.py --preparador L
```

```bash
python scripts/hi_large/b2_hismall.py
```

```bash
python scripts/hi_large/a3_conferencia.py --dados <mesma pasta>
```

```bash
python scripts/hi_large/b3_equivalencia.py
```

```bash
python scripts/hi_large/b4_correcao_lote.py
```

`a3_conferencia.py` confere hashes, partições e atributos gravados. `b3_equivalencia.py` compara, em dados reais, o estado incremental, o lote e a força bruta. `b4_correcao_lote.py` compara o lote anterior com o corrigido no teste do HI-Small: atributos, força bruta, scores, alertas e tempo. O padrão é `--ref HEAD`; depois que a correção for commitada, use `--ref 9095451`.

Antes das quatro etapas de avaliação, defina a variável `NODEWATCH_XGBOOST` com a pasta do XGBoost. Sem ela, o XGBoost fica fora da grade e o resultado registra isso.

```bash
python scripts/hi_large/c_treinar_avaliar.py --etapa validacao
```

```bash
python scripts/hi_large/c_treinar_avaliar.py --etapa teste
```

```bash
python scripts/hi_large/c_treinar_avaliar.py --etapa reserva
```

```bash
python scripts/hi_large/c_treinar_avaliar.py --etapa hismall
```

Cada etapa grava um JSON em `resultados/`. Os dados intermediários ficam em `artefatos_ml/hi_large/`, que o git ignora:

- partições diárias em Parquet;
- atributos por dia;
- preparador do HI-Large;
- modelos candidatos;
- escolhas congeladas.

O teste e a reserva **recusam uma segunda consulta**. `--forcar` permite repetir, mas a repetição fica registrada em `artefatos_ml/hi_large/consultas.json` e precisa ser declarada.

### Emenda 2: lote corrigido e teste final novo

Os atributos do HI-Large não passam pelo lote e não precisam ser refeitos. Refazem-se só os que vinham do lote antigo e a fonte S+L, e calcula-se o teste final novo:

```bash
python scripts/hi_large/b2_hismall.py
```

```bash
python scripts/hi_large/b_atributos.py --preparador S --dias 16 --gravar-a-partir 11 --sufixo final2
```

```bash
python scripts/hi_large/b_atributos.py --preparador L --dias 16 --gravar-a-partir 11 --sufixo final2
```

```bash
python scripts/hi_large/c_treinar_avaliar.py --etapa validacao --emenda2
```

```bash
python scripts/hi_large/c_treinar_avaliar.py --etapa final2
```

```bash
python scripts/hi_large/c_treinar_avaliar.py --etapa hismall
```

```bash
python scripts/hi_large/b6_conferir_final2.py
```

`b6` confere que a passada refeita reproduz o dia 12/08 e que os dias 13 a 16 têm todas as linhas e todos os positivos. Grava `b6_conferencia_final2.json`.

Descritivo, fora da Emenda 2 e decidido depois da consulta: as florestas com os parâmetros do artefato, treinadas só no HI-Large e nas duas bases, no mesmo teste final. A etapa usa o mesmo contador de consultas. No registro desta avaliação, ela foi repetida com `--forcar` porque a primeira tentativa falhou antes de gravar.

```bash
python scripts/hi_large/c_treinar_avaliar.py --etapa final2_rf
```

### Emenda 3: segundo teste final (17 a 23/08)

Nada é retreinado. Os atributos são refeitos do dia 1, gravando de 16/08 em diante. O dia 16/08 serve só para conferir que reproduz o arquivo de `final2`.

```bash
python scripts/hi_large/b_atributos.py --preparador S --dias 23 --gravar-a-partir 15 --sufixo final3
```

```bash
python scripts/hi_large/b_atributos.py --preparador L --dias 23 --gravar-a-partir 15 --sufixo final3
```

```bash
python scripts/hi_large/b6_conferir_final2.py --sufixo final3 --anterior final2 --dia-repro 15 --dias 16-22
```

```bash
python scripts/hi_large/c_treinar_avaliar.py --etapa final3
```

A etapa `final3` recusa a consulta se o artefato atual mudou depois da Emenda 3 ou se `b6_conferencia_final3.json` não mostrar o dia 16/08 idêntico e os dias 17 a 23 completos. Também confere o hash de cada modelo e calcula o critério da emenda em `criterio_emenda3`.

Conferências da correção e dos dados:

```bash
python scripts/hi_large/b5_amostra_estratificada.py
```

```bash
python scripts/hi_large/a6_reconferencia.py --dados <mesma pasta>
```

`b5` confere o lote anterior, o lote corrigido e o incremental contra a força bruta, em quatro estratos de 100 linhas: maior divergência antiga, maior acumulado da conta, borda de janela e sorteio. Depois que a correção for commitada, use `--ref 9095451`. `a6` relê as partições sem usar os resultados da primeira passada.

### Reprodução dos treinos X11 e X25

Refaz, numa pasta isolada (`artefatos_ml/hi_large/reproducao_treinos/`), as duas grades treinadas na avaliação: X11 (rodada 1, fontes L e S+L com o HI-Small do lote antigo) e X25 (Emenda 2, S+L corrigida). Usa as mesmas entradas gravadas, a mesma semente e o mesmo XGBoost (`NODEWATCH_XGBOOST`). Compara cada arquivo com o original pelo SHA-256, pela configuração aprendida e pelas previsões na validação purgada de 07 e 08/08, que só confere a reprodução. Não lê os dias 13 a 23/08 e confere, antes e depois, os hashes de `modelos/`, das escolhas, do preparador, do contador de consultas, do artefato de produção e dos resultados.

```bash
python scripts/hi_large/g_reproduzir_treinos.py --execucoes X11 X25
```

### Auditoria de fechamento

Só lê: não pontua modelos nem consulta períodos.

```bash
python scripts/hi_large/e_auditoria.py --dados <mesma pasta>
```

Depois de editar os documentos, refaça só a consistência e o inventário:

```bash
python scripts/hi_large/e_auditoria.py --so-documentos
```

### Testes

```bash
python -m pytest -q -p no:cacheprovider --junitxml=docs/ml/hi_large/resultados/pytest_fechamento.xml
```

```bash
python -m pytest -q -p no:cacheprovider testes/ml/test_hi_large_avaliacao.py --junitxml=docs/ml/hi_large/resultados/pytest_fechamento_hi_large.xml
```
