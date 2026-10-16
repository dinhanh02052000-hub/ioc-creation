// Trang "Từ đã học" - tổng hợp từ vựng đã học của CẢ 2 world vào 1 chỗ
// (trước đây chỉ xem được riêng từng world qua nút nổi trong world1/world2.html).
// Dùng lại đúng getVocabLearnedList() ở course-progress.js, không thêm nguồn
// dữ liệu mới.

function vocabEscapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

function vocabRenderWorldSection(world) {
  const entries = typeof getVocabLearnedList === 'function' ? getVocabLearnedList(world.id) : [];

  const bodyHtml = entries.length
    ? entries.map(e => `
        <div class="vocab-group-item">
          <div class="vocab-group-level">Level ${e.level}</div>
          <div class="vocab-group-body">
            <strong>${vocabEscapeHtml(e.group_title || 'Nhóm từ')}</strong>
            <span>${e.words.map(vocabEscapeHtml).join(', ')}</span>
          </div>
        </div>
      `).join('')
    : `<div class="analysis-empty">Chưa có nhóm từ nào. Hoàn thành (PASS) 1 level của ${world.label} để từ vựng xuất hiện ở đây.</div>`;

  return `
    <div class="card vocab-world-card">
      <div class="card-header">
        <span class="card-title">${world.label} - ${world.name}</span>
        <span class="badge">${entries.length} nhóm</span>
      </div>
      <div class="vocab-group-list">${bodyHtml}</div>
    </div>
  `;
}

function renderVocab() {
  const worldsHtml = COURSE_WORLDS.map(vocabRenderWorldSection).join('');
  return `
    <div class="vocab-page">
      <h1 class="analysis-heading">Từ vựng đã học</h1>
      <p class="page-desc">Tổng hợp tất cả nhóm từ bạn đã hoàn thành (PASS), theo từng world.</p>
      <div class="vocab-world-grid">${worldsHtml}</div>
    </div>
  `;
}

function initVocabInteractions() {
  // Trang này chỉ hiển thị, không có tương tác riêng.
}
