---
name: improvement-review
description: >
  Use after a development branch has been finished (finishing-a-development-branch completed)
  to find improvement opportunities in the built result. Compresses the ouroboros
  research→analyze→enhance-identification pattern into a single focused review. Produces a
  structured findings document covering feature improvements, refactoring opportunities, and
  new feature ideas, then hands off to the planner persona to close the ouroboros loop.
---

# Improvement Review

Review a completed development branch for improvement opportunities. Do not fix anything here — only identify and categorize. The output is a findings document handed to the planner.

## When to use

Invoke this skill after the **user has approved** the improvement gate (the persona asked "구현 결과를 검토해 개선·리팩토링·추가 아이디어를 찾을까요?" and the user said yes). Do not invoke it before the gate question is answered.

## Process

### Step 1 — Establish scope

Identify what was built in this cycle:

- [ ] Read the recent git log: `git log --oneline -20` to understand what commits were made.
- [ ] Note the branch name and any PR description if available.
- [ ] If a spec or plan file was produced in this cycle (e.g., in `docs/superpowers/plans/` or a similar location), read it to understand the intended scope.
- [ ] Establish the target: which files were changed? Run `git diff --name-only <base-branch>...HEAD` (replace `<base-branch>` with `main` or `master` as appropriate).

**Hard limit**: read at most 10 files during scope establishment. Focus on entry points and changed files, not the entire codebase.

### Step 2 — Review the built result

Read the changed files and key adjacent files to understand what was built and how:

- [ ] For each file in the diff (up to 10), skim the diff content: `git diff <base-branch>...HEAD -- <file>`.
- [ ] Note observations — do not classify yet, just observe:
  - What does this code do?
  - What assumptions does it make?
  - What is missing, unclear, or over-engineered?
  - What could be done better with a small effort?
  - What entirely new capability is suggested by this work?

Observations are raw notes only. One sentence per observation is enough.

### Step 3 — Categorize findings

Classify each observation into exactly one of three categories:

**A. Feature improvements** — The implemented feature works, but could work better.
- Examples: edge cases not handled, performance not considered, UX could be smoother, error messages not helpful, configuration not exposed.
- Criterion: the feature exists and is correct, but has room to be more complete or robust.

**B. Refactoring opportunities** — The code works, but its structure could be cleaner.
- Examples: duplicated logic, overly long functions, unclear naming, missing abstraction, tangled responsibilities, brittle patterns.
- Criterion: behavior would be unchanged after refactoring; only internal structure improves.

**C. New feature ideas** — The built work suggests a natural next capability that does not exist yet.
- Examples: the new API suggests a CLI command, the new data model suggests a dashboard, the new algorithm suggests a benchmarking tool.
- Criterion: entirely new functionality, not improvement of the existing feature.

**Filtering rule**: only include a finding if it is actionable (a planner could write a task for it), specific (names the file or area), and realistic (could be done in one focused plan). Discard vague impressions.

**Scope limit**: produce at most 3 findings per category (9 total). Prefer quality over quantity — 2 sharp findings beat 6 vague ones.

### Step 4 — Produce findings document

Write a findings document to `.improvement-review/findings.md` (create the directory if absent):

```markdown
# Improvement Review Findings

> Branch: <branch name>
> Reviewed: <today's date>
> Files reviewed: <N>

## A. Feature Improvements

- **<short title>** (`<file or area>`): <one-sentence description of the improvement and why it matters>
- ...

## B. Refactoring Opportunities

- **<short title>** (`<file or area>`): <one-sentence description of what to refactor and what it simplifies>
- ...

## C. New Feature Ideas

- **<short title>**: <one-sentence description of the new capability and what triggers the idea>
- ...

## Summary

<2-3 sentences: overall quality of the built work, the single most impactful finding, and whether the loop back to the planner is recommended.>
```

If a category has no findings, write `(none found)` under it — do not omit the section.

- [ ] Write the file to `.improvement-review/findings.md`.
- [ ] Confirm the file exists and is non-empty.

### Step 5 — Gate: dispatch or close

After producing the findings document, decide whether to loop or stop:

- [ ] Count the total number of findings across all three categories (excluding "none found" entries).
- [ ] If **total findings >= 1**: dispatch to the planner persona.
  - Use `agora.dispatch` to send the findings to the registered planner worker.
  - Payload format:
    ```json
    {
      "type": "task",
      "from": "improver",
      "ts": "<ISO timestamp>",
      "message": "improvement-review findings — see .improvement-review/findings.md",
      "findings_path": ".improvement-review/findings.md",
      "summary": "<copy the ## Summary section text here>"
    }
    ```
  - After dispatch, send the user a brief message: "개선 아이디어 N건을 planner에게 전달했습니다. planner가 새 플랜으로 전환합니다."
- [ ] If **total findings == 0**: close the loop.
  - Send the user: "검토 완료 — 현재 상태에서 추가할 의미 있는 개선 사항이 없습니다. 워크플로를 종료합니다."
  - Send a `type=closing` message to the conversation originator.

### Notes

- Do not modify any source files during this skill. This is a review-only step.
- Do not invent findings to fill categories. An empty category with "(none found)" is a valid and honest result.
- The findings document is intentionally lightweight — it is input to the planner, not a final report. The planner will expand each finding into tasks.
- If `agora.find` returns no registered planner worker, log the findings path and instruct the user to manually forward `.improvement-review/findings.md` to the planner.
