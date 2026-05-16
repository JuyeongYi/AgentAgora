# 예제 — AgentAgora 띄워보기

서버를 실제로 띄우고 **봇 스키마 fan-out**과 **워커↔워커 통신 ACL(comm-matrix)**
두 가지를 직접 굴려보는 최소 예제다. Claude Code 인스턴스 없이 파이썬 스크립트만으로
end-to-end가 돈다.

```
examples/
  echo_bot/        데모 1 — 스키마 구독 봇
    echo_bot.py      echo_task 를 구독하고 bot_reply 로 회신하는 핸들러 봇 (AgoraBot SDK 상속)
    send.py          봇에게 태스크 하나를 보내고 회신을 받는 일회성 워커
    run-bot.bat      echo_bot.py 실행 (저장소 .venv 사용)
    run-send.bat     send.py 실행
  comm_demo/       데모 2 — 워커↔워커 dispatch ACL
    demo.py          워커 둘을 띄워 comm-matrix가 dispatch를 막는지 확인
    run-demo.bat     demo.py 실행
  comm-matrix.csv  서버 startup에 로드되는 ACL 예시 파일 (hub-and-spoke)
```

---

## 사전 준비

저장소 루트에서 패키지를 설치한다 (Python 3.13+).

```bash
pip install -e .          # 또는: uv sync
```

`.bat` 실행 스크립트는 저장소의 `.venv/Scripts/python.exe`를 쓴다. `.venv`가
없다면 `python examples/.../*.py` 형태로 직접 실행해도 된다.

기본 포트는 `8420`이다. 다른 포트를 쓰려면 클라이언트 쪽에 `AGORA_URL`
환경변수를 주면 된다 (예: `AGORA_URL=http://127.0.0.1:8455/mcp`).

---

## 데모 1 — echo 봇 (스키마 fan-out)

워커가 `target` 없이 `echo_task` payload를 dispatch하면, 서버가 그 스키마를
**구독한 봇에게 라우팅**한다. 봇은 처리 결과를 `bot_reply`로 원 발신자에게 회신한다.

```
worker_demo ──dispatch(echo_task)──▶ 서버 ──(schema-routed)──▶ bot_echo
worker_demo ◀──────── bot_reply ────── 서버 ◀──bot_emit(in_reply_to)── bot_echo
```

**터미널 1 — 서버**

```bash
python -m agent_agora --port 8420 --no-tls --no-timeout
```

**터미널 2 — 봇** (계속 떠 있는다)

```bash
python examples/echo_bot/echo_bot.py
#   또는  examples\echo_bot\run-bot.bat
```

이 봇은 `agent_agora.bot.AgoraBot` SDK를 상속한다 — SDK 사용법은 [`docs/bot-sdk.md`](../docs/bot-sdk.md).

봇은 자기를 핸들러 봇으로 등록하면서 `echo_task` 스키마를 인라인으로 같이
등록한다(`agora.register_bot`의 `schemas` 인자). 출력:

```
[bot_echo] 등록 완료 (구독: ['echo_task']). wait 루프 시작.
```

**터미널 3 — 메시지 보내기**

```bash
python examples/echo_bot/send.py "안녕, 아고라!"
#   또는  examples\echo_bot\run-send.bat "안녕, 아고라!"
```

기대 출력:

```
[worker_demo] dispatch 완료 — 라우팅된 봇: ['bot_echo']
[worker_demo] <- bot_echo : {"msgtype": "bot_reply", ..., "result": {"echo": "안녕, 아고라!"}}
```

봇 터미널에도 수신·회신 로그가 찍힌다. 봇을 먼저 띄우지 않으면 `echo_task`
스키마가 없어 `send.py`가 `unknown_msgtype`/`no_route`로 실패한다 — 순서 주의.

---

## 데모 2 — comm-matrix (워커↔워커 ACL)

`comm-matrix`는 **워커가 다른 워커에게 dispatch할 수 있는지**를 N×N 화이트리스트로
강제한다 (봇으로 가는 schema-routed 메시지나 cc는 대상이 아니다). `demo.py`는 한
프로세스에서 워커 둘을 별도 세션으로 띄우고, 런타임에 매트릭스를 설치한 뒤 dispatch가
규칙대로 막히는지 확인한다.

설치하는 매트릭스: `worker_a → worker_b`는 금지, `worker_b → worker_a`는 허용.

```bash
# 서버 (데모 1과 별개로, 깨끗한 상태 권장)
python -m agent_agora --port 8420 --no-tls --no-timeout

# 데모 실행
python examples/comm_demo/demo.py
#   또는  examples\comm_demo\run-demo.bat
```

기대 출력:

```
comm-matrix 설치: {'status': 'ok', 'active': True}
[a -> b] 거부됨 (기대대로) : {'error': '[agora] comm_denied: worker_a -> worker_b ...'}
[b -> a] 허용됨 (기대대로) : {'status': 'ok', ...}
=== PASS — ACL이 기대대로 동작 ===
```

`agora.register_comm_matrix`는 서버 **전역** ACL을 교체하며 끌 수 없다. 매트릭스가
없는 깨끗한 상태로 다시 보려면 서버를 재시작한다 (런타임 설치본은 영속되지 않는다).

---

## comm-matrix.csv 파일 형식

`examples/comm-matrix.csv`는 **서버 startup 시 로드되는** ACL 예시다. 서버는
`<--dir>/.agentagora/comm-matrix.csv`가 있으면 기동 때 읽어들인다.

```bash
mkdir -p mydir/.agentagora
cp examples/comm-matrix.csv mydir/.agentagora/comm-matrix.csv
python -m agent_agora --dir mydir --port 8420 --no-tls --no-timeout
```

형식 — 헤더 1줄 + 데이터 N줄, 정확히 N×N, 셀은 `0`/`1`:

```
pm,coder,reviewer
0,1,1
1,0,0
1,0,0
```

- **헤더** = `from` instance_id 목록 (열 방향).
- **i번째 데이터 행** = 헤더 i번째 인스턴스를 `to`로 했을 때, 각 `from`의 허용 여부.
- 셀 `1` = 허용, `0` = 금지.

위 예시는 hub-and-spoke다 — `pm`은 누구에게나 dispatch 가능하고 누구나 `pm`에게
보낼 수 있지만, `coder`와 `reviewer`는 서로 직접 dispatch하지 못한다(`pm` 경유만).

주석 줄·빈 셀은 허용되지 않는다. 행·열 수가 안 맞으면 서버가 거부한다. 런타임
교체는 `agora.register_comm_matrix(csv_text=...)` 도구로 같은 형식의 텍스트를 넘긴다.
