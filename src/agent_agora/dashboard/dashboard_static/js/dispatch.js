// 메시지 보내기 — 상시 표시 패널(#dispatch-panel). schema 선택 시 JSONEditor가 폼을
// 자동 생성(필수 필드 채움). ts/timestamp는 폼에서 제외 — 서버가 dispatch 시 자동 주입.
window.agoraDispatch = (function() {
  const panel = () => document.getElementById('dispatch-panel');
  let editor = null;
  let schemas = [];
  let instances = [];

  async function render() {
    if (!panel()) return;
    schemas = (await window.agoraApi.get('/dashboard/schemas').catch(() => ({schemas: []}))).schemas || [];
    const snap = await window.agoraApi.get('/dashboard/data').catch(() => ({instances: []}));
    instances = snap.instances || [];

    panel().innerHTML = `
      <h3>메시지 보내기</h3>
      <div class="dispatch-grid">
        <div class="dispatch-controls">
          <div class="dispatch-modes">
            <label><input type="radio" name="dmode" value="single" checked>단일</label>
            <label><input type="radio" name="dmode" value="broadcast">브로드캐스트</label>
          </div>
          <div id="dispatch-target"></div>
          <label class="dispatch-field">Schema (= msgtype)
            <select id="dispatch-schema">${
              schemas.map(s => `<option value="${escapeAttr(s.id)}">${escapeAttr(s.id)}</option>`).join('')
            }</select>
          </label>
          <label class="dispatch-field"><input type="checkbox" id="dispatch-reply-only">reply_only</label>
          <button id="dispatch-send" class="action-btn">보내기</button>
          <span id="dispatch-status" class="dispatch-status"></span>
        </div>
        <div class="dispatch-payload-col">
          <label class="dispatch-field">Payload <span class="dispatch-hint">(msgtype는 스키마 선택, ts는 서버가 자동)</span></label>
          <div id="dispatch-payload"></div>
        </div>
      </div>`;

    setupTargetPicker();
    setupPayloadEditor();
    document.getElementsByName('dmode').forEach(r => r.onchange = setupTargetPicker);
    document.getElementById('dispatch-schema').onchange = setupPayloadEditor;
    document.getElementById('dispatch-send').onclick = send;
  }

  function escapeAttr(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
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

  function setupPayloadEditor() {
    const sel = document.getElementById('dispatch-schema');
    if (!sel) return;
    const schema = stripServerFields((schemas.find(s => s.id === sel.value) || {}).schema);
    const wrap = document.getElementById('dispatch-payload');
    wrap.innerHTML = '<div id="payload-edit"></div>';
    if (editor) try { editor.destroy(); } catch (e) {}
    if (schema && window.JSONEditor) {
      editor = new JSONEditor(document.getElementById('payload-edit'), {
        schema: schema, theme: 'html', disable_collapse: true, disable_edit_json: false,
      });
    } else {
      wrap.innerHTML = '<textarea id="payload-raw" rows="5" style="width:100%">{}</textarea>';
      editor = null;
    }
  }

  function getPayload() {
    if (editor) return editor.getValue();
    try { return JSON.parse(document.getElementById('payload-raw').value); }
    catch (e) { throw new Error('Payload JSON 파싱 실패'); }
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
      const payload = getPayload();
      let skipped = [];
      if (mode === 'single') {
        const to = document.getElementById('dispatch-to').value;
        const res = await window.agoraApi.post('/dashboard/dispatch', {to, schema, payload, reply_only});
        skipped = res.skipped_full || [];
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

  return {render, refreshTargets};
})();
