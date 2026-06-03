// 전문 검색 — 메시지 본문 검색바 + 결과 모달. /dashboard/search 소비 (read-only).
// 행 클릭 시 해당 대화 드릴다운으로 점프. 모든 셀 textContent(XSS-safe).
window.agoraSearch = (function() {
  const modal = () => document.getElementById('search-modal');

  async function open(query) {
    modal().innerHTML = `
      <div class="modal-card">
        <h2>검색 <span id="search-count"></span></h2>
        <div class="logs-toolbar">
          <input id="search-modal-input" type="search" placeholder="메시지 본문 검색…">
          <button id="search-go">검색</button>
        </div>
        <div id="search-body"><em>검색어를 입력하세요</em></div>
        <button id="search-close">닫기</button>
      </div>`;
    modal().classList.remove('hidden');
    document.getElementById('search-close').onclick = close;
    const input = document.getElementById('search-modal-input');
    const go = () => render(input.value);
    document.getElementById('search-go').onclick = go;
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
    if (query) { input.value = query; await render(query); }
    input.focus();
  }

  async function render(q) {
    q = (q || '').trim();
    const body = document.getElementById('search-body');
    const count = document.getElementById('search-count');
    if (!q) { body.innerHTML = ''; if (count) count.textContent = ''; return; }
    let data;
    try {
      data = await window.agoraApi.get('/dashboard/search?q=' + encodeURIComponent(q) + '&limit=50');
    } catch (e) { data = {results: []}; }
    const results = data.results || [];
    if (count) count.textContent = `(${results.length}${data.fts === false ? ', LIKE' : ''})`;
    body.innerHTML = '';
    if (!results.length) {
      const em = document.createElement('em');
      em.textContent = '결과 없음';
      body.appendChild(em);
      return;
    }
    const tbl = document.createElement('table');
    tbl.className = 'search-table';
    results.forEach((m) => {
      const tr = document.createElement('tr');
      tr.appendChild(cell(m.created_at));
      tr.appendChild(cell((m.source || '') + ' → ' + (m.target || '')));
      tr.appendChild(cell(m.snippet, 'search-snippet'));
      tr.style.cursor = 'pointer';
      tr.onclick = () => {
        if (m.conversation_id && window.agoraDrilldown) {
          window.agoraDrilldown.openConversation(m.conversation_id);
          close();
        }
      };
      tbl.appendChild(tr);
    });
    body.appendChild(tbl);
  }

  function cell(text, cls) {
    const td = document.createElement('td');
    if (cls) td.className = cls;
    td.textContent = text == null ? '' : String(text);  // textContent — XSS-safe
    return td;
  }

  function close() { modal().classList.add('hidden'); }

  // 헤더 검색바 배선.
  const headerInput = document.getElementById('search-input');
  const headerBtn = document.getElementById('open-search');
  if (headerBtn) headerBtn.onclick = () => open(headerInput ? headerInput.value : '');
  if (headerInput) headerInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') open(headerInput.value);
  });

  return {open, close, render};
})();
