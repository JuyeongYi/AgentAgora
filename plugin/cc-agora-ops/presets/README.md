# comm-matrix 프리셋

서버측 `.agentagora/comm-matrix.csv`로 떨어뜨려 워커↔워커 dispatch ACL을 강제하는
프리셋. 비활성(파일 없음) 시 all-allow. 헤더는 정규식(인스턴스 id를 `re.fullmatch`),
셀은 0 이상 정수 weight(`from`=열 → `to`=행, 0=금지).

## `review-gated.csv` — 리뷰 게이트 파이프라인

페르소나 워크플로(planner→coder→tester→reviewer→writer)에서 **리뷰를 건너뛸 수 없게**
ACL로 강제한다. 핵심: **`coder`는 `writer`에 직접 dispatch 불가(`comm_denied`)** —
`writer`(개선/마감)는 오직 `reviewer`(와 `orchestrator`)에서만 도달 가능. 즉
"coder 작업 → reviewer 검토 → writer"가 토폴로지에 박힌다. 페르소나 SKILL.md의
"tests green → dispatch to reviewer" 규칙을 워커 자율 준수가 아니라 broker ACL로 보강.

허용 엣지 요약(`from → to`):

| from \ to | orchestrator | planner | coder | tester | reviewer | writer | general |
|-----------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| orchestrator | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| planner | ✓ | · | ✓ | · | · | · | · |
| coder | ✓ | · | · | ✓ | ✓ | **✗** | · |
| tester | ✓ | · | ✓ | · | ✓ | · | · |
| reviewer | ✓ | · | ✓ | · | · | **✓** | · |
| writer | ✓ | · | · | · | · | · | · |
| general | ✓ | · | · | · | · | · | · |

- **✗ coder→writer**(게이트): 리뷰 우회 금지. **✓ reviewer→writer**: 리뷰 통과 후에만.
- tester→coder, reviewer→coder: 실패·지적 시 재작업 루프(의도된 사이클 — `cycles()`는
  진단만, 거부 안 함).
- 모든 역할 → orchestrator: 보고/조율은 항상 허용.
- `operator:<user>`는 매트릭스와 무관하게 항상 허용(대시보드 운영자).

## 적용

워커 인스턴스 id가 페르소나명으로 시작한다고 가정(`coder1`, `Reviewer-2` 등; `(?i)`로
대소문자 무관). 서버 `--dir`의 `.agentagora/`에 복사:

```
copy plugin\cc-agora-ops\presets\review-gated.csv <server-dir>\.agentagora\comm-matrix.csv
```

서버 시작 시 로드되며, 런타임 교체는 `POST /admin/comm-matrix`(`AGORA_ADMIN_TOKEN`).
토폴로지가 팀 구성과 다르면 셀을 직접 조정하라(weight>0=허용). 회귀 테스트:
`tests/test_comm_matrix_preset.py`.
