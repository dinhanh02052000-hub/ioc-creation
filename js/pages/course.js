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
      <h1 class="analysis-heading">Lộ trình học</h1>
      <p class="page-desc">Từ vựng tiếng Anh theo trường nghĩa</p>
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
          <span class="world-levels-pill">${world.totalLevels} level</span>
          <div class="world-menu-wrap">
            <button type="button" class="world-menu-btn" data-world-id="${world.id}" aria-haspopup="true" aria-expanded="false" aria-label="Thêm tuỳ chọn">
              ${icon('moreHorizontal', 18)}
            </button>
            <div class="world-menu" hidden>
              <button type="button" class="world-replay-btn" data-world-id="${world.id}">
                ${icon('x', 14)}<span>Chơi lại từ đầu</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="world-panel">
        <h2 class="world-name">${world.name}</h2>
        <p class="world-subtitle-text">${world.subtitle}</p>

        <div class="world-progress-bar">
          <div class="world-progress-fill" id="world-fill-${world.id}" style="width: ${percent}%;"></div>
        </div>
        <div class="world-progress-footer">
          <span id="world-passed-${world.id}">${completed}/${world.totalLevels} level</span>
          <span id="world-percent-${world.id}">${percent}%</span>
        </div>

        <button type="button" class="ai-btn world-continue-btn" data-world-id="${world.id}">
          Tiếp tục
        </button>
      </div>
    </div>
  `;
}

function updateWorldProgressUI(world) {
  const completed = getWorldCompletedLevels(world.id);
  const percent = Math.min(100, Math.round((completed / world.totalLevels) * 100));

  const fillEl = document.getElementById(`world-fill-${world.id}`);
  const passedEl = document.getElementById(`world-passed-${world.id}`);
  const percentEl = document.getElementById(`world-percent-${world.id}`);

  if (fillEl) fillEl.style.width = `${percent}%`;
  if (passedEl) passedEl.textContent = `${completed}/${world.totalLevels} level`;
  if (percentEl) percentEl.textContent = `${percent}%`;
}

function goToWorldPage(worldId) {
  const world = COURSE_WORLDS.find(w => w.id === worldId);
  if (world && world.page) {
    window.location.href = world.page;
  }
}

function closeAllWorldMenus() {
  document.querySelectorAll('.world-menu').forEach(m => { m.hidden = true; });
  document.querySelectorAll('.world-menu-btn').forEach(b => b.setAttribute('aria-expanded', 'false'));
}

function initCourseInteractions() {
  document.querySelectorAll('.world-menu-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const menu = btn.nextElementSibling;
      const wasHidden = menu.hidden;
      closeAllWorldMenus();
      if (wasHidden) {
        menu.hidden = false;
        btn.setAttribute('aria-expanded', 'true');
      }
    });
  });
  document.addEventListener('click', closeAllWorldMenus);

  document.querySelectorAll('.world-replay-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      closeAllWorldMenus();
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
      if (e.target.closest('.world-menu-wrap') || e.target.closest('.world-continue-btn')) return;
      goToWorldPage(card.getAttribute('data-world-id'));
    });
  });
}
