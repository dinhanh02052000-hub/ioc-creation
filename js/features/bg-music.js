// ==== NHẠC NỀN (xuyên suốt index.html, world1.html, world2.html) ====
// Site nhiều trang tĩnh (chuyển world1/world2 là tải lại toàn bộ trang,
// không phải SPA) nên không thể giữ tiếng nhạc liền mạch qua các lần chuyển
// trang - mỗi trang tự phát lại từ đầu theo lựa chọn lưu trong localStorage.
// Trình duyệt chặn tự phát khi trang chưa có tương tác, nên phát bù ngay khi
// người dùng click/gõ phím lần đầu.

const BG_MUSIC_MUTE_KEY = 'bg_music_muted'; // sở thích riêng của trình duyệt - KHÔNG prefix "ioc_", không đồng bộ tài khoản
const BG_MUSIC_VOLUME_KEY = 'bg_music_volume'; // 0..1
const BG_MUSIC_TRACK_KEY = 'bg_music_track_id'; // id trong BG_MUSIC_TRACKS, hoặc 'mixed'
const BG_MUSIC_DEFAULT_VOLUME = 0.35;
const BG_MUSIC_MIXED_ID = 'mixed';

// "Mixed" không phải 1 file, mà là chế độ tự random bản khác mỗi khi bản
// hiện tại phát hết (xem bgMusicHandleTrackEnded()).
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

// Ở chế độ Mixed, loại trừ bản vừa phát để tránh lặp lại liên tiếp.
function resolveTrackToPlay() {
  const selected = getSelectedTrackId();
  if (selected === BG_MUSIC_MIXED_ID) {
    return pickRandomTrack(bgMusicCurrentPlayingId);
  }
  return BG_MUSIC_TRACKS.find(track => track.id === selected) || BG_MUSIC_TRACKS[0];
}

function bgMusicHandleTrackEnded() {
  // audio.loop=true khi phát 1 bản cụ thể nên 'ended' chỉ bắn khi ở chế độ Mixed.
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
  // Bị trình duyệt chặn autoplay sẽ reject - bỏ qua, initBgMusic() đã có
  // fallback đợi tương tác đầu tiên để gọi lại.
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

// Chuyển ngay sang bản mới thay vì đợi bản đang phát kết thúc.
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
