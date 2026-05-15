---
description: Recommend the best cc-agora worker for a natural-language task using agora.find then propose an /invoke chaining string for manual confirmation.
---

# /cc-agora:agora-target

자연어 task에 가장 적합한 워커 한 명을 추천한다. spec §4.3.

## 인자

- `"<task>"`: 자연어 작업 설명. 따옴표로 감싸 공백을 보존한다.

## 동작

1. **키워드 추출** — `<task>`에서 핵심 키워드 1~3개를 뽑는다. 예: "react 컴포넌트 작성" → "react", "component", "코딩". 키워드는 영문/한글 모두 가능하다.
2. **1차 필터** — 가장 강한 키워드 1개를 골라 `agora.find(query=<keyword>)` 도구를 호출한다. 필요하면 다른 키워드로 한 번 더 호출해 합집합을 만든다. 후보는 instance_id/role/description 중 키워드를 포함하는 인스턴스만 추려진다(spec §4.3 step 1, `src/agent_agora/server.py:131`).
3. **2차 필터** — 1차 결과가 0건이면 `agora.instances()`를 호출해 전체 목록을 받아 task와 매칭한다.
4. **1순위 선택** — 후보 중 task에 가장 적합한 1명을 role/description을 보고 선택한다. 인스턴스 수가 ≤3명이면 사유를 2~3문장, 더 많으면 1문장으로 줄인다.
5. **chaining 제안 (자동 발사 X)** — 다음 한 줄을 그대로 출력한다:

   ```
   /cc-agora:invoke <recommended-id> "<task>"
   ```

   spec §9.1대로 Claude Code가 슬래시 응답을 다음 입력으로 prefill 하는 표준 메커니즘은 없다고 전제한다. 사용자가 위 문자열을 복사·수정·확정 후 Enter를 누른다. 본 슬래시는 절대로 `agora.dispatch`를 직접 호출하지 않는다.

## 출력 예시

후보 3명일 때:

```
추천: Coder1
사유: role=coder이며 description에 "React"가 포함돼 task와 일치한다. Coder2는 백엔드 중심이라 우선순위가 낮다.

다음 명령 (사용자 확정 필요):
/cc-agora:invoke Coder1 "React 컴포넌트로 로그인 폼 작성"
```

## 예시

```
/cc-agora:agora-target "React 컴포넌트로 로그인 폼 작성"
```

추천 워커 1명 + chaining 문자열이 출력되고, 발사는 사용자가 결정한다.
