// ==== AI CHATBOT UI ====
// Điều khiển khung chat nổi lên khi bấm 1 level có bật AI. Chỉ lo phần hiển
// thị + thu thập input người dùng; mọi gọi mạng đi qua gesture.js, mọi tính
// điểm/PASS-RETRY do backend quyết định (xem server/main.py).
//
// aiChat.stage đánh dấu đúng giai đoạn UI hiện tại (LEARNING, RECOGNITION,
// CORRECTION, CONFIDENCE, OPEN_ENDED, REPORT, REMEDIATION_RECAP,
// REMEDIATION_MCQ, REMEDIATION_CORRECTION, REMEDIATION_OPEN_ENDED,
// REMEDIATION_DONE). Toàn bộ aiChat được lưu vào localStorage (qua
// course-progress.js) sau mỗi bước -> nếu người dùng đóng modal giữa chừng
// rồi mở lại đúng level đó, ta dựng lại đúng giai đoạn đang dở thay vì bắt
// đầu lại từ đầu.

const AI_CONFIDENCE_QUESTION =
  'Sau khi xem đáp án và lời giải, bạn tự đánh giá mức độ tự tin của mình trong việc phân biệt và sử dụng các từ này trong một ngữ cảnh mới là bao nhiêu trên thang điểm 10?';

// Tên hiển thị của từng world, khớp với config.title/subtitle trong
// js/pages/world1.js và world2.js - dùng để soạn lời chào mừng ngắn khi vào 1
// level KHÔNG phải World 1 - Level 1 (level đó mới có hướng dẫn cách dùng đầy
// đủ, các level còn lại chỉ cần 1 câu chào mừng phù hợp).
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

// AI hay trả lời kèm markdown nhẹ (####, **bold**, gạch đầu dòng). Escape
// trước để chặn HTML lạ, sau đó mới "dịch" đúng các ký hiệu markdown mình hỗ
// trợ thành thẻ HTML thật — không dùng innerHTML trực tiếp trên text gốc.
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

// Điểm thoát DUY NHẤT khi người dùng chủ động rời khỏi modal (nút ✕ ở header,
// bấm ra ngoài nền tối, và cả nút "Đóng" trong footer báo cáo). Trước đây nút
// ✕/bấm ra ngoài gọi thẳng closeAIChat() nên nếu người dùng không bấm đúng
// nút "Đóng" trong footer, kết quả không được lưu - giờ việc lưu đã tách khỏi
// đây hoàn toàn (xem aiRenderFinalReport), hàm này chỉ lo dọn dẹp + đóng modal.
function aiHandleUserDismiss() {
  if (!aiChat) { closeAIChat(); return; }
  const worldId = aiChat.worldId;
  const level = aiChat.level;
  const onComplete = aiChat.onComplete;

  // Kết quả đã được lưu NGAY khi báo cáo hiển thị (xem aiRenderFinalReport),
  // không đợi tới lúc đóng nữa. Chỉ XOÁ tiến trình resume khi báo cáo là PASS
  // - vì lần bấm vào level đó sau này là để "chơi lại" (replay) 1 lượt hoàn
  // toàn mới, không phải xem lại báo cáo cũ. Nếu là RETRY thì GIỮ NGUYÊN tiến
  // trình: level đó chưa qua (vẫn là node "current"), nên bấm vào lại phải
  // quay về đúng trang báo cáo vừa rồi, không được khởi động lại từ đầu. Mọi
  // giai đoạn khác (kể cả các bước ôn tập) vẫn lưu liên tục qua
  // aiPersistProgress() ở mỗi bước như bình thường.
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

// Nếu backend báo phiên không tồn tại (thường do server bị khởi động lại
// giữa chừng), việc "Thử lại" y hệt sẽ luôn thất bại vì session đã mất. Thay
// vào đó cho người dùng lựa chọn bắt đầu lại từ đầu (session mới).
function aiRenderSessionAwareError(e, onRetry) {
  const msg = e && e.message ? e.message : String(e);
  if (/không tồn tại hoặc đã hết hạn/i.test(msg)) {
    aiSetBody(`<div class="ai-error">Phiên làm bài đã hết hạn (có thể do server khởi động lại). Bạn cần bắt đầu lại từ đầu.</div>`);
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
    const res = await gestureStartSession(aiChat.worldId, aiChat.level, aiChat.isRetry);
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

  // World 1 - Level 1 (lần đầu, không phải retry): hiện hướng dẫn cách dùng
  // đầy đủ. MỌI level khác (kể cả replay/retry của chính level 1 đó): chỉ
  // hiện 1 lời chào mừng ngắn theo đúng world/level - không lặp lại hướng dẫn
  // cách dùng vốn chỉ cần đọc 1 lần duy nhất.
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
  `);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-begin-recognition-btn">Bắt đầu làm bài (20 câu)</button>`);
  document.getElementById('ai-begin-recognition-btn').addEventListener('click', aiBeginRecognition);
  aiPersistProgress();
}

// ---- Bước 2: sinh 20 MCQ ----

async function aiBeginRecognition() {
  aiRenderLoading('AI đang soạn 20 câu hỏi... (có thể mất 30–60 giây)');
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
    aiRenderMCQList();
  } catch (e) {
    aiRenderSessionAwareError(e, aiBeginRecognition);
  }
}

function aiRenderMCQList() {
  aiChat.stage = 'RECOGNITION';
  const optionLabels = ['A', 'B', 'C', 'D'];
  const itemsHtml = aiChat.questions.map((q, qIndex) => `
    <div class="ai-mcq-item">
      <div class="ai-mcq-question"><strong>Câu ${qIndex + 1}.</strong>${aiEscapeHtml(q.question)}</div>
      <div class="ai-mcq-options">
        ${q.options.map((opt, i) => `
          <label class="ai-mcq-option">
            <input type="radio" name="ai-q-${q.id}" value="${i}" ${aiChat.answers[String(q.id)] === i ? 'checked' : ''}>
            <span>${optionLabels[i]}. ${aiEscapeHtml(opt)}</span>
          </label>
        `).join('')}
      </div>
    </div>
  `).join('');

  aiSetBody(`
    <div class="ai-mcq-progress" id="ai-mcq-progress">Đã trả lời: ${Object.keys(aiChat.answers).length} / ${aiChat.questions.length}</div>
    <div class="ai-mcq-list">${itemsHtml}</div>
  `);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-submit-mcq-btn" ${Object.keys(aiChat.answers).length < aiChat.questions.length ? 'disabled' : ''}>Nộp bài</button>`);

  aiChatEls.body.querySelectorAll('input[type="radio"]').forEach(input => {
    input.addEventListener('change', (e) => {
      const qid = e.target.name.replace('ai-q-', '');
      aiChat.answers[qid] = parseInt(e.target.value, 10);
      aiUpdateMCQProgress();
      aiPersistProgress();
    });
  });

  document.getElementById('ai-submit-mcq-btn').addEventListener('click', aiSubmitRecognition);
  aiPersistProgress();
}

function aiUpdateMCQProgress() {
  const total = aiChat.questions.length;
  const answered = Object.keys(aiChat.answers).length;
  const progressEl = document.getElementById('ai-mcq-progress');
  if (progressEl) progressEl.textContent = `Đã trả lời: ${answered} / ${total}`;
  const submitBtn = document.getElementById('ai-submit-mcq-btn');
  if (submitBtn) submitBtn.disabled = answered < total;
}

// ---- Bước 3: chấm + correction ----

async function aiSubmitRecognition() {
  aiRenderLoading('Đang chấm bài và soạn giải thích...');
  try {
    const res = await gestureSubmitRecognition(aiChat.sessionId, aiChat.answers);
    // Lưu tạm cặp từ chọn-sai/đúng của LƯỢT NÀY - dùng khi lưu kết quả cuối
    // cùng (saveThisAttemptResult) để trang Analysis có dữ liệu phân tích xu
    // hướng nhầm lẫn từ vựng cụ thể, không cần gọi thêm AI.
    aiChat.wrongWords = res.wrong_words || [];
    aiRenderCorrection(res.correction_text);
  } catch (e) {
    aiRenderSessionAwareError(e, aiSubmitRecognition);
  }
}

function aiRenderCorrection(correctionText) {
  aiChat.stage = 'CORRECTION';
  aiChat.correctionText = correctionText;
  aiSetBody(`<div class="ai-msg">${aiMarkdownToHtml(correctionText)}</div>`);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-to-confidence-btn">Tiếp tục</button>`);
  document.getElementById('ai-to-confidence-btn').addEventListener('click', aiRenderConfidenceQuestion);
  aiPersistProgress();
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

// Lưu kết quả lượt vừa xong (accuracy = Overall + illusion status). Gọi NGAY
// khi màn báo cáo hiện ra (xem aiRenderFinalReport) - không đợi người dùng
// bấm nút nào, để không phụ thuộc vào việc họ thoát bằng cách nào (Đóng, Ôn
// tập & Kiểm tra lại, ✕, bấm ra ngoài, hay đóng hẳn tab).
function saveThisAttemptResult(report) {
  const isPass = report.final_result === 'PASS';
  if (isPass && typeof advanceWorldCompletedLevels === 'function') {
    advanceWorldCompletedLevels(aiChat.worldId, aiChat.level);
  }
  if (typeof setLevelResults === 'function') {
    // Lưu ĐẦY ĐỦ breakdown (không chỉ accuracy/illusion_status) - trang
    // Analysis cần recognition/distinction/application/overall/confidence/gap
    // riêng biệt + wrong_words/feedback để phân tích xu hướng nhầm lẫn.
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

// Ghi lại nhóm từ đã học (vĩnh viễn, không bị "Chơi lại" xoá) - lấy thẳng từ
// KB qua GET nhẹ, không phải AI call. Không chặn luồng chính nếu lỗi; thử lại
// vài lần vì đây là lúc PASS duy nhất trong lượt này, bỏ lỡ thì phải đợi lần
// pass sau (thường là replay) mới có cơ hội ghi lại.
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

  // Lưu kết quả NGAY khi báo cáo hiện ra (không đợi người dùng bấm nút nào cả)
  // - đảm bảo badge dưới level luôn được cập nhật dù người dùng thoát bằng
  // cách nào sau đó: bấm "Đóng", bấm "Ôn tập & Kiểm tra lại", bấm ✕, bấm ra
  // ngoài nền tối, hay thậm chí đóng thẳng tab/điều hướng sang trang khác.
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
        ${aiRubricTableHtml(report.distinction_rubric)}
        ${aiMarkdownToHtml(report.distinction_feedback)}
      </div>
      <div class="ai-feedback-block">
        <div class="ai-open-ended-label">Rubric Vận dụng (${report.application_score.toFixed(1)}/10)</div>
        ${aiRubricTableHtml(report.application_rubric)}
        ${aiMarkdownToHtml(report.application_feedback)}
      </div>

      ${retryNoteHtml}
    </div>
  `);

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
// Phân tích câu sai (recognition) + điểm/nhận xét yếu (distinction/application)
// để tạo 1 bài luyện tập nhỏ cho CẢ 3 PHẦN, rồi mới cho retest đầy đủ.

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
    // Retest = chạy lại đúng luồng chính (20 MCQ -> confidence -> 2 câu mở).
    // Nếu vẫn RETRY, aiRenderFinalReport sẽ lại đưa ra nút "Ôn tập & Kiểm tra
    // lại" -> chu kỳ ôn tập/retest tự lặp cho tới khi PASS.
    aiChat.questions = null;
    aiChat.answers = {};
    aiBeginRecognition();
  });
  aiPersistProgress();
}
