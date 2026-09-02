const USER_NAME_KEY = 'ioc_user_name';
const DEFAULT_USER_NAME = 'Anh';

function getUserName() {
  try {
    const saved = localStorage.getItem(USER_NAME_KEY);
    return saved && saved.trim() ? saved.trim() : DEFAULT_USER_NAME;
  } catch (e) {
    return DEFAULT_USER_NAME;
  }
}

function setUserName(name) {
  const trimmed = (name || '').trim();
  try {
    localStorage.setItem(USER_NAME_KEY, trimmed || DEFAULT_USER_NAME);
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function getDayOfYear() {
  const now = new Date();
  const start = new Date(now.getFullYear(), 0, 0);
  const diff = now - start;
  const oneDay = 1000 * 60 * 60 * 24;
  return Math.floor(diff / oneDay);
}

// Ngày (theo giờ local) mà renderHome() đã dùng để chọn quote/tip lần gần nhất.
// Dùng để phát hiện đã sang ngày mới khi trang Home vẫn đang mở (xem
// refreshDailyContentIfDateChanged bên dưới).
let homeRenderedDate = null;
let homeDailyCheckIntervalId = null;

function renderHome() {
  const dayOfYear = getDayOfYear();

  const quoteIndex = (dayOfYear - 1) % QUOTES_LIST.length;
  const tipIndex = (dayOfYear - 1) % TIPS_LIST.length;

  const todayQuote = QUOTES_LIST[quoteIndex];
  const todayTip = TIPS_LIST[tipIndex];
  const userName = getUserName();

  if (typeof getTodayDateString === 'function') {
    homeRenderedDate = getTodayDateString();
  }

  return `
    <div class="home-dashboard">
      <!-- Cột trái: Streak -->
      <div class="left-column">
        <div class="card streak-card">
          <div class="card-header">
            <span class="card-title">STREAK</span>
            <span class="badge inactive" id="streak-badge">Chưa kích hoạt (00:00/10:00)</span>
          </div>
          <div class="streak-main">
            <div class="streak-number" id="streak-number">0 DAY</div>
            <span class="status-tag" id="streak-status-tag">Chờ học 10p</span>
          </div>
          <p class="sub-text">LEARNING STREAK</p>
          
          <div class="progress-section">
            <div class="progress-info">
              <span>Hoạt động hôm nay:</span>
              <span id="streak-progress-current">00:00 / 10:00</span>
            </div>
            <div class="progress-bar">
              <div class="progress-fill" id="streak-progress-fill" style="width: 0%;"></div>
            </div>
              <p class="hint-text" id="streak-hint-text">Còn 10:00 để kích hoạt Streak</p>
          </div>

          <div class="mascot-container">
            <svg class="mascot-robot" viewBox="0 0 140 130" xmlns="http://www.w3.org/2000/svg">
              <line class="mascot-antenna" x1="68" y1="12" x2="68" y2="26" />
              <circle class="mascot-antenna-dot" cx="68" cy="12" r="5" />

              <rect class="mascot-shell" x="34" y="26" width="68" height="48" rx="17" />
              <rect class="mascot-eye" x="51" y="45" width="9" height="13" rx="4.5" />
              <rect class="mascot-eye" x="76" y="45" width="9" height="13" rx="4.5" />
              <path class="mascot-mouth" d="M54 64 q14 10 28 0" />

              <rect class="mascot-shell" x="46" y="78" width="44" height="36" rx="15" />
              <rect class="mascot-shell" x="22" y="90" width="15" height="24" rx="7" />

              <g class="mascot-wave">
                <path class="mascot-arm" d="M90 90 Q104 70 112 52" />
                <path class="mascot-arm-fill" d="M90 90 Q104 70 112 52" />
                <circle class="mascot-shell" cx="112" cy="52" r="8" />
                <line class="mascot-finger" x1="106" y1="46" x2="101" y2="35" />
                <line class="mascot-finger" x1="112" y1="43" x2="112" y2="30" />
                <line class="mascot-finger" x1="118" y1="46" x2="123" y2="35" />
              </g>
            </svg>
          </div>
        </div>
      </div>

      <!-- Cột giữa: Quote & Tip tự động thay đổi theo ngày -->
      <div class="middle-column">
        <div class="card quote-card">
          <div class="card-header">
            <span class="card-title">QUOTE OF THE DAY</span>
            <span class="badge">Daily Rotation</span>
          </div>
          <p class="quote-content">"${todayQuote.en}"</p>
          <div class="card-footer">
            <span class="tag">${todayQuote.vi}</span>
            <span class="author">— ${todayQuote.author}</span>
          </div>
        </div>

        <div class="card tip-card">
          <div class="card-header">
            <span class="card-title">TIP OF THE DAY</span>
            <span class="badge">Daily Rotation</span>
          </div>
          <p class="tip-content">${todayTip.text}</p>
          <div class="card-footer">
            <span class="tip-id">Tip #${tipIndex + 1}</span>
            <span class="tag">${todayTip.category}</span>
          </div>
        </div>
      </div>

      <!-- Cột phải: Welcome & Developer -->
      <div class="right-column">
        <div class="card welcome-card">
          <p class="welcome-subtitle">WELCOME BACK, LEARNER!</p>
          <h2 class="welcome-title">
            <span id="user-name-display" contenteditable="true" spellcheck="false">${userName}</span>
            <button id="edit-name-btn" class="edit-name-btn" title="Đổi tên hiển thị" type="button">
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M13.5 3.5a1.5 1.5 0 0 1 2.12 0l0.88 0.88a1.5 1.5 0 0 1 0 2.12L6.5 16.5 3 17.5l1-3.5L13.5 3.5z"/>
              </svg>
            </button>
          </h2>
        </div>

        <div class="card dev-card">
          <div class="card-header">
            <span class="card-title">DEVELOPER</span>
          </div>
          <h3 class="dev-heading">Tiểu ban AI trường THPT Hạ Hoà</h3>
          <p class="dev-subheading">HA HOA HIGH SCHOOL - AI INNOVATION GROUP</p>
          
          <div class="dev-body">
            <div class="dev-logo-placeholder" id="dev-logo-placeholder">
              <img src="assets/images/stem-logo.jpg" alt="STEM Club THPT Hạ Hòa" class="dev-logo-img" id="dev-logo-img">
            </div>
            <blockquote class="dev-quote">
              "Vượt qua ảo tưởng về năng lực, chuyển hoá trí thức thành hành động thực tế. Tiên phong ứng dụng Trí tuệ Nhân tạo để nâng tầm tư duy và làm chủ tương lai số."
              <footer>— Lời ngỏ từ Tiểu ban AI <span class="motto">See Beyond. Improve Truly.</span></footer>
            </blockquote>
          </div>
        </div>
      </div>
    </div>
  `;
}

// Gắn các sự kiện tương tác cho trang Home. Gọi hàm này SAU KHI renderHome()
// đã được chèn vào DOM (main.js gọi hàm này trong loadContent()).
function initHomeInteractions() {
  // --- Cho phép đổi tên hiển thị ở "WELCOME BACK" ---
  const nameDisplay = document.getElementById('user-name-display');
  const editBtn = document.getElementById('edit-name-btn');

  if (nameDisplay) {
    nameDisplay.addEventListener('blur', () => {
      setUserName(nameDisplay.textContent);
      nameDisplay.textContent = getUserName();
    });
    nameDisplay.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        nameDisplay.blur();
      }
    });
  }

  if (editBtn && nameDisplay) {
    editBtn.addEventListener('click', () => {
      nameDisplay.focus();
      const range = document.createRange();
      range.selectNodeContents(nameDisplay);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    });
  }

  // --- Ảnh logo Developer bị lỗi -> hiển thị fallback thay vì icon vỡ ---
  const devImg = document.getElementById('dev-logo-img');
  if (devImg) {
    devImg.addEventListener(
      'error',
      () => {
        const placeholder = document.getElementById('dev-logo-placeholder');
        devImg.remove();
        if (placeholder && !placeholder.querySelector('.dev-logo-fallback')) {
          const fallback = document.createElement('span');
          fallback.className = 'dev-logo-fallback';
          fallback.textContent = 'STEM';
          placeholder.appendChild(fallback);
        }
      },
      { once: true }
    );
  }

  // --- Khởi động bộ đếm streak ---
  if (typeof startStreakTimer === 'function') {
    startStreakTimer();
  }

  // --- Theo dõi để quote/tip tự cập nhật khi sang ngày mới mà trang Home
  // vẫn đang mở (không cần bấm chuyển tab hoặc F5) ---
  startHomeDailyRefreshWatcher();
}

// Nếu ngày hiện tại (giờ local) khác với ngày lúc renderHome() chạy lần cuối,
// nghĩa là đã qua 0h -> cập nhật lại quote/tip trên DOM mà không render lại
// cả trang (tránh mất trạng thái đang sửa tên hiển thị).
function refreshDailyContentIfDateChanged() {
  if (typeof getTodayDateString !== 'function') return;
  const today = getTodayDateString();
  if (today === homeRenderedDate) return;
  homeRenderedDate = today;

  const dayOfYear = getDayOfYear();
  const quoteIndex = (dayOfYear - 1) % QUOTES_LIST.length;
  const tipIndex = (dayOfYear - 1) % TIPS_LIST.length;
  const todayQuote = QUOTES_LIST[quoteIndex];
  const todayTip = TIPS_LIST[tipIndex];

  const quoteContentEl = document.querySelector('.quote-card .quote-content');
  const quoteTagEl = document.querySelector('.quote-card .tag');
  const quoteAuthorEl = document.querySelector('.quote-card .author');
  const tipContentEl = document.querySelector('.tip-card .tip-content');
  const tipIdEl = document.querySelector('.tip-card .tip-id');
  const tipTagEl = document.querySelector('.tip-card .tag');

  if (quoteContentEl) quoteContentEl.textContent = `"${todayQuote.en}"`;
  if (quoteTagEl) quoteTagEl.textContent = todayQuote.vi;
  if (quoteAuthorEl) quoteAuthorEl.textContent = `— ${todayQuote.author}`;
  if (tipContentEl) tipContentEl.textContent = todayTip.text;
  if (tipIdEl) tipIdEl.textContent = `Tip #${tipIndex + 1}`;
  if (tipTagEl) tipTagEl.textContent = todayTip.category;
}

function startHomeDailyRefreshWatcher() {
  stopHomeDailyRefreshWatcher();
  // Kiểm tra mỗi 30s là đủ nhanh để cảm giác "tự động" mà không tốn tài nguyên.
  homeDailyCheckIntervalId = setInterval(refreshDailyContentIfDateChanged, 30000);
}

function stopHomeDailyRefreshWatcher() {
  if (homeDailyCheckIntervalId) {
    clearInterval(homeDailyCheckIntervalId);
    homeDailyCheckIntervalId = null;
  }
}