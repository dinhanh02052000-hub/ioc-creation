"""Bước Confidence đo bằng HAI dự đoán riêng (Distinction, Application) + căn cứ tự khai.

Nguyên tắc: điểm dự đoán là điều HỌC SINH chọn; code lưu nguyên giá trị và tính độ lệch bằng công thức xác định.
AI không chấm, không chỉnh dự đoán, không suy đoán tâm lý. Toàn bộ hàm ở đây là hàm thuần, không gọi mạng."""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

MEASURE_TWO_SKILL = "two_skill_v2"      # cách đo mới (2 dự đoán)
MEASURE_LEGACY = "single_v1"            # Confidence chung cũ, giữ nguyên để đọc lịch sử

SKILLS = ("distinction", "application")
STATUS_SCORED = "scored"
STATUS_UNSURE = "unsure"

REASON_IDS = (
    "familiar", "understood_after_explanation", "explained_before", "used_before", "not_enough_basis", "other",
)
MAX_REASONS = 2
MAX_NOTE_CHARS = 500

# Gap lệch tối đa mà vẫn coi là "sát" (cùng ngưỡng PASS hiện hành trong scoring.determine_pass).
GAP_TOLERANCE = 1.0


class ConfidenceError(ValueError):
    """Dữ liệu dự đoán sai (máy chủ trả 422 với thông điệp dễ hiểu)."""


def round1(x: float) -> float:
    """Làm tròn 1 chữ số thập phân kiểu HALF_UP (0,25 -> 0,3; -0,25 -> -0,3), nhất quán giữa máy chủ và UI
    (UI hiển thị đúng số máy chủ trả, không tự tính lại)."""
    return float(Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def round2(x: float) -> float:
    """Làm tròn 2 chữ số HALF_UP cho công thức v3 (chỉ ở bước hiển thị/lưu)."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


FORMULA_V3 = 3
SOURCE_TWO_SKILL = "two_skill_average"
SOURCE_JOINT = "joint_direct"


def _valid_score(v) -> bool:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    if not math.isfinite(v) or not (0 <= v <= 10):
        return False
    return round(v * 2) == v * 2


def normalize_input(predictions, reasons, note, allow_legacy: bool = False) -> dict:
    """Xác thực phía máy chủ. Trả 'inputs' chuẩn hóa (dùng để lưu và so sánh khi gửi lại).
    Không biến thiếu thành 0 hoặc 5; 'chưa ước lượng được' không được kèm điểm."""
    if not isinstance(predictions, dict):
        raise ConfidenceError("Cần quyết định cho cả hai kỹ năng (Phân biệt và Vận dụng).")
    if not allow_legacy:
        # Lượt mới: BẮT BUỘC có điểm dự đoán cho cả hai kỹ năng bằng thanh kéo (không còn 'chưa ước lượng được', không có dự đoán chung)
        # để luôn tính được Confidence và Gap. allow_legacy chỉ để đọc lại bản ghi cũ.
        if set(predictions) != set(SKILLS):
            raise ConfidenceError("Cần đúng hai mục dự đoán: distinction và application.")
        for sk in SKILLS:
            p = predictions[sk]
            if not isinstance(p, dict) or p.get("status") != STATUS_SCORED:
                raise ConfidenceError("Cần chọn điểm dự đoán cho cả Phân biệt và Vận dụng bằng thanh kéo.")
    joint_raw = predictions.get("joint")
    if set(predictions) - {"joint"} != set(SKILLS):
        raise ConfidenceError("Cần đúng hai mục dự đoán: distinction và application (kèm joint nếu có).")
    out: dict[str, dict] = {}
    for skill in SKILLS:
        p = predictions[skill]
        if not isinstance(p, dict):
            raise ConfidenceError(f"Dự đoán '{skill}' sai định dạng.")
        status = p.get("status")
        if status == STATUS_SCORED:
            if not _valid_score(p.get("score")):
                raise ConfidenceError("Điểm dự đoán phải là số từ 0 đến 10, bước 0,5.")
            out[skill] = {"status": STATUS_SCORED, "score": float(p["score"])}
        elif status == STATUS_UNSURE:
            if p.get("score") is not None:
                raise ConfidenceError("Đã chọn 'chưa ước lượng được' thì không gửi kèm điểm số.")
            out[skill] = {"status": STATUS_UNSURE, "score": None}
        else:
            raise ConfidenceError("Mỗi kỹ năng cần một quyết định: chọn điểm hoặc 'chưa ước lượng được'.")

    # Dự đoán chung (kết quả trung bình của hai bài): chỉ có nghĩa khi chưa đủ hai dự đoán riêng. Đủ hai dự đoán riêng thì máy chủ tự
    # lấy trung bình và bỏ qua dự đoán chung (không lưu hai nguồn cùng lúc).
    both_scored = all(out[sk]["status"] == STATUS_SCORED for sk in SKILLS)
    joint = None
    if joint_raw is not None and not both_scored:
        if not isinstance(joint_raw, dict):
            raise ConfidenceError("Dự đoán chung sai định dạng.")
        jst = joint_raw.get("status")
        if jst == STATUS_SCORED:
            if not _valid_score(joint_raw.get("score")):
                raise ConfidenceError("Dự đoán chung phải là số từ 0 đến 10, bước 0,5.")
            joint = {"status": STATUS_SCORED, "score": float(joint_raw["score"])}
        elif jst == STATUS_UNSURE:
            if joint_raw.get("score") is not None:
                raise ConfidenceError("Đã chọn 'chưa ước lượng được' thì không gửi kèm điểm số.")
            joint = {"status": STATUS_UNSURE, "score": None}
        else:
            raise ConfidenceError("Dự đoán chung cần một quyết định: chọn điểm hoặc 'chưa ước lượng được'.")

    if reasons is None:
        reasons = []
    if not isinstance(reasons, list) or any(not isinstance(r, str) for r in reasons):
        raise ConfidenceError("Căn cứ dự đoán phải là danh sách lựa chọn có sẵn.")
    if len(set(reasons)) != len(reasons):
        raise ConfidenceError("Căn cứ dự đoán bị lặp.")
    if len(reasons) > MAX_REASONS:
        raise ConfidenceError(f"Chỉ được chọn tối đa {MAX_REASONS} căn cứ.")
    if any(r not in REASON_IDS for r in reasons):
        raise ConfidenceError("Có căn cứ không nằm trong danh sách lựa chọn.")

    if note is not None and not isinstance(note, str):
        raise ConfidenceError("Ghi chú phải là văn bản.")
    note = (note or "").strip()
    if len(note) > MAX_NOTE_CHARS:
        raise ConfidenceError(f"Ghi chú tối đa {MAX_NOTE_CHARS} ký tự.")

    return {
        "version": 2,
        "formula": FORMULA_V3,             # lượt mới: Gap tổng trên số gốc, hiển thị 2 chữ số
        "predictions": out,
        "joint": joint,                    # None khi đã đủ hai dự đoán riêng
        "joint_source": "direct" if joint else None,
        "reasons": list(reasons),
        "reasons_scope": "general",        # căn cứ chung: không tự gán riêng cho từng kỹ năng
        "note": note or None,              # nguyên văn học sinh viết; không có nhãn suy diễn
    }


def describe_gap(gap: float | None) -> str:
    """Diễn đạt bằng lời, học sinh không phải tự giải nghĩa dấu."""
    if gap is None:
        return ""
    if gap == 0:
        return "Dự đoán khớp kết quả"
    n = f"{abs(gap):.2f}".replace(".", ",")
    return f"Dự đoán {'cao' if gap > 0 else 'thấp'} hơn {n} điểm"


def effective_confidence(inputs: dict) -> tuple[float | None, str | None]:
    """Confidence chính thức: trung bình hai dự đoán riêng; chỉ khi thiếu thì mới dùng dự đoán chung học sinh nhập trực tiếp.
    Một dự đoán riêng đơn lẻ KHÔNG đại diện cho cả hai phần; 0,00 là dự đoán hợp lệ (không bị coi là thiếu)."""
    p = inputs["predictions"]
    if all(p[sk]["status"] == STATUS_SCORED for sk in SKILLS):
        return (p["distinction"]["score"] + p["application"]["score"]) / 2, SOURCE_TWO_SKILL
    j = inputs.get("joint")
    if j and j["status"] == STATUS_SCORED:
        return j["score"], SOURCE_JOINT
    return None, None


def compare(inputs: dict, d_actual: float | None, a_actual: float | None) -> dict:
    """Đối chiếu từng dự đoán với điểm thực tế của ĐÚNG kỹ năng đó. Điểm Recognition/Overall không tham gia.
    Dự đoán gốc đã khóa; điểm thực tế sửa sau (rà soát) thì gọi lại hàm này, Gap được tính lại từ dự đoán gốc."""
    v3 = inputs.get("formula") == FORMULA_V3
    rnd = round2 if v3 else round1
    actuals = {"distinction": d_actual, "application": a_actual}
    skills: dict[str, dict] = {}
    for skill in SKILLS:
        pred = inputs["predictions"][skill]
        actual = actuals[skill]
        gap = None
        if pred["status"] == STATUS_UNSURE:
            state = "unsure"
        elif actual is None:
            state = "awaiting_result"
        else:
            state = "compared"
            gap = rnd(Decimal(str(pred["score"])) - Decimal(str(actual)))
        skills[skill] = {
            "status": pred["status"], "predicted": pred["score"], "actual": actual,
            "gap": gap, "state": state, "text": describe_gap(gap),
        }

    gd, ga = skills["distinction"]["gap"], skills["application"]["gap"]
    both = gd is not None and ga is not None
    conf, source = effective_confidence(inputs)
    have_actuals = d_actual is not None and a_actual is not None
    actual_avg = (Decimal(str(d_actual)) + Decimal(str(a_actual))) / 2 if have_actuals else None
    gap_total = typical = None
    if conf is not None and have_actuals:
        gap_total = rnd(Decimal(str(conf)) - actual_avg)
    if both:
        typical = rnd((abs(Decimal(str(gd))) + abs(Decimal(str(ga)))) / 2)
    compared = sum(1 for s in skills.values() if s["state"] == "compared")
    if conf is not None:
        state = "COMPLETE" if have_actuals else "AWAITING_RESULT"
    elif any(s["state"] == "awaiting_result" for s in skills.values()):
        state = "AWAITING_RESULT"
    elif compared == 1:
        state = "PARTIAL"
    else:
        state = "NONE"
    return {
        "skills": skills, "gap_total": gap_total, "typical_deviation": typical, "state": state,
        "confidence": None if conf is None else (rnd(Decimal(str(conf))) if v3 else conf),
        "confidence_source": source,
        "actual_average": None if actual_avg is None else rnd(actual_avg),
        "joint": inputs.get("joint"),
        # hai độ lệch trái dấu, mỗi bên vượt ngưỡng, có thể triệt tiêu nhau trong Gap tổng nhưng từng kỹ năng vẫn lệch
        "offsetting": bool(both and gd * ga < 0 and abs(gd) > GAP_TOLERANCE and abs(ga) > GAP_TOLERANCE
                           and gap_total is not None and abs(gap_total) <= GAP_TOLERANCE),
    }


def classify(cmp: dict) -> str:
    """Trạng thái hiển thị của độ lệch. Chỉ NÓI 'sát' khi cả hai kỹ năng đều sát."""
    if cmp["state"] == "NONE":
        return "NO_PREDICTION"
    if cmp["state"] == "AWAITING_RESULT":
        return "AWAITING_RESULT"
    if cmp["state"] == "PARTIAL":
        return "PARTIAL_DATA"
    gap = cmp["gap_total"]
    if abs(gap) > GAP_TOLERANCE:
        return "DETECTED" if gap > 0 else "UNDERCONFIDENT"
    if cmp["typical_deviation"] > GAP_TOLERANCE:
        return "MIXED_DEVIATION"
    return "CALIBRATED"


def weakest_criterion(scores: dict | None, criteria: dict, labels: dict) -> str | None:
    """Tiêu chí mất nhiều điểm nhất theo điểm thành phần đã chấm; None nếu không có dữ liệu hoặc hòa."""
    if not isinstance(scores, dict):
        return None
    losses = []
    for key, max_v in criteria.items():
        v = scores.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        losses.append((max_v - v, key))
    top = max(losses)[0]
    if top <= 0:
        return None
    winners = [k for loss, k in losses if loss == top]
    return labels[winners[0]] if len(winners) == 1 else None
