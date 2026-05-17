---
description: Spawn a whole cc-agora worker team from a manifest JSON — batch directory setup with optional Windows Terminal auto-launch.
---

# /cc-agora:agora-spawn-team

manifest 파일 한 개로 다수 워커를 일괄 spawn한다. spec §4.8.

## 인자

- `<manifest.json>`: team manifest 파일 경로. 스키마는 `templates/team.json.example` 참조 — `{version:1, team:[{id, role, description, preset?}, ...]}`.
- `--dir=<path>` (선택): 모든 워커 디렉토리의 공통 부모를 명시한다. 미명시 시 `/cc-agora:agora-spawn`과 동일한 §4.2 결정 순서를 따른다.
- `--launch` (선택, Windows 우선): 각 spawn 직후 `wt.exe new-tab -d <id> -- claude`로 자식 탭을 띄워 워커를 자동 기동한다. 디폴트 비활성. `--launch=manual`은 안내 문자열만 출력한다.

## 동작

1. plugin root는 `<repo>/plugin/cc-agora/`로 가정한다. Bash 도구로 `python <plugin-root>/scripts/spawn_team.py $ARGUMENTS`를 실행한다.
2. manifest 스키마(JSON Schema는 `spawn_team.py` 내장) + id 중복 + id 형식을 검증한다. 검증 실패면 abort하고 어느 항목이 문제인지 stderr에 출력한다 — 어떤 디렉토리도 만들지 않는다.
3. 검증 통과 시 각 항목에 대해 `do_spawn`(공유 라이브러리)을 순차 호출한다. 부분 실패 정책 — 한 항목이 실패해도 직전까지 생성된 디렉토리는 두고(롤백 X), 실패 지점과 나머지 미수행 항목을 사용자에 보고한다.
4. 미정의 role은 항목별로 §4.1 미정의 처리를 적용한다(manifest 전체 abort 아님).
5. 종료 시 한국어 요약: "spawn 성공 N건 / 실패 M건. 워커 시작: `claude` 실행 (또는 --launch=auto)."

## 예시

```
/cc-agora:agora-spawn-team C:/AgoraTeam/team.json --dir=C:/AgoraTeam --launch
```

manifest의 모든 워커 디렉토리가 `C:/AgoraTeam/<id>/`에 생성되고, `wt.exe`가 설치돼 있으면 각 워커가 새 Windows Terminal 탭으로 자동 시작된다.
