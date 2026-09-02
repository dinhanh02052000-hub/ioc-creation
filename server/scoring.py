"""Công thức tính điểm / PASS-RETRY / phát hiện illusion — chuyển nguyên văn từ
score_model, understanding_classification, illusion_detection, passing_rules,
weakness_detection trong ioc database.json sang code. Đây là logic xác định
kết quả cuối cùng nên KHÔNG được để AI tự quyết, luôn tính bằng code thuần."""


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
    """PASS khi Overall >= 7.0 VÀ |gap| <= 1.0 (dùng trị tuyệt đối cho điều
    kiện PASS - lệch quá 1.0 theo hướng nào cũng không đạt). classify_illusion()
    ở trên mới dùng dấu +/- của gap để phân biệt DETECTED (quá tự tin) với
    UNDERCONFIDENT (thiếu tự tin) cho mục đích HIỂN THỊ, không ảnh hưởng công
    thức PASS này."""
    return "PASS" if overall >= 7.0 and abs(gap) <= 1.0 else "RETRY"


def detect_weakness(recognition: float, distinction: float, application: float) -> str:
    scores = {"recognition": recognition, "distinction": distinction, "application": application}
    mn, mx = min(scores.values()), max(scores.values())
    if (mx - mn) < 1.0:
        return "all_three"
    weak = [k for k, v in scores.items() if v == mn]
    return "_and_".join(weak)
