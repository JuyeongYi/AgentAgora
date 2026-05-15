---
description: Manually invoke agora.wait with fine-grain controls — timeout, from_sources filter, sort by priority, or filter by conversation_id.
---

# /cc-agora:agora-wait

`agora.wait` 도구를 fine-grain 인자로 직접 호출한다. spec §4.4.

## 인자

- `--timeout=<ms>` (선택): wait 타임아웃 밀리초. 미지정 또는 `0`이면 unbounded(서버가 `--no-timeout` 적용 상태일 때). 인자 없으면 Stop hook 디폴트와 동일하게 unbounded.
- `--from=<id1,id2,...>` (선택): 콤마로 구분된 source instance_id 목록. 지정하면 해당 source에서 온 메시지만 깨운다.
- `--conv=<conv_id>` (선택): 특정 conversation_id에 묶인 메시지만 깨운다.
- `--sort=fifo|priority` (선택): 큐 정렬. 디폴트 `fifo`. `priority`는 `/cc-agora:invoke --priority=high` 메시지를 앞으로 끌어온다.

## 동작

1. 인자를 파싱해 `agora.wait` MCP 도구를 호출한다:
   - `timeout_ms` ← `--timeout` (없으면 `None` 또는 `0`).
   - `from_sources` ← `--from`을 콤마 분리해 리스트로 변환. 미지정 시 `None`.
   - `sort` ← `--sort` (디폴트 `"fifo"`).
   - `by_conversation` ← `--conv`. 미지정 시 `None`.
2. 응답 메시지(들)를 그대로 사용자에 출력한다. envelope 메타(`delivered_as`, `source`, `conversation_id` 등)를 같이 표시한다.
3. Stop hook이 디폴트 폴링(timeout=0 unbounded)을 담당하므로 본 슬래시는 fine-grain 제어용이다. 일상에는 hook이 자동 처리한다.

## 예시

```
/cc-agora:agora-wait --timeout=5000 --from=Coder1,Coder2 --sort=priority
```

Coder1·Coder2에서 오는 메시지만 priority 정렬로 최대 5초 기다리고, 도착 메시지를 envelope 메타와 함께 출력한다.
