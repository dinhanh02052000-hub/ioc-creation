// ==== COURSE PROGRESS (dùng chung giữa course.js và world1.html/world2.html) ====
// Lưu số level đã hoàn thành của mỗi world vào localStorage, kèm chi tiết kết quả từng level.

const COURSE_PROGRESS_KEY = 'ioc_course_progress';
const LEVEL_RESULTS_KEY = 'ioc_level_results'; // { "world-1": { "1": { accuracy, illusion_status, timestamp }, ... } }

function loadCourseProgress() {
  try {
    const data = JSON.parse(localStorage.getItem(COURSE_PROGRESS_KEY));
    return data && typeof data === 'object' ? data : {};
  } catch (e) {
    return {};
  }
}

function saveCourseProgress(data) {
  try {
    localStorage.setItem(COURSE_PROGRESS_KEY, JSON.stringify(data));
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function loadLevelResults() {
  try {
    const data = JSON.parse(localStorage.getItem(LEVEL_RESULTS_KEY));
    return data && typeof data === 'object' ? data : {};
  } catch (e) {
    return {};
  }
}

function saveLevelResults(data) {
  try {
    localStorage.setItem(LEVEL_RESULTS_KEY, JSON.stringify(data));
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function getWorldCompletedLevels(worldId) {
  const data = loadCourseProgress();
  return Number.isFinite(data[worldId]) ? data[worldId] : 0;
}

function setWorldCompletedLevels(worldId, count) {
  // Set thẳng giá trị (có thể lùi) - dùng cho hành động chủ động như "Chơi
  // lại từ đầu".
  const data = loadCourseProgress();
  data[worldId] = Math.max(0, count);
  saveCourseProgress(data);
}

function advanceWorldCompletedLevels(worldId, count) {
  // Chỉ tiến lên, không bao giờ lùi: replay level 1 (đã có completed=5) và
  // pass lại không được làm completed tụt về 1.
  const data = loadCourseProgress();
  const current = Number.isFinite(data[worldId]) ? data[worldId] : 0;
  data[worldId] = Math.max(current, count);
  saveCourseProgress(data);
}

function getLevelResults(worldId, level) {
  const allResults = loadLevelResults();
  if (!allResults[worldId]) return null;
  const levelStr = String(level);
  return allResults[worldId][levelStr] || null;
}

// Lưu kết quả lần làm bài gần nhất của 1 level, đè lên kết quả cũ (không cộng
// dồn). Dùng chung 1 store cho cả badge bản đồ lẫn trang Analysis để
// resetWorldProgress() xoá đồng thời, không cần đồng bộ 2 nơi.
function setLevelResults(worldId, level, results) {
  const allResults = loadLevelResults();
  const levelStr = String(level);

  if (!allResults[worldId]) {
    allResults[worldId] = {};
  }

  allResults[worldId][levelStr] = {
    accuracy: results.accuracy || null,
    illusion_status: results.illusion_status || null,
    recognition: Number.isFinite(results.recognition) ? results.recognition : null,
    distinction: Number.isFinite(results.distinction) ? results.distinction : null,
    application: Number.isFinite(results.application) ? results.application : null,
    overall: Number.isFinite(results.overall) ? results.overall : null,
    confidence: Number.isFinite(results.confidence) ? results.confidence : null,
    gap: Number.isFinite(results.gap) ? results.gap : null,
    group_title: results.group_title || null,
    wrong_words: Array.isArray(results.wrong_words) ? results.wrong_words : [],
    distinction_feedback: results.distinction_feedback || null,
    application_feedback: results.application_feedback || null,
    timestamp: Date.now()
  };

  saveLevelResults(allResults);
}

// Gom kết quả level của 1 hoặc cả 2 world thành 1 mảng phẳng cho trang
// Analysis. Chỉ lấy bản ghi có đủ breakdown (recognition khác null) để tự
// loại bản ghi cũ thiếu dữ liệu.
function getAllLevelResultsFlat(worldIds) {
  const ids = worldIds || ['world-1', 'world-2'];
  const allResults = loadLevelResults();
  const flat = [];
  ids.forEach(worldId => {
    const worldData = allResults[worldId] || {};
    Object.keys(worldData).forEach(levelStr => {
      const r = worldData[levelStr];
      if (r && r.recognition != null) {
        flat.push({ world_id: worldId, level: parseInt(levelStr, 10), ...r });
      }
    });
  });
  return flat;
}

function resetWorldProgress(worldId) {
  setWorldCompletedLevels(worldId, 0);
  const allResults = loadLevelResults();
  if (allResults[worldId]) {
    allResults[worldId] = {};
    saveLevelResults(allResults);
  }
  if (typeof clearAIChatProgressForWorld === 'function') {
    clearAIChatProgressForWorld(worldId);
  }
}

// ==== TIẾN TRÌNH CHAT AI ĐANG DỞ (dùng cho tính năng resume) ====
// Lưu state của phiên chat chưa đóng báo cáo cuối, để chatbot.js dựng lại
// đúng giai đoạn nếu người dùng ra vào lại level đó.

const AI_CHAT_PROGRESS_KEY = 'ioc_ai_chat_progress';

function aiChatProgressKey(worldId, level) {
  return `${worldId}:${level}`;
}

function loadAllAIChatProgress() {
  try {
    const data = JSON.parse(localStorage.getItem(AI_CHAT_PROGRESS_KEY));
    return data && typeof data === 'object' ? data : {};
  } catch (e) {
    return {};
  }
}

function saveAllAIChatProgress(data) {
  try {
    localStorage.setItem(AI_CHAT_PROGRESS_KEY, JSON.stringify(data));
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function loadAIChatProgress(worldId, level) {
  const all = loadAllAIChatProgress();
  return all[aiChatProgressKey(worldId, level)] || null;
}

function saveAIChatProgress(worldId, level, state) {
  const all = loadAllAIChatProgress();
  all[aiChatProgressKey(worldId, level)] = { ...state, savedAt: Date.now() };
  saveAllAIChatProgress(all);
}

function clearAIChatProgress(worldId, level) {
  const all = loadAllAIChatProgress();
  delete all[aiChatProgressKey(worldId, level)];
  saveAllAIChatProgress(all);
}

function clearAIChatProgressForWorld(worldId) {
  const all = loadAllAIChatProgress();
  const prefix = `${worldId}:`;
  Object.keys(all).forEach(key => {
    if (key.startsWith(prefix)) delete all[key];
  });
  saveAllAIChatProgress(all);
}

// ==== TỪ VỰNG ĐÃ HỌC (vĩnh viễn, KHÔNG bị xoá bởi "Chơi lại từ đầu") ====
// Ghi lại group_title + từ mục tiêu của mỗi level đã PASS ít nhất 1 lần. Là
// nhật ký thành tích lâu dài, cố tình không bị resetWorldProgress() đụng tới.

const VOCAB_LEARNED_KEY = 'ioc_vocab_learned'; // { "world-1": { "1": {group_title, words, timestamp} } }

function loadVocabLearned() {
  try {
    const data = JSON.parse(localStorage.getItem(VOCAB_LEARNED_KEY));
    return data && typeof data === 'object' ? data : {};
  } catch (e) {
    return {};
  }
}

function saveVocabLearnedData(data) {
  try {
    localStorage.setItem(VOCAB_LEARNED_KEY, JSON.stringify(data));
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function hasVocabLearned(worldId, level) {
  const all = loadVocabLearned();
  return !!(all[worldId] && all[worldId][String(level)]);
}

function addVocabLearned(worldId, level, groupTitle, words) {
  const all = loadVocabLearned();
  if (!all[worldId]) all[worldId] = {};
  all[worldId][String(level)] = {
    group_title: groupTitle,
    words: Array.isArray(words) ? words : [],
    timestamp: Date.now()
  };
  saveVocabLearnedData(all);
}

function getVocabLearnedList(worldId) {
  const all = loadVocabLearned();
  const worldData = all[worldId] || {};
  return Object.keys(worldData)
    .map(lv => ({ level: parseInt(lv, 10), ...worldData[lv] }))
    .sort((a, b) => a.level - b.level);
}
