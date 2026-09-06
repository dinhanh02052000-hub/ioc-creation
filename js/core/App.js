// Bảng giá Key Shop + bonus theo mốc số lần đã mua (purchase count) - xem
// giải thích mốc ở getKeyShopBonusForCount(). purchase_count giờ lưu ở server
// (gắn với tài khoản Google, xem server/db.py) - PHẢI khớp CHÍNH XÁC với bảng
// _KEY_SHOP_PACKAGES ở server/main.py (server tự tính lại bonus khi mua, chỉ
// dùng bảng này để hiển thị đúng con số trước khi bấm mua).
const KEY_SHOP_PACKAGES = [
  { label: 'Gói nhỏ', price: '10.000 VNĐ', keys: 10, bonus10: 1, bonus20: 1, bonus50: 1 },
  { label: 'Gói vừa', price: '20.000 VNĐ', keys: 25, bonus10: 1, bonus20: 2, bonus50: 2 },
  { label: 'Gói 50', price: '35.000 VNĐ', keys: 50, bonus10: 2, bonus20: 3, bonus50: 5 },
  { label: 'Gói 100', price: '60.000 VNĐ', keys: 100, bonus10: 3, bonus20: 5, bonus50: 8 },
  { label: 'Gói 250', price: '135.000 VNĐ', keys: 250, bonus10: 5, bonus20: 10, bonus50: 15 },
  { label: 'Gói 500', price: '250.000 VNĐ', keys: 500, bonus10: 10, bonus20: 20, bonus50: 30 },
];

// Mốc ≥50 > ≥20 > ≥10 - đạt mốc nào cao nhất thì dùng bonus của mốc đó (KHÔNG
// cộng dồn cả 3 mốc lại với nhau).
function getKeyShopBonusForCount(pkg, purchaseCount) {
  if (purchaseCount >= 50) return pkg.bonus50;
  if (purchaseCount >= 20) return pkg.bonus20;
  if (purchaseCount >= 10) return pkg.bonus10;
  return 0;
}

function getKeyShopEffectiveAmount(pkg, purchaseCount) {
  return pkg.keys + getKeyShopBonusForCount(pkg, purchaseCount);
}

// purchaseCount: lấy từ /api/auth/me (field purchase_count) - main.js truyền
// vào mỗi khi mở Key Shop hoặc sau khi mua thành công. Mặc định 0 cho lần vẽ
// tĩnh đầu tiên lúc App() khởi tạo (modal đang ẩn, main.js sẽ vẽ lại đúng số
// thật ngay khi mở).
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

function App() {
  return `
    <div class="app-container">
      <header class="navbar">
        <div class="brand">
          <div class="logo-placeholder">
            <img src="assets/images/ioc-logo.jpg" alt="IOC Logo" class="logo-img">
          </div>
          <div class="brand-text">
            <span class="brand-title">IOC <span class="sub-title">ILLUSION OF COMPETENCE</span></span>
            <span class="brand-notice">Để kết quả được tối ưu, trong quá trình làm bài không dùng công cụ hoặc thiết bị hỗ trợ</span>
          </div>
          <div class="header-key-area">
            <div class="key-balance-pill" title="Số key còn lại (dùng để giới hạn tính năng AI)">
              <span class="key-balance-value" id="header-key-value">000</span>
              <span class="key-balance-icon"><img src="assets/images/key.png" alt="Key"></span>
            </div>
            <button type="button" class="key-topup-btn" id="key-topup-btn" title="Nạp thêm key">+</button>
          </div>
        </div>
        <nav class="nav-links">
          <button class="nav-btn active" data-target="home">
            <span class="title">HOME</span>
          </button>
          <button class="nav-btn" data-target="course">
            <span class="title">COURSE</span>
          </button>
          <button class="nav-btn" data-target="analysis">
            <span class="title">ANALYSIS</span>
          </button>
          <button class="nav-btn" data-target="profile">
            <span class="title">PROFILE</span>
          </button>
        </nav>
      </header>
      
      <!-- Khu vực hiển thị nội dung động -->
      <main id="main-content" class="content-area"></main>
    </div>

    <button id="feedback-fab" class="feedback-fab" type="button" title="Gửi góp ý">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4 5h16v10H8l-4 4V5z"/>
      </svg>
    </button>

    <div id="feedback-panel" class="feedback-panel">
      <div class="feedback-panel-header">
        <span class="feedback-panel-title">Góp ý / Feedback</span>
        <button id="feedback-close-btn" class="feedback-close-btn" type="button" aria-label="Đóng">✕</button>
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
          <button type="button" class="key-shop-close" id="key-shop-close" aria-label="Đóng">✕</button>
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