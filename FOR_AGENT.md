# AgentAgora 서버 셋업 — 에이전트 런북

AgentAgora **서버**를 처음부터 띄우는 절차다. 명령을 순서대로 실행하고 각 단계의
확인 항목을 점검한다. (플러그인은 이 서버를 호출하는 클라이언트 측이다 — 플러그인
등록 절차는 [`docs/plugins.md`](docs/plugins.md) §5.)

## 0. 사전 — uv 확인

```
uv --version
```

없으면 <https://docs.astral.sh/uv/> 의 안내로 설치한다.

## 1. `agent_agora` 설치 (`uv tool install`)

서버 패키지를 uv 도구로 설치하면 CLI `agent-agora`·`agora-channel`이 PATH에 등록된다.
아래 중 하나를 쓴다.

- 저장소를 로컬에 클론했다면 — 클론 루트(`pyproject.toml`이 있는 디렉토리)에서:

  ```
  uv tool install .
  ```

- 클론 없이 git에서 직접:

  ```
  uv tool install "git+https://<git-host>/<org>/AgentAgora.git"
  ```

  SSH 원격이면:

  ```
  uv tool install "git+ssh://git@<git-host>/<org>/AgentAgora.git"
  ```

- 이미 설치돼 있고 갱신하려면 `--force`를 붙인다:

  ```
  uv tool install . --force
  ```

확인:

```
agent-agora --help
uv tool list
```

`uv tool list`에 `agent-agora`가 보이고 버전이 의도한 값인지 확인한다 — 구버전이
박혀 있으면 위 `--force`로 다시 설치한다.

## 2. 배포 폴더

서버는 `<배포폴더>/.agentagora/`를 데이터 디렉토리(SQLite DB·스키마·통신 매트릭스·
파일 정책)로 쓴다. 배포 폴더가 아직 초기화되지 않았다면 Claude Code에서
`/cc-agora-ops:agora-setup`을 실행해 스키마·통신 매트릭스·파일 정책·워커를 만든다.

서버만 빠르게 띄울 거라면 빈 폴더도 된다 — 서버가 `.agentagora/`를 자동 생성하고
빈 설정으로 시작한다. 단 3단계의 실행 스크립트는 `.agentagora/`가 없으면 멈춘다
(잘못된 폴더에서 띄우는 것을 막기 위함).

## 3. 서버 실행

배포 폴더로 이동한 뒤 OS에 맞는 실행 스크립트를 돌린다. 스크립트는 현재 폴더에
`.agentagora/`가 있는지 확인하고, 그 폴더를 `--dir`로 서버에 넘긴다.

- Windows:

  ```
  cd <배포폴더>
  <저장소경로>\run-server.ps1
  ```

- Unix:

  ```
  cd <배포폴더>
  <저장소경로>/run-server.sh
  ```

스크립트 없이 직접 실행해도 된다:

```
agent-agora --dir "<배포폴더>" --port 8420 --no-tls
```

확인: 콘솔에 `AgentAgora starting on http://127.0.0.1:8420/mcp`가 출력되면 기동
성공이다. `Ctrl+C`로 종료한다.

## 4. 플러그인 등록

워커 Claude Code가 슬래시 명령(`/cc-agora:invoke` 등)을 쓰려면 cc-agora 플러그인
마켓플레이스를 등록해야 한다. 절차는 [`docs/plugins.md`](docs/plugins.md) §5 또는
[`plugin/README.md`](plugin/README.md) 참조.

서버가 떠 있어야 슬래시 명령이 동작한다 — 플러그인 등록만으로는 부족하다. 워커는
서버를 가리키는 `.mcp.json`도 필요하며, 이는 `/cc-agora-ops:agora-spawn`이 생성한다.
