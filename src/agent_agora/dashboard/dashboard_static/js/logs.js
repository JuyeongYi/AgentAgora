// 로그 패널 — 최근 WARNING+ 운영 이벤트 뷰. /dashboard/logs 소비 (read-only).
window.agoraLogs = (function() {
  const modal = () => document.getElementById('logs-modal');
  let currentLevel = '';  // '' = all(WARNING+), 'ERROR' 등

  async function fetchLogs() {
    const q = currentLevel ? `?min_level=${encodeURIComponent(currentLevel)}` : '';
    const data = await window.agoraApi.get('/dashboard/logs' + q).catch(() => ({logs: []}));
    return data.logs || [];
  }

  async function open() {
    modal().innerHTML = `
      <div class="modal-card">
        <h2>로그 <span id="logs-count"></span></h2>
        <div class="logs-toolbar">
          <label>최소 레벨
            <select id="logs-level">
              <option value="">WARNING+</option>
              <option value="ERROR">ERROR+</option>
              <option value="CRITICAL">CRITICAL</option>
            </select>
          </label>
          <button id="logs-refresh">새로고침</button>
        </div>
        <div id="logs-body"><em>불러오는 중…</em></div>
        <button id="logs-close">닫기</button>
      </div>`;
    modal().classList.remove('hidden');
    document.getElementById('logs-close').onclick = close;
    document.getElementById('logs-refresh').onclick = render;
    const sel = document.getElementById('logs-level');
    sel.value = currentLevel;
    sel.onchange = () => { currentLevel = sel.value; render(); };
    await render();
  }

  async function render() {
    const logs = await fetchLogs();
    const count = document.getElementById('logs-count');
    if (count) count.textContent = `(${logs.length})`;
    const wrap = document.getElementById('logs-body');
    wrap.innerHTML = '';
    if (!logs.length) {
      const em = document.createElement('em');
      em.textContent = '기록된 이벤트 없음';
      wrap.appendChild(em);
      return;
    }
    const tbl = document.createElement('table');
    tbl.className = 'logs-table';
    // 최신이 위로 오도록 역순.
    logs.slice().reverse().forEach((e) => {
      const tr = document.createElement('tr');
      tr.className = 'log-' + String(e.level || '').toLowerCase();
      tr.appendChild(cell(e.time));
      tr.appendChild(cell(e.level));
      tr.appendChild(cell(e.logger));
      tr.appendChild(cell(e.message));
      tbl.appendChild(tr);
    });
    wrap.appendChild(tbl);
  }

  function cell(text) {
    const td = document.createElement('td');
    td.textContent = text == null ? '' : String(text);  // textContent — XSS-safe
    return td;
  }

  function close() {
    modal().classList.add('hidden');
  }

  const btn = document.getElementById('open-logs');
  if (btn) btn.onclick = open;
  return {open, close, render};
})();
