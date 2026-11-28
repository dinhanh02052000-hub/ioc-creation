"""Soạn, kiểm tra và ghép lời giải sau khi nộp Recognition (chỉ Recognition chính thức).

Phân công:
  - MÁY CHỦ (code) quyết định câu đúng/sai, lựa chọn của học sinh, khóa hiệu lực, chế độ (wrong/unanswered/correct); kiểm ID,
    phiên bản, đoạn trích nguyên văn, độ dài từng phần, phương án đối chiếu, danh sách phương án còn lại, đoạn tô đậm, ví dụ
    tự đặt tách riêng; ghép văn bản hiển thị.
  - AI diễn giải: dấu hiệu trong đề, vì sao chọn khóa, đối chiếu với từ dễ nhầm, nhận định từng phương án còn lại, và tự báo
    `review_key` khi căn cứ không đủ. Một lượt AI thứ hai (tùy chọn, cùng vai trò `explanation`) rà nội dung: lặp ý, dấu hiệu
    không phân biệt được, đối chiếu sai, dịch lệch mức chắc chắn.
  - Lượt soạn lời giải KHÔNG có quyền đổi khóa, đổi điểm hay hủy câu: nghi vấn đáp án chỉ được chuyển sang cơ chế gắn cờ.

Ba phần hiển thị, đúng thứ tự: Chìa khóa nhận biết -> Phân biệt từ gây nhiễu -> Dịch nghĩa. Thêm một khối "các phương án còn
lại" (mở bằng nút) và danh sách đoạn tô đậm trong thân câu. Văn bản lưu/dùng lại là MỘT chuỗi (định dạng v2) để mọi nơi đang lưu
lời giải (bộ nhớ dùng lại, lượt làm, phiên) không phải đổi cấu trúc:

    - **Chìa khóa nhận biết:** «đoạn trích» — ...
    - **Phân biệt từ gây nhiễu:** ...
    - **Dịch nghĩa:** ...
    ::others::
    - **A. từ:** nhận định ngắn
    ::stem::
    đoạn cần tô đậm trong thân câu (mỗi dòng một đoạn)

Hai loại lỗi tách bạch:
  - LỖI LỜI GIẢI (quá dài, lặp ý, trích sai, so nhầm lựa chọn, thiếu trường, vòng quanh...): viết lại đúng mục, số lần hữu hạn;
    hết lần thì 'unavailable' (cho thử tạo lại), điểm và khóa không đổi. KHÔNG tự cắt chữ cho vừa giới hạn.
  - NGHI VẤN ĐÁP ÁN (thiếu dữ kiện, phương án khác ngang mức): 'under_review', gắn cờ đáp án, không xuất lời khẳng định."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor

import review
from ai_client import AIRateLimitError
from ai_json import parse_ai_json
from recognition_set import _contains_quote, norm_text

logger = logging.getLogger("ioc.explanations")

CHUNK = 4                 # số câu mỗi lời gọi AI (chạy song song)
MAX_ATTEMPTS = 3          # 1 lần đầu + 2 lần viết lại các mục lỗi
STATUS_READY, STATUS_UNDER_REVIEW, STATUS_UNAVAILABLE = "ready", "under_review", "unavailable"
ABSOLUTE_PHRASES = ("không bao giờ", "luôn luôn", "chỉ dùng được", "never", "always", "bất kỳ trường hợp nào")
FORMAT = "v2"             # đổi định dạng lời giải thì đổi số này: bản cũ trong bộ nhớ dùng lại không bị dùng nhầm
OTHERS_MARK, STEM_MARK = "::others::", "::stem::"

# Trần số từ (không có mức tối thiểu). Đếm bằng word_count().
LIMITS = {"clue": 50, "contrast": 55, "translation": 70, "total": 135, "other": 30}
LONG_SENTENCE_WORDS = 35      # câu gốc dài đến mức này mới được xin ngoại lệ cho bản dịch
TRANSLATION_HARD_MAX = 100    # ngoại lệ cũng không vượt mức này
EMPH_SPAN_MAX_WORDS = 8
EMPH_STEM_MAX = 2


# ---------------------------------------------------------------- đếm từ

def word_count(text) -> int:
    """Số từ = số đơn vị tách bởi khoảng trắng sau khi chuẩn hóa khoảng trắng. Bỏ ký hiệu định dạng (*, `, «, ») trước khi đếm;
    đơn vị không có chữ hay số nào (—, ___, -) không tính."""
    s = re.sub(r"[*`«»]", " ", str(text or ""))
    return sum(1 for tok in s.split() if re.search(r"[^\W_]", tok))


# ---------------------------------------------------------------- dữ liệu của từng câu (từ bản ghi thật)

def make_target(q: dict, snap_q: dict, per_q: dict) -> dict:
    """q: câu đã phát; snap_q: ảnh chụp phiên bản câu; per_q: kết quả chấm HIỆU LỰC của câu (khóa, lựa chọn). Chế độ và lựa chọn do
    máy chủ xác định, không lấy từ văn bản AI."""
    oid_to_idx = {o["oid"]: i for i, o in enumerate(snap_q["options"])}
    key_idx = next(oid_to_idx[o] for o in per_q["key_oids"] if o in oid_to_idx)
    chosen = per_q.get("chosen")
    sel = oid_to_idx.get(chosen) if chosen is not None else None
    if sel is None:
        mode = "unanswered"
    elif chosen in per_q["key_oids"]:
        mode = "correct"
    else:
        mode = "wrong"
    d = snap_q.get("dossier") or {}
    return {"id": q["id"], "qv": snap_q["qv"], "sentence": q["question"], "options": [o["text"] for o in snap_q["options"]],
            "key_index": key_idx, "selected_index": sel, "mode": mode, "difficulty": d.get("difficulty"),
            "dossier": d, "key_oid": snap_q["options"][key_idx]["oid"],
            "chosen_oid": snap_q["options"][sel]["oid"] if sel is not None else None,
            "key_sig": "+".join(sorted(per_q["key_oids"]))}


def cache_key(t: dict) -> tuple[str, str, str, str]:
    return (t["qv"], t["key_sig"], t["chosen_oid"] or "-", f"{t['mode']}|{FORMAT}")


# ---------------------------------------------------------------- kiểm tra một mục do AI trả về

def _s(v) -> str:
    """Chuỗi sạch: bỏ ký hiệu định dạng markdown do AI tự chèn (việc tô đậm là của code), gộp khoảng trắng."""
    if not isinstance(v, str):
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[*`]", "", v)).strip()


def _quotes(raw) -> list[str]:
    if isinstance(raw, list):
        if not all(isinstance(x, str) for x in raw):
            return []
        out: list[str] = []
        for x in raw:
            out += _quotes(x)            # một phần tử có thể chứa nhiều đoạn trong ngoặc kép
        return out
    if isinstance(raw, str) and raw.strip():
        found = re.findall(r'["“]([^"”]+)["”]', raw)
        return [q.strip() for q in found if q.strip()] or [raw.strip()]
    return []


def _sentences(text: str) -> set[str]:
    """Các câu (từ 5 từ trở lên) đã chuẩn hóa, để phát hiện chép nguyên văn giữa các phần."""
    out = set()
    for part in re.split(r"[.!?;\n]+", text or ""):
        n = norm_text(re.sub(r"[^\w\s]", " ", part.replace("___", " ")))
        if len(n.split()) >= 5:
            out.add(n)
    return out


def _check_duplicates(parts: dict[str, str]) -> list[str]:
    """Chỉ bắt chuỗi trùng NGUYÊN VĂN giữa hai phần. Lặp ý bằng lời khác là việc của lượt AI rà nội dung."""
    errs, names = [], list(parts)
    sents = {k: _sentences(v) for k, v in parts.items()}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if norm_text(parts[a]) == norm_text(parts[b]) or sents[a] & sents[b]:
                errs.append(f"phần {a} và phần {b} lặp nguyên văn một câu; mỗi phần phải nói một điều riêng, viết lại phần {b}")
    return errs


def _validate_emphasis(raw, sentence: str, bodies: dict[str, str]) -> tuple[list[str], dict[str, str], list[str]]:
    """Đoạn tô đậm do AI đề xuất, code xác nhận từng đoạn có NGUYÊN VĂN trong đúng nguồn. Đoạn không khớp bị bỏ (không tìm gần đúng),
    ghi lỗi để theo dõi; không làm hỏng lời giải. Trả (đoạn trong thân câu, {phần: văn bản đã chèn **}, danh sách lỗi)."""
    errs: list[str] = []
    stem: list[str] = []
    marked: dict[str, str] = {}
    if raw in (None, [], ""):
        return stem, marked, errs
    if not isinstance(raw, list):
        return stem, marked, ["emphasis không phải danh sách: bỏ qua việc tô đậm"]
    for e in raw:
        if not isinstance(e, dict) or not isinstance(e.get("text"), str) or e.get("in") not in ("stem", "clue", "contrast", "translation"):
            errs.append("một mục emphasis sai dạng: bỏ")
            continue
        span, where = e["text"].strip(), e["in"]
        source = sentence if where == "stem" else bodies.get(where, "")
        if not span or "*" in span or span not in source:
            errs.append(f"đoạn tô đậm không có nguyên văn trong {where}: {span[:40]!r}")
            continue
        if word_count(span) > EMPH_SPAN_MAX_WORDS or span == source.strip():
            errs.append(f"đoạn tô đậm trong {where} quá dài hoặc tô cả đoạn: bỏ")
            continue
        if where == "stem":
            if len(stem) >= EMPH_STEM_MAX:
                errs.append("thân câu đã đủ 2 đoạn tô đậm: bỏ đoạn thừa")
            elif span not in stem:
                stem.append(span)
        elif where in marked:
            errs.append(f"mỗi phần lời giải chỉ tô tối đa một đoạn: bỏ đoạn thừa trong {where}")
        else:
            marked[where] = source.replace(span, f"**{span}**", 1)
    return stem, marked, errs


def validate_item(raw, t: dict) -> tuple[dict | None, list[str]]:
    """Trả (mục đã chuẩn hóa, []) hoặc (None, danh sách lỗi cụ thể để viết lại đúng mục)."""
    if not isinstance(raw, dict):
        return None, ["không có mục cho câu này"]
    errs: list[str] = []
    options = t["options"]
    opt_norm = {norm_text(o): o for o in options}
    key_text = options[t["key_index"]]
    status = raw.get("status")
    if status not in ("ready", "review_key"):
        return None, ["status phải là 'ready' hoặc 'review_key'"]

    ev = _quotes(raw.get("evidence"))
    if not (1 <= len(ev) <= 2):
        errs.append("evidence phải gồm 1-2 đoạn trích nguyên văn từ thân câu")
    bad = [e for e in ev if not _contains_quote(t["sentence"], e)]
    if bad:
        errs.append(f"đoạn trích không có nguyên văn trong thân câu: {bad[0][:70]!r}")
    clue = _s(raw.get("key_clue_vi"))
    if not clue:
        errs.append("thiếu key_clue_vi (dấu hiệu quyết định và vì sao nó dẫn tới đáp án)")

    if status == "review_key":
        reason = _s(raw.get("doubt_reason"))
        if not reason:
            errs.append("review_key phải có doubt_reason cụ thể")
        also = raw.get("also_defensible") or []
        if not isinstance(also, list) or any(not isinstance(a, str) or norm_text(a) not in opt_norm for a in also):
            errs.append("also_defensible phải là danh sách phương án thuộc câu")
        if errs:
            return None, errs
        return {"status": "review_key", "evidence": ev, "key_clue": clue, "doubt_reason": reason,
                "also_defensible": [opt_norm[norm_text(a)] for a in also]}, []

    if raw.get("also_defensible"):
        # Lời giải khẳng định mà còn phương án khác bảo vệ được ngang mức: không được xuất như chắc chắn.
        if errs:
            return None, errs
        return {"status": "review_key", "evidence": ev, "key_clue": clue,
                "doubt_reason": _s(raw.get("doubt_reason")) or "Còn phương án khác cũng bảo vệ được trong câu này",
                "also_defensible": [opt_norm[norm_text(a)] for a in raw["also_defensible"]
                                    if isinstance(a, str) and norm_text(a) in opt_norm]}, []

    translation = _s(raw.get("translation_vi"))
    if not translation:
        errs.append("thiếu translation_vi")

    contrast = _s(raw.get("contrast_option"))
    need_contrast = t["mode"] in ("wrong", "unanswered")
    clean_contrast = None
    contrast_vi = _s(raw.get("contrast_vi"))
    if contrast or need_contrast:
        if norm_text(contrast) not in opt_norm:
            errs.append("contrast_option phải chép nguyên văn một phương án của câu")
        elif norm_text(contrast) == norm_text(key_text):
            errs.append("contrast_option không được là chính khóa")
        elif t["mode"] == "wrong" and norm_text(contrast) != norm_text(options[t["selected_index"]]):
            errs.append("câu sai phải đối chiếu với đúng lựa chọn của học sinh")
        else:
            clean_contrast = opt_norm[norm_text(contrast)]
        if not contrast_vi:
            errs.append("đối chiếu cần contrast_vi (khác biệt quyết định giữa khóa và từ này trong câu đang xét)")
    else:
        contrast_vi = ""

    example_en, example_vi = _s(raw.get("example_en")), _s(raw.get("example_vi"))
    if example_en and (norm_text(example_en) == norm_text(t["sentence"]) or not example_vi):
        errs.append("ví dụ tự đặt phải khác thân câu và có example_vi")
    if example_en and not clean_contrast:
        example_en = example_vi = ""            # ví dụ chỉ đi kèm phần đối chiếu

    for f, v in (("key_clue_vi", clue), ("contrast_vi", contrast_vi), ("others", " ".join(
            _s(o.get("note")) for o in (raw.get("others") or []) if isinstance(o, dict)))):
        if any(p in v.lower() for p in ABSOLUTE_PHRASES):
            errs.append(f"{f}: tránh khẳng định tuyệt đối về một từ (kết luận chỉ đúng trong câu đang xét)")

    # ---- các phương án còn lại: đủ, không trùng, không mã lạ; phương án đã đối chiếu ở trên chỉ nhắc "đã giải thích ở trên"
    required = [o for o in options if norm_text(o) != norm_text(key_text) and (clean_contrast is None or norm_text(o) != norm_text(clean_contrast))]
    others: dict[str, str] = {}
    raw_others = raw.get("others")
    if not isinstance(raw_others, list):
        errs.append("others phải là danh sách {option, note} cho mọi phương án còn lại")
    else:
        for o in raw_others:
            name = _s(o.get("option")) if isinstance(o, dict) else ""
            note = _s(o.get("note")) if isinstance(o, dict) else ""
            if norm_text(name) not in opt_norm:
                errs.append(f"others có phương án không thuộc câu: {name[:30]!r}")
                continue
            real = opt_norm[norm_text(name)]
            if norm_text(real) == norm_text(key_text) or (clean_contrast and norm_text(real) == norm_text(clean_contrast)):
                continue                      # khóa và phương án đã đối chiếu không cần dòng riêng
            if real in others:
                errs.append(f"others lặp phương án {real!r}")
            elif not note:
                errs.append(f"others: thiếu nhận định cho {real!r}")
            else:
                others[real] = note
        missing = [o for o in required if o not in others]
        if missing:
            errs.append("others thiếu phương án: " + ", ".join(repr(m) for m in missing))
        for real, note in others.items():
            if word_count(note) > LIMITS["other"]:
                errs.append(f"nhận định cho {real!r} dài {word_count(note)} từ, tối đa {LIMITS['other']}: phải bớt ít nhất {word_count(note) - LIMITS['other'] + 4} từ (nhắm 20 từ); bỏ vế phụ, giữ lý do loại")

    # ---- độ dài từng phần (đếm phần hiển thị: đoạn trích + lời giải); KHÔNG cắt chữ, quá thì yêu cầu viết lại
    clue_body = f"«{' … '.join(ev)}» — {clue}"
    contrast_body = contrast_vi + (f" Ví dụ: {example_en} — {example_vi}" if example_en else "")
    n_clue, n_con, n_tr = word_count(clue_body), word_count(contrast_body), word_count(translation)
    exceptions: list[str] = []
    tr_cap = LIMITS["translation"]
    if n_tr > tr_cap and raw.get("translation_over_cap") is True and word_count(t["sentence"]) >= LONG_SENTENCE_WORDS \
            and n_tr <= TRANSLATION_HARD_MAX:
        exceptions.append("translation_over_cap")       # câu gốc rất dài: ghi nhận và cho qua, không âm thầm
        tr_cap = n_tr
    total_cap = LIMITS["total"] + max(0, tr_cap - LIMITS["translation"])
    part_over = False
    for name, n, cap in (("key_clue_vi (cùng đoạn trích)", n_clue, LIMITS["clue"]), ("contrast_vi (cùng ví dụ nếu có)", n_con, LIMITS["contrast"]),
                         ("translation_vi", n_tr, tr_cap)):
        if n > cap:
            part_over = True
            errs.append(f"{name} dài {n} từ, tối đa {cap}: phải bớt ít nhất {n - cap + 3} từ (nhắm {max(cap - 12, 1)} từ để có dư); bỏ ý lặp, rút đoạn trích, hoặc bỏ ví dụ; giữ nguyên nghĩa, phủ định, điều kiện, mức chắc chắn")
    if not part_over and n_clue + n_con + n_tr > total_cap:
        errs.append(f"ba phần tổng {n_clue + n_con + n_tr} từ, tối đa {total_cap}: rút gọn phần nào lặp ý")

    parts = {"Chìa khóa nhận biết": clue}
    if contrast_vi:
        parts["Phân biệt từ gây nhiễu"] = contrast_vi
    parts["Dịch nghĩa"] = translation
    errs += _check_duplicates(parts)

    stem_spans, marked, emph_errs = _validate_emphasis(
        raw.get("emphasis"), t["sentence"], {"clue": clue_body, "contrast": contrast_body, "translation": translation})
    if errs:
        return None, errs
    return {"status": "ready", "evidence": ev, "key_clue": clue, "clue_body": marked.get("clue", clue_body),
            "translation": marked.get("translation", translation), "contrast_option": clean_contrast,
            "contrast_body": marked.get("contrast", contrast_body), "contrast_vi": contrast_vi,
            "example_en": example_en or None, "example_vi": example_vi or None,
            "others": others, "stem_emphasis": stem_spans, "emphasis_errors": emph_errs, "exceptions": exceptions,
            "words": {"clue": n_clue, "contrast": n_con, "translation": n_tr}}, []


# ---------------------------------------------------------------- ghép văn bản hiển thị

def compose(clean: dict, t: dict) -> str:
    lines = [f"- **Chìa khóa nhận biết:** {clean['clue_body']}"]
    if clean.get("contrast_option"):
        head = f"Em đã chọn «{clean['contrast_option']}». " if t["mode"] == "wrong" else f"Dễ nhầm với «{clean['contrast_option']}». "
        lines.append(f"- **Phân biệt từ gây nhiễu:** {head}{clean['contrast_body']}")
    lines.append(f"- **Dịch nghĩa:** {clean['translation']}")
    options, key_idx = t["options"], t["key_index"]
    rows = []
    for i, opt in enumerate(options):
        if i == key_idx:
            continue
        if clean.get("contrast_option") and opt == clean["contrast_option"]:
            note = "Đã giải thích ở trên."
        else:
            note = clean["others"].get(opt, "")
        if note:
            rows.append(f"- **{'ABCD'[i]}. {opt}:** {note}")
    out = "\n".join(lines)
    if rows:
        out += f"\n{OTHERS_MARK}\n" + "\n".join(rows)
    if clean.get("stem_emphasis"):
        out += f"\n{STEM_MARK}\n" + "\n".join(clean["stem_emphasis"])
    return out


def compose_partial(clean: dict) -> str:
    """Khi câu đang bị xem lại đáp án: chỉ phần nghĩa của dấu hiệu có thể xác nhận, KHÔNG khẳng định một đáp án duy nhất."""
    return f"- **Chìa khóa nhận biết:** «{' … '.join(clean['evidence'])}» — {clean['key_clue']}"


def split_text(text: str) -> dict:
    """Tách chuỗi v2 thành {main, others: [dòng], stem: [đoạn]}. Bản cũ (không có dấu) trả others/stem rỗng."""
    main, others, stem, cur = [], [], [], None
    for line in str(text or "").split("\n"):
        s = line.strip()
        if s == OTHERS_MARK:
            cur = others
        elif s == STEM_MARK:
            cur = stem
        elif s:
            (cur if cur is not None else main).append(s)
    return {"main": "\n".join(main), "others": others, "stem": stem}


# ---------------------------------------------------------------- điều phối

def _call_chunk(ask_fn, kb_text: str, chunk: list[dict], errors: dict[int, list[str]], prompt_fn) -> dict:
    data = parse_ai_json(ask_fn(prompt_fn(kb_text, chunk, errors)))
    out: dict = {}
    for r in (data.get("items") or []):
        if isinstance(r, dict) and isinstance(r.get("id"), int) and r["id"] not in out:      # ID trùng: giữ mục đầu
            out[r["id"]] = r
    return out


def _review_chunk(ask_fn, kb_text: str, pairs: list[dict], review_prompt_fn) -> dict:
    """Lượt AI rà nội dung cho một nhóm lời giải đã qua kiểm của code. Trả {id: {"ok", "issues", "key_doubt", "doubt_reason"}}."""
    data = parse_ai_json(ask_fn(review_prompt_fn(kb_text, pairs)))
    out: dict = {}
    for r in (data.get("items") or []):
        if isinstance(r, dict) and isinstance(r.get("id"), int) and r["id"] not in out:
            out[r["id"]] = r
    return out


def _issues_to_errors(r: dict) -> list[str]:
    errs = []
    for i in (r.get("issues") or []):
        if isinstance(i, dict) and _s(i.get("note")):
            errs.append(f"[rà nội dung · {_s(i.get('part')) or 'chung'} · {_s(i.get('code')) or 'lỗi'}] {_s(i.get('note'))}")
    return errs or ["[rà nội dung] lời giải chưa đạt tiêu chí, viết lại cụ thể hơn"]


def build(ask_fn, kb_text: str, targets: list[dict], prompt_fn, flagged_qvs: set[str] | None = None,
          cache_get=None, cache_put=None, review_prompt_fn=None, review_ask_fn=None) -> dict:
    """Sinh lời giải cho `targets`. Mục lỗi chỉ ảnh hưởng chính nó; các mục hợp lệ giữ nguyên. Trả
    {texts, partial, status, doubts, flagged, exceptions, emphasis_errors}. Không bao giờ đổi khóa/điểm.
    review_prompt_fn (tùy chọn): có thì mỗi mục qua code còn được một lượt AI rà nội dung trước khi nhận; lượt rà lỗi kỹ thuật
    thì mục vẫn được nhận (độ dài, trích, phương án đã do code kiểm). review_ask_fn: hàm ask riêng cho lượt rà (khâu
    explanation_review); không đặt thì dùng ask_fn."""
    flagged_qvs = flagged_qvs or set()
    result = {"texts": {}, "partial": {}, "status": {}, "doubts": {}, "flagged": [], "exceptions": {}, "emphasis_errors": {}, "review_notes": {}}
    todo: list[dict] = []
    for t in targets:
        pos = str(t["id"])
        if t["qv"] in flagged_qvs:                                  # đã có cờ đáp án: không gọi AI, không khẳng định
            result["status"][pos] = STATUS_UNDER_REVIEW
            continue
        cached = cache_get(cache_key(t)) if cache_get else None
        if cached:
            result["texts"][pos] = cached
            result["status"][pos] = STATUS_READY
            continue
        todo.append(t)

    errors: dict[int, list[str]] = {}
    prev: dict[int, dict] = {}
    for attempt in range(MAX_ATTEMPTS):
        if not todo:
            break
        chunks = [[dict(t, _prev=prev.get(t["id"])) for t in todo[i:i + CHUNK]] for i in range(0, len(todo), CHUNK)]
        rows: dict = {}
        with ThreadPoolExecutor(max_workers=min(len(chunks), 6)) as ex:
            futs = [ex.submit(_call_chunk, ask_fn, kb_text, c, {t["id"]: errors.get(t["id"], []) for t in c}, prompt_fn)
                    for c in chunks]
            for f in futs:
                try:
                    rows.update(f.result())
                except AIRateLimitError:
                    pass
                except Exception:  # noqa: BLE001 - một nhóm lỗi không làm mất nhóm khác
                    logger.exception("Một nhóm lời giải thất bại")
        still: list[dict] = []
        passed: list[tuple[dict, dict, str]] = []
        for t in todo:
            clean, errs = validate_item(rows.get(t["id"]), t)
            if clean is None:
                errors[t["id"]] = errs or ["không có kết quả"]
                if isinstance(rows.get(t["id"]), dict):
                    prev[t["id"]] = rows[t["id"]]
                still.append(t)
            elif clean["status"] == "review_key":
                _accept_review(result, t, clean)
            else:
                passed.append((t, clean, compose(clean, t)))

        reviews: dict = {}
        if review_prompt_fn and passed:
            pairs = [{"target": t, "text": text, "clean": c} for t, c, text in passed]
            rchunks = [pairs[i:i + CHUNK] for i in range(0, len(pairs), CHUNK)]
            with ThreadPoolExecutor(max_workers=min(len(rchunks), 6)) as ex:
                futs = [ex.submit(_review_chunk, review_ask_fn or ask_fn, kb_text, c, review_prompt_fn) for c in rchunks]
                for f in futs:
                    try:
                        reviews.update(f.result())
                    except Exception:  # noqa: BLE001 - lượt rà lỗi: nhận bản đã qua kiểm của code, ghi nhận
                        logger.warning("Lượt rà nội dung lời giải lỗi; nhận bản đã qua kiểm của code")
        for t, clean, text in passed:
            pos = str(t["id"])
            r = reviews.get(t["id"])
            if isinstance(r, dict) and r.get("key_doubt") is True and _s(r.get("doubt_reason")):
                # rà nội dung thấy căn cứ không đủ/mâu thuẫn với hồ sơ kiểm định: gắn cờ đáp án, không xuất lời khẳng định
                _accept_review(result, t, {"status": "review_key", "evidence": clean["evidence"], "key_clue": clean["key_clue"],
                                           "doubt_reason": _s(r["doubt_reason"]), "also_defensible": []})
            elif isinstance(r, dict) and r.get("ok") is False and attempt < MAX_ATTEMPTS - 1:
                errors[t["id"]] = _issues_to_errors(r)
                prev[t["id"]] = {"id": t["id"], "status": "ready", "evidence": clean["evidence"], "key_clue_vi": clean["key_clue"],
                                 "contrast_option": clean["contrast_option"], "contrast_vi": clean["contrast_vi"],
                                 "translation_vi": clean["translation"], "others": [{"option": k, "note": v} for k, v in clean["others"].items()],
                                 "example_en": clean["example_en"], "example_vi": clean["example_vi"]}
                still.append(t)
            else:
                result["texts"][pos] = text
                result["status"][pos] = STATUS_READY
                if isinstance(r, dict) and r.get("ok") is False:
                    # hết lần viết lại mà lượt rà vẫn còn góp ý (không phải nghi đáp án): bản đã qua kiểm của code vẫn được nhận,
                    # ghi nhận góp ý để rà sau; học sinh không bị mất lời giải vì lỗi diễn đạt nhẹ
                    result["review_notes"][pos] = _issues_to_errors(r)
                    logger.warning("Lời giải câu %s nhận khi còn góp ý rà nội dung: %s", t["id"], "; ".join(result["review_notes"][pos])[:200])
                if clean["exceptions"]:
                    result["exceptions"][pos] = clean["exceptions"]
                    logger.warning("Lời giải câu %s dùng ngoại lệ: %s", t["id"], ", ".join(clean["exceptions"]))
                if clean["emphasis_errors"]:
                    result["emphasis_errors"][pos] = clean["emphasis_errors"]
                    logger.info("Lời giải câu %s bỏ đoạn tô đậm không hợp lệ: %s", t["id"], "; ".join(clean["emphasis_errors"])[:200])
                if cache_put:
                    cache_put(cache_key(t), text)
        todo = still
    for t in todo:
        result["status"][str(t["id"])] = STATUS_UNAVAILABLE
        logger.warning("Lời giải câu %s chưa đạt sau %d lần: %s", t["id"], MAX_ATTEMPTS, "; ".join(errors.get(t["id"], []))[:200])
    return result


def _accept_review(result: dict, t: dict, clean: dict) -> None:
    pos = str(t["id"])
    result["status"][pos] = STATUS_UNDER_REVIEW
    result["partial"][pos] = compose_partial(clean)
    result["doubts"][pos] = {"reason": clean["doubt_reason"], "also_defensible": clean["also_defensible"]}
    result["flagged"].append((t["qv"], clean["doubt_reason"]))
