# 팀 대시보드 Plan 2 — `agora-dashboard` 슬래시 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cc-agora-ops` 플러그인에 팀 대시보드를 브라우저로 여는 `agora-dashboard` 슬래시를 추가한다.

**Architecture:** 단일 SKILL.md — 운영자가 `/cc-agora-ops:agora-dashboard`를 트리거하면 플랫폼별 open 명령으로 대시보드 URL을 연다. 스크립트 불필요. SKILL.md 본문·frontmatter 영어(CLAUDE.md 규약).

**Tech Stack:** Claude Code 플러그인(SKILL.md), Markdown. 테스트는 `.venv\Scripts\python.exe -m pytest`.

spec: `docs/superpowers/specs/2026-05-17-team-dashboard-design.md` (§6).

**선행 의존:** 없음 — URL만 여는 슬래시라 Plan 1과 독립적으로 머지 가능(단 실제로 열어 보려면 Plan 1이 머지돼 서버가 `/dashboard`를 서빙해야 함).

---

### Task 1: `agora-dashboard` SKILL.md

**Files:**
- Create: `plugin/cc-agora-ops/skills/agora-dashboard/SKILL.md`

- [ ] **Step 1: SKILL.md 생성**

`plugin/cc-agora-ops/skills/agora-dashboard/SKILL.md`:

```markdown
---
description: Open the AgentAgora team dashboard in a browser — a live view of instances, bots, conversations, and the comm-matrix graph.
argument-hint: [--server-url]
disable-model-invocation: true
---

# /cc-agora-ops:agora-dashboard

Open the AgentAgora team-status dashboard in the operator's default browser.

## Arguments

- `--server-url` (optional) — server base URL. Default `http://127.0.0.1:8420`.

## Behavior

1. Resolve the dashboard URL: `<server-url>/dashboard` (default
   `http://127.0.0.1:8420/dashboard`).
2. Open it in the default browser via the Bash tool, picking the platform's
   command:
   - Windows: `start "" "<url>"`
   - macOS: `open "<url>"`
   - Linux: `xdg-open "<url>"`
3. Always also print the URL plainly, so the operator can open it manually if
   the browser launch fails.

The dashboard is served by the AgentAgora server (the server must be running).
It polls live every few seconds — no refresh needed. It is read-only; to change
the comm-matrix use `/cc-agora-ops:agora-comm-matrix`.
```

- [ ] **Step 2: 파일 유효성 확인**

Run: `.venv\Scripts\python.exe -c "t=open('plugin/cc-agora-ops/skills/agora-dashboard/SKILL.md',encoding='utf-8').read(); assert t.startswith('---'); assert 'disable-model-invocation: true' in t; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 전체 스위트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS — SKILL.md만 추가했으므로 변동 없음.

- [ ] **Step 4: 커밋**

```bash
git add plugin/cc-agora-ops/skills/agora-dashboard/SKILL.md
git commit -m "feat: cc-agora-ops — agora-dashboard 슬래시"
```

---

### Task 2: `cc-agora-ops` README 갱신

**Files:**
- Modify: `plugin/cc-agora-ops/README.md`

- [ ] **Step 1: README에 슬래시 추가**

`plugin/cc-agora-ops/README.md`의 슬래시 요약(현재 `agora-spawn`·`agora-spawn-team`·
`agora-comm-matrix` 3종을 기술)에 `agora-dashboard`를 4번째 항목으로 추가한다 — 한 줄
설명: "팀 현황 대시보드를 브라우저로 연다". 한국어(산출물 문서 규약).

- [ ] **Step 2: 커밋**

```bash
git add plugin/cc-agora-ops/README.md
git commit -m "docs: cc-agora-ops README — agora-dashboard 슬래시 추가"
```

---

## 완료 기준

- `cc-agora-ops`에 `agora-dashboard` 슬래시가 있고 `disable-model-invocation: true`다.
- 슬래시가 대시보드 URL을 브라우저로 열고 URL도 출력한다.
- `cc-agora-ops` README가 슬래시 4종을 기술한다.
- 전체 테스트 스위트 통과.
