<#
  One-time setup on a new machine:
    - Python venv + API dependencies
    - Private PostgreSQL 15 cluster in .local\pgdata on :5546, role `tracker`, databases `activity` and `activity_test`
    - .local\.env with TRACKER_DATABASE_URL (passwords are generated and stay in .local, which is git-ignored)
  Safe to re-run: existing pieces are kept.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pgbin = "C:\Program Files\PostgreSQL\15\bin"
$pgdata = Join-Path $root ".local\pgdata"
$secrets = Join-Path $root ".local\secrets"
$port = 5546
New-Item -ItemType Directory -Force $secrets, (Join-Path $root ".local\logs") | Out-Null

function New-Secret { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object { [char]$_ }) }

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { python -m venv (Join-Path $root ".venv") }
& $py -m pip install -q -r (Join-Path $root "apps\api\requirements.txt")

if (-not (Test-Path (Join-Path $pgdata "PG_VERSION"))) {
  $suFile = Join-Path $secrets "pg-superuser.txt"
  New-Secret | Set-Content -NoNewline $suFile
  & "$pgbin\initdb.exe" -D $pgdata -U postgres --pwfile=$suFile -A scram-sha-256 -E UTF8 | Out-Null
  Add-Content (Join-Path $pgdata "postgresql.conf") "`nport = $port`nlisten_addresses = '127.0.0.1'"
}

$up = [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
if (-not $up) {
  # Start-Process, not `&`: postgres inherits the caller's output handles and would keep this script waiting.
  Start-Process -WindowStyle Hidden "$pgbin\pg_ctl.exe" -ArgumentList "start", "-D", "`"$pgdata`"", "-l", "`"$root\.local\pg.log`""
  for ($i = 0; $i -lt 20 -and -not (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue); $i++) { Start-Sleep 1 }
}

$appFile = Join-Path $secrets "pg-tracker.txt"
if (-not (Test-Path $appFile)) {
  $appPw = New-Secret
  $appPw | Set-Content -NoNewline $appFile
  $env:PGPASSWORD = Get-Content -Raw (Join-Path $secrets "pg-superuser.txt")
  & "$pgbin\psql.exe" -h 127.0.0.1 -p $port -U postgres -q -c "CREATE ROLE tracker LOGIN PASSWORD '$appPw'"
  foreach ($db in "activity", "activity_test") {
    & "$pgbin\psql.exe" -h 127.0.0.1 -p $port -U postgres -q -c "CREATE DATABASE $db OWNER tracker"
  }
  Remove-Item Env:PGPASSWORD
}
$appPw = Get-Content -Raw $appFile
@(
  "TRACKER_DATABASE_URL=postgresql+psycopg://tracker:$appPw@127.0.0.1:$port/activity"
  "TRACKER_TEST_DATABASE_URL=postgresql+psycopg://tracker:$appPw@127.0.0.1:$port/activity_test"
) | Set-Content (Join-Path $root ".local\.env")

Push-Location (Join-Path $root "apps\api")
& $py -m alembic upgrade head
& $py -m app.cli seed
Pop-Location
Write-Host "Setup done. Create the first admin with:  .venv\Scripts\python -m app.cli create-admin <email> <name>  (run in apps\api)"
