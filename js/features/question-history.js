// ==== LỊCH SỬ CÂU HỎI ĐÃ SINH (chống lặp giữa các lần làm) ====
// Lưu vĩnh viễn theo (worldId, level), cố tình KHÔNG wire vào
// resetWorldProgress() - dữ liệu này không được xoá khi "Chơi lại từ đầu"
// hay replay level.
//
// 3 bộ tách riêng (recognition/distinction/application) vì server tránh lặp
// theo từng loại câu hỏi. Bộ recognition dùng chung cho lần đầu, retest, và
// remediation để 3 luồng đó không lặp ý của nhau.

const RECOGNITION_HISTORY_KEY = 'ioc_recognition_history';
const DISTINCTION_HISTORY_KEY = 'ioc_distinction_history';
const APPLICATION_HISTORY_KEY = 'ioc_application_history';

function questionHistoryKey(worldId, level) {
  return `${worldId}:${level}`;
}

function _loadHistoryStore(storageKey) {
  try {
    const data = JSON.parse(localStorage.getItem(storageKey));
    return data && typeof data === 'object' ? data : {};
  } catch (e) {
    return {};
  }
}

function _saveHistoryStore(storageKey, data) {
  try {
    localStorage.setItem(storageKey, JSON.stringify(data));
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function _loadHistoryList(storageKey, worldId, level) {
  const all = _loadHistoryStore(storageKey);
  const list = all[questionHistoryKey(worldId, level)];
  return Array.isArray(list) ? list : [];
}

function _appendHistoryList(storageKey, worldId, level, newTexts) {
  const texts = (Array.isArray(newTexts) ? newTexts : [newTexts]).filter(t => typeof t === 'string' && t.trim());
  if (!texts.length) return;
  const all = _loadHistoryStore(storageKey);
  const key = questionHistoryKey(worldId, level);
  all[key] = [...(Array.isArray(all[key]) ? all[key] : []), ...texts];
  _saveHistoryStore(storageKey, all);
}

function loadRecognitionHistory(worldId, level) {
  return _loadHistoryList(RECOGNITION_HISTORY_KEY, worldId, level);
}

function appendRecognitionHistory(worldId, level, questionTexts) {
  _appendHistoryList(RECOGNITION_HISTORY_KEY, worldId, level, questionTexts);
}

function loadDistinctionHistory(worldId, level) {
  return _loadHistoryList(DISTINCTION_HISTORY_KEY, worldId, level);
}

function appendDistinctionHistory(worldId, level, questionText) {
  _appendHistoryList(DISTINCTION_HISTORY_KEY, worldId, level, questionText);
}

function loadApplicationHistory(worldId, level) {
  return _loadHistoryList(APPLICATION_HISTORY_KEY, worldId, level);
}

function appendApplicationHistory(worldId, level, scenarioText) {
  _appendHistoryList(APPLICATION_HISTORY_KEY, worldId, level, scenarioText);
}
