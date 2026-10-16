// Nhãn hiển thị ở tiêu đề topbar + title cho từng mục - dùng chung giữa
// sidebar, thanh đáy và topbar nên khai báo 1 chỗ.
const PAGE_TITLES = {
  home: 'Trang chủ',
  course: 'Lộ trình',
  analysis: 'Phân tích',
  vocab: 'Từ đã học',
  about: 'Giới thiệu',
  profile: 'Hồ sơ',
};

document.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('root');
  if (root) {
    root.innerHTML = App();

    // ?page=<tab> cho phép mở thẳng đúng tab (vd. quay lại từ world1/world2.html
    // về Lộ trình, hoặc điều hướng tới Hồ sơ khi AI báo lỗi chưa đăng nhập/hết key).
    const params = new URLSearchParams(window.location.search);
    const validTargets = new Set(Object.keys(PAGE_TITLES));
    const requestedTarget = params.get('page');
    const initialTarget = validTargets.has(requestedTarget) ? requestedTarget : 'home';

    setActiveNavTarget(initialTarget);
    loadContent(initialTarget);

    initInteractions();
    initSidebar();

    // Bộ đếm thời gian học chạy toàn cục, không dừng khi chuyển tab.
    if (typeof startPlaytimeTimer === 'function') {
      startPlaytimeTimer();
    }

    if (typeof initHeaderKeyBadge === 'function') {
      initHeaderKeyBadge();
    }
  }
});

function setActiveNavTarget(target) {
  document.querySelectorAll('.sidebar-nav-item, .bottom-nav-item').forEach(el => {
    el.classList.toggle('active', el.getAttribute('data-target') === target);
  });
  const titleEl = document.getElementById('topbar-title');
  if (titleEl) titleEl.textContent = PAGE_TITLES[target] || '';
  document.body.dataset.page = target;
}

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
  } else if (target === 'vocab' && typeof renderVocab === 'function') {
    contentArea.innerHTML = renderVocab();
    if (typeof initVocabInteractions === 'function') {
      initVocabInteractions();
    }
  } else if (target === 'about' && typeof renderAbout === 'function') {
    contentArea.innerHTML = renderAbout();
  } else if (target === 'profile' && typeof renderProfile === 'function') {
    contentArea.innerHTML = renderProfile();
    if (typeof initProfileInteractions === 'function') {
      initProfileInteractions();
    }
  } else {
    contentArea.innerHTML = `<div class="placeholder-page"><h2>Trang ${target} đang phát triển...</h2></div>`;
  }

  contentArea.scrollTo(0, 0);
}

function navigateTo(target) {
  setActiveNavTarget(target);
  loadContent(target);
  closeMobileSidebar();
  closeAvatarMenu();
}

function initInteractions() {
  document.querySelectorAll('.sidebar-nav-item, .bottom-nav-item').forEach(btn => {
    btn.addEventListener('click', () => navigateTo(btn.getAttribute('data-target')));
  });

  initFeedbackWidget();
  initKeyShopWidget();
  initAvatarMenu();
}

// ==== Sidebar: thu gọn/mở rộng + overlay mobile ====
// Trạng thái lưu localStorage nên giữ nguyên qua lần tải trang sau - khoá
// KHÔNG prefix "ioc_" vì đây là sở thích hiển thị riêng trình duyệt, không
// cần đồng bộ lên tài khoản (giống sfx_muted ở sound-effects.js).
const SIDEBAR_STATE_KEY = 'ioc.sidebar';

function getSidebarState() {
  try {
    const v = localStorage.getItem(SIDEBAR_STATE_KEY);
    return v === 'collapsed' ? 'collapsed' : 'expanded';
  } catch (e) {
    return 'expanded';
  }
}

function setSidebarState(state) {
  try {
    localStorage.setItem(SIDEBAR_STATE_KEY, state);
  } catch (e) {
    // localStorage không khả dụng -> chỉ áp dụng cho phiên hiện tại
  }
}

function applySidebarState(state) {
  const sidebar = document.getElementById('app-sidebar');
  const toggleBtn = document.getElementById('sidebar-toggle-btn');
  const shell = document.querySelector('.app-shell');
  if (!sidebar || !toggleBtn || !shell) return;

  const collapsed = state === 'collapsed';
  shell.classList.toggle('sidebar-collapsed', collapsed);
  toggleBtn.innerHTML = icon(collapsed ? 'panelLeftOpen' : 'panelLeftClose', 18);
  toggleBtn.setAttribute('aria-expanded', String(!collapsed));
  toggleBtn.setAttribute('aria-label', collapsed ? 'Mở rộng thanh bên' : 'Thu gọn thanh bên');
  toggleBtn.title = (collapsed ? 'Mở rộng thanh bên' : 'Thu gọn thanh bên') + ' (Ctrl/Cmd+B)';
}

function toggleSidebar() {
  const next = getSidebarState() === 'collapsed' ? 'expanded' : 'collapsed';
  setSidebarState(next);
  applySidebarState(next);
}

function openMobileSidebar() {
  document.querySelector('.app-shell')?.classList.add('sidebar-mobile-open');
}

function closeMobileSidebar() {
  document.querySelector('.app-shell')?.classList.remove('sidebar-mobile-open');
}

function initSidebar() {
  applySidebarState(getSidebarState());

  const toggleBtn = document.getElementById('sidebar-toggle-btn');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      // Dưới 1024px, sidebar luôn ở dạng overlay (CSS tự ẩn) - nút toggle lúc
      // đó chỉ có tác dụng mở/đóng overlay, không đổi trạng thái lưu lại.
      if (window.innerWidth < 1024) {
        document.querySelector('.app-shell')?.classList.contains('sidebar-mobile-open')
          ? closeMobileSidebar()
          : openMobileSidebar();
      } else {
        toggleSidebar();
      }
    });
  }

  const overlay = document.getElementById('sidebar-overlay');
  if (overlay) overlay.addEventListener('click', closeMobileSidebar);

  document.addEventListener('keydown', (e) => {
    const key = e.key ? e.key.toLowerCase() : '';
    if ((e.ctrlKey || e.metaKey) && key === 'b') {
      e.preventDefault();
      toggleSidebar();
    } else if (key === 'escape') {
      closeMobileSidebar();
    }
  });
}

// ==== Menu avatar ở topbar ====
function closeAvatarMenu() {
  const menu = document.getElementById('topbar-avatar-menu');
  const btn = document.getElementById('topbar-avatar-btn');
  if (menu) menu.hidden = true;
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

function initAvatarMenu() {
  const btn = document.getElementById('topbar-avatar-btn');
  const menu = document.getElementById('topbar-avatar-menu');
  const img = document.getElementById('topbar-avatar-img');
  if (!btn || !menu) return;

  if (img && typeof getEffectiveAvatarUrl === 'function') {
    img.src = getEffectiveAvatarUrl();
    img.addEventListener('error', () => {
      if (typeof getDefaultAvatarDataUri === 'function') img.src = getDefaultAvatarDataUri();
    });
  }

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const nowOpen = menu.hidden;
    menu.hidden = !nowOpen;
    btn.setAttribute('aria-expanded', String(nowOpen));
    // Đọc lại trạng thái đăng nhập mỗi lần mở (không chỉ lúc init) - để kịp
    // phản ánh nếu người dùng vừa đăng nhập/đăng xuất ở trang Hồ sơ mà chưa
    // tải lại trang.
    const logoutBtn = document.getElementById('topbar-logout-btn');
    if (nowOpen && logoutBtn) {
      logoutBtn.hidden = !(typeof isLoggedIn === 'function' ? isLoggedIn() : false);
    }
    if (nowOpen && img && typeof getEffectiveAvatarUrl === 'function') {
      img.src = getEffectiveAvatarUrl();
    }
  });

  document.addEventListener('click', (e) => {
    if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) closeAvatarMenu();
  });

  menu.querySelectorAll('[data-target]').forEach(item => {
    item.addEventListener('click', () => navigateTo(item.getAttribute('data-target')));
  });

  const logoutBtn = document.getElementById('topbar-logout-btn');
  if (logoutBtn) {
    // Khách (chưa đăng nhập Google) không có phiên để đăng xuất.
    const loggedIn = typeof isLoggedIn === 'function' ? isLoggedIn() : false;
    logoutBtn.hidden = !loggedIn;
    logoutBtn.addEventListener('click', () => {
      closeAvatarMenu();
      if (typeof authSignOut === 'function') authSignOut();
    });
  }
}

// Thanh toán tạo giao dịch VietQR thật (mã tham chiếu + QR), sau đó poll
// /api/keys/payment-status mỗi 3s tới khi webhook SePay xác nhận tiền vào.
// purchase_count là nguồn sự thật phía server, luôn lấy lại từ /api/auth/me
// hoặc response payment-status thay vì tự tăng ở client.
function initKeyShopWidget() {
  const openBtn = document.getElementById('key-topup-btn');
  const overlay = document.getElementById('key-shop-overlay');
  const closeBtn = document.getElementById('key-shop-close');
  const countEl = document.getElementById('key-shop-purchase-count-value');
  const packageView = document.getElementById('key-shop-package-view');
  const paymentView = document.getElementById('key-shop-payment-view');
  const packagesContainer = overlay ? overlay.querySelector('.key-shop-packages') : null;
  const qrImg = document.getElementById('key-shop-qr-img');
  const qrFallback = document.getElementById('key-shop-qr-fallback');
  const paymentAmountEl = document.getElementById('key-shop-payment-amount');
  const paymentCodeEl = document.getElementById('key-shop-payment-code');
  const paymentStatusEl = document.getElementById('key-shop-payment-status');
  const paymentTimerEl = document.getElementById('key-shop-payment-timer');
  const cancelBtn = document.getElementById('key-shop-cancel-btn');
  if (!openBtn || !overlay || !closeBtn || !packagesContainer || !packageView || !paymentView) return;

  let pollTimer = null;
  let pollGiveUpTimer = null;
  let pollFailCount = 0;
  let countdownTimer = null;

  // Tính lại (expires_at - now) mỗi tick thay vì trừ dần một biến đếm, để
  // giá trị luôn đúng kể cả khi tab bị ẩn/throttle giữa chừng.
  const startCountdown = (expiresAtIso) => {
    if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
    const expiresAtMs = new Date(expiresAtIso).getTime();
    const tick = () => {
      if (!paymentTimerEl) return;
      const remainingSec = Math.round((expiresAtMs - Date.now()) / 1000);
      if (remainingSec <= 0) {
        paymentTimerEl.textContent = 'Hết hạn';
        if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
        return;
      }
      const mm = Math.floor(remainingSec / 60);
      const ss = remainingSec % 60;
      paymentTimerEl.textContent = `${mm}:${String(ss).padStart(2, '0')}`;
    };
    tick();
    countdownTimer = setInterval(tick, 1000);
  };

  // Điểm dừng poll duy nhất, dùng chung cho mọi lối thoát (Huỷ, ✕, click ra ngoài).
  const stopPolling = () => {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (pollGiveUpTimer) { clearTimeout(pollGiveUpTimer); pollGiveUpTimer = null; }
    if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
    pollFailCount = 0;
  };

  const showPackageView = () => {
    stopPolling();
    paymentView.hidden = true;
    packageView.hidden = false;
  };

  // Mốc 10/20/50 đổi bonus của TẤT CẢ các gói, không riêng gói vừa mua,
  // nên phải vẽ lại toàn bộ danh sách với purchase_count mới nhất.
  const renderWithCount = (purchaseCount) => {
    if (countEl) countEl.textContent = String(purchaseCount);
    packagesContainer.innerHTML = renderKeyShopPackages(purchaseCount);
    attachPayHandlers();
  };

  const startPolling = (referenceCode) => {
    stopPolling();
    const poll = async () => {
      try {
        const status = await authApiRequest(`/api/keys/payment-status/${referenceCode}`, 'GET');
        pollFailCount = 0;
        if (status.status === 'paid') {
          stopPolling();
          if (paymentStatusEl) paymentStatusEl.textContent = 'Thanh toán thành công! Đang cập nhật...';
          if (typeof setHeaderKeyDisplay === 'function') setHeaderKeyDisplay(status.keys);
          setTimeout(() => {
            renderWithCount(status.purchase_count);
            showPackageView();
          }, 1200);
        } else if (status.status === 'expired') {
          // Mã đã hết hạn thì không thể cộng key cho nó nữa, cần lấy mã mới.
          stopPolling();
          if (paymentStatusEl) {
            paymentStatusEl.textContent = 'Mã thanh toán đã hết hạn do quá lâu chưa thấy tiền vào. Vui lòng quay lại và bấm "Thanh toán" để lấy mã mới.';
          }
          setTimeout(showPackageView, 2500);
        }
      } catch (e) {
        pollFailCount += 1;
        if (pollFailCount >= 5) {
          stopPolling();
          if (paymentStatusEl) paymentStatusEl.textContent = 'Mất kết nối khi kiểm tra thanh toán, vui lòng thử lại.';
        }
      }
    };
    pollTimer = setInterval(poll, 3000);
    // Lưới an toàn dự phòng nếu vì lý do nào đó (mất mạng, lỗi request)
    // không nhận được trạng thái 'expired' đúng lúc từ server.
    pollGiveUpTimer = setTimeout(() => {
      stopPolling();
      if (paymentStatusEl) {
        paymentStatusEl.textContent = 'Không nhận được xác nhận, mã có thể đã hết hạn. Vui lòng quay lại và bấm "Thanh toán" để lấy mã mới.';
      }
    }, 5 * 60 * 1000);
    poll();
  };

  const showPaymentView = (payment) => {
    packageView.hidden = true;
    paymentView.hidden = false;
    if (qrImg) {
      qrImg.hidden = false;
      qrImg.src = payment.qr_url;
    }
    if (qrFallback) qrFallback.hidden = true;
    if (paymentAmountEl) paymentAmountEl.textContent = `${Number(payment.amount_vnd).toLocaleString('vi-VN')} VNĐ`;
    if (paymentCodeEl) paymentCodeEl.textContent = payment.reference_code;
    if (paymentStatusEl) paymentStatusEl.textContent = 'Đang chờ chuyển khoản...';
    if (payment.expires_at) startCountdown(payment.expires_at);
    startPolling(payment.reference_code);
  };

  // Ảnh QR do dịch vụ ngoài render, lỗi/timeout vẫn phải có lối chuyển khoản thủ công.
  if (qrImg) {
    qrImg.addEventListener('error', () => {
      qrImg.hidden = true;
      if (qrFallback) {
        qrFallback.hidden = false;
        qrFallback.innerHTML =
          'Không tải được mã QR. Chuyển khoản thủ công:<br>' +
          'Ngân hàng: VietinBank<br>' +
          'Số TK: 106884671125<br>' +
          'Chủ TK: DINH VIET ANH<br>' +
          `Số tiền: ${paymentAmountEl ? paymentAmountEl.textContent : '-'}<br>` +
          `Nội dung CK: ${paymentCodeEl ? paymentCodeEl.textContent : '-'}`;
      }
    });
  }

  const attachPayHandlers = () => {
    packagesContainer.querySelectorAll('.key-shop-pay-btn').forEach((btn, idx) => {
      btn.addEventListener('click', async () => {
        if (typeof isLoggedIn === 'function' && !isLoggedIn()) {
          alert('Cần đăng nhập bằng Google để mua key.');
          return;
        }
        btn.disabled = true;
        const originalLabel = btn.textContent;
        btn.textContent = 'Đang tạo mã...';
        try {
          const res = await authApiRequest('/api/keys/create-payment', 'POST', { package_index: idx });
          showPaymentView(res);
        } catch (e) {
          alert('Không tạo được mã thanh toán: ' + e.message);
        } finally {
          btn.disabled = false;
          btn.textContent = originalLabel;
        }
      });
    });
  };

  if (cancelBtn) cancelBtn.addEventListener('click', showPackageView);

  const openShop = async () => {
    showPackageView();
    overlay.classList.add('open');
    if (typeof isLoggedIn === 'function' && !isLoggedIn()) {
      renderWithCount(0);
      return;
    }
    try {
      const me = await authApiRequest('/api/auth/me', 'GET');
      renderWithCount(me.purchase_count || 0);
    } catch (e) {
      renderWithCount(0);
    }
  };
  const closeShop = () => {
    stopPolling();
    overlay.classList.remove('open');
  };

  openBtn.addEventListener('click', openShop);
  closeBtn.addEventListener('click', closeShop);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeShop();
  });

  attachPayHandlers();
}

function initFeedbackWidget() {
  const fab = document.getElementById('feedback-fab');
  const panel = document.getElementById('feedback-panel');
  const closeBtn = document.getElementById('feedback-close-btn');
  const form = document.getElementById('feedback-form');
  if (!fab || !panel || !form) return;

  const openPanel = () => {
    panel.classList.add('open');
    document.getElementById('feedback-content').focus();
    const statusEl = document.getElementById('feedback-status');
    if (statusEl) statusEl.hidden = true;
  };
  const closePanel = () => panel.classList.remove('open');

  fab.addEventListener('click', () => {
    panel.classList.contains('open') ? closePanel() : openPanel();
  });

  if (closeBtn) {
    closeBtn.addEventListener('click', closePanel);
  }

  const statusEl = document.getElementById('feedback-status');
  const submitBtn = form.querySelector('.feedback-submit-btn');

  const showStatus = (message, kind) => {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.className = `feedback-status ${kind}`;
    statusEl.hidden = false;
  };

  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const nameInput = document.getElementById('feedback-name');
    const contentInput = document.getElementById('feedback-content');
    const name = (nameInput.value || '').trim();
    const content = (contentInput.value || '').trim();

    if (!content) {
      contentInput.focus();
      return;
    }

    // Gửi thẳng qua API thay vì mailto: - mailto chỉ mở email nháp chứ không
    // tự gửi, dễ khiến feedback "biến mất" nếu máy chưa cấu hình mail mặc định.
    submitBtn.disabled = true;
    const originalLabel = submitBtn.textContent;
    submitBtn.textContent = 'Đang gửi...';
    try {
      const res = await fetch(`${AI_BACKEND_URL}/api/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, content })
      });
      if (!res.ok) throw new Error('Gửi thất bại');
      showStatus('Đã gửi góp ý, cảm ơn bạn!', 'success');
      form.reset();
      setTimeout(closePanel, 1500);
    } catch (e2) {
      showStatus('Gửi không thành công, thử lại sau.', 'error');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = originalLabel;
    }
  });
}