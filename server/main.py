"""Backend cho tính năng chat AI của World Map.

Luồng 1 lượt học (xem session_state trong session_store.py):
  /start -> dạy nội dung (AI)
  /begin-recognition -> sinh 20 MCQ (AI, đáp án giữ ở server)
  /submit-recognition -> chấm (code) + sinh correction (AI)
  /submit-confidence -> lưu điểm tự tin + sinh 2 câu hỏi mở (AI)
  /submit-open-ended -> chấm theo rubric (AI) + tính Overall/Gap/PASS-RETRY (code)

Nếu RETRY, trả đầy đủ điểm + trạng thái illusion như khi PASS. Frontend có thể
gọi thêm luồng ôn tập trọng tâm trước khi retest:
  /begin-remediation -> phân tích lỗi sai -> sinh recap + MCQ luyện tập + 1 câu
                         Distinction + 1 câu Application luyện tập (AI)
  /submit-remediation-mcq -> chấm (code) + sinh correction (AI)
  /submit-remediation-open-ended -> chấm luyện tập (AI, chỉ để tham khảo)
Sau đó /begin-recognition retest lại đầy đủ (20 MCQ + 2 câu mở) cho tới khi PASS.

Prompt được nén tối đa (xem engine_prompts.py) để giữ chi phí token thấp cho
1 lượt đầy đủ.
"""

import hmac
import logging
import os
import re
import secrets
import string
from datetime import timedelta
from difflib import SequenceMatcher

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel

import db
import scoring
from ai_json import parse_ai_json
from ai_client import AIProviderError, AIRateLimitError, ask
from analysis_prompts import analysis_task
from config import (
    BANK_ACCOUNT_NUMBER,
    BASE_DIR,
    GOOGLE_CLIENT_ID,
    SEPAY_API_KEY,
)
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
    strong_answer_generation_task,
    strong_answer_verification_task,
)
from session_store import create_session, get_session

logger = logging.getLogger("ioc.payments")

app = FastAPI(title="IOC AI Tutor Backend")
db.init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: siết lại origin cụ thể khi deploy thật
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
    """Parse + validate JSON rows AI trả về thành list câu hỏi MCQ chuẩn.

    Phần tử thứ 6 là NGUYÊN VĂN đáp án đúng, không phải index: bắt AI tự đếm
    số thứ tự 0-3 là nguồn lỗi phổ biến (chọn đúng từ nhưng khai sai index),
    nên code đối chiếu text với 4 lựa chọn để tự suy ra index thay vì tin AI."""
    if len(rows) != expected_n:
        raise HTTPException(status_code=502, detail=f"AI trả về {len(rows)} câu thay vì {expected_n}, thử lại.")

    questions = []
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, list) or len(row) != 6:
            raise HTTPException(status_code=502, detail=f"Câu {i} sai định dạng, thử lại.")
        question, opt_a, opt_b, opt_c, opt_d, correct_text = row
        if "___" not in str(question):
            raise HTTPException(status_code=502, detail=f"Câu {i} thiếu chỗ trống (___), thử lại.")
        options = [opt_a, opt_b, opt_c, opt_d]
        normalized_options = [str(o).strip().lower() for o in options]
        if len(set(normalized_options)) != 4:
            raise HTTPException(status_code=502, detail=f"Câu {i} có lựa chọn trùng lặp, thử lại.")
        correct_norm = str(correct_text).strip().lower()
        if correct_norm not in normalized_options:
            raise HTTPException(
                status_code=502,
                detail=f"Câu {i} có đáp án đúng không khớp với 4 lựa chọn đã cho, thử lại.",
            )
        correct_idx = normalized_options.index(correct_norm)
        questions.append({
            "id": i,
            "question": question,
            "options": options,
            "correct_index": correct_idx,
        })
    return questions


# ---------- chống lặp câu hỏi ----------
# Lớp phòng thủ thứ 2 (lớp 1 là hướng dẫn "không lặp lại" trong prompt, xem
# engine_prompts._history_avoidance_block). Dùng difflib nên miễn phí, vì vậy
# so sánh được với TOÀN BỘ lịch sử thay vì chỉ phần đã cắt gọn cho prompt.

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")
_DUPLICATE_SIMILARITY_THRESHOLD = 0.82


def _normalize_for_similarity(text: str) -> str:
    t = str(text).lower().replace("___", " ")
    t = _PUNCT_RE.sub(" ", t)
    return _WS_RE.sub(" ", t).strip()


def _find_duplicate(new_texts: list[str], history: list[str]) -> str | None:
    """So sánh từng cặp trong batch mới, và từng câu mới với toàn bộ history.
    Trả về mô tả vi phạm nếu 2 câu quá giống nhau (ratio >= ngưỡng), hoặc None.

    Chỉ bắt được kiểu chép sát/đổi vài từ (paraphrase nông) - có chủ đích:
    đa dạng ý tưởng/cấu trúc sâu hơn dựa vào chất lượng prompt sinh câu, không
    có lớp kiểm tra AI riêng cho việc đó (tốn token, chậm)."""
    normed_new = [_normalize_for_similarity(t) for t in new_texts]
    for i in range(len(normed_new)):
        for j in range(i + 1, len(normed_new)):
            if not normed_new[i] or not normed_new[j]:
                continue
            if SequenceMatcher(None, normed_new[i], normed_new[j]).ratio() >= _DUPLICATE_SIMILARITY_THRESHOLD:
                return f"Câu {i + 1} và câu {j + 1} trong batch quá giống nhau"

    normed_hist = [_normalize_for_similarity(h) for h in history]
    for i, nq in enumerate(normed_new):
        if not nq:
            continue
        for h in normed_hist:
            if h and SequenceMatcher(None, nq, h).ratio() >= _DUPLICATE_SIMILARITY_THRESHOLD:
                return f"Câu {i + 1} trùng ý với 1 câu đã sinh trước đó cho level này"
    return None


def _bound_history(history: list[str] | None, max_entries: int) -> list[str]:
    """Cắt history để nhét vào prompt (tốn token), chỉ giữ các mục gần nhất.
    _find_duplicate dùng history đầy đủ, không qua hàm này, vì so sánh miễn phí."""
    if not history:
        return []
    return history[-max_entries:]


# ---------- Strong answer pipeline: xác định + kiểm tra đáp án độc lập ----------
# 1 model suy ra đáp án từ KB mà không biết generator đã chọn gì, 1 lượt độc
# lập khác verify lại; code từ chối 1 "PASS" tự mâu thuẫn (verifier kết luận
# đáp án khác nhưng vẫn báo PASS). Chỉ câu FAIL được sinh lại đáp án (câu hỏi
# giữ nguyên); còn FAIL sau hết lượt thì huỷ cả batch qua cơ chế 502 -> retry.
_ANSWER_CONFIDENCE_THRESHOLD = 0.75
_MAX_ANSWER_REGEN_ROUNDS = 2
_LETTER_TO_INDEX = {"A": 0, "B": 1, "C": 2, "D": 3}


def _determine_and_verify_answers(kb: dict, questions: list[dict]) -> None:
    items_by_id = {q["id"]: q for q in questions}
    pending_ids = list(items_by_id.keys())
    feedback: dict[int, str] = {}
    answer_model = os.environ.get("OPENAI_ANSWER_MODEL") or None

    for _round in range(1 + _MAX_ANSWER_REGEN_ROUNDS):
        if not pending_ids:
            break

        gen_items = [
            {"id": qid, "sentence": items_by_id[qid]["question"], "options": items_by_id[qid]["options"]}
            for qid in pending_ids
        ]
        gen_prompt = assemble(compact_kb(kb), strong_answer_generation_task(gen_items, feedback or None))
        gen_data = parse_ai_json(ask(gen_prompt, reasoning_effort="low", model=answer_model))
        proposals_by_id = {a["id"]: a for a in (gen_data.get("answers") or [])}

        verify_items = []
        for qid in pending_ids:
            prop = proposals_by_id.get(qid)
            if not prop or not prop.get("correct_letter"):
                feedback[qid] = "Không nhận được đề xuất đáp án hợp lệ từ AI"
                continue
            verify_items.append({
                "id": qid,
                "sentence": items_by_id[qid]["question"],
                "options": items_by_id[qid]["options"],
                "proposed_letter": prop["correct_letter"],
                "evidence": prop.get("evidence", ""),
                "explanation": prop.get("explanation", ""),
            })

        if not verify_items:
            continue  # tất cả đều thiếu đề xuất hợp lệ - thử sinh lại ở vòng sau

        verify_prompt = assemble(compact_kb(kb), strong_answer_verification_task(verify_items))
        verify_data = parse_ai_json(ask(verify_prompt, reasoning_effort="low", model=answer_model))
        results_by_id = {r["id"]: r for r in (verify_data.get("results") or [])}

        new_pending = []
        for vi in verify_items:
            qid = vi["id"]
            result = results_by_id.get(qid)
            if not result:
                feedback[qid] = "Không nhận được kết quả kiểm tra hợp lệ từ AI"
                new_pending.append(qid)
                continue

            status = result.get("status")
            confidence = float(result.get("confidence") or 0)
            verified_letter = result.get("correct_answer")
            # Verifier tự kết luận đáp án khác mà vẫn báo PASS là tự mâu thuẫn - không tin PASS của nó trong trường hợp đó.
            if verified_letter != vi["proposed_letter"]:
                status = "FAIL"
            if confidence < _ANSWER_CONFIDENCE_THRESHOLD:
                status = "FAIL"

            if status != "PASS":
                feedback[qid] = result.get("failure_reason") or "Đáp án đề xuất không được xác nhận đủ tin cậy"
                new_pending.append(qid)
                continue

            idx = _LETTER_TO_INDEX.get(str(vi["proposed_letter"]).strip().upper())
            if idx is None or idx >= len(items_by_id[qid]["options"]):
                feedback[qid] = "Chữ cái đáp án không hợp lệ"
                new_pending.append(qid)
                continue

            items_by_id[qid]["correct_index"] = idx
            feedback.pop(qid, None)

        pending_ids = new_pending

    if pending_ids:
        raise HTTPException(
            status_code=502,
            detail=f"Không xác định chắc chắn đáp án đúng cho câu {sorted(pending_ids)}, thử lại.",
        )


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
    # Lịch sử câu hỏi đã sinh cho level này, lưu phía client (xem
    # js/features/question-history.js), gửi kèm để tránh lặp. begin-recognition
    # chỉ dùng recognition_history; begin-remediation dùng cả 3.
    recognition_history: list[str] = []
    distinction_history: list[str] = []
    application_history: list[str] = []


class SubmitRecognitionRequest(BaseModel):
    session_id: str
    answers: dict[str, int]  # {"1": 2, "2": 0, ...} id câu hỏi (string) -> index đáp án chọn


class SubmitConfidenceRequest(BaseModel):
    session_id: str
    confidence: float
    distinction_history: list[str] = []
    application_history: list[str] = []


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


class GoogleAuthRequest(BaseModel):
    credential: str  # ID token JWT do Google Identity Services trả về ở frontend


class ProgressSaveRequest(BaseModel):
    data: dict


class CreatePaymentRequest(BaseModel):
    package_index: int


class FeedbackRequest(BaseModel):
    name: str = ""
    content: str


def get_current_user(authorization: str | None = Header(default=None)):
    """Dependency xác thực Bearer token - áp dụng cho progress save/load và mọi
    route chat AI, vì AI giới hạn theo key gắn với tài khoản Google (guest
    luôn có 0 key, không dùng được AI)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Chưa đăng nhập.")
    token = authorization.removeprefix("Bearer ").strip()
    user = db.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")
    return user


# ---------- "key" currency: giới hạn dùng AI ----------
# Chỉ begin-recognition (2) và begin-remediation (1) trừ key - các route khác
# chỉ cần đăng nhập, chi phí AI của chúng đã tính vào lượt begin- tương ứng.
def _require_keys(user, cost: int) -> None:
    """Chặn sớm trước khi tốn AI. Không phải bước trừ key thật (xem _charge_keys)."""
    if user["keys"] < cost:
        raise HTTPException(status_code=402, detail="Bạn đã hết key.")


def _charge_keys(user_id: int, cost: int) -> None:
    """Trừ key thật - chỉ gọi sau khi AI của request đã thành công. db.deduct_keys
    atomic nên vẫn chống được race dù _require_keys ở trên không atomic."""
    if not db.deduct_keys(user_id, cost):
        raise HTTPException(status_code=402, detail="Bạn đã hết key.")


# ---------- endpoints ----------

@app.get("/api/vocab/{world_id}/{level}")
def get_vocab(world_id: str, level: int):
    """Trả về group_title + danh sách từ mục tiêu thẳng từ file KB (không gọi
    AI) - dùng cho "Từ vựng đã học" ở frontend, cần dữ liệu gốc chứ không phải
    nội dung AI diễn giải."""
    try:
        kb = load_knowledge_base(world_id, level)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "group_title": kb.get("group_title"),
        "words": list(kb.get("target_words", {}).keys()),
    }


@app.post("/api/chat/start")
def start_session(req: StartRequest, user=Depends(get_current_user)):
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
def begin_recognition(req: SessionIdRequest, user=Depends(get_current_user)):
    session = get_session(req.session_id)
    # RETRY/REMEDIATION_DONE = nút "Kiểm tra lại" (retest 20 câu, có hoặc
    # không qua ôn tập trước đó).
    if session["current_state"] not in ("READY_FOR_RECOGNITION", "RETRY", "REMEDIATION_DONE"):
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")
    _require_keys(user, 2)

    is_retest = session["current_state"] in ("RETRY", "REMEDIATION_DONE")
    if is_retest:
        session["is_retry"] = True

    kb = load_knowledge_base(session["world_id"], session["level"])
    n = len(kb["target_words"])
    bounded_recognition_history = _bound_history(req.recognition_history, 60)

    prompt = assemble(
        compact_kb(kb),
        recognition_task(n, session.get("is_retry", False), bounded_recognition_history),
    )
    raw = ask(prompt)
    data = parse_ai_json(raw)
    questions = _parse_mcq_rows(data["q"], 20)

    duplicate_violation = _find_duplicate([q["question"] for q in questions], req.recognition_history)
    if duplicate_violation:
        raise HTTPException(status_code=502, detail=f"{duplicate_violation}, thử lại.")
    _determine_and_verify_answers(kb, questions)
    _charge_keys(user["id"], 2)

    session["generated_questions"] = questions
    session["secure_answer_key"] = {str(q["id"]): q["correct_index"] for q in questions}
    session["current_state"] = "WAITING_RECOGNITION_SUBMISSION"

    return {
        "questions": [{"id": q["id"], "question": q["question"], "options": q["options"]} for q in questions],
        "is_retest": is_retest,
        "keys_remaining": db.get_keys(user["id"]),
    }


@app.post("/api/chat/submit-recognition")
def submit_recognition(req: SubmitRecognitionRequest, user=Depends(get_current_user)):
    session = get_session(req.session_id)
    if session["current_state"] != "WAITING_RECOGNITION_SUBMISSION":
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")

    answer_key = session["secure_answer_key"]
    questions = {str(q["id"]): q for q in session["generated_questions"]}

    correct_count, wrong_questions, wrong_summary = _grade_mcq_answers(answer_key, questions, req.answers)

    recognition = scoring.calc_recognition(correct_count)
    session["recognition"] = recognition
    session["user_recognition_answers"] = req.answers
    session["wrong_questions"] = wrong_questions  # Lưu trữ để dùng cho retest

    kb = load_knowledge_base(session["world_id"], session["level"])
    prompt = assemble(compact_kb(kb), correction_task(wrong_summary))
    correction_text = ask(prompt)

    session["current_state"] = "WAITING_CONFIDENCE"

    # Trả kèm cặp từ (chọn sai/đúng) để frontend lưu cho trang Analysis, không cần gọi lại AI.
    wrong_words = [
        {"selected": (wq["options"][wq["selected_index"]] if wq["selected_index"] is not None else None),
         "correct": wq["options"][wq["correct_index"]],
         "question": wq["question"]}
        for wq in wrong_questions
    ]

    return {"correction_text": correction_text, "wrong_words": wrong_words}


@app.post("/api/chat/submit-confidence")
def submit_confidence(req: SubmitConfidenceRequest, user=Depends(get_current_user)):
    session = get_session(req.session_id)
    if session["current_state"] != "WAITING_CONFIDENCE":
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")

    if not (0 <= req.confidence <= 10) or round(req.confidence * 2) != req.confidence * 2:
        raise HTTPException(status_code=422, detail="Confidence phải trong khoảng 0-10, bước nhảy 0.5.")

    session["confidence"] = req.confidence

    kb = load_knowledge_base(session["world_id"], session["level"])
    used_questions = [q["question"] for q in (session.get("generated_questions") or [])]
    prompt = assemble(
        compact_kb(kb),
        open_ended_generation_task(
            used_questions,
            _bound_history(req.distinction_history, 30),
            _bound_history(req.application_history, 30),
        ),
    )
    raw = ask(prompt)
    data = parse_ai_json(raw)

    duplicate_violation = (
        _find_duplicate([data["d"]], req.distinction_history)
        or _find_duplicate([data["a"]], req.application_history)
    )
    if duplicate_violation:
        raise HTTPException(status_code=502, detail=f"{duplicate_violation}, thử lại.")

    session["distinction_prompt"] = data["d"]
    session["application_prompt"] = data["a"]
    session["current_state"] = "WAITING_OPEN_ENDED_SUBMISSION"

    return {
        "distinction_prompt": data["d"],
        "application_prompt": data["a"],
    }


@app.post("/api/chat/submit-open-ended")
def submit_open_ended(req: SubmitOpenEndedRequest, user=Depends(get_current_user)):
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
def begin_remediation(req: SessionIdRequest, user=Depends(get_current_user)):
    session = get_session(req.session_id)
    if session["current_state"] != "RETRY":
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")
    _require_keys(user, 1)

    kb = load_knowledge_base(session["world_id"], session["level"])
    missed_words = _missed_words_text(session.get("wrong_questions"))
    n_practice = 10
    bounded_recognition_history = _bound_history(req.recognition_history, 60)

    prompt = assemble(
        compact_kb(kb),
        remediation_task(
            missed_words,
            session.get("weak_area") or "",
            session.get("distinction_feedback") or "",
            session.get("application_feedback") or "",
            n_practice,
            bounded_recognition_history,
            _bound_history(req.distinction_history, 30),
            _bound_history(req.application_history, 30),
        ),
    )
    raw = ask(prompt)
    data = parse_ai_json(raw)
    questions = _parse_mcq_rows(data["q"], n_practice)

    duplicate_violation = (
        _find_duplicate([q["question"] for q in questions], req.recognition_history)
        or _find_duplicate([data["d"]], req.distinction_history)
        or _find_duplicate([data["a"]], req.application_history)
    )
    if duplicate_violation:
        raise HTTPException(status_code=502, detail=f"{duplicate_violation}, thử lại.")
    _determine_and_verify_answers(kb, questions)
    _charge_keys(user["id"], 1)

    session["practice_questions"] = questions
    session["practice_secure_answer_key"] = {str(q["id"]): q["correct_index"] for q in questions}
    session["practice_distinction_prompt"] = data["d"]
    session["practice_application_prompt"] = data["a"]
    session["current_state"] = "REMEDIATION_MCQ"

    return {
        "recap": data.get("recap", ""),
        "practice_questions": [{"id": q["id"], "question": q["question"], "options": q["options"]} for q in questions],
        "keys_remaining": db.get_keys(user["id"]),
    }


@app.post("/api/chat/submit-remediation-mcq")
def submit_remediation_mcq(req: RemediationMCQRequest, user=Depends(get_current_user)):
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
def submit_remediation_open_ended(req: RemediationOpenEndedRequest, user=Depends(get_current_user)):
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
def generate_analysis(req: AnalysisRequest, user=Depends(get_current_user)):
    """1 lời gọi AI, do frontend gọi khi mở trang Analysis (đã tự cache ở
    client). Không dùng session_store - input là nhóm từ yếu nhất frontend
    tự chọn từ localStorage."""
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


# ---------- đăng nhập Google + đồng bộ tiến độ (không bắt buộc, chỉ để backup
# localStorage giữa các thiết bị) ----------

@app.post("/api/auth/google")
def google_login(req: GoogleAuthRequest):
    try:
        idinfo = google_id_token.verify_oauth2_token(
            req.credential, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Token Google không hợp lệ hoặc đã hết hạn.")

    user = db.upsert_user(
        google_sub=idinfo["sub"],
        email=idinfo.get("email", ""),
        name=idinfo.get("name", ""),
        picture=idinfo.get("picture", ""),
    )
    token = db.create_session(user["id"])
    return {
        "token": token,
        "user": {"email": user["email"], "name": user["name"], "picture": user["picture"]},
    }


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        db.delete_session(authorization.removeprefix("Bearer ").strip())
    return {"ok": True}


@app.get("/api/auth/me")
def get_me(user=Depends(get_current_user)):
    return {
        "email": user["email"],
        "name": user["name"],
        "picture": user["picture"],
        "keys": user["keys"],
        "purchase_count": user["purchase_count"],
    }


@app.delete("/api/auth/delete-account")
def delete_account(user=Depends(get_current_user)):
    """Xoá vĩnh viễn tài khoản + toàn bộ tiến độ đã lưu trên server. Không thể
    khôi phục - frontend phải xác nhận rõ ràng với người dùng trước khi gọi."""
    db.delete_user(user["id"])
    return {"ok": True}


@app.post("/api/progress/save")
def save_progress(req: ProgressSaveRequest, user=Depends(get_current_user)):
    db.save_progress(user["id"], req.data)
    return {"ok": True}


@app.get("/api/progress/load")
def load_progress_endpoint(user=Depends(get_current_user)):
    return {"data": db.load_progress(user["id"])}


# ---------- Key Shop ----------

# Phải khớp chính xác bảng KEY_SHOP_PACKAGES ở js/core/App.js (thứ tự + giá
# trị). Server tự tính bonus theo purchase_count của tài khoản, không tin số
# client gửi lên.
_KEY_SHOP_PACKAGES = [
    {"keys": 10, "bonus10": 1, "bonus20": 1, "bonus50": 1},
    {"keys": 25, "bonus10": 1, "bonus20": 2, "bonus50": 2},
    {"keys": 50, "bonus10": 2, "bonus20": 3, "bonus50": 5},
    {"keys": 100, "bonus10": 3, "bonus20": 5, "bonus50": 8},
    {"keys": 250, "bonus10": 5, "bonus20": 10, "bonus50": 15},
    {"keys": 500, "bonus10": 10, "bonus20": 20, "bonus50": 30},
]

# VNĐ - nguồn giá trị thật duy nhất, client không tự gửi số tiền lên. Phải
# khớp thứ tự với _KEY_SHOP_PACKAGES ở trên.
_KEY_SHOP_PRICES_VND = [10_000, 20_000, 35_000, 60_000, 135_000, 250_000]
assert len(_KEY_SHOP_PRICES_VND) == len(_KEY_SHOP_PACKAGES)

_REFERENCE_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _key_shop_bonus_for_count(pkg: dict, purchase_count: int) -> int:
    if purchase_count >= 50:
        return pkg["bonus50"]
    if purchase_count >= 20:
        return pkg["bonus20"]
    if purchase_count >= 10:
        return pkg["bonus10"]
    return 0


def _generate_reference_code() -> str:
    """"IOC" + 8 ký tự ngẫu nhiên (secrets vì đây là tiền thật). Độ dài cố định
    đảm bảo không mã nào là chuỗi con của mã khác, nên webhook đối chiếu theo
    kiểu "chứa" không bị nhập nhằng."""
    suffix = "".join(secrets.choice(_REFERENCE_CODE_ALPHABET) for _ in range(8))
    return f"IOC{suffix}"


def _static_qr_url(package_index: int) -> str:
    """Ảnh QR tĩnh (tạo qua SePay) cho từng gói, không mang nội dung chuyển
    khoản riêng theo giao dịch - vì vậy webhook cần thêm lớp đối chiếu theo số
    tiền làm dự phòng (xem sepay_webhook())."""
    return f"assets/images/keyshop-qr-{package_index}.png"


def _verify_sepay_auth(authorization: str | None) -> bool:
    """SEPAY_API_KEY trống phải luôn bị từ chối - không coi là "chưa cấu hình
    nên cho qua", nếu không endpoint này thành cổng cộng key không cần xác thực."""
    if not SEPAY_API_KEY:
        return False
    if not authorization or not authorization.startswith("Apikey "):
        return False
    provided = authorization.removeprefix("Apikey ").strip()
    if not provided:
        return False
    return hmac.compare_digest(provided, SEPAY_API_KEY)


@app.post("/api/keys/create-payment")
def create_payment(req: CreatePaymentRequest, user=Depends(get_current_user)):
    if req.package_index < 0 or req.package_index >= len(_KEY_SHOP_PACKAGES):
        raise HTTPException(status_code=400, detail="Gói key không hợp lệ.")

    # Dọn hết hạn trước khi xét tái sử dụng, tránh trả nhầm 1 giao dịch cũ đã quá hạn.
    db.expire_stale_pending_payments()

    existing = db.get_active_pending_payment(user["id"], req.package_index)
    if existing:
        return {
            "reference_code": existing["reference_code"],
            "amount_vnd": existing["amount_vnd"],
            "qr_url": _static_qr_url(req.package_index),
            "expires_at": (existing["created_at"] + timedelta(minutes=db.PENDING_PAYMENT_TTL_MINUTES)).isoformat(),
        }

    amount_vnd = _KEY_SHOP_PRICES_VND[req.package_index]
    for _ in range(5):
        reference_code = _generate_reference_code()
        try:
            payment = db.create_pending_payment(reference_code, user["id"], req.package_index, amount_vnd)
            break
        except psycopg.errors.UniqueViolation:
            continue
    else:
        raise HTTPException(status_code=500, detail="Không tạo được mã thanh toán, thử lại.")

    return {
        "reference_code": reference_code,
        "amount_vnd": amount_vnd,
        "qr_url": _static_qr_url(req.package_index),
        "expires_at": (payment["created_at"] + timedelta(minutes=db.PENDING_PAYMENT_TTL_MINUTES)).isoformat(),
    }


@app.get("/api/keys/payment-status/{reference_code}")
def get_payment_status(reference_code: str, user=Depends(get_current_user)):
    # Dọn hết hạn trước khi đọc trạng thái, để frontend thấy "expired" ngay ở lần poll tiếp theo.
    db.expire_stale_pending_payments()

    payment = db.get_pending_payment(reference_code)
    if not payment:
        raise HTTPException(status_code=404, detail="Không tìm thấy giao dịch.")
    if payment["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Giao dịch không thuộc về bạn.")

    if payment["status"] == "expired":
        return {"status": "expired"}
    if payment["status"] != "paid":
        # Việc frontend poll endpoint này chứng minh có người đang thật sự chờ
        # giao dịch - đánh dấu verified để webhook ưu tiên khớp đúng nó (xem
        # db.get_pending_payments_by_amount).
        db.mark_payment_verified(reference_code)
        return {"status": "pending"}

    return {"status": "paid", "keys": db.get_keys(user["id"]), "purchase_count": db.get_purchase_count(user["id"])}


class SePayWebhookPayload(BaseModel):
    id: int | str | None = None
    gateway: str | None = None
    transactionDate: str | None = None
    accountNumber: str | None = None
    code: str | None = None
    content: str = ""
    transferType: str | None = None
    description: str = ""
    transferAmount: float = 0
    accumulated: float | None = None
    referenceCode: str | None = None


@app.post("/api/webhooks/sepay")
def sepay_webhook(payload: SePayWebhookPayload, authorization: str | None = Header(default=None)):
    if not _verify_sepay_auth(authorization):
        raise HTTPException(status_code=401, detail="Không xác thực được webhook.")

    # Bắt buộc dọn trước khi so khớp: 1 giao dịch cũ còn 'pending' quá lâu có
    # thể bị FIFO chọn nhầm thay cho giao dịch thật (xem PENDING_PAYMENT_TTL_MINUTES trong db.py).
    db.expire_stale_pending_payments()

    # Từ đây là các nhánh quyết định KHÔNG cộng key - luôn trả success:true
    # theo đúng hợp đồng API của SePay. Không bọc try/except Exception rồi trả
    # success:true cho lỗi hệ thống thật: SePay sẽ không gọi lại, và tiền đã
    # vào mà key chưa cộng sẽ không còn cách nào phát hiện lại.
    if payload.transferType != "in":
        logger.info("SePay webhook: bỏ qua giao dịch không phải tiền vào (transferType=%s)", payload.transferType)
        return {"success": True}
    if BANK_ACCOUNT_NUMBER and payload.accountNumber != BANK_ACCOUNT_NUMBER:
        logger.warning("SePay webhook: accountNumber lạ (%s), bỏ qua.", payload.accountNumber)
        return {"success": True}

    # Lớp 1 (ưu tiên, chính xác tuyệt đối): đối chiếu mã tham chiếu trong nội
    # dung chuyển khoản - chỉ hoạt động nếu khách sửa nội dung trước khi chuyển.
    normalized = re.sub(r"[^A-Z0-9]", "", f"{payload.content} {payload.description}".upper())
    candidates = db.list_pending_reference_codes()
    content_matches = [code for code in candidates if code in normalized]

    payment = None
    if len(content_matches) == 1:
        payment = db.get_pending_payment(content_matches[0])
    elif len(content_matches) > 1:
        logger.warning(
            "SePay webhook: khớp NHIỀU mã tham chiếu theo nội dung (%s), cần đối soát thủ công - content=%r",
            content_matches, payload.content,
        )
        return {"success": True}

    # Lớp 2 (dự phòng): QR tĩnh không mang nội dung riêng theo giao dịch, nên
    # đối chiếu theo số tiền. Chỉ xét giao dịch đã 'verified' (get_payment_status
    # đánh dấu khi frontend thật sự poll màn hình QR - bằng chứng có người
    # đang chờ): loại các giao dịch pending chưa từng ai mở lên chờ, để tránh
    # FIFO chọn nhầm giao dịch rác/test thay cho giao dịch thật mới hơn. Nếu
    # có nhiều verified, ưu tiên giao dịch đăng ký trước; nếu không giao dịch
    # nào verified thì thà không cộng còn hơn cộng nhầm, để đối soát thủ công.
    if payment is None:
        amount_matches = db.get_pending_payments_by_amount(int(payload.transferAmount))
        if len(amount_matches) == 0:
            logger.warning(
                "SePay webhook: KHÔNG khớp giao dịch nào theo nội dung lẫn số tiền (tiền đã vào, cần đối soát "
                "thủ công) - content=%r amount=%s",
                payload.content, payload.transferAmount,
            )
            return {"success": True}
        verified_matches = [p for p in amount_matches if p["verified"]]
        if not verified_matches:
            logger.warning(
                "SePay webhook: có %d giao dịch chờ đúng số tiền %s nhưng CHƯA giao dịch nào được xác thực "
                "(chưa từng có ai mở màn hình QR chờ) - không đoán bừa, cần đối soát thủ công.",
                len(amount_matches), payload.transferAmount,
            )
            return {"success": True}
        if len(verified_matches) > 1:
            logger.warning(
                "SePay webhook: có %d giao dịch ĐÃ xác thực cùng chờ số tiền %s - tự động khớp giao dịch đăng "
                "ký trước trong số đó (mã %s, user_id=%s).",
                len(verified_matches), payload.transferAmount,
                verified_matches[0]["reference_code"], verified_matches[0]["user_id"],
            )
        payment = verified_matches[0]

    reference_code = payment["reference_code"]
    if int(payload.transferAmount) != payment["amount_vnd"]:
        logger.warning(
            "SePay webhook: số tiền không khớp mã %s (nhận %s, cần %s) - cần đối soát thủ công",
            reference_code, payload.transferAmount, payment["amount_vnd"],
        )
        return {"success": True}

    package = _KEY_SHOP_PACKAGES[payment["package_index"]]
    result = db.finalize_payment(reference_code, package, _key_shop_bonus_for_count)
    if result is None:
        logger.info("SePay webhook: mã %s đã được xử lý từ trước (webhook gọi lại), bỏ qua.", reference_code)
    else:
        logger.info(
            "SePay webhook: đã cộng %s key cho user_id=%s (mã %s).",
            result["amount_credited"], result["user_id"], reference_code,
        )
    return {"success": True}


# ---------- Feedback ----------
# Lưu thẳng vào DB, xem lại bằng prompt/view_feedback.py. Không yêu cầu đăng nhập.
@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest):
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Nội dung góp ý không được để trống.")
    db.save_feedback(req.name.strip(), content)
    return {"ok": True}


# ---------- phục vụ frontend tĩnh cùng origin với API (Google Sign-In yêu
# cầu origin http(s) đã đăng ký, không chạy được với file://). Chỉ mount các
# thư mục công khai, không mount cả BASE_DIR (tránh lộ server/.env).

app.mount("/js", StaticFiles(directory=str(BASE_DIR / "js")), name="static-js")
app.mount("/css", StaticFiles(directory=str(BASE_DIR / "css")), name="static-css")
app.mount("/assets", StaticFiles(directory=str(BASE_DIR / "assets")), name="static-assets")


@app.get("/")
@app.get("/index.html")
def serve_index():
    return FileResponse(str(BASE_DIR / "index.html"))


@app.get("/world1.html")
def serve_world1():
    return FileResponse(str(BASE_DIR / "world1.html"))


@app.get("/world2.html")
def serve_world2():
    return FileResponse(str(BASE_DIR / "world2.html"))
