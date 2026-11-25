"""Wrapper gọi mô hình AI. Interface chính: ask(prompt, reasoning_effort, model) -> str.

Hai nhà cung cấp: model bắt đầu bằng "claude" (hoặc "anthropic:") -> Anthropic Messages API; còn lại -> OpenAI Responses API.
Chọn model theo khâu xem ai_router.py."""

import os
import threading
import time

from dotenv import load_dotenv
from openai import OpenAI

import ai_router

load_dotenv()

_client = None
_anthropic_client = None
_tls = threading.local()

# Bộ ghi lượt gọi cho Demo Lab: hàm nhận một dict {role, model, effort, prompt, response, error, seconds, input_tokens, output_tokens}.
# None = tắt (mặc định, bản chạy thật không ghi gì). Xem lab_trace.py.
RECORDER = None


class AIRateLimitError(Exception):
    """Rate limit / hết hạn mức / quá tải từ nhà cung cấp (429, 529)."""


class AIProviderError(Exception):
    """Lỗi khác từ phía nhà cung cấp AI (không phải rate limit)."""


def get_client():
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic

        _anthropic_client = anthropic.Anthropic()          # đọc ANTHROPIC_API_KEY từ môi trường
    return _anthropic_client


_ANTHROPIC_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
ANTHROPIC_MAX_TOKENS = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "16000"))


def _is_rate_limit(e: Exception) -> bool:
    msg = str(e)
    low = msg.lower()
    status = getattr(e, "status_code", None)
    return (
        status in (429, 529)
        or "429" in msg
        or "529" in msg
        or "rate limit" in low
        or "rate_limit" in low
        or "overloaded" in low
        or "quota" in low
        or "insufficient_quota" in low
    )


def _ask_anthropic(prompt: str, effort: str, model: str) -> str:
    """Claude qua Messages API: thinking thích ứng + effort qua output_config (không gửi temperature/prefill/forced tool_choice).
    Lỗi API/từ chối -> AIProviderError; 429/529 -> AIRateLimitError để các luồng 'chấm nốt phần còn thiếu' xử lý như cũ."""
    model = model.split(":", 1)[1] if model.startswith("anthropic:") else model
    eff = effort if effort in _ANTHROPIC_EFFORTS else ("low" if effort in (None, "none", "minimal") else "medium")
    try:
        response = get_anthropic_client().messages.create(
            model=model,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": eff},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        if _is_rate_limit(e):
            raise AIRateLimitError(
                "Đã đạt giới hạn số lượt gọi AI trong khoảng thời gian này. Vui lòng đợi rồi thử lại."
            ) from e
        raise AIProviderError(f"Lỗi từ nhà cung cấp AI: {e}") from e
    if getattr(response, "stop_reason", None) == "refusal":
        raise AIProviderError("Mô hình từ chối trả lời yêu cầu này.")
    if getattr(response, "stop_reason", None) == "max_tokens":
        raise AIProviderError("Phản hồi của mô hình bị cắt do quá dài.")
    u = getattr(response, "usage", None)
    if u:
        _tls.usage = (u.input_tokens, u.output_tokens)
        print(f"[ai_client] {model} tokens: input={u.input_tokens} output={u.output_tokens}")
    return "".join(b.text for b in response.content if getattr(b, "type", None) == "text")


def ask(prompt: str, reasoning_effort: str = "low", model: str | None = None) -> str:
    rec = RECORDER
    if rec is None:
        return _ask_impl(prompt, reasoning_effort, model)
    import ai_router
    _tls.usage = None
    t0 = time.time()
    out, err = None, None
    try:
        out = _ask_impl(prompt, reasoning_effort, model)
        return out
    except Exception as e:  # noqa: BLE001 - ghi lại rồi ném tiếp nguyên vẹn
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        u = getattr(_tls, "usage", None) or (None, None)
        rec({"role": ai_router.current_role(), "model": model or os.environ.get("OPENAI_MODEL", "gpt-5.6"),
             "effort": reasoning_effort, "prompt": prompt, "response": out, "error": err,
             "seconds": round(time.time() - t0, 2), "input_tokens": u[0], "output_tokens": u[1]})


def _ask_impl(prompt: str, reasoning_effort: str = "low", model: str | None = None) -> str:
    """reasoning_effort: 'none'|'low'|'medium'|'high'|'xhigh'|'max'. Model có
    reasoning token ẩn tính vào output, dao động rất mạnh nếu để mặc định
    (có thể tốn hàng nghìn token dù việc đơn giản); 'low' đủ để tuân thủ
    rule nhiều ràng buộc mà không suy luận tràn lan.

    model: override OPENAI_MODEL cho riêng lượt gọi này; "claude-..." -> Anthropic (xem ai_router)."""
    if ai_router.is_anthropic(model):
        return _ask_anthropic(prompt, reasoning_effort, model)
    client = get_client()
    model = model or os.environ.get("OPENAI_MODEL", "gpt-5.6")
    try:
        response = client.responses.create(
            model=model,
            input=prompt,
            reasoning={"effort": reasoning_effort},
        )
    except Exception as e:
        if _is_rate_limit(e) and "overloaded" not in str(e).lower():
            raise AIRateLimitError(
                "Đã đạt giới hạn số lượt gọi AI trong khoảng thời gian này. Vui lòng đợi rồi thử lại."
            ) from e
        raise AIProviderError(f"Lỗi từ nhà cung cấp AI: {e}") from e

    if getattr(response, "usage", None):
        u = response.usage
        _tls.usage = (u.input_tokens, u.output_tokens)
        print(f"[ai_client] tokens: input={u.input_tokens} output={u.output_tokens} total={u.total_tokens}")

    return response.output_text
