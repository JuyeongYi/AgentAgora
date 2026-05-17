# 서버 로그 payload pretty-print 구현 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 서버 로그의 payload 출력을 한 줄 압축 JSON에서 `indent=2` pretty-print로 바꿔 가독성을 높인다.

**Architecture:** `dispatcher.py`의 `_fmt_payload` 한 곳만 고친다 — dispatch·broadcast·bot_emit 로그 3곳이 모두 이 헬퍼를 거친다.

**Tech Stack:** Python 3.13, pytest. 출처: `docs/backlog.md` "개선 항목 — 서버 로그 payload pretty-print". 트레이드오프(멀티라인 로그는 grep이 약간 불편)는 backlog에서 이미 가독성 우선으로 결정됨.

**전제:** 별도 브랜치/worktree에서 실행. `2026-05-17-restart-clean-start.md`·`2026-05-17-wait-to-flush.md`와 독립. 테스트 인터프리터는 저장소 `.venv`(Python 3.13).

---

### Task 1: `_fmt_payload` pretty-print

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Modify: dispatcher 테스트 파일 (`_fmt_payload` 테스트가 있으면 그곳, 없으면 신규 추가)

- [ ] **Step 1: 실패하는 테스트 추가**

dispatcher 테스트 파일에 추가 (위치는 실행자가 확인 — `tests/test_v3_dispatcher.py` 등):

```python
from agent_agora.dispatcher import _fmt_payload


def test_fmt_payload_is_pretty_printed():
    out = _fmt_payload({"msgtype": "x", "from": "A", "n": 1})
    assert "\n" in out                       # 멀티라인 (indent)
    assert '"msgtype": "x"' in out            # ": " 구분자 — 압축 아님
    assert '"n": 1' in out


def test_fmt_payload_non_serializable_falls_back_to_repr():
    out = _fmt_payload(object())              # JSON 직렬화 불가
    assert "object" in out                    # repr fallback
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v3_dispatcher.py -k fmt_payload -v` (파일명은 실제 위치에 맞춤)
Expected: `test_fmt_payload_is_pretty_printed` FAIL — 현재 `separators=(",", ":")` 압축 출력이라 `"\n"`도 `": "`도 없다. (`test_fmt_payload_non_serializable_falls_back_to_repr`는 기존 동작이라 PASS.)

- [ ] **Step 3: `_fmt_payload` 수정**

`src/agent_agora/dispatcher.py`의 `_fmt_payload`(현 `dispatcher.py:28-32`)에서 `json.dumps` 인자를 바꾼다:

```python
def _fmt_payload(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return repr(payload)
```

(`separators=(",", ":")` → `indent=2`. fallback `repr`은 그대로.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v3_dispatcher.py -k fmt_payload -v`
Expected: 2건 PASS

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전체 PASS. 다른 테스트가 `_fmt_payload`의 압축 출력에 의존하면(로그 문자열 단언 등) 그 테스트도 pretty-print에 맞게 갱신한다.

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v3_dispatcher.py
git commit -m "feat: 서버 로그 payload pretty-print (_fmt_payload indent=2)"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

- [ ] **Step 6: backlog 항목 정리**

`docs/backlog.md`의 "개선 항목 — 서버 로그 payload pretty-print" 항목을 제거한다(완료됨). 같은 커밋에 포함하거나 별도 커밋 — 실행자 재량. backlog.md는 작업 트리에 무관한 기존 미커밋 변경이 있을 수 있으니, `git add docs/backlog.md` 시 그 항목 삭제만 스테이징되는지 확인한다.

---

## Self-Review

- **커버리지** — backlog "서버 로그 payload pretty-print" 항목 = `_fmt_payload`의 `indent=2` 전환. Task 1이 전부 구현하고 backlog 항목도 제거한다.
- **Placeholder** — 없음. `_fmt_payload` 수정 코드·테스트 완전체.
- **타입 일관성** — `_fmt_payload(payload: Any) -> str` 시그니처 불변. dispatch·broadcast·bot_emit 로그 3곳은 `_fmt_payload`만 거치므로 자동 반영.
