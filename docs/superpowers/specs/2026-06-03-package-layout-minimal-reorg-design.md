# 패키지 레이아웃 — `dashboard/`·`files/` 최소 서브패키지화 설계

작성일: 2026-06-03
브랜치(예정): `feat/subpkg-files-dashboard`
선행 분석: 2026-06-03 패키지 재구성 워크플로(의존그래프 정밀 매핑 → 후보 3종 → 적대적 평가 → 권고)

## 1. 배경과 문제

`src/agent_agora/`의 28개 모듈이 평면(flat)으로 깔려 있다. "모듈로 묶을 코드가
많아 보인다"는 직관에서 출발해 서브패키지 재구성을 검토했다.

**핵심 사실 — 의존그래프는 이미 깨끗한 무순환 DAG다.** 실제 소스 대조(grep + Read)로
확인:

- leaf가 바닥에 있다: `errors`(in-degree 7)·`registry`(8)·`persistence`(7)·`envelope`는
  내부 import가 0인 코어 leaf.
- 정적 순환 0: `dispatcher`↔`sweeper`는 `sweeper`가 `dispatcher`를 static import하지
  않고 런타임 주입(`dispatcher=self`)만 받는다. `dispatcher`는 `conversation_store`·
  `sweeper`·`dispatch_persistence`를 **함수스코프 lazy import**(`dispatcher.py:83/92/102`)로
  들여 구성 시점 순환을 끊는다.

따라서 서브패키징은 **결합을 줄이지 못한다** — 이미 DAG라 엣지를 없앨 게 없고, import
경로만 길게 relabel한다(coupling *reduction*이 아니라 *relabeling*). 전면 계층화
(full-by-layer)·도메인 분리(by-domain)는 24~28모듈 이동 + 235개 테스트 import(49파일)
갱신이라는 최대 churn을 치르고 얻는 게 탐색성뿐이라 **이 소규모 저장소엔 과하다**(권고 안 함).

**두 가지 통증의 구분:** "묶을 코드가 많다"는 직관은 (a) 평면 28모듈 탐색성과
(b) `dispatcher.py` 1084줄·`server.py` 696줄 god-module이 섞인 것이다. **(b)는 파일
이동이 아니라 분해이고**, 어떤 패키지 재구성도 1084줄을 1줄도 줄이지 못한다 — 별도
plan(`dispatcher-fanout-decompose-skeleton`) 소관. 본 spec은 (a) 중 ROI가 명확한
부분만 다룬다.

## 2. 설계 결정 트레일 — 왜 minimal인가

판단 기준(순환안전 > 응집/결합 > blast radius > 탐색성)으로 후보 3종을 거른 결과:

- **순환안전**은 셋을 못 가른다(전부 신규 순환 0). 단 라우팅 코어를 패키지로 가르면
  lazy-import 절단선이 *cross-package*가 되어 "방어적 lazy"가 "경계유지 필수 lazy"로
  격상되는 함정이 생긴다. minimal은 라우팅 코어 전체를 평면에 남겨 이 절단선을 같은
  공간에 가둔다 — 구조적으로 가장 안전.
- **결합 감소**는 셋 다 ≈0(DAG라 줄일 엣지 없음).
- **blast radius**: minimal은 inbound-0인 7모듈만 이동 → 최소.
- 남는 실익(탐색성) 중 ROI가 명확한 것은 **`server` import 그래프에서 `__main__`만이
  import하는** 두 feature slice(`dashboard` 4모듈, `files` 3모듈)를 디렉터리로 묶는 것.
  이 7모듈은 코어 leaf로만 의존이 나가 묶어도 결합이 안 늘고, 데이터파일(`dashboard.html`·
  `dashboard_static/`)과 라우트가 한곳에 모여 탐색 실익이 실재한다.

→ minimal은 keep-flat보다 한 뼘 낫고(저비용 feature 응집), full/by-domain보다 압도적으로
안전하다.

## 3. 비목표 (Non-goals)

- 라우팅 코어(`dispatcher`/`server`/`sweeper`/`conversation_store`/`dispatch_persistence`/
  `schemas`/`comm_matrix`/`bot_registry`/`envelope`/`errors`/`registry`/`persistence`)
  서브패키지화 — **하지 않는다**. lazy-import 절단선을 평면에 가두는 것이 가장 안전.
- HTTP 라우트 통합 서브패키지(`admin_routes`/`channel_routes`/`auto_register`) — 보류.
  `admin_routes→comm_matrix`, `channel_routes→dispatcher` 의존 때문에 routes로 묶으면
  cross-package 참조만 늘어난다. (결과적으로 라우트가 평면 3 + `files/` + `dashboard/`
  세 곳에 흩어지는 비대칭은 의도된 trade-off — backlog에 명시.)
- `bot.py`·`channel_adapter.py` 이동 — 보류. 내부 import 0(standalone)이라 이동 이득이
  적고, `channel_adapter`는 진입점(`agora-channel`)이라 옮기면 lockstep 갱신 필요.
- `schemas.py` 이동 — 보류. `default_schemas.jsonl`을 `Path(__file__).with_name`으로
  로드하고 라우팅 코어가 공유하므로 평면 유지.
- god-module 분해(`dispatcher`/`server`) — 본 spec 범위 밖(별도 plan).
- `__main__.py` 이동 — 진입점 `agent_agora.__main__:main` 고정, 그대로 둔다.

## 4. 목표 레이아웃

```
src/agent_agora/
├── (21개 모듈 평면 유지: __init__, __main__, errors, registry, envelope,
│    persistence, schemas, default_schemas.jsonl, comm_matrix, bot_registry,
│    conversation_store, dispatch_console, dispatch_persistence, sweeper,
│    dispatcher, server, auto_register, admin_routes, channel_routes, certs,
│    bot, channel_adapter)
├── dashboard/
│   ├── __init__.py          # re-export: register, EventBroker, HealthCollector,
│   │                        #   DashboardAuthMiddleware, parse_tokens
│   ├── routes.py            # ← dashboard_routes.py
│   ├── events.py            # ← dashboard_events.py
│   ├── auth.py              # ← dashboard_auth.py
│   ├── health.py            # ← dashboard_health.py
│   ├── dashboard.html       # ← 동거 이동 (routes.py가 with_name으로 로드)
│   └── dashboard_static/    # ← 동거 이동
└── files/
    ├── __init__.py          # re-export: FileStore, load_file_policy, register
    ├── store.py             # ← file_store.py
    ├── policy.py            # ← file_policy.py
    └── routes.py            # ← file_routes.py
```

(이동 모듈의 공개 심볼 re-export 목록은 이동 직후 `grep`으로 확정.)

## 5. 마이그레이션 — 4 step, 각 독립 머지

### Step 0 — 브랜치 + 기준선 (코드 이동 0)

- 브랜치 `feat/subpkg-files-dashboard` 생성(큰 변경은 master 직접 금지).
- `.venv/Scripts/python.exe -m pytest tests/` 그린 확인.
- **`uv`를 PATH에 두고 `.venv/Scripts/python.exe -m pytest tests/test_packaging.py` 통과
  확인** — 이 테스트가 실제 휠을 빌드해 `dashboard_static` 에셋 포함을 검사하는,
  package-data 회귀의 **유일한 안전망**이다. uv가 없으면 skip되어 그냥 통과해버리므로
  PATH 보장 필수.

### Step 1 — `files/` (독립 머지, 가장 안전)

- `src/agent_agora/files/` + `__init__.py` 생성.
- `git mv`: `file_store.py→files/store.py`, `file_policy.py→files/policy.py`,
  `file_routes.py→files/routes.py`.
- 이동 3모듈 내부의 `from agent_agora.errors`/`agent_agora.persistence`는 평면 유지라 **무수정**.
- `files/__init__.py`에 공개 심볼 re-export.
- `__main__.py`의 파일공유 함수스코프 import 3줄 갱신.
- **테스트 import 일괄 갱신(명시 경로)**: `tests/test_file_store.py`·`test_file_policy.py`·
  `test_file_routes.py`·`test_file_sharing.py`, 그리고 **`tests/test_admin_routes.py`**
  (이 파일이 `from agent_agora.file_policy import ...` — admin 테스트라 놓치기 쉬움).
- `files/`엔 데이터파일 없음 → package-data 무변경.
- `pytest` 그린 후 머지.

### Step 2 — `dashboard/` (독립 머지, 데이터파일 동반) ★ 가장 위험한 단계

- `src/agent_agora/dashboard/` + `__init__.py` 생성.
- `git mv`: `dashboard_routes.py→routes.py`, `dashboard_events.py→events.py`,
  `dashboard_auth.py→auth.py`, `dashboard_health.py→health.py`.
- **CRITICAL — 데이터 동반 이동**: `dashboard.html`·`dashboard_static/`을 `dashboard/`
  안으로 함께 `git mv`. `routes.py`가 `Path(__file__).with_name('dashboard.html')`
  (`:25`)·`dashboard_static`(`:166`)으로 로드하므로 `__file__`이 따라 움직여 **코드 무수정**
  — 단 파일이 같이 가야 한다.
- `dashboard/__init__.py`에 `register`/`EventBroker`/`HealthCollector`/
  `DashboardAuthMiddleware`/`parse_tokens` re-export.
- `__main__.py`의 dashboard import 4줄 갱신.
- **테스트 import 일괄 갱신**: `tests/test_dashboard_routes.py`·`test_dashboard_events.py`·
  `test_dashboard_auth.py`·`test_dashboard_health.py`·`test_dashboard_dispatch.py`.
- **경로문자열 갱신(import 아님 — grep으로 안 잡힘)**:
  - `tests/test_dashboard_static.py:8` `STATIC_DIR = .../'agent_agora'/'dashboard_static'`
    → `.../'agent_agora'/'dashboard'/'dashboard_static'`.
  - `tests/test_packaging.py:42-47` required 리스트의 `agent_agora/dashboard_static/...`
    5줄 → `agent_agora/dashboard/dashboard_static/...`.
- **pyproject package-data 재경로** (§6).
- 검증: `pytest tests/` + (uv PATH) `test_packaging.py` 휠 빌드 통과 — package-data
  누락을 잡는 유일 수단. 머지.

### Step 3 — 마무리 (독립 머지)

- `CLAUDE.md` "구조" 섹션의 모듈 경로 서술을 `dashboard/`·`files/` 반영해 갱신.
- `docs/backlog.md`에 보류 항목 기록: (1) HTTP 라우트 계열(`admin`/`channel`/`auto_register`)은
  `comm_matrix`/`dispatcher` 의존 때문에 routes 서브패키지화 보류, (2) `bot`/`channel_adapter`는
  진입점·이득 문제로 보류, (3) ※가장 급한 건 패키지가 아니라 `dispatcher.py` 1084줄
  god-module 분해 — 별도 plan.
- `conftest.py`는 `bot_registry`+`comm_matrix`만 import(둘 다 평면 유지) → 변경 불필요.
- 전체 `pytest` 최종 확인.

## 6. pyproject / 외부 참조 변경

- **`[project.scripts]` 무변경** — `agent-agora='agent_agora.__main__:main'`,
  `agora-channel='agent_agora.channel_adapter:cli'` 둘 다 이동 대상 아님(console-script 안전).
- **`[tool.setuptools.package-data]` 재경로 (Step 2):**
  ```toml
  # 현재
  agent_agora = ["default_schemas.jsonl", "*.html", "dashboard_static/**/*"]
  # 변경
  agent_agora = ["default_schemas.jsonl"]                          # schemas는 평면 유지
  "agent_agora.dashboard" = ["*.html", "dashboard_static/**/*"]    # 신규 서브패키지 글롭
  ```
  글롭은 패키지 디렉터리 상대라, `dashboard.html`·`dashboard_static/`이 `agent_agora/dashboard/`로
  이동하면 기존 `agent_agora` 글롭이 더 이상 매치하지 않는다.
- **`[tool.setuptools.packages.find] where=["src"]` 무변경** — 중첩 패키지 자동 discover
  (각 서브디렉터리에 `__init__.py` 필수).
- `plugin/*.mcp.json` 무관(커맨드명만 참조, 모듈경로 결합 없음).

## 7. 위험과 완화

| 위험 | 심각도 | 완화 |
|------|--------|------|
| **package-data 글롭 재경로 누락** | 높음 | `dashboard.html`/`dashboard_static` 이동 후 `"agent_agora.dashboard"` 글롭 누락 시 **소스트리 pytest는 그린이지만 배포 휠에서만 에셋 누락(404)**. "pytest가 정답"인데 pytest가 구조적으로 못 잡는 유일 케이스. → `test_packaging.py`를 **uv PATH에서 반드시** 실행(휠 빌드 검사) |
| **경로문자열 테스트 누락** | 중 | `test_dashboard_static.py:8`·`test_packaging.py:42-47` 하드코딩 경로는 `grep "from agent_agora"`에 안 걸림. Step 2 체크리스트에 명시(누락 시 CI 즉시 빨강) |
| **lazy-import 절단선 오염** | (범위 밖 경고) | 라우팅 코어를 평면에 남기는 것이 이 권고의 안전 근거. 향후 "정리" 명목으로 `dispatcher`/`sweeper`/`conversation_store`/`dispatch_persistence`를 서브패키지로 가르거나 lazy를 module-top으로 올리면 cross-package 순환 폭발 — backlog 경고 |
| 테스트 import 갱신 불가피 | 낮음 | 이동 7모듈 import하는 ~11~12개 테스트파일. 고팬인 모듈(dispatcher/registry/persistence)은 무이동이라 heavy 테스트 무영향 |
| `__init__` re-export 부분초기화 | 낮음 | 이동 모듈은 서로 import 안 함(leaf) → import-time 부작용 여지 없음(검증 완료) |

## 8. 테스트 / 검증

- 순수 파일 이동 + import 갱신 — 기존 66개 테스트가 안전망(동작 무변경).
- 각 step 후 `.venv/Scripts/python.exe -m pytest tests/` 그린 유지, 단계별 명시 경로 커밋.
- **Step 2 필수 추가 검증**: uv PATH 보장 후 `test_packaging.py`(휠 빌드)로 `dashboard_static`
  에셋 포함 확인 — 이게 통과해야 배포본 회귀 없음.

## 9. 후속 (범위 밖)

- god-module 분해(`dispatcher-fanout-decompose-skeleton`, `dispatcher-routing-stdout-to-logging`)가
  탐색성·복잡도의 더 급한 절반. 패키지 재구성보다 우선순위 높음.
- HTTP 라우트 통합·`bot`/`channel_adapter` 이동은 ROI 재평가 후(현재 보류).
