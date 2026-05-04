#!/usr/bin/env bash
# Script de push para o GitHub (bash / Git Bash no Windows)
# Execute na pasta raiz do projeto:
#   bash push_to_github.sh
set -euo pipefail

echo "=== Verificando estado do repositorio ==="
git status

echo ""
echo "=== Commits a serem enviados ==="
git log --oneline

echo ""
echo "=== Remote configurado ==="
git remote -v

echo ""
echo "=== Iniciando push para o GitHub ==="
git push -u origin main

echo ""
echo "Push concluido com sucesso!"
echo "Acesse: https://github.com/1s4ntos/Sistema-de-Detec-o-de-Fraudes-em-Transa-es-Financeiras"
