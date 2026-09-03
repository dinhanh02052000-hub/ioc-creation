// ==== TRANG PROFILE ====
// Không bắt buộc đăng nhập mới học được - đăng nhập chỉ để backup/đồng bộ
// tiến độ (localStorage) lên server. Xem js/features/auth.js cho logic đăng
// nhập + đồng bộ, js/features/playtime.js cho tổng thời gian học (timer chạy
// toàn site, tự cập nhật #profile-total-playtime mỗi giây nếu đang mở trang
// này), js/features/theme.js cho chế độ sáng/tối, js/features/bg-music.js
// cho nhạc nền.
//
// Gộp chung 1 ô "TÀI KHOẢN + CÀI ĐẶT" theo yêu cầu, dưới cùng là hàng Đăng
// xuất + Xoá tài khoản (chỉ hiện khi đã đăng nhập).
//
// Tiểu sử ngắn do người học tự viết về bản thân - thay cho "Mục tiêu học mỗi
// ngày" đã bỏ. Lưu debounce khi gõ (giống pattern chỉnh tên hiển thị ở Home),
// đồng bộ tự động vì bắt đầu bằng "ioc_".
const USER_BIO_KEY = 'ioc_user_bio';
const USER_BIO_MAX_LENGTH = 200;

function getUserBio() {
  try {
    const saved = JSON.parse(localStorage.getItem(USER_BIO_KEY));
    return typeof saved === 'string' ? saved : '';
  } catch (e) {
    return '';
  }
}

function setUserBio(bio) {
  const trimmed = (bio || '').slice(0, USER_BIO_MAX_LENGTH);
  try {
    localStorage.setItem(USER_BIO_KEY, JSON.stringify(trimmed));
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function renderProfile() {
  return `
    <div class="placeholder-page profile-page">
      <h1 class="analysis-heading">Tài khoản của bạn</h1>
      <p class="profile-desc">
        Hãy đăng nhập vào Google để lưu tiến trình học của bạn. Ở dạng ẩn danh, tiến độ học sẽ
        không được lưu và sau này khi đăng nhập tiến độ cũng sẽ bị mất.
      </p>

      <div class="card profile-single-card">
        <div class="card-header"><span class="card-title">TÀI KHOẢN</span></div>
        <div id="auth-widget-area"></div>
        <div id="auth-error-area" class="ai-error" hidden></div>

        <div class="profile-section-divider"></div>

        <div class="card-header"><span class="card-title">CÀI ĐẶT</span></div>

        <div class="profile-setting-row">
          <div class="profile-setting-label">
            <span>Chế độ hiển thị</span>
            <span class="profile-setting-hint">Sáng / Tối</span>
          </div>
          <button id="theme-toggle-btn" class="profile-toggle-btn" type="button"></button>
        </div>

        <div class="profile-setting-row">
          <div class="profile-setting-label">
            <span>Nhạc nền</span>
            <span class="profile-setting-hint">Bật/tắt và chỉnh âm lượng</span>
          </div>
          <button id="music-mute-toggle" class="profile-toggle-btn" type="button"></button>
        </div>
        <div class="profile-setting-sub">
          <label for="music-volume-slider">Âm lượng nhạc nền</label>
          <input type="range" id="music-volume-slider" min="0" max="100" step="5">
        </div>
        <div class="profile-setting-sub">
          <label for="music-track-select">Bản nhạc nền</label>
          <select id="music-track-select"></select>
        </div>

        <div class="profile-setting-row">
          <div class="profile-setting-label">
            <span>Hiệu ứng âm thanh</span>
            <span class="profile-setting-hint">Phát khi bấm bất kỳ nút nào trên trang</span>
          </div>
          <button id="sfx-mute-toggle" class="profile-toggle-btn" type="button"></button>
        </div>
        <div class="profile-setting-sub">
          <label for="sfx-volume-slider">Âm lượng hiệu ứng</label>
          <input type="range" id="sfx-volume-slider" min="0" max="100" step="5">
        </div>
        <div class="profile-setting-sub">
          <label for="sfx-track-select">Âm thanh khi bấm nút</label>
          <div class="profile-inline-row">
            <select id="sfx-track-select"></select>
            <button id="sfx-preview-btn" class="profile-preview-btn" type="button" title="Nghe thử">▶</button>
          </div>
        </div>
      </div>

      <div id="profile-danger-zone" class="profile-danger-zone" hidden>
        <button id="auth-logout-btn" class="ai-btn" type="button">Đăng xuất</button>
        <button id="delete-account-btn" class="profile-delete-btn" type="button">Xoá tài khoản</button>
      </div>
    </div>
  `;
}

// ---------- Tài khoản (avatar/tên/email/tổng thời gian/level/daily goal) ----------

function profileTotalCompletedLevels() {
  if (typeof getWorldCompletedLevels !== 'function' || typeof COURSE_WORLDS === 'undefined') {
    return { completed: 0, total: 0 };
  }
  let completed = 0;
  let total = 0;
  COURSE_WORLDS.forEach(world => {
    completed += getWorldCompletedLevels(world.id);
    total += world.totalLevels;
  });
  return { completed, total };
}

function renderAuthWidget() {
  const area = document.getElementById('auth-widget-area');
  if (!area) return;

  const session = typeof getAuthSession === 'function' ? getAuthSession() : null;
  const { completed, total } = profileTotalCompletedLevels();
  const dangerZone = document.getElementById('profile-danger-zone');

  const identityHtml = session
    ? `
      <div class="profile-logged-in">
        <img alt="Avatar" class="profile-avatar" id="profile-avatar-img">
        <div class="profile-info">
          <div class="profile-name">${session.name || 'Người dùng'}</div>
          <div class="profile-email">${session.email || ''}</div>
        </div>
      </div>
    `
    : `
      <div class="profile-logged-in profile-logged-out">
        <img alt="Avatar" class="profile-avatar" id="profile-avatar-img">
        <div class="profile-info">
          <div class="profile-name">Guest</div>
          <div class="profile-email">Chưa đăng nhập</div>
        </div>
      </div>
      <div id="google-signin-btn" class="profile-signin-btn-area"></div>
    `;

  const currentBio = getUserBio();

  area.innerHTML = `
    ${identityHtml}
    <div class="profile-playtime-row">
      <span>Tổng thời gian học</span>
      <span class="profile-playtime-value" id="profile-total-playtime">0.0h</span>
    </div>
    <div class="profile-stat-list">
      <div class="profile-stat-row">
        <span>Level đã hoàn thành</span>
        <span class="profile-stat-value">${completed} / ${total}</span>
      </div>
      <div class="profile-stat-row">
        <span>Tài khoản Google</span>
        <span class="profile-stat-value ${session ? 'linked' : 'unlinked'}">${session ? 'Đã liên kết' : 'Chưa liên kết'}</span>
      </div>
    </div>
    <div class="profile-bio-block">
      <div class="profile-setting-label">
        <span>Tiểu sử</span>
        <span class="profile-setting-hint">Viết vài dòng về bản thân bạn</span>
      </div>
      <textarea id="profile-bio-input" class="profile-bio-textarea" maxlength="${USER_BIO_MAX_LENGTH}" placeholder="Mình là ai, mình đang học vì điều gì..."></textarea>
      <div class="profile-bio-counter"><span id="profile-bio-count">0</span>/${USER_BIO_MAX_LENGTH}</div>
    </div>
  `;

  const avatarImg = document.getElementById('profile-avatar-img');
  if (avatarImg) {
    avatarImg.src = typeof getEffectiveAvatarUrl === 'function' ? getEffectiveAvatarUrl() : (session && session.picture) || '';
    avatarImg.addEventListener('error', () => {
      if (typeof getDefaultAvatarDataUri === 'function') avatarImg.src = getDefaultAvatarDataUri();
    });
  }

  if (!session && typeof initGoogleAuth === 'function') {
    initGoogleAuth('google-signin-btn');
  }

  // Tiểu sử: gán qua .value (không chèn thẳng vào chuỗi HTML) để nội dung
  // người dùng tự viết không thể phá cấu trúc HTML. Lưu debounce khi gõ,
  // giống pattern đổi tên hiển thị ở Home.
  const bioInput = document.getElementById('profile-bio-input');
  const bioCount = document.getElementById('profile-bio-count');
  if (bioInput) {
    bioInput.value = currentBio;
    if (bioCount) bioCount.textContent = String(currentBio.length);

    let bioSaveTimer = null;
    bioInput.addEventListener('input', () => {
      if (bioCount) bioCount.textContent = String(bioInput.value.length);
      clearTimeout(bioSaveTimer);
      bioSaveTimer = setTimeout(() => setUserBio(bioInput.value), 500);
    });
    bioInput.addEventListener('blur', () => {
      clearTimeout(bioSaveTimer);
      setUserBio(bioInput.value);
    });
  }

  // Cập nhật tổng thời gian học ngay lần đầu (không đợi tick tiếp theo của
  // interval nền - xem js/features/playtime.js).
  if (typeof updatePlaytimeUI === 'function') updatePlaytimeUI();

  if (dangerZone) dangerZone.hidden = !session;
}

function renderAuthError(message) {
  const area = document.getElementById('auth-error-area');
  if (!area) return;
  area.hidden = false;
  area.textContent = message || 'Đăng nhập thất bại, thử lại sau.';
}

// ---------- Cài đặt (theme + nhạc nền + hiệu ứng âm thanh) ----------

function profileUpdateThemeButton(btn) {
  const current = typeof getTheme === 'function' ? getTheme() : 'dark';
  btn.textContent = current === 'light' ? 'Sáng' : 'Tối';
  btn.classList.toggle('is-on', current === 'light');
}

function profileUpdateMusicToggleButton(btn) {
  const muted = typeof isBgMusicMuted === 'function' ? isBgMusicMuted() : true;
  btn.textContent = muted ? 'Đang tắt' : 'Đang bật';
  btn.classList.toggle('is-on', !muted);
}

function profileUpdateSfxToggleButton(btn) {
  const muted = typeof isSfxMuted === 'function' ? isSfxMuted() : true;
  btn.textContent = muted ? 'Đang tắt' : 'Đang bật';
  btn.classList.toggle('is-on', !muted);
}

function initProfileSettings() {
  const themeBtn = document.getElementById('theme-toggle-btn');
  if (themeBtn) {
    profileUpdateThemeButton(themeBtn);
    themeBtn.addEventListener('click', () => {
      if (typeof toggleTheme === 'function') toggleTheme();
      profileUpdateThemeButton(themeBtn);
    });
  }

  const musicBtn = document.getElementById('music-mute-toggle');
  if (musicBtn) {
    profileUpdateMusicToggleButton(musicBtn);
    musicBtn.addEventListener('click', () => {
      const nowMuted = !(typeof isBgMusicMuted === 'function' && isBgMusicMuted());
      if (typeof setBgMusicMuted === 'function') setBgMusicMuted(nowMuted);
      if (nowMuted) {
        if (typeof bgMusicStop === 'function') bgMusicStop();
      } else if (typeof bgMusicStart === 'function') {
        bgMusicStart();
      }
      profileUpdateMusicToggleButton(musicBtn);
    });
  }

  const volumeSlider = document.getElementById('music-volume-slider');
  if (volumeSlider) {
    const currentVolume = typeof getBgMusicVolume === 'function' ? getBgMusicVolume() : 0.35;
    volumeSlider.value = String(Math.round(currentVolume * 100));
    volumeSlider.addEventListener('input', () => {
      const value = parseInt(volumeSlider.value, 10) / 100;
      if (typeof setBgMusicVolume === 'function') setBgMusicVolume(value);
    });
  }

  const trackSelect = document.getElementById('music-track-select');
  if (trackSelect && typeof BG_MUSIC_TRACKS !== 'undefined') {
    const trackOptionsHtml = BG_MUSIC_TRACKS
      .map(track => `<option value="${track.id}" ${track.available ? '' : 'disabled'}>${track.label}</option>`)
      .join('');
    const mixedOptionHtml = `<option value="${BG_MUSIC_MIXED_ID}">🔀 Mixed (ngẫu nhiên)</option>`;
    trackSelect.innerHTML = mixedOptionHtml + trackOptionsHtml;
    trackSelect.value = typeof getSelectedTrackId === 'function' ? getSelectedTrackId() : 'default';
    trackSelect.addEventListener('change', () => {
      if (typeof bgMusicChangeTrack === 'function') bgMusicChangeTrack(trackSelect.value);
    });
  }

  // ---- Hiệu ứng âm thanh (xem js/features/sound-effects.js) ----
  const sfxBtn = document.getElementById('sfx-mute-toggle');
  if (sfxBtn) {
    profileUpdateSfxToggleButton(sfxBtn);
    sfxBtn.addEventListener('click', () => {
      const nowMuted = !(typeof isSfxMuted === 'function' && isSfxMuted());
      if (typeof setSfxMuted === 'function') setSfxMuted(nowMuted);
      profileUpdateSfxToggleButton(sfxBtn);
    });
  }

  const sfxVolumeSlider = document.getElementById('sfx-volume-slider');
  if (sfxVolumeSlider) {
    const currentVolume = typeof getSfxVolume === 'function' ? getSfxVolume() : 0.5;
    sfxVolumeSlider.value = String(Math.round(currentVolume * 100));
    sfxVolumeSlider.addEventListener('input', () => {
      const value = parseInt(sfxVolumeSlider.value, 10) / 100;
      if (typeof setSfxVolume === 'function') setSfxVolume(value);
    });
  }

  const sfxSelect = document.getElementById('sfx-track-select');
  if (sfxSelect && typeof SFX_OPTIONS !== 'undefined') {
    sfxSelect.innerHTML = SFX_OPTIONS.map(opt => `<option value="${opt.id}">${opt.label}</option>`).join('');
    sfxSelect.value = typeof getSfxChoiceId === 'function' ? getSfxChoiceId() : 'click';
    sfxSelect.addEventListener('change', () => {
      if (typeof setSfxChoiceId === 'function') setSfxChoiceId(sfxSelect.value);
      if (typeof playSfxPreview === 'function') playSfxPreview(sfxSelect.value);
    });
  }

  const sfxPreviewBtn = document.getElementById('sfx-preview-btn');
  if (sfxPreviewBtn && sfxSelect) {
    sfxPreviewBtn.addEventListener('click', () => {
      if (typeof playSfxPreview === 'function') playSfxPreview(sfxSelect.value);
    });
  }
}

// ---------- Đăng xuất / Xoá tài khoản ----------

function initProfileDangerZone() {
  const logoutBtn = document.getElementById('auth-logout-btn');
  if (logoutBtn) {
    // authSignOut() tự reload trang sau khi xoá session + tiến độ cục bộ
    // (xem js/features/auth.js) nên không cần vẽ lại widget ở đây nữa.
    logoutBtn.addEventListener('click', () => {
      if (typeof authSignOut === 'function') authSignOut();
    });
  }

  const deleteBtn = document.getElementById('delete-account-btn');
  if (deleteBtn) {
    deleteBtn.addEventListener('click', async () => {
      const confirmed = window.confirm(
        'Xoá tài khoản sẽ xoá VĨNH VIỄN toàn bộ tiến độ đã lưu trên server (không thể khôi phục). '
        + 'Bạn có chắc chắn muốn xoá tài khoản này không?'
      );
      if (!confirmed) return;

      deleteBtn.disabled = true;
      deleteBtn.textContent = 'Đang xoá...';
      try {
        await authApiRequest('/api/auth/delete-account', 'DELETE');
        if (typeof clearAuthSession === 'function') clearAuthSession();
        if (typeof clearAllLocalProgressData === 'function') clearAllLocalProgressData();
        window.location.reload();
      } catch (e) {
        deleteBtn.disabled = false;
        deleteBtn.textContent = 'Xoá tài khoản';
        if (typeof renderAuthError === 'function') renderAuthError(e.message);
      }
    });
  }
}

function initProfileInteractions() {
  renderAuthWidget();
  initProfileSettings();
  initProfileDangerZone();
}
