// Cấu hình riêng cho World 1 - Sylvan Nightwood Realm. Toàn bộ logic sinh bản
// đồ/level nằm ở js/features/world-map.js, file này chỉ khai báo tham số.

document.addEventListener('DOMContentLoaded', () => {
  const config = {
    worldId: 'world-1',
    totalLevels: 97,
    title: 'Sylvan Nightwood Realm',
    subtitle: 'RỪNG HUYỀN DIỆU',
    backgroundImage: 'assets/images/world1background.jpg',
    theme: 'forest'
  };

  document.getElementById('world-map-root').innerHTML = renderWorldMap(config);
  initWorldMap(config);

  if (typeof initVocabList === 'function') {
    initVocabList(config.worldId);
  }
});
