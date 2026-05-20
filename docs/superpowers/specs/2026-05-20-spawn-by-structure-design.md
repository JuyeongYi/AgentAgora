# spawnByStructure — 구조 분석 기반 워커 분할·다중 스폰 (설계)

- 작성일: 2026-05-20
- 상태: 설계 작성 → 유저 검토 대기
- 관련: 신규 플러그인 `plugin/cc-agora-structure/`, code-review-graph MCP 의존, `plugin/.claude-plugin/marketplace.json` 갱신

## 1. 배경 / 문제

운영자가 큰 코드베이스를 다중 에이전트로 분담시키려 할 때 워커당 구현 범위를 어떻게 한정할지가 명확하지 않다. 무작정 N개의 워커를 띄우면 모두 같은 파일을 만지거나 의도치 않은 경계를 넘는다. 워커당 범위를 **소스코드 구조(포함관계·상속관계)** 에 따라 정해주는 운영자 도구가 필요하다.

추가 제약: Claude Code 워커는 특정 CWD에서 동작하므로 **폴더 구조가 분할의 최우선 기준**이 된다. 그래프 엣지(import·상속·호출)는 폴더 절단선이 깨끗한지 검증하는 오버레이로 쓴다.

## 2. 목표 / 비목표

**목표** — 운영자가 단일 진입점으로 (1) 타깃 레포의 구조를 분석해 폴더 트리 + code-review-graph 엣지 오버레이로 워커별 파티션을 산출하고, (2) 운영자가 검토·편집한 구조 매니페스트로 파티션마다 워커를 다중 스폰하며, (3) 각 워커가 자기 파티션에만 한정해 작업하도록 강제하는 운영자 도구를 **별도 플러그인**으로 제공한다.

**비목표** — 분석 알고리즘의 자동 튜닝(목표 크기 자동 산출). 비-git 레포 지원(분석은 가능하나 스폰은 git 필수). worktree 외 격리(VM·컨테이너). 워커 간 동적 재분할. 분할 결과 시각화(매니페스트 JSON으로 검토).

## 3. 플러그인 구조 & 의존성 선언

신규 마켓플레이스 플러그인 `cc-agora-structure` — `plugin/.claude-plugin/marketplace.json`의 17번째 항목.

```
plugin/cc-agora-structure/
  .claude-plugin/plugin.json         # name, version, dependencies: ["cc-agora"]
  .mcp.json                          # code-review-graph MCP 서버 선언 (의존성 명시)
  README.md                          # 한국어; code-review-graph CLI(pip) 설치 요구사항
  commands/
    agora-structure-analyze.md       # 슬래시 — Claude에게 그래프 쿼리 → 매니페스트 작성 지시
    agora-structure-spawn.md         # 슬래시 — structure_spawn.py 호출
  scripts/
    partition.py                     # 순수 Python 목표크기 트리워크 분할기 (그래프 의존 0)
    structure_spawn.py               # 워커별 스테이징 디렉터리 생성 + 다중 기동
  templates/
    structure-manifest.json.example  # 매니페스트 샘플
    worker-claude.md.template        # scoped CLAUDE.md
    worker-mcp.json.template         # agentagora + code-review-graph
    worker-settings.local.json.template
```

**의존성 선언 방식:**

- `plugin.json`의 `dependencies` 배열은 같은 마켓플레이스의 형제 플러그인 이름만 가리키므로 code-review-graph(단독 MCP 서버 + CLI)는 못 넣는다. `cc-agora-structure`는 `dependencies: ["cc-agora"]` — 워커가 사용하는 통신 코어.
- 플러그인이 **`.mcp.json`을 번들**해 `code-review-graph` MCP 서버(`code-review-graph serve`)를 선언 — 플러그인 설치 시 도구가 자동 등록된다. **이것이 기계가 읽는 명시적 의존성 선언.**
- README가 `code-review-graph` CLI/Python 패키지의 pip 설치를 요구사항으로 명시(MCP 서버 기동 커맨드 `code-review-graph serve`가 PATH에 있어야 함).
- code-review-graph 의존부는 **`analyze` 슬래시 커맨드 안에만** 존재한다(MCP 도구 호출 지시문). `spawn` 단계는 순수 Python — 그래프 무관.
- AgentAgora 마켓플레이스 플러그인 중 `.mcp.json`을 번들하는 첫 사례.

## 4. Stage 1 — `analyze`

**왜 에이전트 주도인가** — `code-review-graph` CLI는 `build/update/status/detect-changes/wiki/serve` 등만 제공하고 그래프 쿼리 서브커맨드(`query_graph`·`file_summary`·`list_communities`)가 없다. 그래프 쿼리는 MCP 도구 전용이다. 분석은 운영자의 Claude 인스턴스가 슬래시 커맨드 지시문에 따라 MCP를 호출하는 방식으로 수행한다(`partition.py` 헬퍼와 결합).

**`analyze` 슬래시가 지시하는 흐름:**

1. **그래프 준비** — `mcp__code-review-graph__list_graph_stats_tool`로 타깃 레포의 그래프 상태 확인. 없거나 stale이면 `mcp__code-review-graph__build_or_update_graph_tool` 호출.
2. **노드·엣지 수집** — `query_graph file_summary`·`semantic_search_nodes_tool`·`query_graph imports_of/inheritors_of`로 (a) 파일별 노드 수, (b) 파일 간 import·inherits·calls 엣지를 수집.
3. **폴더 트리 + 가중치 dump** — 파일 경로를 폴더 트리로 묶고 각 폴더의 가중치 = 직속 파일 노드수 합. 결과를 JSON으로 `partition.py`에 전달.
4. **`partition.py` 호출** — 입력: `{"tree": {...folder weights...}, "target_size": T}`. 출력: 파티션 목록. 순수 함수, 그래프 의존 0.
5. **엣지 오버레이로 결합도 분석** — 파티션 쌍별 크로스 엣지 카운트. **상속 엣지가 파티션을 가로지르면 강한 경고**(상속 계층 분리는 위험), 다대다 import·call이 밀집하면 약한 경고.
6. **매니페스트 작성** — 기본 경로 `<repo>/.agora-structure/manifest.json` (또는 `--out`)에 저장. 운영자에게 검토 요청.

**`partition.py` 알고리즘 (목표 크기 자동 절단):**

- 폴더 트리를 top-down 순회.
- 폴더 F에서: 가중치(F) ≤ T → F를 한 파티션으로 확정.
- 가중치(F) > T → 하위 폴더 각각을 재귀 호출. F의 직속 파일(잔여) 가중치가 ≤ T면 잔여를 한 파티션으로(또는 **가장 작은 형제 파티션과 병합** — 형제 가중치 + 잔여 ≤ T 조건 하에). 잔여 > T 이면서 하위 폴더가 없으면 **과대 리프** → 단일 파티션으로 emit + 경고(`leaf folder, cannot split further`).
- 결과: 파티션 목록. 워커 수는 결과로 산출.

**입력 인자:**

- `--repo <path>` (기본: CWD)
- `--target-size <N>` (기본: 80 노드)
- `--out <path>` (기본: `<repo>/.agora-structure/manifest.json`)

## 5. 구조 매니페스트 스키마

```json
{
  "version": 1,
  "repo": "C:/Users/jylee/source/AgentAgora",
  "target_size": 80,
  "generated": "2026-05-20T12:34:56Z",
  "partitions": [
    {
      "id": "src-agent-agora",
      "root": "src/agent_agora",
      "weight": 412,
      "files": ["src/agent_agora/server.py", "src/agent_agora/dispatcher.py", "..."],
      "suggested_role": "implementer",
      "coupling": [
        {"to": "tests", "edges": 30, "kinds": {"calls": 28, "inherits": 2}}
      ]
    }
  ],
  "warnings": [
    "partition 'src-agent-agora' weight 412 > target 80 — leaf folder, cannot split further",
    "inherits edge crosses partition boundary: tests -> src-agent-agora"
  ]
}
```

`id`는 `root`에서 도출되는 슬러그(`/` → `-`, non-ASCII 문자 → 제거 또는 hex escape, ASCII 강제 — `X-Agora-Description` 헤더에 들어가므로). 운영자는 이 JSON을 수정해 파티션을 병합·삭제·재명명하거나 `suggested_role`을 바꾸고 spawn으로 진행한다.

## 6. Stage 2 — `spawn`

`structure_spawn.py`는 **git plumbing을 직접 수행하지 않는다.** 파티션마다 워커별 **설정 전용 스테이징 디렉터리**만 만들고 워커를 기동한다. 실제 worktree·sparse-checkout 생성은 워커가 첫 구현 task를 받았을 때 자기 스킬로 수행한다.

**입력 인자:**

- `--manifest <path>` (필수)
- `--out <staging-base>` (기본: `<repo>/.agora-structure/workers/`)
- `--worktree-base <path>` (기본: `<repo>/../<repo이름>.structure-worktrees/`) — 워커가 task 시 만들 worktree의 **사전 결정 위치**(permission 화이트리스트가 알아야 하므로 spawn 시점에 확정)
- `--launch off|manual|auto` (기본 `manual`) — `spawn_team.py`와 동일
- `--server-url`, `--instance-id-prefix` — `spawn.py`와 동일

**파티션마다 (`<staging-base>/<partition-id>/` 안):**

- **`CLAUDE.md`** — `worker-claude.md.template` 렌더. 포함:
  - 파티션 배정 블록: `id`·`root`(절대경로 forward-slash)·파일 목록·suggested_role.
  - 범위 규칙: "네 범위는 `<root>`. 범위 밖 편집 금지."
  - worktree 절차: "구현 task를 받으면 superpowers `using-git-worktrees` 스킬로 `<worktree-base>/<partition-id>`에 worktree를 만들고, 그 안에서 `git sparse-checkout init --cone` + `git sparse-checkout set <partition.root>` 실행 후 거기서 작업. 후속 task는 같은 worktree에서 새 브랜치로 진행."
  - 크로스파티션 규칙: "다른 파티션 코드는 디스크에 없다. 시그니처·구조는 code-review-graph MCP(`query_graph`·`semantic_search_nodes`)로 조회. 다른 파티션 파일의 *수정*이 필요하면 agora로 그 파티션 담당 워커에 task 디스패치."
- **`.claude/settings.local.json`** — Edit·Write·NotebookEdit 권한 화이트리스트:
  - 허용: `<staging-base>/<partition-id>/**`, `<worktree-base>/<partition-id>/**` (두 경로 모두 절대경로 glob).
  - 그 외 deny.
- **`.mcp.json`** — `worker-mcp.json.template` 렌더. 서버 2개:
  - `agentagora` (HTTP) — 헤더: `X-Agora-Cwd`=스테이징 디렉터리(워커 세션 CWD), `X-Agora-Role`=manifest의 suggested_role, `X-Agora-Description`=`"Partition <id> at <root>"` (ASCII 강제, 위반 시 spawn이 거부).
  - `code-review-graph` (stdio) — `command: "code-review-graph"`, `args: ["serve"]`.
- **`run.bat`** — `cd <staging-base>/<partition-id>` 후 `claude --model <m> --effort <e> --dangerously-skip-permissions` 기동(`suggested_role`별 모델/effort 매핑은 `spawn.py`와 동일 규약).

**기동:**

- `--launch off` — 스테이징만 생성.
- `--launch manual` (기본) — 스테이징 + 출력에 기동 커맨드 인쇄.
- `--launch auto` — `wt.exe` 탭으로 자동 기동(`run-agora.ps1` 패턴).

**워커 런타임 흐름:**

1. 스테이징 디렉터리에서 기동 → scoped CLAUDE.md 읽음 → `auto_register` 미들웨어가 `X-Agora-Cwd`=스테이징 경로로 등록 → idle.
2. agora `invoke`로 구현 task 수신.
3. CLAUDE.md 지침대로 `using-git-worktrees` 스킬 적용 → `git worktree add <worktree-base>/<partition-id>` (타깃 레포 HEAD 기준, 새 브랜치) → `git sparse-checkout init --cone` + `git sparse-checkout set <partition.root>` → 콘 모드라 파티션 폴더 전체 + 루트 직속 파일(레포 CLAUDE.md·pyproject.toml 등)만 디스크에 머티리얼라이즈.
4. 워커는 Bash `cd`로 worktree로 들어가 작업. Edit·Write·NotebookEdit은 permission 화이트리스트로 worktree 내부로 제한됨.
5. 후속 task는 같은 worktree 재사용(브랜치 분기는 워커의 워크플로 스킬 책임).

## 7. 범위 강제 (4계층)

| 계층 | 기제 | 종류 | 활성 시점 |
|---|---|---|---|
| 1. sparse-checkout | 워커가 task 첫 수신 시 콘 모드로 파티션 폴더만 머티리얼라이즈 — 그 외 파일이 worktree 디스크에 *없음* | 물리 | 첫 task 이후 |
| 2. CWD | 세션 CWD = 스테이징 디렉터리. 작업은 Bash `cd`로 worktree로 — 워크플로/스킬 규약 의존 | 운영 규약 | 항상 |
| 3. scoped CLAUDE.md | 파티션 + worktree 절차 + 크로스파티션 규칙. 워커가 매 turn 참조 | 지시 | 항상 |
| 4. settings.local.json permission | Edit·Write·NotebookEdit 허용 = 스테이징 + 예약 worktree만. 외부 경로 차단 | 권한 | 항상 (Claude Code 권한 시스템) |

계층 1은 첫 task 전엔 비활성이고, 활성 후에도 "범위 밖 신규 파일 *생성*" 시도는 못 막는다 — 계층 4가 보완. 계층 1·4가 강제, 2·3이 지시. 둘이 묶여야 안전.

## 8. 크로스파티션

- **읽기** — code-review-graph MCP. 그래프는 레포 전체를 보유하므로 워커가 sparse-checkout으로 디스크에 없는 다른 파티션의 시그니처·호출관계·상속을 조회한다. code-review-graph 의존이 분석뿐 아니라 **런타임 크로스파티션 채널**로도 정당화된다.
- **쓰기** (경계 넘는 변경) — agora로 해당 파티션 담당 워커에 task 디스패치. broker의 본래 용도.

## 9. 파일 영향

| 파일 | 변경 |
|---|---|
| `plugin/.claude-plugin/marketplace.json` | `cc-agora-structure` 항목 추가 |
| `plugin/cc-agora-structure/.claude-plugin/plugin.json` | 신규 — `dependencies: ["cc-agora"]` |
| `plugin/cc-agora-structure/.mcp.json` | 신규 — `code-review-graph` MCP 서버 선언 |
| `plugin/cc-agora-structure/README.md` | 신규 — 한국어, CLI 설치 요구·사용법 |
| `plugin/cc-agora-structure/commands/agora-structure-analyze.md` | 신규 슬래시 — 분석 지시문 |
| `plugin/cc-agora-structure/commands/agora-structure-spawn.md` | 신규 슬래시 — `structure_spawn.py` 호출 |
| `plugin/cc-agora-structure/scripts/partition.py` | 신규 — 트리워크 분할 |
| `plugin/cc-agora-structure/scripts/structure_spawn.py` | 신규 — 스테이징 + 기동 |
| `plugin/cc-agora-structure/templates/structure-manifest.json.example` | 신규 |
| `plugin/cc-agora-structure/templates/worker-claude.md.template` | 신규 |
| `plugin/cc-agora-structure/templates/worker-mcp.json.template` | 신규 |
| `plugin/cc-agora-structure/templates/worker-settings.local.json.template` | 신규 |
| `tests/test_structure_partition.py` | 신규 — `partition.py` 단위 테스트 |
| `tests/test_structure_spawn.py` | 신규 — 스테이징 렌더링·매니페스트 검증 |

## 10. 에러 / 엣지케이스

- **타깃 레포가 git 아님** — `analyze`는 폴더 트리만으로 동작 가능(엣지 데이터는 그래프 의존). `spawn`은 워커가 worktree를 만들 수 없으므로 사전 검증에서 거부.
- **그래프 미빌드/stale** — `analyze`가 `build_or_update_graph` 선행.
- **과대 리프 폴더** (가중치 > T, 하위 없음) — 단일 파티션 + warning. 운영자가 매니페스트에서 파일 단위로 직접 분할하거나 수용.
- **운영자 편집 후 빈 파티션** (파일 0) — `spawn`이 스킵 + warning.
- **매니페스트 스키마 위반** — `spawn` 시작 시 검증 후 거부(dataclass 파싱 또는 JSON Schema).
- **worktree 예약 경로 충돌** — `spawn` 사전 검증에서 비어있는지 확인. 비어있지 않으면 `--force` 없이 거부.
- **더티 워킹트리** — worktree가 HEAD 기준이라 미커밋 변경은 미반영. `spawn` 시 경고.
- **HTTP 헤더 non-ASCII** — `X-Agora-Description`은 ASCII 강제. 파티션 root에 non-ASCII가 있으면 슬러그화 시 제거되어 ASCII 보장.
- **워커가 worktree 생성 실패** — 워커가 agora로 운영자에 에러 보고 + 해당 task abort. `spawn` 스크립트 책임 밖.

## 11. 테스트

- **`test_structure_partition.py`** — `partition.py` 순수 함수:
  - 균형 트리에서 N개 파티션 산출 (각 ≤ T).
  - 과대 리프 폴더 → 단일 파티션 + warning.
  - 잔여 파일을 가장 작은 형제와 병합하는 케이스.
  - 단일 파일 레포 / 빈 트리 엣지 케이스.
- **`test_structure_spawn.py`** — `structure_spawn.py`:
  - 매니페스트 파싱·스키마 검증 (정상·위반 케이스).
  - 스테이징 렌더링: scoped CLAUDE.md에 root·파일 목록·worktree 절차·크로스파티션 규칙이 모두 포함.
  - settings.local.json permission 화이트리스트에 두 경로(스테이징·예약 worktree)가 절대경로 glob으로 들어가는지.
  - `.mcp.json`에 agentagora + code-review-graph 두 서버가 들어가고 `X-Agora-Cwd`가 스테이징 절대경로(forward-slash)인지, 헤더 ASCII 검증.
  - 빈 파티션 스킵 + warning 출력.
- **플러그인 메타** — `plugin.json`·`marketplace.json` JSON 유효성; `cc-agora-structure.dependencies == ["cc-agora"]` 검증; 플러그인 번들 `.mcp.json`에 code-review-graph 서버가 있는지.

## 12. 미해결

없음 — 범위·결정 모두 확정.
