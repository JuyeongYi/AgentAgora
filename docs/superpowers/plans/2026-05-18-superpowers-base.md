# superpowers-base 플러그인 — 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공통 스킬 3종(using-superpowers, verification-before-completion, writing-skills)과 SessionStart 훅을 `plugin/superpowers/superpowers-base/`에 배치하고, 마켓플레이스에 등록·구조 검증이 통과하는 상태를 만든다.

**Architecture:** 설계 spec §3·§4·§12(플랜 1) 기준. `superpowers-base`는 페르소나 스킬 없이 공통 스킬만 담는 라이브러리 플러그인이다. 원본 `superpowers_model_specified`의 `skills/` 디렉토리 3개와 `hooks/` 디렉토리(3파일)를 그대로 복사한다. `session-start` 스크립트는 `dirname` 기준 상위 디렉토리를 `PLUGIN_ROOT`로 자기 결정하며 `${PLUGIN_ROOT}/skills/using-superpowers/SKILL.md`를 읽는다 — `superpowers-base`의 레이아웃이 이 경로와 정확히 일치하므로 스크립트 내용을 수정할 필요가 없다.

**Tech Stack:** Claude Code 플러그인(.claude-plugin/plugin.json, marketplace.json), pytest.

---

## 파일 구조

```
plugin/superpowers/superpowers-base/
  .claude-plugin/
    plugin.json                               생성
  README.md                                   생성
  hooks/
    hooks.json                                복사 (원본 verbatim)
    run-hook.cmd                              복사 (원본 verbatim)
    session-start                             복사 (원본 verbatim — 경로 수정 불필요)
  skills/
    using-superpowers/
      SKILL.md                                복사
      references/                             복사
    verification-before-completion/
      SKILL.md                                복사
    writing-skills/
      SKILL.md                                복사
      anthropic-best-practices.md             복사
      examples/                               복사
      graphviz-conventions.dot                복사
      persuasion-principles.md                복사
      render-graphs.js                        복사
      testing-skills-with-subagents.md        복사
plugin/.claude-plugin/marketplace.json        수정 — superpowers-base 항목 추가
```

---

## Task 1: 플러그인 디렉토리 + plugin.json + README 생성

- [ ] 디렉토리 생성:
  ```bash
  mkdir -p "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/.claude-plugin"
  mkdir -p "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/hooks"
  mkdir -p "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/skills"
  ```

- [ ] `.claude-plugin/plugin.json` 생성 (전체 내용):
  ```json
  {
    "name": "superpowers-base",
    "description": "Superpowers persona base — shared skills every persona needs: skill discovery, verification before completion, and skill authoring.",
    "version": "0.1.0"
  }
  ```
  경로: `plugin/superpowers/superpowers-base/.claude-plugin/plugin.json`

- [ ] `README.md` 생성 (전체 내용):
  ```markdown
  # superpowers-base

  superpowers 페르소나 플러그인들이 공통으로 의존하는 기반 라이브러리 플러그인이다.
  스킬 탐색·사용법(`using-superpowers`), 완료 전 검증(`verification-before-completion`),
  스킬 작성법(`writing-skills`) — 모든 페르소나 워커가 필요로 하는 공통 스킬 3종을 제공한다.

  SessionStart 훅(`hooks/`)도 포함한다. 매 세션 시작 시 `using-superpowers` SKILL.md를
  컨텍스트에 자동 주입해, 워커가 처음부터 스킬 사용법을 인지하도록 한다.

  다른 superpowers 페르소나 플러그인(`superpowers-planner`, `superpowers-implementer` 등)은
  이 플러그인을 `dependencies`로 선언한다.

  ## 활성화

  워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 추가한다:

  ```json
  {
    "enabledPlugins": {
      "superpowers-base@agentagora": true
    }
  }
  ```
  ```
  경로: `plugin/superpowers/superpowers-base/README.md`

- [ ] 커밋:
  ```bash
  git add plugin/superpowers/superpowers-base/.claude-plugin/plugin.json \
          plugin/superpowers/superpowers-base/README.md
  git commit -m "feat: superpowers-base 플러그인 스캐폴드 (plugin.json + README)"
  ```

---

## Task 2: hooks/ 디렉토리 복사

원본 `hooks/` 안의 파일 3개(`hooks.json`, `run-hook.cmd`, `session-start`)를 그대로 복사한다.

**주의: `session-start` 스크립트는 수정 불필요.** 스크립트가 `SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"`로 자기 위치를 결정하고 `PLUGIN_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"`를 계산하므로, `superpowers-base/hooks/session-start`가 실행될 때 `PLUGIN_ROOT`는 자동으로 `superpowers-base/`가 된다. 이 경로 아래 `skills/using-superpowers/SKILL.md`가 존재하면 훅이 정상 동작한다 — Task 3에서 해당 스킬을 복사한다.

- [ ] 훅 파일 복사:
  ```bash
  cp "C:/Users/jylee/source/superpowers_model_specified/hooks/hooks.json" \
     "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/hooks/hooks.json"

  cp "C:/Users/jylee/source/superpowers_model_specified/hooks/run-hook.cmd" \
     "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/hooks/run-hook.cmd"

  cp "C:/Users/jylee/source/superpowers_model_specified/hooks/session-start" \
     "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/hooks/session-start"
  ```

- [ ] `session-start` 실행 권한 설정 (Unix 환경):
  ```bash
  chmod +x "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/hooks/session-start"
  ```
  (Windows Git Bash / WSL 에서도 실행; Windows 네이티브 환경에서는 `run-hook.cmd`가 bash를 호출하므로 권한 무관)

- [ ] 복사 결과 확인:
  ```bash
  ls -la "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/hooks/"
  # 기대: hooks.json, run-hook.cmd, session-start 3개
  ```

- [ ] 커밋:
  ```bash
  git add plugin/superpowers/superpowers-base/hooks/
  git commit -m "feat: superpowers-base hooks/ 복사 (SessionStart 훅 — 경로 수정 없음)"
  ```

---

## Task 3: 스킬 3개 복사

`using-superpowers`, `verification-before-completion`, `writing-skills` 디렉토리를 원본에서 그대로 복사한다. `model`/`effort` frontmatter 보존.

- [ ] `using-superpowers` 복사:
  ```bash
  cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/using-superpowers" \
        "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/skills/using-superpowers"
  ```

- [ ] `verification-before-completion` 복사:
  ```bash
  cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/verification-before-completion" \
        "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/skills/verification-before-completion"
  ```

- [ ] `writing-skills` 복사 (보조 파일 `anthropic-best-practices.md`, `examples/`, `graphviz-conventions.dot`, `persuasion-principles.md`, `render-graphs.js`, `testing-skills-with-subagents.md` 포함):
  ```bash
  cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/writing-skills" \
        "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/skills/writing-skills"
  ```

- [ ] 복사 결과 확인:
  ```bash
  ls "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/skills/"
  # 기대: using-superpowers  verification-before-completion  writing-skills

  ls "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/skills/using-superpowers/"
  # 기대: SKILL.md  references/

  ls "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/skills/writing-skills/"
  # 기대: SKILL.md  anthropic-best-practices.md  examples/  graphviz-conventions.dot
  #        persuasion-principles.md  render-graphs.js  testing-skills-with-subagents.md
  ```

- [ ] `session-start`가 읽는 SKILL.md 경로 검증:
  ```bash
  test -f "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/skills/using-superpowers/SKILL.md" \
    && echo "OK: session-start 훅 경로 정상" \
    || echo "FAIL: SKILL.md 없음"
  ```

- [ ] 커밋:
  ```bash
  git add plugin/superpowers/superpowers-base/skills/
  git commit -m "feat: superpowers-base 공통 스킬 3종 복사 (using-superpowers, verification-before-completion, writing-skills)"
  ```

---

## Task 4: marketplace.json 등록

`plugin/.claude-plugin/marketplace.json`의 `plugins` 배열에 `superpowers-base` 항목을 추가한다.

현재 마지막 항목(`cc-agora-writer`) 뒤에 아래 항목을 추가한다:

```json
{
  "name": "superpowers-base",
  "source": "./superpowers/superpowers-base",
  "description": "Superpowers persona base — shared skills every persona needs."
}
```

- [ ] `plugin/.claude-plugin/marketplace.json`의 `plugins` 배열에 위 항목을 추가한다.
  (배열의 마지막 기존 항목 뒤, 닫는 `]` 앞에 삽입. 콤마·들여쓰기는 기존 항목과 동일하게 맞춘다.)

- [ ] JSON 유효성 확인:
  ```bash
  python -c "import json; f=open('plugin/.claude-plugin/marketplace.json'); data=json.load(f); print('plugins count:', len(data['plugins'])); print('OK')"
  # 기대: plugins count: 10  (기존 9 + 1)
  ```

- [ ] 커밋:
  ```bash
  git add plugin/.claude-plugin/marketplace.json
  git commit -m "feat: marketplace.json에 superpowers-base 등록"
  ```

---

## Task 5: 검증

- [ ] 플러그인 디렉토리 구조 전체 확인:
  ```bash
  ls -R "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-base/"
  ```
  기대 구조:
  ```
  .claude-plugin/plugin.json
  README.md
  hooks/hooks.json
  hooks/run-hook.cmd
  hooks/session-start
  skills/using-superpowers/SKILL.md
  skills/using-superpowers/references/  (하위 파일 포함)
  skills/verification-before-completion/SKILL.md
  skills/writing-skills/SKILL.md
  skills/writing-skills/anthropic-best-practices.md
  skills/writing-skills/examples/       (하위 파일 포함)
  skills/writing-skills/graphviz-conventions.dot
  skills/writing-skills/persuasion-principles.md
  skills/writing-skills/render-graphs.js
  skills/writing-skills/testing-skills-with-subagents.md
  ```

- [ ] `plugin.json` 파싱 확인:
  ```bash
  python -c "
  import json
  with open('plugin/superpowers/superpowers-base/.claude-plugin/plugin.json') as f:
      d = json.load(f)
  assert d['name'] == 'superpowers-base', 'name mismatch'
  assert d['version'] == '0.1.0', 'version mismatch'
  print('plugin.json OK:', d)
  "
  ```

- [ ] `marketplace.json` 파싱 및 항목 확인:
  ```bash
  python -c "
  import json
  with open('plugin/.claude-plugin/marketplace.json') as f:
      data = json.load(f)
  names = [p['name'] for p in data['plugins']]
  assert 'superpowers-base' in names, 'superpowers-base not in marketplace'
  entry = next(p for p in data['plugins'] if p['name'] == 'superpowers-base')
  assert entry['source'] == './superpowers/superpowers-base', 'source path wrong'
  print('marketplace.json OK, plugins:', names)
  "
  ```

- [ ] pytest 마켓플레이스 테스트 실행:
  ```bash
  uv run --extra dev python -m pytest tests/test_plugin_marketplace.py -q
  ```
  기대: 전체 PASSED, 실패 없음.

- [ ] (전체 이상 없으면) 최종 확인 커밋 — 변경사항이 없으면 생략:
  ```bash
  git status
  # 변경사항 있으면: git add <파일> && git commit -m "chore: superpowers-base 검증 완료"
  ```

---

## Self-Review

구현 완료 후 아래 항목을 점검한다:

1. **hooks 경로 무결성**: `hooks/session-start`가 `${PLUGIN_ROOT}/skills/using-superpowers/SKILL.md`를 읽는 경로가 실제 레이아웃과 일치하는가 — `session-start` 스크립트의 `dirname` 기반 경로 계산이 새 위치에서도 올바른가.
2. **verbatim 복사 확인**: `cp -r`로 복사한 스킬 디렉토리에 원본 대비 누락 파일이 없는가 (`writing-skills` 보조 파일 7종 포함).
3. **marketplace.json JSON 유효성**: 항목 추가 후 JSON 파싱 오류가 없는가.
4. **pytest 통과**: `tests/test_plugin_marketplace.py`가 실패 없이 통과하는가.
5. **`dependencies` 없음 확인**: `plugin.json`에 `dependencies` 키가 없는가 — `superpowers-base`는 의존 대상이지 의존하지 않는다.
6. **persona 스킬 없음 확인**: `skills/persona/` 디렉토리가 없는가 — `superpowers-base`는 라이브러리이므로 persona 스킬을 갖지 않는다.
