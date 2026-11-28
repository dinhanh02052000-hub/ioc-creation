// Cấu hình riêng cho World 2 - Frostveil Caverns. Toàn bộ logic sinh bản
// đồ/level nằm ở js/features/world-map.js, file này chỉ khai báo tham số.

document.addEventListener('DOMContentLoaded', () => {
  const config = {
    worldId: 'world-2',
    totalLevels: 121,
    title: 'Frostveil Caverns',
    backgroundImage: 'assets/images/world2background.jpg?v=2',
    theme: 'ice'
  };

  document.getElementById('world-map-root').innerHTML = renderWorldMap(config);
  initWorldMap(config);

  if (typeof initVocabList === 'function') {
    initVocabList(config.worldId);
  }

  if (typeof initGradingGuide === 'function') {
    initGradingGuide();
  }

  // Tổng thời gian học phải chạy ở MỌI trang, không riêng gì Home.
  if (typeof startPlaytimeTimer === 'function') {
    startPlaytimeTimer();
  }
});
