# agora-channel 어댑터 주기적 재발화 설계

- 작성일: 2026-05-18
- 상태: 설계 승인 → 구현
- 브랜치: `channel-reemit`

## 1. 문제

`agora-channel` 어댑터의 `watch_loop`(`channel_adapter.py`)는 인박스 도착을 감지하면
`claude/channel` 알림을 emit해 워커를 깨운 뒤, 워커가 큐를 드레인할 때까지 대기한다:

```python
await emit(content, meta)
while await peek_pending(instance_id) > 0:
    await asyncio.sleep(drain_poll_s)
```

이 drain 대기 루프에는 **재발화가 없다.** 워커가 드레인하지 않으면 — `claude/channel`
알림 드롭(research preview, 전달 ack 없음), 컴팩션으로 채널 루프 상태 상실, 워커 에러
등 — 어댑터는 이 루프에 영구히 갇혀 다시 emit하지 않는다. **알림 한 번 유실 = 그 워커
영구 정지.**

## 2. 목표 / 비목표

**목표** — 인박스가 비지 않은 채로 일정 시간이 지나면 어댑터가 `claude/channel`을
재발화해, 워커가 결국 다시 깨어나 드레인하도록 self-heal한다.

**비목표**

- 서버 측 변경. 브로커는 워커 채널로 발신할 수 없다(채널 연결 없음). 신호는 어댑터만
  emit할 수 있다.
- 정상 드레인 중 재발화. edge-triggered 동작은 유지 — `reemit_interval_s` 동안
  인박스가 계속 비지 않을 때만 재발화가 작동한다(짧게 드레인하면 재발화 없음).

## 3. 설계

`watch_loop`에 키워드 파라미터 `reemit_interval_s: float = 30.0`을 추가한다. drain
대기 루프를 다음으로 바꾼다:

- `drain_poll_s` 간격으로 `peek_pending`을 폴링한다.
- `peek_pending`이 0이면 루프 종료 → `wait_notify`로 복귀(기존과 동일).
- 인박스가 계속 비지 않은 누적 시간이 `reemit_interval_s`를 넘으면 `claude/channel`을
  재발화하고 누적 카운터를 리셋한다.

재발화 content는 `format_channel_notification(instance_id, depth, sources)` —
`depth`는 `peek_pending`의 최신값, `sources`는 최초 `wait_notify` signal의 값(재발화엔
약간 stale해도 무방 — 정보성 힌트다).

`watch_loop` 호출부(`_run_watch`)는 변경하지 않는다 — `reemit_interval_s`는 기본값
`30.0`을 쓴다. (CLI 노출은 YAGNI — 필요 시 후속.)

## 4. 부작용

워커가 정상적으로 긴 턴을 처리 중이어도(인박스 미드레인) `reemit_interval_s`마다
재발화가 쌓인다. 무해 — 워커는 턴이 끝나면 한 번의 `agora.flush`로 전부 처리한다.
영구 정지보다 압도적으로 낫다.

## 5. 파일 영향

| 파일 | 변경 |
|---|---|
| `src/agent_agora/channel_adapter.py` | `watch_loop` — `reemit_interval_s` 파라미터 + drain 루프 재발화 |
| `tests/test_channel_adapter.py` | 재발화 테스트 추가 |

## 6. 검증

- `peek_pending`이 계속 `> 0`이면 `emit`이 최초 1회 + `reemit_interval_s`마다 재발화로
  여러 번 호출된다.
- `peek_pending`이 곧 0이 되면 재발화 없이 `wait_notify`로 복귀한다 — 최초 emit 1회뿐.
