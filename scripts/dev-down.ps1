param([switch]$KeepDb)
$root = Split-Path -Parent $PSScriptRoot
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*uvicorn*app.main:app*8040*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host "stopped api (pid $($_.ProcessId))" }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*app.worker*" -and $_.CommandLine -like "*activity-tracker*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host "stopped worker (pid $($_.ProcessId))" }
# The web server is node running next on :3030 from this repo.
Get-NetTCPConnection -State Listen -LocalPort 3030 -ErrorAction SilentlyContinue | ForEach-Object {
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)"
  if ($p.CommandLine -like "*activity-tracker*") { Stop-Process -Id $p.ProcessId -Force; Write-Host "stopped web (pid $($p.ProcessId))" }
}
if (-not $KeepDb) {
  & "C:\Program Files\PostgreSQL\15\bin\pg_ctl.exe" stop -D "$root\.local\pgdata" -m fast
}
