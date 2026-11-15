# Instala o Robô de Revenda RJ no Windows e agenda a execução a cada 2 horas (7h às 23h).
# Uso (no PowerShell, dentro da pasta do repositório):
#   powershell -ExecutionPolicy Bypass -File windows\instalar.ps1

$ErrorActionPreference = "Continue"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
Write-Host "Pasta do robô: $raiz" -ForegroundColor Cyan

# 1) Python: tenta o lançador "py", o "python" do PATH e as pastas padrão de instalação.
$candidatos = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $candidatos += ,@("py", "-3") }
$cmdPython = Get-Command python -ErrorAction SilentlyContinue
if ($cmdPython -and $cmdPython.Source -notlike "*WindowsApps*") { $candidatos += ,@($cmdPython.Source) }
$pastas = @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles", "${env:ProgramFiles(x86)}")
foreach ($pasta in $pastas) {
    if ($pasta -and (Test-Path $pasta)) {
        Get-ChildItem -Path $pasta -Filter "Python3*" -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | ForEach-Object {
                $exe = Join-Path $_.FullName "python.exe"
                if (Test-Path $exe) { $candidatos += ,@($exe) }
            }
    }
}
$py = $null
foreach ($c in $candidatos) {
    $exe = $c[0]; $extra = @($c | Select-Object -Skip 1)
    $v = (& $exe @extra --version 2>&1 | Out-String).Trim()
    Write-Host "  testando $($c -join ' '): $v"
    if ($v -match "Python 3\.(1[0-9])") { $py = $c; break }
}
if (-not $py) {
    Write-Host ""
    Write-Host "Python 3.10+ não encontrado." -ForegroundColor Red
    Write-Host "Instale com:  winget install -e --id Python.Python.3.12" -ForegroundColor Yellow
    Write-Host "(ou baixe em https://www.python.org/downloads/ marcando 'Add python.exe to PATH')"
    Write-Host "Depois FECHE e ABRA o PowerShell de novo e rode este instalador outra vez."
    exit 1
}
Write-Host "Usando: $($py -join ' ') ($v)" -ForegroundColor Cyan

# 2) Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git não encontrado. Instale em https://git-scm.com/download/win e rode de novo." -ForegroundColor Red
    exit 1
}

# 3) Ambiente virtual + dependências
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Criando ambiente virtual (.venv)..."
    $exe = $py[0]; $extra = @($py | Select-Object -Skip 1)
    & $exe @extra -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Host "Falha ao criar o ambiente virtual." -ForegroundColor Red; exit 1 }
}
& .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { Write-Host "Falha ao instalar dependências." -ForegroundColor Red; exit 1 }

# 4) Chave da API (fica só neste computador, no arquivo .env, que não vai para o GitHub)
if (-not (Test-Path ".env") -or -not (Select-String -Path ".env" -Pattern "^ANTHROPIC_API_KEY=sk-" -Quiet)) {
    Write-Host ""
    Write-Host "Cole a sua chave da Anthropic (começa com sk-ant-) e tecle Enter." -ForegroundColor Yellow
    Write-Host "Ela fica salva só neste PC, no arquivo .env." -ForegroundColor Yellow
    $seg = Read-Host "ANTHROPIC_API_KEY" -AsSecureString
    $chave = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($seg))
    if (-not $chave.StartsWith("sk-")) { Write-Host "Chave inválida (deveria começar com sk-)." -ForegroundColor Red; exit 1 }
    Set-Content -Path ".env" -Value "ANTHROPIC_API_KEY=$chave`nLOG_LEVEL=INFO" -Encoding ASCII
}

# 5) Agendamento: todo dia às 7h, repetindo a cada 2h por 16h (até 23h).
#    StartWhenAvailable: se o PC estava desligado no horário, roda assim que ligar.
$script = Join-Path $raiz "windows\rodar.ps1"
$acao = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`"" -WorkingDirectory $raiz
$gatilho = New-ScheduledTaskTrigger -Daily -At "07:00"
$gatilho.Repetition = (New-ScheduledTaskTrigger -Once -At "07:00" `
    -RepetitionInterval (New-TimeSpan -Hours 2) -RepetitionDuration (New-TimeSpan -Hours 16)).Repetition
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 45) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Revenda RJ" -Action $acao -Trigger $gatilho -Settings $config `
    -Description "Robô de revenda RJ: coleta OLX, promoções e passagens; envia o painel para o GitHub." -Force | Out-Null

Write-Host ""
Write-Host "Pronto! Tarefa 'Revenda RJ' agendada a cada 2h (7h-23h)." -ForegroundColor Green
Write-Host "Para rodar agora e testar:  powershell -ExecutionPolicy Bypass -File windows\rodar.ps1"
Write-Host "Logs ficam em: $raiz\logs"
