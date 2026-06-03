# 파일 공유 일원화 (agora-channel `file.put`/`file.get`) 설계

**상태**: 설계 승인됨 (2026-06-03) — 구현 계획 대기
**토픽**: 파일 공유 방법을 브로커 HTTP `/files`(서버 중앙 저장+송신) 단일 경로로 일원화. 워커는 워커측 채널 어댑터의 MCP 도구(`file.put`/`file.get`)로만 다룬다. 분산·OS 무관.

## 배경 / 문제

현재 파일 공유는 **두 갈래**다:

- **MCP `agora.share_file(path)` / `agora.fetch_file(file_id, dest)`** (`server.py`) — 서버에서 `shutil.copyfile`로 복사. **서버=워커 같은 파일시스템(단일 머신) 전제**. MCP 도구는 서버에서 실행되므로, 분산(다른 PC/OS)에서 워커의 로컬 파일을 읽지 못해 깨진다.
- **HTTP `POST /files` / `GET /files/<id>`** (`files/routes.py`) — 서버가 바이트를 받아 `agora_dir/files/`에 저장(메타는 SQLite `files` 테이블), 다운로드로 돌려줌. **내용 전송이라 OS/경로 무관**(원격 워커용).

두 갈래 공존이 혼란이고, MCP 로컬-복사 경로는 분산에서 무용하다.

## 목표 / 비목표

**목표**
- 모든 파일 공유를 **브로커 HTTP `/files` 단일 경로**로 일원화.
- 워커는 워커측 `agora-channel` 어댑터의 MCP 도구 `file.put`/`file.get`로만 파일을 다룬다(curl 불필요).
- 단일머신·분산·OS 무관.

**비목표 (YAGNI)**
- 파일 바이트의 DB(BLOB) 저장 — 100MB까지라 현행(디스크 + 메타 DB)이 적절.
- 디렉터리/폴더 통째 공유, 자동 watch/sync.
- `file.put`의 자동 dispatch — 업로드와 메시지 전송은 분리(아래).

## 핵심 제약

`agora-channel`은 **워커 PC에서 도는 stdio MCP 서버**(워커 Claude가 자식으로 spawn). 따라서 어댑터는 **워커 로컬 파일을 읽고/쓸 수 있고** 동시에 브로커 HTTP를 호출할 수 있다 — 서버측 MCP 도구가 못 하던 것. 이 위치가 일원화의 열쇠다.

## 구조 / 위치

| 파일 | 변경 |
|------|------|
| `channel_adapter.py` | stdio MCP 서버에 `file.put`/`file.get` 도구 등록. 현재 도구 표면이 비어 있으니 `Server` lowlevel에 `list_tools`/`call_tool` 추가. |
| `_broker_http.py` | 브로커 `/files` 업로드(POST)·다운로드(GET) httpx 헬퍼 추가(`/channel/wait`와 동거). |
| `server.py` | `agora.share_file`/`agora.fetch_file` 도구 제거(폐기). |
| `files/` | 변경 없음(서버 저장소·라우트는 그대로 단일 경로의 백엔드). |

## 인터페이스

- **`file.put(path)`** → 어댑터가 워커 로컬 `path`를 읽어 브로커 `POST /files`(헤더 `X-Agora-Instance-Id`=워커, `X-Agora-File-Name`=basename)로 전송 → `{file_id, name, size, sha256}` 반환. 워커는 이 `file_id`를 `agora.dispatch`로 `file_share` 메시지에 실어 보낸다(대화 컨텍스트는 dispatch가 자유롭게 — 업로드와 분리).
- **`file.get(file_id, dest_path?)`** → 브로커 `GET /files/<file_id>` → `dest_path`(생략 시 `./agora-inbox/<원래이름>`)에 저장 → `{path, name, size}` 반환.

## 데이터 흐름

- **송신**: 워커 → `file.put(path)` → (어댑터가 로컬 읽어 HTTP 업로드) → `file_id` → 워커가 `agora.dispatch({msgtype:"file_share", file_id, name, ...}, to)`
- **수신**: 워커가 `agora.flush`로 `file_share` 수신 → `file_id` 추출 → `file.get(file_id)` → `./agora-inbox/<이름>`에 저장

## 경로(저장 위치) 규약

- `file.get`의 `dest_path` 생략 시 기본 `./agora-inbox/<원래이름>`(워커 cwd 기준). inbox 디렉터리는 자동 생성.
- **충돌**: 대상 경로(dest 또는 inbox/<name>)에 파일이 **이미 있으면 덮어쓰지 않고 에러 반환** — `file_exists`. 예: `{"error":"file_exists: '<path>'에 파일이 이미 있습니다. dest_path로 다른 위치를 지정하거나 기존 파일을 옮기세요."}`. 워커가 받아 dest를 바꾸거나 기존 파일을 정리한다.

## 에러 / 제약

- `file.put`: 파일 없음(로컬), 크기 초과(`file_too_large`, `/files` 413), 업로드 거부(403, `file_policy.can_upload`).
- `file.get`: `unknown_file`(404), 다운로드 거부(403, `file_policy.can_download`), `file_exists`(대상 존재).
- 모든 에러는 도구 반환 JSON `{"error": ...}`로 워커(인스턴스)에 전달.
- `file_exists`는 `errors.py`에 새 코드로 추가(기존 `file_too_large` 등과 동일 패턴).

## 테스트 (TDD)

- `_broker_http` `/files` 업로드·다운로드 헬퍼 단위(httpx mock 또는 라이브 브로커).
- `channel_adapter` `file.put`/`file.get`: 브로커 mock으로 업로드→file_id, 다운로드→inbox 기본 경로, 충돌 시 `file_exists`.
- `server.py` `share_file`/`fetch_file` 제거 — 관련 기존 테스트 정리.
- 통합: 라이브 브로커로 `put → dispatch(file_share) → get` round-trip(분산 모사: bind 0.0.0.0).

## 호환 / 마이그레이션

- `agora.share_file`/`agora.fetch_file` 제거 → 그 도구를 참조하는 곳(docs `file-sharing.md`, plugin 스킬 등) 정리.
- `file_share` 스키마는 그대로(`file_id` 기반).
- HTTP `/files` 라우트는 유지(단일 경로의 백엔드 + 직접 curl도 가능).

## 미해결 / 구현 시 확인

- MCP 도구명에 점(`file.put`) 사용 — `agora.flush` 등 점 포함 도구가 이미 동작하므로 문제없을 것이나 등록 시 확인.
- **도구 + 알림 공존 (확정)**: `agora-channel`을 `Server.run`(표준 도구 처리)으로 전환한다. `Server.run(read_stream, write_stream, init_opts, ...)`이 **write 스트림을 인자로 받으므로**, `stdio_server()`가 준 `write_stream`을 보유한 채 `run`에 넘기고 백그라운드 watch가 **같은 `write_stream`으로 claude/channel 알림을 emit**한다(anyio 스트림은 SessionMessage 객체 단위 send라 동시성 안전). MCP 서버는 agora-channel 1개 유지(추가 없음). watch는 run과 동시 시작하고, 핸드셰이크 직전 짧은 창의 emit 유실은 기존 reemit self-heal이 복구.
- 수신 파일명 — `file.get`이 `inbox/<원래이름>`을 정하려면 이름이 필요하므로, `/files` 다운로드 응답에 `Content-Disposition: filename`을 실어(`FileResponse(filename=meta["name"])`) 어댑터가 추출한다. dest_path를 주면 그 경로 우선.
- 파일 크기 상한(100MB)에서 어댑터가 전체를 메모리에 버퍼하는지 스트리밍하는지 — `/files` 업로드는 스트리밍 cap이 있으나 어댑터측 읽기도 점검(초판은 전체 read_bytes, 추후 스트리밍).
