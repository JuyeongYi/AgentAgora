---
description: Restore this instance's Stop hook from settings.local.json.bak — the inverse of /cc-agora:agora-unwait.
---

# /cc-agora:agora-rewait

`/cc-agora:agora-unwait`의 짝. Stop hook을 복원한다. spec §4.5b.

## 인자

없음.

## 동작

1. 자기 워커의 `.claude/settings.local.json.bak` 경로를 확인한다.
2. 백업 파일이 없으면 no-op + 한국어 안내 "복원할 백업 없음."을 출력하고 종료한다.
3. `.claude/settings.local.json.bak`을 `.claude/settings.local.json`으로 복원한다(기존 원본은 덮어쓴다).
4. `.claude/settings.local.json.bak`을 삭제한다.
5. 사용자에 한 줄 안내: "Stop hook을 복원했습니다. 다음 wait가 자동 발화합니다."
6. 사용자가 hook이 즉시 발화하길 원하면 자연스럽게 다음 턴에 wait 진입한다(별도 강제 트리거 없음).

## 구현 도구 선택

Read/Edit/Write 도구로 파일을 복원하거나, Bash로 `mv` 한 줄로 끝내도 된다. 모델 자율 판단. Windows 경로는 forward slash.

## 예시

```
/cc-agora:agora-rewait
```

`.bak`이 원본으로 복원되고 삭제된다. Stop hook이 다시 활성화된다.
