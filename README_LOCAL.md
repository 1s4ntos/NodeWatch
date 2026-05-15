# Como rodar localmente

Guia rapido para executar o Sentinel AI e o dashboard na sua maquina.

## Pre-requisitos

- Python 3.11+
- Chave de API do Google Gemini ([aistudio.google.com](https://aistudio.google.com/apikey))
- Navegador moderno (Chrome, Firefox ou Edge)

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

---

## Estrutura dos endpoints

| Metodo | Endpoint    | Descricao                          |
| ------ | ----------- | ---------------------------------- |
| GET    | /           | Dashboard (servido pelo Flask)     |
| GET    | /health     | Health check do backend            |
| POST   | /api/chat   | Envia mensagem ao Sentinel AI      |

---

## Seguranca

- O arquivo `.env` contem a chave de API e **nao deve ser commitado**.
- `.env` ja esta listado no `.gitignore`.
- O frontend (`interface/index.html`) nao armazena nem expoe a chave de API.
- Erros do backend nao expoem dados sensiveis ao cliente.

---

## Como o Sentinel AI funciona

O Sentinel AI e o assistente de chat integrado ao dashboard. Ele recebe:

1. **System prompt tecnico** — define o papel, regras e restricoes do assistente;
2. **Snapshot do dashboard** — estado atual da interface em JSON (ciclos, estatisticas, transacoes);
3. **Catalogo da interface** — lista de todos os componentes visuais com nomes, aliases e legendas de cores;
4. **Dados dos graficos** — distribuicao por valor, distribuicao por step temporal, top contas por risco;
5. **Aliases para erros de digitacao** — permite reconhecer variantes como "distruicao", "distruicao de valores", etc.

O modo de linguagem (leiga/tecnica) e selecionado pelo usuario no chat e persiste via `localStorage`.

---

## Rodando com Docker

### Pre-requisitos

- Git
- Docker Desktop ou Docker Engine
- Internet
- Chave do Google Gemini

### Passo a passo

```bash
git clone https://github.com/SEU_USUARIO/Sistema-de-Detec-o-de-Fraudes-em-Transa-es-Financeiras.git
cd Sistema-de-Detec-o-de-Fraudes-em-Transa-es-Financeiras
cp .env.example .env
```

Editar `.env` e preencher:

```env
GEMINI_API_KEY=sua_chave_google
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
