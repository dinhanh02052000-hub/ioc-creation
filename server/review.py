"""Chấm lại, gắn cờ và xử lý báo cáo cho Recognition chính thức. Toàn bộ là hàm thuần (không DB, không mạng).

Ranh giới trách nhiệm:
  - CODE: định danh phiên bản câu/mã phương án, chấm bài từ lựa chọn đã lưu, áp quyết định thành điểm, xác thực
    báo cáo (đúng lượt, đúng câu, đúng loại), xác thực đầu ra AI, quy tắc trạng thái.
  - AI: bằng chứng ngôn ngữ (đánh giá mù, phản biện báo cáo, viết lời giải). AI chỉ ĐỀ XUẤT; mọi quyết định đổi
    điểm hay áp quy tắc dùng chung cần người có thẩm quyền xác nhận (review_admin.py)."""

from __future__ import annotations

import hashlib
import json

import scoring
from confidence import round1
from recognition_set import _contains_quote, norm_text

# ---------------------------------------------------------------- ký hiệu chất lượng câu / độ tin cậy đáp án

QUALITY_CRITERIA_TOTAL = 7


def quality_signals(meta: dict | None) -> dict:
    """Quy đổi HỒ SƠ KIỂM ĐỊNH thật của câu thành hai ký hiệu dễ hiểu. Không dùng độ tự tin do AI tự khai (chưa hiệu chuẩn);
    mọi mức đều suy ra bằng quy tắc xác định từ kết quả thẩm định mù và cờ của câu.

    Chất lượng câu (số tiêu chí AI thẩm định mù chấm ĐẠT trên 7: phạm vi, tự nhiên, một đáp án tốt nhất, nhiễu hợp lý,
    đủ dữ kiện, không lộ từ, không áp đặt giả định):
      high   : đạt đủ 7/7 và không có cảnh báo
      medium : 4 tiêu chí chặn đều đạt nhưng có tiêu chí phụ/cảnh báo chưa đạt
      low    : câu được nhận qua lối thoát (thiếu dữ kiện) -> nên xem kỹ
    Độ tin cậy đáp án:
      high   : thẩm định mù chọn đúng đáp án và kết luận có MỘT phương án tốt nhất
      medium : câu có 2 đáp án ngang nhau được chấp nhận (chấm theo tập đáp án)
      low    : thẩm định chỉ chọn đúng đáp án nhưng nêu thiếu dữ kiện để phân biệt (weak_key)
      unknown: bản ghi cũ chưa có hồ sơ kiểm định chi tiết"""
    meta = meta or {}
    audit = meta.get("audit") or {}
    judges = audit.get("judges") if isinstance(audit, dict) else None
    has_criteria = bool(audit.get("criteria")) if isinstance(audit, dict) else False
    if not judges or not has_criteria or meta.get("verification") not in ("two_blind_judges", "blind_judge"):
        return {"quality": {"level": "unknown", "label": "Chưa có dữ liệu kiểm định chi tiết", "passed": None,
                            "total": QUALITY_CRITERIA_TOTAL},
                "reliability": {"level": "unknown", "label": "Chưa có dữ liệu kiểm định chi tiết"}}
    criteria = audit.get("criteria") or {}
    passed = sum(1 for v in criteria.values() if v is True)
    warnings = [w for j in judges if isinstance(j, dict) for w in (j.get("warnings") or [])]
    weak = bool(audit.get("weak_key"))
    two = bool(meta.get("also_correct"))
    if weak:
        q_level, q_label = "low", "Nên xem kỹ"
    elif passed >= QUALITY_CRITERIA_TOTAL and not warnings:
        q_level, q_label = "high", "Tốt"
    else:
        q_level, q_label = "medium", "Khá"
    if weak:
        r_level, r_label = "low", "Cần xem lại: dấu hiệu phân biệt còn yếu"
    elif two:
        r_level, r_label = "medium", "Câu chấp nhận 2 đáp án"
    else:
        r_level, r_label = "high", "Cao: thẩm định độc lập chọn đúng đáp án"
    return {"quality": {"level": q_level, "label": q_label, "passed": passed, "total": QUALITY_CRITERIA_TOTAL},
            "reliability": {"level": r_level, "label": r_label}}


def apply_state_to_signals(sig: dict, question_code: str) -> dict:
    """Độ tin cậy đáp án là kết quả thẩm định LÚC TẠO CÂU; khi câu đang bị xem lại hoặc đáp án đã bị đổi/loại thì mức 'Cao' đó không còn đúng,
    nên trạng thái hiện tại của câu ghi đè lên ký hiệu (không sửa hồ sơ kiểm định gốc)."""
    override = {
        "answer_under_review": ("review", "Đáp án đang được xem lại nên chưa thể coi là chắc chắn"),
        "key_fixed": ("low", "Đáp án đã được điều chỉnh sau khi xem lại"),
        "multi_accepted": ("medium", "Đã chấp nhận thêm phương án sau khi xem lại"),
        "voided": ("low", "Câu đã bị loại khỏi điểm sau khi xem lại"),
    }.get(question_code)
    if not override:
        return sig
    return {**sig, "reliability": {"level": override[0], "label": override[1]}}


# ---------------------------------------------------------------- định danh ổn định


def option_id(text: str) -> str:
    """Mã phương án ổn định theo NỘI DUNG, không phụ thuộc thứ tự A/B/C/D đã xáo."""
    return "o" + hashlib.sha1(norm_text(text).encode("utf-8")).hexdigest()[:8]


def question_version_id(world_id: str, level: int, sentence: str, options: list[str]) -> str:
    """Mã phiên bản câu: theo level + thân câu + TẬP phương án (không phụ thuộc thứ tự). Hai đề khác nhau cùng có
    'Câu 1' vẫn có mã khác nhau; hai học sinh gặp cùng câu với thứ tự A/B/C/D khác nhau có CÙNG mã."""
    ids = sorted(option_id(o) for o in options)
    raw = "|".join([world_id, str(level), norm_text(sentence.replace("___", "_")), *ids])
    return "qv" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_snapshot(world_id: str, level: int, questions: list[dict]) -> list[dict]:
    """Ảnh chụp những gì học sinh ĐÃ THẤY (thứ tự lựa chọn thực tế) + khóa gốc + trạng thái hồ sơ kiểm định."""
    snap = []
    for q in questions:
        opts = [{"oid": option_id(o), "text": o} for o in q["options"]]
        meta = q.get("meta") or {}
        audit = meta.get("audit") or {}
        judges = audit.get("judges") if isinstance(audit, dict) else None
        snap.append({
            "pos": q["id"], "qv": question_version_id(world_id, level, q["question"], q["options"]),
            # câu có tập đáp án chấp nhận (hai đáp án ngang nhau): các phương án đúng ngoài khóa chính
            "alt_oids": [option_id(t) for t in (meta.get("also_correct") or []) if t in q["options"]],
            "signals": quality_signals(meta),
            # hồ sơ xác minh gọn dùng để soạn lời giải (không gửi xuống giao diện); bản ghi cũ không có -> rỗng, không dựng hộ
            "dossier": {"difficulty": meta.get("difficulty"), "cue": audit.get("cue"), "rival": audit.get("rival"),
                        "rival_reading": audit.get("rival_reason"), "usage": audit.get("usage")} if audit else {},
            "text": q["question"], "options": opts, "key_oid": opts[q["correct_index"]]["oid"],
            # Bản ghi cũ chưa có hồ sơ kiểm định: nói đúng là thiếu dữ liệu, KHÔNG gán 'đã xác minh độc lập'.
            "audit_status": meta.get("verification") if (meta.get("verification") in ("two_blind_judges", "blind_judge")
                                                         and judges) else "missing_audit",
        })
    return snap


def answers_by_qv(snapshot: list[dict], answers_by_pos: dict) -> dict[str, str | None]:
    """Đổi {vị trí: chỉ số lựa chọn} sang {mã câu: mã phương án đã chọn | None}. Bỏ trống -> None (không bịa)."""
    out: dict[str, str | None] = {}
    for q in snapshot:
        idx = answers_by_pos.get(str(q["pos"]))
        out[q["qv"]] = q["options"][idx]["oid"] if isinstance(idx, int) and 0 <= idx < len(q["options"]) else None
    return out


# ---------------------------------------------------------------- quyết định có hiệu lực

DECISION_TYPES = ("keep", "fix_key", "accept_multi", "void", "fix_explanation")
SCORE_DECISIONS = ("fix_key", "accept_multi", "void")


def effective_decisions(decisions: list[dict]) -> dict[str, dict]:
    """Từ danh sách quyết định ĐÃ ÁP DỤNG (cũ -> mới, bỏ revoked) suy ra trạng thái hiệu lực mỗi phiên bản câu.
    Tính lại từ đầu mỗi lần nên chạy lại bao nhiêu lần cũng ra cùng kết quả (không cộng dồn)."""
    eff: dict[str, dict] = {}
    for d in sorted(decisions, key=lambda x: x["id"]):
        if d.get("status") != "applied":
            continue
        e = eff.setdefault(d["qv"], {"key_oids": None, "void": False, "explanation_fix": None, "ids": [], "last": None})
        t = d["decision_type"]
        if t in ("fix_key", "accept_multi"):
            e["key_oids"] = list(d["key_oids"])
            e["void"] = False
        elif t == "void":
            e["void"] = True
        elif t == "fix_explanation":
            e["explanation_fix"] = d.get("explanation_fix")
        e["ids"].append(d["id"])
        e["last"] = d
    return eff


def grade(snapshot: list[dict], answers: dict[str, str | None], eff: dict[str, dict],
          tentative_qvs: set[str] | None = None) -> dict:
    """Chấm từ lựa chọn GỐC đã lưu theo khóa/tập khóa/hủy đang có hiệu lực. Hủy câu: bỏ khỏi cả số đúng và mẫu số
    (5/20 -> 5/19 nếu em sai câu bị hủy, 4/19 nếu em đúng). Không còn câu hợp lệ: score None (không chia 0, không
    gán 0). tentative: có câu đang bị gắn cờ xem lại đáp án mà em đã làm, nên kết quả chỉ là tạm tính."""
    tentative_qvs = tentative_qvs or set()
    per: dict[str, dict] = {}
    correct = valid = 0
    tentative = False
    for q in snapshot:
        e = eff.get(q["qv"]) or {}
        chosen = answers.get(q["qv"])
        key_oids = e.get("key_oids") or [q["key_oid"], *q.get("alt_oids", [])]
        if e.get("void"):
            status = "voided"
        else:
            valid += 1
            if chosen is None:
                status = "unanswered"
            elif chosen in key_oids:
                status = "correct"
                correct += 1
            else:
                status = "wrong"
        if q["qv"] in tentative_qvs:
            tentative = True
        per[q["qv"]] = {"status": status, "chosen": chosen, "key_oids": key_oids, "pos": q["pos"]}
    score = scoring.calc_recognition(correct, valid) if valid else None
    return {"correct": correct, "valid_total": valid, "score": score, "per_question": per, "tentative": tentative}


# ---------------------------------------------------------------- báo cáo

# loại -> (số phương án cần chọn: 'one' | 'many' | 'none', ghi chú bắt buộc?, quyết định AI được đề xuất)
REPORT_TYPES = {
    "wrong_key": {"options": "one", "note_required": False,
                  "decisions": ("fix_key", "accept_multi", "keep", "needs_human"), "scope": "key"},
    "multiple_answers": {"options": "many", "note_required": False,
                         "decisions": ("accept_multi", "void", "keep", "needs_human"), "scope": "key"},
    "no_answer": {"options": "none", "note_required": False,
                  "decisions": ("void", "keep", "needs_human"), "scope": "key"},
    "out_of_scope": {"options": "none", "note_required": False,
                     "decisions": ("void", "keep", "needs_human"), "scope": "key"},
    "explanation_wrong": {"options": "none", "note_required": True,
                          "decisions": ("fix_explanation", "keep", "needs_human"), "scope": "explanation"},
    "explanation_unclear": {"options": "none", "note_required": False, "decisions": (), "scope": "explanation"},
}
MAX_NOTE_CHARS = 1200

# Trạng thái báo cáo (khác trạng thái câu và trạng thái lời giải).
REPORT_STATUSES = ("received", "reviewing", "accepted", "kept", "needs_human", "recorded", "pending_error")


class ReportError(ValueError):
    pass


def validate_report(report_type, option_oids, note, snap_q: dict) -> dict:
    """Điều kiện hợp lệ của dữ liệu (không dùng độ dài ghi chú làm tiêu chí đúng/sai; 'A và C đều điền được' là đủ)."""
    spec = REPORT_TYPES.get(report_type) if isinstance(report_type, str) else None
    if spec is None:
        raise ReportError("Loại báo cáo không hợp lệ.")
    if note is not None and not isinstance(note, str):
        raise ReportError("Ghi chú phải là văn bản.")
    note = (note or "").strip()
    if len(note) > MAX_NOTE_CHARS:
        raise ReportError(f"Ghi chú tối đa {MAX_NOTE_CHARS} ký tự.")
    if spec["note_required"] and not note:
        raise ReportError("Hãy chỉ ra đoạn hoặc lỗi cụ thể trong lời giải.")
    if option_oids is None:
        option_oids = []
    if not isinstance(option_oids, list) or any(not isinstance(o, str) for o in option_oids):
        raise ReportError("Danh sách phương án không hợp lệ.")
    valid = {o["oid"] for o in snap_q["options"]}
    if len(set(option_oids)) != len(option_oids) or any(o not in valid for o in option_oids):
        raise ReportError("Phương án không thuộc câu hỏi em đã làm.")
    kind = spec["options"]
    if kind == "one":
        if len(option_oids) != 1:
            raise ReportError("Hãy chọn đúng một phương án em cho là đúng.")
        if option_oids[0] == snap_q["key_oid"]:
            raise ReportError("Phương án đề xuất trùng với đáp án hiện tại. Nếu em thấy nhiều phương án cùng đúng, hãy chọn loại 'có nhiều đáp án hợp lý'.")
    elif kind == "many":
        if len(option_oids) < 2:
            raise ReportError("Hãy chọn từ hai phương án trở lên (có thể gồm cả đáp án hiện tại).")
    elif option_oids:
        raise ReportError("Loại báo cáo này không kèm lựa chọn phương án.")
    return {"report_type": report_type, "option_oids": option_oids, "note": note}


def case_id(qv: str, report_type: str) -> str:
    """Báo cáo của nhiều người về cùng câu/loại liên kết cùng một ca rà soát (mỗi người vẫn chỉ xem dữ liệu của mình)."""
    return f"{qv}:{report_type}"


# ---------------------------------------------------------------- xác thực đầu ra AI khi xét báo cáo

TRIAGE_VERDICTS = ("accept", "keep", "needs_human")


def validate_triage(out, report_type: str, snap_q: dict, letters_to_oid: dict[str, str]) -> tuple[dict | None, str | None]:
    """Xác thực schema nghiêm. Trả (kết quả chuẩn hóa, None) hoặc (None, lý do). Lỗi/thiếu trường KHÔNG bị hiểu là
    'báo cáo sai': người gọi chuyển sang trạng thái chờ."""
    if not isinstance(out, dict):
        return None, "đầu ra không phải đối tượng"
    spec = REPORT_TYPES[report_type]
    verdict = out.get("verdict")
    decision = out.get("decision")
    if verdict not in TRIAGE_VERDICTS:
        return None, "verdict không hợp lệ"
    if decision not in spec["decisions"]:
        return None, f"quyết định đề xuất '{decision}' không thuộc loại báo cáo này"
    if (verdict == "keep") != (decision == "keep") or (verdict == "needs_human") != (decision == "needs_human"):
        return None, "verdict và decision mâu thuẫn"
    for f in ("student_argument", "response_to_argument", "reason"):
        if not isinstance(out.get(f), str) or not out[f].strip():
            return None, f"thiếu {f}"
    if not isinstance(out.get("affects_score"), bool):
        return None, "affects_score phải là boolean"
    quote = out.get("sentence_detail_quote")
    if verdict in ("accept", "keep") and report_type not in ("explanation_unclear",) and not _contains_quote(snap_q["text"], quote):
        return None, "sentence_detail_quote không xuất hiện nguyên văn trong thân câu"
    letters = out.get("accepted_options")
    oids: list[str] = []
    if decision in ("fix_key", "accept_multi"):
        if not isinstance(letters, list) or any(l not in letters_to_oid for l in letters) or len(set(letters)) != len(letters):
            return None, "accepted_options không hợp lệ"
        oids = [letters_to_oid[l] for l in letters]
        if decision == "fix_key" and len(oids) != 1:
            return None, "fix_key cần đúng một phương án"
        if decision == "accept_multi" and len(oids) < 2:
            return None, "accept_multi cần từ hai phương án"
    elif letters:
        return None, "accepted_options chỉ đi kèm fix_key/accept_multi"
    if decision in SCORE_DECISIONS and out["affects_score"] is not True:
        return None, "quyết định đổi điểm phải khai affects_score=true"
    fix_text = out.get("explanation_fix")
    if decision == "fix_explanation" and (not isinstance(fix_text, str) or not fix_text.strip()):
        return None, "fix_explanation cần nội dung lời giải đề xuất"
    return {
        "verdict": verdict, "decision": decision, "accepted_oids": oids, "affects_score": out["affects_score"],
        "student_argument": out["student_argument"].strip()[:400], "response": out["response_to_argument"].strip()[:500],
        "reason": out["reason"].strip()[:300], "quote": str(quote or "")[:200],
        "explanation_fix": fix_text.strip()[:900] if isinstance(fix_text, str) else None,
    }, None


def reconcile_with_dossier(result: dict, report_type: str, snap_q: dict, blind_choice_oid: str | None) -> dict:
    """Đối chiếu đề xuất của AI với đánh giá mù. Nếu AI đề xuất đổi khóa mà đánh giá mù độc lập KHÔNG ủng hộ, hoặc
    đánh giá mù bất đồng với khóa hiện tại, hạ xuống needs_human (có bất đồng thật giữa các phán đoán hợp lệ)."""
    if result["verdict"] != "accept" or result["decision"] not in ("fix_key", "accept_multi"):
        return result
    if blind_choice_oid is None:
        return {**result, "verdict": "needs_human", "decision": "needs_human", "accepted_oids": [],
                "reason": "Chưa có đánh giá mù hợp lệ để đối chiếu: " + result["reason"]}
    if result["decision"] == "fix_key" and blind_choice_oid not in result["accepted_oids"]:
        return {**result, "verdict": "needs_human", "decision": "needs_human", "accepted_oids": [],
                "reason": "Đánh giá mù độc lập không ủng hộ đáp án đề xuất: " + result["reason"]}
    return result


# ---------------------------------------------------------------- trạng thái hiển thị cho học sinh

def question_states(snap_q: dict, flags: list[dict], eff_q: dict | None, my_reports: list[dict]) -> dict:
    """Tách ba trạng thái độc lập: câu, lời giải, báo cáo. Một báo cáo mới gửi chưa có nghĩa là câu bị sai."""
    open_types = {f["flag_type"] for f in flags if f["status"] == "open"}
    eff_q = eff_q or {}
    final = None
    if eff_q.get("void"):
        final = ("voided", "Đã loại câu khỏi điểm")
    elif eff_q.get("key_oids") and len(eff_q["key_oids"]) > 1:
        final = ("multi_accepted", "Đã chấp nhận thêm phương án")
    elif eff_q.get("key_oids"):
        final = ("key_fixed", "Đã sửa đáp án")
    expl_fixed = bool(eff_q.get("explanation_fix"))
    last = eff_q.get("last")
    kept = bool(last and last["decision_type"] == "keep")
    if kept and not final:
        final = ("kept", "Giữ đáp án")
    question = {"code": "normal", "label": ""}
    if "answer_under_review" in open_types:
        question = {"code": "answer_under_review", "label": "Đáp án đang được xem lại"}
    elif final:
        question = {"code": final[0], "label": final[1]}
    explanation = {"code": "normal", "label": ""}
    if "explanation_under_review" in open_types:
        explanation = {"code": "under_review", "label": "Lời giải đang được xem lại"}
    elif expl_fixed:
        explanation = {"code": "fixed", "label": "Đã sửa lời giải"}
    report = None
    if my_reports:
        r = my_reports[-1]
        report = {"status": r["status"], "type": r["report_type"],
                  "label": {"received": "Đã nhận báo cáo", "reviewing": "Đang rà soát", "accepted": "Báo cáo được ghi nhận",
                            "kept": "Giữ kết quả hiện tại", "needs_human": "Chờ người rà soát",
                            "recorded": "Đã ghi nhận", "pending_error": "Đã nhận báo cáo, đang chờ xử lý"}[r["status"]]}
    return {"question": question, "explanation": explanation, "report": report}


# ---------------------------------------------------------------- quy tắc rút kinh nghiệm

RULE_SCOPES = ("question", "group", "general")


def validate_rule_proposal(out) -> tuple[dict | None, str | None]:
    """Đề xuất quy tắc phải đủ cụ thể: phạm vi, điều kiện kích hoạt, ví dụ phải chặn và phản ví dụ hợp lệ phải giữ."""
    if not isinstance(out, dict):
        return None, "không phải đối tượng"
    if out.get("scope") not in RULE_SCOPES:
        return None, "scope không hợp lệ"
    for f in ("condition", "guidance", "block_example", "keep_example"):
        if not isinstance(out.get(f), str) or len(out[f].strip()) < 8:
            return None, f"thiếu {f}"
    return {k: out[k].strip()[:400] if isinstance(out[k], str) else out[k] for k in
            ("scope", "condition", "guidance", "block_example", "keep_example")}, None


def rules_block(rules: list[dict]) -> str:
    """Chỉ quy tắc ĐÃ ĐƯỢC DUYỆT mới vào prompt (không bao giờ là nguyên văn báo cáo hay ghi chú AI chưa duyệt)."""
    if not rules:
        return ""
    nl = chr(10)
    lines = []
    for r in rules:
        lines.append(f"- [{r['scope']}] Khi: {r['condition']} -> {r['guidance']} "
                     f"(ví dụ cần chặn: {r['block_example']}; ví dụ hợp lệ phải giữ: {r['keep_example']})")
    return "QUY TẮC ĐÃ DUYỆT (áp dụng đúng phạm vi và điều kiện, không mở rộng):" + nl + nl.join(lines) + nl + nl


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def recompute_results(original: dict | None, new_recognition: float | None, d_score: float | None,
                      a_score: float | None, comparison_gap: float | None, legacy_confidence: float | None) -> dict:
    """Tính lại các kết quả dẫn xuất từ điểm Recognition mới. GIỮ NGUYÊN dự đoán/tự tin gốc. Không có
    Recognition hoặc thiếu D/A: không suy diễn (trả None)."""
    if new_recognition is None or d_score is None or a_score is None:
        return {"overall": None, "gap": None, "final_result": None, "state": "cannot_compute"}
    if original and original.get("formula_version") == scoring.FORMULA_VERSION:
        # Lượt công thức v3: tính trên số gốc, qua màn theo điểm kiến thức; Gap (từ dự đoán gốc và điểm tự luận) không đổi khi sửa Recognition.
        dec = scoring.decide_progress(new_recognition, d_score, a_score)
        return {"overall": scoring.calc_overall_v3(new_recognition, d_score, a_score), "gap": comparison_gap,
                "final_result": dec["final_result"], "decision": dec["decision"], "state": "ok"}
    overall = scoring.calc_overall(new_recognition, d_score, a_score)
    gap = comparison_gap
    if legacy_confidence is not None:                       # cách đo cũ: Gap phụ thuộc Overall nên đổi theo
        gap = scoring.calc_gap(legacy_confidence, overall)
    return {"overall": overall, "gap": gap, "final_result": scoring.determine_pass(overall, gap), "state": "ok"}
