// ==== WORLD MAP ENGINE ====
// Dùng chung cho world1.html và world2.html. Sinh ra một con đường ngoằn
// ngoèo NẰM NGANG (trục X là hướng đi chính, dao động lên/xuống theo hàm
// sin) chứa N level, có thể cuộn ngang. world1.js / world2.js chỉ truyền
// config riêng (ảnh nền, số level, theme) vào renderWorldMap()/initWorldMap().

const WORLD_MAP_LEVEL_SPACING = 150; // khoảng cách ngang giữa 2 level liên tiếp
const WORLD_MAP_AMPLITUDE = 115; // biên độ lượn sóng lên/xuống - to hơn để phủ kín màn hình theo chiều dọc
const WORLD_MAP_LEVELS_PER_WAVE = 6; // bao nhiêu level thì lượn hết 1 chu kỳ sóng
const WORLD_MAP_PADDING_X = 170;
const WORLD_MAP_TRACK_HEIGHT = 480;
const WORLD_MAP_DECORATION_INTERVAL = 7;

function worldMapPointAt(t) {
  const x = WORLD_MAP_PADDING_X + (t - 1) * WORLD_MAP_LEVEL_SPACING;
  const angle = ((t - 1) / WORLD_MAP_LEVELS_PER_WAVE) * Math.PI * 2;
  const y = WORLD_MAP_TRACK_HEIGHT / 2 + Math.sin(angle) * WORLD_MAP_AMPLITUDE;
  return { x, y };
}

function worldMapTrackWidth(totalLevels) {
  return WORLD_MAP_PADDING_X * 2 + (totalLevels - 1) * WORLD_MAP_LEVEL_SPACING;
}

function worldMapBuildRoadPath(totalLevels) {
  const step = 0.2;
  let d = '';
  for (let t = 1; t <= totalLevels; t += step) {
    const p = worldMapPointAt(t);
    d += `${t === 1 ? 'M' : 'L'}${p.x.toFixed(1)} ${p.y.toFixed(1)} `;
  }
  const last = worldMapPointAt(totalLevels);
  d += `L${last.x.toFixed(1)} ${last.y.toFixed(1)}`;
  return d;
}

// ---- Icon trang trí quanh đường đi ----
// World "ice" vẽ tay bằng SVG (nền trong suốt tự nhiên). World "forest" dùng
// bộ 13 icon rừng/động vật trong assets/images/world1-decor (đổi từ bộ
// sticker huyền bí cũ - xem world1iconbackground2.0 gốc, đã xoá sau khi copy
// vào đây).
const WORLD_MAP_DECOR_PATH = {
  forest: 'assets/images/world1-decor/',
  ice: 'assets/images/world2-decor/'
};

const WORLD_MAP_FOREST_ICONS = [
  'animal-1.png', 'animal-2.png', 'animal-3.png', 'bear.png', 'bird.png',
  'butterfly.png', 'fox.png', 'mushroom.png', 'paw.png', 'reindeer.png',
  'rock.png', 'temple.png', 'tree.png'
];

// World 2 (ice) dùng bộ 10 icon băng tuyết/động vật trong assets/images/world2-decor
// (đổi từ bộ sticker cũ - xem world2iconbackground2.0 gốc, đã xoá sau khi copy vào đây).
const WORLD_MAP_ICE_ICONS = [
  'ice.png', 'mountain.png', 'penguin.png', 'pine-tree.png', 'polar-bear.png',
  'raccoon.png', 'reindeer.png', 'seal.png', 'snowflake.png'
];

const WORLD_MAP_DECORATIONS = {
  forest: WORLD_MAP_FOREST_ICONS,
  ice: WORLD_MAP_ICE_ICONS
};

function worldMapBuildDecorations(totalLevels, theme) {
  const variants = WORLD_MAP_DECORATIONS[theme] || [];
  if (!variants.length) return '';

  let html = '';
  let i = 0;
  for (let level = 4; level < totalLevels; level += WORLD_MAP_DECORATION_INTERVAL) {
    const p = worldMapPointAt(level + 0.5);
    const lane = i % 2 === 0 ? -1 : 1;
    const y = WORLD_MAP_TRACK_HEIGHT / 2 + lane * (WORLD_MAP_AMPLITUDE + 55);
    const size = 70 + (i % 4) * 20;
    const variant = variants[i % variants.length];
    const inner = typeof variant === 'string'
      ? `<img src="${WORLD_MAP_DECOR_PATH[theme] || ''}${variant}" alt="" loading="lazy">`
      : variant();

    html += `
      <div class="world-map-decoration" style="left:${(p.x - size / 2).toFixed(0)}px; top:${(y - size / 2).toFixed(0)}px; width:${size}px; height:${size}px;">
        ${inner}
      </div>
    `;
    i++;
  }
  return html;
}

// ---- Level node (chốt trên đường đi) ----

function worldMapNodeIcon(state) {
  if (state === 'completed') {
    return `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5l3.2 3.2L13 5"/></svg>`;
  }
  if (state === 'locked') {
    return `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="7" width="9" height="6" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/></svg>`;
  }
  return null;
}

const WORLD_MAP_ILLUSION_LABELS = {
  DETECTED: 'IOC Detected',
  UNDERCONFIDENT: 'Underconfidence Detected',
  CALIBRATED: 'Good'
};

function worldMapBuildNodes(totalLevels, completed, worldId) {
  let html = '';
  for (let level = 1; level <= totalLevels; level++) {
    const p = worldMapPointAt(level);
    let state = 'locked';
    if (level <= completed) state = 'completed';
    else if (level === completed + 1) state = 'current';

    const icon = worldMapNodeIcon(state);
    const inner = icon || level;
    // completed cũng bấm được để chơi lại - chỉ locked mới thực sự khoá.
    const disabledAttr = state === 'locked' ? 'disabled' : '';

    // Badge kết quả (overall + trạng thái) - chỉ 1 khối duy nhất, canh giữa
    // dưới node bằng flex, không còn 2 phần tử định vị tuyệt đối chồng nhau.
    // Lấy kết quả cho cả node "current" (không chỉ "completed"): 1 lượt RETRY
    // không làm level được coi là completed (chỉ PASS mới tiến level), nhưng
    // kết quả vẫn phải hiển thị ngay dưới level đó dù pass hay không.
    const levelResults = state !== 'locked' ? worldMapGetLevelResults(worldId, level) : null;
    let badgeHtml = '';
    if (levelResults && levelResults.accuracy != null) {
      const dotColor = (levelResults.illusion_status === 'DETECTED' || levelResults.illusion_status === 'UNDERCONFIDENT')
        ? 'red' : 'green';
      const statusLabel = WORLD_MAP_ILLUSION_LABELS[levelResults.illusion_status] || '';
      badgeHtml = `
        <div class="world-map-node-badge">
          <span class="world-map-node-badge-score">Overall: ${levelResults.accuracy.toFixed(1)}</span>
          ${statusLabel ? `<span class="world-map-node-badge-status world-map-node-badge-status--${dotColor}">${statusLabel}</span>` : ''}
        </div>
      `;
    }

    html += `
      <button
        type="button"
        class="world-map-node world-map-node--${state}"
        style="left:${p.x.toFixed(0)}px; top:${p.y.toFixed(0)}px;"
        data-level="${level}"
        ${disabledAttr}
      >${inner}${badgeHtml}</button>
    `;
  }
  return html;
}

function worldMapGetLevelResults(worldId, level) {
  // Lấy kết quả level từ localStorage (được lưu ở chatbot.js)
  if (typeof getLevelResults === 'function') {
    return getLevelResults(worldId, level);
  }
  return null;
}

function renderWorldMap(config) {
  const completed = Math.min(config.totalLevels, getWorldCompletedLevels(config.worldId));
  const currentLevel = Math.min(config.totalLevels, completed + 1);
  const trackWidth = worldMapTrackWidth(config.totalLevels);
  const roadPath = worldMapBuildRoadPath(config.totalLevels);
  const decorationsHtml = worldMapBuildDecorations(config.totalLevels, config.theme);
  const nodesHtml = worldMapBuildNodes(config.totalLevels, completed, config.worldId);

  return `
    <div class="world-map-page world-map--${config.theme}">
      <div class="world-map-bg" style="background-image: url('${config.backgroundImage}');"></div>
      <div class="world-map-overlay"></div>

      <div class="world-map-position-badge">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-6.1-7-11.5A7 7 0 0 1 19 9.5C19 14.9 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.4"/></svg>
        <span>Vị trí hiện tại: Level ${currentLevel}</span>
      </div>

      <header class="world-map-header">
        <a href="/" class="world-map-back">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3L5 8l5 5"/></svg>
          <span>Quay lại</span>
        </a>
        <div class="world-map-heading">
          <h1>${config.title}</h1>
          <p>${config.subtitle}</p>
        </div>
        <div class="world-map-progress-pill">Level ${completed} / ${config.totalLevels}</div>
      </header>

      <div class="world-map-scroll" id="world-map-scroll">
        <div class="world-map-track" style="width:${trackWidth}px; height:${WORLD_MAP_TRACK_HEIGHT}px;">
          <svg class="world-map-road" width="${trackWidth}" height="${WORLD_MAP_TRACK_HEIGHT}" viewBox="0 0 ${trackWidth} ${WORLD_MAP_TRACK_HEIGHT}">
            <defs>
              <filter id="worldMapRoadGlow" x="-30%" y="-30%" width="160%" height="160%">
                <feGaussianBlur stdDeviation="7" />
              </filter>
            </defs>
            <path d="${roadPath}" class="world-map-road-glow" filter="url(#worldMapRoadGlow)"></path>
            <path d="${roadPath}" class="world-map-road-base"></path>
            <path d="${roadPath}" class="world-map-road-highlight"></path>
            <path d="${roadPath}" class="world-map-road-dash"></path>
          </svg>
          ${decorationsHtml}
          ${nodesHtml}
        </div>
      </div>
    </div>
  `;
}

function initWorldMap(config) {
  const root = document.getElementById('world-map-root');
  const scrollEl = document.getElementById('world-map-scroll');

  // "completed" cũng bấm được để chơi lại màn đã qua - không chỉ "current".
  // Chỉ "locked" mới thực sự không cho bấm (đã có [disabled] trên nút đó).
  document.querySelectorAll('.world-map-node--current, .world-map-node--completed').forEach(btn => {
    btn.addEventListener('click', () => {
      const level = parseInt(btn.getAttribute('data-level'), 10);
      const isReplay = btn.classList.contains('world-map-node--completed');

      // Chat AI đã bật cho toàn bộ level 2 world (trừ 3 level KB đang hỏng -
      // xem WORLD_MAP_AI_ENABLED_LEVELS). Backend (server/main.py) tự map
      // (worldId, level) -> đúng file KB tương ứng, không cần sửa gì thêm ở
      // đây khi thêm/bớt level được bật.
      if (typeof openAIChat === 'function' && worldMapIsAIEnabled(config.worldId, level)) {
        // isReplay=true -> truyền isRetry cho backend để sinh bộ câu hỏi mới,
        // khác lần trước, thay vì lặp lại y hệt.
        openAIChat(config.worldId, level, () => {
          root.innerHTML = renderWorldMap(config);
          initWorldMap(config);
        }, isReplay);
        return;
      }

      if (isReplay) return; // level demo (chưa có AI) không có gì để chơi lại

      const confirmed = window.confirm(
        `Đánh dấu hoàn thành Level ${level}? (demo - chưa có nội dung bài học thật)`
      );
      if (!confirmed) return;

      advanceWorldCompletedLevels(config.worldId, level);
      root.innerHTML = renderWorldMap(config);
      initWorldMap(config);
    });
  });

  // Tự cuộn ngang tới level hiện tại mỗi khi (re)render.
  if (scrollEl) {
    const completed = getWorldCompletedLevels(config.worldId);
    const currentLevel = Math.min(config.totalLevels, completed + 1);
    const p = worldMapPointAt(currentLevel);
    scrollEl.scrollLeft = Math.max(0, p.x - scrollEl.clientWidth / 2);
  }
}

function worldMapRange(n) {
  return Array.from({ length: n }, (_, i) => i + 1);
}

// World 1: bật AI cho toàn bộ 97 level (KB: database/vocab b2 database/vocab-b2-001..097.json).
// World 2: bật AI cho toàn bộ 121 level (KB: database/vocab c1 database/vocab-c1-001..121.json).
// Level 87-89 trước đó có file KB hỏng (byte rỗng), đã được cập nhật lại nội dung mới và
// validate sạch (xem database/vocab c1 database/vocab-c1-087/088/089.json).
const WORLD_MAP_AI_ENABLED_LEVELS = {
  'world-1': worldMapRange(97),
  'world-2': worldMapRange(121),
};

function worldMapIsAIEnabled(worldId, level) {
  const levels = WORLD_MAP_AI_ENABLED_LEVELS[worldId];
  return Array.isArray(levels) && levels.includes(level);
}
