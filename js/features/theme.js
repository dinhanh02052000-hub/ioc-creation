// ==== CHẾ ĐỘ SÁNG/TỐI ====
// File này PHẢI load sớm trong <head> (trước khi render nội dung) và áp dụng
// theme NGAY khi chạy (applyTheme(getTheme()) ở cuối file) để tránh hiện
// tượng "chớp" sai theme lúc đầu (FOUC) - không đợi DOMContentLoaded.

const THEME_STORAGE_KEY = 'ui_theme'; // 'dark' | 'light' - sở thích riêng trình duyệt, không đồng bộ tài khoản

function getTheme() {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY) === 'light' ? 'light' : 'dark';
  } catch (e) {
    return 'dark';
  }
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
}

function setTheme(theme) {
  const value = theme === 'light' ? 'light' : 'dark';
  try {
    localStorage.setItem(THEME_STORAGE_KEY, value);
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
  applyTheme(value);
}

function toggleTheme() {
  const next = getTheme() === 'light' ? 'dark' : 'light';
  setTheme(next);
  return next;
}

applyTheme(getTheme());
