// Khung ứng dụng: sidebar (máy tính/tablet) + topbar + thanh điều hướng đáy
// (điện thoại). Thay cho header 2 hàng + 4 nút tab to trước đây. Logic mở/
// đóng sidebar, điều hướng, nối key-shop/feedback nằm ở main.js - file này
// chỉ lo phần render HTML tĩnh ban đầu.

// Phải khớp chính xác với _KEY_SHOP_PACKAGES ở server/main.py, vốn là nguồn
// tính bonus thật khi mua - bảng này chỉ dùng để hiển thị trước khi bấm mua.
const KEY_SHOP_PACKAGES = [
  { label: 'Gói nhỏ', price: '10.000 VNĐ', keys: 10, bonus10: 1, bonus20: 1, bonus50: 1 },
  { label: 'Gói vừa', price: '20.000 VNĐ', keys: 25, bonus10: 1, bonus20: 2, bonus50: 2 },
  { label: 'Gói 50', price: '35.000 VNĐ', keys: 50, bonus10: 2, bonus20: 3, bonus50: 5 },
  { label: 'Gói 100', price: '60.000 VNĐ', keys: 100, bonus10: 3, bonus20: 5, bonus50: 8 },
  { label: 'Gói 250', price: '135.000 VNĐ', keys: 250, bonus10: 5, bonus20: 10, bonus50: 15 },
  { label: 'Gói 500', price: '250.000 VNĐ', keys: 500, bonus10: 10, bonus20: 20, bonus50: 30 },
];

// Dùng bonus của mốc cao nhất đạt được, không cộng dồn các mốc.
function getKeyShopBonusForCount(pkg, purchaseCount) {
  if (purchaseCount >= 50) return pkg.bonus50;
  if (purchaseCount >= 20) return pkg.bonus20;
  if (purchaseCount >= 10) return pkg.bonus10;
  return 0;
}

function getKeyShopEffectiveAmount(pkg, purchaseCount) {
  return pkg.keys + getKeyShopBonusForCount(pkg, purchaseCount);
}

// Mặc định 0 chỉ dùng cho lần vẽ tĩnh lúc App() khởi tạo (modal đang ẩn);
// main.js sẽ vẽ lại với purchase_count thật ngay khi mở Key Shop.
function renderKeyShopPackages(purchaseCount = 0) {
  return KEY_SHOP_PACKAGES.map(p => `
    <div class="key-shop-package">
      <span class="key-shop-package-amount">+${getKeyShopEffectiveAmount(p, purchaseCount)} key</span>
      <span class="key-shop-package-icon"><img src="assets/images/key.png" alt="Key"></span>
      <span class="key-shop-package-price">${p.price}</span>
      <button type="button" class="key-shop-pay-btn" title="Sắp ra mắt">Thanh toán</button>
    </div>
  `).join('');
}

// Danh sách mục điều hướng DÙNG CHUNG cho sidebar và thanh đáy mobile (thanh
// đáy chỉ lấy 4 mục đầu đánh dấu primary:true - xem initBottomNav ở main.js).
const NAV_ITEMS = [
  { target: 'home', label: 'Trang chủ', icon: 'home', primary: true },
  { target: 'course', label: 'Lộ trình', icon: 'map', primary: true },
  { target: 'analysis', label: 'Phân tích', icon: 'chartLine', primary: true },
  { target: 'vocab', label: 'Từ đã học', icon: 'bookOpen', primary: false },
  { target: 'about', label: 'Giới thiệu', icon: 'info', primary: false, group: 'secondary' },
  { target: 'profile', label: 'Hồ sơ', icon: 'user', primary: true, group: 'secondary' },
];

function renderSidebarNavItem(item) {
  return `
    <button type="button" class="sidebar-nav-item" data-target="${item.target}" title="${item.label}">
      <span class="sidebar-nav-icon">${icon(item.icon, 20)}</span>
      <span class="sidebar-nav-label">${item.label}</span>
    </button>
  `;
}

function renderSidebar() {
  const mainItems = NAV_ITEMS.filter(i => i.group !== 'secondary').map(renderSidebarNavItem).join('');
  const secondaryItems = NAV_ITEMS.filter(i => i.group === 'secondary').map(renderSidebarNavItem).join('');

  return `
    <aside class="sidebar" id="app-sidebar">
      <div class="sidebar-top">
        <div class="sidebar-logo">
          <img src="assets/images/ioc-logo.jpg" alt="IOC Logo" class="sidebar-logo-img">
          <span class="sidebar-logo-text">IOC</span>
        </div>
        <button type="button" class="sidebar-toggle-btn" id="sidebar-toggle-btn"
          aria-label="Thu gọn thanh bên" aria-expanded="true" title="Thu gọn thanh bên (Ctrl/Cmd+B)">
          ${icon('panelLeftClose', 18)}
        </button>
      </div>

      <nav class="sidebar-nav">${mainItems}</nav>
      <div class="sidebar-spacer"></div>
      <nav class="sidebar-nav sidebar-nav-secondary">${secondaryItems}</nav>
    </aside>
    <div class="sidebar-overlay" id="sidebar-overlay"></div>
  `;
}

function renderTopbar() {
  return `
    <header class="topbar">
      <h1 class="topbar-title" id="topbar-title">Trang chủ</h1>
      <div class="topbar-right">
        <div class="key-balance-pill" id="header-key-pill" title="Key dùng để giới hạn số lượt dùng tính năng AI (sinh câu hỏi, chấm bài...)">
          <span class="key-balance-icon"><img src="assets/images/key.png" alt="Key"></span>
          <span class="key-balance-value" id="header-key-value">000</span>
        </div>
        <button type="button" class="key-topup-btn" id="key-topup-btn" title="Nạp thêm key">Nạp key</button>

        <div class="topbar-avatar-wrap" id="topbar-avatar-wrap">
          <button type="button" class="topbar-avatar-btn" id="topbar-avatar-btn" aria-haspopup="true" aria-expanded="false" aria-label="Menu tài khoản">
            <img alt="Ảnh đại diện" class="topbar-avatar-img" id="topbar-avatar-img">
          </button>
          <div class="topbar-avatar-menu" id="topbar-avatar-menu" hidden>
            <button type="button" class="topbar-avatar-menu-item" data-target="profile">${icon('user', 16)}<span>Hồ sơ</span></button>
            <button type="button" class="topbar-avatar-menu-item" id="topbar-settings-btn" data-target="profile">${icon('settings', 16)}<span>Cài đặt</span></button>
            <button type="button" class="topbar-avatar-menu-item" id="topbar-logout-btn">${icon('logOut', 16)}<span>Đăng xuất</span></button>
          </div>
        </div>
      </div>
    </header>
  `;
}

function renderBottomNav() {
  const items = NAV_ITEMS.filter(i => i.primary).map(item => `
    <button type="button" class="bottom-nav-item" data-target="${item.target}">
      <span class="bottom-nav-icon">${icon(item.icon, 22)}</span>
      <span class="bottom-nav-label">${item.label}</span>
    </button>
  `).join('');

  return `<nav class="bottom-nav" id="bottom-nav">${items}</nav>`;
}

function App() {
  return `
    <div class="app-shell">
      ${renderSidebar()}
      <div class="app-main">
        ${renderTopbar()}
        <main id="main-content" class="content-area"></main>
        <footer class="app-footer">
          <span>Illusion of Competence Detector là AI và có thể mắc sai lầm. Hãy kiểm tra kĩ lại thông tin nếu phát hiện bất thường.</span>
        </footer>
      </div>
    </div>
    ${renderBottomNav()}

    <button id="feedback-fab" class="feedback-fab" type="button" title="Gửi góp ý" aria-label="Gửi góp ý">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4 5h16v10H8l-4 4V5z"/>
      </svg>
    </button>

    <div id="feedback-panel" class="feedback-panel">
      <div class="feedback-panel-header">
        <span class="feedback-panel-title">Góp ý / Feedback</span>
        <button id="feedback-close-btn" class="feedback-close-btn" type="button" aria-label="Đóng">${icon('x', 16)}</button>
      </div>
      <p class="feedback-desc">Bạn có góp ý, phát hiện lỗi hay muốn đề xuất tính năng mới? Gửi cho tụi mình nhé!</p>
      <form id="feedback-form" class="feedback-form">
        <input type="text" id="feedback-name" class="feedback-input" placeholder="Tên của bạn (không bắt buộc)">
        <textarea id="feedback-content" class="feedback-textarea" rows="3" placeholder="Nội dung góp ý..." required></textarea>
        <button type="submit" class="feedback-submit-btn">Gửi góp ý</button>
        <p class="feedback-status" id="feedback-status" hidden></p>
      </form>
    </div>

    <div id="key-shop-overlay" class="key-shop-overlay">
      <div class="key-shop-panel">
        <div class="key-shop-header">
          <span class="key-shop-title">Key Shop</span>
          <button type="button" class="key-shop-close" id="key-shop-close" aria-label="Đóng">${icon('x', 16)}</button>
        </div>
        <div class="key-shop-body">
          <div id="key-shop-package-view">
            <p class="key-shop-notice">Mỗi bài test và retest sẽ trừ 2 key, tạo bài ôn tập trừ 1 key.</p>
            <div class="key-shop-packages">${renderKeyShopPackages()}</div>
            <div class="key-shop-purchase-count">
              <span>Số lần đã mua</span>
              <span class="key-shop-purchase-count-value" id="key-shop-purchase-count-value">0</span>
            </div>
          </div>

          <div id="key-shop-payment-view" hidden>
            <div class="key-shop-qr-wrap">
              <img id="key-shop-qr-img" class="key-shop-qr-img" alt="Mã QR thanh toán">
              <div id="key-shop-qr-fallback" class="key-shop-qr-fallback" hidden></div>
            </div>
            <div class="key-shop-payment-info">
              <div class="key-shop-payment-row">
                <span>Số tiền</span>
                <span id="key-shop-payment-amount">-</span>
              </div>
              <div class="key-shop-payment-row">
                <span>Mã đơn hàng</span>
                <span id="key-shop-payment-code">-</span>
              </div>
              <div class="key-shop-payment-row">
                <span>Còn lại</span>
                <span id="key-shop-payment-timer" class="key-shop-payment-timer">-</span>
              </div>
            </div>
            <p class="key-shop-payment-hint">Quét mã QR và chuyển khoản đúng số tiền trên. Nếu ứng dụng ngân hàng cho phép sửa nội dung, thêm mã đơn hàng ở trên vào để xử lý nhanh hơn (không bắt buộc).</p>
            <p class="key-shop-payment-status" id="key-shop-payment-status">Đang chờ chuyển khoản...</p>
            <button type="button" class="key-shop-cancel-btn" id="key-shop-cancel-btn">Huỷ</button>
          </div>
        </div>
      </div>
    </div>
  `;
}
