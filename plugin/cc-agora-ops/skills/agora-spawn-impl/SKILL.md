---
description: Interactive implementation worker spawn — asks whether to spawn a single implementer or an MVC trio (model+view+controller), then delegates to the appropriate spawn flow.
argument-hint: [--dir --force --server-url]
disable-model-invocation: true
---

# /cc-agora-ops:agora-spawn-impl

구현 워커를 스폰하기 전에 토폴로지를 선택한다. 단순·집중형 작업에는 단일 implementer 하나를, UI 복잡도가 큰 작업에는 model·view·controller 세 워커를 스폰한다.

## 동작

1. `AskUserQuestion`으로 스폰 방식을 선택하게 한다.

   - **단일 implementer** — 한 워커가 모든 구현 코드 담당 (작은·집중형 작업)
   - **MVC 3종** — model·view·controller 세 워커가 책임 분담 (UI 복잡도 큰 작업)

2. **단일 implementer 선택 시**:
   - `AskUserQuestion`으로 워커 `id` (예: `Impl1`)와 `description` (한 줄 설명)을 입력받는다.
   - `/cc-agora-ops:agora-spawn` 슬래시 흐름을 `role=sp-implementer`로 호출한다.
   - 내부적으로 `python <plugin-root>/scripts/spawn.py <id> sp-implementer "<description>" [옵션]`을 실행한다.

3. **MVC 3종 선택 시**:
   - 기본 워커 id는 `Model1` / `View1` / `Controller1`이다. 운영자가 변경하고 싶으면 `AskUserQuestion`으로 입력받는다.
   - `/cc-agora-ops:agora-spawn-team` 슬래시 흐름을 번들 매니페스트 `templates/team-mvc.json.example`로 호출한다.
   - 내부적으로 `python <plugin-root>/scripts/spawn_team.py <plugin-root>/templates/team-mvc.json.example [옵션]`을 실행한다.
   - id를 변경한 경우, 임시 매니페스트를 tmp 경로에 작성한 뒤 실행한다.

## 인자 (선택)

- `--dir=<path>`: 워커 폴더를 생성할 부모 디렉터리. 지정하지 않으면 agora-spawn §4.2 cascade 기본값 사용.
- `--force`: 기존 디렉터리가 있으면 덮어쓴다.
- `--server-url=<url>`: MCP 서버 URL. 기본값 `http://127.0.0.1:8420/mcp`.

## 예시

```
/cc-agora-ops:agora-spawn-impl
```

실행하면 토폴로지 선택 질문이 표시되고, 선택에 따라 단일 워커 또는 MVC 3개 워커 디렉터리가 생성된다.

## 단일 implementer 예시 결과

```
Impl1/
  CLAUDE.md
  .mcp.json
  run.bat
  .claude/settings.local.json  ← superpowers-implementer 플러그인 활성화
```

## MVC 예시 결과

```
Model1/       ← superpowers-model 플러그인 활성화
View1/        ← superpowers-view 플러그인 활성화
Controller1/  ← superpowers-controller 플러그인 활성화
```

각 워커는 `run.bat`을 실행해 채널 모드로 시작하면 자동으로 서버에 등록된다.
