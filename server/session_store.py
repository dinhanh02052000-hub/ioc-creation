"""Lưu session trong RAM (dict) — phù hợp cho 1 tiến trình duy nhất; cần scale
ra nhiều instance thì thay bằng DB (sqlite/redis) mà không cần sửa main.py.

QUAN TRỌNG: secure_answer_key chỉ tồn tại ở đây, không bao giờ trả ra frontend
— main.py luôn strip field này trước khi trả questions ra ngoài."""

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
        "is_retry": is_retry,
        "current_state": "IDLE",
        "generated_questions": None,  # không kèm đáp án đúng
        "secure_answer_key": None,    # {question_id: correct_index} - KHÔNG trả ra ngoài
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
        "wrong_questions": None,  # câu sai từ lần trước, dùng cho retest focused
        "d_scores": None,         # điểm chi tiết từng tiêu chí Phân biệt, dùng cho phân tích ôn tập
        "a_scores": None,         # điểm chi tiết từng tiêu chí Vận dụng, dùng cho phân tích ôn tập
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
