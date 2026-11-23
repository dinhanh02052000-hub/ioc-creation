// ==== AI GESTURE (client-side orchestrator gọi backend AI) ====
// Không tự vẽ UI — chatbot.js gọi các hàm ở đây, nhận dữ liệu về rồi tự render.
// Toàn bộ logic chấm điểm/quyết định PASS-RETRY nằm ở backend (server/main.py),
// file này chỉ là lớp gọi API mỏng.

// FastAPI phục vụ cả frontend tĩnh lẫn API trên cùng 1 origin - dùng
// window.location.origin thay vì hardcode localhost để chạy đúng khi deploy.
const AI_BACKEND_URL = window.location.origin;

async function aiRequest(path, body) {
  // Mọi route AI yêu cầu đăng nhập (giới hạn dùng theo tài khoản) -> gắn kèm
  // Bearer token nếu có, giống authApiRequest() ở auth.js.
  const session = typeof getAuthSession === 'function' ? getAuthSession() : null;
  const headers = { 'Content-Type': 'application/json' };
  if (session) headers['Authorization'] = `Bearer ${session.token}`;

  let res;
  try {
    res = await fetch(`${AI_BACKEND_URL}${path}`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body || {})
    });
  } catch (e) {
    throw new Error('Không kết nối được tới AI backend. Kiểm tra server đã chạy ở ' + AI_BACKEND_URL + ' chưa.');
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const errData = await res.json();
      if (errData && errData.detail) detail = errData.detail;
    } catch (e) {
      // response không phải JSON -> giữ nguyên statusText
    }
    // Gắn status để caller phân biệt 401 (chưa đăng nhập) / 402 (hết key)
    // với lỗi khác, đáng tin cậy hơn so khớp chuỗi thông báo.
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }

  return res.json();
}

function gestureStartSession(worldId, level, isRetry = false, recognitionHistory = []) {
  return aiRequest('/api/chat/start', {
    world_id: worldId, level, is_retry: isRetry, recognition_history: recognitionHistory
  });
}

// GET thuần, không tốn AI - lấy group_title + danh sách từ mục tiêu từ file KB.
async function gestureGetVocab(worldId, level) {
  let res;
  try {
    res = await fetch(`${AI_BACKEND_URL}/api/vocab/${worldId}/${level}`);
  } catch (e) {
    throw new Error('Không kết nối được tới AI backend. Kiểm tra server đã chạy ở ' + AI_BACKEND_URL + ' chưa.');
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const errData = await res.json();
      if (errData && errData.detail) detail = errData.detail;
    } catch (e) {
      // response không phải JSON -> giữ nguyên statusText
    }
    throw new Error(detail);
  }
  return res.json();
}

// recognitionHistory: câu đã sinh cho level này từ trước, server dùng để
// tránh lặp ý.
function gestureBeginRecognition(sessionId, recognitionHistory = []) {
  return aiRequest('/api/chat/begin-recognition', {
    session_id: sessionId,
    recognition_history: recognitionHistory
  });
}

function gestureSubmitRecognition(sessionId, answers, distinctionHistory = [], applicationHistory = []) {
  return aiRequest('/api/chat/submit-recognition', {
    session_id: sessionId,
    answers,
    distinction_history: distinctionHistory,
    application_history: applicationHistory
  });
}

// prediction: { distinction: {status, score}, application: {status, score}, reasons: [], note: '' }.
// Điểm null chỉ đi kèm status 'unsure'; không bao giờ gửi giá trị mặc định thay cho "chưa chọn".
function gestureSubmitConfidence(sessionId, prediction, distinctionHistory = [], applicationHistory = []) {
  const pick = (p) => ({ status: p.status, score: p.status === 'scored' ? p.score : null });
  return aiRequest('/api/chat/submit-confidence', {
    session_id: sessionId,
    predictions: { distinction: pick(prediction.distinction), application: pick(prediction.application) },
    reasons: prediction.reasons || [],
    note: (prediction.note || '').trim() || null,
    distinction_history: distinctionHistory,
    application_history: applicationHistory
  });
}

// GET thuần: rubric đang dùng để chấm (một nguồn với bộ chấm ở máy chủ).
async function gestureGetConfidenceRubric() {
  let res;
  try {
    res = await fetch(`${AI_BACKEND_URL}/api/confidence/rubric`);
  } catch (e) {
    throw new Error('Không kết nối được tới AI backend. Kiểm tra server đã chạy ở ' + AI_BACKEND_URL + ' chưa.');
  }
  if (!res.ok) throw new Error('Không tải được tiêu chí chấm.');
  return res.json();
}

function gestureSubmitOpenEnded(sessionId, distinctionAnswer, applicationAnswer, distinctionHistory = [], applicationHistory = []) {
  return aiRequest('/api/chat/submit-open-ended', {
    session_id: sessionId,
    distinction_answer: distinctionAnswer,
    application_answer: applicationAnswer,
    distinction_history: distinctionHistory,
    application_history: applicationHistory
  });
}

// Soạn lời giải của MỘT câu (câu đúng: 'Xem giải thích'; hoặc tạo lại riêng một câu sai). Không nộp lại bài, không đổi điểm.
function gestureExplainQuestion(sessionId, questionId, practice = false) {
  return aiRequest('/api/chat/explain-question', { session_id: sessionId, question_id: questionId, practice });
}

// Chấm nốt RIÊNG phần còn chờ (lượt đối chiếu hoặc lượt ba); không nộp lại bài.
function gestureRetryOpenGrading(sessionId, distinctionHistory = [], applicationHistory = []) {
  return aiRequest('/api/chat/retry-open-grading', {
    session_id: sessionId, distinction_history: distinctionHistory, application_history: applicationHistory
  });
}

function gestureBeginRemediation(sessionId, recognitionHistory = [], distinctionHistory = [], applicationHistory = []) {
  return aiRequest('/api/chat/begin-remediation', {
    session_id: sessionId,
    recognition_history: recognitionHistory,
    distinction_history: distinctionHistory,
    application_history: applicationHistory
  });
}

function gestureSubmitRemediationMCQ(sessionId, answers) {
  return aiRequest('/api/chat/submit-remediation-mcq', { session_id: sessionId, answers });
}

function gestureSubmitRemediationOpenEnded(sessionId, distinctionAnswer, applicationAnswer) {
  return aiRequest('/api/chat/submit-remediation-open-ended', {
    session_id: sessionId,
    distinction_answer: distinctionAnswer,
    application_answer: applicationAnswer
  });
}

// Trang Analysis - lời gọi AI độc lập, không qua session_store.
function gestureGenerateAnalysis(groups) {
  return aiRequest('/api/analysis/generate', { groups });
}

function gestureSubmitReport(payload) {
  return aiRequest('/api/report', payload);
}

// Báo cáo tự luận theo loại/tiêu chí; gửi lại (mất mạng) không tạo thêm báo cáo, máy chủ trả bản đang có.
function gestureSubmitOpenReport(payload) {
  return aiRequest('/api/report/open', payload);
}


async function aiGetAuth(path) {
  const session = typeof getAuthSession === 'function' ? getAuthSession() : null;
  const headers = {};
  if (session) headers['Authorization'] = `Bearer ${session.token}`;
  let res;
  try {
    res = await fetch(`${AI_BACKEND_URL}${path}`, { headers });
  } catch (e) {
    throw new Error('Không kết nối được tới AI backend.');
  }
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

// Trạng thái hiện hành của lượt làm (điểm hiệu lực, cờ, quyết định, báo cáo của riêng em).
function gestureGetAttempt(attemptId) {
  return aiGetAuth(`/api/attempts/${encodeURIComponent(attemptId)}`);
}

function gestureSendRecognitionReport(payload) {
  return aiRequest('/api/report/recognition', payload);
}

// Tạo lại RIÊNG lời giải còn thiếu: không nộp lại bài, không tính lại lượt dùng.
function gestureRegenerateExplanations(sessionId, practice = false) {
  return aiRequest('/api/chat/regenerate-explanations', { session_id: sessionId, practice });
}


// ---- Thẻ ôn + tự thử (máy chủ giữ trạng thái: gợi ý đã mở, câu trả lời đầu, lời giải đã xem) ----
function gestureCardsState(sessionId) { return aiRequest('/api/chat/remediation/cards-state', { session_id: sessionId }); }
function gestureCardHint(sessionId, cardId, level) { return aiRequest('/api/chat/remediation/card-hint', { session_id: sessionId, card_id: cardId, level }); }
function gestureCardSolution(sessionId, cardId) { return aiRequest('/api/chat/remediation/card-solution', { session_id: sessionId, card_id: cardId }); }
function gestureCardAnswer(sessionId, cardId, phase, choice, text) {
  return aiRequest('/api/chat/remediation/card-answer', { session_id: sessionId, card_id: cardId, phase, choice, text: text || null });
}
