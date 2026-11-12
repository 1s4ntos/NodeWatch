@echo off
setlocal
rem Abre o site de apresentacao do NodeWatch (site\index.html) no navegador padrao.
rem So visualiza o site: nao inicia o aplicativo, nao abre o painel e nao pede token nem modelo.
rem O site e estatico e funciona aberto como arquivo local, sem servidor.
rem O caminho e relativo a esta pasta (%~dp0), entao espacos e acentos nao atrapalham.

set "SITE=%~dp0..\site\index.html"
rem Resolve o ".." para mostrar um caminho limpo.
for %%I in ("%SITE%") do set "SITE=%%~fI"

if not exist "%SITE%" (
    echo.
    echo [ERRO] Site de apresentacao nao encontrado.
    echo.
    echo Procurado em:
    echo   "%SITE%"
    echo.
    echo Extraia o repositorio completo do NodeWatch mantendo, lado a lado na pasta
    echo principal do projeto, a pasta "site" e esta pasta do inicializador.
    echo Depois rode este arquivo de novo.
    echo.
    pause
    exit /b 1
)

echo Abrindo o site de apresentacao no navegador padrao:
echo   "%SITE%"
start "" "%SITE%"
endlocal
exit /b 0
