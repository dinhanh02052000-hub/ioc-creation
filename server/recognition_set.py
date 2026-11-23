"""Sinh và kiểm định bộ 20 câu Recognition chính thức (lần đầu và kiểm tra lại).

Luồng (xem build_recognition_set):
  1. plan_set      : CODE lập kế hoạch đếm được cho 20 vị trí (từ đáp án, mức khó, chủ đề,
                     kiểu cấu trúc, tập từ trong 4 lựa chọn). Đây là yêu cầu giao cho bộ sinh.
  2. generate      : AI viết câu cho các vị trí còn thiếu (lần đầu: cả 20; sau đó chỉ vị trí lỗi).
  3. validate_item : CODE kiểm kiểu dữ liệu, chỗ trống, 4 phương án, thành phần nhóm, đáp án, lộ từ.
  4. find_conflicts: CODE kiểm trùng câu chữ với bộ đang sinh, lịch sử tài khoản, ví dụ KB và
                     câu trong Present Knowledge vừa hiển thị.
  5. blind judge   : AI độc lập (không biết từ mục tiêu / đáp án / mức khó dự kiến) thử điền cả
                     4 phương án, chấm rubric và mức khó. Máy chủ đối chiếu sau.
  6. verify        : AI xác minh lần hai đáp án đã khóa.
  7. select_final  : CODE chọn 20 câu theo ĐÁP ÁN VÀ MỨC KHÓ ĐÃ THẨM ĐỊNH (độ phủ từ chênh <= 1,
                     phân bố khó 6-8-6); câu lệch mức được chuyển sang vị trí còn thiếu cùng từ.
  8. diversity     : AI rà lặp tình huống / dấu hiệu giải trong bộ và với các câu lịch sử liên quan.
  9. finalize      : CODE xáo A/B/C/D sau khi đã khóa đáp án, lưu cố định thứ tự.

Mọi nhận định của AI (cue, câu đối thủ, rubric, mức khó thẩm định) nằm trong meta của câu và
KHÔNG gửi ra giao diện. Toàn bộ hàm kiểm tra là hàm thuần, không gọi mạng, để test được."""

from __future__ import annotations

import logging
import random
from concurrent.futures import ThreadPoolExecutor
import re
import uuid
from difflib import SequenceMatcher

from fastapi import HTTPException

import engine_prompts as ep
from ai_client import AIProviderError, AIRateLimitError
from ai_json import parse_ai_json

logger = logging.getLogger("ioc.recognition_set")

# ---------------------------------------------------------------- cấu hình (một nơi)

SET_SIZE = 20
# Phân bố độ khó dự kiến. Đổi ở đây là đủ (tổng phải bằng SET_SIZE).
DIFFICULTY_DISTRIBUTION = {"easy": 6, "medium": 8, "hard": 6}
DIFFICULTIES = ("easy", "medium", "hard")

# Bộ nhỏ nhất vẫn được phát khi sinh bù mãi không đủ (mỗi câu vẫn phải đạt đủ kiểm tra, trong đó có đúng một chỗ trống).
MIN_SET_SIZE = 18
# Từ vòng sinh thứ PARTIAL_FROM_ROUND+1, đã có >= MIN_SET_SIZE câu đạt thì dừng, không tốn thêm vòng.
PARTIAL_FROM_ROUND = 2
# Hạ độ khó thích ứng: một (từ, mức) bị loại từng ấy lần thì mức đó bị hạ 1 bậc trong mục tiêu của bộ này (hard->medium->easy).
DOWNGRADE_THRESHOLD = 2
MAX_ROUNDS = 5                     # số vòng sinh/sửa tối đa cho một bộ
# Số bản nháp xin cho MỖI vị trí còn thiếu từ vòng sinh thứ hai (vòng đầu đã có 20 vị trí). Cặp từ gần nghĩa
# bị rubric nghiêm loại nhiều, xin dư giúp hội tụ nhanh; câu dư đã đạt được giữ lại trong pool để dùng sau.
OVERGENERATE = 2
# Tốc độ: chia việc cho nhiều lời gọi AI chạy SONG SONG (mỗi lời gọi chỉ xử lý tối đa ngần này câu) thay vì 1 lời gọi
# dài; vòng đầu xin dư vài câu để ít phải làm thêm vòng.
PARALLEL_CHUNK = 7
# Lối thoát có kiểm soát cho nhóm từ gần nghĩa: từ vòng sinh thứ TIE_FROM_ROUND+1, câu mà thẩm định chỉ ra ĐÚNG HAI phương án
# ngang nhau (đáp án thiết kế là một trong hai, mọi tiêu chí chặn khác đạt) được giữ lại làm câu CÓ 2 ĐÁP ÁN ĐƯỢC CHẤP NHẬN
# (chấm theo tập đáp án, hiển thị rõ cho học sinh) thay vì bị loại mãi. Đặt ALLOW_TIE_AS_TWO_ANSWERS = False để tắt.
ALLOW_TIE_AS_TWO_ANSWERS = True
TIE_FROM_ROUND = 2
# Lối thoát cuối: từ vòng WEAK_FROM_ROUND+1, câu mà thẩm định CHỌN ĐÚNG đáp án thiết kế và chỉ bị chê 'chưa đủ dữ kiện để
# phân biệt' (single_best=false, các tiêu chí chặn khác đạt) được nhận, tối đa WEAK_MAX câu mỗi bộ, đánh dấu weak_key để rà sau.
ALLOW_WEAK_KEY_FILL = True
WEAK_FROM_ROUND = 2
WEAK_MAX = 4
FIRST_ROUND_EXTRA = 4
# Một (từ, mức khó) bị rubric/thẩm định loại từng ấy lần thì coi là 'khó đạt' cho cặp đó: không giao lại mức đó cho
# từ đó nữa mà chuyển mức khó sang từ khác (đổi chỗ với một câu đã đạt), giữ nguyên tổng 6-8-6 và độ phủ từ.
BLOCK_THRESHOLD = 6
OVERGENERATE_FEW = 3              # khi chỉ còn <= 3 vị trí (thường là cặp khó nhất) xin dư nhiều hơn
OVERGENERATE_MAX_CANDIDATES = 20
AI_CALL_RETRIES = 2               # thử lại 1 lời gọi khi lỗi nhà cung cấp (không áp dụng rate limit)
JUDGE_OUTPUT_RETRIES = 1          # thử lại riêng lượt thẩm định khi đầu ra thiếu/sai kiểu
DUPLICATE_SIMILARITY_THRESHOLD = 0.88   # nhóm từ cùng chủ đề (vd bằng cấp) cho câu tự nhiên giống khung; trùng ý sâu hơn do AI rà đa dạng
CONTAINMENT_MIN_TOKENS = 5        # câu/ví dụ chứa nguyên văn nhau từ ngần này từ trở lên = trùng
HISTORY_PROMPT_LIMIT = 40         # số câu lịch sử đưa vào prompt sinh (so sánh code dùng toàn bộ)
HISTORY_COMPARE_LIMIT = 800
DIVERSITY_MAX_REMOVALS = 6        # mỗi lần rà đa dạng chỉ loại tối đa ngần này câu
SET_FORMAT = 2                    # bộ do pipeline này tạo (bộ cũ không có trường format)

REASONING = {"generate": "low", "judge": "low", "diversity": "low"}

# Số lượt thẩm định mù cho mỗi câu. 1 = một lượt quyết định (rẻ, nhanh); 2 = thêm lượt đảo thứ tự phương án, CẢ HAI
# phải đạt (nghiêm nhưng gấp đôi token và hay không hội tụ với nhóm từ gần nghĩa).
JUDGE_PASSES = 1
# Tiêu chí CHẶN câu. Các tiêu chí còn lại vẫn bắt buộc đúng kiểu boolean và được lưu trong hồ sơ (cảnh báo) nhưng
# không loại câu, vì chúng làm hầu hết câu của nhóm từ gần nghĩa bị loại.
BLOCKING_CRITERIA = ("scope", "natural", "single_best", "no_leak")
REQUIRED_CRITERIA = (
    "scope", "natural", "single_best", "distractors", "sufficient", "no_leak", "no_assumption",
)
OPTION_VERDICTS = ("best", "defensible", "rejected")
assert sum(DIFFICULTY_DISTRIBUTION.values()) == SET_SIZE


def distribution_for(size: int) -> dict[str, int]:
    """Phân bố độ khó theo kích thước bộ (cùng tỷ lệ 30% dễ / 40% vừa / 30% khó). size=20 trả đúng DIFFICULTY_DISTRIBUTION."""
    if size == SET_SIZE:
        return dict(DIFFICULTY_DISTRIBUTION)
    easy = round(size * DIFFICULTY_DISTRIBUTION["easy"] / SET_SIZE)
    hard = round(size * DIFFICULTY_DISTRIBUTION["hard"] / SET_SIZE)
    return {"easy": easy, "medium": size - easy - hard, "hard": hard}


def min_size_for(size: int) -> int:
    """Số câu tối thiểu vẫn được phát: cùng độ chùng (SET_SIZE - MIN_SET_SIZE) cho mọi kích thước."""
    return max(1, size - (SET_SIZE - MIN_SET_SIZE))

# Kiểu cấu trúc gợi ý (xoay vòng, không quá 2 câu liên tiếp cùng kiểu). Chỉ là gợi ý: nếu không hợp
# với từ đang kiểm tra thì ưu tiên sự tự nhiên.
STRUCTURES = (
    "mệnh đề thời gian/điều kiện đứng đầu (After..., Once..., If..., When...)",
    "câu phủ định hoặc thiếu điều kiện (Without..., ... not ...)",
    "câu bị động",
    "câu có mệnh đề quan hệ (who/which/that)",
    "câu hỏi nhưng VẪN là câu điền từ có đúng một chỗ trống ___ (VD \"Why did the ___ matter so much?\"), không phải câu hỏi kiểu \"Which word...?\"",
    "câu mô tả hiện tượng chung, không gắn tên riêng",
    "câu kể hậu quả/hệ quả (As a result..., which led to...)",
    "câu so sánh (more/less/compared to...)",
    "câu ghép hai mệnh đề bằng liên từ (although/because/since...)",
    "câu mở đầu bằng cụm trạng ngữ (Despite..., Given..., In light of...)",
)

# ---------------------------------------------------------------- chuẩn hóa / từ vựng

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def norm_text(s: str) -> str:
    """Chuẩn hóa hoa/thường + khoảng trắng (dùng để so lựa chọn)."""
    return _WS_RE.sub(" ", str(s).strip()).lower()


def norm_for_similarity(text: str) -> str:
    t = str(text).lower().replace("___", " ")
    t = _PUNCT_RE.sub(" ", t)
    return _WS_RE.sub(" ", t).strip()


def key_variants(key: str) -> list[str]:
    """Các cách viết hợp lệ của 1 từ mục tiêu trong KB, vd 'sea / ocean' -> ['sea', 'ocean'],
    'stressed (out)' -> ['stressed', 'stressed out']. Luôn gồm cả bản gốc đã chuẩn hóa."""
    variants: list[str] = []

    def add(v: str) -> None:
        v = _WS_RE.sub(" ", v).strip()
        if v and v.lower() not in variants:
            variants.append(v.lower())

    add(key)
    for part in re.split(r"\s*/\s*", key):
        part = re.sub(r"<=>.*", "", part)
        part = re.sub(r"\b(sb|sth)\b", "", part)
        add(re.sub(r"\([^)]*\)", "", part))   # bỏ phần tùy chọn trong ngoặc
        add(re.sub(r"[()]", "", part))        # giữ phần tùy chọn
    return variants


def _word_regex(phrase: str) -> re.Pattern:
    body = r"\s+".join(re.escape(tok) for tok in phrase.split())
    return re.compile(rf"(?<![A-Za-z]){body}(?![A-Za-z])", re.IGNORECASE)


def _inflections(word: str) -> list[str]:
    """Biến thể quy tắc đáng tin cậy của 1 từ đơn (chỉ dùng để tự loại khi lộ đáp án)."""
    forms = [word + "s", word + "es", word + "ed", word + "d", word + "ing"]
    if word.endswith("e"):
        forms.append(word[:-1] + "ing")
    if word.endswith("y") and len(word) > 2:
        forms += [word[:-1] + "ies", word[:-1] + "ied"]
    return forms


def leak_matches(sentence: str, targets: list[str], answer: str) -> list[str]:
    """Trả về các từ/cụm mục tiêu xuất hiện NGUYÊN VẸN trong thân câu (ranh giới từ). Với từ đáp án
    còn dò thêm biến thể quy tắc (s/es/ed/d/ing...). Biến thể khó phân xử để AI đánh giá (no_leak)."""
    found: list[str] = []
    for key in targets:
        phrases = list(key_variants(key))
        if key == answer:
            for v in list(phrases):
                if " " not in v:
                    phrases += _inflections(v)
        if any(_word_regex(p).search(sentence) for p in phrases):
            found.append(key)
    return found


# ---------------------------------------------------------------- kiểm tra từng câu (CODE)

def _err(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def check_blank(sentence: str) -> dict | None:
    """Giao diện thay /_{3,}/ bằng ô trống: thống nhất đúng một cụm '___' (3 gạch dưới)."""
    runs = re.findall(r"_+", sentence)
    if not runs:
        return _err("blank_count", "Thiếu chỗ trống ___ trong câu.")
    if len(runs) > 1:
        return _err("blank_count", f"Có {len(runs)} chỗ trống, chỉ được đúng 1.")
    if runs[0] != "___":
        return _err("blank_format", f"Chỗ trống phải là đúng 3 dấu gạch dưới ___, đang là '{runs[0]}'.")
    return None


def _match_target(option: str, targets: dict[str, list[str]]) -> str | None:
    n = norm_text(option)
    for key, variants in targets.items():
        if n == norm_text(key) or n in variants:
            return key
    return None


def _repair_missing_blank(sentence: str, answer: str) -> str:
    """Lỗi hay gặp: bộ sinh viết câu ĐÃ điền sẵn đáp án mà quên chỗ trống. Nếu từ đáp án xuất hiện đúng MỘT lần
    (nguyên văn, có ranh giới từ) thì thay bằng '___': sửa tất định, không đoán. Ngược lại giữ nguyên để báo lỗi."""
    if not isinstance(answer, str) or not answer.strip():
        return sentence
    rx = _word_regex(_WS_RE.sub(" ", answer.strip()))
    if len(rx.findall(sentence)) == 1:
        return rx.sub("___", sentence, count=1)
    return sentence


def validate_item(raw, slot: dict, kb: dict) -> tuple[list[dict], dict | None]:
    """Kiểm 1 câu do bộ sinh trả về. Trả (danh sách lỗi có mã, item chuẩn hóa hoặc None).
    Lỗi gắn đúng câu nên có thể sửa riêng. Không ép kiểu: null/số/đối tượng là lỗi bad_type."""
    if not isinstance(raw, dict):
        return [_err("bad_type", "Câu phải là một đối tượng JSON.")], None
    sentence, options, answer = raw.get("sentence"), raw.get("options"), raw.get("answer")
    if not isinstance(sentence, str) or not sentence.strip():
        return [_err("bad_type", "sentence phải là chuỗi có nội dung.")], None
    if not isinstance(options, list):
        return [_err("bad_type", "options phải là danh sách.")], None
    if not isinstance(answer, str) or not answer.strip():
        return [_err("bad_type", "answer phải là chuỗi có nội dung.")], None
    if any(not isinstance(o, str) or not o.strip() for o in options):
        return [_err("bad_type", "Mọi lựa chọn phải là chuỗi có nội dung (không null/số/rỗng).")], None
    cue = raw.get("cue")
    cue = cue.strip() if isinstance(cue, str) else ""

    sentence = _WS_RE.sub(" ", sentence).strip()
    options = [_WS_RE.sub(" ", o).strip() for o in options]
    errors: list[dict] = []
    if "_" not in sentence:
        sentence = _repair_missing_blank(sentence, answer)

    blank_err = check_blank(sentence)
    if blank_err:
        errors.append(blank_err)

    if len(options) != 4:
        errors.append(_err("options_count", f"Cần đúng 4 lựa chọn, đang có {len(options)}."))
    if len({norm_text(o) for o in options}) != len(options):
        errors.append(_err("options_dup", "Có lựa chọn trùng nhau sau khi chuẩn hóa hoa/thường và khoảng trắng."))

    target_keys = list(kb["target_words"].keys())
    targets = {k: key_variants(k) for k in target_keys}
    n = len(target_keys)
    matched = [_match_target(o, targets) for o in options]
    internal = [m for m in matched if m is not None]
    external_count = len(options) - len(internal)

    if len(options) == 4:
        if len(set(internal)) != len(internal):
            errors.append(_err("options_dup", "Hai lựa chọn cùng là một từ mục tiêu."))
        elif n == 2 and not (len(internal) == 2 and external_count == 2):
            errors.append(_err("composition", "Nhóm 2 từ: cần đủ 2 từ mục tiêu và 2 nhiễu ngoài nhóm."))
        elif n == 3 and not (len(internal) == 3 and external_count == 1):
            errors.append(_err("composition", "Nhóm 3 từ: cần đủ 3 từ mục tiêu và 1 nhiễu ngoài nhóm."))
        elif n == 4 and not (len(internal) == 4):
            errors.append(_err("composition", "Nhóm 4 từ: phải dùng đủ cả 4 từ mục tiêu, không nhiễu ngoài."))
        elif n > 4 and not (len(internal) == 4):
            errors.append(_err("composition", "Nhóm lớn: 4 lựa chọn phải là 4 từ mục tiêu khác nhau trong nhóm."))

    # Đáp án: khớp duy nhất 1 lựa chọn, thuộc nhóm mục tiêu và đúng từ được giao ở kế hoạch.
    answer_norm = norm_text(answer)
    hits = [i for i, o in enumerate(options) if norm_text(o) == answer_norm]
    answer_key = None
    if len(hits) != 1:
        errors.append(_err("answer_missing", "Đáp án phải khớp đúng 1 trong 4 lựa chọn (chép nguyên văn)."))
    else:
        answer_key = matched[hits[0]]
        if answer_key is None:
            errors.append(_err("answer_not_target", "Đáp án phải là một từ mục tiêu của nhóm, không phải nhiễu ngoài."))
        elif slot.get("word") and answer_key != slot["word"]:
            errors.append(_err(
                "answer_mismatch_plan",
                f"Đáp án là '{answer_key}' nhưng vị trí này được giao kiểm tra '{slot['word']}'."))

    if answer_key and "___" in sentence:
        # Chỉ chặn lộ CHÍNH từ đáp án (và biến thể quy tắc). Từ khác trong nhóm xuất hiện trong câu không làm lộ đáp án.
        leaks = leak_matches(sentence, [answer_key], answer_key)
        if leaks:
            errors.append(_err("leak", "Thân câu chứa nguyên văn từ/cụm mục tiêu: " + ", ".join(leaks) + "."))

    if errors:
        return errors, None
    # Từ mục tiêu giữ đúng cách viết người dùng sẽ thấy; chỉ làm sạch khoảng trắng.
    return [], {
        "sentence": sentence, "options": options, "answer": options[hits[0]],
        "word": answer_key, "cue": cue,
    }


# ---------------------------------------------------------------- trùng câu chữ (CODE)

def _similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short.split()) >= CONTAINMENT_MIN_TOKENS and short in long_:
        return True
    sm = SequenceMatcher(None, a, b)
    return (
        sm.real_quick_ratio() >= DUPLICATE_SIMILARITY_THRESHOLD
        and sm.quick_ratio() >= DUPLICATE_SIMILARITY_THRESHOLD
        and sm.ratio() >= DUPLICATE_SIMILARITY_THRESHOLD
    )


def filled_sentence(sentence: str, answer: str) -> str:
    return sentence.replace("___", answer)


def reference_pool(kb: dict, lesson_sentences: list[str] | None) -> list[tuple[str, str]]:
    """(nhãn, câu đã chuẩn hóa) của ví dụ trong KB và câu Present Knowledge vừa hiển thị."""
    pool: list[tuple[str, str]] = []
    for word, info in kb["target_words"].items():
        for ex in info.get("examples") or []:
            if isinstance(ex, str) and ex.strip():
                pool.append(("ví dụ KB", norm_for_similarity(ex)))
    for s in lesson_sentences or []:
        if isinstance(s, str) and s.strip():
            pool.append(("câu trong bài giảng vừa học", norm_for_similarity(s)))
    return pool


def lesson_reference_sentences(lesson) -> list[str]:
    """Các câu tiếng Anh trong bản Present Knowledge thực tế của lượt học (ví dụ + cặp so sánh)."""
    if not isinstance(lesson, dict):
        return []
    out: list[str] = []
    for w in lesson.get("words") or []:
        if isinstance(w, dict) and isinstance(w.get("example_en"), str):
            out.append(w["example_en"])
    contrast = lesson.get("contrast")
    if isinstance(contrast, dict):
        for k in ("sentence_a", "sentence_b"):                 # bài cũ dạng một cặp
            if isinstance(contrast.get(k), str):
                out.append(contrast[k])
        for item in contrast.get("sentences") or []:           # bài mới: mọi từ của nhóm
            if isinstance(item, dict) and isinstance(item.get("sentence"), str):
                out.append(item["sentence"])
    return out


def find_conflicts(
    candidates: list[dict], existing: list[dict], history: list[str], kb: dict,
    lesson_sentences: list[str] | None = None,
) -> dict[int, dict]:
    """Trùng nguyên văn/diễn đạt quá sát. candidates/existing là item đã validate (có sentence+answer).
    Trả {chỉ số trong candidates: lỗi}. Câu thật sự khác nhau nhưng cùng kiểm tra 1 từ KHÔNG bị loại."""
    conflicts: dict[int, dict] = {}
    cand_n = [norm_for_similarity(c["sentence"]) for c in candidates]
    exist_n = [norm_for_similarity(e["sentence"]) for e in existing]
    hist_n = [norm_for_similarity(h) for h in history[-HISTORY_COMPARE_LIMIT:] if isinstance(h, str)]
    refs = reference_pool(kb, lesson_sentences)

    for i, c in enumerate(candidates):
        if not cand_n[i]:
            continue
        for j in range(i):
            if j not in conflicts and _similar(cand_n[i], cand_n[j]):
                conflicts[i] = _err("dup_batch", f"Quá giống một câu khác trong cùng lượt sinh (vị trí {j + 1}).")
                break
        if i in conflicts:
            continue
        if any(_similar(cand_n[i], e) for e in exist_n):
            conflicts[i] = _err("dup_batch", "Quá giống một câu đã được giữ lại trong bộ đang sinh.")
            continue
        if any(_similar(cand_n[i], h) for h in hist_n if h):
            conflicts[i] = _err("dup_history", "Trùng ý với một câu đã phát trước đó cho level này.")
            continue
        filled = norm_for_similarity(filled_sentence(c["sentence"], c.get("answer", "")))
        for label, ref in refs:
            if _similar(filled, ref):
                conflicts[i] = _err("dup_reference", f"Chép hoặc chỉ đổi vài chữ từ {label}.")
                break
    return conflicts


# ---------------------------------------------------------------- kế hoạch (CODE)

def _slot_options(kb: dict, word: str, use_count: dict[str, int], rng: random.Random) -> list[str]:
    targets = list(kb["target_words"].keys())
    others = [w for w in targets if w != word]
    if len(targets) <= 4:
        return [word] + others
    ranked = sorted(others, key=lambda w: (use_count.get(w, 0), rng.random()))
    chosen = ranked[:3]
    for w in chosen:
        use_count[w] = use_count.get(w, 0) + 1
    return [word] + chosen


def _external_needed(n_targets: int) -> int:
    return {2: 2, 3: 1}.get(n_targets, 0)


def make_slot(kb: dict, slot_id: int, word: str, difficulty: str, domain: str, structure: str,
              use_count: dict[str, int], rng: random.Random) -> dict:
    n = len(kb["target_words"])
    return {
        "id": slot_id, "word": word, "difficulty": difficulty,
        "options_words": _slot_options(kb, word, use_count, rng),
        "external_needed": _external_needed(n),
        "domain": domain, "structure": structure,
    }


def plan_set(kb: dict, rng: random.Random | None = None, size: int = SET_SIZE, focus: list[str] | None = None) -> dict:
    """Kế hoạch 20 vị trí: độ phủ từ chênh <= 1, phân bố khó theo DIFFICULTY_DISTRIBUTION, trải đều
    các mức khó giữa các từ, chủ đề khác nhau, kiểu cấu trúc xoay vòng, thứ tự được trộn."""
    rng = rng or random.Random()
    words = list(kb["target_words"].keys())
    k = len(words)
    if k < 2:
        raise ValueError("Nhóm từ phải có ít nhất 2 từ mục tiêu.")
    base, rem = divmod(size, k)
    # focus: từ học sinh hay nhầm (bộ ôn tập) được ưu tiên nhận câu dư; độ phủ vẫn chênh tối đa 1.
    ranked = sorted(words, key=lambda w: (0 if focus and w in focus else 1, rng.random()))
    bonus = set(ranked[:rem])
    word_targets = {w: base + (1 if w in bonus else 0) for w in words}

    # Phân mức khó: từng mức, lần lượt chọn từ đang có ít câu mức đó nhất (và còn chỗ).
    assigned = {w: {d: 0 for d in DIFFICULTIES} for w in words}
    totals = {w: 0 for w in words}
    pairs: list[tuple[str, str]] = []
    dist = distribution_for(size)
    for d in ("hard", "medium", "easy"):
        for _ in range(dist[d]):
            open_words = [w for w in words if totals[w] < word_targets[w]]
            rng.shuffle(open_words)
            w = min(open_words, key=lambda x: (assigned[x][d], totals[x]))
            assigned[w][d] += 1
            totals[w] += 1
            pairs.append((w, d))

    for _ in range(200):  # trộn thứ tự, tránh 3 câu liên tiếp cùng từ đáp án
        rng.shuffle(pairs)
        if all(not (pairs[i][0] == pairs[i + 1][0] == pairs[i + 2][0]) for i in range(len(pairs) - 2)):
            break

    domains = rng.sample(ep.FIELD_DATABASE, size)
    structures: list[str] = []
    while len(structures) < size:
        cycle = list(STRUCTURES)
        rng.shuffle(cycle)
        if structures and cycle[0] == structures[-1]:
            cycle.append(cycle.pop(0))
        structures += cycle
    use_count: dict[str, int] = {}
    slots = [
        make_slot(kb, i + 1, w, d, domains[i], structures[i], use_count, rng)
        for i, (w, d) in enumerate(pairs)
    ]
    return {
        "slots": slots, "word_targets": word_targets,
        "difficulty_targets": dist, "size": size,
    }


# ---------------------------------------------------------------- chọn bộ cuối theo mức khó đã thẩm định

def _max_flow_assign(need_w: dict[str, int], need_d: dict[str, int],
                     supply: dict[tuple[str, str], int]) -> dict[tuple[str, str], int]:
    """Chọn số câu lấy từ mỗi ô (từ, mức) sao cho tổng theo từ <= need_w và theo mức <= need_d,
    tối đa hóa tổng. Luồng cực đại trên đồ thị nhỏ (nguồn -> từ -> ô -> mức -> đích)."""
    words = sorted(need_w)
    diffs = sorted(need_d)
    S, T = "S", "T"
    cap: dict[tuple, int] = {}

    def add(u, v, c):
        cap[(u, v)] = cap.get((u, v), 0) + c
        cap.setdefault((v, u), 0)

    for w in words:
        add(S, ("w", w), need_w[w])
    for (w, d), s in supply.items():
        if s > 0 and w in need_w and d in need_d:
            add(("w", w), ("c", w, d), s)
            add(("c", w, d), ("d", d), s)
    for d in diffs:
        add(("d", d), T, need_d[d])
    adj: dict = {}
    for (u, v) in cap:
        adj.setdefault(u, []).append(v)

    while True:
        parent = {S: None}
        queue = [S]
        while queue and T not in parent:
            u = queue.pop(0)
            for v in adj.get(u, []):
                if v not in parent and cap[(u, v)] > 0:
                    parent[v] = u
                    queue.append(v)
        if T not in parent:
            break
        v, bottleneck = T, 10 ** 9
        while parent[v] is not None:
            bottleneck = min(bottleneck, cap[(parent[v], v)])
            v = parent[v]
        v = T
        while parent[v] is not None:
            cap[(parent[v], v)] -= bottleneck
            cap[(v, parent[v])] += bottleneck
            v = parent[v]

    used: dict[tuple[str, str], int] = {}
    for (w, d), s in supply.items():
        if s > 0 and w in need_w and d in need_d:
            used[(w, d)] = cap[(("c", w, d), ("w", w))]  # lượng đã đẩy qua cạnh ngược
    return used


def partial_items(placed: dict[int, dict], pool: list[dict], plan: dict) -> list[dict]:
    """Ứng viên cho bộ 18-19 câu: các câu đã đặt đúng vị trí + câu đạt còn DƯ trong pool (của từ khác) để lấp chỗ trống,
    ưu tiên từ đang ít câu nhất, tối đa SET_SIZE. Độ phủ từ cho phép lệch hơn ở bộ thiếu (xem check_set_invariants)."""
    ordered = [placed[sl["id"]] for sl in plan["slots"] if sl["id"] in placed]
    used = {id(x) for x in ordered}
    counts: dict[str, int] = {}
    for it in ordered:
        counts[it["word"]] = counts.get(it["word"], 0) + 1
    spare = [it for it in pool if id(it) not in used]
    while spare and len(ordered) < len(plan["slots"]):
        spare.sort(key=lambda it: counts.get(it["word"], 0))
        it = spare.pop(0)
        ordered.append(it)
        counts[it["word"]] = counts.get(it["word"], 0) + 1
    return ordered


def pick_evictions(placed: dict[int, dict], missing: list[dict], blocked: dict[tuple[str, str], int],
                   rng: random.Random) -> list[dict]:
    """Với mỗi vị trí còn thiếu mà (từ, mức) đã bị loại quá nhiều lần: tìm 1 câu đã đạt của TỪ KHÁC (đang ở mức khác)
    để đổi chỗ. Câu bị gỡ sẽ được sinh lại ở mức bị kẹt, còn từ bị kẹt nhận mức của câu bị gỡ. Chỉ đổi khi cả hai
    chiều đều chưa bị 'khó đạt', nên tổng theo từ và theo mức không đổi."""
    chosen: list[dict] = []
    for m in missing:
        word, d = m["word"], m["difficulty"]
        if blocked.get((word, d), 0) < BLOCK_THRESHOLD:
            continue
        cands = [
            it for it in placed.values()
            if it["word"] != word and it["difficulty"] != d and it not in chosen
            and blocked.get((it["word"], d), 0) < BLOCK_THRESHOLD
            and blocked.get((word, it["difficulty"]), 0) < BLOCK_THRESHOLD
        ]
        if cands:
            chosen.append(rng.choice(cands))
    return chosen


def select_final(pool: list[dict], plan: dict, rng: random.Random | None = None,
                 avoid: dict[tuple[str, str], int] | None = None,
                 targets: dict[str, int] | None = None) -> tuple[dict[int, dict], list[dict]]:
    """Gán câu đã thẩm định vào các vị trí của kế hoạch theo (từ đáp án, mức khó THẨM ĐỊNH).
    Trả ({id vị trí: item}, danh sách vị trí còn thiếu kèm từ/mức cần sinh bù).
    Câu lệch mức được giao nhưng đúng từ sẽ được chuyển sang vị trí còn thiếu cùng từ."""
    rng = rng or random.Random()
    slots = plan["slots"]
    unused = list(pool)
    placed: dict[int, dict] = {}

    # Bước 1: khớp đúng (từ, mức).
    leftover_slots = []
    for slot in slots:
        hit = next((it for it in unused if it["word"] == slot["word"] and it["difficulty"] == slot["difficulty"]), None)
        if hit is not None:
            placed[slot["id"]] = hit
            unused.remove(hit)
        else:
            leftover_slots.append(slot)

    # Bước 2: phần còn lại chỉ cần thỏa phân bố theo từ và theo mức khó (luồng cực đại).
    if leftover_slots and unused:
        need_w: dict[str, int] = {}
        need_d: dict[str, int] = {}
        for s in leftover_slots:
            need_w[s["word"]] = need_w.get(s["word"], 0) + 1
            need_d[s["difficulty"]] = need_d.get(s["difficulty"], 0) + 1
        supply: dict[tuple[str, str], int] = {}
        for it in unused:
            key = (it["word"], it["difficulty"])
            supply[key] = supply.get(key, 0) + 1
        used = _max_flow_assign(need_w, need_d, supply)
        chosen: list[dict] = []
        for (w, d), cnt in used.items():
            members = [it for it in unused if it["word"] == w and it["difficulty"] == d][:cnt]
            chosen += members
        for it in chosen:
            unused.remove(it)
        still_open = []
        for slot in leftover_slots:
            it = next((x for x in chosen if x["word"] == slot["word"]), None)
            if it is None:
                still_open.append(slot)
            else:
                placed[slot["id"]] = it
                chosen.remove(it)
        leftover_slots = still_open

    # Phần thiếu: ghép từ còn thiếu với mức còn thiếu (chỉ biên theo từ/mức mới có ý nghĩa).
    missing: list[dict] = []
    if leftover_slots:
        used_diff = {d: 0 for d in DIFFICULTIES}
        for it in placed.values():
            used_diff[it["difficulty"]] += 1
        need_diff: list[str] = []
        for d in DIFFICULTIES:
            need_diff += [d] * max(0, (targets or plan.get("difficulty_targets") or DIFFICULTY_DISTRIBUTION)[d] - used_diff[d])
        # Giữ mức khó của kế hoạch khi mức đó vẫn còn thiếu (và chưa từng bị AI xếp sang mức khác cho từ này);
        # chỉ những vị trí còn lại mới nhận mức khác. Tránh ghép lại (từ, mức) đã nhiều lần bị thẩm định lệch
        # (vd cụm cố định luôn là easy) để vòng sau không lặp đúng lỗi cũ.
        rng.shuffle(need_diff)
        decided: dict[int, str] = {}
        penal = avoid or {}
        # (1) Vị trí mà mức kế hoạch đã bị tránh chọn trước, để chúng được nhường mức khác còn dư;
        # (2) vị trí còn lại giữ mức kế hoạch nếu còn thiếu; (3) phần sót nhận mức ít bị tránh nhất.
        for slot in leftover_slots:
            if penal.get((slot["word"], slot["difficulty"]), 0) > 0 and need_diff:
                d = min(need_diff, key=lambda x: (penal.get((slot["word"], x), 0), x == slot["difficulty"]))
                need_diff.remove(d)
                decided[slot["id"]] = d
        for slot in leftover_slots:
            if slot["id"] not in decided and slot["difficulty"] in need_diff:
                need_diff.remove(slot["difficulty"])
                decided[slot["id"]] = slot["difficulty"]
        for slot in leftover_slots:
            if slot["id"] not in decided and need_diff:
                d = min(need_diff, key=lambda x: penal.get((slot["word"], x), 0))
                need_diff.remove(d)
                decided[slot["id"]] = d
        for slot in leftover_slots:
            if slot["id"] in decided:
                missing.append({**slot, "difficulty": decided[slot["id"]]})
    return placed, missing


# ---------------------------------------------------------------- bất biến của cả bộ (CODE)

def check_set_invariants(questions: list[dict], kb: dict, targets: dict[str, int] | None = None,
                         allow_partial: bool = False, size: int = SET_SIZE) -> list[str]:
    """Điều kiện bắt buộc trước khi phát: đủ SET_SIZE, mỗi câu hợp lệ, độ phủ từ theo ĐÁP ÁN CUỐI
    chênh <= 1, phân bố khó theo mức ĐÃ THẨM ĐỊNH đúng cấu hình. Trả danh sách lỗi (rỗng = đạt)."""
    problems: list[str] = []
    if not allow_partial and len(questions) != size:
        problems.append(f"Bộ có {len(questions)} câu thay vì {size}.")
    if allow_partial and not (min_size_for(size) <= len(questions) <= size):
        problems.append(f"Bộ có {len(questions)} câu, ngoài khoảng {min_size_for(size)}-{size}.")
    words = list(kb["target_words"].keys())
    counts = {w: 0 for w in words}
    diffs = {d: 0 for d in DIFFICULTIES}
    for i, q in enumerate(questions, start=1):
        errs, item = validate_item(
            {"sentence": q.get("question"), "options": q.get("options"),
             "answer": (q.get("options") or [None])[q["correct_index"]] if isinstance(q.get("correct_index"), int)
             and 0 <= q["correct_index"] < len(q.get("options") or []) else None},
            {}, kb,
        )
        if errs:
            problems.append(f"Câu {i}: " + "; ".join(e["code"] for e in errs))
            continue
        counts[item["word"]] += 1
        meta = q.get("meta") or {}
        if meta.get("difficulty") in diffs:
            diffs[meta["difficulty"]] += 1
        else:
            problems.append(f"Câu {i}: thiếu mức khó đã thẩm định.")
    if counts and max(counts.values()) - min(counts.values()) > (3 if allow_partial else 1):
        problems.append(f"Độ phủ từ lệch quá mức cho phép: {counts}.")
    if not allow_partial and diffs != (targets or distribution_for(size)):
        problems.append(f"Phân bố độ khó {diffs} khác mục tiêu {targets or distribution_for(size)}.")
    return problems


def recheck_questions(questions: list[dict], kb: dict, history: list[str],
                      lesson_sentences: list[str] | None) -> list[int]:
    """Kiểm bằng CODE (không gọi AI) lúc sắp phát: chỉ số các câu trùng lịch sử mới nhất / ví dụ KB /
    câu bài giảng, hoặc không còn hợp lệ cấu trúc. Dùng cho bộ đã sinh sẵn nhưng chưa phát."""
    bad: list[int] = []
    items: list[dict | None] = []
    for i, q in enumerate(questions):
        idx = q.get("correct_index")
        opts = q.get("options") or []
        answer = opts[idx] if isinstance(idx, int) and 0 <= idx < len(opts) else None
        errs, item = validate_item({"sentence": q.get("question"), "options": opts, "answer": answer}, {}, kb)
        if errs:
            bad.append(i)
            items.append(None)
        else:
            items.append(item)
    valid = [(i, it) for i, it in enumerate(items) if it is not None]
    conflicts = find_conflicts([it for _, it in valid], [], history, kb, lesson_sentences)
    bad += [valid[ci][0] for ci in conflicts]
    return sorted(set(bad))


# ---------------------------------------------------------------- gọi AI

def _call(ask_fn, prompt: str, role: str, model: str | None = None) -> dict:
    last: Exception | None = None
    for _ in range(1 + AI_CALL_RETRIES):
        try:
            return parse_ai_json(ask_fn(prompt, reasoning_effort=REASONING[role], model=model))
        except AIRateLimitError:
            raise
        except (AIProviderError, ValueError) as e:  # ValueError gồm JSONDecodeError
            last = e
    raise last  # type: ignore[misc]


def _letter_index(letter) -> int | None:
    if not isinstance(letter, str):
        return None
    return {"A": 0, "B": 1, "C": 2, "D": 3}.get(letter.strip().upper())


def _contains_quote(sentence: str, quote) -> bool:
    """Đoạn trích phải xuất hiện NGUYÊN VĂN trong thân câu (không tính chỗ trống). Chỉ chứng minh trích có thật,
    không chứng minh lập luận đúng: việc đánh giá giá trị phân biệt của chi tiết là của AI."""
    if not isinstance(quote, str):
        return False
    q = norm_text(quote.replace("___", " ")).strip(" .,;:!?\"'“”‘’")
    return len(q) >= 2 and q in norm_text(sentence.replace("___", " "))


def evaluate_judgement(row, item: dict, shown: list[str] | None = None, targets: list[str] | None = None,
                       allow_tie: bool = False, allow_weak: bool = False) -> tuple[bool, list[str], dict | None]:
    """Đối chiếu kết quả của MỘT lượt thẩm định mù với câu của bộ sinh.
    shown: thứ tự phương án mà lượt thẩm định thực sự nhìn thấy (lượt đảo thứ tự khác thứ tự gốc).
    Trả (đạt?, lý do, audit). Trường thiếu / sai kiểu / false đều khiến câu chưa đạt; không suy diễn thiếu = đạt.
    Nhãn tổng hay độ tự tin không được ghi đè các tiêu chí. `reasons[0]` bắt đầu bằng 'judge_output' nghĩa là
    đầu ra hỏng về cấu trúc (được thử lại), còn lại là phán quyết về nội dung."""
    shown = shown or item["options"]
    if not isinstance(row, dict):
        return False, ["judge_output: không có kết quả thẩm định cho câu này"], None

    def bad(msg: str):
        return False, [f"judge_output: {msg}"], None

    chosen = _letter_index(row.get("chosen"))
    rival = _letter_index(row.get("rival"))
    criteria = row.get("criteria")
    difficulty = row.get("difficulty")
    if chosen is None or rival is None or rival == chosen or difficulty not in DIFFICULTIES \
            or not isinstance(criteria, dict):
        return bad("thiếu hoặc sai kiểu trường bắt buộc (chosen/rival/criteria/difficulty)")
    missing = [k for k in REQUIRED_CRITERIA if not isinstance(criteria.get(k), bool)]
    if missing:
        return bad(f"tiêu chí thiếu hoặc không phải boolean: {', '.join(missing)}")

    # Kết luận từng phương án (đủ 4 mã duy nhất) và sự nhất quán với kết luận tổng.
    options = row.get("options")
    if not isinstance(options, dict) or set(options) != set("ABCD"):
        return bad("thiếu kết luận cho đủ bốn phương án A/B/C/D")
    verdicts = {}
    for letter in "ABCD":
        o = options[letter]
        if not isinstance(o, dict) or o.get("verdict") not in OPTION_VERDICTS or not isinstance(o.get("note"), str):
            return bad(f"kết luận phương án {letter} sai định dạng")
        verdicts[letter] = o["verdict"]
    bests = [l for l in "ABCD" if verdicts[l] == "best"]
    if bests != ["ABCD"[chosen]] and len(bests) == 1:
        return bad("phương án 'best' không khớp phương án tự chọn")
    if not bests:
        return bad("không có phương án nào được kết luận 'best'")
    if len(bests) > 1 and criteria["single_best"] is True:
        return bad("kết luận tổng (single_best=true) mâu thuẫn với việc có nhiều phương án 'best'")
    if verdicts["ABCD"[rival]] == "best" and len(bests) == 1:
        return bad("phương án cạnh tranh không thể là phương án 'best' duy nhất")

    sentence = item["sentence"]
    if not _contains_quote(sentence, row.get("cue_quote")):
        return bad("cue_quote thiếu hoặc không xuất hiện nguyên văn trong thân câu")
    warnings: list[str] = []
    if not _contains_quote(sentence, row.get("rival_detail_quote")):
        warnings.append("rival_detail_quote không có trong thân câu")
    if not isinstance(row.get("rival_reading"), str) or len(row["rival_reading"].strip()) < 5:
        return bad("thiếu cách hiểu hợp lý nhất của phương án cạnh tranh (rival_reading)")
    kb_ref = row.get("kb_ref")
    if not isinstance(kb_ref, list) or not kb_ref or any(not isinstance(k, str) for k in kb_ref):
        return bad("thiếu tham chiếu kiến thức (kb_ref)")
    if targets is not None:
        known = {norm_text(t) for t in targets}
        if any(norm_text(k) not in known for k in kb_ref):
            warnings.append("kb_ref có từ không thuộc nhóm của level")

    reasons: list[str] = []
    failed = [k for k in BLOCKING_CRITERIA if criteria[k] is not True]
    warnings += [f"tiêu chí không chặn chưa đạt: {k}" for k in REQUIRED_CRITERIA
                 if k not in BLOCKING_CRITERIA and criteria[k] is not True]
    if failed:
        revise = row.get("revise")
        reasons.append(
            "rubric không đạt (" + ", ".join(failed) + ")"
            + (f": {revise.strip()}" if isinstance(revise, str) and revise.strip() else "")
        )
    if len(bests) > 1:
        reasons.append("hai phương án ngang nhau trong chính ngữ cảnh của câu (nhiều phương án 'best')")
    chosen_text = shown[chosen]
    also_correct: list[str] = []
    if allow_tie and len(bests) == 2 and criteria["single_best"] is False:
        best_texts = [shown["ABCD".index(l)] for l in bests]
        only_tie_failed = [k for k in BLOCKING_CRITERIA if criteria[k] is not True] == ["single_best"]
        if item["answer"] in best_texts and only_tie_failed:
            also_correct = [t for t in best_texts if t != item["answer"]]
            chosen_text = item["answer"]
            reasons = []                                   # hai đáp án ngang nhau được chấp nhận làm tập đáp án
    weak = False
    if (allow_weak and not also_correct and chosen_text == item["answer"] and criteria["single_best"] is False
            and [k for k in BLOCKING_CRITERIA if criteria[k] is not True] == ["single_best"]):
        weak = True
        reasons = []                                       # chọn đúng đáp án thiết kế nhưng thiếu dữ kiện: nhận có đánh dấu
    if chosen_text != item["answer"]:
        reasons.append(
            f"AI thẩm định độc lập chọn '{chosen_text}' thay vì đáp án thiết kế "
            f"'{item['answer']}' (dấu hiệu trong câu chưa đủ phân biệt, hoặc nhiễu mạnh hơn đáp án)"
        )
    audit = {
        "chosen": chosen_text,
        "usage": str(row.get("usage") or "")[:200],
        "cue": str(row.get("cue_quote") or "")[:200],
        "rival": shown[rival],
        "rival_reading": str(row.get("rival_reading") or "")[:300],
        "rival_detail_quote": str(row.get("rival_detail_quote") or "")[:200],
        "options": {shown["ABCD".index(l)]: {"verdict": verdicts[l], "note": options[l]["note"][:160]} for l in "ABCD"},
        "criteria": {k: criteria[k] for k in REQUIRED_CRITERIA},
        "difficulty": difficulty,
        "kb_ref": [str(k)[:80] for k in kb_ref][:6],
        "warnings": warnings,
        "also_correct": also_correct,
        "weak_key": weak,
    }
    return (not reasons), reasons, audit


def run_blind_judge(ask_fn, kb: dict, items: list[dict], model: str | None, reverse: bool = False,
                    allow_tie: bool = False, allow_weak: bool = False) -> dict[int, tuple[bool, list[str], dict | None]]:
    """Chia items thành các nhóm nhỏ chạy song song (nhanh hơn một lời gọi dài); gộp kết quả theo chỉ số gốc."""
    if len(items) <= PARALLEL_CHUNK:
        return _run_blind_judge_chunk(ask_fn, kb, items, model, reverse, allow_tie, allow_weak)
    spans = [(i, items[i:i + PARALLEL_CHUNK]) for i in range(0, len(items), PARALLEL_CHUNK)]
    out: dict[int, tuple[bool, list[str], dict | None]] = {}
    with ThreadPoolExecutor(max_workers=len(spans)) as ex:
        futs = [(off, ex.submit(_run_blind_judge_chunk, ask_fn, kb, chunk, model, reverse, allow_tie, allow_weak)) for off, chunk in spans]
        for off, f in futs:
            for j, res in f.result().items():
                out[off + j] = res
    return out


def _run_blind_judge_chunk(ask_fn, kb: dict, items: list[dict], model: str | None, reverse: bool = False,
                           allow_tie: bool = False, allow_weak: bool = False) -> dict[int, tuple[bool, list[str], dict | None]]:
    """MỘT lượt thẩm định mù. Đầu vào CHỈ gồm thân câu + 4 phương án + kiến thức của level: không từ mục tiêu dự
    kiến, đáp án/kết luận của bộ sinh, mức khó dự kiến hay kết quả của lượt kia. reverse=True đảo thứ tự phương án
    (lượt thứ hai nhìn bản đề khác) để hai lượt thực sự độc lập và không cùng thiên lệch vị trí."""
    results: dict[int, tuple[bool, list[str], dict | None]] = {}
    pending = list(range(len(items)))
    kb_text = ep.lesson_kb_text(kb)
    targets = list(kb["target_words"].keys())
    shown_by_i = {i: (list(reversed(items[i]["options"])) if reverse else list(items[i]["options"])) for i in pending}
    for _attempt in range(1 + JUDGE_OUTPUT_RETRIES):
        if not pending:
            break
        payload = [{"id": i + 1, "sentence": items[i]["sentence"], "options": shown_by_i[i]} for i in pending]
        data = _call(ask_fn, ep.assemble(kb_text, ep.recognition_blind_judge_task(payload)), "judge", model)
        rows = {r.get("id"): r for r in (data.get("results") or []) if isinstance(r, dict)}
        still: list[int] = []
        for i in pending:
            ok, reasons, audit = evaluate_judgement(rows.get(i + 1), items[i], shown_by_i[i], targets, allow_tie, allow_weak)
            if reasons and reasons[0].startswith("judge_output"):
                results[i] = (False, reasons, None)
                still.append(i)        # lỗi đầu ra: thử lại lượt thẩm định (hữu hạn), không suy diễn thiếu = đạt
            else:
                results[i] = (ok, reasons, audit)
        pending = still
    return results


def combine_judges(a: tuple[bool, list[str], dict | None], b: tuple[bool, list[str], dict | None],
                   single: bool = False) -> tuple[bool, list[str], dict | None]:
    """Gộp hai lượt thẩm định mù. Chỉ đạt khi CẢ HAI đạt (cùng chọn đáp án thiết kế, đủ tiêu chí). Nếu hai phán đoán
    hợp lệ bất đồng về nội dung thì ghi nhận bất đồng và loại câu để viết lại (không gọi lại cho tới khi 'vừa ý')."""
    (ok_a, ra, au_a), (ok_b, rb, au_b) = a, b
    if single:
        if not ok_a:
            return False, ra, None
        return True, [], {
            "cue": au_a["cue"], "usage": au_a["usage"], "rival": au_a["rival"], "rival_reason": au_a["rival_reading"],
            "criteria": au_a["criteria"], "difficulty": au_a["difficulty"], "difficulty_judges": [au_a["difficulty"]],
            "also_correct": au_a.get("also_correct", []), "weak_key": au_a.get("weak_key", False),
            "judges": [au_a], "agreement": True,
        }
    if ok_a and ok_b:
        level_a, level_b = au_a["difficulty"], au_b["difficulty"]
        easier = min(level_a, level_b, key=DIFFICULTIES.index)     # lệch mức: lấy mức dễ hơn, không nâng khống
        criteria = {k: au_a["criteria"][k] and au_b["criteria"][k] for k in REQUIRED_CRITERIA}
        return True, [], {
            "cue": au_a["cue"], "usage": au_a["usage"], "rival": au_a["rival"], "rival_reason": au_a["rival_reading"],
            "criteria": criteria, "difficulty": easier, "difficulty_judges": [level_a, level_b],
            "judges": [au_a, au_b], "agreement": True,
        }
    reasons: list[str] = []
    for label, ok, r in (("lượt thẩm định 1", ok_a, ra), ("lượt thẩm định 2", ok_b, rb)):
        if not ok:
            reasons += [f"{label}: {x}" for x in r]
    if ok_a != ok_b and not any(x.startswith("judge_output") for x in ra + rb):
        reasons.append("hai lượt thẩm định mù bất đồng về nội dung (một lượt đạt, một lượt không)")
    return False, reasons, None


def run_diversity_check(ask_fn, chosen: list[dict], history: list[str]) -> list[int]:
    """AI rà lặp TÌNH HUỐNG và DẤU HIỆU GIẢI. Trả chỉ số (trong chosen) các câu nên thay. Chỉ đưa các
    câu lịch sử liên quan (giống nhất) thay vì toàn bộ lịch sử."""
    hist_norm = [(h, norm_for_similarity(h)) for h in history[-HISTORY_COMPARE_LIMIT:] if isinstance(h, str)]
    relevant: list[str] = []
    for it in chosen:
        n = norm_for_similarity(filled_sentence(it["sentence"], it["answer"]))
        scored = []
        for h, hn in hist_norm:
            sm = SequenceMatcher(None, n, hn)
            if hn and sm.real_quick_ratio() >= 0.4 and sm.quick_ratio() >= 0.4:
                scored.append((sm.ratio(), h))
        scored = sorted(scored, key=lambda x: -x[0])[:2]
        for score, h in scored:
            if score >= 0.4 and h not in relevant:
                relevant.append(h)
    relevant = relevant[:30]
    data = _call(ask_fn, ep.assemble("(không cần KB cho bước này)", ep.recognition_diversity_task(
        [{"id": i + 1, "sentence": it["sentence"], "answer": it["answer"],
          "cue": (it.get("audit") or {}).get("cue") or it.get("cue", "")} for i, it in enumerate(chosen)],
        relevant,
    )), "diversity")
    repeats = data.get("repeats")
    if not isinstance(repeats, list):
        raise ValueError("Lượt rà đa dạng trả về sai định dạng (thiếu repeats).")
    flagged: list[int] = []
    for r in repeats:
        if not isinstance(r, dict) or not isinstance(r.get("id"), int):
            continue
        i = r["id"] - 1
        other = r.get("with")
        if not (0 <= i < len(chosen)):
            continue
        # Hai câu trong bộ lặp nhau: chỉ loại 1 câu (câu đứng sau), không loại cả hai.
        if isinstance(other, int) and 1 <= other <= len(chosen) and other != r["id"]:
            i = max(i, other - 1)
            if (min(r["id"], other) - 1) in flagged:
                continue
        if i not in flagged:
            flagged.append(i)
    return flagged[:DIVERSITY_MAX_REMOVALS]


# ---------------------------------------------------------------- điều phối

def _final_questions(chosen_in_order: list[dict], rng: random.Random) -> list[dict]:
    """Khóa đáp án rồi xáo A/B/C/D bằng code; lưu cố định thứ tự cùng bộ đề. meta (hồ sơ kiểm định) ở lại máy chủ."""
    questions = []
    for pos, it in enumerate(chosen_in_order, start=1):
        options = list(it["options"])
        rng.shuffle(options)
        audit = it.get("audit") or {}
        questions.append({
            "id": pos,
            "question": it["sentence"],
            "options": options,
            "correct_index": options.index(it["answer"]),
            "meta": {
                "word": it["word"], "difficulty": it["difficulty"], "planned_difficulty": it.get("planned_difficulty"),
                "verification": "two_blind_judges" if len(audit.get("judges") or []) == 2 else "blind_judge", "audit": audit,
                "also_correct": list(it.get("also_correct") or []),
            },
        })
    return questions


def item_from_question(q: dict) -> dict:
    """Dựng lại item trong pool từ câu đã lưu (dùng khi chỉ sửa vài câu của bộ chưa phát)."""
    meta = q.get("meta") or {}
    options = list(q["options"])
    audit = meta.get("audit") or {}
    return {
        "sentence": q["question"], "options": options, "answer": options[q["correct_index"]],
        "word": meta.get("word"), "difficulty": meta.get("difficulty"),
        "planned_difficulty": meta.get("planned_difficulty"), "cue": audit.get("cue", ""), "audit": audit,
        "also_correct": list(meta.get("also_correct") or []),
    }


def build_recognition_set(
    kb: dict, *, ask_fn, history_fn, refs_fn, is_retry: bool = False, lessons_text: str = "",
    kept: list[dict] | None = None, plan: dict | None = None,
    rng: random.Random | None = None, answer_model: str | None = None,
    size: int = SET_SIZE, focus_words: list[str] | None = None,
) -> dict:
    """Sinh bộ Recognition đạt đủ ràng buộc. history_fn() trả lịch sử mới nhất của tài khoản;
    refs_fn(wait) trả các câu trong Present Knowledge (wait=True: chờ bài giảng xong, có giới hạn).
    kept: item đã thẩm định giữ lại (khi chỉ sửa một vài vị trí). Hết MAX_ROUNDS mà chưa đạt -> 502."""
    rng = rng or random.Random()
    plan = plan or plan_set(kb, rng, size, focus_words)
    size = len(plan["slots"])
    min_size = min_size_for(size)
    pool: list[dict] = list(kept or [])
    failures: dict[tuple[str, str], list[dict]] = {}   # (từ, mức) -> các lần hỏng gần nhất để sửa đúng chỗ
    fail_counts: dict[tuple[str, str], int] = {}       # (từ, mức) -> số lần bị rubric/thẩm định/xác minh loại
    diversity_ok: set[tuple] = set()
    mismatch: dict[tuple[str, str], int] = {}
    last_problem = ""

    def note_failure(slot: dict, sentence: str, reasons: list[str], quality: bool = False) -> None:
        logger.info("loại câu %s/%s: %s", slot["word"], slot["difficulty"], " | ".join(reasons)[:220])
        if quality:   # chỉ lỗi nội dung (rubric/thẩm định/xác minh) mới tính là 'khó đạt'; lỗi định dạng thì không
            fail_counts[(slot["word"], slot["difficulty"])] = fail_counts.get((slot["word"], slot["difficulty"]), 0) + 1
        bucket = failures.setdefault((slot["word"], slot["difficulty"]), [])
        bucket.append({"sentence": sentence, "reasons": reasons})
        del bucket[:-2]

    targets = dict(plan.get("difficulty_targets") or distribution_for(size))       # mục tiêu độ khó CỦA BỘ NÀY (có thể bị hạ khi nhóm từ quá mơ hồ)
    easier = {"hard": "medium", "medium": "easy"}

    def finalize(ordered: list[dict], partial: bool) -> dict:
        questions = _final_questions(ordered, rng)
        problems = check_set_invariants(questions, kb, targets, allow_partial=partial, size=size)
        if problems:
            raise HTTPException(status_code=502, detail="Bộ câu không đạt kiểm tra cuối: " + "; ".join(problems))
        return {"set_id": uuid.uuid4().hex, "format": SET_FORMAT, "questions": questions, "plan": plan,
                "difficulty_targets": dict(targets), "partial": len(questions) < size, "relaxed": partial}

    for _round in range(MAX_ROUNDS):
        avoid = {k: mismatch.get(k, 0) + (100 if fail_counts.get(k, 0) >= BLOCK_THRESHOLD else 0)
                 for k in set(mismatch) | set(fail_counts)}
        placed, missing = select_final(pool, plan, rng, avoid, targets)
        if missing:
            # Hạ độ khó: vị trí còn thiếu mà (từ, mức) đã bị loại nhiều lần -> bỏ 1 câu mức đó khỏi mục tiêu, thêm 1 câu mức dễ hơn.
            changed = False
            for m in missing:
                d = m["difficulty"]
                # 'khó đạt' = bị loại nhiều lần HOẶC câu đạt nhưng luôn được thẩm định ở mức dễ hơn mức giao
                if (d in easier and targets[d] > 0
                        and fail_counts.get((m["word"], d), 0) + mismatch.get((m["word"], d), 0) >= DOWNGRADE_THRESHOLD):
                    targets[d] -= 1
                    targets[easier[d]] += 1
                    changed = True
                    logger.info("hạ độ khó: %s -> %s (từ %s liên tục không đạt)", d, easier[d], m["word"])
            if changed:
                placed, missing = select_final(pool, plan, rng, avoid, targets)
        if missing and _round >= PARTIAL_FROM_ROUND and len(partial_items(placed, pool, plan)) >= min_size:
            # Đủ tối thiểu: dừng sớm, chỉ giữ câu không trùng lịch sử/ví dụ/bài giảng, vẫn qua kiểm tra từng câu (có ô trống).
            ordered = partial_items(placed, pool, plan)
            conflicts = find_conflicts(ordered, [], history_fn(), kb, refs_fn(True))
            keep = [it for i, it in enumerate(ordered) if i not in conflicts]
            if len(keep) >= min_size:
                return finalize(keep, partial=True)
        if missing:
            evict = pick_evictions(placed, missing, fail_counts, rng)
            if evict:
                for it in evict:
                    pool.remove(it)
                logger.info("đổi chỗ mức khó: gỡ %d câu đã đạt để chuyển mức khó sang từ khác", len(evict))
                placed, missing = select_final(pool, plan, rng, avoid, targets)

        if not missing:
            history = history_fn()
            lesson_refs = refs_fn(True)
            ordered = [placed[s["id"]] for s in plan["slots"]]
            conflicts = find_conflicts(ordered, [], history, kb, lesson_refs)
            # find_conflicts so cả các cặp trong bộ; câu sau bị loại, câu trước được giữ.
            if conflicts:
                for ci in conflicts:
                    pool.remove(ordered[ci])
                last_problem = "trùng lịch sử / ví dụ / bài giảng: " + "; ".join(
                    f"câu {ci + 1}: {e['message']}" for ci, e in conflicts.items())
                continue
            sig = tuple(sorted(id(it) for it in ordered))
            if sig not in diversity_ok and history:
                try:
                    flagged = run_diversity_check(ask_fn, ordered, history)
                except AIRateLimitError:
                    raise
                except (AIProviderError, ValueError) as e:
                    last_problem = f"lượt rà đa dạng lỗi: {e}"
                    continue
                if flagged:
                    for fi in flagged:
                        pool.remove(ordered[fi])
                    last_problem = f"AI rà đa dạng loại {len(flagged)} câu lặp tình huống/dấu hiệu giải"
                    continue
                diversity_ok.add(sig)
            return finalize(ordered, partial=False)

        history = history_fn()
        lesson_refs = refs_fn(False)
        requested = list(missing)
        if OVERGENERATE > 1 and len(missing) >= size and FIRST_ROUND_EXTRA:
            # vòng đầu: thêm vài bản nháp dư cho các vị trí đầu (id >= 1000), câu dư đạt được giữ trong pool
            for k, slot in enumerate(rng.sample(missing, min(FIRST_ROUND_EXTRA, len(missing)))):
                use = {}
                requested.append({**slot, "id": 1000 + k, "domain": rng.choice(ep.FIELD_DATABASE),
                                  "structure": rng.choice(STRUCTURES),
                                  "options_words": _slot_options(kb, slot["word"], use, rng)})
        if OVERGENERATE > 1 and len(missing) < size:  # (test đặt OVERGENERATE=1 để tắt)
            next_id = 1000
            for slot in missing:
                for _extra in range((OVERGENERATE_FEW if len(missing) <= 3 else OVERGENERATE) - 1):
                    if len(requested) >= OVERGENERATE_MAX_CANDIDATES:
                        break
                    use = {}
                    requested.append({**slot, "id": next_id, "domain": rng.choice(ep.FIELD_DATABASE),
                                      "structure": rng.choice(STRUCTURES),
                                      "options_words": _slot_options(kb, slot["word"], use, rng)})
                    next_id += 1
        logger.info("recognition_set vòng %d: còn thiếu %d vị trí (%s)", _round + 1, len(missing), last_problem or "-")
        def gen_chunk(chunk: list[dict]) -> dict:
            prompt = ep.assemble(
                ep.lesson_kb_text(kb),
                ep.recognition_set_generation_task(
                    chunk, kb, is_retry,
                    [{"word": w, "difficulty": d, "attempts": v} for (w, d), v in failures.items()
                     if any(m["word"] == w and m["difficulty"] == d for m in chunk)],
                    history[-HISTORY_PROMPT_LIMIT:], lesson_refs,
                ),
                lessons_text,
            )
            return _call(ask_fn, prompt, "generate")

        chunks = [requested[i:i + PARALLEL_CHUNK] for i in range(0, len(requested), PARALLEL_CHUNK)]
        by_id = {}
        try:
            if len(chunks) == 1:
                datas = [gen_chunk(chunks[0])]
            else:
                with ThreadPoolExecutor(max_workers=len(chunks)) as ex:
                    futs = [ex.submit(gen_chunk, c) for c in chunks]
                    datas = []
                    for f in futs:
                        try:
                            datas.append(f.result())
                        except (AIProviderError, ValueError) as e:      # một nhóm hỏng: các nhóm khác vẫn dùng được
                            last_problem = f"lượt sinh câu lỗi: {e}"
            if not datas:
                continue
        except AIRateLimitError:
            raise
        except (AIProviderError, ValueError) as e:
            last_problem = f"lượt sinh câu lỗi: {e}"
            continue
        for data in datas:
            rows = data.get("q") if isinstance(data, dict) else None
            if isinstance(rows, list):
                for r in rows:
                    if isinstance(r, dict) and isinstance(r.get("id"), int) and r["id"] not in by_id:
                        by_id[r["id"]] = r

        # --- kiểm bằng code, từng câu
        valid: list[tuple[dict, dict]] = []   # (slot, item)
        for slot in requested:
            errs, item = validate_item(by_id.get(slot["id"]), slot, kb)
            if errs:
                note_failure(slot, str((by_id.get(slot["id"]) or {}).get("sentence", ""))[:200],
                             [f"{e['code']}: {e['message']}" for e in errs])
                last_problem = f"vị trí {slot['id']}: {errs[0]['code']}"
                continue
            item["planned_difficulty"] = slot["difficulty"]
            valid.append((slot, item))
        if not valid:
            continue

        # --- trùng câu chữ (bộ đang sinh, lịch sử, ví dụ KB, bài giảng)
        conflicts = find_conflicts([it for _, it in valid], pool, history, kb, lesson_refs)
        survivors = []
        for ci, (slot, it) in enumerate(valid):
            if ci in conflicts:
                note_failure(slot, it["sentence"], [f"{conflicts[ci]['code']}: {conflicts[ci]['message']}"])
                last_problem = f"vị trí {slot['id']}: {conflicts[ci]['code']}"
            else:
                survivors.append((slot, it))
        if not survivors:
            continue

        # --- thẩm định MÙ: 1 lượt (mặc định) hoặc 2 lượt độc lập chạy song song (lượt 2 nhìn thứ tự phương án đảo)
        batch = [it for _, it in survivors]
        try:
            if JUDGE_PASSES >= 2:
                with ThreadPoolExecutor(max_workers=2) as pool_ex:
                    fut_a = pool_ex.submit(run_blind_judge, ask_fn, kb, batch, answer_model, False)
                    fut_b = pool_ex.submit(run_blind_judge, ask_fn, kb, batch, answer_model, True)
                    judged_a, judged_b = fut_a.result(), fut_b.result()
            else:
                judged_a = run_blind_judge(ask_fn, kb, batch, answer_model, False,
                                           allow_tie=ALLOW_TIE_AS_TWO_ANSWERS and _round >= TIE_FROM_ROUND,
                                           allow_weak=ALLOW_WEAK_KEY_FILL and _round >= WEAK_FROM_ROUND)
                judged_b = None
        except AIRateLimitError:
            raise
        except (AIProviderError, ValueError) as e:
            last_problem = f"lượt thẩm định lỗi: {e}"
            continue
        for si, (slot, it) in enumerate(survivors):
            ok, reasons, audit = (combine_judges(judged_a[si], judged_b[si]) if judged_b is not None
                                  else combine_judges(judged_a[si], judged_a[si], single=True))
            if not ok:
                note_failure(slot, it["sentence"], reasons, quality=True)
                last_problem = f"vị trí {slot['id']}: {reasons[0]}"
                continue
            it["difficulty"] = audit["difficulty"]     # mức do AI thẩm định, không phải mức được giao
            if it["difficulty"] != it.get("planned_difficulty"):
                key = (it["word"], it["planned_difficulty"])
                mismatch[key] = mismatch.get(key, 0) + 1
            if audit.get("weak_key") and sum(1 for x in pool if (x.get("audit") or {}).get("weak_key")) >= WEAK_MAX:
                note_failure(slot, it["sentence"], ["đã đủ số câu 'thiếu dữ kiện' được nhận trong bộ này"], quality=True)
                continue
            it["audit"] = audit
            it["also_correct"] = list(audit.get("also_correct") or [])
            pool.append(it)

    placed, _missing = select_final(pool, plan, rng, None, targets)
    ordered = partial_items(placed, pool, plan)
    if len(ordered) >= min_size:
        conflicts = find_conflicts(ordered, [], history_fn(), kb, refs_fn(True))
        keep = [it for i, it in enumerate(ordered) if i not in conflicts]
        if len(keep) >= min_size:
            return finalize(keep, partial=True)
    exc = HTTPException(
        status_code=502,
        detail=f"Không tạo được bộ {size} câu đạt đủ tiêu chí sau {MAX_ROUNDS} vòng ({last_problem}), thử lại.",
    )
    # Giữ các câu ĐÃ ĐẠT và kế hoạch để lần thử sau chỉ sinh bù phần còn thiếu, không bỏ làm lại cả 20 câu.
    exc.partial = {"pool": pool, "plan": plan}  # type: ignore[attr-defined]
    raise exc
