"""Công thức tính điểm, phân loại PASS/RETRY và phát hiện illusion. Đây là
logic xác định kết quả cuối cùng nên luôn tính bằng code thuần, không để AI
tự quyết."""


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


def determine_pass(overall: float, gap: float) -> str:
    """PASS khi Overall >= 7.0 và |gap| <= 1.0 (lệch quá 1.0 theo hướng nào cũng
    không đạt). classify_illusion() dùng dấu +/- của gap để phân biệt
    DETECTED/UNDERCONFIDENT chỉ cho mục đích hiển thị, không ảnh hưởng đến
    điều kiện PASS này."""
    return "PASS" if overall >= 7.0 and abs(gap) <= 1.0 else "RETRY"


def detect_weakness(recognition: float, distinction: float, application: float) -> str:
    scores = {"recognition": recognition, "distinction": distinction, "application": application}
    mn, mx = min(scores.values()), max(scores.values())
    if (mx - mn) < 1.0:
        return "all_three"
    weak = [k for k, v in scores.items() if v == mn]
    return "_and_".join(weak)
