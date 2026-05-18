#!/usr/bin/env bash
# start_presentation.sh - Inicio rapido para apresentacao (Python local)
# Uso: chmod +x start_presentation.sh && ./start_presentation.sh

set -e
cd "$(dirname "$0")"

echo ""
echo "======================================================="
echo "  Sentinel AI - Modo Apresentacao"
echo "======================================================="
echo ""

# 1. Verificar Python instalado
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "[ERRO] Python nao esta instalado."
    echo ""
    echo "Instale o Python 3.11+:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv"
    echo "  macOS:         brew install python"
    echo ""
    echo "Depois rode este script novamente."
    exit 1
fi

PY_VERSION=$($PYTHON --version 2>&1)
echo "[OK] $PY_VERSION detectado."

# 2. Verificar / criar .venv
if [ ! -d ".venv" ]; then
    echo "[...] Criando ambiente virtual (.venv)..."
    $PYTHON -m venv .venv
    echo "[OK] .venv criado."
else
    echo "[OK] .venv ja existe."
fi

# 3. Ativar .venv
source .venv/bin/activate

# 4. Instalar dependencias
echo "[...] Instalando dependencias..."
pip install -r requirements.txt --quiet
echo "[OK] Dependencias instaladas."

# 5. Verificar/criar .env
if [ ! -f .env ]; then
    echo ""
    echo "Arquivo .env nao encontrado. Criando a partir de .env.example..."
    cp .env.example .env
    echo ""
    echo "Edite o arquivo .env e preencha sua GEMINI_API_KEY."
    echo ""
    if command -v nano &>/dev/null; then
        nano .env
    elif command -v vi &>/dev/null; then
        vi .env
    else
        echo "Abra .env com seu editor preferido, preencha a chave e rode novamente."
        exit 1
    fi
fi

# 6. Validar GEMINI_API_KEY
KEY=$(grep -E '^GEMINI_API_KEY=' .env | cut -d'=' -f2- | tr -d '[:space:]')

case "$KEY" in
    ""|"coloque_sua_chave_gemini_aqui"|"sua_chave_google"|"sua_chave_aqui")
        echo ""
        echo "[ERRO] GEMINI_API_KEY nao esta preenchida no .env."
        echo ""
        echo "Abra o arquivo .env e substitua o valor de GEMINI_API_KEY pela sua chave do Google Gemini."
        echo ""
        echo "Para obter uma chave:"
        echo "  https://aistudio.google.com/apikey"
        echo ""
        echo "Depois rode este script novamente."
        exit 1
        ;;
esac

echo "[OK] Chave Gemini detectada."
echo ""
echo "Iniciando Sentinel AI..."
echo ""
echo "  Acesse: http://127.0.0.1:5000/"
echo ""

# 7. Iniciar o backend
python src/sentinel_ai.py
