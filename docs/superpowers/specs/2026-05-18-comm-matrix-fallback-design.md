# comm-matrix `*` fallback 와일드카드 설계

> 2026-05-18. 이미 머지된 comm-matrix(N×N 정수 weight)에 `*` 와일드카드 fallback
> 행/열을 추가한다. 하위 호환 — `*` 없는 기존 CSV는 동작 불변.

## 1. 배경 / 동기

현 `CommMatrix`(comm-matrix v2)는 활성 시 strict whitelist다 — CSV에 등재되지 않은
`from`/`to` 인스턴스는 `weight_of`가 `0`을 반환해 `is_allowed`가 거부한다. 매트릭스에
새 인스턴스를 추가하려면 매번 CSV의 행·열을 늘려야 한다.

`*` 와일드카드 fallback을 도입해, 매트릭스에 명시되지 않은 `from`/`to`에 적용할 기본
weight를 운영자가 한 줄/한 칸으로 지정할 수 있게 한다.

## 2. `*` 와일드카드

`*`를 CSV의 일반 라벨로 취급한다. 헤더(= `from` 목록)에 `*`를 두면 미등재 발신자용
와일드카드 *열*이 되고, 데이터 행 라벨에 `*`를 두면 미등재 수신자용 와일드카드 *행*이
된다. 매트릭스는 여전히 N×N 정사각이다 — `*`도 N개 라벨 중 하나일 뿐.

```
*,pm,coder,reviewer
0,1,1,1
1,0,1,1
1,1,0,0
1,1,0,0
```

- 1행(`to=*`) — 미등재 *수신자* fallback.
- 1열(`from=*`) — 미등재 *발신자* fallback.
- `_weights["*"]["*"]` — `from`·`to` 둘 다 미등재인 catch-all.

`*`를 정식 라벨로 두면 정사각을 유지하면서 행(미등재 `to`)·열(미등재 `from`) fallback을
모두 얻고, `load_csv`·shape 검증을 전혀 건드리지 않는다. `*` 행만 두는(비정사각) 방식은
shape 검증 예외가 필요해 오히려 복잡하므로 채택하지 않는다.

## 3. 구현 변경

`src/agent_agora/comm_matrix.py`.

- **`load_csv` — 무변경.** `*`는 평범한 문자열 라벨이라 기존 파싱이 그대로 처리한다.
  `_weights["*"]`·`_weights[to]["*"]`가 자연히 채워진다. shape 검증(정사각)도 그대로.
- **`weight_of(from_, to)` — fallback 로직 추가:**

```python
def weight_of(self, from_: str, to: str) -> int:
    """from_→to 엣지의 정수 weight. 비활성이면 0.
    활성이면 셀 값, 미등재 to/from은 '*' 와일드카드 행/열로 폴백, 없으면 0."""
    if not self.active:
        return 0
    row = self._weights.get(to)
    if row is None:
        row = self._weights.get("*", {})   # 미등재 to → '*' 행
    if from_ in row:
        return row[from_]
    return row.get("*", 0)                  # 미등재 from → 행의 '*' 열, 없으면 0
```

- **`is_allowed` — 무변경.** 활성 시 `weight_of(from_, to) > 0` 그대로. `*` fallback이
  `weight_of`에 녹아 있으므로 `is_allowed`도 자동으로 fallback을 따른다.
- **`snapshot` — 무변경.** `_weights`를 그대로 반환하므로 `*` 엔트리가 포함된다.

## 4. 하위 호환

`*`가 없는 CSV에서는 `self._weights.get("*")`가 항상 없어 `row`가 `{}`로 떨어지고
`row.get("*", 0)`이 `0`을 반환한다 — 현 strict whitelist와 **정확히 동일**하다. 기존
comm-matrix CSV·테스트는 변경 없이 그대로 동작한다.

## 5. 테스트

`tests/test_v4_comm_matrix.py`:
- `*` 행만 — 미등재 `to`가 `*` 행 weight를 받는다.
- `*` 열만 — 미등재 `from`이 행의 `*` 열 weight를 받는다.
- `*`/`*` catch-all — 둘 다 미등재면 `_weights["*"]["*"]`.
- 명시 셀이 `*`보다 우선 — 등재된 `to`·`from`은 `*`로 폴백하지 않는다.
- `*` 없는 CSV는 strict whitelist 불변(미등재 from/to → `is_allowed` False).
- `is_allowed`가 `*` fallback weight>0이면 True.

## 6. 비목표 (YAGNI)

- `*` 셀에 음수·특수 의미 — `*` 셀도 일반 셀처럼 0 이상 정수, `0`=금지.
- comm-matrix 외 정책(file-policy 등)의 `*` — 무관, 이 spec은 comm-matrix만.

## 7. 구현 — 단일 플랜

변경이 `weight_of` 한 메서드 + 테스트로 작아 단일 플랜이다. 태스크: ① `weight_of`
fallback 로직 + 테스트.
