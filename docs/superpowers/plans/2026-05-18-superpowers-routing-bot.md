# superpowers 라우팅 봇 — 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `delegation_request` 스키마를 구독하는 `AgoraBot` 서브클래스(라우팅 봇)를 구현해, 페르소나 워커가 다른 역할에 위임이 필요할 때 라우팅 봇이 대상 인스턴스를 찾아 메시지를 직접 전달하도록 한다.

**Architecture:** 설계 spec §5·§10·§12(플랜 8) 기준. 페르소나 워커가 `agora.dispatch` (target 생략 — schema-routed)로 `delegation_request` 메시지를 emit하면, 라우팅 봇이 이를 수신한다. 봇의 `handle()`은 `agora.find`로 `to_persona`/`to_capability` 값에 해당하는 워커 인스턴스를 조회하고, `self.emit(target=...)` (`agora.bot_emit(target=...)`)으로 해당 워커의 인박스에 `payload`를 직접 전달한다.

**Tech Stack:** Python, AgentAgora `AgoraBot` SDK, pytest.

---

## 파일 구조

```
src/agent_agora/
  server.py           agora.bot_emit 도구에 target 파라미터 추가 (Task 1)
  dispatcher.py       Dispatcher.bot_emit에 target 파라미터 추가 (Task 1)
  bot.py              AgoraBot.emit()에 target 파라미터 추가 (Task 1)
tests/
  test_v4_bot_emit_target.py   bot_emit target 확장 단위 테스트 (Task 1)
plugin/superpowers/routing-bot/
  routing_bot.py          AgoraBot 서브클래스 + main()
  run-bot.bat             Windows 런처
  run-bot.sh              Unix 런처
  tests/
    test_routing_bot.py   단위 테스트 (FakeSession 패턴, 서버 불필요)
    conftest.py           sys.path 설정
.agentagora/
  schemas.jsonl           신규 생성 — delegation_request 스키마 포함
```

**배치 위치 결정:** `plugin/superpowers/routing-bot/`에 배치한다.
`examples/`는 데모/교육용 디렉토리이고, 라우팅 봇은 superpowers 페르소나 생태계의 실운영 컴포넌트다. `plugin/superpowers/` 아래 두면 (a) 관련 컴포넌트가 한 곳에 모이고, (b) 통합 플랜(플랜 9)에서 `agora-setup` 연동 시 경로 추론이 단순해진다.

---

## Task 1: `agora.bot_emit` `target` 확장 — TDD

**목표:** 봇이 `agora.bot_emit(target=<instance_id>)`를 호출하면 해당 워커의 인박스에 직접 메시지가 전달된다. 이것이 라우팅 봇의 SDK 선행 조건이다 (spec §10).

**변경 범위:** `server.py` (MCP 도구 시그니처), `dispatcher.py` (`Dispatcher.bot_emit`), `bot.py` (`AgoraBot.emit`). 기존 `in_reply_to`/schema fan-out 동작은 변경 없다 — `target` 없을 때 기존 경로, `target` 있을 때 신규 경로.

### 1-1. 테스트 먼저 작성 (RED)

- [ ] `tests/test_v4_bot_emit_target.py` 파일 생성 (전체 내용):

  ```python
  """agora.bot_emit target 파라미터 확장 단위 테스트.

  FakeSession 패턴(test_v4_bot_sdk.py)을 그대로 따른다.
  Dispatcher 레벨 통합 테스트는 test_v4_wait_notify.py 패턴을 따른다.
  """
  from __future__ import annotations

  import asyncio
  import json

  import pytest

  from agent_agora.bot import AgoraBot


  # ── FakeSession 헬퍼 ─────────────────────────────────────────────────────────

  class _FakeItem:
      def __init__(self, text: str) -> None:
          self.text = text


  class _FakeResult:
      def __init__(self, payload: dict) -> None:
          self.content = [_FakeItem(json.dumps(payload, ensure_ascii=False))]


  class FakeSession:
      def __init__(self, responses: dict | None = None) -> None:
          self.calls: list[tuple[str, dict]] = []
          self.responses = responses or {}

      async def initialize(self) -> None:
          pass

      async def call_tool(self, name: str, args: dict) -> _FakeResult:
          self.calls.append((name, args))
          return _FakeResult(self.responses.get(name, {"status": "ok"}))

      def emit_calls(self) -> list[dict]:
          return [a for n, a in self.calls if n == "agora.bot_emit"]


  # ── 테스트용 봇 ──────────────────────────────────────────────────────────────

  class _TargetEmitBot(AgoraBot):
      INSTANCE_ID = "t_target_emit"
      SUBSCRIBE_SCHEMAS = ["x"]

      async def handle(self, cmd):
          # 직접 target을 지정해 emit
          await self.emit(
              {"msgtype": "worker_freeform", "type": "task",
               "from": self.INSTANCE_ID, "ts": self.now(), "message": "hi"},
              target="worker-001",
          )
          return None


  # ── 테스트 1: emit(target=...) → agora.bot_emit에 target이 전달된다 ──────────

  @pytest.mark.asyncio
  async def test_emit_with_target_passes_target_to_bot_emit():
      """AgoraBot.emit(target=X) → agora.bot_emit 호출 시 target=X가 포함돼야 한다."""
      bot = _TargetEmitBot()
      bot._session = FakeSession()

      await bot._dispatch({"id": "cmd-1", "source": "worker-000", "payload": {"x": 1}})

      emits = bot._session.emit_calls()
      assert len(emits) == 1, "bot_emit이 1회 호출돼야 한다"
      assert emits[0].get("target") == "worker-001", (
          "target이 agora.bot_emit 인자로 전달돼야 한다")
      # in_reply_to는 None이어야 한다 (target 지정 시 명시적 대상이므로 reply 불필요)
      assert emits[0].get("in_reply_to") is None


  # ── 테스트 2: emit(target=None) → 기존 동작 유지 (in_reply_to 경로) ─────────

  class _NoTargetBot(AgoraBot):
      INSTANCE_ID = "t_no_target"
      SUBSCRIBE_SCHEMAS = ["x"]

      async def handle(self, cmd):
          await self.emit(
              {"msgtype": "bot_reply", "from": self.INSTANCE_ID,
               "ts": self.now(), "result": "ok"},
          )
          return None


  @pytest.mark.asyncio
  async def test_emit_without_target_uses_in_reply_to():
      """AgoraBot.emit(target 미지정) → agora.bot_emit에 in_reply_to가 전달된다."""
      bot = _NoTargetBot()
      bot._session = FakeSession()

      await bot._dispatch({"id": "cmd-2", "source": "worker-000", "payload": {}})

      emits = bot._session.emit_calls()
      assert len(emits) == 1
      # target 없음 (또는 None)
      assert emits[0].get("target") is None
      # in_reply_to = 현재 cmd id
      assert emits[0].get("in_reply_to") == "cmd-2"
  ```

  경로: `tests/test_v4_bot_emit_target.py`

- [ ] 테스트를 실행해 FAIL을 확인한다:
  ```powershell
  cd "C:/Users/jylee/source/AgentAgora"
  uv run --extra dev python -m pytest tests/test_v4_bot_emit_target.py -v
  ```
  기대: `test_emit_with_target_passes_target_to_bot_emit` FAILED (현재 `emit()`에 `target` 파라미터 없음). `test_emit_without_target_uses_in_reply_to`는 PASSED 가능 — 중요한 건 첫 번째가 RED.

- [ ] git add + commit:
  ```powershell
  git add tests/test_v4_bot_emit_target.py
  git commit -m "test: agora.bot_emit target 파라미터 확장 테스트 추가 (RED)"
  ```

### 1-2. 구현 (GREEN)

**분석:** 세 파일에 최소한의 additive 변경만 한다.

- `dispatcher.py` `Dispatcher.bot_emit`: `target: str | None = None` 파라미터 추가. `target`이 주어지면 `_registry.resolve_instance_id(target)` 또는 `_bot_registry.resolve_instance_id(target)` 검증 후 `_enqueue(target, "primary")`. `reply_target` / schema fan-out 경로는 그대로 유지.
- `server.py` `agora_bot_emit` 도구: `target: str | None = None` 파라미터 추가. `dispatcher.bot_emit(... , target=target)` 전달.
- `bot.py` `AgoraBot.emit()`: `target: str | None = None` 파라미터 추가. `target`이 있으면 `agora.bot_emit` 호출 시 `target=target`을 인자에 포함하고 `in_reply_to`를 None으로(reply 불필요). 없으면 기존 경로 그대로.

- [ ] `src/agent_agora/dispatcher.py` 수정 — `bot_emit` 시그니처 및 구현:

  ```python
  # 변경 전 (line ~469):
  async def bot_emit(
      self,
      source: str,
      payload: Any,
      in_reply_to: str | None = None,
  ) -> dict[str, Any]:
      """봇 결과 emit (결정 25). in_reply_to 지정 시 원 메시지의 source로 라우팅,
      미지정 시 payload msgtype 구독 봇에 schema-routed fan-out. 항상 observer cc."""
  ```

  ```python
  # 변경 후:
  async def bot_emit(
      self,
      source: str,
      payload: Any,
      in_reply_to: str | None = None,
      target: str | None = None,
  ) -> dict[str, Any]:
      """봇 결과 emit (결정 25).

      target 지정 시: 해당 워커/봇 인박스에 직접 전달 (라우팅 봇용 — spec §10).
      in_reply_to 지정 시: 원 메시지의 source로 라우팅.
      둘 다 미지정 시: payload msgtype 구독 봇에 schema-routed fan-out.
      항상 observer cc.
      target과 in_reply_to를 동시에 지정하면 ValueError.
      """
  ```

  그리고 함수 본문에서 `reply_target` 설정 직전에 target 검증을 추가한다:

  ```python
  # 기존:
  reply_target: str | None = None
  if in_reply_to is not None:
      reply_target = self._conv.source_of(in_reply_to)
      if reply_target is None:
          reply_target = self._persistence.lookup_source_for(in_reply_to)
  subscriber_bots: list[str] = []
  if in_reply_to is None:
      subscriber_bots = sorted(self._bot_registry.subscribers_of(msgtype))
  ```

  ```python
  # 변경 후:
  if target is not None and in_reply_to is not None:
      raise ValueError("target과 in_reply_to를 동시에 지정할 수 없습니다")
  reply_target: str | None = None
  if target is not None:
      # target을 워커 또는 봇 레지스트리에서 검증 — 미등록이면 NotRegisteredError
      if not self._bot_registry.is_bot(target):
          self._registry.resolve_instance_id(target)  # 워커 미등록 시 raise
      reply_target = target
  elif in_reply_to is not None:
      reply_target = self._conv.source_of(in_reply_to)
      if reply_target is None:
          reply_target = self._persistence.lookup_source_for(in_reply_to)
  subscriber_bots: list[str] = []
  if target is None and in_reply_to is None:
      subscriber_bots = sorted(self._bot_registry.subscribers_of(msgtype))
  ```

  `_enqueue(reply_target, "primary")` 는 그대로 유지된다 — `target` 지정 시 `reply_target = target`이 되어 기존 `_enqueue` 경로를 타기 때문이다.

- [ ] `src/agent_agora/server.py` 수정 — `agora_bot_emit` 도구 시그니처 및 `dispatcher.bot_emit` 호출:

  ```python
  # 변경 전:
  @mcp.tool(name="agora.bot_emit")
  async def agora_bot_emit(
      ctx: Context,
      payload: dict,
      in_reply_to: str | None = None,
  ) -> str:
      """Emit a bot result. Bots only. in_reply_to 지정 시 원 caller로,
      미지정 시 payload msgtype 구독 봇에 fan-out (결정 25)."""
  ```

  ```python
  # 변경 후:
  @mcp.tool(name="agora.bot_emit")
  async def agora_bot_emit(
      ctx: Context,
      payload: dict,
      in_reply_to: str | None = None,
      target: str | None = None,
  ) -> str:
      """Emit a bot result. Bots only.

      target 지정 시 해당 워커/봇 인박스에 직접 전달 (라우팅 봇용).
      in_reply_to 지정 시 원 caller로 회신.
      둘 다 미지정 시 payload msgtype 구독 봇에 schema-routed fan-out (결정 25).
      target과 in_reply_to는 동시에 지정 불가.
      """
  ```

  그리고 `dispatcher.bot_emit` 호출 부분:

  ```python
  # 변경 전:
  result = await dispatcher.bot_emit(
      source=bot.instance_id, payload=payload, in_reply_to=in_reply_to)
  ```

  ```python
  # 변경 후:
  result = await dispatcher.bot_emit(
      source=bot.instance_id, payload=payload,
      in_reply_to=in_reply_to, target=target)
  ```

- [ ] `src/agent_agora/bot.py` 수정 — `AgoraBot.emit()` 시그니처:

  ```python
  # 변경 전:
  async def emit(self, payload: Any, *, in_reply_to: str | None = None) -> dict:
      """결과를 emit한다 (③ 경로 — handle 안에서 직접 호출 가능).

      payload가 `msgtype` 키를 가진 dict면 그대로 보내고, 아니면 `bot_reply`
      스키마로 감싼다. in_reply_to 생략 시 현재 처리 중인 cmd에 회신하고,
      처리 중인 cmd가 없으면 msgtype 구독 봇에게 schema-routed fan-out 된다.
      """
      if in_reply_to is None:
          in_reply_to = self._current_cmd_id
      if not (isinstance(payload, dict) and "msgtype" in payload):
          payload = {
              "msgtype": "bot_reply",
              "from": self.INSTANCE_ID,
              "ts": self.now(),
              "result": payload,
          }
      res = _result_json(await self.session.call_tool(
          "agora.bot_emit", {"payload": payload, "in_reply_to": in_reply_to}))
  ```

  ```python
  # 변경 후:
  async def emit(
      self,
      payload: Any,
      *,
      in_reply_to: str | None = None,
      target: str | None = None,
  ) -> dict:
      """결과를 emit한다 (③ 경로 — handle 안에서 직접 호출 가능).

      payload가 `msgtype` 키를 가진 dict면 그대로 보내고, 아니면 `bot_reply`
      스키마로 감싼다.

      target 지정 시: 해당 워커/봇 인박스에 직접 전달. in_reply_to를 쓰지 않는다.
      target 미지정 시: in_reply_to 생략 시 현재 처리 중인 cmd에 회신하고,
      처리 중인 cmd가 없으면 msgtype 구독 봇에게 schema-routed fan-out 된다.
      """
      args: dict = {"payload": payload}
      if target is not None:
          args["target"] = target
          # target 직접 지정 시 in_reply_to 불필요 (서버가 동시 지정을 거부)
      else:
          effective_reply_to = in_reply_to if in_reply_to is not None else self._current_cmd_id
          if effective_reply_to is not None:
              args["in_reply_to"] = effective_reply_to
      if not (isinstance(payload, dict) and "msgtype" in payload):
          args["payload"] = {
              "msgtype": "bot_reply",
              "from": self.INSTANCE_ID,
              "ts": self.now(),
              "result": payload,
          }
      res = _result_json(await self.session.call_tool("agora.bot_emit", args))
  ```

  나머지 두 줄(`if "error" in res` / `self._emitted = True` / `return res`)은 그대로 유지.

- [ ] 테스트를 실행해 GREEN을 확인한다:
  ```powershell
  cd "C:/Users/jylee/source/AgentAgora"
  uv run --extra dev python -m pytest tests/test_v4_bot_emit_target.py -v
  ```
  기대 출력:
  ```
  tests/test_v4_bot_emit_target.py::test_emit_with_target_passes_target_to_bot_emit  PASSED
  tests/test_v4_bot_emit_target.py::test_emit_without_target_uses_in_reply_to        PASSED
  2 passed
  ```

- [ ] 전체 테스트 스위트가 깨지지 않음을 확인한다:
  ```powershell
  uv run --extra dev python -m pytest tests/ -v --tb=short
  ```
  기대 출력: 기존 테스트 전부 PASSED. 특히 `test_v4_bot_sdk.py`의 회신 계약 테스트가 모두 PASSED임을 확인.

- [ ] git add + commit:
  ```powershell
  git add src/agent_agora/dispatcher.py
  git add src/agent_agora/server.py
  git add src/agent_agora/bot.py
  git commit -m "feat: agora.bot_emit target 파라미터 추가 — 봇이 특정 워커 인박스에 직접 전달 가능 (GREEN)"
  ```

---

## Task 2: `delegation_request` 스키마 정의 + `.agentagora/schemas.jsonl` 생성

**목표:** 서버 기동 시 `delegation_request` 스키마가 자동 로드된다.

- [ ] `.agentagora/` 디렉토리가 없으면 생성한다:
  ```powershell
  New-Item -ItemType Directory -Force "C:/Users/jylee/source/AgentAgora/.agentagora"
  ```

- [ ] `.agentagora/schemas.jsonl` 파일을 생성한다. 이 파일은 서버 기동 시 `ensure_schemas_file` / `load_schemas_into`로 로드되는 프로젝트 고유 스키마 목록이다. `default_schemas.jsonl` 항목은 포함하지 않는다 — 서버가 번들 파일에서 먼저 로드하고, 이 파일에서 추가 항목을 로드한다.

  파일 전체 내용 (`C:/Users/jylee/source/AgentAgora/.agentagora/schemas.jsonl`):
  ```jsonl
  {"name":"delegation_request","kind":"bot-task","purpose":"페르소나 워커 간 위임 요청. 발신 페르소나가 대상 페르소나(또는 역할)에게 작업을 넘길 때 사용한다. 라우팅 봇이 구독해 대상 워커를 찾아 payload를 전달한다.","body":{"type":"object","required":["msgtype","from_persona","payload"],"properties":{"msgtype":{"type":"string","const":"delegation_request"},"from_persona":{"type":"string","description":"위임하는 페르소나 instance_id"},"to_persona":{"type":"string","description":"대상 페르소나 instance_id. to_capability와 둘 중 하나는 필수."},"to_capability":{"type":"string","description":"대상 역할/역량 키워드. agora.find 검색어로 쓴다. to_persona 미지정 시 필수."},"payload":{"type":"object","description":"대상 워커에게 그대로 전달할 작업 본문. worker_freeform 또는 대상이 이해하는 스키마."},"context_summary":{"type":"string","description":"현재까지 작업 컨텍스트 요약. 대상 워커가 빠르게 파악할 수 있도록 제공한다."}},"additionalProperties":false}}
  ```

  **스키마 필드 설명:**
  | 필드 | 필수 | 설명 |
  |---|---|---|
  | `msgtype` | 필수 | `"delegation_request"` 고정 |
  | `from_persona` | 필수 | 위임하는 인스턴스 id |
  | `to_persona` | 조건부 | 대상 instance_id 직접 지정 (우선) |
  | `to_capability` | 조건부 | 역할 키워드 — `to_persona` 없을 때 `agora.find` 검색어 |
  | `payload` | 필수 | 대상에게 전달할 실제 작업 본문 |
  | `context_summary` | 선택 | 컨텍스트 요약 (대상 워커 온보딩용) |

  `to_persona`와 `to_capability` 중 하나는 반드시 있어야 한다. JSON Schema의 `anyOf`로 표현하면 body가 복잡해지므로, 런타임 유효성 검사(`handle()` 진입부)에서 둘 다 없는 경우를 명시적으로 처리한다.

- [ ] 스키마 파싱이 정상임을 확인한다 (서버 없이):
  ```powershell
  cd "C:/Users/jylee/source/AgentAgora"
  uv run python -c "
  from agent_agora.schemas import parse_schema_lines
  from pathlib import Path
  lines = parse_schema_lines(Path('.agentagora/schemas.jsonl').read_text('utf-8'))
  print('parsed:', [l['name'] for l in lines])
  assert lines[0]['name'] == 'delegation_request'
  print('OK')
  "
  ```
  기대 출력:
  ```
  parsed: ['delegation_request']
  OK
  ```

- [ ] `.gitignore` 확인: `.agentagora/`는 이미 `.gitignore`에 등록돼 있다. `schemas.jsonl`은 런타임 데이터(DB, 파일 스토어)와 달리 소스 관리 대상이다 — 예외로 추적한다:
  ```powershell
  git check-ignore -v .agentagora/schemas.jsonl
  ```
  ignore가 적용 중이면 `.gitignore`에 예외 라인을 추가한다:
  ```
  !.agentagora/schemas.jsonl
  ```
  그런 다음 git add:
  ```powershell
  git add -f .agentagora/schemas.jsonl   # -f: gitignore 무시하고 강제 추가
  git add .gitignore                     # .gitignore 예외 라인 변경도 함께 커밋
  git commit -m "feat: delegation_request 스키마 추가 (.agentagora/schemas.jsonl)"
  ```

---

## Task 3: 라우팅 봇 `handle()` 로직 — TDD (테스트 먼저)

**목표:** `handle()`의 라우팅 판단 로직을 서버 없이 검증하는 테스트를 작성하고, 테스트가 FAIL(skip)하는 것을 확인한다.

- [ ] 디렉토리 생성:
  ```powershell
  New-Item -ItemType Directory -Force "C:/Users/jylee/source/AgentAgora/plugin/superpowers/routing-bot/tests"
  ```

- [ ] `plugin/superpowers/routing-bot/tests/test_routing_bot.py` 파일 생성 (전체 내용):

  ```python
  """라우팅 봇 단위 테스트 — FakeSession으로 서버 없이 handle() 로직 검증.

  test_v4_bot_sdk.py 패턴을 그대로 따른다:
  - FakeSession / _FakeResult 재사용
  - bot._session을 직접 주입해 handle() + _dispatch()만 테스트
  """
  from __future__ import annotations

  import json

  import pytest

  from agent_agora.bot import AgoraBot


  # ── FakeSession 헬퍼 ─────────────────────────────────────────────────────────

  class _FakeItem:
      def __init__(self, text: str) -> None:
          self.text = text


  class _FakeResult:
      def __init__(self, payload: dict) -> None:
          self.content = [_FakeItem(json.dumps(payload, ensure_ascii=False))]


  class FakeSession:
      """호출을 기록하고, responses로 도구별 반환값을 지정한다."""

      def __init__(self, responses: dict | None = None) -> None:
          self.calls: list[tuple[str, dict]] = []
          self.responses = responses or {}

      async def initialize(self) -> None:
          pass

      async def call_tool(self, name: str, args: dict) -> _FakeResult:
          self.calls.append((name, args))
          return _FakeResult(self.responses.get(name, {"status": "ok"}))

      def emit_calls(self) -> list[dict]:
          return [a for n, a in self.calls if n == "agora.bot_emit"]

      def find_calls(self) -> list[dict]:
          return [a for n, a in self.calls if n == "agora.find"]


  # ── RoutingBot import ─────────────────────────────────────────────────────────

  try:
      from routing_bot import RoutingBot  # conftest.py가 sys.path 설정
      _IMPORT_OK = True
  except ImportError:
      _IMPORT_OK = False
      RoutingBot = None  # type: ignore[assignment,misc]


  pytestmark = pytest.mark.skipif(
      not _IMPORT_OK,
      reason="routing_bot.py 아직 없음 — Task 4에서 구현 후 통과 예정",
  )


  # ── 픽스처: agora.find 응답 빌더 ────────────────────────────────────────────

  def _find_response(instance_id: str, role: str = "planner") -> dict:
      return {
          "results": [
              {"kind": "worker", "instance_id": instance_id,
               "role": role, "description": f"{role} 워커"}
          ]
      }


  # ── 테스트 1: to_persona 직접 지정 → target으로 bot_emit ─────────────────────

  @pytest.mark.asyncio
  async def test_handle_to_persona_uses_target_emit():
      """to_persona가 있으면 agora.find 없이 곧바로 해당 instance_id를 target으로 bot_emit.

      Task 1에서 추가된 target 파라미터로 직접 전달 — 2-hop 우회 없이 한 번에.
      """
      bot = RoutingBot()
      bot._session = FakeSession()

      cmd = {
          "id": "cmd-1",
          "source": "superpowers-planner-001",
          "payload": {
              "msgtype": "delegation_request",
              "from_persona": "superpowers-planner-001",
              "to_persona": "superpowers-implementer-001",
              "payload": {"msgtype": "worker_freeform", "type": "task",
                          "from": "superpowers-planner-001",
                          "ts": "2026-05-18T00:00:00Z",
                          "message": "플랜 실행을 시작하세요."},
              "context_summary": "플랜 작성 완료",
          },
      }
      await bot._dispatch(cmd)

      emits = bot._session.emit_calls()
      assert len(emits) == 1, "bot_emit이 정확히 1회 호출돼야 한다"
      # target이 to_persona여야 한다
      assert emits[0].get("target") == "superpowers-implementer-001", (
          "target이 agora.bot_emit에 전달돼야 한다")
      # in_reply_to는 없어야 한다 (target 직접 지정 경로)
      assert emits[0].get("in_reply_to") is None
      # 전달 payload는 delegation_request.payload여야 한다
      assert emits[0]["payload"]["msgtype"] == "worker_freeform"
      assert emits[0]["payload"]["message"].startswith("플랜 실행을 시작하세요.")
      # agora.find는 호출되지 않아야 한다
      assert bot._session.find_calls() == []


  # ── 테스트 2: to_capability로 agora.find → 결과 target으로 bot_emit ──────────

  @pytest.mark.asyncio
  async def test_handle_to_capability_uses_agora_find_then_target_emit():
      """to_persona 없고 to_capability 있으면 agora.find로 대상 워커를 조회하고
      찾은 instance_id를 target으로 bot_emit한다."""
      bot = RoutingBot()
      bot._session = FakeSession(responses={
          "agora.find": _find_response("superpowers-implementer-001", role="implementer"),
      })

      cmd = {
          "id": "cmd-2",
          "source": "superpowers-planner-001",
          "payload": {
              "msgtype": "delegation_request",
              "from_persona": "superpowers-planner-001",
              "to_capability": "implementer",
              "payload": {"msgtype": "worker_freeform", "type": "task",
                          "from": "superpowers-planner-001",
                          "ts": "2026-05-18T00:00:00Z",
                          "message": "구현을 시작하세요."},
              "context_summary": "플랜 작성 완료",
          },
      }
      await bot._dispatch(cmd)

      find_calls = bot._session.find_calls()
      assert len(find_calls) == 1, "agora.find가 1회 호출돼야 한다"
      assert find_calls[0]["query"] == "implementer"

      emits = bot._session.emit_calls()
      assert len(emits) == 1, "bot_emit이 정확히 1회 호출돼야 한다"
      assert emits[0].get("target") == "superpowers-implementer-001"
      assert emits[0].get("in_reply_to") is None


  # ── 테스트 3: to_persona도 to_capability도 없으면 bot_error emit ─────────────

  @pytest.mark.asyncio
  async def test_handle_missing_target_emits_error():
      """to_persona, to_capability 둘 다 없으면 라우팅 불가 — 오류를 emit한다."""
      bot = RoutingBot()
      bot._session = FakeSession()

      cmd = {
          "id": "cmd-3",
          "source": "superpowers-planner-001",
          "payload": {
              "msgtype": "delegation_request",
              "from_persona": "superpowers-planner-001",
              # to_persona, to_capability 둘 다 없음
              "payload": {"msgtype": "worker_freeform", "type": "task",
                          "from": "superpowers-planner-001",
                          "ts": "2026-05-18T00:00:00Z",
                          "message": "..."},
          },
      }
      await bot._dispatch(cmd)

      # handle()이 ValueError를 raise → _dispatch가 bot_error를 emit
      emits = bot._session.emit_calls()
      assert len(emits) == 1
      assert emits[0]["payload"]["msgtype"] == "bot_error"
      assert ("to_persona" in emits[0]["payload"]["error_message"] or
              "to_capability" in emits[0]["payload"]["error_message"])


  # ── 테스트 4: agora.find 결과 없으면 bot_error emit ──────────────────────────

  @pytest.mark.asyncio
  async def test_handle_no_find_result_emits_error():
      """agora.find가 빈 결과를 반환하면 라우팅 불가 오류를 emit한다."""
      bot = RoutingBot()
      bot._session = FakeSession(responses={
          "agora.find": {"results": []},
      })

      cmd = {
          "id": "cmd-4",
          "source": "superpowers-planner-001",
          "payload": {
              "msgtype": "delegation_request",
              "from_persona": "superpowers-planner-001",
              "to_capability": "nonexistent-role",
              "payload": {"msgtype": "worker_freeform", "type": "task",
                          "from": "superpowers-planner-001",
                          "ts": "2026-05-18T00:00:00Z",
                          "message": "..."},
          },
      }
      await bot._dispatch(cmd)

      emits = bot._session.emit_calls()
      assert len(emits) == 1
      assert emits[0]["payload"]["msgtype"] == "bot_error"
      assert "nonexistent-role" in emits[0]["payload"]["error_message"]


  # ── 테스트 5: context_summary가 있으면 payload에 포함 ────────────────────────

  @pytest.mark.asyncio
  async def test_handle_context_summary_appended_to_payload():
      """context_summary가 있으면 전달하는 payload의 message에 요약이 추가된다."""
      bot = RoutingBot()
      bot._session = FakeSession()

      cmd = {
          "id": "cmd-5",
          "source": "superpowers-planner-001",
          "payload": {
              "msgtype": "delegation_request",
              "from_persona": "superpowers-planner-001",
              "to_persona": "superpowers-implementer-001",
              "payload": {"msgtype": "worker_freeform", "type": "task",
                          "from": "superpowers-planner-001",
                          "ts": "2026-05-18T00:00:00Z",
                          "message": "구현을 시작하세요."},
              "context_summary": "플랜: 3단계 TDD 사이클",
          },
      }
      await bot._dispatch(cmd)

      emits = bot._session.emit_calls()
      assert len(emits) == 1
      forwarded = emits[0]["payload"]
      # context_summary가 message에 포함되거나 별도 필드로 전달돼야 한다
      msg_text = forwarded.get("message", "")
      assert ("플랜: 3단계 TDD 사이클" in msg_text or
              forwarded.get("context_summary") == "플랜: 3단계 TDD 사이클")
  ```

- [ ] 테스트를 실행해 skip을 확인한다:
  ```powershell
  cd "C:/Users/jylee/source/AgentAgora"
  uv run --extra dev python -m pytest plugin/superpowers/routing-bot/tests/test_routing_bot.py -v
  ```
  기대 출력 (routing_bot.py 없으므로 skip):
  ```
  SSSSS   [100%]
  5 skipped
  ```
  **PASS가 나면 안 된다.**

- [ ] git add + commit:
  ```powershell
  git add plugin/superpowers/routing-bot/tests/test_routing_bot.py
  git commit -m "test: 라우팅 봇 handle() 단위 테스트 추가 (RED)"
  ```

---

## Task 4: `RoutingBot` 구현 — 테스트를 PASS시킨다

**목표:** `routing_bot.py`를 구현해 Task 3 테스트가 모두 PASS한다. Task 1의 `target` 파라미터로 대상 워커에게 직접 전달한다.

- [ ] `plugin/superpowers/routing-bot/tests/conftest.py` 생성 (전체 내용):
  ```python
  """pytest가 routing_bot.py를 찾을 수 있도록 sys.path에 부모 디렉토리를 추가한다."""
  import sys
  from pathlib import Path

  # plugin/superpowers/routing-bot/ 을 Python 경로에 추가
  _BOT_DIR = Path(__file__).parent.parent
  if str(_BOT_DIR) not in sys.path:
      sys.path.insert(0, str(_BOT_DIR))
  ```

- [ ] `plugin/superpowers/routing-bot/routing_bot.py` 파일 생성 (전체 내용):

  ```python
  """RoutingBot — superpowers 페르소나 간 위임 라우팅 봇.

  `delegation_request` 스키마를 구독한다. 페르소나 워커가
  다른 역할에 작업을 위임할 때 이 스키마로 메시지를 emit하면,
  이 봇이 대상 워커를 찾아 payload를 직접 전달한다.

  실행 (서버와 라우팅 봇을 함께 기동):
      python -m agent_agora --port 8420 --no-tls --no-timeout   # 터미널 1
      python plugin/superpowers/routing-bot/routing_bot.py       # 터미널 2

  Task 1에서 추가된 agora.bot_emit의 target 파라미터를 활용한다.
  봇 세션은 agora.dispatch를 호출할 수 없지만(서버 가드),
  agora.bot_emit(target=<instance_id>)으로 특정 워커 인박스에 직접 전달한다.
  """
  from __future__ import annotations

  import asyncio
  import json

  import httpx
  from mcp import ClientSession

  from agent_agora.bot import AgoraBot, _result_json

  _INSTANCE_ID = "bot_superpowers_router"


  class RoutingBot(AgoraBot):
      INSTANCE_ID = _INSTANCE_ID
      DESCRIPTION = "superpowers persona routing bot. Subscribes delegation_request, resolves target worker, and delivers payload directly via agora.bot_emit(target=...)."
      SUBSCRIBE_SCHEMAS = ["delegation_request"]

      # delegation_request 스키마는 .agentagora/schemas.jsonl에 등록되어
      # 서버 기동 시 permanent 스키마로 로드된다. 봇이 인라인 SCHEMAS로
      # 중복 등록하면 body 일치 시 idempotent이지만, permanent 스키마와
      # body가 달라지는 실수를 막기 위해 SCHEMAS를 선언하지 않는다.
      SCHEMAS = {}

      async def handle(self, cmd: dict):
          """delegation_request 1건을 처리한다.

          처리 흐름:
          1. payload에서 to_persona / to_capability 추출
          2. to_persona 있으면 곧바로 사용; 없으면 agora.find(to_capability)로 resolve
          3. self.emit(forwarded_payload, target=resolved_instance_id) 로 직접 전달
             — Task 1에서 추가된 agora.bot_emit target 파라미터 활용
          """
          p = cmd.get("payload") or {}
          from_persona: str = p.get("from_persona", cmd.get("source", "unknown"))
          to_persona: str | None = p.get("to_persona")
          to_capability: str | None = p.get("to_capability")
          inner_payload: dict = p.get("payload") or {}
          context_summary: str | None = p.get("context_summary")

          # 대상 검증
          if not to_persona and not to_capability:
              raise ValueError(
                  "delegation_request에 to_persona 또는 to_capability가 필요합니다. "
                  f"수신 메시지 source={from_persona}"
              )

          # to_capability로 agora.find 조회
          if not to_persona:
              find_result = await self._call_find(to_capability)  # type: ignore[arg-type]
              results = find_result.get("results", [])
              workers = [r for r in results if r.get("kind") == "worker"]
              if not workers:
                  raise ValueError(
                      f"to_capability='{to_capability}'에 해당하는 워커를 찾을 수 없습니다. "
                      "대상 페르소나 워커가 등록돼 있는지 확인하세요."
                  )
              to_persona = workers[0]["instance_id"]
              print(
                  f"[{self.INSTANCE_ID}] {from_persona} -> {to_persona} "
                  f"(capability='{to_capability}' resolve 결과)",
                  flush=True,
              )
          else:
              print(
                  f"[{self.INSTANCE_ID}] {from_persona} -> {to_persona} "
                  f"(to_persona 직접 지정)",
                  flush=True,
              )

          # context_summary를 message에 주입한다
          forwarded = dict(inner_payload)
          if context_summary:
              existing_msg = forwarded.get("message", "")
              if existing_msg:
                  forwarded["message"] = (
                      f"{existing_msg}\n\n[위임 컨텍스트] {context_summary}"
                  )
              else:
                  forwarded["context_summary"] = context_summary

          # agora.bot_emit(target=to_persona)으로 직접 전달.
          # Task 1에서 추가된 target 파라미터를 사용한다.
          # in_reply_to 없이 target만 지정 — 발신자 회신이 아닌 직접 push.
          await self.emit(forwarded, target=to_persona)
          return None  # 직접 emit했으므로 자동 회신 없음

      async def _call_find(self, query: str) -> dict:
          """agora.find를 호출해 워커를 검색한다."""
          result = await self.session.call_tool("agora.find", {"query": query})
          return _result_json(result)


  if __name__ == "__main__":
      asyncio.run(RoutingBot.main())
  ```

- [ ] 테스트를 실행해 PASS를 확인한다:
  ```powershell
  cd "C:/Users/jylee/source/AgentAgora"
  uv run --extra dev python -m pytest plugin/superpowers/routing-bot/tests/test_routing_bot.py -v
  ```
  기대 출력:
  ```
  test_routing_bot.py::test_handle_to_persona_uses_target_emit                    PASSED
  test_routing_bot.py::test_handle_to_capability_uses_agora_find_then_target_emit PASSED
  test_routing_bot.py::test_handle_missing_target_emits_error                     PASSED
  test_routing_bot.py::test_handle_no_find_result_emits_error                     PASSED
  test_routing_bot.py::test_handle_context_summary_appended_to_payload            PASSED
  5 passed
  ```

- [ ] 전체 테스트 스위트가 깨지지 않음을 확인한다:
  ```powershell
  uv run --extra dev python -m pytest tests/ -v --tb=short
  ```
  기대 출력: 기존 테스트 전부 PASSED.

- [ ] git add + commit:
  ```powershell
  git add plugin/superpowers/routing-bot/routing_bot.py
  git add plugin/superpowers/routing-bot/tests/conftest.py
  git add plugin/superpowers/routing-bot/tests/test_routing_bot.py
  git commit -m "feat: RoutingBot AgoraBot 서브클래스 구현 (GREEN) — target 파라미터로 직접 전달"
  ```

---

## Task 5: 런처 스크립트

**목표:** 서버가 떠 있을 때 `run-bot.bat` / `run-bot.sh` 한 줄로 봇을 기동할 수 있다.

- [ ] `plugin/superpowers/routing-bot/run-bot.bat` 생성 (전체 내용):
  ```bat
  @echo off
  REM superpowers 라우팅 봇 실행.
  REM 사전: AgentAgora 서버가 http://127.0.0.1:8420 에 떠 있어야 한다.
  REM   python -m agent_agora --port 8420 --no-tls --no-timeout
  REM AGORA_URL 환경변수로 서버 주소를 덮어쓸 수 있다.
  "%~dp0..\..\..\..\.venv\Scripts\python.exe" "%~dp0routing_bot.py" %*
  ```

  **경로 설명:** `%~dp0`는 `run-bot.bat`이 있는 `plugin/superpowers/routing-bot/`이다.
  `.venv`는 repo 루트에 있다. `routing-bot/ → superpowers/ → plugin/ → AgentAgora/` — 3단계 상위(`..\..\..`)이므로 `%~dp0..\..\..\`가 repo 루트다.

  경로가 맞는지 bat 파일을 작성하기 전에 확인한다:
  ```powershell
  Test-Path "C:/Users/jylee/source/AgentAgora/.venv/Scripts/python.exe"
  ```
  존재하면 진행. 없으면 `uv sync` 후 재확인.

- [ ] `plugin/superpowers/routing-bot/run-bot.sh` 생성 (전체 내용):
  ```bash
  #!/usr/bin/env bash
  # superpowers 라우팅 봇 실행 (Unix/macOS).
  # 사전: AgentAgora 서버가 http://127.0.0.1:8420 에 떠 있어야 한다.
  #   python -m agent_agora --port 8420 --no-tls --no-timeout
  # AGORA_URL 환경변수로 서버 주소를 덮어쓸 수 있다.
  set -euo pipefail
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
  exec "$REPO_ROOT/.venv/bin/python" "$SCRIPT_DIR/routing_bot.py" "$@"
  ```

- [ ] Unix 권한 설정 (Git 기록용):
  ```powershell
  git add plugin/superpowers/routing-bot/run-bot.bat
  git add plugin/superpowers/routing-bot/run-bot.sh
  ```
  Unix에서는 추가로:
  ```bash
  chmod +x plugin/superpowers/routing-bot/run-bot.sh
  git update-index --chmod=+x plugin/superpowers/routing-bot/run-bot.sh
  ```

- [ ] git commit:
  ```powershell
  git commit -m "feat: 라우팅 봇 런처 스크립트 추가 (run-bot.bat, run-bot.sh)"
  ```

---

## Task 6: 통합 검증

**목표:** 서버를 실제로 기동하고 라우팅 봇이 `delegation_request`를 수신해 대상 워커 인박스에 직접 전달하는 것을 확인한다.

- [ ] 터미널 1 — 서버 기동:
  ```powershell
  cd "C:/Users/jylee/source/AgentAgora"
  uv run python -m agent_agora --port 8420 --no-tls --no-timeout
  ```
  기대 출력에서 확인:
  ```
  [agora] schemas.jsonl 로드 완료: N개 스키마
  ```
  N에 `delegation_request`가 포함돼야 한다. 서버가 `Listening on http://127.0.0.1:8420`을 출력하면 OK.

- [ ] 터미널 2 — 라우팅 봇 기동:
  ```powershell
  cd "C:/Users/jylee/source/AgentAgora"
  plugin/superpowers/routing-bot/run-bot.bat
  ```
  기대 출력:
  ```
  [bot_superpowers_router] register_bot 완료 (구독: ['delegation_request']).
  [bot_superpowers_router] 수신 루프 시작 (mode=handler, subscribe=['delegation_request'], heartbeat=30000ms).
  ```

- [ ] 터미널 3 — 대상 워커와 발신 워커를 등록하고 delegation_request 발송:
  ```powershell
  cd "C:/Users/jylee/source/AgentAgora"
  uv run python -c "
  import asyncio, json, os
  from mcp import ClientSession
  from mcp.client.streamable_http import streamable_http_client

  AGORA_URL = os.environ.get('AGORA_URL', 'http://127.0.0.1:8420/mcp')

  def _rj(result):
      for item in result.content:
          t = getattr(item, 'text', None)
          if t:
              try:
                  d = json.loads(t)
                  if isinstance(d, dict): return d
              except: pass
      return {}

  async def main():
      async with streamable_http_client(AGORA_URL) as conn:
          async with ClientSession(conn[0], conn[1]) as s:
              await s.initialize()
              # 대상 워커 등록 (라우팅 봇이 이 인박스에 전달해야 한다)
              await s.call_tool('agora.register', {
                  'instance_id': 'test-implementer-001',
                  'role': 'implementer',
                  'description': 'test implementer worker'
              })
              # 발신 워커 등록
              await s.call_tool('agora.register', {
                  'instance_id': 'test-planner-001',
                  'role': 'planner',
                  'description': 'test planner worker'
              })
              r = _rj(await s.call_tool('agora.dispatch', {
                  'payload': {
                      'msgtype': 'delegation_request',
                      'from_persona': 'test-planner-001',
                      'to_persona': 'test-implementer-001',
                      'payload': {
                          'msgtype': 'worker_freeform',
                          'type': 'task',
                          'from': 'test-planner-001',
                          'ts': '2026-05-18T00:00:00Z',
                          'message': '라우팅 테스트 — target 직접 전달'
                      },
                      'context_summary': '통합 테스트'
                  }
              }))
              print('dispatch 결과:', json.dumps(r, ensure_ascii=False, indent=2))
              # 대상 워커 인박스 확인 — bot_emit(target=...) 으로 전달된 메시지가 있어야 한다
              inbox = _rj(await s.call_tool('agora.flush', {}))
              print('implementer inbox:', json.dumps(inbox, ensure_ascii=False, indent=2))
              await s.call_tool('agora.unregister', {})

  asyncio.run(main())
  "
  ```

  기대 출력 (터미널 3):
  ```
  dispatch 결과: {
    "dispatched_to": [{"instance_id": "bot_superpowers_router", "as": "subscribed"}, ...],
    ...
  }
  implementer inbox: {
    "commands": [{"payload": {"msgtype": "worker_freeform", "message": "라우팅 테스트 — target 직접 전달...", ...}, ...}]
  }
  ```

  기대 출력 (터미널 2 — 라우팅 봇):
  ```
  [bot_superpowers_router] test-planner-001 -> test-implementer-001 (to_persona 직접 지정)
  [bot_superpowers_router] handled <- test-planner-001
  ```

- [ ] 검증 완료 후 최종 전체 테스트:
  ```powershell
  cd "C:/Users/jylee/source/AgentAgora"
  uv run --extra dev python -m pytest tests/ plugin/superpowers/routing-bot/tests/ -v --tb=short
  ```
  기대 출력: 기존 테스트 + 라우팅 봇 테스트 전부 PASSED.

- [ ] git add + commit:
  ```powershell
  git add -u
  git commit -m "feat: superpowers 라우팅 봇 구현 완료 (delegation_request + agora.bot_emit target + AgoraBot + 런처 + 테스트)"
  ```

---

## Self-Review — Spec 커버리지 & 오픈 리스크

### Spec 커버리지

| Spec 항목 | 커버 여부 | 비고 |
|---|---|---|
| §5 `delegation_request` 스키마 필드 | 완료 | `from_persona`, `to_persona`, `to_capability`, `payload`, `context_summary` |
| §5 `.agentagora/schemas.jsonl` 등록 | 완료 | Task 2 |
| §5 라우팅 봇 `AgoraBot` 서브클래스 | 완료 | Task 4 |
| §5 `agora.find`로 대상 워커 resolve | 완료 | `to_capability` 경로 |
| §10 `agora.bot_emit` `target` 파라미터 추가 | 완료 | Task 1 — SDK 선행 확장 |
| §10 런처 스크립트 (`run-*.bat`/`.sh`) | 완료 | Task 5 |
| §12 봇 단위 테스트 | 완료 | FakeSession 패턴, 5개 케이스 |
| §12 배치 위치 결정 | 완료 | `plugin/superpowers/routing-bot/` |

### `agora.bot_emit` target 확장 — 설계 근거

**최소 침습 확인:** 코드를 직접 읽은 결과, 변경은 진짜 최소다.

`dispatcher.bot_emit`의 핵심 enqueue 경로는 이미 `reply_target: str | None`을 받아 `_enqueue(reply_target, "primary")`를 실행하는 구조다. `target` 파라미터를 추가하면 기존 `reply_target = self._conv.source_of(in_reply_to)` 경로를 타는 대신 `reply_target = target`으로 설정하면 된다 — 나머지 `_enqueue` 경로, observer bot fan-out, persistence 경로는 그대로 유지된다.

`AgoraBot.emit()`은 `call_tool("agora.bot_emit", {...})` 호출 dict를 조립하는 구조이므로, `target`을 인자에 추가하는 것이 전부다.

**기존 호출자 무영향:** `target=None`이 기본값이므로 기존 `emit()` / `agora.bot_emit` 호출은 모두 변경 없이 기존 경로를 탄다. `test_v4_bot_sdk.py`의 모든 테스트가 그대로 PASS여야 한다.

**주의 — `target` + `in_reply_to` 동시 지정:** `dispatcher.bot_emit`에서 두 파라미터를 동시에 지정하면 의미가 모호해지므로(어느 것이 우선인가) `ValueError`로 명시적으로 거부한다. `AgoraBot.emit()`도 `target`이 있으면 `in_reply_to`를 None으로 처리해 이 제약을 자연스럽게 따른다.

### 추가 오픈 포인트

- **`comm-matrix.csv` 게이팅:** 페르소나 간 위임 ACL은 통합 플랜(플랜 9)에서 설정된다. 현재 라우팅 봇은 ACL 없이 동작한다. `bot_emit(target=...)` 경로도 comm-matrix를 타지 않는다 — 봇의 emit은 워커의 `dispatch`가 아니기 때문이다. ACL이 필요하면 `dispatcher.bot_emit`에 위임 허용 검사를 추가한다.
- **`cc-agora-ops/config/roles.json`:** 7개 페르소나 role 매핑은 통합 플랜에서 추가된다.
- **`.agentagora/schemas.jsonl` Git 추적:** `.gitignore`가 `.agentagora/` 전체를 제외할 수 있다. Task 2에서 `!.agentagora/schemas.jsonl` 예외 라인 추가와 `git add -f`로 처리한다.
- **`target` 미등록 워커:** `dispatcher.bot_emit`에서 `_registry.resolve_instance_id(target)`이 `NotRegisteredError`를 던지면 `server.py`가 이를 JSON error로 반환한다. 라우팅 봇의 `_emit_error` 경로가 동작하므로 봇은 생존한다.
