# Roda o robô uma vez e envia banco + painel para o GitHub. Chamado pelo Agendador de Tarefas.
$ErrorActionPreference = "Continue"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
$env:PYTHONUTF8 = "1"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$log = "logs\robo-$(Get-Date -Format 'yyyy-MM-dd').log"
Start-Transcript -Path $log -Append | Out-Null
Write-Host "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="

# Pega mudanças de configuração feitas no GitHub (catálogo, regras, rotas...).
git pull --rebase --autostash -X theirs origin main
if ($LASTEXITCODE -ne 0) { git rebase --abort 2>$null; Write-Host "Aviso: não consegui atualizar do GitHub; sigo com a versão local." }

# Saída do Python vai para um log próprio (o Transcript do PowerShell 5 não captura programas externos).
$logPy = "logs\python-$(Get-Date -Format 'yyyy-MM-dd').log"
cmd /c ".venv\Scripts\python.exe -m src.main >> $logPy 2>&1"   # caminho relativo e sem espaços
$codigo = $LASTEXITCODE
Write-Host "Robô terminou com código $codigo (detalhes em $logPy)"

git add data docs
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "chore(dados): atualiza $(Get-Date -Format 'yyyy-MM-dd HH:mm') (PC)" | Out-Null
    for ($i = 1; $i -le 4; $i++) {
        git pull --rebase -X theirs origin main
        git push origin main
        if ($LASTEXITCODE -eq 0) { Write-Host "Enviado para o GitHub."; break }
        Write-Host "Push falhou (tentativa $i), tentando de novo..."
        Start-Sleep -Seconds (5 * $i)
    }
} else { Write-Host "Nada mudou." }

Stop-Transcript | Out-Null
exit $codigo
