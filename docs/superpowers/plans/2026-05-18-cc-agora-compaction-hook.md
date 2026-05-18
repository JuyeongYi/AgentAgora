# cc-agora 컴팩션 복구 훅 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 컴팩션 직후 채널 모드 워커에게 인박스 재드레인 안내문을 주입하는 `SessionStart(compact)` 훅을 cc-agora 플러그인에 추가한다.

**Architecture:** Claude Code 플러그인 루트의 `hooks/hooks.json`(자동 발견)에 `SessionStart` 훅 하나를 등록한다. `matcher: "compact"` + `type: "command"`로, 명령은 셸 메타문자 없는 한 줄 `echo`다 — 그 stdout이 컴팩션 후 워커 컨텍스트에 주입된다.

**Tech Stack:** Claude Code plugin hooks (`hooks.json`), pytest (JSON 구조 검증).

**Spec:** `docs/superpowers/specs/2026-05-18-cc-agora-compaction-hook-design.md`

---

## File Structure

| 파일 | 책임 |
|---|---|
| `plugin/cc-agora/hooks/hooks.json` | 신규 — `SessionStart(compact)` 훅 정의. 수정 본체 |
| `tests/test_plugin_hooks.py` | 신규 — `hooks.json` 구조·의도·메타문자 회귀 검증 |
| `plugin/cc-agora/README.md` | 수정 — 훅 1종 문서화 |
| `docs/channel-mode.md` | 수정 — 컴팩션 복구 절 추가 |
| `docs/backlog.md` | 수정 — 항목 문구를 실제 메커니즘으로 정정 |

`plugin.json` 수정 불필요 — Claude Code가 플러그인 루트 `hooks/hooks.json`을 자동 발견한다.

---

## Task 1: SessionStart(compact) 훅 + 검증 테스트

**Files:**
- Create: `plugin/cc-agora/hooks/hooks.json`
- Test: `tests/test_plugin_hooks.py`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_plugin_hooks.py`:

```python
"""Validates the cc-agora plugin hooks manifest (hooks/hooks.json)."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOKS_JSON = REPO / "plugin" / "cc-agora" / "hooks" / "hooks.json"

# Shell metacharacters that break an unquoted inline `echo` on cmd.exe or a
# POSIX shell. The SessionStart(compact) reminder command must avoid all of
# them (see spec section 4.3).
_FORBIDDEN = set("`;|&<>()$\"'!%^")


def _load() -> dict:
    return json.loads(HOOKS_JSON.read_text(encoding="utf-8"))


def _compact_command() -> str:
    """Extract the command string of the SessionStart compact hook."""
    groups = _load()["hooks"]["SessionStart"]
    compact = [g for g in groups if g.get("matcher") == "compact"]
    cmds = [
        h["command"]
        for g in compact
        for h in g["hooks"]
        if h.get("type") == "command"
    ]
    return cmds[0]


def test_sessionstart_compact_command_hook_exists():
    groups = _load()["hooks"]["SessionStart"]
    compact = [g for g in groups if g.get("matcher") == "compact"]
    assert len(compact) == 1, "exactly one SessionStart group with matcher 'compact'"
    cmd_hooks = [h for h in compact[0]["hooks"] if h.get("type") == "command"]
    assert len(cmd_hooks) == 1, "exactly one command-type hook in the compact group"
    assert cmd_hooks[0]["command"].strip(), "compact hook command is non-empty"


def test_compact_command_carries_the_recovery_intent():
    cmd = _compact_command()
    assert "agora.flush" in cmd
    assert "channel-mode worker" in cmd


def test_compact_command_is_free_of_shell_metacharacters():
    cmd = _compact_command()
    found = sorted(_FORBIDDEN & set(cmd))
    assert not found, f"forbidden shell metacharacter(s) in hook command: {found}"
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/test_plugin_hooks.py -v`
Expected: 3개 테스트 모두 FAIL — `FileNotFoundError` (`hooks.json` 미존재).

- [ ] **Step 3: 훅 정의 작성**

Create `plugin/cc-agora/hooks/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "compact",
        "hooks": [
          {
            "type": "command",
            "command": "echo Context was just compacted. If you are an AgentAgora channel-mode worker, call agora.flush now to drain any unprocessed inbox messages, reply to each sender, then return to idle."
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `python -m pytest tests/test_plugin_hooks.py -v`
Expected: 3개 테스트 모두 PASS.

- [ ] **Step 5: 전체 테스트 회귀 확인**

Run: `python -m pytest tests/ -v`
Expected: 신규 3개 포함 전부 PASS — 기존 테스트 회귀 없음.

- [ ] **Step 6: 커밋**

```bash
git add plugin/cc-agora/hooks/hooks.json tests/test_plugin_hooks.py
git commit -m "feat: cc-agora 컴팩션 복구 훅 (SessionStart compact)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 문서 갱신

**Files:**
- Modify: `plugin/cc-agora/README.md`
- Modify: `docs/channel-mode.md`
- Modify: `docs/backlog.md`

- [ ] **Step 1: cc-agora README에 훅 절 추가**

`plugin/cc-agora/README.md`에서 `## agora-protocol 스킬` 절과 `## payload.py` 절 사이에 다음 절을 삽입한다. 앵커: `## payload.py` 라인 바로 앞.

```markdown
## 훅

`hooks/hooks.json`은 `SessionStart` 훅을 하나 등록한다 — `matcher: "compact"`로
컴팩션 직후 발화해, 채널 모드 워커가 `agora.flush`로 인박스를 다시 드레인하도록
안내문을 stdout으로 주입한다. 컴팩션이 채널 루프 진행 상태를 요약에서 잃어
워커가 멈추는 것을 복구한다. 안내문은 셸 메타문자 없는 한 줄 평문이어야 한다
(cmd.exe·POSIX 셸 양쪽에서 동일하게 출력되도록).

```

- [ ] **Step 2: channel-mode.md에 컴팩션 복구 절 추가**

`docs/channel-mode.md`에서 `## 수동 smoke test` 절 바로 앞에 다음 절을 삽입한다 (앞 절의 닫는 `---` 뒤).

```markdown
## 컴팩션 복구

워커의 컨텍스트 창이 차면 Claude Code가 대화를 요약한다(컴팩션). 컴팩션이 채널
루프 도중 — 인박스 드레인·메시지 처리 중 — 일어나면 진행 상태가 요약에서 사라져
워커가 멈출 수 있다. `cc-agora` 플러그인의 `SessionStart`(`matcher: "compact"`)
훅이 컴팩션 직후 "인박스를 `agora.flush`로 다시 확인하고 채널 루프를 재개하라"는
안내문을 컨텍스트에 주입해 이를 복구한다.

---

```

- [ ] **Step 3: backlog.md 항목 정정**

`docs/backlog.md`의 `## 진행 중` 아래 "cc-agora PostCompact 훅" 불릿 전체를 다음으로 교체한다.

```markdown
- **cc-agora 컴팩션 복구 훅** — 채널 모드 워커가 컴팩션 후 대화가 끊기는 현상.
  컴팩션이 채널 루프 상태(인박스 드레인 중 등)를 요약에서 잃어 워커가 멈춘다.
  spec 완료 — `docs/superpowers/specs/2026-05-18-cc-agora-compaction-hook-design.md`,
  브랜치 `cc-agora-compaction-hook`. `cc-agora` 플러그인에 `SessionStart`
  (`matcher: "compact"`) command 훅을 추가해 "인박스를 `agora.flush`로 확인하고
  채널 루프를 재개하라"는 안내문을 stdout으로 주입한다. (`PostCompact` 훅은
  side-effect 전용이라 컨텍스트 주입 불가 — spec §3 참조.) 구현·테스트 완료,
  머지 대기.
```

- [ ] **Step 4: 커밋**

```bash
git add plugin/cc-agora/README.md docs/channel-mode.md docs/backlog.md
git commit -m "docs: 컴팩션 복구 훅 문서화

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## 후속 (이 플랜 범위 밖)

- 브랜치 `cc-agora-compaction-hook`를 master에 머지할 때 `docs/backlog.md`의
  "진행 중" 항목을 제거한다.
- 수동 검증: 채널 모드 워커에서 실제 컴팩션을 유발해(긴 대화) 컴팩션 후 안내문이
  주입되고 워커가 `agora.flush`로 복귀하는지 확인. 훅 발화는 자동 테스트로
  재현 불가하므로 머지 전 1회 수동 smoke test 권장.
