# 아고라 파일 공유 설계

> 2026-05-17. 에이전트(워커) 간 파일 공유. 서버 측 파일 스토어 + 워커별 권한 정책.
> 메시지 payload에는 작은 핸들만 — 원본 바이트는 별도 경로(로컬 파일시스템 / HTTP).

## 1. 배경 / 동기

워커는 자연어 메시지로 소통하지만 파일(코드·문서·산출물)을 직접 주고받을 수단이
없다. CLAUDE.md 규약상 원본 바이너리는 메시지 payload에 넣을 수 없다 — 작은
파생물만. 따라서 파일 바이트는 별도 전송 경로가 필요하고, 메시지에는 작은 **핸들**만
싣는다.

서버가 파일 스토어를 보유한다(서버 측 스토어 모델). 공유자는 파일을 스토어에 넣고
핸들을 받아 메시지로 전달하며, 수신자는 핸들로 스토어에서 파일을 가져간다. 같은
파일시스템이면 파일시스템 복사로, 원격이면 HTTP 업/다운로드로 바이트가 오간다.

## 2. 파일 스토어

- `.agentagora/files/<file_id>` — 파일 바이트. `file_id`는 서버 생성 uuid.
- SQLite `files` 테이블 — 메타: `file_id`·`name`(원본 파일명, 확장자 포함)·`size`·
  `sha256`·`content_type`·`registered_by`(공유한 워커 id)·`created_at`.
- 최대 업로드 크기 상한 — 설정값(`max_file_bytes`, 기본 `104_857_600` = 100 MB).
  초과 시 거부.

## 3. FilePolicy — 워커별 파일 권한

`CommMatrix`와 같은 거버넌스 패턴의 신규 `FilePolicy` 클래스. 설정은 **JSON** —
`.agentagora/file-policy.json`. (CSV 대신 JSON — `level` + `extensions` 리스트가
구조화 데이터라 JSON이 자연스럽고, 프로젝트가 이미 JSON을 쓴다. stdlib `json`만
사용, 새 의존성 없음.)

```json
{
  "workers": {
    "Coder1":    { "level": "rw", "extensions": [".py", ".md"] },
    "Reviewer1": { "level": "r",  "extensions": ["*"] }
  },
  "fallback":    { "level": "r",  "extensions": [".md", ".txt"] }
}
```

- `level` — `"rw"`(업로드+다운로드) 또는 `"r"`(다운로드만). 업로드만은 무의미하므로
  없음.
- `extensions` — 업로드 허용 확장자 목록(점 포함, 예 `".py"`). `["*"]`는 전체 허용.
- `workers` — 명시 등재 워커별 정책.
- `fallback` — 선택. `workers`에 없는 워커에 적용되는 기본 정책 행. `fallback`이
  없으면 미등재 워커는 무제한(`rw`·전체 확장자).
- **파일(`file-policy.json`)이 아예 없으면** `FilePolicy` 비활성 → 전원 무제한.

**다운로드는 모든 레벨이 허용한다** — `level`은 `rw`/`r` 둘뿐이고 둘 다 다운로드
포함. 따라서 정책은 **업로드만 게이트**한다.

`FilePolicy` API:
- `active: bool` — 설정 파일 존재 여부.
- `load_json(text)` — 파싱·제자리 교체. 잘못된 구조는 `AgoraError`.
- `can_upload(worker_id, extension) -> bool` — 정책 해석: 워커가 `workers`에 있으면
  그 항목, 없으면 `fallback`, 그것도 없거나 비활성이면 무제한. `level == "rw"` 이고
  `extension`이 허용 목록에 있거나 목록에 `"*"`가 있으면 True.
- `snapshot() -> dict` — 현재 정책 조회용(admin GET).

`extension`은 파일명의 마지막 확장자(점 포함, 소문자 정규화). 확장자 없는 파일은
`""` — 허용 목록에 `"*"`가 있을 때만 업로드 가능.

## 4. MCP 도구 (로컬 — 파일시스템)

서버와 워커가 같은 파일시스템일 때(로컬 개발) 쓰는 경로.

- **`agora.share_file(path)`** — 호출 워커가 로컬 파일을 공유한다. 서버가:
  1. 호출자 instance_id 해석 → `file_policy.can_upload(caller, ext)` 검사. 거부 시
     `AgoraError("file_upload_denied")`.
  2. `path`의 크기가 `max_file_bytes` 초과면 거부.
  3. `path`를 `.agentagora/files/<file_id>`로 복사(공유자의 원본은 그대로 둔다 —
     이동이 아닌 복사), sha256·size·content_type 계산, `files` 행 기록.
  4. 핸들 `{file_id, name, size, sha256}` 반환.
- **`agora.fetch_file(file_id, dest_path)`** — 스토어의 `<file_id>`를 `dest_path`로
  복사한다. 다운로드는 게이트 없음. `file_id`가 없으면 `AgoraError("unknown_file")`.

## 5. 메시지 연동 — `file_share` 빌트인 스키마

신규 빌트인 스키마 `file_share`(`kind=conversation`). body 필수 property:
`msgtype`·`file_id`·`name`·`size`·`sha256`·`from`·`ts`, 선택 `note`.

흐름: 공유자 A가 `agora.share_file`로 핸들을 얻고, `agora.dispatch`로 `file_share`
payload를 수신자 B에 보낸다. `dispatch`는 기존대로 comm-matrix가 게이트하므로
파일 핸들 전달도 통신 ACL을 따른다. B는 `flush`로 `file_share` 메시지를 받아
`agora.fetch_file(file_id, dest)`를 호출한다. `dispatch` 자체는 무변경 —
`file_share`는 또 하나의 msgtype일 뿐이다.

`file_share`는 startup에 코드로 permanent 등록한다(`schema_conflict`와 동일 방식 —
번들 `default_schemas.jsonl`에도 등재).

## 6. HTTP 엔드포인트 (원격)

서버 파일시스템에 접근할 수 없는 원격 워커용. 신규 `file_routes.py`(`admin_routes.py`
패턴).

- **`POST /files`** — 바이트 업로드. 업로더 식별은 `X-Agora-Instance-Id` 헤더
  (auto-register와 동일) → `file_policy.can_upload` 검사. 파일명은 헤더 또는 멀티파트.
  `max_file_bytes` 초과 거부. 스토어에 저장 후 핸들 JSON 반환.
- **`GET /files/<file_id>`** — 다운로드. 스토어 파일을 바이트로 반환. 미존재 404.
- localhost 전용·토큰 없음(대시보드와 동일 — 개방·인증은 향후. 라우트를 `register`
  함수로 구조화해 게이트를 나중에 끼우기 쉽게).

## 7. TTL GC

`Sweeper`에 `file_gc_sweep(now=None) -> int` 추가 — `created_at`이 보관 기간
(`file_retention_days`, 기본 7일)을 지난 파일을 스토어(`.agentagora/files/<id>`)와
`files` 테이블에서 삭제. 삭제 건수 반환. `__main__.py`의 기존 GC 루프에 배선
(`message_gc_sweep` 옆).

## 8. 운영자 정책 교체

`admin_routes.py`에 `GET/POST /admin/file-policy`를 추가한다(`/admin/comm-matrix`와
동일 — `AGORA_ADMIN_TOKEN` Bearer 게이트). `POST` 바디는 `file-policy.json`
JSON으로 in-memory `FilePolicy`를 재기동 없이 교체. `GET`은 현재 정책 조회.

## 9. 비목표 (YAGNI)

- 업로드만(`w`) 레벨 — 무의미, 없음.
- 다운로드 권한 게이트 — 모든 레벨이 다운로드 허용, 게이트 안 함.
- 파일 버전 관리·중복 제거(같은 sha256 병합) — 단순 스토어.
- HTTP 엔드포인트 인증·네트워크 개방 — 향후. v1은 localhost 전용.
- comm-matrix fallback 행 — 별개 기능(이미 머지된 comm-matrix 수정). 별도 spec.

## 10. 플랜 분할 (독립 머지 가능)

- **Plan 1 — 파일 스토어 + MCP 도구.** `.agentagora/files/` 스토어, `files` 영속
  테이블·마이그레이션, `agora.share_file`·`agora.fetch_file` 도구, `file_share`
  빌트인 스키마, `max_file_bytes`. (FilePolicy 전 — 업로드 게이트 없이 동작.)
- **Plan 2 — `FilePolicy`.** `FilePolicy` 클래스(JSON 로드·`can_upload`·`snapshot`),
  startup 로드, `share_file`의 업로드 게이트 배선, `/admin/file-policy` 엔드포인트.
- **Plan 3 — HTTP 엔드포인트.** `file_routes.py`의 `POST /files`·`GET /files/<id>`,
  앱 와이어링.
- **Plan 4 — TTL GC.** `Sweeper.file_gc_sweep` + GC 루프 배선.

Plan 1이 먼저. Plan 2·3·4는 Plan 1 위에서 — Plan 3의 업로드도 Plan 2의 `can_upload`를
호출하므로 Plan 3은 Plan 2 이후가 자연스럽다.
