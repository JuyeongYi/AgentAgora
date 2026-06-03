// fetch wrapper — 인증 헤더 자동 첨부. mode에 따라 헤더 결정.
window.agoraApi = (function() {
  function b64utf8(s) {
    // UTF-8 안전 base64 (btoa는 latin1만) — 서버는 b64decode→utf-8 decode.
    return btoa(unescape(encodeURIComponent(s)));
  }

  function authHeaders() {
    const mode = localStorage.getItem('operator_auth_mode') || 'trust';
    const user = localStorage.getItem('operator_username') || '';
    if (mode === 'basic') {
      // Authorization: Basic <b64(user:pass)>. EventSource(SSE)는 헤더 불가라 basic
      // 모드에선 /dashboard/stream이 401 — 폴링으로 degrade(문서화됨).
      const pw = localStorage.getItem('operator_basic_pw') || '';
      return {'Authorization': 'Basic ' + b64utf8(user + ':' + pw)};
    }
    const tok = localStorage.getItem('operator_token') || '';
    const h = {'X-Agora-Operator-User': user};
    if (tok) h['Authorization'] = 'Bearer ' + tok;
    return h;
  }

  async function get(path) {
    const r = await fetch(path, {headers: authHeaders(), cache: 'no-store'});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.json();
  }

  async function post(path, body) {
    const r = await fetch(path, {
      method: 'POST',
      headers: {...authHeaders(), 'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const json = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error('HTTP ' + r.status), {status: r.status, body: json});
    return json;
  }

  return {get, post, authHeaders};
})();
