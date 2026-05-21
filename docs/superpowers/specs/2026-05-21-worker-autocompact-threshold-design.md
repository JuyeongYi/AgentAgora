# 워커 autoCompact 임계값 강제 — 설계

- 작성일: 2026-05-21
- 상태: 설계 작성 → 유저 검토 대기
- 관련: `plugin/cc-agora-ops/scripts/spawn.py`, `plugin/cc-agora-structure/scripts/structure_spawn.py`

## 1. 배경 / 문제

장기 실행 채널 모드 워커가 컨텍스트 가득 차서 멈추는 사례가 관측됨. 원인은 워커가 적절한 시점에 `/compact`를 트리거하지 못해 input tokens가 컨텍스트 wall에 도달.

워커 자력으로 `/compact`를 트리거하는 공식 메커니즘은 없음 — 에이전트 응답에 `/compact` 텍스트를 출력해도 harness가 인터셉트하지 않고(non-interactive 모드), `Compact` 도구는 존재하지 않으며, hook은 compact에 반응할 뿐 능동 발화 불가. 외부에서 stdin 파이프로 `/compact`를 주입하려면 launcher 인프라가 필요한데 현재 워커는 `wt.exe` 탭에서 인터랙티브로 도니까 stdin이 사용자(터미널) 차지 — launcher 변경은 과한 작업.

Claude Code는 `autoCompactEnabled: true`일 때 input tokens가 컨텍스트의 ~95%를 넘으면 자동 compact함. 이 임계값은 환경변수 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`로 조정 가능 (default 95, 0-100 정수).

## 2. 목표 / 비목표

**목표** — 워커가 컨텍스트 wall에 도달하기 전에 자주 compact하도록 임계값을 60%로 강제. 변경은 워커 기동 스크립트(`run.bat`) 두 곳에 환경변수 한 줄 추가에 한정.

**비목표** — task 단위 "dispatch 후 즉시 compact" 정확성 (공식 API 없음 — 운영자가 받아들인 trade-off). launcher/IPC 인프라 추가. 운영자 인터랙티브 세션의 autoCompact 동작 변경 (운영자는 자신의 세션에선 OFF로 두기를 선호 — 그 설정은 보존).

## 3. 변경

### `plugin/cc-agora-ops/scripts/spawn.py` — `_RUN_BAT` 상수

`set CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60` 한 줄을 `claude` 실행 직전에 삽입:

```bat
@echo off
REM 채널 모드 워커 기동. agora-channel은 공식 allowlist에 없는 자작 채널이라
REM --dangerously-load-development-channels 플래그가 필요하다.
set CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60
claude --dangerously-load-development-channels server:agora-channel %*
```

### `plugin/cc-agora-structure/scripts/structure_spawn.py` — `render_staging` 안의 run.bat 문자열

같은 한 줄을 같은 위치에 삽입:

```bat
@echo off
REM Channel-mode worker. agora-channel needs the development-channels flag.
set CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60
claude --dangerously-load-development-channels server:agora-channel %*
```

## 4. 임계값 = 60% — 근거

- 기본 95%는 wall에 너무 가까움 — dispatch 도중에 발화하지 못하는 케이스 가능.
- 60%는 한 task 분량의 응답(보통 컨텍스트의 20-30%)이 들어가도 직전 compact 발화점에서 충분히 떨어져 있음.
- 너무 낮으면(40 이하) compact가 잦아져 컨텍스트 손실·응답성 손실.
- 환경변수라 운영자가 워커 spawn 시 추가 override 가능 (향후 `--autocompact-pct` CLI 옵션 추가 여지가 있으나 본 spec 범위 외).

## 5. 파일 영향

| 파일 | 변경 |
|---|---|
| `plugin/cc-agora-ops/scripts/spawn.py` | `_RUN_BAT` 상수에 `set CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60` 한 줄 |
| `plugin/cc-agora-structure/scripts/structure_spawn.py` | `render_staging` 안의 run.bat 문자열에 같은 한 줄 |
| `tests/test_plugin_spawn.py` | 렌더된 run.bat에 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60` 라인 존재 검증 |
| `tests/test_structure_spawn.py` | 같은 검증을 `render_staging` 결과의 run.bat에 추가 |

## 6. 검증 / 테스트

- `test_plugin_spawn.py` — `do_spawn`이 만든 워커 디렉터리의 `run.bat`에 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60` 라인이 있는지 (substring 검증).
- `tests/test_structure_spawn.py` — 기존 `test_render_creates_expected_files` 또는 신규 테스트로 `render_staging`이 쓴 `run.bat`에 같은 라인이 있는지 검증.

## 7. 미해결

없음 — 범위·결정 모두 확정.
