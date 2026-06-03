// 운영자 인박스 패널 — left panel.
window.agoraInbox = (function() {
  const el = () => document.getElementById('inbox-panel');
  let messages = [];

  async function refresh() {
    try {
      const d = await window.agoraApi.get('/dashboard/operator/inbox');
      messages = d.messages || [];
      render();
    } catch (e) { console.error('inbox refresh', e); }
  }

  function bodyHtml(m) {
    // 등록된 스키마 포맷이 있으면 그 HTML로, 없으면 JSON 폴백.
    const fmt = window.agoraFormats && window.agoraFormats.render(m.payload);
    return fmt || `<div class="payload">${escape(JSON.stringify(m.payload).slice(0, 200))}</div>`;
  }

  function render() {
    const lis = messages.map(m => `
      <div class="message-card" data-id="${escape(m.message_id)}">
        <div><span class="sender">${escape(m.sender)}</span>
             <span class="timestamp">${escape(m.created_at)}</span></div>
        <div class="schema">schema: ${escape((m.payload && m.payload.msgtype) || '')}</div>
        ${bodyHtml(m)}
        ${m.reply_only ? '<div class="reply-only">reply_only</div>' : ''}
        <div class="card-actions">
          <button class="reply-btn" data-id="${escape(m.message_id)}">답장</button>
          <button class="ack-btn" data-id="${escape(m.message_id)}">ack</button>
        </div>
      </div>`).join('') || '<p>(메시지 없음)</p>';
    el().innerHTML = `<h3>운영자 인박스 (${messages.length})</h3>` + lis;
    el().querySelectorAll('.ack-btn').forEach(btn => {
      btn.onclick = (e) => { e.stopPropagation(); ack([e.target.dataset.id]); };
    });
    el().querySelectorAll('.reply-btn').forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const m = messages.find(x => x.message_id === e.target.dataset.id);
        if (m && window.agoraDispatch) window.agoraDispatch.prefillReply(
          {to: m.sender, conversation_id: m.conversation_id, in_reply_to: m.message_id});
      };
    });
    el().querySelectorAll('.message-card').forEach(card => {
      card.onclick = (e) => {
        if (e.target.tagName === 'BUTTON' || e.target.tagName === 'A') return;
        const id = card.dataset.id;
        const m = messages.find(x => x.message_id === id);
        if (m) window.agoraDrilldown.openMessage(m);
      };
    });
  }

  async function ack(ids) {
    try {
      await window.agoraApi.post('/dashboard/operator/inbox/ack', {message_ids: ids});
      refresh();
    } catch (e) { console.error('ack', e); }
  }

  // SSE에서 operator_inbox_message 이벤트 도착 시
  function push(evt) {
    refresh();  // 간단한 전체 refresh — 작은 패널이라 OK
  }

  function escape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  return {refresh, push};
})();
