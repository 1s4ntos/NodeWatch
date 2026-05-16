# Deploy com Docker

Guia para rodar o Sentinel AI em qualquer maquina com Docker e internet.

## Pre-requisitos

- Git
- Docker Desktop ou Docker Engine
- Internet (para build e chamadas a API do Gemini)
- Chave do Google Gemini ([aistudio.google.com](https://aistudio.google.com/apikey))

---

## Passo a passo

```bash
git clone https://github.com/SEU_USUARIO/Sistema-de-Detec-o-de-Fraudes-em-Transa-es-Financeiras.git
cd Sistema-de-Detec-o-de-Fraudes-em-Transa-es-Financeiras
cp .env.example .env
```

Editar `.env` e preencher a chave:

```env
GEMINI_API_KEY=sua_chave_google
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

## Configuracao do .env

| Variavel | Descricao | Valor padrao |
|---|---|---|
| SENTINEL_PROVIDER | Provider de IA | gemini |
| GEMINI_API_KEY | Chave do Google Gemini | (obrigatorio) |
| GEMINI_MODEL | Modelo do Gemini | gemini-2.5-flash |
| SENTINEL_HOST | Host do servidor | 0.0.0.0 |
| SENTINEL_PORT | Porta do servidor | 5000 |

Para trocar o modelo Gemini, altere `GEMINI_MODEL` no `.env`:

```env
GEMINI_MODEL=gemini-2.0-flash
```

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
2. `GEMINI_API_KEY` esta preenchida com uma chave valida
3. Reinicie o container: `docker compose down && docker compose up`

### Confirmar que .env nao foi commitado

```bash
git status
```

O arquivo `.env` nao deve aparecer na lista. Ele esta protegido pelo `.gitignore`.

---

## Seguranca

- `.env` contem a API key e **nunca deve ser commitado**
- O Dockerfile nao copia `.env` para a imagem
- A chave e injetada em tempo de execucao via `env_file` no docker-compose
- O frontend nao armazena nem expoe a chave
- O endpoint `/health` informa se a chave esta configurada, mas nao a expoe

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
- Valida se a chave foi preenchida;
- Inicia o sistema com `docker compose up --build`;
- `.env` fica apenas na maquina local e nao e enviado ao GitHub;
- Depois de configurado uma vez, o sistema inicia rapido;
- Para parar: `Ctrl+C` ou `docker compose down`
