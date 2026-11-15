# Roda o robô uma vez e envia banco + painel para o GitHub. Chamado pelo Agendador de Tarefas.
# Para acompanhar ao vivo:   powershell -ExecutionPolicy Bypass -File windows\rodar.ps1 -AoVivo
# Forçar leilões agora:      powershell -ExecutionPolicy Bypass -File windows\rodar.ps1 -AoVivo -ForcarLeiloes
param([switch]$AoVivo, [switch]$ForcarLeiloes)
$ErrorActionPreference = "Continue"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
$env:PYTHONUTF8 = "1"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$log = "logs\robo-$(Get-Date -Format 'yyyy-MM-dd').log"
Start-Transcript -Path $log -Append | Out-Null
Write-Host "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="

# Identidade do Git só deste repositório (os commits do robô precisam de nome e e-mail).
if (-not (git config user.email)) {
    git config user.name "Revenda RJ (PC)"
    git config user.email "revenda-rj@users.noreply.github.com"
}

# Pega mudanças de configuração feitas no GitHub (catálogo, regras, rotas...).
git pull --rebase --autostash -X theirs origin main
if ($LASTEXITCODE -ne 0) { git rebase --abort 2>$null; Write-Host "Aviso: não consegui atualizar do GitHub; sigo com a versão local." }

# Saída do Python vai para um log próprio (o Transcript do PowerShell 5 não captura programas externos).
$logPy = "logs\python-$(Get-Date -Format 'yyyy-MM-dd').log"
$extra = ""
if ($ForcarLeiloes) { $extra = "--forcar-leiloes" }
if ($AoVivo) {
    # Mostra tudo na tela enquanto roda (e também grava no log).
    cmd /c ".venv\Scripts\python.exe -m src.main $extra 2>&1" | Tee-Object -FilePath $logPy -Append
} else {
    cmd /c ".venv\Scripts\python.exe -m src.main $extra >> $logPy 2>&1"   # caminho relativo e sem espaços
}
$codigo = $LASTEXITCODE
Write-Host "Robô terminou com código $codigo (detalhes em $logPy)"

git add data docs
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "chore(dados): atualiza $(Get-Date -Format 'yyyy-MM-dd HH:mm') (PC)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERRO: o commit falhou; nada foi enviado ao GitHub." -ForegroundColor Red
        if ($codigo -eq 0) { $codigo = 2 }
    } else {
        $enviado = $false
        for ($i = 1; $i -le 4; $i++) {
            git pull --rebase -X theirs origin main
            if ($LASTEXITCODE -eq 0) {
                git push origin main
                if ($LASTEXITCODE -eq 0) { $enviado = $true; break }
            } else { git rebase --abort 2>$null }
            Write-Host "Envio falhou (tentativa $i), tentando de novo..."
            Start-Sleep -Seconds (5 * $i)
        }
        if ($enviado) { Write-Host "Enviado para o GitHub." -ForegroundColor Green }
        else { Write-Host "ERRO: não consegui enviar ao GitHub." -ForegroundColor Red; if ($codigo -eq 0) { $codigo = 3 } }
    }
} else { Write-Host "Nada mudou." }

Stop-Transcript | Out-Null
exit $codigo
