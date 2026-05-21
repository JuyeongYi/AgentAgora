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

  function render() {
    const lis = messages.map(m => `
      <div class="message-card" data-id="${m.message_id}">
        <div><span class="sender">${escape(m.sender)}</span>
             <span class="timestamp">${escape(m.timestamp)}</span></div>
        <div class="schema">schema: ${escape(m.schema)}</div>
        <div class="payload">${escape(JSON.stringify(m.payload).slice(0,200))}</div>
        ${m.reply_only ? '<div class="reply-only">reply_only</div>' : ''}
        <button class="ack-btn" data-id="${m.message_id}">ack</button>
      </div>`).join('') || '<p>(메시지 없음)</p>';
    el().innerHTML = `<h3>운영자 인박스 (${messages.length})</h3>` + lis;
    el().querySelectorAll('.ack-btn').forEach(btn => {
      btn.onclick = (e) => ack([e.target.dataset.id]);
    });
    el().querySelectorAll('.message-card').forEach(card => {
      card.onclick = (e) => {
        if (e.target.classList.contains('ack-btn')) return;
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
