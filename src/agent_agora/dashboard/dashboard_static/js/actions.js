// 운영자 state-changing 액션 — force-close 대화 / unregister 워커 / comm-matrix 토글·교체.
// 모든 액션은 확인 모달 → agoraApi.post → window._refresh(). 동적 텍스트는 textContent(XSS-safe).
window.agoraActions = (function() {
  const modal = () => document.getElementById('action-modal');

  function close() { modal().classList.add('hidden'); modal().innerHTML = ''; }

  function _card(titleText) {
    const card = document.createElement('div');
    card.className = 'modal-card';
    const h = document.createElement('h2');
    h.textContent = titleText;
    card.appendChild(h);
    return card;
  }

  function _buttons(card, confirmLabel, onConfirm, danger) {
    const row = document.createElement('div');
    row.className = 'action-buttons';
    const ok = document.createElement('button');
    ok.textContent = confirmLabel;
    ok.className = danger ? 'danger-btn' : 'action-btn';
    ok.onclick = onConfirm;
    const cancel = document.createElement('button');
    cancel.textContent = '취소';
    cancel.onclick = close;
    row.appendChild(ok);
    row.appendChild(cancel);
    card.appendChild(row);
  }

  async function _run(promise) {
    try {
      await promise;
      close();
      if (window._refresh) window._refresh();
    } catch (e) {
      const msg = (e && e.body && e.body.error) || String(e);
      alert('실패: ' + msg);
    }
  }

  function _open(card) {
    const m = modal();
    m.innerHTML = '';
    m.appendChild(card);
    m.classList.remove('hidden');
  }

  function unregister(instanceId) {
    const card = _card('워커 등록 해제');
    const p = document.createElement('p');
    p.textContent = `'${instanceId}' 를 unregister 합니다. 대기 중인 메시지는 유실될 수 있습니다.`;
    card.appendChild(p);
    _buttons(card, '해제', () => _run(
      window.agoraApi.post(`/dashboard/instance/${encodeURIComponent(instanceId)}/unregister`, {})), true);
    _open(card);
  }

  function closeConversation(conversationId) {
    const card = _card('대화 강제 종료');
    const p = document.createElement('p');
    p.textContent = `대화 '${conversationId}' 를 close 합니다.`;
    card.appendChild(p);
    const ta = document.createElement('textarea');
    ta.id = 'close-reason';
    ta.placeholder = '사유 (선택)';
    card.appendChild(ta);
    _buttons(card, '닫기', () => _run(
      window.agoraApi.post(
        `/dashboard/operator/conversation/${encodeURIComponent(conversationId)}/close`,
        {reason: ta.value})), true);
    _open(card);
  }

  function toggleMatrix(active) {
    const card = _card('통신 매트릭스 ' + (active ? '활성화' : '비활성화'));
    const p = document.createElement('p');
    p.textContent = active
      ? '매트릭스를 활성화합니다 (whitelist ACL 적용).'
      : '매트릭스를 비활성화합니다 (all-allow — 모든 워커가 서로 dispatch 가능). 주의.';
    card.appendChild(p);
    _buttons(card, active ? '활성화' : '비활성화', () => _run(
      window.agoraApi.post('/dashboard/comm-matrix', {active})), !active);
    _open(card);
  }

  // 통신 매트릭스 표 편집 — 행(to)·열(from) 독립 그리드(비정사각 허용). 셀=weight 정수.
  // 행/열을 따로 추가·삭제. 적용 시 {matrix} dict로 POST(=활성화).
  async function matrixEdit() {
    const data = await window.agoraApi.get('/dashboard/comm-matrix').catch(() => ({matrix: {}}));
    const matrix = data.matrix || {};
    let rows = Object.keys(matrix);                 // to-패턴(행)
    let cols = [];                                  // from-패턴(열, 합집합)
    rows.forEach(r => Object.keys(matrix[r] || {}).forEach(c => { if (!cols.includes(c)) cols.push(c); }));
    if (!rows.length) rows = ['(?i)orchestrator.*'];
    if (!cols.length) cols = ['(?i)coder.*'];
    let weights = rows.map(r => cols.map(c => Number((matrix[r] || {})[c]) || 0));

    const card = _card('통신 매트릭스 편집');
    const help = document.createElement('p');
    help.textContent = '행=받는 쪽(to), 열=보내는 쪽(from), 셀=weight(0=차단, ≥1=허용). 헤더는 정규식. 행·열 독립 추가. 적용 시 활성화.';
    help.className = 'matrix-help';
    card.appendChild(help);
    const host = document.createElement('div');
    host.className = 'matrix-edit-host';
    card.appendChild(host);

    function patInput(arr, idx, onDel, delTitle) {
      const wrap = document.createElement('span');
      wrap.className = 'matrix-pat-wrap';
      const inp = document.createElement('input');
      inp.value = arr[idx]; inp.className = 'matrix-pat';
      inp.oninput = () => { arr[idx] = inp.value; };
      const del = document.createElement('button');
      del.textContent = '✕'; del.className = 'matrix-del'; del.title = delTitle;
      del.onclick = onDel;
      wrap.appendChild(inp); wrap.appendChild(del);
      return wrap;
    }

    function rebuild() {
      host.innerHTML = '';
      const tbl = document.createElement('table');
      tbl.className = 'matrix-edit';
      // 헤더 행: 코너 + from(열) 패턴 입력
      const head = document.createElement('tr');
      const corner = document.createElement('th');
      corner.textContent = 'to ＼ from'; corner.className = 'matrix-corner';
      head.appendChild(corner);
      cols.forEach((c, j) => {
        const th = document.createElement('th');
        th.appendChild(patInput(cols, j,
          () => { cols.splice(j, 1); weights.forEach(r => r.splice(j, 1)); rebuild(); }, '열 삭제'));
        head.appendChild(th);
      });
      tbl.appendChild(head);
      // 데이터 행: to(행) 패턴 입력 + weight 셀
      rows.forEach((r, i) => {
        const tr = document.createElement('tr');
        const rh = document.createElement('th');
        rh.appendChild(patInput(rows, i,
          () => { rows.splice(i, 1); weights.splice(i, 1); rebuild(); }, '행 삭제'));
        tr.appendChild(rh);
        cols.forEach((_c, j) => {
          const td = document.createElement('td');
          const w = document.createElement('input');
          w.type = 'number'; w.min = '0'; w.value = String(weights[i][j]);
          w.className = 'matrix-w';
          w.oninput = () => { weights[i][j] = Math.max(0, parseInt(w.value, 10) || 0); };
          td.appendChild(w);
          tr.appendChild(td);
        });
        tbl.appendChild(tr);
      });
      host.appendChild(tbl);
      const addRow = document.createElement('button');
      addRow.textContent = '+ 행(to)'; addRow.className = 'action-btn';
      addRow.onclick = () => { rows.push('(?i)new.*'); weights.push(cols.map(() => 0)); rebuild(); };
      const addCol = document.createElement('button');
      addCol.textContent = '+ 열(from)'; addCol.className = 'action-btn';
      addCol.onclick = () => { cols.push('(?i)new.*'); weights.forEach(r => r.push(0)); rebuild(); };
      host.appendChild(addRow);
      host.appendChild(addCol);
    }

    function buildMatrix() {
      const m = {};
      rows.forEach((r, i) => { m[r] = {}; cols.forEach((c, j) => { m[r][c] = weights[i][j]; }); });
      return m;
    }

    rebuild();
    _buttons(card, '적용', () => _run(
      window.agoraApi.post('/dashboard/comm-matrix', {matrix: buildMatrix()})), false);
    _open(card);
  }

  return {unregister, closeConversation, toggleMatrix, matrixEdit, close};
})();
