# comm-matrix v2 — 엣지 weight 우선순위 설계

> 2026-05-17. comm-matrix를 0/1 불리언 ACL에서 0 이상 정수 weight로 확장한다.
> 선행: `2026-05-17-comm-matrix-governance-design.md`(운영자 전용 admin 엔드포인트).

## 1. 배경 / 동기

현 `CommMatrix`는 worker↔worker dispatch를 0/1로 허용·금지만 한다. 운영자가
"이 엣지의 메시지는 더 중요하다"는 구조적 우선순위를 표현할 수단이 없다.

별개로 메시지 envelope에는 발신자가 선언하는 `priority`(high/normal/low)가
이미 있고, `flush(sort="priority")`가 이를 정렬에 쓴다.

v2는 comm-matrix 셀을 정수 weight로 바꾼다. `0`=금지, `>0`=허용이며 그 값이
수신자 인박스에서의 처리 우선순위다. 운영자가 제어하는 **엣지 weight**와
발신자가 선언하는 **메시지 priority**는 의미가 다른 별개 차원으로, 하나로
합치지 않고 정렬 키 튜플의 1차/2차로 둔다.

## 2. 정렬 우선순위 결정

수신자가 `flush`로 인박스를 받을 때 정렬 키는 다음 순서다:

1. **엣지 weight** (`matrix[수신자][발신자]`) — 내림차순, 큰 값 먼저
2. **메시지 priority** (high→normal→low)
3. **created_at, id** — FIFO 타이브레이크

엣지 weight를 1차로 두는 근거: weight는 운영자가 의도적으로 설정한 거버넌스
계층이며 워커가 변조할 수 없다. 메시지 priority는 발신자의 힌트로, 모든
메시지에 `high`를 다는 식의 게이밍이 가능하므로 2차 키가 적절하다.

weight는 (발신자, 수신자) 쌍마다 고정값이므로, 결과적으로 정렬은 "발신자별로
묶고 → 각 발신자의 메시지들은 그가 선언한 긴급도 순"이 된다.

## 3. 데이터 모델

`CommMatrix`의 내부 표현을 바꾼다:

```
# v1
self._allowed: dict[str, set[str]]   # _allowed[to] = {from, ...}

# v2
self._weights: dict[str, dict[str, int]]   # _weights[to][from] = weight
```

CSV 형식은 그대로 — 헤더 1줄(`from` 목록) + 데이터 N줄. 셀만 `0/1`에서
**0 이상 정수**로 확장된다.

```
pm,coder,reviewer
0,5,5
10,0,1
10,1,0
```

위 예: `pm`이 받을 때 `coder`·`reviewer`는 weight 5. `coder`가 받을 때 `pm`은
weight 10, `reviewer`는 weight 1. 셀 `0`은 금지.

기존 `0/1` CSV는 변경 없이 호환된다 — `1`은 weight 1로 읽힌다.

## 4. CommMatrix API

| 메서드 | v1 | v2 |
|--------|----|----|
| `is_allowed(from_, to) -> bool` | `from_ in _allowed[to]` | 비활성→`True`, 활성→`weight_of(from_,to) > 0` |
| `weight_of(from_, to) -> int` | (없음) | 비활성→`0`, 활성→`_weights.get(to,{}).get(from_, 0)` |
| `snapshot() -> dict` | `{to: [from,...]}` | `{to: {from: weight}}` |
| `load_csv(text)` | 셀 `=="1"` | 셀을 `int`로 파싱 |

`load_csv`는 각 셀을 정수로 파싱한다. 정수가 아니거나 음수면 신규 에러
`AgoraError("comm_matrix_invalid_cell", detail=...)`로 거부한다. shape 불일치는
기존대로 `comm_matrix_shape_mismatch`.

`is_allowed`는 활성 시 `weight_of > 0`과 동치다. 비활성(CSV 없음) 매트릭스는
v1과 동일하게 all-allow이며, `weight_of`는 항상 `0`을 반환해 weight 차원을
평탄하게 만든다 — 이때 정렬은 메시지 priority로만 갈린다.

## 5. flush 정렬

`Dispatcher.flush`의 정렬을 weight-aware로 바꾼다.

```python
# sort == "priority" (신규 기본값)
drained.sort(key=lambda e: (
    -self._comm_matrix.weight_of(e.source, instance_id),
    _PRIORITY_RANK[e.priority],
    e.created_at,
    e.id,
))
# sort == "fifo" (escape hatch, 유지)
drained.sort(key=lambda e: (e.created_at, e.id))
```

- `flush(sort=...)`의 기본값을 `"fifo"` → `"priority"`로 바꾼다. 채널 어댑터·봇
  등 `sort` 미지정 호출자는 자동으로 weight-aware 정렬을 받는다.
- `sort="fifo"`는 `(created_at, id)`만 — 디버깅·검증용 escape hatch로 남긴다.
- weight는 **flush 시점에 조회**한다. envelope·DB 스키마는 바뀌지 않는다.
  dispatch와 flush 사이 매트릭스가 교체되면 최신 정책이 반영된다.
- 내부 `_queues[target]`는 `list`로 유지한다. `flush`가 큐를 전량 드레인하므로
  정렬은 드레인 시점에 한 번 하면 충분하다 — heapq로 바꿔도 관측 동작은 동일.

## 6. 엣지 케이스

- **cc 메시지** — cc는 comm-matrix ACL 면제(governance spec 유지). 0-엣지/미등재
  발신자의 cc는 `weight_of`가 `0`을 반환해 정렬 최하위로 간다. 사본은 후순위라는
  의도된 동작이다.
- **broadcast 수신분** — broadcast는 fan-out 단계에서 이미 ACL(`weight>0`)을
  통과한 대상에만 도달하므로 자연스럽게 정렬된다.
- **봇 인박스** — 봇은 comm-matrix 대상이 아니다. `weight_of`가 `0`이라
  봇 인박스 정렬은 메시지 priority로 폴백한다.
- **재시작 복구** — `restore_from_persistence`로 복구된 메시지도 flush 시점
  조회라 현재 매트릭스 기준으로 정렬된다.

## 7. admin 엔드포인트

`GET /admin/comm-matrix` 응답의 `matrix` 필드가 `snapshot()` 변경에 따라
`{to: {from: weight}}` 형태가 된다. `POST`는 CSV 본문을 그대로 받아
`load_csv`에 넘기므로 변경 없음 — 정수 파싱은 `load_csv` 내부에서 처리된다.

## 8. 테스트

`tests/test_v4_comm_matrix.py`:
- 정수 weight CSV 파싱 → `weight_of`가 셀 값 반환.
- `is_allowed`가 `weight_of > 0`과 동치.
- 음수·비정수 셀 → `comm_matrix_invalid_cell`.
- 기존 `0/1` CSV 하위호환 — `1`→weight 1, `0`→금지.
- `snapshot()`이 `{to:{from:weight}}` 형태.
- 비활성 매트릭스 — `is_allowed`=True, `weight_of`=0.

`tests/test_v3_dispatcher.py`:
- flush `sort="priority"` — weight 큰 발신자 메시지가 먼저.
- 같은 weight 내에서 메시지 priority(high>normal>low) 순.
- 같은 weight·priority 내에서 created_at FIFO.
- 비활성 매트릭스 — weight 평탄, priority로만 정렬.
- `sort="fifo"`는 created_at 순 그대로.

`tests/test_v4_comm_matrix.py` 또는 admin 테스트:
- `GET /admin/comm-matrix`의 `matrix`가 weight 형태.

## 9. 플랜 분할 (독립 머지 가능)

- **Plan 1 — CommMatrix v2 모델.** `_weights` 내부 표현, `weight_of`, `is_allowed`
  재정의, `load_csv` 정수 파싱 + `comm_matrix_invalid_cell`, `snapshot()` 형태
  변경, admin GET 응답. 정렬을 건드리지 않으므로 dispatch 동작 불변 — 단독
  머지 가능.
- **Plan 2 — flush weight-aware 정렬.** `flush` 정렬 키를 weight-aware로,
  `sort` 기본값을 `"priority"`로. Plan 1의 `weight_of`에 의존.

## 10. 비목표 (YAGNI)

- weight 기반 inbox depth 차등 (`max_inbox_depth`는 균일 유지).
- broadcast fan-out 순서에 weight 반영 (수신자별 인박스 정렬로 충분).
- weight를 envelope에 stamp / DB 영속화 (flush 시점 조회로 충분).
- `_queues`를 heapq로 전환 (전량 드레인이라 불필요).
