# agora.register cwd durability + 미들웨어 빈-헤더 가드 설계

작성일: 2026-06-03
브랜치(예정): `fix/register-cwd-durability`
선행 분석: 2026-06-03 리팩토링 워크플로 비판 6-A(cwd durability 버그)

## 1. 문제

`InstanceInfo`에 `cwd` 필드가 있고 `InstanceRegistry.register(cwd=...)`가 받지만,
두 경로의 상호작용으로 cwd가 durable하지 않다:

- `agora.register` MCP 도구(`server.py`)는 `cwd` 파라미터가 **없어** 도구로는 cwd를
  설정할 수 없다 — 오직 `AutoRegisterMiddleware`의 `X-Agora-CWD` 헤더로만 들어온다.
- `AutoRegisterMiddleware`는 **매 HTTP 요청**마다 헤더를 읽어 `existing.cwd != cwd`면
  재등록한다(`auto_register.py:43,51`). 헤더가 없으면 `cwd=""`(기본값).

따라서 (가상의) 도구나 이전 요청이 cwd를 `/work`로 세팅해도, `X-Agora-CWD` 헤더가
없는(또는 빈) **다음 요청에서 `existing.cwd("/work") != ""` → 빈 값으로 클로버**된다.
cwd는 매 요청 헤더가 실릴 때만 유지되는 셈이라, 도구 기반 설정은 durable하지 않다.

## 2. 설계 결정 — cwd 우선순위

**규칙: 비어있지 않은 값만 cwd를 갱신한다(empty doesn't clobber).**

- `agora.register(cwd=...)` 도구 인자가 비어있지 않으면 그 값으로 등록.
- `AutoRegisterMiddleware`는 `X-Agora-CWD` 헤더가 **비어있지 않을 때만** cwd를 갱신.
  빈/부재 헤더는 기존 등록 cwd를 **보존**한다(클로버 금지).
- 비어있지 않은 헤더는 last-non-empty-wins(현행 `test_cwd_change_triggers_update`
  동작 유지 — 명시적 새 경로는 갱신됨).

근거: cwd는 "이 워커가 어디서 도는가"라는 **안정적 정체성 메타데이터**다. 매 요청에
실리지 않는다고 사라지면 안 된다. 빈 헤더는 "정보 없음"이지 "cwd를 비우라"가 아니다.
RC-friendly 헤더 전달(backlog MCP RC 추적)과도 정합 — 헤더가 매 요청 안 와도 안정.

## 3. 비목표

- 헤더 cwd와 도구 cwd 충돌 시 복잡한 병합 — 단순 "비어있지 않은 최신 값" 규칙으로 충분.
- cwd 검증(경로 존재 등) — broker는 문자열 메타데이터로만 다룬다.
- 영속 — registry는 in-memory(현행 유지).

## 4. 범위

- `server.py` `agora.register`: `cwd: str = ""` 파라미터 추가 → `instance_registry.register(..., cwd=cwd)` 전달, 반환 dict에 `cwd` 포함.
- `auto_register.py` `AutoRegisterMiddleware.__call__`: `effective_cwd = cwd or existing.cwd`로
  비교·등록(빈 헤더가 기존 비-빈 cwd를 덮지 않게). 신규 등록(NotRegistered) 경로는 현행대로.

## 5. 테스트 (TDD)

- `test_auto_register.py`: 빈 `X-Agora-CWD` 헤더가 기존 비-빈 cwd를 **보존**(durability 회귀,
  현재 버그 노출). 기존 `test_cwd_change_triggers_update`(비-빈 헤더 갱신)·
  `test_cwd_header_is_captured`·`test_cwd_default_is_empty`는 그대로 통과해야 함.
- `test_v4_server_cwd.py`: `agora.register` 도구의 `cwd` 인자가 등록·반환에 반영됨.

## 6. 후속

- 패키지 재구성(`auto_register`는 평면 유지) 무관.
