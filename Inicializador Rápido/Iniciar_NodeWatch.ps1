# Iniciar_NodeWatch.ps1 - inicia o NodeWatch no Windows com poucos cliques.
# Uso: clique duas vezes em Iniciar_NodeWatch.bat (ou rode este arquivo no PowerShell).
# Para parar: Ctrl+C nesta janela.
#
# Sequencia de boot visual: cada etapa mostrada na tela corresponde a uma operacao real deste script
# (projeto e porta, Python/.venv, dependencias, modelo de ML, token do Gemini, servidor). Um [OK] so aparece
# depois que a operacao terminou com sucesso; falhas aparecem em vermelho com a saida tecnica preservada.
# Animacoes: so com console interativo; NODEWATCH_SEM_ANIMACAO=1 (ou saida redirecionada) desliga todas.
# Este arquivo e ASCII puro (o Windows PowerShell 5.1 le .ps1 sem BOM como ANSI): os caracteres graficos
# sao gerados por codigo ([char]0x2588 etc.).

# "Continue": no Windows PowerShell 5.1, com "Stop", qualquer texto que python/pip escrevam na saida de
# erro (avisos, Traceback do teste de importacao) encerraria o script. Os resultados sao conferidos por
# $LASTEXITCODE / ExitCode; erros inesperados caem no trap abaixo, que mantem a janela aberta.
$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
trap {
    Write-Host ""
    Write-Host "    [ERROR]    Falha inesperada: $_" -ForegroundColor Red
    Write-Host ""; Read-Host "Pressione Enter para fechar" | Out-Null
    exit 1
}
$URL = "http://127.0.0.1:5000/"
$URL_ESTADO = "http://127.0.0.1:5000/api/painel/estado"
# numpy==2.5.4 (requirements-ml.txt) exige Python >= 3.12; os pacotes fixados tem wheels de 3.12 a 3.15.
# O projeto foi testado no Python 3.14.
$PY_MIN = [version]"3.12"
$PY_TESTADO = "3.14"

# ---------------------------------------------------------------------------------------------------------
# Visual do terminal, na identidade da marca (sem bibliotecas externas)
#   NODE branco #F5F5F5 | WATCH e simbolo vermelho #FF2B1B | vermelho secundario #E31E24 | cinza #888888
#   fundo preto do console (#0C0C0C no esquema padrao do Windows, o mais proximo de #0A0A0A)
#   Verde so para operacao concluida com sucesso. Cores exatas (24 bits) quando o console interpreta
#   sequencias ANSI; senao, as 16 cores do console (Red, White, Gray, Green...). NODEWATCH_CORES_BASICAS=1
#   forca as 16 cores.
# ---------------------------------------------------------------------------------------------------------
$ANIMAR = $true
try { if ([Console]::IsOutputRedirected) { $ANIMAR = $false } } catch { $ANIMAR = $false }
$INTERATIVO = $ANIMAR
if ($env:NODEWATCH_SEM_ANIMACAO) { $ANIMAR = $false }
$BLOCO = [string][char]0x2588; $VAZIO = [string][char]0x2591; $TRACO = [string][char]0x2500; $DUPLO = [string][char]0x2550
$SETA = [string][char]0x25BA
$ESC = [string][char]27
$TOTAL = 8
$script:pct = 0
# nome = @(R, G, B, cor de reserva do console)
$PALETA = @{
    vermelho  = @(255, 43, 27, 'Red');      vermelho2 = @(227, 30, 36, 'Red')
    branco    = @(245, 245, 245, 'White');  cinza     = @(136, 136, 136, 'Gray')
    escuro    = @(88, 88, 88, 'DarkGray');  verde     = @(46, 204, 113, 'Green')
    amarelo   = @(255, 193, 7, 'Yellow')
}
if ($INTERATIVO) { try { $Host.UI.RawUI.BackgroundColor = 'Black'; Clear-Host } catch {} }
# Teste real: se o console interpreta ESC[0m, o cursor nao anda; se nao interpreta, apaga o lixo e usa 16 cores
$VT = $false
if ($INTERATIVO -and -not $env:NODEWATCH_CORES_BASICAS) {
    try {
        $x0 = [Console]::CursorLeft; [Console]::Write($ESC + "[0m")
        if ([Console]::CursorLeft -eq $x0) { $VT = $true } else { [Console]::Write("`r        `r") }
    } catch {}
}
function W([string]$t, $cor = 'branco', [switch]$N, [switch]$Negrito) {
    $p = $PALETA[$cor]
    if ($VT) {
        $pre = $ESC + '['; if ($Negrito) { $pre += '1;' }
        Write-Host ($pre + '38;2;' + $p[0] + ';' + $p[1] + ';' + $p[2] + 'm' + $t + $ESC + '[0m') -NoNewline:$N
    } else { Write-Host $t -ForegroundColor $p[3] -NoNewline:$N }
}
# Texto com trechos coloridos: "{b}NODE{v}WATCH" (b branco, v vermelho, g verde, a amarelo, c cinza)
$MARCAS = @{ b = 'branco'; v = 'vermelho'; g = 'verde'; a = 'amarelo'; c = 'cinza' }
function Sem-Marcas($s) { $s -replace '\{[bvgac]\}', '' }
function W-Marcado($s, [switch]$N) {
    $cor = 'branco'
    foreach ($parte in ($s -split '(\{[bvgac]\})')) {
        if ($parte -match '^\{([bvgac])\}$') { $cor = $MARCAS[$Matches[1]] } elseif ($parte) { W $parte $cor -N }
    }
    if (-not $N) { Write-Host "" }
}

function Titulo($t) { try { $Host.UI.RawUI.WindowTitle = $t } catch {} }
function Pausa($ms) { if ($ANIMAR) { Start-Sleep -Milliseconds $ms } }
function Limpar-Linha {
    if (-not $ANIMAR) { return }
    $w = 100; try { $w = [Console]::WindowWidth - 1 } catch {}
    Write-Host ("`r" + (" " * $w) + "`r") -NoNewline
}
# Texto aparecendo progressivamente (alguns caracteres por quadro). Toda a animacao soma menos de 1 s:
# o Windows arredonda pausas curtas para ~15 ms, entao os quadros sao poucos.
function Digitar($t, $cor = 'branco') {
    if (-not $ANIMAR) { W $t $cor; return }
    for ($i = 0; $i -lt $t.Length; $i += 12) {
        W $t.Substring($i, [Math]::Min(12, $t.Length - $i)) $cor -N
        Start-Sleep -Milliseconds 8
    }
    Write-Host ""
}
# Linha de status: [WAITING] [LOADING] [OK] [WARN] [ERROR]
function Status($tag, $cor, $texto) {
    Write-Host "    " -NoNewline
    W ("[" + $tag + "]").PadRight(11) $cor -N -Negrito:($tag -eq 'ERROR')
    W $texto 'branco'
}
function Ok($t)      { Status "OK" verde $t }
function Info($t)    { Status "LOADING" vermelho $t }
function Aviso($t)   { Status "WARN" amarelo $t }
function Erro($t)    { Status "ERROR" vermelho $t }
function Detalhe($t, $cor = 'cinza') { W ("               " + $t) $cor }
function Sair($c)    { Write-Host ""; Read-Host "Pressione Enter para fechar" | Out-Null; exit $c }
function Avisar-Versao($v) {
    if ("$($v.Major).$($v.Minor)" -ne $PY_TESTADO) { Aviso "Python $v aceito, mas o projeto foi testado no $PY_TESTADO." }
}

# Banner: simbolo da marca (hexagono com anel central e seis nos) + NODEWATCH em letras de bloco
$SIMBOLO = @(
    "    .-'^'-.    ",
    "  .'   o   '.  ",
    " /   o\|/o   \ ",
    "|     (O)     |",
    " \   o/|\o   / ",
    "  '.   o   .'  ",
    "    '-._.-'    "
)
$LETRAS = @{
    'N' = @('#   #', '##  #', '# # #', '#  ##', '#   #'); 'O' = @(' ### ', '#   #', '#   #', '#   #', ' ### ')
    'D' = @('#### ', '#   #', '#   #', '#   #', '#### '); 'E' = @('#####', '#    ', '#### ', '#    ', '#####')
    'W' = @('#   #', '#   #', '# # #', '## ##', '#   #'); 'A' = @(' ### ', '#   #', '#####', '#   #', '#   #')
    'T' = @('#####', '  #  ', '  #  ', '  #  ', '  #  '); 'C' = @(' ####', '#    ', '#    ', '#    ', ' ####')
    'H' = @('#   #', '#   #', '#####', '#   #', '#   #')
}
function Palavra($p, $linha) { (($p.ToCharArray() | ForEach-Object { $LETRAS[[string]$_][$linha] }) -join ' ').Replace('#', $BLOCO) }
function Banner {
    Write-Host ""
    for ($l = 0; $l -lt 7; $l++) {
        Write-Host "   " -NoNewline
        W $SIMBOLO[$l] 'vermelho' -N
        if ($l -ge 1 -and $l -le 5) {
            Write-Host "   " -NoNewline
            W (Palavra 'NODE' ($l - 1)) 'branco' -N
            Write-Host "  " -NoNewline
            W (Palavra 'WATCH' ($l - 1)) 'vermelho'
        } else { Write-Host "" }
        Pausa 15
    }
    Write-Host ""
    Write-Host "   " -NoNewline; Digitar "F R A U D   D E T E C T I O N   &   M O N I T O R I N G   S Y S T E M" 'branco'
    W ("   " + ($TRACO * 75)) 'vermelho2'
    W "   Inicializador Rapido  |  Ctrl+C encerra o servidor iniciado nesta janela" 'cinza'
    Write-Host ""
}
$ETAPAS = @(
    @('NODEWATCH BOOT',   'projeto e porta 5000'),
    @('ENVIRONMENT',      'Python e ambiente virtual .venv'),
    @('DEPENDENCIES',     'requirements.txt + requirements-ml.txt'),
    @('DATA ENGINE',      'numpy, pandas, pyarrow, scipy'),
    @('MACHINE LEARNING', 'modelo de deteccao (modelos/ -> artefatos_ml/)'),
    @('SENTINEL AI',      'token do Gemini (opcional)'),
    @('FRAUD DETECTION',  'servidor, API do painel e modelo carregado'),
    @('SYSTEM READY',     'painel do analista')
)
$DESTAQUE = @(5, 7)  # MACHINE LEARNING e FRAUD DETECTION: o nucleo antifraude
# Manifesto de boot: todos os modulos comecam em [WAITING]
function Manifesto {
    for ($i = 0; $i -lt $TOTAL; $i++) {
        Write-Host "    " -NoNewline
        W "[WAITING]  " 'cinza' -N
        W ("{0:D2}  " -f ($i + 1)) 'escuro' -N
        W $ETAPAS[$i][0].PadRight(18) 'vermelho2' -N
        W $ETAPAS[$i][1] 'escuro'
    }
}
function Etapa($n) {
    $nome = $ETAPAS[$n - 1][0]
    Titulo ("NodeWatch - boot {0}/{1}: {2}" -f $n, $TOTAL, $nome)
    Write-Host ""
    W ("  {0:D2}/{1:D2}  " -f $n, $TOTAL) 'vermelho2' -N
    if ($DESTAQUE -contains $n) {
        W ($SETA + " " + $nome) 'vermelho' -N -Negrito
        W "  [ CORE ]" 'branco' -N
        W ("  " + ($DUPLO * [Math]::Max(3, 41 - $nome.Length))) 'vermelho'
    } else {
        W $nome 'vermelho' -N -Negrito
        W ("  " + ($TRACO * [Math]::Max(3, 52 - $nome.Length))) 'vermelho2'
    }
}
# Barra de progresso geral: avanca so quando a etapa termina
function Progresso($n) {
    $alvo = [int]($n * 100 / $TOTAL); $larg = 40
    $quadros = 1; if ($ANIMAR) { $quadros = 2 }
    for ($k = 1; $k -le $quadros; $k++) {
        $p = [int]($script:pct + ($alvo - $script:pct) * $k / $quadros)
        $ch = [int]($larg * $p / 100)
        if ($ANIMAR) { Write-Host "`r" -NoNewline }
        Write-Host "    " -NoNewline
        W ($BLOCO * $ch) 'vermelho' -N
        W ($VAZIO * ($larg - $ch)) 'escuro' -N
        W (" {0,3}%" -f $p) 'branco' -N
        if ($k -lt $quadros) { Start-Sleep -Milliseconds 15 }
    }
    Write-Host ""
    $script:pct = $alvo
}
# Roda o Python do .venv com indicador animado; a saida e capturada e devolvida para ser mostrada inteira.
function Executar-Python($rotulo, $argumentos) {
    $tmpOut = [System.IO.Path]::GetTempFileName(); $tmpErr = [System.IO.Path]::GetTempFileName()
    $antes = $env:PYTHONIOENCODING; $env:PYTHONIOENCODING = "utf-8"
    try {
        $p = Start-Process -FilePath $venvPy -ArgumentList $argumentos -WorkingDirectory $raiz -NoNewWindow -PassThru `
            -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr -ErrorAction Stop
    } finally { $env:PYTHONIOENCODING = $antes }
    $null = $p.Handle  # sem isso o ExitCode pode vir vazio no Windows PowerShell
    $giro = @('|', '/', '-', '\'); $i = 0; $t0 = Get-Date
    if (-not $ANIMAR) { Info $rotulo }
    while (-not $p.HasExited) {
        if ($ANIMAR) {
            $s = [int]((Get-Date) - $t0).TotalSeconds
            Write-Host "`r    " -NoNewline
            W "[LOADING]  " 'vermelho' -N
            W ($rotulo + " ") 'branco' -N
            W $giro[$i % 4] 'vermelho' -N
            W ("  {0}s " -f $s) 'cinza' -N
            $i++
        }
        Start-Sleep -Milliseconds 100
    }
    $p.WaitForExit()
    Limpar-Linha
    $r = [pscustomobject]@{
        Codigo = $p.ExitCode
        Saida  = @(Get-Content -LiteralPath $tmpOut -Encoding UTF8 -ErrorAction SilentlyContinue)
        Erros  = @(Get-Content -LiteralPath $tmpErr -Encoding UTF8 -ErrorAction SilentlyContinue)
    }
    Remove-Item -LiteralPath $tmpOut, $tmpErr -ErrorAction SilentlyContinue
    return $r
}
# Mostra a saida capturada, colorindo pelas marcas que o proprio NodeWatch usa
function Mostrar-Saida($linhas) {
    foreach ($l in $linhas) {
        if ($null -eq $l -or $l -eq "") { continue }
        $cor = 'cinza'
        if ($l -match '^\s*\[OK\]') { $cor = 'verde' } elseif ($l -match '^\s*\[(AVISO|WARN)') { $cor = 'amarelo' }
        elseif ($l -match '^\s*\[ERRO|Traceback|Error') { $cor = 'vermelho' }
        Detalhe $l $cor
    }
}
# Quadro final; as linhas aceitam trechos coloridos ("{b}NODE{v}WATCH{b} ONLINE")
function Quadro($linhas, $cor) {
    $larg = 46
    Write-Host ""
    W ("   " + [char]0x2554 + ($DUPLO * $larg) + [char]0x2557) $cor
    foreach ($t in $linhas) {
        W ("   " + [char]0x2551) $cor -N
        Write-Host "  " -NoNewline
        W-Marcado $t -N
        Write-Host (" " * [Math]::Max(0, $larg - 2 - (Sem-Marcas $t).Length)) -NoNewline
        W ([string][char]0x2551) $cor
        Pausa 20
    }
    W ("   " + [char]0x255A + ($DUPLO * $larg) + [char]0x255D) $cor
}

Titulo "NodeWatch - boot"
Banner
Manifesto

# =========================================================================================================
# 01 NODEWATCH BOOT - raiz do projeto e porta 5000
# =========================================================================================================
Etapa 1
# Raiz do projeto = pasta pai deste script (confirmada pelos arquivos do NodeWatch)
$raiz = Split-Path -Parent $PSScriptRoot
$servidor = Join-Path $raiz "src\sentinel_ai.py"
$reqBase = Join-Path $raiz "requirements.txt"
$reqMl = Join-Path $raiz "requirements-ml.txt"
if (-not ((Test-Path -LiteralPath $servidor) -and (Test-Path -LiteralPath $reqBase) -and (Test-Path -LiteralPath $reqMl))) {
    Erro "Nao encontrei o NodeWatch na pasta acima deste script:"
    Detalhe $raiz
    Detalhe "Mantenha a pasta 'Inicializador Rapido' dentro da pasta principal do repositorio."
    Sair 1
}
Ok "Projeto encontrado em: $raiz"

# Porta 5000: reaproveita o NodeWatch se ja estiver rodando
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
# De que pasta e o NodeWatch que ja responde na porta? (pela linha de comando do processo que escuta a porta;
# $null quando o Windows nao informa). Evita reaproveitar, sem avisar, um servidor de outra copia do projeto.
function Pasta-Do-Servidor {
    try {
        $dono = (Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 5000 -State Listen -ErrorAction Stop | Select-Object -First 1).OwningProcess
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId = $dono" -ErrorAction Stop).CommandLine
        if ($cmd -match '^\s*"?(.+?)\\\.venv\\Scripts\\python(w)?\.exe') { return $Matches[1] }
    } catch {}
    return $null
}
if (Testar-NodeWatch) {
    $outra = Pasta-Do-Servidor
    $mesma = $outra -and ([System.IO.Path]::GetFullPath($outra).TrimEnd('\') -ieq [System.IO.Path]::GetFullPath($raiz).TrimEnd('\'))
    if ($outra -and -not $mesma) {
        Erro "Ja ha um NodeWatch rodando na porta 5000, mas de OUTRA pasta:"
        Detalhe $outra
        Detalhe "Ele nao tem as alteracoes desta pasta. Na janela desse NodeWatch, pressione Ctrl+C para encerra-lo"
        Detalhe "(nada foi encerrado por este script) e rode este inicializador de novo."
        Sair 1
    }
    Ok "O NodeWatch desta pasta ja esta rodando. Abrindo o painel: $URL"
    Quadro @("{b}NODE{v}WATCH{b} ONLINE", "{c}ja em execucao nesta maquina", "{b}SYSTEM STATUS: {g}OPERATIONAL") 'vermelho'
    Titulo "NodeWatch - online"
    Start-Process $URL
    Write-Host ""
    Write-Host "Para encerra-lo, use Ctrl+C na janela onde ele foi iniciado."
    Sair 0
}
if (Porta-Ocupada) {
    Erro "A porta 5000 esta ocupada por outro programa, que nao e o NodeWatch."
    Detalhe "Feche esse programa (nada foi encerrado por este script) e tente de novo."
    Detalhe "Para ver quem usa a porta: netstat -ano | findstr :5000"
    Sair 1
}
Ok "Porta 5000 livre."
Progresso 1

# =========================================================================================================
# 02 ENVIRONMENT - Python compativel (sem instalar nada) e .venv
# =========================================================================================================
Etapa 2
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
        Detalhe "Instale o Python 3.14 (versao testada no projeto; o minimo e 3.12) em:"
        Detalhe "  https://www.python.org/downloads/windows/"
        Detalhe "Marque 'Add python.exe to PATH' na instalacao e rode este inicializador de novo."
        Sair 1
    }
    # Cria o .venv (somente se nao existir; nunca apaga um existente)
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
Progresso 2

# =========================================================================================================
# 03 DEPENDENCIES - so pelos manifestos do projeto e dentro do .venv
# =========================================================================================================
Etapa 3
# google.genai (requirements.txt) e o que o Sentinel AI usa; sem ele, um .venv antigo passaria nesta checagem.
# A mesma importacao informa as versoes realmente carregadas (mostradas nas etapas 03 a 05).
$CHECAGEM = "import flask, flask_cors, dotenv, google.genai, numpy, pandas, sklearn, scipy, joblib, pyarrow; " +
    "from importlib.metadata import version as v; " +
    "print(chr(10).join(n + '=' + v(n) for n in ('flask', 'google-genai', 'numpy', 'pandas', 'pyarrow', 'scipy', 'scikit-learn', 'joblib')))"
$ARGS_CHECAGEM = '-c "' + $CHECAGEM + '"'
function Ler-Versoes($saida) {
    $d = @{}
    foreach ($l in $saida) { if ($l -match '^([\w\-]+)=(.+)$') { $d[$Matches[1]] = $Matches[2].Trim() } }
    return $d
}
$chk = Executar-Python "Verificando bibliotecas no .venv" $ARGS_CHECAGEM
if ($chk.Codigo -ne 0) {
    Aviso "Dependencias ausentes ou incompletas no .venv."
    Info "Instalando dependencias no .venv (primeiro uso: precisa de internet, pode levar alguns minutos)..."
    Write-Host ""
    & $venvPy -m pip install --disable-pip-version-check -r $reqBase -r $reqMl
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Erro "A instalacao das dependencias falhou."
        Detalhe "- Confira a conexao com a internet (ou proxy/firewall) e rode de novo."
        Detalhe "- Se o erro citar 'Long Path' ou 'No such file or directory', a pasta do projeto esta num caminho"
        Detalhe "  longo demais para o Windows (limite de 260 caracteres): mova o projeto para uma pasta curta,"
        Detalhe "  por exemplo C:\NodeWatch, e rode de novo. A instalacao parcial no .venv e aproveitada."
        Detalhe "- Se o erro citar versoes indisponiveis, use o Python 3.14 (versao em que o requirements-ml.txt foi fixado e testado)."
        Detalhe "- Comando manual, na pasta do projeto: .venv\Scripts\python -m pip install -r requirements.txt -r requirements-ml.txt"
        Sair 1
    }
    Write-Host ""
    Ok "Dependencias instaladas."
    # confere de novo para mostrar as versoes realmente instaladas
    $chk = Executar-Python "Conferindo a instalacao" $ARGS_CHECAGEM
    if ($chk.Codigo -ne 0) {
        Erro "Mesmo apos a instalacao, uma biblioteca nao carregou (saida tecnica abaixo)."
        Mostrar-Saida $chk.Erros
    }
} else { Ok "Dependencias ja instaladas." }
$ver = Ler-Versoes $chk.Saida
if ($ver.Count) {
    Detalhe ("flask {0}  |  google-genai {1}" -f $ver['flask'], $ver['google-genai']) 'branco'
}
Progresso 3

# =========================================================================================================
# 04 DATA ENGINE - bibliotecas de dados (carregadas na verificacao acima)
# =========================================================================================================
Etapa 4
if ($chk.Codigo -eq 0) {
    Ok "Motor de dados carregado."
    Detalhe ("numpy {0}  |  pandas {1}  |  pyarrow {2}  |  scipy {3}" -f $ver['numpy'], $ver['pandas'], $ver['pyarrow'], $ver['scipy']) 'branco'
} else {
    Erro "As bibliotecas de dados nao carregaram (veja a saida acima). O servidor pode nao iniciar."
}
Progresso 4

# =========================================================================================================
# 05 MACHINE LEARNING - instala a partir de modelos/ (ou baixa, conferindo o SHA-256) e valida com uma previsao
# =========================================================================================================
Etapa 5
if ($ver.Count) { Detalhe ("scikit-learn {0}  |  joblib {1}" -f $ver['scikit-learn'], $ver['joblib']) 'branco' }
$ml = Executar-Python "Preparando e validando o modelo de ML" "-m src.ml.provisionamento"
Mostrar-Saida $ml.Saida
$codigoModelo = $ml.Codigo
if ($codigoModelo -ne 0) {
    Mostrar-Saida $ml.Erros
    Aviso "O modelo de ML nao ficou pronto (veja a mensagem acima). O painel abre e as analises"
    Detalhe "gravadas continuam abrindo, mas novas analises ficam bloqueadas ate o modelo ser instalado." 'amarelo'
}
Progresso 5

# =========================================================================================================
# 06 SENTINEL AI - token do Gemini (opcional; ativa o Sentinel AI no Assistente de duvidas e no chat antigo)
#    Variavel lida por src/sentinel_ai.py: GEMINI_API_KEY, carregada do .env na raiz do projeto.
#    O valor nunca e exibido, registrado ou passado como argumento; nenhuma chamada e feita ao Gemini.
# =========================================================================================================
Etapa 6
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
    Ok "$VAR_TOKEN ja definido no ambiente do Windows (Sentinel AI habilitado no Assistente de duvidas e no chat antigo)."
} elseif (Token-Configurado) {
    Ok "$VAR_TOKEN ja configurado no .env (Sentinel AI habilitado no Assistente de duvidas e no chat antigo)."
} elseif ([Console]::IsInputRedirected) {
    Aviso "$VAR_TOKEN nao configurado; o chat Sentinel AI ficara indisponivel e o Assistente de duvidas respondera no modo local."
} else {
    Write-Host ""
    $seguro = Read-Host -AsSecureString "Token do Gemini para habilitar o chat Sentinel AI (opcional). Cole o token ou pressione Enter para continuar sem ele"
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($seguro)
    try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr).Trim() }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr); $seguro.Dispose() }
    if (-not $token) {
        Aviso "Sem token: o chat Sentinel AI ficara indisponivel ate $VAR_TOKEN ser configurado no .env;"
        Detalhe "o painel do analista funciona normalmente e o Assistente de duvidas responde no modo local."
    } elseif ($token -notmatch '^[A-Za-z0-9_\-\.]+$') {
        Aviso "O texto colado tem caracteres inesperados para um token (espacos, aspas ou simbolos)."
        Detalhe "Nada foi gravado; o chat ficara indisponivel. Rode de novo e cole somente o token."
    } else {
        try {
            Gravar-Token $token
            Ok "Token gravado em .env ($VAR_TOKEN). O valor nao e exibido."
            $ign = & git -C $raiz check-ignore -q -- .env 2>$null; $codigo = $LASTEXITCODE
            if ($codigo -eq 1) { Aviso "O .env NAO esta ignorado pelo Git neste projeto: nao faca commit dele." }
        } catch {
            Erro "Nao foi possivel gravar o .env (sem permissao ou arquivo em uso). Seguindo sem o token."
        }
    }
    $token = $null
}
Progresso 6

# =========================================================================================================
# 07 FRAUD DETECTION - inicia o servidor pelo comando oficial, na raiz do projeto, e confirma pela API
# =========================================================================================================
Etapa 7
Info "Iniciando o NodeWatch (python src\sentinel_ai.py)..."
Detalhe "Painel do analista: $URL"
Detalhe "Interface antiga:   ${URL}legado"
Detalhe "Para parar: Ctrl+C nesta janela."
Detalhe "Mensagens do servidor:" 'escuro'
Write-Host ""
$proc = Start-Process -FilePath $venvPy -ArgumentList '"src\sentinel_ai.py"' -WorkingDirectory $raiz -NoNewWindow -PassThru -ErrorAction Stop
try {
    $pronto = $false
    for ($i = 0; $i -lt 180 -and -not $proc.HasExited; $i++) {
        if (Testar-NodeWatch) { $pronto = $true; break }
        Start-Sleep -Milliseconds 500
    }
    Write-Host ""
    if ($pronto) {
        Ok "Servidor e API do painel respondendo em $URL"
        # Estado real do motor de deteccao e do Sentinel AI, lido da propria API (sem chamar o Gemini)
        $modeloOk = $false
        try {
            $est = Invoke-RestMethod -Uri $URL_ESTADO -TimeoutSec 5
            if ($est.modelo.disponivel) {
                $modeloOk = $true
                $limiar = $est.modelo.limiar_alerta
                if ($limiar -is [double] -or $limiar -is [decimal]) { $limiar = ([double]$limiar).ToString("0.0000", [Globalization.CultureInfo]::InvariantCulture) }
                Ok ("Motor de deteccao carregado: modelo {0} (limiar de alerta {1})" -f $est.modelo.versao, $limiar)
            } else {
                Aviso "Motor de deteccao sem modelo: novas analises ficam bloqueadas."
                if ($est.modelo.motivo) { Detalhe $est.modelo.motivo 'amarelo' }
            }
            $sen = $est.assistente.sentinel
            if ($sen.disponivel) { Ok ("Sentinel AI habilitado ({0}, {1}); confira em Assistente de duvidas > Testar conexao." -f $sen.provedor, $sen.modelo) }
            else { Status "LOCAL" amarelo "Sentinel AI desligado: o Assistente de duvidas responde no modo local." }
        } catch {
            Aviso "Nao consegui ler o estado do painel ($URL_ESTADO); o servidor esta no ar."
        }
        Progresso 7

        Etapa 8
        Ok "Painel disponivel. Abrindo o navegador em $URL"
        Progresso 8
        if ($modeloOk) {
            Quadro @("{b}NODE{v}WATCH{b} ONLINE", "{b}FRAUD DETECTION SYSTEM READY", "{b}SYSTEM STATUS: {g}OPERATIONAL") 'vermelho'
        } else {
            Quadro @("{b}NODE{v}WATCH{b} ONLINE", "{b}FRAUD DETECTION: {a}MODELO PENDENTE", "{b}SYSTEM STATUS: {a}DEGRADED") 'amarelo'
        }
        Titulo "NodeWatch - online ($URL)"
        Write-Host ""
        W "   Painel: $URL   |   Ctrl+C nesta janela encerra o servidor" 'cinza'
        Write-Host ""
        Start-Process $URL
    } elseif ($proc.HasExited) {
        Erro "O servidor encerrou antes de ficar disponivel (veja as mensagens acima)."
        Quadro @("{b}NODE{v}WATCH{b} OFFLINE", "{b}SYSTEM STATUS: {v}FAILURE") 'vermelho'
        Titulo "NodeWatch - falha na inicializacao"
        $falhou = $true
    } else {
        Aviso "O painel ainda nao respondeu; abra $URL manualmente quando aparecer."
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
# Falha ao subir: a janela fica aberta para a mensagem de erro do servidor continuar legivel
if ($falhou) { Sair 1 }
