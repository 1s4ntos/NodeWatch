# Como rodar localmente

Guia para executar o Sentinel AI e o dashboard na sua maquina.

## Pre-requisitos

- Python 3.11+
- Chave de API do Google Gemini ([aistudio.google.com/apikey](https://aistudio.google.com/apikey))
- Navegador moderno (Chrome, Firefox ou Edge)

---

## Inicio rapido para apresentacao

### Windows

```powershell
.\start_presentation.ps1
```

### Linux/macOS

```bash
chmod +x start_presentation.sh
./start_presentation.sh
```

Depois acessar:

```
http://127.0.0.1:5000/
```

O script:

- Verifica se o Python esta instalado;
- Cria `.venv` se nao existir;
- Instala dependencias;
- Cria `.env` a partir de `.env.example` se nao existir;
- Valida se a `GEMINI_API_KEY` esta configurada (rejeita placeholders);
- Inicia o backend com `python src/sentinel_ai.py`;
- Nao exibe a chave no terminal.

---

## Como rodar localmente no Windows

1. Criar ambiente virtual e instalar dependencias:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Copiar `.env.example` para `.env` e inserir sua chave do Gemini:

```powershell
Copy-Item .env.example .env
notepad .env
```

3. Iniciar o backend:

```powershell
python src/sentinel_ai.py
```

4. Abrir o dashboard no navegador:

```
http://127.0.0.1:5000/
```

Ou usar o script de setup completo:

```powershell
.\run_local.ps1
```

---

## Como rodar localmente no Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python src/sentinel_ai.py
```

Depois acessar:

```
http://127.0.0.1:5000/
```

Ou usar o script de setup completo:

```bash
chmod +x run_local.sh
./run_local.sh
```

---

## Como obter a GEMINI_API_KEY

1. Acesse [Google AI Studio](https://aistudio.google.com/apikey)
2. Faca login com sua conta Google
3. Clique em "Create API Key"
4. Copie a chave gerada
5. Cole no campo `GEMINI_API_KEY` do arquivo `.env`

---

## Como testar se o backend esta online

Abrir no navegador:

```
http://127.0.0.1:5000/health
```

Resposta esperada:

```json
{
  "status": "ok",
  "service": "Sentinel AI",
  "provider": "gemini",
  "model": "gemini-2.5-flash",
  "apiKeyConfigured": true
}
```

---

## Configuracao do `.env`

O arquivo `.env` armazena a chave de API e **nunca deve ser commitado**.

Exemplo seguro (sem chave real):

```env
SENTINEL_PROVIDER=gemini
GEMINI_API_KEY=coloque_sua_chave_gemini_aqui
GEMINI_MODEL=gemini-2.5-flash
SENTINEL_HOST=127.0.0.1
SENTINEL_PORT=5000
```

| Variavel           | Descricao                          | Valor padrao              |
| ------------------ | ---------------------------------- | ------------------------- |
| SENTINEL_PROVIDER  | Provider de IA (gemini / anthropic)| gemini                    |
| GEMINI_API_KEY     | Chave de API do Google Gemini      | (obrigatorio se gemini)   |
| GEMINI_MODEL       | Modelo do Gemini a ser usado       | gemini-2.5-flash          |
| SENTINEL_HOST      | Host do servidor Flask             | 127.0.0.1                 |
| SENTINEL_PORT      | Porta do servidor Flask            | 5000                      |

Para usar Anthropic como provider alternativo:

| Variavel           | Descricao                          | Valor padrao              |
| ------------------ | ---------------------------------- | ------------------------- |
| SENTINEL_PROVIDER  | Definir como `anthropic`           | gemini                    |
| ANTHROPIC_API_KEY  | Chave de API da Anthropic          | (obrigatorio se anthropic)|
| SENTINEL_MODEL     | Modelo do Claude a ser usado       | claude-sonnet-4-20250514  |

Protecoes:

- `.env` fica apenas na maquina local;
- `.env` esta no `.gitignore` — nao vai para o GitHub;
- A chave nao aparece no frontend nem nos logs.

---

## Endpoints

| Metodo | Endpoint    | Descricao                          |
| ------ | ----------- | ---------------------------------- |
| GET    | /           | Dashboard (servido pelo Flask)     |
| GET    | /health     | Health check do backend            |
| POST   | /api/chat   | Envia mensagem ao Sentinel AI      |

---

## Principais arquivos

| Arquivo                    | Descricao                                              |
| -------------------------- | ------------------------------------------------------ |
| `interface/index.html`     | Dashboard visual interativo e chat Sentinel AI         |
| `src/sentinel_ai.py`       | Backend Flask, health check, proxy Gemini, serve dashboard |
| `.env.example`             | Modelo de configuracao (sem chave real)                |
| `start_presentation.ps1`   | Inicio rapido no Windows                               |
| `start_presentation.sh`    | Inicio rapido no Linux/macOS                           |
| `run_local.ps1`            | Setup local no Windows                                 |
| `run_local.sh`             | Setup local no Linux/macOS                             |
| `README_DEPLOY.md`         | Guia de execucao com Python                            |
| `docs/SENTINEL_AI.md`      | Documentacao tecnica do assistente                     |

---

## Seguranca da chave API

- Nunca commitar o `.env`;
- Nunca colocar chave real no codigo-fonte;
- Nunca colocar chave no frontend;
- Usar `.env` local para configuracao.

---

## Como o Sentinel AI funciona

O Sentinel AI e o assistente de chat integrado ao dashboard. Ele recebe:

1. **System prompt tecnico** — define o papel, regras e restricoes do assistente;
2. **Snapshot do dashboard** — estado atual da interface em JSON (ciclos, estatisticas, transacoes);
3. **Catalogo da interface** — lista de todos os componentes visuais com nomes, aliases e legendas de cores;
4. **Dados dos graficos** — distribuicao por valor, distribuicao por step temporal, top contas por risco;
5. **Aliases para erros de digitacao** — permite reconhecer variantes como "distruicao", "distruicao de valores", etc.

O modo de linguagem (leiga/tecnica) e selecionado pelo usuario no chat e persiste via `localStorage`.

A IA **nao decide fraude sozinha** — a decisao final cabe sempre ao analista humano.

Para detalhes tecnicos, consulte [docs/SENTINEL_AI.md](docs/SENTINEL_AI.md).
