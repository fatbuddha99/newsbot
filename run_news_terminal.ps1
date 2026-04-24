param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8000
)

$candidates = @(
    (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    (Get-Command py -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    "C:\Users\jd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $candidates) {
    Write-Error "No Python runtime found. Install Python or update run_news_terminal.ps1."
    exit 1
}

$python = $candidates[0]
$env:NEWS_TERMINAL_HOST = $HostName
$env:NEWS_TERMINAL_PORT = "$Port"

Write-Host "Starting Signal Terminal at http://$HostName`:$Port using $python"
& $python "app.py"
