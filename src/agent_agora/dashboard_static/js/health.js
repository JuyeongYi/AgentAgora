// 서버 헬스 카드 — 헤더 inline summary + left panel expand 카드.
window.agoraHealth = (function() {
  let lastSnap = null;
  let lastSyncMs = 0;

  function fmtDuration(secs) {
    if (secs == null) return '?';
    if (secs < 60) return secs + 's';
    if (secs < 3600) return Math.floor(secs/60) + 'm';
    if (secs < 86400) return Math.floor(secs/3600) + 'h' + Math.floor((secs%3600)/60) + 'm';
    return Math.floor(secs/86400) + 'd';
  }

  function fmtBytes(b) {
    if (b == null) return '?';
    if (b < 1024) return b + 'B';
    if (b < 1024*1024) return Math.round(b/1024) + 'KB';
    if (b < 1024*1024*1024) return Math.round(b/1024/1024) + 'MB';
    return Math.round(b/1024/1024/1024 * 10)/10 + 'GB';
  }

  function update(serverSnap) {
    lastSnap = serverSnap;
    lastSyncMs = Date.now();
    render();
  }

  function render() {
    if (!lastSnap) return;
    const drift = Math.floor((Date.now() - lastSyncMs) / 1000);
    const uptime = (lastSnap.uptime_seconds || 0) + drift;
    const summary = document.getElementById('health-summary');
    if (summary) summary.textContent = `uptime ${fmtDuration(uptime)} | db ${fmtBytes(lastSnap.db_size_bytes)}`;

    const detail = document.getElementById('health-detail');
    if (detail) {
      detail.innerHTML = `
        <h3>서버 헬스</h3>
        <div>uptime: ${fmtDuration(uptime)}</div>
        <div>db: ${fmtBytes(lastSnap.db_size_bytes)}</div>
        <div>write queue: ${lastSnap.write_queue_depth ?? '?'}</div>
        <div>sweeper: ${lastSnap.sweeper_runs_total ?? '?'}회</div>`;
    }
  }

  // 1초마다 client-side 보간(uptime drift)
  setInterval(render, 1000);

  return {update};
})();
