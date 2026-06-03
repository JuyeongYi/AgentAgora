# AgentAgora run-all: start the server, wait for its port, then launch each worker.
# Worker = a subdirectory that contains .mcp.json. run.ps1 is preferred over run.bat.
# Uses Windows Terminal tabs (wt.exe) when available, otherwise separate windows.
$ErrorActionPreference = "SilentlyContinue"
$root = $PSScriptRoot
$port = 8420
$haveWt = $null -ne (Get-Command wt.exe -ErrorAction SilentlyContinue)

function Start-Pane($dir, $cmd) {
    if ($haveWt) { wt.exe -w 0 new-tab -d "$dir" cmd /k $cmd }
    else { Start-Process cmd -ArgumentList "/k", $cmd -WorkingDirectory $dir }
}

# 1) server
Start-Pane $root "agent-agora --dir ""$root"" --port $port --no-tls"

# 2) wait for the server port to open
for ($i = 0; $i -lt 60; $i++) {
    if (Test-NetConnection 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue) { break }
    Start-Sleep -Milliseconds 500
}

# 3) launch each worker (subdir with .mcp.json)
Get-ChildItem -Directory $root | Where-Object { Test-Path (Join-Path $_.FullName ".mcp.json") } | ForEach-Object {
    $wd = $_.FullName
    if (Test-Path (Join-Path $wd "run.ps1")) { $cmd = "powershell -ExecutionPolicy Bypass -File run.ps1" }
    elseif (Test-Path (Join-Path $wd "run.bat")) { $cmd = "run.bat" }
    else { return }
    Start-Pane $wd $cmd
}
