"""Backend cho tính năng chat AI của World Map.

Luồng 1 lượt học (happy path, xem lại session_state trong session_store.py):
  /start -> dạy nội dung (AI)
  /begin-recognition -> sinh 20 MCQ (AI, JSON có đáp án - giữ ở server)
  /submit-recognition -> chấm 20 câu (code, không AI) + sinh correction (AI)
  /submit-confidence -> lưu điểm tự tin + sinh 2 câu hỏi mở (AI)
  /submit-open-ended -> chấm 2 câu mở theo rubric chi tiết (AI) + tính
                         Overall/Gap/PASS-RETRY (code)

Nếu RETRY, luôn trả về đầy đủ điểm + trạng thái illusion như PASS (yêu cầu
luôn hiển thị dù pass hay không). Từ RETRY, frontend có thể gọi thêm luồng
ôn tập trọng tâm (remediation), phân tích lỗi sai để luyện tập cả 3 phần
trước khi retest:
  /begin-remediation -> phân tích wrong_questions + điểm yếu -> sinh recap +
                         bộ MCQ luyện tập nhỏ + 1 câu Distinction + 1 câu
                         Application luyện tập (AI, 1 lời gọi)
  /submit-remediation-mcq -> chấm MCQ luyện tập (code) + sinh correction (AI)
  /submit-remediation-open-ended -> chấm 2 câu mở luyện tập (AI, chỉ để tham
                         khảo, không tính vào kết quả chính thức)
Sau đó /begin-recognition được gọi lại (retest đầy đủ 20 MCQ + 2 câu mở) -
nếu vẫn RETRY, chu kỳ ôn tập -> retest lặp lại cho tới khi PASS.

Prompt được nén tối đa (xem engine_prompts.py) để 1 lượt đầy đủ (5 lời gọi AI)
chỉ rơi vào khoảng 4000-5000 token thay vì ~18K như bản JSON-dump trước đó.
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import scoring
from ai_json import parse_ai_json
from ai_client import AIProviderError, AIRateLimitError, ask
from analysis_prompts import analysis_task
from engine_prompts import (
    assemble,
    compact_kb,
    correction_task,
    learning_content_task,
    load_knowledge_base,
    open_ended_generation_task,
    open_ended_grading_task,
    recognition_task,
    remediation_task,
)
from session_store import create_session, get_session

app = FastAPI(title="IOC AI Tutor Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # demo local - siết lại origin cụ thể khi deploy thật
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AIRateLimitError)
async def handle_rate_limit(request: Request, exc: AIRateLimitError):
    return JSONResponse(status_code=429, content={"detail": str(exc)})


@app.exception_handler(AIProviderError)
async def handle_provider_error(request: Request, exc: AIProviderError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(KeyError)
async def handle_session_not_found(request: Request, exc: KeyError):
    return JSONResponse(status_code=404, content={"detail": str(exc) or "Session không tồn tại hoặc đã hết hạn."})


# ---------- rubric ----------

DISTINCTION_CRITERIA = {"hieu_goc": 2, "doi_nghia": 2, "phan_biet": 2, "ngu_canh": 2, "so_sanh": 2}
APPLICATION_CRITERIA = {"chon_tu": 2, "dung_dung": 3, "giai_thich": 3, "tinh_huong": 2}

DISTINCTION_LABELS = {
    "hieu_goc": "Hiểu từ gốc",
    "doi_nghia": "Thay đổi nghĩa",
    "phan_biet": "Phân biệt ngữ nghĩa",
    "ngu_canh": "Phù hợp ngữ cảnh",
    "so_sanh": "Lập luận so sánh",
}
APPLICATION_LABELS = {
    "chon_tu": "Chọn từ đúng",
    "dung_dung": "Dùng đúng",
    "giai_thich": "Giải thích hợp lý",
    "tinh_huong": "Phù hợp tình huống",
}


def _clamp_scores(scores: dict, criteria: dict) -> dict:
    result = {}
    for key, max_v in criteria.items():
        v = float(scores.get(key, 0) or 0)
        v = max(0.0, min(max_v, v))
        v = round(v * 2) / 2
        result[key] = v
    return result


def _rubric_rows(scores: dict, criteria: dict, labels: dict) -> list[dict]:
    return [
        {"label": labels[key], "score": scores[key], "max": max_v}
        for key, max_v in criteria.items()
    ]


def _parse_mcq_rows(rows: list, expected_n: int) -> list[dict]:
    """Parse + validate JSON rows AI trả về thành list câu hỏi MCQ chuẩn. Dùng
    chung cho cả recognition (20 câu) và remediation practice (ít câu hơn)."""
    if len(rows) != expected_n:
        raise HTTPException(status_code=502, detail=f"AI trả về {len(rows)} câu thay vì {expected_n}, thử lại.")

    questions = []
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, list) or len(row) != 6:
            raise HTTPException(status_code=502, detail=f"Câu {i} sai định dạng, thử lại.")
        question, opt_a, opt_b, opt_c, opt_d, correct_idx = row
        if "___" not in str(question):
            raise HTTPException(status_code=502, detail=f"Câu {i} thiếu chỗ trống (___), thử lại.")
        options = [opt_a, opt_b, opt_c, opt_d]
        if len({str(o).strip().lower() for o in options}) != 4:
            raise HTTPException(status_code=502, detail=f"Câu {i} có lựa chọn trùng lặp, thử lại.")
        try:
            correct_idx = int(correct_idx)
        except (TypeError, ValueError):
            raise HTTPException(status_code=502, detail=f"Câu {i} có chỉ số đáp án không hợp lệ, thử lại.")
        if not (0 <= correct_idx <= 3):
            raise HTTPException(status_code=502, detail=f"Câu {i} có chỉ số đáp án không hợp lệ, thử lại.")
        questions.append({
            "id": i,
            "question": question,
            "options": options,
            "correct_index": correct_idx,
        })
    return questions


def _grade_mcq_answers(answer_key: dict, questions_by_id: dict, answers: dict) -> tuple[int, list[dict], str]:
    """Chấm 1 bộ MCQ (dùng chung cho recognition chính thức và remediation
    practice). Trả về (số câu đúng, list câu sai chi tiết, summary text cho
    correction_task)."""
    correct_count = 0
    wrong_questions = []
    unanswered_count = 0

    for qid, correct_index in answer_key.items():
        selected = answers.get(qid)
        q = questions_by_id[qid]
        if selected == correct_index:
            correct_count += 1
        elif selected is None:
            unanswered_count += 1
            wrong_questions.append({
                "id": qid, "question": q["question"], "options": q["options"],
                "correct_index": correct_index, "selected_index": None, "type": "unanswered",
            })
        else:
            wrong_questions.append({
                "id": qid, "question": q["question"], "options": q["options"],
                "correct_index": correct_index, "selected_index": int(selected), "type": "incorrect",
            })

    total = len(answer_key)
    summary_parts = [
        f"Tóm tắt: {correct_count}/{total} câu đúng, "
        f"{len(wrong_questions) - unanswered_count} câu sai, {unanswered_count} câu để trống."
    ]
    for wq in wrong_questions:
        if wq["type"] == "unanswered":
            summary_parts.append(f"Câu {wq['id']}: (bỏ trống) \"{wq['question']}\" - Đúng là: {wq['options'][wq['correct_index']]}")
        else:
            summary_parts.append(
                f"Câu {wq['id']}: \"{wq['question']}\" - Chọn: {wq['options'][wq['selected_index']]}, "
                f"Đúng: {wq['options'][wq['correct_index']]}"
            )

    return correct_count, wrong_questions, "\n".join(summary_parts)


def _missed_words_text(wrong_questions: list[dict] | None) -> str:
    """Rút ra danh sách từ mục tiêu mà học sinh hay chọn sai ở phần Nhận diện,
    dùng làm input cho remediation_task."""
    if not wrong_questions:
        return ""
    words = []
    seen = set()
    for wq in wrong_questions:
        word = str(wq["options"][wq["correct_index"]]).strip()
        key = word.lower()
        if key and key not in seen:
            seen.add(key)
            words.append(word)
    return ", ".join(words)


# ---------- request schemas ----------

class StartRequest(BaseModel):
    world_id: str
    level: int
    is_retry: bool = False  # True nếu đây là lần retry sau khi RETRY


class SessionIdRequest(BaseModel):
    session_id: str


class SubmitRecognitionRequest(BaseModel):
    session_id: str
    answers: dict[str, int]  # {"1": 2, "2": 0, ...} id câu hỏi (string) -> index đáp án chọn


class SubmitConfidenceRequest(BaseModel):
    session_id: str
    confidence: float


class SubmitOpenEndedRequest(BaseModel):
    session_id: str
    distinction_answer: str
    application_answer: str


class RemediationMCQRequest(BaseModel):
    session_id: str
    answers: dict[str, int]


class RemediationOpenEndedRequest(BaseModel):
    session_id: str
    distinction_answer: str
    application_answer: str


class AnalysisGroup(BaseModel):
    world_id: str
    level: int
    group_title: str
    overall: float
    wrong_words: list[dict] = []
    distinction_feedback: str | None = None
    application_feedback: str | None = None


class AnalysisRequest(BaseModel):
    groups: list[AnalysisGroup]


# ---------- endpoints ----------

@app.get("/api/vocab/{world_id}/{level}")
def get_vocab(world_id: str, level: int):
    """Trả về group_title + danh sách từ mục tiêu THẲNG TỪ FILE KB (không gọi
    AI, không tốn token) - dùng cho tính năng "Từ vựng đã học" ở frontend, lấy
    đúng dữ liệu gốc thay vì nội dung do AI diễn giải."""
    try:
        kb = load_knowledge_base(world_id, level)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "group_title": kb.get("group_title"),
        "words": list(kb.get("target_words", {}).keys()),
    }


@app.post("/api/chat/start")
def start_session(req: StartRequest):
    try:
        kb = load_knowledge_base(req.world_id, req.level)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    session = create_session(req.world_id, req.level, req.is_retry)

    prompt = assemble(compact_kb(kb), learning_content_task())
    learning_content = ask(prompt)

    session["current_state"] = "READY_FOR_RECOGNITION"

    show_onboarding = req.world_id == "world-1" and req.level == 1 and not req.is_retry

    return {
        "session_id": session["session_id"],
        "show_onboarding": show_onboarding,
        "group_title": kb.get("group_title"),
        "learning_content": learning_content,
    }


@app.post("/api/chat/begin-recognition")
def begin_recognition(req: SessionIdRequest):
    session = get_session(req.session_id)
    # Cho phép bắt đầu từ READY_FOR_RECOGNITION (lần đầu) HOẶC từ RETRY/
    # REMEDIATION_DONE (retest sau khi ôn tập, hoặc bỏ qua ôn tập retest thẳng)
    # - đây chính là nút "Kiểm tra lại" lặp lại từ đầu 20 câu MCQ.
    if session["current_state"] not in ("READY_FOR_RECOGNITION", "RETRY", "REMEDIATION_DONE"):
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")

    is_retest = session["current_state"] in ("RETRY", "REMEDIATION_DONE")
    if is_retest:
        session["is_retry"] = True

    kb = load_knowledge_base(session["world_id"], session["level"])
    n = len(kb["target_words"])

    prompt = assemble(compact_kb(kb), recognition_task(n, session.get("is_retry", False)))
    raw = ask(prompt)
    data = parse_ai_json(raw)
    questions = _parse_mcq_rows(data["q"], 20)

    session["generated_questions"] = questions
    session["secure_answer_key"] = {str(q["id"]): q["correct_index"] for q in questions}
    session["current_state"] = "WAITING_RECOGNITION_SUBMISSION"

    return {
        "questions": [{"id": q["id"], "question": q["question"], "options": q["options"]} for q in questions],
        "is_retest": is_retest,
    }


@app.post("/api/chat/submit-recognition")
def submit_recognition(req: SubmitRecognitionRequest):
    session = get_session(req.session_id)
    if session["current_state"] != "WAITING_RECOGNITION_SUBMISSION":
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")

    answer_key = session["secure_answer_key"]
    questions = {str(q["id"]): q for q in session["generated_questions"]}

    # gửi ĐỦ mọi câu sai cho correction - cap độ dài output đã nằm ở correction_task
    correct_count, wrong_questions, wrong_summary = _grade_mcq_answers(answer_key, questions, req.answers)

    recognition = scoring.calc_recognition(correct_count)
    session["recognition"] = recognition
    session["user_recognition_answers"] = req.answers
    session["wrong_questions"] = wrong_questions  # Lưu trữ để dùng cho retest

    kb = load_knowledge_base(session["world_id"], session["level"])
    prompt = assemble(compact_kb(kb), correction_task(wrong_summary))
    correction_text = ask(prompt)

    session["current_state"] = "WAITING_CONFIDENCE"

    # Bài đã chấm xong (đáp án không còn là bí mật cần bảo vệ nữa) - trả kèm
    # cặp từ (chọn sai / đúng) để frontend lưu lại phục vụ trang Analysis
    # (phân tích xu hướng nhầm lẫn từ vựng), không cần gọi lại AI cho việc này.
    wrong_words = [
        {"selected": (wq["options"][wq["selected_index"]] if wq["selected_index"] is not None else None),
         "correct": wq["options"][wq["correct_index"]],
         "question": wq["question"]}
        for wq in wrong_questions
    ]

    return {"correction_text": correction_text, "wrong_words": wrong_words}


@app.post("/api/chat/submit-confidence")
def submit_confidence(req: SubmitConfidenceRequest):
    session = get_session(req.session_id)
    if session["current_state"] != "WAITING_CONFIDENCE":
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")

    if not (0 <= req.confidence <= 10) or round(req.confidence * 2) != req.confidence * 2:
        raise HTTPException(status_code=422, detail="Confidence phải trong khoảng 0-10, bước nhảy 0.5.")

    session["confidence"] = req.confidence

    kb = load_knowledge_base(session["world_id"], session["level"])
    used_questions = [q["question"] for q in (session.get("generated_questions") or [])]
    prompt = assemble(compact_kb(kb), open_ended_generation_task(used_questions))
    raw = ask(prompt)
    data = parse_ai_json(raw)

    session["distinction_prompt"] = data["d"]
    session["application_prompt"] = data["a"]
    session["current_state"] = "WAITING_OPEN_ENDED_SUBMISSION"

    return {
        "distinction_prompt": data["d"],
        "application_prompt": data["a"],
    }


@app.post("/api/chat/submit-open-ended")
def submit_open_ended(req: SubmitOpenEndedRequest):
    session = get_session(req.session_id)
    if session["current_state"] != "WAITING_OPEN_ENDED_SUBMISSION":
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")

    kb = load_knowledge_base(session["world_id"], session["level"])
    context = (
        f"Câu hỏi Distinction: {session['distinction_prompt']}\n"
        f"Trả lời học sinh: {req.distinction_answer}\n"
        f"Tình huống Application: {session['application_prompt']}\n"
        f"Trả lời học sinh: {req.application_answer}"
    )
    prompt = assemble(compact_kb(kb), open_ended_grading_task(context))
    raw = ask(prompt)
    data = parse_ai_json(raw)

    d_scores = _clamp_scores(data.get("d_scores", {}), DISTINCTION_CRITERIA)
    a_scores = _clamp_scores(data.get("a_scores", {}), APPLICATION_CRITERIA)
    distinction_score = round(sum(d_scores.values()), 1)
    application_score = round(sum(a_scores.values()), 1)

    overall = scoring.calc_overall(session["recognition"], distinction_score, application_score)
    gap = scoring.calc_gap(session["confidence"], overall)
    understanding = scoring.classify_understanding(overall)
    illusion = scoring.classify_illusion(gap)
    session["accuracy"] = overall  # hiển thị = Overall (tổng hợp recognition + distinction + application)
    final_result = scoring.determine_pass(overall, gap)
    weak_area = scoring.detect_weakness(session["recognition"], distinction_score, application_score)

    session.update({
        "distinction_score": distinction_score,
        "application_score": application_score,
        "overall": overall,
        "gap": gap,
        "final_result": final_result,
        "d_scores": d_scores,
        "a_scores": a_scores,
        "distinction_feedback": data.get("d_fb", ""),
        "application_feedback": data.get("a_fb", ""),
        "weak_area": weak_area,
    })
    session["current_state"] = "LEVEL_COMPLETED" if final_result == "PASS" else "RETRY"

    return {
        "recognition": session["recognition"],
        "accuracy": session["accuracy"],
        "distinction_score": distinction_score,
        "distinction_feedback": data.get("d_fb", ""),
        "distinction_rubric": _rubric_rows(d_scores, DISTINCTION_CRITERIA, DISTINCTION_LABELS),
        "application_score": application_score,
        "application_feedback": data.get("a_fb", ""),
        "application_rubric": _rubric_rows(a_scores, APPLICATION_CRITERIA, APPLICATION_LABELS),
        "overall": overall,
        "confidence": session["confidence"],
        "gap": gap,
        "understanding_level": understanding,
        "illusion_status": illusion,
        "weak_area": weak_area,
        "final_result": final_result,
        "retry_note": None if final_result == "PASS" else (
            "Chưa đạt yêu cầu (Overall >= 7.0 và |Gap| <= 1.0). Hãy ôn tập trọng tâm rồi kiểm tra lại."
        ),
    }


# ---------- luồng ôn tập trọng tâm (remediation) khi RETRY ----------

@app.post("/api/chat/begin-remediation")
def begin_remediation(req: SessionIdRequest):
    session = get_session(req.session_id)
    if session["current_state"] != "RETRY":
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")

    kb = load_knowledge_base(session["world_id"], session["level"])
    missed_words = _missed_words_text(session.get("wrong_questions"))
    n_practice = 10

    prompt = assemble(
        compact_kb(kb),
        remediation_task(
            missed_words,
            session.get("weak_area") or "",
            session.get("distinction_feedback") or "",
            session.get("application_feedback") or "",
            n_practice,
        ),
    )
    raw = ask(prompt)
    data = parse_ai_json(raw)
    questions = _parse_mcq_rows(data["q"], n_practice)

    session["practice_questions"] = questions
    session["practice_secure_answer_key"] = {str(q["id"]): q["correct_index"] for q in questions}
    session["practice_distinction_prompt"] = data["d"]
    session["practice_application_prompt"] = data["a"]
    session["current_state"] = "REMEDIATION_MCQ"

    return {
        "recap": data.get("recap", ""),
        "practice_questions": [{"id": q["id"], "question": q["question"], "options": q["options"]} for q in questions],
    }


@app.post("/api/chat/submit-remediation-mcq")
def submit_remediation_mcq(req: RemediationMCQRequest):
    session = get_session(req.session_id)
    if session["current_state"] != "REMEDIATION_MCQ":
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")

    answer_key = session["practice_secure_answer_key"]
    questions = {str(q["id"]): q for q in session["practice_questions"]}
    _correct_count, _wrong, wrong_summary = _grade_mcq_answers(answer_key, questions, req.answers)

    kb = load_knowledge_base(session["world_id"], session["level"])
    prompt = assemble(compact_kb(kb), correction_task(wrong_summary))
    correction_text = ask(prompt)

    session["current_state"] = "REMEDIATION_OPEN_ENDED"

    return {
        "correction_text": correction_text,
        "distinction_prompt": session["practice_distinction_prompt"],
        "application_prompt": session["practice_application_prompt"],
    }


@app.post("/api/chat/submit-remediation-open-ended")
def submit_remediation_open_ended(req: RemediationOpenEndedRequest):
    session = get_session(req.session_id)
    if session["current_state"] != "REMEDIATION_OPEN_ENDED":
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")

    kb = load_knowledge_base(session["world_id"], session["level"])
    context = (
        f"Câu hỏi Distinction (luyện tập): {session['practice_distinction_prompt']}\n"
        f"Trả lời học sinh: {req.distinction_answer}\n"
        f"Tình huống Application (luyện tập): {session['practice_application_prompt']}\n"
        f"Trả lời học sinh: {req.application_answer}"
    )
    prompt = assemble(compact_kb(kb), open_ended_grading_task(context))
    raw = ask(prompt)
    data = parse_ai_json(raw)

    d_scores = _clamp_scores(data.get("d_scores", {}), DISTINCTION_CRITERIA)
    a_scores = _clamp_scores(data.get("a_scores", {}), APPLICATION_CRITERIA)
    distinction_score = round(sum(d_scores.values()), 1)
    application_score = round(sum(a_scores.values()), 1)

    # REMEDIATION_DONE -> begin-recognition được phép chạy lại (retest) từ đây.
    session["current_state"] = "REMEDIATION_DONE"

    return {
        "distinction_score": distinction_score,
        "distinction_feedback": data.get("d_fb", ""),
        "distinction_rubric": _rubric_rows(d_scores, DISTINCTION_CRITERIA, DISTINCTION_LABELS),
        "application_score": application_score,
        "application_feedback": data.get("a_fb", ""),
        "application_rubric": _rubric_rows(a_scores, APPLICATION_CRITERIA, APPLICATION_LABELS),
    }


# ---------- trang Analysis (độc lập, không qua session_store) ----------

@app.post("/api/analysis/generate")
def generate_analysis(req: AnalysisRequest):
    """Chỉ 1 lời gọi AI duy nhất, do FRONTEND chủ động gọi khi người dùng mở
    trang Analysis (đã tự cache theo chữ ký dữ liệu ở client, không gọi lặp
    lại). Không đụng tới session_store - không cần "phiên" nào cả, input là
    danh sách nhóm từ yếu nhất do frontend tự chọn sẵn từ localStorage."""
    if not req.groups:
        raise HTTPException(status_code=422, detail="Chưa có dữ liệu level nào để phân tích.")

    groups = [g.model_dump() for g in req.groups]
    prompt = analysis_task(groups)
    raw = ask(prompt, reasoning_effort="low")
    data = parse_ai_json(raw)

    return {
        "weak_patterns": data.get("weak_patterns", []),
        "improvement_tips": data.get("improvement_tips", []),
        "encouragement": data.get("encouragement", ""),
    }
