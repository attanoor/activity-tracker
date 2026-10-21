<#
  Builds what the Downloads page offers, into dist\downloads:
    ActivityTrackerAgent.exe            Windows tray agent (PyInstaller, one file)
    activity-tracker-extension.zip      Chrome/Edge extension (load unpacked)
  -Server is the address the agent's setup window suggests (people can change it there).
#>
param([string]$Server = "http://localhost:3030")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$out = Join-Path $root "dist\downloads"
$work = Join-Path $root ".local\build"
$tools = Join-Path $PSScriptRoot "build_tools.py"
New-Item -ItemType Directory -Force $out, $work | Out-Null

$agentVersion = (& $py -c "import sys; sys.path.insert(0, r'$root\agent'); import tracker_agent; print(tracker_agent.__version__)")
"DEFAULT_SERVER = `"$Server`"" | Set-Content (Join-Path $root "agent\tracker_agent\_build.py")
& $py $tools icon (Join-Path $work "agent.ico")
Push-Location (Join-Path $root "agent")
try {
  & $py -m PyInstaller --noconfirm --onefile --noconsole --name ActivityTrackerAgent `
    --icon (Join-Path $work "agent.ico") --distpath $out --workpath (Join-Path $work "pyi") --specpath $work `
    --hidden-import pystray._win32 run_agent.py
  if ($LASTEXITCODE) { throw "PyInstaller failed" }
} finally {
  Pop-Location
  Remove-Item (Join-Path $root "agent\tracker_agent\_build.py") -ErrorAction SilentlyContinue
}
& $py $tools manifest $out agent ActivityTrackerAgent.exe $agentVersion

$extVersion = (Get-Content (Join-Path $root "extension\manifest.json") -Raw | ConvertFrom-Json).version
& $py $tools zip-extension (Join-Path $root "extension") (Join-Path $out "activity-tracker-extension.zip")
& $py $tools manifest $out extension activity-tracker-extension.zip $extVersion

Get-ChildItem $out | Format-Table Name, Length -AutoSize
