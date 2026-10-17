// Tra từ điển Cambridge: bấm một từ hoặc bôi đen một cụm từ trong vùng [data-dict]
// để hiện ô tra nhỏ. Mọi lần tra dùng chung MỘT tab Cambridge (không mở tab mới mỗi lần).
// Không nhúng iframe/proxy Cambridge: trang này chặn nhúng và cấm tải qua server.

const CAMBRIDGE_TAB = 'cambridge-lookup';
const DICT_ZONE = '[data-dict]';
// Chỗ người dùng cần thao tác bình thường (đáp án trắc nghiệm đang làm cũng nằm trong nhóm này).
const DICT_SKIP = 'input, textarea, select, button, a, audio, video, [data-no-dict], .ai-q-option:not(.ai-q-option--review)';
const WORD_CHAR = /[\p{L}'’-]/u;

/** Làm sạch đoạn được chọn thành từ khóa; null nếu không hợp lệ. */
function lookupQuery(raw) {
  const text = String(raw)
    .replace(/\(\d+\)/g, ' ')
    .replace(/[“”"«»]/g, ' ')
    .replace(/’/g, "'")
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^[^\p{L}]+|[^\p{L}]+$/gu, '');
  if (!text || !/\p{L}/u.test(text)) return null;
  if (text.length > 80 || text.split(' ').length > 8) return null;
  return text.toLowerCase();
}

function cambridgeUrl(query, dataset) {
  return `https://dictionary.cambridge.org/search/direct/?datasetsearch=${dataset}&q=${encodeURIComponent(query)}`;
}

/** Từ chứa vị trí offset trong chuỗi (giữ nguyên từ có gạch nối/dấu nháy). */
function wordAt(text, offset) {
  let start = Math.min(Math.max(offset, 0), text.length);
  let end = start;
  while (start > 0 && WORD_CHAR.test(text[start - 1])) start--;
  while (end < text.length && WORD_CHAR.test(text[end])) end++;
  const word = text.slice(start, end).replace(/^['’-]+|['’-]+$/g, '');
  return word && /\p{L}/u.test(word) ? word : null;
}

/** Từ nằm dưới điểm bấm (x, y). */
function wordAtPoint(x, y) {
  let node = null;
  let offset = 0;
  if (document.caretPositionFromPoint) {
    const p = document.caretPositionFromPoint(x, y);
    if (p) { node = p.offsetNode; offset = p.offset; }
  } else if (document.caretRangeFromPoint) {
    const r = document.caretRangeFromPoint(x, y);
    if (r) { node = r.startContainer; offset = r.startOffset; }
  }
  if (!node || node.nodeType !== Node.TEXT_NODE) return null;
  return wordAt(node.textContent || '', offset);
}

function dictInZone(node) {
  const el = node instanceof Element ? node : node && node.parentElement;
  return !!(el && el.closest(DICT_ZONE) && !el.closest(DICT_SKIP));
}

/** Mở Cambridge trong MỘT tab dùng chung. Không dùng noopener, nếu không trình duyệt không tìm lại được tab theo tên. */
function openInCambridgeTab(e) {
  closeDictPopup();
  if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return; // để link tự mở tab riêng
  e.preventDefault();
  const tab = window.open(e.currentTarget.href, CAMBRIDGE_TAB);
  if (tab) tab.focus();
}

let dictPopupEl = null;
let dictSelTimer = 0;

function closeDictPopup() {
  if (dictPopupEl) { dictPopupEl.remove(); dictPopupEl = null; }
}

function showDictPopup(raw, rect) {
  const query = raw ? lookupQuery(raw) : null;
  if (!query) return false;
  closeDictPopup();

  const x = Math.min(Math.max(rect.left + rect.width / 2, 150), window.innerWidth - 150);
  const y = rect.bottom + 8 > window.innerHeight - 120 ? rect.bottom - 130 : rect.bottom + 8;

  dictPopupEl = document.createElement('div');
  dictPopupEl.className = 'dict-popup';
  dictPopupEl.setAttribute('role', 'dialog');
  dictPopupEl.setAttribute('aria-label', `Tra từ "${query}"`);
  dictPopupEl.style.left = `${x}px`;
  dictPopupEl.style.top = `${y}px`;
  dictPopupEl.innerHTML = `
    <div class="dict-popup__head">
      <strong class="dict-popup__word"></strong>
      <button type="button" class="dict-popup__close" aria-label="Đóng">×</button>
    </div>
    <div class="dict-popup__actions">
      <a class="dict-popup__btn dict-popup__btn--primary" target="${CAMBRIDGE_TAB}">Anh–Anh ↗</a>
      <a class="dict-popup__btn" target="${CAMBRIDGE_TAB}">Anh–Việt ↗</a>
    </div>
    <p class="dict-popup__note">Dùng lại tab Cambridge đang mở (chưa có thì mở tab mới) · bôi đen để tra cụm từ</p>`;
  dictPopupEl.querySelector('.dict-popup__word').textContent = query; // textContent: không chèn HTML từ trang
  const [en, vi] = dictPopupEl.querySelectorAll('a');
  en.href = cambridgeUrl(query, 'english');
  vi.href = cambridgeUrl(query, 'english-vietnamese');
  en.addEventListener('click', openInCambridgeTab);
  vi.addEventListener('click', openInCambridgeTab);
  dictPopupEl.querySelector('.dict-popup__close').addEventListener('click', closeDictPopup);
  document.body.appendChild(dictPopupEl);
  return true;
}

function showDictFromSelection() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return false;
  const range = sel.getRangeAt(0);
  if (!dictInZone(range.commonAncestorContainer)) return false;
  return showDictPopup(sel.toString(), range.getBoundingClientRect());
}

document.addEventListener('pointerup', (e) => {
  if (dictPopupEl && dictPopupEl.contains(e.target)) return;
  const target = e.target;
  if (!(target instanceof Element) || !target.closest(DICT_ZONE) || target.closest(DICT_SKIP)) {
    closeDictPopup();
    return;
  }
  setTimeout(() => { // đợi trình duyệt cập nhật vùng chọn
    if (showDictFromSelection()) return;
    const word = wordAtPoint(e.clientX, e.clientY);
    if (!showDictPopup(word, { left: e.clientX, bottom: e.clientY + 10, width: 0 })) closeDictPopup();
  }, 0);
});

// Điện thoại: giữ ngón tay để bôi đen cụm từ, vùng chọn đứng yên 450 ms thì hiện ô tra.
document.addEventListener('selectionchange', () => {
  clearTimeout(dictSelTimer);
  dictSelTimer = setTimeout(showDictFromSelection, 450);
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDictPopup(); });
window.addEventListener('scroll', closeDictPopup, true);
window.addEventListener('resize', closeDictPopup);
