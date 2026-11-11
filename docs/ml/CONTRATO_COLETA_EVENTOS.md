# Contrato de coleta para um aplicativo instrumentado (PROPOSTA)

Este documento diz o que um aplicativo, ou o backend de pagamentos dele, precisa registrar para que transações e rede possam ser relacionadas de forma **verificável**. Com esses dados, a fusão `fusao_rede_transacao` pode ser treinada e avaliada.

Hoje esses dados não existem. O NodeWatch já aceita os eventos descritos aqui (ver [EVENTOS.md](EVENTOS.md)), mas sem dados reais a validação preditiva continua pendente.

O contrato complementa [CONTRATO_INTEGRACAO.md](CONTRATO_INTEGRACAO.md): aquele define as tabelas `transacao_v1` e `vinculo_v1` e a junção temporal; este define **como coletar** os dados na origem.

## 1. Princípios

1. **O vínculo é registrado, nunca inferido.** Proximidade de horário, mesmo IP aparente ou mesma conta não são vínculo. O aplicativo grava explicitamente que a transação X foi feita na sessão S, que usava o dispositivo D, cujo tráfego passa pelo fluxo de rede F.
2. **Conta bancária não é nó de rede.** `conta_origem` e `conta_destino` identificam contas. `anchor_id` e `probe_id` identificam equipamentos de medição. Nenhum dos dois serve de chave técnica.
3. **Todo instante tem relógio conhecido.** Use UTC, com relógios sincronizados por NTP e erro máximo documentado (por exemplo, ≤ 1 s). Cada evento leva o instante em que ocorreu e o instante em que ficou disponível para análise.
4. **Rótulo tem origem e data.** Fraude confirmada vem com a evidência (chargeback, investigação, decisão) e a data da confirmação. Ausência de confirmação não é legitimidade.
5. **Identidade estável.** Ids únicos, que não mudam no reenvio. O NodeWatch descarta duplicatas pela chave natural.

## 2. Eventos a emitir

Todos usam o envelope `evento_v1`: `tipo`, `versao_esquema`, `origem`, `modo = "novo_evento"` e `dados`. A seguir, os campos de `dados`.

### 2.1 Transação (`transacao`, esquema `transacao_hismall_v1`)

| campo | obrigatório | como coletar |
|---|---|---|
| `id_transacao` | sim | Id do backend de pagamentos, único e imutável. |
| `timestamp` | sim | Instante da transação (UTC). |
| `timestamp_disponivel` | recomendado | Quando a transação chegou ao sistema de análise. É o instante usado para escolher sinais de rede. |
| `banco_origem`, `conta_origem`, `banco_destino`, `conta_destino` | sim | Banco e conta. O NodeWatch forma a identidade `banco-conta`. |
| `valor_pago`, `moeda_pagamento`, `valor_recebido`, `moeda_recebimento` | sim | Valores e moedas como liquidados. Informe a fonte do câmbio, se houver conversão. |
| `formato` | sim | Meio de pagamento (ACH, Wire, Cartão, ...). Categorias fora das do treino viram indicadores zerados. |
| `chave_tecnica` | para a fusão | Id da **sessão** ou do **dispositivo** em que a transação foi iniciada. Precisa ser o mesmo id usado nos vínculos. |

### 2.2 Medição de rede (`medicao_rede`, esquema `rede_v1`)

Enquanto não houver extrator causal documentado, a medição precisa chegar com os 21 atributos `rede_v1` **já calculados** pela infraestrutura de medição, mais `id_fluxo` (`<probe_id>_<anchor_id>`), `anchor_id`, `probe_id` e `timestamp`.

Para um futuro `rede_v2`, que aceitaria a telemetria bruta, a fonte precisa fornecer:
- RTT e jitter por medição, perda de pacotes, TTL e intervalo de medição;
- **a referência p95/p99 de cada fluxo**, com o período usado no cálculo e a regra de atualização. Sem essa referência, as razões não podem ser reproduzidas.

### 2.3 Vínculo (`vinculo`, esquema `vinculo_v1`)

| campo | como coletar |
|---|---|
| `chave`, `tipo_chave` | `id_transacao` (vínculo direto) ou `chave_tecnica` (sessão ou dispositivo). |
| `id_fluxo` | Fluxo de rede que transporta o tráfego daquela sessão ou dispositivo. Vem do inventário de rede ou do roteamento, não de uma estimativa. |
| `valido_de`, `valido_ate` | Período em que a associação vale: início e fim da sessão, ou a mudança de rota. O fim é exclusivo. |
| `fonte_vinculo` | Sistema que afirmou a associação, por exemplo `inventario_rede:v3` ou `gateway_sessoes`. |
| `declarado_em` | Quando o vínculo ficou conhecido. Um vínculo declarado depois da transação **não** é usado para ela. |

### 2.4 Rótulos (fora do fluxo de eventos, para treino e avaliação)

Campos: `id_transacao`, `rotulo_fraude` (`fraude_confirmada`, `legitima_confirmada` ou `sem_conclusao`), `origem_rotulo` e `timestamp_confirmacao`. Quando a legitimidade é decidida por maturação, o prazo também precisa ser informado.

## 3. Qualidade mínima para começar a validar

| requisito | por quê |
|---|---|
| Transações e telemetria do **mesmo período** e do mesmo ambiente | Sem sobreposição no tempo não há sinal para relacionar. HI-Small (2022) e `dataset_final.csv` (2026) não se sobrepõem. |
| Fração conhecida de transações com vínculo, e o motivo de quem não tem | Para separar "sem vínculo" de "sem sinal" (`cobertura_vinculo`). |
| Rótulos maduros nos períodos de validação e de teste | Para comparar financeiro × financeiro + rede sem viés de rótulos pendentes. |
| Relógios sincronizados e erro documentado | A tolerância de 480 s e a regra "sinal anterior à decisão" dependem disso. |
| Custos de erro e capacidade de investigação | Para escolher o limiar da fusão. Sem eles, vale o máximo F1 na validação. |

## 4. Como o NodeWatch usará esses dados

1. Os eventos entram pela API (`POST /api/ml/eventos`) e são validados com as regras de [EVENTOS.md](EVENTOS.md). Hoje a API exige uma sessão ativa da interface; uma fonte contínua de produção precisará de uma autorização própria, que ainda não existe.
2. Cada transação recebe o último sinal de rede **disponível no instante da decisão**, pelos fluxos vinculados e vigentes, e o mostra ao lado do score financeiro.
3. Com rótulos maduros, treina-se `fusao_rede_transacao` como descreve a seção 4 de [CONTRATO_INTEGRACAO.md](CONTRATO_INTEGRACAO.md):
   - mesma divisão temporal;
   - modelo financeiro sem e com sinais de rede;
   - limiar escolhido na validação;
   - teste usado uma única vez.
