# Backlog — 미뤄둔 작업

## 진행 중

- **wait-tool-gating** — `agora.wait_notify`(블로킹 long-poll)를 채널 모드 워커
  (Claude Code)의 MCP 도구 표면에서 들어내는 작업. spec 완료 —
  `docs/superpowers/specs/2026-05-18-wait-tool-gating-design.md`, 브랜치
  `wait-tool-gating`. 다음 단계는 구현 플랜 작성 → 구현 → 브랜치 마무리. 설계
  요지: `GET /channel/wait` HTTP 엔드포인트 신설(always-on), `agora-channel`
  어댑터·`AgoraBot` SDK를 HTTP로 전환, MCP `agora.wait_notify`는 기본 비등록 +
  `--add-wait` 플래그로만 등록.

## 기능 후보 — observability · 편의 도구

2026-05-15 워커 brainstorming에서 나온 미구현 제안. 6명의 워커 중 5명이
observability 결핍을 독립적으로 보고했다. (원본 제안서는 git 이력에 보존.)

- **`agora.transcript(conversation_id, since_ts?)`** — 한 conversation의 메시지
  시퀀스를 시간순 envelope 배열로 반환. 현재는 SQLite 직접 조회로만 가능하다.
- **`agora.coverage(command_id)`** — `expect_result=true`로 발사된 command의 응답
  커버리지(`responded` / `pending` / `deadline_ts`)를 한 호출로 조회.
- **`agora.reply(message, ...)`** — 최근 수신한 명령을 컨텍스트로 잡아 `in_reply_to`
  · `conversation_id` · `target` · `payload.from`을 자동으로 채우는 답신 헬퍼.
- **`agora.cancel(command_id)`** — 발신자가 아직 consume되지 않은 in-flight 명령을
  회수. 이미 consume됐으면 no-op + 사유 반환.

## 미수정 버그

- **register_bot 재등록 검증 실패 시 ref 오류** — `server.py`의 `agora_register_bot`은
  봇 재등록 시작 시점에 옛 스키마 ref를 먼저 해제한다. 그 후 검증이 실패하면
  (`unknown_msgtype` 등) 봇의 옛 등록은 `BotRegistry`에 그대로 살아 있는데 스키마
  ref만 날아가, 그 스키마가 잘못 해제될 수 있다. 정상 재등록·최초 등록엔 영향 없음 —
  재등록이 *검증 실패*하는 드문 경우만. register_bot의 스키마 ref 변경을 검증 통과
  후로 미루는 트랜잭션 순서 정리가 필요하다.
