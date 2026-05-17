# 팀 대시보드 Plan 1 — 서버 측 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AgentAgora 서버가 팀 현황 대시보드(HTML 페이지 + JSON 데이터 엔드포인트)를 서빙한다.

**Architecture:** 신규 `dashboard_routes.py`가 `GET /dashboard`(HTML)·`GET /dashboard/data`(JSON) Starlette 라우트를 등록한다(`admin_routes.py` 패턴). `dashboard.html`은 자기완결형 HTML+CSS+JS+SVG — `/dashboard/data`를 3초 폴링해 인스턴스·봇·대화·comm-matrix 방향 그래프를 렌더. localhost 전용·토큰 없음. `__main__.py`가 `admin_routes.maybe_register` 옆에서 대시보드를 등록한다.

**Tech Stack:** Python 3.13, Starlette, pytest. 테스트는 `.venv\Scripts\python.exe -m pytest`. 셸 PowerShell. Pyright 무시(pytest 정답).

spec: `docs/superpowers/specs/2026-05-17-team-dashboard-design.md`.

---

### Task 1: `dashboard_routes.py` — 데이터 조립 + 라우트

**Files:**
- Create: `src/agent_agora/dashboard_routes.py`
- Test: `tests/test_dashboard_routes.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_dashboard_routes.py`:

```python
"""팀 대시보드 라우트 테스트."""
from __future__ import annotations

import json

from starlette.applications import Starlette
from starlette.testclient import TestClient

from agent_agora.bot_registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from agent_agora.dashboard_routes import register, build_dashboard_data
from _helpers import make_schema_registry


def _deps(tmp_path):
    reg = InstanceRegistry()
    reg.register("sess-Inst1", "Inst1", role="orchestrator", description="PM")
    reg.register("sess-Coder1", "Coder1", role="coder", description="코더")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    return reg, persistence


def test_build_dashboard_data_shape(tmp_path):
    reg, persistence = _deps(tmp_path)
    bot_registry = BotRegistry()
    cm = CommMatrix()
    queue = AsyncWriteQueue(persistence)
    d = Dispatcher(reg, persistence, queue, schema_registry=make_schema_registry(),
                   bot_registry=bot_registry, comm_matrix=cm)
    data = build_dashboard_data(
        dispatcher=d, instance_registry=reg, bot_registry=bot_registry, comm_matrix=cm)
    assert set(data) == {"generated_at", "summary", "instances", "bots",
                         "conversations", "comm_matrix"}
    assert data["summary"]["instances"] == 2
    assert {i["instance_id"] for i in data["instances"]} == {"Inst1", "Coder1"}
    assert data["comm_matrix"]["active"] is False
    inst = next(i for i in data["instances"] if i["instance_id"] == "Inst1")
    assert set(inst) >= {"instance_id", "role", "inbox_depth", "in_flight",
                         "last_seen_at", "accepting"}


def test_data_route_returns_json(tmp_path):
    reg, persistence = _deps(tmp_path)
    bot_registry = BotRegistry()
    cm = CommMatrix()
    queue = AsyncWriteQueue(persistence)
    d = Dispatcher(reg, persistence, queue, schema_registry=make_schema_registry(),
                   bot_registry=bot_registry, comm_matrix=cm)
    app = Starlette()
    register(app, dispatcher=d, instance_registry=reg,
             bot_registry=bot_registry, comm_matrix=cm)
    r = TestClient(app).get("/dashboard/data")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["instances"] == 2


def test_dashboard_route_serves_html(tmp_path):
    reg, persistence = _deps(tmp_path)
    bot_registry = BotRegistry()
    cm = CommMatrix()
    queue = AsyncWriteQueue(persistence)
    d = Dispatcher(reg, persistence, queue, schema_registry=make_schema_registry(),
                   bot_registry=bot_registry, comm_matrix=cm)
    app = Starlette()
    register(app, dispatcher=d, instance_registry=reg,
             bot_registry=bot_registry, comm_matrix=cm)
    r = TestClient(app).get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "/dashboard/data" in r.text  # JS가 폴링하는 엔드포인트
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dashboard_routes.py -q`
Expected: FAIL — `dashboard_routes` 모듈 없음.

- [ ] **Step 3: `dashboard_routes.py` 작성**

`src/agent_agora/dashboard_routes.py`:

```python
"""팀 현황 대시보드 HTTP 라우트 — GET /dashboard(HTML) + GET /dashboard/data(JSON).

읽기 전용 운영 데이터. localhost 전용·토큰 없음 — 서버의 127.0.0.1 바인딩에 의존.
향후 인증이 필요하면 register에 token 인자를 더하고 핸들러 앞에 게이트를 끼운다.
spec: docs/superpowers/specs/2026-05-17-team-dashboard-design.md.
"""
from __future__ import annotations

import datetime
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

_DASHBOARD_HTML = Path(__file__).with_name("dashboard.html")


def build_dashboard_data(*, dispatcher, instance_registry, bot_registry, comm_matrix) -> dict:
    """팀 현황 JSON 스냅샷을 조립한다."""
    instances = instance_registry.list_instances()
    peek = dispatcher.peek([i.instance_id for i in instances])
    inst_rows = []
    total_inbox = 0
    for info in instances:
        p = peek.get(info.instance_id, {})
        depth = p.get("queue_depth") or 0
        total_inbox += depth
        inst_rows.append({
            "instance_id": info.instance_id,
            "role": info.role,
            "description": info.description,
            "inbox_depth": depth,
            "in_flight": p.get("in_flight") or 0,
            "last_seen_at": info.last_seen_at,
            "accepting": info.accepting,
        })
    bot_rows = [
        {"instance_id": b.instance_id, "bot_mode": b.bot_mode,
         "subscribe_schemas": list(b.subscribe_schemas)}
        for b in bot_registry.list_bots()
    ]
    convs = dispatcher.conversations_list(limit=50)
    open_convs = sum(1 for c in convs if c.get("status") == "open")
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "summary": {
            "instances": len(inst_rows),
            "bots": len(bot_rows),
            "open_conversations": open_convs,
            "total_inbox_depth": total_inbox,
        },
        "instances": inst_rows,
        "bots": bot_rows,
        "conversations": convs,
        "comm_matrix": {"active": comm_matrix.active, "matrix": comm_matrix.snapshot()},
    }


def register(app: Starlette, *, dispatcher, instance_registry, bot_registry, comm_matrix) -> None:
    """app에 대시보드 라우트 2개를 등록한다."""

    async def data_endpoint(request: Request) -> JSONResponse:
        return JSONResponse(build_dashboard_data(
            dispatcher=dispatcher, instance_registry=instance_registry,
            bot_registry=bot_registry, comm_matrix=comm_matrix))

    async def page_endpoint(request: Request) -> HTMLResponse:
        return HTMLResponse(_DASHBOARD_HTML.read_text(encoding="utf-8"))

    app.router.routes.append(Route("/dashboard", page_endpoint, methods=["GET"]))
    app.router.routes.append(Route("/dashboard/data", data_endpoint, methods=["GET"]))
```

`conversations_list`가 반환하는 키(`conversation_id`·`kind`·`status`·`started_at`·
`last_message_at`·`message_count`)는 `dispatcher.py`(현 `ConversationStore.list_conversations`)
구현 그대로 통과시킨다.

- [ ] **Step 4: 임시 빈 `dashboard.html` (Task 2에서 채움)**

`GET /dashboard` 테스트가 `_DASHBOARD_HTML.read_text()`를 호출하므로, Task 2 전까지
파일이 있어야 한다. `src/agent_agora/dashboard.html`을 최소 내용으로 생성한다:

```html
<!doctype html><meta charset="utf-8"><title>AgentAgora</title>
<!-- polls /dashboard/data --><body>dashboard placeholder</body>
```

(Task 2에서 전체 대시보드로 교체. 이 최소 파일도 `/dashboard/data` 문자열을 포함해
Step 1의 `test_dashboard_route_serves_html`를 통과시킨다.)

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dashboard_routes.py -q`
Expected: 3개 PASS.

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/dashboard_routes.py src/agent_agora/dashboard.html tests/test_dashboard_routes.py
git commit -m "feat: dashboard_routes — /dashboard·/dashboard/data 라우트"
```

---

### Task 2: `dashboard.html` — 자기완결 대시보드 UI

**Files:**
- Modify: `src/agent_agora/dashboard.html` (Task 1의 placeholder를 전체 UI로 교체)

- [ ] **Step 1: `dashboard.html` 전체 작성**

`src/agent_agora/dashboard.html`을 아래 전체 내용으로 교체한다 — 자기완결형(외부
CDN·라이브러리 없음), `/dashboard/data`를 3초 폴링, comm-matrix는 SVG 방향 그래프:

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>AgentAgora — 팀 현황</title>
<style>
  body { font: 13px/1.5 system-ui, sans-serif; background:#1a1a2e; color:#e8e8e8; margin:0; padding:16px; }
  h2 { font-size:14px; color:#9aa; margin:18px 0 6px; text-transform:uppercase; letter-spacing:.05em; }
  #conn { float:right; font-size:12px; padding:2px 8px; border-radius:4px; }
  .ok { background:#1b5e20; } .bad { background:#7f1d1d; }
  table { border-collapse:collapse; width:100%; }
  th,td { text-align:left; padding:4px 8px; border-bottom:1px solid #33334d; }
  th { color:#9aa; font-weight:600; }
  .summary { display:flex; gap:24px; margin:8px 0; }
  .summary div { background:#252542; padding:8px 14px; border-radius:6px; }
  .summary b { font-size:20px; display:block; }
  .hot { color:#ff9; font-weight:700; }
  svg { background:#252542; border-radius:6px; }
  .node { fill:#3d3d6b; stroke:#8888c0; }
  .nodelabel { fill:#e8e8e8; font-size:11px; text-anchor:middle; }
  .edge { stroke:#7a7ad0; fill:none; }
  .edgelabel { fill:#bbf; font-size:10px; text-anchor:middle; }
</style>
</head>
<body>
<span id="conn" class="bad">연결 중…</span>
<h1 style="font-size:18px;margin:0">AgentAgora 팀 현황</h1>

<div class="summary" id="summary"></div>

<h2>인스턴스</h2>
<table><thead><tr><th>ID</th><th>role</th><th>인박스</th><th>in-flight</th>
<th>last seen</th><th>accepting</th></tr></thead><tbody id="instances"></tbody></table>

<h2>봇</h2>
<table><thead><tr><th>ID</th><th>mode</th><th>구독 스키마</th></tr></thead>
<tbody id="bots"></tbody></table>

<h2>대화</h2>
<table><thead><tr><th>conversation</th><th>kind</th><th>status</th>
<th>메시지</th><th>last message</th></tr></thead><tbody id="convs"></tbody></table>

<h2>comm-matrix</h2>
<div id="commwrap"></div>

<script>
const $ = id => document.getElementById(id);
function esc(s){ return String(s==null?"":s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }

function render(d){
  $("summary").innerHTML =
    `<div><b>${d.summary.instances}</b>인스턴스</div>` +
    `<div><b>${d.summary.bots}</b>봇</div>` +
    `<div><b>${d.summary.open_conversations}</b>열린 대화</div>` +
    `<div><b>${d.summary.total_inbox_depth}</b>총 인박스</div>`;
  $("instances").innerHTML = d.instances.map(i =>
    `<tr><td>${esc(i.instance_id)}</td><td>${esc(i.role)}</td>` +
    `<td class="${i.inbox_depth>0?'hot':''}">${i.inbox_depth}</td>` +
    `<td>${i.in_flight}</td><td>${esc(i.last_seen_at)}</td>` +
    `<td>${i.accepting?'예':'아니오'}</td></tr>`).join("") ||
    `<tr><td colspan=6>(없음)</td></tr>`;
  $("bots").innerHTML = d.bots.map(b =>
    `<tr><td>${esc(b.instance_id)}</td><td>${esc(b.bot_mode)}</td>` +
    `<td>${esc((b.subscribe_schemas||[]).join(", "))}</td></tr>`).join("") ||
    `<tr><td colspan=3>(없음)</td></tr>`;
  $("convs").innerHTML = d.conversations.map(c =>
    `<tr><td>${esc(c.conversation_id)}</td><td>${esc(c.kind)}</td>` +
    `<td>${esc(c.status)}</td><td>${c.message_count}</td>` +
    `<td>${esc(c.last_message_at)}</td></tr>`).join("") ||
    `<tr><td colspan=5>(없음)</td></tr>`;
  renderGraph(d.comm_matrix);
}

function renderGraph(cm){
  const wrap = $("commwrap");
  if(!cm.active){ wrap.innerHTML = "<p>비활성 — all-allow (모든 워커가 서로 dispatch 가능)</p>"; return; }
  const nodes = Object.keys(cm.matrix);
  if(nodes.length===0){ wrap.innerHTML = "<p>(빈 매트릭스)</p>"; return; }
  const W=520, H=420, cx=W/2, cy=H/2, R=Math.min(cx,cy)-60;
  const pos = {};
  nodes.forEach((n,i)=>{ const a=2*Math.PI*i/nodes.length - Math.PI/2;
    pos[n]={x:cx+R*Math.cos(a), y:cy+R*Math.sin(a)}; });
  let edges = "";
  // matrix[to][from] = weight; edge from->to when weight>0, from!=to
  for(const to of nodes){ for(const from of Object.keys(cm.matrix[to]||{})){
    const w = cm.matrix[to][from];
    if(w>0 && from!==to && pos[from] && pos[to]){
      const a=pos[from], b=pos[to];
      // 노드 반지름(18)만큼 끝점을 당겨 화살표가 노드에 닿게
      const dx=b.x-a.x, dy=b.y-a.y, len=Math.hypot(dx,dy)||1;
      const ux=dx/len, uy=dy/len;
      const x1=a.x+ux*20, y1=a.y+uy*20, x2=b.x-ux*22, y2=b.y-uy*22;
      // 양방향 겹침 방지로 살짝 휜 quadratic path
      const mx=(x1+x2)/2 - uy*18, my=(y1+y2)/2 + ux*18;
      edges += `<path class="edge" marker-end="url(#arr)" `+
               `d="M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}"/>`+
               `<text class="edgelabel" x="${mx}" y="${my}">${w}</text>`;
    }
  }}
  const circles = nodes.map(n=>
    `<circle class="node" cx="${pos[n].x}" cy="${pos[n].y}" r="18"/>`+
    `<text class="nodelabel" x="${pos[n].x}" y="${pos[n].y+4}">${esc(n)}</text>`).join("");
  wrap.innerHTML =
    `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`+
    `<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" `+
    `markerWidth="7" markerHeight="7" orient="auto-start-reverse">`+
    `<path d="M0 0 L10 5 L0 10 z" fill="#7a7ad0"/></marker></defs>`+
    edges + circles + `</svg>`;
}

async function poll(){
  try{
    const r = await fetch("/dashboard/data", {cache:"no-store"});
    if(!r.ok) throw new Error(r.status);
    render(await r.json());
    $("conn").textContent="연결됨"; $("conn").className="ok";
  }catch(e){
    $("conn").textContent="연결 끊김"; $("conn").className="bad";
  }
}
poll();
setInterval(poll, 3000);
</script>
</body>
</html>
```

- [ ] **Step 2: 라우트 테스트 재확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dashboard_routes.py -q`
Expected: 3개 PASS — `test_dashboard_route_serves_html`가 전체 HTML에서도 `/dashboard/data` 문자열을 찾는다(JS의 `fetch("/dashboard/data")`).

- [ ] **Step 3: HTML 유효성 간이 확인**

Run: `.venv\Scripts\python.exe -c "t=open('src/agent_agora/dashboard.html',encoding='utf-8').read(); assert t.lstrip().startswith('<!doctype'); assert 'renderGraph' in t and 'setInterval' in t; print('ok')"`
Expected: `ok`

- [ ] **Step 4: 커밋**

```bash
git add src/agent_agora/dashboard.html
git commit -m "feat: dashboard.html — 자기완결 대시보드 UI + comm-matrix 방향 그래프"
```

---

### Task 3: `__main__.py` 와이어링 + 패키지 데이터

**Files:**
- Modify: `src/agent_agora/__main__.py`
- Modify: `pyproject.toml` (필요 시 — `dashboard.html` 패키지 데이터 포함)

- [ ] **Step 1: `__main__.py`에 대시보드 등록**

`src/agent_agora/__main__.py`의 `admin_routes.maybe_register` 블록(현 193~198행) 바로
다음에 대시보드 등록을 추가한다:

```python
        from agent_agora.dashboard_routes import register as register_dashboard
        register_dashboard(
            starlette_app,
            dispatcher=dispatcher,
            instance_registry=instance_registry,
            bot_registry=bot_registry,
            comm_matrix=mcp._agora_comm_matrix,  # type: ignore[attr-defined]
        )
        print(f"  Dashboard: GET /dashboard")
```

`dispatcher`·`instance_registry`·`bot_registry`가 그 지점 스코프에 있는 지역 변수가
아니면, `admin_routes`가 `mcp._agora_comm_matrix`를 쓰듯 `create_agora_app`이 설정한
`mcp._agora_*` 속성을 쓴다 — `server.py`의 `create_agora_app`에서 정확한 속성명
(`_agora_dispatcher`·`_agora_instance_registry`·`_agora_bot_registry` 등)을 확인해
맞춘다.

- [ ] **Step 2: `dashboard.html` 패키지 데이터 포함 확인**

`dashboard.html`은 런타임에 `Path(__file__).with_name("dashboard.html")`로 읽힌다.
`pyproject.toml`의 패키징 설정이 `.html`을 패키지 데이터로 포함하는지 확인한다 —
`[tool.setuptools.package-data]` 또는 `include-package-data` 설정. 누락 시
`agent_agora` 패키지에 `*.html`을 포함하도록 추가한다(개발 모드 `pip install -e .`에선
소스가 직접 읽히므로 무관하나, 정식 설치 대비).

- [ ] **Step 3: 전체 스위트 회귀 + 서버 기동 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS (기존 + dashboard 3개).

Run: `.venv\Scripts\python.exe -c "import tempfile,pathlib; from agent_agora.__main__ import _build_app; d=pathlib.Path(tempfile.mkdtemp())/'.agentagora'; d.mkdir(); _build_app(agora_dir=d, port=0); print('build ok')"`
Expected: `build ok` — 앱 구성이 깨지지 않음. (`_build_app` 시그니처가 다르면 맞춰 호출.)

- [ ] **Step 4: 커밋**

```bash
git add src/agent_agora/__main__.py pyproject.toml
git commit -m "feat: 대시보드 라우트를 서버 앱에 등록"
```

---

## 완료 기준

- `GET /dashboard`가 자기완결 HTML을, `GET /dashboard/data`가 팀 현황 JSON을 반환한다.
- 대시보드가 인스턴스·봇·대화·comm-matrix 방향 그래프를 3초 폴링으로 렌더한다.
- comm-matrix 그래프는 SVG·바닐라 JS·읽기 전용.
- 전체 테스트 스위트 통과 + 서버 기동 정상.
