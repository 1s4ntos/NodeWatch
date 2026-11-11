# Processamento de eventos no NodeWatch

O NodeWatch recebe eventos, gera previsões novas com o modelo salvo e mostra o resultado na seção **Machine Learning → Eventos** da interface antiga (`http://127.0.0.1:5000/legado#ml/eventos`). O painel do analista, em `http://127.0.0.1:5000/`, não tem essa área.

- **Nada é treinado nem reajustado.** O artefato `modelo_unificado.joblib` é carregado **uma vez por processo** e usado como está, inclusive o `PreparadorFinanceiro` (câmbio, formatos, moedas, colunas e quantis).
- **Nenhuma fonte é "ao vivo".** O replay reenvia arquivos existentes e é rotulado como *replay histórico*. A API recebe o que um produtor enviar. A simulação é rotulada como *simulação*.
- **Rede e lavagem continuam separadas.** A fusão `fusao_rede_transacao` segue **indisponível**. Quando há vínculo, o sinal de rede aparece ao lado do score financeiro, sem combiná-los.

- **Nada roda sem uma sessão da interface.** Iniciar o servidor, abrir a página ou consultar status não processa nem retoma nada. A sessão e seus prazos estão em [ANALISE_DATASETS.md](ANALISE_DATASETS.md#sessão-pausa-encerramento-e-retomada).

Para analisar um arquivo seu, use [ANALISE_DATASETS.md](ANALISE_DATASETS.md); esta página trata do fluxo de eventos. Números de desempenho e de equivalência: [BENCHMARK_EVENTOS.md](BENCHMARK_EVENTOS.md). Contrato para um aplicativo instrumentado: [CONTRATO_COLETA_EVENTOS.md](CONTRATO_COLETA_EVENTOS.md). Revisão de confiabilidade e cenários de falha: [REVISAO_CONFIABILIDADE_EVENTOS.md](REVISAO_CONFIABILIDADE_EVENTOS.md).

## 1. Como executar

```bash
python src/sentinel_ai.py
```
Abra `http://127.0.0.1:5000/legado#ml/eventos` (interface antiga). Não precisa de chave do Gemini.

Na tela:

0. **Processamento de eventos**: mostra quem é responsável (esta aba, outra aba, ninguém ou sessão expirada), a recuperação pendente e os eventos bloqueados. **Iniciar processamento**, **Recuperar e iniciar** e **Assumir nesta aba** são ações explícitas. Iniciar um replay também torna esta aba a responsável.
1. **Replay histórico — rede**: reenvia `artefatos_ml/exemplos/rede_teste_sem_rotulos.csv` (46.105 medições) em ordem cronológica.
2. **Replay histórico — financeiro**: reenvia `artefatos_ml/exemplos/hismall_2022-09-10_sem_rotulo.csv` (208.325 transações de 10/09/2022).
   - Marque *Montar o estado antes com o histórico* para carregar as 4,87 milhões de transações anteriores do HI-Small. O caminho vem de `[financeiro].transacoes` em `ml_config.local.toml` e a carga leva cerca de 1 min.
   - Sem essa carga, as contas começam sem passado e as primeiras 72 h saem com `historico_incompleto`.
3. Controles: velocidade, pausar (sempre na virada do minuto), retomar e parar. A barra mostra os eventos **processados** pelo trabalhador, não só os enviados.
4. **Status**, atualizado a cada 2, 5 ou 15 s ou só sob pedido:
   - modo ativo, última atualização e contagens;
   - fila pendente, recusas por motivo e falhas;
   - latência p50/p95/p99 e cobertura do estado financeiro.
5. **Arquivos gerados** (`artefatos_ml/previsoes/eventos_<modo>_<dominio>.csv`): abrem direto na Análise de rede ou na Análise financeira.
6. **Gerar previsões de rede a partir de um CSV** `rede_v1`, sem usar a CLI.
7. **Rede + transações**: situação da fusão e o laboratório de simulação.

Produtor de exemplo, que envia pela API HTTP. Inicie o processamento na tela, que mostra os comandos já com o identificador da sessão:

```bash
python scripts/produtor_eventos_exemplo.py --sessao <id-da-sessao> --tipo financeiro --limite 2000
```
```bash
python scripts/produtor_eventos_exemplo.py --sessao <id-da-sessao> --tipo rede --limite 500 --eventos-por-segundo 50
```

O produtor usa uma sessão da interface e não a abre nem a renova. Encerrada ou expirada a sessão, ele recebe a recusa, explica e para (código de saída 3). Retransmitir é seguro.

Testes e benchmark:

```bash
python -m pytest testes
```
```bash
python scripts/benchmark_eventos.py
```
Rode o benchmark com o servidor parado; ele grava `docs/ml/BENCHMARK_EVENTOS.md`.

## 2. Arquitetura

```
 produtores ──► ingestão ──► fila limitada ──► trabalhador (1 por processo) ──► saídas CSV + status ──► interface
 (API, replay,   eventos.py     servico_eventos     │                                   │
  laboratório)   valida e        .py                ├─ rede: tabela_previsoes_rede ──────┤
                 identifica                         │   (matriz_rede + cabeça salva)     │
                                                    ├─ vínculos: RegistroVinculos        │
                                                    ├─ financeiro: EstadoFinanceiro ─────┤
                                                    │   (incremental.py) + pontuar_lavagem
                                                    └─ fusão técnica: associar_sinais_rede (integracao.py)
                                    instantâneo ◄── estado financeiro, sinais, vínculos, cursores, tamanho das saídas
```

| camada | módulo | responsabilidade |
|---|---|---|
| ingestão | `src/ml/eventos.py` | Valida o envelope e os dados, define a identidade estável e normaliza tempo e contas. |
| registro durável | `src/ml/registro_eventos.py` | Grava cada evento aceito antes de aplicá-lo. Com o instantâneo, é a fonte da recuperação. |
| fila e trabalhador | `src/ml/servico_eventos.py` | Fila limitada, um trabalhador, regras de identidade, atraso e fechamento de minuto, aplicação em etapas e bloqueio. |
| sessões | `src/ml/sessoes.py` | Quem autoriza processamento novo. |
| preparação de atributos | `src/ml/incremental.py` | Estado por conta: os 49 atributos financeiros sem reconstruir o histórico. A rede chega preparada. |
| inferência | `src/ml/previsao.py` | `tabela_previsoes_rede` e `pontuar_lavagem`, as mesmas funções usadas pela CLI. |
| persistência | `EstadoFinanceiro.salvar` e `ServicoEventos.salvar_estado` | Instantâneo atômico em `artefatos_ml/estado_eventos/`; depois dele, o registro é podado. |
| apresentação | `src/api_eventos.py` + `interface/index.html` | API Flask e área **Eventos**. As saídas também abrem nas áreas de exploração. |
| replay | `src/ml/replay.py` | Lê um arquivo existente, em ordem, e produz eventos `replay_historico`. |
| simulação | `src/ml/simulacao.py` | Laboratório da integração rede ↔ transação, rotulado como SIMULAÇÃO. |

**Concorrência.** `CabecaClassificacao.probabilidades` trocava `n_jobs` do estimador compartilhado durante previsões de menos de 1.000 linhas. Com a API e o trabalhador prevendo ao mesmo tempo, uma thread podia restaurar o valor no meio da previsão da outra. Agora lotes pequenos usam uma **cópia rasa privada** com `n_jobs=1`:
- a cópia compartilha as árvores, que só são lidas;
- o original nunca é alterado;
- a cópia não é salva no artefato (`__getstate__`).

O teste `test_previsoes_simultaneas_nao_alteram_n_jobs_compartilhado` usa 6 threads.

## 3. Contrato de eventos (`evento_v1`)

```json
{
  "tipo": "transacao | medicao_rede | vinculo",
  "versao_esquema": "transacao_hismall_v1 | rede_v1 | vinculo_v1",
  "id_evento": "opcional",
  "origem": "quem produziu",
  "modo": "novo_evento | replay_historico | simulacao",
  "dados": { "...": "campos do esquema do tipo" }
}
```

| campo | quem define | regra |
|---|---|---|
| identidade (`chave_natural`) | servidor | `tx:<id_transacao>`, `rede:<id_fluxo>@<timestamp>` ou `vinc:<hash>` de chave, tipo, fluxo e validade. Mesma identidade e mesmo conteúdo é retransmissão; conteúdo diferente é conflito. `id_evento`, se vier, é só exibido. |
| `ocorrido_em` | dados | Instante da transação, da medição ou `declarado_em` do vínculo. |
| `recebido_em` | servidor | Relógio do servidor (UTC) na chegada. |
| `origem` | produtor | Texto livre de até 120 caracteres. O replay usa `replay:<arquivo>`. |
| `modo` | produtor | `novo_evento` é o padrão da API; o replay usa sempre `replay_historico`; o laboratório usa `simulacao`. |
| `versao_esquema` | produtor | Versão diferente da suportada é recusada. |

### `transacao_hismall_v1` (entrada da cabeça `lavagem`)

Obrigatórios:
- `id_transacao` e `timestamp`;
- `banco_origem`, `conta_origem`, `banco_destino`, `conta_destino`;
- `valor_pago`, `moeda_pagamento`, `valor_recebido`, `moeda_recebimento`;
- `formato`.

Opcionais: `timestamp_disponivel` (≥ `timestamp`) e `chave_tecnica`.

Regras de normalização:
- **Conta:** a conta é `banco-conta`, como na leitura do HI-Small. O mesmo número em bancos diferentes são contas diferentes.
- **Tempo:** aceita `AAAA/MM/DD HH:MM`, ISO 8601 ou época em segundos. Texto sem fuso é tratado como UTC. O modelo trabalha em minutos inteiros, então os segundos só contam para `timestamp_disponivel` (junção com a rede).

### `rede_v1` (entrada da cabeça `estado_rede`)

As medições chegam **com os 21 atributos já preparados**, além de `id_fluxo`, `anchor_id`, `probe_id` e `timestamp`. `classe_atual` é opcional e só é exigida pela variante comparativa. A validação completa do esquema roda em lote e isola as linhas ruins.

**A telemetria bruta é recusada** (por exemplo `rtt_ms`, `jitter_ms`). As razões `razao_rtt_p95/p99` e `razao_jitter_p95` dividem pela referência p95/p99 de cada fluxo, e o período dessa referência não está documentado. Inventar uma referência mudaria o significado dos atributos com que o modelo foi treinado.

### `vinculo_v1`

Campos: `chave`, `tipo_chave` (`id_transacao` | `chave_tecnica`), `id_fluxo`, `valido_de`, `valido_ate` (exclusivo) e `fonte_vinculo`; opcionalmente `declarado_em`.

Regras além do esquema:
- `id_fluxo` segue `<probe_id>_<anchor_id>`;
- `valido_de < valido_ate`;
- `fonte_vinculo` não pode ser vazia;
- **conta bancária não é chave técnica:** uma chave no formato `banco-conta` do HI-Small, ou já conhecida como conta pelo estado financeiro, é recusada. O vínculo liga transação, sessão, dispositivo ou nó a um fluxo; contas não são âncoras nem sondas.

**Política de versões.** Mudar o significado de um campo cria um esquema novo. Um extrator causal que calcule os atributos de rede a partir da telemetria bruta, por exemplo, será `rede_v2`, com referência p95/p99 documentada e janelas por tempo ou por linhas explícitas. O servidor só aceita as versões listadas em `GET /api/ml/eventos/contratos`.

## 4. Política de aceitação, durabilidade, recuperação, duplicatas e atraso

### Aceitação durável

`POST /api/ml/eventos` só responde que aceitou **depois de gravar e sincronizar (`fsync`) o evento no registro durável**. Um evento em `aceitos` não some se o processo cair antes do próximo instantâneo. Aceito não quer dizer previsto: o resultado sai depois e pode ser consultado em `GET /api/ml/eventos/consulta?id=tx:<id>` (`aceito_pendente`, `aplicado`, `bloqueado` ou `descartado`).

### Registro, instantâneo e projeções

- **Registro** (`artefatos_ml/estado_eventos/registro/wal_*.jsonl`): todo evento aceito e todo comando de fechamento ou descarte, com sequência, identidade, hash, origem, modo, versão do esquema e instantes.
- **Instantâneo** (`estado_eventos.pkl` + `.meta.json`): estado, índice de identidades, cursores e tamanho das saídas, cobrindo até `aplicado_ate`. É gravado ao pausar um replay, no fim dele, a cada 120 s ou 100 mil eventos com atividade, ao parar o servidor e em *Gravar estado agora*.
- **CSVs de saída** (`eventos_<modo>_*.csv`): são **projeções**. Instantâneo + registro as reconstroem. Os CSVs de `recusas` guardam os eventos aceitos que não geraram previsão, com o motivo.

### Etapas de cada lote

1. **Preparação**: o evento está no registro.
2. **Aplicação**: estado e previsões em memória.
3. **Confirmação**: CSVs escritos; só então avançam `aplicado_ate` e o cursor do replay.

Se a aplicação ou a escrita falhar, o serviço é reconstruído a partir do instantâneo e do registro até o evento anterior ao lote, as saídas voltam ao tamanho certo e o lote é repetido (3 tentativas). Não há cópia do estado a cada evento: o custo de uma falha é o de reconstruir desde o último instantâneo.

Se a falha persistir, os eventos do lote são aplicados um a um, para isolar o que falha, e o processamento fica **bloqueado** nele. Ele fica identificado na tela, com a causa, e nada depois dele avança até uma ação explícita:
- **Repetir**, depois de corrigir a causa;
- **Descartar evento**: grava um comando no registro e uma linha em `recusas`. O descarte sobrevive ao reinício.

Se a causa estiver no fechamento de um minuto anterior, descartar o evento que o disparou não resolve; é preciso corrigir e repetir.

### Reinício

Nada é retomado sozinho. O status só informa o instantâneo e quantos eventos aceitos esperam. **Recuperar e iniciar**, com sessão ativa, carrega o instantâneo, devolve as saídas ao tamanho dele e reaplica o registro. Reaplicar não duplica. Uma linha final incompleta no registro (queda durante a escrita) é ignorada: aquele evento não foi confirmado ao produtor, que deve reenviá-lo.

**Replay e API têm garantias diferentes.** A fonte de verdade do replay é o arquivo: seus eventos passam pelo registro sem fsync por evento, e o que se perder na queda é relido a partir do cursor. Na API, o registro é a única cópia, por isso há fsync antes da resposta. A garantia vale para queda do processo e, até onde o `fsync` do sistema e o disco cumprem o contrato, do sistema. Perda do próprio disco não é coberta.

### Duplicatas e conflitos

| caso | resposta |
|---|---|
| Mesma identidade e mesmo conteúdo | Vem em `ja_aceitos`: é retransmissão. Nada é gravado, aplicado ou previsto de novo. |
| Mesma identidade, conteúdo diferente | Recusado como `conflito`. |

O índice lembra até 1 milhão de identidades. Depois disso, uma transação retransmitida ainda é recusada por ser de minuto já fechado.

### Fechamento do minuto financeiro e atraso

Há dois tempos: o **tempo do evento** (quando a transação ocorreu) e o **relógio de processamento** (o do servidor). Ociosidade não fecha minutos.

| quem fecha | quando | vale para |
|---|---|---|
| Evento posterior | Chegou evento de minuto `m`: fecham os minutos `< m − atraso_permitido_min` (`NODEWATCH_ATRASO_MIN`, padrão 0) | todos os modos |
| Relógio | O relógio passou do fim do minuto + atraso permitido + carência (2 s) | só minutos com eventos `novo_evento` |
| Fim do replay financeiro | Último minuto do arquivo | replay |
| **Fechar minutos abertos** (comando) | Na hora; a tela avisa do efeito | todos; o que chegar depois desses minutos será `atrasada` |

Um replay de 2022 nunca é fechado pelo relógio de hoje. Todo fechamento fica no registro, para a reconstrução ser idêntica. Ao fechar, as transações do minuto são pontuadas contra o estado anterior e só então incorporadas: as do mesmo minuto não se enxergam.

Transação de minuto já fechado é recusada como `atrasada`, não entra no estado nem é pontuada (incorporá-la mudaria atributos já emitidos) e fica em `recusas`.

Um produtor que envie `novo_evento` com data antiga terá o minuto fechado pelo relógio assim que o serviço ficar ocioso. Dados antigos devem ir como `replay_historico`.

### Outras regras

| situação | o que acontece |
|---|---|
| **Fila cheia** (20.000) | A API recusa os excedentes com `fila_cheia` e HTTP 429, sem gravar. O replay espera vaga. |
| **Sessão responsável inativa** | O trabalhador para de consumir; replays pausam na virada do minuto. Os eventos aceitos esperam no registro. Outra sessão retoma com **Assumir** ou **Retomar nesta aba**. |
| **Carga inicial** | Bloqueia o trabalhador enquanto monta o estado e grava um instantâneo logo depois. O status continua respondendo, com `ocupado`. |
| **Várias linhas do tempo** | O estado tem uma linha do tempo só: misturar replay de 2022 e eventos novos faz o mais antigo chegar atrasado. Use *Descartar estado* entre cenários. Para arquivos seus, *Analisar dataset* tem estado isolado. |

## 5. Contratos de atributos

### Rede (`rede_v1`): produzidos na fonte

O NodeWatch **não recalcula** nenhum atributo de rede. Eles vêm prontos e são só validados (faixas, domínios e sentinelas `-1`). O dicionário completo está em [DICIONARIO_DADOS.md](DICIONARIO_DADOS.md).

| grupo | atributos | como é produzido | observação para um extrator causal |
|---|---|---|---|
| medição | `perda_pct`, `rtt_ausente`, `delta_ttl_clip`, `ttl_reset`, `perdas_consecutivas` | Pela sonda, a cada medição. | `perdas_consecutivas` precisa do histórico do fluxo. |
| razões | `razao_rtt_p95`, `razao_rtt_p99`, `razao_jitter_p95`, `amplitude_rtt_rel` | RTT e jitter da medição divididos pelo p95/p99 de **referência** do fluxo. | O período da referência não está documentado. Sem ele, não há extração causal. |
| janelas | `perda_media_w{3,6,12}`, `rtt_p95_max_w{3,6,12}`, `jitter_p95_max_w{3,6,12}`, `n_rtt_acima_p95_w{3,6,12}` | Últimas *k* **medições** do fluxo, incluindo a atual. | As janelas contam linhas, não tempo. O extrator precisa de estado por fluxo. |
| contexto | `classe_atual` (opcional) | Regra sobre perda e razões; reproduzida a 99,94%. | Só na variante comparativa. |

Inferência: `matriz_rede` seleciona os atributos na ordem do esquema e `CabecaClassificacao.probabilidades` aplica o pipeline salvo. A saída `previsao_rede_v1` traz:
- id do fluxo e instante da medição;
- horizonte `proxima_medicao`;
- classe prevista e as três probabilidades;
- `score_alerta_rede` = P(RISCO) + P(FALHA), o alerta e o limiar oficial (0,3173);
- a versão do modelo e `modelo_rede_treinado_ate`.

Os eventos acrescentam `id_evento`, `origem_evento`, `modo_evento`, `ocorrido_em_utc`, `recebido_em_utc` e `processado_em_utc`.

### Financeiro (`lavagem`): calculados pelo estado incremental

Janela `[t − w, t)` em minutos inteiros. O minuto da própria transação nunca entra.

| atributo | definição | estado usado |
|---|---|---|
| `log_valor_usd`, `sem_taxa_cambio` | `log1p(valor_pago × câmbio)`; câmbio do treino; sem taxa = NaN + indicador | nenhum |
| `moeda_diferente`, `mesmo_banco`, `auto_transferencia` | comparações na própria transação | nenhum |
| `n_env_origem_6h/24h/72h` | envios da origem na janela | contagem por conta; registro de 72 h com um cursor por janela |
| `soma_env_origem_usd_24h` | soma em USD dos envios em 24 h | soma compensada (Neumaier) por conta, descontada quando o evento sai da janela |
| `n_env_origem_total` | todos os envios anteriores da origem | contador por conta |
| `z_valor_origem` | `(x − média) / √(var + 0,01)` do log-valor; 0 se houver menos de 2 envios anteriores | soma e soma dos quadrados do log-valor deslocado pelo 1º envio da conta |
| `min_desde_env_origem`, `min_desde_rec_origem`, `min_desde_rec_destino` | minutos desde o último envio ou recebimento, com teto de 14.400; sem histórico = 14.400 + indicador `sem_historico_*` | último minuto por conta |
| `n_env_destino_24h` | envios da conta de destino em 24 h | contagem por conta |
| `n_rec_origem_24h`, `soma_rec_origem_usd_24h` | recebimentos da origem em 24 h | contagem e soma compensada |
| `razao_saida_entrada_24h` | `soma_env_24h / (soma_rec_24h + 1)` | as duas somas acima |
| `n_rec_destino_24h/72h` | recebimentos do destino na janela | contagem por conta |
| `par_novo`, `n_par_previas` | se o par origem→destino já ocorreu e quantas vezes | dicionário de pares → contagem |
| `dest_distintos_origem`, `orig_distintas_destino` | contrapartes distintas anteriores | contador por conta, incrementado quando um par é visto pela 1ª vez |
| `formato_*`, `moeda_*` | indicadores das categorias do treino | nenhum |

**Equivalência.** `testes/ml/test_incremental.py` compara o incremental com o lote (`atributos_financeiros`) nos 49 atributos e com a referência por força bruta. Cobre também:
- bordas de janela (*t − w* entra; *t − w − 1* não; o mesmo minuto não);
- diferentes tamanhos de lote;
- instantâneo no meio de um minuto aberto;
- duplicatas e atrasos;
- a ausência de reconstrução do histórico.

Os resultados no HI-Small real estão em [BENCHMARK_EVENTOS.md](BENCHMARK_EVENTOS.md).

**`razao_saida_entrada_24h`.** Até 09/11/2026, o lote somava em prefixos acumulados globais e perdia precisão por cancelamento (até 5,0% no teste do HI-Small e 27% no HI-Large, contra a força bruta). Agora as somas acumuladas do lote recomeçam em cada conta, e o lote coincide com o incremental, que soma por conta com compensação. Detalhes em `docs/ml/hi_large/RELATORIO_HI_LARGE.md`, seção 3.4.

**Carga inicial.** `EstadoFinanceiro.carregar_historico` monta o estado de forma vetorizada, equivalente a fechar em ordem todos os minutos do histórico. Só é permitida com o estado vazio. A cobertura registrada traz:
- início da observação;
- último minuto fechado;
- transações e contas;
- pares;
- eventos nas janelas.

Cada previsão traz `historico_incompleto` quando a conta tem menos de 72 h de observação no estado.

## 6. Fusão rede ↔ transação

O trabalho está em três níveis, e só os dois primeiros estão prontos:

| nível | situação | o que comprova |
|---|---|---|
| **Integração técnica** | pronta | Vínculos validados. O sinal de rede só é usado se estava disponível no instante da decisão: previsão com `timestamp ≤ timestamp_disponivel`, idade ≤ 480 s, modelo de rede treinado antes, vínculo vigente **e declarado** antes da decisão (`disponivel_em`). Reutiliza `associar_sinais_rede`. |
| **Cenário simulado** | laboratório pronto | `src/ml/simulacao.py`: medições reais de três fluxos, com transações e vínculos sintéticos. São 8 casos de cobertura com resultado esperado e 5 recusas (conta bancária como chave técnica, telemetria bruta, validade invertida, duplicata e atraso). Vai para `artefatos_ml/simulacao/`, longe das previsões reais. |
| **Validação preditiva** | **pendente** | Exige dados reais relacionados (seção 9). Sem eles, nenhuma comparação "financeiro × financeiro + rede" é feita. As datas do HI-Small não são alteradas e nenhum par é fabricado. |

Na saída de lavagem, o vínculo aparece em `cobertura_vinculo`, `n_fluxos_vinculados`, `score_alerta_rede_vinculado` e `idade_sinal_rede_s`. `sinais_utilizados` continua `financeiro`.

## 7. Endpoints

`[sessão]` exige o cabeçalho `X-NodeWatch-Sessao` com uma sessão ativa. Sem ele: HTTP 403, e nada é processado.

| método e rota | uso |
|---|---|
| `POST /api/ml/sessao` | Abre uma sessão; devolve o id e a política de prazos. |
| `POST /api/ml/sessao/pulso` | [sessão] Renova. Expirada ou encerrada: HTTP 410. |
| `POST /api/ml/sessao/encerrar` | [sessão] Encerra; o trabalho dela para no próximo ponto seguro. |
| `GET /api/ml/sessao` | Situação da sessão e política. |
| `GET /api/ml/eventos/status` | Sem efeitos. Responsável, recuperação, bloqueio, registro, fila, contadores, latências, cobertura, replays e saídas. |
| `GET /api/ml/eventos/contratos` | Envelope e esquemas aceitos. |
| `POST /api/ml/eventos/iniciar` | [sessão] Recupera, se preciso, e torna esta sessão a responsável. |
| `POST /api/ml/eventos/pausar` | [sessão] Para de consumir; os eventos aceitos ficam no registro. |
| `POST /api/ml/eventos` | [sessão responsável] Ingestão durável de `{"eventos": [...], "origem": "...", "modo": "..."}`, até 5.000 por pedido. 202; 429 se a fila encheu; 409 se o processamento não foi iniciado por esta sessão. |
| `GET /api/ml/eventos/consulta?id=tx:...` | Situação de um evento pela identidade. |
| `POST /api/ml/eventos/fechar` | [sessão] Fechamento forçado dos minutos abertos. |
| `GET /api/ml/eventos/recentes?dominio=rede\|lavagem\|rejeicoes&n=50` | Últimas previsões ou recusas. |
| `POST /api/ml/eventos/replay` | [sessão] `{"fonte": "rede\|financeiro", "acao": "iniciar\|pausar\|retomar\|parar", "eventos_por_segundo": 0, "usar_historico": false}`. |
| `POST /api/ml/eventos/salvar` | [sessão] Grava o instantâneo agora. |
| `POST /api/ml/eventos/bloqueio/repetir` | [sessão] Repete os eventos bloqueados. |
| `POST /api/ml/eventos/bloqueio/descartar` | [sessão] Descarta os que falharam (fica no registro). |
| `POST /api/ml/eventos/descartar` | [sessão] Para os replays e apaga estado, registro e arquivos `eventos_*`. |
| `GET` / `POST /api/ml/eventos/laboratorio` | Último relatório / [sessão] nova execução do laboratório de SIMULAÇÃO. |
| `POST /api/ml/prever/rede` | [sessão] Previsão síncrona de até 1.000 medições `rede_v1` em JSON. |
| `POST /api/ml/prever/rede/csv` | [sessão] CSV `rede_v1` (multipart, campo `arquivo`, até 64 MB) → `artefatos_ml/previsoes/<nome>_previsoes_rede.csv` + relatório. |
| `/api/ml/analises...` | Ver [ANALISE_DATASETS.md](ANALISE_DATASETS.md#api). |

Exemplo, com o processamento iniciado na tela:

```bash
curl -X POST http://127.0.0.1:5000/api/ml/eventos -H "Content-Type: application/json" -H "X-NodeWatch-Sessao: <id-da-sessao>" -d "{\"eventos\":[{\"tipo\":\"transacao\",\"dados\":{\"id_transacao\":\"t-1\",\"timestamp\":\"2026-11-03T12:00:00Z\",\"banco_origem\":12,\"conta_origem\":\"8010D4440\",\"banco_destino\":137218,\"conta_destino\":\"80EB2C3F0\",\"valor_pago\":1500.0,\"moeda_pagamento\":\"US Dollar\",\"valor_recebido\":1500.0,\"moeda_recebimento\":\"US Dollar\",\"formato\":\"ACH\"}}]}"
```

## 8. Versões

| item | valor |
|---|---|
| envelope | `evento_v1` |
| esquemas aceitos | `transacao_hismall_v1`, `rede_v1`, `vinculo_v1` |
| registro de eventos | `wal_<seq>.jsonl`, uma linha JSON por evento aceito ou comando |
| estado financeiro | `estado_financeiro_v1`, mais a assinatura do `PreparadorFinanceiro`: hash de câmbio, formatos, moedas e colunas |
| modelo (artefato atual) | `estado_rede-20261102T083053Z` (limiar 0,3173, treinado até 2026-10-03T17:59:49 UTC) e `lavagem-20261102T083253Z` (limiar 0,0910) |
| instantâneo | só é restaurado se as versões das duas cabeças e a assinatura do preparador forem as mesmas |

## 9. Limites e dados externos necessários

Limites conhecidos:
- Um trabalhador por processo e estado em memória. Com o HI-Small completo, o instantâneo tem centenas de MB; veja o benchmark.
- Minuto financeiro fechado não reabre. Corrigir uma transação atrasada exige refazer o estado a partir do histórico.
- A previsão financeira de eventos novos espera o minuto fechar: da ordem de um minuto. As latências medidas valem para a máquina do benchmark; o tempo do modelo isolado **não** é o tempo do sistema.
- A recuperação custa o tempo de carregar o instantâneo e reaplicar o registro, e a falha repetida de um lote custa isso a cada tentativa.
- Aceitar eventos de uma fonte não a torna "ao vivo": hoje só há demonstração local (replay, produtor de exemplo e eventos enviados à mão).
- Os scores dos eventos não reavaliam a qualidade dos modelos. A qualidade continua sendo a da avaliação oficial (`#ml/avaliacao`), e o período de teste não é usado para ajustar nada aqui.
- A sessão é controle de uso, não autenticação: quem acessa a porta pode abrir uma sessão. A API é feita para rodar em `127.0.0.1`; não exponha a porta em rede pública.

Para concluir o que falta, são necessários dados de fora do projeto:

1. **Referência p95/p99 por fluxo** (definição e período) e telemetria bruta, para um extrator causal `rede_v2`. Sem isso, a rede só aceita atributos já preparados.
2. **Transações do mesmo período e ambiente da telemetria**, com `timestamp_disponivel`.
3. **Tabela de vínculo real** (transação, sessão, dispositivo ou nó → fluxo), com validade e fonte documentada (ver [CONTRATO_COLETA_EVENTOS.md](CONTRATO_COLETA_EVENTOS.md)).
4. **Rótulos de fraude** com origem e data de confirmação, ou um critério de maturação para os legítimos.
5. **Custos de erro e capacidade de investigação**, para escolher limiares da fusão.

Com os itens 2 a 4, a comparação "financeiro × financeiro + rede" pode ser feita como descreve a seção 4 de [CONTRATO_INTEGRACAO.md](CONTRATO_INTEGRACAO.md).
