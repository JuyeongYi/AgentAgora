# AgentAgora Inter-Instance Smoke Test

End-to-end verification of the A→B command channel using two real Claude Code instances and a running AgentAgora server. Automated tests use in-process simulation; this procedure exercises the real HTTP transport + `Mcp-Session-Id` header path that production clients use.

## Prerequisites

- Python 3.13 with the `agent-agora` package installable (`pip install -e .` from the repo root)
- A directory containing `.agentagora/schemas.json` (any valid user schemas — `instances`, `commands`, `results` are auto-injected)
- Two Claude Code instances ready to connect to the AgentAgora MCP endpoint

## Procedure

### 1. Start the AgentAgora server

From the repo root (or any directory containing `.agentagora/`):

```
agent-agora --dir ./.agentagora --port 8420
```

You should see:

```
AgentAgora starting on https://127.0.0.1:8420/mcp
  Data dir : .../​.agentagora
  Schemas  : finding, status, instances, commands, results
  Cert     : .../cert.pem
```

The reserved schemas (`instances`, `commands`, `results`) should appear alongside user schemas.

### 2. Connect Claude Code instance A

In Claude Code instance A, configure the MCP server to connect to `https://127.0.0.1:8420/mcp` (accept the self-signed cert).

In A, prompt:

> Call the `agora.register` tool with `instance_id="A"` and `role="orchestrator"`.

Expected: `{"status": "ok", "instance_id": "A", "role": "orchestrator", "registered_at": "..."}`.

### 3. Connect Claude Code instance B and put it in wait loop

In Claude Code instance B, configure the same MCP endpoint.

In B, prompt:

> Call `agora.register` with `instance_id="B"`, `role="worker"`. Then enter a loop: call `agora.wait` repeatedly. For each command received, examine `payload` and act on it. After acting, dispatch the result back to the command's `source` instance using `agora.dispatch(target=<source>, payload={"result_for": <command id>, ...})`. Then call `agora.wait` again.

Expected: B registers successfully and enters the long-poll loop. The first `agora.wait` should block (because the queue is empty) until a command arrives.

### 4. From A, dispatch a command to B

In A, prompt:

> First call `agora.instances` to confirm B is registered. Then call `agora.dispatch` with `target="B"` and `payload={"task": "list the files in src/agent_agora"}`.

Expected:
- `agora.instances` shows entries for both A and B with correct `role` values
- `agora.dispatch` returns `{"status": "ok", "command_id": "<uuid>", "target": "B"}`

### 5. Observe B receiving and processing

Within a moment, B's pending `agora.wait` call should return with the dispatched command. B's LLM then:
- Reads the payload
- Performs the action (here: lists files in `src/agent_agora`)
- Calls `agora.dispatch(target="A", payload={"result_for": <id>, "files": [...]})`
- Loops back to `agora.wait`

### 6. From A, retrieve the result

In A, prompt:

> Call `agora.wait` with `timeout_ms=5000`. The result from B should arrive.

Expected: A's `agora.wait` returns a command whose `source` is `"B"` and whose payload contains the file list with `result_for` matching A's original command id.

### 7. Test broadcast (optional)

In A:

> Call `agora.broadcast` with `payload={"ping": 1}`.

Expected: B receives one command with payload `{"ping": 1}`. A does NOT receive its own broadcast.

### 8. Test session-close auto-unregister

Terminate Claude Code instance B (Ctrl+C the process, or close the window).

After a moment, in A:

> Call `agora.instances` again.

Expected: B is no longer in the list. The `SessionCloseMiddleware` should have unregistered B's session when its HTTP connection dropped.

## Pass criteria

- Step 2: A registers.
- Step 3: B registers and `agora.wait` blocks rather than returning immediately.
- Step 4: A's `agora.instances` lists both, and `agora.dispatch` succeeds.
- Step 5: B's `agora.wait` returns the command within a second of dispatch.
- Step 6: A receives the result.
- Step 7: Broadcast reaches B but not A.
- Step 8: B is auto-unregistered after disconnect.

## Common failure modes

- **B's `agora.wait` returns immediately with empty commands every call:** B may not be registered, or B's instance_id doesn't match the dispatch target. Verify via `agora.instances`.
- **`Mcp-Session-Id` header missing:** Indicates the Claude Code client is not using the Streamable HTTP transport. AgentAgora only supports Streamable HTTP — verify the client config.
- **Self-signed cert rejected:** Claude Code must trust the cert at `~/.agent-agora/certs/cert.pem`, or be configured to skip verification.
- **B still listed after termination:** Either the disconnect did not trigger `http.disconnect` (some shutdown paths skip the event), or middleware was not attached. Check server logs for the unregister.
