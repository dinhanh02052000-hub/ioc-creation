"""Định tuyến model theo TỪNG KHÂU. Cấu hình bằng biến môi trường; không cấu hình thì giữ hành vi cũ (một model OpenAI mặc định).

  AI_MODEL_<KHÂU>   = id model. Bắt đầu bằng "claude" -> gọi Anthropic; còn lại -> OpenAI. VD: AI_MODEL_GRADE_1=claude-sonnet-5-5
  AI_EFFORT_<KHÂU>  = low|medium|high|xhigh|max (ghi đè effort mà nơi gọi tự đặt). AI_EFFORT_DEFAULT áp cho mọi khâu chưa đặt riêng.

Các khâu (tên viết hoa khi đặt biến môi trường):
  recognition_gen        sinh 20 câu trắc nghiệm (cả 10 câu ôn tập)      recognition_judge    thẩm định mù đáp án (AI 1)
  recognition_judge_2    thẩm định mù lượt 2, đảo thứ tự phương án (AI 2); bỏ trống = dùng model của AI 1
  recognition_diversity  kiểm tra trùng/gần trùng                        open_gen             sinh đề Distinction/Application
  grade_1 / grade_2      hai lượt chấm tự luận (lượt 1 kèm đáp án mẫu)    grade_3              lượt chấm thứ ba (khi lệch > 0,75)
  lesson                 present knowledge (bài học)                     cards                thẻ ôn trọng tâm
  try_assess             chấm câu tự thử trong thẻ                       explanation          lời giải sau khi nộp trắc nghiệm
  report                 xét báo cáo (trắc nghiệm + tự luận)             rules                đề xuất quy tắc học"""

from __future__ import annotations

import os
import threading

_tls = threading.local()


def set_role(role: str | None) -> None:
    _tls.role = role


def current_role() -> str | None:
    return getattr(_tls, "role", None)


ROLES = (
    "recognition_gen", "recognition_judge", "recognition_judge_2", "recognition_diversity", "open_gen", "grade_1", "grade_2", "grade_3",
    "lesson", "cards", "try_assess", "explanation", "report", "rules",
)


def model_for(role: str) -> str | None:
    if role not in ROLES:
        raise KeyError(f"Khâu AI không có trong cấu hình: {role}")
    return os.environ.get(f"AI_MODEL_{role.upper()}") or None


def effort_for(role: str) -> str | None:
    return os.environ.get(f"AI_EFFORT_{role.upper()}") or os.environ.get("AI_EFFORT_DEFAULT") or None


def routed(ask_fn, role: str):
    """Bọc một hàm ask(prompt, **kw): thêm model/effort của khâu NẾU được cấu hình (không đè model mà nơi gọi đã chỉ định rõ).
    Chưa cấu hình thì không thêm tham số nào, nên hàm giả trong kiểm thử và hành vi cũ không đổi."""
    def call(prompt: str, **kw):
        set_role(role)
        m = model_for(role)
        if m and not kw.get("model"):
            kw["model"] = m
        e = effort_for(role)
        if e:
            kw["reasoning_effort"] = e
        return ask_fn(prompt, **kw)
    return call


def is_anthropic(model: str | None) -> bool:
    return bool(model) and (model.startswith("claude") or model.startswith("anthropic:"))
