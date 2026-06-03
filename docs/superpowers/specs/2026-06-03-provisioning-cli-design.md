# 최초 세팅 CLI (`agora-init`) 설계

**상태**: 구현 완료 (2026-06-03, 브랜치 `feat/provisioning-cli`)
**토픽**: AI를 거치지 않고 사람이 직접 실행하는, 팀 워커 + 통신 매트릭스 최초 부트스트랩 CLI

## 배경 / 문제

현재 워커 스폰 자산은 `plugin/cc-agora-ops/`에 있고 Claude(슬래시) 사용을 전제로 한다:

- `scripts/spawn.py` — 워커 1명 셋업(`CLAUDE.md`·`.mcp.json`·`run.bat`·`.claude/settings.local.json` 생성)
- `scripts/spawn_team.py` — `team.json` manifest로 팀 일괄 spawn
- `scripts/comm_matrix.py` — 매트릭스 GET/POST(HTTP, `AGORA_ADMIN_TOKEN`)
- `config/roles.json` — role → 페르소나 플러그인 매핑

빠진 것: **팀 + 스폰 위치 + 통신 매트릭스를 한 번에** 설정·생성하는 진입점(현 `spawn_team`은 매트릭스를 안 건드린다). 그리고 이 부트스트랩은 **AI 무개입**으로 사람이 워커/서버를 띄우기 *전에* 최초 1회 실행하는 결정론적 절차여야 한다.

## 목표 / 비목표

**목표**
- 사용자가 셸에서 직접 실행하는 콘솔 명령 `agora-init`.
- 대화형으로 팀 구성·스폰 위치·각 워커의 dispatch 허용 대상(`allow`)을 수집.
- 워커 디렉터리 파일들 + `team.json` + `comm-matrix.csv` + 서버 기동 스크립트를 생성.
- 입력을 manifest로 보존해 비대화형 재실행 가능.
- `src/agent_agora/` 안에 정식 기능으로 편입(plugin scripts는 *참고*만).

**비목표 (YAGNI)**
- 슬래시/Claude 통합(이 CLI는 AI 무관).
- `status`/`test-dispatch` 등 조회 서브커맨드.
- 워커 자동 기동(Claude Code 제어는 CLI 범위 밖 — 사용자가 `run.bat`/`run.sh` 실행).
- 서버 기동 및 서버 기동 스크립트 생성 — agora-init은 에이전트 스폰 전용, 서버는 `agent-agora`로 따로 띄운다.

## 위치 / 형태

`src/agent_agora/provisioning/` 새 서브패키지. `pyproject.toml`의 `[project.scripts]`에 콘솔 엔트리 `agora-init` 추가(기존 `agent-agora`·`agora-channel` 옆).

| 모듈 | 책임 |
|------|------|
| `cli.py` | argparse + 대화형 진입(`main()`). 인자 없으면 대화형, `--manifest`면 비대화형. |
| `manifest.py` | 확장 manifest 스키마·검증·(역)직렬화. |
| `spawn.py` | 워커 디렉터리 파일 생성(plugin `spawn.py` 참고 재작성). |
| `matrix.py` | `allow`→CSV 변환, 서버 가동 시 선택적 POST. |
| `roles.py` | role→플러그인 매핑(plugin `config/roles.json` 동등 — plugin은 `agent_agora`를 import하지 않는 3.11 독립 구조라 공유 불가, src 자체 보유). |
| `templates/` | `CLAUDE.md`·`.mcp.json`·`run.bat`·`settings.local.json`·`run-server.bat` 템플릿. |

> 순수 stdlib(argparse/input/json/csv/urllib). 매트릭스 POST만 네트워크(서버 가동 시).

## 대화형 흐름 (`input()`, cp949)

1. 스폰 위치(부모 dir) — 기본 cwd.
2. 서버 URL — 기본 `http://127.0.0.1:8420/mcp`.
3. 팀원 반복 입력:
   - `id` (1–32, 영숫자/-/_, 중복 금지)
   - `role` (roles 후보 표시; 미정의 시 `cc-agora-general` 폴백 경고)
   - `description` (한 줄)
   - `allow` (dispatch 가능 대상 id/정규식, 쉼표구분; 빈칸=없음, `*`=전체)
   - "더 추가? (y/n)"
4. 요약표 출력 → 최종 확인(y) → 생성.

## 확장 manifest 스키마

`spawn_dir/team.json`로 저장(입력 보존·재실행):

```json
{
  "version": 1,
  "spawn_dir": "C:/work/team",
  "server_url": "http://127.0.0.1:8420/mcp",
  "team": [
    {"id": "Coder1", "role": "coder", "description": "...", "allow": ["Reviewer1", ".*"]}
  ]
}
```

`spawn_dir`·`server_url`·`allow`가 기존 `team.json` 대비 추가분(없으면 기존 동작과 호환).

## 산출물

- `spawn_dir/team.json`
- 각 워커 디렉터리: `CLAUDE.md`·`.mcp.json`·`run.bat`(Windows) 또는 `run.sh`(POSIX, 실행 OS 자동 감지)·`.claude/settings.local.json`
- `spawn_dir/.agentagora/comm-matrix.csv`
- 서버가 이미 떠 있고 `AGORA_ADMIN_TOKEN` 있으면 매트릭스 즉시 POST. 아니면 파일만 — 서버가 시작 시 `.agentagora/comm-matrix.csv` 로드.

## `allow` → CSV 변환

- 행 = from(워커 id들 + `.*`), 열 = to(워커 id들 + `.*`).
- `from`의 `allow`가 `to`를 매치하면 셀 1, 아니면 0.
- self(from==to)는 `allow`에 명시 안 하면 0.
- operator는 매트릭스 무시(항상 allow)라 행렬에서 제외.
- 정확한 행/열 방향은 구현 시 `src/agent_agora/comm_matrix.py`의 `load_csv` 규약에 맞춘다(구현 전 확인 필요 항목).

## 비대화형 재실행

`agora-init --manifest team.json` → 프롬프트 생략, manifest 그대로 생성(재실행·CI). 대화형은 인자 없을 때.

## 검증 / 에러

- id 형식·중복(기존 `spawn_team` 규칙 동등).
- role 미정의 → `cc-agora-general` 폴백 + 경고(stderr).
- `allow`에 팀에 없는 id → 경고(정규식 패턴은 통과).
- 진행 메시지 stdout, 경고/에러 stderr(한국어).
- 기존 디렉터리 존재 시 `--force` 없으면 중단.

## 테스트 (TDD)

`tests/`에 정식 pytest:
- manifest 파싱·검증(정상/형식오류/중복/버전).
- `allow`→CSV 변환(프리셋 결과 골든).
- 비대화형 생성(`--manifest` → 산출 파일 존재·내용).
- 대화형은 stdin mock으로 핵심 경로 1개.
- 생성된 CSV가 `comm_matrix.CommMatrix.load_csv`로 round-trip 로드되는지(방향 정합 가드).

## 구현 시 확정된 사항

- `comm-matrix.csv` 행/열 방향 — `comm_matrix.py`의 `_weights[to_pat][from_pat]` 규약에 맞춰 **행=수신자(to), 열=발신자(from)**, 코너셀 없는 정사각 NxN으로 확정. `matrix.py`의 round-trip 테스트가 `CommMatrix.load_csv`로 방향 정합을 가드한다.
- `extraKnownMarketplaces` source — 기본 **github**(repo=`JuyeongYi/AgentAgora-ClaudePlugins`), 또는 **directory**(로컬 plugin 경로, `find_marketplace()` 탐색/프롬프트) 선택 가능(manifest `marketplace:{type,repo|path}`, 레거시 `marketplace_path`는 directory로 매핑). 별칭은 `marketplace.json`의 `name`과 같은 **`agent-agora`**로 고정해 `/plugin marketplace add`(식별자=name)와 충돌하지 않게 한다. `enabledPlugins`는 `<plugin>@agent-agora`.
- cp949 콘솔 안전 — 사용자 대면 print는 ASCII+한글만(em dash 등 cp949 밖 문자 금지). 회귀 테스트(`test_generate_output_is_cp949_safe`)로 가드.
- 실행 스크립트 크로스플랫폼 — `spawn_worker(platform=)`(기본 `sys.platform`)이 win32면 `run.bat`(ASCII+CRLF), POSIX면 `run.sh`(LF + 0o755 실행권한)를 생성. 서버 기동 스크립트는 생성하지 않음(에이전트 스폰 전용).
- 페르소나 선택 — 워커별 `persona:"none"`(대화형 'n')이면 역할 페르소나 플러그인을 켜지 않고 `cc-agora`(통신 코어)만 활성화하고 CLAUDE.md도 무페르소나 안내로 렌더. 미지정이면 role 매핑 플러그인(기존). `enabledPlugins`가 워커마다 달라진다.
- 대화형 role 다중 선택 — `tui.checkbox_select`(tty면 ↑↓·스페이스 화살표 체크박스, 비-tty/raw·VT 실패면 번호 입력 자동 폴백). 화살표 경로는 실제 터미널 전용이라 자동 테스트 불가 — 순수 토글 로직 `_toggle_step`과 번호 폴백만 가드한다. 선택 role마다 워커 1명(id=PascalCase(role), description=role, persona·통신 allow는 공통 1회 입력). 워커별 세밀 제어는 비대화형 manifest.
- plugin `cc-agora-ops/scripts/spawn.py`와의 중복은 의도적 수용(정식 버전은 src). 추후 plugin이 src를 얇게 호출하도록 정리할지는 별건.
