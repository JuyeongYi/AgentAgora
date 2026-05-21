// 드릴다운 모달 — 대화 thread / 인스턴스 인박스 / 개별 메시지.
window.agoraDrilldown = (function() {
  const modal = () => document.getElementById('drilldown-modal');

  function escape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function msgCard(m) {
    return `<div class="message-card">
      <div><span class="sender">${escape(m.sender)}</span>
           → <span>${escape(m.target)}</span>
           <span class="timestamp">${escape(m.created_at)}</span></div>
      <div>schema: ${escape((m.payload && m.payload.msgtype) || '')}</div>
      <pre class="payload">${escape(JSON.stringify(m.payload, null, 2))}</pre>
      ${m.reply_only ? '<div class="reply-only">reply_only</div>' : ''}
    </div>`;
  }

  async function openConversation(convId) {
    show('대화 ' + convId, '<p>불러오는 중…</p>');
    try {
      const d = await window.agoraApi.get('/dashboard/conversation/' + encodeURIComponent(convId));
      const html = (d.messages || []).map(msgCard).join('') || '<p>(빈 thread)</p>';
      show('대화 ' + convId, html);
    } catch (e) { show('대화 ' + convId, '<p>로드 실패: ' + escape(e.message) + '</p>'); }
  }

  async function openInstanceInbox(instId) {
    show(instId + ' 인박스', '<p>불러오는 중…</p>');
    try {
      const d = await window.agoraApi.get('/dashboard/instance/' + encodeURIComponent(instId) + '/inbox');
      const html = (d.messages || []).map(msgCard).join('') || '<p>(빈 인박스)</p>';
      show(instId + ' 인박스', html);
    } catch (e) { show(instId + ' 인박스', '<p>로드 실패: ' + escape(e.message) + '</p>'); }
  }

  function openMessage(m) { show('메시지', msgCard(m)); }

  function show(title, html) {
    modal().innerHTML = `<div class="modal-card">
      <h2>${escape(title)}</h2>
      <div>${html}</div>
      <button onclick="window.agoraDrilldown.close()">닫기</button>
    </div>`;
    modal().classList.remove('hidden');
  }

  function close() { modal().classList.add('hidden'); }

  return {openConversation, openInstanceInbox, openMessage, close};
})();
