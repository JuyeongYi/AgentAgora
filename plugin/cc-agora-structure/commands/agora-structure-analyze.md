---
description: 타깃 레포의 구조를 분석해 워커별 파티션 매니페스트를 작성한다.
---

# /agora-structure-analyze

타깃 레포의 폴더 구조를 code-review-graph로 분석해 워커별 파티션을 산출하고, 구조 매니페스트(`structure-manifest.json`)를 작성한다. 운영자가 검토·편집한 뒤 `/agora-structure-spawn`으로 진행한다.

## 인자

`$ARGUMENTS`에서 다음을 파싱한다(없으면 기본값):

- `--repo <path>` — 타깃 레포 경로 (기본: 슬래시 커맨드 호출 시점의 CWD).
- `--target-size <N>` — 파티션 목표 가중치 (기본: 80).
- `--out <path>` — 매니페스트 출력 경로 (기본: `<repo>/.agora-structure/manifest.json`).

## 절차

다음 단계를 **순서대로** 수행하라. 각 단계는 결과를 다음 단계의 입력으로 쓴다.

### 1. 그래프 준비

`mcp__code-review-graph__list_graph_stats_tool`을 `repo_root=<repo>`로 호출해 그래프 상태를 확인하라. `total_nodes == 0`이거나 `last_updated`가 없으면 빌드한다:

`mcp__code-review-graph__build_or_update_graph_tool`을 `repo_root=<repo>`, `full_rebuild=true`, `postprocess="minimal"`로 호출.

### 2. 파일 노드 수집

타깃 레포의 파일 목록을 Bash 도구로 열거한다(그래프에는 enumeration API가 없음):

```bash
git -C <repo> ls-files
```

각 결과(이미 `<repo>` 기준 상대경로·forward-slash)를 보관한다. 그래프가 파싱한 언어 외의 파일(`list_graph_stats_tool`의 `languages`에 없는 확장자)은 가중치 0·엣지 0으로 처리한다.

### 3. 파일별 가중치 계산

각 파일에 대해 `mcp__code-review-graph__query_graph_tool`을 `pattern="file_summary"`, `target=<상대경로>`로 호출. 반환 `results`에서 `kind != "File"`인 노드 개수를 그 파일의 가중치로 한다. 그래프가 그 파일을 모르면(빈 results) 가중치는 0.

대규모 레포에서는 호출 수가 파일 수만큼 늘어난다. 100개마다 진행 상황을 한 줄로 보고하라(`stderr` 또는 출력 메시지).

### 4. 엣지 수집

각 파일에 대해 `query_graph` `pattern`을 `imports_of`·`importers_of`로 호출해 import 엣지를 모은다.

**Class 노드는 별도 검색으로 수집한다** — `mcp__code-review-graph__semantic_search_nodes_tool`을 `kind="Class"`, `limit=10000`로 호출. 각 Class 노드의 `qualified_name`을 `target`으로 `query_graph pattern="inheritors_of"`를 호출해 상속 엣지를 모은다.

각 엣지는 `(source_file, target_file, kind)`로 기록. `kind`는 `imports` 또는 `inherits`.

### 5. 폴더 트리 구성

파일 경로의 디렉터리 부분을 키로 폴더 트리를 만든다. 각 노드 형식:

```json
{
  "name": "<basename>",
  "path": "<rel path from repo root>",
  "files": [{"path": "<rel>", "weight": <int>}],
  "subfolders": [...recursive...]
}
```

루트는 `path == ""`.

> **`<plugin-root>` 해석:** 이 슬래시 커맨드가 속한 플러그인의 루트 디렉터리 — `<repo>/plugin/cc-agora-structure/`(마켓플레이스 등록 경로 기준). 아래 명령들은 Bash 도구로 절대경로로 실행한다.

### 6. 분할기 호출

플러그인의 `partition.py`를 호출한다:

```
echo '{"tree": <트리>, "target_size": <T>}' | python <plugin-root>/scripts/partition.py
```

여기서 `<plugin-root>`은 `plugin/cc-agora-structure/` (현재 플러그인의 루트). 표준출력으로 받은 JSON에서 `partitions`와 `warnings`를 사용한다.

### 7. 결합도 오버레이

수집한 엣지를 파티션 단위로 집계한다 — 각 엣지의 `source_file`·`target_file`이 속한 파티션을 찾아 `(from_partition, to_partition, kind)`로 카운트.

각 파티션의 `coupling` 필드에 다음 형식으로 저장:

```json
{"to": "<other-partition-id>", "edges": <count>, "kinds": {"imports": K, "inherits": M}}
```

**`inherits` 엣지가 파티션을 가로지르면** 매니페스트의 `warnings`에 다음을 추가:

```
inherits edge crosses partition boundary: <from-id> -> <to-id>
```

### 8. 매니페스트 작성

`<out>` 경로(필요하면 부모 디렉터리 생성)에 다음 형식의 JSON을 쓴다:

```json
{
  "version": 1,
  "repo": "<repo absolute path, forward-slash>",
  "target_size": <T>,
  "generated": "<ISO-8601 UTC, e.g. 2026-05-20T12:34:56Z>",
  "partitions": [
    {
      "id": "<slug from partition root>",
      "root": "<rel folder path>",
      "weight": <int>,
      "files": ["<rel file path>", ...],
      "suggested_role": "implementer",
      "coupling": [...]
    }
  ],
  "warnings": [...]
}
```

`suggested_role`은 모든 파티션에 대해 `"implementer"`로 둔다(운영자가 검토 시 변경).

### 9. 운영자 보고

매니페스트 경로와 한 줄 요약(`N partitions, M warnings`)을 출력하라. 운영자에게 다음을 안내:

> 매니페스트가 작성되었습니다. 검토·편집 후 `/agora-structure-spawn --manifest <path>`로 진행하십시오. `warnings` 항목은 특히 주의해 확인하십시오 — `inherits edge crosses partition boundary` 경고는 그 파티션을 합쳐야 할 수 있다는 신호입니다.
