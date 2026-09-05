const USER_NAME_KEY = 'ioc_user_name';
const DEFAULT_USER_NAME = 'Guest';

function getUserName() {
  try {
    // Lưu ý: PHẢI JSON.parse vì mọi key "ioc_*" được đồng bộ lên server đều
    // giả định giá trị là JSON hợp lệ (xem collectLocalProgressData ở
    // auth.js) - lưu chuỗi thô sẽ khiến JSON.parse ở đó lỗi và bị âm thầm bỏ
    // qua, tên đặt sẽ không bao giờ đồng bộ được (đây từng là 1 lỗi thật).
    const saved = JSON.parse(localStorage.getItem(USER_NAME_KEY));
    return typeof saved === 'string' && saved.trim() ? saved.trim() : DEFAULT_USER_NAME;
  } catch (e) {
    return DEFAULT_USER_NAME;
  }
}

function setUserName(name) {
  const trimmed = (name || '').trim();
  try {
    localStorage.setItem(USER_NAME_KEY, JSON.stringify(trimmed || DEFAULT_USER_NAME));
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

// Ảnh mặc định khi chưa đăng nhập (hoặc ảnh Google bị lỗi) - vẽ trực tiếp
// bằng SVG (data URI) thay vì dùng file ảnh, luôn có sẵn không cần tải.
function getDefaultAvatarDataUri() {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">'
    + '<circle cx="20" cy="20" r="20" fill="#1c2129"/>'
    + '<circle cx="20" cy="16.5" r="7.2" fill="#6e7681"/>'
    + '<path d="M6.5 34.5c1.3-8.4 7.6-13 13.5-13s12.2 4.6 13.5 13" fill="#6e7681"/>'
    + '</svg>';
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

// Ảnh Google của tài khoản đang đăng nhập (lấy mới mỗi lần đăng nhập, không
// có ảnh riêng nào để tự đặt) - chưa đăng nhập thì dùng ảnh mặc định.
function getEffectiveAvatarUrl() {
  if (typeof getAuthSession === 'function') {
    const session = getAuthSession();
    if (session && session.picture) return session.picture;
  }
  return getDefaultAvatarDataUri();
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
      <!-- Cột trái: mascot IOC (thay cho Streak đã bỏ) -->
      <div class="left-column">
        <div class="card mascot-card">
          <div class="card-header">
            <span class="card-title">MEET IOC</span>
          </div>
          <p class="sub-text">TRỢ LÝ HỌC TẬP CỦA BẠN</p>

          <div class="mascot-container">
            <svg class="mascot-robot" viewBox="0 0 140 130" xmlns="http://www.w3.org/2000/svg">
              <path class="mascot-cape" d="M46 76 Q28 96 32 120 L48 106 Q68 116 90 106 L106 120 Q110 96 92 76 Z" />

              <line class="mascot-antenna" x1="68" y1="12" x2="68" y2="26" />
              <circle class="mascot-antenna-dot" cx="68" cy="12" r="5" />

              <rect class="mascot-shell" x="34" y="26" width="68" height="48" rx="17" />

              <g class="mascot-cap">
                <path class="mascot-cap-top" d="M68 4 L102 19 L68 34 L34 19 Z" />
                <rect class="mascot-cap-band" x="50" y="19" width="36" height="9" rx="3" />
                <line class="mascot-cap-string" x1="102" y1="19" x2="102" y2="33" />
                <circle class="mascot-cap-tassel" cx="102" cy="35" r="3" />
              </g>

              <rect class="mascot-eye" x="51" y="45" width="9" height="13" rx="4.5" />
              <path class="mascot-eye-wink" d="M76 51 q4.5 4 9 0" />
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

          <div class="mascot-speech-bubble">
            <p>Chào bạn! Mình là IOC — luôn sẵn sàng đồng hành cùng bạn chinh phục từ vựng mỗi ngày! 🚀</p>
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
          <div class="welcome-row">
            <div class="welcome-avatar-wrap">
              <img alt="Ảnh đại diện" class="welcome-avatar" id="welcome-avatar-img">
            </div>
            <div class="welcome-text">
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
          </div>
        </div>

        <div class="card dev-card">
          <div class="card-header">
            <span class="card-title">MEET THE FOUNDER</span>
          </div>

          <div class="founder-row">
            <div class="founder-member">
              <img src="assets/images/founder-dinhanh.jpg" alt="Đinh Việt Anh" class="founder-avatar">
              <div class="founder-role">Trưởng nhóm</div>
              <div class="founder-name">Đinh Việt Anh</div>
            </div>
            <div class="founder-member">
              <img src="assets/images/founder-tuan.jpg" alt="Nguyễn Minh Tuấn" class="founder-avatar">
              <div class="founder-role">Thành viên</div>
              <div class="founder-name">Nguyễn Minh Tuấn</div>
            </div>
            <div class="founder-member">
              <img src="assets/images/founder-hanlinh.jpg" alt="Hán Linh Linh" class="founder-avatar">
              <div class="founder-role">Thành viên</div>
              <div class="founder-name">Hán Linh Linh</div>
            </div>
          </div>

          <div class="dev-divider"></div>

          <blockquote class="dev-quote">
            Cảm ơn bạn đã trải nghiệm IOC! Mong rằng hệ thống của chúng mình sẽ luôn là người bạn đồng hành đáng tin cậy, giúp bạn làm chủ kiến thức mỗi ngày.
            <footer>— Lời nhắn từ tác giả <span class="motto">See you Beyond, Improve Truly.</span></footer>
          </blockquote>
        </div>
      </div>

      <div class="ai-disclaimer">
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="10" cy="10" r="7.5"/>
          <line x1="10" y1="6.5" x2="10" y2="10.5"/>
          <circle cx="10" cy="13.3" r="0.15" fill="currentColor" stroke-width="1.2"/>
        </svg>
        <span>Illusion of Competence Detector là AI và có thể mắc sai lầm. Hãy kiểm tra kĩ lại thông tin nếu phát hiện bất thường.</span>
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

  // --- Ảnh đại diện: lấy trực tiếp ảnh Google của tài khoản đang đăng nhập,
  // không có ảnh riêng thì hiện ảnh mặc định (không cho tự đặt link nữa). ---
  const avatarImg = document.getElementById('welcome-avatar-img');
  if (avatarImg) {
    avatarImg.src = getEffectiveAvatarUrl();
    avatarImg.addEventListener('error', () => {
      avatarImg.src = getDefaultAvatarDataUri();
    });
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