# superpowers runtime file installer (Windows PowerShell).
#
# Copies comm-matrix.csv and delegation_request schema from the routing-bot
# directory into the AgentAgora deployment's .agentagora/ data directory.
# Run this once before starting the AgentAgora server for a superpowers deployment.
#
# Usage:
#   .\setup.ps1 -Dir <deployment-folder>
#   .\setup.ps1          # uses current directory as deployment folder
#
# Example:
#   cd C:\my-deployment
#   C:\path\to\AgentAgora\plugin\superpowers\setup.ps1 -Dir .

param(
    [string]$Dir = "."
)

$ErrorActionPreference = "Stop"

# Resolve the script's own directory — routing-bot/ is a sibling of this script.
$ScriptDir   = $PSScriptRoot
$BotDir      = Join-Path $ScriptDir "routing-bot"
$CommMatrix  = Join-Path $BotDir "comm-matrix.csv"
$SchemaFile  = Join-Path $BotDir "delegation_request.schema.jsonl"

# Resolve the deployment directory.
$DeployDir   = (Resolve-Path $Dir).Path
$AgoraDir    = Join-Path $DeployDir ".agentagora"
$DestMatrix  = Join-Path $AgoraDir "comm-matrix.csv"
$DestSchemas = Join-Path $AgoraDir "schemas.jsonl"

# --- Validate source files exist ---
if (-not (Test-Path -LiteralPath $CommMatrix -PathType Leaf)) {
    Write-Host "ERROR: source not found: $CommMatrix" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath $SchemaFile -PathType Leaf)) {
    Write-Host "ERROR: source not found: $SchemaFile" -ForegroundColor Red
    exit 1
}

# --- Create .agentagora/ if absent ---
if (-not (Test-Path -LiteralPath $AgoraDir -PathType Container)) {
    New-Item -ItemType Directory -Path $AgoraDir | Out-Null
    Write-Host "  [created] $AgoraDir"
}

# --- Copy comm-matrix.csv ---
Copy-Item -LiteralPath $CommMatrix -Destination $DestMatrix -Force
Write-Host "  [copied]  comm-matrix.csv -> $DestMatrix"

# --- Append delegation_request schema (skip if already present) ---
$SchemaLine = Get-Content -LiteralPath $SchemaFile -Raw
# Trim trailing whitespace so Add-Content writes a clean single line.
$SchemaTrimmed = $SchemaLine.Trim()

$AlreadyPresent = $false
if (Test-Path -LiteralPath $DestSchemas -PathType Leaf) {
    $Existing = Get-Content -LiteralPath $DestSchemas -Raw
    if ($Existing -match '"name"\s*:\s*"delegation_request"') {
        $AlreadyPresent = $true
    }
}

if ($AlreadyPresent) {
    Write-Host "  [skipped] delegation_request schema already in $DestSchemas"
} else {
    # Ensure file exists before appending; Add-Content creates if absent.
    Add-Content -LiteralPath $DestSchemas -Value $SchemaTrimmed -Encoding UTF8
    Write-Host "  [appended] delegation_request schema -> $DestSchemas"
}

Write-Host ""
Write-Host "Runtime files installed. Next step:" -ForegroundColor Green
Write-Host "  Start the routing bot before launching persona workers:"
Write-Host "    $BotDir\run-bot.bat"
