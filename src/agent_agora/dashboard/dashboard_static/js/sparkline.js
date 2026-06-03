// 시계열 sparkline — /dashboard/metrics 폴링. 새 라이브러리 없이 inline-SVG polyline.
window.agoraSparkline = (function() {
  function escape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }

  // 값 배열 → SVG polyline 문자열 (순수 함수, 좌표만 계산).
  function spark(values, opts) {
    const o = opts || {};
    const w = o.width || 120, h = o.height || 24, pad = 2;
    const nums = (values || []).map(Number).filter(v => !Number.isNaN(v));
    if (nums.length === 0) return `<svg class="spark" width="${w}" height="${h}"></svg>`;
    const max = Math.max(...nums, 0.0001), min = Math.min(...nums, 0);
    const span = (max - min) || 1;
    const n = nums.length;
    const pts = nums.map((v, i) => {
      const x = n === 1 ? pad : pad + (w - 2 * pad) * i / (n - 1);
      const y = h - pad - (h - 2 * pad) * (v - min) / span;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">`
         + `<polyline class="spark-line" points="${pts}"/></svg>`;
  }

  function row(label, values, current, unit) {
    const cur = current == null ? '' : (typeof current === 'number'
      ? current.toFixed(unit === 'rate' ? 1 : 0) : current);
    return `<div class="spark-row"><span class="spark-label">${escape(label)}</span>`
         + spark(values)
         + `<span class="spark-cur">${escape(cur)}${unit === 'rate' ? '/m' : ''}</span></div>`;
  }

  function last(arr) { return (arr && arr.length) ? arr[arr.length - 1] : null; }

  async function refresh() {
    const panel = document.getElementById('metrics-panel');
    if (!panel) return;
    let m;
    try { m = await window.agoraApi.get('/dashboard/metrics'); }
    catch (e) { return; }
    const g = m.global || {};
    let html = '<h3>메트릭 (10초 샘플)</h3>';
    html += row('dispatch rate', g.dispatch_rate_per_min, last(g.dispatch_rate_per_min), 'rate');
    html += row('error rate', g.error_rate_per_min, last(g.error_rate_per_min), 'rate');
    html += row('총 인박스', g.total_inbox_depth, last(g.total_inbox_depth), 'count');
    const workers = m.workers || {};
    const ids = Object.keys(workers).sort();
    if (ids.length) {
      html += '<h4>워커 인박스 depth</h4>';
      ids.forEach(iid => {
        const wd = workers[iid] || {};
        html += row(iid, wd.inbox_depth, last(wd.inbox_depth), 'count');
      });
    }
    panel.innerHTML = html;
  }

  return {spark, refresh};
})();
