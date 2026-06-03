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

  function matrixCsv() {
    const card = _card('통신 매트릭스 CSV 교체');
    const p = document.createElement('p');
    p.textContent = '헤더(정규식) + N×N 정수 셀. 적용 시 매트릭스가 활성화됩니다.';
    card.appendChild(p);
    const ta = document.createElement('textarea');
    ta.id = 'matrix-csv';
    ta.rows = 8;
    ta.placeholder = 'Coder.*,Reviewer.*\n0,1\n1,0';
    card.appendChild(ta);
    _buttons(card, '교체', () => _run(
      window.agoraApi.post('/dashboard/comm-matrix', {csv: ta.value})), false);
    _open(card);
  }

  return {unregister, closeConversation, toggleMatrix, matrixCsv, close};
})();
