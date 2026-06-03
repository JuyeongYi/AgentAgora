// 메시지 보내기 — 상시 표시 패널(#dispatch-panel)은 일반 송신용(단일/브로드캐스트).
// 답장은 별도 팝업 모달(#reply-modal)로 띄운다 — 폼 레이아웃(스키마 select·payload
// editor·reply_only·보내기)은 패널과 공유하되, 대상을 원 발신자로 고정하고
// in_reply_to/conversation_id를 실어 보낸다. schema 선택 시 JSONEditor가 폼을 자동
// 생성(필수 필드). ts/timestamp/from은 서버가 dispatch 시 자동 주입하므로 폼에서 제외.
window.agoraDispatch = (function() {
  const panel = () => document.getElementById('dispatch-panel');
  const replyModal = () => document.getElementById('reply-modal');
  let editor = null;            // 상시 패널 JSONEditor
  let replyEditor = null;       // 답장 모달 JSONEditor (별도 인스턴스 — 동시 생존 가능)
  let schemas = [];
  let instances = [];
  let modalCtx = null;          // {to, conversation_id, in_reply_to} — 답장 모달 컨텍스트
  let panelGetPayload = () => ({});
  let modalGetPayload = () => ({});

  function escapeAttr(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }

  function schemaOptions(selected) {
    return schemas.map(s =>
      `<option value="${escapeAttr(s.id)}"${s.id === selected ? ' selected' : ''}>${escapeAttr(s.id)}</option>`
    ).join('');
  }

  // 폼에서 자동 결정 필드를 제거한다(서버가 채움):
  //  - msgtype: 스키마 드롭다운 선택값으로 서버가 주입(_inject_msgtype).
  //  - ts/timestamp: dispatch 시 서버 시각.
  //  - from: dispatch source(보내는 운영자/워커)로 서버가 주입.
  const _AUTO_FIELDS = ['msgtype', 'ts', 'timestamp', 'from'];
  function stripServerFields(schema) {
    if (!schema || typeof schema !== 'object') return schema;
    const s = JSON.parse(JSON.stringify(schema));
    if (s.properties) _AUTO_FIELDS.forEach(k => delete s.properties[k]);
    if (Array.isArray(s.required)) s.required = s.required.filter(k => !_AUTO_FIELDS.includes(k));
    return s;
  }

  // editEl(빈 div)에 schemaId용 JSONEditor를 만든다. 스키마가 없으면 raw textarea.
  // 반환: {editor, getValue} — getValue()는 payload 객체(파싱 실패 시 throw).
  function buildEditor(editEl, schemaId) {
    const schema = stripServerFields((schemas.find(s => s.id === schemaId) || {}).schema);
    if (schema && window.JSONEditor) {
      const ed = new JSONEditor(editEl, {
        schema: schema, theme: 'html', disable_collapse: true, disable_edit_json: false,
      });
      return {editor: ed, getValue: () => ed.getValue()};
    }
    editEl.innerHTML = '<textarea class="payload-raw" rows="5" style="width:100%">{}</textarea>';
    const ta = editEl.querySelector('.payload-raw');
    return {editor: null, getValue: () => {
      try { return JSON.parse(ta.value); }
      catch (e) { throw new Error('Payload JSON 파싱 실패'); }
    }};
  }

  // 단일 대상 dispatch 공통 경로(패널 single 모드 + 답장 모달이 공유). skipped_full 반환.
  async function doDispatchSingle(body) {
    const res = await window.agoraApi.post('/dashboard/dispatch', body);
    return res.skipped_full || [];
  }

  // ---- 상시 패널 (#dispatch-panel) — 일반 송신 ----

  async function render() {
    if (!panel()) return;
    schemas = (await window.agoraApi.get('/dashboard/schemas').catch(() => ({schemas: []}))).schemas || [];
    const snap = await window.agoraApi.get('/dashboard/data').catch(() => ({instances: []}));
    instances = snap.instances || [];

    panel().innerHTML = `
      <h3>메시지 보내기</h3>
      <div class="dispatch-controls-row">
        <div class="dispatch-modes">
          <label><input type="radio" name="dmode" value="single" checked>단일</label>
          <label><input type="radio" name="dmode" value="broadcast">브로드캐스트</label>
        </div>
        <div id="dispatch-target"></div>
        <label class="dispatch-field">Schema (= msgtype)
          <select id="dispatch-schema">${schemaOptions()}</select>
        </label>
        <label class="dispatch-field"><input type="checkbox" id="dispatch-reply-only">reply_only</label>
      </div>
      <label class="dispatch-field">Payload <span class="dispatch-hint">(msgtype는 스키마 선택, ts/from은 서버가 자동)</span></label>
      <div id="dispatch-payload"></div>
      <div class="dispatch-send-row">
        <button id="dispatch-send" class="action-btn">보내기</button>
        <span id="dispatch-status" class="dispatch-status"></span>
      </div>`;

    setupTargetPicker();
    setupPayloadEditor();
    document.getElementsByName('dmode').forEach(r => r.onchange = setupTargetPicker);
    document.getElementById('dispatch-schema').onchange = setupPayloadEditor;
    document.getElementById('dispatch-send').onclick = send;
  }

  // 인스턴스 목록 변동 시 대상 picker만 갱신(폼 입력은 보존).
  async function refreshTargets() {
    if (!panel() || !document.getElementById('dispatch-target')) return;
    const snap = await window.agoraApi.get('/dashboard/data').catch(() => null);
    if (snap) instances = snap.instances || [];
    setupTargetPicker();
  }

  function setupTargetPicker() {
    const checked = document.querySelector('input[name="dmode"]:checked');
    const mode = checked ? checked.value : 'single';
    const wrap = document.getElementById('dispatch-target');
    if (!wrap) return;
    const opts = instances.map(i =>
      `<option value="${escapeAttr(i.instance_id)}">${escapeAttr(i.instance_id)} (${escapeAttr(i.role)})</option>`).join('');
    if (mode === 'single') {
      wrap.innerHTML = `<label class="dispatch-field">To <select id="dispatch-to">${opts}</select></label>`;
    } else {
      wrap.innerHTML = `<label class="dispatch-field">대상</label>
        <div id="dispatch-targets-list">${
          instances.map(i => `<label class="dispatch-tgt"><input type="checkbox" value="${escapeAttr(i.instance_id)}" checked> ${escapeAttr(i.instance_id)}</label>`).join('')
        }</div>`;
    }
  }

  function setupPayloadEditor() {
    const sel = document.getElementById('dispatch-schema');
    if (!sel) return;
    const wrap = document.getElementById('dispatch-payload');
    wrap.innerHTML = '<div id="payload-edit"></div>';
    if (editor) try { editor.destroy(); } catch (e) {}
    const built = buildEditor(document.getElementById('payload-edit'), sel.value);
    editor = built.editor;
    panelGetPayload = built.getValue;
  }

  function status(text, ok) {
    const el = document.getElementById('dispatch-status');
    if (el) { el.textContent = text; el.className = 'dispatch-status ' + (ok ? 'ok' : 'err'); }
  }

  async function send() {
    try {
      const checked = document.querySelector('input[name="dmode"]:checked');
      const mode = checked ? checked.value : 'single';
      const schema = document.getElementById('dispatch-schema').value;
      const reply_only = document.getElementById('dispatch-reply-only').checked;
      const payload = panelGetPayload();
      let skipped = [];
      if (mode === 'single') {
        const to = document.getElementById('dispatch-to').value;
        skipped = await doDispatchSingle({to, schema, payload, reply_only});
      } else {
        const targets = Array.from(document.querySelectorAll('#dispatch-targets-list input:checked')).map(c => c.value);
        if (!targets.length) { status('최소 1개 대상 선택', false); return; }
        const res = await window.agoraApi.post('/dashboard/broadcast', {targets, schema, payload, reply_only});
        skipped = (res.results || []).flatMap(r => r.skipped_full || []);
      }
      if (skipped.length) status('일부 누락(인박스 만석): ' + skipped.join(', '), false);
      else status('보냄 ✓', true);
      if (window._refresh) window._refresh();
    } catch (e) {
      const msg = (e && e.body && e.body.error) || e.message || String(e);
      status('전송 실패: ' + msg, false);
    }
  }

  // ---- 답장 모달 (#reply-modal) — 폼 레이아웃은 패널과 공유, 대상은 발신자 고정 ----

  // 특정 인박스/대화 메시지에 답장 — 팝업 모달을 띄운다.
  // opts: {to, conversation_id, in_reply_to, msgtype}
  function prefillReply(opts) {
    openReplyModal(opts || {});
  }

  function openReplyModal(opts) {
    const m = replyModal();
    if (!m) return;
    modalCtx = {
      to: opts.to || '',
      conversation_id: opts.conversation_id || null,
      in_reply_to: opts.in_reply_to || null,
    };
    const short = (opts.in_reply_to || '').slice(0, 8);
    m.innerHTML = `
      <div class="modal-card">
        <h2>답장</h2>
        <div class="reply-quote">→ <b>${escapeAttr(opts.to || '')}</b>${
          short ? `<span class="reply-irt">in_reply_to ${escapeAttr(short)}…</span>` : ''}</div>
        <div class="dispatch-controls-row">
          <label class="dispatch-field">Schema (= msgtype)
            <select id="reply-schema">${schemaOptions(opts.msgtype)}</select>
          </label>
          <label class="dispatch-field"><input type="checkbox" id="reply-reply-only">reply_only</label>
        </div>
        <label class="dispatch-field">Payload <span class="dispatch-hint">(msgtype는 스키마 선택, ts/from은 서버가 자동)</span></label>
        <div id="reply-payload"></div>
        <div class="dispatch-send-row">
          <button id="reply-send" class="action-btn">보내기</button>
          <button id="reply-cancel" class="action-btn">취소</button>
          <span id="reply-status" class="dispatch-status"></span>
        </div>
      </div>`;
    setupReplyEditor();
    document.getElementById('reply-schema').onchange = setupReplyEditor;
    document.getElementById('reply-send').onclick = sendReply;
    document.getElementById('reply-cancel').onclick = closeReplyModal;
    m.classList.remove('hidden');
  }

  function setupReplyEditor() {
    const sel = document.getElementById('reply-schema');
    if (!sel) return;
    const wrap = document.getElementById('reply-payload');
    wrap.innerHTML = '<div id="reply-payload-edit"></div>';
    if (replyEditor) try { replyEditor.destroy(); } catch (e) {}
    const built = buildEditor(document.getElementById('reply-payload-edit'), sel.value);
    replyEditor = built.editor;
    modalGetPayload = built.getValue;
  }

  function replyStatus(text, ok) {
    const el = document.getElementById('reply-status');
    if (el) { el.textContent = text; el.className = 'dispatch-status ' + (ok ? 'ok' : 'err'); }
  }

  async function sendReply() {
    if (!modalCtx) return;
    try {
      const schema = document.getElementById('reply-schema').value;
      const reply_only = document.getElementById('reply-reply-only').checked;
      const payload = modalGetPayload();
      const body = {to: modalCtx.to, schema, payload, reply_only};
      if (modalCtx.conversation_id) body.conversation_id = modalCtx.conversation_id;
      if (modalCtx.in_reply_to) body.in_reply_to = modalCtx.in_reply_to;
      const skipped = await doDispatchSingle(body);
      if (skipped.length) { replyStatus('일부 누락(인박스 만석): ' + skipped.join(', '), false); return; }
      closeReplyModal();
      if (window._refresh) window._refresh();
    } catch (e) {
      const msg = (e && e.body && e.body.error) || e.message || String(e);
      replyStatus('전송 실패: ' + msg, false);
    }
  }

  function closeReplyModal() {
    if (replyEditor) try { replyEditor.destroy(); } catch (e) {}
    replyEditor = null;
    modalCtx = null;
    const m = replyModal();
    if (m) { m.classList.add('hidden'); m.innerHTML = ''; }
  }

  return {render, refreshTargets, prefillReply, closeReplyModal};
})();
