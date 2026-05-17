---
description: Recommend the best cc-agora worker for a natural-language task using agora.find then propose an /invoke chaining string for manual confirmation.
argument-hint: "<task>"
---

# /cc-agora:agora-target

Recommend the single most suitable worker for a natural-language task. spec §4.3.

## Arguments

- `"<task>"`: Natural-language task description. Wrap in quotes to preserve spaces.

## Behavior

1. **Keyword extraction** — Extract 1–3 core keywords from `<task>`. Example: "write a react component" → "react", "component", "coding". Keywords may be in any language.
2. **First-pass filter** — Pick the strongest keyword and call `agora.find(query=<keyword>)`. If needed, call again with another keyword and union the results. Candidates are instances whose instance_id, role, or description contain the keyword (spec §4.3 step 1, `src/agent_agora/server.py:131`).
3. **Second-pass filter** — If first pass returns 0 results, call `agora.instances()` to get the full list and match against the task.
4. **Top-1 selection** — From the candidates, pick the one most suited to the task based on role/description. If there are ≤3 instances, give a 2–3 sentence rationale; with more, condense to 1 sentence.
5. **Chaining proposal (do not auto-fire)** — Print exactly this one line:

   ```
   /cc-agora:invoke <recommended-id> "<task>"
   ```

   Per spec §9.1, there is no standard Claude Code mechanism to prefill the next input with a slash response. The user copies, edits, confirms, and presses Enter. This slash never calls `agora.dispatch` directly.

## Output example

With 3 candidates:

```
Recommendation: Coder1
Rationale: role=coder and description includes "React", matching the task. Coder2 is backend-focused and ranked lower.

Next command (user confirmation required):
/cc-agora:invoke Coder1 "Write a login form as a React component"
```

## Example

```
/cc-agora:agora-target "Write a login form as a React component"
```

Outputs one recommended worker + chaining string. The user decides whether to fire it.
