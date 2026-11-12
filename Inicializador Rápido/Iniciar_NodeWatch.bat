@echo off
rem Abre o inicializador do NodeWatch por duplo clique, a partir da pasta deste arquivo.
rem O PowerShell abre numa janela propria ("NodeWatch") e este .bat termina em seguida: assim o Ctrl+C
rem encerra o servidor sem a pergunta "Deseja finalizar o arquivo em lotes (S/N)?" do cmd.
rem -ExecutionPolicy Bypass vale so para esta execucao; a politica do sistema nao muda.
start "NodeWatch" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Iniciar_NodeWatch.ps1"
