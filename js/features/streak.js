// ==== STREAK LOGIC ====
// Theo dõi thời gian học thực tế trong ngày (localStorage) và kích hoạt
// streak khi người dùng đạt đủ 5 phút hoạt động trong 1 ngày.

const STREAK_STORAGE_KEY = 'ioc_streak_data';
const STREAK_GOAL_KEY = 'ioc_daily_goal_minutes'; // đặt ở trang Profile
const STREAK_GOAL_OPTIONS_MINUTES = [10, 20, 30];
const STREAK_GOAL_DEFAULT_MINUTES = 10;

let streakIntervalId = null;

function getDailyGoalMinutes() {
  try {
    const saved = JSON.parse(localStorage.getItem(STREAK_GOAL_KEY));
    return STREAK_GOAL_OPTIONS_MINUTES.includes(saved) ? saved : STREAK_GOAL_DEFAULT_MINUTES;
  } catch (e) {
    return STREAK_GOAL_DEFAULT_MINUTES;
  }
}

function setDailyGoalMinutes(minutes) {
  const value = STREAK_GOAL_OPTIONS_MINUTES.includes(minutes) ? minutes : STREAK_GOAL_DEFAULT_MINUTES;
  try {
    localStorage.setItem(STREAK_GOAL_KEY, JSON.stringify(value));
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function getStreakGoalSeconds() {
  return getDailyGoalMinutes() * 60;
}

// ==== TỔNG THỜI GIAN HỌC (vĩnh viễn) ====
// KHÔNG reset theo ngày (khác todaySeconds ở trên) - chỉ mất khi đăng xuất
// hoặc xoá tài khoản (clearAllLocalProgressData() ở auth.js quét mọi key
// "ioc_*", key này cũng nằm trong đó nên tự động được xử lý đúng, không cần
// thêm logic riêng).
const TOTAL_PLAYTIME_KEY = 'ioc_total_playtime_seconds';

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

// Đơn vị GIỜ (số thập phân, vd "2.3h") cho tổng thời gian học - khác
// formatMMSS() (chỉ hợp cho đồng hồ đếm ngắn trong ngày như todaySeconds).
function formatHoursMinutes(totalSeconds) {
  const safeSeconds = Math.max(0, totalSeconds);
  const hours = safeSeconds / 3600;
  return `${hours.toFixed(1)}h`;
}

function pad2(n) {
  return String(n).padStart(2, '0');
}

function getDateString(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

function getTodayDateString() {
  return getDateString(new Date());
}

function getYesterdayDateString() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return getDateString(d);
}

function formatMMSS(totalSeconds) {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(safeSeconds / 60);
  const s = safeSeconds % 60;
  return `${pad2(m)}:${pad2(s)}`;
}

function loadStreakData() {
  let data = null;
  try {
    data = JSON.parse(localStorage.getItem(STREAK_STORAGE_KEY));
  } catch (e) {
    data = null;
  }

  if (!data || typeof data !== 'object') {
    data = { streakCount: 0, lastActiveDate: null, todaySeconds: 0, todayDate: getTodayDateString() };
  }

  const today = getTodayDateString();
  if (data.todayDate !== today) {
    // Sang ngày mới: reset bộ đếm thời gian trong ngày
    data.todayDate = today;
    data.todaySeconds = 0;

    // Nếu ngày hoạt động gần nhất không phải hôm qua (và không phải hôm nay),
    // nghĩa là streak đã bị đứt quãng -> reset về 0
    if (data.lastActiveDate && data.lastActiveDate !== today && data.lastActiveDate !== getYesterdayDateString()) {
      data.streakCount = 0;
    }
  }

  return data;
}

function saveStreakData(data) {
  try {
    localStorage.setItem(STREAK_STORAGE_KEY, JSON.stringify(data));
  } catch (e) {
    // localStorage không khả dụng (vd: chế độ ẩn danh) -> bỏ qua, không crash app
  }
}

function isStreakActiveToday(data) {
  return data.lastActiveDate === getTodayDateString();
}

function updateStreakUI() {
  const badge = document.getElementById('streak-badge');
  const numberEl = document.getElementById('streak-number');
  const statusTag = document.getElementById('streak-status-tag');
  const progressFill = document.getElementById('streak-progress-fill');
  const progressCurrent = document.getElementById('streak-progress-current');
  const hintText = document.getElementById('streak-hint-text');

  // Ô daily goal ở trang Profile (khác ID, có thể không tồn tại nếu đang ở
  // trang khác - cập nhật cả 2 nơi trong CÙNG 1 vòng lặp tick, không cần
  // thêm 1 interval riêng cho Profile).
  const goalProgressFill = document.getElementById('goal-progress-fill');
  const goalProgressCurrent = document.getElementById('goal-progress-current');
  const goalCheckBadge = document.getElementById('goal-check-badge');
  const totalPlaytimeEl = document.getElementById('profile-total-playtime');

  if (totalPlaytimeEl) {
    totalPlaytimeEl.textContent = formatHoursMinutes(getTotalPlaytimeSeconds());
  }

  const data = loadStreakData();
  const goalSeconds = getStreakGoalSeconds();
  // "Đã đạt goal HÔM NAY" tính theo goal HIỆN TẠI (có thể vừa đổi 10 -> 20p),
  // KHÔNG dùng lastActiveDate (cờ đó chỉ để tính streakCount 1 lần/ngày, cố
  // tình không tụt lại khi đổi goal cao hơn - xem tickStreak()). Nếu chỉ
  // dùng lastActiveDate thì sau khi đổi goal cao hơn, dấu tick/badge vẫn báo
  // "hoàn thành" dù thực ra chưa đủ giờ theo goal mới - đây chính là bug đã
  // gặp.
  const active = data.todaySeconds >= goalSeconds;
  const goalLabel = formatMMSS(goalSeconds);
  const seconds = Math.min(data.todaySeconds, goalSeconds);
  const percent = Math.min(100, Math.round((seconds / goalSeconds) * 100));
  const remaining = Math.max(0, goalSeconds - data.todaySeconds);

  if (goalProgressCurrent) goalProgressCurrent.textContent = `${formatMMSS(seconds)} / ${goalLabel}`;
  if (goalProgressFill) goalProgressFill.style.width = `${percent}%`;
  if (goalCheckBadge) goalCheckBadge.hidden = !active;

  // Phần dưới chỉ có trên trang Home
  if (!badge || !numberEl) return;

  if (active) {
    badge.textContent = 'Đã kích hoạt hôm nay';
    badge.classList.remove('inactive');
    badge.classList.add('active-badge');
    if (statusTag) statusTag.textContent = 'Hoàn thành';
    if (hintText) hintText.textContent = 'Bạn đã duy trì streak hôm nay. Hẹn gặp lại ngày mai!';
  } else {
    badge.textContent = `Chưa kích hoạt (${formatMMSS(seconds)}/${goalLabel})`;
    badge.classList.add('inactive');
    badge.classList.remove('active-badge');
    if (statusTag) statusTag.textContent = `Chờ học ${getDailyGoalMinutes()}p`;
    if (hintText) hintText.textContent = `Còn ${formatMMSS(remaining)} để kích hoạt Streak`;
  }

  numberEl.textContent = `${data.streakCount} DAY${data.streakCount === 1 ? '' : 'S'}`;
  if (progressCurrent) progressCurrent.textContent = `${formatMMSS(seconds)} / ${goalLabel}`;
  if (progressFill) progressFill.style.width = `${percent}%`;

  // Icon lửa: xám khi chưa có streak nào (0 DAY), đỏ ngay khi streakCount >= 1.
  const flameIcon = document.getElementById('streak-flame-icon');
  if (flameIcon) flameIcon.classList.toggle('streak-flame--lit', data.streakCount > 0);
}

function tickStreak() {
  // Chỉ tính thời gian khi tab đang được xem (tránh cộng thời gian khi ở nền)
  if (document.hidden) return;

  // Tổng thời gian học - tăng MỖI GIÂY bất kể đã đạt goal hôm nay hay chưa
  // (khác todaySeconds bên dưới, bị chặn ở goalSeconds).
  addTotalPlaytimeSeconds(1);

  const data = loadStreakData();
  const goalSeconds = getStreakGoalSeconds();
  const alreadyCountedToday = isStreakActiveToday(data);

  // LUÔN tăng todaySeconds, kể cả sau khi đã đạt goal cũ - nếu dừng lại ở
  // đây thì khi người dùng NÂNG goal lên cao hơn giữa chừng (vd 10 -> 20p),
  // đồng hồ sẽ đứng hình mãi vì điều kiện dưới không còn đúng nữa (bug đã
  // gặp: "đổi goal xong đồng hồ không chạy nữa"). Không cap theo goalSeconds
  // ở đây - updateStreakUI() tự Math.min() lại lúc HIỂN THỊ, tách biệt lưu
  // trữ khỏi hiển thị.
  data.todaySeconds += 1;

  // streakCount chỉ được CỘNG 1 LẦN/NGÀY (lastActiveDate) - cố tình KHÔNG
  // dùng lại điều kiện này để chặn todaySeconds ở trên, vì đây là 2 việc
  // khác nhau: "đã tính streak hôm nay chưa" (persistent, không tụt lại dù
  // sau đó đổi goal cao hơn) khác với "có đang đạt goal HIỆN TẠI không"
  // (updateStreakUI() tự tính lại mỗi lần, xem comment ở đó).
  if (!alreadyCountedToday && data.todaySeconds >= goalSeconds) {
    data.streakCount += 1;
    data.lastActiveDate = getTodayDateString();
  }

  saveStreakData(data);
  updateStreakUI();
}

function startStreakTimer() {
  stopStreakTimer();
  updateStreakUI();
  streakIntervalId = setInterval(tickStreak, 1000);
}

function stopStreakTimer() {
  if (streakIntervalId) {
    clearInterval(streakIntervalId);
    streakIntervalId = null;
  }
}
