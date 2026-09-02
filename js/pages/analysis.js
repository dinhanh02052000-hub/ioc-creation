// ==== TRANG ANALYSIS ====
// Ô 1 (điểm trung bình + trạng thái năng lực) tính THUẦN CLIENT-SIDE từ dữ
// liệu đã lưu (course-progress.js), không cần AI. Ô 2/3/4 gọi AI (server/
// analysis_prompts.py) - CHỈ gọi khi người dùng mở trang này (không chạy nền
// liên tục), và tự cache theo "chữ ký" dữ liệu đầu vào nên nếu chưa có level
// nào mới hoàn thành thì không gọi lại API vô ích.

const ANALYSIS_CACHE_KEY = 'ioc_analysis_cache'; // { signature, result: {weak_patterns, improvement_tips, encouragement} }
const ANALYSIS_ILLUSION_META = {
  DETECTED: { label: 'IOC Detected', dot: 'red' },
  UNDERCONFIDENT: { label: 'Underconfidence Detected', dot: 'red' },
  CALIBRATED: { label: 'Good', dot: 'green' }
};

function analysisEscapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

function analysisClassifyIllusion(gap) {
  if (gap > 1) return 'DETECTED';
  if (-gap > 1) return 'UNDERCONFIDENT';
  return 'CALIBRATED';
}

function analysisComputeAggregate() {
  const flat = typeof getAllLevelResultsFlat === 'function' ? getAllLevelResultsFlat() : [];
  if (!flat.length) return null;

  const sums = { recognition: 0, distinction: 0, application: 0, overall: 0, confidence: 0 };
  flat.forEach(r => {
    sums.recognition += r.recognition;
    sums.distinction += r.distinction;
    sums.application += r.application;
    sums.overall += r.overall;
    sums.confidence += r.confidence;
  });

  const n = flat.length;
  const avg = {
    recognition: sums.recognition / n,
    distinction: sums.distinction / n,
    application: sums.application / n,
    overall: sums.overall / n,
    confidence: sums.confidence / n
  };
  const gap = avg.confidence - avg.overall;

  return { ...avg, gap, illusion_status: analysisClassifyIllusion(gap), levelCount: n };
}

function analysisScoreRowHtml(label, value) {
  const pct = Math.max(0, Math.min(100, (value / 10) * 100));
  return `
    <div class="analysis-score-row">
      <div class="analysis-score-label">${label}</div>
      <div class="analysis-score-bar"><div class="analysis-score-bar-fill" style="width:${pct}%;"></div></div>
      <div class="analysis-score-value">${value.toFixed(1)}</div>
    </div>
  `;
}

function analysisRenderBox1(agg) {
  if (!agg) {
    return `<div class="analysis-empty">Bạn chưa hoàn thành level nào. Hãy làm bài ở World 1 hoặc World 2 để xem điểm tổng hợp tại đây.</div>`;
  }
  const meta = ANALYSIS_ILLUSION_META[agg.illusion_status] || { label: agg.illusion_status, dot: 'red' };
  return `
    ${analysisScoreRowHtml('Recognition', agg.recognition)}
    ${analysisScoreRowHtml('Distinction', agg.distinction)}
    ${analysisScoreRowHtml('Application', agg.application)}
    ${analysisScoreRowHtml('Overall', agg.overall)}
    <div class="analysis-illusion-row">
      <span class="analysis-status-dot analysis-status-dot--${meta.dot}"></span>
      <span>${meta.label}</span>
      <span class="analysis-illusion-hint">(trung bình ${agg.levelCount} level đã làm)</span>
    </div>
  `;
}

function analysisPickWeakGroups(limit) {
  const flat = typeof getAllLevelResultsFlat === 'function' ? getAllLevelResultsFlat() : [];
  return flat
    .slice()
    .sort((a, b) => a.overall - b.overall)
    .slice(0, limit)
    .map(r => ({
      world_id: r.world_id,
      level: r.level,
      group_title: r.group_title || `Level ${r.level}`,
      overall: r.overall,
      wrong_words: r.wrong_words || [],
      distinction_feedback: r.distinction_feedback || null,
      application_feedback: r.application_feedback || null
    }));
}

function analysisSignature(groups) {
  return groups.map(g => `${g.world_id}:${g.level}:${g.overall}:${(g.wrong_words || []).length}`).sort().join('|');
}

function analysisLoadCache() {
  try {
    const data = JSON.parse(localStorage.getItem(ANALYSIS_CACHE_KEY));
    return data && typeof data === 'object' ? data : null;
  } catch (e) {
    return null;
  }
}

function analysisSaveCache(signature, result) {
  try {
    localStorage.setItem(ANALYSIS_CACHE_KEY, JSON.stringify({ signature, result, timestamp: Date.now() }));
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function renderAnalysis() {
  const agg = analysisComputeAggregate();

  return `
    <div class="analysis-page">
      <h1 class="analysis-heading">Your Learning Performance</h1>

      <div class="analysis-grid">
        <div class="card analysis-card" id="analysis-box-1">
          <div class="card-header">
            <span class="card-title">BẢNG ĐIỂM TỔNG HỢP</span>
            <span class="badge">Tất cả level</span>
          </div>
          ${analysisRenderBox1(agg)}
        </div>

        <div class="card analysis-card" id="analysis-box-2">
          <div class="card-header">
            <span class="card-title">XU HƯỚNG NHẦM LẪN TỪ VỰNG</span>
            <span class="badge">AI phân tích</span>
          </div>
          <div class="analysis-box-body" id="analysis-box-2-body"></div>
        </div>

        <div class="card analysis-card" id="analysis-box-3">
          <div class="card-header">
            <span class="card-title">GỢI Ý CẢI THIỆN</span>
            <span class="badge">AI phân tích</span>
          </div>
          <div class="analysis-box-body" id="analysis-box-3-body"></div>
        </div>

        <div class="card analysis-card" id="analysis-box-4">
          <div class="card-header">
            <span class="card-title">LỜI ĐỘNG VIÊN</span>
            <span class="badge">AI phân tích</span>
          </div>
          <div class="analysis-box-body" id="analysis-box-4-body"></div>
        </div>
      </div>
    </div>
  `;
}

function analysisRenderAIResult(result) {
  const box2 = document.getElementById('analysis-box-2-body');
  const box3 = document.getElementById('analysis-box-3-body');
  const box4 = document.getElementById('analysis-box-4-body');

  if (box2) {
    const patterns = result.weak_patterns || [];
    box2.innerHTML = patterns.length
      ? patterns.map(p => `
          <div class="analysis-pattern-item">
            <div class="analysis-pattern-title">${analysisEscapeHtml(p.group_title)}</div>
            <p>${analysisEscapeHtml(p.analysis)}</p>
          </div>
        `).join('')
      : `<div class="analysis-empty">Chưa có đủ dữ liệu.</div>`;
  }

  if (box3) {
    const tips = result.improvement_tips || [];
    box3.innerHTML = tips.length
      ? `<div class="analysis-tips-list">${tips.map(t => `
          <div class="analysis-tip-item">
            <div class="analysis-tip-word">${analysisEscapeHtml(t.word)}</div>
            <p><strong>Mẹo:</strong> ${analysisEscapeHtml(t.tip)}</p>
            <p><strong>Lỗi thường gặp:</strong> ${analysisEscapeHtml(t.common_mistake)}</p>
          </div>
        `).join('')}</div>`
      : `<div class="analysis-empty">Chưa có đủ dữ liệu.</div>`;
  }

  if (box4) {
    box4.innerHTML = `<p class="analysis-encouragement">${analysisEscapeHtml(result.encouragement || '')}</p>`;
  }
}

function analysisRenderAILoading() {
  ['analysis-box-2-body', 'analysis-box-3-body', 'analysis-box-4-body'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = `<div class="ai-loading"><div class="ai-spinner"></div><span>Đang phân tích...</span></div>`;
  });
}

function analysisRenderAIError(message, onRetry) {
  ['analysis-box-2-body', 'analysis-box-3-body', 'analysis-box-4-body'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '';
  });
  const box2 = document.getElementById('analysis-box-2-body');
  if (box2) {
    box2.innerHTML = `
      <div class="ai-error">${analysisEscapeHtml(message)}</div>
      <button type="button" class="ai-btn" id="analysis-retry-btn">Thử lại</button>
    `;
    const btn = document.getElementById('analysis-retry-btn');
    if (btn) btn.addEventListener('click', onRetry);
  }
}

async function analysisRunAI(forceRefresh) {
  const groups = analysisPickWeakGroups(5);
  if (!groups.length) {
    ['analysis-box-2-body', 'analysis-box-3-body', 'analysis-box-4-body'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = `<div class="analysis-empty">Hoàn thành ít nhất 1 level để xem phân tích.</div>`;
    });
    return;
  }

  const signature = analysisSignature(groups);
  const cache = analysisLoadCache();
  if (!forceRefresh && cache && cache.signature === signature && cache.result) {
    analysisRenderAIResult(cache.result);
    return;
  }

  analysisRenderAILoading();
  try {
    const result = await gestureGenerateAnalysis(groups);
    analysisSaveCache(signature, result);
    analysisRenderAIResult(result);
  } catch (e) {
    analysisRenderAIError(e.message, () => analysisRunAI(true));
  }
}

function initAnalysisInteractions() {
  analysisRunAI(false);
}
