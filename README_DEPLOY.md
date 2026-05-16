# Deploy com Docker

Guia para rodar o Sentinel AI em qualquer maquina com Docker e internet.

## Pre-requisitos

- Git
- Docker Desktop ou Docker Engine
- Internet (para build e chamadas a API do Gemini)
- Chave do Google Gemini ([aistudio.google.com/apikey](https://aistudio.google.com/apikey))

---

## Passo a passo

```bash
git clone https://github.com/1s4ntos/Sistema-de-Detec-o-de-Fraudes-em-Transa-es-Financeiras.git
cd Sistema-de-Detec-o-de-Fraudes-em-Transa-es-Financeiras
cp .env.example .env
```

Editar `.env` e preencher a chave:

```env
GEMINI_API_KEY=sua_chave_real_aqui
```

Rodar:

```bash
docker compose up --build
```

Acessar o dashboard:

```
http://127.0.0.1:5000/
```

Health check:

```
http://127.0.0.1:5000/health
```

---

## Comandos uteis

Parar o container:

```bash
docker compose down
```

Ver logs em tempo real:

```bash
docker compose logs -f
```

Rebuild apos alteracoes no codigo:

```bash
docker compose up --build
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

| Variavel          | Descricao                    | Valor padrao     |
| ----------------- | ---------------------------- | ---------------- |
| SENTINEL_PROVIDER | Provider de IA               | gemini           |
| GEMINI_API_KEY    | Chave do Google Gemini       | (obrigatorio)    |
| GEMINI_MODEL      | Modelo do Gemini             | gemini-2.5-flash |
| SENTINEL_HOST     | Host do servidor             | 0.0.0.0          |
| SENTINEL_PORT     | Porta do servidor            | 5000             |

Protecoes:

- `.env` fica apenas na maquina local;
- `.env` esta no `.gitignore` — nao vai para o GitHub;
- `.env` esta no `.dockerignore` — nao entra na imagem Docker;
- A chave nao aparece no frontend nem nos logs.

Para trocar o modelo Gemini, altere `GEMINI_MODEL` no `.env`:

```env
GEMINI_MODEL=gemini-2.0-flash
```

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

---

## Resolucao de problemas

### Porta 5000 ocupada

```bash
# Ver o que esta usando a porta
# Linux/macOS:
lsof -i :5000
# Windows:
netstat -ano | findstr :5000

# Ou mude a porta no .env e docker-compose.yml
```

### Erro de API key

Se o chat retornar erro sobre chave nao configurada, verifique:

1. O arquivo `.env` existe na raiz do projeto
2. `GEMINI_API_KEY` esta preenchida com uma chave valida (nao pode ser placeholder)
3. Reinicie o container: `docker compose down && docker compose up`

### Confirmar que .env nao foi commitado

```bash
git status
```

O arquivo `.env` nao deve aparecer na lista. Ele esta protegido pelo `.gitignore`.

---

## Seguranca da chave API

- Nunca commitar o `.env`;
- Nunca colocar chave real no codigo-fonte;
- Nunca colocar chave no Dockerfile;
- Nunca colocar chave no frontend;
- Usar `.env` local para configuracao;
- O Dockerfile nao copia `.env` para a imagem;
- A chave e injetada em tempo de execucao via `env_file` no docker-compose;
- O endpoint `/health` informa se a chave esta configurada, mas nao a expoe.

---

## Validacao

O projeto foi validado com:

- Docker build bem-sucedido;
- Container com status healthy;
- `/health` retornando `{"status": "ok", "apiKeyConfigured": true}`;
- Dashboard servido via Flask na rota `/`;
- Sentinel AI respondendo perguntas no chat;
- `.env` fora do controle de versao (`git status` limpo).

---

## Modo apresentacao

Para apresentacoes academicas, use os scripts de inicio rapido.

### Windows

Configure a chave uma unica vez no arquivo `.env`. Depois rode:

```powershell
.\start_presentation.ps1
```

Acesse:

```
http://127.0.0.1:5000/
```

### Linux/macOS

```bash
chmod +x start_presentation.sh
./start_presentation.sh
```

Acesse:

```
http://127.0.0.1:5000/
```

### Como funciona

- O script verifica se Docker esta instalado e rodando;
- Cria `.env` a partir de `.env.example` se nao existir;
- Abre o editor para voce preencher a `GEMINI_API_KEY`;
- Valida se a chave foi preenchida (rejeita placeholders);
- Inicia o sistema com `docker compose up --build`;
- `.env` fica apenas na maquina local e nao e enviado ao GitHub;
- Depois de configurado uma vez, o sistema inicia rapido;
- Para parar: `Ctrl+C` ou `docker compose down`
