// mode-aware 로그인 모달. /dashboard/auth-mode 호출해 token 필드 노출 여부 결정.
window.agoraLogin = (function() {
  let onAuthenticated = null;

  // JWT payload의 sub 클레임을 클라이언트에서 디코드(표시용 — 서명검증은 서버가 함).
  function jwtSub(t) {
    try {
      const b = t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      const json = decodeURIComponent(escape(atob(b)));
      return (JSON.parse(json).sub) || '';
    } catch (e) { return ''; }
  }

  async function init(callback) {
    onAuthenticated = callback;
    const user = localStorage.getItem('operator_username');
    const tok = localStorage.getItem('operator_token');
    const pw = localStorage.getItem('operator_basic_pw');

    // mode 확인
    const mode = await fetch('/dashboard/auth-mode').then(r => r.json()).then(j => j.mode).catch(() => 'trust');
    localStorage.setItem('operator_auth_mode', mode);  // api.js가 헤더 결정에 사용

    if (user && (mode === 'trust' || (mode === 'token' && tok) || (mode === 'basic' && pw) || (mode === 'jwt' && tok))) {
      // 이미 인증 정보 있음
      showApp(user);
      return;
    }
    showModal(mode);
  }

  function showModal(mode) {
    const modal = document.getElementById('login-modal');
    const tokLabel = document.getElementById('login-token-label');
    // token·basic·jwt 모드는 비밀 입력 필드를 노출(같은 password input 재사용).
    if (mode === 'token' || mode === 'basic' || mode === 'jwt') {
      tokLabel.classList.remove('hidden');
      // 라벨 텍스트만 교체(input 보존) — childNodes[0]이 선행 텍스트 노드.
      if (tokLabel.childNodes[0]) {
        const labels = {basic: 'Password ', jwt: 'JWT ', token: 'Token '};
        tokLabel.childNodes[0].nodeValue = labels[mode] || 'Token ';
      }
    } else {
      tokLabel.classList.add('hidden');
    }
    modal.classList.remove('hidden');

    document.getElementById('login-submit').onclick = () => submit(mode);
    document.getElementById('login-username').onkeydown = (e) => { if (e.key === 'Enter') submit(mode); };
    document.getElementById('login-token').onkeydown = (e) => { if (e.key === 'Enter') submit(mode); };
  }

  function submit(mode) {
    let user = document.getElementById('login-username').value.trim();
    const secret = document.getElementById('login-token').value;  // basic 비번은 trim 안 함
    // jwt 모드는 username을 JWT sub에서 도출(타이핑 불요).
    if (mode === 'jwt') {
      const jwt = secret.trim();
      if (!jwt) { alert('JWT 필수'); return; }
      user = jwtSub(jwt) || user;
      if (!user) { alert('JWT에서 sub를 읽지 못함'); return; }
      localStorage.setItem('operator_username', user);
      localStorage.setItem('operator_auth_mode', mode);
      localStorage.setItem('operator_token', jwt);  // api.js가 Bearer로 전송
      document.getElementById('login-modal').classList.add('hidden');
      showApp(user);
      return;
    }
    if (!user) { alert('username 필수'); return; }
    if (mode === 'token' && !secret.trim()) { alert('token 필수'); return; }
    if (mode === 'basic' && !secret) { alert('password 필수'); return; }
    localStorage.setItem('operator_username', user);
    localStorage.setItem('operator_auth_mode', mode);
    if (mode === 'token') localStorage.setItem('operator_token', secret.trim());
    if (mode === 'basic') localStorage.setItem('operator_basic_pw', secret);
    document.getElementById('login-modal').classList.add('hidden');
    showApp(user);
  }

  function showApp(user) {
    ['header', 'top-row', 'tabs', 'main'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.remove('hidden');
    });
    document.getElementById('who').textContent = 'operator:' + user;
    if (onAuthenticated) onAuthenticated(user);
  }

  function logout() {
    localStorage.removeItem('operator_username');
    localStorage.removeItem('operator_token');
    localStorage.removeItem('operator_basic_pw');
    localStorage.removeItem('operator_auth_mode');
    location.reload();
  }

  return {init, logout};
})();
