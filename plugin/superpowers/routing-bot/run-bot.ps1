# superpowers routing bot launcher (Windows PowerShell).
#
# Prerequisites: AgentAgora server must be running at http://127.0.0.1:8420.
#   python -m agent_agora --port 8420 --no-tls --no-timeout
#
# Override the server address with $env:AGORA_URL before calling this script.
# Pass any extra arguments; they are forwarded to routing_bot.py.

$ScriptDir = $PSScriptRoot
$RepoRoot = (Get-Item "$ScriptDir\..\..\..\..").FullName
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$BotScript = Join-Path $ScriptDir "routing_bot.py"

& $PythonExe $BotScript @args
