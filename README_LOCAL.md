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

- Verifica se o Docker esta instalado e rodando;
- Cria `.env` a partir de `.env.example` se nao existir;
- Valida se a `GEMINI_API_KEY` esta configurada (rejeita placeholders);
- Inicia o sistema com `docker compose up --build`;
- Nao exibe a chave no terminal.

---

## Como rodar localmente no Windows

1. Copiar `.env.example` para `.env`:

```powershell
Copy-Item .env.example .env
```

2. Abrir o `.env` e inserir sua chave do Gemini:

```powershell
notepad .env
```

3. Rodar o script de setup:

```powershell
.\run_local.ps1
```

4. Abrir o dashboard no navegador:

```
interface/index.html
```

---

## Como rodar localmente no Linux/macOS

```bash
cp .env.example .env
nano .env
chmod +x run_local.sh
./run_local.sh
```

Depois abrir no navegador:

```
interface/index.html
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
SENTINEL_HOST=0.0.0.0
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
- `.env` esta no `.dockerignore` — nao entra na imagem Docker;
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
| `Dockerfile`               | Imagem Docker da aplicacao                             |
| `docker-compose.yml`       | Execucao do container com env_file                     |
| `.env.example`             | Modelo de configuracao (sem chave real)                |
| `start_presentation.ps1`   | Inicio rapido no Windows                               |
| `start_presentation.sh`    | Inicio rapido no Linux/macOS                           |
| `README_DEPLOY.md`         | Guia de deploy com Docker                              |
| `docs/SENTINEL_AI.md`      | Documentacao tecnica do assistente                     |

---

## Rodando com Docker

### Pre-requisitos

- Docker Desktop ou Docker Engine
- Internet
- Chave do Google Gemini

### Passo a passo

```bash
git clone https://github.com/1s4ntos/Sistema-de-Detec-o-de-Fraudes-em-Transa-es-Financeiras.git
cd Sistema-de-Detec-o-de-Fraudes-em-Transa-es-Financeiras
cp .env.example .env
```

Editar `.env` e preencher:

```env
GEMINI_API_KEY=sua_chave_real_aqui
```

Rodar:

```bash
docker compose up --build
```

Acessar:

```
http://127.0.0.1:5000/
```

Health check:

```
http://127.0.0.1:5000/health
```

Parar:

```bash
docker compose down
```

Ver logs:

```bash
docker compose logs -f
```

Para mais detalhes, consulte [README_DEPLOY.md](README_DEPLOY.md).

---

## Seguranca da chave API

- Nunca commitar o `.env`;
- Nunca colocar chave real no codigo-fonte;
- Nunca colocar chave no Dockerfile;
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
