// ==== TỔNG THỜI GIAN HỌC ====
// Thay cho tính năng Streak (đã bỏ) - chỉ còn đếm tổng thời gian học vĩnh
// viễn, hiển thị ở trang Profile. KHÔNG reset theo ngày, chỉ mất khi đăng
// xuất hoặc xoá tài khoản (clearAllLocalProgressData() ở auth.js quét mọi
// key "ioc_*", key này cũng nằm trong đó nên tự động được xử lý đúng).

const TOTAL_PLAYTIME_KEY = 'ioc_total_playtime_seconds';

let playtimeIntervalId = null;

function getTotalPlaytimeSeconds() {
  try {
    const saved = JSON.parse(localStorage.getItem(TOTAL_PLAYTIME_KEY));
    return Number.isFinite(saved) && saved >= 0 ? saved : 0;
  } catch (e) {
    return 0;
  }
}

function addTotalPlaytimeSeconds(deltaSeconds) {
  const next = getTotalPlaytimeSeconds() + deltaSeconds;
  try {
    localStorage.setItem(TOTAL_PLAYTIME_KEY, JSON.stringify(next));
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

// Đơn vị GIỜ (số thập phân, vd "2.3h") cho tổng thời gian học.
function formatHoursMinutes(totalSeconds) {
  const safeSeconds = Math.max(0, totalSeconds);
  const hours = safeSeconds / 3600;
  return `${hours.toFixed(1)}h`;
}

function updatePlaytimeUI() {
  const totalPlaytimeEl = document.getElementById('profile-total-playtime');
  if (totalPlaytimeEl) {
    totalPlaytimeEl.textContent = formatHoursMinutes(getTotalPlaytimeSeconds());
  }
}

function tickPlaytime() {
  // Chỉ tính thời gian khi tab đang được xem (tránh cộng thời gian khi ở nền)
  if (document.hidden) return;
  addTotalPlaytimeSeconds(1);
  updatePlaytimeUI();
}

function startPlaytimeTimer() {
  stopPlaytimeTimer();
  updatePlaytimeUI();
  playtimeIntervalId = setInterval(tickPlaytime, 1000);
}

function stopPlaytimeTimer() {
  if (playtimeIntervalId) {
    clearInterval(playtimeIntervalId);
    playtimeIntervalId = null;
  }
}
