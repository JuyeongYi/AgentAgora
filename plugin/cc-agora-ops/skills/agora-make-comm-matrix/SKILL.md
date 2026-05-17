---
description: Author a communication-matrix CSV from the live registered instances — lays out the N×N grid (plus the * fallback row/column) for a chosen topology.
argument-hint: [<out-path>]
disable-model-invocation: true
---

# /cc-agora-ops:agora-make-comm-matrix

Build a comm-matrix CSV for the current team. The comm-matrix is the
worker↔worker dispatch ACL: `matrix[to][from]` is a non-negative integer
weight — `0` forbids the edge, `>0` allows it and sets the receiver-side
processing priority (higher = sorted earlier in the receiver's inbox).

This skill *authors* the CSV. To *apply* it, use
`/cc-agora-ops:agora-comm-matrix <out-path>`.

## Arguments

- `<out-path>` (optional) — where to write the CSV. Default
  `$CWD/.agentagora/comm-matrix.csv` — i.e. `comm-matrix.csv` inside the
  `.agentagora/` directory under the current working directory. Run the skill
  from the AgentAgora server's working directory and the CSV lands in the very
  `.agentagora/` the server loads on startup. On Windows, write the path with
  forward slashes.

## Behavior

1. Call the `agora.instances` MCP tool to list the currently registered worker
   instances (the comm-matrix governs workers; bots are exempt). If none are
   registered, tell the operator to start the team first, then stop.

2. Show the operator the instance ids and ask which topology they want — one
   question at a time, do not assume:
   - **hub-and-spoke** — pick a hub; the hub may dispatch to every spoke and
     each spoke to the hub, spokes cannot dispatch to each other.
   - **all-allow** — every instance may dispatch to every other.
   - **custom** — the operator dictates the allowed edges and their weights.

3. Build the CSV:
   - Header row = the `from` list: every instance id, plus `*` (the wildcard
     column — fallback weight for a sender not in the matrix).
   - One data row per instance id (the row label is the `to` instance), plus a
     `*` row (the wildcard row — fallback for a receiver not in the matrix).
   - The grid is square: N instances + the `*` label → (N+1)×(N+1).
   - Cells are non-negative integers — `0` = forbidden, `>0` = allowed weight.
     Default every `*` fallback cell to `0` (an instance absent from the matrix
     is denied) unless the operator asks otherwise.

4. Show the operator the rendered CSV, then write it to `<out-path>`.

5. Tell the operator how to apply it. With the default `<out-path>` the CSV is
   already at the server's startup-load location (`.agentagora/comm-matrix.csv`),
   so a server restart picks it up. For a no-restart runtime replace, run
   `/cc-agora-ops:agora-comm-matrix <out-path>` (needs `AGORA_ADMIN_TOKEN`).

## CSV format

```
*,pm,coder,reviewer
0,1,1,1
1,0,1,1
1,1,0,0
1,1,0,0
```

Header = the `from` list (`*` = unlisted-sender fallback column). Data row i
has `to` = header[i]; the `*` row is the unlisted-receiver fallback. The server
resolves `weight_of(from, to)` against the explicit cell, falling back to the
`*` row/column for instances absent from the matrix. A matrix with no `*` label
is a strict whitelist — any unlisted `from`/`to` is denied.
