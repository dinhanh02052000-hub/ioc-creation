// ==== TRANG PROFILE: đăng nhập Google để đồng bộ/lưu tiến độ ====
// Không bắt buộc đăng nhập mới học được - đây chỉ là lớp backup/đồng bộ tiến
// độ (localStorage) lên server, phòng khi đổi trình duyệt/máy hoặc xoá dữ
// liệu trình duyệt. Xem js/features/auth.js cho logic đăng nhập + đồng bộ.

function renderProfile() {
  return `
    <div class="placeholder-page profile-page">
      <h1 class="analysis-heading">Tài khoản của bạn</h1>
      <p class="profile-desc">
        Hãy đăng nhập vào Google để lưu tiến trình học của bạn. Ở dạng ẩn danh, tiến độ học sẽ
        không được lưu và sau này khi đăng nhập tiến độ cũng sẽ bị mất.
      </p>
      <div class="card profile-card">
        <div id="auth-widget-area"></div>
        <div id="auth-error-area" class="ai-error" hidden></div>
      </div>
    </div>
  `;
}

function renderAuthWidget() {
  const area = document.getElementById('auth-widget-area');
  if (!area) return;

  const session = typeof getAuthSession === 'function' ? getAuthSession() : null;

  if (session) {
    area.innerHTML = `
      <div class="profile-logged-in">
        ${session.picture ? `<img src="${session.picture}" alt="Avatar" class="profile-avatar">` : ''}
        <div class="profile-info">
          <div class="profile-name">${session.name || 'Người dùng'}</div>
          <div class="profile-email">${session.email || ''}</div>
        </div>
        <button id="auth-logout-btn" class="ai-btn" type="button">Đăng xuất</button>
      </div>
    `;
    const logoutBtn = document.getElementById('auth-logout-btn');
    if (logoutBtn) {
      // authSignOut() tự reload trang sau khi xoá session + tiến độ cục bộ
      // (xem js/features/auth.js) nên không cần vẽ lại widget ở đây nữa.
      logoutBtn.addEventListener('click', () => {
        if (typeof authSignOut === 'function') authSignOut();
      });
    }
  } else {
    area.innerHTML = `
      <p class="profile-signin-desc">Chưa đăng nhập - tiến độ hiện tại chỉ lưu trên trình duyệt này.</p>
      <div id="google-signin-btn"></div>
    `;
    if (typeof initGoogleAuth === 'function') initGoogleAuth('google-signin-btn');
  }
}

function renderAuthError(message) {
  const area = document.getElementById('auth-error-area');
  if (!area) return;
  area.hidden = false;
  area.textContent = message || 'Đăng nhập thất bại, thử lại sau.';
}

function initProfileInteractions() {
  renderAuthWidget();
}
