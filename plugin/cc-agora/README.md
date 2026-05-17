# cc-agora

AgentAgora 워커 간 통신 코어 Claude Code 플러그인. 메시지 dispatch·broadcast·타깃 추천·conversation 종결 슬래시 4종과 운용 규칙 스킬(`agora-protocol`)을 제공한다.

운영자 셋업(spawn·팀 manifest·서버 런처)은 `cc-agora-ops` 플러그인으로 분리됐다. 역할 페르소나는 `cc-agora-<role>` 페르소나 플러그인이 담당한다.

## 슬래시 명령

| 슬래시 | 시그니처 | 동작 |
| ------ | -------- | ---- |
| `/cc-agora:invoke` | `<id> "<message>" [--reply-to --conv --expect --cc --closing --priority --deadline]` | 한 워커에 task dispatch. payload 자동 채움 + envelope 분리. |
| `/cc-agora:broadcast` | `"<message>" [--closing --priority --conv --expect]` | 모든 등록 워커에 fan-out. announcement·세션 종료 신호. |
| `/cc-agora:agora-target` | `"<task>"` | `agora.find` + 매칭으로 1순위 워커 추천. chaining 문자열 제안만 — 직접 발사 X. |
| `/cc-agora:agora-close` | `<conversation-id> [--reason="<text>"]` | conversation을 명시 종결. 다른 참여자에 `type=closing` payload 자동 dispatch. |
| `/cc-agora:agora-run-script` | `[<dir>]` | 워커 디렉토리에 OS에 맞는 채널 모드 실행 스크립트(`run.ps1`/`run.sh`)를 생성. |

## agora-protocol 스킬

`/cc-agora:agora-protocol`은 채널 모드 워커의 운용 규칙을 담은 참조 스킬이다. 워커가 채널 알림으로 깨어나 `agora.flush`로 인박스를 드레인하고, 처리 후 `agora.dispatch`로 답신하는 루프를 기술한다. 등록·해제는 `.mcp.json` 헤더로 자동 처리되므로 `agora.register`/`agora.unregister`를 명시적으로 호출하지 않는다.

각 슬래시의 상세 동작은 `skills/<name>/SKILL.md`에 있다. frontmatter `description`은 영어, 본문은 한국어 평서체.

## payload.py

`scripts/payload.py`의 `make_payload`가 `type` enum(`task | reply | closing | ack`)을 강제해 envelope·payload 분리를 보장한다(spec §5.3).

## 요구 사항

- Python 3.13+ (`agent_agora`가 설치돼 있어야 함).
- AgentAgora MCP 서버가 실행 중이어야 한다 (기본 `http://127.0.0.1:8420/mcp`).
