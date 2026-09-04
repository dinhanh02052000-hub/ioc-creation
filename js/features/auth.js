// ==== ĐĂNG NHẬP GOOGLE + ĐỒNG BỘ TIẾN ĐỘ ====
// File này load ở CẢ 3 trang (index.html, world1.html, world2.html) vì tiến
// độ thực tế được ghi trong lúc chơi (world1/world2), không chỉ ở trang chủ.
// Phần khởi tạo nút Google (initGoogleAuth) chỉ thực sự chạy khi có Google
// Identity Services script + container - tức chỉ ở trang Profile (index.html),
// nên các hàm liên quan tới `google.accounts` đều tự kiểm tra trước khi gọi.

const AUTH_SESSION_KEY = 'ioc_auth_session'; // { token, name, email, picture }
const AUTH_SYNC_KEYS_SKIP = new Set([AUTH_SESSION_KEY]);

function getAuthSession() {
  try {
    const data = JSON.parse(localStorage.getItem(AUTH_SESSION_KEY));
    return data && data.token ? data : null;
  } catch (e) {
    return null;
  }
}

function saveAuthSession(session) {
  try {
    localStorage.setItem(AUTH_SESSION_KEY, JSON.stringify(session));
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function clearAuthSession() {
  try {
    localStorage.removeItem(AUTH_SESSION_KEY);
  } catch (e) {
    // bỏ qua
  }
}

function isLoggedIn() {
  return !!getAuthSession();
}

// Gom toàn bộ dữ liệu tiến độ (mọi key "ioc_*" trừ chính session đăng nhập)
// thành 1 object phẳng để gửi lên server - tự động bao gồm cả những key mới
// thêm sau này (course progress, level results, vocab learned, playtime, chat
// đang dở...) mà không cần sửa lại chỗ này.
function collectLocalProgressData() {
  const data = {};
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key || !key.startsWith('ioc_') || AUTH_SYNC_KEYS_SKIP.has(key)) continue;
    try {
      data[key] = JSON.parse(localStorage.getItem(key));
    } catch (e) {
      // giá trị không phải JSON hợp lệ -> bỏ qua key đó
    }
  }
  return data;
}

// Xoá SẠCH mọi dữ liệu tiến độ cục bộ (playtime, course progress, level
// results, từ vựng đã học, chat đang dở, cache analysis...) - dùng khi đăng
// nhập vào 1 tài khoản (dữ liệu ẩn danh trước đó không được mang theo, tránh
// lẫn dữ liệu giữa các tài khoản) VÀ khi đăng xuất (không để lộ tiến độ của
// tài khoản vừa đăng xuất cho người dùng ẩn danh tiếp theo trên máy này).
function clearAllLocalProgressData() {
  const keysToRemove = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && key.startsWith('ioc_') && !AUTH_SYNC_KEYS_SKIP.has(key)) {
      keysToRemove.push(key);
    }
  }
  keysToRemove.forEach(key => localStorage.removeItem(key));
}

function applyRemoteProgressData(data) {
  if (!data || typeof data !== 'object') return;
  Object.keys(data).forEach(key => {
    if (!key.startsWith('ioc_') || AUTH_SYNC_KEYS_SKIP.has(key)) return;
    try {
      localStorage.setItem(key, JSON.stringify(data[key]));
    } catch (e) {
      // bỏ qua
    }
  });
}

async function authApiRequest(path, method, body) {
  const session = getAuthSession();
  const headers = { 'Content-Type': 'application/json' };
  if (session) headers['Authorization'] = `Bearer ${session.token}`;
  const res = await fetch(`${AI_BACKEND_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const errData = await res.json();
      if (errData && errData.detail) detail = errData.detail;
    } catch (e) {
      // không phải JSON -> giữ statusText
    }
    throw new Error(detail);
  }
  return res.json();
}

async function authSyncPush() {
  if (!isLoggedIn()) return;
  try {
    await authApiRequest('/api/progress/save', 'POST', { data: collectLocalProgressData() });
  } catch (e) {
    console.warn('Đồng bộ tiến độ lên server thất bại:', e.message);
  }
}

// Gọi ngay sau khi đăng nhập + đã clearAllLocalProgressData(): nếu server đã
// có dữ liệu (tài khoản này từng lưu trước đó) thì tải về; nếu server chưa
// có gì (tài khoản mới) thì đẩy trạng thái rỗng hiện tại lên để "gieo" bản
// ghi tiến độ ban đầu cho tài khoản.
async function authSyncPull() {
  if (!isLoggedIn()) return;
  try {
    const res = await authApiRequest('/api/progress/load', 'GET');
    const remote = res && res.data;
    if (remote && Object.keys(remote).length > 0) {
      applyRemoteProgressData(remote);
    } else {
      await authSyncPush();
    }
  } catch (e) {
    console.warn('Tải tiến độ từ server thất bại:', e.message);
  }
}

// Tự động đẩy dữ liệu lên server mỗi khi có bất kỳ key "ioc_*" nào được ghi
// (course-progress.js, playtime.js... không cần biết gì về tính năng đăng nhập,
// chỉ cần gọi localStorage.setItem như bình thường). Gộp nhiều lần ghi liên
// tiếp (vd lưu xong 1 level ghi 2-3 key liền) thành 1 lần gọi API bằng debounce.
(function interceptLocalStorageForSync() {
  const originalSetItem = localStorage.setItem.bind(localStorage);
  let pushTimer = null;
  localStorage.setItem = function (key, value) {
    originalSetItem(key, value);
    if (typeof key === 'string' && key.startsWith('ioc_') && !AUTH_SYNC_KEYS_SKIP.has(key) && isLoggedIn()) {
      clearTimeout(pushTimer);
      pushTimer = setTimeout(authSyncPush, 800);
    }
  };
})();

// ---------- Google Identity Services (chỉ dùng ở trang Profile) ----------

async function handleGoogleCredentialResponse(response) {
  try {
    const result = await authApiRequest('/api/auth/google', 'POST', { credential: response.credential });
    saveAuthSession({ token: result.token, ...result.user });
    // Dữ liệu ẩn danh trước khi đăng nhập KHÔNG được mang theo vào tài khoản -
    // xoá sạch trước, rồi mới tải tiến độ thật của tài khoản này về (nếu có).
    clearAllLocalProgressData();
    await authSyncPull();
    // Reload để MỌI phần UI (đồng hồ tổng thời gian học, thanh tiến độ Course, cache
    // Analysis...) đọc lại đúng dữ liệu vừa đổi thay vì phải tự dò từng nơi.
    window.location.reload();
  } catch (e) {
    if (typeof renderAuthError === 'function') renderAuthError(e.message);
  }
}

function initGoogleAuth(containerId, retriesLeft) {
  // Script accounts.google.com load async - nếu người dùng vào trang quá
  // nhanh, "google" có thể chưa sẵn sàng -> thử lại vài lần thay vì bỏ qua
  // im lặng (khiến nút đăng nhập không bao giờ hiện).
  if (typeof google === 'undefined' || !google.accounts || !google.accounts.id) {
    const left = retriesLeft === undefined ? 20 : retriesLeft;
    if (left > 0) setTimeout(() => initGoogleAuth(containerId, left - 1), 250);
    return;
  }
  google.accounts.id.initialize({
    client_id: '290773416982-0cmegk2eirqj4reql0sd1io6c7s3p8e9.apps.googleusercontent.com',
    callback: handleGoogleCredentialResponse
  });
  const container = document.getElementById(containerId);
  if (container && !isLoggedIn()) {
    google.accounts.id.renderButton(container, { theme: 'outline', size: 'large', text: 'signin_with', shape: 'pill' });
  }
}

function authSignOut() {
  // Gọi API logout TRƯỚC khi xoá session cục bộ (authApiRequest cần token
  // còn trong localStorage để gắn header Authorization).
  if (isLoggedIn()) {
    authApiRequest('/api/auth/logout', 'POST').catch(() => {});
  }
  clearAuthSession();
  // Đăng xuất -> tiến độ hiện trên máy cũng về 0 (không lộ dữ liệu tài khoản
  // vừa đăng xuất). Đăng nhập lại đúng tài khoản đó sẽ tự tải lại đầy đủ từ
  // server (xem handleGoogleCredentialResponse -> authSyncPull).
  clearAllLocalProgressData();
  if (typeof google !== 'undefined' && google.accounts && google.accounts.id) {
    google.accounts.id.disableAutoSelect();
  }
  window.location.reload();
}

// ==== Badge số key ở góc trên-phải header (chỉ tồn tại trên index.html - an
// toàn khi gọi từ world1.html/world2.html vì #header-key-value không có nên
// no-op) ====
// Số key KHÔNG cache trong localStorage như session (token/name/email/picture)
// - vì nó đổi phía server (mỗi lần dùng AI), cache lại dễ bị lệch/gây hiểu
// nhầm. Luôn lấy trực tiếp từ /api/auth/me hoặc từ keys_remaining trả về sau
// mỗi lượt gọi AI có trừ key.
function setHeaderKeyDisplay(keys) {
  const el = document.getElementById('header-key-value');
  if (!el) return;
  const n = Number.isFinite(keys) ? keys : 0;
  el.textContent = String(Math.max(0, n)).padStart(3, '0');
}

async function initHeaderKeyBadge() {
  if (!isLoggedIn()) {
    setHeaderKeyDisplay(0);
    return;
  }
  try {
    const me = await authApiRequest('/api/auth/me', 'GET');
    setHeaderKeyDisplay(me.keys);
  } catch (e) {
    // Không chặn UI vì lỗi phụ (VD backend tạm offline) - giữ nguyên "000".
  }
}
