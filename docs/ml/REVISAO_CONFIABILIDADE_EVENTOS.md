# Revisão de confiabilidade do processamento de eventos

Revisão da versão `9095451`. Cada problema foi constatado por leitura do código e depois reproduzido por um teste que falha nessa versão. A saída da execução antiga está em [`evidencias/testes_antes_9095451.txt`](evidencias/testes_antes_9095451.txt). Os testes estão em `testes/ml/test_confiabilidade_eventos.py`.

Os números de linha abaixo são da versão antiga, `9095451`.

## 1. Problemas confirmados

| # | Problema | Constatação por leitura | Reprodução (falhou em `9095451`) | Correção |
|---|---|---|---|---|
| 1 | Previsão fechada por ociosidade não era gravada | `servico_eventos.py:322-326` chama `_fechar(None)`; a escrita só ocorre em `processar` (`:364`); `salvar_estado` (`:529`) não leva `_pendentes` | `test_fechamento_por_ociosidade_grava_a_previsao_e_sobrevive_ao_reinicio`: `[] == ['t1']` | Fechamento e escrita passam pelo mesmo ciclo de confirmação |
| 2 | Evento da API sem fonte durável | Fila só em memória; `restaurar` (`:572`) volta as saídas à marca do instantâneo | `test_evento_da_api_sobrevive_a_queda_sem_novo_instantaneo`: o CSV mantinha `t1`, mas o estado restaurado tinha 0 transações. Estado e saída ficavam **incoerentes**, e a retransmissão duplicaria a previsão | Registro durável com fsync antes de aceitar; recuperação explícita |
| 3 | Falha depois de aplicação parcial | `incremental.py:229` incorpora antes de pontuar (`servico_eventos.py:467`); a rede marca a duplicata (`:415`) antes de prever; a exceção (`:371-379`) só limpa as pendências; o cursor usa `max` (`:368`) | `test_falha_na_pontuacao_nao_perde_nem_duplica_a_transacao` e `test_falha_na_previsao_de_rede_nao_marca_a_medicao_como_vista` | Preparação → aplicação → confirmação; reconstrução e nova tentativa; bloqueio identificado |
| 4 | Ociosidade fechava o minuto corrente | `:325-326`; `incremental.py:190` recusa o resto do minuto | `test_pausa_dentro_do_minuto_nao_torna_a_proxima_transacao_atrasada`: `atrasada == 1` | Fechamento por tempo do evento; relógio só para eventos novos, depois do fim do minuto + atraso + carência |
| 5 | Relatório de desempenho confundia medidas | Leitura de `BENCHMARK_EVENTOS.md` e do gerador | Não se aplica (texto) | Relatório refeito, com o que cada medida inclui e não inclui; nova medição com fsync |

Encontrados durante esta revisão, na interface e no backend novos, e corrigidos:

| Problema | Como apareceu | Correção |
|---|---|---|
| O formulário de Analisar dataset reenviava o histórico da seleção anterior | Captura da demonstração: um arquivo sem histórico apareceu com histórico | Formulário limpo depois de cada validação |
| O fim do replay de rede fechava o minuto de um replay financeiro simultâneo | 111 recusas na demonstração anterior | Só o replay financeiro fecha minutos; `test_replays_simultaneos_nao_fecham_minutos_um_do_outro` |
| Replay pausado por sessão inativa esperaria 600 s por uma fila que ninguém consome | Leitura | `esperar_fila_vazia` retorna; `test_esperar_fila_nao_trava_sem_sessao` |
| Contadores de análise podiam dobrar ao retomar depois de erro | Leitura | Contadores salvos no checkpoint |
| Instantâneo antigo sem `meta.json` poderia ser carregado | Leitura, com o arquivo real da pasta | Renomeado para `.legado.pkl`, nunca carregado; `test_instantaneo_antigo_sem_registro_nao_e_carregado` |

## 2. Cenários de falha cobertos

**Por teste automatizado**, com falha injetada e a comprovação no CSV em disco:

| Cenário | Resultado exigido |
|---|---|
| Falha temporária na pontuação do modelo (financeiro e rede) | Uma previsão e uma atualização lógica |
| Falha na escrita da saída | Repetição sem duplicar |
| Falha depois de saída parcial do lote (rede escrita, lavagem não) | Rede não duplicada |
| Falha persistente | Bloqueio; evento identificado; `aplicado_ate` não avança; `repetir` funciona depois de corrigir |
| Falha persistente seguida de queda | Volta bloqueado, sem perder nada |
| Descarte explícito | Gravado no registro e em `recusas`; sobrevive ao reinício |
| Falha na gravação do instantâneo | Anterior preservado; registro intacto; recuperação correta |
| Queda depois de aceitar e antes de aplicar | Reaplicado |
| Linha final incompleta no registro | Ignorada |
| Queda depois do instantâneo e antes de podar | Nada é reaplicado duas vezes |
| Mesma identidade com outro conteúdo | `conflito` |
| Relógio de 2026 sobre minuto de replay de 2022 | Não fecha |

**Pela interface real**, com Chrome headless (saídas em [`evidencias/`](evidencias/)):

| Cenário | Observado |
|---|---|
| Sem sessão ou com sessão inventada | HTTP 403 |
| Reabrir ou consultar status | Nada inicia; trabalhador parado |
| Trocar entre Grafos e ML | Mesma sessão |
| Dois datasets diferentes até os resultados | Concluídos; sem contas de um no outro; exportação com o número certo de linhas |
| Pausa e retomada | 207.382 linhas, todas com `linha_origem` única |
| Cancelamento | Marcado como resultado parcial também na exploração; sem botão de retomar |
| Evento pela API e `Stop-Process -Force` no servidor | Depois de reiniciar, nada roda até a ação; recuperação com 3 eventos reaplicados e uma linha por evento; retransmissão reconhecida; conteúdo diferente recusado |
| Navegador morto no meio de uma análise (prazo de 5 s no servidor de demonstração) | Análise parou sozinha em 6,0 s; sessão velha recusada; reabertura sem retomada; concluída depois da ação explícita |
| Aba realmente oculta (`visibilityState = hidden`) por 7 min | Pulsos passam de 15 s para 60 s depois de cerca de 80 s; sessão continua ativa, porque o prazo é de 150 s |
| Eventos bloqueados | Causa e evento na tela; repetir com a causa presente mantém bloqueado; sem ela, confirma; descarte registrado |
| Produtor | Funciona com sessão; reenvio é reconhecido; com sessão inválida ou encerrada, recusa explicada e código de saída 3 |
| Celular (390 px) | Sem rolagem horizontal da página; sem erros de console |

## 3. O que estas evidências não cobrem

- Queda do sistema operacional ou perda de energia. O `fsync` foi chamado, mas nenhum desses cenários foi executado.
- Concorrência HTTP sob carga: as medições são de um pedido por vez.
- A aba oculta foi testada no Chrome headless por 7 min. Outros navegadores e economia de energia do sistema podem espaçar mais os temporizadores. Se passarem de 150 s, a sessão expira e o trabalho pausa, com retomada explícita: o efeito é seguro, mas interrompe.
- Conexão com uma fonte real de dados: só há demonstração local.
- A fusão rede + transação continua sem validação preditiva.

## 4. Política resultante

Aceitação, durabilidade, recuperação, duplicatas e atraso: [EVENTOS.md, seção 4](EVENTOS.md). Sessão e análise de datasets: [ANALISE_DATASETS.md](ANALISE_DATASETS.md). Desempenho: [BENCHMARK_EVENTOS.md](BENCHMARK_EVENTOS.md).
