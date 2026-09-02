// ==== NHẠC NỀN (xuyên suốt index.html, world1.html, world2.html) ====
// Danh sách bản nhạc + chế độ "Mixed" (random) được chọn/chỉnh ở trang
// Profile (index.html, xem js/pages/profile.js) - KHÔNG có nút bật/tắt nổi
// trên trang theo yêu cầu trước đó. Vì đây là site nhiều trang tĩnh (chuyển
// world1/world2 là tải lại toàn bộ trang, không phải SPA) nên KHÔNG THỂ giữ
// tiếng nhạc liền mạch tuyệt đối qua các lần chuyển trang - mỗi trang tự
// phát lại từ đầu bản nhạc đang chọn (hoặc random 1 bản khác nếu đang ở chế
// độ Mixed). Trạng thái BẬT/TẮT + âm lượng + bản nhạc đang chọn lưu ở
// localStorage nên xuyên suốt mọi trang không cần chỉnh lại. Trình duyệt
// luôn chặn tự phát âm thanh khi trang vừa mở (chưa có tương tác) nên sẽ tự
// phát ngay khi người dùng click/gõ phím lần đầu.

const BG_MUSIC_MUTE_KEY = 'bg_music_muted'; // sở thích riêng của trình duyệt - KHÔNG prefix "ioc_", không đồng bộ tài khoản
const BG_MUSIC_VOLUME_KEY = 'bg_music_volume'; // 0..1
const BG_MUSIC_TRACK_KEY = 'bg_music_track_id'; // id trong BG_MUSIC_TRACKS, hoặc 'mixed'
const BG_MUSIC_DEFAULT_VOLUME = 0.35;
const BG_MUSIC_MIXED_ID = 'mixed';

// Danh sách bản nhạc nền thật - chọn ở trang Profile. "Mixed" không phải 1
// file, mà là chế độ tự chọn ngẫu nhiên 1 bản khác mỗi khi bản hiện tại phát
// hết (xem bgMusicHandleTrackEnded()).
const BG_MUSIC_TRACKS = [
  { id: 'default', label: 'Chill mặc định', src: 'assets/audio/backgroundmusic.mp3', available: true },
  { id: 'am-beat', label: 'AM Beat - Martin', src: 'assets/audio/am-beat-martin.mp3', available: true },
  { id: 'call-of-silence', label: 'Call of Silence (Piano) - Attack on Titan', src: 'assets/audio/call-of-silence-piano.mp3', available: true },
  { id: 'golden-hour', label: 'Golden Hour (Piano)', src: 'assets/audio/golden-hour-piano.mp3', available: true },
  { id: 'interstellar', label: 'Interstellar Main Theme - Hans Zimmer', src: 'assets/audio/interstellar-main-theme.mp3', available: true },
  { id: 'we-dont-talk', label: "We Don't Talk Anymore (Instrumental)", src: 'assets/audio/we-dont-talk-anymore.mp3', available: true },
  { id: 'overthinking', label: 'Overthinking - Øneheart', src: 'assets/audio/overthinking-oneheart.mp3', available: true },
  { id: 'zhuo-xue', label: '灼雪 (Zhuó Xuě) - Instrumental', src: 'assets/audio/zhuo-xue-instrumental.mp3', available: true },
];

let bgMusicAudioEl = null;
let bgMusicCurrentPlayingId = null; // bản ĐANG THỰC SỰ PHÁT - khác lựa chọn nếu đang ở chế độ Mixed

function isBgMusicMuted() {
  try {
    return localStorage.getItem(BG_MUSIC_MUTE_KEY) === '1';
  } catch (e) {
    return false;
  }
}

function setBgMusicMuted(muted) {
  try {
    localStorage.setItem(BG_MUSIC_MUTE_KEY, muted ? '1' : '0');
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function getBgMusicVolume() {
  try {
    const saved = parseFloat(localStorage.getItem(BG_MUSIC_VOLUME_KEY));
    return Number.isFinite(saved) && saved >= 0 && saved <= 1 ? saved : BG_MUSIC_DEFAULT_VOLUME;
  } catch (e) {
    return BG_MUSIC_DEFAULT_VOLUME;
  }
}

function setBgMusicVolume(value) {
  const clamped = Math.min(1, Math.max(0, value));
  try {
    localStorage.setItem(BG_MUSIC_VOLUME_KEY, String(clamped));
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
  if (bgMusicAudioEl) bgMusicAudioEl.volume = clamped;
}

function getSelectedTrackId() {
  try {
    const saved = localStorage.getItem(BG_MUSIC_TRACK_KEY);
    if (saved === BG_MUSIC_MIXED_ID) return BG_MUSIC_MIXED_ID;
    return BG_MUSIC_TRACKS.some(track => track.id === saved) ? saved : 'default';
  } catch (e) {
    return 'default';
  }
}

function setSelectedTrackId(id) {
  const value = id === BG_MUSIC_MIXED_ID || BG_MUSIC_TRACKS.some(track => track.id === id) ? id : 'default';
  try {
    localStorage.setItem(BG_MUSIC_TRACK_KEY, value);
  } catch (e) {
    // localStorage không khả dụng -> bỏ qua
  }
}

function pickRandomTrack(excludeId) {
  const pool = BG_MUSIC_TRACKS.filter(track => track.id !== excludeId);
  const list = pool.length ? pool : BG_MUSIC_TRACKS;
  return list[Math.floor(Math.random() * list.length)];
}

// Bản SẼ phát tiếp theo - nếu đang chọn 1 bản cụ thể thì luôn là bản đó, nếu
// đang ở chế độ Mixed thì random 1 bản KHÁC bản vừa phát (đỡ lặp lại liên
// tiếp cùng 1 bài).
function resolveTrackToPlay() {
  const selected = getSelectedTrackId();
  if (selected === BG_MUSIC_MIXED_ID) {
    return pickRandomTrack(bgMusicCurrentPlayingId);
  }
  return BG_MUSIC_TRACKS.find(track => track.id === selected) || BG_MUSIC_TRACKS[0];
}

function bgMusicHandleTrackEnded() {
  // Bản cụ thể (không phải Mixed) đã có audio.loop=true nên KHÔNG bao giờ
  // bắn sự kiện 'ended' - hàm này chỉ thực sự chạy khi đang ở chế độ Mixed.
  bgMusicPlayResolvedTrack();
}

function bgMusicGetAudio() {
  if (!bgMusicAudioEl) {
    bgMusicAudioEl = new Audio();
    bgMusicAudioEl.volume = getBgMusicVolume();
    bgMusicAudioEl.addEventListener('ended', bgMusicHandleTrackEnded);
  }
  return bgMusicAudioEl;
}

function bgMusicPlayResolvedTrack() {
  const track = resolveTrackToPlay();
  const audio = bgMusicGetAudio();
  bgMusicCurrentPlayingId = track.id;
  audio.src = track.src;
  audio.loop = getSelectedTrackId() !== BG_MUSIC_MIXED_ID;
  audio.volume = getBgMusicVolume();
  // play() trả về Promise, bị trình duyệt chặn (chưa có tương tác) sẽ
  // reject - bỏ qua trong im lặng, initBgMusic() đã có fallback đợi click/
  // phím đầu tiên để gọi lại.
  audio.play().catch(() => {});
}

function bgMusicStart() {
  const audio = bgMusicGetAudio();
  audio.volume = getBgMusicVolume();
  if (!audio.src || bgMusicCurrentPlayingId === null) {
    bgMusicPlayResolvedTrack();
    return;
  }
  audio.play().catch(() => {});
}

function bgMusicStop() {
  if (bgMusicAudioEl) bgMusicAudioEl.pause();
}

// Gọi khi người dùng đổi lựa chọn bản nhạc/chế độ Mixed ở Profile - chuyển
// NGAY sang bản mới thay vì đợi bản đang phát kết thúc.
function bgMusicChangeTrack(id) {
  setSelectedTrackId(id);
  if (!isBgMusicMuted()) {
    bgMusicPlayResolvedTrack();
  }
}

function initBgMusic() {
  if (!isBgMusicMuted()) {
    bgMusicStart();
  }

  const onFirstInteraction = () => {
    if (!isBgMusicMuted()) bgMusicStart();
  };
  document.addEventListener('click', onFirstInteraction, { once: true });
  document.addEventListener('keydown', onFirstInteraction, { once: true });
}

document.addEventListener('DOMContentLoaded', initBgMusic);
