# AgentAgora server launcher (Windows).
#
# Usage: cd into your deployment folder, then run this script.
#   cd C:\path\to\deployment
#   C:\path\to\AgentAgora\run-server.ps1
#
# It checks the current folder for AgentAgora deployment data (.agentagora\)
# and passes that folder to the server via --dir. Press Ctrl+C to stop.

$Port = 8420

# Deployment folder = the current working directory this script was run from.
$DeployDir = (Get-Location).Path
$AgoraDir = Join-Path $DeployDir ".agentagora"

if (-not (Test-Path -LiteralPath $AgoraDir -PathType Container)) {
    Write-Host "No .agentagora\ in current folder: $DeployDir" -ForegroundColor Red
    Write-Host "This is not an AgentAgora deployment folder. cd into a deployment" -ForegroundColor Red
    Write-Host "folder and retry, or run /cc-agora-ops:agora-setup to initialize it." -ForegroundColor Red
    exit 1
}

# Report deployment config files (the server falls back to defaults if missing).
foreach ($name in @("server-info.json", "schemas.jsonl", "comm-matrix.csv", "file-policy.json")) {
    if (Test-Path -LiteralPath (Join-Path $AgoraDir $name) -PathType Leaf) {
        Write-Host "  [ok]      .agentagora\$name"
    } else {
        Write-Host "  [missing] .agentagora\$name"
    }
}

Write-Host "Starting AgentAgora server -- dir: $DeployDir  port: $Port"

if (Get-Command agent-agora -ErrorAction SilentlyContinue) {
    agent-agora --dir "$DeployDir" --port $Port --no-tls
} else {
    Write-Host "agent-agora CLI not found -- falling back to 'python -m agent_agora'." -ForegroundColor Yellow
    Write-Host "(To install the server, see FOR_AGENT.md.)" -ForegroundColor Yellow
    python -m agent_agora --dir "$DeployDir" --port $Port --no-tls
}
