# Processamento de eventos no NodeWatch

O NodeWatch recebe eventos, gera previsões novas com o modelo salvo e mostra o resultado na seção **Machine Learning → Eventos** do painel (`#ml/eventos`).

- **Nada é treinado nem reajustado.** O artefato `modelo_unificado.joblib` é carregado **uma vez por processo** e usado como está, inclusive o `PreparadorFinanceiro` (câmbio, formatos, moedas, colunas e quantis).
- **Nenhuma fonte é "ao vivo".** O replay reenvia arquivos existentes e é rotulado como *replay histórico*. A API recebe o que um produtor enviar. A simulação é rotulada como *simulação*.
- **Rede e lavagem continuam separadas.** A fusão `fusao_rede_transacao` segue **indisponível**. Quando há vínculo, o sinal de rede aparece ao lado do score financeiro, sem combiná-los.

Números de desempenho e de equivalência: [BENCHMARK_EVENTOS.md](BENCHMARK_EVENTOS.md). Contrato para um aplicativo instrumentado: [CONTRATO_COLETA_EVENTOS.md](CONTRATO_COLETA_EVENTOS.md).

## 1. Como executar

```bash
python src/sentinel_ai.py
```
Abra `http://127.0.0.1:5000/#ml/eventos`. Não precisa de chave do Gemini.

Na tela:

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

Produtor de exemplo, que envia pela API HTTP:

```bash
python scripts/produtor_eventos_exemplo.py --tipo financeiro --limite 2000
```
```bash
python scripts/produtor_eventos_exemplo.py --tipo rede --limite 500 --eventos-por-segundo 50
```

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
| fila e trabalhador | `src/ml/servico_eventos.py` | Fila limitada, um trabalhador, regras de duplicata, atraso e fechamento de minuto. |
| preparação de atributos | `src/ml/incremental.py` | Estado por conta: os 49 atributos financeiros sem reconstruir o histórico. A rede chega preparada. |
| inferência | `src/ml/previsao.py` | `tabela_previsoes_rede` e `pontuar_lavagem`, as mesmas funções usadas pela CLI. |
| persistência | `EstadoFinanceiro.salvar` e `ServicoEventos.salvar_estado` | Instantâneo atômico em `artefatos_ml/estado_eventos/`. |
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
| identidade (`chave_natural`) | servidor | `tx:<id_transacao>`, `rede:<id_fluxo>@<timestamp>` ou `vinc:<hash>` de chave, tipo, fluxo e validade. É usada para descartar duplicatas. `id_evento`, se vier, é só exibido. |
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

## 4. Regras de entrega

| situação | o que acontece |
|---|---|
| **Duplicata** (mesma chave natural) | Recusada como `duplicada`. Transações: o id fica lembrado nos minutos abertos e em até 500 mil ids recentes; minuto fechado nunca reabre, então nada é contado duas vezes mesmo depois disso. Rede: até 200 mil chaves recentes. Vínculos: todos. |
| **Atraso** (transação de minuto já fechado) | Recusada como `atrasada`. **Não entra no estado nem é pontuada**: incorporá-la mudaria atributos já emitidos de transações posteriores. Aparece em *Recusas* com o minuto. |
| **Fechamento do minuto** | Um minuto fecha quando chega uma transação de minuto posterior (`atraso_permitido_min = 0`), ou depois disso se `NODEWATCH_ATRASO_MIN` for maior. Também fecha por `POST /api/ml/eventos/fechar`, pelo fim do replay financeiro ou depois de `fechar_ocioso_s = 5 s` sem eventos. Ao fechar, todas as transações do minuto são pontuadas contra o estado anterior e só então incorporadas. |
| **Fila cheia** (20.000) | A API recusa os excedentes com `fila_cheia` e responde HTTP 429 com `Retry-After`. Nada é descartado em silêncio. O replay espera vaga. |
| **Reinício** | O instantâneo é gravado ao pausar um replay, no fim dele, a cada 120 s com atividade, ao parar o servidor e em *Gravar estado agora*. Ao subir, o servidor restaura o estado, volta cada CSV de saída ao tamanho registrado no instantâneo e o replay continua da última posição **processada**. O que foi feito depois do instantâneo é refeito, sem duplicar linhas. Instantâneo de outra versão do modelo é ignorado e isso aparece no status. |
| **Falha num lote** | O lote é contado em `falhas`, com a última mensagem no status, e o trabalhador continua. |
| **Carga inicial** | Bloqueia o trabalhador enquanto monta o estado. O status continua respondendo, com a marca `ocupado`. |

`POST /api/ml/eventos/fechar` fecha **todos** os minutos abertos. Usá-lo com um replay financeiro no meio de um minuto faz o restante desse minuto chegar atrasado.

O estado financeiro tem **uma linha do tempo**. Misturar no mesmo estado um replay de 2022 e eventos novos de 2026 faz o que for mais antigo chegar atrasado. Use *Descartar estado* entre cenários.

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

| método e rota | uso |
|---|---|
| `GET /api/ml/eventos/status` | Trabalhador, modos, fila, contadores, recusas, falhas, latências, cobertura, replays, saídas, versões, configuração e fusão. |
| `GET /api/ml/eventos/contratos` | Envelope e esquemas aceitos. |
| `POST /api/ml/eventos` | Ingestão de `{"eventos": [...], "origem": "...", "modo": "..."}`, até 5.000 por pedido. Responde 202, ou 429 se a fila encheu. |
| `POST /api/ml/eventos/fechar` | Fecha os minutos financeiros abertos. |
| `GET /api/ml/eventos/recentes?dominio=rede\|lavagem\|rejeicoes&n=50` | Últimas previsões ou recusas. |
| `POST /api/ml/eventos/replay` | `{"fonte": "rede\|financeiro", "acao": "iniciar\|pausar\|retomar\|parar", "eventos_por_segundo": 0, "usar_historico": false}`. |
| `POST /api/ml/eventos/salvar` | Grava o instantâneo agora. |
| `POST /api/ml/eventos/descartar` | Para os replays e apaga o instantâneo e os arquivos `eventos_*` deste serviço. |
| `GET` / `POST /api/ml/eventos/laboratorio` | Último relatório ou nova execução do laboratório de SIMULAÇÃO. |
| `POST /api/ml/prever/rede` | Previsão síncrona de até 1.000 medições `rede_v1` em JSON. Devolve id, instante da medição, instante de processamento, horizonte, classe, probabilidades, score, alerta, limiar e versão. |
| `POST /api/ml/prever/rede/csv` | CSV `rede_v1` (multipart, campo `arquivo`, até 64 MB) → `artefatos_ml/previsoes/<nome>_previsoes_rede.csv` + relatório. |

Exemplo de ingestão:

```bash
curl -X POST http://127.0.0.1:5000/api/ml/eventos -H "Content-Type: application/json" -d "{\"eventos\":[{\"tipo\":\"transacao\",\"dados\":{\"id_transacao\":\"t-1\",\"timestamp\":\"2026-11-03T12:00:00Z\",\"banco_origem\":12,\"conta_origem\":\"8010D4440\",\"banco_destino\":137218,\"conta_destino\":\"80EB2C3F0\",\"valor_pago\":1500.0,\"moeda_pagamento\":\"US Dollar\",\"valor_recebido\":1500.0,\"moeda_recebimento\":\"US Dollar\",\"formato\":\"ACH\"}}]}"
```

## 8. Versões

| item | valor |
|---|---|
| envelope | `evento_v1` |
| esquemas aceitos | `transacao_hismall_v1`, `rede_v1`, `vinculo_v1` |
| estado financeiro | `estado_financeiro_v1`, mais a assinatura do `PreparadorFinanceiro`: hash de câmbio, formatos, moedas e colunas |
| modelo (artefato atual) | `estado_rede-20261102T083053Z` (limiar 0,3173, treinado até 2026-10-03T17:59:49 UTC) e `lavagem-20261102T083253Z` (limiar 0,0910) |
| instantâneo | só é restaurado se as versões das duas cabeças e a assinatura do preparador forem as mesmas |

## 9. Limites e dados externos necessários

Limites conhecidos:
- Um trabalhador por processo e estado em memória. Com o HI-Small completo, o instantâneo tem centenas de MB; veja o benchmark.
- Minuto financeiro fechado não reabre. Corrigir uma transação atrasada exige refazer o estado a partir do histórico.
- A latência financeira inclui a espera pelo fechamento do minuto. As latências medidas valem para a máquina do benchmark; o tempo de 9 ms de uma previsão do modelo **não** é o tempo do sistema.
- Os scores dos eventos não reavaliam a qualidade dos modelos. A qualidade continua sendo a da avaliação oficial (`#ml/avaliacao`), e o período de teste não é usado para ajustar nada aqui.
- A API não tem autenticação. É feita para rodar em `127.0.0.1`; não exponha a porta em rede pública.

Para concluir o que falta, são necessários dados de fora do projeto:

1. **Referência p95/p99 por fluxo** (definição e período) e telemetria bruta, para um extrator causal `rede_v2`. Sem isso, a rede só aceita atributos já preparados.
2. **Transações do mesmo período e ambiente da telemetria**, com `timestamp_disponivel`.
3. **Tabela de vínculo real** (transação, sessão, dispositivo ou nó → fluxo), com validade e fonte documentada (ver [CONTRATO_COLETA_EVENTOS.md](CONTRATO_COLETA_EVENTOS.md)).
4. **Rótulos de fraude** com origem e data de confirmação, ou um critério de maturação para os legítimos.
5. **Custos de erro e capacidade de investigação**, para escolher limiares da fusão.

Com os itens 2 a 4, a comparação "financeiro × financeiro + rede" pode ser feita como descreve a seção 4 de [CONTRATO_INTEGRACAO.md](CONTRATO_INTEGRACAO.md).
