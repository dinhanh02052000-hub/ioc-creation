document.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('root');
  if (root) {
    root.innerHTML = App();

    // Quay lại từ world1.html/world2.html sẽ có ?page=course -> mở đúng tab
    // Course thay vì luôn mặc định về Home. ?page=profile dùng khi lỗi AI
    // (chưa đăng nhập/hết key) điều hướng người dùng thẳng tới trang tài khoản.
    const params = new URLSearchParams(window.location.search);
    const validTargets = new Set(['home', 'course', 'analysis', 'profile']);
    const requestedTarget = params.get('page');
    const initialTarget = validTargets.has(requestedTarget) ? requestedTarget : 'home';

    const navBtns = document.querySelectorAll('.nav-btn');
    navBtns.forEach(b => b.classList.remove('active'));
    const initialBtn = document.querySelector(`.nav-btn[data-target="${initialTarget}"]`);
    if (initialBtn) initialBtn.classList.add('active');

    loadContent(initialTarget);

    initInteractions();

    // Khởi động bộ đếm tổng thời gian học toàn cục khi app load (chạy trên
    // tất cả trang, không dừng khi chuyển tab).
    if (typeof startPlaytimeTimer === 'function') {
      startPlaytimeTimer();
    }

    // Cập nhật số key hiển thị ở góc trên-phải header (guest luôn thấy 000).
    if (typeof initHeaderKeyBadge === 'function') {
      initHeaderKeyBadge();
    }
  }
});

function loadContent(target) {
  const contentArea = document.getElementById('main-content');
  if (!contentArea) return;

  if (typeof stopHomeDailyRefreshWatcher === 'function') {
    stopHomeDailyRefreshWatcher();
  }

  if (target === 'home' && typeof renderHome === 'function') {
    contentArea.innerHTML = renderHome();
    if (typeof initHomeInteractions === 'function') {
      initHomeInteractions();
    }
  } else if (target === 'course' && typeof renderCourse === 'function') {
    contentArea.innerHTML = renderCourse();
    if (typeof initCourseInteractions === 'function') {
      initCourseInteractions();
    }
  } else if (target === 'analysis' && typeof renderAnalysis === 'function') {
    contentArea.innerHTML = renderAnalysis();
    if (typeof initAnalysisInteractions === 'function') {
      initAnalysisInteractions();
    }
  } else if (target === 'profile' && typeof renderProfile === 'function') {
    contentArea.innerHTML = renderProfile();
    if (typeof initProfileInteractions === 'function') {
      initProfileInteractions();
    }
  } else {
    contentArea.innerHTML = `<div class="placeholder-page"><h2>Trang ${target.toUpperCase()} đang phát triển...</h2></div>`;
  }
}

function initInteractions() {
  const navBtns = document.querySelectorAll('.nav-btn');
  navBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      navBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      const target = btn.getAttribute('data-target');
      loadContent(target);
    });
  });

  initFeedbackWidget();
}

// Nút góp ý nổi, hiển thị xuyên suốt mọi trang (không phụ thuộc trang đang xem).
function initFeedbackWidget() {
  const fab = document.getElementById('feedback-fab');
  const panel = document.getElementById('feedback-panel');
  const closeBtn = document.getElementById('feedback-close-btn');
  const form = document.getElementById('feedback-form');
  if (!fab || !panel || !form) return;

  const openPanel = () => {
    panel.classList.add('open');
    document.getElementById('feedback-content').focus();
  };
  const closePanel = () => panel.classList.remove('open');

  fab.addEventListener('click', () => {
    panel.classList.contains('open') ? closePanel() : openPanel();
  });

  if (closeBtn) {
    closeBtn.addEventListener('click', closePanel);
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();

    const nameInput = document.getElementById('feedback-name');
    const contentInput = document.getElementById('feedback-content');
    const name = (nameInput.value || '').trim();
    const content = (contentInput.value || '').trim();

    if (!content) {
      contentInput.focus();
      return;
    }

    const subject = `[IOC] Góp ý từ ${name || 'người dùng'}`;
    const bodyLines = [];
    if (name) bodyLines.push(`Tên: ${name}`);
    bodyLines.push('');
    bodyLines.push(content);

    const mailtoUrl =
      `mailto:dinhanh02052000@gmail.com` +
      `?subject=${encodeURIComponent(subject)}` +
      `&body=${encodeURIComponent(bodyLines.join('\n'))}`;

    window.location.href = mailtoUrl;
    form.reset();
    closePanel();
  });
}