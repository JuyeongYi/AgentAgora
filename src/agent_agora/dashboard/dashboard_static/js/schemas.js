// 스키마 explorer — read-only 카탈로그 뷰 (메타 + body). /dashboard/schemas 소비.
window.agoraSchemas = (function() {
  const modal = () => document.getElementById('schemas-modal');

  async function open() {
    const data = await window.agoraApi.get('/dashboard/schemas').catch(() => ({schemas: []}));
    const schemas = data.schemas || [];
    modal().innerHTML = `
      <div class="modal-card">
        <h2>스키마 카탈로그 (${schemas.length})</h2>
        <div class="schema-explorer">
          <ul id="schema-list"></ul>
          <div id="schema-body"><em>스키마를 선택하세요</em></div>
        </div>
        <button id="schemas-close">닫기</button>
      </div>`;
    const list = document.getElementById('schema-list');
    schemas.forEach((s) => {
      const li = document.createElement('li');
      const meta = `${s.kind || ''} · ${s.purpose || ''} · by ${s.registered_by || '(permanent)'} · refs ${s.ref_count}`;
      const head = document.createElement('strong');
      head.textContent = s.id;
      const sub = document.createElement('div');
      sub.className = 'schema-meta';
      sub.textContent = meta;
      li.appendChild(head);
      li.appendChild(sub);
      li.onclick = () => showBody(s);
      list.appendChild(li);
    });
    modal().classList.remove('hidden');
    document.getElementById('schemas-close').onclick = close;
  }

  function showBody(s) {
    const wrap = document.getElementById('schema-body');
    wrap.innerHTML = '';
    const pre = document.createElement('pre');
    // textContent — 스키마 body의 임의 JSON(< > 등)을 안전하게 표시.
    pre.textContent = JSON.stringify(s.schema, null, 2);
    wrap.appendChild(pre);
  }

  function close() {
    modal().classList.add('hidden');
  }

  const btn = document.getElementById('open-schemas');
  if (btn) btn.onclick = open;
  return {open, close};
})();
