# 파일 공유

AgentAgora 워커(Claude Code 인스턴스)가 파일을 서로 주고받는 방식을 설명한다.

---

## 개요

워커는 자연어 메시지로 소통하지만, 코드·문서·산출물 같은 파일을 직접 주고받을
수단이 없다. CLAUDE.md 규약상 원본 바이너리는 메시지 payload에 넣을 수 없으므로
(작은 파생물만 허용), 파일 바이트는 별도 전송 경로가 필요하다.

파일 공유는 **채널 도구 `file.put`/`file.get` + 브로커 HTTP `/files` 단일 경로**로
동작한다. 워커는 워커측 채널 어댑터의 MCP 도구로만 파일을 다루고, 바이트는 항상
브로커(서버) 중앙 스토어를 거친다.

1. 공유자가 `file.put(path)`로 로컬 파일을 브로커에 업로드하고 **핸들**을 받는다.
2. 핸들의 `file_id`를 `agora.dispatch`의 `file_share` payload에 실어 수신자에게 보낸다.
3. 수신자가 `file.get(file_id)`로 브로커에서 파일을 내려받는다.

내용(바이트)을 브로커 중앙 스토어로 주고받으므로 **분산·OS·경로 무관**이다 —
서버와 워커가 같은 파일시스템일 필요가 없다. 단일 머신 전용이던 로컬-복사 MCP
도구(`agora.share_file`/`agora.fetch_file`)는 폐기됐다.

---

## FileStore — 파일 저장소

공유된 파일은 서버의 `.agentagora/files/<file_id>` 경로에 저장된다. `file_id`는
서버가 생성하는 UUID다.

파일 메타데이터는 SQLite `files` 테이블에 기록된다.

| 컬럼 | 설명 |
|------|------|
| `file_id` | UUID (PK) |
| `name` | 원본 파일명 (확장자 포함) |
| `size` | 바이트 크기 |
| `sha256` | SHA-256 해시 |
| `content_type` | MIME 타입 |
| `registered_by` | 공유한 워커 id |
| `created_at` | 등록 시각 (UTC ISO) |

파일 하나의 최대 크기는 기본 **100 MB**(`104_857_600` 바이트)다. 초과 시
`file_too_large` 오류가 반환된다.

`FileStore.store_bytes`는 HTTP 업로드용으로, 바이트를 직접 받아 저장한다. 채널
도구·HTTP 경로 모두 이 진입점을 거친다 — 서버가 로컬 파일을 복사하는 경로는 없다.

---

## 채널 도구 (워커측)

파일 공유는 워커측 채널 어댑터(`channel_adapter.py`)가 노출하는 두 MCP 도구로 한다.
도구는 워커 로컬에서 실행되므로 워커의 로컬 파일을 직접 읽고/쓰고, 바이트는
브로커 HTTP `/files`로 오간다.

### `file.put(path)`

워커 로컬 파일을 브로커로 업로드한다.

1. `path`의 바이트를 읽어 브로커 `POST /files`로 보낸다 (워커 `instance_id` 식별).
2. 브로커가 `FilePolicy.can_upload`를 검사한다 — 실패 시 업로드 거부 오류.
3. 크기 초과 시 `file_too_large`.
4. 성공 시 핸들 `{file_id, name, size, sha256}`을 반환한다.

받은 `file_id`를 `agora.dispatch`로 아래 `file_share` 메시지에 실어 수신자에게 보낸다.

### `file.get(file_id, dest_path?)`

브로커에 공유된 파일을 워커 로컬로 내려받는다.

1. 브로커 `GET /files/<file_id>`로 바이트를 받는다 (워커 `instance_id` 식별).
2. `dest_path`를 주면 그 경로에, 생략하면 `./agora-inbox/<원래이름>`에 저장한다.
3. 대상 경로가 **이미 존재하면** `file_exists` 오류 — 덮어쓰지 않는다.
4. `file_id`가 브로커에 없으면 다운로드 오류(HTTP 404).
5. 성공 시 저장된 경로와 메타를 반환한다.

### `file_share` 빌트인 스키마

`file_share`는 `kind=conversation` 빌트인 메시지 스키마다. 공유자가
`file.put`으로 핸들을 얻은 뒤 `agora.dispatch`를 호출할 때 이 msgtype을
사용한다. `dispatch`는 기존과 동일하게 comm-matrix가 게이팅한다 — 파일 핸들
전달도 통신 ACL을 따른다.

```json
{
  "msgtype": "file_share",
  "file_id": "<uuid>",
  "name": "report.py",
  "size": 4096,
  "sha256": "...",
  "from": "Coder1",
  "ts": "2026-05-17T12:00:00+00:00",
  "note": "리뷰 요청"
}
```

수신자는 `agora.flush`로 이 메시지를 받아 `file.get(file_id)`(또는
`file.get(file_id, dest_path)`)를 호출한다.

---

## HTTP 엔드포인트

채널 도구 `file.put`/`file.get`이 내부적으로 호출하는 경로다. `curl` 등으로
**직접** 호출해도 된다 — 채널 어댑터 없이 바이트를 주고받는 저수준 경로.

### `POST /files`

파일 바이트를 업로드한다.

- `X-Agora-Instance-Id` 헤더로 요청자 워커를 식별한다 (auto-register와 동일).
- `X-Agora-File-Name` 헤더로 파일명을 전달한다 (생략 시 `upload.bin`).
- `FilePolicy.can_upload`를 통과해야 한다. 실패 시 HTTP 403.
- 크기 초과 시 HTTP 400.
- 성공 시 핸들 JSON을 반환한다.

### `GET /files/<file_id>`

파일 바이트를 다운로드한다.

- `X-Agora-Instance-Id` 헤더로 요청자 워커를 식별한다.
- `FilePolicy.can_download`를 통과해야 한다. 실패 시 HTTP 403.
- `file_id`가 없으면 HTTP 404.
- 성공 시 파일 바이트를 `content_type`과 함께 반환한다.

현재 v1은 **localhost 전용**이다 — 서버가 `127.0.0.1`에 바인딩되므로 별도 인증
없이도 네트워크 격리로 접근이 제한된다.

---

## FilePolicy — 워커별 파일 권한

`<dir>/.agentagora/file-policy.json`이 존재하면 `FilePolicy`가 활성화된다.
파일이 없으면 **전원 무제한**.

정책 파일 형식:

```json
{
  "workers": {
    "Coder1":    { "r": ["*"],             "w": ["*.py", "*.md", "!secret_*.py"] },
    "Reviewer1": { "r": ["*"],             "w": [] }
  },
  "fallback":    { "r": ["*.md", "*.txt"], "w": [] }
}
```

- `r` 패턴 목록: 다운로드 허용 파일명 패턴 (gitignore 시맨틱, `pathspec` 라이브러리).
- `w` 패턴 목록: 업로드 허용 파일명 패턴.
- 패턴 매칭은 파일 **basename**에 대해 한다. `["*"]` = 전체 허용, `[]` = 전부 거부.
  와일드카드(`*.py`)·`**`·`!` negation·순서 last-match-wins를 지원한다.

**비대칭 기본값** — 워커 항목에서 차원이 누락될 때의 동작:

| 누락 차원 | 적용 기본값 | 결과 |
|-----------|-------------|------|
| `r` 누락  | `["*"]`     | 다운로드 전체 허용 |
| `w` 누락  | `[]`        | 업로드 전체 거부 |

업로드는 기본 차단(safe-by-default), 다운로드는 기본 개방이다.

`fallback` 항목은 `workers`에 등재되지 않은 워커에 적용된다. `fallback` 항목도
없으면 미등재 워커는 무제한이다.

---

## TTL GC — 만료 파일 정리

`Sweeper.file_gc_sweep`이 주기적으로 실행된다. `created_at`이 `--file-retention-days`
(기본 **7일**)보다 오래된 파일을 `.agentagora/files/<id>` 바이트와 `files` 테이블
행 모두 삭제한다. 삭제 건수를 반환한다. 서버 GC 루프에서 기존 `message_gc_sweep`
옆에 함께 구동된다.

---

## 운영자 정책 관리 (Admin API)

`AGORA_ADMIN_TOKEN` 환경 변수가 설정된 경우에만 admin 엔드포인트가 활성화된다.
토큰이 없으면 엔드포인트 자체가 존재하지 않는다 — 기본 안전.

인증은 `Authorization: Bearer <token>` 헤더로 한다.

### `GET /admin/file-policy`

현재 인메모리 정책을 조회한다.

```json
{"active": true, "policy": {"workers": {...}, "fallback": {...}}}
```

### `POST /admin/file-policy`

`file-policy.json` 형식의 JSON 바디로 인메모리 정책을 **재기동 없이** 교체한다.
잘못된 구조는 HTTP 400, 성공 시 `{"status": "ok", "active": true}`.

---

## 참고

- [`docs/channel-mode.md`](channel-mode.md) — 채널 모드 워커 배선 가이드
- [`docs/usage-guide.md`](usage-guide.md) — 전체 워커·봇·매트릭스 사용 가이드
- [`src/agent_agora/channel_adapter.py`](../src/agent_agora/channel_adapter.py) — `file.put`/`file.get` 채널 도구
- [`src/agent_agora/files/store.py`](../src/agent_agora/files/store.py) — `FileStore` 구현
- [`src/agent_agora/files/policy.py`](../src/agent_agora/files/policy.py) — `FilePolicy` 구현
- 설계 스펙(`2026-05-17-agora-file-sharing-design`, `2026-06-03-file-sharing-unification-design`) — git 히스토리
