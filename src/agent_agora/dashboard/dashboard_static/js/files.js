// 파일 스토어 뷰 — 공유 파일 메타 목록. /dashboard/files 소비 (read-only).
// 다운로드는 /files/{file_id} (별도 라우트). trust 모드에서 바로 동작.
window.agoraFiles = (function() {
  const modal = () => document.getElementById('files-modal');

  function fmtSize(n) {
    if (n == null) return '';
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
  }

  async function open() {
    modal().innerHTML = `
      <div class="modal-card">
        <h2>공유 파일 <span id="files-count"></span></h2>
        <div class="logs-toolbar"><button id="files-refresh">새로고침</button></div>
        <div id="files-body"><em>불러오는 중…</em></div>
        <button id="files-close">닫기</button>
      </div>`;
    modal().classList.remove('hidden');
    document.getElementById('files-close').onclick = close;
    document.getElementById('files-refresh').onclick = render;
    await render();
  }

  async function render() {
    const data = await window.agoraApi.get('/dashboard/files').catch(() => ({files: []}));
    const files = data.files || [];
    const count = document.getElementById('files-count');
    if (count) count.textContent = `(${files.length})`;
    const wrap = document.getElementById('files-body');
    wrap.innerHTML = '';
    if (!files.length) {
      const em = document.createElement('em');
      em.textContent = '공유된 파일 없음';
      wrap.appendChild(em);
      return;
    }
    const tbl = document.createElement('table');
    tbl.className = 'files-table';
    const head = document.createElement('tr');
    ['이름', '크기', '타입', '등록자', '시각', ''].forEach((h) => {
      const th = document.createElement('th');
      th.textContent = h;
      head.appendChild(th);
    });
    tbl.appendChild(head);
    files.forEach((f) => {
      const tr = document.createElement('tr');
      tr.appendChild(cell(f.name));
      tr.appendChild(cell(fmtSize(f.size)));
      tr.appendChild(cell(f.content_type));
      tr.appendChild(cell(f.registered_by));
      tr.appendChild(cell(f.created_at));
      // 다운로드 링크 — href는 file_id로 구성, textContent는 라벨.
      const td = document.createElement('td');
      const a = document.createElement('a');
      a.href = '/files/' + encodeURIComponent(f.file_id);
      a.textContent = '다운로드';
      a.target = '_blank';
      a.rel = 'noopener';
      a.title = 'sha256: ' + (f.sha256 || '');
      td.appendChild(a);
      tr.appendChild(td);
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

  const btn = document.getElementById('open-files');
  if (btn) btn.onclick = open;
  return {open, close, render};
})();
