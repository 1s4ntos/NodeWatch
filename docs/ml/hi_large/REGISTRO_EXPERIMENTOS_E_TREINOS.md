# Registro de experimentos e treinos: avaliação do HI-Large

Trilha de auditoria de tudo o que foi executado na avaliação do HI-Large em 09/11/2026: preparação, atributos, treinos, escolhas, consultas, conferências, falhas e testes de software. O relatório com a interpretação é o [`RELATORIO_HI_LARGE.md`](RELATORIO_HI_LARGE.md).

## Como este registro foi montado

**Horários em UTC.** Os logs em `artefatos_ml/hi_large/log_*.txt` usam o horário local (UTC−3).

**Fontes de evidência, em ordem de preferência:**

1. **Resultados** em `docs/ml/hi_large/resultados/*.json`. O campo `gerado_em_utc` marca o **início** da execução, e a data de modificação do arquivo marca o **fim**.
2. **Logs** de cada execução, em `artefatos_ml/hi_large/log_*.txt`.
3. **Arquivos de hash e de controle:** `escolhas*.sha256`, `emenda3_registro.sha256` e `consultas.json`.
4. **O inventário** em `resultados/e_auditoria.json`, com SHA-256 de resultados, modelos, código e documentos, gerado na auditoria de fechamento.
5. **A transcrição da sessão do Claude Code**, fora do repositório: `~/.claude/projects/…/a4142517-f4b6-4556-a9e1-24a512ad04e5.jsonl`. Ela serve **só** onde o log foi sobrescrito ou não existe: falhas e execuções repetidas.

Quando nenhuma dessas fontes registra um dado, aparece **"não registrado"**.

**Tipos de execução:**

| Sigla | Tipo |
|---|---|
| **P** | Perfil ou preparação dos dados |
| **A** | Geração de atributos |
| **AC** | Conferência de atributos ou de dados |
| **T** | Treino ou retreino efetivo: pesos novos são ajustados |
| **E** | Escolha de modelo, hiperparâmetros e limiar na validação |
| **C** | Consulta de avaliação com modelos **congelados**: só inferência, nenhum peso muda |
| **QE** | Teste estatístico: bootstrap pareado dentro de uma consulta |
| **QC** | Teste de código: testes de software ou ensaio do script, sem valor preditivo |
| **R** | Registro de protocolo: plano ou emenda |

## 1. Dados de entrada

| Arquivo | Bytes | SHA-256 | Conteúdo |
|---|---|---|---|
| `HI-Large_Trans.csv` | 17.052.760.651 | `d13635e297c64673826217631fb88d635c4f506052e1bde833895eda2a65c3f2` | 179.702.229 transações |
| `HI-Large_Patterns.txt` | 13.807.473 | `bcf815a1931cfdcefd5d6d9feaa8f95dbc33cfd6ef8cd52d9a41e8d994c22820` | 16.467 tentativas, 137.936 linhas |
| `HI-Large_accounts.csv` | 147.691.860 | `c799ad2527e90b439147942518ae9a19f660e70ae6c3b78029ecb380a2d81cf4` | 2.126.855 contas |
| HI-Small, transações (via `ml_config.local.toml`) | não registrado aqui | `93c9d65156a28596c756bd1395531e231c5950bbbdbfe665500bc866ed595179` (`b2_hismall.json`) | Treino do modelo atual e parte S da S+L |

Os hashes do HI-Large foram calculados no perfil (`a_perfil.json`) e recalculados duas vezes (`a3_conferencia.json`), sempre iguais.

### 1.1 Divisões

Todas são por **dia de calendário** do HI-Large, com o dia 1 = 01/08/2022. A **purga** (Emenda 1) tira dos períodos avaliados os positivos de tentativas com padrão iniciadas antes do primeiro minuto do período.

| Divisão | Dias | Datas (2022) | Transações | Positivos | Avaliado depois da purga | Positivos retirados | Uso |
|---|---|---|---|---|---|---|---|
| Treino | 1 a 6 | 01 a 06/08 | 14.103.822 | 6.234 | Amostra de 2.825.151 linhas: todos os positivos e 20% dos negativos, com peso 5 e semente `[42, dia]` | — | Treino de L e parte HI-Large da S+L |
| Validação | 7 e 8 | 07 e 08/08 | 2.757.564 | 2.162 | 2.757.188 linhas e 1.786 positivos | 376 | Escolha, limiar e parada antecipada do XGBoost |
| Teste | 9 e 10 | 09 e 10/08 | 3.856.451 | 2.527 | 3.855.946 e 2.022 | 505 | Rodada 1 |
| Reserva | 11 e 12 | 11 e 12/08 | 4.550.843 | 2.759 | 4.550.177 e 2.093 | 666 | Rodada 1 |
| Teste final 2 | 13 a 16 | 13 a 16/08 | 5.519.536 | 5.696 | 5.517.821 e 3.981 | 1.715 | Emenda 2 |
| Teste final 3 | 17 a 23 | 17 a 23/08 | 12.394.384 | 11.528 | 12.390.529 e 7.673 | 3.855 | Emenda 3 |
| HI-Small, treino | — | 01 a 06/09 (`treino_ate` = 2022-09-07, exclusivo) | — | — | Amostra de 651.808 linhas e 2.530 positivos: a mesma do modelo atual, semente 42 e 20% dos negativos | — | Parte S da S+L |
| HI-Small, teste | — | 09 e 10/09 | 862.792 | 956 | Sem purga; já consultado antes desta avaliação | — | Só descritivo |

**Fontes de treino:**

- **S:** o modelo atual, treinado no HI-Small em 02/11/2026.
- **L:** a amostra de treino do HI-Large, 2.825.151 linhas e 6.234 positivos.
- **S+L:** a amostra do HI-Small empilhada à de L, 3.476.959 linhas e 8.764 positivos.

As sobreposições de contas, tentativas e padrões entre as divisões estão na seção 12.1 do relatório e em `e_auditoria.json`.

## 2. Ambiente, código e versões

| Item | Valor |
|---|---|
| Máquina | Windows 11 (10.0.26200), Intel 64, 20 CPUs lógicas, 15,7 GB de RAM, com pouca RAM livre durante as execuções (0,9 a 3,9 GB, conforme cada JSON) |
| Threads | 4 em todas as etapas (`comum.THREADS`) |
| Python e bibliotecas | Python 3.14.0, NumPy 2.5.4, pandas 3.1.0, pyarrow 26.0.0, scikit-learn 1.9.1 |
| XGBoost | **3.4.1, em ambiente temporário, fora do projeto.** Instalado às 05:49 UTC de 09/11 com `pip install --target <scratchpad>/xgb --no-deps xgboost==3.4.1`. Usa o NumPy e o SciPy do `.venv`. Pacote (wheel) `py3-none-win_amd64`; a `xgboost.dll` tem SHA-256 (base64) `3LFck91yaIfKnNa33C0Mu8oKIQwO9CeLuVTU2jxdFn4`, segundo o `RECORD`. **Não é dependência do NodeWatch** e não está em `requirements*.txt` |
| Semente | 42 em todos os sorteios, modelos e bootstraps (`comum.SEMENTE`) |
| Código | Branch `ml/sessoes-analise-datasets`, HEAD `9095451` e 42 alterações locais, **sem commit**. Os scripts da avaliação e a correção do lote não estão no git. O SHA-256 de cada arquivo de código (`src/ml/*.py`, `scripts/hi_large/*.py` e os testes) está em `e_auditoria.json` → `inventario.codigo` |
| Preparação dos atributos | `src/ml/preparacao.py` (`PreparadorFinanceiro`) e `src/ml/incremental.py` (`EstadoFinanceiro`). Os atributos do HI-Large vêm sempre do **incremental**. Os do HI-Small vêm do **lote**, que foi corrigido às cerca de 08:17 UTC (seção 5) |

**Configuração dos candidatos** (`c_treinar_avaliar.py`, `GRADE` e `criar_xgb`; `src/ml/modelos.py`):

| Família | Configurações | Fixos |
|---|---|---|
| Logística | C = 0,1 e 1,0 | `max_iter=3000`, `tol=1e-6`, `random_state=42`; imputação pela mediana, log com sinal e padronização |
| Floresta | (100 árvores, folha mínima 50, `max_samples=0.5`) e (200, 10, 0,5) | `max_features="sqrt"`, `random_state=42`, `n_jobs=4` |
| HGB | 31 e 63 folhas | `max_iter=300`, `learning_rate=0.1`, `l2_regularization=1.0`, `early_stopping=False`, `random_state=42` |
| XGBoost | profundidade 6 e 8, `min_child_weight=10` | `hist`, CPU, `learning_rate=0.1`, `subsample=1`, `colsample_bytree=1`, `reg_lambda=1`, até 1.000 árvores com **parada antecipada de 50 rodadas pela `aucpr` da validação purgada**, `random_state=42` |

Em todas as famílias, o peso das amostras é 5 nos negativos amostrados, e o limiar é o de máximo F1 na validação purgada.

## 3. Tabela-resumo por execução

"Treino?" diz se a execução ajustou pesos de algum modelo. Os hashes completos de resultados e modelos estão nas seções 4 e 6 e em `e_auditoria.json`.

| ID | Início → fim (UTC, 09/11) | Tipo | O que fez | Registrado antes? | Treino? | Saída principal | Desfecho |
|---|---|---|---|---|---|---|---|
| X00 | arquivo de 05:45:32 | R | Plano de avaliação | — | — | `PLANO_AVALIACAO.md` (`2200c8d6…0851c`) | Gravado no perfil |
| X01 | 05:47:49 | QC | Ensaio do perfil numa amostra de 300 mil linhas (`head` do CSV) | — | Não | Saída em `artefatos_ml/hi_large`, sobrescrita por X02 | Concluído e **descartado**; evidência só na transcrição |
| X02 | 05:48:53 → 06:04:33 | P | Perfil, hashes e partição por dia | Plano | Não | `a_perfil.json`, 165 partições, `positivos.parquet` e `padroes_casados.parquet` | Concluído (`log_a_perfil.txt`) |
| X03 | 06:05:32 → 06:05:53 | P | Ajuste e comparação do preparador do HI-Large (`--so-ajustar`) | Plano | Não | `b_preparador_L.json` | Concluído |
| X04 | 06:06:07 → 06:17:10 | A | Atributos dos dias 1 a 12, preparador S, incremental | Plano | Não | `atributos_S/`, `b_atributos_S.json` | Concluído (`log_b_S.txt`) |
| X05 | 06:17:15 → 06:18:07 | A | Atributos do HI-Small pelo **lote com defeito**: amostra de treino (S) e teste (L) | Plano | Não | `hismall_*_lote_antigo.parquet` (renomeados em X21), `b2_hismall_lote_antigo.json` | Concluído; **substituído** em X21 |
| X06 | 06:18:09 → 06:29:38 | A | Atributos dos dias 1 a 12, preparador L (reajusta e salva `preparador_L.joblib`) | Plano | Não | `atributos_L/`, `b_atributos_L.json` | Concluído (`log_b_L.txt`) |
| X07 | 06:06:26 e 06:07:13 → 06:07:17 | P | Complementos: duração das tentativas e contas em comum com o HI-Small; rodado duas vezes, o segundo JSON sobrescreveu o primeiro | Plano | Não | `a2_complementos.json` | Concluído |
| X08 | arquivo de 06:29:32 | R | **Emenda 1**: purga por tentativa | Antes de qualquer treino | — | `EMENDA_1_PURGA_POR_TENTATIVA.md` (`878b125e…f006`) | — |
| X09 | 06:30 → 06:30:50 | AC | Conferência de hashes, partições e atributos | — | Não | `a3_conferencia.json`, **sobrescrito** em X29 | Concluído; o primeiro JSON não foi preservado (`log_a3.txt`) |
| X10 | 06:30:21 (2º plano) e 06:32:09 | AC | Incremental × lote × força bruta, em 02/08, **antes** da correção | — | Não | `b3_equivalencia_antes_da_correcao.json` | A execução de 06:32 gravou o JSON. A de 06:30 em segundo plano não tem desfecho registrado |
| X11 | 06:34:23 → 07:23:45 | T + E | **Rodada 1:** treino da grade de 8 configurações nas fontes L e S+L (16 modelos; S+L com o HI-Small do lote antigo); escolha pela AP na validação purgada | Plano e Emenda 1 | **Sim** | 16 modelos em `modelos/` (`L__*` e `S_L__*`), `c_validacao.json`, `escolhas.json` (`f5ee059f…a7d1`) | Concluído (`log_c_validacao.txt`) |
| X12 | 06:34:49 | P | Tentativas por partição | — | Não | `a4_tentativas.json` | Concluído |
| X13 | 07:24:16 | — | Hash das escolhas antes do teste | — | — | `escolhas_antes_do_teste.sha256` | Igual a `f5ee059f…` |
| X14 | 07:24:24 → 07:42:46 | C + QE | **Teste** (09 e 10/08), com todos os candidatos congelados e as regras | Plano e Emenda 1 | Não | `d_teste.json` | Consulta única (`teste` = 1) |
| X15 | 07:43:02 → 08:00:32 | C + QE | **Reserva** (11 e 12/08), só com os escolhidos | Plano e Emenda 1 | Não | `d_reserva.json` | Consulta única (`reserva` = 1) |
| X16 | 08:00:41 | C | HI-Small (descritivo; teste já consultado antes) | — | Não | `f_hismall_lote_antigo.json` | Concluído; substituído em X27 |
| X17 | cerca de 08:17 | — | **Correção do lote** em `src/ml/preparacao.py` (`_IndiceEventos`) | — | — | Código; a versão anterior está em `9095451` | Horário só pela Emenda 2 ("05:17 local") |
| X18 | 08:18:31 | AC | `b4_correcao_lote.py`, 1ª tentativa | — | Não | Nenhum | **Falhou** antes de gravar: `AttributeError` ao carregar o módulo antigo com `importlib` (dataclass sem módulo em `sys.modules`). Evidência: transcrição, 08:20:26. O log foi sobrescrito em X19b |
| X19 | 08:18:35 → 08:20:17 | AC | Incremental × lote × força bruta, em 02/08, **depois** da correção | — | Não | `b3_equivalencia.json` | Concluído (`log_b3_corrigido.txt`) |
| X19b | 08:20:44 → 08:23:01 | AC | Lote anterior × corrigido no teste do HI-Small, com força bruta, scores e alertas do modelo atual **sem retreino** | — | Não | `b4_correcao_lote.json` | Concluído (`log_b4.txt`) |
| X20 | 10:03:48 (arquivo de 10:03:47) | R | **Emenda 2**: refazer o que dependia do lote e criar o teste final novo | Antes de regenerar e de calcular os dias 13 a 16 | — | `EMENDA_2_LOTE_CORRIGIDO_E_TESTE_FINAL.md` (`52f87254…42317`) | — |
| X21 | 10:04:14 → 10:04:55 | A | HI-Small refeito com o lote corrigido; os antigos ficaram como `*_lote_antigo.parquet` | Emenda 2 | Não | `hismall_treino_S.parquet`, `hismall_teste_L.parquet`, `b2_hismall.json` | Concluído (`log_b2_corrigido.txt`) |
| X22 | 10:05:15 → 10:22:49 | A | Dias 1 a 16, preparador S, gravando de 12/08 em diante | Emenda 2 | Não | `atributos_S_final2/`, `b_atributos_S_final2.json` | Concluído |
| X23 | 10:22:55 → 10:35:16 | A | Dias 1 a 16, preparador L, reaproveitando `preparador_L.joblib` | Emenda 2 | Não | `atributos_L_final2/`, `b_atributos_L_final2.json` | Concluído |
| X24 | 10:18:52 → 10:19:04 | AC | Reconferência independente das partições, contas e padrões | — | Não | `a6_reconferencia.json`, `PARTICOES.md` | Concluído |
| X25 | 10:35:49 → 11:03:28 | T + E | **Rodada 2:** retreino das 8 configurações da S+L com o HI-Small corrigido; escolha pela AP na validação purgada | Emenda 2 | **Sim** | 8 modelos `corrigido__S_L__*`, `c_validacao_emenda2.json`, `escolhas_emenda2.json` (`c9f7159d…7a59`) | Concluído. Também regravou `preparador_L.joblib` às 10:35:50 (seção 6.3) |
| X26 | 11:03:39 → 11:24:00 | C + QE | **Teste final 2** (13 a 16/08): S, L escolhido, S+L corrigida escolhida, S+L antiga (descritiva) e taxa do formato | Emenda 2 | Não | `d_teste_final2.json` | Consulta única (`teste_final2` = 1) |
| X27 | 11:24:07 → 11:24:13 | C | HI-Small descritivo com os atributos corrigidos | Emenda 2 | Não | `f_hismall.json` | Concluído |
| X28 | 11:24:16 → 11:29:37 | AC | Conferência estratificada do lote contra a força bruta | — | Não | `b5_amostra_estratificada.json` | Concluído (`log_b5.txt`) |
| X29 | 11:29:38 → 11:30:06 | AC | Hashes e conferência, 2ª vez | — | Não | `a3_conferencia.json` | Concluído (`log_a3_final.txt`) |
| X30 | ~11:31 → 11:39:54 | C | Florestas de produção no teste final 2, 1ª tentativa | **Não**: decidida depois de ver X26 | Não | Nenhum | **Falhou** depois de pontuar: `KeyError: 'S+L'` no bootstrap. O contador foi a 1. Evidência: transcrição. O log foi sobrescrito |
| X31 | 11:40:18 → 11:52:59 | C + QE | Florestas de produção no teste final 2, repetida com `--forcar` | **Não** | Não | `d_teste_final2_rf_descritivo.json` | Concluída; **descritiva**, 2ª consulta registrada |
| X32 | ~11:54 | AC | Conferência dos atributos do teste final 2 | — | Não | `b6_conferencia_final2.json` (1ª versão) | Concluído; **sobrescrito** em X36b com os mesmos valores e campos renomeados |
| X33 | 18:51:58 (arquivo de 18:51:56) | R | **Emenda 3**: segundo teste final, com hipóteses principal e secundária | Antes de calcular os dias 17 a 23 | — | `EMENDA_3_SEGUNDO_TESTE_FINAL.md` (`d62af3cb…8d1a`), `emenda3_registro.sha256` | — |
| X34 | 18:54:56 → 19:00:16 | QC | Ensaio da etapa `final3` sobre 13/08, já consultado, com contador e saída à parte | — | Não | `<scratchpad>/ensaio_final3/` (temporário) | Concluído; **descartado**. Reproduziu os valores conhecidos de 13/08, e o contador real não mudou |
| X35 | 19:00:35 → 19:21:01 | A | Dias 1 a 23, preparador S, gravando de 16/08 em diante | Emenda 3 | Não | `atributos_S_final3/`, `b_atributos_S_final3.json` | Concluído |
| X35b | 19:21:09 → 19:39:44 | A | Dias 1 a 23, preparador L | Emenda 3 | Não | `atributos_L_final3/`, `b_atributos_L_final3.json` | Concluído |
| X36 | 19:39:47 → 19:40:32 | AC | Reprodução de 16/08 e integridade dos dias 17 a 23 | Emenda 3 (condição da consulta) | Não | `b6_conferencia_final3.json` | Concluído; tudo idêntico e completo |
| X36b | 19:40:34 → 19:41:08 | AC | Regravação de `b6_conferencia_final2.json` com o script generalizado | — | Não | `b6_conferencia_final2.json` | Concluído; os mesmos valores de X32 |
| X37 | 19:43:30 → 20:44:56 | C + QE | **Teste final 3** (17 a 23/08): S, S+L XGBoost (principal), S+L floresta (secundária), L XGBoost e L floresta (descritivos) e taxa do formato | Emenda 3 | Não | `d_teste_final3.json` | Consulta única (`teste_final3` = 1) |
| X38 | 21:13 (passada completa); regravado depois dos documentos com `--so-documentos` | AC | Auditoria de fechamento: sobreposições, bootstrap, critério, artefato, inventário (`e_auditoria.py`) | — | Não | `e_auditoria.json` | Concluído; não pontua modelos e não muda `consultas.json` |
| X39 | 21:15:37 → 21:16:40 e 21:22:19 → 21:23:21 | QC | Testes de software, refeitos depois da última alteração de código (`e_auditoria.py`) | — | Não | `pytest_fechamento.xml`, `pytest_fechamento_hi_large.xml` (depois regravados em X42) | 207 aprovados; 14 aprovados |
| X40, X40b | 21:47 e 21:48:14 → 21:52:24 | QC | Ensaios do script de reprodução no scratchpad (seção 12) | — | Ensaio, descartado | Scratchpad | X40 falhou (caminho); X40b concluído, com 3 modelos idênticos |
| X41 | 21:52:36 → 22:58:36 | **T (reprodução)** | **Reprodução de X11 e X25** em pasta isolada, com os mesmos insumos e código (seção 12) | Pedido antes de executar; nada escolhido nem ajustado | **Sim**, em `reproducao_treinos/`; não substitui nenhum modelo | `g_reproducao_treinos.json`, 24 modelos | **24 de 24 idênticos** byte a byte |
| X42 | 22:59:41 → 23:01:00 | QC | Testes de software depois do script de reprodução e de um teste novo (seção 10) | — | Não | `pytest_fechamento.xml`, `pytest_fechamento_hi_large.xml` (regravados em X43) | 208 aprovados; 15 aprovados |
| X43 | 10/11, 02:14:59 → 02:18:37 | QC | Testes de software antes dos commits, depois de os scripts deixarem de gravar o caminho local do XGBoost (seção 10) | — | Não | `pytest_fechamento.xml`, `pytest_fechamento_hi_large.xml`, com `hostname` removido | 208 aprovados; 15 aprovados |

## 4. Resultados e consultas: arquivos e hashes

| Arquivo em `resultados/` | Início (UTC) | Fim (UTC) | SHA-256 (16 primeiros) |
|---|---|---|---|
| `a_perfil.json` | 05:48:53 | 06:04:33 | `19dfc43a41a94a23` |
| `a2_complementos.json` | 06:07:13 | 06:07:17 | `1ee8a1406357be72` |
| `a3_conferencia.json` | 11:29:38 | 11:30:06 | `b5c08537f852dfdb` |
| `a4_tentativas.json` | 06:34:49 | 06:34:49 | `56a33fa8c2a67f75` |
| `a6_reconferencia.json` | 10:18:52 | 10:19:04 | `fce668042674a533` |
| `b_preparador_L.json` | 06:05:32 | 06:05:53 | `3eb3310578020523` |
| `b_atributos_S.json` / `_L.json` | 06:06:07 / 06:18:09 | 06:17:10 / 06:29:38 | `9307c795ee52f14c` / `afeac3ed15a20f45` |
| `b_atributos_S_final2.json` / `_L_final2.json` | 10:05:15 / 10:22:55 | 10:22:49 / 10:35:16 | `1bc1832fb7f609f8` / `c6f1453de8e041f6` |
| `b_atributos_S_final3.json` / `_L_final3.json` | 19:00:35 / 19:21:09 | 19:21:01 / 19:39:44 | `1152ab022316c09e` / `af501b71db800606` |
| `b2_hismall_lote_antigo.json` (cópia) / `b2_hismall.json` | 06:17:15 / 10:04:14 | — / 10:04:55 | `5ad78d3fdc6be14a` / `6c3472fa83765841` |
| `b3_equivalencia_antes_da_correcao.json` / `b3_equivalencia.json` | 06:32:09 / 08:18:35 | — / 08:20:17 | `d031fac8d5d50a87` / `a4d5484b11e982bc` |
| `b4_correcao_lote.json` | 08:20:44 | 08:23:01 | `5ba0a8815b0075db` |
| `b5_amostra_estratificada.json` | 11:24:16 | 11:29:37 | `cc9fa663948234e8` |
| `b6_conferencia_final2.json` / `_final3.json` | 19:40:34 / 19:39:47 | 19:41:08 / 19:40:32 | `0609db21624e455e` / `5d279214a5425e95` |
| `c_validacao.json` (= `c_validacao_historico.json`) | 06:34:23 | 07:23:45 | `5b2d792f1c3c346b` |
| `c_validacao_emenda2.json` | 10:35:49 | 11:03:28 | `ed4e0ccbfd9a703b` |
| `d_teste.json` | 07:24:24 | 07:42:46 | `183c0f066212b789` |
| `d_reserva.json` | 07:43:02 | 08:00:32 | `b8cabed0e9183f05` |
| `d_teste_final2.json` | 11:03:39 | 11:24:00 | `f6e0b5dbd1e0fb60` |
| `d_teste_final2_rf_descritivo.json` | 11:40:18 | 11:52:59 | `85e375b824a3be80` |
| `d_teste_final3.json` | 19:43:30 | 20:44:56 | `f89e77c44264f127` |
| `f_hismall_lote_antigo.json` (cópia) / `f_hismall.json` | 08:00:41 / 11:24:07 | — / 11:24:13 | `e7d746caed25a1c3` / `5d1510db385d629c` |

Nas cópias `*_lote_antigo.json` e `*_antes_da_correcao.json`, a data do arquivo é a da cópia, não a do fim da execução, e por isso o fim aparece como "—". Os hashes completos estão em `e_auditoria.json` → `inventario.resultados`.

**Arquivos de controle** (`artefatos_ml/hi_large/`):

| Arquivo | Conteúdo |
|---|---|
| `escolhas.json` | `f5ee059fe849a8aae9a72c2a987ae34ca189f95cbe0e5535e3d877924a18a7d1`, igual em `escolhas_antes_do_teste.sha256` (07:24:16) e em `escolhas_antes_emenda2.sha256` (10:35:41) |
| `escolhas_emenda2.json` | `c9f7159df0f5faafbd61aea956e5289f88426f7ca2c583fa4d8732b6de777a59`, gravado às 11:03:28 e conferido às 11:03:30, antes do teste final 2 (11:03:39) |
| `emenda3_registro.sha256` | `d62af3cbba28681bd7f9898425c278ce70d43d3c40281910e813d77b1f6c8d1a`, registrada às 18:51:58 |
| `consultas.json` | `teste` 1, `reserva` 1, `teste_final2` 1, `teste_final2_rf_descritivo` 2, `teste_final3` 1 |

## 5. Sequência das emendas e da correção

| Ordem | Horário (UTC) | Evento | Efeito |
|---|---|---|---|
| 1 | 05:45 | Plano | Divisões, grade, métricas e critério da rodada 1 (teste nos dois dias e reserva) |
| 2 | 06:29 | Emenda 1 | Purga por tentativa na validação, no teste e na reserva. Escrita depois do perfil e antes de qualquer treino |
| 3 | 06:34 a 08:00 | Rodada 1 | Treino (X11), teste (X14) e reserva (X15). Critério não atendido |
| 4 | ~08:17 | **Correção do lote** | As somas acumuladas passaram a recomeçar em cada conta. Antes, o erro chegava a 27% no HI-Large e a 5,0% no teste do HI-Small (X10, X19, X19b, X28) |
| 5 | 10:03 | Emenda 2 | Refazer o HI-Small e a S+L; teste final novo de 13 a 16/08, com critério de IC e 3 de 4 dias. Escrita depois de conhecida a rodada 1 |
| 6 | 10:04 a 11:24 | Rodada 2 | Regeneração (X21), retreino da S+L (X25) e teste final 2 (X26). A S+L com XGBoost atendeu o critério |
| 7 | 11:31 a 11:53 | Descritivo pós-consulta | Florestas de produção no teste final 2 (X30 falhou; X31) |
| 8 | 18:51 | Emenda 3 | Teste final 3 de 17 a 23/08, com hipótese principal (XGBoost S+L), secundária (floresta S+L) e critério de IC e 5 de 7 dias. Escrita depois de conhecido o teste final 2 |
| 9 | 19:00 a 20:45 | Rodada 3 | Atributos (X35 e X35b), conferência (X36) e consulta (X37). A principal não foi atendida; a secundária foi |

## 6. Modelos

### 6.1 Modelo atual (S): nunca retreinado

| Item | Valor |
|---|---|
| Arquivo | `artefatos_ml/modelo_unificado.joblib`, com 38.645.843 bytes |
| SHA-256 | `28a13a1873f4896a0ede445070cf5adff907b88007e3f25ab4ca5cf6dbcdb4aa` |
| Versão da cabeça de lavagem | `lavagem-20261102T083253Z`: floresta de 100 árvores, folha 50 e amostra de 50%, treinada no HI-Small com o lote **antigo** |
| Limiar | 0,0910, do artefato; 0,0862 reportado como alternativa, recalculado na validação do HI-Large |
| Data do arquivo | 2026-11-02 08:32:54 UTC, anterior a toda esta avaliação |

**Hash conferido** em quatro momentos:

- às 08:25 UTC de 09/11, registrado na transcrição;
- na Emenda 3, às 18:51;
- na consulta do teste final 3 (`d_teste_final3.json` → `artefato_sha256`);
- e de novo na auditoria (`e_auditoria.json`).

Antes de 09/11, não há hash registrado. A data do arquivo é a única evidência de que ele não mudou entre 02/11 e 09/11.

**Por que não foi retreinado.** S é a **referência** de todas as comparações. Retreiná-lo mudaria o termo de comparação no meio da avaliação. Os artefatos confirmam isto:

- nenhum script de `scripts/hi_large/` chama `ModeloUnificado.salvar`;
- todas as consultas carregam o artefato com `ModeloUnificado.carregar`;
- `b4` mediu o efeito da correção sobre o modelo **sem** retreiná-lo: os mesmos 620 alertas.

Um retreino de S com o lote corrigido não foi feito nem avaliado.

### 6.2 Modelos treinados nesta avaliação

Todos ficam em `artefatos_ml/hi_large/modelos/`, e os hashes estão em `e_auditoria.json` → `inventario.modelos`.

| Execução | Fonte | Arquivo (prefixo) | Configuração | SHA-256 (16 primeiros) | AP na validação | Limiar | Árvores do XGBoost (parada antecipada) | Uso posterior |
|---|---|---|---|---|---|---|---|---|
| X11 | L | `L__` | Logística C = 0,1 / 1,0 | `fe5d596ff5793dd7` / `b8aa24827dcfd45d` | 0,027 / 0,027 | — | — | Teste (X14) |
| X11 | L | `L__` | Floresta 100/50 | `ed8cef2306f430a5` | 0,059 | 0,0366 | — | Teste; X31 e X37 (descritivos) |
| X11 | L | `L__` | Floresta 200/10 | `e8dea4f9c947c85d` | 0,049 | — | — | Teste |
| X11 | L | `L__` | HGB 31 / 63 | `0a8dc1c24df8fc02` / `a605cad9d13578b4` | 0,052 / 0,038 | — | — | Teste |
| X11 | L | `L__` | XGBoost 6 | `b3e62628b9a55029` | 0,098 | — | 159 | Teste |
| X11 | L | `L__` | **XGBoost 8, escolhido** | `3facedae9dd7398c` | 0,106 | 0,0956 | 220 | Teste, reserva, X26 e X37 (descritivo) |
| X11 | S+L antiga | `S_L__` | Logística, floresta, HGB e XGBoost 8 (7 modelos) | ver inventário | 0,031 a 0,108 | — | 179 (XGBoost 8) | Teste (histórico) |
| X11 | S+L antiga | `S_L__` | **XGBoost 6, escolhido** | `3399adb8281b7ae0` | 0,111 | 0,1421 | 218 | Teste, reserva e X26 (descritivo); histórico |
| X25 | S+L corrigida | `corrigido__S_L__` | Logística C = 0,1 / 1,0 | `540dd6f7b10e218a` / `0ff97c00eba84895` | 0,031 / 0,031 | 0,0375 / 0,0354 | — | Nenhum |
| X25 | S+L corrigida | `corrigido__S_L__` | Floresta 100/50 | `85380b56019abc80` | 0,091 | 0,0519 | — | X31 (descritivo) e X37 (**secundária**) |
| X25 | S+L corrigida | `corrigido__S_L__` | Floresta 200/10 | `09fe4f71d5ac9af1` | 0,096 | 0,0680 | — | Nenhum |
| X25 | S+L corrigida | `corrigido__S_L__` | HGB 31 / 63 | `96ca82c1f39747b6` / `793267f4d342c0e7` | 0,057 / 0,054 | 0,1074 / 0,1155 | — | Nenhum |
| X25 | S+L corrigida | `corrigido__S_L__` | **XGBoost 6, escolhido** | `999890b9ec9e4b6c` | 0,115 | 0,1269 | 341 | X26 e X37 (**principal**) |
| X25 | S+L corrigida | `corrigido__S_L__` | XGBoost 8 | `ff23cc29458a001f` | 0,103 | 0,1311 | 96 | Nenhum |

**Tempos de treino**, de uma única execução cada:

- **Rodada 1:** de 31 a 503 s em L e de 39 a 620 s na S+L (`c_validacao.json`).
- **Rodada 2:** de 24 a 701 s, 1.586 s no total (`c_validacao_emenda2.json`).

O pico de memória do processo foi de 7,6 GB (fonte L) e 9,7 GB (S+L) na rodada 1 e de 9,5 GB na rodada 2 (`pico_memoria_mb` nos JSON de validação).

### 6.3 O preparador do HI-Large

`preparador_L.joblib` foi:

- ajustado em X03 (`--so-ajustar`);
- reajustado e salvo em X06;
- **regravado** em X25, às 10:35:50, porque `etapa_validacao` recalcula os quantis das regras com o mesmo treino L e salva o arquivo.

A versão anterior a X25 não foi preservada. Há duas evidências de que a regravação não mudou os atributos:

- `atributos_L_final2` foi calculado com a versão anterior, e `atributos_L_final3` com a nova;
- o dia 16/08 dos dois é **idêntico** coluna por coluna (`b6_conferencia_final3.json`).

Os quantis só entram nas regras F2 e F3, que não foram usadas depois da rodada 1.

## 7. Consultas e métricas

As métricas completas estão nos JSON e nas seções 5 a 7 do relatório. Os modelos de todas as consultas estavam congelados: **nenhuma consulta treinou nada**.

| Consulta | Período e linhas avaliadas | Modelo | AP | Diferença para S (IC 95%) | Alertas | Precisão / recall | Papel |
|---|---|---|---|---|---|---|---|
| X14 | Teste, 3.855.946 / 2.022 | S / L XGBoost / S+L antiga XGBoost | 0,070 / 0,079 / 0,089 | L +0,009 [−0,003; +0,022]; S+L +0,019 [+0,008; +0,032] | 1.232 / 1.712 / 738 | 0,164/0,100; 0,145/0,123; 0,243/0,089 | Rodada 1 |
| X15 | Reserva, 4.550.177 / 2.093 | S / L / S+L antiga | 0,081 / 0,067 / 0,081 | L −0,015 [−0,028; −0,003]; S+L −0,001 [−0,012; +0,010] | 1.369 / 1.859 / 759 | — | Rodada 1 |
| X26 | Teste final 2, 5.517.821 / 3.981 | S | 0,0978 | — | 2.793 | 0,191 / 0,134 | Comparação |
| X26 | | L XGBoost | 0,0951 | −0,0027 [−0,0128; +0,0076] | 3.480 | 0,155 / 0,136 | Escolhido de L |
| X26 | | S+L corrigida XGBoost | 0,1152 | +0,0174 [+0,0081; +0,0278] | 2.072 | 0,251 / 0,131 | **Critério da Emenda 2 atendido** |
| X26 | | S+L antiga XGBoost | 0,1115 | +0,0137 [+0,0054; +0,0232] | 1.398 | 0,310 / 0,109 | Descritivo |
| X26 | | Taxa do formato | 0,0037 | — | 701.553 | 0,004 / 0,774 | Referência |
| X31 | Teste final 2 | Florestas L / S+L corrigida | 0,0801 / 0,1081 | −0,0177 [−0,0271; −0,0092] / +0,0103 [+0,0049; +0,0175] | 2.957 / 1.932 | 0,167/0,124; 0,275/0,134 | Descritivo, pós-consulta |
| X37 | Teste final 3, 12.390.529 / 7.673 | S | 0,1259 | — | 5.735 | 0,220 / 0,164 | Comparação |
| X37 | | S+L corrigida XGBoost | 0,1291 | +0,0032 [−0,0043; +0,0105] | 4.094 | 0,273 / 0,146 | **Principal: não atendido** (3 de 7 dias) |
| X37 | | S+L corrigida floresta | 0,1371 | +0,0112 [+0,0064; +0,0172] | 3.414 | 0,336 / 0,150 | Secundária; **exploratória** (6 de 7 dias) |
| X37 | | Taxa do formato | 0,0031 | — | 1.570.166 | 0,004 / 0,762 | Referência |
| X37 | | L XGBoost / L floresta | 0,1071 / 0,1053 | −0,0188 [−0,0279; −0,0104] / −0,0207 [−0,0298; −0,0133] | 6.802 / 4.469 | 0,172/0,153; 0,235/0,137 | Descritivos |

**Tempos das consultas:**

- teste final 2, cerca de 20 min;
- florestas, 13 min;
- teste final 3, 3.805 s, dos quais 1.753 s em bootstrap.

A pontuação em lote ficou entre 170 mil e 538 mil linhas/s no teste final 3 e entre 434 mil e 797 mil no teste final 2.

## 8. Atributos regenerados e preservados

| Atributos | Por quê | Situação |
|---|---|---|
| `hismall_treino_S.parquet` e `hismall_teste_L.parquet` | Vinham do **lote com defeito** | **Regenerados** em X21; os antigos estão em `*_lote_antigo.parquet` |
| Modelos S+L da rodada 1 | Treinados com a amostra do HI-Small do lote antigo | **Repetidos** em X25. Os antigos ficaram em `modelos/S_L__*`, e os resultados de S+L da rodada 1 viraram históricos |
| `atributos_S` e `atributos_L` (dias 1 a 12) | Vêm do incremental, não do lote | **Preservados**. O dia 12/08 recalculado em X22 e X23 é idêntico (`b6_conferencia_final2.json`) |
| `atributos_*_final2` (13 a 16/08) e `atributos_*_final3` (17 a 23/08) | Incremental | Calculados uma vez cada, e o dia de sobreposição é idêntico |
| Modelos L e preparador L | Não dependem do lote | Preservados (o preparador foi regravado em X25; seção 6.3) |
| Modelo atual S | Referência | Preservado, sem retreino |

## 9. Execuções com falha, repetidas ou excluídas

| ID | O quê | Desfecho | Efeito no resultado |
|---|---|---|---|
| X01 | Ensaio do perfil em amostra | Descartado | Nenhum: a saída foi sobrescrita por X02 |
| X10 (06:30) | `b3` em segundo plano | Desfecho não registrado; o JSON é da execução de 06:32 | Nenhum |
| X18 | `b4`, 1ª tentativa | Falhou antes de gravar | Nenhum; o código foi corrigido e X19b concluiu |
| X30 | Florestas no teste final 2, 1ª tentativa | Falhou depois de pontuar, antes de gravar; o contador foi a 1 | O período foi consultado **duas vezes** para uma avaliação descritiva. Não há resultado da 1ª tentativa. Se ela imprimiu métricas, elas não foram registradas |
| X34 | Ensaio da etapa `final3` em 13/08 | Descartado | Nenhum: período já consultado, contador à parte |
| X09, X32 | Primeiras versões de `a3_conferencia.json` e `b6_conferencia_final2.json` | Sobrescritas | `a3`: só a 2ª versão existe; a 1ª tinha hashes iguais (transcrição). `b6`: os mesmos valores |
| — | Rodada 1 da S+L | Excluída das conclusões atuais | Lote com defeito (seção 8) |
| X40 | Ensaio do script de reprodução | Falhou ao gravar o resumo, por causa do caminho do scratchpad | Nenhum: só no scratchpad; corrigido antes de X40b e X41 |

## 10. Testes de software

Os testes de software verificam o código; **não medem desempenho preditivo**.

**Revisão atual:** confirmada em 10/11/2026, às 02:15–02:18 UTC (X43), depois da última alteração de código, com o código cujos hashes estão em `e_auditoria.json` → `inventario.codigo`: branch `ml/sessoes-analise-datasets`, HEAD `9095451`, com 42 alterações locais e sem commit.

| Comando | Resultado | Evidência |
|---|---|---|
| `python -m pytest -q -p no:cacheprovider --junitxml=docs/ml/hi_large/resultados/pytest_fechamento.xml` | **208 aprovados**, 0 falhas, 0 pulados | `resultados/pytest_fechamento.xml`; hash em `e_auditoria.json` → `inventario.resultados` |
| `python -m pytest -q -p no:cacheprovider testes/ml/test_hi_large_avaliacao.py --junitxml=docs/ml/hi_large/resultados/pytest_fechamento_hi_large.xml` | **15 aprovados** | `resultados/pytest_fechamento_hi_large.xml`; hash em `e_auditoria.json` |

**Execuções anteriores,** registradas só na transcrição e em revisões anteriores do código:

| Horário (UTC) | Escopo | Resultado |
|---|---|---|
| 05:56 | Testes do HI-Large | 7 aprovados |
| 06:36 | Testes do HI-Large | 9 aprovados e 1 falha esperada (`xfail`) da soma do lote |
| 08:17 | Correção do lote | 37 testes dos atributos financeiros e 11 do HI-Large |
| 12:03 | Suíte inteira | 204 |
| 19:01 | Testes do HI-Large | 14 |
| 20:49 | Suíte inteira | 207 |
| 21:16 e 21:23 (X39) | Suíte inteira; testes do HI-Large | 207; 14 |
| 22:59 a 23:01 (X42) | Suíte inteira; testes do HI-Large | 208; 15 |

## 11. Como reproduzir

Os comandos, na ordem, estão no [`README.md`](README.md). Para um **ambiente limpo**, são necessários:

1. **Os três arquivos do HI-Large,** com os SHA-256 da seção 1, e o HI-Small configurado em `ml_config.local.toml`, com o SHA-256 `93c9d651…5179`.
2. **O código desta revisão.** Ele **não está no git**: está como alterações locais sobre `9095451`. Sem um commit, a reprodução depende de copiar a pasta. Os hashes dos arquivos em `e_auditoria.json` permitem conferir a cópia. O código da época de X11 não foi guardado; a seção 12.1 diz como se sabe que o caminho de treino não mudou.
3. **O `.venv` do NodeWatch,** com as versões da seção 2.
4. **O XGBoost 3.4.1 num diretório à parte,** como foi usado aqui, sem instalar no `.venv`:

   ```bash
   python -m pip install --target <pasta_xgboost> --no-deps xgboost==3.4.1
   ```

   E antes das etapas `c_treinar_avaliar.py`, defina `NODEWATCH_XGBOOST=<pasta_xgboost>`. A pasta usada nesta avaliação ficou no diretório temporário da sessão (`…/scratchpad/xgb`) e pode ter sido apagada.

5. **O artefato atual,** `artefatos_ml/modelo_unificado.joblib`, com SHA-256 `28a13a18…dcbdb4aa`. Ele não está no git, e sem ele não há modelo S.
6. **Disco e memória:** além dos 17 GB do CSV, `artefatos_ml/hi_large/` ocupa 6,8 GB ao fim da avaliação. A máquina usada tinha 15,7 GB de RAM, e o pico de um processo foi de 9,7 GB.

**Determinismo:**

- Os atributos são determinísticos: a mesma passada reproduziu os dias de sobreposição bit a bit.
- **Treinos:** X11 e X25 foram refeitos na mesma máquina, com os mesmos insumos e versões (X41). Os 24 arquivos de modelo saíram **idênticos byte a byte** (seção 12). Em outra máquina ou com outro número de threads, isso não foi testado.
- **Pontuação das florestas:** não é determinística no último bit. O mesmo arquivo, pontuado duas vezes com 4 threads, dá scores que diferem em até 5,6·10⁻¹⁷. Isso explica a AP do modelo atual na validação, que variou na 9ª casa decimal entre duas execuções: 0,08919944334 e 0,08919944143.

**O que não se reproduz:**

- **As consultas finais.** Os períodos de teste, de reserva e dos testes finais 2 e 3 já foram consultados, e uma nova execução com `--forcar` não seria independente.
- **As execuções que falharam,** X18 e X30.

## 12. Reprodução dos treinos X11 e X25

**Objetivo:** conferir se os dois treinos efetivos podem ser refeitos e se dão os mesmos modelos. É **reprodução do processo de treino**, não avaliação de qualidade nem nova escolha. Nada foi selecionado ou ajustado, e os dias 13 a 23/08 não foram lidos.

### 12.1 Insumos conferidos antes de executar

| Insumo | Situação | Evidência |
|---|---|---|
| **Atributos de treino e validação** (`atributos_L/dia=000` a `007`) | Existem, com data entre 06:19 e 06:25 UTC, gravados em X06 e não regravados depois. SHA-256 de cada arquivo em `g_reproducao_treinos.json` → `insumos.arquivos` | Data dos arquivos; X06 |
| **Amostra do HI-Small de X11** (lote antigo) | Existe como `hismall_treino_S_lote_antigo.parquet`, com data de 06:17:49 UTC: o arquivo original renomeado em X21 | Data; X05 e X21 |
| **Amostra do HI-Small de X25** (lote corrigido) | Existe como `hismall_treino_S.parquet`, com data de 10:04:42 UTC (X21) | Data |
| **Tentativas, para a purga da validação** | `padroes_casados.parquet`, com data de 06:04:33 UTC (X02) | Data |
| **Ordem das colunas** | Lida do artefato de produção, só para leitura; hash `28a13a18…` | — |
| **Código de treino** | `ajustar`, `criar_xgb`, `GRADE`, `manter_purgado` e `carregar` em `c_treinar_avaliar.py`, mais `src/ml/modelos.py`. **Não há cópia do arquivo da época de X11.** A transcrição mostra que as edições posteriores a X11 não tocaram o treino: a Emenda 2 só parametrizou as fontes e o prefixo, e a Emenda 3 passou o carregamento a ser dia a dia, com os mesmos dados e a mesma ordem. `src/ml/modelos.py` está igual ao `9095451`. A diferença de `src/ml/preparacao.py` para o git é só o cálculo em lote, que não entra no treino | Transcrição; `git diff` |
| **Configuração** | Grade, semente 42, 4 threads, peso 5 nos negativos, purga da Emenda 1 e parada antecipada do XGBoost pela validação purgada: tudo no código | Seção 2 |
| **Versões** | Python 3.14.0, NumPy 2.5.4, pandas 3.1.0, pyarrow 26.0.0, scikit-learn 1.9.1, joblib 1.6.0 e SciPy 1.18.1. Nenhum pacote do `.venv` foi alterado desde 09/11 (`insumos.pacotes_do_venv_alterados_desde_09_11` vazio). joblib e SciPy não tinham sido registrados na época | `g_reproducao_treinos.json` |
| **XGBoost** | O mesmo diretório temporário. A SHA-256 da `xgboost.dll`, recalculada agora, é igual à do `RECORD` da instalação (`3LFck91…`) | `insumos.xgboost` |

**Conclusão da conferência:** os insumos eram suficientes. A única ressalva é o código da época, que não foi guardado; a transcrição mostra que o caminho de treino não mudou.

### 12.2 Execução

| ID | Início → fim (UTC) | Tipo | O quê | Desfecho |
|---|---|---|---|---|
| X40 | 21:47 | QC | Ensaio do script de reprodução no scratchpad | **Falhou**: o caminho do scratchpad fora da raiz do projeto quebrou a gravação do resumo. Corrigido com `rel()` no script; nenhum arquivo do projeto foi tocado |
| X40b | 21:48:14 → 21:52:24 | QC | Ensaio de 3 configurações da fonte L (logística, HGB e XGBoost), com a comparação detalhada forçada | Concluído e **descartado**. Os 3 idênticos byte a byte; 60 arquivos protegidos sem alteração |
| X41 | 21:52:36 → 22:58:36 | **T (reprodução)** | `g_reproduzir_treinos.py --execucoes X11 X25`: refaz as 24 configurações em `artefatos_ml/hi_large/reproducao_treinos/X11/` e `X25/`, com `joblib.dump(compress=3)` igual ao original | Concluído (`log_g_reproducao.txt`, `g_reproducao_treinos.json`) |

- **Treino somado:** 3.678 s.
- **Pico de memória:** 8,6 GB, com 4,5 GB de RAM livre no início.
- **Arquivos protegidos:** os hashes de 60 arquivos foram comparados antes e depois. Entre eles estão os modelos originais, as escolhas, o preparador, o contador de consultas, o artefato de produção e os resultados. Nenhum mudou, e nenhum foi criado ou removido.

### 12.3 Resultado

| Execução e fonte | Modelos | Arquivo idêntico ao original (SHA-256) | Igual ao hash registrado em `escolhas*.json` | Escolha pela maior AP na validação | Árvores do XGBoost |
|---|---|---|---|---|---|
| X11, L | 8 | **8 de 8** | 8 de 8 | Igual: XGBoost 8 | 159 e 220, iguais |
| X11, S+L antiga | 8 | **8 de 8** | 8 de 8 | Igual: XGBoost 6 | 218 e 179, iguais |
| X25, S+L corrigida | 8 | **8 de 8** | 8 de 8 | Igual: XGBoost 6 | 341 e 96, iguais |

Como os arquivos são idênticos byte a byte, os pesos, as árvores, os coeficientes e os boosters são os mesmos. Os SHA-256 originais e reproduzidos de cada modelo estão em `g_reproducao_treinos.json` → `execucoes`. A comparação detalhada (coeficientes, árvores, booster) só roda quando os arquivos diferem; aqui, só rodou no ensaio X40b, também com tudo igual.

**Previsões na validação purgada (07 e 08/08), só para conferir a reprodução:**

- **Logística, HGB e XGBoost:** previsões iguais em todas as 2.757.188 linhas, a mesma AP registrada e o mesmo limiar.
- **Florestas:** o **mesmo arquivo**, pontuado duas vezes, dá scores que diferem em até 5,6·10⁻¹⁷, em 28 mil a 66 mil linhas. Isso vem da soma das árvores em 4 threads, cuja ordem varia.
  - O efeito na AP é de até 3,7·10⁻⁸ em relação ao valor registrado.
  - O efeito no limiar aparece só no 17º algarismo.
  - A mesma variação aparece ao pontuar duas vezes o arquivo **original**. É não determinismo da **inferência**, não do treino.
  - Ela explica a variação na 9ª casa da AP do modelo atual na validação, entre X11 e X25 (seção 11).

**Tempos de treino:** variaram de −45% a +34% em relação aos registrados, por exemplo 197 s contra 281 s e 334 s contra 249 s nas florestas. A máquina estava sob pressão de memória, e o tempo não entra no hash.

### 12.4 O que a reprodução comprova e o que não comprova

- **Comprova:** com os mesmos insumos, o mesmo código de treino, as mesmas versões e a mesma máquina, X11 e X25 produzem **exatamente** os mesmos 24 arquivos de modelo, as mesmas escolhas e os mesmos limiares, a menos do arredondamento da pontuação das florestas.
- **Não comprova:**
  - **Qualidade do modelo.** Reproduzir um treino não diz se o modelo é bom. A avaliação de qualidade continua sendo a das consultas X14, X15, X26 e X37, e a conclusão do relatório **não muda**.
  - **Confirmação independente de melhoria.** Nenhum período novo foi consultado.
  - **Reprodução em ambiente limpo:** outra máquina, outro sistema operacional, outra instalação ou outro número de threads não foram testados.
  - **Reprodução dos insumos.** Os atributos e as amostras foram reaproveitados dos arquivos gravados, não regenerados a partir do CSV. A geração de atributos foi reproduzida só nos dias de sobreposição (12/08 e 16/08; seção 8).

### 12.5 Redação de caminhos locais

Antes do commit, foram tirados dos arquivos versionados os dados que só identificam a máquina:

- **Caminho absoluto da pasta do XGBoost.** Em `g_reproducao_treinos.json`, ele foi substituído por um marcador (campo `redacao`), e nada mais mudou nesse arquivo. A cópia original fica fora do git, em `artefatos_ml/hi_large/copias_antes_de_editar/`. `g_reproduzir_treinos.py` e `e_auditoria.py` deixaram de gravar esse caminho.
- **Nome da máquina (`hostname`)** nos XML do JUnit.

A versão do XGBoost, a etiqueta do pacote e o hash da biblioteca continuam registrados.
