// ==== AI CHATBOT UI ====
// Khung chat nổi cho level có bật AI: chỉ lo hiển thị + thu thập input, mọi
// gọi mạng đi qua gesture.js, điểm/PASS-RETRY do backend quyết định.
//
// aiChat.stage đánh dấu giai đoạn UI hiện tại và được lưu vào localStorage
// (qua course-progress.js) sau mỗi bước, để đóng modal giữa chừng rồi mở lại
// vẫn tiếp tục đúng chỗ thay vì phải làm lại từ đầu.

const AI_CONFIDENCE_QUESTION =
  'Sau khi xem đáp án và lời giải, bạn tự đánh giá mức độ tự tin của mình trong việc phân biệt và sử dụng các từ này trong một ngữ cảnh mới là bao nhiêu trên thang điểm 10?';

// Phải khớp với config.title/subtitle trong js/pages/world1.js và world2.js.
const AI_WORLD_META = {
  'world-1': { title: 'Sylvan Nightwood Realm', subtitle: 'Rừng Huyền Diệu' },
  'world-2': { title: 'Frost Glaciers Realm', subtitle: 'Tuyết Sơn Cực Quang' }
};

function aiWelcomeMessage(worldId, level) {
  const meta = AI_WORLD_META[worldId];
  const worldLabel = meta ? `${meta.title} - ${meta.subtitle}` : worldId;
  return `🗺️ Chào mừng bạn đến <strong>Level ${level}</strong> tại <strong>${worldLabel}</strong>! Cùng khám phá nhóm từ mới và chinh phục thử thách phía trước nhé.`;
}

let aiChat = null;
let aiChatEls = null; // { overlay, body, footer }
let aiPersistTimer = null;

function aiEscapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

// Escape HTML trước, rồi mới dịch markdown sang thẻ HTML — tránh chèn HTML
// thô của AI trực tiếp vào DOM.
function aiInlineMarkdown(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+?)\*/g, '<strong>$1</strong>')
    .replace(/`(.+?)`/g, '<code>$1</code>');
}

function aiMarkdownToHtml(rawText) {
  const escaped = aiEscapeHtml(rawText);
  const lines = escaped.split('\n');
  let html = '';
  let inList = false;
  const closeList = () => { if (inList) { html += '</ul>'; inList = false; } };

  lines.forEach(rawLine => {
    const line = rawLine.trim();
    if (!line) { closeList(); return; }

    const headingMatch = line.match(/^#{1,6}\s+(.*)$/);
    if (headingMatch) {
      closeList();
      html += `<div class="ai-md-heading">${aiInlineMarkdown(headingMatch[1])}</div>`;
      return;
    }

    const bulletMatch = line.match(/^[*-]\s+(.*)$/);
    if (bulletMatch) {
      if (!inList) { html += '<ul class="ai-md-list">'; inList = true; }
      html += `<li>${aiInlineMarkdown(bulletMatch[1])}</li>`;
      return;
    }

    closeList();
    html += `<p class="ai-md-p">${aiInlineMarkdown(line)}</p>`;
  });
  closeList();
  return html;
}

// ---- Lưu/khôi phục tiến trình (resume) ----

function aiPersistProgress() {
  if (!aiChat || !aiChat.stage) return;
  if (typeof saveAIChatProgress !== 'function') return;
  const { onComplete, ...serializable } = aiChat; // bỏ hàm callback, không serialize được
  saveAIChatProgress(aiChat.worldId, aiChat.level, serializable);
}

function aiDebouncedPersist() {
  if (aiPersistTimer) clearTimeout(aiPersistTimer);
  aiPersistTimer = setTimeout(aiPersistProgress, 400);
}

function aiClearProgress(worldId, level) {
  if (typeof clearAIChatProgress === 'function') clearAIChatProgress(worldId, level);
}

function aiNewChatState(worldId, level, isRetry, onComplete) {
  return {
    sessionId: null,
    worldId,
    level,
    isRetry,
    stage: null,
    showOnboarding: false,
    groupTitle: null,
    learningContent: null,
    questions: null,
    answers: {},
    correctionText: null,
    confidence: null,
    distinctionPrompt: null,
    applicationPrompt: null,
    distinctionDraft: '',
    applicationDraft: '',
    report: null,
    remediationRecap: null,
    practiceQuestions: null,
    practiceAnswers: {},
    remediationCorrectionText: null,
    practiceDistinctionPrompt: null,
    practiceApplicationPrompt: null,
    practiceDistinctionDraft: '',
    practiceApplicationDraft: '',
    remediationResult: null,
    onComplete: typeof onComplete === 'function' ? onComplete : null
  };
}

function openAIChat(worldId, level, onComplete, isRetry = false) {
  const saved = typeof loadAIChatProgress === 'function' ? loadAIChatProgress(worldId, level) : null;

  aiChat = saved
    ? { ...saved, onComplete: typeof onComplete === 'function' ? onComplete : null }
    : aiNewChatState(worldId, level, isRetry, onComplete);

  const overlay = document.createElement('div');
  overlay.className = 'ai-chat-overlay';
  overlay.id = 'ai-chat-overlay';
  overlay.innerHTML = `
    <div class="ai-chat-panel">
      <div class="ai-chat-header">
        <div>
          <div class="ai-chat-title">Trợ lý AI · Ôn từ vựng</div>
          <div class="ai-chat-subtitle">${aiEscapeHtml(worldId)} · Level ${level}</div>
        </div>
        <button type="button" class="ai-chat-close" id="ai-chat-close" title="Đóng">✕</button>
      </div>
      <div class="ai-chat-body" id="ai-chat-body"></div>
      <div class="ai-chat-footer" id="ai-chat-footer"></div>
    </div>
  `;
  document.body.appendChild(overlay);

  aiChatEls = {
    overlay,
    body: overlay.querySelector('#ai-chat-body'),
    footer: overlay.querySelector('#ai-chat-footer')
  };

  overlay.querySelector('#ai-chat-close').addEventListener('click', aiHandleUserDismiss);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) aiHandleUserDismiss();
  });

  // Guest chắc chắn bị backend chặn 401 (tính năng key) - báo ngay, khỏi tốn
  // 1 round-trip network vô ích.
  if (typeof isLoggedIn === 'function' && !isLoggedIn()) {
    aiRenderSessionAwareError({ status: 401 }, null);
    return;
  }

  if (saved && saved.stage) {
    aiResumeFromStage();
  } else {
    aiStartFlow();
  }
}

function closeAIChat() {
  if (aiChatEls && aiChatEls.overlay) {
    aiChatEls.overlay.remove();
  }
  aiChat = null;
  aiChatEls = null;
}

// Điểm thoát duy nhất khi người dùng chủ động rời modal (nút ✕, bấm ra ngoài,
// nút "Đóng"). Việc lưu kết quả đã xảy ra ở aiRenderFinalReport, nên đây chỉ
// lo dọn tiến trình resume + đóng modal.
function aiHandleUserDismiss() {
  if (!aiChat) { closeAIChat(); return; }
  const worldId = aiChat.worldId;
  const level = aiChat.level;
  const onComplete = aiChat.onComplete;

  // Chỉ xoá tiến trình resume khi PASS: lần bấm vào level sau đó là chơi lại
  // từ đầu. Nếu RETRY, giữ nguyên để bấm vào lại quay về đúng trang báo cáo.
  if (aiChat.stage === 'REPORT' && aiChat.report && aiChat.report.final_result === 'PASS') {
    aiClearProgress(worldId, level);
  }

  closeAIChat();
  if (typeof onComplete === 'function') onComplete();
}

function aiSetFooter(html) {
  aiChatEls.footer.innerHTML = html;
}

function aiSetBody(html) {
  aiChatEls.body.innerHTML = html;
}

function aiRenderLoading(message) {
  aiSetBody(`
    <div class="ai-loading">
      <div class="ai-spinner"></div>
      <span>${aiEscapeHtml(message)}</span>
    </div>
  `);
  aiSetFooter('');
}

function aiRenderError(message, onRetry) {
  aiSetBody(`<div class="ai-error">${aiEscapeHtml(message)}</div>`);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-retry-btn">Thử lại</button>`);
  const btn = document.getElementById('ai-retry-btn');
  if (btn) btn.addEventListener('click', onRetry);
}

// Một số lỗi không tự khỏi khi bấm "Thử lại" y hệt (session mất, chưa đăng
// nhập, hết key) - trong các trường hợp đó phải đưa hành động khác thay vì
// nút retry vô nghĩa.
function aiRenderSessionAwareError(e, onRetry) {
  if (e && e.status === 401) {
    aiSetBody(`<div class="ai-error">Bạn cần đăng nhập bằng Google để dùng tính năng AI. Đăng nhập lần đầu được tặng 15 key miễn phí.</div>`);
    aiSetFooter(`<a href="index.html?page=profile" class="ai-btn">Đăng nhập với Google</a>`);
    return;
  }
  if (e && e.status === 402) {
    aiSetBody(`<div class="ai-error">Bạn đã dùng hết key. Hiện chưa hỗ trợ nạp thêm key.</div>`);
    aiSetFooter(`<a href="index.html?page=profile" class="ai-btn ai-btn-secondary">Xem tài khoản</a>`);
    return;
  }
  const msg = e && e.message ? e.message : String(e);
  // 409: state lưu ở localStorage lệch với state thật trên server (VD: request
  // trước đã thành công trên server nhưng máy mất mạng trước khi lưu lại tiến
  // trình mới). Server không tự lùi trạng thái nên chỉ còn cách bắt đầu lại.
  if ((e && e.status === 409) || /không tồn tại hoặc đã hết hạn/i.test(msg)) {
    aiSetBody(`<div class="ai-error">Tiến trình lưu ở máy không khớp với trạng thái hiện tại trên server (có thể do mất mạng/thoát giữa chừng ở bước trước). Bạn cần bắt đầu lại từ đầu.</div>`);
    aiSetFooter(`<button type="button" class="ai-btn" id="ai-restart-session-btn">Bắt đầu lại từ đầu</button>`);
    document.getElementById('ai-restart-session-btn').addEventListener('click', () => {
      aiClearProgress(aiChat.worldId, aiChat.level);
      const fresh = aiNewChatState(aiChat.worldId, aiChat.level, aiChat.isRetry, aiChat.onComplete);
      aiChat = fresh;
      aiStartFlow();
    });
    return;
  }
  aiRenderError(msg, onRetry);
}

function aiResumeFromStage() {
  switch (aiChat.stage) {
    case 'LEARNING': aiRenderLearningContent(aiChat.groupTitle, aiChat.learningContent); break;
    case 'RECOGNITION': aiRenderMCQList(); break;
    case 'CORRECTION': aiRenderCorrection(aiChat.correctionText); break;
    case 'CONFIDENCE': aiRenderConfidenceQuestion(); break;
    case 'OPEN_ENDED': aiRenderOpenEnded(aiChat.distinctionPrompt, aiChat.applicationPrompt); break;
    case 'REPORT': aiRenderFinalReport(aiChat.report); break;
    case 'REMEDIATION_RECAP': aiRenderRemediationRecap(); break;
    case 'REMEDIATION_MCQ': aiRenderRemediationMCQList(); break;
    case 'REMEDIATION_CORRECTION': aiRenderRemediationCorrection(); break;
    case 'REMEDIATION_OPEN_ENDED': aiRenderRemediationOpenEnded(); break;
    case 'REMEDIATION_DONE': aiRenderRemediationDone(); break;
    default: aiStartFlow();
  }
}

// ---- Bước 1: mở phiên + dạy nội dung ----

async function aiStartFlow() {
  aiRenderLoading('Đang chuẩn bị bài học...');
  try {
    const history = typeof loadRecognitionHistory === 'function'
      ? loadRecognitionHistory(aiChat.worldId, aiChat.level)
      : [];
    const res = await gestureStartSession(aiChat.worldId, aiChat.level, aiChat.isRetry, history);
    aiChat.sessionId = res.session_id;
    aiChat.showOnboarding = res.show_onboarding;
    aiRenderLearningContent(res.group_title, res.learning_content);
  } catch (e) {
    aiRenderSessionAwareError(e, aiStartFlow);
  }
}

function aiRenderLearningContent(groupTitle, content) {
  aiChat.stage = 'LEARNING';
  aiChat.groupTitle = groupTitle;
  aiChat.learningContent = content;

  // Hướng dẫn đầy đủ chỉ hiện ở World 1 - Level 1 lần đầu; các lần/level khác
  // chỉ cần lời chào ngắn.
  const onboardingBlock = aiChat.showOnboarding
    ? `<div class="ai-msg-system ai-msg-onboarding">
        👋 Chào bạn! Đây là trợ lý AI giúp bạn học và tự kiểm tra từ vựng.
        Cách dùng: đọc phần giải thích bên dưới, sau đó làm 20 câu trắc nghiệm,
        xem giải thích các câu sai, tự chấm mức độ tự tin, rồi trả lời 2 câu hỏi
        mở để AI đánh giá khả năng vận dụng thực tế của bạn. Cuối cùng bạn sẽ
        nhận được kết quả PASS hoặc cần ôn tập thêm.
      </div>`
    : `<div class="ai-msg-system ai-msg-onboarding">${aiWelcomeMessage(aiChat.worldId, aiChat.level)}</div>`;

  aiSetBody(`
    ${onboardingBlock}
    <div class="ai-msg-system">Chào bạn! Hôm nay chúng ta học nhóm từ: <strong>${aiEscapeHtml(groupTitle)}</strong></div>
    <div class="ai-msg">${aiMarkdownToHtml(content)}</div>
    <div class="ai-start-notice">
      <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="10" cy="10" r="7.5"/>
        <line x1="10" y1="6.5" x2="10" y2="10.5"/>
        <circle cx="10" cy="13.3" r="0.15" fill="currentColor" stroke-width="1.2"/>
      </svg>
      <span>Để kết quả được tối ưu, trong quá trình làm bài không dùng công cụ hoặc thiết bị hỗ trợ.</span>
    </div>
  `);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-begin-recognition-btn">Bắt đầu làm bài (20 câu)</button>`);
  document.getElementById('ai-begin-recognition-btn').addEventListener('click', aiBeginRecognition);
  aiPersistProgress();
}

// ---- Bước 2: sinh 20 MCQ ----

async function aiBeginRecognition() {
  aiRenderLoading('Đang chuẩn bị 20 câu hỏi...');
  try {
    const history = typeof loadRecognitionHistory === 'function'
      ? loadRecognitionHistory(aiChat.worldId, aiChat.level)
      : [];
    const res = await gestureBeginRecognition(aiChat.sessionId, history);
    aiChat.questions = res.questions;
    aiChat.answers = {};
    if (typeof appendRecognitionHistory === 'function') {
      appendRecognitionHistory(aiChat.worldId, aiChat.level, res.questions.map(q => q.question));
    }
    if (typeof setHeaderKeyDisplay === 'function') {
      setHeaderKeyDisplay(res.keys_remaining);
    }
    aiRenderMCQList();
  } catch (e) {
    aiRenderSessionAwareError(e, aiBeginRecognition);
  }
}

// "___" trong câu hỏi hiển thị thành ô trống gạch chân, dễ nhìn hơn dấu gạch thô.
function aiQuestionHtml(text) {
  return aiEscapeHtml(text).replace(/_{3,}/g, '<span class="ai-q-blank">&nbsp;</span>');
}

function aiRenderMCQList() {
  aiChat.stage = 'RECOGNITION';
  const optionLabels = ['A', 'B', 'C', 'D'];
  const total = aiChat.questions.length;

  const itemsHtml = aiChat.questions.map((q, qIndex) => `
    <section class="ai-q" id="ai-q-card-${q.id}">
      <div class="ai-q-head"><span class="ai-q-num">Câu ${qIndex + 1}</span></div>
      <p class="ai-q-text">${aiQuestionHtml(q.question)}</p>
      <div class="ai-q-options">
        ${q.options.map((opt, i) => `
          <label class="ai-q-option">
            <input type="radio" name="ai-q-${q.id}" value="${i}" ${aiChat.answers[String(q.id)] === i ? 'checked' : ''}>
            <span class="ai-q-radio"></span>
            <span class="ai-q-option-text"><b>${optionLabels[i]}.</b> ${aiEscapeHtml(opt)}</span>
          </label>
        `).join('')}
      </div>
    </section>
  `).join('');

  const navHtml = aiChat.questions.map((q, qIndex) =>
    `<button type="button" class="ai-quiz-nav-btn" data-qid="${q.id}">${qIndex + 1}</button>`
  ).join('');

  aiSetBody(`
    <div class="ai-quiz">
      <div class="ai-quiz-main">${itemsHtml}</div>
      <aside class="ai-quiz-nav">
        <div class="ai-quiz-nav-head">
          <span>Đã làm</span><strong id="ai-mcq-progress">0/${total}</strong>
        </div>
        <div class="ai-quiz-nav-bar"><div class="ai-quiz-nav-bar-fill" id="ai-mcq-bar"></div></div>
        <div class="ai-quiz-nav-grid">${navHtml}</div>
      </aside>
    </div>
  `);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-submit-mcq-btn" disabled>Nộp bài</button>`);

  aiChatEls.body.querySelectorAll('input[type="radio"]').forEach(input => {
    input.addEventListener('change', (e) => {
      const qid = e.target.name.replace('ai-q-', '');
      aiChat.answers[qid] = parseInt(e.target.value, 10);
      aiUpdateMCQProgress();
      aiPersistProgress();
    });
  });

  aiChatEls.body.querySelectorAll('.ai-quiz-nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = document.getElementById(`ai-q-card-${btn.getAttribute('data-qid')}`);
      if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  document.getElementById('ai-submit-mcq-btn').addEventListener('click', aiSubmitRecognition);
  aiUpdateMCQProgress();
  aiPersistProgress();
}

function aiUpdateMCQProgress() {
  const total = aiChat.questions.length;
  const answered = Object.keys(aiChat.answers).length;
  const progressEl = document.getElementById('ai-mcq-progress');
  if (progressEl) progressEl.textContent = `${answered}/${total}`;
  const barEl = document.getElementById('ai-mcq-bar');
  if (barEl) barEl.style.width = `${(answered / total) * 100}%`;
  aiChatEls.body.querySelectorAll('.ai-quiz-nav-btn').forEach(btn => {
    btn.classList.toggle('answered', aiChat.answers[btn.getAttribute('data-qid')] !== undefined);
  });
  const submitBtn = document.getElementById('ai-submit-mcq-btn');
  if (submitBtn) submitBtn.disabled = answered < total;
}

// ---- Bước 3: chấm + correction ----

async function aiSubmitRecognition() {
  aiRenderLoading('Đang chấm bài và soạn giải thích...');
  try {
    const dHistory = typeof loadDistinctionHistory === 'function'
      ? loadDistinctionHistory(aiChat.worldId, aiChat.level) : [];
    const aHistory = typeof loadApplicationHistory === 'function'
      ? loadApplicationHistory(aiChat.worldId, aiChat.level) : [];
    const res = await gestureSubmitRecognition(aiChat.sessionId, aiChat.answers, dHistory, aHistory);
    // Giữ lại để saveThisAttemptResult đưa vào kết quả cho trang Analysis.
    aiChat.wrongWords = res.wrong_words || [];
    aiChat.explanations = res.explanations || {};
    aiChat.quality = res.quality || {};
    aiRenderCorrection(res.correction_text);
  } catch (e) {
    aiRenderSessionAwareError(e, aiSubmitRecognition);
  }
}

// Trang kết quả phần trắc nghiệm: lời giải CHỈ hiện ở đây (sau khi nộp). Câu
// đúng chỉ báo ngắn gọn; câu sai hiện đáp án đúng, còn phần giải thích AI viết
// 1 khối chung cho mọi câu sai (backend không tách theo từng câu).
function aiRenderCorrection(correctionText) {
  aiChat.stage = 'CORRECTION';
  aiChat.correctionText = correctionText;

  const labels = ['A', 'B', 'C', 'D'];
  const wrongByQuestion = new Map((aiChat.wrongWords || []).map(w => [w.question, w]));
  const questions = aiChat.questions || [];
  let wrongCount = 0;

  const reviewHtml = questions.map((q, qIndex) => {
    const selected = aiChat.answers[String(q.id)];
    const wrong = wrongByQuestion.get(q.question);
    const correctIndex = wrong ? q.options.indexOf(wrong.correct) : selected;
    const isCorrect = !wrong;
    if (!isCorrect) wrongCount += 1;
    const explanation = (aiChat.explanations || {})[String(q.id)];
    const quality = (aiChat.quality || {})[String(q.id)];

    const optionsHtml = q.options.map((opt, i) => {
      let cls = '';
      let tag = '';
      if (i === correctIndex) { cls = 'is-correct'; tag = '<span class="ai-q-tag ok">Đáp án đúng</span>'; }
      else if (i === selected) { cls = 'is-wrong'; tag = '<span class="ai-q-tag bad">Bạn chọn</span>'; }
      return `<div class="ai-q-option ai-q-option--review ${cls}">
        <span class="ai-q-radio"></span>
        <span class="ai-q-option-text"><b>${labels[i]}.</b> ${aiEscapeHtml(opt)}</span>${tag}
      </div>`;
    }).join('');

    return `
      <section class="ai-q ${isCorrect ? 'ai-q--ok' : 'ai-q--bad'}">
        <div class="ai-q-head">
          <span class="ai-q-num">Câu ${qIndex + 1}</span>
          <span class="ai-q-status ${isCorrect ? 'ok' : 'bad'}">${isCorrect ? 'Đúng' : 'Sai'}</span>
          ${aiQualityBadgeHtml(quality)}
        </div>
        <p class="ai-q-text">${aiQuestionHtml(q.question)}</p>
        <div class="ai-q-options">${optionsHtml}</div>
        ${isCorrect
          ? '<div class="ai-q-feedback ok">Bạn đã trả lời chính xác!</div>'
            : (explanation ? `<div class="ai-q-feedback bad">${aiMarkdownToHtml(explanation)}</div>` : '')}
        <button type="button" class="ai-report-btn" data-report="recognition" data-qid="${q.id}">Báo cáo đáp án</button>
        <div class="ai-report-slot"></div>
      </section>
    `;
  }).join('');

  const correctCount = questions.length - wrongCount;
  const hasPerQuestion = aiChat.explanations && Object.keys(aiChat.explanations).length > 0;
  const explainHtml = (wrongCount && !hasPerQuestion)
    ? `<section class="ai-q ai-q-explain">
         <div class="ai-q-head"><span class="ai-q-num">Giải thích các câu sai</span></div>
         <div class="ai-msg">${aiMarkdownToHtml(correctionText)}</div>
       </section>`
    : '';

  aiSetBody(`
    <div class="ai-review-summary">
      Bạn trả lời đúng <strong>${correctCount}/${questions.length}</strong> câu.
    </div>
    <div class="ai-review-list">${reviewHtml}</div>
    ${explainHtml}
  `);
  aiBindReportButtons();
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-to-confidence-btn">Tiếp tục</button>`);
  document.getElementById('ai-to-confidence-btn').addEventListener('click', aiRenderConfidenceQuestion);
  aiPersistProgress();
}

// ---- Chỉ số tin cậy + báo cáo của người dùng ----

function aiQualityBadgeHtml(q) {
  if (!q) return '';
  const parts = [`Đáp án tin cậy ${q.answer_conf}%`];
  if (q.question_ok != null) parts.push(`Câu hỏi đạt ${q.question_ok}%`);
  return `<span class="ai-q-quality ${q.needs_check ? 'warn' : 'good'}" title="Do AI kiểm tra độc lập tính toán">
    ${q.needs_check ? 'Nên kiểm tra · ' : ''}${parts.join(' · ')}</span>`;
}

function aiSpreadHtml(spread, kind) {
  const v = spread && spread[kind];
  if (v == null) return '';
  const warn = v >= spread.flag_threshold;
  return `<div class="ai-spread ${warn ? 'warn' : 'good'}">
    Chênh lệch giữa 2 lần AI chấm: <strong>${v.toFixed(1)} điểm</strong>${warn ? ' · nên xem lại kỹ' : ''}</div>`;
}

function aiBindReportButtons() {
  aiChatEls.body.querySelectorAll('.ai-report-btn').forEach(btn => {
    btn.addEventListener('click', () => aiOpenReportForm(btn));
  });
}

function aiOpenReportForm(btn) {
  const slot = btn.nextElementSibling;
  if (slot.innerHTML) { slot.innerHTML = ''; return; }
  const kind = btn.dataset.report;
  let pickHtml = '';
  if (kind === 'recognition') {
    const q = (aiChat.questions || []).find(x => String(x.id) === btn.dataset.qid);
    const labels = ['A', 'B', 'C', 'D'];
    pickHtml = `<div class="ai-report-label">Theo bạn đáp án đúng là:</div>` + q.options.map((o, i) =>
      `<label class="ai-report-opt"><input type="radio" name="rp-${q.id}" value="${i}"> <b>${labels[i]}.</b> ${aiEscapeHtml(o)}</label>`
    ).join('');
  } else {
    pickHtml = `<div class="ai-report-label">Theo bạn điểm/nhận xét nên thế nào? (không bắt buộc)</div>
      <input type="text" class="ai-report-note" maxlength="300" placeholder="Ví dụ: nên được 8/10 vì...">`;
  }
  slot.innerHTML = `<div class="ai-report-form">${pickHtml}
    <div class="ai-report-label">Giải thích của bạn (dựa trên nội dung bài học):</div>
    <textarea class="ai-report-text" rows="3" maxlength="1200"></textarea>
    <div class="ai-report-actions"><button type="button" class="ai-btn ai-report-send">Gửi báo cáo</button>
    <span class="ai-report-status"></span></div></div>`;
  slot.querySelector('.ai-report-send').addEventListener('click', () => aiSendReport(btn, slot));
}

async function aiSendReport(btn, slot) {
  const kind = btn.dataset.report;
  const status = slot.querySelector('.ai-report-status');
  const explanation = slot.querySelector('.ai-report-text').value.trim();
  const payload = { session_id: aiChat.sessionId, kind, explanation };
  if (kind === 'recognition') {
    const picked = slot.querySelector('input[type=radio]:checked');
    if (!picked) { status.textContent = 'Hãy chọn đáp án bạn cho là đúng.'; return; }
    payload.question_id = Number(btn.dataset.qid);
    payload.suggested_index = Number(picked.value);
  } else {
    payload.suggested_note = slot.querySelector('.ai-report-note').value.trim();
  }
  if (explanation.length < 10) { status.textContent = 'Giải thích cần ít nhất 10 ký tự.'; return; }
  status.textContent = 'AI đang thẩm định...';
  slot.querySelector('.ai-report-send').disabled = true;
  try {
    const res = await gestureSubmitReport(payload);
    slot.innerHTML = `<div class="ai-report-result ${res.accepted ? 'good' : 'warn'}">${res.accepted
      ? 'Cảm ơn bạn! Báo cáo hợp lý và đã được ghi nhận để AI học dần.'
      : 'Báo cáo chưa được chấp nhận: ' + aiEscapeHtml(res.reason || 'không đủ căn cứ trong bài học.')}</div>`;
    btn.disabled = true;
  } catch (e) {
    status.textContent = e.message;
    slot.querySelector('.ai-report-send').disabled = false;
  }
}

// ---- Bước 4: tự đánh giá tự tin ----

function aiRenderConfidenceQuestion() {
  aiChat.stage = 'CONFIDENCE';
  if (aiChat.confidence == null) aiChat.confidence = 5;

  aiSetBody(`
    <div class="ai-msg">${aiEscapeHtml(AI_CONFIDENCE_QUESTION)}</div>
    <div class="ai-confidence-block">
      <div class="ai-confidence-value" id="ai-confidence-value">${aiChat.confidence.toFixed(1)}</div>
      <input type="range" min="0" max="10" step="0.5" value="${aiChat.confidence}" class="ai-confidence-slider" id="ai-confidence-slider">
    </div>
  `);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-submit-confidence-btn">Xác nhận</button>`);

  const slider = document.getElementById('ai-confidence-slider');
  const valueEl = document.getElementById('ai-confidence-value');
  slider.addEventListener('input', () => {
    aiChat.confidence = parseFloat(slider.value);
    valueEl.textContent = aiChat.confidence.toFixed(1);
    aiDebouncedPersist();
  });

  document.getElementById('ai-submit-confidence-btn').addEventListener('click', aiSubmitConfidence);
  aiPersistProgress();
}

async function aiSubmitConfidence() {
  aiRenderLoading('Đang tạo câu hỏi vận dụng...');
  try {
    const dHistory = typeof loadDistinctionHistory === 'function'
      ? loadDistinctionHistory(aiChat.worldId, aiChat.level) : [];
    const aHistory = typeof loadApplicationHistory === 'function'
      ? loadApplicationHistory(aiChat.worldId, aiChat.level) : [];
    const res = await gestureSubmitConfidence(aiChat.sessionId, aiChat.confidence, dHistory, aHistory);
    if (typeof appendDistinctionHistory === 'function') {
      appendDistinctionHistory(aiChat.worldId, aiChat.level, res.distinction_prompt);
    }
    if (typeof appendApplicationHistory === 'function') {
      appendApplicationHistory(aiChat.worldId, aiChat.level, res.application_prompt);
    }
    aiRenderOpenEnded(res.distinction_prompt, res.application_prompt);
  } catch (e) {
    aiRenderSessionAwareError(e, aiSubmitConfidence);
  }
}

// ---- Bước 5: 2 câu hỏi mở ----

function aiRenderOpenEnded(distinctionPrompt, applicationPrompt) {
  aiChat.stage = 'OPEN_ENDED';
  aiChat.distinctionPrompt = distinctionPrompt;
  aiChat.applicationPrompt = applicationPrompt;

  aiSetBody(`
    <div class="ai-open-ended-block">
      <div class="ai-open-ended-label">PHÂN BIỆT</div>
      <div class="ai-msg">${aiMarkdownToHtml(distinctionPrompt)}</div>
      <textarea class="ai-textarea" id="ai-distinction-answer" placeholder="Trả lời của bạn...">${aiEscapeHtml(aiChat.distinctionDraft || '')}</textarea>
    </div>
    <div class="ai-open-ended-block">
      <div class="ai-open-ended-label">VẬN DỤNG</div>
      <div class="ai-msg">${aiMarkdownToHtml(applicationPrompt)}</div>
      <textarea class="ai-textarea" id="ai-application-answer" placeholder="Trả lời của bạn...">${aiEscapeHtml(aiChat.applicationDraft || '')}</textarea>
    </div>
  `);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-submit-open-ended-btn" disabled>Nộp bài</button>`);

  const distEl = document.getElementById('ai-distinction-answer');
  const appEl = document.getElementById('ai-application-answer');
  const submitBtn = document.getElementById('ai-submit-open-ended-btn');

  const checkReady = () => {
    submitBtn.disabled = !distEl.value.trim() || !appEl.value.trim();
  };
  distEl.addEventListener('input', () => {
    aiChat.distinctionDraft = distEl.value;
    checkReady();
    aiDebouncedPersist();
  });
  appEl.addEventListener('input', () => {
    aiChat.applicationDraft = appEl.value;
    checkReady();
    aiDebouncedPersist();
  });
  checkReady();

  submitBtn.addEventListener('click', () => aiSubmitOpenEnded(distEl.value.trim(), appEl.value.trim()));
  aiPersistProgress();
}

async function aiSubmitOpenEnded(distinctionAnswer, applicationAnswer) {
  aiRenderLoading('AI đang chấm câu trả lời...');
  try {
    const report = await gestureSubmitOpenEnded(aiChat.sessionId, distinctionAnswer, applicationAnswer);
    aiChat.report = report;
    aiRenderFinalReport(report);
  } catch (e) {
    aiRenderSessionAwareError(e, () => aiSubmitOpenEnded(distinctionAnswer, applicationAnswer));
  }
}

// ---- Bước 6: báo cáo cuối ----

function aiRubricTableHtml(rows) {
  return `
    <table class="ai-rubric-table">
      <tbody>
        ${(rows || []).map(r => `
          <tr>
            <td>${aiEscapeHtml(r.label)}</td>
            <td class="ai-rubric-score">${r.score.toFixed(1)} / ${r.max}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

// Theo tiêu chí đã thống nhất: DETECTED (ảo tưởng năng lực) và UNDERCONFIDENT
// (tự tin thấp hơn thực lực) đều là lệch chuẩn -> chấm tròn ĐỎ. Chỉ CALIBRATED
// (tự đánh giá đúng) mới chấm tròn XANH.
function aiIllusionMeta(status) {
  const map = {
    DETECTED: { label: 'Ảo tưởng năng lực (Illusion of Competence)', dot: 'red' },
    UNDERCONFIDENT: { label: 'Tự tin thấp hơn thực lực (Underconfidence)', dot: 'red' },
    CALIBRATED: { label: 'Tự đánh giá chính xác (Good)', dot: 'green' }
  };
  return map[status] || { label: status, dot: 'red' };
}

// Gọi ngay khi báo cáo hiện ra (không đợi người dùng bấm gì), để không phụ
// thuộc vào việc họ thoát bằng cách nào sau đó.
function saveThisAttemptResult(report) {
  const isPass = report.final_result === 'PASS';
  if (isPass && typeof advanceWorldCompletedLevels === 'function') {
    advanceWorldCompletedLevels(aiChat.worldId, aiChat.level);
  }
  if (typeof setLevelResults === 'function') {
    // Breakdown đầy đủ - trang Analysis cần từng phần riêng, không chỉ tổng.
    setLevelResults(aiChat.worldId, aiChat.level, {
      accuracy: report.accuracy,
      illusion_status: report.illusion_status,
      recognition: report.recognition,
      distinction: report.distinction_score,
      application: report.application_score,
      overall: report.overall,
      confidence: report.confidence,
      gap: report.gap,
      group_title: aiChat.groupTitle,
      wrong_words: aiChat.wrongWords || [],
      distinction_feedback: report.distinction_feedback,
      application_feedback: report.application_feedback
    });
  }
  if (isPass) {
    aiCaptureVocabLearned(aiChat.worldId, aiChat.level);
  }
}

// Ghi nhóm từ đã học vĩnh viễn (không bị "Chơi lại" xoá). Không chặn luồng
// chính nếu lỗi, nhưng thử lại vài lần vì bỏ lỡ lúc PASS này thì phải đợi
// lần pass tiếp theo mới có cơ hội ghi lại.
async function aiCaptureVocabLearned(worldId, level, attempt = 1) {
  if (typeof hasVocabLearned === 'function' && hasVocabLearned(worldId, level)) return;
  if (typeof gestureGetVocab !== 'function' || typeof addVocabLearned !== 'function') return;
  try {
    const data = await gestureGetVocab(worldId, level);
    addVocabLearned(worldId, level, data.group_title, data.words);
  } catch (e) {
    if (attempt < 3) {
      setTimeout(() => aiCaptureVocabLearned(worldId, level, attempt + 1), 2000);
    }
  }
}

function aiRenderFinalReport(report) {
  aiChat.stage = 'REPORT';
  aiChat.report = report;

  // Lưu ngay để badge dưới level luôn cập nhật dù người dùng thoát kiểu gì
  // sau đó (kể cả đóng tab).
  saveThisAttemptResult(report);

  const isPass = report.final_result === 'PASS';
  const understandingLabel = {
    WELL_UNDERSTOOD: 'Hiểu tốt',
    PARTIALLY_UNDERSTOOD: 'Hiểu một phần',
    LIMITED_UNDERSTANDING: 'Hiểu hạn chế',
    NOT_YET_UNDERSTOOD: 'Chưa hiểu rõ'
  }[report.understanding_level] || report.understanding_level;

  const illusionMeta = aiIllusionMeta(report.illusion_status);

  const retryNoteHtml = report.retry_note
    ? `<div class="ai-msg-system">${aiEscapeHtml(report.retry_note)}</div>`
    : '';

  aiSetBody(`
    <div class="ai-report">
      <span class="ai-result-badge ${isPass ? 'pass' : 'retry'}">${isPass ? 'PASS' : 'CẦN ÔN TẬP THÊM'}</span>

      <div class="ai-score-grid">
        <div class="ai-score-item"><div class="ai-score-value">${report.recognition.toFixed(1)}</div><div class="ai-score-label">RECOGNITION</div></div>
        <div class="ai-score-item"><div class="ai-score-value">${report.distinction_score.toFixed(1)}</div><div class="ai-score-label">DISTINCTION</div></div>
        <div class="ai-score-item"><div class="ai-score-value">${report.application_score.toFixed(1)}</div><div class="ai-score-label">APPLICATION</div></div>
        <div class="ai-score-item"><div class="ai-score-value">${report.overall.toFixed(1)}</div><div class="ai-score-label">OVERALL</div></div>
        <div class="ai-score-item"><div class="ai-score-value">${report.confidence.toFixed(1)}</div><div class="ai-score-label">TỰ TIN</div></div>
        <div class="ai-score-item">
          <div class="ai-score-value">${report.gap > 0 ? '+' : ''}${report.gap.toFixed(1)}</div>
          <div class="ai-score-label">
            <span class="ai-status-dot ai-status-dot--${illusionMeta.dot}"></span>GAP
          </div>
        </div>
      </div>

      <div class="ai-msg-system">
        Mức độ hiểu: <strong>${understandingLabel}</strong><br>
        <span class="ai-status-dot ai-status-dot--${illusionMeta.dot}"></span>${illusionMeta.label}
      </div>

      <div class="ai-feedback-block">
        <div class="ai-open-ended-label">Rubric Phân biệt (${report.distinction_score.toFixed(1)}/10)</div>
        ${aiSpreadHtml(report.grading_spread, 'distinction')}
        ${aiRubricTableHtml(report.distinction_rubric)}
        ${aiMarkdownToHtml(report.distinction_feedback)}
        <button type="button" class="ai-report-btn" data-report="distinction">Báo cáo điểm / nhận xét</button>
        <div class="ai-report-slot"></div>
      </div>
      <div class="ai-feedback-block">
        <div class="ai-open-ended-label">Rubric Vận dụng (${report.application_score.toFixed(1)}/10)</div>
        ${aiSpreadHtml(report.grading_spread, 'application')}
        ${aiRubricTableHtml(report.application_rubric)}
        ${aiMarkdownToHtml(report.application_feedback)}
        <button type="button" class="ai-report-btn" data-report="application">Báo cáo điểm / nhận xét</button>
        <div class="ai-report-slot"></div>
      </div>

      ${retryNoteHtml}
    </div>
  `);

  aiBindReportButtons();

  const footerHtml = isPass
    ? `<button type="button" class="ai-btn" id="ai-close-report-btn">Đóng</button>`
    : `
      <button type="button" class="ai-btn ai-btn-secondary" id="ai-close-report-btn">Đóng</button>
      <button type="button" class="ai-btn" id="ai-remediate-btn">Ôn tập &amp; Kiểm tra lại</button>
    `;
  aiSetFooter(footerHtml);

  document.getElementById('ai-close-report-btn').addEventListener('click', aiHandleUserDismiss);

  const remediateBtn = document.getElementById('ai-remediate-btn');
  if (remediateBtn) {
    remediateBtn.addEventListener('click', aiBeginRemediation);
  }

  aiPersistProgress();
}

// ---- Luồng ôn tập trọng tâm (remediation) khi RETRY ----
// Phân tích lỗi sai của cả 3 phần để tạo bài luyện tập nhỏ trước khi retest.

async function aiBeginRemediation() {
  aiRenderLoading('Đang phân tích lỗi sai và soạn bài ôn tập trọng tâm...');
  try {
    const rHistory = typeof loadRecognitionHistory === 'function'
      ? loadRecognitionHistory(aiChat.worldId, aiChat.level) : [];
    const dHistory = typeof loadDistinctionHistory === 'function'
      ? loadDistinctionHistory(aiChat.worldId, aiChat.level) : [];
    const aHistory = typeof loadApplicationHistory === 'function'
      ? loadApplicationHistory(aiChat.worldId, aiChat.level) : [];
    const res = await gestureBeginRemediation(aiChat.sessionId, rHistory, dHistory, aHistory);
    aiChat.remediationRecap = res.recap;
    aiChat.practiceQuestions = res.practice_questions;
    aiChat.practiceAnswers = {};
    if (typeof appendRecognitionHistory === 'function') {
      appendRecognitionHistory(aiChat.worldId, aiChat.level, res.practice_questions.map(q => q.question));
    }
    if (typeof setHeaderKeyDisplay === 'function') {
      setHeaderKeyDisplay(res.keys_remaining);
    }
    aiRenderRemediationRecap();
  } catch (e) {
    aiRenderSessionAwareError(e, aiBeginRemediation);
  }
}

function aiRenderRemediationRecap() {
  aiChat.stage = 'REMEDIATION_RECAP';
  aiSetBody(`
    <div class="ai-msg-system">Ôn tập trọng tâm dựa trên lỗi sai của bạn ở lượt vừa rồi:</div>
    <div class="ai-msg">${aiMarkdownToHtml(aiChat.remediationRecap || '')}</div>
  `);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-begin-remediation-mcq-btn">Bắt đầu luyện tập (${aiChat.practiceQuestions.length} câu)</button>`);
  document.getElementById('ai-begin-remediation-mcq-btn').addEventListener('click', aiRenderRemediationMCQList);
  aiPersistProgress();
}

function aiRenderRemediationMCQList() {
  aiChat.stage = 'REMEDIATION_MCQ';
  const optionLabels = ['A', 'B', 'C', 'D'];
  const itemsHtml = aiChat.practiceQuestions.map((q, qIndex) => `
    <div class="ai-mcq-item">
      <div class="ai-mcq-question"><strong>Câu ${qIndex + 1}.</strong>${aiEscapeHtml(q.question)}</div>
      <div class="ai-mcq-options">
        ${q.options.map((opt, i) => `
          <label class="ai-mcq-option">
            <input type="radio" name="ai-pq-${q.id}" value="${i}" ${aiChat.practiceAnswers[String(q.id)] === i ? 'checked' : ''}>
            <span>${optionLabels[i]}. ${aiEscapeHtml(opt)}</span>
          </label>
        `).join('')}
      </div>
    </div>
  `).join('');

  aiSetBody(`
    <div class="ai-mcq-progress" id="ai-mcq-progress">Đã trả lời: ${Object.keys(aiChat.practiceAnswers).length} / ${aiChat.practiceQuestions.length}</div>
    <div class="ai-mcq-list">${itemsHtml}</div>
  `);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-submit-remediation-mcq-btn" ${Object.keys(aiChat.practiceAnswers).length < aiChat.practiceQuestions.length ? 'disabled' : ''}>Nộp bài luyện tập</button>`);

  aiChatEls.body.querySelectorAll('input[type="radio"]').forEach(input => {
    input.addEventListener('change', (e) => {
      const qid = e.target.name.replace('ai-pq-', '');
      aiChat.practiceAnswers[qid] = parseInt(e.target.value, 10);
      const total = aiChat.practiceQuestions.length;
      const answered = Object.keys(aiChat.practiceAnswers).length;
      const progressEl = document.getElementById('ai-mcq-progress');
      if (progressEl) progressEl.textContent = `Đã trả lời: ${answered} / ${total}`;
      const submitBtn = document.getElementById('ai-submit-remediation-mcq-btn');
      if (submitBtn) submitBtn.disabled = answered < total;
      aiPersistProgress();
    });
  });

  document.getElementById('ai-submit-remediation-mcq-btn').addEventListener('click', aiSubmitRemediationMCQ);
  aiPersistProgress();
}

async function aiSubmitRemediationMCQ() {
  aiRenderLoading('Đang chấm bài luyện tập...');
  try {
    const res = await gestureSubmitRemediationMCQ(aiChat.sessionId, aiChat.practiceAnswers);
    aiChat.remediationCorrectionText = res.correction_text;
    aiChat.practiceDistinctionPrompt = res.distinction_prompt;
    aiChat.practiceApplicationPrompt = res.application_prompt;
    if (typeof appendDistinctionHistory === 'function') {
      appendDistinctionHistory(aiChat.worldId, aiChat.level, res.distinction_prompt);
    }
    if (typeof appendApplicationHistory === 'function') {
      appendApplicationHistory(aiChat.worldId, aiChat.level, res.application_prompt);
    }
    aiRenderRemediationCorrection();
  } catch (e) {
    aiRenderSessionAwareError(e, aiSubmitRemediationMCQ);
  }
}

function aiRenderRemediationCorrection() {
  aiChat.stage = 'REMEDIATION_CORRECTION';
  aiSetBody(`<div class="ai-msg">${aiMarkdownToHtml(aiChat.remediationCorrectionText || '')}</div>`);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-to-remediation-open-ended-btn">Tiếp tục</button>`);
  document.getElementById('ai-to-remediation-open-ended-btn').addEventListener('click', aiRenderRemediationOpenEnded);
  aiPersistProgress();
}

function aiRenderRemediationOpenEnded() {
  aiChat.stage = 'REMEDIATION_OPEN_ENDED';
  aiSetBody(`
    <div class="ai-open-ended-block">
      <div class="ai-open-ended-label">PHÂN BIỆT (luyện tập)</div>
      <div class="ai-msg">${aiMarkdownToHtml(aiChat.practiceDistinctionPrompt || '')}</div>
      <textarea class="ai-textarea" id="ai-p-distinction-answer" placeholder="Trả lời của bạn...">${aiEscapeHtml(aiChat.practiceDistinctionDraft || '')}</textarea>
    </div>
    <div class="ai-open-ended-block">
      <div class="ai-open-ended-label">VẬN DỤNG (luyện tập)</div>
      <div class="ai-msg">${aiMarkdownToHtml(aiChat.practiceApplicationPrompt || '')}</div>
      <textarea class="ai-textarea" id="ai-p-application-answer" placeholder="Trả lời của bạn...">${aiEscapeHtml(aiChat.practiceApplicationDraft || '')}</textarea>
    </div>
  `);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-submit-remediation-open-ended-btn" disabled>Nộp bài luyện tập</button>`);

  const distEl = document.getElementById('ai-p-distinction-answer');
  const appEl = document.getElementById('ai-p-application-answer');
  const submitBtn = document.getElementById('ai-submit-remediation-open-ended-btn');

  const checkReady = () => {
    submitBtn.disabled = !distEl.value.trim() || !appEl.value.trim();
  };
  distEl.addEventListener('input', () => {
    aiChat.practiceDistinctionDraft = distEl.value;
    checkReady();
    aiDebouncedPersist();
  });
  appEl.addEventListener('input', () => {
    aiChat.practiceApplicationDraft = appEl.value;
    checkReady();
    aiDebouncedPersist();
  });
  checkReady();

  submitBtn.addEventListener('click', () => aiSubmitRemediationOpenEnded(distEl.value.trim(), appEl.value.trim()));
  aiPersistProgress();
}

async function aiSubmitRemediationOpenEnded(distinctionAnswer, applicationAnswer) {
  aiRenderLoading('AI đang chấm bài luyện tập...');
  try {
    const res = await gestureSubmitRemediationOpenEnded(aiChat.sessionId, distinctionAnswer, applicationAnswer);
    aiChat.remediationResult = res;
    aiRenderRemediationDone();
  } catch (e) {
    aiRenderSessionAwareError(e, () => aiSubmitRemediationOpenEnded(distinctionAnswer, applicationAnswer));
  }
}

function aiRenderRemediationDone() {
  aiChat.stage = 'REMEDIATION_DONE';
  const r = aiChat.remediationResult || {};
  aiSetBody(`
    <div class="ai-msg-system">Đã ôn tập xong! Nhận xét dưới đây chỉ mang tính tham khảo, KHÔNG tính vào kết quả chính thức:</div>
    <div class="ai-feedback-block">
      <div class="ai-open-ended-label">Phân biệt (luyện tập) - ${(r.distinction_score || 0).toFixed(1)}/10</div>
      ${aiRubricTableHtml(r.distinction_rubric)}
      ${aiMarkdownToHtml(r.distinction_feedback || '')}
    </div>
    <div class="ai-feedback-block">
      <div class="ai-open-ended-label">Vận dụng (luyện tập) - ${(r.application_score || 0).toFixed(1)}/10</div>
      ${aiRubricTableHtml(r.application_rubric)}
      ${aiMarkdownToHtml(r.application_feedback || '')}
    </div>
    <div class="ai-msg-system">Sẵn sàng làm lại bài kiểm tra đầy đủ (20 câu trắc nghiệm + 2 câu Phân biệt/Vận dụng) chưa?</div>
  `);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-retest-btn">Kiểm tra lại</button>`);
  document.getElementById('ai-retest-btn').addEventListener('click', () => {
    // Chạy lại luồng chính đầy đủ; nếu vẫn RETRY, chu kỳ ôn tập lặp lại.
    aiChat.questions = null;
    aiChat.answers = {};
    aiBeginRecognition();
  });
  aiPersistProgress();
}
