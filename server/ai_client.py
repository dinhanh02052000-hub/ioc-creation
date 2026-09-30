"""Wrapper gọi OpenAI Responses API. Interface chính: ask(prompt) -> str."""

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client = None


class AIRateLimitError(Exception):
    """Rate limit / hết hạn mức từ nhà cung cấp (429)."""


class AIProviderError(Exception):
    """Lỗi khác từ phía nhà cung cấp AI (không phải rate limit)."""


def get_client():
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def ask(prompt: str, reasoning_effort: str = "low", model: str | None = None) -> str:
    """reasoning_effort: 'none'|'low'|'medium'|'high'|'xhigh'|'max'. Model có
    reasoning token ẩn tính vào output, dao động rất mạnh nếu để mặc định
    (có thể tốn hàng nghìn token dù việc đơn giản); 'low' đủ để tuân thủ
    rule nhiều ràng buộc mà không suy luận tràn lan.

    model: override OPENAI_MODEL cho riêng lượt gọi này, dùng khi cần độ
    chính xác cao hơn chi phí (vd xác định đáp án, xem OPENAI_ANSWER_MODEL)."""
    client = get_client()
    model = model or os.environ.get("OPENAI_MODEL", "gpt-5.6")
    try:
        response = client.responses.create(
            model=model,
            input=prompt,
            reasoning={"effort": reasoning_effort},
        )
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        if (
            "429" in msg
            or "rate limit" in low
            or "rate_limit" in low
            or "quota" in low
            or "insufficient_quota" in low
        ):
            raise AIRateLimitError(
                "Đã đạt giới hạn số lượt gọi AI trong khoảng thời gian này. Vui lòng đợi rồi thử lại."
            ) from e
        raise AIProviderError(f"Lỗi từ nhà cung cấp AI: {msg}") from e

    if getattr(response, "usage", None):
        u = response.usage
        print(f"[ai_client] tokens: input={u.input_tokens} output={u.output_tokens} total={u.total_tokens}")

    return response.output_text
