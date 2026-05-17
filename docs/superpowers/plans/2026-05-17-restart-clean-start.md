# 서버 재시작 클린 스타트 구현 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 서버 재시작 시 기본 동작을 클린 스타트로 바꾼다 — 이전 실행의 미배달 메시지를 인박스에 복구하지 않고 drop 마킹한다. `--restore` CLI 플래그를 주면 기존 복구 동작(크래시 내구성).

**Architecture:** `Dispatcher`에 `drop_inflight_on_restart()` 신규 — 미배달 메시지를 전부 `drop_reason='server_restart'`로 마킹(큐 미적재). `__main__.py`의 `run_server`는 `--restore` 여부에 따라 `restore_from_persistence()`(기존) 또는 `drop_inflight_on_restart()`(신규)를 호출한다.

**Tech Stack:** Python 3.13, pytest. spec: `docs/superpowers/specs/2026-05-17-channel-receive-finalize-design.md` §3.1.

**전제:**
- 이 plan은 `2026-05-17-wait-to-flush.md`와 독립이다 — 어느 쪽을 먼저 머지해도 무방.
- 별도 브랜치/worktree에서 실행. 테스트 인터프리터는 저장소 `.venv`(Python 3.13).
- 참고: `Dispatcher.restore_from_persistence()`(현 `dispatcher.py:958`)는 미배달 메시지를 `_queues`로 복구하고, 닫힌 대화의 메시지만 `drained_at`/`drop_reason='server_restart'`로 마킹한다. 신규 메서드는 그 마킹을 *모든* 미배달 메시지에 적용하고 복구는 하지 않는다.

---

### Task 1: `Dispatcher.drop_inflight_on_restart()`

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Modify: `tests/test_v3_dispatcher.py` (또는 dispatcher 단위 테스트가 있는 파일 — 실행자가 확인)

- [ ] **Step 1: 실패하는 테스트 추가**

dispatcher 테스트 파일에서, Dispatcher를 persistence와 함께 만드는 기존 패턴(예: `tests/test_v4_comm_matrix.py`의 `_make_dispatcher`/`cm_app`이 `Persistence`·`AsyncWriteQueue`·`InstanceRegistry`로 Dispatcher를 구성하는 방식)을 참고해 다음 테스트를 추가한다:

```python
@pytest.mark.asyncio
async def test_drop_inflight_on_restart_clears_undrained(tmp_path):
    """drop_inflight_on_restart는 미배달 메시지를 전부 drop 마킹하고,
    이후 restore_from_persistence가 복구할 게 없게 만든다."""
    # 1) Dispatcher A — 메시지 하나 dispatch (미배달 상태로 DB에 남김)
    # 2) 같은 persistence로 Dispatcher B (재시작 시뮬레이션) 생성
    # 3) B.drop_inflight_on_restart() 호출
    # 4) B.restore_from_persistence()를 새 Dispatcher C에서 호출 → _queues 비어 있음
    ...
```

실행자는 위 시나리오를 그 파일의 기존 fixture/헬퍼에 맞춰 구체적 코드로 작성한다. 핵심 단언: `drop_inflight_on_restart()` 후 같은 DB로 `restore_from_persistence()`를 돌리면 어떤 워커 큐에도 메시지가 복구되지 않는다(`dispatcher._queues`가 비어 있음).

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v3_dispatcher.py -k drop_inflight -v` (파일명은 실제 위치에 맞춤)
Expected: FAIL — `AttributeError: 'Dispatcher' object has no attribute 'drop_inflight_on_restart'`

- [ ] **Step 3: `drop_inflight_on_restart()` 구현**

`src/agent_agora/dispatcher.py`의 `restore_from_persistence` 메서드 바로 뒤에 추가한다. `restore_from_persistence` 안의 `UPDATE messages ...` 문(닫힌 대화 한정)을 참고해, WHERE 절에서 닫힌-대화 조건을 빼고 *모든* 미배달 메시지에 적용한다. commit/트랜잭션 처리는 `restore_from_persistence`의 UPDATE와 동일 패턴을 따른다:

```python
    def drop_inflight_on_restart(self) -> None:
        """클린 스타트 — 이전 실행의 미배달(undrained) 메시지를 전부 drop
        마킹한다. restore_from_persistence와 달리 _queues에 싣지 않는다.
        대화·메시지 행 자체는 audit용으로 남는다."""
        now = _now_iso()
        self._persistence.conn.execute(
            """
            UPDATE messages
            SET drained_at = ?, drop_reason = 'server_restart'
            WHERE drained_at IS NULL
            """,
            (now,),
        )
```

(`_now_iso`는 `dispatcher.py`가 이미 쓰는 헬퍼다 — `restore_from_persistence`가 `now = _now_iso()`로 사용한다.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v3_dispatcher.py -k drop_inflight -v`
Expected: PASS

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전체 PASS (회귀 없음)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v3_dispatcher.py
git commit -m "feat: Dispatcher.drop_inflight_on_restart — 재시작 클린 스타트"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 2: `--restore` 플래그 + `run_server` 분기

**Files:**
- Modify: `src/agent_agora/__main__.py`
- Modify: `tests/test_v3_*` (CLI 파싱 테스트가 있는 파일 — 없으면 신규 작은 테스트)

- [ ] **Step 1: 실패하는 테스트 추가**

`__main__.parse_args`를 검증하는 테스트를 추가한다(`tests/`에 `__main__` 또는 `parse_args` 테스트가 있으면 거기, 없으면 `tests/test_v3_cli.py` 신규):

```python
from agent_agora.__main__ import parse_args


def test_restore_flag_defaults_false():
    assert parse_args(["--port", "8420"]).restore is False


def test_restore_flag_true_when_given():
    assert parse_args(["--restore"]).restore is True
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v3_cli.py -v`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'restore'`

- [ ] **Step 3: `--restore` 플래그 추가**

`src/agent_agora/__main__.py`의 `parse_args`에서, 기존 인자들 뒤(예: `--gc-hour` 다음)에 추가한다:

```python
    parser.add_argument(
        "--restore",
        action="store_true",
        help="재시작 시 이전 미배달 메시지를 인박스로 복구한다 "
             "(크래시 내구성). 미지정 시 클린 스타트 — 미배달 메시지는 drop된다.",
    )
```

- [ ] **Step 4: `run_server` 분기**

`run_server` 안에서 현재 무조건 호출하는 줄:

```python
        dispatcher.restore_from_persistence()
```

을 다음으로 교체한다:

```python
        if args.restore:
            dispatcher.restore_from_persistence()
        else:
            dispatcher.drop_inflight_on_restart()
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v3_cli.py -v`
Expected: PASS

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전체 PASS

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/__main__.py tests/test_v3_cli.py
git commit -m "feat: --restore 플래그 — 미지정 시 재시작 클린 스타트"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Self-Review

- **Spec 커버리지** — spec §3.1(클린 스타트 기본, `--restore` opt-in, 미배달 메시지 drop 마킹)을 Task 1(`drop_inflight_on_restart`)+Task 2(`--restore` 플래그·`run_server` 분기)가 전부 구현한다.
- **Placeholder** — Task 1 Step 1의 테스트는 시나리오를 구체 단언으로 지정하되 fixture 결합은 실행자가 기존 dispatcher 테스트 패턴에 맞춰 작성한다(파일마다 헬퍼가 달라 정확한 코드를 plan에 박으면 깨지기 쉬움). 구현 코드(`drop_inflight_on_restart`, `--restore` 인자, 분기)는 완전체.
- **타입 일관성** — `drop_inflight_on_restart(self) -> None`은 `restore_from_persistence`와 같은 무인자 메서드. `run_server`의 분기는 `args.restore`(bool)에만 의존 — Task 2에서 추가하는 인자명과 일치.
