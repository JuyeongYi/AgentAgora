# AgentAgora 플러그인 마켓플레이스

이 디렉토리(`plugin/`)는 AgentAgora의 Claude Code 플러그인 마켓플레이스다. 매니페스트는 [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json)이고, 아래 9개 플러그인 소스가 모두 이 디렉토리 안에 상대경로로 들어 있어 `plugin/` 서브트리만으로 자기완결적이다.

## 플러그인

| 플러그인 | 용도 |
|---|---|
| `cc-agora` | 통신 코어 — 워커 간 메시지 dispatch·broadcast·종결 슬래시와 운용 규칙. 모든 세션에 필요. |
| `cc-agora-ops` | 운영자 도구 — 워커 spawn, 팀 일괄 설정, 통신 매트릭스, 대시보드. |
| `cc-agora-coder` | 코더 페르소나 — task를 최소·검토 가능한 코드 변경으로 구현. |
| `cc-agora-reviewer` | 리뷰어 페르소나 — diff의 정확성·가독성·테스트 커버리지 검토. |
| `cc-agora-tester` | 테스터 페르소나 — 황금 경로·엣지·회귀 시나리오 테스트 작성·실행. |
| `cc-agora-writer` | 문서 작성자 페르소나 — 구체적 예시가 있는 문서·산문. |
| `cc-agora-planner` | 플래너 페르소나 — 목표를 의존성·수용 기준이 있는 순서화된 task로 분해. |
| `cc-agora-orchestrator` | 오케스트레이터 페르소나 — 사용자 요청을 워커에 위임하는 팀 PM. |
| `cc-agora-general` | 제너럴리스트 폴백 페르소나 — 직접 처리하거나 전문가에게 forward. |

`cc-agora`는 모든 세션에 필요하다. 운영자 세션에는 `cc-agora-ops`를, 워커에 페르소나를 부여할 때는 해당 `cc-agora-<role>` 플러그인을 함께 설치한다.

## 설치

이 마켓플레이스는 `marketplace.json`이 저장소 루트가 아니라 `plugin/` 서브디렉토리에 있으므로 `/plugin marketplace add`의 git-URL·`owner/repo` 형식으로는 등록할 수 없다 — git-URL 형식은 저장소 루트에서만 매니페스트를 찾고, `owner/repo` shorthand는 github.com 호스트 전용이다. 대신 **`plugin/` 디렉토리를 로컬 경로 마켓플레이스로 등록**한다. 로컬 경로 방식만이 서브디렉토리를 직접 가리킬 수 있다.

### 1) 저장소 받기

`plugin/` 서브트리만 있으면 되므로 sparse partial clone으로 충분하다(저장소가 작아 전체 클론도 무방하다):

```
git clone --filter=blob:none --sparse <repo-url> AgentAgora
git -C AgentAgora sparse-checkout set plugin
```

`<repo-url>`은 저장소 호스트에 맞는 git URL이다(예: `git@<git-host>:<org>/AgentAgora.git`). `--filter=blob:none --sparse`로 blob을 지연 fetch하고, `sparse-checkout set plugin`이 `plugin/` 서브트리만 워킹 트리에 채운다.

### 2) 마켓플레이스 등록

두 방법 중 하나를 쓴다.

*대화형* — Claude Code에서 클론한 `plugin/` 디렉토리를 마켓플레이스로 추가한 뒤 `/plugin` 메뉴로 플러그인을 설치한다. 가리키는 경로는 저장소 루트가 아니라 `.claude-plugin/`을 직접 담은 `plugin/` 디렉토리다.

*선언형* — `.claude/settings.json`(또는 `settings.local.json`)에 등록한다:

```json
{
  "extraKnownMarketplaces": {
    "agentagora": {
      "source": "directory",
      "path": "C:/path/to/AgentAgora/plugin"
    }
  },
  "enabledPlugins": {
    "cc-agora@agentagora": true
  }
}
```

`path`는 클론한 `plugin/` 디렉토리의 절대경로다 — Windows에서도 forward slash로 쓴다. `enabledPlugins`에는 설치할 플러그인을 `<plugin>@agentagora`로 나열한다(운영자 세션 `cc-agora-ops@agentagora`, 워커 `cc-agora-<role>@agentagora`).

### 3) 업데이트

로컬 경로 마켓플레이스는 그 경로에서 live로 읽힌다. 클론 디렉토리에서 `git pull`하면 재등록 없이 최신 플러그인이 반영된다.

---

전체 저장소가 있으면 [`docs/plugins.md`](../docs/plugins.md)에 각 플러그인의 슬래시 명령, `agora-protocol` 운용 규칙, 워커 생성 경로(`agora-spawn` / `agora-design-worker` / `agora-setup`)가 상세히 정리돼 있다.
