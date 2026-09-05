// ==== AI GESTURE (client-side orchestrator gọi backend AI) ====
// Không tự vẽ UI — chatbot.js gọi các hàm ở đây, nhận dữ liệu về rồi tự render.
// Toàn bộ logic chấm điểm/quyết định PASS-RETRY nằm ở backend (server/main.py),
// file này chỉ là lớp gọi API mỏng.

// FastAPI (server/main.py) tự phục vụ luôn cả frontend tĩnh (index.html,
// world1.html, world2.html, js/, css/, assets/) VÀ API trên CÙNG 1 origin -
// dùng window.location.origin thay vì hardcode localhost để chạy đúng cả khi
// deploy lên domain thật (Render/Railway...), không cần đổi gì thêm.
const AI_BACKEND_URL = window.location.origin;

async function aiRequest(path, body) {
  // Từ khi có tính năng "key" (giới hạn dùng AI theo tài khoản Google), mọi
  // route AI ở backend đều yêu cầu đăng nhập -> gắn kèm Bearer token nếu có,
  // giống hệt cách authApiRequest() ở auth.js đã làm cho progress save/load.
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
    // Gắn status vào error để caller (chatbot.js) phân biệt được 401 (chưa
    // đăng nhập) / 402 (hết key) với các lỗi khác - đáng tin cậy hơn nhiều so
    // với so khớp chuỗi tiếng Việt.
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }

  return res.json();
}

function gestureStartSession(worldId, level, isRetry = false) {
  return aiRequest('/api/chat/start', { world_id: worldId, level, is_retry: isRetry });
}

// GET thuần, không tốn AI - lấy group_title + danh sách từ mục tiêu thẳng từ
// file KB (dùng cho tính năng "Từ vựng đã học").
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

// recognitionHistory: mảng text các câu đã sinh cho level này từ trước (mọi
// lần: đầu tiên/retest/ôn tập) - server dùng để tránh sinh lại ý đã dùng.
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

// Trang Analysis - 1 lời gọi AI duy nhất mỗi khi có dữ liệu mới, KHÔNG qua
// session (xem server/main.py: /api/analysis/generate không đụng session_store).
function gestureGenerateAnalysis(groups) {
  return aiRequest('/api/analysis/generate', { groups });
}
