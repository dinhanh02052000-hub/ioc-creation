// Danh sách "thế giới" từ vựng dùng để render trang Course. Tiến trình đọc/ghi
// qua js/features/course-progress.js, dùng chung với các trang world.

const COURSE_WORLDS = [
  {
    id: 'world-1',
    label: 'WORLD 1',
    name: 'Sylvan Nightwood Realm',
    subtitle: 'RỪNG HUYỀN DIỆU',
    image: 'assets/images/world1icon.jpg',
    totalLevels: 97,
    accent: 'green',
    page: 'world1.html'
  },
  {
    id: 'world-2',
    label: 'WORLD 2',
    name: 'Frost Glaciers Realm',
    subtitle: 'TUYẾT SƠN CỰC QUANG',
    image: 'assets/images/world-2.jpg',
    totalLevels: 121,
    accent: 'blue',
    page: 'world2.html'
  }
];

function renderCourse() {
  const worldCardsHtml = COURSE_WORLDS.map(renderWorldCard).join('');

  return `
    <div class="course-page">
      <div class="course-header">
        <h1 class="course-title">VOCABULARY <span class="course-title-accent">JOURNEY</span></h1>
        <p class="course-subtitle">
          Hành trình chinh phục từ vựng tiếng Anh qua ${COURSE_WORLDS.length} thế giới
          <span class="course-hint">• Nhấp vào thẻ để bắt đầu hành trình</span>
        </p>
      </div>
      <div class="world-grid">
        ${worldCardsHtml}
      </div>
    </div>
  `;
}

function renderWorldCard(world) {
  const completed = getWorldCompletedLevels(world.id);
  const percent = Math.min(100, Math.round((completed / world.totalLevels) * 100));

  return `
    <div class="world-card" data-accent="${world.accent}" data-world-id="${world.id}">
      <div class="world-art" style="background-image: url('${world.image}');">
        <div class="world-art-top">
          <span class="world-badge-pill">${world.label}</span>
          <span class="world-levels-pill">${world.totalLevels} Levels</span>
        </div>
        <div class="world-art-info">
          <h2 class="world-name">${world.name}</h2>
          <p class="world-subtitle-text">${world.subtitle}</p>
        </div>
      </div>

      <div class="world-panel">
        <div class="world-progress-header">
          <span>TIẾN TRÌNH HOÀN THÀNH</span>
          <span class="world-progress-level" id="world-level-${world.id}">Level ${completed} / ${world.totalLevels}</span>
        </div>
        <div class="world-progress-bar">
          <div class="world-progress-fill" id="world-fill-${world.id}" style="width: ${percent}%;"></div>
        </div>
        <div class="world-progress-footer">
          <span id="world-passed-${world.id}">Đã qua ${completed} màn</span>
          <span id="world-percent-${world.id}">${percent}% Hoàn thành</span>
        </div>

        <div class="world-actions">
          <button type="button" class="world-continue-btn" data-world-id="${world.id}">
            <span>Tiếp tục</span>
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M6 3l5 5-5 5" />
            </svg>
          </button>
          <button type="button" class="world-replay-btn" data-world-id="${world.id}" title="Chơi lại từ đầu">
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 10a7 7 0 0 1 12-4.95M17 10a7 7 0 0 1-12 4.95" />
              <path d="M15 2v4h-4M5 18v-4h4" />
            </svg>
            <span>Chơi lại</span>
          </button>
        </div>
      </div>
    </div>
  `;
}

function updateWorldProgressUI(world) {
  const completed = getWorldCompletedLevels(world.id);
  const percent = Math.min(100, Math.round((completed / world.totalLevels) * 100));

  const levelEl = document.getElementById(`world-level-${world.id}`);
  const fillEl = document.getElementById(`world-fill-${world.id}`);
  const passedEl = document.getElementById(`world-passed-${world.id}`);
  const percentEl = document.getElementById(`world-percent-${world.id}`);

  if (levelEl) levelEl.textContent = `Level ${completed} / ${world.totalLevels}`;
  if (fillEl) fillEl.style.width = `${percent}%`;
  if (passedEl) passedEl.textContent = `Đã qua ${completed} màn`;
  if (percentEl) percentEl.textContent = `${percent}% Hoàn thành`;
}

function goToWorldPage(worldId) {
  const world = COURSE_WORLDS.find(w => w.id === worldId);
  if (world && world.page) {
    window.location.href = world.page;
  }
}

function initCourseInteractions() {
  document.querySelectorAll('.world-replay-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const worldId = btn.getAttribute('data-world-id');
      const world = COURSE_WORLDS.find(w => w.id === worldId);
      if (!world) return;

      const confirmed = window.confirm(`Chơi lại từ đầu "${world.name}"? Tiến trình sẽ về 0.`);
      if (!confirmed) return;

      resetWorldProgress(worldId);
      updateWorldProgressUI(world);
    });
  });

  document.querySelectorAll('.world-continue-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      goToWorldPage(btn.getAttribute('data-world-id'));
    });
  });

  document.querySelectorAll('.world-card').forEach(card => {
    card.addEventListener('click', (e) => {
      if (e.target.closest('.world-replay-btn') || e.target.closest('.world-continue-btn')) return;
      goToWorldPage(card.getAttribute('data-world-id'));
    });
  });
}
