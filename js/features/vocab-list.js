// ==== TỪ VỰNG ĐÃ HỌC (nút góc dưới-trái world1.html / world2.html) ====
// Hiện danh sách "tên nhóm: các từ trong nhóm" cho mọi level đã PASS ít nhất
// 1 lần, lấy dữ liệu vĩnh viễn từ course-progress.js (ioc_vocab_learned) -
// không tự fetch lại từ server ở đây, dữ liệu đã được ghi lúc PASS
// (xem chatbot.js: aiCaptureVocabLearned).

function initVocabList(worldId) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'world-map-vocab-btn';
  btn.id = 'world-map-vocab-btn';
  btn.title = 'Từ vựng đã học';
  btn.innerHTML = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
    </svg>
    <span>Từ vựng đã học</span>
  `;
  document.body.appendChild(btn);

  btn.addEventListener('click', () => openVocabListModal(worldId));
}

function vocabListEscapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

function openVocabListModal(worldId) {
  const entries = typeof getVocabLearnedList === 'function' ? getVocabLearnedList(worldId) : [];

  const overlay = document.createElement('div');
  overlay.className = 'vocab-list-overlay';
  overlay.id = 'vocab-list-overlay';

  const bodyHtml = entries.length
    ? entries.map(entry => `
        <div class="vocab-list-item">
          <div class="vocab-list-item-level">Level ${entry.level}</div>
          <div class="vocab-list-item-text">
            <strong>${vocabListEscapeHtml(entry.group_title || '(không có tên nhóm)')}</strong>:
            ${entry.words.map(w => vocabListEscapeHtml(w)).join(', ')}
          </div>
        </div>
      `).join('')
    : `<div class="vocab-list-empty">Chưa có nhóm từ nào được hoàn thành. Hoàn thành (PASS) 1 level để nhóm từ của level đó xuất hiện ở đây.</div>`;

  overlay.innerHTML = `
    <div class="vocab-list-panel">
      <div class="vocab-list-header">
        <div class="vocab-list-title">Từ vựng đã học (${entries.length} nhóm)</div>
        <button type="button" class="vocab-list-close" id="vocab-list-close" title="Đóng">✕</button>
      </div>
      <div class="vocab-list-body">${bodyHtml}</div>
    </div>
  `;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.querySelector('#vocab-list-close').addEventListener('click', close);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });
}
