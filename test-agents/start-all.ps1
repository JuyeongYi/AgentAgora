# AgentAgora 테스트 하니스 — 전체 기동: 브로커 + 7 워커 + comm-matrix.
# Windows Terminal(wt.exe) 탭을 워커당 하나씩 띄운다. wt.exe가 없으면 안내만 출력.
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$workers = @('Orchestrator', 'Planner', 'Coder', 'Tester', 'Reviewer', 'Writer', 'General')

$wt = Get-Command wt.exe -ErrorAction SilentlyContinue
if (-not $wt) {
    Write-Host "[test-agents] wt.exe 없음 — 수동 실행:" -ForegroundColor Yellow
    Write-Host "  1) start-broker.bat (별도 창)"
    Write-Host "  2) apply-comm-matrix.bat"
    Write-Host "  3) 각 워커 폴더에서 run.bat"
    exit 1
}

# 1) 브로커 탭
Write-Host "[test-agents] 브로커 기동 (탭)..."
& wt.exe -w 0 new-tab -d "$here" --title "agora-broker" cmd /k "start-broker.bat"

# 2) 브로커 헬스 대기 (/dashboard/auth-mode — 인증 없이 200)
Write-Host "[test-agents] 브로커 응답 대기 중..."
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8420/dashboard/auth-mode' -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {}
}
if (-not $ok) {
    Write-Host "[test-agents] 브로커 응답 없음 (30s) — comm-matrix/워커는 수동으로." -ForegroundColor Yellow
}

# 3) comm-matrix(review-gated) 적용
if ($ok) {
    Write-Host "[test-agents] comm-matrix(review-gated) 적용..."
    & "$here\apply-comm-matrix.bat"
}

# 4) 워커 탭들
foreach ($w in $workers) {
    Write-Host "[test-agents] 워커 $w 기동 (탭)..."
    & wt.exe -w 0 new-tab -d "$here\$w" --title "agora-$w" cmd /k "run.bat"
}

Write-Host ""
Write-Host "[test-agents] 완료 — 대시보드: http://127.0.0.1:8420/dashboard" -ForegroundColor Green
