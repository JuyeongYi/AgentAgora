// 드릴다운 모달 — 대화 thread / 인스턴스 인박스 / 개별 메시지.
window.agoraDrilldown = (function() {
  const modal = () => document.getElementById('drilldown-modal');

  function escape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // 메시지를 created_at 오름차순(시간순)으로 정렬. ISO 8601은 사전식 정렬이 시간순과 일치.
  // 백엔드도 ASC로 주지만 클라이언트 가드로 명시적 시간순을 보장한다.
  function byTime(msgs) {
    return (msgs || []).slice().sort(
      (a, b) => String(a.created_at).localeCompare(String(b.created_at)));
  }

  function msgCard(m) {
    const cmd = m.message_id || m.command_id || '';
    const covSlot = cmd
      ? `<span class="coverage-inline" data-cmd="${escape(cmd)}"></span>` : '';
    // 등록된 스키마 포맷이 있으면 그 HTML로, 없으면 JSON 폴백.
    const fmt = window.agoraFormats && window.agoraFormats.render(m.payload);
    const body = fmt || `<pre class="payload">${escape(JSON.stringify(m.payload, null, 2))}</pre>`;
    const replyBtn = (m.sender && cmd)
      ? `<button class="reply-btn" data-to="${escape(m.sender)}" ` +
        `data-conv="${escape(m.conversation_id || '')}" data-irt="${escape(cmd)}" ` +
        `data-mt="${escape((m.payload && m.payload.msgtype) || '')}">답장</button>` : '';
    return `<div class="message-card">
      <div><span class="sender">${escape(m.sender)}</span>
           → <span>${escape(m.target)}</span>
           <span class="timestamp">${escape(m.created_at)}</span>${covSlot}</div>
      <div>schema: ${escape((m.payload && m.payload.msgtype) || '')}</div>
      ${body}
      ${m.reply_only ? '<div class="reply-only">reply_only</div>' : ''}
      <div class="card-actions">${replyBtn}</div>
    </div>`;
  }

  // 답장 버튼 → dispatch 패널 prefill(대상=발신자, in_reply_to=메시지) 후 모달 닫기.
  function wireReply() {
    modal().querySelectorAll('.reply-btn').forEach(btn => {
      btn.onclick = () => {
        if (window.agoraDispatch) window.agoraDispatch.prefillReply({
          to: btn.getAttribute('data-to'),
          conversation_id: btn.getAttribute('data-conv') || null,
          in_reply_to: btn.getAttribute('data-irt'),
          msgtype: btn.getAttribute('data-mt') || undefined,
        });
        close();
      };
    });
  }

  // expect_result 메시지의 coverage(pending/responded/expired)를 lazy 인라인 표시.
  // pending+responded가 비면(=expect_result 아님) 아무것도 안 그린다. 실패는 조용히 무시.
  async function hydrateCoverage() {
    const slots = modal().querySelectorAll('.coverage-inline[data-cmd]');
    slots.forEach(async (slot) => {
      const cmd = slot.getAttribute('data-cmd');
      try {
        const c = await window.agoraApi.get('/dashboard/coverage/' + encodeURIComponent(cmd));
        const pending = (c.pending || []).length;
        const responded = (c.responded || []).length;
        if (pending + responded === 0) return;  // expect_result 아님
        const parts = [];
        if (pending) parts.push(`<span class="cov-pending">대기 ${pending}</span>`);
        if (responded) parts.push(`<span class="cov-responded">응답 ${responded}</span>`);
        if (c.expired) parts.push('<span class="cov-expired">만료</span>');
        slot.innerHTML = ' ' + parts.join(' ');  // 값은 정수/고정 라벨 — 안전
      } catch (e) { /* 무시 — 카드 본문 유지 */ }
    });
  }

  async function openConversation(convId) {
    show('대화 ' + convId, '<p>불러오는 중…</p>');
    try {
      const d = await window.agoraApi.get('/dashboard/conversation/' + encodeURIComponent(convId));
      const html = byTime(d.messages).map(msgCard).join('') || '<p>(빈 thread)</p>';
      show('대화 ' + convId, html);
      hydrateCoverage();
      wireReply();
    } catch (e) { show('대화 ' + convId, '<p>로드 실패: ' + escape(e.message) + '</p>'); }
  }

  async function openInstanceInbox(instId) {
    show(instId + ' 인박스', '<p>불러오는 중…</p>');
    try {
      const d = await window.agoraApi.get('/dashboard/instance/' + encodeURIComponent(instId) + '/inbox');
      const html = byTime(d.messages).map(msgCard).join('') || '<p>(빈 인박스)</p>';
      show(instId + ' 인박스', html);
      hydrateCoverage();
      wireReply();
    } catch (e) { show(instId + ' 인박스', '<p>로드 실패: ' + escape(e.message) + '</p>'); }
  }

  function openMessage(m) { show('메시지', msgCard(m)); wireReply(); }

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
