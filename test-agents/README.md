# test-agents — 멀티 에이전트 테스트 하니스

cc-agora 페르소나 7종(채널 모드 워커)을 한 브로커에 붙여 실제 메시지 라우팅을
end-to-end로 굴려보는 로컬 테스트 환경이다.

## 구성

| 워커 | role | 페르소나 플러그인 |
|------|------|-------------------|
| `Orchestrator` | orchestrator | cc-agora-orchestrator |
| `Planner` | planner | cc-agora-planner |
| `Coder` | coder | cc-agora-coder |
| `Tester` | tester | cc-agora-tester |
| `Reviewer` | reviewer | cc-agora-reviewer |
| `Writer` | writer | cc-agora-writer |
| `General` | general | cc-agora-general |

각 워커는 spawn 도구로 생성된 채널 모드 디렉토리다 — `CLAUDE.md`(thin),
`.mcp.json`(HTTP 브로커 + `agora-channel` stdio 어댑터), `run.bat`(기동),
`.claude/settings.local.json`(페르소나 플러그인 활성화).

## 스크립트

| 스크립트 | 용도 |
|----------|------|
| `start-all.bat [-c]` | **전체 기동** — 브로커 탭 → 헬스 대기 → comm-matrix 적용 → 워커 7개 탭 (Windows Terminal 필요). 각 워커는 최초 프롬프트 `.`로 기동. `-c`를 주면 워커 claude에 `--continue`(이전 세션 재개) 전달 |
| `start-all.ps1` | 위의 PowerShell 본체 (`-c` switch) |
| `start-broker.bat` | 브로커만 기동 (포그라운드, `--no-tls --no-timeout`, 데이터는 `./.agentagora/`) |
| `seed-demo.bat` / `seed-demo.py` | **실제 워커 없이** 대시보드에 데모 트래픽 주입(인스턴스·대화·검색·메트릭·comm-matrix). 빠른 미리보기용 |
| `apply-comm-matrix.bat` | review-gated 통신 매트릭스 적용 (coder↛writer — 리뷰어 게이트) |
| `spawn-all.bat` | `team-manifest.json`으로 워커 디렉토리 재생성 (`--force`) |
| `run.bat` (각 워커) | 해당 워커를 채널 모드로 기동 |

> **설치 버전으로 실행**: 브로커는 `uv tool install`로 설치한 `agent-agora`를, 워커
> 채널 어댑터는 `agora-channel`을 쓴다(둘 다 같은 설치 버전 → 버전 불일치 없음). 운영
> 스크립트(comm_matrix/spawn_team/seed-demo)는 stdlib만 쓰므로 시스템 `python`으로 돈다.
> **repo 코드를 고친 뒤 그 변경을 반영하려면** repo 루트에서 `uv tool install --force .`로
> 재설치한다(설치본은 editable이 아닌 스냅샷).
>
> 모든 `.bat`은 ASCII + CRLF로 생성된다 — cp949 Windows의 cmd.exe가 LF+한글(멀티바이트)
> `.bat`의 줄을 잘못 쪼개기 때문(주석/경로는 영어·forward slash). 워커 이름은 폴더 basename이
> 자동으로 `--name`·instance-id가 된다(`run.bat`의 `%~nxI`). `run.bat`은
> `--dangerously-skip-permissions`로 기동해 워커가 권한 프롬프트 없이 자동 동작한다.
> `run.bat`에 넘긴 인자는 그대로 claude로 forward된다(예: `run.bat .` = 최초 프롬프트 `.`,
> `run.bat -c .` = 이전 세션 이어서).

## 대시보드만 빠르게 보기 (워커 없이)

7개 Claude 세션을 띄우지 않고 새 패널들(플로우·메트릭·검색·운영자 액션·로그·파일)을
바로 보고 싶으면:

```
start-broker.bat        REM 한 창에서 브로커 기동(이 창 점유)
REM 다른 창에서:
seed-demo.bat           REM 가짜 인스턴스·대화·검색 데이터 주입
```

그다음 브라우저로 <http://127.0.0.1:8420/dashboard> (trust 모드 — username 아무거나).
플로우 뷰의 in-flight 엣지와 coverage 배지는 워커↔워커 expect_result가 있어야 채워지므로
실제 워커(아래)를 띄워야 보인다.

## 빠른 시작

Windows Terminal(`wt.exe`)이 있으면:

```
start-all.bat
```

브로커 탭이 뜨고, 헬스 체크 후 comm-matrix가 적용되고, 워커 7개가 각 탭에서
기동된다. 대시보드: <http://127.0.0.1:8420/dashboard>

## 수동 기동

`wt.exe`가 없거나 단계별로 보고 싶을 때:

```
REM 1) 브로커 (이 창을 점유)
start-broker.bat

REM 2) 다른 창에서 — comm-matrix 적용
apply-comm-matrix.bat

REM 3) 각 워커 폴더에서 (워커당 창 하나)
cd Coder && run.bat
cd Reviewer && run.bat
...
```

## 통신 매트릭스 (review-gated)

`plugin/cc-agora-ops/presets/review-gated.csv` 를 적용한다. 헤더는
instance_id 접두사 정규식(`(?i)coder.*` 등)으로 매칭되므로 워커 이름
(`Coder`, `Reviewer` …)이 그대로 규칙에 걸린다. 핵심 거버넌스:

- 모두가 `Orchestrator`에 보고 가능.
- `Coder` → `Writer` 직접 dispatch 금지 (리뷰어 게이트).
- `Reviewer`가 `Coder`/`Tester`로 피드백 가능.

매트릭스를 끄고 all-allow로 테스트하려면 `apply-comm-matrix.bat`를 건너뛴다.

## 전제

- `uv tool install`로 `agent-agora`가 설치돼 `agent-agora`·`agora-channel` 콘솔
  스크립트가 PATH에 있어야 한다. 브로커(`agent-agora`)와 워커 채널 어댑터
  (`agora-channel`)가 같은 설치 버전을 쓴다 → 버전 불일치 없음. repo 코드 변경을
  반영하려면 repo 루트에서 `uv tool install --force .`.
- 운영 스크립트(comm_matrix/spawn_team/seed-demo)는 stdlib만 쓰므로 시스템 `python`이
  PATH에 있으면 된다(agent_agora 미의존).
- 워커 디렉토리(`Coder/` 등)와 `.agentagora/` 런타임 데이터는 `.gitignore` 처리된다 —
  `.mcp.json`에 머신별 절대경로가 박히므로 커밋하지 않고 `spawn-all.bat`로 재생성한다.

## 재생성

머신을 옮겼거나 워커 설정이 어긋나면:

```
spawn-all.bat
```

`team-manifest.json`을 편집해 워커를 추가/변경한 뒤 다시 돌리면 된다.
