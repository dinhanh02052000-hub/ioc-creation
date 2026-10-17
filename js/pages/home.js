// Trang chủ - bố cục bento 5 ô (xem mục 5.1 của yêu cầu redesign):
// A. Tiếp tục học  B. Chỉ số IoC  C. Kết quả gần đây  D. Từ cần ôn  E. Mẹo hôm nay
// Founders/Quote-Tip cũ đã chuyển sang trang Giới thiệu (about.js) và gộp
// vào ô E - không xoá nội dung, chỉ đổi chỗ theo đúng yêu cầu.

const USER_NAME_KEY = 'ioc_user_name';
const DEFAULT_USER_NAME = 'Guest';

function getUserName() {
  try {
    // PHẢI JSON.parse: mọi key "ioc_*" được đồng bộ lên server giả định giá
    // trị là JSON hợp lệ (xem collectLocalProgressData ở auth.js).
    const saved = JSON.parse(localStorage.getItem(USER_NAME_KEY));
    return typeof saved === 'string' && saved.trim() ? saved.trim() : DEFAULT_USER_NAME;
  } catch (e) {
    return DEFAULT_USER_NAME;
  }
}

function setUserName(name) {
  const trimmed = (name || '').trim();
  try {
    localStorage.setItem(USER_NAME_KEY, JSON.stringify(trimmed || DEFAULT_USER_NAME));
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function getDefaultAvatarDataUri() {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">'
    + '<circle cx="20" cy="20" r="20" fill="#1c2129"/>'
    + '<circle cx="20" cy="16.5" r="7.2" fill="#6e7681"/>'
    + '<path d="M6.5 34.5c1.3-8.4 7.6-13 13.5-13s12.2 4.6 13.5 13" fill="#6e7681"/>'
    + '</svg>';
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function getEffectiveAvatarUrl() {
  if (typeof getAuthSession === 'function') {
    const session = getAuthSession();
    if (session && session.picture) return session.picture;
  }
  return getDefaultAvatarDataUri();
}

function getDayOfYear() {
  const now = new Date();
  const start = new Date(now.getFullYear(), 0, 0);
  const diff = now - start;
  const oneDay = 1000 * 60 * 60 * 24;
  return Math.floor(diff / oneDay);
}

let homeRenderedDate = null;
let homeDailyCheckIntervalId = null;

function homeEscapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

// ---- A. Tiếp tục học ----

function homeGetContinueWorld() {
  for (const w of COURSE_WORLDS) {
    const completed = getWorldCompletedLevels(w.id);
    if (completed < w.totalLevels) return { world: w, completed };
  }
  const w = COURSE_WORLDS[COURSE_WORLDS.length - 1];
  return { world: w, completed: getWorldCompletedLevels(w.id) };
}

function homeRenderContinueCard() {
  const { world, completed } = homeGetContinueWorld();
  const nextLevel = Math.min(world.totalLevels, completed + 1);
  const percent = Math.min(100, Math.round((completed / world.totalLevels) * 100));
  const isFirstEver = COURSE_WORLDS.every(w => getWorldCompletedLevels(w.id) === 0);

  return `
    <div class="card home-continue-card">
      <p class="home-greeting">Chào ${homeEscapeHtml(getUserName())}</p>
      <div class="home-continue-body">
        <div class="home-continue-info">
          <div class="home-continue-world">${world.name}</div>
          <div class="home-continue-level" id="home-continue-level">Level ${nextLevel}${isFirstEver ? '' : ' · <span class="home-continue-topic">đang tải chủ đề...</span>'}</div>
          <div class="home-continue-progress-row">
            <div class="home-continue-bar"><div class="home-continue-bar-fill" style="width:${percent}%;"></div></div>
            <span class="home-continue-progress-text">${completed}/${world.totalLevels} level</span>
          </div>
          <button type="button" class="ai-btn home-continue-btn" data-world-id="${world.id}">
            ${isFirstEver ? 'Bắt đầu hành trình' : 'Tiếp tục học'}
          </button>
        </div>
        <img class="home-continue-mascot" src="assets/images/ioc-bear.png" alt="Gấu IOC" draggable="false">
      </div>
    </div>
  `;
}

async function homeLoadContinueTopic(worldId, level) {
  const el = document.querySelector('#home-continue-level .home-continue-topic');
  if (!el || typeof gestureGetVocab !== 'function') return;
  try {
    const data = await gestureGetVocab(worldId, level);
    el.textContent = data.group_title || '';
  } catch (e) {
    el.textContent = '';
  }
}

// ---- B. Chỉ số IoC ----
// Cùng công thức/nguồn dữ liệu với trang Phân tích (analysisComputeAggregate
// ở js/pages/analysis.js) - không tính lại từ đầu để tránh 2 nơi lệch số liệu.
function homeRenderIocIndexBody() {
  const agg = typeof analysisComputeAggregate === 'function' ? analysisComputeAggregate() : null;

  if (!agg) {
    return `
      <div class="home-iocindex-example">
        <span class="badge">Ví dụ</span>
        ${analysisScoreRowHtml('Ảo tưởng', 7.5)}
        ${analysisScoreRowHtml('Thực tế', 5.8)}
        <div class="analysis-illusion-row">
          <span class="analysis-status-dot analysis-status-dot--red"></span>
          <span>GAP: +1.7</span>
          <span class="analysis-illusion-hint">Hoàn thành 1 level để xem số liệu thật</span>
        </div>
      </div>
    `;
  }
  const meta = ANALYSIS_ILLUSION_META[agg.illusion_status] || { label: agg.illusion_status, dot: 'red' };
  const gapSign = agg.gap > 0 ? '+' : '';
  return `
    ${analysisScoreRowHtml('Ảo tưởng', agg.confidence)}
    ${analysisScoreRowHtml('Thực tế', agg.overall)}
    <div class="analysis-illusion-row">
      <span class="analysis-status-dot analysis-status-dot--${meta.dot}"></span>
      <span>GAP: ${gapSign}${agg.gap.toFixed(1)}</span>
      <span class="analysis-illusion-hint">${meta.label}</span>
    </div>
  `;
}

// ---- C. Kết quả gần đây ----

const HOME_ILLUSION_LABELS = {
  DETECTED: { text: 'Ảo tưởng', cls: 'illusion' },
  UNDERCONFIDENT: { text: 'Tự ti', cls: 'under' },
  CALIBRATED: { text: 'Cân bằng', cls: 'balanced' },
};

function homeRenderRecentResultsCard() {
  const flat = typeof getAllLevelResultsFlat === 'function' ? getAllLevelResultsFlat() : [];
  const recent = flat.slice().sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0)).slice(0, 3);

  const bodyHtml = recent.length
    ? recent.map(r => {
        const worldLabel = r.world_id === 'world-1' ? 'World 1' : 'World 2';
        const status = HOME_ILLUSION_LABELS[r.illusion_status] || { text: r.illusion_status || '-', cls: 'balanced' };
        const gapSign = r.gap > 0 ? '+' : '';
        return `
          <div class="home-recent-row">
            <span class="home-recent-level">${worldLabel} · Level ${r.level}</span>
            <span class="home-recent-overall">${(r.overall ?? 0).toFixed(1)}</span>
            <span class="home-recent-gap">Gap ${gapSign}${(r.gap ?? 0).toFixed(1)}</span>
            <span class="home-recent-status home-recent-status--${status.cls}">${status.text}</span>
          </div>
        `;
      }).join('')
    : `<div class="analysis-empty">Chưa có level nào hoàn thành.</div>`;

  return `
    <div class="card home-recent-card">
      <div class="card-header">
        <span class="card-title">Kết quả gần đây</span>
      </div>
      <div class="home-recent-list">${bodyHtml}</div>
      <button type="button" class="home-card-link" data-target="analysis">Xem tất cả →</button>
    </div>
  `;
}

// ---- D. Quote hôm nay (1 bong bóng chat, quote có sẵn đổi theo ngày) ----

function homeQuoteBubbleInner(dayOfYear) {
  const q = QUOTES_LIST[(dayOfYear - 1) % QUOTES_LIST.length];
  return `
    <p class="home-quote-en">“${homeEscapeHtml(q.en)}”</p>
    <p class="home-quote-vi">${homeEscapeHtml(q.vi)}</p>
    <span class="home-quote-author">— ${homeEscapeHtml(q.author)}</span>
  `;
}

function homeRenderReviewWordsCard(dayOfYear) {
  return `
    <div class="card home-review-card">
      <div class="card-header">
        <span class="card-title">Quote hôm nay</span>
      </div>
      <div class="home-chat-bubble home-chat-bubble--quote" id="home-quote-bubble">${homeQuoteBubbleInner(dayOfYear)}</div>
    </div>
  `;
}

// ---- E. Mẹo hôm nay (gộp Quote + Tip cũ) ----

function homeRenderDailyTipStrip(dayOfYear) {
  const tipIndex = (dayOfYear - 1) % TIPS_LIST.length;
  const todayTip = TIPS_LIST[tipIndex];
  return `
    <div class="card home-tip-strip" id="home-tip-strip">
      <span class="home-tip-icon">${icon('lightbulb', 20)}</span>
      <span class="home-tip-text" id="home-tip-text">${homeEscapeHtml(todayTip.text)}</span>
      <span class="badge" id="home-tip-category">${homeEscapeHtml(todayTip.category)}</span>
    </div>
  `;
}

function renderHome() {
  const dayOfYear = getDayOfYear();
  if (typeof getTodayDateString === 'function') {
    homeRenderedDate = getTodayDateString();
  }

  return `
    <div class="home-bento">
      <div class="home-cell home-cell-a">${homeRenderContinueCard()}</div>
      <div class="home-cell home-cell-b">
        <div class="card ioc-index-card">
          <div class="card-header">
            <span class="card-title">Chỉ số IOC</span>
            <span class="badge">Tổng hợp</span>
          </div>
          ${homeRenderIocIndexBody()}
        </div>
      </div>
      <div class="home-cell home-cell-c">${homeRenderRecentResultsCard()}</div>
      <div class="home-cell home-cell-d">${homeRenderReviewWordsCard(dayOfYear)}</div>
      <div class="home-cell home-cell-e">${homeRenderDailyTipStrip(dayOfYear)}</div>
    </div>
  `;
}

function initHomeInteractions() {
  const continueBtn = document.querySelector('.home-continue-btn');
  if (continueBtn) {
    continueBtn.addEventListener('click', () => {
      if (typeof goToWorldPage === 'function') goToWorldPage(continueBtn.getAttribute('data-world-id'));
    });
  }

  const bear = document.querySelector('.home-continue-mascot');
  if (bear) {
    bear.addEventListener('click', () => {
      bear.classList.remove('is-jumping');
      void bear.offsetWidth;
      bear.classList.add('is-jumping');
    });
    bear.addEventListener('animationend', (e) => {
      if (e.animationName === 'bear-jump') bear.classList.remove('is-jumping');
    });
  }

  const { world, completed } = homeGetContinueWorld();
  const isFirstEver = COURSE_WORLDS.every(w => getWorldCompletedLevels(w.id) === 0);
  if (!isFirstEver) {
    homeLoadContinueTopic(world.id, Math.min(world.totalLevels, completed + 1));
  }

  document.querySelectorAll('.home-card-link[data-target]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (typeof navigateTo === 'function') navigateTo(btn.getAttribute('data-target'));
    });
  });

  startHomeDailyRefreshWatcher();
}

// Cập nhật tip trực tiếp trên DOM thay vì render lại cả trang.
function refreshDailyContentIfDateChanged() {
  if (typeof getTodayDateString !== 'function') return;
  const today = getTodayDateString();
  if (today === homeRenderedDate) return;
  homeRenderedDate = today;

  const dayOfYear = getDayOfYear();
  const tipIndex = (dayOfYear - 1) % TIPS_LIST.length;
  const todayTip = TIPS_LIST[tipIndex];

  const quoteEl = document.getElementById('home-quote-bubble');
  if (quoteEl) quoteEl.innerHTML = homeQuoteBubbleInner(dayOfYear);

  const tipTextEl = document.getElementById('home-tip-text');
  const tipCategoryEl = document.getElementById('home-tip-category');
  if (tipTextEl) tipTextEl.textContent = todayTip.text;
  if (tipCategoryEl) tipCategoryEl.textContent = todayTip.category;
}

function startHomeDailyRefreshWatcher() {
  stopHomeDailyRefreshWatcher();
  homeDailyCheckIntervalId = setInterval(refreshDailyContentIfDateChanged, 30000);
}

function stopHomeDailyRefreshWatcher() {
  if (homeDailyCheckIntervalId) {
    clearInterval(homeDailyCheckIntervalId);
    homeDailyCheckIntervalId = null;
  }
}
