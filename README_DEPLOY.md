# Execucao com Python

Guia para rodar o Sentinel AI localmente com Python.

## Pre-requisitos

- Git
- Python 3.11+
- Internet (para chamadas a API do Gemini)
- Chave do Google Gemini ([aistudio.google.com/apikey](https://aistudio.google.com/apikey))

---

## Passo a passo (Windows)

```powershell
git clone https://github.com/1s4ntos/NodeWatch.git
cd NodeWatch
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python src/sentinel_ai.py
```

## Passo a passo (Linux/macOS)

```bash
git clone https://github.com/1s4ntos/NodeWatch.git
cd NodeWatch
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python src/sentinel_ai.py
```

Editar `.env` e preencher a chave:

```env
GEMINI_API_KEY=sua_chave_real_aqui
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

## Modo apresentacao

Para apresentacoes academicas, use os scripts de inicio rapido.

### Windows

Configure a chave uma unica vez no arquivo `.env`. Depois rode:

```powershell
.\start_presentation.ps1
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

- O script verifica se Python esta instalado;
- Cria `.venv` se nao existir;
- Instala dependencias;
- Cria `.env` a partir de `.env.example` se nao existir;
- Abre o editor para voce preencher a `GEMINI_API_KEY`;
- Valida se a chave foi preenchida (rejeita placeholders);
- Inicia o backend com `python src/sentinel_ai.py`;
- `.env` fica apenas na maquina local e nao e enviado ao GitHub;
- Depois de configurado uma vez, o sistema inicia rapido;
- Para parar: `Ctrl+C`

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

| Variavel          | Descricao                    | Valor padrao     |
| ----------------- | ---------------------------- | ---------------- |
| SENTINEL_PROVIDER | Provider de IA               | gemini           |
| GEMINI_API_KEY    | Chave do Google Gemini       | (obrigatorio)    |
| GEMINI_MODEL      | Modelo do Gemini             | gemini-2.5-flash |
| SENTINEL_HOST     | Host do servidor             | 127.0.0.1        |
| SENTINEL_PORT     | Porta do servidor            | 5000             |

Protecoes:

- `.env` fica apenas na maquina local;
- `.env` esta no `.gitignore` — nao vai para o GitHub;
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
| `.env.example`             | Modelo de configuracao (sem chave real)                |
| `start_presentation.ps1`   | Inicio rapido no Windows                               |
| `start_presentation.sh`    | Inicio rapido no Linux/macOS                           |
| `run_local.ps1`            | Setup local no Windows                                 |
| `run_local.sh`             | Setup local no Linux/macOS                             |
| `src/algoritmos/scc.py`    | Componentes Fortemente Conectados (Kosaraju)           |
| `src/algoritmos/centralidade.py` | Centralidade de grau e score de risco            |
| `src/leitura/exportador.py` | Exportacao de analises em JSON                        |

---

## Resolucao de problemas

### Porta 5000 ocupada

```bash
# Ver o que esta usando a porta
# Linux/macOS:
lsof -i :5000
# Windows:
netstat -ano | findstr :5000

# Ou mude a porta no .env:
SENTINEL_PORT=5001
```

### Erro de API key

Se o chat retornar erro sobre chave nao configurada, verifique:

1. O arquivo `.env` existe na raiz do projeto
2. `GEMINI_API_KEY` esta preenchida com uma chave valida (nao pode ser placeholder)
3. Reinicie o backend: `Ctrl+C` e `python src/sentinel_ai.py`

### Confirmar que .env nao foi commitado

```bash
git status
```

O arquivo `.env` nao deve aparecer na lista. Ele esta protegido pelo `.gitignore`.

### Erro ao criar .venv

Certifique-se de que o Python 3.11+ esta instalado:

```bash
python --version
```

No Linux/macOS pode ser necessario instalar o pacote `python3-venv`:

```bash
sudo apt install python3-venv
```

---

## Seguranca da chave API

- Nunca commitar o `.env`;
- Nunca colocar chave real no codigo-fonte;
- Nunca colocar chave no frontend;
- Usar `.env` local para configuracao;
- O endpoint `/health` informa se a chave esta configurada, mas nao a expoe.

---

## Validacao

O projeto foi validado com:

- Backend Flask iniciando com `python src/sentinel_ai.py`;
- `/health` retornando `{"status": "ok", "apiKeyConfigured": true}`;
- Dashboard servido via Flask na rota `/`;
- Sentinel AI respondendo perguntas no chat;
- `.env` fora do controle de versao (`git status` limpo);
- SCC, centralidade e exportacao JSON funcionando via CLI e dashboard;
