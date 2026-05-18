# start_presentation.ps1 - Inicio rapido para apresentacao (Python local)
# Uso: .\start_presentation.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  Sentinel AI - Modo Apresentacao" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

Set-Location $PSScriptRoot

# 1. Verificar Python instalado
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "[ERRO] Python nao esta instalado ou nao esta no PATH." -ForegroundColor Red
    Write-Host ""
    Write-Host "Instale o Python 3.11+ em:" -ForegroundColor Yellow
    Write-Host "  https://www.python.org/downloads/" -ForegroundColor White
    Write-Host ""
    Write-Host "Marque 'Add Python to PATH' durante a instalacao." -ForegroundColor Yellow
    exit 1
}

$pyVersion = python --version 2>&1
Write-Host "[OK] $pyVersion detectado." -ForegroundColor Green

# 2. Verificar / criar .venv
if (-not (Test-Path ".venv")) {
    Write-Host "[...] Criando ambiente virtual (.venv)..." -ForegroundColor Yellow
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERRO] Falha ao criar .venv." -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] .venv criado." -ForegroundColor Green
} else {
    Write-Host "[OK] .venv ja existe." -ForegroundColor Green
}

# 3. Ativar .venv
& ".venv\Scripts\Activate.ps1"

# 4. Instalar dependencias
Write-Host "[...] Instalando dependencias..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERRO] Falha ao instalar dependencias." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Dependencias instaladas." -ForegroundColor Green

# 5. Verificar/criar .env
$envFile = Join-Path $PSScriptRoot ".env"
$envExample = Join-Path $PSScriptRoot ".env.example"

if (-not (Test-Path $envFile)) {
    Write-Host ""
    Write-Host "Arquivo .env nao encontrado. Criando a partir de .env.example..." -ForegroundColor Yellow
    Copy-Item $envExample $envFile
    Write-Host ""
    Write-Host "Cole sua GEMINI_API_KEY no .env, salve e feche o Notepad." -ForegroundColor Yellow
    Write-Host ""
    Start-Process notepad.exe $envFile -Wait
}

# 6. Validar GEMINI_API_KEY
$envContent = Get-Content $envFile -Raw
$match = [regex]::Match($envContent, 'GEMINI_API_KEY=(.+)')
$key = ""
if ($match.Success) {
    $key = $match.Groups[1].Value.Trim()
}

$placeholders = @("coloque_sua_chave_gemini_aqui", "sua_chave_google", "sua_chave_aqui", "")

if ($placeholders -contains $key) {
    Write-Host ""
    Write-Host "[ERRO] GEMINI_API_KEY nao esta preenchida no .env." -ForegroundColor Red
    Write-Host ""
    Write-Host "Abra o arquivo .env e substitua o valor de GEMINI_API_KEY pela sua chave do Google Gemini." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Para obter uma chave:" -ForegroundColor White
    Write-Host "  https://aistudio.google.com/apikey" -ForegroundColor White
    Write-Host ""
    Write-Host "Depois rode este script novamente." -ForegroundColor Yellow
    exit 1
}

Write-Host "[OK] Chave Gemini detectada." -ForegroundColor Green
Write-Host ""
Write-Host "Iniciando Sentinel AI..." -ForegroundColor Cyan
Write-Host ""
Write-Host "  Acesse: http://127.0.0.1:5000/" -ForegroundColor White
Write-Host ""

# 7. Iniciar o backend
python src/sentinel_ai.py
