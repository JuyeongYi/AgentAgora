// EventSource wrapper — SSE 연결 + 재연결 backoff + 폴링 fallback + indicator.
window.agoraStream = (function() {
  let eventSource = null;
  let pollHandle = null;
  let backoffMs = 5000;
  const POLL_INTERVAL = 3000;
  const onEvent = {}; // type → listener[]

  function setIndicator(state) {
    const el = document.getElementById('conn-indicator');
    if (!el) return;
    el.className = state; // 'connected' | 'fallback' | ''
    el.textContent = state === 'connected' ? '● SSE' : (state === 'fallback' ? '○ poll' : '… connect');
  }

  function fire(evt) {
    const handlers = onEvent[evt.type] || [];
    for (const h of handlers) try { h(evt); } catch(e) { console.error(e); }
  }

  function startPolling() {
    if (pollHandle) return;
    setIndicator('fallback');
    pollHandle = setInterval(async () => {
      try {
        const snap = await window.agoraApi.get('/dashboard/data');
        fire({type: 'data_snapshot', payload: snap});
      } catch (e) { /* indicator already shows fallback */ }
    }, POLL_INTERVAL);
  }

  function stopPolling() {
    if (pollHandle) { clearInterval(pollHandle); pollHandle = null; }
  }

  function connect() {
    setIndicator('');
    // EventSource는 헤더 첨부 못 함 (스펙 한계). 인증 쿼리파라미터 또는 cookie 폴백이 필요.
    // 본 spec 범위: trust 모드는 헤더 없이도 동작하도록 path-level query param fallback. token 모드는 cookie 또는 query.
    const user = encodeURIComponent(localStorage.getItem('operator_username') || '');
    const tok = encodeURIComponent(localStorage.getItem('operator_token') || '');
    const qs = `?u=${user}` + (tok ? `&t=${tok}` : '');
    eventSource = new EventSource('/dashboard/stream' + qs);

    eventSource.onopen = () => {
      backoffMs = 5000;
      stopPolling();
      setIndicator('connected');
    };
    eventSource.onmessage = (m) => {
      try {
        const evt = JSON.parse(m.data);
        fire(evt);
      } catch(e) { console.error('SSE parse', e); }
    };
    eventSource.onerror = () => {
      eventSource.close();
      eventSource = null;
      startPolling();
      // exponential backoff
      setTimeout(connect, backoffMs);
      backoffMs = Math.min(backoffMs * 2, 60000);
    };
  }

  function on(type, handler) {
    (onEvent[type] = onEvent[type] || []).push(handler);
  }

  return {connect, on};
})();
