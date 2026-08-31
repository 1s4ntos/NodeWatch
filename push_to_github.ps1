# Script de push para o GitHub (Windows PowerShell)
# Execute este script na pasta raiz do projeto, com:
#   .\push_to_github.ps1
#
# Pré-requisitos:
#   - Git instalado (https://git-scm.com/)
#   - Você precisa estar autenticado no GitHub (token PAT, GitHub CLI, ou SSH)
#   - O repositório https://github.com/1s4ntos/NodeWatch
#     já deve existir (vazio) na sua conta GitHub.

$ErrorActionPreference = "Stop"

Write-Host "=== Verificando estado do repositorio ===" -ForegroundColor Cyan
git status

Write-Host "`n=== Commits a serem enviados ===" -ForegroundColor Cyan
git log --oneline

Write-Host "`n=== Remote configurado ===" -ForegroundColor Cyan
git remote -v

Write-Host "`n=== Iniciando push para o GitHub ===" -ForegroundColor Yellow
git push -u origin main

Write-Host "`nPush concluido com sucesso!" -ForegroundColor Green
Write-Host "Acesse: https://github.com/1s4ntos/NodeWatch" -ForegroundColor Green
