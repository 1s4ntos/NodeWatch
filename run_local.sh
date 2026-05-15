#!/usr/bin/env bash
# run_local.sh — Inicializa o ambiente local do Sentinel AI (Linux / macOS)

set -e

echo "======================================================="
echo "  Sentinel AI — Setup do ambiente local"
echo "======================================================="
echo ""

# 1. Verificar / criar .venv
if [ ! -d ".venv" ]; then
    echo "[1/4] Criando ambiente virtual (.venv)..."
    python3 -m venv .venv
    echo "       .venv criado com sucesso."
else
    echo "[1/4] .venv ja existe."
fi

# 2. Ativar o ambiente virtual
echo "[2/4] Ativando ambiente virtual..."
source .venv/bin/activate

# 3. Instalar dependencias
echo "[3/4] Instalando dependencias..."
pip install -r requirements.txt --quiet
echo "       Dependencias instaladas."

# 4. Verificar .env
if [ ! -f ".env" ]; then
    echo ""
    echo "[AVISO] Arquivo .env nao encontrado!"
    echo "        Copie o arquivo de exemplo e insira sua chave:"
    echo ""
    echo "        cp .env.example .env"
    echo "        nano .env"
    echo ""
    echo "        Substitua 'coloque_sua_chave_aqui' pela sua ANTHROPIC_API_KEY."
    echo ""
    exit 1
else
    echo "[4/4] .env encontrado."
fi

# 5. Iniciar o backend
echo ""
echo "-------------------------------------------------------"
echo "  Iniciando Sentinel AI backend..."
echo "  Health check: http://127.0.0.1:5000/health"
echo "  Dashboard:    abra interface/index.html no navegador"
echo "-------------------------------------------------------"
echo ""

python src/sentinel_ai.py
