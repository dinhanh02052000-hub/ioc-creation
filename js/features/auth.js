// ==== ĐĂNG NHẬP GOOGLE + ĐỒNG BỘ TIẾN ĐỘ ====
// Load ở cả 3 trang vì tiến độ được ghi trong lúc chơi (world1/world2), không
// chỉ ở trang chủ. initGoogleAuth() chỉ thực sự chạy ở Profile (nơi có script
// + container Google Identity Services) - các hàm dùng `google.accounts` đều
// tự kiểm tra trước khi gọi.

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

// Gom mọi key "ioc_*" (trừ session đăng nhập) thành 1 object để gửi lên
// server - tự động bao gồm cả key mới thêm sau này, không cần sửa lại đây.
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

// Xoá sạch mọi dữ liệu tiến độ cục bộ - dùng khi đăng nhập (tránh mang theo
// dữ liệu ẩn danh trước đó) và khi đăng xuất (không lộ tiến độ cho người dùng
// tiếp theo trên máy này).
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

// Gọi sau khi đăng nhập + clearAllLocalProgressData(): tải dữ liệu server nếu
// có, hoặc đẩy trạng thái rỗng lên để "gieo" bản ghi ban đầu cho tài khoản mới.
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

// Tự động đẩy dữ liệu lên server mỗi khi có key "ioc_*" được ghi, để các
// module khác không cần biết gì về đăng nhập. Debounce để gộp nhiều lần ghi
// liên tiếp thành 1 lần gọi API.
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
    // Xoá dữ liệu ẩn danh trước khi tải tiến độ thật của tài khoản về.
    clearAllLocalProgressData();
    await authSyncPull();
    // Reload để mọi phần UI đọc lại đúng dữ liệu vừa đổi.
    window.location.reload();
  } catch (e) {
    if (typeof renderAuthError === 'function') renderAuthError(e.message);
  }
}

function initGoogleAuth(containerId, retriesLeft) {
  // Script accounts.google.com load async nên "google" có thể chưa sẵn sàng
  // -> thử lại vài lần thay vì bỏ qua im lặng.
  if (typeof google === 'undefined' || !google.accounts || !google.accounts.id) {
    const left = retriesLeft === undefined ? 20 : retriesLeft;
    if (left > 0) setTimeout(() => initGoogleAuth(containerId, left - 1), 250);
    return;
  }
  google.accounts.id.initialize({
    client_id: '560912613294-ohckrbqk8hk8po63dd2hem52efo39emc.apps.googleusercontent.com',
    callback: handleGoogleCredentialResponse
  });
  const container = document.getElementById(containerId);
  if (container && !isLoggedIn()) {
    google.accounts.id.renderButton(container, { theme: 'outline', size: 'large', text: 'signin_with', shape: 'pill' });
  }
}

function authSignOut() {
  // Gọi logout trước khi xoá session cục bộ vì authApiRequest cần token còn
  // trong localStorage để gắn header Authorization.
  if (isLoggedIn()) {
    authApiRequest('/api/auth/logout', 'POST').catch(() => {});
  }
  clearAuthSession();
  clearAllLocalProgressData();
  if (typeof google !== 'undefined' && google.accounts && google.accounts.id) {
    google.accounts.id.disableAutoSelect();
  }
  window.location.reload();
}

// ==== Badge số key ở góc trên-phải header (chỉ tồn tại trên index.html;
// an toàn khi gọi từ world1/world2 vì #header-key-value không có nên no-op) ====
// Không cache số key trong localStorage vì nó đổi phía server mỗi lần dùng AI
// - luôn lấy trực tiếp từ /api/auth/me hoặc keys_remaining sau mỗi lượt gọi AI.
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
