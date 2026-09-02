"""Parse JSON từ output text của AI một cách an toàn — model đôi khi bọc JSON
trong ```json ... ``` dù đã được yêu cầu không làm vậy, nên cần bóc trước khi
json.loads()."""

import json
import re

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_ai_json(text: str) -> dict:
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # thử lấy đúng khối {...} lớn nhất trong text, phòng khi AI thêm lời dẫn
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise
