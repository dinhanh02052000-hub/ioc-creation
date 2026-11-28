// ==== AI CHATBOT UI ====
// Khung chat nổi cho level có bật AI: chỉ lo hiển thị + thu thập input, mọi
// gọi mạng đi qua gesture.js, điểm/PASS-RETRY do backend quyết định.
//
// aiChat.stage đánh dấu giai đoạn UI hiện tại và được lưu vào localStorage
// (qua course-progress.js) sau mỗi bước, để đóng modal giữa chừng rồi mở lại
// vẫn tiếp tục đúng chỗ thay vì phải làm lại từ đầu.

const AI_CONFIDENCE_INTRO =
  'Em vừa xem lại phần Nhận biết. Ở hai phần tiếp theo, em sẽ tự phân biệt và sử dụng từ trong ngữ cảnh mới. Dựa vào tiêu chí bên dưới, em dự đoán mình sẽ đạt bao nhiêu điểm?';

const AI_CONFIDENCE_SKILLS = [
  {
    key: 'distinction',
    title: 'A. Dự đoán Distinction – Phân biệt từ',
    question: 'Khi đọc một câu mới, em sẽ giải thích vì sao một từ phù hợp và so sánh nó với một từ gần nghĩa. Em dự đoán bài của mình sẽ đạt bao nhiêu điểm trên 10?'
  },
  {
    key: 'application',
    title: 'B. Dự đoán Application – Vận dụng từ',
    question: 'Khi gặp một tình huống mới, em sẽ chọn từ, đặt một câu tiếng Anh và giải thích lựa chọn của mình. Em dự đoán bài của mình sẽ đạt bao nhiêu điểm trên 10?'
  }
];

const AI_CONFIDENCE_REASONS = {
  familiar: 'Em đã gặp các từ này nhiều lần nên thấy quen.',
  understood_after_explanation: 'Khi đọc lời giải, em hiểu vì sao đáp án phù hợp.',
  explained_before: 'Em từng tự giải thích được sự khác nhau giữa những từ này.',
  used_before: 'Em từng tự dùng từ trong một câu hoặc tình huống mới.',
  not_enough_basis: 'Em chưa có đủ căn cứ để ước lượng.',
  other: 'Lý do khác.'
};

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
    prediction: null,
    confidenceSubmitting: false,
    attemptId: null,
    questionStates: {},
    explanationStatus: {},
    explanationPartial: {},
    explanationBusy: {},
    recognitionSummary: null,
    recognitionStatus: null,
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
      <div class="ai-chat-body" id="ai-chat-body" data-dict></div>
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
    case 'RECOGNITION': aiRecoverRecognition(); break;
    case 'CORRECTION': aiRenderCorrection(aiChat.correctionText); break;
    case 'CONFIDENCE': aiRenderConfidenceQuestion(); break;
    case 'OPEN_ENDED': aiRenderOpenEnded(aiChat.distinctionPrompt, aiChat.applicationPrompt); break;
    case 'REPORT': aiRenderFinalReport(aiChat.report); break;
    case 'REMEDIATION_RECAP': aiRenderRemediationRecap(); break;
    case 'REMEDIATION_CARD': aiRenderRemediationCards(true); break;
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

// Present Knowledge: tình huống -> từng từ -> so sánh trực tiếp. Bài cũ lưu ở máy
// (chuỗi markdown) vẫn hiển thị được.
function aiLessonHtml(content) {
  if (!content || typeof content !== 'object') {
    return `<div class="ai-msg">${aiMarkdownToHtml(content || '')}</div>`;
  }
  const inline = (t) => aiInlineMarkdown(aiEscapeHtml(t || ''));
  const wordCards = (content.words || []).map(w => `
    <div class="ai-lesson-word">
      <div class="ai-lesson-word__head">
        <span class="ai-lesson-word__name">${aiEscapeHtml(w.word)}</span>
        <span class="ai-lesson-word__meaning">${inline(w.meaning_vi)}</span>
      </div>
      <div class="ai-lesson-row ai-lesson-row--en"><span class="ai-lesson-label">Câu ví dụ</span><span class="ai-lesson-text">${inline(w.example_en)}</span></div>
      <div class="ai-lesson-row"><span class="ai-lesson-label">Ý của câu</span><span class="ai-lesson-text">${inline(w.example_vi)}</span></div>
      <div class="ai-lesson-row ai-lesson-row--why"><span class="ai-lesson-label">Vì sao dùng từ này</span><span class="ai-lesson-text">${inline(w.why)}</span></div>
    </div>`).join('');
  const c = content.contrast;
  const contrast = c ? `
    <div class="ai-lesson-section">So sánh trực tiếp</div>
    <div class="ai-lesson-contrast">
      <div class="ai-lesson-contrast__pair">
        ${Array.isArray(c.sentences)
          ? c.sentences.filter(x => x && x.word && x.sentence).map(x => `<div class="ai-lesson-contrast__side"><span class="ai-lesson-contrast__word">${aiEscapeHtml(x.word)}</span><span>${inline(x.sentence)}</span>${x.focus ? `<span class="ai-lesson-contrast__focus">${inline(x.focus)}</span>` : ''}</div>`).join('')
          : (c.word_a && c.sentence_a && c.word_b && c.sentence_b
              ? `<div class="ai-lesson-contrast__side"><span class="ai-lesson-contrast__word">${aiEscapeHtml(c.word_a)}</span><span>${inline(c.sentence_a)}</span></div>
                 <div class="ai-lesson-contrast__side"><span class="ai-lesson-contrast__word">${aiEscapeHtml(c.word_b)}</span><span>${inline(c.sentence_b)}</span></div>`
              : '')}
      </div>
      <div class="ai-lesson-contrast__why">${inline(c.explanation)}</div>
    </div>` : '';
  return `
    <div class="ai-lesson">
      <div class="ai-lesson-section">Tình huống</div>
      <div class="ai-lesson-intro">${inline(content.intro)}</div>
      <div class="ai-lesson-section">Từng từ</div>
      ${wordCards}
      ${contrast}
    </div>`;
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
        Cách dùng: đọc phần giải thích bên dưới, sau đó làm các câu trắc nghiệm,
        xem giải thích các câu sai, tự chấm mức độ tự tin, rồi trả lời 2 câu hỏi
        mở để AI đánh giá khả năng vận dụng thực tế của bạn. Cuối cùng bạn sẽ
        nhận được kết quả PASS hoặc cần ôn tập thêm.
      </div>`
    : `<div class="ai-msg-system ai-msg-onboarding">${aiWelcomeMessage(aiChat.worldId, aiChat.level)}</div>`;

  aiSetBody(`
    ${onboardingBlock}
    <div class="ai-msg-system">Chào bạn! Hôm nay chúng ta học nhóm từ: <strong>${aiEscapeHtml(groupTitle)}</strong></div>
    <div class="ai-dict-hint">Bấm vào một từ hoặc bôi đen cụm từ để tra từ điển Cambridge (Anh–Anh / Anh–Việt).</div>
    ${aiLessonHtml(content)}
    <div class="ai-start-notice">
      <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="10" cy="10" r="7.5"/>
        <line x1="10" y1="6.5" x2="10" y2="10.5"/>
        <circle cx="10" cy="13.3" r="0.15" fill="currentColor" stroke-width="1.2"/>
      </svg>
      <span>Để kết quả được tối ưu, trong quá trình làm bài không dùng công cụ hoặc thiết bị hỗ trợ.</span>
    </div>
  `);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-begin-recognition-btn">Bắt đầu làm bài</button>`);
  document.getElementById('ai-begin-recognition-btn').addEventListener('click', aiBeginRecognition);
  aiPersistProgress();
}

// ---- Bước 2: sinh 20 MCQ ----

async function aiBeginRecognition() {
  aiRenderLoading('Đang chuẩn bị câu hỏi (có thể mất 1-3 phút)...');
  try {
    const history = typeof loadRecognitionHistory === 'function'
      ? loadRecognitionHistory(aiChat.worldId, aiChat.level)
      : [];
    const res = await gestureBeginRecognition(aiChat.sessionId, history);
    aiChat.questions = res.questions;
    aiChat.answers = res.resumed ? aiKeepSavedAnswers(res.questions) : {};
    aiChat.recoveredOnce = false;
    // Bộ mở lại (đã phát trước đó) không ghi lịch sử lần nữa.
    if (!res.resumed && typeof appendRecognitionHistory === 'function') {
      appendRecognitionHistory(aiChat.worldId, aiChat.level, res.questions.map(q => q.question));
    }
    if (typeof setHeaderKeyDisplay === 'function') {
      setHeaderKeyDisplay(res.keys_remaining);
    }
    aiRenderMCQList();
  } catch (e) {
    if (aiIsSessionLost(e) && !aiChat.recoveredOnce) {
      aiChat.recoveredOnce = true;
      await aiRecoverRecognition();
      return;
    }
    aiRenderSessionAwareError(e, aiBeginRecognition);
  }
}

function aiIsSessionLost(e) {
  return !!e && (e.status === 404 || /không tồn tại hoặc đã hết hạn/i.test(e.message || '')) && !/đăng nhập/i.test(e.message || '');
}

// Giữ lại các lựa chọn đã chọn trước khi thoát nếu bộ câu mở lại là đúng bộ đó (cùng id câu).
function aiKeepSavedAnswers(questions) {
  const ids = new Set((questions || []).map(q => String(q.id)));
  const kept = {};
  Object.keys(aiChat.answers || {}).forEach(k => { if (ids.has(String(k))) kept[k] = aiChat.answers[k]; });
  return kept;
}

// Vào lại giữa lúc làm trắc nghiệm (hoặc phiên máy chủ đã mất): lấy lại đúng bộ câu đã phát, không quay về trang bài học và không sinh lại.
async function aiRecoverRecognition() {
  aiRenderLoading('Đang mở lại bài làm của bạn...');
  try {
    const history = typeof loadRecognitionHistory === 'function' ? loadRecognitionHistory(aiChat.worldId, aiChat.level) : [];
    const res = await gestureResumeSession(aiChat.sessionId, aiChat.worldId, aiChat.level, aiChat.isRetry, history);
    aiChat.sessionId = res.session_id;
    if (res.questions) {
      aiChat.questions = res.questions;
      aiChat.answers = aiKeepSavedAnswers(res.questions);
      if (typeof setHeaderKeyDisplay === 'function' && res.keys_remaining != null) setHeaderKeyDisplay(res.keys_remaining);
      aiRenderMCQList();
    } else if (aiChat.learningContent) {
      aiRenderLearningContent(aiChat.groupTitle, aiChat.learningContent);   // chưa phát đề: về đúng bài học đã lưu (không tải lại)
    } else {
      aiStartFlow();
    }
  } catch (e) {
    aiRenderSessionAwareError(e, aiRecoverRecognition);
  }
}

// Nhãn độ khó (mức do AI thẩm định). Câu không có trường difficulty (bộ cũ, câu ôn tập) thì không hiện nhãn.
function aiDifficultyChipHtml(level) {
  const map = { easy: 'Dễ', medium: 'Vừa', hard: 'Khó' };
  return map[level] ? `<span class="ai-q-diff ai-q-diff--${level}" title="Độ khó do AI thẩm định">${map[level]}</span>` : '';
}

// "___" trong câu hỏi hiển thị thành ô trống gạch chân, dễ nhìn hơn dấu gạch thô.
// spans (tùy chọn): đoạn cần tô đậm, đã được máy chủ kiểm là có nguyên văn trong thân câu. Chỉ tô lần xuất hiện đầu tiên.
function aiQuestionHtml(text, spans) {
  let html = aiEscapeHtml(text);
  (spans || []).forEach(span => {
    const e = aiEscapeHtml(span);
    const at = e ? html.indexOf(e) : -1;
    if (at >= 0) html = html.slice(0, at) + '<strong class="ai-q-hl">' + e + '</strong>' + html.slice(at + e.length);
  });
  return html.replace(/_{3,}/g, '<span class="ai-q-blank">&nbsp;</span>');
}

// Mô tả mức khó trước bài. Số câu dễ/vừa/khó lấy từ mức đã thẩm định của CHÍNH bộ câu đang phát; câu chưa có mức thì nêu số đó,
// không có câu nào có mức thì không hiện thống kê.
function aiQuizNoticeHtml(questions) {
  const c = { easy: 0, medium: 0, hard: 0, unknown: 0 };
  (questions || []).forEach(q => { if (c[q.difficulty] !== undefined && q.difficulty !== 'unknown') c[q.difficulty] += 1; else c.unknown += 1; });
  const known = c.easy + c.medium + c.hard;
  const stats = known
    ? `<div class="ai-quiz-notice__stats">Mức khó dự kiến: ${c.easy} câu dễ · ${c.medium} câu vừa · ${c.hard} câu khó${c.unknown ? ` · ${c.unknown} câu chưa xác định mức` : ''}</div>`
    : '';
  return `<div class="ai-quiz-notice"><div>Bài có các câu nhận biết cách dùng và phân biệt sắc thái trong ngữ cảnh mới. Một số câu cần đọc cả tình huống để lựa chọn.</div>${stats}</div>`;
}

function aiRenderMCQList() {
  aiChat.stage = 'RECOGNITION';
  aiRenderQuizView({
    questions: aiChat.questions,
    answers: aiChat.answers,
    onSubmit: aiSubmitRecognition,
    submitLabel: 'Nộp bài'
  });
}

// Giao diện làm bài trắc nghiệm dùng chung cho 20 câu chính thức và 10 câu ôn tập.
// ctx.answers là object được giữ nguyên tham chiếu để các thay đổi lưu lại vào aiChat.
let aiQuizCtx = null;

function aiRenderQuizView(ctx) {
  aiQuizCtx = ctx;
  const optionLabels = ['A', 'B', 'C', 'D'];
  const total = ctx.questions.length;

  const itemsHtml = ctx.questions.map((q, qIndex) => `
    <section class="ai-q" id="ai-q-card-${q.id}">
      <div class="ai-q-head"><span class="ai-q-num">Câu ${qIndex + 1}</span>${aiDifficultyChipHtml(q.difficulty)}</div>
      <p class="ai-q-text">${aiQuestionHtml(q.question)}</p>
      <div class="ai-q-options">
        ${q.options.map((opt, i) => `
          <label class="ai-q-option">
            <input type="radio" name="ai-q-${q.id}" value="${i}" ${ctx.answers[String(q.id)] === i ? 'checked' : ''}>
            <span class="ai-q-radio"></span>
            <span class="ai-q-option-text"><b>${optionLabels[i]}.</b> ${aiEscapeHtml(opt)}</span>
          </label>
        `).join('')}
      </div>
    </section>
  `).join('');

  const navHtml = ctx.questions.map((q, qIndex) =>
    `<button type="button" class="ai-quiz-nav-btn" data-qid="${q.id}">${qIndex + 1}</button>`
  ).join('');

  aiSetBody(`
    <div class="ai-quiz">
      <div class="ai-quiz-main">${aiQuizNoticeHtml(ctx.questions)}${itemsHtml}</div>
      <aside class="ai-quiz-nav">
        <div class="ai-quiz-nav-head">
          <span>Đã làm</span><strong id="ai-mcq-progress">0/${total}</strong>
        </div>
        <div class="ai-quiz-nav-bar"><div class="ai-quiz-nav-bar-fill" id="ai-mcq-bar"></div></div>
        <div class="ai-quiz-nav-grid">${navHtml}</div>
      </aside>
    </div>
  `);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-submit-mcq-btn" disabled>${ctx.submitLabel}</button>`);

  aiChatEls.body.querySelectorAll('input[type="radio"]').forEach(input => {
    input.addEventListener('change', (e) => {
      const qid = e.target.name.replace('ai-q-', '');
      ctx.answers[qid] = parseInt(e.target.value, 10);
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

  document.getElementById('ai-submit-mcq-btn').addEventListener('click', ctx.onSubmit);
  aiUpdateMCQProgress();
  aiPersistProgress();
}

function aiUpdateMCQProgress() {
  const ctx = aiQuizCtx;
  if (!ctx) return;
  const total = ctx.questions.length;
  const answered = Object.keys(ctx.answers).length;
  const progressEl = document.getElementById('ai-mcq-progress');
  if (progressEl) progressEl.textContent = `${answered}/${total}`;
  const barEl = document.getElementById('ai-mcq-bar');
  if (barEl) barEl.style.width = `${(answered / total) * 100}%`;
  aiChatEls.body.querySelectorAll('.ai-quiz-nav-btn').forEach(btn => {
    btn.classList.toggle('answered', ctx.answers[btn.getAttribute('data-qid')] !== undefined);
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
    aiChat.explanationStatus = res.explanation_status || {};
    aiChat.explanationPartial = res.explanation_partial || {};
    aiChat.explanationBusy = {};
    aiChat.questionStates = res.question_states || {};
    aiChat.attemptId = res.attempt_id || null;
    aiChat.recognitionSummary = {
      correct: res.correct_count, total: res.valid_total, score: res.recognition, tentative: !!res.tentative
    };
    aiChat.recoveredOnce = false;
    aiRenderCorrection(res.correction_text);
  } catch (e) {
    if (aiIsSessionLost(e) && !aiChat.recoveredOnce) {
      // Phiên mất giữa chừng: mở lại đúng bộ câu đã phát với phiên mới rồi nộp lại đúng các lựa chọn em đã chọn.
      aiChat.recoveredOnce = true;
      try {
        const history = typeof loadRecognitionHistory === 'function' ? loadRecognitionHistory(aiChat.worldId, aiChat.level) : [];
        const r = await gestureResumeSession(aiChat.sessionId, aiChat.worldId, aiChat.level, aiChat.isRetry, history);
        aiChat.sessionId = r.session_id;
        if (r.questions) { aiChat.questions = r.questions; aiChat.answers = aiKeepSavedAnswers(r.questions); await aiSubmitRecognition(); return; }
      } catch (e2) { aiRenderSessionAwareError(e2, aiSubmitRecognition); return; }
    }
    aiRenderSessionAwareError(e, aiSubmitRecognition);
  }
}

// Trang kết quả phần trắc nghiệm: lời giải CHỈ hiện ở đây (sau khi nộp). Câu
// đúng chỉ báo ngắn gọn; câu sai hiện đáp án đúng, còn phần giải thích AI viết
// 1 khối chung cho mọi câu sai (backend không tách theo từng câu).
function aiRenderCorrection(correctionText) {
  aiChat.stage = 'CORRECTION';
  aiChat.correctionText = correctionText;
  aiRenderReviewView({
    questions: aiChat.questions || [],
    answers: aiChat.answers,
    wrongWords: aiChat.wrongWords || [],
    explanations: aiChat.explanations || {},
    explanationStatus: aiChat.explanationStatus || {},
    explanationPartial: aiChat.explanationPartial || {},
    explanationBusy: aiChat.explanationBusy || {},
    states: aiChat.questionStates || {},
    summary: aiChat.recognitionSummary || null,
    correctionText,
    reportable: true,
    continueLabel: 'Tiếp tục',
    onContinue: aiRenderConfidenceQuestion
  });
}

// Trang xem lại bài trắc nghiệm, dùng chung cho 20 câu chính thức và 10 câu ôn tập.
function aiRenderReviewView(opts) {
  const labels = ['A', 'B', 'C', 'D'];
  const wrongByQuestion = new Map(opts.wrongWords.map(w => [w.question, w]));
  const questions = opts.questions;
  let wrongCount = 0;

  const reviewHtml = questions.map((q, qIndex) => {
    const selected = opts.answers[String(q.id)];
    const wrong = wrongByQuestion.get(q.question);
    const correctIndex = wrong ? q.options.indexOf(wrong.correct) : selected;
    const isCorrect = !wrong;
    if (!isCorrect) wrongCount += 1;
    const explanation = opts.explanations[String(q.id)];
    const explStatus = (opts.explanationStatus || {})[String(q.id)];
    const partial = (opts.explanationPartial || {})[String(q.id)];
    const busy = !!(opts.explanationBusy || {})[String(q.id)];
    const qState = (opts.states || {})[String(q.id)];

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
          <span class="ai-q-num">Câu ${qIndex + 1}</span>${aiDifficultyChipHtml(q.difficulty)}
          <span class="ai-q-status ${isCorrect ? 'ok' : 'bad'}">${isCorrect ? 'Đúng' : 'Sai'}</span>
        </div>
        ${aiQuestionStateHtml(qState, explStatus)}
        <p class="ai-q-text">${aiQuestionHtml(q.question, aiExplanationStem(explanation))}</p>
        <div class="ai-q-options">${optionsHtml}</div>
        ${(opts.reportable || opts.practice)
          ? aiExplanationBlockHtml({ q, isCorrect, explanation, explStatus, partial, busy, qState })
          : (isCorrect
              ? '<div class="ai-q-feedback ok">Bạn đã trả lời chính xác!</div>'
              : (explanation ? `<div class="ai-q-feedback bad">${aiExplanationHtml(explanation)}</div>` : ''))}
        ${opts.reportable ? `<button type="button" class="ai-report-btn" data-report="recognition" data-qid="${q.id}">Báo lỗi câu hỏi hoặc lời giải</button>
        <div class="ai-report-slot"></div>` : ''}
      </section>
    `;
  }).join('');

  const sum = opts.summary;
  const correctCount = sum && Number.isFinite(sum.correct) ? sum.correct : questions.length - wrongCount;
  const totalCount = sum && Number.isFinite(sum.total) ? sum.total : questions.length;
  const missingExpl = Object.values(opts.explanationStatus || {}).filter(v => v === 'unavailable').length;
  const hasPerQuestion = Object.keys(opts.explanations).length > 0;
  const explainHtml = (wrongCount && !hasPerQuestion && opts.correctionText)
    ? `<section class="ai-q ai-q-explain">
         <div class="ai-q-head"><span class="ai-q-num">Giải thích các câu sai</span></div>
         <div class="ai-msg">${aiMarkdownToHtml(opts.correctionText)}</div>
       </section>`
    : '';

  aiSetBody(`
    <div class="ai-review-summary">
      Bạn trả lời đúng <strong>${correctCount}/${totalCount}</strong> câu.
      ${sum && sum.tentative ? '<div class="ai-review-tentative">Điểm đang tạm tính: có câu đang được xem lại đáp án.</div>' : ''}
      ${missingExpl ? `<div class="ai-review-tentative">${missingExpl} câu chưa có lời giải. <button type="button" class="ai-btn" id="ai-regen-expl-btn">Tạo lại lời giải còn thiếu</button></div>` : ''}
    </div>
    <div class="ai-review-list">${reviewHtml}</div>
    ${explainHtml}
  `);
  if (opts.reportable) aiBindReportButtons();
  if (opts.reportable || opts.practice) aiBindExplanationButtons();
  const regen = document.getElementById('ai-regen-expl-btn');
  if (regen) regen.addEventListener('click', aiRegenerateExplanations);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-review-continue-btn">${opts.continueLabel}</button>`);
  document.getElementById('ai-review-continue-btn').addEventListener('click', opts.onContinue);
  aiPersistProgress();
}

// ---- Chỉ số tin cậy + báo cáo của người dùng ----

// Làm đậm 3 nhãn cố định của lời giải trắc nghiệm nếu AI chưa tự in đậm.
// Lời giải v2 là một chuỗi: ba phần chính, rồi khối '::others::' (các phương án còn lại), rồi '::stem::' (đoạn tô đậm trong thân câu).
// Bản cũ không có hai dấu này: hiện như trước.
function aiParseExplanation(text) {
  const out = { main: [], others: [], stem: [] };
  let cur = out.main;
  String(text || '').split('\n').forEach(raw => {
    const line = raw.trim();
    if (line === '::others::') cur = out.others;
    else if (line === '::stem::') cur = out.stem;
    else if (line) cur.push(line);
  });
  return out;
}

function aiExplanationStem(text) { return aiParseExplanation(text).stem; }

function aiExplanationHtml(text) {
  const p = aiParseExplanation(text);
  const others = p.others.length
    ? `<details class="ai-expl-others"><summary>Xem các phương án còn lại</summary>${aiMarkdownToHtml(p.others.join('\n'))}</details>`
    : '';
  return aiMarkdownToHtml(aiBoldExplanationLabels(p.main.join('\n'))) + others;
}

function aiBoldExplanationLabels(text) {
  return String(text).replace(/(^|\n)(\s*-\s*)(?!\*\*)(Dấu hiệu ngữ pháp|Từ khóa manh mối|So sánh & dịch nghĩa)\s*:/g, '$1$2**$3:**');
}

function aiModelAnswerHtml(text) {
  if (!text) return '';
  return `<div class="ai-model-answer"><div class="ai-report-label">Đáp án tham khảo</div>${aiMarkdownToHtml(text)}</div>`;
}

function aiSpreadHtml(spread, kind, grading) {
  const v = spread && spread[kind];
  if (v == null) return '';
  const warn = v > spread.flag_threshold;               // chỉ lệch HƠN ngưỡng (0,75) mới có lượt chấm thứ ba
  const g = grading && grading[kind];
  const third = g && g.third_pass;
  const fmt = (x) => String(Number(x)).replace('.', ',');
  const note = third
    ? ' · đã chấm lần thứ ba, điểm từng tiêu chí lấy trung vị của ba lượt'
    : (warn ? ' · nên xem lại kỹ' : '');
  const flags = g && g.criterion_flags && g.criterion_flags.length
    ? ` · hai lượt chưa thống nhất ở ${g.criterion_flags.length} tiêu chí` : '';
  return `<div class="ai-spread ${warn ? 'warn' : 'good'}">
    Chênh lệch tổng giữa 2 lượt AI chấm: <strong>${fmt(v)} điểm</strong>${note}${flags}</div>`;
}

function aiBindReportButtons() {
  aiChatEls.body.querySelectorAll('.ai-report-btn').forEach(btn => {
    btn.addEventListener('click', () => aiOpenReportForm(btn));
  });
}

function aiOpenReportForm(btn) {
  if (btn.dataset.report === 'recognition') { aiOpenRecognitionReportForm(btn); return; }
  if (btn.dataset.report === 'distinction' || btn.dataset.report === 'application') { aiOpenEndedReportForm(btn); return; }
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

// ---- Báo cáo điểm/nhận xét TỰ LUẬN: biểu mẫu theo loại, gắn với đúng lượt làm, bài, đề và rubric ----
// Học sinh đọc lại đề, bài nguyên văn và điểm các lượt ngay trong biểu mẫu (không phải gõ lại). Máy chủ tự đính kèm điểm/căn cứ các lượt.

const AI_OPEN_REPORT_TYPES = {
  missed_points: { label: 'AI bỏ sót ý hoặc chấm sai mức', criterion: true, quote: 'answer', score: true,
    hint: 'Chọn tiêu chí, đọc mô tả mốc điểm, bôi đen đoạn trong bài làm của em rồi bấm "Dùng đoạn đã chọn". Ghi ngắn đoạn đó đáp ứng điều gì.' },
  ai_conflict: { label: 'Hai lượt AI chấm mâu thuẫn', criterion: true, score: true, noteOptional: true,
    hint: 'Chọn tiêu chí em thấy các lượt chấm không thống nhất. Hệ thống tự đính kèm điểm và căn cứ của từng lượt.' },
  feedback_wrong: { label: 'Nhận xét sai hoặc gợi ý khó hiểu', target: 'feedback',
    hint: 'Chọn đúng câu nhận xét/gợi ý đang báo và nêu điều sai hoặc chỗ gây vướng. Em vẫn có thể đồng ý với số điểm.' },
  reference_issue: { label: 'Đáp án tham khảo có vấn đề',
    hint: 'Nêu lỗi nghĩa, ngữ pháp, thiếu yêu cầu của đề, hoặc một cách dùng khác hợp lý.' },
  rubric_mismatch: { label: 'Đề và rubric không khớp', criterion: true, quote: 'question', score: true,
    hint: 'Trích yêu cầu trong đề, chọn tiêu chí mà AI đã dùng để trừ điểm, và nêu vì sao yêu cầu đó không có trong đề.' },
  calc_error: { label: 'Sai tính toán hoặc hiển thị', target: 'calc', noteOptional: true,
    hint: 'Chọn ô điểm hoặc kết quả bị ảnh hưởng. Máy chủ tự lấy dữ liệu gốc để kiểm lại.' }
};
const AI_OPEN_FEEDBACK_TARGETS = { strength: 'Điều làm được', improve: 'Cần cải thiện', hint: 'Gợi ý sửa' };
const AI_OPEN_CALC_TARGETS = { criterion_score: 'Điểm một tiêu chí', skill_total: 'Tổng điểm của bài', overall: 'Overall', gap: 'Gap / Confidence' };
const AI_OPEN_STATUS_TEXT = {
  received: 'Đã nhận báo cáo.', reviewing: 'Báo cáo đang được xét.',
  accepted: 'Báo cáo của em được công nhận.', kept: 'Sau khi xét lại, hệ thống giữ kết quả hiện tại.',
  needs_human: 'Báo cáo cần người có thẩm quyền xem lại. Điểm hiện tại giữ nguyên trong lúc chờ.',
  pending_error: 'Chưa xét xong do lỗi kỹ thuật (không phải do báo cáo của em). Em bấm gửi lại để xét tiếp.'
};

function aiOpenReportResultHtml(res) {
  const status = AI_OPEN_STATUS_TEXT[res.status] || res.status;
  const cls = res.status === 'accepted' ? 'good' : 'warn';
  let extra = '';
  if (res.status === 'accepted' && res.decision_state === 'proposed') {
    extra = '<p>Điểm chỉ thay đổi sau khi người có thẩm quyền xác nhận; dự đoán em đã khóa được giữ nguyên.</p>';
  } else if (res.status === 'accepted' && res.fixed_text) {
    extra = `<p><strong>Bản sửa:</strong> ${aiEscapeHtml(res.fixed_text)}</p><p>Điểm giữ nguyên.</p>`;
  }
  return `<div class="ai-report-result ${cls}"><strong>${aiEscapeHtml(status)}</strong>${res.reply ? `<p>${aiEscapeHtml(res.reply)}</p>` : ''}${extra}</div>`;
}

function aiOpenEndedReportForm(btn) {
  const slot = btn.nextElementSibling;
  if (slot.innerHTML) { slot.innerHTML = ''; return; }
  const skill = btn.dataset.report;
  const report = aiChat.report || {};
  const detail = report.grading_detail && report.grading_detail[skill];
  const submitted = report.submitted && report.submitted[skill];
  if (!report.attempt_id || !submitted) {
    slot.innerHTML = '<div class="ai-report-result warn">Lượt này chưa có đủ hồ sơ để gửi báo cáo theo tiêu chí. Em thử lại sau khi tải lại kết quả.</div>';
    return;
  }
  const typeOptions = Object.keys(AI_OPEN_REPORT_TYPES).map(k =>
    `<label class="ai-report-opt"><input type="radio" name="ort-${skill}" value="${k}"> ${aiEscapeHtml(AI_OPEN_REPORT_TYPES[k].label)}</label>`).join('');
  const scores = detail
    ? detail.criteria.map(c => `${aiEscapeHtml(c.label)}: ${c.passes.map(p => aiFmt2(p.score)).join(' / ')} → ${aiFmt2(c.final)}/${aiFmt2(c.max)}`).join('<br>')
    : 'Lượt này không lưu điểm riêng từng lần chấm.';
  slot.innerHTML = `<div class="ai-report-form ai-open-report">
    <details class="ai-open-report-dossier"><summary>Xem lại đề, bài làm nguyên văn và điểm các lượt</summary>
      <div class="ai-report-label">Đề</div><div class="ai-open-report-box">${aiEscapeHtml(submitted.question)}</div>
      <div class="ai-report-label">Bài làm em đã nộp</div><div class="ai-open-report-box" data-answer-box>${aiEscapeHtml(submitted.answer)}</div>
      <div class="ai-report-label">Điểm các lượt (lượt 1 / lượt 2 → điểm chốt)</div><div class="ai-open-report-box">${scores}</div>
    </details>
    <div class="ai-report-label">Em muốn báo điều gì?</div>${typeOptions}
    <div class="ai-report-dyn"></div>
    <div class="ai-report-actions"><button type="button" class="ai-btn ai-report-send" disabled>Gửi báo cáo</button>
    <span class="ai-report-status" aria-live="polite"></span></div></div>`;

  const dyn = slot.querySelector('.ai-report-dyn');
  const sendBtn = slot.querySelector('.ai-report-send');
  const status = slot.querySelector('.ai-report-status');
  let chosen = null;
  let quote = '';

  slot.querySelectorAll(`input[name="ort-${skill}"]`).forEach(radio => {
    radio.addEventListener('change', () => {
      chosen = radio.value;
      quote = '';
      const spec = AI_OPEN_REPORT_TYPES[chosen];
      let html = '';
      if (spec.criterion) {
        const crit = detail ? detail.criteria : [];
        html += `<div class="ai-report-label">Tiêu chí bị ảnh hưởng</div>
          <select class="ai-report-select" data-field="criterion"><option value="">— chọn tiêu chí —</option>
          ${crit.map(c => `<option value="${aiEscapeHtml(c.key)}">${aiEscapeHtml(c.label)} (tối đa ${aiFmt2(c.max)})</option>`).join('')}</select>
          <div class="ai-open-report-bands" data-bands></div>`;
      }
      if (spec.target === 'feedback') {
        html += `<div class="ai-report-label">Câu nhận xét đang báo</div><select class="ai-report-select" data-field="target">
          <option value="">— chọn —</option>${Object.keys(AI_OPEN_FEEDBACK_TARGETS).map(k => `<option value="${k}">${AI_OPEN_FEEDBACK_TARGETS[k]}</option>`).join('')}</select>`;
      }
      if (spec.target === 'calc') {
        html += `<div class="ai-report-label">Ô điểm hoặc kết quả bị ảnh hưởng</div><select class="ai-report-select" data-field="target">
          <option value="">— chọn —</option>${Object.keys(AI_OPEN_CALC_TARGETS).map(k => `<option value="${k}">${AI_OPEN_CALC_TARGETS[k]}</option>`).join('')}</select>`;
      }
      if (spec.quote) {
        const src = spec.quote === 'answer' ? 'bài làm của em (bôi đen trong khung "Bài làm em đã nộp" ở trên)' : 'đề (bôi đen trong khung "Đề" ở trên)';
        html += `<div class="ai-report-label">Đoạn trích từ ${src}</div>
          <div class="ai-open-report-quote" data-quote-view>Chưa chọn đoạn nào</div>
          <button type="button" class="ai-btn ai-btn-secondary" data-use-selection>Dùng đoạn đã chọn</button>`;
      }
      if (spec.score) {
        html += `<div class="ai-report-label">Điểm em đề xuất cho tiêu chí (không bắt buộc, bước 0,5)</div>
          <input type="number" class="ai-report-note" data-field="score" min="0" step="0.5" inputmode="decimal">`;
      }
      html += `<div class="ai-report-label">${aiEscapeHtml(spec.hint)}${spec.noteOptional ? ' (không bắt buộc)' : ''}</div>
        <textarea class="ai-report-text" rows="3" maxlength="1200"></textarea>`;
      dyn.innerHTML = html;
      sendBtn.disabled = false;

      const sel = dyn.querySelector('[data-field="criterion"]');
      if (sel) {
        sel.addEventListener('change', () => {
          const c = detail && detail.criteria.find(x => x.key === sel.value);
          dyn.querySelector('[data-bands]').innerHTML = c && c.bands
            ? `<div class="ai-report-label">Mô tả mốc điểm</div>` + Object.keys(c.bands).map(k => `<div class="ai-open-report-band"><b>${aiFmt2(k)}:</b> ${aiEscapeHtml(c.bands[k])}</div>`).join('')
            : '';
        });
      }
      const useBtn = dyn.querySelector('[data-use-selection]');
      if (useBtn) {
        useBtn.addEventListener('click', () => {
          const text = String(window.getSelection ? window.getSelection().toString() : '').trim().replace(/\s+/g, ' ');
          if (!text) { status.textContent = 'Hãy bôi đen một đoạn trong khung bài làm/đề trước.'; return; }
          quote = text.slice(0, 400);
          dyn.querySelector('[data-quote-view]').textContent = `«${quote}»`;
          status.textContent = '';
        });
      }
    });
  });

  sendBtn.addEventListener('click', async () => {
    if (!chosen) { status.textContent = 'Hãy chọn loại vấn đề.'; return; }
    const spec = AI_OPEN_REPORT_TYPES[chosen];
    const field = (name) => { const el = dyn.querySelector(`[data-field="${name}"]`); return el ? el.value : ''; };
    const note = (dyn.querySelector('.ai-report-text') || { value: '' }).value.trim();
    if (spec.criterion && !field('criterion')) { status.textContent = 'Hãy chọn tiêu chí.'; return; }
    if (spec.target && !field('target')) { status.textContent = 'Hãy chọn đối tượng em đang báo.'; return; }
    if (spec.quote && !quote) { status.textContent = 'Hãy bôi đen và chọn đoạn trích.'; return; }
    if (!spec.noteOptional && note.length < 10) { status.textContent = 'Giải thích cần ít nhất 10 ký tự.'; return; }
    const scoreRaw = field('score');
    status.textContent = 'Đang gửi...';
    sendBtn.disabled = true;
    try {
      const res = await gestureSubmitOpenReport({
        attempt_id: report.attempt_id, skill, category: chosen, criterion: field('criterion') || null, target: field('target') || null,
        quote: quote || null, note: note || null, suggested_score: scoreRaw === '' ? null : Number(scoreRaw)
      });
      slot.innerHTML = aiOpenReportResultHtml(res);
    } catch (e) {
      status.textContent = e.message || 'Chưa gửi được báo cáo. Em thử lại (báo cáo sẽ không bị gửi trùng).';
      sendBtn.disabled = false;
    }
  });
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

// ---- Báo lỗi câu hỏi hoặc lời giải (Recognition chính thức) ----
// Học sinh chọn LOẠI vấn đề trước; trường chọn phương án chỉ hiện khi phù hợp. Máy chủ xét theo loại; một báo cáo
// mới gửi chưa có nghĩa là câu đã bị kết luận sai (điểm giữ nguyên cho tới khi có quyết định được xác nhận).

const AI_REPORT_TYPES = {
  wrong_key: {
    label: 'Đáp án hệ thống sai',
    hint: 'Chọn phương án em cho là đúng và nêu dấu hiệu trong câu khiến phương án đó phù hợp hơn.',
    options: 'one'
  },
  multiple_answers: {
    label: 'Có nhiều đáp án hợp lý',
    hint: 'Chọn từ hai phương án trở lên cùng điền được (có thể gồm cả đáp án hiện tại). Ghi chú ngắn như "A và C đều điền được" là đủ.',
    options: 'many'
  },
  no_answer: {
    label: 'Không có đáp án phù hợp / thiếu dữ kiện',
    hint: 'Chỉ ra phần bị thiếu, hoặc vì sao câu trở nên vô nghĩa với mọi lựa chọn.',
    options: 'none'
  },
  out_of_scope: {
    label: 'Câu hỏi ngoài nội dung đã học',
    hint: 'Nêu nghĩa, từ loại hoặc kiến thức chưa được dạy mà em cần để giải câu này.',
    options: 'none'
  },
  explanation_wrong: {
    label: 'Lời giải sai (em vẫn có thể đồng ý với đáp án)',
    hint: 'Chỉ ra đoạn giải thích, bản dịch hoặc phần so sánh bị sai và sai ở đâu.',
    options: 'none',
    noteRequired: true
  },
  explanation_unclear: {
    label: 'Lời giải khó hiểu',
    hint: 'Cho biết đoạn nào còn vướng. Em không cần chứng minh lỗi kiến thức.',
    options: 'none'
  }
};

// Ký hiệu chất lượng câu hỏi (chấm bằng quy tắc xác định từ hồ sơ thẩm định mù) và độ tin cậy của đáp án.
// Có cả chữ và số chấm, không chỉ dùng màu.
function aiSignalsHtml(sig) {
  if (!sig) return '';
  const dots = { high: 3, medium: 2, low: 1, review: 0, unknown: 0 };
  const q = sig.quality || { level: 'unknown', label: '' };
  const r = sig.reliability || { level: 'unknown', label: '' };
  const dotRow = (lvl) => [0, 1, 2].map(i => `<i class="ai-sig-dot${i < (dots[lvl] || 0) ? ' on' : ''}"></i>`).join('');
  const qTitle = q.passed == null ? q.label : `${q.label}: đạt ${q.passed}/${q.total} tiêu chí thẩm định (AI thẩm định mù, code quy đổi)`;
  return `<div class="ai-sigs">
    <span class="ai-sig ai-sig--${q.level}" title="${aiEscapeHtml(qTitle)}"><span class="ai-sig-name">Chất lượng câu</span>${dotRow(q.level)}<span class="ai-sig-text">${aiEscapeHtml(q.level === 'unknown' ? 'Chưa có dữ liệu' : q.label)}</span></span>
    <span class="ai-sig ai-sig--${r.level}" title="${aiEscapeHtml(r.label)}"><span class="ai-sig-name">Độ tin cậy đáp án</span>${dotRow(r.level)}<span class="ai-sig-text">${aiEscapeHtml({ high: 'Cao', medium: '2 đáp án', low: 'Cần xem lại', review: 'Đang xem lại', unknown: 'Chưa có dữ liệu' }[r.level] || '')}</span></span>
  </div>`;
}

function aiQuestionStateHtml(st, explStatus) {
  if (!st) return '';
  const chips = [];
  if (st.accepts_two_answers) {
    chips.push('<span class="ai-q-state ai-q-state--multi_accepted">Câu này chấp nhận 2 đáp án</span>');
  }
  if (st.question && st.question.code !== 'normal') {
    chips.push(`<span class="ai-q-state ai-q-state--${aiEscapeHtml(st.question.code)}">${aiEscapeHtml(st.question.label)}</span>`);
  }
  if (st.explanation && st.explanation.code !== 'normal') {
    chips.push(`<span class="ai-q-state ai-q-state--expl">${aiEscapeHtml(st.explanation.label)}</span>`);
  } else if (explStatus === 'under_review') {
    chips.push('<span class="ai-q-state ai-q-state--expl">Lời giải đang được xem lại</span>');
  }
  if (st.report) {
    chips.push(`<span class="ai-q-state ai-q-state--report">${aiEscapeHtml(st.report.label)}</span>`);
  }
  return aiSignalsHtml(st.signals) + (chips.length ? `<div class="ai-q-states">${chips.join('')}</div>` : '');
}

async function aiRefreshAttemptStatus() {
  if (!aiChat || !aiChat.attemptId || typeof gestureGetAttempt !== 'function') return null;
  try {
    const st = await gestureGetAttempt(aiChat.attemptId);
    aiChat.questionStates = st.question_states || aiChat.questionStates;
    aiChat.recognitionStatus = st.recognition || null;
    if (st.explanations && Object.keys(st.explanations).length) {
      aiChat.explanations = { ...(st.explanations || {}), ...(aiChat.explanations || {}) };
      Object.keys(aiChat.explanations).forEach(k => { aiChat.explanationStatus = { ...(aiChat.explanationStatus || {}), [k]: 'ready' }; });
    }
    if (st.result && typeof patchLevelScores === 'function') {
      patchLevelScores(aiChat.worldId, aiChat.level, aiChat.attemptId, st.result);
    }
    return st;
  } catch (e) {
    return null; // không chặn người dùng nếu chưa tải được trạng thái
  }
}

function aiOpenRecognitionReportForm(btn) {
  const slot = btn.nextElementSibling;
  if (slot.innerHTML) { slot.innerHTML = ''; return; }
  const qid = btn.dataset.qid;
  const q = (aiChat.questions || []).find(x => String(x.id) === qid);
  const st = (aiChat.questionStates || {})[qid];
  if (!q || !st) { slot.innerHTML = '<div class="ai-report-result warn">Chưa gửi báo lỗi được cho câu này.</div>'; return; }
  const labels = ['A', 'B', 'C', 'D'];
  const typeOptions = Object.keys(AI_REPORT_TYPES).map(k =>
    `<label class="ai-report-opt"><input type="radio" name="rt-${qid}" value="${k}"> ${aiEscapeHtml(AI_REPORT_TYPES[k].label)}</label>`
  ).join('');
  slot.innerHTML = `<div class="ai-report-form">
    <div class="ai-report-label">Em muốn báo điều gì?</div>${typeOptions}
    <div class="ai-report-dyn"></div>
    <div class="ai-report-actions"><button type="button" class="ai-btn ai-report-send" disabled>Gửi báo cáo</button>
    <span class="ai-report-status" aria-live="polite"></span></div></div>`;

  const dyn = slot.querySelector('.ai-report-dyn');
  const sendBtn = slot.querySelector('.ai-report-send');
  slot.querySelectorAll(`input[name="rt-${qid}"]`).forEach(radio => {
    radio.addEventListener('change', () => {
      const spec = AI_REPORT_TYPES[radio.value];
      let pick = '';
      if (spec.options !== 'none') {
        const type = spec.options === 'one' ? 'radio' : 'checkbox';
        pick = `<div class="ai-report-label">${spec.options === 'one' ? 'Theo em đáp án đúng là:' : 'Các phương án cùng đúng:'}</div>` +
          q.options.map((o, i) =>
            `<label class="ai-report-opt"><input type="${type}" name="rp-opt-${qid}" value="${aiEscapeHtml(st.options[i])}"> <b>${labels[i]}.</b> ${aiEscapeHtml(o)}</label>`
          ).join('');
      }
      dyn.innerHTML = `${pick}
        <div class="ai-report-label">${aiEscapeHtml(spec.hint)}${spec.noteRequired ? '' : ' (không bắt buộc)'}</div>
        <textarea class="ai-report-text" rows="3" maxlength="1200"></textarea>`;
      sendBtn.disabled = false;
    });
  });
  sendBtn.addEventListener('click', () => aiSendRecognitionReport(btn, slot, qid, st));
}

async function aiSendRecognitionReport(btn, slot, qid, st) {
  const status = slot.querySelector('.ai-report-status');
  const sendBtn = slot.querySelector('.ai-report-send');
  const typeEl = slot.querySelector(`input[name="rt-${qid}"]:checked`);
  if (!typeEl) { status.textContent = 'Hãy chọn loại vấn đề.'; return; }
  const spec = AI_REPORT_TYPES[typeEl.value];
  const note = (slot.querySelector('.ai-report-text') || { value: '' }).value.trim();
  const oids = Array.from(slot.querySelectorAll(`input[name="rp-opt-${qid}"]:checked`)).map(i => i.value);
  if (spec.options === 'one' && oids.length !== 1) { status.textContent = 'Hãy chọn đúng một phương án.'; return; }
  if (spec.options === 'many' && oids.length < 2) { status.textContent = 'Hãy chọn từ hai phương án trở lên.'; return; }
  if (spec.noteRequired && !note) { status.textContent = 'Hãy chỉ ra đoạn hoặc lỗi cụ thể trong lời giải.'; return; }
  status.textContent = 'Đang gửi...';
  sendBtn.disabled = true;
  try {
    const res = await gestureSendRecognitionReport({
      attempt_id: aiChat.attemptId, qv: st.qv, report_type: typeEl.value, option_oids: oids, note
    });
    const msg = {
      received: 'Đã nhận báo cáo.', reviewing: 'Báo cáo đang được rà soát.',
      accepted: 'Báo cáo của em được ghi nhận. Điểm hiện tại giữ nguyên cho tới khi có quyết định được xác nhận; câu này đang được xem lại.',
      kept: 'Sau khi rà lại, hệ thống giữ kết quả hiện tại cho câu này.',
      needs_human: 'Báo cáo cần người rà soát. Điểm hiện tại giữ nguyên trong lúc chờ.',
      recorded: 'Đã ghi nhận góp ý về cách viết lời giải. Điểm giữ nguyên.',
      pending_error: 'Đã nhận báo cáo. Hệ thống chưa xử lý xong, em không cần gửi lại: báo cáo vẫn được giữ.'
    }[res.status] || 'Đã nhận báo cáo.';
    slot.innerHTML = `<div class="ai-report-result ${res.status === 'accepted' ? 'good' : 'warn'}">${aiEscapeHtml(msg)}</div>`;
    await aiRefreshAttemptStatus();
    if (aiChat.stage === 'CORRECTION') aiRenderCorrection(aiChat.correctionText);
  } catch (e) {
    status.textContent = e.message;
    sendBtn.disabled = false;
  }
}

// Ba trạng thái tách bạch: đang tạo / tạo chưa thành công (thử lại được) / đáp án đang được xem lại (không có lời khẳng định).
function aiExplanationBlockHtml({ q, isCorrect, explanation, explStatus, partial, busy, qState }) {
  const qid = q.id;
  const underReview = explStatus === 'under_review' || (qState && qState.question && qState.question.code === 'answer_under_review')
    || (qState && qState.explanation && qState.explanation.code === 'under_review');
  const retryBtn = (label) => `<button type="button" class="ai-btn ai-expl-btn" data-qid="${qid}">${label}</button>`;
  if (busy) return '<div class="ai-q-feedback pending">Đang tạo lời giải...</div>';
  if (underReview) {
    return `<div class="ai-q-feedback pending">Đáp án của câu này đang được xem lại nên chưa có lời giải khẳng định chắc chắn một đáp án.</div>`
      + (partial ? `<div class="ai-q-feedback bad">${aiMarkdownToHtml(aiBoldExplanationLabels(partial))}</div>` : '');
  }
  if (explanation) {
    const body = `<div class="ai-q-feedback ${isCorrect ? 'ok' : 'bad'}">${aiExplanationHtml(explanation)}</div>`;
    return isCorrect
      ? `<details class="ai-expl-details" open><summary>Bạn đã trả lời chính xác! Giải thích</summary>${body}</details>` : body;
  }
  if (isCorrect) {
    return `<div class="ai-q-feedback ok">Bạn đã trả lời chính xác! ${retryBtn('Xem giải thích')}</div>`;
  }
  return `<div class="ai-q-feedback pending">Tạo lời giải chưa thành công. Điểm của em không bị ảnh hưởng. ${retryBtn('Thử tạo lại lời giải')}</div>`;
}

function aiBindExplanationButtons() {
  aiChatEls.body.querySelectorAll('.ai-expl-btn').forEach(btn => {
    btn.addEventListener('click', () => aiLoadExplanation(Number(btn.dataset.qid)));
  });
}

function aiIsPracticeStage() { return aiChat.stage === 'REMEDIATION_CORRECTION'; }
function aiRerenderExplanationView() {
  if (aiChat.stage === 'REMEDIATION_CORRECTION') aiRenderRemediationCorrection();
  else if (aiChat.stage === 'CORRECTION') aiRenderCorrection(aiChat.correctionText);
}

async function aiLoadExplanation(qid) {
  const practice = aiIsPracticeStage();
  const P = practice ? 'practiceExplanation' : 'explanation';
  const key = String(qid);
  if ((aiChat[P + 'Busy'] || {})[key]) return;       // chống bấm đúp: một tiến trình cho mỗi câu
  aiChat[P + 'Busy'] = { ...(aiChat[P + 'Busy'] || {}), [key]: true };
  aiRerenderExplanationView();
  try {
    const res = await gestureExplainQuestion(aiChat.sessionId, qid, practice);
    if (res.text) {
      const texts = practice ? 'practiceExplanations' : 'explanations';
      aiChat[texts] = { ...(aiChat[texts] || {}), [key]: res.text };
      aiChat[P + 'Status'] = { ...(aiChat[P + 'Status'] || {}), [key]: 'ready' };
    } else {
      aiChat[P + 'Status'] = { ...(aiChat[P + 'Status'] || {}), [key]: res.status };
      if (res.partial) aiChat[P + 'Partial'] = { ...(aiChat[P + 'Partial'] || {}), [key]: res.partial };
    }
    if (!practice) await aiRefreshAttemptStatus();
  } catch (e) {
    aiChat[P + 'Status'] = { ...(aiChat[P + 'Status'] || {}), [key]: 'unavailable' };
  } finally {
    aiChat[P + 'Busy'] = { ...(aiChat[P + 'Busy'] || {}), [key]: false };
    aiRerenderExplanationView();
  }
}

async function aiRegenerateExplanations() {
  const practice = aiIsPracticeStage();
  const btn = document.getElementById('ai-regen-expl-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Đang tạo lại lời giải...'; }
  try {
    const res = await gestureRegenerateExplanations(aiChat.sessionId, practice);
    const P = practice ? 'practiceExplanation' : 'explanation';
    const texts = practice ? 'practiceExplanations' : 'explanations';
    aiChat[texts] = res.explanations || aiChat[texts];
    aiChat[P + 'Status'] = { ...(aiChat[P + 'Status'] || {}), ...(res.explanation_status || {}) };
    aiChat[P + 'Partial'] = { ...(aiChat[P + 'Partial'] || {}), ...(res.explanation_partial || {}) };
    Object.keys(aiChat[texts]).forEach(k => { aiChat[P + 'Status'][k] = 'ready'; });
    if (!practice) await aiRefreshAttemptStatus();
    aiRerenderExplanationView();
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = 'Tạo lại lời giải còn thiếu'; }
    aiRenderSessionAwareError(e, aiRegenerateExplanations);
  }
}

// ---- Bước 4: hai dự đoán điểm (Distinction, Application) + căn cứ ----
// Điểm dự đoán là điều HỌC SINH chọn; máy chủ khóa nguyên giá trị trước khi trả đề mở và tính độ lệch bằng công
// thức xác định. Mỗi kỹ năng bắt đầu "Chưa chọn" (không gửi ngầm 5.0); 0 là điểm hợp lệ.

function aiNewPrediction() {
  return {
    distinction: { status: null, score: null },
    application: { status: null, score: null },
    reasons: [],
    note: ''
  };
}

function aiFmtScore(n) {
  return String(Number(n)).replace('.', ',');
}

// Cả hai kỹ năng BẮT BUỘC có điểm dự đoán do học sinh chủ động chọn bằng thanh kéo (để luôn tính được Confidence và Gap).
function aiPredictionDecided(p) {
  return !!p && p.status === 'scored' && Number.isFinite(p.score);
}

function aiPredictionComplete(pred) {
  return !!pred && aiPredictionDecided(pred.distinction) && aiPredictionDecided(pred.application);
}

function aiPredictionStateText(p) {
  if (p.status === 'scored' && Number.isFinite(p.score)) return `Em dự đoán: ${aiFmtScore(p.score)}/10`;
  return 'Chưa chọn';
}

function aiConfidenceSkillHtml(skill, rubric, pred) {
  const r = rubric[skill.key];
  const p = pred[skill.key];
  const criteria = r.criteria.map(c =>
    `<li><span>${aiEscapeHtml(c.text)}</span><span class="ai-pred-pts">tối đa ${aiFmtScore(c.max)} điểm</span></li>`
  ).join('');
  const active = p.status === 'scored' && Number.isFinite(p.score);
  const openAttr = window.matchMedia && window.matchMedia('(max-width: 640px)').matches ? '' : 'open';
  return `
    <section class="ai-pred" data-skill="${skill.key}">
      <h3 class="ai-pred-title">${aiEscapeHtml(skill.title)}</h3>
      <p class="ai-pred-question">${aiEscapeHtml(skill.question)}</p>
      <details class="ai-pred-rubric" ${openAttr}>
        <summary>Tiêu chí chấm (tổng ${aiFmtScore(r.total)} điểm)</summary>
        <ul>${criteria}</ul>
      </details>
      <div class="ai-pred-controls">
        <label class="ai-pred-label" for="ai-pred-slider-${skill.key}">Kéo thanh để chọn điểm em dự đoán sẽ đạt (thang 10)</label>
        <div class="ai-pred-slider-wrap">
          <input type="range" min="0" max="10" step="0.5" value="${active ? p.score : 0}"
            class="ai-pred-slider${active ? ' is-active' : ''}" id="ai-pred-slider-${skill.key}"
            aria-label="Điểm em dự đoán sẽ đạt trên thang 10 cho ${aiEscapeHtml(skill.title)}"
            aria-valuetext="${active ? aiFmtScore(p.score) + ' trên 10' : 'Chưa chọn'}">
          <div class="ai-pred-slider-scale"><span>0</span><span>5</span><span>10</span></div>
        </div>
      </div>
      <div class="ai-pred-state" id="ai-pred-state-${skill.key}" aria-live="polite"></div>
    </section>
  `;
}

async function aiRenderConfidenceQuestion() {
  aiChat.stage = 'CONFIDENCE';
  aiChat.confidenceSubmitting = false;
  if (!aiChat.prediction) aiChat.prediction = aiNewPrediction();
  aiRenderLoading('Đang tải tiêu chí chấm...');

  let rubric;
  try {
    rubric = await gestureGetConfidenceRubric();
  } catch (e) {
    aiRenderError(e.message || 'Không tải được tiêu chí chấm.', aiRenderConfidenceQuestion);
    return;
  }
  if (!aiChat || aiChat.stage !== 'CONFIDENCE') return; // người dùng đã đóng/chuyển bước trong lúc tải

  const pred = aiChat.prediction;
  ['distinction', 'application'].forEach(k => {
    if (!pred[k] || pred[k].status !== 'scored') pred[k] = { status: null, score: null };
  });
  delete pred.joint;
  const reasonsHtml = rubric.reasons.map(id => `
    <label class="ai-pred-reason">
      <input type="checkbox" value="${aiEscapeHtml(id)}" ${pred.reasons.includes(id) ? 'checked' : ''}>
      <span>${aiEscapeHtml(AI_CONFIDENCE_REASONS[id] || id)}</span>
    </label>
  `).join('');

  aiSetBody(`
    <div class="ai-confidence-wrap">
      <div class="ai-msg ai-confidence-question">${aiEscapeHtml(AI_CONFIDENCE_INTRO)}</div>
      ${AI_CONFIDENCE_SKILLS.map(s => aiConfidenceSkillHtml(s, rubric, pred)).join('')}
      <section class="ai-pred">
        <h3 class="ai-pred-title">Căn cứ của dự đoán (không bắt buộc)</h3>
        <p class="ai-pred-question">Điều gì ảnh hưởng nhiều nhất đến hai mức em vừa dự đoán? Chọn tối đa ${rubric.max_reasons} ý.</p>
        <div class="ai-pred-reasons" id="ai-pred-reasons">${reasonsHtml}</div>
        <label class="ai-pred-label" for="ai-pred-note">Em có thể viết thêm (tùy chọn)</label>
        <textarea class="ai-textarea ai-pred-note" id="ai-pred-note" maxlength="${rubric.max_note_chars}"
          placeholder="Ví dụ: Em khá chắc phần phân biệt nhưng chưa từng tự đặt câu">${aiEscapeHtml(pred.note || '')}</textarea>
        <div class="ai-pred-hint" id="ai-pred-reason-hint" aria-live="polite"></div>
      </section>
    </div>
  `);
  aiSetFooter(`
    <span class="ai-pred-footer-hint" id="ai-pred-footer-hint"></span>
    <button type="button" class="ai-btn" id="ai-submit-confidence-btn" disabled>Xác nhận</button>
  `);

  const syncUi = () => {
    AI_CONFIDENCE_SKILLS.forEach(s => {
      document.getElementById(`ai-pred-state-${s.key}`).textContent = aiPredictionStateText(pred[s.key]);
    });
    const ok = aiPredictionComplete(pred);
    document.getElementById('ai-submit-confidence-btn').disabled = !ok;
    document.getElementById('ai-pred-footer-hint').textContent = ok
      ? 'Sau khi xác nhận, dự đoán sẽ được khóa trước khi em thấy đề.'
      : 'Em cần kéo thanh để chọn điểm dự đoán cho cả hai phần (0 cũng là một dự đoán).';
  };

  AI_CONFIDENCE_SKILLS.forEach(s => {
    const slider = document.getElementById(`ai-pred-slider-${s.key}`);
    // Thanh kéo luôn có một vị trí, nên "chưa chọn" được phân biệt bằng trạng thái: chỉ khi học sinh CHỦ ĐỘNG chạm/kéo/
    // bấm phím thì giá trị mới được ghi. Vị trí mặc định ban đầu (0) KHÔNG phải một lựa chọn và không bao giờ được gửi.
    const choose = () => {
      pred[s.key] = { status: 'scored', score: parseFloat(slider.value) };
      slider.classList.add('is-active');
      slider.setAttribute('aria-valuetext', `${aiFmtScore(pred[s.key].score)} trên 10`);
      syncUi();
      aiDebouncedPersist();
    };
    slider.addEventListener('input', choose);
    slider.addEventListener('pointerup', choose);   // bấm thẳng lên nút kéo (kể cả giữ nguyên vị trí 0) = chủ động chọn
    slider.addEventListener('keydown', (e) => {
      if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'].includes(e.key)) {
        setTimeout(choose, 0);                      // sau khi trình duyệt cập nhật giá trị
      }
    });
  });

  const reasonBoxes = Array.from(document.querySelectorAll('#ai-pred-reasons input[type="checkbox"]'));
  reasonBoxes.forEach(box => {
    box.addEventListener('change', () => {
      const hint = document.getElementById('ai-pred-reason-hint');
      const checked = reasonBoxes.filter(b => b.checked);
      if (checked.length > rubric.max_reasons) {
        box.checked = false;
        hint.textContent = `Chỉ chọn tối đa ${rubric.max_reasons} ý.`;
        return;
      }
      hint.textContent = '';
      pred.reasons = checked.map(b => b.value);
      aiDebouncedPersist();
    });
  });
  document.getElementById('ai-pred-note').addEventListener('input', (e) => {
    pred.note = e.target.value;
    aiDebouncedPersist();
  });

  document.getElementById('ai-submit-confidence-btn').addEventListener('click', aiSubmitConfidence);
  syncUi();
  aiPersistProgress();
}

async function aiSubmitConfidence() {
  if (aiChat.confidenceSubmitting) return; // chống bấm đúp
  if (!aiPredictionComplete(aiChat.prediction)) return;
  aiChat.confidenceSubmitting = true;
  aiRenderLoading('Đang khóa dự đoán và tạo câu hỏi...');
  try {
    const dHistory = typeof loadDistinctionHistory === 'function'
      ? loadDistinctionHistory(aiChat.worldId, aiChat.level) : [];
    const aHistory = typeof loadApplicationHistory === 'function'
      ? loadApplicationHistory(aiChat.worldId, aiChat.level) : [];
    const res = await gestureSubmitConfidence(aiChat.sessionId, aiChat.prediction, dHistory, aHistory);
    if (typeof appendDistinctionHistory === 'function') {
      appendDistinctionHistory(aiChat.worldId, aiChat.level, res.distinction_prompt);
    }
    if (typeof appendApplicationHistory === 'function') {
      appendApplicationHistory(aiChat.worldId, aiChat.level, res.application_prompt);
    }
    aiChat.confidenceSubmitting = false;
    aiRenderOpenEnded(res.distinction_prompt, res.application_prompt);
  } catch (e) {
    aiChat.confidenceSubmitting = false;
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
    const dHistory = typeof loadDistinctionHistory === 'function'
      ? loadDistinctionHistory(aiChat.worldId, aiChat.level) : [];
    const aHistory = typeof loadApplicationHistory === 'function'
      ? loadApplicationHistory(aiChat.worldId, aiChat.level) : [];
    const report = await gestureSubmitOpenEnded(aiChat.sessionId, distinctionAnswer, applicationAnswer, dHistory, aHistory);
    if (report.status === 'pending') { aiRenderOpenGradingPending(report); return; }
    aiChat.report = report;
    aiRenderFinalReport(report);
  } catch (e) {
    aiRenderSessionAwareError(e, () => aiSubmitOpenEnded(distinctionAnswer, applicationAnswer));
  }
}

// Một bài chưa đủ lượt chấm hợp lệ (lượt đối chiếu hoặc lượt ba lỗi): KHÔNG hiện điểm tạm. Bài đã chốt giữ nguyên; bấm
// 'Thử lại' chỉ chấm nốt phần còn thiếu, không cần nộp lại.
function aiRenderOpenGradingPending(res) {
  const names = { distinction: 'Phân biệt (Distinction)', application: 'Vận dụng (Application)' };
  const rows = Object.keys(res.pending || {}).map(k =>
    `<li><strong>${aiEscapeHtml(names[k] || k)}</strong>: ${aiEscapeHtml(res.pending[k].label)}</li>`).join('');
  const done = ['distinction', 'application'].filter(k => res[`${k}_score`] != null).map(k =>
    `<li><strong>${aiEscapeHtml(names[k])}</strong>: đã chấm xong (${aiFmt2(res[`${k}_score`])}/10)</li>`).join('');
  aiSetBody(`
    <div class="ai-msg-system">
      ${aiEscapeHtml(res.message || 'Một phần bài chấm chưa hoàn tất.')}
      <ul>${rows}${done}</ul>
      Điểm tổng, Gap và kết quả đạt/chưa đạt chỉ được chốt khi cả hai bài đã chấm xong.
    </div>`);
  aiSetFooter('<button type="button" class="ai-btn" id="ai-retry-grading-btn">Thử lại</button>');
  document.getElementById('ai-retry-grading-btn').addEventListener('click', async () => {
    aiRenderLoading('Đang chấm nốt phần còn lại...');
    try {
      const dH = typeof loadDistinctionHistory === 'function' ? loadDistinctionHistory(aiChat.worldId, aiChat.level) : [];
      const aH = typeof loadApplicationHistory === 'function' ? loadApplicationHistory(aiChat.worldId, aiChat.level) : [];
      const next = await gestureRetryOpenGrading(aiChat.sessionId, dH, aH);
      if (next.status === 'pending') { aiRenderOpenGradingPending(next); return; }
      aiChat.report = next;
      aiRenderFinalReport(next);
    } catch (e) {
      aiRenderSessionAwareError(e, () => aiRenderOpenGradingPending(res));
    }
  });
}

// ---- Bước 6: báo cáo cuối ----

function aiRubricTableHtml(rows) {
  return `
    <table class="ai-rubric-table">
      <tbody>
        ${(rows || []).map(r => `
          <tr>
            <td>${aiEscapeHtml(r.label)}</td>
            <td class="ai-rubric-score">${aiFmt2(r.score)} / ${aiFmt2(r.max)}</td>
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
    DETECTED: { label: 'Dự đoán cao hơn kết quả', dot: 'amber' },
    UNDERCONFIDENT: { label: 'Em làm tốt hơn em nghĩ', dot: 'amber' },
    CALIBRATED: { label: 'Dự đoán sát kết quả', dot: 'green' },
    MIXED_DEVIATION: { label: 'Tổng thể sát, từng phần còn chênh', dot: 'amber' },
    PARTIAL_DATA: { label: 'Chỉ đối chiếu được một kỹ năng', dot: 'gray' },
    NO_PREDICTION: { label: 'Chưa có dự đoán để đối chiếu', dot: 'gray' },
    AWAITING_RESULT: { label: 'Chờ kết quả (tạm tính)', dot: 'gray' }
  };
  return map[status] || { label: status, dot: 'amber' };
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
      confidence_version: report.confidence_version || 1,
      decision: report.decision || null,
      attempt_id: aiChat.attemptId || null,
      confidence_comparison: report.confidence_comparison || null,
      group_title: aiChat.groupTitle,
      wrong_words: aiChat.wrongWords || [],
      distinction_feedback: report.distinction_feedback,
      application_feedback: report.application_feedback,
      distinction_rubric: report.distinction_rubric,
      application_rubric: report.application_rubric
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

// Mọi điểm, tổng và độ lệch hiển thị đúng 2 chữ số sau dấu phẩy (0,00; 2,00; 1,25); số liệu do máy chủ tính, UI không tự tính lại.
function aiFmt2(n) {
  if (n == null || n === '' || !Number.isFinite(Number(n))) return '—';
  return Number(n).toFixed(2).replace('.', ',');
}

function aiFmtSigned2(n) {
  if (n == null || !Number.isFinite(Number(n))) return '—';
  const v = Number(n);
  return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(2).replace('.', ',');
}

const AI_DECISION_META = {
  PASS: { cls: 'pass', badge: 'QUA MÀN' },
  PASS_WITH_REVIEW: { cls: 'pass', badge: 'QUA MÀN · CÓ GỢI Ý ÔN TẬP' },
  RETRY: { cls: 'retry', badge: 'ÔN THÊM RỒI THỬ LẠI' }
};

const AI_UNDERSTANDING_FALLBACK = {
  WELL_UNDERSTOOD: 'Hiểu tốt', PARTIALLY_UNDERSTOOD: 'Hiểu một phần',
  LIMITED_UNDERSTANDING: 'Đang hiểu một phần', NOT_YET_UNDERSTOOD: 'Đang làm quen'
};

// Hai câu hỏi đầu: "Em dự đoán bao nhiêu?" và "Em thực sự làm được đến đâu?" - Confidence và Gap là MỘT chỉ số chính thức mỗi loại,
// hai dòng kỹ năng chỉ là chi tiết.
function aiConfidenceComparisonHtml(report) {
  const c = report.confidence_comparison;
  const cs = report.confidence_summary;
  if (!c || c.version !== 2 || !cs) return '';
  const names = { distinction: 'Phân biệt', application: 'Vận dụng' };
  const stateText = { compared: '', awaiting_result: 'Chờ kết quả', unsure: 'Chưa có dự đoán riêng' };

  const rows = ['distinction', 'application'].map(k => {
    const s = c.skills[k];
    const d = cs.details[k];
    const predicted = s.status === 'scored' ? aiFmt2(s.predicted) : 'Chưa ước lượng được';
    const actual = s.actual == null ? 'Chờ kết quả' : aiFmt2(s.actual);
    const dev = d.state === 'compared' ? aiFmtSigned2(d.gap) : (stateText[d.state] || '—');
    return `<tr><td>${names[k]}</td><td>${predicted}</td><td>${actual}</td><td>${dev}</td></tr>`;
  }).join('');

  const sourceNote = cs.source === 'joint_direct'
    ? 'Confidence lấy từ dự đoán chung em nhập trước khi làm bài.'
    : (cs.source === 'two_skill_average' ? 'Confidence = trung bình hai dự đoán em chọn cho Phân biệt và Vận dụng.' : '');

  let headline;
  if (cs.available) {
    headline = `
      <div class="ai-conf-main">
        <div class="ai-conf-metric"><div class="ai-score-value">${aiFmt2(cs.confidence)}</div><div class="ai-score-label">CONFIDENCE (em dự đoán)</div></div>
        <div class="ai-conf-metric"><div class="ai-score-value">${aiFmt2(cs.reference_score != null ? cs.reference_score : cs.actual_average)}</div><div class="ai-score-label">${cs.reference_kind === 'overall' ? 'OVERALL (đối chiếu, cả ba kỹ năng)' : 'ĐIỂM ĐỐI CHIẾU (trung bình hai bài)'}</div></div>
        <div class="ai-conf-metric"><div class="ai-score-value">${aiFmtSigned2(cs.gap)}</div><div class="ai-score-label">GAP</div></div>
      </div>
      <p class="ai-pred-note-line"><strong>${aiEscapeHtml(cs.gap_text)}</strong> ${aiEscapeHtml(sourceNote)}</p>`;
  } else if (c.state === 'AWAITING_RESULT') {
    headline = '<p class="ai-pred-note-line">Kết quả đang chờ xác nhận nên Confidence/Gap là tạm tính. Dự đoán gốc của em được giữ nguyên.</p>';
  } else {
    headline = `<p class="ai-pred-note-line"><strong>Chưa đủ dữ liệu tính Confidence/Gap.</strong> Em chưa có đủ dự đoán cho hai bài (hoặc một dự đoán chung) nên hệ thống không tự điền số thay em. Điểm năng lực của em vẫn được tính như bình thường.</p>`;
  }

  const notes = [];
  if (report.calibration && report.calibration.offsetting) notes.push(report.calibration.text);
  ['distinction', 'application'].forEach(k => {
    const s = c.skills[k];
    if (s.state === 'compared' && s.gap > 0 && s.weakest_criterion) {
      notes.push(`Ở lượt này, em dự đoán phần ${names[k].toLowerCase()} cao hơn kết quả ${aiFmt2(s.gap)} điểm. Tiêu chí em mất nhiều điểm nhất là «${s.weakest_criterion}».`);
    }
  });

  let basis = '';
  if ((c.reasons && c.reasons.length) || c.note) {
    const items = (c.reasons || []).map(id => aiEscapeHtml(AI_CONFIDENCE_REASONS[id] || id));
    basis = `<div class="ai-pred-basis"><strong>Em cho biết:</strong> ${items.join(' ')} ${c.note ? `<q>${aiEscapeHtml(c.note)}</q>` : ''}</div>`;
  }
  const typical = cs.typical_deviation != null
    ? `<p class="ai-pred-note-line ai-dim">Độ lệch điển hình (không có hướng, chỉ để tham khảo): ${aiFmt2(cs.typical_deviation)} điểm.</p>` : '';

  return `
    <div class="ai-pred-compare">
      <div class="ai-open-ended-label">EM DỰ ĐOÁN BAO NHIÊU · EM LÀM ĐƯỢC ĐẾN ĐÂU</div>
      ${headline}
      <table class="ai-rubric-table ai-pred-table">
        <thead><tr><th>Kỹ năng</th><th>Em dự đoán</th><th>Kết quả bài làm</th><th>Độ lệch</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      ${notes.map(n => `<p class="ai-pred-note-line">${aiEscapeHtml(n)}</p>`).join('')}
      ${typical}
      ${basis}
    </div>
  `;
}

// Câu hỏi thứ ba: "Vì sao em được qua hoặc cần ôn?" - tách ba thông tin: mức hiểu, mức sát của dự đoán, quyết định qua màn.
function aiDecisionPanelHtml(report) {
  const decision = report.decision || (report.final_result === 'PASS' ? 'PASS' : 'RETRY');
  const info = report.decision_info || null;
  const understanding = report.understanding
    ? report.understanding.text
    : (AI_UNDERSTANDING_FALLBACK[report.understanding_level] || report.understanding_level || '');
  let calibration;
  if (report.calibration) {
    calibration = report.calibration.text;
  } else {
    calibration = aiIllusionMeta(report.illusion_status).label;
  }
  const meta = AI_DECISION_META[decision] || AI_DECISION_META.RETRY;
  const note = info ? info.note : (report.retry_note || '');
  const dot = report.calibration ? (report.calibration.code === 'CLOSE' ? 'green' : report.calibration.code === 'UNKNOWN' ? 'gray' : 'amber')
    : aiIllusionMeta(report.illusion_status).dot;
  return `
    <div class="ai-decision">
      <div class="ai-decision-row"><span class="ai-decision-key">Mức hiểu qua bài làm</span><span>Ở lượt này: <strong>${aiEscapeHtml(understanding)}</strong></span></div>
      <div class="ai-decision-row"><span class="ai-decision-key">Mức sát của dự đoán</span><span><span class="ai-status-dot ai-status-dot--${dot}"></span>${aiEscapeHtml(calibration)}</span></div>
      <div class="ai-decision-row"><span class="ai-decision-key">Quyết định qua màn</span><span><strong>${aiEscapeHtml(meta.badge)}</strong>${note ? ` — ${aiEscapeHtml(note)}` : ''}</span></div>
      <div class="ai-decision-foot">Quyết định qua màn dựa trên điểm kiến thức; Gap chỉ cho em biết mức tự đánh giá của mình.</div>
    </div>`;
}

// Câu hỏi thứ tư: "Từng lượt AI đã cho điểm thế nào?" - điểm gốc từng lượt theo từng tiêu chí + dòng tổng + điểm chốt.
function aiGradingTableHtml(detail, skill) {
  if (!detail) {
    return '<div class="ai-grade-legacy">Lượt này không lưu điểm riêng từng lần chấm.</div>';
  }
  const n = detail.pass_count;
  const third = detail.third_pass;
  const cols = third ? 3 : 2;
  const head = `<tr><th>Tiêu chí</th><th>Tối đa</th><th>AI lượt 1</th><th>AI lượt 2</th>${third ? '<th>AI lượt 3</th>' : ''}<th>Điểm chốt</th></tr>`;
  const cell = (p) => (p ? aiFmt2(p.score) : '—');
  const rows = detail.criteria.map((c, i) => {
    const more = c.passes.map((p, k) => {
      const ev = p.evidence && p.evidence.length ? ` «${aiEscapeHtml(p.evidence[0])}»` : ' (không trích dẫn)';
      return `<div class="ai-grade-pass"><b>Lượt ${k + 1} (${aiFmt2(p.score)}):</b>${ev} — ${aiEscapeHtml(p.reason)}</div>`;
    }).join('');
    const tds = Array.from({ length: cols }, (_, k) => `<td>${cell(c.passes[k])}</td>`).join('');
    return `
      <tr class="ai-grade-row${c.flagged ? ' is-flagged' : ''}">
        <td><button type="button" class="ai-grade-toggle" data-grade-toggle="${skill}-${i}" aria-expanded="false">${aiEscapeHtml(c.label)}${c.flagged ? ' ⚑' : ''}</button></td>
        <td>${aiFmt2(c.max)}</td>${tds}<td><strong>${aiFmt2(c.final)}</strong></td>
      </tr>
      <tr class="ai-grade-more" data-grade-more="${skill}-${i}" hidden><td colspan="${cols + 3}">${more}</td></tr>`;
  }).join('');
  const totals = Array.from({ length: cols }, (_, k) => `<td>${detail.pass_totals[k] != null ? aiFmt2(detail.pass_totals[k]) : '—'}</td>`).join('');
  const maxTotal = detail.criteria.reduce((a, c) => a + c.max, 0);

  const notes = [];
  if (detail.method === 'empty_by_rule') {
    notes.push('Bài để trống: hệ thống chấm 0 theo quy tắc, không gọi AI chấm.');
  } else {
    if (detail.deviation != null) {
      notes.push(`Chênh lệch tổng hai lượt: ${aiFmt2(detail.deviation)} điểm (lượt thứ ba chỉ chạy khi chênh lệch lớn hơn ${aiFmt2(detail.threshold)}).`);
    }
    if (third) {
      notes.push('Đã chấm lượt thứ ba. Điểm chốt mỗi tiêu chí là trung vị của ba lượt rồi cộng lại' +
        (detail.final_differs_from_every_pass ? '; vì vậy tổng chốt khác cả ba tổng riêng của từng lượt.' : '.'));
    } else {
      notes.push('Điểm chốt mỗi tiêu chí là trung bình của hai lượt rồi cộng lại.');
    }
    notes.push('Bấm tên tiêu chí để xem đoạn trích và lý do ngắn của từng lượt. ⚑ nghĩa là hai lượt chưa thống nhất ở tiêu chí đó.');
  }
  return `
    <div class="ai-grade-scroll">
      <table class="ai-grade-table">
        <thead>${head}</thead>
        <tbody>${rows}
          <tr class="ai-grade-total"><td>Tổng</td><td>${aiFmt2(maxTotal)}</td>${totals}<td><strong>${aiFmt2(detail.final_total)}</strong></td></tr>
        </tbody>
      </table>
    </div>
    ${notes.map(t => `<div class="ai-grade-note">${aiEscapeHtml(t)}</div>`).join('')}`;
}

function aiBindGradeTables(root) {
  root.querySelectorAll('[data-grade-toggle]').forEach(btn => {
    btn.addEventListener('click', () => {
      const row = root.querySelector(`[data-grade-more="${btn.dataset.gradeToggle}"]`);
      if (!row) return;
      row.hidden = !row.hidden;
      btn.setAttribute('aria-expanded', String(!row.hidden));
    });
  });
}

function aiScoreGridHtml(report) {
  const cs = report.confidence_summary;
  let confTiles = '';
  if (cs) {
    confTiles = `
        <div class="ai-score-item"><div class="ai-score-value">${cs.available || cs.confidence != null ? aiFmt2(cs.confidence) : '—'}</div><div class="ai-score-label">CONFIDENCE</div></div>
        <div class="ai-score-item">
          <div class="ai-score-value">${cs.available ? aiFmtSigned2(cs.gap) : '—'}</div>
          <div class="ai-score-label"><span class="ai-status-dot ai-status-dot--${report.calibration && report.calibration.code === 'CLOSE' ? 'green' : (cs.available ? 'amber' : 'gray')}"></span>GAP</div>
        </div>`;
  }
  return `
      <div class="ai-score-grid">
        <div class="ai-score-item"><div class="ai-score-value">${aiFmt2(report.recognition)}</div><div class="ai-score-label">RECOGNITION</div></div>
        <div class="ai-score-item"><div class="ai-score-value">${aiFmt2(report.distinction_score)}</div><div class="ai-score-label">DISTINCTION</div></div>
        <div class="ai-score-item"><div class="ai-score-value">${aiFmt2(report.application_score)}</div><div class="ai-score-label">APPLICATION</div></div>
        <div class="ai-score-item"><div class="ai-score-value">${aiFmt2(report.overall)}</div><div class="ai-score-label">OVERALL</div></div>
        ${confTiles}
      </div>`;
}

function aiRenderFinalReport(report) {
  aiChat.stage = 'REPORT';
  aiChat.report = report;
  aiRefreshAttemptStatus(); // lấy điểm hiệu lực mới nhất (nếu đã có quyết định sửa điểm); không chặn hiển thị

  // Lưu ngay để badge dưới level luôn cập nhật dù người dùng thoát kiểu gì
  // sau đó (kể cả đóng tab).
  saveThisAttemptResult(report);

  const decision = report.decision || (report.final_result === 'PASS' ? 'PASS' : 'RETRY');
  const isPass = report.final_result === 'PASS';
  const meta = AI_DECISION_META[decision] || AI_DECISION_META.RETRY;
  const skillBlock = (skill, title, score, rubric, feedback, model) => `
      <div class="ai-feedback-block">
        <div class="ai-open-ended-label">${title} (${aiFmt2(score)}/10)</div>
        ${aiGradingTableHtml(report.grading_detail ? report.grading_detail[skill] : null, skill)}
        ${report.grading_detail ? '' : aiSpreadHtml(report.grading_spread, skill, report.grading) + aiRubricTableHtml(rubric)}
        ${aiMarkdownToHtml(feedback)}
        ${aiModelAnswerHtml(model)}
        <button type="button" class="ai-report-btn" data-report="${skill}">Báo cáo điểm / nhận xét</button>
        <div class="ai-report-slot"></div>
      </div>`;

  aiSetBody(`
    <div class="ai-report">
      <span class="ai-result-badge ${meta.cls}">${meta.badge}</span>

      ${aiScoreGridHtml(report)}

      ${aiConfidenceComparisonHtml(report)}

      ${aiDecisionPanelHtml(report)}

      ${skillBlock('distinction', 'Rubric Phân biệt', report.distinction_score, report.distinction_rubric, report.distinction_feedback, report.distinction_model)}
      ${skillBlock('application', 'Rubric Vận dụng', report.application_score, report.application_rubric, report.application_feedback, report.application_model)}
    </div>
  `);

  aiBindReportButtons();
  aiBindGradeTables(aiChatEls.body);

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
    aiChat.remediationCards = res.cards || [];
    aiChat.practiceQuestions = res.practice_questions;
    aiChat.practiceAnswers = {};
    if (typeof appendRecognitionHistory === 'function') {
      appendRecognitionHistory(aiChat.worldId, aiChat.level, res.practice_questions.map(q => q.question));
    }
    if (typeof setHeaderKeyDisplay === 'function') {
      setHeaderKeyDisplay(res.keys_remaining);
    }
    if (aiChat.remediationCards.length) aiRenderRemediationCards(false); else aiRenderRemediationRecap();
  } catch (e) {
    aiRenderSessionAwareError(e, aiBeginRemediation);
  }
}

// ---- Thẻ ôn có cấu trúc: mục tiêu -> hai ví dụ đối chiếu -> tự thử (gợi ý/lời giải theo thứ tự) ----
// Trạng thái (độc lập / sau gợi ý / còn vướng / xem lời giải trước) do máy chủ suy ra từ dữ liệu đã lưu; giao diện chỉ hiển thị.

const AI_CARD_STATUS_TEXT = {
  independent: 'Làm được độc lập (trong thẻ)',
  after_hint: 'Làm được sau gợi ý',
  stuck: 'Còn vướng ở bước cụ thể',
  solution_first: 'Đã xem lời giải trước khi tự làm (không tính là tự làm được)',
  assisted_start: 'Làm với khung hỗ trợ ngay từ đầu (không tính là làm độc lập)',
  not_assessed: 'Chưa đánh giá được phần giải thích',
  no_data: 'Chưa tự thử'
};

function aiCardTryHtml(card) {
  const st = card.state;
  const done = st.first && st.first.status === 'solid';
  const locked = !!st.first && (done || !!st.after);
  const opts = card.try.options
    ? `<div class="ai-card-options">${card.try.options.map((o, i) =>
      `<label class="ai-report-opt"><input type="radio" name="card-opt-${card.id}" value="${i}" ${locked ? 'disabled' : ''}> ${aiEscapeHtml(o)}</label>`).join('')}</div>`
    : '';
  const placeholder = card.try.options ? 'Dấu hiệu nào trong câu giúp em chọn? (nên viết)' : (card.try.frame || 'Trả lời của em...');
  const frameNote = card.assisted_start && card.try.frame
    ? `<div class="ai-dim">Khung gợi ý: ${aiEscapeHtml(card.try.frame)} (bài làm có khung hỗ trợ, không tính là làm độc lập)</div>` : '';
  const hints = st.hints.map((h, i) => `<div class="ai-card-hint"><b>Gợi ý ${i + 1}:</b> ${aiEscapeHtml(h)}</div>`).join('');
  const feedback = st.after ? st.after.comment : (st.first ? st.first.comment : '');
  const canAfter = !!st.first && st.first.status !== 'solid' && !st.after && st.hints.length > 0;
  const mode = !st.first ? 'first' : (canAfter ? 'after' : '');
  const solution = st.solution ? `<div class="ai-card-solution"><b>Cách làm mẫu:</b> ${aiEscapeHtml(st.solution)}</div>` : '';
  return `
    <div class="ai-card-try" data-card="${card.id}">
      <div class="ai-open-ended-label">Tự thử trước khi xem lời giải</div>
      <div class="ai-msg">${aiMarkdownToHtml(card.try.prompt)}</div>
      ${opts}
      ${frameNote}
      <textarea class="ai-textarea" data-card-text rows="3" placeholder="${aiEscapeHtml(placeholder)}" ${locked ? 'disabled' : ''}></textarea>
      ${hints}
      ${feedback ? `<div class="ai-card-feedback">${aiEscapeHtml(feedback)}</div>` : ''}
      ${solution}
      <div class="ai-card-actions">
        ${mode ? `<button type="button" class="ai-btn" data-card-submit="${mode}">${mode === 'after' ? 'Nộp lại sau gợi ý' : 'Nộp câu tự thử'}</button>` : ''}
        ${st.hints.length < 2 && !done ? `<button type="button" class="ai-btn ai-btn-secondary" data-card-hint="${st.hints.length + 1}">Xem gợi ý ${st.hints.length + 1}</button>` : ''}
        ${!st.solution ? `<button type="button" class="ai-btn ai-btn-secondary" data-card-solution>Xem lời giải${!st.first ? ' (sẽ không tính là em tự làm)' : ''}</button>` : ''}
      </div>
      <div class="ai-card-status ai-card-status--${st.status}">${aiEscapeHtml(AI_CARD_STATUS_TEXT[st.status] || '')}</div>
      <div class="ai-report-status" data-card-msg aria-live="polite"></div>
    </div>`;
}

function aiCardHtml(card) {
  const ex = card.examples.map((e, i) => `
    <div class="ai-card-example">
      <div class="ai-card-example-tag">Ví dụ ${i + 1}</div>
      <div class="ai-card-example-en">${aiEscapeHtml(e.en)}</div>
      <div class="ai-card-example-vi">${aiEscapeHtml(e.vi)}</div>
      <div class="ai-card-example-note">${aiEscapeHtml(e.note)}</div>
    </div>`).join('');
  return `
    <section class="ai-card" data-card-root="${card.id}">
      <div class="ai-open-ended-label">${aiEscapeHtml(card.skill_label)} · em đang luyện điều gì?</div>
      <div class="ai-card-goal"><strong>${aiEscapeHtml(card.goal)}</strong></div>
      <div class="ai-card-why"><b>Vì sao ôn mục này?</b> ${aiEscapeHtml(card.why)}</div>
      <div class="ai-card-examples">${ex}</div>
      <div class="ai-card-notice"><b>Để ý:</b> ${aiEscapeHtml(card.notice)}</div>
      <div class="ai-card-selfcheck"><b>Câu tự kiểm tra em có thể dùng ở bài sau:</b> ${aiEscapeHtml(card.self_check)}</div>
      ${aiCardTryHtml(card)}
    </section>`;
}

async function aiRenderRemediationCards(reload) {
  aiChat.stage = 'REMEDIATION_CARD';
  if (reload || !aiChat.remediationCards) {
    aiRenderLoading('Đang tải thẻ ôn...');
    try {
      const res = await gestureCardsState(aiChat.sessionId);
      aiChat.remediationCards = res.cards || [];
    } catch (e) {
      aiRenderSessionAwareError(e, () => aiRenderRemediationCards(true));
      return;
    }
  }
  if (!aiChat || aiChat.stage !== 'REMEDIATION_CARD') return;
  const cards = aiChat.remediationCards;
  if (!cards.length) { aiRenderRemediationRecap(); return; }
  aiSetBody(`
    <div class="ai-rem-intro">
      <div class="ai-rem-title">Ôn tập trọng tâm</div>
      <div class="ai-rem-sub">Đọc thẻ, tự thử trước khi xem lời giải, rồi luyện ${(aiChat.practiceQuestions || []).length} câu trắc nghiệm và 2 câu viết. Gợi ý và lời giải không ảnh hưởng điểm chính thức.</div>
    </div>
    ${cards.map(aiCardHtml).join('')}
    <div class="ai-dict-hint">Bấm vào một từ hoặc bôi đen cụm từ để tra từ điển Cambridge.</div>
  `);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-cards-continue-btn">Tiếp tục luyện ${(aiChat.practiceQuestions || []).length} câu</button>`);
  document.getElementById('ai-cards-continue-btn').addEventListener('click', aiRenderRemediationMCQList);
  aiBindCards();
  aiPersistProgress();
}

function aiBindCards() {
  aiChatEls.body.querySelectorAll('.ai-card-try').forEach(root => {
    const id = root.dataset.card;
    const msg = root.querySelector('[data-card-msg]');
    const apply = (card) => {
      const i = aiChat.remediationCards.findIndex(c => c.id === id);
      if (i >= 0) aiChat.remediationCards[i] = card;
      const holder = aiChatEls.body.querySelector(`[data-card-root="${id}"]`);
      const keep = holder.querySelector('[data-card-text]');
      const draft = keep ? keep.value : '';
      const tmp = document.createElement('div');
      tmp.innerHTML = aiCardHtml(card);
      holder.replaceWith(tmp.firstElementChild);
      const fresh = aiChatEls.body.querySelector(`[data-card-root="${id}"] [data-card-text]`);
      if (fresh && !fresh.disabled) fresh.value = draft;
      aiBindCards();
    };
    const run = async (fn) => {
      msg.textContent = 'Đang xử lý...';
      root.querySelectorAll('button').forEach(b => { b.disabled = true; });
      try { apply(await fn()); } catch (e) {
        msg.textContent = e.message || 'Chưa xử lý được, em thử lại (câu trả lời đã gửi không bị mất).';
        root.querySelectorAll('button').forEach(b => { b.disabled = false; });
      }
    };
    const submit = root.querySelector('[data-card-submit]');
    if (submit) {
      submit.addEventListener('click', () => {
        const pick = root.querySelector(`input[name="card-opt-${id}"]:checked`);
        const text = root.querySelector('[data-card-text]').value.trim();
        run(async () => {
          const res = await gestureCardAnswer(aiChat.sessionId, id, submit.dataset.cardSubmit, pick ? Number(pick.value) : null, text);
          return res;
        });
      });
    }
    const hint = root.querySelector('[data-card-hint]');
    if (hint) hint.addEventListener('click', () => run(() => gestureCardHint(aiChat.sessionId, id, Number(hint.dataset.cardHint))));
    const sol = root.querySelector('[data-card-solution]');
    if (sol) sol.addEventListener('click', () => run(() => gestureCardSolution(aiChat.sessionId, id)));
  });
}

// Tổng kết: Trước khi ôn / Trong lúc luyện / Ở tình huống mới / Bước tiếp theo. Chỉ hiển thị điều có dữ liệu thật.
function aiRemediationSummaryHtml(summary) {
  if (!summary || !summary.length) return '';
  return `<div class="ai-feedback-block"><div class="ai-open-ended-label">EM ĐÃ SỬA ĐƯỢC GÌ</div>` + summary.map(s => `
    <div class="ai-sum-item">
      <div><b>${aiEscapeHtml(s.skill)}:</b> ${aiEscapeHtml(s.action)}</div>
      <div class="ai-sum-row"><span class="ai-decision-key">Trước khi ôn</span><span>${aiEscapeHtml(s.before)}</span></div>
      <div class="ai-sum-row"><span class="ai-decision-key">Trong lúc luyện</span><span>${aiEscapeHtml(s.during.text)}</span></div>
      <div class="ai-sum-row"><span class="ai-decision-key">Ở tình huống mới</span><span>${aiEscapeHtml(s.new_situation.text)}</span></div>
      <div class="ai-sum-row"><span class="ai-decision-key">Bước tiếp theo</span><span>${aiEscapeHtml(s.next)}</span></div>
    </div>`).join('') + '</div>';
}

function aiRenderRemediationRecap() {
  aiChat.stage = 'REMEDIATION_RECAP';
  const n = aiChat.practiceQuestions.length;
  aiSetBody(`
    <div class="ai-rem-intro">
      <div class="ai-rem-title">Ôn tập trọng tâm</div>
      <div class="ai-rem-sub">Dựa trên những chỗ bạn nhầm ở lượt vừa rồi. Đọc kỹ rồi làm ${n} câu luyện tập và 2 câu viết.</div>
    </div>
    <div class="ai-rem-recap">${aiMarkdownToHtml(aiChat.remediationRecap || '')}</div>
    <div class="ai-dict-hint">Bấm vào một từ hoặc bôi đen cụm từ để tra từ điển Cambridge.</div>
  `);
  aiSetFooter(`<button type="button" class="ai-btn" id="ai-begin-remediation-mcq-btn">Bắt đầu luyện tập (${n} câu)</button>`);
  document.getElementById('ai-begin-remediation-mcq-btn').addEventListener('click', aiRenderRemediationMCQList);
  aiPersistProgress();
}

function aiRenderRemediationMCQList() {
  aiChat.stage = 'REMEDIATION_MCQ';
  aiRenderQuizView({
    questions: aiChat.practiceQuestions,
    answers: aiChat.practiceAnswers,
    onSubmit: aiSubmitRemediationMCQ,
    submitLabel: 'Nộp bài luyện tập'
  });
}

async function aiSubmitRemediationMCQ() {
  aiRenderLoading('Đang chấm bài luyện tập...');
  try {
    const res = await gestureSubmitRemediationMCQ(aiChat.sessionId, aiChat.practiceAnswers);
    aiChat.practiceWrongWords = res.wrong_words || [];
    aiChat.practiceExplanations = res.explanations || {};
    aiChat.practiceExplanationStatus = res.explanation_status || {};
    aiChat.practiceExplanationPartial = res.explanation_partial || {};
    aiChat.practiceExplanationBusy = {};
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
  aiRenderReviewView({
    questions: aiChat.practiceQuestions,
    answers: aiChat.practiceAnswers,
    wrongWords: aiChat.practiceWrongWords || [],
    explanations: aiChat.practiceExplanations || {},
    explanationStatus: aiChat.practiceExplanationStatus || {},
    explanationPartial: aiChat.practiceExplanationPartial || {},
    explanationBusy: aiChat.practiceExplanationBusy || {},
    correctionText: aiChat.remediationCorrectionText || '',
    reportable: false,
    practice: true,
    continueLabel: 'Tiếp tục',
    onContinue: aiRenderRemediationOpenEnded
  });
}

function aiRenderRemediationOpenEnded() {
  aiChat.stage = 'REMEDIATION_OPEN_ENDED';
  aiSetBody(`
    <div class="ai-open-ended-block">
      <div class="ai-open-ended-label">PHÂN BIỆT · luyện tập</div>
      <div class="ai-msg">${aiMarkdownToHtml(aiChat.practiceDistinctionPrompt || '')}</div>
      <textarea class="ai-textarea" id="ai-p-distinction-answer" placeholder="Trả lời của bạn...">${aiEscapeHtml(aiChat.practiceDistinctionDraft || '')}</textarea>
    </div>
    <div class="ai-open-ended-block">
      <div class="ai-open-ended-label">VẬN DỤNG · luyện tập</div>
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
  const total = (aiChat.practiceQuestions || []).length;
  const correct = total - (aiChat.practiceWrongWords || []).length;
  aiSetBody(`
    <div class="ai-report">
      <div class="ai-msg-system">Bạn đã ôn tập xong. Kết quả dưới đây chỉ để tham khảo, KHÔNG tính vào kết quả chính thức.</div>
      <div class="ai-score-grid ai-score-grid--3">
        <div class="ai-score-item"><div class="ai-score-value">${correct}/${total}</div><div class="ai-score-label">TRẮC NGHIỆM</div></div>
        <div class="ai-score-item"><div class="ai-score-value">${aiFmt2(r.distinction_score || 0)}</div><div class="ai-score-label">PHÂN BIỆT</div></div>
        <div class="ai-score-item"><div class="ai-score-value">${aiFmt2(r.application_score || 0)}</div><div class="ai-score-label">VẬN DỤNG</div></div>
      </div>
      <div class="ai-feedback-block">
        <div class="ai-open-ended-label">Rubric Phân biệt (${aiFmt2(r.distinction_score || 0)}/10)</div>
        ${aiSpreadHtml(r.grading_spread, 'distinction')}
        ${aiRubricTableHtml(r.distinction_rubric)}
        ${aiMarkdownToHtml(r.distinction_feedback || '')}
        ${aiModelAnswerHtml(r.distinction_model)}
      </div>
      <div class="ai-feedback-block">
        <div class="ai-open-ended-label">Rubric Vận dụng (${aiFmt2(r.application_score || 0)}/10)</div>
        ${aiSpreadHtml(r.grading_spread, 'application')}
        ${aiRubricTableHtml(r.application_rubric)}
        ${aiMarkdownToHtml(r.application_feedback || '')}
        ${aiModelAnswerHtml(r.application_model)}
      </div>
      ${aiRemediationSummaryHtml(r.summary)}
      <div class="ai-msg-system">Sẵn sàng làm lại bài kiểm tra đầy đủ (20 câu trắc nghiệm + 2 câu Phân biệt/Vận dụng) chưa?</div>
    </div>
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
