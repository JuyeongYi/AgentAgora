# Junction 샌드박스 워커 — 세팅 가이드

워커의 **쓰기 권한을 워크스페이스 하위로 가두는** 운영 세팅. 코드 변경이 아니라
워커를 띄울 때(spawn 시) 해야 할 일에 가깝다. 현재 spawn 모델·Claude Code 권한
레이어로 충분히 구성 가능하며, 새 기능 구현은 필요 없다(단 §4 검증은 필수).

> 상태: 설계 가이드. CC의 junction 경로-경계 해석(§4)을 실측해 채택 여부를 확정하기 전엔
> 권장 기본값이 아니다.

## 1. 목표와 동기

- 워커(Claude Code 인스턴스)가 **자기 워크스페이스 밖을 수정하지 못하게** 가둔다.
- 워크스페이스를 워커 home에 **junction(또는 symlink)**으로 걸어, "보이는 작업 영역"을
  워크스페이스 하위로 한정한다.

핵심 원칙: **junction은 경로 별칭일 뿐 권한 게이트가 아니다.** 실제 "쓰기 제한"
enforcement는 Claude Code 권한 레이어(cwd 경계 + `.claude/settings.local.json`의
allow/deny)가 한다. junction은 *무엇이 보이는가*를 좁히고, CC 권한은 *무엇을 쓸 수
있는가*를 막는다 — 둘을 함께 써야 샌드박스가 성립한다.

## 2. 현재 spawn 모델 (출발점)

`cc-agora-ops`의 `spawn.py`는 워커를 `<parent>/<instance_id>/`에 생성하고(스캐폴딩:
`CLAUDE.md`·`.claude/`·`.mcp.json`), `.mcp.json`의 `cwd`를 그 worker_dir로 둔다.
즉 이미 **instance_id로 키잉된, 링크 없는 per-instance 디렉터리**다. 정션 샌드박스는
여기에 "실제 작업 대상(repo/폴더)"을 어떻게 안전하게 노출할지를 더한다.

## 3. 권장 레이아웃

```
<root>/Agents/<instance_id>/          # 워커 home — CC가 cwd로 잡는 곳
├── CLAUDE.md / .claude/ / .mcp.json   # 스캐폴딩 (spawn 생성)
└── workspace/  ──(junction)──▶  <실제 프로젝트 경로>
```

- cwd = `Agents/<instance_id>/` → CC의 cwd 경계가 자연히 이 하위로 쓰기를 가둔다.
- 그 하위의 "진짜"는 `workspace/` 정션뿐 → 쓰기가 **워크스페이스 하위로 구조적으로 한정**.
- 키는 persona명이 아니라 **instance_id** (같은 persona 다중 인스턴스 충돌 방지).

## 4. ★ 채택 전 필수 검증 (make-or-break)

Claude Code의 경로-경계 검사가 **junction(reparse point)을 canonical화하는지**가 관건이다.
OS·CC 버전 의존이므로 **타깃 환경에서 실측**한다:

1. `Agents/<id>/workspace` 정션 생성 → 실제 프로젝트로 연결.
2. cwd=`Agents/<id>`로 CC 실행.
3. `workspace/` 안 파일 편집 → **허용**되는가?
4. `workspace/` 밖(예: `../`, 절대경로) 편집 → **거부**되는가?

- 경로를 풀어 비교(canonicalize)하면: 정션 안 편집이 "cwd 밖"으로 보여 **거부**될 수 있음.
- 안 풀면: 정션 경로가 cwd 하위라 허용되지만 경계 탈출 여지.

→ 4번이 의도대로(안=허용/밖=거부) 동작해야 채택. 아니면 §6 보강책 필수.

## 5. 세팅 절차 (Windows 기준)

1. 워커 home 생성(기존 spawn): `<root>/Agents/<instance_id>/`.
2. 정션 생성(관리자 불필요): `mklink /J "<root>\Agents\<id>\workspace" "<실제 프로젝트>"`.
   - symlink(`mklink /D`)는 관리자/개발자 모드 필요 → **junction 권장**.
3. `.mcp.json`의 cwd를 `Agents/<id>`로(또는 spawn `--target`을 그쪽으로).
4. `.claude/settings.local.json`에 워크스페이스 경로로 **명시 allow/deny**도 박는다(§6).
5. 브로커에 등록되는 `cwd`(대시보드·comm-matrix·file_policy에 노출)는 **실제 워크스페이스
   경로**로 정규화 — 운영자 가시성·file_policy 매칭 일관성.

## 6. 보강책 (belt-and-suspenders)

junction 해석 동작에만 의존하지 말 것:

- **CC 권한 명시**: `settings.local.json`의 `permissions.deny`로 워크스페이스 밖 쓰기
  도구(Edit/Write/Bash 등)를 차단, `allow`로 워크스페이스 하위만 허용.
- **`file_policy` 경로 일관성**: AgentAgora `file_policy`는 gitignore류 경로 패턴으로 r/w를
  매칭한다. 정션 경로 vs 실제 경로가 갈리면 매칭이 어긋날 수 있으니, 정책 패턴과 보고 cwd를
  **같은 경로 표현(실제 경로)**으로 통일.
- **agora 파일 공유 우선**: 워커 간 파일 교환은 정션 공유보다 `files/`(`POST /files`·
  `GET /files/<id>`) 메커니즘을 쓰는 게 시스템 철학에 맞고 경로 이중화를 피한다.

## 7. 대안 — 정션 없이

샌드박스만 목적이면 정션 없이도 가능:

- **`--add-dir`**: home=설정, 실제 프로젝트는 추가 작업 디렉터리로 부여(설정-위치와 작업-위치
  분리, 경로 이중화 회피).
- **worker_dir를 repo 안에 배치**: cwd 경계가 곧 repo 하위.

정션은 "여러 워크스페이스를 한 home에 깔끔히 모으고 싶을 때" 가치가 있다. 단순 샌드박스면
`--add-dir` + `settings.local.json` deny가 더 단순하고 견고하다.

## 8. 요약

- 방향(쓰기 샌드박스)은 타당. **enforcement 주체는 CC 권한 레이어, 정션은 보조.**
- 채택 전 §4(정션-경계 해석) 실측 필수. 통과하면 §5 세팅 + §6 보강.
- 코드 변경 불요 — spawn 산출물 + `settings.local.json` + `mklink /J` 세팅으로 구성.
