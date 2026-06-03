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

  // 통신 매트릭스 표 편집 — N×N 그리드(행=to 패턴, 열=from 패턴, 셀=weight 정수).
  // 적용 시 CSV로 변환해 POST(=활성화). 패턴 추가/삭제로 N을 조절.
  async function matrixEdit() {
    const data = await window.agoraApi.get('/dashboard/comm-matrix').catch(() => ({matrix: {}}));
    const matrix = data.matrix || {};
    let patterns = Object.keys(matrix);
    if (!patterns.length) patterns = ['(?i)orchestrator.*', '(?i)coder.*'];
    let weights = patterns.map(to => patterns.map(from => Number((matrix[to] || {})[from]) || 0));

    const card = _card('통신 매트릭스 편집');
    const help = document.createElement('p');
    help.textContent = '행=받는 쪽(to), 열=보내는 쪽(from), 셀=weight(0=차단, ≥1=허용). 헤더는 정규식. 적용 시 활성화.';
    help.className = 'matrix-help';
    card.appendChild(help);
    const host = document.createElement('div');
    host.className = 'matrix-edit-host';
    card.appendChild(host);

    function rebuild() {
      host.innerHTML = '';
      const tbl = document.createElement('table');
      tbl.className = 'matrix-edit';
      // 헤더 행: 코너 + from 패턴 입력 + 삭제
      const head = document.createElement('tr');
      head.appendChild(document.createElement('th'));  // corner
      patterns.forEach((pat, j) => {
        const th = document.createElement('th');
        const inp = document.createElement('input');
        inp.value = pat; inp.className = 'matrix-pat';
        inp.oninput = () => { patterns[j] = inp.value; syncRowLabels(); };
        th.appendChild(inp);
        head.appendChild(th);
      });
      head.appendChild(document.createElement('th'));  // del col header
      tbl.appendChild(head);
      // 데이터 행
      patterns.forEach((pat, i) => {
        const tr = document.createElement('tr');
        const rowLabel = document.createElement('th');
        rowLabel.className = 'matrix-rowlabel';
        rowLabel.textContent = pat;  // from 헤더 입력과 동기(syncRowLabels)
        tr.appendChild(rowLabel);
        patterns.forEach((_from, j) => {
          const td = document.createElement('td');
          const inp = document.createElement('input');
          inp.type = 'number'; inp.min = '0'; inp.value = String(weights[i][j]);
          inp.className = 'matrix-w';
          inp.oninput = () => { weights[i][j] = Math.max(0, parseInt(inp.value, 10) || 0); };
          td.appendChild(inp);
          tr.appendChild(td);
        });
        const delTd = document.createElement('td');
        const del = document.createElement('button');
        del.textContent = '✕'; del.title = '행/열 삭제'; del.className = 'matrix-del';
        del.onclick = () => { patterns.splice(i, 1); weights.splice(i, 1); weights.forEach(r => r.splice(i, 1)); rebuild(); };
        delTd.appendChild(del);
        tr.appendChild(delTd);
        tbl.appendChild(tr);
      });
      host.appendChild(tbl);
      const add = document.createElement('button');
      add.textContent = '+ 패턴 추가'; add.className = 'action-btn';
      add.onclick = () => {
        patterns.push('(?i)new.*');
        weights.forEach(r => r.push(0));
        weights.push(patterns.map(() => 0));
        rebuild();
      };
      host.appendChild(add);
    }

    function syncRowLabels() {
      const labels = host.querySelectorAll('.matrix-rowlabel');
      labels.forEach((el, i) => { el.textContent = patterns[i]; });
    }

    function buildCsv() {
      const rows = [patterns.join(',')];
      weights.forEach(r => rows.push(r.join(',')));
      return rows.join('\n');
    }

    rebuild();
    _buttons(card, '적용', () => _run(
      window.agoraApi.post('/dashboard/comm-matrix', {csv: buildCsv()})), false);
    _open(card);
  }

  return {unregister, closeConversation, toggleMatrix, matrixEdit, close};
})();
