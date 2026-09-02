// ==== STREAK LOGIC ====
// Theo dõi thời gian học thực tế trong ngày (localStorage) và kích hoạt
// streak khi người dùng đạt đủ 5 phút hoạt động trong 1 ngày.

const STREAK_STORAGE_KEY = 'ioc_streak_data';
const STREAK_GOAL_SECONDS = 10 * 60; // 10 phút

let streakIntervalId = null;

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

  // Không ở trang Home thì không cần cập nhật
  if (!badge || !numberEl) return;

  const data = loadStreakData();
  const active = isStreakActiveToday(data);
  const seconds = Math.min(data.todaySeconds, STREAK_GOAL_SECONDS);
  const percent = Math.min(100, Math.round((seconds / STREAK_GOAL_SECONDS) * 100));
  const remaining = Math.max(0, STREAK_GOAL_SECONDS - data.todaySeconds);

  if (active) {
    badge.textContent = 'Đã kích hoạt hôm nay';
    badge.classList.remove('inactive');
    badge.classList.add('active-badge');
    if (statusTag) statusTag.textContent = 'Hoàn thành';
    if (hintText) hintText.textContent = 'Bạn đã duy trì streak hôm nay. Hẹn gặp lại ngày mai!';
  } else {
    badge.textContent = `Chưa kích hoạt (${formatMMSS(seconds)}/10:00)`;
    badge.classList.add('inactive');
    badge.classList.remove('active-badge');
    if (statusTag) statusTag.textContent = 'Chờ học 10p';
    if (hintText) hintText.textContent = `Còn ${formatMMSS(remaining)} để kích hoạt Streak`;
  }

  numberEl.textContent = `${data.streakCount} DAY${data.streakCount === 1 ? '' : 'S'}`;
  if (progressCurrent) progressCurrent.textContent = `${formatMMSS(seconds)} / 10:00`;
  if (progressFill) progressFill.style.width = `${percent}%`;
}

function tickStreak() {
  // Chỉ tính thời gian khi tab đang được xem (tránh cộng thời gian khi ở nền)
  if (document.hidden) return;

  const data = loadStreakData();

  if (!isStreakActiveToday(data)) {
    data.todaySeconds = Math.min(data.todaySeconds + 1, STREAK_GOAL_SECONDS);

    if (data.todaySeconds >= STREAK_GOAL_SECONDS) {
      data.streakCount += 1;
      data.lastActiveDate = getTodayDateString();
    }

    saveStreakData(data);
  }

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
