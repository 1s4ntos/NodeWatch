# Inicializador Rápido (Windows)

## Iniciar

1. Clique duas vezes em **`Iniciar_NodeWatch.bat`**.
2. Aguarde: o navegador abre sozinho no painel do analista, `http://127.0.0.1:5000/`, quando ele estiver pronto.

A interface antiga continua em `http://127.0.0.1:5000/legado`.

No primeiro uso, o inicializador cria o ambiente `.venv` na pasta do projeto e instala as dependências de `requirements.txt` e `requirements-ml.txt`. Isso **precisa de internet** e pode levar alguns minutos. Nos usos seguintes, ele aproveita o que já está instalado.

Se o NodeWatch já estiver rodando, o inicializador só abre o painel. Se a porta 5000 estiver ocupada por outro programa, ele avisa e não encerra nada.

## Token do Gemini (opcional)

Se `GEMINI_API_KEY` ainda não estiver configurado, o inicializador pergunta:

> Token do Gemini para habilitar o chat Sentinel AI (opcional). Cole o token ou pressione Enter para continuar sem ele:

- **Enter sem token:** o painel abre normalmente. Só o chat Sentinel AI, na interface antiga, fica indisponível até o token ser configurado.
- **Token colado:** a digitação fica oculta. O token é gravado na variável `GEMINI_API_KEY` do arquivo `.env`, na pasta principal do projeto. O arquivo é criado se não existir; se existir, só essa linha muda. O inicializador não exibe o token nas mensagens, não o passa como argumento de processo, não o grava em logs e não o testa no Gemini. O lugar onde o token fica guardado é o `.env`, em texto puro.
- **Token já configurado:** o inicializador não pergunta nem mostra o valor. Para trocar o token, edite a linha `GEMINI_API_KEY=` no `.env`.

**Atenção:** o `.env` guarda o token **localmente, em texto puro**. Não compartilhe esse arquivo nem faça commit dele. O `.gitignore` do projeto já ignora o `.env`.

## Encerrar

Na janela do inicializador, pressione **Ctrl+C**, ou feche a janela. Só o servidor iniciado por ela é encerrado.

## Requisitos

- **Python 3.14** no PATH. É a versão testada. O mínimo aceito é o 3.12, porque o `numpy==2.5.4` do `requirements-ml.txt` não instala no 3.11. As versões 3.12, 3.13 e 3.15 têm pacotes publicados, mas não foram testadas. O Python pode ser baixado em [python.org](https://www.python.org/downloads/windows/). O inicializador não instala o Python.
- Uma pasta de projeto com caminho curto, como `C:\NodeWatch` ou `Downloads\NodeWatch`. Algumas dependências têm nomes de arquivo muito longos, e num caminho profundo a instalação esbarra no limite de 260 caracteres do Windows. Espaços e acentos no caminho não atrapalham.
- A chave do Gemini **não** é necessária para o painel. Ela só é usada pelo chat da interface antiga (veja acima).

Alternativa sem o `.bat`: clique com o botão direito em `Iniciar_NodeWatch.ps1` e escolha **Executar com o PowerShell**.
