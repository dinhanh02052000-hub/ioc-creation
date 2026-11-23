"""Soạn, kiểm tra và ghép lời giải sau khi nộp Recognition (chỉ Recognition chính thức).

Phân công:
  - MÁY CHỦ (code) quyết định câu đúng/sai, lựa chọn của học sinh, khóa hiệu lực, chế độ (wrong/unanswered/correct); kiểm ID,
    phiên bản, đoạn trích nguyên văn, phương án đối chiếu, trường bắt buộc, ví dụ tự đặt tách riêng; ghép văn bản hiển thị.
  - AI diễn giải: dấu hiệu trong đề, vì sao chọn khóa, đối chiếu với từ dễ nhầm, và tự báo `review_key` khi căn cứ không đủ.
  - Lượt soạn lời giải KHÔNG có quyền đổi khóa, đổi điểm hay hủy câu: nghi vấn đáp án chỉ được chuyển sang cơ chế gắn cờ.

Hai loại lỗi tách bạch:
  - LỖI LỜI GIẢI (trích sai, so nhầm lựa chọn, thiếu trường, vòng quanh...): viết lại đúng mục, số lần hữu hạn; hết lần thì
    'unavailable' (cho thử tạo lại), điểm và khóa không đổi.
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
    return (t["qv"], t["key_sig"], t["chosen_oid"] or "-", t["mode"])


# ---------------------------------------------------------------- kiểm tra một mục do AI trả về

def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


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
    meaning = _s(raw.get("evidence_meaning"))
    if not meaning:
        errs.append("thiếu evidence_meaning (đoạn trích cho biết điều gì)")

    if status == "review_key":
        reason = _s(raw.get("doubt_reason"))
        if not reason:
            errs.append("review_key phải có doubt_reason cụ thể")
        also = raw.get("also_defensible") or []
        if not isinstance(also, list) or any(not isinstance(a, str) or norm_text(a) not in opt_norm for a in also):
            errs.append("also_defensible phải là danh sách phương án thuộc câu")
        if errs:
            return None, errs
        return {"status": "review_key", "evidence": ev, "evidence_meaning": meaning, "doubt_reason": reason,
                "also_defensible": [opt_norm[norm_text(a)] for a in also]}, []

    why = _s(raw.get("why_key"))
    if not why:
        errs.append("thiếu why_key (vì sao chọn khóa trong chính câu này)")
    if why and meaning and norm_text(why) == norm_text(meaning):
        errs.append("why_key trùng nguyên văn evidence_meaning (chưa có bước nối nghĩa)")
    translation = _s(raw.get("translation_vi"))
    if not translation:
        errs.append("thiếu translation_vi")
    if raw.get("also_defensible"):
        # Lời giải khẳng định mà còn phương án khác bảo vệ được ngang mức: không được xuất như chắc chắn.
        return {"status": "review_key", "evidence": ev, "evidence_meaning": meaning,
                "doubt_reason": _s(raw.get("doubt_reason")) or "Còn phương án khác cũng bảo vệ được trong câu này",
                "also_defensible": [opt_norm[norm_text(a)] for a in raw["also_defensible"]
                                    if isinstance(a, str) and norm_text(a) in opt_norm]}, []
    for f in ("evidence_meaning", "why_key", "shared_point", "contrast_vi"):
        if any(p in _s(raw.get(f)).lower() for p in ABSOLUTE_PHRASES):
            errs.append(f"{f}: tránh khẳng định tuyệt đối về một từ (kết luận chỉ đúng trong câu đang xét)")

    contrast = _s(raw.get("contrast_option"))
    need_contrast = t["mode"] in ("wrong", "unanswered")
    clean_contrast = None
    if contrast or need_contrast:
        if norm_text(contrast) not in opt_norm:
            errs.append("contrast_option phải chép nguyên văn một phương án của câu")
        elif norm_text(contrast) == norm_text(key_text):
            errs.append("contrast_option không được là chính khóa")
        elif t["mode"] == "wrong" and norm_text(contrast) != norm_text(options[t["selected_index"]]):
            errs.append("câu sai phải đối chiếu với đúng lựa chọn của học sinh")
        else:
            clean_contrast = opt_norm[norm_text(contrast)]
        shared, why_not = _s(raw.get("shared_point")), _s(raw.get("contrast_vi"))
        if not shared or not why_not:
            errs.append("đối chiếu cần shared_point (vì sao dễ nhầm) và contrast_vi (khác biệt quyết định trong câu này)")
        elif norm_text(shared) == norm_text(why_not):
            errs.append("shared_point và contrast_vi không được trùng nhau")
    else:
        shared = why_not = ""

    example_en, example_vi = _s(raw.get("example_en")), _s(raw.get("example_vi"))
    if example_en and (norm_text(example_en) == norm_text(t["sentence"]) or not example_vi):
        errs.append("ví dụ tự đặt phải khác thân câu và có example_vi")
    grammar = _s(raw.get("grammar_vi"))
    excludes = raw.get("grammar_excludes") or []
    grammar_ok = bool(grammar) and isinstance(excludes, list) and excludes and all(
        isinstance(x, str) and norm_text(x) in opt_norm and norm_text(x) != norm_text(key_text) for x in excludes)
    start_hint = _s(raw.get("start_hint"))
    if t["mode"] == "unanswered" and not start_hint:
        errs.append("câu bỏ trống cần start_hint (cách bắt đầu đọc câu)")
    if errs:
        return None, errs
    return {"status": "ready", "evidence": ev, "evidence_meaning": meaning, "why_key": why, "translation": translation,
            "contrast_option": clean_contrast, "shared_point": shared, "contrast_vi": why_not,
            "example_en": example_en or None, "example_vi": example_vi or None,
            # ngữ pháp chỉ giữ khi nó loại được ít nhất một phương án CỤ THỂ; không thì bỏ dòng này (không thất bại cả mục)
            "grammar_vi": grammar if grammar_ok else None, "grammar_excludes": excludes if grammar_ok else [],
            "start_hint": start_hint or None}, []


# ---------------------------------------------------------------- ghép văn bản hiển thị

def compose(clean: dict, t: dict) -> str:
    key_text = t["options"][t["key_index"]]
    q = " … ".join(clean["evidence"])
    lines = []
    if t["mode"] == "unanswered" and clean.get("start_hint"):
        lines.append(f"- **Cách bắt đầu:** {clean['start_hint']}")
    lines.append(f"- **Dấu hiệu trong đề:** «{q}» — {clean['evidence_meaning']}")
    lines.append(f"- **Vì sao chọn {key_text}:** {clean['why_key']}")
    if clean.get("contrast_option"):
        tag = "em đã chọn" if t["mode"] == "wrong" else "dễ nhầm"
        sp = clean["shared_point"]
        sp = sp[:1].lower() + sp[1:] if sp else sp          # nối sau 'vì ...' nên viết thường chữ đầu
        if t["mode"] == "wrong":
            lines.append(f"- **So với «{clean['contrast_option']}» ({tag}):** hai từ dễ nhầm vì {sp} "
                         f"Khác biệt quyết định trong câu này: {clean['contrast_vi']}")
        else:
            lines.append(f"- **So với «{clean['contrast_option']}» ({tag}):** {clean['shared_point']} {clean['contrast_vi']}")
    if clean.get("example_en"):
        lines.append(f"- **Ví dụ minh họa mới** (do hệ thống đặt, không nằm trong đề): {clean['example_en']} — {clean['example_vi']}")
    if clean.get("grammar_vi"):
        lines.append(f"- **Ngữ pháp:** {clean['grammar_vi']}")
    lines.append(f"- **Dịch nghĩa:** {clean['translation']}")
    return "\n".join(lines)


def compose_partial(clean: dict) -> str:
    """Khi câu đang bị xem lại đáp án: chỉ phần nghĩa của dấu hiệu có thể xác nhận, KHÔNG khẳng định một đáp án duy nhất."""
    return f"- **Dấu hiệu trong đề:** «{' … '.join(clean['evidence'])}» — {clean['evidence_meaning']}"


# ---------------------------------------------------------------- điều phối

def _call_chunk(ask_fn, kb_text: str, chunk: list[dict], errors: dict[int, list[str]], prompt_fn) -> dict:
    data = parse_ai_json(ask_fn(prompt_fn(kb_text, chunk, errors)))
    out: dict = {}
    for r in (data.get("items") or []):
        if isinstance(r, dict) and isinstance(r.get("id"), int) and r["id"] not in out:      # ID trùng: giữ mục đầu
            out[r["id"]] = r
    return out


def build(ask_fn, kb_text: str, targets: list[dict], prompt_fn, flagged_qvs: set[str] | None = None,
          cache_get=None, cache_put=None) -> dict:
    """Sinh lời giải cho `targets`. Mục lỗi chỉ ảnh hưởng chính nó; các mục hợp lệ giữ nguyên. Trả
    {texts, partial, status, doubts, flagged}. Không bao giờ đổi khóa/điểm."""
    flagged_qvs = flagged_qvs or set()
    result = {"texts": {}, "partial": {}, "status": {}, "doubts": {}, "flagged": []}
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
    for attempt in range(MAX_ATTEMPTS):
        if not todo:
            break
        chunks = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
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
        for t in todo:
            pos = str(t["id"])
            clean, errs = validate_item(rows.get(t["id"]), t)
            if clean is None:
                errors[t["id"]] = errs or ["không có kết quả"]
                still.append(t)
            elif clean["status"] == "review_key":
                result["status"][pos] = STATUS_UNDER_REVIEW
                result["partial"][pos] = compose_partial(clean)
                result["doubts"][pos] = {"reason": clean["doubt_reason"], "also_defensible": clean["also_defensible"]}
                result["flagged"].append((t["qv"], clean["doubt_reason"]))
            else:
                text = compose(clean, t)
                result["texts"][pos] = text
                result["status"][pos] = STATUS_READY
                if cache_put:
                    cache_put(cache_key(t), text)
        todo = still
    for t in todo:
        result["status"][str(t["id"])] = STATUS_UNAVAILABLE
        logger.warning("Lời giải câu %s chưa đạt sau %d lần: %s", t["id"], MAX_ATTEMPTS, "; ".join(errors.get(t["id"], []))[:200])
    return result
