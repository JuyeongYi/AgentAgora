// dispatch 모달 — 단일 워커 / 브로드캐스트, schema 선택, payload (JSONEditor), reply_only.
window.agoraDispatch = (function() {
  const modal = () => document.getElementById('dispatch-modal');
  let editor = null;
  let schemas = [];
  let instances = [];

  async function open() {
    schemas = (await window.agoraApi.get('/dashboard/schemas').catch(() => ({schemas:[]}))).schemas || [];
    const snap = await window.agoraApi.get('/dashboard/data').catch(() => ({instances:[]}));
    instances = snap.instances || [];

    modal().innerHTML = `
      <div class="modal-card">
        <h2>메시지 보내기</h2>
        <div>
          <label><input type="radio" name="dmode" value="single" checked>단일 워커</label>
          <label><input type="radio" name="dmode" value="broadcast">브로드캐스트</label>
        </div>
        <div id="dispatch-target"></div>
        <div>
          <label>Schema
            <select id="dispatch-schema">${schemas.map(s => `<option value="${s.id}">${s.id}</option>`).join('')}</select>
          </label>
        </div>
        <div>
          <label>Payload</label>
          <div id="dispatch-payload"></div>
        </div>
        <div>
          <label><input type="checkbox" id="dispatch-reply-only">reply_only (다른 워커로 forward 금지)</label>
        </div>
        <div>
          <button id="dispatch-send">보내기</button>
          <button id="dispatch-cancel">취소</button>
        </div>
      </div>`;
    modal().classList.remove('hidden');

    setupTargetPicker();
    setupPayloadEditor();
    document.getElementsByName('dmode').forEach(r => r.onchange = setupTargetPicker);
    document.getElementById('dispatch-schema').onchange = setupPayloadEditor;
    document.getElementById('dispatch-send').onclick = send;
    document.getElementById('dispatch-cancel').onclick = close;
  }

  function setupTargetPicker() {
    const mode = document.querySelector('input[name="dmode"]:checked').value;
    const wrap = document.getElementById('dispatch-target');
    if (mode === 'single') {
      wrap.innerHTML = `<label>To <select id="dispatch-to">${
        instances.map(i => `<option value="${i.instance_id}">${i.instance_id} (${i.role})</option>`).join('')
      }</select></label>`;
    } else {
      wrap.innerHTML = `<label>대상 워커</label>
        <div id="dispatch-targets-list">${
          instances.map(i => `<label><input type="checkbox" value="${i.instance_id}" checked> ${i.instance_id} (${i.role})</label>`).join('<br>')
        }</div>`;
    }
  }

  function setupPayloadEditor() {
    const sid = document.getElementById('dispatch-schema').value;
    const schema = (schemas.find(s => s.id === sid) || {}).schema;
    const wrap = document.getElementById('dispatch-payload');
    wrap.innerHTML = '<div id="payload-edit"></div>';
    if (editor) try { editor.destroy(); } catch(e) {}
    if (schema && window.JSONEditor) {
      editor = new JSONEditor(document.getElementById('payload-edit'), {
        schema: schema, theme: 'html', disable_collapse: true, disable_edit_json: false,
      });
    } else {
      wrap.innerHTML = '<textarea id="payload-raw" rows="6" style="width:100%">{}</textarea>';
      editor = null;
    }
  }

  function getPayload() {
    if (editor) return editor.getValue();
    try { return JSON.parse(document.getElementById('payload-raw').value); }
    catch (e) { throw new Error('Payload JSON 파싱 실패'); }
  }

  async function send() {
    try {
      const mode = document.querySelector('input[name="dmode"]:checked').value;
      const schema = document.getElementById('dispatch-schema').value;
      const reply_only = document.getElementById('dispatch-reply-only').checked;
      const payload = getPayload();
      if (mode === 'single') {
        const to = document.getElementById('dispatch-to').value;
        await window.agoraApi.post('/dashboard/dispatch', {to, schema, payload, reply_only});
      } else {
        const targets = Array.from(document.querySelectorAll('#dispatch-targets-list input:checked')).map(c => c.value);
        if (!targets.length) { alert('최소 1개 대상 선택'); return; }
        await window.agoraApi.post('/dashboard/broadcast', {targets, schema, payload, reply_only});
      }
      close();
    } catch (e) { alert('전송 실패: ' + e.message); }
  }

  function close() {
    modal().classList.add('hidden');
    if (editor) try { editor.destroy(); } catch(e) {}
    editor = null;
  }

  const fab = document.getElementById('open-dispatch');
  if (fab) fab.onclick = open;
  return {open, close};
})();
