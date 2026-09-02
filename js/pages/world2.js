// Cấu hình riêng cho World 2 - Frost Glaciers Realm. Toàn bộ logic sinh bản
// đồ/level nằm ở js/features/world-map.js, file này chỉ khai báo tham số.

document.addEventListener('DOMContentLoaded', () => {
  const config = {
    worldId: 'world-2',
    totalLevels: 121,
    title: 'Frost Glaciers Realm',
    subtitle: 'TUYẾT SƠN CỰC QUANG',
    backgroundImage: 'assets/images/world-2.jpg',
    theme: 'ice'
  };

  document.getElementById('world-map-root').innerHTML = renderWorldMap(config);
  initWorldMap(config);

  if (typeof initVocabList === 'function') {
    initVocabList(config.worldId);
  }
});
