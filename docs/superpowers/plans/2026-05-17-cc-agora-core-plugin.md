# cc-agora 코어 플러그인 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cc-agora` 플러그인을 통신 코어로 정비한다 — 통신 4종 슬래시를 영어화하고 신규 `agora-protocol` 운용 규칙 스킬을 추가한다.

**Architecture:** 이 플랜은 `plugin/cc-agora/`의 통신 슬래시(`invoke`·`broadcast`·`agora-target`·`agora-close`)만 다룬다. 운영자 콘텐츠(spawn 등)는 아직 `cc-agora`에 남아 있으나 Plan 2에서 `cc-agora-ops`로 이동한다. 따라서 이 플랜만 머지해도 저장소는 동작한다. SKILL.md 본문·frontmatter는 영어(CLAUDE.md 규약).

**Tech Stack:** Claude Code 플러그인(SKILL.md), Markdown. 테스트는 `.venv\Scripts\python.exe -m pytest`.

spec: `docs/superpowers/specs/2026-05-17-cc-agora-plugin-split-design.md` (§6·§7·§9).

---

### Task 1: `agora-protocol` 운용 규칙 스킬

**Files:**
- Create: `plugin/cc-agora/skills/agora-protocol/SKILL.md`

- [ ] **Step 1: 스킬 파일 생성**

`plugin/cc-agora/skills/agora-protocol/SKILL.md`를 아래 내용으로 생성:

```markdown
---
description: AgentAgora worker operating protocol — how a channel-mode worker receives, processes, and replies to messages. Background knowledge applied automatically by every cc-agora worker.
user-invocable: false
---

# AgentAgora worker protocol

Standard operating rules for an AgentAgora worker (a "council member"). Every
cc-agora persona depends on this plugin, so every worker shares these rules.

## Receive cycle

This worker runs in **channel mode**. It does not block-wait for messages.

1. A `<channel source="agora-channel">` notification wakes the worker's turn.
2. Call `agora.flush` to drain the inbox immediately (non-blocking — it returns
   whatever is queued right now). The blocking `agora.wait` tool no longer exists.
3. Process each drained message.
4. Reply to the sender with `agora.dispatch`.

## Payload rules

Every message payload is a JSON object with a `msgtype` field. Worker-to-worker
messages use the `worker_freeform` schema. The payload `type` field is one of:
`task`, `reply`, `closing`, `ack`.

- A reply uses `type: "reply"` and sets `in_reply_to` to the original message id.
- `from` and `ts` are filled by the sender.

Envelope fields — `in_reply_to`, `closing`, `conversation_id`, `cc`, `priority`,
`deadline_ts`, `reply_to`, `expect_result` — are passed as `agora.dispatch`
arguments, **not** inside the payload object.

## comm-matrix awareness

A dispatch can be rejected with `comm_denied` when the communication matrix
forbids the sender→target edge. `agora.flush` returns the inbox sorted by
comm-matrix edge weight first, then message priority — the inbox is not strict
FIFO.

## Conversation etiquette

- Inherit a conversation by passing `in_reply_to` (or an explicit
  `conversation_id`) when replying.
- End a conversation with `closing: true` on the final dispatch, or with the
  `/cc-agora:agora-close` slash.
- Do not call `agora.register` / `agora.unregister` — registration is automatic
  via the `.mcp.json` `X-Agora-*` headers.
```

- [ ] **Step 2: 파일 검증**

Run: `.venv\Scripts\python.exe -c "import pathlib; t=pathlib.Path('plugin/cc-agora/skills/agora-protocol/SKILL.md').read_text(encoding='utf-8'); assert t.startswith('---'); assert 'user-invocable: false' in t; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 커밋**

```bash
git add plugin/cc-agora/skills/agora-protocol/SKILL.md
git commit -m "feat: cc-agora — agora-protocol 운용 규칙 스킬"
```

---

### Task 2: 통신 4종 슬래시 영어화 + frontmatter 정비

기존 4개 SKILL.md(`invoke`·`broadcast`·`agora-target`·`agora-close`)의 한국어 본문을 영어로 옮기고, frontmatter에 `argument-hint`를 추가한다. 동작·인자·예시는 그대로 — 언어만 영어로, frontmatter만 보강한다. `description`은 이미 영어이므로 유지한다.

**Files:**
- Modify: `plugin/cc-agora/skills/invoke/SKILL.md`
- Modify: `plugin/cc-agora/skills/broadcast/SKILL.md`
- Modify: `plugin/cc-agora/skills/agora-target/SKILL.md`
- Modify: `plugin/cc-agora/skills/agora-close/SKILL.md`

- [ ] **Step 1: `invoke` 영어화**

`plugin/cc-agora/skills/invoke/SKILL.md`의 frontmatter에 `argument-hint`를 추가하고 본문 전체를 영어로 옮긴다. frontmatter는:

```markdown
---
description: Dispatch a task to one cc-agora worker — auto-fills payload, supports reply chaining, cc observers, closing, priority, and deadline envelope flags.
argument-hint: <instance> "<message>" [--reply-to --conv --expect --cc --closing --priority --deadline]
---
```

본문은 현 한국어 SKILL.md의 모든 절(인자·payload 자동 채움·envelope 분리·MCP 호출·에러 처리·예시)을 의미 보존하며 영어로 옮긴다. `agora-protocol`로 중앙화된 채널 동작은 재기술하지 않고, 필요 시 "see the agora-protocol skill"로 참조한다. stale wait 어휘가 있으면 channel/flush로 교정한다.

- [ ] **Step 2: `broadcast` 영어화**

`plugin/cc-agora/skills/broadcast/SKILL.md`의 frontmatter에 `argument-hint`를 추가하고 본문을 영어로 옮긴다:

```markdown
---
description: Broadcast a task or closing announcement to all registered cc-agora instances — auto-fills payload, separates envelope flags like priority and conversation_id.
argument-hint: "<message>" [--closing --priority --conv --expect]
---
```

- [ ] **Step 3: `agora-target` 영어화**

`plugin/cc-agora/skills/agora-target/SKILL.md`의 frontmatter에 `argument-hint`를 추가하고 본문을 영어로 옮긴다:

```markdown
---
description: Recommend the best cc-agora worker for a natural-language task using agora.find then propose an /invoke chaining string for manual confirmation.
argument-hint: "<task>"
---
```

- [ ] **Step 4: `agora-close` 영어화**

`plugin/cc-agora/skills/agora-close/SKILL.md`의 frontmatter에 `argument-hint`를 추가하고 본문을 영어로 옮긴다. 본문의 에러 처리 절에 있는 stale wait 표현("수신자가 wait를 못 따라가는 중")을 "the receiver is not keeping up with its inbox"로 교정한다:

```markdown
---
description: Explicitly close an agora conversation thread — dispatches closing payloads to other primary participants and transitions status to closed.
argument-hint: <conversation-id> [--reason="<text>"]
---
```

- [ ] **Step 5: 4개 파일이 유효한지 확인**

Run: `.venv\Scripts\python.exe -c "import pathlib; [print(p, pathlib.Path(p).read_text(encoding='utf-8').startswith('---')) for p in ['plugin/cc-agora/skills/invoke/SKILL.md','plugin/cc-agora/skills/broadcast/SKILL.md','plugin/cc-agora/skills/agora-target/SKILL.md','plugin/cc-agora/skills/agora-close/SKILL.md']]"`
Expected: 4줄 모두 `True`.

- [ ] **Step 6: 커밋**

```bash
git add plugin/cc-agora/skills/invoke/SKILL.md plugin/cc-agora/skills/broadcast/SKILL.md plugin/cc-agora/skills/agora-target/SKILL.md plugin/cc-agora/skills/agora-close/SKILL.md
git commit -m "refactor: cc-agora 통신 슬래시 영어화 + argument-hint"
```

---

### Task 3: `cc-agora` plugin.json description 갱신

**Files:**
- Modify: `plugin/cc-agora/.claude-plugin/plugin.json`

- [ ] **Step 1: description을 통신 코어로 갱신**

`plugin/cc-agora/.claude-plugin/plugin.json`을 아래로 교체:

```json
{
  "name": "cc-agora",
  "description": "AgentAgora communication core — worker-to-worker messaging slashes (invoke, broadcast, target, close) and the agora-protocol operating rules.",
  "version": "0.2.0"
}
```

- [ ] **Step 2: JSON 유효성 확인**

Run: `.venv\Scripts\python.exe -c "import json; json.load(open('plugin/cc-agora/.claude-plugin/plugin.json',encoding='utf-8')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: 전체 테스트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS — 이 플랜은 SKILL.md·plugin.json만 건드렸고 스크립트는 무변경이라 `test_plugin_*`도 그대로 통과.

- [ ] **Step 4: 커밋**

```bash
git add plugin/cc-agora/.claude-plugin/plugin.json
git commit -m "chore: cc-agora plugin.json — 통신 코어로 description 갱신"
```

---

## 완료 기준

- `plugin/cc-agora/skills/agora-protocol/SKILL.md`가 `user-invocable: false`로 존재한다.
- 통신 4종 SKILL.md 본문이 영어이고 `argument-hint`가 있다.
- `cc-agora` plugin.json description이 통신 코어를 기술한다.
- 전체 테스트 스위트 통과.

## 비고

운영자 콘텐츠(spawn 스킬·스크립트·presets)는 이 플랜에서 건드리지 않는다 — Plan 2 소관. 이 플랜 머지 후 `cc-agora`는 통신 코어 + (아직) 운영자 콘텐츠를 함께 갖지만, 저장소는 정상 동작한다.
