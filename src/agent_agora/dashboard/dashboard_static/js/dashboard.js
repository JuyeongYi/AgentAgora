// 메인 hydration + 레이아웃 조립.
(async function() {
  document.getElementById('logout').onclick = () => window.agoraLogin.logout();

  await window.agoraLogin.init(async (user) => {
    // 인증 완료 → 초기 hydration + SSE 연결
    try {
      const snap = await window.agoraApi.get('/dashboard/data');
      renderSnapshot(snap);
    } catch (e) {
      console.error('초기 hydration 실패', e);
    }

    window.agoraStream.on('data_snapshot', (evt) => renderSnapshot(evt.payload));
    window.agoraStream.on('instance_registered', () => refresh());
    window.agoraStream.on('instance_unregistered', () => refresh());
    window.agoraStream.on('message_dispatched', () => refresh());
    window.agoraStream.on('deadline_expired', (evt) => { console.warn('deadline expired', evt); refresh(); });
    window.agoraStream.on('operator_inbox_message', (evt) => window.agoraInbox.push(evt));
    window.agoraInbox.refresh();
    window.agoraStream.connect();
  });

  function renderSnapshot(d) {
    renderSummary(d.summary);
    renderInstances(d.instances);
    renderConversations(d.conversations);
    renderBots(d.bots);
    renderCommMatrix(d.comm_matrix);
    if (window.agoraFlow) window.agoraFlow.render(d);
    if (d.server) window.agoraHealth.update(d.server);
  }

  function renderSummary(s) {
    document.getElementById('summary-cards').innerHTML =
      `<div class="card"><b>${s.instances}</b>인스턴스</div>` +
      `<div class="card"><b>${s.bots}</b>봇</div>` +
      `<div class="card"><b>${s.open_conversations}</b>열린 대화</div>` +
      `<div class="card"><b>${s.total_inbox_depth}</b>총 인박스</div>`;
  }

  function renderInstances(rows) {
    // Tabulator 인스턴스 (재사용 패턴 — 이미 만들어졌으면 setData)
    if (!window._instTab) {
      window._instTab = new Tabulator('#instances-table', {
        layout: 'fitColumns', height: 250,
        columns: [
          {title: 'ID', field: 'instance_id', headerFilter: true},
          {title: 'role', field: 'role', headerFilter: true},
          {title: '인박스', field: 'inbox_depth', formatter: hotIfPos},
          {title: 'in-flight', field: 'in_flight'},
          {title: 'last seen', field: 'last_seen_at'},
          {title: 'accepting', field: 'accepting',
           formatter: c => c.getValue() ? '예' : '아니오'},
        ],
        rowClick: (e, row) => window.agoraDrilldown.openInstanceInbox(row.getData().instance_id),
      });
    }
    window._instTab.replaceData(rows);
  }

  function hotIfPos(cell) {
    const v = cell.getValue();
    if (v > 0) cell.getElement().classList.add('hot');
    return v;
  }

  function renderConversations(rows) {
    if (!window._convTab) {
      window._convTab = new Tabulator('#conversations-table', {
        layout: 'fitColumns', height: 250,
        columns: [
          {title: 'conversation', field: 'conversation_id', headerFilter: true},
          {title: 'kind', field: 'kind'},
          {title: 'status', field: 'status', headerFilter: true},
          {title: '메시지', field: 'message_count'},
          {title: 'last message', field: 'last_message_at'},
        ],
        rowClick: (e, row) => window.agoraDrilldown.openConversation(row.getData().conversation_id),
      });
    }
    window._convTab.replaceData(rows);
  }

  function renderBots(rows) {
    if (!window._botTab) {
      window._botTab = new Tabulator('#bots-table', {
        layout: 'fitColumns', height: 150,
        columns: [
          {title: 'ID', field: 'instance_id'},
          {title: 'mode', field: 'bot_mode'},
          {title: '구독 스키마', field: 'subscribe_schemas',
           formatter: c => (c.getValue() || []).join(', ')},
        ],
      });
    }
    window._botTab.replaceData(rows);
  }

  function renderCommMatrix(cm) {
    // 기존 dashboard.html(prev) 의 renderGraph 함수 — 원형 layout SVG.
    const wrap = document.getElementById('comm-matrix');
    if (!cm.active) { wrap.innerHTML = '<p>비활성 — all-allow (모든 워커가 서로 dispatch 가능)</p>'; return; }
    const nodes = Object.keys(cm.matrix);
    if (nodes.length === 0) { wrap.innerHTML = '<p>(빈 매트릭스)</p>'; return; }
    const W = 520, H = 420, cx = W/2, cy = H/2, R = Math.min(cx, cy) - 60;
    const pos = {};
    nodes.forEach((n, i) => {
      const a = 2 * Math.PI * i / nodes.length - Math.PI / 2;
      pos[n] = {x: cx + R * Math.cos(a), y: cy + R * Math.sin(a)};
    });
    let edges = '';
    // matrix[to][from] = weight; edge from->to when weight>0, from!=to
    for (const to of nodes) {
      for (const from of Object.keys(cm.matrix[to] || {})) {
        const w = cm.matrix[to][from];
        if (w > 0 && from !== to && pos[from] && pos[to]) {
          const a = pos[from], b = pos[to];
          const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
          const ux = dx / len, uy = dy / len;
          const x1 = a.x + ux * 20, y1 = a.y + uy * 20;
          const x2 = b.x - ux * 22, y2 = b.y - uy * 22;
          const mx = (x1 + x2) / 2 - uy * 18, my = (y1 + y2) / 2 + ux * 18;
          edges += `<path class="edge" marker-end="url(#arr)" d="M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}"/>` +
                   `<text class="edgelabel" x="${mx}" y="${my}">${escape(String(w))}</text>`;
        }
      }
    }
    const circles = nodes.map(n =>
      `<circle class="node" cx="${pos[n].x}" cy="${pos[n].y}" r="18"/>` +
      `<text class="nodelabel" x="${pos[n].x}" y="${pos[n].y + 4}">${escape(n)}</text>`).join('');
    // 라우팅 루프(SCC/self-loop) 진단 — 거부 아님, 정상 반복 워크플로일 수 있음.
    const cyc = cm.cycles || [];
    const cyclesNote = cyc.length
      ? `<p class="cycles-note">⚠ 라우팅 루프 ${cyc.length}개: ${
          cyc.map(c => escape(c.join(' → '))).join(' / ')} (진단 — 정상 반복일 수 있음)</p>`
      : '';
    wrap.innerHTML =
      `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">` +
      `<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">` +
      `<path d="M0 0 L10 5 L0 10 z" fill="#7a7ad0"/></marker></defs>` +
      edges + circles + `</svg>` + cyclesNote;
  }

  function escape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  async function refresh() {
    try {
      const snap = await window.agoraApi.get('/dashboard/data');
      renderSnapshot(snap);
    } catch (e) { console.error('refresh failed', e); }
  }

  window._refresh = refresh;
})();
