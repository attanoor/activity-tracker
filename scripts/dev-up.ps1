<#
  Starts the local stack, detached:
    PostgreSQL :5546 (private cluster in .local\pgdata)
    API        :8040 (uvicorn, 127.0.0.1 only; reached through the web app's /api)
    Web        :3030 (Next.js)
  Logs: .local\logs\*.log    Stop with scripts\dev-down.ps1
#>
param([switch]$DevWeb)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$logs = Join-Path $root ".local\logs"
$pgbin = "C:\Program Files\PostgreSQL\15\bin"
New-Item -ItemType Directory -Force $logs | Out-Null

function Test-Port($port) { [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) }

if (-not (Test-Port 5546)) {
  # Start-Process, not `&`: postgres inherits the caller's output handles and would keep this script waiting.
  Start-Process -WindowStyle Hidden "$pgbin\pg_ctl.exe" -ArgumentList "start", "-D", "`"$root\.local\pgdata`"", "-l", "`"$root\.local\pg.log`""
  for ($i = 0; $i -lt 20 -and -not (Test-Port 5546); $i++) { Start-Sleep 1 }
}
Write-Host "postgres :5546 $(if (Test-Port 5546) {'up'} else {'FAILED - see .local\pg.log'})"

Push-Location "$root\apps\api"
& $py -m alembic upgrade head
Pop-Location

if (-not (Test-Port 8040)) {
  Start-Process -WindowStyle Hidden -WorkingDirectory "$root\apps\api" $py `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8040" `
    -RedirectStandardOutput "$logs\api.log" -RedirectStandardError "$logs\api.err.log"
  Start-Sleep 3
}
Write-Host "api      :8040 $(if (Test-Port 8040) {'up'} else {'starting... see .local\logs\api.err.log'})"

$worker = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*app.worker*" -and $_.CommandLine -like "*activity-tracker*" }
if (-not $worker) {
  # Full venv path in the command line, so dev-down can find this worker and only this one.
  Start-Process -WindowStyle Hidden -WorkingDirectory "$root\apps\api" $py -ArgumentList "-m", "app.worker" `
    -RedirectStandardOutput "$logs\worker.log" -RedirectStandardError "$logs\worker.err.log"
}
Write-Host "worker   $(if ($worker) {'already running'} else {'started (logs: .local\logs\worker.err.log)'})"

if (-not (Test-Port 3030)) {
  # next start serves the last build; run `npm run build` in apps\web after UI changes (or use -DevWeb).
  $cmd = if ($DevWeb) { "dev" } else { "start" }
  Start-Process -WindowStyle Hidden -WorkingDirectory "$root\apps\web" "cmd.exe" -ArgumentList "/c", "npm run $cmd > `"$logs\web.log`" 2>&1"
  for ($i = 0; $i -lt 30 -and -not (Test-Port 3030); $i++) { Start-Sleep 1 }
}
Write-Host "web      :3030 $(if (Test-Port 3030) {'up'} else {'starting... see .local\logs\web.log'})"
Write-Host "Open http://localhost:3030"
