---
name: analyzing-test-results
description: Use when a test run produces failures - classify each failure and decide whether the implementer can fix it inline or it needs the debugger
model: opus
effort: high
delegation-target: "sp-implementer"
delegation-schema: "delegation_request"
---

# Analyzing Test Results

## Overview

Test failures are not all the same kind. Routing every failure to the debugger overloads it; routing every failure to the implementer lets structural problems get masked by patches. This skill classifies failures and decides where each one goes next.

## Failure classification

Sort each failure into one of four categories:

1. **Real bug** — the implementation code does not behave as specified. Reproducible and deterministic.
2. **Wrong test** — the test itself is wrong (bad expected value, bad setup). Fix the test, not the implementation.
3. **Flaky** — the same code passes and fails across runs. A timing, ordering, or isolation problem.
4. **Environmental** — a missing dependency, path, permission, or other cause outside the code.

## Routing decision

- **Wrong test** → the tester fixes the test itself (no delegation).
- **Simple real bug** (clear, local cause) → return to the implementer with `type=reply`, including the failing test, expected behavior, and the suspected cause.
- **Real bug with an unclear or structural cause, or flaky** → delegate to the debugger via `agora.dispatch` `type=task`, including the error, reproduction steps, and what was tried.
- **Environmental** → report to the implementer, stating clearly that it is not a code defect.

## Output convention

Always state the classification and the reasoning with the result. Not "3 tests failed" but "3 tests — 2 real bugs (simple, implementer), 1 flaky (debugger)" — name the destination too.

## Verification

Follow `superpowers:verification-before-completion` — confirm the actual test output before claiming a failure has been classified.
