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
      </form>
    </div>
  `;
}