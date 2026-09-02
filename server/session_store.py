"""Lưu session ngay trong RAM (dict) — đủ dùng cho demo 1 người dùng/1 máy.
Nếu sau này cần nhiều người dùng cùng lúc thật, thay bằng DB (sqlite/redis)
mà không phải sửa gì ở main.py, chỉ đổi implementation của module này.

QUAN TRỌNG: secure_answer_key chỉ tồn tại ở đây, không bao giờ đi vào response
trả cho frontend (xem main.py — mọi chỗ trả questions ra ngoài đều strip field
này trước khi jsonify)."""

import time
import uuid
from typing import Any

SESSIONS: dict[str, dict[str, Any]] = {}


def create_session(world_id: str, level: int, is_retry: bool = False) -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    session = {
        "session_id": session_id,
        "world_id": world_id,
        "level": level,
        "is_retry": is_retry,  # True nếu đây là lần retry
        "current_state": "IDLE",
        "generated_questions": None,       # list câu hỏi đã gửi cho user (không có đáp án đúng)
        "secure_answer_key": None,         # {question_id: correct_index} - KHÔNG trả ra ngoài
        "user_recognition_answers": None,
        "recognition": None,
        "accuracy": None,
        "confidence": None,
        "distinction_prompt": None,
        "application_prompt": None,
        "distinction_score": None,
        "application_score": None,
        "overall": None,
        "gap": None,
        "final_result": None,
        "wrong_questions": None,  # Lưu câu sai từ lần trước (dùng cho retest focused)
        "d_scores": None,          # Điểm chi tiết từng tiêu chí Phân biệt (dùng phân tích ôn tập)
        "a_scores": None,          # Điểm chi tiết từng tiêu chí Vận dụng (dùng phân tích ôn tập)
        "distinction_feedback": None,
        "application_feedback": None,
        "weak_area": None,
        # ---- Luồng ôn tập trọng tâm (remediation) khi RETRY ----
        "practice_questions": None,
        "practice_secure_answer_key": None,
        "practice_distinction_prompt": None,
        "practice_application_prompt": None,
        "created_at": time.time(),
    }
    SESSIONS[session_id] = session
    return session


def get_session(session_id: str) -> dict[str, Any]:
    session = SESSIONS.get(session_id)
    if not session:
        raise KeyError("Session không tồn tại hoặc đã hết hạn.")
    return session
