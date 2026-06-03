# AgentAgora run-all (zellij): open the server and each worker in a zellij tab.
# Works inside OR outside a zellij session:
#   - outside: start a new zellij session (via a temp layout) and re-run this inside it.
#   - inside:  add tabs to the current session with `zellij action new-tab`.
# Worker = a subdirectory that contains .mcp.json; runs its run.bat.
# Native Windows zellij requires >= 0.44.0 (no WSL).
$ErrorActionPreference = "SilentlyContinue"
$here = $PSScriptRoot
$self = (Join-Path $here "run-all.ps1") -replace '\\', '/'
$root = $here
$port = {{PORT}}

if ($null -eq (Get-Command zellij -ErrorAction SilentlyContinue)) {
    Write-Host "zellij not found. Install zellij first (>= 0.44.0 for native Windows)."
    exit 1
}

# Outside a zellij session: start one (temp layout) and re-run this script inside it.
if (-not $env:ZELLIJ) {
    $layout = (Join-Path ([System.IO.Path]::GetTempPath()) "agora-run-all.kdl") -replace '\\', '/'
    $kdl = @"
layout {
    pane command="powershell" {
        args "-ExecutionPolicy" "Bypass" "-File" "$self"
    }
}
"@
    Set-Content -Path $layout -Value $kdl -Encoding ascii
    zellij --layout $layout
    exit
}

# Inside a session: start server (only if this script manages it)
{{SERVER_BLOCK}}

# wait for the server port to open
for ($i = 0; $i -lt 60; $i++) {
    if (Test-NetConnection 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue) { break }
    Start-Sleep -Milliseconds 500
}

# one tab per worker (subdir with .mcp.json)
Get-ChildItem -Directory $root | Where-Object { Test-Path (Join-Path $_.FullName ".mcp.json") } | ForEach-Object {
    if (Test-Path (Join-Path $_.FullName "run.bat")) {
        zellij action new-tab --name $_.Name --cwd $_.FullName -- cmd /c run.bat
    }
}
