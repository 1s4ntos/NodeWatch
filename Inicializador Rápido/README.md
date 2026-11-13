# Inicializador Rápido (Windows)

Esta pasta tem dois atalhos com funções diferentes:

| Arquivo | O que faz |
|---|---|
| **`Iniciar_NodeWatch.bat`** | Inicia o **aplicativo NodeWatch**: prepara o `.venv`, sobe o servidor e abre o painel do analista. |
| **`Abrir_Site_Apresentacao.bat`** | Abre **só o site de apresentação** (`site/index.html`) no navegador. Não inicia o aplicativo. |

## Iniciar o aplicativo

1. Clique duas vezes em **`Iniciar_NodeWatch.bat`**.
2. Aguarde: o navegador abre sozinho no painel do analista, `http://127.0.0.1:5000/`, quando ele estiver pronto.

A interface antiga continua em `http://127.0.0.1:5000/legado`.

### Sequência de inicialização na janela

A janela abre com o banner **NODEWATCH** e uma lista das oito etapas em `[WAITING]`. Cada etapa é uma operação real do inicializador. A barra de progresso só avança quando a etapa termina, e um `[OK]` só aparece depois do sucesso.

| Etapa | O que acontece de verdade |
|---|---|
| 01 NODEWATCH BOOT | confere a pasta do projeto e a porta 5000 (reaproveita o NodeWatch desta pasta se já estiver rodando) |
| 02 ENVIRONMENT | encontra o Python 3.12+ e cria ou confere o `.venv` |
| 03 DEPENDENCIES | importa as bibliotecas no `.venv`; se faltar alguma, instala pelos `requirements` (saída do pip na tela) |
| 04 DATA ENGINE | mostra as versões de numpy, pandas, pyarrow e scipy carregadas na etapa 03 |
| 05 MACHINE LEARNING | `python -m src.ml.provisionamento`: instala e valida o modelo (a saída dele aparece inteira) |
| 06 SENTINEL AI | token do Gemini (opcional), como descrito abaixo |
| 07 FRAUD DETECTION | inicia `python src\sentinel_ai.py` (as mensagens do servidor aparecem como sempre) e lê `/api/painel/estado` para confirmar o modelo carregado e o estado do Sentinel AI |
| 08 SYSTEM READY | abre o painel e mostra **NODEWATCH ONLINE / FRAUD DETECTION SYSTEM READY / SYSTEM STATUS: OPERATIONAL** |

**Identidade visual:** é a mesma da logo.
- **Banner:** o símbolo (hexágono com o anel central e os seis nós) aparece em ASCII, em vermelho, ao lado de NODEWATCH. O "NODE" fica em branco `#F5F5F5` e o "WATCH" em vermelho `#FF2B1B`, sobre o fundo preto do console.
- **Vermelho:** etapas, divisores, barra de progresso e indicador de carregamento. MACHINE LEARNING e FRAUD DETECTION aparecem em destaque, com `► … [ CORE ]` e divisor duplo.
- **Verde:** só para operações concluídas com sucesso.
- **Quadro final:** NODEWATCH segue a logo, com NODE em branco e WATCH em vermelho.
- **Como as cores são aplicadas:** as cores exatas usam sequências ANSI de 24 bits. O inicializador testa se o console as interpreta; se não interpretar, usa as 16 cores do console. Para forçar as 16 cores, defina `NODEWATCH_CORES_BASICAS=1`.

Status: `[WAITING]` (cinza `#888888`), `[LOADING]` (vermelho, com indicador girando e o tempo decorrido enquanto o Python trabalha), `[OK]` (verde), `[WARN]` e `[LOCAL]` (amarelo), `[ERROR]` (vermelho, em negrito). Erros continuam com a saída técnica completa (pip, Traceback do servidor). Se o servidor encerrar antes de ficar disponível, a janela mostra **NODEWATCH OFFLINE / SYSTEM STATUS: FAILURE** e fica aberta até você pressionar Enter. Sem modelo de ML, o quadro final mostra **SYSTEM STATUS: DEGRADED**.

A animação acrescenta menos de 1 segundo e não instala nada: é feita com o próprio PowerShell. Para desligá-la, defina `NODEWATCH_SEM_ANIMACAO=1`; ela também é desligada quando a saída é redirecionada para um arquivo.

No primeiro uso, o inicializador cria o ambiente `.venv` na pasta do projeto e instala as dependências de `requirements.txt` e `requirements-ml.txt`. Isso **precisa de internet** e pode levar alguns minutos. Nos usos seguintes, ele aproveita o que já está instalado.

Em seguida ele prepara o **modelo de ML**: instala em `artefatos_ml/` o modelo distribuído em `modelos/`, conferindo o SHA-256 e fazendo uma previsão de teste, e mostra `[OK] Modelo de ML pronto`. Se algo falhar, a janela mostra a causa e o que fazer; o painel abre assim mesmo, mas novas análises ficam bloqueadas até o modelo ser instalado. Detalhes em [modelos/README.md](../modelos/README.md).

Se o NodeWatch **desta pasta** já estiver rodando, o inicializador só abre o painel. Se o NodeWatch em execução for de **outra pasta** (outra cópia ou um download mais antigo), ele mostra qual é e não abre o painel: feche aquele com Ctrl+C na janela dele e rode o inicializador de novo. Se a porta 5000 estiver ocupada por outro programa, ele avisa. Em nenhum caso ele encerra o que não iniciou.

## Abrir só o site de apresentação

Clique duas vezes em **`Abrir_Site_Apresentacao.bat`**. Ele abre `site/index.html` no navegador padrão, direto como arquivo local, porque o site é estático e não precisa de servidor. Não há nada para encerrar: basta fechar a aba.

O atalho só mostra o site:

- não inicia `src/sentinel_ai.py`;
- não abre o painel do analista;
- não pede o token do Gemini nem o modelo de Machine Learning;
- não exige Python nem internet.

O arquivo procura o site pela própria pasta (`..\site\index.html`). Espaços e acentos no caminho não atrapalham. Se a pasta `site` não estiver ao lado desta, ele avisa que o repositório deve ser extraído completo, com `site/` e `Inicializador Rápido/` preservadas.

## Token do Gemini (opcional)

Se `GEMINI_API_KEY` ainda não estiver configurado, o inicializador pergunta:

> Token do Gemini para habilitar o chat Sentinel AI (opcional). Cole o token ou pressione Enter para continuar sem ele:

- **Enter sem token:** o painel abre normalmente. O Sentinel AI fica indisponível até o token ser configurado: o Assistente de dúvidas responde no modo local (sem serviço externo) e o chat da interface antiga não funciona.
- **Token colado:** a digitação fica oculta. O token é gravado na variável `GEMINI_API_KEY` do arquivo `.env`, na pasta principal do projeto. O arquivo é criado se não existir; se existir, só essa linha muda. O inicializador não exibe o token nas mensagens, não o passa como argumento de processo, não o grava em logs e não o testa no Gemini. O lugar onde o token fica guardado é o `.env`, em texto puro.
- **Token já configurado:** o inicializador não pergunta nem mostra o valor. Para trocar o token, edite a linha `GEMINI_API_KEY=` no `.env`.

**Como o token chega ao Sentinel AI:** o servidor lê o `.env` quando inicia e o Sentinel AI usa a variável `GEMINI_API_KEY`. Uma `GEMINI_API_KEY` já definida nas variáveis de ambiente do Windows tem precedência (nesse caso o inicializador não pergunta). Para confirmar que funciona, abra o painel, clique em **Assistente de dúvidas** (canto inferior direito) e em **Testar conexão**. Se aparecer *Sentinel AI indisponível*, o motivo vem escrito (chave recusada, limite de uso, sem conexão, serviço indisponível); a lista completa e o que fazer estão em `docs/SENTINEL_AI.md`. Depois de trocar o token no `.env`, feche e abra o inicializador de novo.

**Atenção:** o `.env` guarda o token **localmente, em texto puro**. Não compartilhe esse arquivo nem faça commit dele. O `.gitignore` do projeto já ignora o `.env`.

## Encerrar

Na janela do inicializador, pressione **Ctrl+C**, ou feche a janela. Só o servidor iniciado por ela é encerrado.

## Requisitos

- **Python 3.14** no PATH. É a versão testada. O mínimo aceito é o 3.12, porque o `numpy==2.5.4` do `requirements-ml.txt` não instala no 3.11. As versões 3.12, 3.13 e 3.15 têm pacotes publicados, mas não foram testadas. O Python pode ser baixado em [python.org](https://www.python.org/downloads/windows/). O inicializador não instala o Python.
- Uma pasta de projeto com caminho curto, como `C:\NodeWatch` ou `Downloads\NodeWatch`. Algumas dependências têm nomes de arquivo muito longos, e num caminho profundo a instalação esbarra no limite de 260 caracteres do Windows. Espaços e acentos no caminho não atrapalham.
- A chave do Gemini **não** é necessária para o painel. Ela ativa o Sentinel AI no Assistente de dúvidas (que só envia o contexto da análise depois da sua autorização na tela) e o chat da interface antiga (veja acima).

Alternativa sem o `.bat`: clique com o botão direito em `Iniciar_NodeWatch.ps1` e escolha **Executar com o PowerShell**.
