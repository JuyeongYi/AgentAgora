// fetch wrapper — 인증 헤더 자동 첨부. mode에 따라 헤더 결정.
window.agoraApi = (function() {
  function authHeaders() {
    const user = localStorage.getItem('operator_username') || '';
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
