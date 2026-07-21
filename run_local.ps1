$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$RuntimeDir = Join-Path $ProjectRoot ".runtime"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Ambiente virtual nao encontrado. Execute: python -m venv .venv"
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".env"))) {
    throw "Arquivo .env nao encontrado. Copie .env.example, ajuste os valores e tente novamente."
}

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
Push-Location $ProjectRoot
try {
    & $Python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "A migracao do banco falhou."
    }

    $Collector = Start-Process `
        -FilePath $Python `
        -ArgumentList "-m", "app.collector" `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput (Join-Path $RuntimeDir "collector.out.log") `
        -RedirectStandardError (Join-Path $RuntimeDir "collector.err.log") `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath (Join-Path $RuntimeDir "collector.pid") -Value $Collector.Id

    $Web = Start-Process `
        -FilePath $Python `
        -ArgumentList "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput (Join-Path $RuntimeDir "web.out.log") `
        -RedirectStandardError (Join-Path $RuntimeDir "web.err.log") `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath (Join-Path $RuntimeDir "web.pid") -Value $Web.Id

    Start-Sleep -Seconds 2
    if ($Collector.HasExited) {
        throw "O coletor encerrou ao iniciar. Consulte .runtime\collector.err.log."
    }
    if ($Web.HasExited) {
        throw "A aplicacao web encerrou ao iniciar. Consulte .runtime\web.err.log."
    }

    Write-Host "Crypto Risk Monitor iniciado em http://127.0.0.1:8000"
    Write-Host "Use .\stop_local.ps1 para encerrar os processos."
}
catch {
    & (Join-Path $ProjectRoot "stop_local.ps1") -Quiet
    throw
}
finally {
    Pop-Location
}
