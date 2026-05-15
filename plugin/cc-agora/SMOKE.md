# cc-agora — manual smoke test 시나리오

pytest로 다루기 어려운 e2e·hook 충돌·launch 케이스를 사람이 직접 돌려 검증하는 절차. 단위 테스트는 `tests/test_plugin_*.py`에 따로 있다.

각 시나리오는 다음 순서로 정리한다:

1. **사전 조건** — 시작 환경.
2. **절차** — 한 단계씩 실행할 명령.
3. **기대 결과** — 정상 동작 시 관측되어야 할 신호.
4. **실패 진단** — 어긋났을 때 가장 먼저 의심할 지점.

## 0. 공통 사전 준비

- 모노레포가 `pip install -e .` 또는 `uv sync`로 설치되어 있다 → `agent-agora` 또는 `python -m agent_agora` 실행 가능.
- cc-agora 플러그인이 Claude Code에 등록되어 있다 (`~/.claude/plugins/cc-agora` symlink 또는 marketplace 설치).
- 작업용 빈 디렉토리 — 예: `C:/AgoraTeam/` — 가 비어 있고 git 추적 밖이다.
- (Windows) `wt.exe`가 PATH에 있다. 없으면 `--launch=auto` 시나리오는 manual 강등 동작을 검증한다.

## 1. 서버 띄우기

서버는 모든 시나리오의 전제. 별도 터미널에서 띄운 채로 둔다.

**사전 조건**: 위 0번.

**절차**:

```bash
cd C:/Users/jylee/source/AgentAgora
python -m agent_agora --port 8420 --no-tls --no-timeout
```

**기대 결과**:

- 로그에 `serving on 127.0.0.1:8420` 또는 동등한 메시지.
- 종료 시 Ctrl-C로 정상 stop.
- `.agentagora/` 디렉토리가 cwd에 생기고 SQLite WAL 파일이 같이 만들어진다.

**실패 진단**:

- `Address already in use` → 다른 인스턴스가 같은 포트를 점유. `--port`를 다른 값으로.
- `ModuleNotFoundError: agent_agora` → `pip install -e .` 또는 `uv sync` 누락.

## 2. 골든 패스 e2e — orchestrator + 워커 1명

가장 자주 도는 흐름. spec §8 골든 패스에 해당.

**사전 조건**: 1번 서버가 떠 있다. `C:/AgoraTeam/`이 비어 있다.

**절차**:

1. orchestrator 디렉토리 셋업 — 별도 터미널에서:

   ```bash
   cd C:/AgoraTeam
   claude
   ```

   Claude Code 안에서:

   ```
   /cc-agora:agora-spawn Orch1 orchestrator "팀 작업 분배 PM."
   /cc-agora:agora-spawn Coder1 coder "React 컴포넌트 코딩 담당."
   ```

2. 첫 번째 터미널을 그대로 둔 채 새 터미널을 연다:

   ```bash
   cd C:/AgoraTeam/Coder1
   claude
   ```

3. orchestrator 터미널로 돌아가 `/cc-agora:invoke Coder1 "안녕. 자기소개 한 줄." --expect`.

4. Coder1 터미널이 응답을 처리하고 `agora.dispatch`로 reply 발신.

5. orchestrator가 다음 `agora.wait`에서 reply 수신, 사용자에 보고.

**기대 결과**:

- `C:/AgoraTeam/Orch1/` — CLAUDE.md + .mcp.json **만** 존재 (`.claude/` 없음 — orchestrator는 hook=none).
- `C:/AgoraTeam/Coder1/` — CLAUDE.md + .mcp.json + `.claude/settings.local.json` + `.claude/stop-hook.py` 4개 다 존재.
- 서버 로그에 두 인스턴스 등록 이벤트 + dispatch + wait 짝.
- orchestrator 터미널에 Coder1의 reply가 envelope 메타와 함께 출력.

**실패 진단**:

- Coder1이 응답 X → Stop hook 미발화. `Coder1/.claude/settings.local.json`의 hooks 섹션 + `stop-hook.py`가 존재하는지, `py -3.13` launcher가 PATH에 있는지 확인.
- `inbox_full` → Coder1이 wait를 못 따라가고 있다. Coder1 터미널에서 `/cc-agora:agora-wait` 수동 호출.
- "role 'orchestrator'는 roles.json에 정의되지 않음" 경고 → `config/roles.json`이 spawn 시점에 plugin_root 하위에 있는지 확인.

## 3. manifest 일괄 spawn + 자동 등록

**사전 조건**: 1번 서버 가동. `C:/AgoraTeam/`이 비어 있다. `wt.exe`가 PATH에 있다.

**절차**:

1. orchestrator 디렉토리에서:

   ```
   /cc-agora:agora-spawn-team <plugin-root>/templates/team.json.example --dir=C:/AgoraTeam --launch=auto
   ```

2. (또는 wt.exe가 없는 환경) `--launch=manual`로 바꿔 안내 메시지만 출력하게 한다.

**기대 결과**:

- `C:/AgoraTeam/Coder1/`, `Reviewer1/`, `Tester1/` 3개 디렉토리 생성.
- 각 디렉토리에 4개 파일 (모두 hook=stop-auto-wait role).
- `--launch=auto`라면 wt.exe가 새 탭 3개 띄움. 각 탭이 자기 디렉토리에서 `claude` 자동 실행.
- 서버 로그에 3개 인스턴스 등록.
- `wt.exe` 미존재 환경 → stderr에 "wt.exe를 찾을 수 없어 --launch=auto를 manual로 강등합니다." + 각 항목에 manual 안내.

**실패 진단**:

- wt.exe가 PATH에 있는데도 탭이 안 뜸 → `subprocess.Popen` 실패. 수동으로 `wt.exe -w 0 new-tab -d C:/AgoraTeam/Coder1 claude`를 돌려 wt.exe 자체 동작 확인.
- 디렉토리 생성 0건 → manifest 검증 실패. stderr 에러 메시지로 어느 항목·어느 키가 문제인지 확인.

## 4. hook 충돌 케이스 (`--force` 동작)

**사전 조건**: 1번 서버 가동. `C:/AgoraTeam/Coder1/`이 이전 spawn으로 이미 존재한다.

**절차**:

1. (사전) Coder1의 `.claude/settings.local.json`을 수동 편집해 다른 hook 항목(예: PostToolUse)을 추가해 둔다.

2. orchestrator 디렉토리에서 `--force` 없이 spawn 재시도:

   ```
   /cc-agora:agora-spawn Coder1 coder "다른 설명."
   ```

3. `--force`를 붙여 재시도:

   ```
   /cc-agora:agora-spawn Coder1 coder "다른 설명." --force
   ```

4. `Coder1/.claude/settings.local.json`을 직접 열어 확인.

**기대 결과**:

- step 2: exit code 1, stderr에 "`Coder1/` 디렉토리가 이미 존재합니다. --force로 덮어쓰기 가능." (한국어). 파일은 변경되지 않는다.
- step 3: exit code 0. `settings.local.json`이 템플릿 그대로 덮어써진다 — 사용자가 손으로 추가한 PostToolUse 항목은 사라진다. CLAUDE.md + .mcp.json + stop-hook.py도 갱신.

**실패 진단**:

- step 2가 통과해 버린다 → `do_spawn`의 `worker_dir.exists()` 체크 로직 회귀.
- step 3에서 권한 에러 → Windows에서 다른 프로세스가 파일을 잡고 있을 가능성. Coder1에서 돌고 있는 `claude`를 종료한 뒤 재시도.

## 5. unwait / rewait 왕복

**사전 조건**: 1번 서버 가동 + Coder1이 4번 시나리오 끝에서 정상 상태 + Coder1에서 `claude`가 떠 있다.

**절차**:

1. Coder1 안에서:

   ```
   /cc-agora:agora-unwait
   ```

2. 한 턴을 끝까지 진행 (예: 일반 채팅 메시지 하나). Stop hook이 발화하지 않는지 본다.

3. Coder1에서:

   ```
   /cc-agora:agora-rewait
   ```

4. 다시 한 턴을 끝까지 진행. Stop hook이 발화해 `agora.wait`로 진입하는지 본다.

**기대 결과**:

- step 1 직후 `Coder1/.claude/settings.local.json.bak`이 새로 생기고, 원본의 `hooks` 섹션이 비워진다(`{}` 또는 키 삭제).
- step 2에서 Stop 이벤트 시 hook이 발화하지 않고 정상 턴 종료. 사용자에 control 반환.
- step 3 후 `.bak`이 사라지고 `settings.local.json`이 복원된다.
- step 4에서 hook이 다시 발화 — Claude Code 응답에 `agora.wait(timeout_ms=0)` 호출이 포함된다.

**실패 진단**:

- step 1에서 "이미 unwait 상태입니다." 경고 → 이전 시나리오에서 `.bak`이 남아 있다. 수동으로 정리하거나 `/cc-agora:agora-rewait` 먼저.
- step 2에서 hook이 계속 발화 → 백업 파일은 생겼지만 원본의 hooks 섹션이 비워지지 않았다. JSON 파싱·재기록 로직 확인.

## 6. conversation 명시 종결 (`/cc-agora:agora-close`)

**사전 조건**: 1번 서버 + orchestrator + Coder1 등록 + 두 인스턴스 사이에 conversation 한 개가 열려 있다(예: `--conv=conv-test-01`로 dispatch).

**절차**:

1. orchestrator에서 conversation 한 개를 열어 둔다:

   ```
   /cc-agora:invoke Coder1 "테스트 메시지." --conv=conv-test-01 --expect
   ```

2. Coder1이 reply 보낸 뒤 두 인스턴스가 같은 conversation에 묶였는지 확인 (서버 로그 또는 `agora.conversation_status` 도구).

3. orchestrator에서 명시 종결:

   ```
   /cc-agora:agora-close conv-test-01 --reason="테스트 종료."
   ```

4. Coder1 터미널에서 다음 wait 결과에 `type=closing` payload가 들어오는지 본다.

5. `agora.conversation_status(conv-test-01)`를 호출해 상태 확인.

**기대 결과**:

- step 4: Coder1이 받은 메시지의 payload는 `{type:"closing", from:"Orch1", reason:"테스트 종료.", ts:"..."}`.
- step 5: status=`closed`, `closed_by`에 orchestrator 인스턴스 id가 등재.
- 종결 후 같은 `--conv=conv-test-01`로 dispatch 시도 시 서버가 status=closed로 거절 (또는 정책에 따라 새 conversation 생성).

**실패 진단**:

- step 4에서 closing payload가 안 옴 → 서버의 `agora.close_thread`가 dispatch를 빠뜨림. 서버 로그 확인.
- "본인은 대화 <conv>의 참여자가 아닙니다." → orchestrator가 실제 dispatch 발신자였는지 다시 확인. envelope `from`이 일치해야 한다.

## 7. 미정의 role 처리 (§4.1)

**사전 조건**: 1번 서버 가동.

**절차**:

1. orchestrator에서:

   ```
   /cc-agora:agora-spawn Phantom1 phantom "미정의 role 테스트."
   ```

**기대 결과**:

- exit code 0 — spawn 자체는 성공.
- stderr에 한국어 경고: "role 'phantom'는 roles.json에 정의되지 않음. hook 미설치. roles.json 편집 가이드: ..."
- `Phantom1/CLAUDE.md` + `Phantom1/.mcp.json` 생성됨.
- `Phantom1/.claude/`는 **존재하지 않는다** (settings.local.json·stop-hook.py 없음).
- `.mcp.json`에 `X-Agora-Wait-Mode` 헤더가 **없다** (서버는 wait_mode=unknown으로 기록).
- CLAUDE.md는 `general` preset을 fallback으로 사용한다.

**실패 진단**:

- `.claude/`가 만들어진다 → `do_spawn`의 `if hook == "stop-auto-wait":` 분기 회귀.
- `.mcp.json`이 invalid JSON → `_render_mcp_json`의 sentinel line 제거 로직 회귀. 단위 테스트가 잡아야 한다.

## 8. 사후 정리

- 사용한 `C:/AgoraTeam/`은 git 추적 밖이므로 수동으로 비우거나 보관한다.
- 서버 데이터(`.agentagora/`)는 다음 세션에 재활용 가능하지만, 깨끗한 상태로 시작하려면 삭제한다 (서버 중지 후).
