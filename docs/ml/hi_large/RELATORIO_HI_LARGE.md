# HI-Large no módulo financeiro: dados, compatibilidade e avaliação

**Data:** 09/11/2026. **Versão avaliada:** NodeWatch na branch `ml/sessoes-analise-datasets`, a partir de `9095451`, com alterações locais. **Modelo atual:** `lavagem-20261102T083253Z`, que não foi alterado.

O plano foi registrado antes dos experimentos, em [`PLANO_AVALIACAO.md`](PLANO_AVALIACAO.md), com SHA-256 `2200c8d6…0851c`, gravado no perfil. Há três emendas, cada uma registrada antes dos experimentos que muda:

- [Emenda 1](EMENDA_1_PURGA_POR_TENTATIVA.md), de purga por tentativa (`878b125e…`);
- [Emenda 2](EMENDA_2_LOTE_CORRIGIDO_E_TESTE_FINAL.md), de lote corrigido e teste final novo (`52f87254…`);
- [Emenda 3](EMENDA_3_SEGUNDO_TESTE_FINAL.md), de segundo teste final (`d62af3cb…`). Os comandos estão no [README](README.md). Cada número vem de `resultados/*.json`. A trilha de auditoria de cada execução (treinos, consultas, falhas, hashes e horários) está em [`REGISTRO_EXPERIMENTOS_E_TREINOS.md`](REGISTRO_EXPERIMENTOS_E_TREINOS.md), e a auditoria de fechamento, na seção 12.

## Resumo

**Medido:**

- Os três arquivos estão íntegros e se associam corretamente.
- São compatíveis com o módulo financeiro em **formato e rótulo nominal**.
- Não são a mesma população: só 19 contas em comum com o HI-Small, quatro vezes mais volume por dia, tentativas 9 vezes mais longas e prevalência menor no início.

**Rodada 1** (plano e Emenda 1; teste de 09 e 10/08 e reserva de 11 e 12/08, consultados uma vez cada; seção 5):

- Os escolhidos treinados com o HI-Large, sozinho (L) ou junto com o HI-Small (S+L), superaram o modelo atual no teste, mas **não na reserva**. O critério do plano não foi atendido.
- A parte HI-Small da S+L dessa rodada foi calculada pelo lote com defeito. Os números de S+L da rodada 1 ficam como **históricos**.

**Rodadas 2 e 3** (S+L refeita com o lote corrigido; dois testes finais novos, cada um com a emenda registrada antes e consultado uma única vez, com os modelos congelados; seções 6 e 7):

| Modelo, contra o atual | Teste final 2 (13 a 16/08) | Teste final 3 (17 a 23/08) |
|---|---|---|
| AP do modelo atual (S) | 0,0978 | 0,1259 |
| **S+L, XGBoost** | +0,0174 (IC +0,0081 a +0,0278), 4 de 4 dias: **atende** a Emenda 2 | **Hipótese principal:** +0,0032 (IC −0,0043 a +0,0105), 3 de 7 dias: **não atende** a Emenda 3 |
| S+L, floresta do mesmo tipo da atual | +0,0103 (+0,0049 a +0,0175), 4 de 4 dias; descritivo, depois da consulta | **Hipótese secundária, resultado exploratório:** +0,0112 (+0,0064 a +0,0172), 6 de 7 dias; atende, mas não muda a conclusão |
| L, XGBoost | −0,0027 (−0,0128 a +0,0076), 2 de 4 dias: não atende | −0,0188 (−0,0279 a −0,0104), 1 de 7 dias; descritivo |
| L, floresta | −0,0177 (−0,0271 a −0,0092); descritivo | −0,0207 (−0,0298 a −0,0133), 0 de 7 dias; descritivo |

**Conclusão: não há melhora confirmada do módulo financeiro com o HI-Large** (seção 8).

- **Treinar só com o HI-Large piora** em relação ao modelo atual.
- **A S+L com XGBoost,** que tinha atendido a Emenda 2, **não se confirmou** no segundo período.
- **A S+L com floresta** ficou acima do atual nos dois testes finais, mas nunca como hipótese principal registrada. É uma pista, não uma confirmação.
- **O modelo do sistema não foi trocado**, e nada foi integrado ao treino.
- A auditoria de fechamento, o que as evidências comprovam e não comprovam e a conclusão estão nas seções 12 a 14.

**Achado colateral, já corrigido:** o cálculo em lote do NodeWatch perdia precisão nas somas em USD. O erro chegava a 27% com valores na escala do HI-Large e a 5,0% no teste do HI-Small, conferido por força bruta. Desde 09/11/2026, as somas acumuladas recomeçam em cada conta, e o erro fica abaixo de 1e-6 (seção 3.4).

A correção **não é melhora do modelo**. O modelo atual mantém os mesmos 620 alertas no teste do HI-Small, e isso só mostra que, para esse modelo e esse teste, a correção não muda decisões. Os resultados das rodadas 2 e 3 vêm de modelos **retreinados** e de testes novos.

## 1. Os três arquivos

**Executado**, em 09/11/2026, por `a_perfil_particionar.py` e `a2_complementos.py`.

| Arquivo | Tamanho | SHA-256 | Conteúdo |
|---|---|---|---|
| `HI-Large_Trans.csv` | 17.052.760.651 bytes | `d13635e2…65c3f2` | 179.702.229 transações; 11 colunas |
| `HI-Large_Patterns.txt` | 13.807.473 bytes | `bcf815a1…c22820` | 16.467 tentativas; 137.936 linhas de transação |
| `HI-Large_accounts.csv` | 147.691.860 bytes | `c799ad25…81cf4` | 2.126.855 contas; 5 colunas |

### 1.1 Transações

- **Esquema:** o mesmo cabeçalho do HI-Small. As colunas são:
  - `Timestamp`, em `AAAA/MM/DD HH:MM`;
  - `From Bank` e `To Bank`, códigos numéricos em texto;
  - duas colunas `Account`, a origem e o destino, com 9 dígitos hexadecimais;
  - valores recebido e pago, com as moedas;
  - `Payment Format`;
  - `Is Laundering`, com 0 ou 1.
- **Qualidade:** nenhum valor ausente, nenhum valor negativo, zero ou não finito e nenhum rótulo fora de {0, 1}. Todos os horários têm segundos iguais a zero. Valores vão de 0,000001 a 8,2·10¹². Pago e recebido coincidem em todas as transações de mesma moeda.
- **Duplicatas exatas:** 150, em 61 dias. Ficam como estão, como as 9 do HI-Small.
- **Ordem:** o arquivo **não é cronológico**. 47,6% das linhas têm horário anterior ao da linha de cima, com recuo de até 70 dias. Por isso a leitura separa as linhas por dia antes de calcular qualquer coisa.
- **Período:** de 01/08/2022 a 12/01/2023, em 165 dias.

| Período | Dias | Transações | Positivos | Prevalência |
|---|---|---|---|---|
| Principal (01/08 a 05/11/2022) | 97 | 179.661.510 | 201.273 | 0,112% |
| Cauda do gerador (06/11/2022 a 12/01/2023) | 68 | 40.719 | 24.273 | 59,6% |
| Janela de modelagem (01 a 12/08/2022) | 12 | 25.268.680 | 13.682 | 0,054% |

A cauda tem menos de 1% do volume diário mediano, que é de 831.092, e cerca de 60% de lavagem. É o mesmo artefato do gerador visto no HI-Small, onde a cauda começa em 11/09. A regra do plano a exclui só pelo volume.

**Rótulo, segundo a fonte.** O artigo que publica o conjunto (Altman et al., 2023, arXiv:2306.16424, seções 3.1 a 3.5 e apêndice A) explica:

- O rótulo vem do **próprio gerador**. Como ele "sabe a origem de todos os fundos", sabe quais transferências são lavagem e propaga essa marca entre as transações.
- Não vem de regra de detecção nem de investigação, e o artigo apresenta os rótulos como completos.
- A lavagem **não se limita aos 8 padrões**: parte dela ocorre "naturalmente", por exemplo quando o criminoso paga salários ou compra insumos.
- No LI-Large, cerca de 80% da lavagem fica fora dos padrões (tabela 8 do artigo).
- A tabela 4 do artigo dá ao HI-Large 97 dias, cerca de 2.116 mil contas, 180 M de transações e 223 mil de lavagem, a mesma ordem de grandeza medida aqui.

A página do Kaggle não pôde ser lida, e o nome exato da coluna vem dos arquivos.

Portanto, `Is Laundering = 1` marca transações que o **simulador** gerou como parte de lavagem. É verdade de simulação: não é fraude confirmada, não tem data de confirmação nem investigação, e lavagem não representa todos os tipos de fraude. A prevalência sobe com o tempo: 0,02% em 01/08 e cerca de 0,13% nos dias úteis de outubro. Isso é coerente com tentativas que se acumulam ao longo de semanas.

### 1.2 Contas e identidade

- **Cadastro:** 2.126.855 contas, sem valores ausentes. A chave `banco-conta`, com o banco numérico, não se repete, e todas as 2.116.168 contas das transações existem no cadastro. 10.687 contas cadastradas não aparecem em nenhuma transação.
- **Zeros à esquerda:** todos os códigos de banco das transações têm zero à esquerda, e os do cadastro não têm. Há 122.394 códigos em texto, mas 122.333 números. Em 61 casos, dois textos, como `0011` e `011`, viram o mesmo número.
  - O cadastro tem **um único nome de banco por número**. Logo, a identidade do NodeWatch, com banco numérico, é a correta.
  - Comparar o código como texto separaria contas que são a mesma.
- **Entidades:** 670.231, com tipos parecidos aos do HI-Small: Partnership, Corporation, Sole Proprietorship, Country, Individual e Direct.
- **Contas e entidades nunca viram atributo.** O identificador de entidade ligaria contas de um mesmo dono e poderia carregar informação de rótulo.

### 1.3 Padrões

- 16.467 tentativas em 8 tipologias, com cerca de 2.000 de cada tipo. Todas as 137.936 linhas têm rótulo 1, e **todas casam com uma transação positiva** pela chave completa: minuto, contas, valor pago e formato. Nenhuma linha se repete entre tentativas.
- **38,8% dos positivos (87.610) não pertencem a nenhum padrão.** No HI-Small, eram 38,0%. Os padrões descrevem só parte do que o simulador rotula.
- **As tentativas duram muito mais que no HI-Small:**

| Duração da tentativa | HI-Small | HI-Large |
|---|---|---|
| Mediana | 75 h (3,1 dias) | 655 h (27 dias) |
| Percentil 90 | 110 h | 891 h (37 dias) |
| Máximo | 202 h (8,4 dias) | 1.691 h (70 dias) |

Dentro da janela de 12 dias, 1.552 das 1.810 tentativas atravessam a fronteira entre partições. O teste do HI-Large tem, portanto, poucas tentativas novas.

## 2. HI-Large × HI-Small

| Aspecto | HI-Small (usado hoje) | HI-Large | Consequência |
|---|---|---|---|
| Esquema e tipos | `hismall_v1` | Igual | Leitura e validação do NodeWatch servem |
| Moedas e formatos | 15 e 7 | Os mesmos 15 e 7 | One-hot igual: as 49 colunas coincidem |
| Câmbio estimado no treino | — | Mesmo método; difere até 0,12% (libra) e cerca de 0,013% nas demais moedas | Quase idêntico, mas não igual: atributos calculados com cada preparador |
| Período | 01 a 10/09/2022, mais cauda até 18/09 | 01/08 a 05/11/2022, mais cauda até 12/01/2023 | Mesmo calendário em parte, mas são **simulações separadas** |
| Contas | 518.581 | 2.126.855 | Só 19 chaves em comum, e 1 com o mesmo nome de entidade: populações independentes |
| Volume por dia útil | ~480 mil | ~1,93 milhão | Estado e atributos 4 vezes maiores por dia |
| Prevalência no período principal | 0,089% | 0,112% (0,044% no treino da janela) | Linha de base da AP diferente entre as bases |
| ACH entre os positivos | 86,6% | 88,3% | O mesmo sinal grosso |
| Positivos sem padrão | 38,0% | 38,8% | Semelhante |
| Duração das tentativas | mediana de 3 dias | mediana de 27 dias | **Diferença de significado**: o mesmo nome de padrão tem outra escala de tempo |
| Mesmo banco / autotransferência | 13,6% / 11,6% | 6,8% / 6,1% | Estrutura da população diferente |
| Arquivo | ZIP de 5 M linhas, lido inteiro na memória | CSV de 17 GB, fora de ordem | O leitor atual (`ler_hismall`) não serve: exige memória para o arquivo inteiro |

**Leitura.** Os arquivos são compatíveis em **formato** e em **rótulo nominal**: mesma coluna `Is Laundering`, mesmas tipologias, mesmo gerador AMLworld (Altman et al., 2023). Não são a mesma população nem o mesmo regime temporal. São outras contas, quatro vezes mais volume, prevalência diferente e tentativas nove vezes mais longas. Juntar as bases é empilhar exemplos de dois cenários simulados. Não há continuidade de contas nem de histórico entre eles.

## 3. Conferências: partições, hashes e atributos

### 3.1 As 116 partições × 97 dias

**Explicado e conferido duas vezes:** por `a3_conferencia.py`, contra o perfil, e por `a6_reconferencia.py`, que relê as 165 partições sem usar nenhum resultado da primeira passada. A tabela completa, dia a dia, com arquivo, bytes, linhas e positivos, está em [`PARTICOES.md`](PARTICOES.md).

| Número | Origem |
|---|---|
| **116** | Arquivos que existiam **durante** a leitura, às 02:55. O CSV é fora de ordem, e uma partição é criada quando o primeiro registro do dia aparece |
| **165** | Partições ao fim da leitura: uma por dia com transações, de 01/08/2022 a 12/01/2023 |
| **97** | Dias do período principal (01/08 a 05/11) |
| **68** | Dias da cauda do gerador (06/11/2022 a 12/01/2023), com menos de 1% do volume mediano |

Verificação linha a linha, com um mapa de 179.702.229 posições:

| Item | Resultado |
|---|---|
| Linhas somadas nas 165 partições | 179.702.229, igual ao número de linhas do CSV |
| Linhas repetidas entre ou dentro de partições | 0 |
| Linhas ausentes | 0 |
| Linhas em partição de outro dia | 0 |
| Positivos somados | 225.546, igual ao perfil |
| Dias com contagem diferente do perfil | 0 |
| Arquivos com dia repetido, ou com minutos de outro dia (sobreposição) | 0 e 0 (`a6`) |
| Dias sem arquivo entre 01/08/2022 e 12/01/2023 | 0 (`a6`) |
| Contas das transações sem cadastro; chaves repetidas no cadastro (`a6`, relendo) | 0; 0 |
| Linhas de padrão casadas com positivos relidos agora (`a6`) | 137.936 de 137.936; 87.610 positivos sem padrão (38,8%) |

### 3.2 Hashes

Os três SHA-256 foram recalculados depois das passadas de atributos e de novo no fim da Emenda 2. Nas duas vezes, são **iguais** aos do perfil (`a3_conferencia.json`). Todos os resultados desta pasta vêm desses arquivos.

### 3.3 Atributos gravados

Nos dois preparadores, os 12 dias foram conferidos. Nenhuma `_linha` se repete, nenhuma fica fora da partição do dia, e cada dia tem **todos os positivos da partição**. Nos dias de treino, ficam todos os positivos e 20% dos negativos. Nos demais, ficam todas as linhas.

**Teste final novo** (`b6_conferencia_final2.json`):

- Os dias 13 a 16/08 têm todas as linhas e todos os positivos da partição, nos dois preparadores, sem `_linha` repetida ou fora da partição. São 829.920, 830.550, 1.928.907 e 1.930.159 linhas, com 1.278, 1.305, 1.519 e 1.594 positivos.
- A passada refeita do dia 1 reproduz o dia 12/08 da primeira passada **coluna por coluna**: 2.621.701 linhas, 57 colunas e diferença zero, nos dois preparadores.

**Segundo teste final, da Emenda 3** (`b6_conferencia_final3.json`, conferido **antes** da consulta):

- Os dias 17 a 23/08 têm todas as linhas e todos os positivos da partição, nos dois preparadores, sem `_linha` repetida ou fora da partição. São 12.394.384 linhas e 11.528 positivos antes da purga.
- A terceira passada, também refeita do dia 1, reproduz o dia 16/08 da passada da Emenda 2 coluna por coluna: 1.930.159 linhas e diferença zero.

### 3.4 Estado incremental × lote × força bruta, em dados reais

**O defeito.** O cálculo em lote do treino do NodeWatch perdia precisão nas somas em USD de 24 h. Ele somava prefixos acumulados sobre **todo** o histórico, de todas as contas, e tirava a soma de uma janela pela diferença de dois prefixos enormes. No HI-Large, os valores chegam a 8·10¹².

**Todos os atributos do HI-Large desta avaliação vêm do estado incremental**, que soma por conta e não usa o lote. A seção 3.5 diz quais artefatos dependiam do lote.

**A correção, em 09/11/2026.** Em `src/ml/preparacao.py` (`_IndiceEventos`), as somas acumuladas recomeçam em cada conta, e a soma de uma janela usa só os eventos da própria conta. A versão anterior continua no git (`9095451`).

#### O que foi comparado

Três scripts conferem a correção, cada um com sua própria seleção de linhas. A referência é a força bruta de `testes/ml/referencia_financeira.py`, que recalcula cada linha varrendo o histórico, sem prefixos.

| Script | Conjunto | Linhas comparadas | Histórico na entrada | Comparação em todas as linhas | Força bruta |
|---|---|---|---|---|---|
| `b3_equivalencia.py` | HI-Large, 02/08/2022, dia de treino | 387.075 gravadas pelo incremental: os 1.011 positivos e 20% dos negativos | 01 e 02/08 (6.398.406 transações) | Lote × incremental, 49 colunas, antes e depois da correção | 300 linhas: as 200 de maior diferença na razão e 100 sorteadas com semente 42 |
| `b4_correcao_lote.py` | HI-Small, teste (09 e 10/09/2022) | 862.792 | HI-Small inteiro (5.078.345) | Lote anterior × corrigido; scores e alertas do modelo atual | 300 linhas: as 200 de maior diferença e 100 sorteadas |
| `b5_amostra_estratificada.py` | Os dois acima, mais a amostra de treino do HI-Small (651.808 linhas) | Todas, em cada conjunto | Igual aos de cima | Lote anterior × corrigido; no HI-Large, também os dois contra o incremental | 4 estratos de 100 linhas por conjunto: 1.200 linhas |

**Registros fora de ordem.** Em todos os conjuntos, o lote recebe as transações na ordem do arquivo, que não é cronológica. No HI-Large, 47,8% das linhas consecutivas voltam no tempo, e no HI-Small, 47,6%. Por isso, todas as linhas comparadas, e não só uma amostra, passam por entrada fora de ordem.

**Estratos de `b5`**, escolhidos nesta ordem e sem repetir linha:

1. **Maior divergência antiga:** as 100 de maior diferença relativa na razão entre o lote anterior e o corrigido.
2. **Acumulado grande:** as 100 cuja conta de origem mais enviou em USD antes do minuto. No estrato, o mínimo enviado é de 72 bilhões no HI-Large, 37 bilhões na amostra de treino do HI-Small e 53 bilhões no teste.
3. **Borda de janela:** 100 sorteadas entre as linhas cuja origem tem evento num minuto de borda:
   - em t − 1440, o primeiro minuto da janela de 24 h, que é incluído;
   - em t − 1, o último minuto incluído;
   - ou outra transação no próprio minuto t, que é excluída.

   São 86.181 linhas assim no HI-Large, 118.414 na amostra de treino do HI-Small e 172.611 no teste.
4. **Sorteada:** 100 ao acaso.

#### Resultado contra a força bruta

Maior erro relativo nas quatro colunas que o lote calcula com somas acumuladas: as somas enviada e recebida em USD em 24 h, a razão saída/entrada e `z_valor_origem`. Nenhuma outra coluna passou de 1e-6.

| Conjunto | Estrato | Lote anterior | Lote corrigido | Incremental |
|---|---|---|---|---|
| HI-Large, 02/08 | Maior divergência antiga | 3,07% | 5,65·10⁻⁸ | 5,65·10⁻⁸ |
| | Acumulado grande | 5,35·10⁻⁸ | 5,35·10⁻⁸ | 5,35·10⁻⁸ |
| | Borda de janela | **26,6%** | 5,25·10⁻⁸ | 5,25·10⁻⁸ |
| | Sorteada | 0,148% | 5,69·10⁻⁸ | 5,69·10⁻⁸ |
| HI-Small, amostra de treino | Maior divergência antiga | **100%** | 4,65·10⁻⁸ | — |
| | Acumulado grande | 4,84·10⁻⁸ | 4,84·10⁻⁸ | — |
| | Borda de janela | 1,89% | 5,68·10⁻⁸ | — |
| | Sorteada | 0,0142% | 5,36·10⁻⁸ | — |
| HI-Small, teste | Maior divergência antiga | 5,02% | 5,42·10⁻⁸ | — |
| | Acumulado grande | 5,02·10⁻⁸ | 5,02·10⁻⁸ | — |
| | Borda de janela | 2,16·10⁻⁶ | 5,82·10⁻⁸ | — |
| | Sorteada | 6,27·10⁻⁶ | 5,76·10⁻⁸ | — |

**Leitura:**

- O lote corrigido e o incremental ficam abaixo de 6·10⁻⁸ em todos os estratos.
- O erro antigo **não** aparecia nas contas de acumulado grande. Nelas, a soma da janela também é grande, e o erro relativo fica pequeno. O erro estava nas somas **pequenas**, calculadas como diferença de dois prefixos globais grandes, e por isso aparece nas bordas e nas maiores divergências.
- Erro de 100% quer dizer que o lote antigo devolvia zero onde a soma real era positiva. São somas minúsculas, de cerca de 0,0001 dólar (seção 3.5).
- O resultado de `b3` anterior à correção está em `b3_equivalencia_antes_da_correcao.json`, com o mesmo máximo: 27% em `soma_rec_origem_usd_24h` e 3,1% na razão.

#### As 10.560 linhas que divergiam

No HI-Large, `b5` comparou o lote anterior e o corrigido com o incremental em **todas** as 387.075 linhas, não numa amostra. O critério é `numpy.isclose`, com tolerância relativa de 1e-5 e absoluta de 1e-3, nas 49 colunas.

| | Lote anterior | Lote corrigido |
|---|---|---|
| Linhas que divergem do incremental | 10.560 | **0** |
| Das 10.560, iguais ao incremental | — | 10.560 |
| Maior diferença relativa para o incremental | até 3% na razão | 2,3·10⁻⁶ na soma recebida; 1,2·10⁻⁷ na enviada; 1,1·10⁻⁷ na razão |

São 10.560 linhas, o mesmo número que `b3` encontrou divergindo na razão. Com um limiar mais fino, de 1e-6 relativo, o lote anterior difere do corrigido em mais linhas: 33.240 na razão, 24.902 na soma recebida, 11.949 na enviada e 33 em `z_valor_origem`.

#### Resumo antes × depois

| Conferência | Antes | Depois |
|---|---|---|
| HI-Large, 02/08: maior erro do lote contra a força bruta (`b3`, 300 linhas; `b5`, 400) | 27% em `soma_rec_origem_usd_24h`; 3,1% na razão | Abaixo de 6·10⁻⁸ |
| HI-Large, 02/08: lote × incremental (387.075 linhas) | 10.560 linhas divergentes | 0 divergentes |
| HI-Small, teste: maior erro do lote contra a força bruta (`b4`, 300 linhas; `b5`, 400) | 5,0% em `soma_env_origem_usd_24h` e na razão | Abaixo de 6·10⁻⁸ |
| HI-Small, teste: modelo atual, sem retreino (`b4`) | AP 0,4640; 620 alertas | Score com diferença máxima de 8·10⁻¹⁷; 620 alertas, nenhum muda de lado; AP 0,4640 |
| Tempo dos atributos do teste do HI-Small (862.792 linhas, 2 execuções) | 15,5 e 15,9 s | 16,1 e 16,5 s |

#### O que a conferência não cobre

- **A força bruta é amostral:** 300 linhas em `b3` e em `b4`, e 400 por conjunto em `b5`. A cobertura de todas as linhas vem de duas implementações independentes que concordam, o lote corrigido e o incremental, e só no dia 02/08 do HI-Large.
- **No HI-Small,** a comparação em todas as linhas é só entre o lote anterior e o corrigido, porque não há incremental gravado para ele.
- **O modelo atual não mudou de decisão,** e isso só vale para ele e para o teste do HI-Small. Ele foi treinado com o lote antigo e não foi retreinado. Isso não diz nada sobre modelos treinados com os atributos corrigidos, que são outros (seção 6).

A medição de 06/11/2026, com até 0,058% de erro no dia 10/09 (`docs/ml/BENCHMARK_EVENTOS.md`), subestimava o problema no HI-Small: no teste inteiro, o erro chegava a 5,0%.

### 3.5 Origem dos atributos de cada experimento

| Atributos | Como foram calculados | Usados em | Afetados pelo lote antigo? |
|---|---|---|---|
| `atributos_S` e `atributos_L`: HI-Large, dias 1 a 12 | `EstadoFinanceiro`, incremental, às 03:07–03:29 | Modelo atual no HI-Large; treino, validação, teste e reserva de L e de S+L (parte HI-Large) | **Não**. O lote não é usado. O dia 12 recalculado na Emenda 2 é idêntico ao arquivo original |
| `atributos_S_final2` e `atributos_L_final2`: dias 13 a 16 | Incremental, refeito do dia 1, às 07:05–07:35 | Teste final novo (Emenda 2) | Não |
| `atributos_S_final3` e `atributos_L_final3`: dias 17 a 23 | Incremental, refeito do dia 1, depois do registro da Emenda 3 | Teste final 3 (Emenda 3) | Não. O dia 16/08 regravado é idêntico ao da Emenda 2 |
| `hismall_treino_S`: amostra de treino do HI-Small | **Lote antigo** (03:17) → **regenerado** com o lote corrigido (Emenda 2) | Parte HI-Small da S+L | **Sim**. A S+L da rodada 1 usou o arquivo antigo; a S+L da Emenda 2 usa o novo |
| `hismall_teste_L`: teste do HI-Small com o preparador L | Lote antigo (03:18) → regenerado | Descritivo (`f_hismall`) | Sim. Refeito |
| `artefatos_ml/cache/financeiro_teste.parquet` | Lote antigo (02/11) | Modelo atual no teste do HI-Small, descritivo | Sim. O efeito foi medido em `b4`: nenhum alerta muda |

**Na amostra de treino do HI-Small**, a regeneração preservou linhas, rótulos e pesos. Mudaram 4 colunas:

| Coluna | Linhas que mudaram (diferença > 1e-6) |
|---|---|
| `razao_saida_entrada_24h` | 30.365 |
| `soma_rec_origem_usd_24h` | 23.755 |
| `soma_env_origem_usd_24h` | 20.779 |
| `z_valor_origem` | 33 |

Na razão, 260 dessas linhas diferem mais de 1% e 82 mais de 10%. As maiores diferenças relativas são somas minúsculas, de cerca de 0,0001 dólar, que o lote antigo arredondava para zero. Os arquivos antigos ficam em `artefatos_ml/hi_large/*_lote_antigo.parquet`.

## 4. Protocolo

### 4.1 Processar por dia não é dividir a avaliação

- **A partição por dia** só existe para processar um CSV de 17 GB fora de ordem sem carregá-lo na memória. O estado incremental atravessa os 12 dias em ordem de minuto, do dia 1 ao 12, sem reiniciar, como um sistema recebendo transações.
- **A divisão da avaliação** é outra decisão, fixada no plano antes dos experimentos:
  - treino: 01 a 06/08;
  - validação: 07 e 08/08;
  - teste: 09 e 10/08;
  - reserva: 11 e 12/08.
- **Contra vazamento temporal:** os atributos usam só minutos estritamente anteriores, e transações do mesmo minuto não se enxergam. Isso é garantido pelo `EstadoFinanceiro` e conferido acima e nos testes.
- **Ajustes:** câmbio, categorias, taxa por formato e quantis vêm só do treino.

### 4.2 Tentativas que atravessam partições

As tentativas duram semanas. A tabela mostra quantas tentativas, conforme a partição em que começam, têm eventos em cada partição (`a4_tentativas.json`):

| Começa em ↓ / tem eventos em → | treino | validação | teste | reserva | depois do dia 12 |
|---|---|---|---|---|---|
| treino | 854 | 265 | 275 | 283 | 700 |
| validação | — | 319 | 93 | 106 | 276 |
| teste | — | — | 290 | 79 | 240 |
| reserva | — | — | — | 347 | 296 |

| Positivos | treino | validação | teste | reserva |
|---|---|---|---|---|
| De tentativa iniciada na própria partição | 1.429 | 394 | 365 | 438 |
| **Continuação** de tentativa iniciada antes | 0 | 376 | 505 | 666 |
| Sem padrão (não agrupável) | 4.805 (77%) | 1.392 (64%) | 1.657 (66%) | 1.655 (60%) |
| Total | 6.234 | 2.162 | 2.527 | 2.759 |

**Emenda 1** ([`EMENDA_1_PURGA_POR_TENTATIVA.md`](EMENDA_1_PURGA_POR_TENTATIVA.md), SHA-256 `878b125e…f006`). Foi registrada às 06:29 UTC, antes de qualquer modelo ser treinado. Pela emenda, a validação, o teste e a reserva **excluem a continuação** de tentativas iniciadas em partição anterior, e essa é a métrica principal.

Com isso, nenhuma tentativa com padrão conhecido tem eventos no treino e no conjunto avaliado, nem na validação e no teste ao mesmo tempo. As métricas sem purga aparecem à parte.

**Limitação:** nos primeiros dias, a maioria dos positivos não pertence a nenhum padrão. Esses positivos não podem ser agrupados e ficam na avaliação. Se algum deles for continuação de um esquema não listado, a purga não o alcança.

## 5. Resultados da rodada 1 (plano e Emenda 1)

Todos os modelos foram comparados nas **mesmas divisões do HI-Large**, com a purga da Emenda 1.

| Sigla | O que é |
|---|---|
| **S** | Modelo atual congelado, treinado no HI-Small, com o próprio preparador. Mede **generalização entre fontes** |
| **L** | Treino com os dias 1 a 6 do HI-Large (atributos com o preparador do HI-Large). Mede **treino com parte do HI-Large** |
| **S+L** | A amostra de treino do HI-Small, com o preparador atual, empilhada à de L. A avaliação no HI-Large usa os atributos de L |

> **Histórico.** Nesta rodada, a parte HI-Small da S+L veio do lote com defeito (seção 3.5). Os números de S+L das seções 5.1 a 5.4 ficam como registro e não são a S+L corrigida, avaliada na seção 6. Os de S, de L e das referências não dependem do lote e continuam válidos.

### 5.1 Validação: escolhas (07 e 08/08/2022, purgada)

**Executado.** Fonte: `c_validacao.json`. Escolhas congeladas em `artefatos_ml/hi_large/escolhas.json`, com SHA-256 `f5ee059f…`, antes do teste.

A validação purgada tem 2.757.188 transações, 1.786 positivas e prevalência de 0,065%. A purga retirou 376 positivos de continuação.

| Fonte | Candidato | AP val. | AP val. sem purga | Treino (s) | Tamanho (MB) |
|---|---|---|---|---|---|
| S | Random Forest atual (100 árvores, folha 50) | 0,089 | — | — (já treinado) | 36,9 (artefato) |
| L | Logística C = 0,1 / 1,0 | 0,027 / 0,027 | 0,049 / 0,052 | 31 / 33 | 0,003 |
| L | RF 100 árvores, folha 50 | 0,059 | 0,134 | 281 | 9,5 |
| L | RF 200 árvores, folha 10 | 0,049 | 0,124 | 503 | 30,6 |
| L | HGB 31 / 63 folhas | 0,052 / 0,038 | 0,096 / 0,061 | 65 / 62 | 0,5 / 0,9 |
| L | XGBoost profundidade 6 / **8** | 0,098 / **0,106*** | 0,190 / 0,199 | 163 / 206 | 0,2 / 0,5 |
| S+L, lote antigo | Logística C = 0,1 / 1,0 | 0,031 / 0,032 | 0,064 / 0,067 | 39 / 39 | 0,003 |
| S+L, lote antigo | RF 100 árvores, folha 50 | 0,090 | 0,194 | 338 | 11,7 |
| S+L, lote antigo | RF 200 árvores, folha 10 | 0,095 | 0,208 | 620 | 38,8 |
| S+L, lote antigo | HGB 31 / 63 folhas | 0,057 / 0,054 | 0,115 / 0,111 | 53 / 55 | 0,5 / 0,9 |
| S+L, lote antigo | XGBoost profundidade **6** / 8 | **0,111*** / 0,108 | 0,226 / 0,216 | 169 / 149 | 0,3 / 0,4 |

\* Escolhido na fonte. É **otimista**: a parada antecipada do XGBoost também usou esta validação.

**Referências na mesma validação**, todas ajustadas no treino do HI-Large:

| Referência | Resultado |
|---|---|
| Prevalência | AP 0,0006 |
| Taxa do formato | AP 0,0033 |
| F2, contagem de motivos | AP 0,0051; o melhor k foi 2, com F1 de 0,015 |
| F3, "formato de risco e par novo" | 78.926 alertas, precisão de 1,4%, recall de 61% e F1 de 0,027 |

**Limiares e modelo atual.** O modelo atual S, no limiar do artefato (0,0910), dá 1.116 alertas, com precisão de 17,7% e recall de 11,0%. O limiar recalculado nesta validação é 0,0862.

**Leitura da validação.** O modelo atual, sem ver nada do HI-Large, tem AP **melhor** que qualquer floresta treinada só no HI-Large: 0,089 contra 0,059. Juntar o HI-Small ao treino melhora todas as famílias. O XGBoost lidera nas duas fontes, mas com a vantagem otimista da parada antecipada.

### 5.2 Teste (09 e 10/08/2022, purgado): avaliação única

**Executado uma vez**, depois de congeladas todas as escolhas (`d_teste.json`; `consultas.json`: teste = 1). O SHA-256 de `escolhas.json` foi conferido igual antes e depois.

O teste purgado tem 3.855.946 transações e 2.022 positivas, com prevalência de 0,052%. A purga retirou 505 positivos de continuação.

Dos 2.022 positivos avaliados, 365 são de tentativas novas e 1.657 (82%) são **sem padrão**.

| Modelo (limiar escolhido na validação) | AP | AP 09/08 | AP 10/08 | Alertas | VP | FP | FN | Precisão | Recall | F1 |
|---|---|---|---|---|---|---|---|---|---|---|
| **S** atual, limiar do artefato (0,0910) | **0,070** | 0,065 | 0,076 | 1.232 | 202 | 1.030 | 1.820 | 0,164 | 0,100 | 0,124 |
| S atual, limiar da validação HI-Large (0,0862) | 0,070 | 0,065 | 0,076 | 1.527 | 225 | 1.302 | 1.797 | 0,147 | 0,111 | 0,127 |
| **L** escolhido: XGBoost profundidade 8 | **0,079** | 0,067 | 0,091 | 1.712 | 248 | 1.464 | 1.774 | 0,145 | 0,123 | 0,133 |
| **S+L** escolhido, lote antigo: XGBoost profundidade 6 | **0,089** | 0,077 | 0,102 | 738 | 179 | 559 | 1.843 | 0,243 | 0,089 | 0,130 |
| L, RF de produção (descritivo) | 0,061 | 0,056 | 0,067 | 1.142 | 170 | 972 | 1.852 | 0,149 | 0,084 | 0,107 |
| S+L, lote antigo, RF de produção (descritivo) | 0,077 | 0,072 | 0,081 | 761 | 169 | 592 | 1.853 | 0,222 | 0,084 | 0,121 |
| L, logística C = 0,1 (descritivo) | 0,020 | 0,019 | 0,022 | 4.994 | 197 | 4.797 | 1.825 | 0,039 | 0,097 | 0,056 |
| Taxa do formato | 0,002 | — | — | 463.349 | 1.413 | 461.936 | 609 | 0,003 | 0,699 | 0,006 |
| Regra F3: formato de risco e par novo | sem ranking | — | — | 76.187 | 1.107 | 75.080 | 915 | 0,015 | 0,547 | 0,028 |
| Regra F2: 2 ou mais motivos | 0,004 | — | — | 170.836 | 1.147 | 169.689 | 875 | 0,007 | 0,567 | 0,013 |

Verdadeiros negativos: 3.852.894 para S no limiar do artefato, 3.852.460 para L e 3.853.365 para S+L. Os demais estão em `d_teste.json`.

Bootstrap pareado da diferença de AP sobre o modelo atual S, agrupado por conta de origem, com 1.000 reamostras:

| Diferença | AP | IC 95% | Fração > 0 |
|---|---|---|---|
| L − S | +0,009 | [−0,003; +0,022] | 0,94 |
| S+L (lote antigo) − S | +0,019 | [+0,008; +0,032] | 1,00 |
| S+L (lote antigo) − L | +0,010 | [+0,003; +0,018] | 1,00 |

**Sem purga** (secundário), o mesmo teste dá AP de 0,194 para S, 0,195 para L e 0,231 para S+L. Contar a continuação de tentativas já vistas quase **triplica** a AP. É a evidência de que a purga era necessária.

| Recall sem purga, por grupo | S | L | S+L |
|---|---|---|---|
| Tentativa iniciada antes do teste (505 positivos) | 0,64 | 0,67 | 0,66 |
| Tentativa nova (365) | 0,44 | 0,52 | 0,44 |
| Sem padrão (1.657) | 0,02 | 0,04 | 0,01 |

### 5.3 Reserva (11 e 12/08/2022, purgada): confirmação única

**Executado uma vez**, só com os escolhidos (`d_reserva.json`; `consultas.json`: reserva = 1). A reserva tem 4.550.177 transações e 2.093 positivas, com prevalência de 0,046%. A purga retirou 666 positivos.

| Modelo | AP | AP 11/08 | AP 12/08 | Alertas | Precisão | Recall | F1 |
|---|---|---|---|---|---|---|---|
| **S** atual, limiar do artefato | **0,081** | 0,081 | 0,083 | 1.369 | 0,174 | 0,114 | 0,137 |
| **L** escolhido | 0,067 | 0,086 | 0,052 | 1.859 | 0,136 | 0,121 | 0,128 |
| **S+L** escolhido, lote antigo | 0,081 | 0,090 | 0,073 | 759 | 0,249 | 0,090 | 0,133 |
| Taxa do formato | 0,002 | — | — | 588.925 | 0,002 | 0,688 | 0,005 |

| Diferença de AP | Valor | IC 95% |
|---|---|---|
| L − S | −0,015 | [−0,028; −0,003] |
| S+L (lote antigo) − S | −0,001 | [−0,012; +0,010] |

### 5.4 HI-Small (09 e 10/09/2022): teste já consultado, só descritivo

Fonte: `f_hismall_lote_antigo.json`, que é a cópia do resultado da rodada 1. Os modelos L e S+L usam aqui os atributos com o preparador do HI-Large, calculados na época pelo lote antigo. A versão refeita com o lote corrigido está na seção 6.4.

| Modelo | AP | Precisão | Recall | F1 | VP | FP |
|---|---|---|---|---|---|---|
| S atual (cache do NodeWatch) | 0,464 | 0,627 | 0,407 | 0,494 | 389 | 231 |
| L escolhido: generalização L→S | 0,339 | 0,425 | 0,357 | 0,388 | 341 | 462 |
| S+L escolhido, lote antigo | 0,484 | 0,702 | 0,400 | 0,509 | 382 | 162 |

**Generalização entre fontes.** O modelo atual cai de AP 0,464 no HI-Small para 0,070 a 0,081 no HI-Large, com purga. O modelo treinado no HI-Large cai de 0,079 para 0,339 no HI-Small, onde a prevalência é o dobro e os positivos sem padrão são 39%, não 82%. As AP não são comparáveis em valor absoluto entre as bases, porque a prevalência e a composição dos positivos são diferentes.

### 5.5 Custo de processamento

**Medido**, nesta máquina: Windows 11, 20 CPUs lógicas, 15,7 GB de RAM, só cerca de 2 GB disponíveis durante as medições por causa de outros programas, 4 threads. Versões: Python 3.14.0, NumPy 2.5.4, pandas 3.1.0, pyarrow 26.0.0, scikit-learn 1.9.1 e XGBoost 3.4.1 (fora do `.venv`). Semente 42.

| Etapa | Tempo | Memória de pico | Observação |
|---|---|---|---|
| Ler 17 GB, perfilar e particionar | 732 s | 6,6 GB | Uma passada; 245 mil linhas/s |
| Duplicatas por dia | 188 s | — | 165 partições |
| Hash dos três arquivos | em paralelo à leitura | — | — |
| Ajustar o preparador L | 21 s | — | 14,1 M linhas do treino |
| Atributos dos 12 dias, por passada (S ou L) | 662 s | 5,1 GB | 25,3 M transações; **38 mil transações/s**; estado com 2,07 M contas e 4,2 M pares |
| Atributos do HI-Small (lote, amostra de treino) | 16 s | 3,7 GB | 651.808 linhas |
| Treino, fonte L (2,83 M linhas) | logística 31 s; RF 281 a 503 s; HGB 62 a 65 s; XGBoost 163 a 206 s | 7,6 GB no processo de avaliação | — |
| Treino, fonte S+L, lote antigo (3,48 M linhas) | logística 39 s; RF 338 a 620 s; HGB 53 a 55 s; XGBoost 149 a 169 s | 9,7 GB | — |
| Pontuação em lote, validação | S (RF) 489 mil linhas/s; XGBoost escolhido 0,75 a 1,1 milhão de linhas/s | — | — |
| Uma linha, mediana / p99 | S 9,6 / 13,4 ms; L 3,2 / 9,7 ms; S+L 2,7 / 4,0 ms | — | Pipeline com uma thread; máquina com pouca memória livre |
| Disco | partições 3,7 GB; atributos 2 × 0,56 GB; modelos 95 MB | — | Em `artefatos_ml/hi_large/`, fora do git |

Os tempos de treino são de uma única execução cada, sem repetição. Os custos da rodada 2 estão na seção 6.5.

## 6. Resultados da rodada 2 (Emenda 2: lote corrigido e teste final novo)

A [Emenda 2](EMENDA_2_LOTE_CORRIGIDO_E_TESTE_FINAL.md) (SHA-256 `52f87254…42317`) foi registrada às 10:03 UTC de 09/11/2026. Isso foi **antes** de regenerar os atributos do HI-Small, de retreinar a S+L e de calcular qualquer atributo dos dias 13 a 16/08. Ela:

- refaz só o que dependia do lote antigo: a amostra de treino do HI-Small e, com ela, a S+L inteira;
- **não refaz L:** os atributos do HI-Large vêm do incremental, e os 8 candidatos de L continuam os mesmos, com as escolhas de `escolhas.json`;
- **não reconsulta** o teste nem a reserva da rodada 1;
- cria um **teste final novo**, de 13 a 16/08/2022, com a purga da Emenda 1, e um critério escrito antes de vê-lo.

**Critério de melhora da Emenda 2:** AP maior que a do modelo atual no período inteiro, com o intervalo de 95% do bootstrap pareado, agrupado por conta de origem, excluindo zero, e AP maior em pelo menos 3 dos 4 dias.

### 6.1 Validação da S+L refeita (07 e 08/08/2022, purgada)

**Executado.** Fonte: `c_validacao_emenda2.json`. É a mesma validação purgada da rodada 1: 2.757.188 transações e 1.786 positivas. O treino S+L tem 3.476.959 linhas e 8.764 positivas. Mesma grade, mesmas sementes e mesma regra de escolha: maior AP na validação, com o limiar no máximo F1.

| Candidato S+L, lote corrigido | AP val. | AP val. sem purga | Treino (s) | Tamanho (MB) | AP val. na rodada 1, lote antigo |
|---|---|---|---|---|---|
| Logística C = 0,1 / 1,0 | 0,031 / 0,031 | 0,064 / 0,067 | 26 / 24 | 0,004 | 0,031 / 0,032 |
| RF 100 árvores, folha 50 | 0,091 | 0,197 | 249 | 11,7 | 0,090 |
| RF 200 árvores, folha 10 | 0,096 | 0,208 | 701 | 38,8 | 0,095 |
| HGB 31 / 63 folhas | 0,057 / 0,054 | 0,115 / 0,111 | 62 / 64 | 0,5 / 0,9 | 0,057 / 0,054 |
| XGBoost profundidade **6** / 8 | **0,115*** / 0,103 | 0,228 / 0,210 | 329 / 132 | 0,4 / 0,3 | 0,111 / 0,108 |

\* Escolhido. É otimista, porque a parada antecipada do XGBoost também usou esta validação. O modelo atual S tem AP de 0,089 na mesma validação.

As escolhas foram congeladas em `artefatos_ml/hi_large/escolhas_emenda2.json` às 11:03:28 UTC, com SHA-256 `c9f7159d…6de777a59`. O limiar do escolhido é 0,1269.

### 6.2 Teste final novo (13 a 16/08/2022, purgado): avaliação única

**Executado uma vez,** às 11:03:39 UTC, depois do congelamento (`d_teste_final2.json`; `consultas.json`: `teste_final2` = 1). Os atributos são `atributos_S_final2` e `atributos_L_final2`, conferidos na seção 3.3.

- **Período:** 5.519.536 transações e 5.696 positivas. A purga retirou 1.715 positivos de tentativas iniciadas antes de 13/08.
- **Avaliado:** 5.517.821 transações e 3.981 positivas, com prevalência de 0,072%. Uma ordenação ao acaso teria AP de cerca de 0,0007.
- **Composição dos positivos avaliados:** 985 (25%) de tentativas novas e 2.996 (75%) **sem padrão**.

| Modelo (limiar escolhido antes) | Limiar | AP | Alertas | VP | FP | FN | VN | Precisão | Recall | F1 | Falsos alertas por 10 mil |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **S** atual, limiar do artefato | 0,0910 | **0,0978** | 2.793 | 534 | 2.259 | 3.447 | 5.511.581 | 0,191 | 0,134 | 0,158 | 4,1 |
| S atual, limiar da validação HI-Large | 0,0862 | 0,0978 | 3.359 | 566 | 2.793 | 3.415 | 5.511.047 | 0,169 | 0,142 | 0,154 | 5,1 |
| **L** escolhido: XGBoost profundidade 8 | 0,0956 | 0,0951 | 3.480 | 540 | 2.940 | 3.441 | 5.510.900 | 0,155 | 0,136 | 0,145 | 5,3 |
| **S+L corrigida** escolhida: XGBoost profundidade 6 | 0,1269 | **0,1152** | 2.072 | 520 | 1.552 | 3.461 | 5.512.288 | 0,251 | 0,131 | 0,172 | 2,8 |
| S+L antiga: XGBoost profundidade 6 (descritivo) | 0,1421 | 0,1115 | 1.398 | 434 | 964 | 3.547 | 5.512.876 | 0,310 | 0,109 | 0,161 | 1,7 |
| Taxa do formato | 0,0028 | 0,0037 | 701.553 | 3.083 | 698.470 | 898 | 4.815.370 | 0,004 | 0,774 | 0,009 | 1.265,8 |

As regras F2 e F3 não entram neste teste, porque a Emenda 2 não as listou. Na rodada 1, as duas ficaram muito abaixo dos modelos (seção 5.2).

**AP por dia:**

| Modelo | 13/08 (sáb.) | 14/08 (dom.) | 15/08 | 16/08 | Dias acima do atual |
|---|---|---|---|---|---|
| S atual | 0,0798 | 0,1170 | 0,1047 | 0,0966 | — |
| L, XGBoost | 0,0897 | 0,1200 | 0,0903 | 0,0883 | 2 de 4 |
| S+L corrigida, XGBoost | 0,1049 | 0,1364 | 0,1150 | 0,1095 | **4 de 4** |
| S+L antiga, XGBoost (descritivo) | 0,0985 | 0,1352 | 0,1112 | 0,1071 | 4 de 4 |
| Taxa do formato | 0,0053 | 0,0057 | 0,0027 | 0,0030 | 0 de 4 |

**Bootstrap pareado** da diferença de AP, agrupado por conta de origem, com 1.000 reamostras:

| Diferença | AP | IC 95% | Fração > 0 |
|---|---|---|---|
| L − S | −0,0027 | [−0,0128; +0,0076] | 0,32 |
| **S+L corrigida − S** | **+0,0174** | **[+0,0081; +0,0278]** | 1,00 |
| S+L corrigida − L | +0,0201 | [+0,0129; +0,0273] | 1,00 |
| S+L antiga − S (descritivo) | +0,0137 | [+0,0054; +0,0232] | 1,00 |

**Recall por grupo de positivos,** no limiar escolhido:

| Grupo | S atual | L, XGBoost | S+L corrigida, XGBoost |
|---|---|---|---|
| Tentativa nova (985) | 0,480 | 0,440 | 0,467 |
| Sem padrão (2.996) | 0,020 | 0,036 | 0,020 |
| Tentativa iniciada antes, retirada pela purga (1.715) | 0,655 | 0,575 | 0,638 |

**Sem purga** (secundário), a AP é de 0,286 para S, 0,250 para L e 0,313 para a S+L corrigida.

Por coincidência, a AP do escolhido no teste (0,11518) fica perto da AP dele na validação (0,11524). São conjuntos diferentes: 3.981 positivos no teste e 1.786 na validação.

### 6.3 Florestas do mesmo tipo da atual: descritivo, depois da consulta

O escolhido da S+L é XGBoost, e o modelo atual é uma floresta aleatória. Para separar o efeito dos dados do efeito da família, avaliei no mesmo teste as florestas com os parâmetros do artefato (100 árvores, folha mínima 50, amostra de 50%). Elas foram treinadas **antes** do teste: L na rodada 1 e S+L na validação da Emenda 2. Os limiares são os da validação.

**Esta avaliação não estava na Emenda 2.** Foi decidida depois de ver o resultado da seção 6.2 e é só descritiva (`d_teste_final2_rf_descritivo.json`). No arquivo, o campo `escolhido_na_validacao` marca o modelo avaliado em cada fonte, mas essas florestas não foram as escolhidas.

O contador em `consultas.json` marca `teste_final2_rf_descritivo` = 2. A primeira tentativa parou com erro no cálculo do bootstrap, depois de pontuar e antes de gravar qualquer resultado. O erro foi corrigido, e a avaliação foi repetida com `--forcar`.

| Floresta de produção | Limiar | AP | AP por dia (13, 14, 15 e 16/08) | Alertas | VP | FP | Precisão | Recall | F1 |
|---|---|---|---|---|---|---|---|---|---|
| L | 0,0366 | 0,0801 | 0,0744 / 0,1032 / 0,0675 / 0,0969 | 2.957 | 495 | 2.462 | 0,167 | 0,124 | 0,143 |
| S+L corrigida | 0,0519 | 0,1081 | 0,0935 / 0,1273 / 0,1068 / 0,1100 | 1.932 | 532 | 1.400 | 0,275 | 0,134 | 0,180 |

| Diferença | AP | IC 95% |
|---|---|---|
| Floresta L − S | −0,0177 | [−0,0271; −0,0092] |
| Floresta S+L corrigida − S | +0,0103 | [+0,0049; +0,0175] |
| Floresta S+L corrigida − floresta L | +0,0280 | [+0,0204; +0,0368] |

**Leitura (descritiva):**

- Com a mesma família do modelo atual, juntar as duas bases também fica acima de S, em AP e nos 4 dias.
- Treinar só com o HI-Large fica abaixo de S.
- O ganho da S+L aparece nas duas famílias, então não depende só do XGBoost.
- A diferença entre XGBoost e floresta na S+L (0,1152 contra 0,1081) **não foi testada** por bootstrap.

### 6.4 HI-Small (09 e 10/09/2022): teste já consultado, só descritivo

Fonte: `f_hismall.json`, refeito com os atributos corrigidos.

| Modelo | AP | Precisão | Recall | F1 | VP | FP |
|---|---|---|---|---|---|---|
| S atual (cache do NodeWatch; com o lote corrigido, o mesmo resultado, seção 3.4) | 0,464 | 0,627 | 0,407 | 0,494 | 389 | 231 |
| L, XGBoost: generalização L→S | 0,339 | 0,425 | 0,357 | 0,388 | 341 | 462 |
| S+L corrigida, XGBoost | 0,483 | 0,642 | 0,425 | 0,511 | 406 | 226 |

Este teste já foi consultado, e a S+L inclui o treino do próprio HI-Small. Portanto, não mede generalização entre fontes nem decide nada.

### 6.5 Custo da rodada 2

**Medido** na mesma máquina, com 3,5 GB de RAM livre no início da validação. Versões e semente iguais às da seção 5.5.

| Etapa | Tempo | Memória de pico | Observação |
|---|---|---|---|
| Atributos dos dias 1 a 16, refeitos do dia 1 | 1.054 s (preparador S) e 739 s (L) | 5,0 GB | 30.788.216 transações; só os dias 12 a 16 são gravados |
| Atributos do HI-Small com o lote corrigido | Seção 3.4: 16,1 a 16,5 s para o teste | — | Amostra de treino e teste regenerados |
| Treino da grade S+L | 1.586 s no total: logística 24 a 26 s; RF 249 a 701 s; HGB 62 a 64 s; XGBoost 132 a 329 s | 9,5 GB | Uma execução cada |
| Pontuação em lote, teste final | XGBoost S+L 519 mil linhas/s; XGBoost L 509 mil; florestas 434 a 462 mil | — | 4 threads |
| Uma linha, mediana / p99 | XGBoost S+L 3,9 / 7,6 ms; S atual 4,3 / 5,2 ms | — | Na rodada 1, S mediu 9,6 / 13,4 ms. Sob pressão de memória, a latência varia mais que a diferença entre os modelos |

O XGBoost de profundidade 6 da S+L levou 329 s nesta rodada e 169 s na rodada 1. São execuções únicas, e a diferença não foi investigada.

## 7. Resultados da rodada 3 (Emenda 3: segundo teste final)

A [Emenda 3](EMENDA_3_SEGUNDO_TESTE_FINAL.md) (SHA-256 `d62af3cb…6c8d1a`) foi registrada às 18:51:58 UTC de 09/11/2026, antes de calcular qualquer atributo dos dias 17 a 23/08. Ela foi escrita **depois** de conhecido o teste final 2.

- **Nada foi retreinado.** Os limiares são os da validação.
- **Hipótese principal:** a S+L corrigida com XGBoost.
- **Hipótese secundária:** a S+L corrigida com floresta, do mesmo tipo da atual.
- **Descritivos:** L com XGBoost, L com floresta e a taxa do formato.
- **Critério:** AP maior que a do modelo atual nos 7 dias, com IC de 95% excluindo zero, e AP maior em pelo menos 5 dos 7 dias.

**Antes da consulta:**

- O código da etapa foi ensaiado no dia 13/08, já consultado, com contador e saída à parte. O ensaio reproduziu os valores conhecidos desse dia, e o resultado foi descartado.
- A conferência dos atributos passou (seção 3.3).
- A etapa conferiu o SHA-256 do artefato atual e de cada modelo congelado.

**Consulta única,** às 19:43 UTC (`d_teste_final3.json`; `consultas.json`: `teste_final3` = 1).

- **Período:** 17 a 23/08/2022, com 12.394.384 transações e 11.528 positivas. A purga retirou 3.855 positivos de tentativas iniciadas antes de 17/08.
- **Avaliado:** 12.390.529 transações e 7.673 positivas, com prevalência de 0,062%. Uma ordenação ao acaso teria AP de cerca de 0,0006.
- **Composição dos positivos avaliados:** 2.187 (28,5%) de tentativas novas e 5.486 (71,5%) **sem padrão**.

### 7.1 Resultado

| Modelo (limiar congelado) | Papel | Limiar | AP | Alertas | VP | FP | FN | VN | Precisão | Recall | F1 | Falsos alertas por 10 mil |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **S** atual, limiar do artefato | Comparação | 0,0910 | **0,1259** | 5.735 | 1.259 | 4.476 | 6.414 | 12.378.380 | 0,220 | 0,164 | 0,188 | 3,6 |
| S atual, limiar da validação HI-Large | — | 0,0862 | 0,1259 | 6.869 | 1.347 | 5.522 | 6.326 | 12.377.334 | 0,196 | 0,176 | 0,185 | 4,5 |
| **S+L corrigida, XGBoost** | **Principal** | 0,1269 | **0,1291** | 4.094 | 1.119 | 2.975 | 6.554 | 12.379.881 | 0,273 | 0,146 | 0,190 | 2,4 |
| S+L corrigida, floresta | Secundária | 0,0519 | 0,1371 | 3.414 | 1.148 | 2.266 | 6.525 | 12.380.590 | 0,336 | 0,150 | 0,207 | 1,8 |
| L, XGBoost | Descritivo | 0,0956 | 0,1071 | 6.802 | 1.173 | 5.629 | 6.500 | 12.377.227 | 0,172 | 0,153 | 0,162 | 4,5 |
| L, floresta | Descritivo | 0,0366 | 0,1053 | 4.469 | 1.050 | 3.419 | 6.623 | 12.379.437 | 0,235 | 0,137 | 0,173 | 2,8 |
| Taxa do formato | Referência | 0,0028 | 0,0031 | 1.570.166 | 5.849 | 1.564.317 | 1.824 | 10.818.539 | 0,004 | 0,762 | 0,007 | 1.262,5 |

**Critério da Emenda 3** (`criterio_emenda3` no JSON). O bootstrap pareado foi agrupado por conta de origem, com 1.000 reamostras:

| Modelo | Diferença de AP para o atual | IC 95% | Fração > 0 | Dias com AP maior | Critério |
|---|---|---|---|---|---|
| **S+L corrigida, XGBoost (principal)** | **+0,0032** | **[−0,0043; +0,0105]** | 0,80 | **3 de 7** | **Não atendido** |
| S+L corrigida, floresta (secundária) | +0,0112 | [+0,0064; +0,0172] | 1,00 | 6 de 7 | Atendido; resultado **exploratório** |
| L, XGBoost (descritivo) | −0,0188 | [−0,0279; −0,0104] | 0,00 | 1 de 7 | — |
| L, floresta (descritivo) | −0,0207 | [−0,0298; −0,0133] | 0,00 | 0 de 7 | — |

**AP por dia:**

| Modelo | 17/08 (qua.) | 18/08 | 19/08 | 20/08 (sáb.) | 21/08 (dom.) | 22/08 | 23/08 |
|---|---|---|---|---|---|---|---|
| S atual | 0,0703 | 0,0882 | 0,0884 | 0,1588 | 0,1678 | 0,1550 | 0,1729 |
| S+L corrigida, XGBoost | **0,0829** | 0,0837 | 0,0758 | **0,1662** | **0,1938** | 0,1529 | 0,1718 |
| S+L corrigida, floresta | **0,0717** | 0,0842 | **0,1010** | **0,1728** | **0,1896** | **0,1640** | **0,1897** |
| L, XGBoost | **0,0732** | 0,0766 | 0,0513 | 0,1549 | 0,1557 | 0,1300 | 0,1538 |
| L, floresta | 0,0618 | 0,0688 | 0,0613 | 0,1454 | 0,1488 | 0,1284 | 0,1530 |

Em negrito, os dias acima do modelo atual.

**Recall por grupo de positivos,** no limiar congelado:

| Grupo | S atual | S+L, XGBoost | S+L, floresta | L, XGBoost | L, floresta |
|---|---|---|---|---|---|
| Tentativa nova (2.187) | 0,513 | 0,475 | 0,498 | 0,451 | 0,431 |
| Sem padrão (5.486) | 0,025 | 0,015 | 0,011 | 0,034 | 0,020 |
| Iniciada antes, retirada pela purga (3.855) | 0,698 | 0,651 | 0,687 | 0,585 | 0,525 |

**Sem purga** (secundário), a AP é de 0,346 para S, 0,354 para a S+L com XGBoost, 0,376 para a S+L com floresta e 0,284 e 0,283 para L.

**Leitura:**

- **A hipótese principal não se confirmou.** A vantagem do XGBoost S+L caiu de +0,0174 (13 a 16/08) para +0,0032, com intervalo que inclui zero, e ele ficou acima do atual em só 3 dos 7 dias.
- **A floresta S+L atendeu o critério,** como hipótese secundária. Pela regra registrada, isso **não muda** a conclusão principal.
- **L fica abaixo do atual,** nas duas famílias, com intervalo excluindo zero.
- **Todos os modelos detectam mal os positivos sem padrão,** entre 1,1% e 3,4%. Esses positivos são 71,5% dos avaliados.
- **A AP do próprio modelo atual varia muito entre os dias,** de 0,070 a 0,173. Diferenças de 0,01 entre modelos são pequenas diante dessa variação.

### 7.2 Custo da rodada 3

| Etapa | Tempo | Memória de pico | Observação |
|---|---|---|---|
| Atributos dos dias 1 a 23, refeitos do dia 1 | 1.224 s (preparador S) e 1.114 s (L) | 5,2 GB | 43.182.600 transações; grava de 16/08 em diante |
| Conferência `b6` | cerca de 30 s por preparador | — | — |
| Consulta única | 3.805 s no total; bootstrap 1.753 s; pontuação de 23 a 73 s por modelo | 8,5 GB | 12,4 M linhas; 2,9 GB de RAM livre no início |

A pontuação em lote foi mais lenta que no teste final 2: 189 mil linhas/s no XGBoost S+L, contra 519 mil antes. O processo tinha 8,5 GB, e a máquina tinha pouca memória livre. Isso não foi investigado.

## 8. Decisão

### 8.1 Os três critérios

| Rodada e período | Critério, registrado antes | L (só HI-Large) | S+L com XGBoost | S+L com floresta |
|---|---|---|---|---|
| 1, plano: teste (09 e 10/08) e reserva (11 e 12/08) | AP maior no teste, nos dois dias, e vantagem repetida na reserva | Teste +0,009 (IC inclui 0); reserva −0,015 (IC exclui 0). **Não atendido** | Lote antigo. Teste +0,019 (IC exclui 0); reserva −0,001. **Não atendido** | Lote antigo, só descritivo no teste: 0,077 contra 0,070 |
| 2, Emenda 2: teste final 2 (13 a 16/08) | AP maior, IC excluindo 0 e 3 de 4 dias | −0,0027; 2 de 4. **Não atendido** | +0,0174 [+0,0081; +0,0278]; 4 de 4. **Atendido** | Descritivo, depois da consulta: +0,0103 [+0,0049; +0,0175]; 4 de 4 |
| 3, Emenda 3: teste final 3 (17 a 23/08) | AP maior, IC excluindo 0 e 5 de 7 dias | XGBoost −0,0188, floresta −0,0207 (descritivos) | **Principal:** +0,0032 [−0,0043; +0,0105]; 3 de 7. **Não atendido** | **Secundária:** +0,0112 [+0,0064; +0,0172]; 6 de 7. Atendido, mas **exploratório** |

### 8.2 Conclusão

**Não há melhora confirmada do módulo financeiro com o HI-Large.**

- **Treinar só com o HI-Large piora** em relação ao modelo atual. Na rodada 3, as duas famílias ficam abaixo, com intervalo excluindo zero. Em nenhuma rodada L atendeu o critério.
- **A S+L com XGBoost,** que atendeu a Emenda 2, **não se confirmou** no segundo período. Pela regra registrada antes, ela não é recomendada.
- **A S+L com floresta** é o único resultado que se repetiu, acima do atual nos testes finais 2 e 3. É um resultado **exploratório**: no teste final 2, ela foi avaliada depois da consulta, e na Emenda 3 era hipótese secundária. Pela regra registrada, isso não muda a conclusão.
- **O artefato fica como está.** O modelo do sistema (`lavagem-20261102T083253Z`, `artefatos_ml/modelo_unificado.joblib`, SHA-256 `28a13a18…dcbdb4aa`) não foi alterado nem retreinado. O hash foi conferido antes da consulta da rodada 3.

### 8.3 Sobre a floresta S+L (resultado exploratório)

O resultado dela é **uma pista, não uma confirmação**:

- **O ganho é pequeno e com outro ponto de operação.** A AP sobe de 0,126 para 0,137 na rodada 3, cerca de 9%. No limiar da validação, ela dá 40% menos alertas (3.414 contra 5.735), mais precisão (0,336 contra 0,220) e um pouco menos de recall (0,150 contra 0,164).
- **Ela detecta ainda menos positivos sem padrão** que o modelo atual: 1,1% contra 2,5%.
- **Nenhuma dessas avaliações saiu de uma hipótese principal registrada.** Três rodadas e duas emendas escritas depois de ver resultados já aumentam a chance de um acerto por acaso. Seguir procurando períodos até algo passar agravaria isso.
- **Se o grupo quiser mesmo assim considerá-la,** o passo honesto é **uma única** confirmação, registrada antes, com a floresta S+L como hipótese principal, num período mais distante: por exemplo, uma semana de setembro ou outubro. O resultado precisa ser aceito qualquer que seja.
- **Ela não exige dependência nova,** porque é da mesma família do modelo atual. Treinar com o HI-Large ainda exigiria, no `treinar`, o leitor em fluxo e o cálculo incremental.

### 8.4 Comparação de famílias (descritiva)

- **Na validação,** o XGBoost foi o melhor nas duas fontes, nas duas rodadas.
- **Nos testes finais,** a ordem não se manteve. Na S+L, o XGBoost ficou acima da floresta no teste final 2 (0,1152 contra 0,1081) e abaixo no teste final 3 (0,1291 contra 0,1371). Nenhuma dessas diferenças foi testada.
- **A vantagem do XGBoost na validação** pode refletir a parada antecipada, que usou a própria validação.

## 9. O que foi integrado

| Item | Situação | Motivo |
|---|---|---|
| Treinar o NodeWatch só com o HI-Large | **Não integrado** | Fica abaixo do modelo atual (seção 7.1) e não atendeu nenhum critério |
| Combinar HI-Small e HI-Large no treino | **Não integrado** | A hipótese principal (XGBoost) não se confirmou. A floresta é só uma pista (seção 8.3) |
| Correção das somas por conta no lote (`src/ml/preparacao.py`) | **Integrada** | Defeito confirmado por força bruta; sem efeito nos alertas do modelo atual; cerca de 4% mais tempo (seção 3.4) |
| Novo leitor para arquivos grandes em `src/ml` | **Não integrado** | Só serviria para treinar com o HI-Large, o que não foi sustentado. Para avaliar, os scripts bastam e reaproveitam o `EstadoFinanceiro` e o `PreparadorFinanceiro` do módulo, sem lógica própria de atributos |
| XGBoost como dependência | **Não adicionado** | Fica fora do `.venv`, só para avaliação |
| Ferramentas de avaliação (`scripts/hi_large/`) | **Adicionadas** | Perfil em fluxo, partição por dia, conferências, atributos incrementais, treino, avaliação purgada e bootstrap. Aceitam outros arquivos IBM AML com `--prefixo`; a janela de modelagem está fixada a partir de 01/08/2022 |
| Testes (`testes/ml/test_hi_large_avaliacao.py`) | **Adicionados**: 14, todos aprovados | Ver abaixo |
| Documentação | **Adicionada** | Plano, três emendas, este relatório, o registro de experimentos (`REGISTRO_EXPERIMENTOS_E_TREINOS.md`), README, `PARTICOES.md` e link em `docs/ml/README.md` |

**Os testes verificam:**

- a partição de um CSV fora de ordem;
- os zeros à esquerda no banco;
- a equivalência entre partição com estado e o lote, em dados embaralhados;
- a associação entre padrões, contas e transações;
- a amostra fixa do treino;
- a regra de purga;
- a AP ponderada e o bootstrap;
- a recusa de reconsultar o teste;
- a soma exata do estado incremental com valores enormes;
- a soma exata do **lote** com valores enormes. Antes da correção, era uma falha esperada (`xfail` estrito); agora é teste de regressão;
- as bordas da soma por conta: janela vazia, janela começando no meio do bloco da conta e conta no fim do vetor;
- na rodada 3:
  - os períodos de avaliação não se sobrepõem entre si nem ao treino;
  - o carregamento por dia mantém a ordem e separa os metadados;
  - a conferência de reprodução aceita valores ausentes iguais e acusa uma diferença mínima.

Os testes usam dados sintéticos pequenos, criados no próprio teste. Não leem o HI-Large nem os resultados desta pasta.

**Alterações no código e na documentação existentes:**

- `src/ml/preparacao.py`: a correção do lote. A versão anterior continua no git, porque o arquivo não tinha alterações locais.
- Atualizados para dizer que o defeito foi corrigido:
  - `docs/ml/notas_relatorio.md` e `docs/ml/RELATORIO_ML.md` (o parágrafo "Divergência pendente");
  - `docs/ml/EVENTOS.md`;
  - `docs/ml/BENCHMARK_EVENTOS.md` (nota sobre a medição de 06/11);
  - `docs/COMO_FUNCIONA_O_NODEWATCH.md` (seções 8.5 e 15.7) e o PDF dele, regerado.
- Link e conclusão desta avaliação em `docs/ml/README.md`.

**Nas rodadas 2 e 3,** dentro de `scripts/hi_large/`:

- `b_atributos.py` ganhou `--dias`, `--gravar-a-partir` e `--sufixo`, e os dias da Emenda 3.
- `c_treinar_avaliar.py` ganhou `--emenda2` e as etapas `final2`, `final2_rf` e `final3`.
  - O erro que interrompeu a primeira tentativa de `final2_rf` foi corrigido.
  - O carregamento passou a ser dia a dia, com os mesmos dados e a mesma ordem.
  - Na rodada 3, o modelo atual é pontuado antes de carregar os atributos de L, e a ordem das linhas das duas pastas é conferida.
- `b6_conferir_final2.py` passou a aceitar `--sufixo`, `--anterior`, `--dia-repro` e `--dias`. Rodado sem opções, regrava `b6_conferencia_final2.json` com o mesmo conteúdo, nos campos novos `dia_reproduzido` e `dias_novos`.
- Novos: `a6_reconferencia.py`, `b4_correcao_lote.py`, `b5_amostra_estratificada.py` e `b6_conferir_final2.py`.
- No fechamento: `e_auditoria.py`, só de leitura (seção 12).

**Cópias e versões anteriores:**

- **Documentos e scripts:** `artefatos_ml/hi_large/copias_antes_de_editar/`. Inclui as versões deste relatório anteriores aos resultados das Emendas 2 e 3 e as dos scripts anteriores à Emenda 3.
- **Resultados da rodada 1 que foram refeitos:** `b2_hismall_lote_antigo.json`, `f_hismall_lote_antigo.json` e `b3_equivalencia_antes_da_correcao.json`. `c_validacao_historico.json` é uma cópia de segurança de `c_validacao.json`, que não foi sobrescrito.
- **Atributos do HI-Small calculados pelo lote antigo:** `artefatos_ml/hi_large/*_lote_antigo.parquet`.
- **Modelos da S+L antiga:** `artefatos_ml/hi_large/modelos/`, sem o prefixo `corrigido__`.
- **Registro da Emenda 3:** `artefatos_ml/hi_large/emenda3_registro.sha256`, com hash e horário.

O artefato do modelo não foi alterado.

## 10. Limitações e próximos passos

**Limitações:**

1. **Dados sintéticos.** O HI-Large e o HI-Small vêm do mesmo simulador. Nada aqui mede desempenho em transações reais, e o rótulo é lavagem simulada, não fraude.
2. **Janela de modelagem curta.** Os modelos usaram 23 dos 97 dias do período principal. O treino ocupa os dias 1 a 6, e a avaliação vai até 23/08. Os resultados valem para o início da simulação e não testam deriva ao longo de meses.
3. **Positivos sem padrão.** São entre 71,5% e 82% dos positivos avaliados. Nenhum modelo os detecta bem: o recall fica entre 1% e 4%. A purga não os alcança, e, se forem continuação de esquemas não listados, ainda há sobreposição possível.
4. **Protocolo emendado depois de ver resultados.** As Emendas 2 e 3 foram escritas depois de conhecidos os resultados anteriores. Cada consulta foi única e com escolhas congeladas, mas o conjunto de decisões sobre o que testar não é independente dos resultados.
5. **Parada antecipada do XGBoost.** Ela usa a validação, e os números de validação ficam otimistas. Os testes não têm esse viés.
6. **Uma execução por candidato,** com uma semente. Não há medida da variação do treino nem repetição de tempos.
7. **Máquina sob pressão de memória.** Os tempos e as latências variam entre execuções.
8. **Diferenças misturadas.** A S+L difere do modelo atual em mais dados e em atributos do HI-Small corrigidos, e, no XGBoost, também na família. Um retreino só com o HI-Small e o lote corrigido não foi feito.
9. **Avaliação descritiva depois da consulta.** A das florestas, no teste final 2, foi decidida depois de ver o resultado. Ela consultou o período duas vezes, porque a primeira tentativa falhou antes de gravar (seção 6.3).

**Próximos passos:**

1. **Manter o modelo atual.** Nenhuma troca está sustentada.
2. **Se o grupo quiser considerar a floresta S+L,** fazer uma única confirmação, registrada antes, com ela como hipótese principal e um período mais distante (seção 8.3). Se não passar, encerrar o uso do HI-Large para treino.
3. **Repetir o treino com 3 a 5 sementes** antes de qualquer troca, para medir a variação do treino.
4. **Para qualquer uso fora da simulação,** obter dados reais rotulados com data de confirmação.

## 11. Respostas objetivas

1. **A diferença entre 116 e 97 partições foi explicada?** Sim.
   - 116 era a contagem **durante** a leitura do CSV fora de ordem.
   - O total final é 165: 97 dias do período principal e 68 da cauda do gerador.
   - As 179.702.229 linhas aparecem cada uma uma única vez, no dia certo. Não há linha repetida, ausente nem fora do dia. As contagens e os positivos batem com o perfil, e `a6` confirma sem usar a primeira passada (seção 3.1 e [`PARTICOES.md`](PARTICOES.md)).
2. **Os três arquivos se associam corretamente e são compatíveis?**
   - **Associação:** sim. Todas as contas das transações existem no cadastro, pela chave `banco-conta` com banco numérico. O cadastro tem um nome de banco por número, e todas as linhas de padrão casam com positivos.
   - **Compatibilidade:** sim **em formato e rótulo nominal**, com as mesmas colunas, moedas, formatos e alvo. **Não em população nem em escala de tempo:** só 19 contas em comum com o HI-Small, tentativas nove vezes mais longas e prevalência diferente.
   - **Adaptação mínima:** ler em fluxo, por dia, e usar o estado incremental, porque o leitor atual carrega tudo na memória.
   - **O rótulo** é a verdade do simulador sobre lavagem, não fraude confirmada (seção 1.1).
3. **Como foi evitado o vazamento?**
   - **Eventos futuros:** atributos só com minutos anteriores, pelo `EstadoFinanceiro`, conferido contra o lote e a força bruta em dados reais.
   - **Ajustes:** preparador e quantis só do treino.
   - **Padrões, contas e rótulos:** nunca viram atributo.
   - **Tentativas:** pela Emenda 1, registrada antes de qualquer treino, a continuação de tentativas iniciadas antes sai da validação, do teste, da reserva e dos testes finais. Sem isso, a AP quase triplicaria.
   - **Limite:** positivos sem padrão não podem ser agrupados.
4. **Quais modelos foram comparados, em quais dados e com quais métricas?**
   - **Modelos:**
     - o modelo atual congelado, uma floresta treinada no HI-Small;
     - a grade de logística, floresta, HGB e XGBoost, treinada no HI-Large (L) e no HI-Small mais o HI-Large (S+L). A S+L foi treinada duas vezes: com o lote antigo, na rodada 1, e com o corrigido, na rodada 2;
     - as referências: prevalência, taxa do formato e regras F2 e F3. As regras entram só na rodada 1.
   - **Dados:** as mesmas divisões do HI-Large, todas purgadas: validação (07 e 08/08), teste (09 e 10/08), reserva (11 e 12/08), teste final 2 (13 a 16/08) e teste final 3 (17 a 23/08). À parte, o teste do HI-Small, só descritivo.
   - **Métricas:**
     - prevalência, AP total e por dia, precisão, recall e F1 no limiar escolhido na validação;
     - matriz de confusão, alertas e falsos alertas por 10 mil;
     - recall@k e recall por padrão e por tentativa;
     - bootstrap pareado, agrupado por conta de origem;
     - tempos de preparação, treino e pontuação.
5. **Há evidência de melhora no teste final? Ele permaneceu independente?**
   - **Rodada 1:** não. Os escolhidos superaram o modelo atual no teste, mas não na reserva.
   - **Rodada 2:** a S+L corrigida com XGBoost atendeu o critério da Emenda 2 (+0,0174). L não atendeu.
   - **Rodada 3:** a mesma S+L **não** se confirmou (+0,0032, IC inclui zero, 3 de 7 dias). A floresta S+L, hipótese secundária, atendeu o critério (+0,0112, 6 de 7 dias), mas isso não muda a conclusão.
   - **Conclusão:** **não há melhora confirmada.**
   - **Independência:** cada teste final usou dias nunca vistos, com a emenda registrada antes de calcular os atributos, as escolhas congeladas com hash e uma única consulta. Nenhum teste final influenciou as escolhas avaliadas nele.
   - **Ressalvas:**
     - as Emendas 2 e 3 foram escritas depois de conhecidos os resultados anteriores;
     - a avaliação das florestas no teste final 2 foi decidida depois de ver o resultado;
     - a Emenda 1 foi feita depois do perfil dos dados, que incluía rótulos por dia e padrões.
6. **Qual foi o custo de processamento e o que foi integrado?**
   - **Custo:**
     - cerca de 12 minutos para ler e particionar;
     - 11 minutos por passada de atributos de 12 dias (38 mil transações/s, até 5,1 GB);
     - de 19 a 20 minutos para refazer 23 dias;
     - de 24 s a 12 min para treinar cada candidato;
     - cerca de 1 hora para a consulta de 7 dias, quase metade dela em bootstrap (seções 5.5, 6.5 e 7.2).
   - **Integração:** ferramentas de avaliação, testes, documentação e a correção das somas por conta no lote, que custa cerca de 4% mais tempo e não muda nenhum alerta do modelo atual. Nem o modelo nem os dados de treino foram trocados (seção 9).
7. **O que falta para uma conclusão confiável?**
   - Para a floresta S+L: uma única confirmação, registrada antes, com ela como hipótese principal e num período mais distante, aceitando o resultado qualquer que seja.
   - A repetição do treino com outras sementes.
   - Sobretudo, **dados reais rotulados com data de confirmação**, sem os quais nenhum resultado aqui se transfere para operação.

## 12. Auditoria de fechamento

A auditoria foi feita depois de todas as consultas e **não iniciou nenhuma consulta nova**:

- **Script:** `scripts/hi_large/e_auditoria.py`, com resultado em `resultados/e_auditoria.json`.
- **Leitura:** ele lê as partições, os rótulos e os resultados já gravados.
- **Não pontua nenhum modelo:** o contador de consultas foi comparado antes e depois, sem mudança.

A trilha de cada execução está em [`REGISTRO_EXPERIMENTOS_E_TREINOS.md`](REGISTRO_EXPERIMENTOS_E_TREINOS.md).

### 12.1 Sobreposição de contas, tentativas e padrões

**Contas ativas,** como origem ou destino de alguma transação:

| Divisão | Contas ativas | Em comum com o treino | Contas em transações positivas | Em comum com os positivos do treino |
|---|---|---|---|---|
| Treino (01 a 06/08) | 2.058.916 | — | 9.674 | — |
| Validação (07 e 08/08) | 939.666 | 934.995 (99,5%) | 3.647 | 413 (11,3%) |
| Teste final 2 (13 a 16/08) | 1.014.509 | 1.005.784 (99,1%) | 9.096 | 662 (7,3%) |
| Teste final 3 (17 a 23/08) | 1.555.831 | 1.541.958 (99,1%) | 17.453 | 930 (5,3%) |

**Entre os períodos avaliados:**

- Validação e teste final 2 têm 877.857 contas ativas em comum, e validação e teste final 3, 905.917.
- Os dois testes finais têm 950.049 contas ativas em comum e 1.350 contas em positivos.

**Positivos avaliados,** depois da purga, cuja conta de origem ou de destino já esteve numa transação positiva do **treino**:

| Período | Positivos avaliados | Com conta em positivo do treino | Tentativa nova | Sem padrão |
|---|---|---|---|---|
| Validação | 1.786 | 562 (31,5%) | 134 de 394 | 428 de 1.392 |
| Teste | 2.022 | 742 (36,7%) | 119 de 365 | 623 de 1.657 |
| Reserva | 2.093 | 783 (37,4%) | 137 de 438 | 646 de 1.655 |
| Teste final 2 | 3.981 | 1.231 (30,9%) | 320 de 985 | 911 de 2.996 |
| Teste final 3 | 7.673 | 2.443 (31,8%) | 593 de 2.187 | 1.850 de 5.486 |

**Tentativas com padrão** (`padroes_casados.parquet`):

| Medida | Validação | Teste | Reserva | Teste final 2 | Teste final 3 |
|---|---|---|---|---|---|
| Tentativas com positivos avaliados | 319 | 290 | 347 | 659 | 1.208 |
| Dessas, com evento em divisão anterior | **0** | **0** | **0** | **0** | **0** |
| Tentativas retiradas pela purga | 265 | 368 | 468 | 875 | 1.468 |
| Positivos retirados pela purga | 376 | 505 | 666 | 1.715 | 3.855 |

Sem a purga, as mesmas tentativas apareceriam em mais de uma divisão:

- 405 tentativas têm eventos no treino e no teste final 2, e 511 no treino e no teste final 3;
- 333 têm eventos na validação e no teste final 2, e 415 na validação e no teste final 3;
- 1.079 têm eventos nos dois testes finais.

Todas iniciaram antes do período avaliado e saíram dele. **Os 8 tipos de padrão** aparecem no treino e em cada período avaliado.

**Leitura:**

- **Contas em comum são histórico, não vazamento por si.** Quase todas as contas do HI-Large aparecem em todas as divisões. Os atributos usam só o passado de cada conta, conferidos contra a força bruta (seção 3.4), e o identificador da conta nunca é atributo. Um sistema real também teria esse histórico no momento da previsão.
- **Tentativas longas foram tratadas pela purga.** Nenhuma tentativa com padrão contribui com positivos para um período avaliado e tem eventos numa divisão anterior. A conferência acima dá zero nos cinco períodos.
- **Risco que continua aberto, conta repetida em positivos:**
  - Cerca de 31% a 37% dos positivos avaliados envolvem uma conta que já esteve num positivo do treino.
  - L e S+L foram treinados com esses rótulos e podem ter aprendido o perfil de comportamento dessas contas.
  - Não é vazamento temporal, porque os rótulos do treino são anteriores. Mas é otimista em relação à operação, onde o rótulo só chega depois da confirmação.
  - O modelo atual não tem essa vantagem: só 19 contas do HI-Large existem no HI-Small.
- **Risco que continua aberto, positivos sem padrão.** Eles não podem ser agrupados por tentativa. Se forem continuação de esquemas não listados, a sobreposição não é medida.
- **Lacuna.** Para saber se a vantagem de algum modelo vem dos positivos com conta repetida, seria preciso o score por linha. Os scores não foram gravados, e recalculá-los exigiria pontuar de novo períodos já consultados. Isso **não foi feito**.

### 12.2 Intervalos de confiança das diferenças de AP

**Método** (`c_treinar_avaliar.bootstrap_pareado`, SHA-256 do código da função em `e_auditoria.json`):

- **Pareado:** sim. Em cada reamostra, as duas pontuações recebem os mesmos pesos, e a diferença de AP é calculada sobre as mesmas linhas.
- **Agrupado por conta de origem:** cada conta de origem recebe um peso de Poisson com média 1, e todas as transações dela levam esse peso.
- **Parâmetros:** 1.000 reamostras, semente 42 e intervalo pelos percentis 2,5 e 97,5.
- **Conferência:** a AP ponderada com pesos 1 é conferida contra o scikit-learn em cada chamada (`assert`).

**Dependências que o método não cobre:**

| Fonte de dependência | O que os dados mostram | Efeito provável |
|---|---|---|
| Conta de destino | Não agrupada | Pode estreitar o intervalo |
| Tentativa, que envolve várias contas | 154 de 659 tentativas avaliadas no teste final 2 e 402 de 1.208 no teste final 3 têm positivos em mais de uma conta de origem | Partes da mesma tentativa entram como independentes: intervalo provavelmente **estreito demais** |
| Concentração por conta | No teste final 3, 5.318 contas de origem têm positivos avaliados. Uma só tem 622 deles, e as 10 maiores somam 19,9%. No teste final 2, são 2.933 contas, máximo de 289 e 18,3% nas 10 maiores | Coberta pelo agrupamento por conta de origem |
| Dia | Não reamostrado. A AP do modelo atual varia de 0,070 a 0,173 entre os dias do teste final 3 | O intervalo não reflete a variação entre dias |

**Limitações do teste de 7 dias:**

- Com só 7 dias, ou 4 no teste final 2, um bootstrap por dia teria poucos grupos para ser estável.
- A regra de "5 de 7 dias" é uma regra de consistência, não um teste estatístico.
- Não há correção para comparações múltiplas: duas hipóteses na Emenda 3 e três rodadas no total.
- O intervalo não inclui a variação de treinar de novo com outra semente, porque cada modelo foi treinado uma vez.
- **Lacuna:** um intervalo alternativo, agrupado por tentativa ou por dia, exigiria os scores por linha, que não foram gravados. Não foi calculado.

### 12.3 O critério da Emenda 3 foi aplicado como registrado?

**Sim**, conferido em `e_auditoria.json` → `criterio_emenda3`.

| Verificação | Resultado |
|---|---|
| SHA-256 da emenda: no arquivo agora, no registro (`emenda3_registro.sha256`) e no JSON da consulta | Os três iguais, `d62af3cb…8d1a` |
| Ordem dos horários | Registro às 18:51:58 UTC. Primeiro arquivo de atributos do período às 19:10:42. Início da consulta às 19:43:30 |
| Número de consultas do período | `teste_final3` = 1 |
| Hashes dos 4 modelos congelados e do artefato atual | Iguais aos da tabela da emenda |
| Limiares usados | Os da emenda: 0,1269; 0,0519; 0,0956; 0,0366; e 0,0910 para o atual |
| Critério recalculado a partir da AP por dia e do bootstrap gravados | O mesmo veredito do script. Principal: 3 de 7 dias, IC inclui zero, **não atendido**. Secundária: 6 de 7 dias, IC exclui zero, atendido |

**Ressalvas:**

- **O código que calcula o critério** foi escrito depois do registro da emenda e antes da consulta. Foi ensaiado num dia já consultado, com contador à parte. O ensaio está descrito no registro (X34).
- **A floresta S+L era hipótese secundária.** Pela emenda, ela "não muda a conclusão principal". Neste relatório, ela foi reclassificada como **resultado exploratório** (seções 7.1, 8.1 a 8.3 e resumo).
- **A Emenda 3 foi escrita depois de conhecido o teste final 2,** assim como a Emenda 2 depois da rodada 1.

### 12.4 Consistência dos números e modelo de produção

**Números.** `e_auditoria.py` procura no texto do relatório e do registro, no formato do documento, os valores dos dois testes finais lidos dos JSON:

- linhas e positivos avaliados;
- AP de cada modelo;
- diferenças e intervalos do bootstrap.

A última execução não encontrou nenhuma divergência (`consistencia.faltando` vazio). `docs/ml/README.md` não traz mais a frase antiga de melhora. Os números das rodadas 1 e 2, como validação, teste e reserva, foram conferidos manualmente contra os JSON quando escritos. A conferência automática **não** cobre todos eles.

**Modelo de produção:** `artefatos_ml/modelo_unificado.joblib`, com 38.645.843 bytes, SHA-256 `28a13a18…dcbdb4aa`, versão `lavagem-20261102T083253Z`.

- O arquivo é de 02/11/2026 às 08:32:54 UTC.
- O hash é o mesmo na transcrição (09/11, 08:25 UTC), na Emenda 3, na consulta do teste final 3 e na auditoria.
- Nenhum script da avaliação chama `ModeloUnificado.salvar`.
- **Lacuna:** não há hash registrado antes de 09/11. Para esse intervalo, a evidência é só a data do arquivo.

### 12.5 Reproduzir com o XGBoost temporário

O XGBoost **não é dependência do NodeWatch**:

- não está em `requirements*.txt` nem no `.venv`;
- foi instalado num diretório temporário da sessão, que pode já ter sido apagado.

Para reproduzir as etapas que o usam, instale a mesma versão num diretório à parte:

```bash
python -m pip install --target <pasta_xgboost> --no-deps xgboost==3.4.1
```

Depois, aponte a variável para ela antes de rodar `c_treinar_avaliar.py`. No Git Bash:

```bash
export NODEWATCH_XGBOOST=<pasta_xgboost>
```

| Item | Valor usado |
|---|---|
| Versão | `xgboost` 3.4.1, pacote (wheel) `py3-none-win_amd64` |
| Biblioteca nativa | `xgboost/lib/xgboost.dll`, 56.915.456 bytes; SHA-256 em base64 no `RECORD`: `3LFck91yaIfKnNa33C0Mu8oKIQwO9CeLuVTU2jxdFn4` |
| Dependências | NumPy 2.5.4 e SciPy 1.18.1, do próprio `.venv`, por causa do `--no-deps` |
| Configuração | `tree_method="hist"`, CPU, 4 threads e semente 42; o resto está na seção 2 do registro |

Sem a variável, o script tira o XGBoost da grade e registra isso no JSON. Os resultados ficariam diferentes, sem os escolhidos de L e da S+L.

### 12.6 Testes de software

Os testes verificam o código, **não** o desempenho preditivo. Foram rodados nesta revisão, em 10/11/2026 às 02:15–02:18 UTC, antes dos commits e depois da última alteração de código. Na versão anterior do fechamento, às 21:22 de 09/11, eram 207 e 14; entraram depois o script de reprodução e um teste da comparação de modelos. A revisão do código é a branch `ml/sessoes-analise-datasets`, sobre `9095451`, com 42 alterações locais sem commit. Os hashes dos arquivos estão em `e_auditoria.json` → `inventario.codigo`.

| Comando | Resultado | Evidência |
|---|---|---|
| `python -m pytest -q -p no:cacheprovider --junitxml=docs/ml/hi_large/resultados/pytest_fechamento.xml` | 208 aprovados, 0 falhas | `resultados/pytest_fechamento.xml` |
| `python -m pytest -q -p no:cacheprovider testes/ml/test_hi_large_avaliacao.py --junitxml=docs/ml/hi_large/resultados/pytest_fechamento_hi_large.xml` | 15 aprovados | `resultados/pytest_fechamento_hi_large.xml` |

### 12.7 Reprodução dos treinos X11 e X25

**O que foi feito.** Os dois treinos efetivos foram refeitos numa pasta isolada (`artefatos_ml/hi_large/reproducao_treinos/`), com `scripts/hi_large/g_reproduzir_treinos.py`:

- **X11:** rodada 1, fontes L e S+L com o HI-Small do lote antigo;
- **X25:** Emenda 2, S+L corrigida.

Foram usados os mesmos insumos gravados, o mesmo código de treino, a semente 42, 4 threads e as mesmas versões, inclusive o XGBoost 3.4.1 do diretório temporário. Nada foi escolhido ou ajustado, e os dias 13 a 23/08 não foram lidos.

**Proteção dos originais.** Os hashes de 60 arquivos foram conferidos antes e depois: modelos originais, escolhas, preparador, contador de consultas, artefato de produção e resultados. Nenhum mudou. Detalhes, insumos e lacunas estão no [registro, seção 12](REGISTRO_EXPERIMENTOS_E_TREINOS.md#12-reprodução-dos-treinos-x11-e-x25), e os números, em `resultados/g_reproducao_treinos.json`.

| Execução e fonte | Arquivos de modelo idênticos ao original (SHA-256) | Escolha na validação | Previsões na validação purgada (07 e 08/08), só para conferir a reprodução |
|---|---|---|---|
| X11, L | 8 de 8 | A mesma (XGBoost 8) | Iguais, salvo nas florestas (abaixo) |
| X11, S+L antiga | 8 de 8 | A mesma (XGBoost 6) | Iguais, salvo nas florestas |
| X25, S+L corrigida | 8 de 8 | A mesma (XGBoost 6) | Iguais, salvo nas florestas |

**Não determinismo encontrado:** só na **pontuação** das florestas com 4 threads, não no treino.

- O mesmo arquivo, pontuado duas vezes, dá scores que diferem em até 5,6·10⁻¹⁷.
- Na AP, o efeito é de até 3,7·10⁻⁸, e no limiar, só no 17º algarismo.
- Isso não muda nenhum número com 4 casas deste relatório.

**Lacunas:**

- O código da época de X11 não foi guardado. A transcrição mostra que o caminho de treino não mudou depois disso.
- A reprodução foi feita na mesma máquina e com o mesmo `.venv`, não num ambiente limpo.
- Os atributos de treino foram reaproveitados, não regenerados a partir do CSV.

## 13. O que as evidências comprovam e o que não comprovam

**Comprovam:**

- **Os dados estão íntegros.** Os três arquivos têm os mesmos SHA-256 do começo ao fim. As 179.702.229 linhas estão nas 165 partições, cada uma uma única vez, e as contas e os padrões se associam corretamente.
- **Os atributos usados nas avaliações estão certos dentro da tolerância:**
  - o incremental e o lote corrigido batem com a força bruta nas amostras conferidas;
  - os dois batem entre si em todas as 387.075 linhas de 02/08;
  - os dias de sobreposição entre passadas são idênticos.
- **A correção do lote eliminou o erro numérico** e não mudou nenhuma decisão do modelo atual no teste do HI-Small.
- **As consultas finais seguiram o protocolo:**
  - modelos congelados, com hash conferido;
  - emendas registradas antes de calcular os períodos;
  - uma consulta por período;
  - a repetição de uma avaliação descritiva (X30 e X31) está declarada.
- **No teste final 3, a S+L com XGBoost não se distinguiu do modelo atual** (+0,0032, IC −0,0043 a +0,0105).
- **Treinar só com o HI-Large ficou abaixo do modelo atual** nos dois testes finais, nas duas famílias, com intervalo excluindo zero no teste final 3.
- **O código passa nos 208 testes** desta revisão.
- **Os dois treinos efetivos são reproduzíveis no mesmo ambiente.** X11 e X25, refeitos numa pasta isolada com os mesmos insumos, o mesmo código e as mesmas versões, deram os 24 arquivos de modelo idênticos byte a byte, com as mesmas escolhas e os mesmos limiares (seção 12.7).

**Não comprovam:**

- **Melhora do módulo financeiro com o HI-Large.** Nenhum candidato atendeu um critério principal em dois períodos. A floresta S+L é só um resultado exploratório.
- **Que a correção numérica, a integridade das partições ou a aprovação dos testes melhorem o modelo.** Elas garantem que os números foram calculados corretamente, não que algum modelo ficou melhor.
- **Ausência de vazamento.** A purga elimina a sobreposição de tentativas com padrão. Ela não elimina a repetição de contas em positivos, de 31% a 37% dos avaliados, nem uma possível continuação de esquemas sem padrão.
- **Validade estatística plena dos intervalos.** Eles não consideram a dependência por tentativa, por conta de destino e por dia. Não há correção para comparações múltiplas nem variação do treino.
- **Desempenho em dados reais, em fraude ou em meses posteriores da simulação.** A avaliação usou só 23 dos 97 dias, de um simulador.
- **Reprodutibilidade em ambiente limpo:**
  - o código desta revisão não está no git, e o da época de X11 não foi guardado;
  - o XGBoost ficou em ambiente temporário;
  - a reprodução de X11 e X25 foi feita na mesma máquina e com o mesmo `.venv`;
  - os atributos de treino foram reaproveitados, não regenerados.
- **Que reproduzir o treino diga algo sobre a qualidade do modelo.** A reprodução confirma o processo, não o desempenho.

## 14. Conclusão

- **Modelo mantido:** `lavagem-20261102T083253Z` (`artefatos_ml/modelo_unificado.joblib`, SHA-256 `28a13a18…dcbdb4aa`). Ele não foi trocado nem retreinado e continua sendo o modelo do sistema.
- **Candidatos:**
  - **S+L com XGBoost:** hipótese principal da Emenda 3. Atendeu o critério no teste final 2 e **não se confirmou** no teste final 3. Não é recomendado.
  - **S+L com floresta do mesmo tipo da atual:** **exploratório**. Ficou acima do atual nos dois testes finais, mas nunca como hipótese principal registrada. Seria preciso uma única confirmação, registrada antes, com ela como principal. Esta avaliação não fez isso e não procurou outro período.
  - **L, só HI-Large:** abaixo do modelo atual. Não é recomendado.
- **Limitações abertas:**
  - repetição de contas em positivos entre treino e avaliação;
  - positivos sem padrão, que não podem ser agrupados e que os modelos quase não detectam (1% a 4%);
  - intervalos sem agrupamento por tentativa e por dia, sem correção para múltiplas comparações e sem variação do treino;
  - emendas escritas depois de conhecidos os resultados anteriores;
  - dados sintéticos, janela de 23 dias e código fora do git;
  - reprodução dos treinos feita só no mesmo ambiente.

**Três coisas diferentes, que este relatório não mistura:**

| Pergunta | Evidência | Resposta |
|---|---|---|
| **O processo de treino é reproduzível?** | Reprodução de X11 e X25 (seção 12.7) | **Sim, no mesmo ambiente.** Os 24 modelos saíram idênticos byte a byte. Em ambiente limpo, não foi testado |
| **Qual é a qualidade dos modelos?** | Consultas únicas: teste, reserva e testes finais 2 e 3 (seções 5 a 7) | AP entre 0,07 e 0,14, contra 0,0006 de uma ordenação ao acaso. Detecta cerca de metade das tentativas novas e cerca de 2% dos positivos sem padrão. Só em dados sintéticos |
| **Há confirmação independente de melhoria?** | Critérios registrados antes, em dois períodos (Emendas 2 e 3) | **Não.** A hipótese principal não se confirmou no segundo período, e a floresta S+L é exploratória |

A reprodução fortalece a confiança de que os números vêm dos modelos descritos. Ela não muda a resposta à terceira pergunta.
