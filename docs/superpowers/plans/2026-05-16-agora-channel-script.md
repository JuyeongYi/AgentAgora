# agora-channel 콘솔 스크립트 구현 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `agora-channel`을 `pyproject.toml` 콘솔 스크립트로 등록해, `uv tool install .` / `pip install .` 시 `agent-agora`(서버)와 `agora-channel`(채널 어댑터) 두 명령이 모두 PATH에 오르게 한다.

**Architecture:** `channel_adapter.py`의 진입점 `main`은 `async def`라 콘솔 스크립트 엔트리로 직접 못 쓴다. 동기 래퍼 `cli()`(`asyncio.run(main())`)를 두고 `[project.scripts]`가 그것을 가리킨다.

**Tech Stack:** Python 3.13, setuptools, pyproject. spec: `docs/superpowers/specs/2026-05-16-cc-agora-channel-turnkey-design.md` §3.1.

**전제:**
- 이 plan은 cc-agora 채널 turnkey plan(`2026-05-16-cc-agora-channel-turnkey.md`)의 선행이다 — 그 plan의 `.mcp.json` 템플릿이 `command: "agora-channel"`을 참조한다.
- 큰 변경 묶음의 일부이므로 별도 브랜치/worktree에서 실행(실행 스킬이 처리).
- 테스트 인터프리터는 저장소 `.venv`(Python 3.13). 기본 `python`은 3.12라 `agent_agora`가 없다.

---

### Task 1: `agora-channel` 콘솔 스크립트 등록

**Files:**
- Modify: `src/agent_agora/channel_adapter.py` — `cli()` 동기 래퍼 추가 + `__main__` 블록
- Modify: `pyproject.toml` — `[project.scripts]`에 `agora-channel` 추가
- Modify: `tests/test_channel_adapter.py` — 엔트리포인트 테스트 추가

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_channel_adapter.py`의 끝에 추가:

```python
def test_cli_entrypoint_registered():
    """agora-channel 콘솔 스크립트가 pyproject에 등록되고 cli()가 동기 호출 가능하다."""
    import pathlib
    from agent_agora import channel_adapter

    assert callable(channel_adapter.cli)
    # cli는 동기 함수여야 한다 (콘솔 스크립트 엔트리는 코루틴을 못 받는다)
    import inspect
    assert not inspect.iscoroutinefunction(channel_adapter.cli)

    pyproject = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert 'agora-channel = "agent_agora.channel_adapter:cli"' in text
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_channel_adapter.py::test_cli_entrypoint_registered -v`
Expected: FAIL — `AttributeError: module 'agent_agora.channel_adapter' has no attribute 'cli'`

- [ ] **Step 3: `cli()` 동기 래퍼 추가**

In `src/agent_agora/channel_adapter.py`, 파일 맨 끝의 `if __name__ == "__main__":` 블록을 찾는다. 현재 형태:

```python
if __name__ == "__main__":
    asyncio.run(main())
```

이것을 다음으로 교체한다 (`cli()` 정의 + `__main__`이 `cli()`를 호출):

```python
def cli() -> None:
    """콘솔 스크립트 진입점 (동기). pyproject [project.scripts]가 가리킨다.

    채널 어댑터의 main은 async라 콘솔 스크립트 엔트리로 직접 못 쓴다 —
    이 동기 래퍼가 asyncio 런루프를 연다."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
```

(`asyncio`는 `channel_adapter.py`가 이미 임포트하고 있다.)

- [ ] **Step 4: `pyproject.toml`에 콘솔 스크립트 추가**

In `pyproject.toml`, `[project.scripts]` 섹션을 찾는다. 현재:

```toml
[project.scripts]
agent-agora = "agent_agora.__main__:main"
```

`agora-channel` 줄을 추가한다:

```toml
[project.scripts]
agent-agora = "agent_agora.__main__:main"
agora-channel = "agent_agora.channel_adapter:cli"
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_channel_adapter.py -v`
Expected: 전체 PASS (기존 channel_adapter 테스트 + 신규 1건)

- [ ] **Step 6: 재설치 후 콘솔 스크립트 검증**

`[project.scripts]` 변경은 재설치해야 PATH에 반영된다. 저장소 `.venv`에 editable 재설치:

Run: `.venv\Scripts\python.exe -m pip install -e . --quiet`
이어서 콘솔 스크립트가 동작하는지:
Run: `.venv\Scripts\agora-channel.exe --help`
Expected: argparse 도움말 출력 — `--instance-id`, `--broker`, `--wait-timeout-ms` 인자가 보인다. (에러·트레이스 없음.)

- [ ] **Step 7: 전체 테스트 회귀 확인 + 커밋**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전체 PASS

```bash
git add src/agent_agora/channel_adapter.py pyproject.toml tests/test_channel_adapter.py
git commit -m "feat: agora-channel 콘솔 스크립트 등록"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Self-Review

- **Spec 커버리지** — spec §3.1(`agora-channel` 콘솔 스크립트, `cli()` 동기 래퍼, `pyproject.toml` 등록)을 Task 1이 전부 구현한다.
- **Placeholder** — 없음. 모든 코드·명령·기대 출력 구체적.
- **타입 일관성** — `cli() -> None`은 동기 함수, `main`은 기존 async 그대로. `[project.scripts]`의 `agora-channel = "agent_agora.channel_adapter:cli"`는 테스트가 검증하는 문자열과 일치.
