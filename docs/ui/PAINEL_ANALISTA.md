# Painel do analista

Página inicial do NodeWatch (`http://127.0.0.1:5000/`), feita para o uso diário de um analista de prevenção à lavagem de dinheiro: enviar ou escolher um dataset de transações, iniciar a análise, acompanhar o processamento e decidir quais transações e contas merecem investigação.

```bash
python src/sentinel_ai.py
```

Na raiz do projeto, com o ambiente virtual ativo. O terminal mostra o endereço do painel na linha `>> Painel do analista (use este): http://127.0.0.1:5000/`; abra-o no navegador. Não precisa de chave de API.

| endereço | o que é |
|---|---|
| `http://127.0.0.1:5000/` | **Painel do analista** (interface atual): dataset, análise, filtros, contas, grafo e tabela. É o endereço a usar. |
| `http://127.0.0.1:5000/legado` | **Interface antiga**, só para consulta: grafos de demonstração, seção de ML antiga (análise de rede, Analisar dataset, Eventos) e chat Sentinel AI. Não é o painel do analista. |
| `http://127.0.0.1:5000/#ml`, `/#ml/eventos`, `/#grafos` | Endereços antigos: redirecionam para a interface antiga (`/legado#ml`…). |

A interface antiga mostra no topo a faixa **Interface antiga do NodeWatch**, com o link **Abrir o painel do analista**, em todas as suas seções.

O painel não funciona aberto como arquivo (`interface/painel.html` com dois cliques): nesse caso a página explica como abri-lo pelo servidor. A visualização de análise de rede saiu do fluxo do analista e ficou na interface antiga; o processamento e os componentes de rede não foram alterados.

## Identidade visual

Tema escuro único (`interface/assets/painel.css`): azul-noite da interface anterior, ciano para ação e foco, e o vermelho da logo como cor da marca (só na logo e na linha do topo). Alerta usa vermelho-coral sempre junto de "⚠" e texto. Fontes do sistema, ícones em SVG embutido, nenhum recurso de CDN.

A logo é a oficial, `interface/NodeWatchlogo_transparente.png`. Os arquivos servidos são derivados dela só por recorte das margens e redução proporcional: `assets/nodewatch-logo.png` (cabeçalho) e `assets/nodewatch-simbolo.png` (tela estreita e ícone da aba). Capturas de antes e depois em `docs/ui/capturas/`.

## Sessão da interface

Enviar, validar e analisar exigem a sessão da página (`src/ml/sessoes.py`, a mesma das rotas `/api/ml`). A página abre a sessão, guarda-a em `sessionStorage` e manda um pulso a cada 15 s e ao voltar a ficar visível.

- **Janela de expiração: 150 s sem pulso.** Minimizar ou trocar de aba não encerra a sessão: o navegador espaça os pulsos para até 1 por minuto, dentro da janela.
- Sessão expirada ou encerrada: a análise para no próximo ponto seguro (fim do bloco), guarda o que pontuou e fica **parcial**. A validação em curso também para.
- **Nada é retomado sozinho.** Reabrir a página ou reiniciar o servidor só mostra o que ficou gravado.
- Outra aba ativa pode cancelar a análise ou assumi-la com **Manter a análise nesta aba**.
- Consultas (`GET`) não exigem sessão e não iniciam nada.

## Acesso local

`src/seguranca_local.py` vale para todo o servidor. Não há mais `Access-Control-Allow-Origin: *`.

- O cabeçalho `Host` precisa ser local (`127.0.0.1`, `localhost`, `::1` ou o `SENTINEL_HOST` configurado).
- Em `/api`, pedido com `Origin` diferente da do próprio servidor recebe 403 antes de qualquer rota, inclusive a pré-verificação `OPTIONS`.
- Escrita com `Sec-Fetch-Site` `cross-site` ou `same-site` é recusada.
- Pedidos sem `Origin` (curl, scripts locais) continuam aceitos, mas precisam da sessão para processar.
- `NODEWATCH_ORIGENS` libera origens extras de propósito; vem **desligada**. `*` é ignorado.

**Exceção: abrir a interface antiga como arquivo do disco.** Não é um modo normal de acesso. Para o painel do analista use `http://127.0.0.1:5000/`; para consultar a interface antiga use `http://127.0.0.1:5000/legado`. Nos dois casos não é preciso configurar nada.

Só se for mesmo preciso abrir `interface/index.html` com dois cliques: a página chega ao servidor como origem `null` e é recusada. Para liberar **temporariamente**, inicie o servidor assim:

```powershell
$env:NODEWATCH_ORIGENS = "null"; python src/sentinel_ai.py
```

```bash
NODEWATCH_ORIGENS=null python src/sentinel_ai.py
```

O terminal confirma com `Origens extras liberadas (NODEWATCH_ORIGENS): null` e mostra um aviso de risco. **Risco:** a origem `null` não é exclusiva dos arquivos do seu computador. Páginas em `iframe` com `sandbox`, de qualquer site aberto no mesmo navegador, também usam `null` e passam a poder chamar a API enquanto a variável estiver ligada.

**Para desligar:** feche o servidor (Ctrl+C) e inicie de novo sem a variável. No PowerShell, a variável continua valendo na mesma janela até ser removida: `Remove-Item Env:NODEWATCH_ORIGENS`. No bash, o formato `NODEWATCH_ORIGENS=null python ...` vale só para aquele comando. Origens externas continuam recusadas mesmo com `null` ligada.

## Fluxo de uso

1. **Dataset e análise.** Envie um `.csv` (ou `.zip` com um CSV) ou escolha um dataset já disponível. O servidor valida o arquivo e mostra nome, tamanho, linhas, período, colunas reconhecidas, moedas e formatos de pagamento. Cada problema traz coluna, linha de exemplo e o que corrigir.
2. **Analisar.** Só o clique em **Analisar**, com um dataset válido, inicia o processamento. Abrir a página, enviar ou validar não analisa nada.
3. **Progresso.** As seis etapas aparecem com o estado de cada uma, o volume lido e, quando há base medida, percentual e tempo restante (rotulado como estimativa). **Cancelar análise** para no fim do bloco atual e mantém o que já foi pontuado.
4. **Filtros.** Um único conjunto de filtros vale para os indicadores, as contas, o grafo e a tabela.
5. **Visão geral, contas e grafo.** Indicadores do recorte, até 10 contas de maior risco e o grafo da conta em foco.
6. **Tabela e detalhes.** Página a página, com seletor de colunas. O ID de exibição abre os detalhes da transação.
7. **Análises recentes.** Abrem os resultados gravados, sem reprocessar.

O botão ☰ abre o painel operacional (desempenho, logs do sistema, logs de ML, métricas de ML). **Legenda** reúne cores, ícones, setas, estados e termos. **Assistente de dúvidas** fica no canto inferior direito.

## Datasets

Formatos aceitos (os mesmos de `docs/ml/ANALISE_DATASETS.md`, só transações financeiras):

- `hismall_v1`: cabeçalho original do IBM AML (`Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,Amount Paid,Payment Currency,Payment Format`), com `Is Laundering` opcional.
- `transacao_hismall_v1`: os mesmos campos em português (`id_transacao,timestamp,banco_origem,…`), com `rotulo` opcional. Colunas extras são guardadas e podem ser exibidas na tabela.

**Arquivo de padrões (opcional).** É o `.txt` de tipologias que acompanha o dataset (por exemplo, `HI-Small_Patterns.txt`). Sem ele, o dataset não tem tipologias, e a tela diz isso em vez de mostrar zeros.

**Envio seguro** (`src/painel/datasets.py`):

- limite de 256 MB por arquivo (32 MB para o de padrões), conferido durante a gravação;
- o nome enviado vira só um rótulo sanitizado; no disco o arquivo se chama `dados.csv` ou `dados.zip`, em pasta com identificador gerado pelo servidor;
- tudo fica em `artefatos_ml/painel/datasets/`, pasta ignorada pelo git;
- nenhuma rota aceita caminho. Os datasets "do servidor" são descobertos em pastas fixas (`dados/`, `docs/exemplos/`, `artefatos_ml/exemplos/` e o arquivo de `ml_config.local.toml`) e identificados por um código.

**Estados do dataset:** válido; válido com linhas recusadas (elas ficam fora da análise e são listadas); inválido (formato, codificação, colunas obrigatórias ou nenhuma linha válida). Formato de pagamento vazio ou desconhecido é aceito e aparece como "Não informado".

Retenção: ficam guardados os 10 datasets enviados mais recentes.

## Processamento

Etapas reais, medidas no servidor (`src/painel/pipeline.py`):

| etapa | o que faz | progresso |
|---|---|---|
| Leitura e validação | lê o arquivo em blocos de 200 mil linhas e valida cada linha | bytes lidos / total |
| Ordenação cronológica | ordena por data e hora (empate: ordem da linha) e atribui os IDs de exibição | — |
| Tipologias registradas | casa o arquivo de padrões com as transações; pulada se não houver arquivo | — |
| Atributos, inferência e gravação | em blocos de 20 mil transações: estado incremental por conta, modelo salvo, gravação no SQLite | transações pontuadas / total |
| Índices e contagens gerais | cria os índices dos campos filtráveis | passos |
| Gravação do manifesto | escrita atômica do manifesto final | — |

A estimativa de tempo só aparece depois de 3 s de etapa com algum progresso: restante = o que falta ÷ vazão observada. Fora disso, o campo não existe.

Nada é treinado nem reajustado. A pontuação reusa `EstadoFinanceiro` e `pontuar_lavagem`, os mesmos do processamento de eventos. Uma análise por vez.

**Estados da análise:** em andamento; concluída; cancelada (a pedido; vale o que foi pontuado até ali); parcial (interrompida sem pedido, por exemplo servidor reiniciado; vale o que foi processado); erro (com causa e ação sugerida).

## Persistência

- **Manifesto:** `artefatos_ml/painel/analises/<id>/manifesto.json`, com id, dataset, hash SHA-256, datas, status, etapas, duração, versão do modelo, limiar, conversão do score, contagens, avisos e erros. A escrita é atômica (arquivo temporário na mesma pasta e `os.replace`, com novas tentativas no Windows).
- **Resultados por transação:** `resultados.sqlite`, um arquivo por análise.

**Por que SQLite e não JSON.** A tabela, os indicadores, as contas e o grafo filtram, ordenam e paginam no servidor. Um JSON teria de ser lido e percorrido inteiro a cada filtro. Medido com 2.076.752 transações (HI-Small, 01–03/09/2022): arquivo de 636 MB, visão geral em 0,4–1,7 s, página da tabela em 0,1–0,3 s, grafo em 0,1–0,2 s. O SQLite é da biblioteca padrão, grava em blocos durante a pontuação (o parcial fica consultável) e tem índices nos campos filtráveis.

**Retenção:** ficam as 20 análises mais recentes; as mais antigas são apagadas quando uma nova começa (`MAX_ANALISES` em `pipeline.py`).

## Score de 0 a 1000

O modelo devolve `predict_proba` de uma floresta aleatória treinada com subamostragem de negativos: um número de 0 a 1 que **não é probabilidade calibrada**. Na avaliação oficial, transações com valor entre 0,1 e 0,2 foram lavagem em 65% dos casos, e o limiar de alerta é cerca de 0,091. Multiplicar por 1000 colocaria todo alerta na faixa baixa.

A conversão (`src/painel/score.py`) é linear por partes, ancorada no limiar:

| score bruto | score do painel |
|---|---|
| 0 | 0 |
| logo abaixo do limiar | 700 |
| limiar | 701 |
| 1 | 1000 |

O score de 0 a 1000 é um índice, não probabilidade de lavagem nem de fraude. A tela mostra o limiar original (0,0910 no modelo atual) e o trecho do score original de cada faixa: baixa de 0 a 0,0391, intermediária de 0,0391 a 0,0910, alta de 0,0910 a 1.

Consequências testadas: a conversão é monótona; score ≥ 701 equivale exatamente a alerta; scores de modelos com limiares diferentes não são comparáveis entre si (o limiar fica no manifesto). O score bruto aparece nos detalhes.

| faixa | intervalo | recomendação |
|---|---|---|
| Baixa | 0–300 | sugestão de aprovação automática |
| Intermediária | 301–700 | área cinzenta para análise manual |
| Alta | 701–1000 | sugestão de recusa ou bloqueio |

As faixas são recomendações de uma análise offline. O NodeWatch não bloqueia nem paga nada e não tem integração bancária. Score alto é sinal para investigação, não prova.

## Tipologias

Vêm do arquivo de padrões do dataset (rótulo do simulador), nunca do modelo. A tela as chama de "registradas no dataset". Cada linha do arquivo é casada com a transação pela chave minuto, conta de origem, conta de destino, valor pago em centavos, moeda e formato. Uma transação em mais de uma tentativa conta em cada tipologia. `padrao_nao_identificado` reúne as transações sem tipologia registrada, inclusive as comuns.

## Filtros, tabela e contas

Filtros: De, Até, Moeda, Alerta (Todos, Com alerta, Sem alerta), Valor mínimo (começa em 1), Banco de origem, Banco de destino, Conta de origem, Conta de destino, Score mínimo e Score máximo (inteiros de 0 a 1000). Não há filtro de valor máximo, motivo, busca nem "amostra de conjunto maior".

**Valor mínimo.** A tela começa com valor mínimo 1, na moeda de cada transação e sem conversão entre moedas. A visão geral mostra quantas transações ficam fora por isso, por moeda. No exemplo de 2.076.752 transações, o padrão deixa 60.401 fora (45.541 em Bitcoin), nenhuma com alerta. Apagar o campo inclui essas transações; valores entre 0 e 1 não são aceitos no campo.

- **Posição:** lugar da linha na lista atual; muda com filtros e ordenação.
- **ID de exibição:** ordem cronológica no dataset inteiro, com empate pela ordem da linha; não muda. O identificador original e a linha do arquivo ficam nos detalhes.
- **Contas de maior risco:** 1º, quantidade de transações com alerta em que a conta participa no recorte; 2º, maior score entre elas; 3º, ordem alfabética. Não existe score por conta.

## Grafo

Um único componente, para a conta do filtro de origem, do filtro de destino ou escolhida no painel de contas. Mostra o que a conta enviou e recebeu e as cadeias até 1, 2 ou 3 saltos (padrão 2).

- Arestas direcionadas, com seta da origem para o destino.
- Arestas agrupam transações de mesma origem, destino e moeda, com quantidade e total. Moedas diferentes nunca são somadas.
- Limites: 30 vértices, 60 arestas e 300 contas expandidas por salto. A tela informa "exibindo X de Y transações relacionadas"; os totais por moeda usam todas as relacionadas do recorte.
- A disposição segue a tipologia registrada mais frequente entre as transações relacionadas: `CYCLE` circular, `FAN-OUT` leque de saída, `FAN-IN` leque de entrada, as demais e `padrao_nao_identificado` em camadas. A tipologia nunca é deduzida pela aparência.
- **Ordem no tempo.** Cada aresta mostra valor, moeda e horário (ou intervalo, se agrupada). Uma relação indireta só é marcada como sequência quando há transação em minuto posterior à chegada do dinheiro na conta intermediária (ou anterior à saída, no caminho até o foco). Mesmo minuto ou fora de ordem aparece tracejado, como "relação do recorte sem ordem temporal confirmada". As sequências confirmadas são listadas passo a passo e podem ser destacadas, inclusive as que voltam à conta em foco (ida e volta, marcada como "volta à conta em foco"). Horário compatível não prova que é o mesmo dinheiro.
- O grafo usa os filtros de período, moeda, alerta, valor, bancos e score. Os filtros de conta escolhem a conta em foco.

## Painel operacional

- **Desempenho:** RAM e CPU do processo do NodeWatch e da máquina (lidas do sistema operacional pela biblioteca padrão), latência de cada consulta em ms, e, da análise ativa ou da última, duração, pico de memória e duas vazões com a fórmula: a da análise inteira (pontuadas ÷ duração total) e a só da pontuação (pontuadas ÷ tempo de atributos, inferência e gravação). No exemplo de 2.076.752 transações: 88,6 s no total, cerca de 23,4 mil por segundo; 47,2 s de pontuação, cerca de 44 mil por segundo.
- **Logs do sistema** e **Logs de ML:** em `artefatos_ml/painel/logs/`. Não guardam contas, linhas do dataset, chaves nem caminhos.
- **Métricas de ML:** precisão, recall, F1 e Average Precision da avaliação histórica (`artefatos_ml/resultados/avaliacao_lavagem.json`), com origem, data e conjunto. Ficam separadas das contagens da análise atual. Métricas do dataset aberto só aparecem quando ele tem rótulo.

## Assistente de dúvidas

O chatbot antigo (`SentinelChat`, `POST /api/chat`) enviava um retrato da tela a um modelo de linguagem externo. O assistente do painel (`src/painel/assistente.py`) é local: responde com o glossário, a ajuda de uso e fatos lidos dos resultados gravados, com os filtros atuais. Não usa serviço externo, não envia dados do dataset e não conclui se houve fraude. O chat antigo continua disponível só na interface em `/legado`.

## API

Todas as rotas em `/api/painel` (`src/api_painel.py`):

| rota | uso |
|---|---|
| `GET /estado` | modelo, limites, legendas, análise em andamento |
| `GET /datasets`, `POST /datasets`, `GET /datasets/<id>`, `POST /datasets/<id>/validar` | catálogo, envio e validação |
| `GET /analises`, `POST /analises`, `GET /analises/<id>`, `POST /analises/<id>/cancelar` | histórico, início, manifesto e cancelamento |
| `GET /analises/<id>/visao` | indicadores e contas do recorte |
| `GET /analises/<id>/transacoes`, `GET /analises/<id>/transacoes/<n>` | página da tabela e detalhes |
| `GET /analises/<id>/grafo` | grafo da conta em foco |
| `GET /operacao/desempenho`, `/operacao/logs`, `/operacao/metricas` | painel operacional |
| `POST /assistente` | resposta local |

## Revisão de aceitação (11/11/2026)

Tudo abaixo foi executado nesta revisão, no Chrome (versão instalada nesta máquina), com arquivos pequenos. Os datasets grandes não foram reprocessados.

| verificação | como | resultado |
|---|---|---|
| Larguras 320, 390, 768, 1280 e 1440 px | Chrome sem janela; estados vazio, erro, resultados e alertas | sem rolagem horizontal da página, sem estouro, sem texto cortado e sem sobreposição no topo (depois das correções abaixo) |
| Carregamento | rede desacelerada (800 ms por pedido) | "Abrindo o painel e a sessão desta página…", anunciado como status |
| Aba em segundo plano | Chrome **com janela**, servidor real (150 s), janela minimizada por 400 s | `visibilityState=hidden`; o Chrome espaçou os pulsos para 1 por minuto; a sessão continuou ativa o tempo todo |
| Aba fechada | mesmo teste, uma segunda aba fechada | sessão dela expirou entre 140 e 150 s depois |
| Página fechada no meio da análise | Chrome com janela + servidor de teste com o código real, sessão de 20 s e modelo desacelerado, em pasta temporária | a análise parou 20 s depois, ficou parcial (233 de 394) e não recomeçou ao reabrir a página |
| Teclado | Tab, Enter, Espaço, setas e Esc reais | envio pelo seletor de arquivos, validação, análise, filtros, tabela, detalhes, contas, grafo, painel lateral e dataset do servidor, todos sem mouse |
| Leitura pelo sistema | UI Automation do Windows (a interface que o Narrador consome), Chrome com janela | 1.260 elementos; nenhum botão, campo, seletor, aba ou imagem sem nome; arestas lidas com origem, destino, valor, moeda, horário e alerta |
| Origem e CORS | curl contra o servidor real | origem externa: 403 em GET, POST e na pré-verificação; `Host` externo: 403; nenhuma resposta com `Access-Control-Allow-Origin` |
| `index.html` (interface antiga) como arquivo | Chrome sem janela, `file://` | sem a variável, a seção de ML diz "servidor indisponível"; com `NODEWATCH_ORIGENS=null` (exceção temporária), carrega e abre sessão; origem externa continua 403 |

Leitor de tela: o Narrador existe nesta máquina, mas não foi ligado. Ele fala em voz alta e assume o teclado da área de trabalho, e a fala não pôde ser ouvida nesta revisão. A leitura por tecnologia assistiva **não está confirmada**; o que foi confirmado é o que o sistema entrega a ela (UI Automation e árvore de acessibilidade do Chrome).

Correções feitas na revisão:

- **Rolagem horizontal em telas estreitas.** Em 320 e 390 px, a página ficava com 634 px de largura. As grades de uma coluna cresciam até a largura da opção mais longa do seletor de dataset (72 caracteres) e as de várias colunas tinham mínimo fixo (`minmax(320px, 1fr)`).
- **Carregamento.** A página ficava em branco enquanto abria a sessão.
- **Rótulos da escala do score.** Em 320 px, ficavam cortados.
- **Botão do assistente.** Em tela estreita, cobria o texto ao lado de **Analisar**; agora fica compacto ("Dúvidas") e a página ganha folga no fim.
- **Painel aberto como arquivo.** Dizia "servidor indisponível" mesmo com o servidor ligado; agora explica como abrir.

## Estabilização (11/11/2026)

Uso normal conferido do começo ao fim, com arquivos pequenos e sem reprocessar datasets grandes:

| fluxo | resultado |
|---|---|
| `python src/sentinel_ai.py` | o terminal mostra `>> Painel do analista (use este): http://127.0.0.1:5000/` e a interface antiga em seguida, identificada como antiga |
| `/` | painel do analista, sem erros no console |
| `/legado`, `/#ml`, `/#ml/eventos`, `/#grafos` | interface antiga, com a faixa de aviso e o link para `/`; o link leva ao painel |
| Envio de `com_linhas_ruins.csv` (399 linhas) pela tela | validação com 394 válidas e 5 recusadas listadas; análise concluída; valor mínimo 1 deixou 5 fora do recorte; filtros, tabela, detalhes, grafo e painel lateral funcionando |
| Dataset do servidor `docs/exemplos/transacoes_inventadas.csv` | validação (12 válidas, 3 recusadas) e análise concluída; grafo de `MERCADO1` mostra a ida e volta `MERCADO1 → NOVA0001 → MERCADO1` como sequência |
| Alertas | conferidos na análise já gravada (571 alertas): linhas com faixa e "⚠ Sim", detalhe com score 706 e limiar 0,0910, grafo com arestas vermelhas. Os dois arquivos pequenos não geram alertas (score máximo 177) |
| Carregamento, erro, cancelamento e fim de sessão | texto de carregamento anunciado; arquivo com colunas erradas recusado com a correção indicada; cancelamento deixa resultado parcial; página fechada no meio da análise deixa resultado parcial; nada recomeçou sozinho |
| Segurança | origem externa e `null` recebem 403 (leitura, escrita e pré-verificação); `Host` externo, 403; nenhuma resposta com `Access-Control-Allow-Origin` |

Cancelamento e fim de sessão foram testados num servidor de teste com o código real, pasta temporária, sessão de 20 s e modelo desacelerado, para a análise durar o suficiente. O prazo real de 150 s foi conferido antes, numa aba fechada sem análise rodando.

Correção feita: sequências que voltam à conta em foco eram marcadas como sequência na aresta, mas não apareciam na lista (o resumo dizia "horários compatíveis" e a lista ficava vazia).

## Testes

```bash
python -m pytest testes/painel -q
```

177 testes em `testes/painel/`: score e faixas, envio e validação, pipeline (progresso, cancelamento, parcial, erro, manifesto, reabertura), resultados (filtros sincronizados, denominadores, IDs, tipologias, top 10, grafo), API (legendas, métricas, logs, assistente), sessão e acesso local, ordem temporal, valor mínimo, vazões as regressões de interface (`test_interface_revisao.py`) e as rotas, mensagens de início e origens (`test_rotas_e_inicio.py`). A suíte inteira (`python -m pytest testes -q`) tem 385 testes.

## Limitações

- **Histórico das contas.** O modelo usa o que cada conta fez antes; o painel só conhece o que está no próprio dataset. Nas primeiras 72 horas do período ele tende a gerar menos alertas (a tela avisa). A área antiga "Analisar dataset", em `/legado`, aceita um arquivo de histórico.
- **Memória.** O dataset validado fica em memória durante a análise. Medido: pico de 2,2 GB no processo com 2,08 milhões de linhas.
- **Uma análise por vez**, sem pausa e retomada: uma análise interrompida (cancelada ou com a sessão expirada) recomeça do zero.
- **Acessibilidade:** conferida por teclas reais, contraste calculado, árvore de acessibilidade do Chrome e UI Automation do Windows. A fala de um leitor de tela (NVDA, Narrador) não foi ouvida.
- **Aba em segundo plano por muito tempo:** testada por 400 s. Se o navegador congelar a aba (economia de energia ou de memória), os pulsos param e a sessão expira; a análise fica parcial, como numa aba fechada.
- **PDFs desatualizados:** `docs/COMO_FUNCIONA_O_NODEWATCH.pdf` e `docs/APRESENTACAO_NODEWATCH.pdf` não foram regerados e ainda mostram os endereços antigos (`/#ml…`), que continuam funcionando pelo redirecionamento.
- **Sem tempo real e sem retomada:** o painel analisa arquivos; não processa transações ao vivo nem continua uma análise interrompida.
- **Grafo em tela estreita:** em 320 e 390 px, o grafo rola dentro da própria moldura (largura mínima de 660 px).
- **Tema:** só o escuro; a logo tem "Node" em branco e não serve a fundo claro.
- **Fuso horário.** O dataset não documenta o fuso; as datas são exibidas como estão no arquivo.
- **Só transações financeiras.** Medições de rede são recusadas neste painel.
