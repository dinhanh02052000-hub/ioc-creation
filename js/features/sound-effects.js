// ==== HIỆU ỨNG ÂM THANH KHI BẤM NÚT ====
// Event delegation trên document nên tự áp dụng cho mọi <button>, kể cả nút
// render động sau này. Cấu hình (bật/tắt, âm lượng, chọn âm thanh) chỉnh ở
// Profile, lưu localStorage nên áp dụng chung cho cả world1.html/world2.html.

const SFX_MUTE_KEY = 'sfx_muted'; // sở thích riêng trình duyệt - KHÔNG prefix "ioc_", không đồng bộ tài khoản
const SFX_VOLUME_KEY = 'sfx_volume'; // 0..1
const SFX_CHOICE_KEY = 'sfx_choice_id';
const SFX_DEFAULT_VOLUME = 0.5;
const SFX_DEFAULT_CHOICE = 'click';

const SFX_OPTIONS = [
  { id: 'click', label: 'Click', src: 'assets/audio/sfx/click.mp3' },
  { id: 'button-press', label: 'Button Press', src: 'assets/audio/sfx/button-press.mp3' },
  { id: 'light-switch', label: 'Light Switch', src: 'assets/audio/sfx/light-switch.mp3' },
  { id: 'pop', label: 'Pop', src: 'assets/audio/sfx/pop.mp3' },
];

function isSfxMuted() {
  try {
    return localStorage.getItem(SFX_MUTE_KEY) === '1';
  } catch (e) {
    return false;
  }
}

function setSfxMuted(muted) {
  try {
    localStorage.setItem(SFX_MUTE_KEY, muted ? '1' : '0');
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function getSfxVolume() {
  try {
    const saved = parseFloat(localStorage.getItem(SFX_VOLUME_KEY));
    return Number.isFinite(saved) && saved >= 0 && saved <= 1 ? saved : SFX_DEFAULT_VOLUME;
  } catch (e) {
    return SFX_DEFAULT_VOLUME;
  }
}

function setSfxVolume(value) {
  const clamped = Math.min(1, Math.max(0, value));
  try {
    localStorage.setItem(SFX_VOLUME_KEY, String(clamped));
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function getSfxChoiceId() {
  try {
    const saved = localStorage.getItem(SFX_CHOICE_KEY);
    return SFX_OPTIONS.some(opt => opt.id === saved) ? saved : SFX_DEFAULT_CHOICE;
  } catch (e) {
    return SFX_DEFAULT_CHOICE;
  }
}

function setSfxChoiceId(id) {
  const value = SFX_OPTIONS.some(opt => opt.id === id) ? id : SFX_DEFAULT_CHOICE;
  try {
    localStorage.setItem(SFX_CHOICE_KEY, value);
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

// Tạo 1 Audio() MỚI mỗi lần phát (không dùng chung 1 thẻ <audio>) để bấm
// nhiều nút liên tiếp nhanh không bị cắt ngang tiếng nhau.
function playSfx() {
  if (isSfxMuted()) return;
  const choice = SFX_OPTIONS.find(opt => opt.id === getSfxChoiceId()) || SFX_OPTIONS[0];
  try {
    const audio = new Audio(choice.src);
    audio.volume = getSfxVolume();
    audio.play().catch(() => {});
  } catch (e) {
    // môi trường không hỗ trợ Audio() -> bỏ qua, không crash app
  }
}

function playSfxPreview(id) {
  if (isSfxMuted()) {
    // Cố tình không return: cho nghe thử ngay cả khi đang tắt SFX.
  }
  const choice = SFX_OPTIONS.find(opt => opt.id === id) || SFX_OPTIONS[0];
  try {
    const audio = new Audio(choice.src);
    audio.volume = getSfxVolume();
    audio.play().catch(() => {});
  } catch (e) {
    // bỏ qua
  }
}

function initSoundEffects() {
  document.addEventListener('click', e => {
    const btn = e.target.closest('button');
    if (!btn || btn.disabled) return;
    playSfx();
  });
}

document.addEventListener('DOMContentLoaded', initSoundEffects);
