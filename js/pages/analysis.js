// Ô 1 tính thuần client-side từ dữ liệu đã lưu, không cần AI. Ô 2/3/4 gọi AI
// (server/analysis_prompts.py) khi mở trang, kết quả cache theo "chữ ký" dữ
// liệu đầu vào để tránh gọi lại API khi chưa có level nào mới hoàn thành.

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
  const gapSign = agg.gap > 0 ? '+' : '';
  return `
    <div class="analysis-iocbig-top">
      ${analysisScoreRowHtml('Ảo tưởng (Confidence)', agg.confidence)}
      ${analysisScoreRowHtml('Thực tế (Overall)', agg.overall)}
    </div>
    <div class="analysis-illusion-row">
      <span class="analysis-status-dot analysis-status-dot--${meta.dot}"></span>
      <span>GAP: ${gapSign}${agg.gap.toFixed(1)}</span>
      <span class="analysis-illusion-hint">${meta.label} · trung bình ${agg.levelCount} level đã làm</span>
    </div>
  `;
}

function analysisRenderScoreBreakdown(agg) {
  if (!agg) return `<div class="analysis-empty">Chưa có dữ liệu.</div>`;
  return `
    ${analysisScoreRowHtml('Nhận diện (Recognition)', agg.recognition)}
    ${analysisScoreRowHtml('Phân biệt (Distinction)', agg.distinction)}
    ${analysisScoreRowHtml('Vận dụng (Application)', agg.application)}
    ${analysisScoreRowHtml('Tổng hợp (Overall)', agg.overall)}
  `;
}

function analysisRenderLevelTable() {
  const flat = typeof getAllLevelResultsFlat === 'function' ? getAllLevelResultsFlat() : [];
  const sorted = flat.slice().sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
  if (!sorted.length) return `<div class="analysis-empty">Chưa có level nào hoàn thành.</div>`;

  const rows = sorted.map(r => {
    const worldLabel = r.world_id === 'world-1' ? 'World 1' : 'World 2';
    const meta = ANALYSIS_ILLUSION_META[r.illusion_status] || { label: r.illusion_status || '-', dot: 'red' };
    const gapSign = r.gap > 0 ? '+' : '';
    return `
      <tr>
        <td>${worldLabel} · Level ${r.level}</td>
        <td>${(r.overall ?? 0).toFixed(1)}</td>
        <td>${(r.confidence ?? 0).toFixed(1)}</td>
        <td>${gapSign}${(r.gap ?? 0).toFixed(1)}</td>
        <td><span class="analysis-status-dot analysis-status-dot--${meta.dot}"></span> ${meta.label}</td>
      </tr>
    `;
  }).join('');

  return `
    <table class="analysis-level-table">
      <thead><tr><th>Level</th><th>Overall</th><th>Tự tin</th><th>Gap</th><th>Trạng thái</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
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
      <h1 class="analysis-heading">Kết quả học tập</h1>

      <div class="analysis-grid">
        <div class="card analysis-card analysis-iocbig" id="analysis-box-1">
          <div class="card-header">
            <span class="card-title">Chỉ số IOC</span>
            <span class="badge">Tất cả level</span>
          </div>
          ${analysisRenderBox1(agg)}
        </div>

        <div class="card analysis-card analysis-span6">
          <div class="card-header"><span class="card-title">Bảng điểm tổng hợp</span></div>
          ${analysisRenderScoreBreakdown(agg)}
        </div>

        <div class="card analysis-card analysis-span6">
          <div class="card-header"><span class="card-title">Theo từng level</span></div>
          <div class="analysis-table-wrap">${analysisRenderLevelTable()}</div>
        </div>

        <div class="card analysis-card analysis-span4" id="analysis-box-2">
          <div class="card-header">
            <span class="card-title">Xu hướng nhầm lẫn</span>
            <span class="badge">AI phân tích</span>
          </div>
          <div class="analysis-box-body" id="analysis-box-2-body"></div>
        </div>

        <div class="card analysis-card analysis-span4" id="analysis-box-3">
          <div class="card-header">
            <span class="card-title">Gợi ý cải thiện</span>
            <span class="badge">AI phân tích</span>
          </div>
          <div class="analysis-box-body" id="analysis-box-3-body"></div>
        </div>

        <div class="card analysis-card analysis-span4" id="analysis-box-4">
          <div class="card-header">
            <span class="card-title">Lời động viên</span>
            <span class="badge">AI phân tích</span>
          </div>
          <div class="analysis-box-body" id="analysis-box-4-body"></div>
        </div>
      </div>
    </div>
  `;
}

// "Xem thêm": hiện 2 mục đầu, phần còn lại ẩn tới khi bấm - thay cho thanh
// cuộn trong ô (mục 4 của spec redesign: không có thanh cuộn trong thẻ).
function analysisWrapShowMore(containerId, items, itemsHtml) {
  if (items.length <= 2) return itemsHtml.join('');
  const visible = itemsHtml.slice(0, 2).join('');
  const hidden = itemsHtml.slice(2).join('');
  return `
    ${visible}
    <div class="analysis-showmore-extra" hidden>${hidden}</div>
    <button type="button" class="home-card-link analysis-showmore-btn" data-container="${containerId}">Xem thêm (${items.length - 2})</button>
  `;
}

function analysisInitShowMoreButtons() {
  document.querySelectorAll('.analysis-showmore-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const extra = btn.previousElementSibling;
      if (extra) extra.hidden = false;
      btn.hidden = true;
    });
  });
}

function analysisRenderAIResult(result) {
  const box2 = document.getElementById('analysis-box-2-body');
  const box3 = document.getElementById('analysis-box-3-body');
  const box4 = document.getElementById('analysis-box-4-body');

  if (box2) {
    const patterns = result.weak_patterns || [];
    const itemsHtml = patterns.map(p => `
      <div class="analysis-pattern-item">
        <div class="analysis-pattern-title">${analysisEscapeHtml(p.group_title)}</div>
        <p>${analysisEscapeHtml(p.analysis)}</p>
      </div>
    `);
    box2.innerHTML = patterns.length
      ? analysisWrapShowMore('analysis-box-2-body', patterns, itemsHtml)
      : `<div class="analysis-empty">Chưa có đủ dữ liệu.</div>`;
  }

  if (box3) {
    const tips = result.improvement_tips || [];
    const itemsHtml = tips.map(t => `
      <div class="analysis-tip-item">
        <div class="analysis-tip-word">${analysisEscapeHtml(t.word)}</div>
        <p><strong>Mẹo:</strong> ${analysisEscapeHtml(t.tip)}</p>
        <p><strong>Lỗi thường gặp:</strong> ${analysisEscapeHtml(t.common_mistake)}</p>
      </div>
    `);
    box3.innerHTML = tips.length
      ? analysisWrapShowMore('analysis-box-3-body', tips, itemsHtml)
      : `<div class="analysis-empty">Chưa có đủ dữ liệu.</div>`;
  }

  if (box4) {
    box4.innerHTML = `<p class="analysis-encouragement">${analysisEscapeHtml(result.encouragement || '')}</p>`;
  }

  analysisInitShowMoreButtons();
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
