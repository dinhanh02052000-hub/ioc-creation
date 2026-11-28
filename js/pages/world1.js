// Cấu hình riêng cho World 1 - Evergrove Realm. Toàn bộ logic sinh bản
// đồ/level nằm ở js/features/world-map.js, file này chỉ khai báo tham số.

document.addEventListener('DOMContentLoaded', () => {
  const config = {
    worldId: 'world-1',
    totalLevels: 97,
    title: 'Evergrove Realm',
    backgroundImage: 'assets/images/world1background.jpg?v=2',
    theme: 'forest'
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
