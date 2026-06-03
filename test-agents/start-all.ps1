# AgentAgora test harness - full bring-up: broker + 7 workers + comm-matrix.
# Opens one Windows Terminal (wt.exe) tab per worker. If wt.exe is missing, prints manual steps.
#   -c : pass --continue to each claude worker (resume prior session). Default: fresh.
# Each worker is launched with an initial prompt of '.' to kick it off.
param([switch]$c)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$workers = @('Orchestrator', 'Planner', 'Coder', 'Tester', 'Reviewer', 'Writer', 'General')
# claude args forwarded via run.bat (%*): initial prompt '.', plus -c when requested.
if ($c) { $runArgs = '-c .' } else { $runArgs = '.' }

$wt = Get-Command wt.exe -ErrorAction SilentlyContinue
if (-not $wt) {
    Write-Host '[test-agents] wt.exe not found - run manually:' -ForegroundColor Yellow
    Write-Host '  1) start-broker.bat (separate window)'
    Write-Host '  2) apply-comm-matrix.bat'
    Write-Host "  3) in each worker folder: run.bat $runArgs"
    exit 1
}

Write-Host '[test-agents] starting broker tab...'
& wt.exe -w 0 new-tab -d "$here" --title 'agora-broker' cmd /k 'start-broker.bat'

Write-Host '[test-agents] waiting for broker...'
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8420/dashboard/auth-mode' -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {}
}
if (-not $ok) { Write-Host '[test-agents] broker not responding (30s) - apply comm-matrix/workers manually.' -ForegroundColor Yellow }

if ($ok) {
    Write-Host '[test-agents] applying comm-matrix (review-gated)...'
    & "$here/apply-comm-matrix.bat"
}

foreach ($w in $workers) {
    Write-Host "[test-agents] starting worker $w tab (run.bat $runArgs)..."
    & wt.exe -w 0 new-tab -d "$here/$w" --title "agora-$w" cmd /k "run.bat $runArgs"
}

Write-Host ''
Write-Host '[test-agents] done - dashboard: http://127.0.0.1:8420/dashboard' -ForegroundColor Green
