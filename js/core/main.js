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
  initKeyShopWidget();
}

// Modal "Key Shop" mở từ nút "+" cạnh số key ở header. Bấm "Thanh toán" giờ
// tạo 1 giao dịch thật (QR VietQR + mã tham chiếu), rồi POLL trạng thái mỗi
// 3s cho tới khi webhook SePay xác nhận đã có tiền vào (xem server/main.py:
// /api/keys/create-payment, /api/keys/payment-status, /api/webhooks/sepay).
// purchase_count lưu ở SERVER (gắn tài khoản Google, xem server/db.py) -
// luôn lấy mới từ /api/auth/me hoặc từ response payment-status.
// KEY_SHOP_PACKAGES/renderKeyShopPackages() định nghĩa ở js/core/App.js.
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
  const cancelBtn = document.getElementById('key-shop-cancel-btn');
  if (!openBtn || !overlay || !closeBtn || !packagesContainer || !packageView || !paymentView) return;

  let pollTimer = null;
  let pollGiveUpTimer = null;
  let pollFailCount = 0;

  // Mọi lối thoát (nút Huỷ, nút ✕, bấm ra ngoài) đều gọi chung 1 hàm dừng
  // poll DUY NHẤT ở đây - không lặp lại clearInterval ở từng nơi, tránh sót.
  const stopPolling = () => {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (pollGiveUpTimer) { clearTimeout(pollGiveUpTimer); pollGiveUpTimer = null; }
    pollFailCount = 0;
  };

  const showPackageView = () => {
    stopPolling();
    paymentView.hidden = true;
    packageView.hidden = false;
  };

  // Đạt mốc 10/20/50 làm TẤT CẢ các gói đổi lượng key được cộng (không chỉ
  // gói vừa mua) - nên mỗi lần vẽ lại phải dùng purchase_count MỚI NHẤT rồi
  // gắn lại listener, thay vì chỉ sửa mỗi gói vừa bấm.
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
          // Mã hết hạn sau vài phút không thấy tiền vào (xem server/db.py:
          // PENDING_PAYMENT_TTL_MINUTES) - không tự cộng key được nữa cho mã
          // này, phải bấm "Thanh toán" lại để lấy mã mới.
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
    // Lưới an toàn dự phòng - bình thường nhánh 'expired' ở trên đã tự dừng
    // poll trong vòng PENDING_PAYMENT_TTL_MINUTES (server/db.py, hiện 3 phút)
    // + tối đa 3s trễ do chu kỳ poll. Timer này chỉ chạy nếu vì lý do gì đó
    // (mất mạng, lỗi request) mà không nhận được trạng thái 'expired' đúng
    // lúc - đặt hơi dài hơn TTL server 1 chút để không bao giờ chặn trước.
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
    startPolling(payment.reference_code);
  };

  // VietQR (dịch vụ ảnh bên ngoài) lỗi/timeout thì vẫn cho người dùng chuyển
  // khoản thủ công bằng tay thay vì kẹt cứng không thanh toán được.
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

    // Lưu thẳng vào DB qua API thay vì mailto: - mailto chỉ mở sẵn 1 email
    // nháp, KHÔNG tự gửi, nên im lặng không có gì xảy ra nếu máy người dùng
    // chưa cấu hình ứng dụng mail mặc định (đây là lý do feedback "biến mất").
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