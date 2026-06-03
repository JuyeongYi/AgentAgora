// 스키마(msgtype)별 HTML 포맷 — 각 스키마의 템플릿은 별도 파일. 서버의
// GET /dashboard/format/<msgtype>가 런타임(agora_dir/formats/) → 동봉(패키지) 순으로
// 서빙하므로, 기본 스키마는 패키지 동봉분이, 런타임 등록 스키마는 agora_dir에 둔 파일이
// 쓰인다. preload()가 등록된 스키마 이름으로 각 파일을 불러 캐시하고, render(payload)가
// 동기로 템플릿을 보간한다(없으면 null → JSON 폴백).
//
// 템플릿 placeholder (모두 XSS-safe):
//   {{field}}       payload[field]를 escape한 텍스트
//   {{field|json}}  payload[field]가 있으면 <pre>로 JSON 표시, 없으면 빈 문자열
//   {{field|url}}   payload[field]를 encodeURIComponent (href 속성용)
window.agoraFormats = (function() {
  const cache = {};  // msgtype -> template string | null(파일 없음)

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }

  function interp(tpl, payload) {
    return tpl.replace(/\{\{([\w.]+)(\|json|\|url)?\}\}/g, (_, key, mod) => {
      const v = payload[key];
      if (mod === '|json') {
        return v == null ? '' : `<pre class="fmt-data">${esc(JSON.stringify(v, null, 2))}</pre>`;
      }
      if (mod === '|url') return encodeURIComponent(v == null ? '' : String(v));
      return esc(v == null ? '' : String(v));
    });
  }

  // 주어진 msgtype들의 템플릿 파일을 불러 캐시한다. 파일이 없으면(404) null로 캐시(폴백).
  // msgtypes 미지정 시 /dashboard/schemas에서 등록된 스키마 이름을 받아온다.
  async function preload(msgtypes) {
    if (!msgtypes) {
      try {
        const d = await window.agoraApi.get('/dashboard/schemas');
        msgtypes = (d.schemas || []).map(s => s.id);
      } catch (e) { msgtypes = []; }
    }
    await Promise.all(msgtypes.map(async mt => {
      if (mt in cache) return;
      try {
        const r = await fetch('/dashboard/format/' + encodeURIComponent(mt),
                              {cache: 'no-store'});
        cache[mt] = r.ok ? await r.text() : null;
      } catch (e) { cache[mt] = null; }
    }));
  }

  // payload → 템플릿 보간 HTML, 또는 해당 스키마 템플릿 파일이 없으면 null(JSON 폴백).
  function render(payload) {
    const mt = payload && payload.msgtype;
    const tpl = mt ? cache[mt] : null;
    return tpl ? interp(tpl, payload) : null;
  }

  return {preload, render, esc};
})();
