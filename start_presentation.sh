#!/usr/bin/env bash
# start_presentation.sh - Inicio rapido para apresentacao
# Uso: chmod +x start_presentation.sh && ./start_presentation.sh

set -e
cd "$(dirname "$0")"

echo ""
echo "======================================================="
echo "  Sentinel AI - Modo Apresentacao"
echo "======================================================="
echo ""

# 1. Verificar Docker instalado
if ! command -v docker &>/dev/null; then
    echo "[ERRO] Docker nao esta instalado."
    echo ""
    echo "Instale o Docker Desktop em:"
    echo "  https://www.docker.com/products/docker-desktop/"
    echo ""
    echo "Depois rode este script novamente."
    exit 1
fi

# 2. Verificar Docker rodando
if ! docker info &>/dev/null; then
    echo "[ERRO] Docker esta instalado mas nao esta rodando."
    echo ""
    echo "Abra o Docker Desktop e aguarde ele iniciar."
    echo "Depois rode este script novamente."
    exit 1
fi

echo "[OK] Docker esta rodando."

# 3. Verificar/criar .env
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

# 4. Validar GEMINI_API_KEY
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

echo "[OK] Chave Gemini detectada localmente."
echo ""
echo "Iniciando Sentinel AI..."
echo ""
echo "Acesse: http://127.0.0.1:5000/"
echo ""

# 5. Subir Docker
docker compose up --build
