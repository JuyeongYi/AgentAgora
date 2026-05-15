---
description: Spawn one cc-agora worker instance — creates directory with CLAUDE.md persona, .mcp.json auto-register headers, and role-derived Stop hook.
---

# /cc-agora:agora-spawn

cc-agora 워커 인스턴스 한 명을 셋업한다. spec §4.2.

## 인자

- `<id>`: 워커 instance_id (영숫자·하이픈·언더스코어, 1~32자).
- `<role>`: roles.json 키. 미정의 role도 허용되며 hook 미설치 + 경고로 진행한다.
- `"<description>"`: 한국어 한 줄 페르소나 설명. 따옴표로 감싸 공백 보존한다.
- `--dir=<path>` (선택): 워커 디렉토리의 부모 경로를 명시 오버라이드한다.
- `--preset=<role>` (선택): preset을 role과 별도로 강제한다. 미명시 시 roles.json의 preset을 쓴다.
- `--force` (선택): 이미 존재하는 `<id>/`를 덮어쓴다.

## 동작

1. plugin root는 `<repo>/plugin/cc-agora/`로 가정한다. Bash 도구로 `python <plugin-root>/scripts/spawn.py $ARGUMENTS`를 실행한다. plugin root 경로는 호출 시점에 모델이 절대경로 또는 forward-slash 상대경로로 구성한다.
2. 스크립트가 `config/roles.json` 조회 → hook/preset/wait_mode 결정. 미정의 role은 §4.1 처리(디렉토리·CLAUDE.md·.mcp.json은 생성, settings.local.json은 생략 + stderr 경고).
3. 디렉토리 디폴트 결정 순서는 spec §4.2 step 2를 따른다 — `--dir` → `AGORA_HOME` → cwd가 워커 디렉토리면 부모, 그 외에는 cwd 자체(경고).
4. 4개 파일(`CLAUDE.md`, `.mcp.json`, `.claude/settings.local.json`, `.claude/stop-hook.py`)을 생성한다. hook policy가 `none`인 role은 settings/stop-hook을 만들지 않는다.
5. 등록은 자동 안 한다 — 워커가 자기 디렉토리에서 `claude`를 실행할 때 `.mcp.json` 헤더로 auto-register된다.
6. 종료 시 stdout/stderr를 그대로 사용자에 전달한다.

## 예시

```
/cc-agora:agora-spawn Coder1 coder "프런트엔드 React 컴포넌트 작성과 훅 설계 담당."
```

`<parent>/Coder1/` 디렉토리에 CLAUDE.md + .mcp.json + .claude/{settings.local.json, stop-hook.py}가 생성되고, 사용자가 `Coder1/`에서 `claude`를 실행하면 자동 등록된다.
