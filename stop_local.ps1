param(
    [switch]$Quiet
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeDir = Join-Path $ProjectRoot ".runtime"

foreach ($Name in @("collector", "web")) {
    $PidFile = Join-Path $RuntimeDir "$Name.pid"
    if (-not (Test-Path -LiteralPath $PidFile)) {
        continue
    }
    $ProcessId = Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue
    if ($ProcessId -and (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $ProcessId
        if (-not $Quiet) {
            Write-Host "$Name encerrado (PID $ProcessId)."
        }
    }
    Remove-Item -LiteralPath $PidFile -Force
}
