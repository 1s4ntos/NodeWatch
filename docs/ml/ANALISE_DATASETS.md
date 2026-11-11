# Analisar dataset: dados novos com o modelo salvo

A área **Machine Learning → Analisar dataset** da interface antiga (`http://127.0.0.1:5000/legado#ml/analisar`) gera previsões para um arquivo escolhido por você, sem depender dos arquivos de exemplo. Ela é diferente de **explorar previsões existentes** (Análise de rede e Análise financeira), que só abre CSVs de previsões já calculadas.

Nada é treinado nem reajustado: câmbio, categorias, limiares e modelo são os do artefato salvo.

## Como usar

```bash
python src/sentinel_ai.py
```

> O painel do analista, em `http://127.0.0.1:5000/`, é o caminho principal para analisar um arquivo; esta página descreve a área equivalente da interface antiga, mantida para consulta (ver `docs/ui/PAINEL_ANALISTA.md`).

1. Abra `http://127.0.0.1:5000/legado#ml/analisar`. A página abre uma sessão; nada começa sozinho.
2. Selecione o dataset e, se tiver, um histórico anterior. Clique em **Validar arquivo**. Validar só confere o arquivo e não gera previsões.
3. Leia o resultado da validação: formato, linhas lidas, válidas e recusadas (com motivos), período, contas ou fluxos, rótulos e moedas ou formatos fora do treino.
4. Clique em **Analisar dataset** e acompanhe o progresso. Use **Pausar**, **Retomar análise** e **Cancelar** se precisar.
5. Em **Abrir resultados**, os dados aparecem nas tabelas, nos gráficos e nos filtros da exploração, sem nova inferência. **Exportar CSV** baixa as previsões.

## Formatos aceitos

Vale qualquer arquivo que cumpra um contrato, sejam quais forem o nome, o caminho, as datas, as contas ou a quantidade de linhas, dentro dos limites abaixo. A interface lista os mesmos formatos, com os cabeçalhos.

### `hismall_v1`: transações no formato original do IBM AML

```
Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,Amount Paid,Payment Currency,Payment Format
```
- `Is Laundering` é opcional, como última coluna (0 ou 1).
- A primeira coluna `Account` é a origem e a segunda, o destino.
- `Timestamp` em `AAAA/MM/DD HH:MM`, tratado como UTC, com resolução de minuto.
- A conta é identificada por `banco-conta`.

### `transacao_hismall_v1`: os mesmos campos em português

```
id_transacao,timestamp,banco_origem,conta_origem,banco_destino,conta_destino,valor_pago,moeda_pagamento,valor_recebido,moeda_recebimento,formato
```
- `rotulo` é opcional (0 ou 1).
- `timestamp` em ISO 8601, `AAAA/MM/DD HH:MM` ou época em segundos. Sem fuso, vale UTC.
- `id_transacao` é a identidade: repetido, é recusado.

### `rede_v1`: medições com atributos já preparados

```
id_fluxo,anchor_id,probe_id,timestamp,perda_pct,rtt_ausente,razao_rtt_p95,razao_rtt_p99,razao_jitter_p95,amplitude_rtt_rel,delta_ttl_clip,ttl_reset,perda_media_w3,rtt_p95_max_w3,jitter_p95_max_w3,n_rtt_acima_p95_w3,perda_media_w6,rtt_p95_max_w6,jitter_p95_max_w6,n_rtt_acima_p95_w6,perda_media_w12,rtt_p95_max_w12,jitter_p95_max_w12,n_rtt_acima_p95_w12,perdas_consecutivas
```
- `alvo` é opcional.
- Telemetria bruta não é aceita: a referência p95/p99 por fluxo não está documentada, e aceitar arquivos novos não muda o significado dos atributos.

### Reconhecidos, mas não analisáveis aqui

| arquivo | o que acontece |
|---|---|
| `previsao_rede_v1` / `previsao_lavagem_v1` | Identificado como previsões já calculadas: abra em **Importar** nas áreas de análise. |
| CSV do grafo (`step,type,amount,nameOrig,nameDest`) | Serve à análise de grafos pela CLI. Para o modelo financeiro faltam bancos, moedas, valor recebido e data absoluta (`step` é relativo). A tela lista o que falta; nada é inventado. |
| Qualquer outro | A tela mostra o contrato mais próximo e as colunas que faltam. |

### Limites

- Dataset: até 256 MB; histórico: até 512 MB. CSV ou ZIP com um CSV.
- O arquivo é lido em blocos de 250 mil linhas e fica em memória durante a análise. Testado na interface até 482.650 linhas de dataset e, como histórico, o HI-Small inteiro (5,08 milhões de linhas; 53 s no total).
- Uma análise por vez.
- O arquivo inteiro é analisado: não há amostragem.

## Validação linha a linha

Uma linha com data inválida, banco não numérico, conta, moeda ou formato vazios, valor ausente, negativo ou não numérico, ou rótulo fora de {0, 1} é **recusada**, com o motivo e exemplos. Ela não é preenchida. Em `rede_v1`, linhas fora das faixas do esquema e chaves `id_fluxo + timestamp` repetidas também são recusadas.

Moedas e formatos fora dos do treino **não** são recusados, mas ficam sinalizados. Moeda sem taxa aprendida deixa o valor em USD ausente, com o indicador `sem_taxa_cambio`. Nenhuma taxa é inventada.

## Histórico

Cada análise tem identidade, pasta e estado financeiro próprios (`artefatos_ml/analises/.jobs/<id>/`). Nada é herdado de outro arquivo.

O histórico é **opcional**, mas muda muito o resultado. O modelo foi treinado com contas que têm passado; sem ele, os atributos de contagem ficam subestimados. Medido com o dia 03/09/2022 do HI-Small (207.382 linhas, 391 positivos):

| | alertas | precisão | recall | average precision |
|---|---|---|---|---|
| sem histórico | 1 | 100% | 0,3% | 0,143 |
| com 01–02/09 como histórico (1,87 milhão de transações) | 203 | 57,6% | 29,9% | 0,394 |

Esses números mostram o efeito da falta de histórico. **Não** são avaliação do modelo: 03/09 pertence ao período de treino. A avaliação oficial continua em `#ml/avaliacao`.

Do histórico informado, só entra o que é anterior ao primeiro minuto do dataset; o resto é ignorado e contado. A cobertura aparece no cartão da análise. `historico_incompleto` marca as previsões com menos de 72 h de observação no estado.

## Ordem, identidade e resultados

- As linhas são ordenadas por minuto (ordenação estável). `linha_origem` guarda a posição original (0 = primeira linha de dados).
- Cada minuto é pontuado contra o estado anterior a ele, com o mesmo código do processamento de eventos.
- Saída: `artefatos_ml/analises/<id>_<nome>__previsoes_<dominio>.csv` e `.relatorio.json`, com dataset, hash, modelo, limiar e situação. O cartão também mostra formato do esquema, instante e contagens.
- Resultados de análises pausadas, canceladas ou interrompidas aparecem como **resultado parcial**, inclusive na exploração.
- **Sem rótulos**, há scores, alertas e estatísticas, e as métricas supervisionadas ficam indisponíveis.
- **Com rótulos**, há uma avaliação separada, no limiar oficial. Os rótulos não entram nos preditores e não disparam treino: os scores são os mesmos com ou sem a coluna (testado).
- Indicadores de domínio são só os que dá para sustentar: moedas e formatos fora do treino, fração sem taxa, fração acima do p99 do treino e, na rede, PSI. Compatibilidade de formato não garante o mesmo desempenho em outra população, e não há medida de confiança inventada.

## Sessão, pausa, encerramento e retomada

Definição em `src/ml/sessoes.py`; prazos informados por `GET /api/ml/sessao`.

| situação | comportamento |
|---|---|
| Iniciar o servidor, abrir a interface, consultar status | Nada é analisado, reproduzido ou retomado. |
| Pedido sem sessão ativa | HTTP 403; nada roda em segundo plano. |
| Sessão | Uma por aba. Recarregar a aba mantém a sessão. Trocar entre Grafos e ML não a afeta. |
| Renovação | Pulso a cada 15 s e ao voltar a ficar visível. |
| Aba em segundo plano ou janela minimizada | Não encerra. Continua renovando; o navegador espaça os temporizadores, e o prazo cobre isso. |
| Aba fechada, navegador caído, conexão perdida | Sem pulso por **150 s**, a sessão expira. Não há aviso confiável de fechamento de janela, então a detecção não é instantânea. |
| Ponto seguro | Fim do bloco em andamento (até 20 mil linhas, frações de segundo a 2 s, conforme a máquina). Interrupção total: cerca de 150 s + um bloco. |
| **Pausar** | Para no ponto seguro, com checkpoint. Resultado parcial. |
| **Cancelar** | Igual, mas definitivo: o parcial fica identificado e não pode ser retomado. |
| **Encerrar sessão** | Vale na hora: o trabalho dela para no próximo ponto seguro, como pausado. |
| Queda do servidor no meio | A análise aparece como *interrompida*. Ao retomar, a saída volta ao tamanho do último checkpoint (a cada 30 s) e o restante é refeito, sem duplicar. |
| Reabrir a interface | Mostra o que ficou parado e oferece **Retomar análise**. Nunca retoma sozinha. |
| Várias abas | Cada uma tem a sua sessão. Todas veem as análises; a responsável aparece como "esta aba" ou "outra aba". Qualquer aba ativa pode pausar ou cancelar. Retomar transfere a responsabilidade para quem retomou. |

## API

| rota | uso |
|---|---|
| `GET /api/ml/analises` | Análises, formatos e limites. |
| `POST /api/ml/analises` | [sessão] Multipart `arquivo` e, opcionalmente, `historico`: seleciona e valida. |
| `GET /api/ml/analises/<id>` | Progresso e resultados. |
| `POST /api/ml/analises/<id>/iniciar\|retomar\|pausar\|cancelar` | [sessão] Controle. |

Sessão é o cabeçalho `X-NodeWatch-Sessao`. As regras completas estão em [EVENTOS.md](EVENTOS.md).
