# run_local.ps1 - Inicializa o ambiente local do Sentinel AI (Windows PowerShell)

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  Sentinel AI - Setup do ambiente local" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Verificar / criar .venv
if (-Not (Test-Path ".venv")) {
    Write-Host "[1/4] Criando ambiente virtual (.venv)..." -ForegroundColor Yellow
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERRO] Falha ao criar .venv. Verifique se o Python 3.11+ esta instalado." -ForegroundColor Red
        exit 1
    }
    Write-Host "       .venv criado com sucesso." -ForegroundColor Green
} else {
    Write-Host "[1/4] .venv ja existe." -ForegroundColor Green
}

# 2. Ativar o ambiente virtual
Write-Host "[2/4] Ativando ambiente virtual..." -ForegroundColor Yellow
& ".venv\Scripts\Activate.ps1"

# 3. Instalar dependencias
Write-Host "[3/4] Instalando dependencias..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERRO] Falha ao instalar dependencias." -ForegroundColor Red
    exit 1
}
Write-Host "       Dependencias instaladas." -ForegroundColor Green

# 4. Verificar .env
if (-Not (Test-Path ".env")) {
    Write-Host "" -ForegroundColor Yellow
    Write-Host "[AVISO] Arquivo .env nao encontrado!" -ForegroundColor Red
    Write-Host "        Copie o arquivo de exemplo e insira sua chave:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "        Copy-Item .env.example .env" -ForegroundColor White
    Write-Host "        notepad .env" -ForegroundColor White
    Write-Host ""
    Write-Host "        Substitua 'coloque_sua_chave_gemini_aqui' pela sua GEMINI_API_KEY." -ForegroundColor Yellow
    Write-Host ""
    exit 1
} else {
    Write-Host "[4/4] .env encontrado." -ForegroundColor Green
}

# 5. Iniciar o backend
Write-Host ""
Write-Host "-------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "  Iniciando Sentinel AI backend..." -ForegroundColor Cyan
Write-Host "  Health check: http://127.0.0.1:5000/health" -ForegroundColor DarkGray
Write-Host "  Dashboard:    http://127.0.0.1:5000/" -ForegroundColor DarkGray
Write-Host "-------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""

python src/sentinel_ai.py
