"""Xây prompt cho từng bước AI.

Bản đầu gửi nguyên JSON rule (database/engine/*.json) vào mỗi lời gọi -> có
lượt tốn tới ~18K token. Bản nén quá tay sau đó (~5K token) lại làm nội dung
sơ sài (thiếu ví dụ, câu hỏi rập khuôn, giải thích cụt lủn). Bản này cân bằng
lại: mục tiêu ~6000-7000 token/lượt, ưu tiên chất lượng nội dung (đa dạng chủ
đề, giải thích đầy đủ) hơn là ép sát 1 con số token cứng nhắc.

Các file JSON trong database/engine/ vẫn được giữ nguyên làm tài liệu tham
chiếu đầy đủ, không dùng trực tiếp để build prompt.
"""

import json
import random
from functools import lru_cache
from pathlib import Path

from config import get_kb_path


@lru_cache(maxsize=None)
def _load_kb_from_path(path_str: str) -> dict:
    return json.loads(Path(path_str).read_text(encoding="utf-8"))


def load_knowledge_base(world_id: str, level: int) -> dict:
    path = get_kb_path(world_id, level)
    return _load_kb_from_path(str(path))


def compact_kb(kb: dict) -> str:
    """Nén Knowledge Base thành text ngắn thay vì JSON đầy đủ."""
    lines = [f"Nhóm từ: {kb['group_title']}"]
    for word, info in kb["target_words"].items():
        distinction = (info.get("key_distinction") or "").strip()
        distinction_part = f" (Phân biệt: {distinction})" if distinction else ""
        lines.append(f"- {word}: {info['meaning']}{distinction_part} VD: {info['examples'][0]}")
    return "\n".join(lines)


CORE_RULE = (
    "Bạn là engine dạy & kiểm tra từ vựng tiếng Anh. Chỉ dùng đúng nghĩa/phân biệt/ví dụ trong "
    "Knowledge Base bên dưới, không tự bịa nghĩa khác. Không tiết lộ đáp án khi chưa được yêu cầu."
)

# Kéo chủ đề ra khỏi vùng an toàn quen thuộc của model (campaign, học sinh,
# radiation leak...) bằng cách gợi ý ngẫu nhiên vài lĩnh vực mỗi lượt gọi. Chủ
# đề càng hẹp, model càng dễ cạn ý và quay về việc chép/paraphrase sát ví dụ
# có sẵn trong KB, hoặc viết câu hoàn chỉnh quên mất chỗ trống - danh sách này
# cố tình rộng và đa dạng để giảm rủi ro đó.
TOPIC_DOMAINS = [
    "Psychology & Human Behavior", "Technology & Artificial Intelligence", "Environment & Climate Change",
    "Education & Learning", "Work & Career", "Economics & Finance", "Politics & Society", "Law & Ethics",
    "Science & Research", "Health & Medicine", "Social Media & Digital Life", "Media & Information",
    "Globalization & International Relations", "Cities & Urban Life", "Culture & Identity",
    "Relationships & Communication", "Art, Literature & Entertainment", "Future & Innovation",
    "Travel & Adventure", "Everyday Life & Consumer Choices",
]


def _sample_domains(k: int) -> str:
    return ", ".join(random.sample(TOPIC_DOMAINS, k))


def assemble(kb_text: str, task: str, extra: str = "") -> str:
    parts = [CORE_RULE, f"KB:\n{kb_text}"]
    if extra:
        parts.append(extra)
    parts.append(f"YÊU CẦU: {task}")
    return "\n\n".join(parts)


def learning_content_task() -> str:
    return (
        "Dạy nhóm từ trên bằng tiếng Việt, thân thiện, dễ hiểu cho học sinh THPT. Với MỖI từ mục tiêu viết "
        "1-2 câu: nghĩa + điểm phân biệt với các từ còn lại, kèm 1 ví dụ tiếng Anh (ưu tiên lấy/phỏng theo "
        "ví dụ trong KB). Kết thúc bằng 1 câu tổng kết so sánh cả nhóm. TỐI ĐA 220 từ. Có thể dùng **in đậm** "
        "cho từ mục tiêu. Chỉ trả văn bản thuần, không JSON, không heading #, không lời mở đầu/kết thừa thãi."
    )


def recognition_task(n: int, is_retry: bool = False) -> str:
    if n == 2:
        coverage = "Cả 2 từ LUÔN có mặt trong 4 lựa chọn mỗi câu (1 đúng, 1 nhiễu nội bộ là từ còn lại, 2 nhiễu ngoài)."
    elif n == 3:
        coverage = "Cả 3 từ LUÔN có mặt trong 4 lựa chọn mỗi câu (1 đúng, 2 nhiễu nội bộ là 2 từ còn lại, 1 nhiễu ngoài)."
    elif n == 4:
        coverage = "Cả 4 từ LUÔN có mặt trong 4 lựa chọn mỗi câu (1 đúng, 3 nhiễu nội bộ), không dùng nhiễu ngoài."
    else:
        coverage = "Mỗi câu chọn 4 trong các từ mục tiêu (1 đúng, 3 từ mục tiêu khác làm nhiễu), không dùng nhiễu ngoài."

    domains = _sample_domains(5)
    retry_note = (
        "ĐÂY LÀ LẦN LÀM LẠI: bắt buộc sinh bộ câu HOÀN TOÀN MỚI, khác hẳn lần trước (đổi ngữ cảnh, chủ đề, "
        "cấu trúc câu). "
    ) if is_retry else ""

    return (
        "Sinh đúng 20 câu MCQ điền từ vào chỗ trống, câu tự nhiên dài 8-16 từ (đa dạng độ dài, không phải câu "
        f"nào cũng cụt như nhau), mỗi câu 4 lựa chọn, đúng 1 đáp án đúng. {coverage} "
        f"TRẢI CHỦ ĐỀ đa dạng qua các lĩnh vực sau (mỗi câu 1 chủ đề khác nhau, xoay vòng, KHÔNG lặp lại 1-2 "
        f"chủ đề quen thuộc cho cả 20 câu): {domains}, và các lĩnh vực đời sống khác. "
        "Đáp án đúng phải rải đều giữa các từ mục tiêu (chênh lệch số lần đúng tối đa 1). Vị trí đáp án đúng "
        "trong 4 lựa chọn phải ngẫu nhiên, không theo mẫu (không phải lúc nào cũng ở lựa chọn đầu/cuối). "
        "RÀNG BUỘC CHẤT LƯỢNG BẮT BUỘC: "
        "(0) MỖI câu hỏi PHẢI có ĐÚNG 1 chỗ trống hiển thị bằng dấu gạch dưới '___' ngay tại vị trí từ mục tiêu "
        "sẽ điền vào (VD: \"A teacher's encouragement can ___ a child's confidence.\"). TUYỆT ĐỐI KHÔNG được "
        "viết thành 1 câu đã hoàn chỉnh không có chỗ trống nào - đây là lỗi nghiêm trọng nhất, kiểm tra lại "
        "từng câu trước khi trả về để chắc chắn có '___'. "
        "(1) Nhiễu ngoài phải THỰC SỰ sai trong ngữ cảnh câu đó, không được là "
        "lựa chọn hợp lý ngang hoặc hơn từ đúng (kiểm tra kỹ trước khi chọn nhiễu ngoài - VD tránh chọn từ tạo "
        "thành cụm quen thuộc hơn từ mục tiêu, như 'personal development' lấn át 'personal effect'). "
        "(2) TUYỆT ĐỐI không dùng lại chính từ mục tiêu (hoặc biến thể/động từ hoá của nó) ở phần câu hỏi "
        "(VD không viết 'influenced' trong câu hỏi nếu 'influence' là 1 lựa chọn). "
        "(3) 4 lựa chọn trong MỖI câu PHẢI khác nhau hoàn toàn, không được lặp lại 1 từ 2 lần trong cùng 1 câu. "
        "(4) Không trùng câu hỏi, không trùng cấu trúc câu giữa các câu. "
        "(5) TUYỆT ĐỐI không sao chép hoặc chỉ paraphrase sát các câu ví dụ đã có sẵn trong Knowledge Base ở "
        "trên - mỗi câu hỏi phải là tình huống hoàn toàn mới do bạn tự nghĩ ra, khác cả nội dung lẫn cấu trúc "
        "câu so với các ví dụ đó. "
        f"{retry_note}"
        "(6) Phần tử thứ 6 của mỗi câu (đáp án đúng) PHẢI là bản CHÉP NGUYÊN VĂN - từng ký tự, không diễn giải "
        "lại, không đổi hoa/thường - của ĐÚNG 1 trong 4 lựa chọn đã viết ở vị trí 2-5 của chính câu đó. TUYỆT "
        "ĐỐI không dùng số thứ tự (0/1/2/3) hay chữ cái (A/B/C/D) ở đây - phải là text của đáp án. Trước khi trả "
        "kết quả, tự kiểm tra lại từng câu: đáp án đúng (phần tử 6) có xuất hiện y hệt trong danh sách 4 lựa "
        "chọn (phần tử 2-5) của ĐÚNG câu đó không - nếu không khớp, sửa lại trước khi trả JSON. "
        "CHỈ trả JSON, không chữ thừa, không markdown fence, đúng schema:\n"
        '{"q": [["câu hỏi có ___ ở chỗ trống", "optA", "optB", "optC", "optD", "optB (chép nguyên văn đáp án '
        'đúng, ở đây minh hoạ là optB nhưng thực tế phải khớp đúng lựa chọn nào là đáp án đúng của câu đó)"], '
        '... đủ 20 phần tử]}'
    )


def correction_task(wrong_summary: str) -> str:
    body = wrong_summary if wrong_summary else "(không có câu sai - chúc mừng!)"
    return (
        f"KẾT QUẢ CỦA HỌC SINH:\n{body}\n\n"
        "Viết Correction bằng tiếng Việt cho TỪNG câu sai (nếu không sai câu nào thì khen 1-2 câu ngắn gọn). "
        "Với MỖI câu sai: nhắc lại NGẮN GỌN nội dung câu (không cần chép lại y nguyên, tóm ý chính đủ để nhận "
        "ra câu nào), nêu rõ vì sao đáp án học sinh chọn KHÔNG phù hợp trong ngữ cảnh này, và vì sao đáp án "
        "đúng phù hợp hơn (dựa vào phân biệt nghĩa trong KB). Nếu >8 câu sai: được phép nhóm các câu có cùng "
        "kiểu nhầm lẫn lại rồi giải thích chung, nhưng vẫn phải nêu số thứ tự từng câu trong nhóm. TỐI ĐA 350 "
        "từ. TUYỆT ĐỐI không nhắc điểm số/tỷ lệ % dạng con số. Có thể dùng **in đậm** cho từ mục tiêu. Chỉ trả "
        "văn bản thuần, không JSON."
    )


def remediation_task(missed_words_text: str, weak_area: str, d_fb: str, a_fb: str, n_practice: int) -> str:
    """Bộ ôn tập trọng tâm sau khi RETRY: phân tích lỗi sai của học sinh (từ hay
    nhầm ở phần Nhận diện + nhận xét Phân biệt/Vận dụng lần trước) để sinh 1 bài
    luyện tập nhỏ CHO CẢ 3 PHẦN trong 1 lời gọi AI duy nhất (đỡ tốn token)."""
    domains = _sample_domains(4)
    missed_block = missed_words_text or "(không có từ nào sai ở phần Nhận diện - lỗi chủ yếu ở phần Phân biệt/Vận dụng)"
    return (
        f"Học sinh vừa làm bài CHƯA ĐẠT. Các từ hay nhầm lẫn nhất ở phần Nhận diện: {missed_block}\n"
        f"Điểm yếu nhất tổng thể (so giữa 3 phần Nhận diện/Phân biệt/Vận dụng): {weak_area or '(không rõ)'}.\n"
        f"Nhận xét Phân biệt lần trước: {d_fb or '(không có)'}\n"
        f"Nhận xét Vận dụng lần trước: {a_fb or '(không có)'}\n\n"
        "Dựa vào đó, soạn 1 bộ ÔN TẬP TRỌNG TÂM gồm 4 phần:\n"
        "1) 'recap': đoạn tiếng Việt TỐI ĐA 250 từ, đi thẳng vào chỗ sai (không lặp lại y nguyên nội dung đã "
        "dạy). Với MỖI từ/tiêu chí hay nhầm liệt kê ở trên: nêu rõ VÌ SAO học sinh dễ nhầm ở đây, phân biệt lại "
        "với (các) từ hay bị nhầm cùng, và cho ĐÚNG 1 ví dụ tiếng Anh ngắn minh hoạ đúng chỗ khác nhau đó (không "
        "lấy nguyên câu ví dụ đã dạy trước đó). Nếu không có từ nào sai ở Nhận diện, tập trung phân tích cụ thể "
        "vào nhận xét Phân biệt/Vận dụng nêu trên (đừng viết chung chung).\n"
        f"2) 'q': đúng {n_practice} câu MCQ điền từ, CÙNG format/ràng buộc chất lượng như câu trắc nghiệm chuẩn: "
        "câu tự nhiên 8-16 từ, MỖI câu PHẢI có ĐÚNG 1 chỗ trống hiển thị bằng dấu '___' ngay tại vị trí từ mục "
        "tiêu (TUYỆT ĐỐI không viết thành câu đã hoàn chỉnh không có chỗ trống), 4 lựa chọn khác nhau hoàn "
        "toàn, nhiễu ngoài phải thực sự sai trong ngữ cảnh, không dùng lại chính từ mục tiêu ở phần câu hỏi, "
        "không trùng câu hỏi/cấu trúc giữa các câu, không sao chép/paraphrase sát các câu ví dụ đã có trong "
        "Knowledge Base, vị trí đáp án đúng trong 4 lựa chọn ngẫu nhiên. Phần tử thứ 6 của mỗi câu PHẢI là bản "
        "chép NGUYÊN VĂN đáp án đúng (khớp y hệt 1 trong 4 lựa chọn vừa viết), TUYỆT ĐỐI không dùng số thứ tự "
        "hay chữ cái - tự kiểm tra lại từng câu trước khi trả JSON. ƯU TIÊN xoáy sâu vào các từ hay nhầm lẫn liệt kê ở "
        f"trên; nếu không có từ nào thì trải đều cả nhóm từ. Trải chủ đề đa dạng qua: {domains}, và các lĩnh "
        "vực đời sống khác (mỗi câu 1 chủ đề khác nhau).\n"
        "3) 'd': 1 câu hỏi Distinction MỚI bằng tiếng Anh (cùng dạng câu Distinction chuẩn: viết 1 câu ví dụ MỚI "
        "- không sao chép ví dụ trong KB - rồi hỏi nếu đổi sang từ dễ nhầm khác thì trọng tâm/sắc thái nghĩa đổi "
        "thế nào), xoáy vào đúng điểm nhầm lẫn nêu trên nếu có nhận xét liên quan.\n"
        "4) 'a': 1 tình huống Application MỚI bằng tiếng Anh (cùng dạng tình huống Application chuẩn, không "
        "chứa sẵn từ mục tiêu, không sao chép ví dụ trong KB), xoáy vào điểm yếu nêu trên nếu có nhận xét liên "
        "quan.\n\n"
        "CHỈ trả JSON, không chữ thừa, không markdown fence, đúng schema:\n"
        '{"recap": "...", "q": [["câu hỏi có ___ ở chỗ trống","optA","optB","optC","optD","optB (chép nguyên '
        f'văn đáp án đúng của câu đó)"], ...đủ {n_practice} phần tử], "d": "distinction question in English", '
        '"a": "application scenario in English"}'
    )


# Hướng dẫn cấu trúc trả lời gắn CỐ ĐỊNH vào cuối câu hỏi hiển thị cho học
# sinh (main.py nối vào sau khi nhận data["d"]/data["a"] từ AI, KHÔNG lưu vào
# session["distinction_prompt"]/["application_prompt"] - context gửi cho
# open_ended_grading_task giữ nguyên câu hỏi gốc, đỡ tốn token lặp lại).
# Cố định (không để AI tự viết lại mỗi lần) để đảm bảo học sinh LUÔN thấy
# đúng 1 cấu trúc nhất quán, không phụ thuộc AI có tuân thủ hay không.
DISTINCTION_ANSWER_FORMAT = (
    "\n\n**Cách trả lời (viết đúng 3 phần theo thứ tự, có thể viết bằng tiếng Việt - riêng câu ví dụ minh hoạ "
    "nếu có thì phải viết bằng tiếng Anh):**\n"
    "1) *Meaning* - giải thích từ trong câu trên nghĩa là gì và vì sao nó hợp với câu này (1-2 câu).\n"
    "2) *Compare* - chọn đúng 1 từ khác trong nhóm; nếu thay vào thì nghĩa/sắc thái câu đổi thế nào (2-3 câu).\n"
    "3) *Why it fits best* - 1 câu so sánh ngắn gọn nêu rõ vì sao từ ban đầu là lựa chọn đúng nhất.\n"
    "*Lưu ý:* viết thành đoạn văn hoàn chỉnh (câu có đầy đủ chủ ngữ - vị ngữ), không viết dạng gạch đầu dòng "
    "hay liệt kê từ khoá rời rạc."
)
APPLICATION_ANSWER_FORMAT = (
    "\n\n**Cách trả lời (viết đúng 2 phần theo thứ tự):**\n"
    "1) *Your sentence* - viết đúng 1 câu tiếng Anh hoàn chỉnh, dùng đúng 1 từ trong nhóm, phù hợp tình huống trên.\n"
    "2) *Why* - 1-2 câu giải thích vì sao chọn từ này thay vì các từ còn lại trong nhóm.\n"
    "*Lưu ý:* phần Why viết thành đoạn văn hoàn chỉnh (câu có đầy đủ chủ ngữ - vị ngữ), không viết dạng gạch "
    "đầu dòng hay liệt kê từ khoá rời rạc."
)


def open_ended_generation_task(used_questions: list[str] | None = None) -> str:
    used_block = ""
    if used_questions:
        joined = " | ".join(used_questions)
        used_block = (
            f"\n\nCÁC CÂU ĐÃ DÙNG Ở PHẦN TRẮC NGHIỆM (KHÔNG được lặp lại, không được chỉ đổi 1-2 từ của các "
            f"câu này — phải là câu/tình huống hoàn toàn mới):\n{joined}"
        )
    domains = _sample_domains(4)
    return (
        "Sinh 1 câu hỏi Distinction và 1 tình huống Application, BẰNG TIẾNG ANH (đây là bài kiểm tra từ vựng "
        "tiếng Anh nên viết bằng tiếng Anh, giống văn phong 20 câu MCQ), MỖI CÁI thuộc 1 lĩnh vực KHÁC NHAU "
        f"trong số: {domains} (không dùng lại chủ đề campaign/student nếu không nằm trong danh sách này).\n"
        "- Distinction: viết 1 câu tiếng Anh MỚI dùng đúng 1 từ mục tiêu, sau đó hỏi (bằng tiếng Anh) nếu thay "
        "từ đó bằng 1 từ dễ nhầm khác trong nhóm thì trọng tâm/sắc thái nghĩa của câu thay đổi thế nào.\n"
        "- Application: viết 1 tình huống/kịch bản MỚI bằng tiếng Anh, KHÔNG chứa sẵn từ mục tiêu nào, yêu "
        "cầu học sinh tự chọn 1 từ trong nhóm để mô tả tình huống và giải thích lý do chọn.\n"
        "TUYỆT ĐỐI không sao chép hoặc chỉ paraphrase sát các câu ví dụ đã có sẵn trong Knowledge Base ở trên - "
        "cả câu Distinction lẫn tình huống Application phải là nội dung hoàn toàn mới do bạn tự nghĩ ra."
        f"{used_block}\n\nCHỈ trả JSON, không chữ thừa, không markdown fence:\n"
        '{"d": "distinction question in English", "a": "application scenario in English"}'
    )


def open_ended_grading_task(context: str) -> str:
    return (
        f"{context}\n\n"
        "Học sinh được yêu cầu trả lời theo cấu trúc bắt buộc sau (xem DISTINCTION_ANSWER_FORMAT/"
        "APPLICATION_ANSWER_FORMAT ở engine_prompts.py) - chấm theo tiêu chí sau (bước 0.5), MỖI tiêu chí gắn "
        "với ĐÚNG 1 phần bắt buộc; nếu học sinh bỏ hẳn 1 phần thì mọi tiêu chí thuộc phần đó = 0:\n"
        "Distinction - 5 tiêu chí, MỖI tiêu chí tối đa 2đ (tổng tối đa 10):\n"
        "  - hieu_goc (Phần 1 - Meaning): có giải thích ĐÚNG nghĩa của từ đã dùng trong câu không.\n"
        "  - ngu_canh (Phần 1 - Meaning): có nêu đúng vì sao từ đó phù hợp với NGỮ CẢNH câu này không.\n"
        "  - doi_nghia (Phần 2 - Compare): có chọn đúng 1 từ khác trong nhóm và nêu đúng nghĩa/sắc thái đổi "
        "thế nào nếu thay vào không.\n"
        "  - phan_biet (Phần 2 - Compare): độ chính xác của việc phân biệt 2 từ (không nhầm lẫn nghĩa).\n"
        "  - so_sanh (Phần 3 - Why it fits best): có lập luận so sánh ngắn gọn, rõ ràng, thuyết phục không.\n"
        "Application - 4 tiêu chí (tổng tối đa 10):\n"
        "  - chon_tu tối đa 2đ (Phần 1 - Your sentence): có chọn đúng từ phù hợp NHẤT trong nhóm cho tình "
        "huống này không.\n"
        "  - dung_dung tối đa 3đ (Phần 1 - Your sentence): câu viết ra đúng ngữ pháp và đúng nghĩa từ đó không.\n"
        "  - tinh_huong tối đa 2đ (Phần 1 - Your sentence): câu có thực sự khớp với tình huống/kịch bản đã cho "
        "không.\n"
        "  - giai_thich tối đa 3đ (Phần 2 - Why): lý do giải thích có cụ thể, hợp lý, đúng trọng tâm không "
        "(không chỉ nói chung chung).\n"
        "Học sinh được phép trả lời phần giải thích bằng tiếng Việt hoặc tiếng Anh đều được - TUYỆT ĐỐI không "
        "trừ điểm chỉ vì trả lời bằng tiếng Việt, chỉ chấm nội dung đúng/sai (riêng câu ví dụ minh hoạ nếu học "
        "sinh có viết thì mới cần bằng tiếng Anh). Câu trả lời phải là đoạn văn hoàn chỉnh (câu có chủ ngữ - "
        "vị ngữ đầy đủ) - nếu học sinh chỉ liệt kê từ khoá/gạch đầu dòng rời rạc thay vì viết câu hoàn chỉnh thì "
        "trừ điểm tiêu chí liên quan (dù nội dung đúng ý cũng không cho điểm tối đa). "
        "Bỏ trống/vô nghĩa/'không biết' = 0 hết các tiêu chí liên quan. Mỗi feedback (d_fb, a_fb) viết 2-3 câu "
        "tiếng Việt: nêu rõ điểm làm tốt, điểm còn thiếu/sai cụ thể là gì (kèm phần nào bị thiếu nếu có), và "
        "gợi ý ngắn để cải thiện — không chỉ nói chung chung 'đúng' hay 'sai'. "
        "CHỈ trả JSON, không chữ thừa, đúng schema (điểm là số, tổng 5 số distinction phải <=10, tổng 4 số "
        "application phải <=10):\n"
        '{"d_scores": {"hieu_goc":0,"doi_nghia":0,"phan_biet":0,"ngu_canh":0,"so_sanh":0}, "d_fb": "...", '
        '"a_scores": {"chon_tu":0,"dung_dung":0,"giai_thich":0,"tinh_huong":0}, "a_fb": "..."}'
    )
