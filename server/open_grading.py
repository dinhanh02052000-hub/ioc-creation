"""Chấm tự luận Distinction / Application: hai lượt độc lập + lượt thứ ba khi độ lệch tổng > 0,75.

Phân công:
  - AI: cho điểm TỪNG TIÊU CHÍ dựa trên những gì học sinh thực sự viết, kèm đoạn trích nguyên văn làm bằng chứng.
  - CODE: kiểm schema và miền điểm (không ép, không làm tròn hộ), đối chiếu đoạn trích với bài làm, tự cộng tổng, so độ
    lệch bằng số chính xác (Decimal), quyết định có gọi lượt ba, chốt điểm (trung bình hai lượt / trung vị ba lượt) và
    dựng phản hồi từ kết quả đã chốt.
Toàn bộ hàm trong module này không gọi mạng trực tiếp; việc gọi AI được truyền vào qua `ask_fn`."""

from __future__ import annotations

import math
import re
from decimal import Decimal

from confidence import round2

RUBRIC_VERSION = "open-grading-v3"
THIRD_PASS_THRESHOLD = Decimal("0.75")     # lượt ba khi độ lệch tổng > 0,75 (KHÔNG phải >=)
STEP = Decimal("0.5")
CRITERION_FLAG_GAP = Decimal("1.0")        # cờ bất đồng tiêu chí khi hai lượt lệch từ 1,0 điểm
MAX_FORMAT_RETRIES = 2                      # thử lại một lượt chấm khi đầu ra sai định dạng
MAX_EXTRA_PASS_ATTEMPTS = 2                 # số lần bổ sung khi chưa đủ hai lượt hợp lệ

SKILLS = ("distinction", "application")

# Nguồn định nghĩa tiêu chí DUY NHẤT cho điểm tối đa; main.py kiểm tra trùng với DISTINCTION_CRITERIA/APPLICATION_CRITERIA.
CRITERIA = {
    "distinction": {"hieu_goc": 2, "ngu_canh": 2, "doi_nghia": 2, "phan_biet": 2, "so_sanh": 2},
    "application": {"chon_tu": 2, "dung_dung": 3, "tinh_huong": 2, "giai_thich": 3},
}

# Mốc điểm từng tiêu chí (ranh giới giữa hai mức liền nhau). 0,5 chỉ dùng khi bài nằm GIỮA hai mức: nghiêng về mức
# thấp hơn thì cho mức thấp + 0,5 và nêu trong score_reason phần còn thiếu để chưa lên mức cao.
BANDS = {
    "hieu_goc": {
        0: "không giải thích nghĩa của từ gốc (chỉ nhắc lại từ tiếng Anh, bỏ trống) hoặc nghĩa sai hoàn toàn",
        1: "có nêu nghĩa nhưng mơ hồ, quá chung hoặc chỉ đúng một phần",
        2: "nêu đúng nghĩa của từ gốc, rõ ràng (diễn đạt qua tình huống vẫn tính)",
    },
    "ngu_canh": {
        0: "không nối từ gốc với chi tiết nào của đề (chỉ chép một cụm trong đề, không giải thích, vẫn là 0)",
        1: "có nhắc chi tiết của đề nhưng liên hệ yếu, chưa nói vì sao từ đó phù hợp",
        2: "nối rõ một chi tiết của đề với lý do từ gốc phù hợp",
    },
    "doi_nghia": {
        0: "không nói người đọc sẽ hiểu khác đi thế nào khi thay từ (chỉ dịch hai bản rời rạc không tính)",
        1: "có nêu sự thay đổi nhưng mơ hồ hoặc chỉ đúng một phần",
        2: "nêu rõ, đúng nghĩa/sắc thái thay đổi khi thay bằng từ được hỏi",
    },
    "phan_biet": {
        0: "không thể hiện ranh giới nghĩa/cách dùng của hai từ (chỉ nói 'hai từ khác nhau') hoặc sai",
        1: "ranh giới đúng một phần hoặc còn lẫn nhẹ",
        2: "ranh giới nghĩa/cách dùng của hai từ chính xác",
    },
    "so_sanh": {
        0: "không có kết luận kèm lý do (chỉ 'X sounds better')",
        1: "có kết luận và lý do nhưng chung chung, thiếu dữ kiện của đề",
        2: "kết luận rõ kèm lý do cụ thể gắn với câu",
    },
    "chon_tu": {
        0: "không chọn từ nào hoặc từ chọn không phù hợp với dữ kiện của đề",
        1: "từ chọn chấp nhận được nhưng ít căn cứ hoặc ngang với từ khác",
        2: "từ chọn phù hợp rõ với dữ kiện của đề (khác đáp án mục tiêu vẫn nhận nếu bài làm hỗ trợ)",
    },
    "dung_dung": {
        0: "không có câu tiếng Anh dùng từ (chỉ 'I choose X', viết tiếng Việt, hoặc không thành câu)",
        1: "có câu nhưng dùng sai nghĩa hoặc lỗi nặng làm sai ý",
        2: "câu dùng đúng nghĩa nhưng còn lỗi ngữ pháp/kết hợp từ đáng kể",
        3: "câu đúng nghĩa và đúng ngữ pháp, minh họa đúng cách dùng của từ",
    },
    "tinh_huong": {
        0: "câu không liên quan tới tình huống của đề",
        1: "bám tình huống chung chung hoặc thiếu dữ kiện có giá trị phân biệt",
        2: "bám dữ kiện có giá trị phân biệt (không cần chép mọi chi tiết phụ như tên, thời lượng, địa điểm)",
    },
    "giai_thich": {
        0: "không có lý do, hoặc lý do rỗng/chung chung ('it is good')",
        1: "có lý do nhưng chưa nối nghĩa của từ với chi tiết của đề",
        2: "nối nghĩa của từ với chi tiết của đề nhưng chưa so sánh (khi đề yêu cầu) hoặc còn thiếu ý",
        3: "lý do cụ thể, nối nghĩa của từ với chi tiết của đề và so sánh với lựa chọn khác khi đề yêu cầu",
    },
}

MISSING_STATES = ("sufficient", "partial_missing", "completely_missing", "incorrect", "mixed")

LABELS = {
    "hieu_goc": "Hiểu từ gốc", "ngu_canh": "Phù hợp ngữ cảnh", "doi_nghia": "Thay đổi nghĩa",
    "phan_biet": "Phân biệt ngữ nghĩa", "so_sanh": "Lập luận so sánh",
    "chon_tu": "Chọn từ đúng", "dung_dung": "Dùng đúng", "giai_thich": "Giải thích hợp lý", "tinh_huong": "Phù hợp tình huống",
}

# ---------------------------------------------------------------- số chính xác & độ lệch


def D(x) -> Decimal:
    return Decimal(str(x))


def total_of(scores: dict) -> Decimal:
    return sum((D(v) for v in scores.values()), Decimal("0"))


def deviation(total_a, total_b) -> Decimal:
    """Độ lệch tổng trên GIÁ TRỊ GỐC (trước khi làm tròn hiển thị)."""
    return abs(D(total_a) - D(total_b))


def needs_third_pass(total_a, total_b) -> bool:
    """Bắt buộc lượt ba khi độ lệch > 0,75. Đúng 0,75 hoặc nhỏ hơn thì không. Không làm tròn trước khi so."""
    return deviation(total_a, total_b) > THIRD_PASS_THRESHOLD


# ---------------------------------------------------------------- kiểm tra đầu ra của một lượt AI

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", str(text)).strip().casefold()


def quote_in_answer(quote, answer: str) -> bool:
    """Đoạn trích phải xuất hiện NGUYÊN VĂN trong bài (chuẩn hóa khoảng trắng/xuống dòng/hoa-thường khi đối chiếu, giữ
    nguyên từ ngữ). Chỉ chứng minh nguồn của trích dẫn, không chứng minh lập luận đúng."""
    if not isinstance(quote, str) or not quote.strip():
        return False
    return _norm(quote) in _norm(answer)


def _valid_score(v, max_score: int) -> bool:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return False
    d = D(v)
    return Decimal("0") <= d <= Decimal(max_score) and (d / STEP) == (d / STEP).to_integral_value()


def validate_skill_output(raw, skill: str, answer: str) -> tuple[dict | None, list[str]]:
    """Xác thực MỘT kỹ năng của MỘT lượt. Trả ({scores, records, total}, []) hoặc (None, danh sách lỗi cụ thể).
    Không sửa hộ: điểm vượt trần không bị ép xuống trần, trường thiếu không bị đổi thành 0, chuỗi số không được ép kiểu."""
    errors: list[str] = []
    crit = CRITERIA[skill]
    items = raw.get("criteria") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return None, [f"{skill}: thiếu danh sách criteria (phải là danh sách bản ghi theo từng tiêu chí)."]
    seen: dict[str, dict] = {}
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("criterion"), str):
            errors.append(f"{skill}: mỗi phần tử criteria phải là đối tượng có trường criterion.")
            continue
        code = it["criterion"]
        if code not in crit:
            errors.append(f"{skill}: tiêu chí '{code}' không thuộc bài này (chỉ gồm {', '.join(crit)}).")
            continue
        if code in seen:
            errors.append(f"{skill}: tiêu chí {code} xuất hiện nhiều hơn một lần.")
            continue
        seen[code] = it
    for code in crit:
        if code not in seen:
            errors.append(f"{skill}: thiếu tiêu chí {code}.")
    for code, it in seen.items():
        mx = crit[code]
        sc = it.get("score")
        if not _valid_score(sc, mx):
            errors.append(f"{code}: score phải là số từ 0 đến {mx}, đúng bước 0,5 (không ép về trần, không dùng chuỗi).")
            continue
        ev = it.get("evidence")
        if not isinstance(ev, list) or any(not isinstance(e, str) for e in ev):
            errors.append(f"{code}: evidence phải là danh sách đoạn trích (có thể rỗng).")
            continue
        miss = it.get("missing_or_incorrect")
        if miss not in MISSING_STATES:
            errors.append(f"{code}: missing_or_incorrect phải là một trong {', '.join(MISSING_STATES)}.")
            continue
        for f in ("assessment", "score_reason"):
            if not isinstance(it.get(f), str) or not it[f].strip():
                errors.append(f"{code}: thiếu {f}.")
        hint = it.get("hint")
        if hint is not None and not isinstance(hint, str):
            errors.append(f"{code}: hint phải là chuỗi hoặc null.")
        benefit = it.get("benefit")
        if benefit is not None and not isinstance(benefit, str):
            errors.append(f"{code}: benefit phải là chuỗi hoặc null.")
        d = D(sc)
        if d < Decimal(mx) and not (isinstance(hint, str) and hint.strip()):
            errors.append(f"{code}: điểm dưới tối đa phải kèm hint là MỘT thao tác sửa cụ thể trên bài của học sinh.")
        if d > 0 and not ev:
            errors.append(f"{code}: điểm {sc} > 0 bắt buộc kèm ít nhất một đoạn trích nguyên văn trong evidence.")
        if miss in ("incorrect", "mixed") and not ev:
            errors.append(f"{code}: kết luận '{miss}' phải trích phần sai trong evidence.")
        if d < Decimal(mx) and miss == "sufficient":
            errors.append(f"{code}: điểm dưới tối đa không thể là 'sufficient'; nêu phần còn thiếu hoặc sai.")
        if d == Decimal(mx) and miss != "sufficient":
            errors.append(f"{code}: điểm tối đa phải có missing_or_incorrect='sufficient'.")
        bad = [e for e in ev if not quote_in_answer(e, answer)]
        if bad:
            errors.append(f"{code}: đoạn trích không có nguyên văn trong bài của học sinh: {bad[0][:80]!r}.")
    if errors:
        return None, errors
    scores = {code: float(D(seen[code]["score"])) for code in crit}
    records = [{
        "criterion": code, "score": scores[code], "evidence": list(seen[code]["evidence"]),
        "assessment": seen[code]["assessment"].strip(), "missing_or_incorrect": seen[code]["missing_or_incorrect"],
        "score_reason": seen[code]["score_reason"].strip(), "hint": (seen[code].get("hint") or "").strip() or None,
        "benefit": (seen[code].get("benefit") or "").strip() or None,
    } for code in crit]
    return {"scores": scores, "records": records, "total": float(total_of(scores))}, []


# ---------------------------------------------------------------- bài trống: code cho 0 theo rubric, không gọi AI

def empty_result(skill: str) -> dict:
    crit = CRITERIA[skill]
    records = [{"criterion": c, "score": 0.0, "evidence": [], "assessment": "Học sinh chưa viết nội dung cho phần này.",
                "missing_or_incorrect": "completely_missing", "score_reason": "Bài trống theo rubric.", "hint": None}
               for c in crit]
    return {"scores": {c: 0.0 for c in crit}, "records": records, "total": 0.0}


def is_blank(answer) -> bool:
    return not isinstance(answer, str) or not answer.strip()


# ---------------------------------------------------------------- chốt điểm

def _median3(a, b, c) -> Decimal:
    return sorted([D(a), D(b), D(c)])[1]


def finalize_skill(skill: str, passes: list[dict]) -> dict:
    """2 lượt hợp lệ: trung bình TỪNG TIÊU CHÍ (giữ giá trị trung gian như 1,25), rồi cộng. 3 lượt hợp lệ: trung vị từng
    tiêu chí rồi cộng. Điểm tổng lưu chính xác (total_exact) và điểm hiển thị làm tròn một quy tắc (HALF_UP)."""
    crit = CRITERIA[skill]
    if len(passes) == 2:
        final = {c: (D(passes[0]["scores"][c]) + D(passes[1]["scores"][c])) / 2 for c in crit}
        method = "mean_of_two"
    elif len(passes) == 3:
        final = {c: _median3(*(p["scores"][c] for p in passes)) for c in crit}
        method = "median_of_three"
    else:
        raise ValueError("Cần đúng 2 hoặc 3 lượt chấm hợp lệ để chốt điểm.")
    total = sum(final.values(), Decimal("0"))
    return {
        "scores": {c: float(v) for c, v in final.items()}, "total_exact": float(total), "total": round2(total),
        "method": method, "flags": criterion_flags(skill, passes),
    }


def criterion_flags(skill: str, passes: list[dict]) -> list[dict]:
    """Cờ bất đồng theo TIÊU CHÍ (dùng để rà rubric và kiểm soát nhận xét; KHÔNG kích hoạt lượt ba)."""
    flags = []
    for c in CRITERIA[skill]:
        vals = [D(p["scores"][c]) for p in passes]
        spread = max(vals) - min(vals)
        zero_vs_evidence = any(v == 0 for v in vals) and any(
            v > 0 and p["records"][list(CRITERIA[skill]).index(c)]["evidence"] for v, p in zip(vals, passes))
        if spread >= CRITERION_FLAG_GAP or zero_vs_evidence:
            flags.append({"criterion": c, "scores": [float(v) for v in vals], "spread": float(spread)})
    return flags


# ---------------------------------------------------------------- phản hồi từ KẾT QUẢ ĐÃ CHỐT

STATE_TEXT = {"completely_missing": "em chưa nêu phần này", "partial_missing": "em mới nêu một phần",
              "incorrect": "có phát biểu chưa đúng", "mixed": "có phần đúng nhưng còn phần sai hoặc thiếu",
              "sufficient": "chưa đạt mức tối đa"}


def compose_feedback(skill: str, final: dict, passes: list[dict], answer: str | None = None) -> str:
    """Ba mục tách chức năng, dựng từ KẾT QUẢ ĐÃ CHỐT (không nhìn Confidence):
    - Điều làm được: MỘT năng lực cụ thể + đoạn trích có thật từ bài của học sinh (không kể lại điểm, không khen chung).
    - Cần cải thiện: một hoặc hai thiếu sót ảnh hưởng nhiều nhất: tiêu chí, bài hiện đã làm được gì, phần thiếu/sai, bổ sung thì tốt hơn thế nào.
    - Gợi ý sửa: một thao tác làm ngay trên bài. Bài đủ điểm: gợi ý chỉ là mở rộng tự chọn, không bịa lỗi.
    Nội dung lấy từ lượt có điểm GẦN điểm đã chốt nhất ở từng tiêu chí; tiêu chí có cờ bất đồng không đưa lời phê chắc chắn."""
    crit = CRITERIA[skill]
    codes = list(crit)
    flagged = {f["criterion"] for f in final["flags"]}

    def rec(code: str) -> dict:
        idx = codes.index(code)
        best = min(passes, key=lambda p: abs(D(p["scores"][code]) - D(final["scores"][code])))
        return best["records"][idx]

    ratios = {c: D(final["scores"][c]) / Decimal(crit[c]) for c in codes}
    strong = [c for c in codes if ratios[c] > 0 and c not in flagged and rec(c)["evidence"]]
    strong.sort(key=lambda c: (-ratios[c], codes.index(c)))
    lost = [c for c in codes if D(final["scores"][c]) < Decimal(crit[c])]
    lost.sort(key=lambda c: (-(Decimal(crit[c]) - D(final["scores"][c])), codes.index(c)))

    lines = []
    if strong:
        c = strong[0]
        r = rec(c)
        lines.append(f"**Điểm làm được ({LABELS[c]}):** {r['assessment']} (từ bài của em: «{r['evidence'][0]}»)")
    elif answer is not None and not is_blank(answer):
        lines.append("**Điểm làm được:** em đã viết một câu trả lời cho phần này, nhưng chưa có tiêu chí nào đủ bằng chứng chắc chắn "
                     "trong bài để ghi nhận; em điều chỉnh theo phần cần cải thiện bên dưới.")
    else:
        lines.append("**Điểm làm được:** em chưa nhập câu trả lời nên chưa có nội dung để ghi nhận.")

    if not lost:
        lines.append("**Cần cải thiện:** bài đã đáp ứng đủ mọi tiêu chí của phần này.")
        lines.append("**Gợi ý (tự chọn, không ảnh hưởng điểm):** em thử áp dụng cách trình bày tương tự cho một tình huống khác để giữ vững kỹ năng.")
        return "\n".join(lines)

    if answer is not None and is_blank(answer):
        lines.append("**Cần cải thiện:** em chưa nhập câu trả lời cho phần này.")
        lines.append("**Gợi ý:** em bắt đầu bằng một câu ngắn trả lời đúng điều đề hỏi, rồi nối nó với một chi tiết trong đề.")
        return "\n".join(lines)

    shown = lost[:1] + [c for c in lost[1:2] if D(crit[c]) - D(final["scores"][c]) >= Decimal("1")]
    hints = []
    for c in shown:
        if c in flagged:
            lines.append(f"**Cần cải thiện ({LABELS[c]}):** ở tiêu chí này các lượt chấm chưa thống nhất nên hệ thống chưa kết luận chắc "
                         "về lỗi cụ thể; em bổ sung ý còn thiếu cho rõ hơn rồi so lại với đáp án tham khảo.")
            continue
        r = rec(c)
        state = STATE_TEXT[r["missing_or_incorrect"]]
        wrong = f" (đoạn liên quan: «{r['evidence'][0]}»)" if r["missing_or_incorrect"] in ("incorrect", "mixed") and r["evidence"] else ""
        benefit = f" {r['benefit']}" if r.get("benefit") else ""
        lines.append(f"**Cần cải thiện ({LABELS[c]}):** {state}. {r['score_reason']}{wrong}{benefit}")
        if r.get("hint"):
            hints.append(r["hint"])
    lines.append("**Gợi ý sửa:** " + (hints[0] if hints else "em thử bổ sung đúng ý còn thiếu ở tiêu chí này, bám vào chi tiết trong đề."))
    return "\n".join(lines)


def grading_detail(skill: str, st: dict) -> dict | None:
    """Bảng điểm từng lượt AI theo tiêu chí để học sinh thấy điểm gốc. Chỉ trả khi bài đã chốt. Không có prompt hay suy luận nội bộ:
    mỗi ô chỉ gồm điểm, đoạn trích nguyên văn từ bài của học sinh và lý do ngắn do chính lượt chấm đó ghi."""
    final = st.get("final")
    if not final:
        return None
    crit = CRITERIA[skill]
    codes = list(crit)
    passes = st["passes"]
    flagged = {f["criterion"] for f in final.get("flags", [])}
    rows = []
    for i, c in enumerate(codes):
        rows.append({
            "key": c, "label": LABELS[c], "max": crit[c], "final": final["scores"][c], "flagged": c in flagged,
            "bands": {str(k): v for k, v in BANDS[c].items()},
            "passes": [{"score": p["scores"][c], "evidence": list(p["records"][i]["evidence"][:2]),
                        "reason": p["records"][i]["score_reason"], "assessment": p["records"][i]["assessment"]} for p in passes],
        })
    totals = [round2(p["total"]) for p in passes]
    return {
        "skill": skill, "criteria": rows, "pass_totals": totals, "final_total": final["total"], "method": final["method"],
        "pass_count": len(passes), "third_pass": len(passes) == 3, "deviation": st.get("deviation"),
        "final_differs_from_every_pass": bool(len(passes) == 3 and final["total"] not in totals),
        "threshold": float(THIRD_PASS_THRESHOLD), "stored": True,
    }


# ---------------------------------------------------------------- trạng thái chấm một bài (để tiếp tục / thử lại)

def new_skill_state(skill: str, answer: str, question: str) -> dict:
    st = {"skill": skill, "question": question, "answer": answer, "passes": [], "status": "pending_pass", "final": None,
          "deviation": None, "third_required": False, "model_answer": "", "flags": []}
    if is_blank(answer):
        st["passes"] = [empty_result(skill)]
        st["status"] = "empty"
        st["final"] = {**finalize_empty(skill)}
    return st


def finalize_empty(skill: str) -> dict:
    e = empty_result(skill)
    return {"scores": e["scores"], "total_exact": 0.0, "total": 0.0, "method": "empty_by_rule", "flags": []}


def refresh_status(st: dict) -> None:
    """Cập nhật trạng thái theo số lượt hợp lệ ĐÃ CÓ. Không bao giờ công bố điểm khi chưa đủ điều kiện."""
    if st["status"] == "empty":
        return
    valid = st["passes"]
    st["final"] = None
    if len(valid) < 2:
        st["status"] = "pending_pass"          # chưa đủ hai lượt hợp lệ -> chưa tuyên bố đã chấm đối chiếu
        st["deviation"] = None
        st["third_required"] = False
        return
    dev = deviation(valid[0]["total"], valid[1]["total"])
    st["deviation"] = float(dev)
    st["third_required"] = dev > THIRD_PASS_THRESHOLD
    if st["third_required"] and len(valid) < 3:
        st["status"] = "pending_third_pass"    # lưu hai kết quả hợp lệ, KHÔNG công bố trung bình hai lượt
        return
    use = valid[:3] if st["third_required"] else valid[:2]
    st["final"] = finalize_skill(st["skill"], use)
    st["flags"] = st["final"]["flags"]
    st["status"] = "final"
    st["feedback"] = compose_feedback(st["skill"], st["final"], use, st.get("answer"))


# ---------------------------------------------------------------- điều phối các lượt chấm (gọi AI qua ask_fn)

def _parse_json(text: str) -> dict:
    from ai_json import parse_ai_json
    return parse_ai_json(text)


def run_one_pass(ask_fn, kb_text: str, lessons: list[str] | None, skills: list[str], states: dict, include_model: bool,
                 model: str | None = None, effort: str | None = None, role: str | None = None) -> dict[str, tuple[dict | None, list[str]]]:
    """MỘT lượt chấm độc lập cho các bài trong `skills`. Prompt chỉ chứa đề, bài làm, KB, rubric (không điểm/nhận xét của
    lượt khác, không Confidence). Đầu ra sai định dạng/miền điểm/trích dẫn là LỖI LƯỢT CHẤM: thử lại hữu hạn kèm lý do cần sửa.
    Trả {skill: (kết quả hợp lệ | None, lỗi cuối cùng)}; kèm kết quả 'model_answer' nếu có."""
    import engine_prompts as ep
    from ai_client import AIProviderError, AIRateLimitError

    result: dict[str, tuple[dict | None, list[str]]] = {s: (None, []) for s in skills}
    pending = list(skills)
    errors: dict[str, list[str]] | None = None
    models: dict = {}
    for attempt in range(1 + MAX_FORMAT_RETRIES):
        if not pending:
            break
        parts = [{"skill": s, "question": states[s]["question"], "answer": states[s]["answer"]} for s in pending]
        prompt = ep.open_grading_prompt(kb_text, parts, lessons, include_model and attempt == 0 or (include_model and not models),
                                        errors)
        try:
            import ai_router
            ai_router.set_role(role or "grade")
            data = _parse_json(ask_fn(prompt, reasoning_effort=effort or "low", model=model))
        except AIRateLimitError:
            raise
        except (AIProviderError, ValueError) as e:
            errors = {s: [f"đầu ra không phải JSON hợp lệ hoặc lỗi gọi AI: {str(e)[:120]}"] for s in pending}
            for s in pending:
                result[s] = (None, errors[s])
            continue
        if isinstance(data.get("reference"), dict):
            models = {k: v for k, v in data["reference"].items() if isinstance(v, str) and v.strip()}
        still, errors = [], {}
        for s in pending:
            ok, errs = validate_skill_output(data.get(s), s, states[s]["answer"])
            if ok:
                if role:
                    ok["role"] = role                      # khâu đã chấm lượt này (grade_1/grade_2/grade_3), để biết lượt nào do model nào
                result[s] = (ok, [])
            else:
                result[s] = (None, errs)
                errors[s] = errs
                still.append(s)
        pending = still
    if models:
        for s in skills:
            if result[s][0] is not None:
                result[s][0]["model"] = {"d": models.get("d_model", ""), "a": models.get("a_model", "")}
    return result


def advance(states: dict, ask_fn, kb_text: str, lessons: list[str] | None, third_model: str | None = None,
            pass_models: dict | None = None, efforts: dict | None = None) -> None:
    """Làm tiếp phần còn thiếu (idempotent; gọi lại để thử lại riêng lượt lỗi): đủ hai lượt hợp lệ -> so độ lệch -> lượt ba CHỈ
    cho bài lệch > 0,75 -> chốt. Lượt lỗi không được tính vào so độ lệch; hai kết quả hợp lệ luôn được giữ."""
    from concurrent.futures import ThreadPoolExecutor

    pass_models, efforts = pass_models or {}, efforts or {}
    third_model = pass_models.get("grade_3") or third_model

    def slot_role(need_skills: list[str]) -> str:
        """Lượt thiếu: khâu CHƯA dùng ở bài có ít lượt nhất (lượt lỗi được chấm bù đúng model còn thiếu, không đổi vai)."""
        weakest = min(need_skills, key=lambda k: len(states[k]["passes"]))
        used = {p.get("role") for p in states[weakest]["passes"]}
        return next((r for r in ("grade_1", "grade_2") if r not in used), "grade_2")

    active = [s for s in SKILLS if states[s]["status"] != "empty"]
    # Giai đoạn 1: đủ hai lượt hợp lệ cho từng bài.
    for attempt in range(1 + MAX_EXTRA_PASS_ATTEMPTS):
        need = [s for s in active if len(states[s]["passes"]) < 2]
        if not need:
            break
        first_model = not any(states[s].get("model_answer") for s in SKILLS)
        if attempt == 0 and all(len(states[s]["passes"]) == 0 for s in need):
            with ThreadPoolExecutor(max_workers=2) as ex:
                roles = ("grade_1", "grade_2")
                futs = [ex.submit(run_one_pass, ask_fn, kb_text, lessons, need, states, first_model and i == 0,
                                  pass_models.get(roles[i]), efforts.get(roles[i]), roles[i]) for i in range(2)]
                outs = [f.result() for f in futs]
        else:
            role = slot_role(need)
            outs = [run_one_pass(ask_fn, kb_text, lessons, need, states, first_model, pass_models.get(role), efforts.get(role), role)]
        for out in outs:
            for s in need:
                rec, _errs = out[s]
                if rec is not None and len(states[s]["passes"]) < 2:
                    states[s]["passes"].append(rec)
                    if rec.get("model"):
                        states[s]["model_answer"] = rec["model"]["d" if s == "distinction" else "a"]
    for s in active:
        refresh_status(states[s])
    # Giai đoạn 2: lượt ba độc lập CHỈ cho bài lệch > 0,75 (không thấy kết quả hai lượt đầu).
    need3 = [s for s in active if states[s]["status"] == "pending_third_pass"]
    for _ in range(1 + MAX_EXTRA_PASS_ATTEMPTS):
        if not need3:
            break
        out = run_one_pass(ask_fn, kb_text, lessons, need3, states, include_model=False, model=third_model,
                           effort=efforts.get("grade_3"), role="grade_3")
        for s in need3:
            rec, _errs = out[s]
            if rec is not None and len(states[s]["passes"]) < 3:
                states[s]["passes"].append(rec)
        for s in need3:
            refresh_status(states[s])
        need3 = [s for s in active if states[s]["status"] == "pending_third_pass"]
    for s in SKILLS:
        st = states[s]
        if st["status"] == "empty" and "feedback" not in st:
            st["feedback"] = ("**Điểm làm được:** em chưa nhập câu trả lời nên chưa có nội dung để ghi nhận.\n"
                              "**Cần cải thiện:** em chưa nhập câu trả lời cho phần này.\n"
                              "**Gợi ý:** em bắt đầu bằng một câu ngắn trả lời đúng điều đề hỏi, rồi nối nó với một chi tiết trong đề.")


# ---------------------------------------------------------------- đáp án tham khảo: kiểm bằng code trước khi hiện

_VI_CHARS = re.compile(r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", re.I)


def validate_reference(skill: str, text) -> str | None:
    """Trả None nếu đạt, hoặc lý do. Code chỉ kiểm cấu trúc/ngôn ngữ (đủ trường, câu tiếng Anh, giải thích tiếng Việt); ý nghĩa và ngữ pháp
    do AI soạn theo đúng phiên bản đề, nên khi lỗi thì chỉ tạo lại riêng bản mẫu, KHÔNG đụng tới điểm đã chấm."""
    if not isinstance(text, str) or len(text.strip()) < 40:
        return "đáp án tham khảo trống hoặc quá ngắn"
    t = text.strip()
    if skill == "distinction":
        if not _VI_CHARS.search(t):
            return "phần phân tích cần viết tiếng Việt"
        return None
    m_en = re.search(r"\*\*Câu tiếng Anh:\*\*\s*(.+)", t)
    m_vi = re.search(r"\*\*Giải thích:\*\*\s*(.+)", t, re.S)
    if not m_en or not m_vi:
        return "thiếu '**Câu tiếng Anh:**' hoặc '**Giải thích:**'"
    en = m_en.group(1).split("\n")[0].strip()
    if len(en.split()) < 5 or _VI_CHARS.search(en) or not re.search(r"[.!?]['\"”’)]*$", en):
        return "câu tiếng Anh phải là MỘT câu hoàn chỉnh bằng tiếng Anh"
    if not _VI_CHARS.search(m_vi.group(1)):
        return "phần giải thích cần viết tiếng Việt"
    return None
