# 인스턴스 CWD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 각 워커의 CWD를 등록 헤더로 수집해 레지스트리에 보관하고, `agora.instances`·`agora.find` 필드와 신규 `agora.cwd` 도구로 노출한다.

**Architecture:** `role`·`description`과 동일한 정적 등록-헤더 패턴. spawn된 워커 `.mcp.json`이 `X-Agora-Cwd` 헤더로 워커 디렉터리를 전달 → `auto_register` 미들웨어가 추출 → `InstanceRegistry`의 `InstanceInfo.cwd`에 저장 → MCP 도구로 노출. Python 코드 변경이라 각 Task는 TDD(실패 테스트 → 구현 → 통과).

**Tech Stack:** Python 3.13, dataclass 레지스트리, ASGI 미들웨어, FastMCP 도구, pytest.

**근거 스펙:** `docs/superpowers/specs/2026-05-19-instance-cwd-design.md`.

**대상 브랜치:** 구현은 master가 아닌 피처 브랜치에서 한다 (subagent-driven-development 가 브랜치를 만든다).

---

## Task 1: registry — `InstanceInfo.cwd` 필드 + `register()` cwd 파라미터

**Files:**
- Modify: `src/agent_agora/registry.py`
- Test: `tests/test_registry.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_registry.py`에 추가:

```python
def test_register_stores_cwd():
    reg = InstanceRegistry()
    info = reg.register(session_id="s1", instance_id="w1", cwd="C:/Users/x/source/Dep/w1")
    assert info.cwd == "C:/Users/x/source/Dep/w1"
    assert reg.resolve_instance_id("w1").cwd == "C:/Users/x/source/Dep/w1"


def test_register_cwd_defaults_to_empty():
    reg = InstanceRegistry()
    reg.register(session_id="s2", instance_id="w2")
    assert reg.resolve_instance_id("w2").cwd == ""


def test_cwd_survives_replace_based_updates():
    reg = InstanceRegistry()
    reg.register(session_id="s3", instance_id="w3", cwd="C:/dep/w3")
    reg.touch_last_seen("w3")
    reg.set_accepting("w3", False)
    assert reg.resolve_instance_id("w3").cwd == "C:/dep/w3"
```

`InstanceRegistry`·`InstanceInfo` 임포트는 파일 상단의 기존 임포트를 따른다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_registry.py -k cwd -v`
Expected: FAIL — `register()`에 `cwd` 인자가 없음 (`TypeError: unexpected keyword argument 'cwd'`).

- [ ] **Step 3: 구현**

`src/agent_agora/registry.py`:

`InstanceInfo` 데이터클래스에 `description` 필드 바로 다음 줄에 `cwd` 필드를 추가한다:

```python
    description: str = ""
    cwd: str = ""
    wait_mode: Literal["auto", "manual", "unknown"] = "unknown"
```

`register()` 시그니처에 `cwd` 파라미터를 추가하고(`description` 다음), `InstanceInfo(...)` 생성에 전달한다:

```python
    def register(
        self,
        session_id: str,
        instance_id: str,
        role: str = "worker",
        description: str = "",
        cwd: str = "",
        wait_mode: Literal["auto", "manual"] | None = None,
    ) -> InstanceInfo:
        info = InstanceInfo(
            instance_id=instance_id,
            session_id=session_id,
            role=role,
            registered_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            description=description,
            cwd=cwd,
            wait_mode=wait_mode if wait_mode is not None else "unknown",
        )
```

`touch_last_seen`·`set_accepting`은 `replace()`로 갱신하므로 새 필드를 따로 손댈 필요가 없다 — `cwd`가 자동 보존된다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_registry.py tests/test_v3_registry.py -v`
Expected: PASS — 신규 cwd 테스트 3개 + 기존 레지스트리 테스트 전부 통과.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/registry.py tests/test_registry.py
git commit -m "feat: InstanceInfo.cwd 필드 + register() cwd 파라미터"
```

---

## Task 2: auto_register — `X-Agora-Cwd` 헤더 추출

**Files:**
- Modify: `src/agent_agora/auto_register.py`
- Test: `tests/test_auto_register.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_auto_register.py`를 먼저 읽어, ASGI scope(헤더 포함)를 만들어 `AutoRegisterMiddleware`를 돌리는 기존 헬퍼/패턴을 파악한다. 그 패턴을 그대로 써서 테스트 3개를 추가한다:

1. `X-Agora-Cwd` 헤더가 있으면 등록된 인스턴스의 `cwd`가 그 값이 된다.
2. `X-Agora-Cwd` 헤더가 없으면 `cwd`는 `""`.
3. instance-id·role·description은 그대로인데 `X-Agora-Cwd`만 바뀐 후속 요청이 재등록을 트리거한다 (레지스트리의 cwd가 갱신됨).

기존 테스트의 scope-빌드 헬퍼(헤더는 `(b"x-agora-...", b"...")` 바이트 튜플 리스트)와 동일한 형식을 쓰고, 헤더 이름은 `b"x-agora-cwd"`.

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_auto_register.py -k cwd -v`
Expected: FAIL — 미들웨어가 `x-agora-cwd`를 추출하지 않아 `cwd`가 항상 `""`.

- [ ] **Step 3: 구현**

`src/agent_agora/auto_register.py`:

헤더 상수 추가 (`DESCRIPTION_HEADER` 다음 줄):

```python
CWD_HEADER = b"x-agora-cwd"
```

`_extract`가 cwd도 뽑아 반환하도록 수정한다 — 반환 튜플을 6원소로 확장:

```python
    def _extract(self, scope) -> tuple[str | None, str | None, str, str, str, str | None]:
        session_id: str | None = None
        instance_id: str | None = None
        role = DEFAULT_ROLE
        description = ""
        cwd = ""
        wait_mode: str | None = None
        for name, value in scope.get("headers", []):
            lname = name.lower()
            if lname == SESSION_ID_HEADER:
                session_id = value.decode("latin-1")
            elif lname == INSTANCE_ID_HEADER:
                instance_id = value.decode("latin-1")
            elif lname == ROLE_HEADER:
                role = value.decode("latin-1")
            elif lname == DESCRIPTION_HEADER:
                description = value.decode("latin-1")
            elif lname == CWD_HEADER:
                cwd = value.decode("latin-1")
            elif lname == WAIT_MODE_HEADER:
                wm = value.decode("latin-1")
                if wm in ("auto", "manual"):
                    wait_mode = wm
        return session_id, instance_id, role, description, cwd, wait_mode
```

`__call__`에서 언패킹과 등록을 수정한다 — `_extract` 결과를 6원소로 받고, 변경 감지에 `existing.cwd != cwd`를 추가하고, 두 `register()` 호출 모두 `cwd=cwd`를 넘긴다:

```python
        if scope.get("type") == "http":
            session_id, instance_id, role, description, cwd, wait_mode = self._extract(scope)
            if session_id and instance_id:
                try:
                    existing = self._registry.resolve_session(session_id)
                    if (
                        existing.instance_id != instance_id
                        or existing.role != role
                        or existing.description != description
                        or existing.cwd != cwd
                        or (wait_mode is not None and existing.wait_mode != wait_mode)
                    ):
                        self._registry.register(
                            session_id=session_id,
                            instance_id=instance_id,
                            role=role,
                            description=description,
                            cwd=cwd,
                            wait_mode=wait_mode,
                        )
                except NotRegisteredError:
                    self._registry.register(
                        session_id=session_id,
                        instance_id=instance_id,
                        role=role,
                        description=description,
                        cwd=cwd,
                        wait_mode=wait_mode,
                    )
        await self._app(scope, receive, send)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_auto_register.py -v`
Expected: PASS — 신규 cwd 테스트 3개 + 기존 auto_register 테스트 전부 통과.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/auto_register.py tests/test_auto_register.py
git commit -m "feat: auto_register가 X-Agora-Cwd 헤더를 추출해 등록"
```

---

## Task 3: server — `agora.instances`·`agora.find`에 cwd 필드 + `agora.cwd` 도구

**Files:**
- Modify: `src/agent_agora/server.py`
- Test: 서버 도구 테스트 (구현자가 패턴 확인 — 아래 Step 1 참조)

- [ ] **Step 1: 실패 테스트 작성**

서버 MCP 도구(`agora.instances`·`agora.find` 등)가 테스트에서 어떻게 호출되는지 확인한다 — `tests/test_v4_routing.py`·`tests/test_v4_bots.py` 등에서 `agora.find`·`agora.instances`를 실제 호출하는 테스트를 찾아 그 하니스(서버 기동 + MCP 클라이언트, 또는 도구 함수 직접 호출)를 파악한다. 그 패턴으로 테스트를 추가한다:

1. 인스턴스를 `cwd`와 함께 등록한 뒤 `agora.instances`를 호출 — 결과의 해당 인스턴스 레코드에 `cwd` 필드가 그 값으로 있다.
2. `agora.find`로 그 인스턴스를 검색 — worker 결과 레코드에 `cwd` 필드가 있다.
3. `agora.cwd("<instance_id>")` 호출 — `{"instance_id": ..., "cwd": ...}`를 반환한다.
4. `agora.cwd("미등록-id")` 호출 — 미등록 에러를 반환한다 (다른 인스턴스 조회 도구의 에러 형식과 동일).
5. cwd 없이 등록한 인스턴스 → `agora.cwd`가 `cwd: ""`를 반환 (에러 아님).

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest <위 테스트 파일> -k cwd -v`
Expected: FAIL — `agora.instances`/`agora.find`에 cwd 필드 없음, `agora.cwd` 도구 미존재.

- [ ] **Step 3: 구현**

`src/agent_agora/server.py`:

`agora.instances` 도구의 `items.append({...})` dict에 `"cwd": i.cwd,`를 추가한다 (`"description": i.description,` 다음 줄):

```python
            items.append({
                "instance_id": i.instance_id,
                "role": i.role,
                "description": i.description,
                "cwd": i.cwd,
                "registered_at": i.registered_at,
                "inbox_depth": m.get("queue_depth", 0),
                "in_flight": m.get("in_flight", 0),
                "last_seen_at": i.last_seen_at,
                "wait_mode": i.wait_mode,
                "accepting": i.accepting,
            })
```

`agora.find` 도구의 worker 결과 dict에 `"cwd": i.cwd,`를 추가한다:

```python
                results.append({
                    "kind": "worker", "instance_id": i.instance_id,
                    "role": i.role, "description": i.description,
                    "cwd": i.cwd,
                    "registered_at": i.registered_at,
                })
```

`agora.find` 도구 정의 바로 다음에 신규 `agora.cwd` 도구를 추가한다. 기존 인스턴스-조회 도구가 `NotRegisteredError`를 처리하는 방식(try/except + 표준 에러 응답)을 그대로 따른다:

```python
    @mcp.tool(name="agora.cwd")
    async def agora_cwd(instance_id: str) -> str:
        """Return the working directory (cwd) of a registered worker instance."""
        info = instance_registry.resolve_instance_id(instance_id)
        return json.dumps({"instance_id": info.instance_id, "cwd": info.cwd},
                          ensure_ascii=False)
```

`resolve_instance_id`가 미등록 시 `NotRegisteredError`를 던진다 — 이 서버의 다른 도구가 `NotRegisteredError`를 표준 에러 응답으로 변환하는 방식(예: `errors.py`·`agora.dispatch`의 처리)을 확인해 동일하게 맞춘다. 미등록 instance_id 호출이 표준 에러로 나가야 한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest <위 테스트 파일> -v`
Expected: PASS — 신규 cwd 테스트 + 해당 파일 기존 테스트 전부 통과.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/server.py tests/
git commit -m "feat: agora.instances·find에 cwd 필드 + agora.cwd 도구"
```

---

## Task 4: spawn — 생성되는 `.mcp.json`에 `X-Agora-Cwd` 헤더

**Files:**
- Modify: `plugin/cc-agora-ops/templates/mcp.json.template`
- Modify: `plugin/cc-agora-ops/scripts/spawn.py`
- Test: `tests/test_plugin_spawn.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_plugin_spawn.py`를 먼저 읽어, `do_spawn`을 호출해 생성된 `.mcp.json`을 검증하는 기존 패턴을 파악한다. 그 패턴으로 테스트를 추가한다:

- `do_spawn`으로 워커를 생성한 뒤, 생성된 `<id>/.mcp.json`을 파싱해 `mcpServers.agentagora.headers["X-Agora-Cwd"]`가 워커 디렉터리의 절대경로(forward-slash, 즉 `<target_dir>/<instance_id>`를 `as_posix()`한 값)와 같은지 단언한다.
- 생성된 `.mcp.json`이 유효 JSON인지도 확인한다 (기존 테스트가 이미 할 수 있음).

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_plugin_spawn.py -k cwd -v`
Expected: FAIL — 템플릿에 `X-Agora-Cwd`가 없어 헤더 부재.

- [ ] **Step 3: 템플릿 수정**

`plugin/cc-agora-ops/templates/mcp.json.template`의 `agentagora` 서버 `headers`에 `X-Agora-Cwd`를 추가한다:

```json
{
  "mcpServers": {
    "agentagora": {
      "type": "http",
      "url": "{{SERVER_URL}}",
      "headers": {
        "X-Agora-Instance-Id": "{{INSTANCE_ID}}",
        "X-Agora-Role": "{{ROLE}}",
        "X-Agora-Description": "{{DESCRIPTION}}",
        "X-Agora-Cwd": "{{CWD}}"
      }
    },
    "agora-channel": {
      "type": "stdio",
      "command": "agora-channel",
      "args": ["--instance-id", "{{INSTANCE_ID}}", "--broker", "{{SERVER_URL}}"]
    }
  }
}
```

- [ ] **Step 4: spawn.py 수정**

`plugin/cc-agora-ops/scripts/spawn.py`:

`_render_mcp_json`에 `cwd` 파라미터를 추가하고 `{{CWD}}`를 치환한다:

```python
def _render_mcp_json(
    *,
    template: str,
    server_url: str,
    instance_id: str,
    role: str,
    description: str,
    cwd: str,
) -> str:
    """2-서버 채널 템플릿을 렌더링한다. 렌더 결과가 유효 JSON인지 self-check."""
    text = template
    text = text.replace("{{SERVER_URL}}", server_url)
    text = text.replace("{{INSTANCE_ID}}", instance_id)
    text = text.replace("{{ROLE}}", role)
    text = text.replace(
        "{{DESCRIPTION}}", json.dumps(description, ensure_ascii=False)[1:-1])
    text = text.replace("{{CWD}}", cwd)
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"rendered .mcp.json is not valid JSON: {exc}") from exc
    return text
```

`do_spawn`에서 `_render_mcp_json` 호출에 `cwd`를 넘긴다. `do_spawn`에는 이미 `worker_dir = target_dir / instance_id`가 있으므로 그 절대경로를 forward-slash로 전달한다:

```python
    _write_text(
        worker_dir / ".mcp.json",
        _render_mcp_json(
            template=mcp_template, server_url=server_url,
            instance_id=instance_id, role=role, description=description,
            cwd=worker_dir.resolve().as_posix()),
    )
```

(`worker_dir`는 `target_dir / instance_id`. `.resolve().as_posix()`로 절대·forward-slash 경로를 만든다 — 헤더에 ASCII로 들어간다.)

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_plugin_spawn.py -v`
Expected: PASS — 신규 cwd 테스트 + 기존 spawn 테스트 전부 통과.

- [ ] **Step 6: Commit**

```bash
git add plugin/cc-agora-ops/templates/mcp.json.template plugin/cc-agora-ops/scripts/spawn.py tests/test_plugin_spawn.py
git commit -m "feat: spawn된 .mcp.json에 X-Agora-Cwd 헤더 (워커 디렉터리)"
```

---

## Task 5: 전체 검증

**Files:** 없음 (검증 전용)

- [ ] **Step 1: 전체 테스트 스위트**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 전부 PASS — 신규 cwd 테스트 포함, 기존 테스트 회귀 없음.

- [ ] **Step 2: end-to-end 스모크**

`do_spawn`으로 워커를 임시 디렉터리에 생성 → 생성된 `.mcp.json`의 `X-Agora-Cwd`가 그 워커 디렉터리 절대경로인지 확인. (이미 Task 4 테스트가 커버하면 이 스텝은 그 테스트 통과로 갈음.)

---

## Self-Review

- **Spec coverage:** §3 수집(헤더) → Task 2(auto_register) + Task 4(template·spawn); §4 레지스트리 → Task 1; §5 노출(필드+`agora.cwd`) → Task 3; §6 파일 영향 → Task 1~4가 모두 커버; §7 검증 → 각 Task의 테스트 + Task 5. §2 비목표(동적 추적·봇·`agora.register` cwd)는 의도적으로 범위 밖.
- **Placeholder scan:** Task 1·2·4는 구현 코드 전문 수록. Task 2·3·4의 테스트는 기존 테스트 파일의 하니스를 따르도록 지시(서버 도구·ASGI scope·spawn 검증 패턴은 기존 파일이 보유) — "docs to check" 범위. `agora.cwd`의 `NotRegisteredError` 처리는 기존 도구 패턴을 따르도록 명시.
- **Type consistency:** `cwd: str` (기본 `""`)가 `InstanceInfo`·`register()`·`_extract` 반환튜플·`_render_mcp_json` 파라미터 전반에서 일관. `{{CWD}}` 플레이스홀더명이 템플릿·spawn.py에서 일치.
