"""Bài giảng Present Knowledge: kiểm tra cấu trúc đầu ra của AI.

Chỉ xác nhận CẤU TRÚC (đủ phần, đủ từ, không rỗng, đối chiếu đủ mọi từ của nhóm), không
đánh giá nội dung đúng/dễ hiểu đến đâu. Mỗi lỗi là 1 câu tiếng Việt cụ thể để đưa
lại cho AI sửa.
"""

WORD_FIELDS = {
    "meaning_vi": "nghĩa tiếng Việt",
    "example_en": "câu ví dụ tiếng Anh",
    "example_vi": "diễn giải ý của câu bằng tiếng Việt",
    "why": "lời giải thích vì sao dùng từ đó trong câu",
}
CONTRAST_ITEM_FIELDS = {
    "sentence": "câu đối chiếu của từ",
    "focus": "điều người nghe chú ý ở câu đó",
}


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _key(word) -> str:
    return " ".join(_text(word).lower().split())


def validate_lesson(data, target_words: list[str]) -> tuple[list[str], dict | None]:
    """Trả (danh sách lỗi, bài đã chuẩn hoá). Không lỗi thì lỗi = [] và bài khác None."""
    if not isinstance(data, dict):
        return ["Đầu ra phải là một đối tượng JSON gồm 3 phần: intro, words, contrast."], None

    errors: list[str] = []
    canonical = {_key(w): w for w in target_words}

    intro = data.get("intro")
    if not _text(intro):
        errors.append("Thiếu phần mở đầu tình huống (intro) hoặc intro rỗng.")

    words = data.get("words")
    entries: dict[str, dict] = {}
    if not isinstance(words, list) or not words:
        errors.append("Thiếu danh sách giảng giải từng từ (words) hoặc words không phải danh sách.")
    else:
        for item in words:
            if not isinstance(item, dict):
                errors.append("Mỗi phần tử của words phải là một đối tượng có trường word.")
                continue
            k = _key(item.get("word"))
            if k not in canonical:
                shown = _text(item.get("word")) or "(trống)"
                errors.append(f"Từ \"{shown}\" không thuộc nhóm từ mục tiêu của level này.")
                continue
            if k in entries:
                errors.append(f"Từ {canonical[k]} bị lặp, mỗi từ chỉ được có đúng một mục.")
                continue
            entries[k] = item
        for k, w in canonical.items():
            if k not in entries:
                errors.append(f"Thiếu mục giảng giải cho từ {w}.")
        for k, item in entries.items():
            for field, label in WORD_FIELDS.items():
                if not _text(item.get(field)):
                    errors.append(f"Từ {canonical[k]} thiếu {label} ({field}).")

    contrast = data.get("contrast")
    contrast_items: dict[str, dict] = {}
    if not isinstance(contrast, dict):
        errors.append("Thiếu phần đối chiếu (contrast) hoặc contrast không phải đối tượng.")
        contrast = {}
    else:
        sentences = contrast.get("sentences")
        if not isinstance(sentences, list) or not sentences:
            errors.append("Thiếu danh sách câu đối chiếu (contrast.sentences) hoặc không phải danh sách.")
        else:
            for item in sentences:
                if not isinstance(item, dict):
                    errors.append("Mỗi phần tử của contrast.sentences phải là một đối tượng có trường word.")
                    continue
                k = _key(item.get("word"))
                if k not in canonical:
                    shown = _text(item.get("word")) or "(trống)"
                    errors.append(f"Câu đối chiếu dùng từ \"{shown}\" không thuộc nhóm đang học.")
                    continue
                if k in contrast_items:
                    errors.append(f"Từ {canonical[k]} bị lặp trong phần đối chiếu, mỗi từ đúng một câu.")
                    continue
                contrast_items[k] = item
            for k, w in canonical.items():
                if k not in contrast_items:
                    errors.append(f"Phần đối chiếu thiếu câu của từ {w} (phải có đủ mọi từ trong nhóm).")
            for k, item in contrast_items.items():
                for field, label in CONTRAST_ITEM_FIELDS.items():
                    if not _text(item.get(field)):
                        errors.append(f"Câu đối chiếu của từ {canonical[k]} thiếu {label} ({field}).")
        if not _text(contrast.get("explanation")):
            errors.append("Phần đối chiếu thiếu lời giải thích sự khác biệt (explanation).")

    if errors:
        return errors, None

    lesson = {
        "intro": _text(intro),
        "words": [
            {"word": canonical[k], **{f: _text(entries[k][f]) for f in WORD_FIELDS}}
            for k in canonical  # giữ đúng thứ tự trong Knowledge Base
        ],
        "contrast": {
            "sentences": [
                {"word": canonical[k], **{f: _text(contrast_items[k][f]) for f in CONTRAST_ITEM_FIELDS}}
                for k in canonical      # đủ mọi từ, đúng thứ tự trong Knowledge Base
            ],
            "explanation": _text(contrast["explanation"]),
        },
    }
    return [], lesson
