# AgentAgora 메모리 / RAG — 아이디어 노트

- 작성일: 2026-05-19
- 상태: **아이디어 기록 — 브레인스토밍 미착수 (큰 작업이라 보류).** 착수 시 brainstorming → spec → plan → 구현 사이클을 정식으로 밟는다.
- 맥락: Ruflo(다중 에이전트 오케스트레이션 플랫폼) 비교에서 드러난 기능 갭. 이 문서는 그 논의의 결정 트레일을 보존하기 위한 것이며, 완성된 설계가 아니다.

## 1. 아이디어

워커가 **과거 맥락**(대화·task 이력 등)을 회상할 수 있게 한다. 현재 AgentAgora는 대화·메시지를 SQLite에 영속하지만, 워커가 그것을 의미적으로 되짚을 수단이 없다.

## 2. 핵심 마찰 — 임베딩 모델

"RAG = 벡터 임베딩"으로 접근하면 임베딩 모델이 필요하고, 어느 선택지든 AgentAgora의 장점 하나를 깎는다:

- 로컬 무거운 모델(sentence-transformers + PyTorch) → "단일 Python 프로세스·가벼움" 훼손.
- 임베딩 API(OpenAI·Voyage·Cohere) → 외부 의존 + 건당 과금 — AgentAgora가 피해온 문제.
- **Anthropic은 임베딩 API가 없다**(Voyage 권장) — "Claude 구독으로 커버" 트릭이 임베딩엔 안 통한다.

## 3. 결정된 방향

- **FTS5 우선.** AgentAgora는 이미 SQLite를 쓰고(`messages` 테이블에 모든 메시지 영속), 환경 확인 결과 sqlite 3.50.4 + **FTS5 사용 가능**. SQLite 내장 FTS5로 키워드/BM25 검색을 붙이면 — **신규 의존성 0, 모델 0, 과금 0, 완전 결정론**. "과거 task·대화 회상"엔 키워드 검색이 대체로 충분하고, AgentAgora의 *결정론·감사가능성* 장점을 그대로 지킨다.
- **임베딩 백엔드는 플러그블.** 의미 검색이 *입증된 필요*가 됐을 때만 켠다 — 후보: 로컬 임베딩 서버(Ollama `nomic-embed-text` 등 — HTTP 호출만, 본체 가벼움·무과금 유지) / `fastembed`(in-process ONNX, torch 없이 경량). API 임베딩은 과금 때문에 비채택.
- 결론: FTS5로 시작하고, 부족이 입증되면 그때 임베딩 백엔드를 붙인다 → 도입 시점엔 "임베딩 모델 필요"라는 마찰이 사라진다.

## 4. 보류 — zero-trust federation

memory/RAG와 함께 검토했으나 보류한다. 이유: AgentAgora의 명시적 설계 전제(`docs/superpowers/specs/2026-05-18-local-remote-deployment-design.md` — "trusted 사설망만 가정, 적대적 네트워크 대비는 범위 밖")와 정면 충돌한다. 위협 모델 자체를 바꾸는 재설계라 별도 프로젝트 규모이고, "cross-trust 운영이 실제로 필요한가"가 확정되기 전엔 착수하지 않는다.

## 5. 미정 — 착수 시 브레인스토밍에서 결정

- 메모리의 정체: 기존 `messages` 테이블 위 검색만인가, 아니면 별도 메모리 스토어(`agora.remember` 류)인가.
- per-worker 메모리 vs 공유 팀 메모리.
- 인터페이스: `agora.recall` 같은 MCP 도구의 질의·결과 형태.
- FTS5 인덱싱 시점: 모든 메시지 자동 인덱싱 vs 명시적 기억.
