# spawnByStructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 새 운영자 플러그인 `cc-agora-structure`를 추가해, 타깃 레포의 폴더 구조를 code-review-graph 엣지 오버레이로 검증하며 목표 크기 기반 자동 절단으로 파티션을 산출하고, 파티션마다 워커별 스테이징 디렉터리를 만들어 다중 스폰한다. 워커는 첫 구현 task 수신 시 worktree+sparse-checkout을 자기 스킬로 생성한다.

**Architecture:** 두 단계 파이프라인. (1) `analyze` 슬래시 — 운영자의 Claude 인스턴스가 code-review-graph MCP로 그래프를 쿼리, 폴더 트리+가중치를 순수 Python `partition.py`에 전달, 결과를 구조 매니페스트로 작성. (2) `spawn` 슬래시 — `structure_spawn.py`가 매니페스트를 읽어 파티션마다 스테이징 디렉터리(scoped CLAUDE.md·.mcp.json[3서버]·settings.local.json[권한 화이트리스트])를 만들고 채널 모드로 다중 기동. 워커가 실행 시점에 worktree+sparse-checkout을 자기 책임으로 생성.

**Tech Stack:** Python 3.13 (`dataclasses`, `argparse`, stdlib JSON), pytest, Claude Code 플러그인(plugin.json·.mcp.json·slash commands), code-review-graph MCP (분석 단계 한정), git worktree + sparse-checkout (cone mode, 워커 런타임).

---

## File Structure

신규 플러그인 (`plugin/cc-agora-structure/`):

| 파일 | 책임 |
|---|---|
| `.claude-plugin/plugin.json` | 플러그인 메타 (`dependencies: ["cc-agora"]`) |
| `.mcp.json` | 플러그인 번들 MCP — code-review-graph 의존 선언 |
| `README.md` | 한국어 사용법·CLI 설치 요구사항 |
| `commands/agora-structure-analyze.md` | 슬래시 — 분석 지시문(MCP 호출+partition.py) |
| `commands/agora-structure-spawn.md` | 슬래시 — `structure_spawn.py` 호출 |
| `scripts/partition.py` | 순수 Python 트리워크 분할 (그래프 의존 0) |
| `scripts/structure_spawn.py` | 매니페스트 → 스테이징 디렉터리 + 다중 기동 |
| `templates/structure-manifest.json.example` | 매니페스트 샘플 |
| `templates/worker-claude.md.template` | scoped CLAUDE.md |
| `templates/worker-mcp.json.template` | 3서버 .mcp.json (agentagora+agora-channel+code-review-graph) |
| `templates/worker-settings.local.json.template` | 권한 화이트리스트 |

수정:

| 파일 | 변경 |
|---|---|
| `plugin/.claude-plugin/marketplace.json` | `cc-agora-structure` 항목 추가 (17번째) |

테스트:

| 파일 | 책임 |
|---|---|
| `tests/test_structure_partition.py` | `partition.py` 순수 함수 단위 |
| `tests/test_structure_spawn.py` | `structure_spawn.py` 매니페스트 파싱·렌더링·CLI |
| `tests/test_structure_plugin.py` | 플러그인 메타·마켓플레이스 항목·번들 .mcp.json |

---

## Task 1: Plugin Skeleton & Marketplace Entry

**Files:**
- Create: `plugin/cc-agora-structure/.claude-plugin/plugin.json`
- Create: `plugin/cc-agora-structure/.mcp.json`
- Create: `plugin/cc-agora-structure/README.md`
- Modify: `plugin/.claude-plugin/marketplace.json` (add 17th entry)
- Create: `tests/test_structure_plugin.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_structure_plugin.py`:

```python
"""Plugin metadata + marketplace + bundled .mcp.json validation for cc-agora-structure."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugin" / "cc-agora-structure"


def test_plugin_json_valid():
    data = json.loads((PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert data["name"] == "cc-agora-structure"
    assert isinstance(data["version"], str)
    assert data["dependencies"] == ["cc-agora"]


def test_bundled_mcp_declares_code_review_graph():
    data = json.loads((PLUGIN_DIR / ".mcp.json").read_text(encoding="utf-8"))
    servers = data["mcpServers"]
    assert "code-review-graph" in servers
    crg = servers["code-review-graph"]
    assert crg["command"] == "code-review-graph"
    assert crg["args"] == ["serve"]


def test_marketplace_contains_structure_plugin():
    marketplace = json.loads(
        (REPO_ROOT / "plugin" / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    names = [p["name"] for p in marketplace["plugins"]]
    assert "cc-agora-structure" in names
    entry = next(p for p in marketplace["plugins"] if p["name"] == "cc-agora-structure")
    assert entry["source"] == "./cc-agora-structure"


def test_readme_exists():
    assert (PLUGIN_DIR / "README.md").is_file()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_structure_plugin.py -v`
Expected: 4 FAIL (files don't exist yet).

- [ ] **Step 3: Create plugin.json**

Create `plugin/cc-agora-structure/.claude-plugin/plugin.json`:

```json
{
  "name": "cc-agora-structure",
  "description": "AgentAgora structure-based spawn — partition the codebase by folder structure with code-review-graph edge overlay, spawn scoped workers per partition.",
  "version": "0.1.0",
  "dependencies": ["cc-agora"]
}
```

- [ ] **Step 4: Create bundled .mcp.json**

Create `plugin/cc-agora-structure/.mcp.json`:

```json
{
  "mcpServers": {
    "code-review-graph": {
      "command": "code-review-graph",
      "args": ["serve"]
    }
  }
}
```

- [ ] **Step 5: Create README.md**

Create `plugin/cc-agora-structure/README.md`:

```markdown
# cc-agora-structure

AgentAgora 운영자 플러그인 — 타깃 레포의 폴더 구조를 분석해 워커별 파티션을 산출하고, 파티션마다 범위 한정 워커를 다중 스폰한다.

## 요구사항

이 플러그인은 [code-review-graph](https://pypi.org/project/code-review-graph/)를 의존한다. `.mcp.json`에 MCP 서버를 선언하지만, **CLI 패키지는 별도 설치해야 한다**:

```bash
pip install code-review-graph
```

설치 후 `code-review-graph serve`가 PATH에서 실행 가능해야 한다.

## 사용

1. `/agora-structure-analyze` — 현재 레포를 분석해 구조 매니페스트를 `<repo>/.agora-structure/manifest.json`에 작성한다. 운영자가 검토·편집.
2. `/agora-structure-spawn --manifest <path>` — 매니페스트로 파티션마다 워커별 스테이징 디렉터리 생성 + 채널 모드 다중 기동.

워커는 첫 구현 task 수신 시 superpowers `using-git-worktrees` 스킬로 자기 파티션의 worktree+sparse-checkout(콘 모드)을 생성해 작업한다. 자세한 설계는 `docs/superpowers/specs/2026-05-20-spawn-by-structure-design.md` 참조.

## 범위 강제 4계층

1. **sparse-checkout** — 워커가 첫 task에 콘 모드로 파티션 폴더만 머티리얼라이즈, 그 외 파일이 worktree 디스크에 없음.
2. **CWD** — 세션 CWD = 스테이징 디렉터리, 작업은 Bash `cd`로 worktree.
3. **scoped CLAUDE.md** — 파티션 + worktree 절차 + 크로스파티션 규칙.
4. **settings.local.json permission** — Edit/Write 허용 = 스테이징 + 예약 worktree만.

크로스파티션 읽기는 code-review-graph MCP, 쓰기는 agora 디스패치.
```

- [ ] **Step 6: Add marketplace entry**

Modify `plugin/.claude-plugin/marketplace.json` — append to `plugins` array (after `superpowers-tester`):

```json
    {
      "name": "cc-agora-structure",
      "source": "./cc-agora-structure",
      "description": "AgentAgora structure-based spawn — partition codebase by folder structure with code-review-graph overlay, spawn scoped workers per partition."
    }
```

- [ ] **Step 7: Run tests to verify pass**

Run: `python -m pytest tests/test_structure_plugin.py -v`
Expected: 4 PASS.

- [ ] **Step 8: Commit**

```bash
git add plugin/cc-agora-structure plugin/.claude-plugin/marketplace.json tests/test_structure_plugin.py
git commit -m "feat: cc-agora-structure 플러그인 스켈레톤 + 마켓플레이스 항목"
```

---

## Task 2: partition.py — Core Algorithm

**Files:**
- Create: `plugin/cc-agora-structure/scripts/partition.py`
- Create: `tests/test_structure_partition.py`

- [ ] **Step 1: Write the failing tests (balanced + oversize leaf)**

Create `tests/test_structure_partition.py`:

```python
"""Pure-function unit tests for cc-agora-structure partition.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "plugin" / "cc-agora-structure" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from partition import Partition, partition_tree, slug  # noqa: E402


def _leaf(name: str, weight: int) -> dict:
    return {"name": name, "path": name, "files": [{"path": name, "weight": weight}], "subfolders": []}


def test_balanced_split_each_subfolder_under_target():
    tree = {
        "name": "root", "path": "", "files": [],
        "subfolders": [
            {"name": "a", "path": "a", "files": [
                {"path": "a/x.py", "weight": 3},
                {"path": "a/y.py", "weight": 4},
            ], "subfolders": []},
            {"name": "b", "path": "b", "files": [
                {"path": "b/z.py", "weight": 5},
            ], "subfolders": []},
        ],
    }
    parts, warnings = partition_tree(tree, target_size=10)
    assert len(parts) == 2
    assert warnings == []
    roots = sorted(p.root for p in parts)
    assert roots == ["a", "b"]
    assert all(p.weight <= 10 for p in parts)


def test_oversize_leaf_emits_with_warning():
    tree = {
        "name": "huge", "path": "huge",
        "files": [{"path": f"huge/f{i}.py", "weight": 50} for i in range(5)],
        "subfolders": [],
    }
    parts, warnings = partition_tree(tree, target_size=80)
    assert len(parts) == 1
    p = parts[0]
    assert p.root == "huge"
    assert p.weight == 250
    assert len(warnings) == 1
    assert "leaf folder, cannot split further" in warnings[0]
    assert "huge" in warnings[0]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_structure_partition.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partition'`.

- [ ] **Step 3: Create partition.py with core algorithm**

Create `plugin/cc-agora-structure/scripts/partition.py`:

```python
"""Pure-Python target-size folder tree partitioner.

Input: a folder tree with per-file weights. Output: a flat list of
partitions, each = one folder subtree (or a folder's loose-file remainder
or an oversize leaf), with weight ≤ target_size where possible.

No code-review-graph or filesystem dependency — operates purely on the
tree JSON passed by the analyze slash command.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Partition:
    id: str
    root: str
    weight: int
    files: tuple[str, ...]


def slug(path: str) -> str:
    """Convert a forward-slash path to an ASCII id slug.

    "src/agent_agora" -> "src-agent-agora"
    "" -> "root"
    "a/한글/b" -> "a-b"  (non-ASCII dropped, consecutive dashes collapsed)
    Underscores and slashes both normalize to dashes; non-ASCII characters
    are dropped (X-Agora-Description header is latin-1).
    """
    s = path.replace("/", "-").replace("\\", "-").replace("_", "-")
    out = "".join(
        c if (c.isascii() and (c.isalnum() or c == "-")) else "" for c in s
    )
    out = re.sub(r"-+", "-", out)
    return out.strip("-") or "root"


def _node_weight(node: dict) -> int:
    return (
        sum(f["weight"] for f in node["files"])
        + sum(_node_weight(s) for s in node["subfolders"])
    )


def _all_files(node: dict) -> list[str]:
    files = [f["path"] for f in node["files"]]
    for sub in node["subfolders"]:
        files.extend(_all_files(sub))
    return files


def partition_tree(tree: dict, target_size: int) -> tuple[list[Partition], list[str]]:
    """Partition the tree into a flat list, with per-partition weight ≤ target_size.

    Returns (partitions, warnings). Warnings are emitted for oversize leaves
    and oversize loose remainders.
    """
    if target_size <= 0:
        raise ValueError(f"target_size must be positive, got {target_size}")
    partitions: list[Partition] = []
    warnings: list[str] = []
    _partition_recurse(tree, target_size, partitions, warnings)
    return partitions, warnings


def _partition_recurse(
    node: dict,
    T: int,
    partitions: list[Partition],
    warnings: list[str],
) -> None:
    w = _node_weight(node)
    path = node["path"]

    if w == 0:
        return

    if w <= T:
        partitions.append(Partition(
            id=slug(path or "root"),
            root=path,
            weight=w,
            files=tuple(_all_files(node)),
        ))
        return

    # w > T
    if not node["subfolders"]:
        warnings.append(
            f"partition '{slug(path or 'root')}' weight {w} > target {T} "
            f"— leaf folder, cannot split further"
        )
        partitions.append(Partition(
            id=slug(path or "root"),
            root=path,
            weight=w,
            files=tuple(_all_files(node)),
        ))
        return

    # Has subfolders — recurse first
    sub_start = len(partitions)
    for sub in node["subfolders"]:
        _partition_recurse(sub, T, partitions, warnings)

    # Handle this node's loose files (direct, not in subfolders)
    loose_files = [f["path"] for f in node["files"]]
    L = sum(f["weight"] for f in node["files"])
    if L == 0:
        return

    if L > T:
        warnings.append(
            f"partition '{slug(path or 'root')}-loose' weight {L} > target {T} "
            f"— folder's loose files exceed target"
        )
        partitions.append(Partition(
            id=slug(path or "root") + "-loose",
            root=path,
            weight=L,
            files=tuple(loose_files),
        ))
        return

    # L <= T — try merging with smallest fitting sibling partition
    sub_partitions = partitions[sub_start:]
    fits = [(i, p) for i, p in enumerate(sub_partitions) if p.weight + L <= T]
    if fits:
        idx, smallest = min(fits, key=lambda x: x[1].weight)
        merged = Partition(
            id=smallest.id,
            root=smallest.root,
            weight=smallest.weight + L,
            files=smallest.files + tuple(loose_files),
        )
        partitions[sub_start + idx] = merged
    else:
        partitions.append(Partition(
            id=slug(path or "root") + "-loose",
            root=path,
            weight=L,
            files=tuple(loose_files),
        ))


def main() -> int:
    payload = json.load(sys.stdin)
    parts, warnings = partition_tree(payload["tree"], payload["target_size"])
    out = {
        "partitions": [asdict(p) for p in parts],
        "warnings": warnings,
    }
    json.dump(out, sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/test_structure_partition.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/cc-agora-structure/scripts/partition.py tests/test_structure_partition.py
git commit -m "feat: partition.py 코어 트리워크 분할기 (균형 + 과대 리프)"
```

---

## Task 3: partition.py — Remainder Merge, Slug, Edge Cases

**Files:**
- Modify: `tests/test_structure_partition.py` (add tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/test_structure_partition.py`:

```python
def test_remainder_merges_with_smallest_fitting_sibling():
    tree = {
        "name": "root", "path": "", "files": [
            {"path": "root.py", "weight": 2},  # remainder
        ],
        "subfolders": [
            {"name": "a", "path": "a",
             "files": [{"path": "a/x.py", "weight": 7}], "subfolders": []},
            {"name": "b", "path": "b",
             "files": [{"path": "b/y.py", "weight": 5}], "subfolders": []},
        ],
    }
    parts, warnings = partition_tree(tree, target_size=10)
    assert warnings == []
    # Total weight = 14. Two subfolders 7,5; remainder 2 should merge with smallest (5 -> 7).
    assert len(parts) == 2
    merged = next(p for p in parts if "root.py" in p.files)
    assert merged.root == "b"
    assert merged.weight == 7
    assert set(merged.files) == {"b/y.py", "root.py"}


def test_remainder_emits_own_partition_when_no_sibling_fits():
    tree = {
        "name": "root", "path": "", "files": [
            {"path": "root.py", "weight": 3},
        ],
        "subfolders": [
            {"name": "a", "path": "a",
             "files": [{"path": "a/x.py", "weight": 9}], "subfolders": []},
            {"name": "b", "path": "b",
             "files": [{"path": "b/y.py", "weight": 9}], "subfolders": []},
        ],
    }
    parts, warnings = partition_tree(tree, target_size=10)
    assert warnings == []
    # No sibling has room (9+3=12 > 10). Remainder gets own partition.
    assert len(parts) == 3
    own = next(p for p in parts if p.id.endswith("-loose"))
    assert own.weight == 3
    assert own.files == ("root.py",)


def test_oversize_loose_remainder_emits_with_warning():
    tree = {
        "name": "big", "path": "big", "files": [
            {"path": f"big/f{i}.py", "weight": 5} for i in range(10)
        ],
        "subfolders": [
            {"name": "sub", "path": "big/sub",
             "files": [{"path": "big/sub/q.py", "weight": 8}], "subfolders": []},
        ],
    }
    parts, warnings = partition_tree(tree, target_size=20)
    # subfolder: 8 ≤ 20 -> one partition.
    # loose: 50 > 20 -> own partition + warning.
    assert any("folder's loose files exceed target" in w for w in warnings)
    loose = next(p for p in parts if p.id.endswith("-loose"))
    assert loose.weight == 50


def test_slug_drops_non_ascii_and_normalizes():
    assert slug("src/agent_agora") == "src-agent-agora"
    assert slug("a/한글/b") == "a-b"
    assert slug("") == "root"
    assert slug("foo_bar-baz") == "foo-bar-baz"
    assert slug("/leading/slash") == "leading-slash"


def test_empty_tree_yields_no_partitions():
    tree = {"name": "root", "path": "", "files": [], "subfolders": []}
    parts, warnings = partition_tree(tree, target_size=10)
    assert parts == []
    assert warnings == []


def test_single_file_under_target():
    tree = {
        "name": "root", "path": "",
        "files": [{"path": "only.py", "weight": 4}],
        "subfolders": [],
    }
    parts, warnings = partition_tree(tree, target_size=10)
    assert len(parts) == 1
    assert parts[0].weight == 4
    assert parts[0].files == ("only.py",)


def test_target_size_must_be_positive():
    with pytest.raises(ValueError):
        partition_tree({"name": "root", "path": "", "files": [], "subfolders": []}, target_size=0)
```

- [ ] **Step 2: Run tests to verify**

Run: `python -m pytest tests/test_structure_partition.py -v`
Expected: All earlier tests still pass; new tests should also pass (the Task 2 implementation already covers these cases). If any fail, fix `partition.py` minimally.

- [ ] **Step 3: Commit**

```bash
git add tests/test_structure_partition.py
git commit -m "test: partition.py 잔여 병합·슬러그·엣지 케이스 커버"
```

---

## Task 4: Worker Templates & Manifest Example

**Files:**
- Create: `plugin/cc-agora-structure/templates/worker-claude.md.template`
- Create: `plugin/cc-agora-structure/templates/worker-mcp.json.template`
- Create: `plugin/cc-agora-structure/templates/worker-settings.local.json.template`
- Create: `plugin/cc-agora-structure/templates/structure-manifest.json.example`

- [ ] **Step 1: Create worker-claude.md.template**

Create `plugin/cc-agora-structure/templates/worker-claude.md.template`:

```markdown
# {{INSTANCE_ID}} ({{ROLE}}) — Partition {{PARTITION_ID}}

이 인스턴스는 **{{INSTANCE_ID}}** 워커이다. 역할: **{{ROLE}}**. 책임: {{DESCRIPTION}}.

## 페르소나

본인의 역할 페르소나는 `cc-agora-{{ROLE}}` 플러그인이 제공하는 `persona` 스킬에 있다. 기동 시 그 스킬을 적용해 역할을 수행한다.

## 통신

채널 모드 메시징은 `agora-protocol` 스킬을 따른다 — 채널 알림으로 깨어나 `agora.flush`로 인박스를 드레인하고, 처리 후 `agora.dispatch`로 답신한다. 등록·해제는 `.mcp.json` 헤더로 자동 처리되므로 `agora.register`/`agora.unregister`를 호출하지 않는다.

## 파티션 배정

- **id:** `{{PARTITION_ID}}`
- **root:** `{{PARTITION_ROOT}}`
- **예약 worktree 경로:** `{{WORKTREE_PATH}}`
- **담당 파일:**
{{PARTITION_FILES}}

## 범위 규칙

네 편집 범위는 `{{PARTITION_ROOT}}` 폴더 내부다. 범위 밖 편집은 금지된다.

**크로스파티션 읽기** — 다른 파티션의 코드는 네 디스크에 없다. 시그니처·구조·호출관계·상속은 `code-review-graph` MCP 도구로 조회한다:
- `mcp__code-review-graph__query_graph_tool` (`pattern`은 `callers_of`·`callees_of`·`imports_of`·`importers_of`·`children_of`·`tests_for`·`inheritors_of`·`file_summary` 중 하나)
- `mcp__code-review-graph__semantic_search_nodes_tool`

**크로스파티션 쓰기** — 다른 파티션 파일의 수정이 필요하면 agora로 그 파티션 담당 워커에 task를 디스패치한다 (`agora.dispatch`).

## worktree 절차

구현 task를 받으면 다음 순서로 작업 공간을 준비한다:

1. superpowers `using-git-worktrees` 스킬을 적용한다.
2. 타깃 레포(`{{REPO_PATH}}`)에서 예약된 경로에 worktree를 만든다:
   ```
   git -C "{{REPO_PATH}}" worktree add "{{WORKTREE_PATH}}" -b structure/{{PARTITION_ID}}
   ```
3. worktree에서 콘 모드 sparse-checkout으로 파티션 폴더만 머티리얼라이즈한다:
   ```
   git -C "{{WORKTREE_PATH}}" sparse-checkout init --cone
   git -C "{{WORKTREE_PATH}}" sparse-checkout set "{{PARTITION_ROOT}}"
   ```
4. `cd {{WORKTREE_PATH}}/{{PARTITION_ROOT}}`로 들어가 거기서 모든 구현 작업을 수행한다.
5. 후속 task는 같은 worktree를 재사용한다 (브랜치 분기는 워크트리 스킬 책임).

worktree 경로가 이미 채워져 있거나 git 명령이 실패하면, task를 중단하고 agora로 운영자에게 에러를 보고한다.
```

- [ ] **Step 2: Create worker-mcp.json.template**

Create `plugin/cc-agora-structure/templates/worker-mcp.json.template`:

```json
{
  "mcpServers": {
    "agentagora": {
      "type": "http",
      "url": "{{SERVER_URL}}",
      "headers": {
        "X-Agora-Instance-Id": "{{INSTANCE_ID}}",
        "X-Agora-Role": "{{ROLE}}",
        "X-Agora-Description": "{{DESCRIPTION}}",
        "X-Agora-Cwd": "{{CWD}}"
      }
    },
    "agora-channel": {
      "command": "claude",
      "args": ["channel", "agora-channel", "--server-url", "{{SERVER_URL}}", "--instance-id", "{{INSTANCE_ID}}"]
    },
    "code-review-graph": {
      "command": "code-review-graph",
      "args": ["serve"]
    }
  }
}
```

(`agora-channel`의 `command`/`args`는 기존 `cc-agora-ops/templates/mcp.json.template`의 형식을 그대로 따르되, code-review-graph를 추가한다. 만약 기존 템플릿과 형식이 다르면 기존 것을 우선으로 맞춘다 — 이 task의 step 3에서 확인.)

- [ ] **Step 3: Verify agora-channel block matches existing template**

Run: `Read plugin/cc-agora-ops/templates/mcp.json.template`. Confirm the `agora-channel` server block (command, args) matches. If different, adjust `worker-mcp.json.template`'s `agora-channel` section to be byte-identical to the existing one (keeping the additional `code-review-graph` block).

- [ ] **Step 4: Create worker-settings.local.json.template**

Create `plugin/cc-agora-structure/templates/worker-settings.local.json.template`:

```json
{
  "extraKnownMarketplaces": {
    "agentagora": {"source": "directory", "path": "{{MARKETPLACE_PATH}}"}
  },
  "enabledPlugins": {
    "{{PERSONA_PLUGIN}}@agentagora": true,
    "cc-agora-structure@agentagora": true
  },
  "permissions": {
    "allow": [
      "Edit({{STAGING_GLOB}})",
      "Write({{STAGING_GLOB}})",
      "NotebookEdit({{STAGING_GLOB}})",
      "Edit({{WORKTREE_GLOB}})",
      "Write({{WORKTREE_GLOB}})",
      "NotebookEdit({{WORKTREE_GLOB}})"
    ]
  }
}
```

- [ ] **Step 5: Create structure-manifest.json.example**

Create `plugin/cc-agora-structure/templates/structure-manifest.json.example`:

```json
{
  "version": 1,
  "repo": "C:/path/to/your/repo",
  "target_size": 80,
  "generated": "2026-05-20T12:34:56Z",
  "partitions": [
    {
      "id": "src-agent-agora",
      "root": "src/agent_agora",
      "weight": 412,
      "files": [
        "src/agent_agora/server.py",
        "src/agent_agora/dispatcher.py"
      ],
      "suggested_role": "implementer",
      "coupling": [
        {"to": "tests", "edges": 30, "kinds": {"calls": 28, "inherits": 2}}
      ]
    },
    {
      "id": "tests",
      "root": "tests",
      "weight": 95,
      "files": [
        "tests/test_v4_dispatcher.py",
        "tests/test_registry.py"
      ],
      "suggested_role": "tester",
      "coupling": []
    }
  ],
  "warnings": [
    "partition 'src-agent-agora' weight 412 > target 80 — leaf folder, cannot split further",
    "inherits edge crosses partition boundary: tests -> src-agent-agora"
  ]
}
```

- [ ] **Step 6: Commit**

```bash
git add plugin/cc-agora-structure/templates/
git commit -m "feat: cc-agora-structure 워커 템플릿 4종 (CLAUDE.md·.mcp.json·settings·manifest)"
```

---

## Task 5: structure_spawn.py — Manifest Loading & Validation

**Files:**
- Create: `plugin/cc-agora-structure/scripts/structure_spawn.py`
- Create: `tests/test_structure_spawn.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_structure_spawn.py`:

```python
"""Tests for cc-agora-structure structure_spawn.py — manifest loading + validation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "plugin" / "cc-agora-structure" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from structure_spawn import Manifest, PartitionSpec, load_manifest  # noqa: E402


def _write_manifest(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _valid_manifest_data(repo_str: str) -> dict:
    return {
        "version": 1,
        "repo": repo_str,
        "target_size": 80,
        "partitions": [
            {
                "id": "src-foo",
                "root": "src/foo",
                "weight": 50,
                "files": ["src/foo/a.py", "src/foo/b.py"],
                "suggested_role": "implementer",
                "coupling": [],
            }
        ],
        "warnings": [],
    }


def test_load_valid_manifest(tmp_path):
    path = _write_manifest(tmp_path, _valid_manifest_data("C:/repo"))
    m = load_manifest(path)
    assert isinstance(m, Manifest)
    assert m.version == 1
    assert m.repo == "C:/repo"
    assert m.target_size == 80
    assert len(m.partitions) == 1
    p = m.partitions[0]
    assert isinstance(p, PartitionSpec)
    assert p.id == "src-foo"
    assert p.root == "src/foo"
    assert p.files == ("src/foo/a.py", "src/foo/b.py")
    assert p.suggested_role == "implementer"


def test_reject_wrong_version(tmp_path):
    data = _valid_manifest_data("C:/repo")
    data["version"] = 2
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ValueError, match="version 1"):
        load_manifest(path)


def test_reject_missing_partition_field(tmp_path):
    data = _valid_manifest_data("C:/repo")
    del data["partitions"][0]["root"]
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ValueError, match="root"):
        load_manifest(path)


def test_reject_non_ascii_partition_id(tmp_path):
    data = _valid_manifest_data("C:/repo")
    data["partitions"][0]["id"] = "한글-id"
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ValueError, match="ASCII"):
        load_manifest(path)


def test_reject_empty_repo(tmp_path):
    data = _valid_manifest_data("")
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ValueError, match="repo"):
        load_manifest(path)


def test_reject_non_positive_target_size(tmp_path):
    data = _valid_manifest_data("C:/repo")
    data["target_size"] = 0
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ValueError, match="target_size"):
        load_manifest(path)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_structure_spawn.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'structure_spawn'`.

- [ ] **Step 3: Create structure_spawn.py — manifest loading skeleton**

Create `plugin/cc-agora-structure/scripts/structure_spawn.py`:

```python
"""/agora-structure-spawn implementation — read a structure manifest and
create per-partition staging dirs that launch channel-mode workers.

Workers create their own worktree+sparse-checkout on first task receipt
(via the superpowers using-git-worktrees skill); this script only writes
config files and launches.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PartitionSpec:
    id: str
    root: str
    weight: int
    files: tuple[str, ...]
    suggested_role: str
    coupling: tuple[dict, ...]


@dataclass(frozen=True)
class Manifest:
    version: int
    repo: str
    target_size: int
    partitions: tuple[PartitionSpec, ...]
    warnings: tuple[str, ...]


def load_manifest(path: Path) -> Manifest:
    data = json.loads(path.read_text(encoding="utf-8"))

    if data.get("version") != 1:
        raise ValueError(
            f"manifest version 1 required, got {data.get('version')!r}"
        )
    if not isinstance(data.get("repo"), str) or not data["repo"]:
        raise ValueError("manifest.repo must be a non-empty string")
    if not isinstance(data.get("target_size"), int) or data["target_size"] <= 0:
        raise ValueError("manifest.target_size must be a positive integer")
    if not isinstance(data.get("partitions"), list):
        raise ValueError("manifest.partitions must be a list")

    parts: list[PartitionSpec] = []
    for i, p in enumerate(data["partitions"]):
        for key in ("id", "root", "weight", "files", "suggested_role"):
            if key not in p:
                raise ValueError(f"partitions[{i}].{key} missing")
        if not isinstance(p["id"], str) or not p["id"].isascii():
            raise ValueError(f"partitions[{i}].id must be an ASCII string")
        parts.append(PartitionSpec(
            id=p["id"],
            root=p["root"],
            weight=int(p["weight"]),
            files=tuple(p["files"]),
            suggested_role=p["suggested_role"],
            coupling=tuple(p.get("coupling", [])),
        ))

    return Manifest(
        version=int(data["version"]),
        repo=data["repo"],
        target_size=int(data["target_size"]),
        partitions=tuple(parts),
        warnings=tuple(data.get("warnings", [])),
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/test_structure_spawn.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/cc-agora-structure/scripts/structure_spawn.py tests/test_structure_spawn.py
git commit -m "feat: structure_spawn.py 매니페스트 로딩·스키마 검증"
```

---

## Task 6: structure_spawn.py — Staging Rendering

**Files:**
- Modify: `plugin/cc-agora-structure/scripts/structure_spawn.py`
- Modify: `tests/test_structure_spawn.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_structure_spawn.py`:

```python
from structure_spawn import render_staging  # noqa: E402


@pytest.fixture
def templates_dir():
    return REPO_ROOT / "plugin" / "cc-agora-structure" / "templates"


@pytest.fixture
def sample_partition():
    return PartitionSpec(
        id="src-foo",
        root="src/foo",
        weight=50,
        files=("src/foo/a.py", "src/foo/b.py"),
        suggested_role="implementer",
        coupling=(),
    )


def test_render_creates_expected_files(tmp_path, templates_dir, sample_partition):
    staging = tmp_path / "workers" / "src-foo"
    worktree = tmp_path / "worktrees" / "src-foo"
    repo = tmp_path / "repo"
    repo.mkdir()
    render_staging(
        partition=sample_partition,
        staging_dir=staging,
        worktree_path=worktree,
        repo_path=repo,
        server_url="http://127.0.0.1:8420/mcp",
        marketplace_path=str(REPO_ROOT / "plugin"),
        templates_dir=templates_dir,
    )
    assert (staging / "CLAUDE.md").is_file()
    assert (staging / ".mcp.json").is_file()
    assert (staging / ".claude" / "settings.local.json").is_file()
    assert (staging / "run.bat").is_file()


def test_render_claude_md_contains_partition_details(tmp_path, templates_dir, sample_partition):
    staging = tmp_path / "workers" / "src-foo"
    worktree = tmp_path / "worktrees" / "src-foo"
    repo = tmp_path / "repo"
    repo.mkdir()
    render_staging(
        partition=sample_partition,
        staging_dir=staging,
        worktree_path=worktree,
        repo_path=repo,
        server_url="http://127.0.0.1:8420/mcp",
        marketplace_path=str(REPO_ROOT / "plugin"),
        templates_dir=templates_dir,
    )
    body = (staging / "CLAUDE.md").read_text(encoding="utf-8")
    assert "src-foo" in body
    assert "src/foo" in body
    assert "src/foo/a.py" in body
    assert "src/foo/b.py" in body
    assert "using-git-worktrees" in body
    assert "code-review-graph" in body
    assert "sparse-checkout" in body
    assert worktree.as_posix() in body


def test_render_mcp_json_has_three_servers_and_ascii_headers(tmp_path, templates_dir, sample_partition):
    staging = tmp_path / "workers" / "src-foo"
    worktree = tmp_path / "worktrees" / "src-foo"
    repo = tmp_path / "repo"
    repo.mkdir()
    render_staging(
        partition=sample_partition,
        staging_dir=staging,
        worktree_path=worktree,
        repo_path=repo,
        server_url="http://127.0.0.1:8420/mcp",
        marketplace_path=str(REPO_ROOT / "plugin"),
        templates_dir=templates_dir,
    )
    data = json.loads((staging / ".mcp.json").read_text(encoding="utf-8"))
    servers = data["mcpServers"]
    assert set(servers.keys()) == {"agentagora", "agora-channel", "code-review-graph"}
    headers = servers["agentagora"]["headers"]
    assert headers["X-Agora-Cwd"] == staging.resolve().as_posix()
    assert headers["X-Agora-Role"] == "implementer"
    # ASCII check
    for k, v in headers.items():
        v.encode("latin-1")


def test_render_settings_whitelist_includes_both_paths(tmp_path, templates_dir, sample_partition):
    staging = tmp_path / "workers" / "src-foo"
    worktree = tmp_path / "worktrees" / "src-foo"
    repo = tmp_path / "repo"
    repo.mkdir()
    render_staging(
        partition=sample_partition,
        staging_dir=staging,
        worktree_path=worktree,
        repo_path=repo,
        server_url="http://127.0.0.1:8420/mcp",
        marketplace_path=str(REPO_ROOT / "plugin"),
        templates_dir=templates_dir,
    )
    settings = json.loads((staging / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    allow = settings["permissions"]["allow"]
    staging_glob = staging.resolve().as_posix() + "/**"
    worktree_glob = worktree.as_posix() + "/**"
    assert f"Edit({staging_glob})" in allow
    assert f"Write({staging_glob})" in allow
    assert f"Edit({worktree_glob})" in allow
    assert f"Write({worktree_glob})" in allow


def test_render_rejects_non_ascii_description(tmp_path, templates_dir):
    p = PartitionSpec(
        id="src-foo",
        root="src/한글",  # non-ASCII root → description would contain it
        weight=50,
        files=("src/한글/a.py",),
        suggested_role="implementer",
        coupling=(),
    )
    staging = tmp_path / "workers" / "src-foo"
    worktree = tmp_path / "worktrees" / "src-foo"
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ValueError, match="ASCII"):
        render_staging(
            partition=p,
            staging_dir=staging,
            worktree_path=worktree,
            repo_path=repo,
            server_url="http://127.0.0.1:8420/mcp",
            marketplace_path=str(REPO_ROOT / "plugin"),
            templates_dir=templates_dir,
        )
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_structure_spawn.py::test_render_creates_expected_files -v`
Expected: FAIL with `ImportError: cannot import name 'render_staging'`.

- [ ] **Step 3: Add render_staging to structure_spawn.py**

Append to `plugin/cc-agora-structure/scripts/structure_spawn.py`:

```python
# Role -> persona plugin mapping mirrors cc-agora-ops/scripts/role_policy.py.
# Kept inline here to avoid cross-plugin imports; if missing, fall back to general.
_DEFAULT_PERSONA_PLUGINS = {
    "implementer": "cc-agora-implementer",
    "planner": "cc-agora-planner",
    "router": "cc-agora-router",
    "reviewer": "cc-agora-reviewer",
    "tester": "cc-agora-tester",
    "debugger": "cc-agora-debugger",
    "improver": "cc-agora-improver",
    "general": "cc-agora-general",
    "coder": "cc-agora-coder",
    "writer": "cc-agora-writer",
    "orchestrator": "cc-agora-orchestrator",
}


def _ascii_only(s: str) -> bool:
    try:
        s.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return all(ord(c) < 128 for c in s)


def _persona_plugin_for(role: str) -> str:
    return _DEFAULT_PERSONA_PLUGINS.get(role, "cc-agora-general")


def _render_template(template_path: Path, mapping: dict[str, str]) -> str:
    text = template_path.read_text(encoding="utf-8")
    for key, value in mapping.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _files_markdown_list(files: tuple[str, ...]) -> str:
    return "\n".join(f"- `{f}`" for f in files)


def render_staging(
    *,
    partition: PartitionSpec,
    staging_dir: Path,
    worktree_path: Path,
    repo_path: Path,
    server_url: str,
    marketplace_path: str,
    templates_dir: Path,
) -> None:
    """Render one partition's staging directory.

    Writes CLAUDE.md, .mcp.json (3 servers), .claude/settings.local.json
    (permission whitelist), and run.bat (channel mode). Does NOT create
    the worktree — the worker does that on first task receipt.
    """
    description = f"Partition {partition.id} at {partition.root}"
    if not _ascii_only(description):
        raise ValueError(
            f"X-Agora-Description must be ASCII (latin-1); got {description!r}"
        )

    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / ".claude").mkdir(exist_ok=True)

    instance_id = partition.id
    role = partition.suggested_role
    persona_plugin = _persona_plugin_for(role)

    common = {
        "INSTANCE_ID": instance_id,
        "ROLE": role,
        "DESCRIPTION": description,
        "PARTITION_ID": partition.id,
        "PARTITION_ROOT": partition.root,
        "PARTITION_FILES": _files_markdown_list(partition.files),
        "WORKTREE_PATH": worktree_path.as_posix(),
        "REPO_PATH": repo_path.as_posix(),
        "SERVER_URL": server_url,
        "CWD": staging_dir.resolve().as_posix(),
        "MARKETPLACE_PATH": marketplace_path.replace("\\", "/"),
        "PERSONA_PLUGIN": persona_plugin,
        "STAGING_GLOB": staging_dir.resolve().as_posix() + "/**",
        "WORKTREE_GLOB": worktree_path.as_posix() + "/**",
    }

    # CLAUDE.md
    claude_md = _render_template(templates_dir / "worker-claude.md.template", common)
    (staging_dir / "CLAUDE.md").write_text(claude_md, encoding="utf-8", newline="\n")

    # .mcp.json
    mcp_content = _render_template(templates_dir / "worker-mcp.json.template", common)
    json.loads(mcp_content)  # self-check
    (staging_dir / ".mcp.json").write_text(mcp_content, encoding="utf-8", newline="\n")

    # settings.local.json
    settings_content = _render_template(
        templates_dir / "worker-settings.local.json.template", common
    )
    json.loads(settings_content)  # self-check
    (staging_dir / ".claude" / "settings.local.json").write_text(
        settings_content, encoding="utf-8", newline="\n"
    )

    # run.bat — channel mode (matches cc-agora-ops convention)
    run_bat = (
        "@echo off\r\n"
        "REM Channel-mode worker. agora-channel needs the development-channels flag.\r\n"
        "claude --dangerously-load-development-channels server:agora-channel %*\r\n"
    )
    (staging_dir / "run.bat").write_text(run_bat, encoding="utf-8", newline="")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/test_structure_spawn.py -v`
Expected: all tests pass (the 6 manifest tests from Task 5 + 5 new render tests).

If `test_render_mcp_json_has_three_servers_and_ascii_headers` fails because `worker-mcp.json.template` doesn't yet have an `agora-channel` block matching the existing cc-agora-ops template, fix the template to include all 3 servers with valid placeholders.

- [ ] **Step 5: Commit**

```bash
git add plugin/cc-agora-structure/scripts/structure_spawn.py plugin/cc-agora-structure/templates/ tests/test_structure_spawn.py
git commit -m "feat: structure_spawn.py 스테이징 디렉터리 렌더링 (CLAUDE.md·3서버 .mcp.json·권한·run.bat)"
```

---

## Task 7: structure_spawn.py — CLI & spawn() Orchestration

**Files:**
- Modify: `plugin/cc-agora-structure/scripts/structure_spawn.py`
- Modify: `tests/test_structure_spawn.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_structure_spawn.py`:

```python
from structure_spawn import spawn, main  # noqa: E402


def test_spawn_creates_all_staging_dirs(tmp_path, templates_dir):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()  # mark as git
    manifest = Manifest(
        version=1, repo=repo.as_posix(), target_size=80,
        partitions=(
            PartitionSpec(id="a", root="a", weight=10, files=("a/x.py",),
                          suggested_role="implementer", coupling=()),
            PartitionSpec(id="b", root="b", weight=10, files=("b/y.py",),
                          suggested_role="tester", coupling=()),
        ),
        warnings=(),
    )
    out = tmp_path / "workers"
    wt_base = tmp_path / "worktrees"
    dirs = spawn(
        manifest=manifest,
        out=out,
        worktree_base=wt_base,
        server_url="http://127.0.0.1:8420/mcp",
        launch="off",
        templates_dir=templates_dir,
        marketplace_path=str(REPO_ROOT / "plugin"),
        force=False,
    )
    assert len(dirs) == 2
    assert (out / "a" / "CLAUDE.md").is_file()
    assert (out / "b" / "CLAUDE.md").is_file()


def test_spawn_skips_empty_partition(tmp_path, templates_dir, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    manifest = Manifest(
        version=1, repo=repo.as_posix(), target_size=80,
        partitions=(
            PartitionSpec(id="empty", root="empty", weight=0, files=(),
                          suggested_role="implementer", coupling=()),
            PartitionSpec(id="good", root="good", weight=5, files=("good/x.py",),
                          suggested_role="implementer", coupling=()),
        ),
        warnings=(),
    )
    out = tmp_path / "workers"
    wt_base = tmp_path / "worktrees"
    dirs = spawn(
        manifest=manifest,
        out=out, worktree_base=wt_base,
        server_url="http://127.0.0.1:8420/mcp",
        launch="off", templates_dir=templates_dir,
        marketplace_path=str(REPO_ROOT / "plugin"),
        force=False,
    )
    assert len(dirs) == 1
    assert dirs[0].name == "good"
    captured = capsys.readouterr()
    assert "empty" in captured.err
    assert "skip" in captured.err.lower()


def test_spawn_rejects_existing_staging_without_force(tmp_path, templates_dir):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    out = tmp_path / "workers"
    (out / "a").mkdir(parents=True)
    (out / "a" / "marker").write_text("x")

    manifest = Manifest(
        version=1, repo=repo.as_posix(), target_size=80,
        partitions=(
            PartitionSpec(id="a", root="a", weight=5, files=("a/x.py",),
                          suggested_role="implementer", coupling=()),
        ),
        warnings=(),
    )
    with pytest.raises(FileExistsError):
        spawn(
            manifest=manifest, out=out,
            worktree_base=tmp_path / "worktrees",
            server_url="http://127.0.0.1:8420/mcp",
            launch="off", templates_dir=templates_dir,
            marketplace_path=str(REPO_ROOT / "plugin"),
            force=False,
        )


def test_main_rejects_non_git_repo(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()  # no .git

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "version": 1, "repo": repo.as_posix(), "target_size": 80,
        "partitions": [
            {"id": "a", "root": "a", "weight": 5,
             "files": ["a/x.py"], "suggested_role": "implementer", "coupling": []}
        ],
        "warnings": [],
    }))
    rc = main(["--manifest", str(manifest_path), "--launch", "off",
               "--out", str(tmp_path / "workers"),
               "--worktree-base", str(tmp_path / "worktrees")])
    assert rc == 2
    captured = capsys.readouterr()
    assert "not a git repo" in captured.err
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_structure_spawn.py -v`
Expected: 4 new tests fail with `ImportError`.

- [ ] **Step 3: Add spawn() and main() to structure_spawn.py**

Append to `plugin/cc-agora-structure/scripts/structure_spawn.py`:

```python
DEFAULT_SERVER_URL = "http://127.0.0.1:8420/mcp"


def spawn(
    *,
    manifest: Manifest,
    out: Path,
    worktree_base: Path,
    server_url: str,
    launch: str,
    templates_dir: Path,
    marketplace_path: str,
    force: bool,
) -> list[Path]:
    """Create staging dirs for all non-empty partitions and optionally launch.

    Returns the list of created staging dirs (in manifest order, skipped
    partitions excluded).
    """
    staging_dirs: list[Path] = []
    repo = Path(manifest.repo)

    for partition in manifest.partitions:
        if not partition.files:
            print(
                f"[cc-agora-structure] partition {partition.id!r} has no files — skipping",
                file=sys.stderr,
            )
            continue

        staging_dir = out / partition.id
        worktree_path = worktree_base / partition.id

        if staging_dir.exists() and not force:
            raise FileExistsError(
                f"staging dir already exists: {staging_dir} (use --force to overwrite)"
            )
        if worktree_path.exists() and not force:
            print(
                f"[cc-agora-structure] warning: worktree reserved path "
                f"{worktree_path} already exists — worker may fail to create worktree",
                file=sys.stderr,
            )

        render_staging(
            partition=partition,
            staging_dir=staging_dir,
            worktree_path=worktree_path,
            repo_path=repo,
            server_url=server_url,
            marketplace_path=marketplace_path,
            templates_dir=templates_dir,
        )
        staging_dirs.append(staging_dir)

    if launch == "manual":
        print("# Launch commands:")
        for d in staging_dirs:
            print(f'wt.exe -d "{d}" cmd /k run.bat')
    elif launch == "auto":
        _launch_auto(staging_dirs)
    # launch == "off" — silent

    return staging_dirs


def _launch_auto(staging_dirs: list[Path]) -> None:
    """Open wt.exe tabs for each staging dir."""
    import subprocess
    if not staging_dirs:
        return
    args = ["wt.exe"]
    for i, d in enumerate(staging_dirs):
        if i > 0:
            args.append(";")
            args.append("new-tab")
        args += ["-d", str(d), "cmd", "/k", "run.bat"]
    subprocess.Popen(args)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agora-structure-spawn",
        description="Spawn channel-mode workers per structure-manifest partition.",
    )
    p.add_argument("--manifest", required=True, type=Path,
                   help="Path to structure-manifest.json")
    p.add_argument("--out", type=Path, default=None,
                   help="Staging-dir parent (default: <repo>/.agora-structure/workers)")
    p.add_argument("--worktree-base", type=Path, default=None,
                   help="Reserved worktree base (default: <repo-parent>/<repo>.structure-worktrees)")
    p.add_argument("--server-url", default=DEFAULT_SERVER_URL,
                   help=f"MCP server URL (default: {DEFAULT_SERVER_URL})")
    p.add_argument("--launch", choices=["off", "manual", "auto"], default="manual")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing staging dirs")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    manifest = load_manifest(args.manifest)
    repo = Path(manifest.repo)

    if not (repo / ".git").exists():
        print(
            f"[cc-agora-structure] error: {repo} is not a git repo — "
            "workers cannot create worktrees",
            file=sys.stderr,
        )
        return 2

    out = args.out or (repo / ".agora-structure" / "workers")
    worktree_base = args.worktree_base or (
        repo.parent / f"{repo.name}.structure-worktrees"
    )

    if manifest.warnings:
        print("# Manifest warnings:", file=sys.stderr)
        for w in manifest.warnings:
            print(f"  - {w}", file=sys.stderr)

    templates_dir = Path(__file__).resolve().parent.parent / "templates"
    marketplace_path = Path(__file__).resolve().parent.parent.parent.as_posix()

    try:
        staging_dirs = spawn(
            manifest=manifest,
            out=out,
            worktree_base=worktree_base,
            server_url=args.server_url,
            launch=args.launch,
            templates_dir=templates_dir,
            marketplace_path=marketplace_path,
            force=args.force,
        )
    except FileExistsError as e:
        print(f"[cc-agora-structure] error: {e}", file=sys.stderr)
        return 1

    print(f"[cc-agora-structure] created {len(staging_dirs)} staging dirs under {out.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run all tests to verify pass**

Run: `python -m pytest tests/test_structure_spawn.py tests/test_structure_partition.py tests/test_structure_plugin.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add plugin/cc-agora-structure/scripts/structure_spawn.py tests/test_structure_spawn.py
git commit -m "feat: structure_spawn.py CLI·spawn() — 다중 스테이징 + git 검증 + launch 모드"
```

---

## Task 8: Slash Commands

**Files:**
- Create: `plugin/cc-agora-structure/commands/agora-structure-analyze.md`
- Create: `plugin/cc-agora-structure/commands/agora-structure-spawn.md`

- [ ] **Step 1: Create agora-structure-analyze.md**

Create `plugin/cc-agora-structure/commands/agora-structure-analyze.md`:

```markdown
---
description: 타깃 레포의 구조를 분석해 워커별 파티션 매니페스트를 작성한다.
---

# /agora-structure-analyze

타깃 레포의 폴더 구조를 code-review-graph로 분석해 워커별 파티션을 산출하고, 구조 매니페스트(`structure-manifest.json`)를 작성한다. 운영자가 검토·편집한 뒤 `/agora-structure-spawn`으로 진행한다.

## 인자

`$ARGUMENTS`에서 다음을 파싱한다(없으면 기본값):

- `--repo <path>` — 타깃 레포 경로 (기본: CWD).
- `--target-size <N>` — 파티션 목표 가중치 (기본: 80).
- `--out <path>` — 매니페스트 출력 경로 (기본: `<repo>/.agora-structure/manifest.json`).

## 절차

다음 단계를 **순서대로** 수행하라. 각 단계는 결과를 다음 단계의 입력으로 쓴다.

### 1. 그래프 준비

`mcp__code-review-graph__list_graph_stats_tool`을 `repo_root=<repo>`로 호출해 그래프 상태를 확인하라. `total_nodes == 0`이거나 `last_updated`가 없으면 빌드한다:

`mcp__code-review-graph__build_or_update_graph_tool`을 `repo_root=<repo>`, `full_rebuild=true`, `postprocess="minimal"`로 호출.

### 2. 파일 노드 수집

`mcp__code-review-graph__semantic_search_nodes_tool`을 `query=""`(또는 한 글자 와일드카드), `kind="File"`, `limit=10000`로 호출해 모든 파일 노드를 얻는다. 각 결과의 `file_path`(절대경로)를 `<repo>` 기준 상대경로(forward-slash)로 변환해 보관.

### 3. 파일별 가중치 계산

각 파일에 대해 `mcp__code-review-graph__query_graph_tool`을 `pattern="file_summary"`, `target=<상대경로>`로 호출. 반환 `results`에서 `kind != "File"`인 노드 개수를 그 파일의 가중치로 한다.

### 4. 엣지 수집

각 파일에 대해 `query_graph` `pattern`을 `imports_of`·`importers_of`로 호출해 import 엣지를 모은다. 각 Class 노드(2단계에서 `kind="Class"`로 추가 검색)에 대해 `inheritors_of`로 상속 엣지를 모은다. 각 엣지는 `(source_file, target_file, kind)`로 기록.

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
{"to": "<other-partition-id>", "edges": <count>, "kinds": {"calls": N, "inherits": M, "imports": K}}
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
```

- [ ] **Step 2: Create agora-structure-spawn.md**

Create `plugin/cc-agora-structure/commands/agora-structure-spawn.md`:

```markdown
---
description: 구조 매니페스트로 파티션마다 워커별 스테이징 디렉터리를 만들고 다중 기동한다.
---

# /agora-structure-spawn

구조 매니페스트를 읽어 파티션마다 워커 스테이징 디렉터리를 만들고, 채널 모드로 다중 기동한다.

## 인자

`$ARGUMENTS`를 `structure_spawn.py`에 그대로 전달한다:

- `--manifest <path>` — **필수**. 매니페스트 JSON 경로.
- `--out <path>` — 스테이징 디렉터리 부모 (기본: `<repo>/.agora-structure/workers/`).
- `--worktree-base <path>` — 워커가 만들 worktree의 예약 베이스 (기본: `<repo-parent>/<repo>.structure-worktrees/`).
- `--server-url <url>` — MCP HTTP 서버 (기본: `http://127.0.0.1:8420/mcp`).
- `--launch off|manual|auto` — 기동 모드 (기본: `manual`).
- `--force` — 기존 스테이징 디렉터리 덮어쓰기.

## 실행

```bash
python <plugin-root>/scripts/structure_spawn.py $ARGUMENTS
```

여기서 `<plugin-root>`은 `plugin/cc-agora-structure/`.

## 결과

- 각 파티션마다 `<out>/<partition-id>/` 안에 `CLAUDE.md`·`.mcp.json`·`.claude/settings.local.json`·`run.bat`이 생성된다.
- `--launch=manual`(기본)이면 기동 커맨드가 출력된다 — 운영자가 복사해 실행.
- `--launch=auto`면 `wt.exe` 탭으로 즉시 기동.
- 타깃 레포가 git 레포가 아니면 종료 코드 2로 거부.

워커는 기동 직후 idle 상태이며, agora로 첫 구현 task를 받으면 superpowers `using-git-worktrees` 스킬로 자기 파티션의 worktree+sparse-checkout(콘 모드)을 만들어 작업한다.
```

- [ ] **Step 3: Commit**

```bash
git add plugin/cc-agora-structure/commands/
git commit -m "feat: cc-agora-structure 슬래시 커맨드 (analyze + spawn)"
```

---

## Task 9: Final Validation & Smoke

**Files:**
- Modify: `tests/test_structure_plugin.py` (add command file checks)

- [ ] **Step 1: Add smoke tests**

Append to `tests/test_structure_plugin.py`:

```python
def test_slash_commands_exist():
    cmd_dir = PLUGIN_DIR / "commands"
    assert (cmd_dir / "agora-structure-analyze.md").is_file()
    assert (cmd_dir / "agora-structure-spawn.md").is_file()


def test_scripts_exist():
    sc = PLUGIN_DIR / "scripts"
    assert (sc / "partition.py").is_file()
    assert (sc / "structure_spawn.py").is_file()


def test_templates_exist():
    t = PLUGIN_DIR / "templates"
    for name in (
        "worker-claude.md.template",
        "worker-mcp.json.template",
        "worker-settings.local.json.template",
        "structure-manifest.json.example",
    ):
        assert (t / name).is_file(), f"missing template: {name}"


def test_manifest_example_is_valid_json_and_loads_via_load_manifest(tmp_path):
    from structure_spawn import load_manifest  # type: ignore
    example = PLUGIN_DIR / "templates" / "structure-manifest.json.example"
    data = json.loads(example.read_text(encoding="utf-8"))
    # The example uses a placeholder repo path — patch it for load_manifest.
    data["repo"] = "C:/x"
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    m = load_manifest(p)
    assert m.version == 1
    assert len(m.partitions) >= 1
```

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/test_structure_partition.py tests/test_structure_spawn.py tests/test_structure_plugin.py -v`
Expected: all tests pass.

- [ ] **Step 3: Run full test suite (regression check)**

Run: `python -m pytest tests/ -x --ignore=tests/test_integration -q`
Expected: no regressions in existing tests. (`--ignore` excludes the slow integration suite; if it's part of CI baseline, include it instead.)

- [ ] **Step 4: Verify plugin loads in Claude Code**

Manual smoke (operator's machine — agentic worker reports outcome):

```bash
ls plugin/cc-agora-structure/.claude-plugin/plugin.json
python -c "import json; json.load(open('plugin/cc-agora-structure/.claude-plugin/plugin.json'))"
python -c "import json; json.load(open('plugin/cc-agora-structure/.mcp.json'))"
python -c "import json; json.load(open('plugin/.claude-plugin/marketplace.json'))"
```

All four should succeed with no output (or "ok").

- [ ] **Step 5: Commit**

```bash
git add tests/test_structure_plugin.py
git commit -m "test: cc-agora-structure 전체 파일 스모크 (커맨드·스크립트·템플릿·example 로딩)"
```

---
