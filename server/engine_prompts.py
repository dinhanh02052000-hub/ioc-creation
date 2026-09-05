"""Xây prompt cho từng bước AI.

Bản đầu gửi nguyên JSON rule (database/engine/*.json, đã xoá - xem lịch sử
git nếu cần) vào mỗi lượt -> có lượt tốn tới ~18K token. Bản nén quá tay sau
đó (~5K token) lại làm nội dung sơ sài (thiếu ví dụ, câu hỏi rập khuôn, giải
thích cụt lủn). Bản này cân bằng lại: mục tiêu ~6000-7000 token/lượt, ưu tiên
chất lượng nội dung (đa dạng chủ đề, giải thích đầy đủ) hơn là ép sát 1 con
số token cứng nhắc.

Hệ thống chống lặp câu hỏi (field database + logic database, xem README ở
cuối file) được thêm để giải quyết tình trạng AI sinh câu hỏi/ý tưởng lặp lại
hoặc chỉ paraphrase sát nhau giữa các lần làm bài (lần đầu/retest/ôn tập) của
CÙNG 1 level - lịch sử câu hỏi đã sinh được lưu vĩnh viễn phía client (xem
js/features/question-history.js) và gửi kèm mỗi lần gọi sinh câu hỏi mới.
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

# ==== FIELD DATABASE ====
# Kéo chủ đề ra khỏi vùng an toàn quen thuộc của model (campaign, học sinh,
# radiation leak...) bằng cách gán CỐ ĐỊNH 1 lĩnh vực/câu thay vì chỉ "gợi ý"
# rồi để AI tự xoay vòng (cách cũ hay bị lờ đi, sinh ra cụm câu tụ lại vài chủ
# đề quen thuộc). Danh sách rộng, đa lĩnh vực để 20 câu/lượt trải thật đa dạng
# chủ thể/đối tượng, không chỉ đổi từ vựng mà giữ nguyên bối cảnh.
FIELD_DATABASE = [
    "Education & Learning", "Artificial Intelligence", "Technology & Innovation", "Social Media",
    "Digital Communication", "Privacy & Data", "Cybersecurity", "Robotics & Automation",
    "Future of Work", "Career & Employment", "Business & Entrepreneurship", "Economics",
    "Personal Finance", "Consumer Behaviour", "Advertising", "Globalization",
    "International Cooperation", "Leadership & Teamwork", "Productivity & Time Management",
    "Innovation & Creativity", "Climate Change", "Environmental Protection", "Renewable Energy",
    "Natural Resources", "Wildlife & Biodiversity", "Agriculture & Food Security",
    "Water & Sustainability", "Waste & Recycling", "Urbanization", "Smart Cities",
    "Health & Well-being", "Medicine & Medical Innovation", "Nutrition & Food",
    "Sports & Competition", "Psychology & Human Behaviour", "Science & Scientific Discovery",
    "Space Exploration", "Biotechnology", "Transportation & Mobility", "Disaster Preparedness",
    "Culture & Identity", "Language & Communication", "Literature & Storytelling",
    "Art & Creativity", "Music & Entertainment", "Film & Media", "Travel & Tourism",
    "History & Social Change", "Law, Justice & Ethics", "Human Rights & Social Equality",
]


def _sample_domains(k: int) -> list[str]:
    """Trả về LIST (không phải chuỗi đã join) để caller tự quyết định dùng làm
    prose (", ".join(...)) hay gán 1:1 theo thứ tự (đủ đa dạng chắc chắn hơn
    để AI tự xoay vòng)."""
    return random.sample(FIELD_DATABASE, min(k, len(FIELD_DATABASE)))


# ==== LOGIC DATABASE (phần "tránh lặp") ====
# Việc SO SÁNH câu mới với lịch sử (near-duplicate check bằng difflib) nằm ở
# main.py (chạy code thuần, không tốn token) - hàm dưới đây chỉ lo phần build
# PROMPT: nhét 1 đoạn "đã dùng rồi, đừng lặp" vào lời gọi sinh câu hỏi, để
# chính AI né những ý đó ngay từ đầu thay vì phải sinh lại nhiều lần. History
# truyền vào đây ĐÃ được main.py cắt bớt (chỉ N mục gần nhất) để đỡ tốn
# token - phần so sánh triệt để (không giới hạn) vẫn nằm ở lớp code phía sau.
def _history_avoidance_block(history: list[str] | None, label: str) -> str:
    if not history:
        return ""
    joined = "\n".join(f"- {h}" for h in history)
    return (
        f"\n\nDANH SÁCH {label} ĐÃ DÙNG CHO LEVEL NÀY TỪ TRƯỚC (kể cả lần làm trước, retest, ôn tập) - "
        f"TUYỆT ĐỐI KHÔNG được lặp lại Ý/LOGIC của bất kỳ mục nào dưới đây, kể cả khi diễn đạt/đổi từ khác "
        f"đi (paraphrase) vẫn tính là lặp:\n{joined}"
    )


# Câu mẫu bắt buộc (được phép diễn đạt lại) kết thúc mỗi tình huống Application
# - xem open_ended_generation_task() và remediation_task().
APPLICATION_CLOSING_QUESTION_SAMPLE = (
    "In a full sentence, use one word from the group to describe/explain the situation, and explicate "
    "why it is the best choice over the others?"
)


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


def recognition_task(n: int, is_retry: bool = False, history: list[str] | None = None) -> str:
    if n == 2:
        coverage = "Cả 2 từ LUÔN có mặt trong 4 lựa chọn mỗi câu (1 đúng, 1 nhiễu nội bộ là từ còn lại, 2 nhiễu ngoài)."
    elif n == 3:
        coverage = "Cả 3 từ LUÔN có mặt trong 4 lựa chọn mỗi câu (1 đúng, 2 nhiễu nội bộ là 2 từ còn lại, 1 nhiễu ngoài)."
    elif n == 4:
        coverage = "Cả 4 từ LUÔN có mặt trong 4 lựa chọn mỗi câu (1 đúng, 3 nhiễu nội bộ), không dùng nhiễu ngoài."
    else:
        coverage = "Mỗi câu chọn 4 trong các từ mục tiêu (1 đúng, 3 từ mục tiêu khác làm nhiễu), không dùng nhiễu ngoài."

    # FIELD DATABASE: gán CỐ ĐỊNH 1 lĩnh vực/câu (20 lĩnh vực khác nhau, không
    # để AI tự xoay vòng) - đảm bảo đa dạng chủ đề/đối tượng thật sự, không
    # phụ thuộc AI có tuân thủ gợi ý hay không.
    domains = _sample_domains(20)
    domain_lines = "\n".join(f"Câu {i + 1}: {d}" for i, d in enumerate(domains))

    retry_note = (
        "ĐÂY LÀ LẦN LÀM LẠI: bắt buộc sinh bộ câu HOÀN TOÀN MỚI, khác hẳn lần trước (đổi ngữ cảnh, chủ đề, "
        "cấu trúc câu). "
    ) if is_retry else ""

    history_block = _history_avoidance_block(history, "CÂU HỎI")

    return (
        "Sinh đúng 20 câu MCQ điền từ vào chỗ trống, câu tự nhiên dài 8-16 từ (đa dạng độ dài, không phải câu "
        f"nào cũng cụt như nhau), mỗi câu 4 lựa chọn, đúng 1 đáp án đúng. {coverage} "
        f"MỖI câu PHẢI đúng chủ đề (field) đã gán sẵn sau đây theo thứ tự (câu 1 dùng field của câu 1, câu 2 "
        f"dùng field của câu 2,...), KHÔNG được đổi field giữa các câu:\n{domain_lines}\n"
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
        "(4) TUYỆT ĐỐI KHÔNG được có 2 câu GIỐNG Y NGUYÊN nhau (trùng từng chữ) - đây là lỗi DUY NHẤT không "
        "được phép xảy ra (KHÔNG có vòng kiểm tra lại sau bước này - phải đúng ngay trong lượt sinh này). Để tự "
        "đa dạng thật sự ngay từ đầu (không chỉ đổi field/chủ đề mà giữ nguyên khung câu), BẮT BUỘC luân phiên "
        "qua ÍT NHẤT 8 KIỂU CẤU TRÚC câu khác nhau dưới đây, rải đều cho 20 câu (mỗi kiểu ~2-3 câu), KHÔNG được "
        "dùng quá 2 câu LIÊN TIẾP cùng 1 kiểu:\n"
        "  a) Mệnh đề thời gian/điều kiện đứng đầu ('After...', 'Before...', 'Once...', 'If...', 'When...')\n"
        "  b) Câu phủ định/thiếu điều kiện ('Without a ___, she could not...')\n"
        "  c) Câu bị động\n"
        "  d) Câu có mệnh đề quan hệ (who/which/that...)\n"
        "  e) Câu hỏi\n"
        "  f) Câu mô tả hiện tượng/sự việc chung, không gắn tên riêng\n"
        "  g) Câu kể hậu quả/hệ quả ('As a result...', '..., which led to...')\n"
        "  h) Câu so sánh (more/less/compared to...)\n"
        "  i) Câu ghép 2 mệnh đề bằng liên từ (although/because/since...)\n"
        "  j) Câu mở đầu bằng cụm trạng ngữ (Despite..., In light of..., Given...)\n"
        "Kết hợp CẢ 2 TRỤC độc lập - field/chủ đề (đã gán sẵn theo danh sách dưới đây) VÀ kiểu cấu trúc câu ở "
        "trên - để không có 2 câu nào trùng cả nội dung lẫn hình thức. TRƯỚC KHI trả JSON, tự rà lại toàn bộ 20 "
        "câu 1 lượt: nếu thấy quá nhiều câu liên tiếp dùng chung kiểu cấu trúc, hoặc 2 câu có tình huống/bối "
        "cảnh gần như hoán đổi được cho nhau, hãy viết lại NGAY trong lượt này - không được để việc đó tồn tại "
        "trong kết quả cuối cùng vì sẽ không có cơ hội sửa lại sau. "
        "(5) TUYỆT ĐỐI không sao chép hoặc chỉ paraphrase sát các câu ví dụ đã có sẵn trong Knowledge Base ở "
        "trên - mỗi câu hỏi phải là tình huống hoàn toàn mới do bạn tự nghĩ ra, khác cả nội dung lẫn cấu trúc "
        "câu so với các ví dụ đó. "
        f"{retry_note}"
        "(6) Phần tử thứ 6 của mỗi câu (đáp án đúng) PHẢI là bản CHÉP NGUYÊN VĂN - từng ký tự, không diễn giải "
        "lại, không đổi hoa/thường - của ĐÚNG 1 trong 4 lựa chọn đã viết ở vị trí 2-5 của chính câu đó. TUYỆT "
        "ĐỐI không dùng số thứ tự (0/1/2/3) hay chữ cái (A/B/C/D) ở đây - phải là text của đáp án. Trước khi trả "
        "kết quả, tự kiểm tra lại từng câu: đáp án đúng (phần tử 6) có xuất hiện y hệt trong danh sách 4 lựa "
        "chọn (phần tử 2-5) của ĐÚNG câu đó không - nếu không khớp, sửa lại trước khi trả JSON. Đồng thời tự "
        "đối chiếu lại với phần \"Phân biệt\" (key_distinction) của từng từ trong KB để chắc chắn từ được chọn "
        "làm đáp án đúng THỰC SỰ là lựa chọn phù hợp nhất trong ngữ cảnh câu đó, không phải chỉ là 1 lựa chọn "
        "có vẻ hợp lý."
        f"{history_block}\n\n"
        "CHỈ trả JSON, không chữ thừa, không markdown fence, đúng schema:\n"
        '{"q": [["câu hỏi có ___ ở chỗ trống", "optA", "optB", "optC", "optD", "optB (chép nguyên văn đáp án '
        'đúng, ở đây minh hoạ là optB nhưng thực tế phải khớp đúng lựa chọn nào là đáp án đúng của câu đó)"], '
        '... đủ 20 phần tử]}'
    )


# ==== STRONG ANSWER PIPELINE (xác định + kiểm tra đáp án ĐỘC LẬP với generator) ====
# Đã BỎ HẲN lớp kiểm tra "lặp Ý/LOGIC" bằng 1 lời gọi AI riêng (logic_duplicate
# _check_task cũ) - dù rẻ (reasoning_effort=low) vẫn tốn thêm 1 lượt gọi/batch
# và mỗi lần bị báo lặp lại phải huỷ sinh lại CẢ batch, quá chậm + tốn token so
# với lợi ích. Thay vào đó dồn lực cho việc PHÒNG NGỪA ngay từ prompt sinh câu
# (xem constraint (4) trong recognition_task và phần tương ứng trong
# remediation_task bên dưới) - ép AI tự đa dạng hoá chủ đề + kiểu câu/cấu trúc
# thật mạnh ngay từ đầu để không cần vòng kiểm tra riêng nữa. _find_duplicate/
# difflib ở main.py (miễn phí) là tuyến phòng thủ DUY NHẤT còn lại, chỉ chặn
# tuyệt đối 2 câu giống Y NGUYÊN.
# Phần kiểm tra đáp án ở trên (chỉ hỏi "đáp án ĐÃ CHỌN có vẻ đúng không" - dễ thiên lệch vì đang xác
# nhận lại chính lựa chọn của generator) - nay đã tách hẳn ra đây thành pipeline
# riêng, mạnh hơn. 2 hàm dưới đây tạo thành 1 pipeline 2 lượt TÁCH BIỆT:
# (1) 1 model KHÔNG được cho biết generator đã chọn gì, tự suy ra đáp án đúng
# chỉ từ KB; (2) 1 lượt kiểm tra độc lập khác tự suy luận lại từ đầu rồi mới
# đối chiếu với đáp án đề xuất ở bước (1) - xem server/main.py:
# _determine_and_verify_answers() để biết cách 2 lượt này được nối với nhau và
# cách code (không chỉ prompt) chặn việc validator "tin" mù quáng đáp án được
# đưa vào.
def strong_answer_generation_task(items: list[dict], feedback: dict[int, str] | None = None) -> str:
    """items: [{"id":1,"sentence":"...","options":["optA","optB","optC","optD"]}, ...] -
    CỐ Ý không kèm theo generator đã định chọn lựa chọn nào là đáp án đúng, để
    lượt này phải tự suy ra hoàn toàn độc lập (nguyên tắc 2-model).
    feedback: {id: lý do bị đánh giá SAI ở vòng trước} - chỉ có khi đây là vòng
    sinh lại (regeneration) cho riêng những câu bị FAIL, giúp tránh lặp lại
    đúng lỗi cũ thay vì đoán lại ngẫu nhiên."""
    lines = []
    for it in items:
        opts = "; ".join(f'{letter}) "{opt}"' for letter, opt in zip("ABCD", it["options"]))
        line = f'{it["id"]}. "{it["sentence"]}" -> Lựa chọn: {opts}'
        if feedback and it["id"] in feedback:
            line += f' [LƯU Ý: lượt trước bị đánh giá SAI vì: {feedback[it["id"]]} - xem xét lại từ đầu, đừng lặp lại lỗi này]'
        lines.append(line)
    return (
        "NHIỆM VỤ: bạn là chuyên gia xác định đáp án đúng cho câu điền từ - KHÔNG PHẢI người soạn câu hỏi, và "
        "KHÔNG được biết/đoán người soạn câu hỏi định chọn đáp án nào. Với MỖI câu dưới đây và 4 lựa chọn A/B/C/D, "
        "hãy tự xác định HOÀN TOÀN ĐỘC LẬP - CHỈ dựa vào nghĩa/phân biệt (key_distinction) trong Knowledge Base ở "
        "trên, không dùng kiến thức bên ngoài KB để đổi kết luận - lựa chọn nào là đáp án ĐÚNG NHẤT trong ngữ cảnh "
        "câu đó. Nếu không tìm được bằng chứng đủ mạnh trong KB cho bất kỳ lựa chọn nào, vẫn phải chọn lựa chọn "
        "hợp lý nhất nhưng ghi rõ trong 'evidence' rằng bằng chứng yếu. Suy luận kỹ trước khi chốt, nhưng phần "
        "VIẾT RA phải NGẮN GỌN tối đa (đây chỉ là ghi chú nội bộ để lượt kiểm tra sau đối chiếu, không hiển thị "
        "cho học sinh) - dùng cụm từ ngắn, KHÔNG viết câu văn đầy đủ, KHÔNG lặp lại nội dung câu hỏi.\n\n"
        + "\n".join(lines) +
        '\n\nCHỈ trả JSON, không chữ thừa, đúng schema: {"answers": [{"id": <id>, "correct_letter": "A|B|C|D", '
        '"evidence": "cụm từ ngắn (tối đa 12 từ) trích ý KB hỗ trợ lựa chọn này", "explanation": "cụm từ ngắn '
        '(tối đa 12 từ) vì sao đúng trong ngữ cảnh câu", "why_others_wrong": {"<letter>": "cụm từ ngắn (tối đa 8 '
        'từ) vì sao KHÔNG phù hợp", ... đủ 3 lựa chọn còn lại}}, ... đủ mọi id được liệt kê ở trên]}'
    )


def strong_answer_verification_task(items: list[dict]) -> str:
    """items: [{"id":1,"sentence":...,"options":[...],"proposed_letter":"B",
    "evidence":...,"explanation":...}, ...] - lượt KIỂM TRA ĐỘC LẬP đáp án đề
    xuất ở strong_answer_generation_task(), KHÔNG được mặc định tin là đúng."""
    lines = []
    for it in items:
        opts = "; ".join(f'{letter}) "{opt}"' for letter, opt in zip("ABCD", it["options"]))
        lines.append(
            f'{it["id"]}. "{it["sentence"]}" -> Lựa chọn: {opts}\n'
            f'   Đáp án ĐỀ XUẤT (cần kiểm tra, KHÔNG mặc định đúng): {it["proposed_letter"]}\n'
            f'   Evidence đề xuất: {it["evidence"]}\n'
            f'   Explanation đề xuất: {it["explanation"]}'
        )
    return (
        "NHIỆM VỤ KIỂM TRA ĐỘC LẬP (validator) cho từng câu dưới đây. QUAN TRỌNG: KHÔNG được tự động đồng ý chỉ "
        "vì đáp án/evidence/explanation đề xuất nghe có vẻ hợp lý - với MỖI câu, trước tiên PHẢI tự đọc lại "
        "Knowledge Base và tự suy ra đáp án đúng nhất theo ý kiến ĐỘC LẬP của riêng bạn (không nhìn đề xuất), rồi "
        "MỚI so sánh với đề xuất. Sau đó kiểm tra rõ từng điều kiện sau cho đề xuất:\n"
        "LƯU Ý QUAN TRỌNG khi chấm single_best_answer/distractors_valid: nhóm từ trong bài học này VỐN LÀ các từ "
        "gần nghĩa (near-synonyms) được thiết kế CHỦ ĐÍCH để dạy học sinh phân biệt - việc 1 lựa chọn khác 'nghe "
        "cũng xuôi tai/cũng tạm chấp nhận được' theo cảm nhận tiếng Anh tự nhiên chung chung KHÔNG tính là vi "
        "phạm, đó là bản chất của bài tập phân biệt từ gần nghĩa. CHỈ đánh giá dựa trên key_distinction cụ thể "
        "của TỪNG từ trong KB: 1 lựa chọn chỉ coi là 'cũng đúng' nếu key_distinction của nó trong KB MÔ TẢ ĐÚNG "
        "trọng tâm/ngữ cảnh của CHÍNH câu này (không phải chỉ vì nó chung nghĩa tổng quát với từ đúng).\n"
        "- knowledge_grounding: đáp án đề xuất có thực sự được KB hỗ trợ không (không bịa/không lấy kiến thức "
        "ngoài KB).\n"
        "- single_best_answer: dựa THEO key_distinction của từng từ trong KB (xem lưu ý ở trên) - có lựa chọn "
        "nào khác mà key_distinction của nó cũng khớp ĐÚNG trọng tâm câu này không? Chỉ false nếu KHÔNG.\n"
        "- distractors_valid: key_distinction của 3 lựa chọn còn lại có rõ ràng LỆCH trọng tâm câu này không "
        "(không cần chúng nghe sai ngữ pháp hay phi tự nhiên - chỉ cần trọng tâm nghĩa theo KB không khớp).\n"
        "- explanation_consistent: explanation đề xuất có nhất quán, không tự mâu thuẫn với chính đáp án đề xuất "
        "không.\n"
        "- question_answer_alignment: đáp án có thực sự trả lời đúng điều câu hỏi/chỗ trống đang hỏi không.\n"
        "- no_hallucination: evidence/explanation có bịa thêm thông tin không có trong KB và ảnh hưởng tới đáp "
        "án không (có bịa -> false).\n"
        "Suy luận kỹ trước khi chốt, nhưng phần VIẾT RA phải NGẮN GỌN (ghi chú nội bộ, không hiển thị cho học "
        "sinh) - failure_reason (nếu có) chỉ cần cụm từ ngắn tối đa 15 từ, không viết đoạn văn dài.\n\n"
        + "\n".join(lines) +
        '\n\nCHỈ trả JSON, không chữ thừa, đúng schema: {"results": [{"id": <id>, "status": "PASS"|"FAIL", '
        '"correct_answer": "A|B|C|D" (kết luận ĐỘC LẬP của riêng bạn, có thể khác lựa chọn đề xuất), "checks": '
        '{"knowledge_grounding": true|false, "single_best_answer": true|false, "distractors_valid": true|false, '
        '"explanation_consistent": true|false, "question_answer_alignment": true|false, "no_hallucination": '
        'true|false}, "confidence": 0.0-1.0, "failure_reason": "cụm từ ngắn (tối đa 15 từ) nếu FAIL, null nếu '
        'PASS"}, ... đủ mọi id được liệt kê ở trên]}'
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


def remediation_task(
    missed_words_text: str,
    weak_area: str,
    d_fb: str,
    a_fb: str,
    n_practice: int,
    recognition_history: list[str] | None = None,
    distinction_history: list[str] | None = None,
    application_history: list[str] | None = None,
) -> str:
    """Bộ ôn tập trọng tâm sau khi RETRY: phân tích lỗi sai của học sinh (từ hay
    nhầm ở phần Nhận diện + nhận xét Phân biệt/Vận dụng lần trước) để sinh 1 bài
    luyện tập nhỏ CHO CẢ 3 PHẦN trong 1 lời gọi AI duy nhất (đỡ tốn token)."""
    domains = _sample_domains(n_practice)
    domain_lines = "\n".join(f"Câu {i + 1}: {d}" for i, d in enumerate(domains))
    missed_block = missed_words_text or "(không có từ nào sai ở phần Nhận diện - lỗi chủ yếu ở phần Phân biệt/Vận dụng)"

    recognition_history_block = _history_avoidance_block(recognition_history, "CÂU HỎI TRẮC NGHIỆM")
    distinction_history_block = _history_avoidance_block(distinction_history, "CÂU HỎI DISTINCTION")
    application_history_block = _history_avoidance_block(application_history, "TÌNH HUỐNG APPLICATION")

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
        "TUYỆT ĐỐI không được có 2 câu GIỐNG Y NGUYÊN nhau (trùng từng chữ) - đây là lỗi DUY NHẤT không được "
        "phép (không có vòng kiểm tra lại sau, phải đúng ngay lượt này). BẮT BUỘC mỗi câu dùng 1 KIỂU cấu trúc "
        "khác nhau trong số: mệnh đề thời gian/điều kiện đứng đầu, câu phủ định/thiếu điều kiện, câu bị động, "
        "câu có mệnh đề quan hệ, câu hỏi, câu kể hậu quả/hệ quả, câu so sánh, câu ghép bằng liên từ - KHÔNG "
        "dùng 2 câu liên tiếp cùng 1 kiểu cấu trúc hoặc cùng bối cảnh/tình huống gần như hoán đổi được cho "
        "nhau. Tự rà lại trước khi trả JSON. Không sao chép/paraphrase sát các câu ví dụ đã có "
        "trong Knowledge Base, vị trí đáp án đúng trong 4 lựa chọn ngẫu nhiên. Phần tử thứ 6 của mỗi câu PHẢI "
        "là bản chép NGUYÊN VĂN đáp án đúng (khớp y hệt 1 trong 4 lựa chọn vừa viết, đối chiếu lại với "
        "key_distinction trong KB trước khi chốt), TUYỆT ĐỐI không dùng số thứ tự hay chữ cái - tự kiểm tra "
        "lại từng câu trước khi trả JSON. ƯU TIÊN xoáy sâu vào các từ hay nhầm lẫn liệt kê ở trên; nếu không có "
        f"từ nào thì trải đều cả nhóm từ. MỖI câu PHẢI đúng field đã gán sẵn theo thứ tự sau, KHÔNG đổi field "
        f"giữa các câu:\n{domain_lines}\n"
        "3) 'd': 1 câu hỏi Distinction MỚI bằng tiếng Anh (cùng dạng câu Distinction chuẩn: viết 1 câu ví dụ MỚI "
        "- không sao chép ví dụ trong KB - rồi hỏi nếu đổi sang từ dễ nhầm khác thì trọng tâm/sắc thái nghĩa đổi "
        "thế nào), xoáy vào đúng điểm nhầm lẫn nêu trên nếu có nhận xét liên quan.\n"
        "4) 'a': 1 tình huống Application MỚI bằng tiếng Anh (cùng dạng tình huống Application chuẩn, không "
        "chứa sẵn từ mục tiêu, không sao chép ví dụ trong KB), xoáy vào điểm yếu nêu trên nếu có nhận xét liên "
        "quan. Tình huống PHẢI kết thúc bằng 1 câu yêu cầu học sinh (tiếng Anh), nội dung tương đương câu mẫu "
        f'sau (được phép diễn đạt lại, không cần y hệt): "{APPLICATION_CLOSING_QUESTION_SAMPLE}"\n'
        f"{recognition_history_block}{distinction_history_block}{application_history_block}\n\n"
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
# LƯU Ý: hiện KHÔNG được tự động nối vào response nữa (đã tạm bỏ theo yêu cầu
# trước đó để chờ làm 1 nút riêng ở UI) - vẫn giữ nguyên ở đây, chưa dùng tới.
DISTINCTION_ANSWER_FORMAT = (
    "\n\n**Cách trả lời (viết đúng 3 phần theo thứ tự, được viết hoàn toàn bằng tiếng Việt hoặc tiếng Anh, kể "
    "cả câu ví dụ minh hoạ nếu có):**\n"
    "1) *Meaning* - giải thích từ trong câu trên nghĩa là gì và vì sao nó hợp với câu này (1-2 câu).\n"
    "2) *Compare* - chọn đúng 1 từ khác trong nhóm; nếu thay vào thì nghĩa/sắc thái câu đổi thế nào (2-3 câu).\n"
    "3) *Why it fits best* - 1 câu so sánh ngắn gọn nêu rõ vì sao từ ban đầu là lựa chọn đúng nhất.\n"
    "*Lưu ý:* viết thành đoạn văn hoàn chỉnh (câu có đầy đủ chủ ngữ - vị ngữ), không viết dạng gạch đầu dòng "
    "hay liệt kê từ khoá rời rạc."
)
APPLICATION_ANSWER_FORMAT = (
    "\n\n**Cách trả lời (viết đúng 2 phần theo thứ tự):**\n"
    "1) *Your sentence* - viết đúng 1 câu TIẾNG ANH hoàn chỉnh (bắt buộc tiếng Anh, đây là bài đặt câu), dùng "
    "đúng 1 từ trong nhóm, phù hợp tình huống trên.\n"
    "2) *Why* - 1-2 câu giải thích vì sao chọn từ này thay vì (các) từ còn lại trong nhóm - có thể viết bằng "
    "tiếng Việt hoặc tiếng Anh; nếu nhóm có nhiều từ dễ nhầm, chỉ cần so sánh với 2-3 từ dễ nhầm nhất.\n"
    "*Lưu ý:* phần Why viết thành đoạn văn hoàn chỉnh (câu có đầy đủ chủ ngữ - vị ngữ), không viết dạng gạch "
    "đầu dòng hay liệt kê từ khoá rời rạc."
)


def open_ended_generation_task(
    used_questions: list[str] | None = None,
    distinction_history: list[str] | None = None,
    application_history: list[str] | None = None,
) -> str:
    used_block = ""
    if used_questions:
        joined = " | ".join(used_questions)
        used_block = (
            f"\n\nCÁC CÂU ĐÃ DÙNG Ở PHẦN TRẮC NGHIỆM (KHÔNG được lặp lại, không được chỉ đổi 1-2 từ của các "
            f"câu này — phải là câu/tình huống hoàn toàn mới):\n{joined}"
        )
    domains = _sample_domains(4)
    distinction_history_block = _history_avoidance_block(distinction_history, "CÂU HỎI DISTINCTION")
    application_history_block = _history_avoidance_block(application_history, "TÌNH HUỐNG APPLICATION")
    return (
        "Sinh 1 câu hỏi Distinction và 1 tình huống Application, BẰNG TIẾNG ANH (đây là bài kiểm tra từ vựng "
        "tiếng Anh nên viết bằng tiếng Anh, giống văn phong 20 câu MCQ), MỖI CÁI thuộc 1 lĩnh vực KHÁC NHAU "
        f"trong số: {', '.join(domains)} (không dùng lại chủ đề campaign/student nếu không nằm trong danh sách này).\n"
        "- Distinction: viết 1 câu tiếng Anh MỚI dùng đúng 1 từ mục tiêu, sau đó hỏi (bằng tiếng Anh) nếu thay "
        "từ đó bằng 1 từ dễ nhầm khác trong nhóm thì trọng tâm/sắc thái nghĩa của câu thay đổi thế nào.\n"
        "- Application: viết 1 tình huống/kịch bản MỚI bằng tiếng Anh, KHÔNG chứa sẵn từ mục tiêu nào, kết "
        "thúc bằng 1 câu yêu cầu học sinh (tiếng Anh), nội dung tương đương câu mẫu sau (được phép diễn đạt "
        f'lại, không cần y hệt): "{APPLICATION_CLOSING_QUESTION_SAMPLE}"\n'
        "TUYỆT ĐỐI không sao chép hoặc chỉ paraphrase sát các câu ví dụ đã có sẵn trong Knowledge Base ở trên - "
        "cả câu Distinction lẫn tình huống Application phải là nội dung hoàn toàn mới do bạn tự nghĩ ra."
        f"{used_block}{distinction_history_block}{application_history_block}\n\n"
        "CHỈ trả JSON, không chữ thừa, không markdown fence:\n"
        '{"d": "distinction question in English", "a": "application scenario in English"}'
    )


def open_ended_grading_task(context: str) -> str:
    return (
        f"{context}\n\n"
        "Chấm theo tiêu chí sau (bước 0.5), MỖI tiêu chí gắn với ĐÚNG 1 phần bắt buộc trong câu trả lời; nếu "
        "học sinh bỏ hẳn 1 phần thì mọi tiêu chí thuộc phần đó = 0:\n"
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
        "  - dung_dung tối đa 3đ (Phần 1 - Your sentence): câu viết ra đúng ngữ pháp và đúng nghĩa từ đó không "
        "- PHẦN NÀY BẮT BUỘC phải viết bằng TIẾNG ANH (đây là bài đặt câu tiếng Anh); nếu học sinh viết câu "
        "này bằng tiếng Việt (hoặc không viết thành 1 câu tiếng Anh cụ thể) thì tiêu chí này = 0.\n"
        "  - tinh_huong tối đa 2đ (Phần 1 - Your sentence): câu có thực sự khớp với tình huống/kịch bản đã cho "
        "không.\n"
        "  - giai_thich tối đa 3đ (Phần 2 - Why): lý do giải thích có cụ thể, hợp lý, đúng trọng tâm không "
        "(không chỉ nói chung chung).\n"
        "Học sinh được phép trả lời TIẾNG VIỆT hoặc TIẾNG ANH cho MỌI phần khác (Distinction cả 3 phần, kể cả "
        "câu ví dụ minh hoạ nếu có; Application phần 2 - Why) - TUYỆT ĐỐI không trừ điểm chỉ vì dùng tiếng "
        "Việt ở những phần đó, chỉ chấm nội dung đúng/sai. CHỈ RIÊNG câu ở Phần 1 của Application (đặt câu, "
        "tiêu chí dung_dung) mới bắt buộc tiếng Anh như nêu trên. Câu trả lời phải là đoạn văn hoàn chỉnh (câu "
        "có chủ ngữ - "
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
