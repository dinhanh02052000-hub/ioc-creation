// Nối bản đồ thiết kế (world1.html: Evergrove Realm, world2.html: Frostveil Caverns) với luồng học thật.
// Nạp trong <head>, TRƯỚC mã bản đồ, để mã bản đồ đọc được tiến độ đã lưu khi dựng.
//   window.__iocCompleted : số level đã PASS của thế giới này (từ course-progress.js)
//   window.__iocPlay(level, isReplay, onPassed) : mở trợ lý AI cho level; onPassed chạy khi đóng trợ lý mà level đã PASS
(function () {
  const WORLD = document.documentElement.dataset.world;
  const completed = () => (typeof getWorldCompletedLevels === 'function' ? getWorldCompletedLevels(WORLD) : 0);

  window.__iocCompleted = completed();

  window.__iocPlay = function (level, isReplay, onPassed) {
    if (typeof openAIChat !== 'function') {
      alert('Chưa tải được trợ lý học tập. Hãy tải lại trang.');
      return;
    }
    openAIChat(WORLD, level, () => {
      // onComplete của trợ lý chạy mỗi khi đóng, kể cả khi chưa PASS: chỉ đi tiếp trên bản đồ khi tiến độ đã lưu level này.
      if (!isReplay && completed() >= level && typeof onPassed === 'function') onPassed();
    }, !!isReplay);
  };

  document.addEventListener('DOMContentLoaded', () => {
    if (typeof initVocabList === 'function') initVocabList(WORLD);
    if (typeof initGradingGuide === 'function') initGradingGuide();
    if (typeof startPlaytimeTimer === 'function') startPlaytimeTimer();
    // Nút quay lại của bản đồ (World 1: .pill.back, World 2: #backBtn) về trang chủ.
    const back = document.getElementById('backBtn') || document.querySelector('.pill.back');
    if (back) back.addEventListener('click', (e) => { e.preventDefault(); e.stopImmediatePropagation(); location.href = '/'; }, true);
  });
})();
