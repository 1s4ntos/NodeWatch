# start_presentation.ps1 - Inicio rapido para apresentacao
# Uso: .\start_presentation.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  Sentinel AI - Modo Apresentacao" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Verificar Docker instalado (PATH padrao ou instalacao do Docker Desktop)
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    $localBin = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin"
    if (Test-Path (Join-Path $localBin "docker.exe")) {
        $env:PATH = "$env:PATH;$localBin"
    } else {
        Write-Host "[ERRO] Docker nao esta instalado." -ForegroundColor Red
        Write-Host ""
        Write-Host "Instale o Docker Desktop em:" -ForegroundColor Yellow
        Write-Host "  https://www.docker.com/products/docker-desktop/" -ForegroundColor White
        Write-Host ""
        Write-Host "Depois rode este script novamente." -ForegroundColor Yellow
        exit 1
    }
}

# 2. Verificar Docker rodando
$dockerInfo = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERRO] Docker esta instalado mas nao esta rodando." -ForegroundColor Red
    Write-Host ""
    Write-Host "Abra o Docker Desktop e aguarde ele iniciar." -ForegroundColor Yellow
    Write-Host "Depois rode este script novamente." -ForegroundColor Yellow
    exit 1
}

Write-Host "[OK] Docker esta rodando." -ForegroundColor Green

# 3. Verificar/criar .env
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

# 4. Validar GEMINI_API_KEY
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

Write-Host "[OK] Chave Gemini detectada localmente." -ForegroundColor Green
Write-Host ""
Write-Host "Iniciando Sentinel AI..." -ForegroundColor Cyan
Write-Host ""

# 5. Subir Docker
Set-Location $PSScriptRoot
docker compose up --build

Write-Host ""
Write-Host "Para parar: Ctrl+C ou: docker compose down" -ForegroundColor Yellow
