// mode-aware 로그인 모달. /dashboard/auth-mode 호출해 token 필드 노출 여부 결정.
window.agoraLogin = (function() {
  let onAuthenticated = null;

  async function init(callback) {
    onAuthenticated = callback;
    const user = localStorage.getItem('operator_username');
    const tok = localStorage.getItem('operator_token');

    // mode 확인
    const mode = await fetch('/dashboard/auth-mode').then(r => r.json()).then(j => j.mode).catch(() => 'trust');

    if (user && (mode === 'trust' || tok)) {
      // 이미 인증 정보 있음
      showApp(user);
      return;
    }
    showModal(mode);
  }

  function showModal(mode) {
    const modal = document.getElementById('login-modal');
    const tokLabel = document.getElementById('login-token-label');
    if (mode === 'token') tokLabel.classList.remove('hidden'); else tokLabel.classList.add('hidden');
    modal.classList.remove('hidden');

    document.getElementById('login-submit').onclick = () => submit(mode);
    document.getElementById('login-username').onkeydown = (e) => { if (e.key === 'Enter') submit(mode); };
    document.getElementById('login-token').onkeydown = (e) => { if (e.key === 'Enter') submit(mode); };
  }

  function submit(mode) {
    const user = document.getElementById('login-username').value.trim();
    const tok = document.getElementById('login-token').value.trim();
    if (!user) { alert('username 필수'); return; }
    if (mode === 'token' && !tok) { alert('token 필수'); return; }
    localStorage.setItem('operator_username', user);
    if (tok) localStorage.setItem('operator_token', tok);
    document.getElementById('login-modal').classList.add('hidden');
    showApp(user);
  }

  function showApp(user) {
    document.getElementById('header').classList.remove('hidden');
    document.getElementById('main').classList.remove('hidden');
    document.getElementById('who').textContent = 'operator:' + user;
    if (onAuthenticated) onAuthenticated(user);
  }

  function logout() {
    localStorage.removeItem('operator_username');
    localStorage.removeItem('operator_token');
    location.reload();
  }

  return {init, logout};
})();
