# 인스턴스 CWD — 설계 (수집·노출)

- 작성일: 2026-05-19
- 상태: 설계 작성 → 유저 검토 대기
- 관련: `src/agent_agora/registry.py`, `src/agent_agora/auto_register.py`, `src/agent_agora/server.py`, `plugin/cc-agora-ops/templates/mcp.json.template`, `plugin/cc-agora-ops/scripts/spawn.py`

## 1. 배경 / 문제

워커(Claude Code 인스턴스)는 각자 자신의 디렉터리에서 돈다. 다른 워커나 운영자가 "이 인스턴스가 어디서 동작하는가"를 알아야 할 때가 있다(좌표 파악, 워커 위치 기반 조율 등). 현재 레지스트리(`InstanceInfo`)는 `instance_id`·`role`·`description` 등은 갖지만 **CWD(작업 디렉터리) 정보가 없다.**

## 2. 목표 / 비목표

**목표** — 각 워커의 CWD를 등록 시점에 수집해 레지스트리에 보관하고, `agora.instances`·`agora.find`의 인스턴스 레코드 필드와 전용 도구 `agora.cwd`로 노출한다.

**비목표** — 런타임 CWD 동적 추적(워커가 worktree 등으로 이동 시 따라가기). 봇(`bot_registry` — 별도 namespace)의 CWD. `agora.register`(수동 등록 도구) 경로의 CWD 입력.

## 3. 수집 — 정적 등록 헤더

워커 등록 메타데이터(`role`·`description`)와 동일한 헤더 패턴을 따른다.

- **`mcp.json.template`** — `agentagora` HTTP 서버 항목의 `headers`에 `"X-Agora-Cwd": "{{CWD}}"`를 추가한다.
- **`spawn.py`** — `_render_mcp_json`에 `{{CWD}}` 치환을 추가한다. 값은 워커 디렉터리의 절대경로(`<target_dir>/<instance_id>`)를 forward-slash(`Path.as_posix()`)로 렌더한다. 경로는 ASCII이므로 HTTP 헤더 제약(latin-1)을 만족한다.
- **`auto_register.py`** — `CWD_HEADER = b"x-agora-cwd"`를 추가하고 `_extract`에서 cwd를 뽑는다. 미들웨어가 `register()`를 호출하는 두 분기(신규 등록 / 변경 시 재등록) 모두에 `cwd`를 전달한다. "변경 감지" 비교에 `existing.cwd != cwd`도 포함해, cwd가 바뀌면 재등록되게 한다.

CWD는 spawn된 워커 홈 디렉터리(정적)다. `X-Agora-Cwd` 헤더가 없는 워커(구버전 spawn 산출물·수동 구성)는 `cwd=""`로 graceful 처리된다.

## 4. 레지스트리 (`registry.py`)

- `InstanceInfo`에 `cwd: str = ""` 필드를 추가한다 — `description`과 동일하게 옵셔널·기본 빈 문자열. `frozen` dataclass이므로 필드 추가만으로 `replace()` 기반 갱신(`touch_last_seen`·`set_accepting`)은 영향 없다.
- `register()`에 `cwd: str = ""` 파라미터를 추가하고 `InstanceInfo(cwd=cwd, ...)`로 전달한다.

## 5. 노출 (`server.py`)

**필드** — `agora.instances`·`agora.find`가 반환하는 각 인스턴스 레코드에 `cwd`를 포함한다 (`role`·`description`과 나란히).

**전용 도구** — `agora.cwd`를 신설한다.
- 입력: `instance_id`.
- 동작: `registry.resolve_instance_id(instance_id)`로 조회해 `cwd`를 반환한다. 반환 형태는 `{"instance_id": ..., "cwd": ...}`.
- 미등록 `instance_id` → 다른 인스턴스 조회 도구와 동일하게 `NotRegisteredError`(→ 표준 에러 응답).
- cwd가 수집되지 않은 인스턴스 → `cwd`는 빈 문자열로 반환(에러 아님).

## 6. 파일 영향

| 파일 | 변경 |
|---|---|
| `src/agent_agora/registry.py` | `InstanceInfo.cwd` 필드, `register()` `cwd` 파라미터 |
| `src/agent_agora/auto_register.py` | `x-agora-cwd` 헤더 추출, 두 `register()` 분기에 전달, 변경 감지에 cwd 포함 |
| `src/agent_agora/server.py` | `agora.instances`·`agora.find` 레코드에 `cwd`, 신규 `agora.cwd` 도구 |
| `plugin/cc-agora-ops/templates/mcp.json.template` | `X-Agora-Cwd` 헤더 추가 |
| `plugin/cc-agora-ops/scripts/spawn.py` | `_render_mcp_json`에 `{{CWD}}` 치환 (워커 디렉터리 절대경로) |
| 관련 테스트 | 레지스트리·auto_register·server 도구·spawn 테스트 |

## 7. 검증 / 테스트

- `registry` — `InstanceInfo.cwd` 기본값 `""`; `register(cwd=...)`가 보존됨; `replace()` 갱신 후에도 cwd 유지.
- `auto_register` — `X-Agora-Cwd` 헤더가 있으면 `cwd`가 등록됨; 없으면 `""`; cwd만 바뀐 요청이 재등록을 트리거.
- `server` — `agora.instances`·`agora.find` 결과에 `cwd` 필드 존재; `agora.cwd(instance_id)`가 올바른 cwd 반환; 미등록 id면 에러; cwd 미수집이면 빈 문자열.
- `spawn` — 생성된 `.mcp.json`의 `agentagora` 헤더에 `X-Agora-Cwd`가 워커 디렉터리 절대경로(forward-slash)로 들어감; 렌더 결과가 유효 JSON.

## 8. 미해결

없음 — 범위·결정이 모두 확정됐다.
