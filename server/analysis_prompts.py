"""Prompt cho trang Analysis (js/pages/analysis.js). Chỉ gọi 1 LẦN DUY NHẤT khi
người dùng mở trang Analysis (frontend tự cache theo "chữ ký" dữ liệu đầu vào,
không gọi lặp lại nếu chưa có gì mới) - hoàn toàn tách biệt khỏi luồng chat AI
per-level ở engine_prompts.py/main.py.

Input do FRONTEND tự chọn sẵn: 5 nhóm từ có điểm Overall thấp nhất trong số
các level user đã làm (đọc từ localStorage), kèm cặp từ chọn-sai/đúng cụ thể
từng câu - nhờ vậy prompt không cần kèm theo cả file KB, giữ token thấp
(~5000-6000 cho cả input+output) mà vẫn đủ dữ liệu cụ thể để AI không "lệch
khung" (bịa lỗi sai không có thật)."""


def _format_group(g: dict) -> str:
    lines = [f"- Nhóm \"{g['group_title']}\" (World {g['world_id']} Level {g['level']}, Overall: {g['overall']}):"]
    wrong_words = g.get("wrong_words") or []
    if wrong_words:
        for w in wrong_words[:8]:  # đủ để thấy xu hướng, tránh phình prompt nếu 1 nhóm sai quá nhiều câu
            sel = w.get("selected") or "(bỏ trống)"
            lines.append(f"  + Câu \"{w.get('question', '')}\" - chọn \"{sel}\", đúng phải là \"{w.get('correct')}\"")
    else:
        lines.append("  + (không sai câu Nhận diện nào - điểm thấp đến từ Phân biệt/Vận dụng)")
    if g.get("distinction_feedback"):
        lines.append(f"  + Nhận xét Phân biệt: {g['distinction_feedback']}")
    if g.get("application_feedback"):
        lines.append(f"  + Nhận xét Vận dụng: {g['application_feedback']}")
    return "\n".join(lines)


def analysis_task(groups: list[dict]) -> str:
    groups_text = "\n".join(_format_group(g) for g in groups)
    return (
        "Bạn là trợ lý phân tích kết quả học từ vựng tiếng Anh. Dưới đây là các nhóm từ có điểm THẤP NHẤT mà "
        f"học sinh đã làm (đã có lỗi sai cụ thể, KHÔNG được bịa thêm lỗi ngoài dữ liệu này):\n\n{groups_text}\n\n"
        "YÊU CẦU (trả lời bằng tiếng Việt):\n"
        "1) weak_patterns: với MỖI nhóm ở trên, viết 1 đoạn ngắn (2-3 câu) chỉ rõ từ nào trong nhóm hay bị dùng "
        "sai NHẤT (dựa đúng vào các câu sai liệt kê), học sinh thường nhầm nó với từ nào khác trong nhóm, và vì "
        "sao 2 từ đó dễ gây nhầm lẫn (dựa vào nghĩa/cách dùng). Nếu nhóm không có câu Nhận diện sai, phân tích "
        "dựa vào nhận xét Phân biệt/Vận dụng thay thế.\n"
        "2) improvement_tips: gom TẤT CẢ các từ hay sai nhất từ mọi nhóm ở trên (không lặp từ trùng), với MỖI từ "
        "đưa ra 1 mẹo cải thiện cụ thể, thực hành được (VD: cách nhớ, ngữ cảnh đặc trưng) và 1 câu mô tả lỗi sai "
        "thường gặp nhất với từ đó.\n"
        "3) encouragement: 1 đoạn ngắn (2-3 câu) động viên học sinh, TÍCH CỰC nhưng chân thực (không sáo rỗng, "
        "không phải mẫu câu chung chung), dựa trên tình hình thực tế ở trên (VD: nếu đã có nhóm điểm khá thì ghi "
        "nhận, nếu đều thấp thì nhấn mạnh đây là bước đầu bình thường của việc học).\n\n"
        "CHỈ trả JSON, không chữ thừa, không markdown fence, đúng schema:\n"
        '{"weak_patterns": [{"group_title": "...", "analysis": "..."}, ...], '
        '"improvement_tips": [{"word": "...", "tip": "...", "common_mistake": "..."}, ...], '
        '"encouragement": "..."}'
    )
