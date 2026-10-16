// Bộ icon dùng cho khung điều hướng mới + các trang redesign - vẽ tay dạng
// SVG nội tuyến (path lấy theo bộ Lucide, license MIT) thay vì tải thư viện
// ngoài, giữ đúng quy tắc "không thêm thư viện UI lớn" và nhất quán với các
// icon viết tay sẵn có trong App.js/chatbot.js.
const ICONS = {
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M9 21v-6h6v6"/>',
  map: '<path d="M9 18 3 21V6l6-3 6 3 6-3v15l-6 3-6-3Z"/><path d="M9 3v15"/><path d="M15 6v15"/>',
  chartLine: '<path d="M3 3v18h18"/><path d="M7 15l4-5 4 3 5-7"/>',
  bookOpen: '<path d="M3 5a2 2 0 0 1 2-2h5v16H5a2 2 0 0 0-2 2V5Z"/><path d="M21 5a2 2 0 0 0-2-2h-5v16h5a2 2 0 0 1 2 2V5Z"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-5"/><circle cx="12" cy="8" r="0.15" fill="currentColor" stroke-width="1.2"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 20c1.3-4 4.5-6 8-6s6.7 2 8 6"/>',
  panelLeftClose: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/><path d="M15 10l-2 2 2 2"/>',
  panelLeftOpen: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/><path d="M13 10l2 2-2 2"/>',
  lightbulb: '<path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.2 1 2.3h6c0-1.1.4-1.8 1-2.3A7 7 0 0 0 12 2Z"/>',
  moreHorizontal: '<circle cx="5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="19" cy="12" r="1.3" fill="currentColor"/>',
  x: '<path d="M18 6 6 18"/><path d="M6 6l12 12"/>',
  chevronDown: '<path d="M6 9l6 6 6-6"/>',
  logOut: '<path d="M9 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2 12h2M20 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 13a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V19a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H4a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H10a1.7 1.7 0 0 0 1-1.6V4a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V10a1.7 1.7 0 0 0 1.6 1H20a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.6 1Z"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="M10.8 12.2 20 3"/><path d="M16 7l3 3"/><path d="M19 4l1.5 1.5"/>',
  check: '<path d="M5 12l5 5 9-9"/>',
};

// size mặc định 20px, dùng var(--..) nên tự đổi màu theo nơi đặt (CSS color).
function icon(name, size) {
  const body = ICONS[name];
  if (!body) return '';
  const s = size || 20;
  return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}
