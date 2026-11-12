# Iniciar_NodeWatch.ps1 - inicia o NodeWatch no Windows com poucos cliques.
# Uso: clique duas vezes em Iniciar_NodeWatch.bat (ou rode este arquivo no PowerShell).
# Para parar: Ctrl+C nesta janela.

# "Continue": no Windows PowerShell 5.1, com "Stop", qualquer texto que python/pip escrevam na saida de
# erro (avisos, Traceback do teste de importacao) encerraria o script. Os resultados sao conferidos por
# $LASTEXITCODE; erros inesperados caem no trap abaixo, que mantem a janela aberta.
$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
trap {
    Write-Host ""
    Write-Host "[ERRO] Falha inesperada: $_" -ForegroundColor Red
    Write-Host ""; Read-Host "Pressione Enter para fechar" | Out-Null
    exit 1
}
$URL = "http://127.0.0.1:5000/"
$URL_ESTADO = "http://127.0.0.1:5000/api/painel/estado"
# numpy==2.5.4 (requirements-ml.txt) exige Python >= 3.12; os pacotes fixados tem wheels de 3.12 a 3.15.
# O projeto foi testado no Python 3.14.
$PY_MIN = [version]"3.12"
$PY_TESTADO = "3.14"
function Avisar-Versao($v) {
    if ("$($v.Major).$($v.Minor)" -ne $PY_TESTADO) {
        Write-Host "[AVISO] Python $v aceito, mas o projeto foi testado no $PY_TESTADO." -ForegroundColor Yellow
    }
}

function Ok($t)    { Write-Host "[OK] $t" -ForegroundColor Green }
function Info($t)  { Write-Host "[...] $t" -ForegroundColor Yellow }
function Erro($t)  { Write-Host "[ERRO] $t" -ForegroundColor Red }
function Sair($c)  { Write-Host ""; Read-Host "Pressione Enter para fechar" | Out-Null; exit $c }

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  NodeWatch - Inicializador Rapido" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

# 1. Raiz do projeto = pasta pai deste script (confirmada pelos arquivos do NodeWatch)
$raiz = Split-Path -Parent $PSScriptRoot
$servidor = Join-Path $raiz "src\sentinel_ai.py"
$reqBase = Join-Path $raiz "requirements.txt"
$reqMl = Join-Path $raiz "requirements-ml.txt"
if (-not ((Test-Path -LiteralPath $servidor) -and (Test-Path -LiteralPath $reqBase) -and (Test-Path -LiteralPath $reqMl))) {
    Erro "Nao encontrei o NodeWatch na pasta acima deste script:"
    Write-Host "  $raiz"
    Write-Host "Mantenha a pasta 'Inicializador Rapido' dentro da pasta principal do repositorio."
    Sair 1
}
Ok "Projeto encontrado em: $raiz"

# 2. Porta 5000: reaproveita o NodeWatch se ja estiver rodando
function Testar-NodeWatch {
    try {
        $r = Invoke-WebRequest -Uri $URL_ESTADO -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -eq 200 -and $r.Content -match "NodeWatch")
    } catch { return $false }
}
function Porta-Ocupada {
    $c = New-Object System.Net.Sockets.TcpClient
    try { $a = $c.BeginConnect("127.0.0.1", 5000, $null, $null); return ($a.AsyncWaitHandle.WaitOne(1000) -and $c.Connected) }
    catch { return $false } finally { $c.Close() }
}
if (Testar-NodeWatch) {
    Ok "O NodeWatch ja esta rodando. Abrindo o painel: $URL"
    Start-Process $URL
    Write-Host "Para encerra-lo, use Ctrl+C na janela onde ele foi iniciado."
    Sair 0
}
if (Porta-Ocupada) {
    Erro "A porta 5000 esta ocupada por outro programa, que nao e o NodeWatch."
    Write-Host "Feche esse programa (nada foi encerrado por este script) e tente de novo."
    Write-Host "Para ver quem usa a porta: netstat -ano | findstr :5000"
    Sair 1
}

# 3. Python compativel (sem instalar nada)
function Versao-Python($exe, $args0) {
    try {
        $v = & $exe @args0 -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) { return [version]($v | Select-Object -Last 1).Trim() }
    } catch {}
    return $null
}
$venvPy = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPy)) {
    $pyBase = $null
    foreach ($cand in @(@("py", @("-3")), @("python", @()), @("python3", @()))) {
        if (-not (Get-Command $cand[0] -ErrorAction SilentlyContinue)) { continue }
        $v = Versao-Python $cand[0] $cand[1]
        if ($v -and $v -ge $PY_MIN) { $pyBase = $cand; Ok "Python $v encontrado."; Avisar-Versao $v; break }
    }
    if (-not $pyBase) {
        Erro "Nao encontrei Python $PY_MIN ou mais novo."
        Write-Host "Instale o Python 3.14 (versao testada no projeto; o minimo e 3.12) em:"
        Write-Host "  https://www.python.org/downloads/windows/"
        Write-Host "Marque 'Add python.exe to PATH' na instalacao e rode este inicializador de novo."
        Sair 1
    }
    # 4. Cria o .venv (somente se nao existir; nunca apaga um existente)
    Info "Criando o ambiente virtual .venv (so na primeira vez)..."
    Push-Location -LiteralPath $raiz
    try { & $pyBase[0] @($pyBase[1]) -m venv .venv } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPy)) { Erro "Falha ao criar o .venv."; Sair 1 }
    Ok ".venv criado."
} else {
    $v = Versao-Python $venvPy @()
    if (-not $v) { Erro "O .venv existente parece corrompido ($venvPy). Nada foi apagado; renomeie a pasta .venv e rode de novo."; Sair 1 }
    if ($v -lt $PY_MIN) { Erro "O .venv existente usa Python $v; o NodeWatch precisa de $PY_MIN+. Renomeie a pasta .venv e rode de novo."; Sair 1 }
    Ok ".venv existente (Python $v)."; Avisar-Versao $v
}

# 5. Dependencias, so pelos manifestos do projeto e dentro do .venv
& $venvPy -c "import flask, flask_cors, dotenv, numpy, pandas, sklearn, scipy, joblib, pyarrow" 2>$null
if ($LASTEXITCODE -ne 0) {
    Info "Instalando dependencias no .venv (primeiro uso: precisa de internet, pode levar alguns minutos)..."
    & $venvPy -m pip install --disable-pip-version-check -r $reqBase -r $reqMl
    if ($LASTEXITCODE -ne 0) {
        Erro "A instalacao das dependencias falhou."
        Write-Host "  - Confira a conexao com a internet (ou proxy/firewall) e rode de novo."
        Write-Host "  - Se o erro citar 'Long Path' ou 'No such file or directory', a pasta do projeto esta num caminho"
        Write-Host "    longo demais para o Windows (limite de 260 caracteres): mova o projeto para uma pasta curta,"
        Write-Host "    por exemplo C:\NodeWatch, e rode de novo. A instalacao parcial no .venv e aproveitada."
        Write-Host "  - Se o erro citar versoes indisponiveis, use o Python 3.14 (versao em que o requirements-ml.txt foi fixado e testado)."
        Write-Host "  - Comando manual, na pasta do projeto: .venv\Scripts\python -m pip install -r requirements.txt -r requirements-ml.txt"
        Sair 1
    }
    Ok "Dependencias instaladas."
} else { Ok "Dependencias ja instaladas." }

# 6. Token do Gemini (opcional; so o chat Sentinel AI da interface antiga precisa dele)
#    Variavel lida por src/sentinel_ai.py: GEMINI_API_KEY, carregada do .env na raiz do projeto.
#    O valor nunca e exibido, registrado ou passado como argumento; nenhuma chamada e feita ao Gemini.
$VAR_TOKEN = "GEMINI_API_KEY"
$envArq = Join-Path $raiz ".env"
$EXEMPLOS = @("", "coloque_sua_chave_gemini_aqui", "sua_chave_google", "sua_chave_aqui")
function Token-Configurado {
    if (Test-Path -LiteralPath $envArq) {
        foreach ($l in [System.IO.File]::ReadAllLines($envArq)) {
            if ($l -match "^\s*(export\s+)?$VAR_TOKEN\s*=\s*(.*)$") {
                $v = $Matches[2].Trim().Trim('"', "'")
                if ($EXEMPLOS -notcontains $v) { return $true }
            }
        }
    }
    return $false
}
function Gravar-Token([string]$valor) {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $linha = "$VAR_TOKEN=$valor"
    if (Test-Path -LiteralPath $envArq) {
        $texto = [System.IO.File]::ReadAllText($envArq)
        $nl = if ($texto -match "`r`n") { "`r`n" } else { "`n" }
        $linhas = New-Object System.Collections.Generic.List[string]
        $linhas.AddRange([string[]]($texto -split "\r?\n"))
        $trocou = $false
        for ($i = 0; $i -lt $linhas.Count; $i++) {
            if (-not $trocou -and $linhas[$i] -match "^\s*(export\s+)?$VAR_TOKEN\s*=") { $linhas[$i] = $linha; $trocou = $true }
        }
        if (-not $trocou) {
            if ($linhas.Count -gt 0 -and $linhas[$linhas.Count - 1] -eq "") { $linhas.Insert($linhas.Count - 1, $linha) }
            else { $linhas.Add($linha) }
        }
        [System.IO.File]::WriteAllText($envArq, ($linhas -join $nl), $utf8)
    } else {
        [System.IO.File]::WriteAllText($envArq, "$linha`r`n", $utf8)
    }
}
if ([Environment]::GetEnvironmentVariable($VAR_TOKEN) -and ($EXEMPLOS -notcontains [Environment]::GetEnvironmentVariable($VAR_TOKEN))) {
    Ok "$VAR_TOKEN ja definido no ambiente do Windows (chat Sentinel AI habilitado)."
} elseif (Token-Configurado) {
    Ok "$VAR_TOKEN ja configurado no .env (chat Sentinel AI habilitado)."
} elseif ([Console]::IsInputRedirected) {
    Write-Host "[AVISO] $VAR_TOKEN nao configurado; o chat Sentinel AI ficara indisponivel." -ForegroundColor Yellow
} else {
    Write-Host ""
    $seguro = Read-Host -AsSecureString "Token do Gemini para habilitar o chat Sentinel AI (opcional). Cole o token ou pressione Enter para continuar sem ele"
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($seguro)
    try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr).Trim() }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr); $seguro.Dispose() }
    if (-not $token) {
        Write-Host "[AVISO] Sem token: o chat Sentinel AI ficara indisponivel ate $VAR_TOKEN ser configurado no .env." -ForegroundColor Yellow
        Write-Host "        O painel do analista funciona normalmente."
    } elseif ($token -notmatch '^[A-Za-z0-9_\-\.]+$') {
        Write-Host "[AVISO] O texto colado tem caracteres inesperados para um token (espacos, aspas ou simbolos)." -ForegroundColor Yellow
        Write-Host "        Nada foi gravado; o chat ficara indisponivel. Rode de novo e cole somente o token."
    } else {
        try {
            Gravar-Token $token
            Ok "Token gravado em .env ($VAR_TOKEN). O valor nao e exibido."
            $ign = & git -C $raiz check-ignore -q -- .env 2>$null; $codigo = $LASTEXITCODE
            if ($codigo -eq 1) { Write-Host "[AVISO] O .env NAO esta ignorado pelo Git neste projeto: nao faca commit dele." -ForegroundColor Yellow }
        } catch {
            Erro "Nao foi possivel gravar o .env (sem permissao ou arquivo em uso). Seguindo sem o token."
        }
    }
    $token = $null
}

# 7. Inicia o servidor pelo comando oficial, na raiz do projeto
Write-Host ""
Write-Host "Iniciando o NodeWatch (python src\sentinel_ai.py)..." -ForegroundColor Cyan
Write-Host "  Painel do analista: $URL"
Write-Host "  Interface antiga:   ${URL}legado"
Write-Host "  Para parar: Ctrl+C nesta janela."
Write-Host ""
$proc = Start-Process -FilePath $venvPy -ArgumentList '"src\sentinel_ai.py"' -WorkingDirectory $raiz -NoNewWindow -PassThru -ErrorAction Stop
try {
    $pronto = $false
    for ($i = 0; $i -lt 180 -and -not $proc.HasExited; $i++) {
        if (Testar-NodeWatch) { $pronto = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if ($pronto) {
        Ok "Painel disponivel. Abrindo o navegador em $URL"
        Start-Process $URL
    } elseif ($proc.HasExited) {
        Erro "O servidor encerrou antes de ficar disponivel (veja as mensagens acima)."
    } else {
        Write-Host "[AVISO] O painel ainda nao respondeu; abra $URL manualmente quando aparecer." -ForegroundColor Yellow
    }
    $proc.WaitForExit()
} finally {
    # Encerra somente o processo iniciado por este script
    if ($proc -and -not $proc.HasExited) {
        Info "Encerrando o servidor iniciado por este inicializador..."
        Stop-Process -Id $proc.Id -ErrorAction SilentlyContinue
    }
    Write-Host "NodeWatch encerrado."
}
