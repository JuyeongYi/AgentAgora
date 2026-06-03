// 플로우 뷰 — in-flight expect_result 메시지의 source→target 흐름.
// comm-matrix(정적 ACL)와 상보적: '지금 누가 누구의 응답을 기다리는가'를 동적으로.
// 새 라이브러리 없이 dashboard.js renderCommMatrix의 inline-SVG 패턴을 확장.
window.agoraFlow = (function() {
  function escape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }

  function render(data) {
    const wrap = document.getElementById('flow-view');
    if (!wrap) return;
    const instances = data.instances || [];
    const inFlight = data.in_flight || [];

    // 노드 = 등록 인스턴스 ∪ in_flight에 등장하는 source/target(operator pseudo 포함).
    const meta = {};
    instances.forEach(i => { meta[i.instance_id] = i; });
    const nodeSet = new Set(instances.map(i => i.instance_id));
    inFlight.forEach(e => { nodeSet.add(e.source); nodeSet.add(e.target); });
    const nodes = Array.from(nodeSet);

    if (nodes.length === 0) {
      wrap.innerHTML = '<h3>플로우</h3><p>(등록된 인스턴스 없음)</p>';
      return;
    }

    const W = 520, H = 440, cx = W / 2, cy = H / 2 + 10, R = Math.min(cx, cy) - 70;
    const pos = {};
    nodes.forEach((n, i) => {
      const a = 2 * Math.PI * i / nodes.length - Math.PI / 2;
      pos[n] = {x: cx + R * Math.cos(a), y: cy + R * Math.sin(a)};
    });

    // in-flight 엣지 — source→target 펄스 점선, 라벨에 count.
    let edges = '';
    inFlight.forEach(e => {
      const a = pos[e.source], b = pos[e.target];
      if (!a || !b || e.source === e.target) return;
      const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
      const ux = dx / len, uy = dy / len;
      const x1 = a.x + ux * 22, y1 = a.y + uy * 22;
      const x2 = b.x - ux * 24, y2 = b.y - uy * 24;
      const mx = (x1 + x2) / 2 - uy * 16, my = (y1 + y2) / 2 + ux * 16;
      edges += `<path class="edge-inflight" marker-end="url(#flowarr)" `
             + `d="M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}"/>`
             + `<text class="edgelabel" x="${mx}" y="${my}">${escape(String(e.count))}</text>`;
    });

    // 노드 + inbox/in-flight 배지.
    const circles = nodes.map(n => {
      const m = meta[n] || {};
      const depth = m.inbox_depth || 0;
      const inf = m.in_flight || 0;
      const badge = (depth || inf)
        ? `<text class="flow-badge" x="${pos[n].x}" y="${pos[n].y + 30}">`
          + `${escape('▦' + depth + ' ⤣' + inf)}</text>`
        : '';
      return `<circle class="node" cx="${pos[n].x}" cy="${pos[n].y}" r="20"/>`
           + `<text class="nodelabel" x="${pos[n].x}" y="${pos[n].y + 4}">${escape(n)}</text>`
           + badge;
    }).join('');

    const note = inFlight.length === 0
      ? '<p class="flow-note">대기 중인 expect_result 메시지 없음</p>'
      : `<p class="flow-note">in-flight expect_result ${inFlight.length}개 흐름 (점선=응답 대기)</p>`;

    wrap.innerHTML = '<h3>플로우 — in-flight</h3>'
      + `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`
      + '<defs><marker id="flowarr" viewBox="0 0 10 10" refX="9" refY="5" '
      + 'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
      + '<path d="M0 0 L10 5 L0 10 z" fill="#f5a623"/></marker></defs>'
      + edges + circles + '</svg>' + note;
  }

  return {render};
})();
