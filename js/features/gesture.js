// ==== AI GESTURE (client-side orchestrator gọi backend AI) ====
// Không tự vẽ UI — chatbot.js gọi các hàm ở đây, nhận dữ liệu về rồi tự render.
// Toàn bộ logic chấm điểm/quyết định PASS-RETRY nằm ở backend (server/main.py),
// file này chỉ là lớp gọi API mỏng.

const AI_BACKEND_URL = 'http://localhost:8001';

async function aiRequest(path, body) {
  let res;
  try {
    res = await fetch(`${AI_BACKEND_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
    throw new Error(detail);
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

function gestureBeginRecognition(sessionId) {
  return aiRequest('/api/chat/begin-recognition', { session_id: sessionId });
}

function gestureSubmitRecognition(sessionId, answers) {
  return aiRequest('/api/chat/submit-recognition', { session_id: sessionId, answers });
}

function gestureSubmitConfidence(sessionId, confidence) {
  return aiRequest('/api/chat/submit-confidence', { session_id: sessionId, confidence });
}

function gestureSubmitOpenEnded(sessionId, distinctionAnswer, applicationAnswer) {
  return aiRequest('/api/chat/submit-open-ended', {
    session_id: sessionId,
    distinction_answer: distinctionAnswer,
    application_answer: applicationAnswer
  });
}

function gestureBeginRemediation(sessionId) {
  return aiRequest('/api/chat/begin-remediation', { session_id: sessionId });
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
