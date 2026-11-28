"""Công thức tính điểm, phân loại PASS/RETRY và phát hiện illusion. Đây là
logic xác định kết quả cuối cùng nên luôn tính bằng code thuần, không để AI
tự quyết."""


from decimal import ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------- công thức v3 (lượt mới): số gốc, hiển thị 2 chữ số
FORMULA_VERSION = 4

# Cấu hình khởi đầu của quyết định qua màn (một nơi duy nhất; mở level, lưu tiến độ, nút bấm và đề xuất ôn đều dùng decide_progress).
PASS_OVERALL = Decimal("7")
REVIEW_OVERALL = Decimal("6")
SKILL_FLOOR = Decimal("5")
GAP_CLOSE = Decimal("1")
GAP_CLEAR = Decimal("2")

SKILL_NAMES = {"recognition": "Nhận biết", "distinction": "Phân biệt", "application": "Vận dụng"}


def _d(x) -> Decimal:
    return Decimal(str(x))


def round2(x) -> float:
    """Làm tròn 2 chữ số kiểu HALF_UP, CHỈ dùng để hiển thị/lưu; so ngưỡng luôn dùng số gốc chưa làm tròn."""
    return float(_d(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def overall_exact(recognition, distinction, application) -> Decimal:
    return (_d(recognition) + _d(distinction) + _d(application)) / 3


def calc_overall_v3(recognition, distinction, application) -> float:
    """Overall = (Recognition + Distinction + Application) / 3 trên số gốc, làm tròn 2 chữ số chỉ ở bước hiển thị."""
    return round2(overall_exact(recognition, distinction, application))


UNDERSTANDING_V3 = (
    (Decimal("4"), "NOT_ENOUGH_BASE", "Đang xây nền kiến thức"),
    (Decimal("6"), "PARTIAL", "Đã hiểu một phần, cùng củng cố thêm"),
    (Decimal("7"), "BASIC", "Hiểu cơ bản"),
    (Decimal("8.5"), "FAIRLY_SOLID", "Hiểu khá vững"),
)
UNDERSTANDING_TOP = ("SOLID", "Hiểu vững trong lượt này")


def understanding_v3(recognition, distinction, application) -> dict:
    """Mức hiểu qua bài làm, theo Overall gốc (so ngưỡng bằng tổng ba điểm để không dính sai số chia)."""
    total = _d(recognition) + _d(distinction) + _d(application)
    for bound, code, text in UNDERSTANDING_V3:
        if total < bound * 3:
            return {"code": code, "text": text}
    return {"code": UNDERSTANDING_TOP[0], "text": UNDERSTANDING_TOP[1]}


def _n(x) -> str:
    """Số hiển thị kiểu Việt, luôn 2 chữ số (0,00; 2,00; 1,25)."""
    return f"{round2(x):.2f}".replace(".", ",")


def decide_progress(recognition, distinction, application) -> dict:
    """Quyết định qua màn theo ĐIỂM KIẾN THỨC (số gốc). Gap không tham gia: nó chỉ quyết định phản hồi tự đánh giá.
    PASS: Overall >= 7 và mọi kỹ năng >= 5. PASS_WITH_REVIEW: 6 <= Overall < 7 và mọi kỹ năng >= 5 (qua kèm một mục tiêu ôn).
    RETRY: còn lại. Điểm chờ xác nhận/thiếu kết quả KHÔNG đi qua hàm này (xem trạng thái 'PENDING' ở nơi gọi)."""
    skills = {"recognition": _d(recognition), "distinction": _d(distinction), "application": _d(application)}
    total = sum(skills.values())
    low = [k for k, v in skills.items() if v < SKILL_FLOOR]
    weakest = min(skills, key=lambda k: (skills[k], list(skills).index(k)))
    reasons: list[str] = []
    if total < REVIEW_OVERALL * 3:
        decision = "RETRY"
        reasons.append(f"Overall {_n(total / 3)} chưa đạt {_n(REVIEW_OVERALL)}.")
    elif low:
        decision = "RETRY"
    elif total < PASS_OVERALL * 3:
        decision = "PASS_WITH_REVIEW"
    else:
        decision = "PASS"
    for k in low:
        reasons.append(f"{SKILL_NAMES[k]} {_n(skills[k])} dưới {_n(SKILL_FLOOR)}.")
    ov = _n(total / 3)
    if decision == "PASS":
        reasons = [f"Overall {ov} ≥ 7,00 và cả ba kỹ năng ≥ 5,00."]
    elif decision == "PASS_WITH_REVIEW":
        reasons = [f"Overall {ov} nằm trong khoảng 6,00–6,99 và cả ba kỹ năng ≥ 5,00: em được qua màn, kèm khuyến nghị ôn."]
    return {
        "decision": decision,
        "final_result": "RETRY" if decision == "RETRY" else "PASS",   # tương thích nơi cũ chỉ biết PASS/RETRY
        "reasons": reasons, "low_skills": low,
        "review_target": SKILL_NAMES[weakest] if decision in ("PASS_WITH_REVIEW", "RETRY") else None,
        "review_target_key": weakest if decision in ("PASS_WITH_REVIEW", "RETRY") else None,
        "thresholds": {"pass_overall": float(PASS_OVERALL), "review_overall": float(REVIEW_OVERALL), "skill_floor": float(SKILL_FLOOR)},
        "formula_version": FORMULA_VERSION,
    }


def describe_total_gap(gap: float | None, kind: str = "overall") -> str:
    target = "Overall (cả ba kỹ năng)" if kind == "overall" else "kết quả hai phần tự luận"
    if gap is None:
        return ""
    if gap == 0:
        return f"Dự đoán của em trùng khít với {target}."
    return f"Em dự đoán {'cao' if gap > 0 else 'thấp'} hơn {target} {_n(abs(_d(gap)))} điểm."


def calibration_v3(gap: float | None, skill_gaps: dict | None = None) -> dict:
    """Khả năng tự đánh giá theo Gap CÓ DẤU, mô tả theo lượt này (không gán nhãn tính cách)."""
    if gap is None:
        return {"code": "UNKNOWN", "text": "Chưa đánh giá: chưa đủ dữ liệu tính Confidence/Gap.", "offsetting": False}
    g = _d(gap)
    a = abs(g)
    if a <= GAP_CLOSE:
        code, text = "CLOSE", "Dự đoán tổng tương đối sát kết quả ở lượt này."
    elif a <= GAP_CLEAR:
        code = "HIGHER" if g > 0 else "LOWER"
        text = ("Ở lượt này, em dự đoán cao hơn kết quả một chút." if g > 0 else "Ở lượt này, em làm tốt hơn mức em dự đoán.")
    else:
        code = "MUCH_HIGHER" if g > 0 else "MUCH_LOWER"
        text = ("Lượt này em dự đoán cao hơn kết quả khá nhiều. Đây là thông tin để em điều chỉnh cách tự đánh giá." if g > 0
                else "Em làm tốt hơn mức em dự đoán khá nhiều. Em có thể tin tưởng bản thân hơn.")
    offsetting = False
    if skill_gaps and all(skill_gaps.get(k) is not None for k in ("distinction", "application")):
        gd, ga = _d(skill_gaps["distinction"]), _d(skill_gaps["application"])
        if gd * ga < 0 and abs(gd) > GAP_CLOSE and abs(ga) > GAP_CLOSE:
            offsetting = True
            hi, lo = ("Phân biệt", "Vận dụng") if gd > 0 else ("Vận dụng", "Phân biệt")
            text += (f" Hai kỹ năng lệch theo hai hướng bù trừ nhau: em dự đoán {hi} cao hơn và {lo} thấp hơn kết quả, "
                     "nên Gap tổng không phản ánh việc em tự đánh giá sát cả hai phần.")
    return {"code": code, "text": text, "offsetting": offsetting}


def calc_recognition(correct_answers: int, total: int = 20) -> float:
    return round((correct_answers / total) * 10, 1)


def calc_overall(recognition: float, distinction: float, application: float) -> float:
    return round((recognition + distinction + application) / 3, 1)


def calc_gap(confidence: float, overall: float) -> float:
    return round(confidence - overall, 1)


def classify_understanding(overall: float) -> str:
    if overall >= 8.0:
        return "WELL_UNDERSTOOD"
    if overall >= 6.0:
        return "PARTIALLY_UNDERSTOOD"
    if overall >= 4.0:
        return "LIMITED_UNDERSTANDING"
    return "NOT_YET_UNDERSTOOD"


def classify_illusion(gap: float) -> str:
    if gap > 1.0:
        return "DETECTED"
    if -gap > 1.0:
        return "UNDERCONFIDENT"
    return "CALIBRATED"


def determine_pass(overall: float, gap: float | None) -> str:
    """PASS khi Overall >= 7.0 và |gap| <= 1.0 (lệch quá 1.0 theo hướng nào cũng
    không đạt). classify_illusion() dùng dấu +/- của gap để phân biệt
    DETECTED/UNDERCONFIDENT chỉ cho mục đích hiển thị, không ảnh hưởng đến
    điều kiện PASS này.

    gap is None = chưa đánh giá được độ lệch (học sinh chọn 'chưa ước lượng được' ở ít nhất một kỹ năng
    trong cách đo hai dự đoán). Khi đó chỉ xét ngưỡng kiến thức Overall >= 7.0; việc không ước lượng được
    KHÔNG bị coi là lỗi và không ép RETRY."""
    if gap is None:
        return "PASS" if overall >= 7.0 else "RETRY"
    return "PASS" if overall >= 7.0 and abs(gap) <= 1.0 else "RETRY"


def detect_weakness(recognition: float, distinction: float, application: float) -> str:
    scores = {"recognition": recognition, "distinction": distinction, "application": application}
    mn, mx = min(scores.values()), max(scores.values())
    if (mx - mn) < 1.0:
        return "all_three"
    weak = [k for k, v in scores.items() if v == mn]
    return "_and_".join(weak)
