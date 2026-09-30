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

function gestureStartSession(worldId, level, isRetry = false) {
  return aiRequest('/api/chat/start', { world_id: worldId, level, is_retry: isRetry });
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

function gestureSubmitRecognition(sessionId, answers) {
  return aiRequest('/api/chat/submit-recognition', { session_id: sessionId, answers });
}

function gestureSubmitConfidence(sessionId, confidence, distinctionHistory = [], applicationHistory = []) {
  return aiRequest('/api/chat/submit-confidence', {
    session_id: sessionId,
    confidence,
    distinction_history: distinctionHistory,
    application_history: applicationHistory
  });
}

function gestureSubmitOpenEnded(sessionId, distinctionAnswer, applicationAnswer) {
  return aiRequest('/api/chat/submit-open-ended', {
    session_id: sessionId,
    distinction_answer: distinctionAnswer,
    application_answer: applicationAnswer
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
