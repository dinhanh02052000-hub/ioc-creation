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

import hashlib
import hmac
import logging
import os
import re
import secrets
import string
import threading
from typing import Any
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel

import confidence
import open_review
import remediation_plan
import engine_prompts as ep
import explanations
import open_grading
import db
import recognition_set
import review
import review_service
import scoring
from ai_json import parse_ai_json
import ai_router
from ai_client import AIProviderError, AIRateLimitError, ask
from analysis_prompts import analysis_task
from lesson_content import validate_lesson
from config import (
    BANK_ACCOUNT_NUMBER,
    BASE_DIR,
    GOOGLE_CLIENT_ID,
    SEPAY_API_KEY,
)
from engine_prompts import (
    lessons_block,
    report_judge_task,
    assemble,
    compact_kb,
    correction_per_question_task,
    correction_task,
    learning_content_task,
    lesson_kb_text,
    load_knowledge_base,
    open_ended_generation_task,
    remediation_task,
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


def _ask_for(role: str):
    """Hàm ask đã gắn model/effort của KHÂU `role` (xem ai_router). Tra `ask` lúc gọi nên kiểm thử thay main.ask vẫn có tác dụng."""
    return ai_router.routed(lambda prompt, **kw: ask(prompt, **kw), role)


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


assert open_grading.CRITERIA == {"distinction": DISTINCTION_CRITERIA, "application": APPLICATION_CRITERIA}, (
    "open_grading.CRITERIA phải trùng DISTINCTION_CRITERIA/APPLICATION_CRITERIA")


def _rubric_rows(scores: dict, criteria: dict, labels: dict) -> list[dict]:
    return [
        {"label": labels[key], "score": scores[key], "max": max_v}
        for key, max_v in criteria.items()
    ]


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
            if not h:
                continue
            sm = SequenceMatcher(None, nq, h)
            if (
                sm.real_quick_ratio() >= _DUPLICATE_SIMILARITY_THRESHOLD
                and sm.quick_ratio() >= _DUPLICATE_SIMILARITY_THRESHOLD
                and sm.ratio() >= _DUPLICATE_SIMILARITY_THRESHOLD
            ):
                return f"Câu {i + 1} trùng ý với 1 câu đã sinh trước đó cho level này"
    return None


def _bound_history(history: list[str] | None, max_entries: int) -> list[str]:
    """Cắt history để nhét vào prompt (tốn token), chỉ giữ các mục gần nhất.
    _find_duplicate dùng history đầy đủ, không qua hàm này, vì so sánh miễn phí."""
    if not history:
        return []
    return history[-max_entries:]


_LESSON_WAIT_SECONDS = 90


_HISTORY_SETS = 3           # chỉ chống lặp trong phạm vi 3 bộ đã phát gần nhất
_HISTORY_MAX_ITEMS = _HISTORY_SETS * 20


def _server_history(user_id: int, world_id: str, level: int, *extra: list[str]) -> list[str]:
    """Lịch sử câu để chống lặp: CHỈ các câu đã được HIỂN THỊ cho học sinh trong 3 bộ gần nhất của đúng người dùng,
    world, level, hợp nhất (giữ thứ tự, bỏ trùng) từ: (1) bảng issued_questions ở máy chủ, (2) lịch sử localStorage đã đồng bộ
    lên tài khoản (bảo toàn lịch sử cũ), (3) dữ liệu client/phiên gửi kèm; nguồn (2) và (3) cũng chỉ lấy phần cuối tương đương
    3 bộ. Bản nháp bị loại không bao giờ vào đây. Lỗi đọc một nguồn không chặn việc sinh."""
    merged: list[str] = []
    try:
        merged += db.load_issued_questions(user_id, world_id, level, _HISTORY_SETS)
    except Exception:  # noqa: BLE001
        logger.exception("Không đọc được lịch sử câu đã phát từ DB")
    try:
        synced = (db.load_progress(user_id) or {}).get("ioc_recognition_history")
        listed = synced.get(f"{world_id}:{level}") if isinstance(synced, dict) else None
        if isinstance(listed, list):
            merged += [x for x in listed if isinstance(x, str)][-_HISTORY_MAX_ITEMS:]
    except Exception:  # noqa: BLE001
        logger.exception("Không đọc được lịch sử đã đồng bộ từ tiến độ tài khoản")
    for part in extra:
        merged += [x for x in (part or []) if isinstance(x, str)][-_HISTORY_MAX_ITEMS:]
    return list(dict.fromkeys(x for x in merged if x.strip()))


def _lesson_refs(session: dict, wait: bool) -> list[str]:
    """Các câu tiếng Anh trong Present Knowledge thực tế của lượt học. Bộ Recognition được sinh song song
    với bài giảng nên wait=True chờ (có giới hạn) bài giảng xong trước bước kiểm tra cuối."""
    ev = session.get("lesson_event")
    if ev is not None and wait:
        ev.wait(timeout=_LESSON_WAIT_SECONDS)
    return list(session.get("lesson_sentences") or [])


# Một khóa cho mỗi (user, world, level): việc PHÁT bộ đề (kiểm lại lịch sử, trừ key, lưu, ghi lịch sử) là một
# đoạn găng nên bấm lại / mở hai tab không phát hai bộ hay trừ key hai lần. Đủ cho 1 tiến trình duy nhất (cùng
# giả định với session_store); nhiều instance cần chuyển sang khóa ở DB.
_ISSUE_LOCKS: dict[tuple, threading.Lock] = {}
_ISSUE_LOCKS_GUARD = threading.Lock()


def _issue_lock(user_id: int, world_id: str, level: int) -> threading.Lock:
    with _ISSUE_LOCKS_GUARD:
        return _ISSUE_LOCKS.setdefault((user_id, world_id, level), threading.Lock())


def _build_recognition_set(session: dict, user_id: int, kb: dict, is_retry: bool,
                           kept: list[dict] | None = None, plan: dict | None = None) -> dict:
    """Sinh (hoặc sửa một phần) bộ 20 câu qua pipeline recognition_set. Trả payload {set_id, format, questions, plan}.
    Nếu lần trước hết vòng mà chưa đủ, các câu đã đạt được giữ trong phiên và dùng lại: chỉ sinh bù phần thiếu."""
    world_id, level = session["world_id"], session["level"]
    if kept is None and session.get("partial_set"):
        kept, plan = session["partial_set"]["pool"], session["partial_set"]["plan"]
    try:
        payload = recognition_set.build_recognition_set(
            kb,
            ask_fn=ask,
            history_fn=lambda: _server_history(user_id, world_id, level, session.get("recognition_history") or []),
            refs_fn=lambda wait: _lesson_refs(session, wait),
            is_retry=is_retry,
            lessons_text=lessons_block(_safe_lessons(world_id, level, "recognition")),
            kept=kept,
            plan=plan,
            answer_model=os.environ.get("OPENAI_ANSWER_MODEL") or None,
        )
    except HTTPException as e:
        partial = getattr(e, "partial", None)
        if partial and partial["pool"]:
            session["partial_set"] = partial
        raise
    session["partial_set"] = None
    return payload


def _legacy_set_id(questions: list[dict]) -> str:
    raw = "\n".join(str(q.get("question")) for q in questions)
    return "legacy-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _prepare_set_for_issue(session: dict, user_id: int, kb: dict, candidate: dict | None,
                           extra_history: list[str]) -> dict:
    """Bước kiểm cuối ngay trước khi phát bộ CHƯA phát: đối chiếu lại với lịch sử mới nhất của tài khoản, ví dụ
    KB và Present Knowledge thực tế (bước này không cần AI). Câu vướng thì chỉ thay đúng các vị trí đó; bộ cũ
    không có kế hoạch (tạo trước thay đổi) mà không hợp lệ thì sinh lại cả bộ."""
    is_retry = bool(session.get("is_retry"))
    if not candidate or not candidate.get("questions"):
        return _build_recognition_set(session, user_id, kb, is_retry)
    if candidate.get("format") != recognition_set.SET_FORMAT:
        # Bộ chưa phát mà thiếu hồ sơ kiểm định (tạo trước quy trình mới): không phát, sinh lại bằng quy trình mới.
        return _build_recognition_set(session, user_id, kb, is_retry)
    history = _server_history(user_id, session["world_id"], session["level"], extra_history)
    bad = recognition_set.recheck_questions(
        candidate["questions"], kb, history, _lesson_refs(session, True))
    try:  # phiên bản câu đang bị gắn cờ/tạm ngừng/loại thì chặn khỏi đề chính thức
        blocked = db.blocked_version_ids(session["world_id"], session["level"])
    except Exception:  # noqa: BLE001
        logger.exception("Không đọc được danh sách phiên bản bị tạm ngừng")
        blocked = set()
    if blocked:
        for i, q in enumerate(candidate["questions"]):
            if review.question_version_id(session["world_id"], session["level"], q["question"], q["options"]) in blocked:
                bad.append(i)
        bad = sorted(set(bad))
    if not bad:
        return candidate
    if candidate.get("format") == recognition_set.SET_FORMAT and candidate.get("plan"):
        kept = [recognition_set.item_from_question(q) for i, q in enumerate(candidate["questions"]) if i not in bad]
        return _build_recognition_set(session, user_id, kb, is_retry, kept=kept, plan=candidate["plan"])
    return _build_recognition_set(session, user_id, kb, is_retry)


# ---------- Sinh sẵn câu hỏi ở nền (prefetch) ----------
# Bộ 20 câu recognition được sinh + thẩm định ngay khi học sinh còn đọc bài (/start), 2 câu mở được sinh
# trong lúc học sinh đọc kết quả recognition. Mọi lỗi được bắt và sửa trong recognition_set (chỉ sinh lại
# các vị trí hỏng, có giới hạn vòng), nên thứ học sinh nhìn thấy luôn là bản đã qua kiểm định.

_PREP_MAX_ATTEMPTS = 3
_PREP_WAIT_SECONDS = 900  # pipeline kiểm định nhiều vòng có thể mất vài phút với nhóm từ rất gần nghĩa


def _safe_lessons(world_id: str, level: int, group: str) -> list[str]:
    """Quy tắc rút kinh nghiệm ĐANG HIỆU LỰC (đã duyệt, đúng world/level) cho prompt sinh/chấm. Báo cáo được công nhận
    hay ghi chú AI chưa duyệt KHÔNG vào prompt; ghi chú cũ (user_reports.lesson) giữ nguyên ở DB nhưng chưa được
    ai phụ trách duyệt nên không được dùng."""
    try:
        return [
            f"[{r['scope']}] Khi {r['condition']}: {r['guidance']} (ví dụ cần chặn: {r['block_example']}; "
            f"ví dụ hợp lệ phải giữ: {r['keep_example']})"
            for r in db.approved_rules(world_id, level, domain="open" if group == "open" else "recognition")
        ]
    except Exception:  # noqa: BLE001
        logger.exception("Không đọc được quy tắc đã duyệt")
        return []


def _start_recognition_prep(session: dict, user_id: int, is_retry: bool) -> None:
    prep = {"status": "pending", "payload": None, "questions": None, "event": threading.Event()}
    session["prep"] = prep

    def work():
        try:
            kb = load_knowledge_base(session["world_id"], session["level"])
            payload = _build_recognition_set(session, user_id, kb, is_retry)
            prep["payload"] = payload
            prep["questions"] = payload["questions"]
            prep["status"] = "ready"
            with _issue_lock(user_id, session["world_id"], session["level"]):
                stored = db.load_question_set(user_id, session["world_id"], session["level"])
                # Không bao giờ ghi đè bộ đã phát (học sinh đang làm dở) bằng bộ mới sinh ở tab khác.
                if not (stored and stored.get("charged")):
                    db.save_question_set(
                        user_id, session["world_id"], session["level"], {**payload, "charged": False}
                    )
        except Exception:  # noqa: BLE001
            logger.exception("Sinh sẵn bộ recognition thất bại (sẽ sinh lại khi học sinh bấm bắt đầu)")
            prep["status"] = "failed"
        finally:
            prep["event"].set()

    threading.Thread(target=work, daemon=True).start()


def _start_open_ended_prep(session: dict, distinction_history: list[str], application_history: list[str]) -> None:
    prep = {"status": "pending", "d": None, "a": None, "event": threading.Event()}
    session["open_prep"] = prep

    def work():
        try:
            kb = load_knowledge_base(session["world_id"], session["level"])
            used_questions = [q["question"] for q in (session.get("generated_questions") or [])]
            for _ in range(2):
                prompt = assemble(
                    compact_kb(kb),
                    open_ended_generation_task(
                        used_questions,
                        _bound_history(distinction_history, 30),
                        _bound_history(application_history, 30),
                    ),
                )
                data = parse_ai_json(_ask_for("open_gen")(prompt))
                if (
                    isinstance(data.get("d"), str) and isinstance(data.get("a"), str)
                    and not _find_duplicate([data["d"]], distinction_history)
                    and not _find_duplicate([data["a"]], application_history)
                ):
                    prep["d"], prep["a"] = data["d"], data["a"]
                    prep["status"] = "ready"
                    return
            prep["status"] = "failed"
        except Exception:  # noqa: BLE001
            logger.exception("Sinh sẵn 2 câu mở thất bại (sẽ sinh lại khi học sinh nhập điểm tự tin)")
            prep["status"] = "failed"
        finally:
            prep["event"].set()

    threading.Thread(target=work, daemon=True).start()



_REMEDIATION_PRACTICE_N = 10


def _missed_target_words(wrong_questions: list[dict] | None, kb: dict) -> list[str]:
    """Từ mục tiêu (đúng cách viết trong KB) mà học sinh hay nhầm: dùng để ưu tiên câu dư trong kế hoạch bộ ôn tập."""
    keys = {recognition_set.norm_text(k): k for k in kb["target_words"]}
    out: list[str] = []
    for wq in wrong_questions or []:
        k = keys.get(recognition_set.norm_text(wq["options"][wq["correct_index"]]))
        if k and k not in out:
            out.append(k)
    return out


def _generate_remediation_text(session: dict, kb: dict, d_history: list[str], a_history: list[str], focus_note: str = "") -> dict:
    """recap + 1 câu Distinction + 1 tình huống Application. Kiểm: đủ 3 trường là chuỗi, không trùng lịch sử; thử lại hữu hạn."""
    lessons = _safe_lessons(session["world_id"], session["level"], "recognition")
    last_error: Exception | None = None
    for _ in range(_PREP_MAX_ATTEMPTS):
        try:
            prompt = assemble(
                compact_kb(kb),
                remediation_task(
                    _missed_words_text(session.get("wrong_questions")),
                    session.get("weak_area") or "",
                    session.get("distinction_feedback") or "",
                    session.get("application_feedback") or "",
                    _bound_history(d_history, 30),
                    _bound_history(a_history, 30),
                    focus_note,
                ),
                lessons_block(lessons),
            )
            data = parse_ai_json(_ask_for("open_gen")(prompt))
            if not all(isinstance(data.get(k), str) and data[k].strip() for k in ("recap", "d", "a")):
                raise HTTPException(status_code=502, detail="Gói ôn tập thiếu recap/câu Distinction/tình huống Application, thử lại.")
            violation = _find_duplicate([data["d"]], d_history) or _find_duplicate([data["a"]], a_history)
            if violation:
                raise HTTPException(status_code=502, detail=violation)
            return {"recap": data["recap"], "d": data["d"], "a": data["a"]}
        except AIRateLimitError:
            raise
        except (HTTPException, AIProviderError, KeyError, ValueError, TypeError) as e:
            last_error = e
    raise last_error  # type: ignore[misc]


def _generate_remediation_pack(session: dict, user_id: int, d_history: list[str], a_history: list[str]) -> dict:
    """Bộ ôn tập: 10 câu trắc nghiệm đi qua ĐÚNG quy trình sinh/thẩm định/chống lặp của bộ Recognition chính thức
    (kế hoạch bằng code, thẩm định mù, mức khó, đúng một chỗ trống, 3 bộ gần nhất) + recap/Distinction/Application, chạy song song."""
    from concurrent.futures import ThreadPoolExecutor

    kb = load_knowledge_base(session["world_id"], session["level"])
    world_id, level = session["world_id"], session["level"]
    focus = _missed_target_words(session.get("wrong_questions"), kb)

    def make_set() -> dict:
        return recognition_set.build_recognition_set(
            kb,
            ask_fn=ask,
            history_fn=lambda: _server_history(user_id, world_id, level, session.get("recognition_history") or []),
            refs_fn=lambda wait: _lesson_refs(session, wait),
            is_retry=True,
            lessons_text=lessons_block(_safe_lessons(world_id, level, "recognition")),
            answer_model=os.environ.get("OPENAI_ANSWER_MODEL") or None,
            size=_REMEDIATION_PRACTICE_N,
            focus_words=focus or None,
        )

    _mark_under_review(session, user_id)
    evidence = remediation_plan.collect_evidence(session)
    targets = remediation_plan.select_targets(evidence)
    focus_note = "; ".join(f"{remediation_plan.SKILL_LABEL[t['skill']]}: {t['action']}" for t in targets if t["evidence_level"] != "group")

    def make_cards() -> list[dict]:
        kb_text = compact_kb(kb)
        words = list(kb["target_words"])
        cards = [remediation_plan.build_card(_ask_for("cards"), parse_ai_json, t, words, kb_text) for t in targets]
        return [c for c in cards if c]

    with ThreadPoolExecutor(max_workers=3) as ex:
        f_set = ex.submit(make_set)
        f_text = ex.submit(_generate_remediation_text, session, kb, d_history, a_history, focus_note)
        f_cards = ex.submit(make_cards)
        text, payload = f_text.result(), f_set.result()
        try:
            cards = f_cards.result()
        except AIRateLimitError:
            raise
        except Exception:  # noqa: BLE001 - thẻ hỏng không chặn bộ luyện: dùng recap cũ, không dựng thẻ giả
            logger.exception("Không soạn được thẻ ôn")
            cards = []
    return {**text, "questions": payload["questions"], "set_id": payload["set_id"], "partial": payload.get("partial", False),
            "cards": cards, "targets": targets}


def _mark_under_review(session: dict, user_id: int) -> None:
    """Câu chính thức đang được xem lại không được dùng làm căn cứ chọn điểm yếu (các bằng chứng độc lập, đã chốt vẫn dùng)."""
    attempt_id = session.get("attempt_id")
    if not attempt_id or not session.get("wrong_questions"):
        return
    try:
        att = db.load_attempt(attempt_id)
        if not att:
            return
        states = _question_states_payload(att, user_id)
        for wq in session["wrong_questions"]:
            st = states.get(str(wq["id"]))
            if st and st["question"]["code"] == "answer_under_review":
                wq["under_review"] = True
    except Exception:  # noqa: BLE001
        logger.exception("Không đọc được trạng thái câu đang xem lại")


def _start_remediation_prep(session: dict, user_id: int, d_history: list[str], a_history: list[str]) -> None:
    """Sinh sẵn bộ ôn tập ở nền ngay khi học sinh nhận kết quả RETRY (lúc đang đọc báo cáo)."""
    prep = {"status": "pending", "pack": None, "event": threading.Event()}
    session["rem_prep"] = prep
    def work():
        try:
            prep["pack"] = _generate_remediation_pack(session, user_id, d_history, a_history)
            prep["status"] = "ready"
        except Exception:  # noqa: BLE001
            logger.exception("Sinh sẵn bộ ôn tập thất bại (sẽ sinh lại khi học sinh bấm ôn tập)")
            prep["status"] = "failed"
        finally:
            prep["event"].set()

    threading.Thread(target=work, daemon=True).start()


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
        summary_parts.append(f"(Các lựa chọn câu {wq['id']}: " + " | ".join(wq["options"]) + ")")
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
    recognition_history: list[str] = []  # câu đã sinh trước đó của level này, để sinh sẵn bộ mới không trùng
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
    distinction_history: list[str] = []  # để sinh sẵn 2 câu mở trong lúc học sinh đọc kết quả
    application_history: list[str] = []


class SubmitConfidenceRequest(BaseModel):
    session_id: str
    # Cách đo mới: hai dự đoán riêng. Kiểu Any cố ý: máy chủ tự xác thực nghiêm (confidence.normalize_input),
    # không để pydantic ép "5" thành 5.0 hay None thành giá trị mặc định.
    predictions: Any = None
    reasons: Any = None
    note: Any = None
    confidence: float | None = None   # cách đo cũ (1 điểm), chỉ để tương thích client chưa cập nhật
    distinction_history: list[str] = []
    application_history: list[str] = []


class SubmitOpenEndedRequest(BaseModel):
    session_id: str
    distinction_answer: str
    application_answer: str
    distinction_history: list[str] = []  # để sinh sẵn bộ ôn tập không trùng câu cũ
    application_history: list[str] = []


class ReportRequest(BaseModel):
    session_id: str
    kind: str  # recognition | distinction | application
    question_id: int | None = None  # chỉ với recognition
    suggested_index: int | None = None  # recognition: lựa chọn người dùng cho là đúng
    explanation: str
    suggested_note: str = ""  # distinction/application: điểm/nhận xét người dùng cho là hợp lý


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


_LESSON_MAX_ATTEMPTS = 3


def _generate_lesson(kb: dict) -> dict:
    """Present Knowledge có cấu trúc (intro/words/contrast). Máy chủ kiểm tra cấu
    trúc, nếu chưa đạt thì đưa lỗi cụ thể cho AI sửa, tối đa _LESSON_MAX_ATTEMPTS lần;
    vẫn hỏng thì 502 như các bước AI khác."""
    words = list(kb["target_words"].keys())
    kb_text = lesson_kb_text(kb)
    errors: list[str] = []
    for _ in range(_LESSON_MAX_ATTEMPTS):
        raw = _ask_for("lesson")(assemble(kb_text, learning_content_task(words, errors)))
        try:
            data = parse_ai_json(raw)
        except ValueError:  # JSONDecodeError là con của ValueError
            errors = ["Đầu ra không phải JSON hợp lệ, chỉ trả đúng một đối tượng JSON theo schema."]
            continue
        errors, lesson = validate_lesson(data, words)
        if lesson:
            return lesson
        logger.warning("Bài giảng chưa đạt kiểm tra cấu trúc: %s", errors)
    raise HTTPException(status_code=502, detail="AI chưa soạn được bài giảng đạt yêu cầu cấu trúc. Vui lòng thử lại.")


@app.post("/api/chat/start")
def start_session(req: StartRequest, user=Depends(get_current_user)):
    try:
        kb = load_knowledge_base(req.world_id, req.level)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    session = create_session(req.world_id, req.level, req.is_retry)
    session["recognition_history"] = list(req.recognition_history)
    # Recognition được sinh song song với bài giảng; bước kiểm cuối cần đối chiếu với câu của bài giảng thực tế.
    session["lesson_event"] = threading.Event()
    session["lesson_sentences"] = []

    # Có bộ câu đã sinh từ lần vào trước (chưa nộp) thì dùng lại, không sinh/trừ key lần nữa. Bộ chưa phát sẽ
    # được kiểm lại với lịch sử mới nhất ở begin-recognition; bộ đã phát được mở lại nguyên trạng.
    stored = db.load_question_set(user["id"], req.world_id, req.level)
    if stored and stored.get("questions"):
        done = threading.Event()
        done.set()
        session["prep"] = {"status": "ready", "payload": stored, "questions": stored["questions"], "event": done}
    else:
        _start_recognition_prep(session, user["id"], req.is_retry)

    try:
        learning_content = _generate_lesson(kb)
        session["lesson_sentences"] = recognition_set.lesson_reference_sentences(learning_content)
    finally:
        session["lesson_event"].set()

    session["current_state"] = "READY_FOR_RECOGNITION"

    show_onboarding = req.world_id == "world-1" and req.level == 1 and not req.is_retry

    return {
        "session_id": session["session_id"],
        "show_onboarding": show_onboarding,
        "group_title": kb.get("group_title"),
        "learning_content": learning_content,
    }


def SESSIONS_LOOKUP(session_id: str | None):
    import session_store
    return session_store.SESSIONS.get(session_id) if session_id else None


class ResumeRequest(BaseModel):
    session_id: str | None = None
    world_id: str
    level: int
    is_retry: bool = False
    recognition_history: list[str] = []


@app.post("/api/chat/resume-session")
def resume_session(req: ResumeRequest, user=Depends(get_current_user)):
    """Vào lại giữa chừng khi phiên trong RAM đã mất (máy chủ khởi động lại/deploy): dựng phiên mới KHÔNG sinh lại bài học và KHÔNG sinh/trừ key lại.
    - Có bộ câu ĐÃ phát (chưa nộp) trong DB: mở lại đúng bộ đó, đúng thứ tự lựa chọn (state WAITING_RECOGNITION_SUBMISSION).
    - Chưa phát: phiên sẵn sàng phát đề (READY_FOR_RECOGNITION), dùng bộ sinh sẵn nếu có. Phiên còn sống thì trả lại nguyên.
    Chỉ dùng cho giai đoạn học/làm trắc nghiệm; sau khi nộp, tiến trình nằm trong phiên đã chấm."""
    existing = SESSIONS_LOOKUP(req.session_id) if req.session_id else None
    if existing and existing.get("world_id") == req.world_id and existing.get("level") == req.level:
        resp = {"session_id": existing["session_id"], "state": existing["current_state"], "recovered": False}
        if existing["current_state"] == "WAITING_RECOGNITION_SUBMISSION" and existing.get("generated_questions"):
            resp.update(_recognition_response(user["id"], existing["generated_questions"], bool(existing.get("is_retry")), True))
        return resp

    try:
        load_knowledge_base(req.world_id, req.level)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    session = create_session(req.world_id, req.level, req.is_retry)
    session["recognition_history"] = list(req.recognition_history)
    session["lesson_event"] = threading.Event()
    session["lesson_event"].set()
    session["lesson_sentences"] = []
    stored = db.load_question_set(user["id"], req.world_id, req.level)
    if stored and stored.get("charged") and stored.get("questions"):
        questions = stored["questions"]
        session["set_id"] = stored.get("set_id")
        session["generated_questions"] = questions
        session["secure_answer_key"] = {str(q["id"]): q["correct_index"] for q in questions}
        session["recognition_history"] = list(dict.fromkeys(session["recognition_history"] + [q["question"] for q in questions]))
        session["current_state"] = "WAITING_RECOGNITION_SUBMISSION"
        return {"session_id": session["session_id"], "state": session["current_state"], "recovered": True,
                **_recognition_response(user["id"], questions, req.is_retry, True)}
    if stored and stored.get("questions"):
        done = threading.Event()
        done.set()
        session["prep"] = {"status": "ready", "payload": stored, "questions": stored["questions"], "event": done}
    else:
        _start_recognition_prep(session, user["id"], req.is_retry)
    session["current_state"] = "READY_FOR_RECOGNITION"
    return {"session_id": session["session_id"], "state": session["current_state"], "recovered": True}


def _recognition_response(user_id: int, questions: list[dict], is_retest: bool, resumed: bool) -> dict:
    # Chỉ gửi dữ liệu học sinh cần để làm bài; đáp án và ghi chú thẩm định ở lại máy chủ.
    return {
        "questions": [
            {"id": q["id"], "question": q["question"], "options": q["options"],
             # độ khó do AI thẩm định (chỉ có ở bộ tạo bằng quy trình mới); không gửi đáp án hay ghi chú thẩm định
             **({"difficulty": q["meta"]["difficulty"]} if (q.get("meta") or {}).get("difficulty") in ("easy", "medium", "hard") else {})}
            for q in questions
        ],
        "is_retest": is_retest,
        "resumed": resumed,
        "keys_remaining": db.get_keys(user_id),
    }


@app.post("/api/chat/begin-recognition")
def begin_recognition(req: SessionIdRequest, user=Depends(get_current_user)):
    session = get_session(req.session_id)
    # Bấm lại / gửi lại yêu cầu sau khi đã nhận đề trong cùng phiên: trả đúng bộ đang làm, không phát hay trừ key nữa.
    if session["current_state"] == "WAITING_RECOGNITION_SUBMISSION" and session.get("generated_questions"):
        return _recognition_response(user["id"], session["generated_questions"], bool(session.get("is_retry")), True)
    # RETRY/REMEDIATION_DONE = nút "Kiểm tra lại" (retest 20 câu, có hoặc
    # không qua ôn tập trước đó).
    if session["current_state"] not in ("READY_FOR_RECOGNITION", "RETRY", "REMEDIATION_DONE"):
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")

    world_id, level = session["world_id"], session["level"]
    is_retest = session["current_state"] in ("RETRY", "REMEDIATION_DONE")
    if is_retest:
        session["is_retry"] = True

    kb = load_knowledge_base(world_id, level)
    extra_history = list(session.get("recognition_history") or []) + list(req.recognition_history)

    # Chờ bộ sinh sẵn NGOÀI khóa (có thể lâu); việc phát đề nằm trong khóa bên dưới.
    prepped = None
    prep = session.get("prep")
    if prep is not None:
        # Bộ đang được sinh ở nền thì chờ chính nó (tránh sinh lần hai tốn gấp đôi); chỉ sinh lại khi nó thất bại.
        prep["event"].wait(timeout=_PREP_WAIT_SECONDS)
        if prep["status"] == "ready":
            prepped = prep["payload"]

    with _issue_lock(user["id"], world_id, level):
        stored = db.load_question_set(user["id"], world_id, level)
        if stored and stored.get("charged") and stored.get("questions"):
            # Mở lại bộ ĐÃ phát (thoát ra vào lại, tab khác, thiết bị khác): đúng câu, đúng thứ tự lựa chọn,
            # không trừ key và không ghi lịch sử lần nữa.
            payload, resumed = stored, True
        else:
            resumed = False
            _require_keys(user, 2)
            candidate = prepped or (stored if stored and stored.get("questions") else None)
            payload = _prepare_set_for_issue(session, user["id"], kb, candidate, extra_history)
            payload.setdefault("set_id", _legacy_set_id(payload["questions"]))
            _charge_keys(user["id"], 2)
            db.save_question_set(user["id"], world_id, level, {**payload, "charged": True})
            try:
                db.record_issued_set(
                    user["id"], world_id, level, payload["set_id"], "recognition",
                    [q["question"] for q in payload["questions"]],
                )
            except Exception:  # noqa: BLE001
                logger.exception("Không ghi được lịch sử bộ recognition đã phát")

    questions = payload["questions"]
    session["set_id"] = payload.get("set_id")
    session["prep"] = None
    session["recognition_history"] = list(dict.fromkeys(extra_history + [q["question"] for q in questions]))

    session["generated_questions"] = questions
    session["secure_answer_key"] = {str(q["id"]): q["correct_index"] for q in questions}
    session["current_state"] = "WAITING_RECOGNITION_SUBMISSION"

    return _recognition_response(user["id"], questions, is_retest, resumed)


def _mcq_wrong_list(questions: list[dict], grade_result: dict, snapshot: list[dict]) -> list[dict]:
    """Danh sách câu sai/bỏ trống theo kết quả chấm HIỆU LỰC (đã tính khóa sửa, nhiều đáp án, câu bị loại)."""
    wrong = []
    by_pos = {q["pos"]: q for q in snapshot}
    for q in questions:
        g = grade_result["per_question"][by_pos[q["id"]]["qv"]]
        if g["status"] not in ("wrong", "unanswered"):
            continue
        key_idx = next(i for i, o in enumerate(by_pos[q["id"]]["options"]) if o["oid"] in g["key_oids"])
        sel = next((i for i, o in enumerate(by_pos[q["id"]]["options"]) if o["oid"] == g["chosen"]), None)
        wrong.append({
            "id": q["id"], "question": q["question"], "options": q["options"], "correct_index": key_idx,
            "selected_index": sel, "type": "unanswered" if g["status"] == "unanswered" else "incorrect",
        })
    return wrong


_EXPLANATION_UNAVAILABLE = "Lời giải cho câu này hiện chưa sẵn sàng"


def _build_explanations(world_id: str, level: int, snapshot: list[dict], questions: list[dict], per_question: dict,
                        ids: set[int]) -> dict:
    """Soạn lời giải cho các câu `ids` bằng explanations.build (đầu ra AI được kiểm từng mục; lỗi một mục không làm mất mục khác).
    Máy chủ xác định đúng/sai, lựa chọn và khóa hiệu lực từ `per_question` (kết quả chấm); AI chỉ diễn giải."""
    snap_by_pos = {q["pos"]: q for q in snapshot}
    targets = [
        explanations.make_target(q, snap_by_pos[q["id"]], per_question[snap_by_pos[q["id"]]["qv"]])
        for q in questions if q["id"] in ids
    ]
    if not targets:
        return {"texts": {}, "partial": {}, "status": {}, "doubts": {}, "flagged": []}
    try:
        flagged = {f["qv"] for f in db.flags_for([t["qv"] for t in targets])
                   if f["status"] == "open" and f["flag_type"] == "answer_under_review"}
    except Exception:  # noqa: BLE001
        logger.exception("Không đọc được cờ đáp án khi soạn lời giải")
        flagged = set()

    def cache_get(key):
        try:
            return db.get_explanation(key)
        except Exception:  # noqa: BLE001
            return None

    def cache_put(key, text):
        try:
            db.put_explanation(key, text)
        except Exception:  # noqa: BLE001
            logger.exception("Không lưu được lời giải vào bộ nhớ dùng lại")

    try:
        kb_text = ep.lesson_kb_text(load_knowledge_base(world_id, level))
    except Exception:  # noqa: BLE001
        logger.exception("Không đọc được KB để soạn lời giải")
        return {"texts": {}, "partial": {}, "status": {str(t["id"]): explanations.STATUS_UNAVAILABLE for t in targets},
                "doubts": {}, "flagged": []}
    return explanations.build(
        _ask_for("explanation"), kb_text, targets, lambda kb, chunk, errors: assemble(kb, ep.explanation_task(chunk, errors)),
        flagged, cache_get, cache_put,
        review_prompt_fn=lambda kb, pairs: assemble(kb, ep.explanation_review_task(pairs)),
        review_ask_fn=_ask_for("explanation_review"))


def _apply_explanation_flags(expl: dict) -> None:
    """Nghi vấn đáp án do bước viết lời giải phát hiện -> cơ chế gắn cờ hiện có (không đổi khóa/điểm/hủy câu ở đây)."""
    for qv, reason in expl["flagged"]:
        try:
            db.open_flag(qv, "answer_under_review", f"Lời giải: {reason}"[:300], "explanation_check")
            db.set_version_status(qv, "paused")
        except Exception:  # noqa: BLE001
            logger.exception("Không gắn được cờ từ bước viết lời giải")


def _question_states_payload(att: dict, user_id: int) -> dict:
    qvs = [q["qv"] for q in att["snapshot"]]
    flags = db.flags_for(qvs)
    eff = review.effective_decisions(db.list_decisions(qvs, "applied"))
    mine = db.reports_for_attempt(user_id, att["attempt_id"])
    out = {}
    for q in att["snapshot"]:
        out[str(q["pos"])] = review.question_states(
            q, [f for f in flags if f["qv"] == q["qv"]], eff.get(q["qv"]), [r for r in mine if r["qv"] == q["qv"]])
        out[str(q["pos"])]["qv"] = q["qv"]
        out[str(q["pos"])]["options"] = [o["oid"] for o in q["options"]]
        out[str(q["pos"])]["audit_status"] = q["audit_status"]
        out[str(q["pos"])]["accepts_two_answers"] = bool(q.get("alt_oids"))
        # bản ghi cũ chưa có signals: nói đúng là thiếu dữ liệu kiểm định chi tiết (không gán 'đã xác minh')
        out[str(q["pos"])]["signals"] = review.apply_state_to_signals(
            q.get("signals") or review.quality_signals(None), out[str(q["pos"])]["question"]["code"])
    return out


@app.post("/api/chat/submit-recognition")
def submit_recognition(req: SubmitRecognitionRequest, user=Depends(get_current_user)):
    session = get_session(req.session_id)
    if session["current_state"] != "WAITING_RECOGNITION_SUBMISSION":
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")

    questions = session["generated_questions"]
    world_id, level = session["world_id"], session["level"]
    snapshot = review.build_snapshot(world_id, level, questions)
    answers_oid = review.answers_by_qv(snapshot, req.answers)
    attempt_no = session.get("attempt_no", 0) + 1
    attempt_id = f"{session['session_id']}:{attempt_no}"

    # Chấm bằng CODE từ lựa chọn gốc theo khóa/quyết định đang có hiệu lực của đúng phiên bản câu.
    try:
        qvs = [q["qv"] for q in snapshot]
        eff = review.effective_decisions(db.list_decisions(qvs, "applied"))
        tentative = {f["qv"] for f in db.flags_for(qvs) if f["status"] == "open" and f["flag_type"] == "answer_under_review"}
    except Exception:  # noqa: BLE001
        logger.exception("Không đọc được quyết định/cờ khi chấm; chấm theo khóa gốc")
        eff, tentative = {}, set()
    graded = review.grade(snapshot, answers_oid, eff, tentative)
    if graded["score"] is None:
        raise HTTPException(status_code=409, detail="Chưa thể tính điểm Nhận biết: mọi câu đang được xem lại.")
    wrong_questions = _mcq_wrong_list(questions, graded, snapshot)
    recognition = graded["score"]

    # LƯU ĐIỂM TRƯỚC KHI gọi AI: lời giải lỗi/thiếu không được làm mất điểm.
    persisted = True
    try:
        db.save_attempt(attempt_id, user["id"], world_id, level, session.get("set_id"), snapshot, answers_oid,
                        graded["correct"], graded["valid_total"], recognition)
    except Exception:  # noqa: BLE001
        persisted = False
        logger.exception("Không lưu được lượt làm Recognition (điểm vẫn trả về; báo cáo tạm thời không dùng được)")

    session["recognition"] = recognition
    session["attempt_no"] = attempt_no
    session["attempt_id"] = attempt_id
    session["confidence_pred"] = None
    session["confidence"] = None
    session["open_grading"] = None      # lượt làm mới: bài tự luận lần trước không dùng lại
    session["open_result"] = None
    session["user_recognition_answers"] = req.answers
    session["wrong_questions"] = wrong_questions  # Lưu trữ để dùng cho retest

    session["grade_per_question"] = graded["per_question"]
    wrong_ids = {w["id"] for w in wrong_questions}
    # Câu sai/bỏ trống được soạn lời giải ngay; câu đúng soạn khi học sinh bấm 'Xem giải thích' (tránh tốn token cho cả bộ).
    expl = _build_explanations(world_id, level, snapshot, questions, graded["per_question"], wrong_ids)
    _apply_explanation_flags(expl)
    if persisted:
        try:
            db.save_attempt_explanations(attempt_id, expl["texts"])
        except Exception:  # noqa: BLE001
            logger.exception("Không lưu được lời giải")
    session["explanations"] = dict(expl["texts"])
    session["explanation_partial"] = dict(expl["partial"])
    session["explanation_status"] = dict(expl["status"])

    session["current_state"] = "WAITING_CONFIDENCE"

    # Đã nộp: bộ câu này không còn dùng lại khi vào lại level.
    db.delete_question_set(user["id"], world_id, level)
    # Sinh sẵn 2 câu mở ngay bây giờ, trong lúc học sinh đọc kết quả recognition.
    _start_open_ended_prep(session, req.distinction_history, req.application_history)

    wrong_words = [
        {"selected": (wq["options"][wq["selected_index"]] if wq["selected_index"] is not None else None),
         "correct": wq["options"][wq["correct_index"]],
         "question": wq["question"]}
        for wq in wrong_questions
    ]
    states = _question_states_payload({"attempt_id": attempt_id, "snapshot": snapshot}, user["id"]) if persisted else {}
    return {
        "attempt_id": attempt_id if persisted else None,
        "recognition": recognition, "correct_count": graded["correct"], "valid_total": graded["valid_total"],
        "tentative": graded["tentative"],
        # Không bao giờ nói 'đúng tất cả' khi có câu sai; câu sai không có lời giải thì ghi trạng thái, không nhồi văn bản.
        "correction_text": "" if wrong_questions else "Bạn đã trả lời đúng tất cả các câu.",
        "explanations": expl["texts"], "explanation_status": expl["status"], "explanation_partial": expl["partial"],
        "question_states": states, "wrong_words": wrong_words,
        "correct_answers": {str(q["id"]): q["options"][q["correct_index"]] for q in questions},
    }


class ExplainQuestionRequest(BaseModel):
    session_id: str
    question_id: int
    practice: bool = False      # True: câu của bộ ôn tập (không lưu DB, không gắn cờ phiên bản)


class RegenerateExplanationsRequest(BaseModel):
    session_id: str
    practice: bool = False


def _expl_context(session: dict, practice: bool) -> dict:
    """Chọn bộ câu + kết quả chấm + nơi lưu lời giải theo bài chính thức hoặc bài ôn tập."""
    if practice:
        return {"questions": session.get("practice_questions"), "per_q": session.get("practice_per_question"),
                "texts": "practice_explanations", "partial": "practice_explanation_partial",
                "status": "practice_explanation_status", "persist": False, "wrong": None}
    return {"questions": session.get("generated_questions"), "per_q": session.get("grade_per_question"),
            "texts": "explanations", "partial": "explanation_partial", "status": "explanation_status", "persist": True,
            "wrong": session.get("wrong_questions")}


def _merge_ctx(session: dict, ctx: dict, attempt_id: str | None, expl: dict) -> None:
    session[ctx["texts"]] = {**(session.get(ctx["texts"]) or {}), **expl["texts"]}
    session[ctx["partial"]] = {**(session.get(ctx["partial"]) or {}), **expl["partial"]}
    session[ctx["status"]] = {**(session.get(ctx["status"]) or {}), **expl["status"]}
    for pos in expl["texts"]:
        session[ctx["partial"]].pop(pos, None)
    if ctx["persist"] and attempt_id:
        try:
            db.save_attempt_explanations(attempt_id, session[ctx["texts"]])
        except Exception:  # noqa: BLE001
            logger.exception("Không lưu được lời giải")


@app.post("/api/chat/regenerate-explanations")
def regenerate_explanations(req: RegenerateExplanationsRequest, user=Depends(get_current_user)):
    """Tạo lại RIÊNG các lời giải của câu sai còn thiếu do lỗi kỹ thuật (bài chính thức hoặc ôn tập). Không nộp lại bài, không tính lại
    lượt dùng, không đổi điểm, không chạy hai tiến trình trùng (khóa theo phiên). Câu đang bị xem lại đáp án không tạo lại ở đây."""
    session = get_session(req.session_id)
    ctx = _expl_context(session, req.practice)
    attempt_id = session.get("attempt_id")
    if ctx["per_q"] is None or ctx["questions"] is None or (ctx["persist"] and not attempt_id):
        raise HTTPException(status_code=409, detail="Chưa có kết quả để tạo lại lời giải.")
    lock_key = ("pexpl:" if req.practice else "expl:") + req.session_id
    with review_service._lock_for(lock_key):
        wrong_ids = {q["id"] for q in ctx["questions"] if ctx["per_q"][
            review.question_version_id(session["world_id"], session["level"], q["question"], q["options"])]["status"] in ("wrong", "unanswered")}
        have = set(int(k) for k in (session.get(ctx["texts"]) or {}))
        status = session.get(ctx["status"]) or {}
        missing = wrong_ids - have - {int(k) for k, v in status.items() if v == explanations.STATUS_UNDER_REVIEW}
        if not missing:
            return {"explanations": session.get(ctx["texts"]) or {}, "explanation_status": {},
                    "explanation_partial": session.get(ctx["partial"]) or {}}
        snapshot = review.build_snapshot(session["world_id"], session["level"], ctx["questions"])
        expl = _build_explanations(session["world_id"], session["level"], snapshot, ctx["questions"], ctx["per_q"], missing)
        if ctx["persist"]:
            _apply_explanation_flags(expl)
        _merge_ctx(session, ctx, attempt_id, expl)
    return {"explanations": session[ctx["texts"]], "explanation_status": expl["status"],
            "explanation_partial": session.get(ctx["partial"]) or {}}


@app.post("/api/chat/explain-question")
def explain_question(req: ExplainQuestionRequest, user=Depends(get_current_user)):
    """Soạn lời giải của MỘT câu theo yêu cầu (câu đúng: 'Xem giải thích', hoặc tạo lại riêng một câu). Không đổi điểm."""
    session = get_session(req.session_id)
    ctx = _expl_context(session, req.practice)
    attempt_id = session.get("attempt_id")
    if ctx["per_q"] is None or ctx["questions"] is None or (ctx["persist"] and not attempt_id):
        raise HTTPException(status_code=409, detail="Chưa có kết quả để soạn lời giải.")
    if not any(q["id"] == req.question_id for q in ctx["questions"]):
        raise HTTPException(status_code=404, detail="Không có câu này trong lượt làm.")
    pos = str(req.question_id)
    with review_service._lock_for(f"{'pexpl' if req.practice else 'expl'}:{req.session_id}:{pos}"):
        texts = session.get(ctx["texts"]) or {}
        if pos in texts:
            return {"text": texts[pos], "status": explanations.STATUS_READY, "partial": None}
        snapshot = review.build_snapshot(session["world_id"], session["level"], ctx["questions"])
        expl = _build_explanations(session["world_id"], session["level"], snapshot, ctx["questions"], ctx["per_q"], {req.question_id})
        if ctx["persist"]:
            _apply_explanation_flags(expl)
        _merge_ctx(session, ctx, attempt_id, expl)
    return {"text": expl["texts"].get(pos), "status": expl["status"].get(pos, explanations.STATUS_UNAVAILABLE),
            "partial": expl["partial"].get(pos)}


# ---------- trạng thái lượt làm + báo cáo theo loại (Recognition chính thức) ----------

_MAX_QUESTION_REPORTS_PER_DAY = 30


def _load_owned_attempt(attempt_id: str, user_id: int) -> dict:
    att = db.load_attempt(attempt_id)
    if not att or att["user_id"] != user_id:       # cùng thông điệp cho 'không có' và 'không phải của em'
        raise HTTPException(status_code=404, detail="Không tìm thấy lượt làm này.")
    return att


@app.get("/api/attempts/{attempt_id}")
def get_attempt_status(attempt_id: str, user=Depends(get_current_user)):
    att = _load_owned_attempt(attempt_id, user["id"])
    res = db.load_attempt_result(attempt_id)
    qvs = [q["qv"] for q in att["snapshot"]]
    decisions = db.list_decisions(qvs, "applied")
    g, _applied = review_service.grade_attempt(att)
    return {
        "attempt_id": attempt_id,
        "recognition": {"original": att["original_score"], "current": g["score"], "correct": g["correct"],
                        "valid_total": g["valid_total"], "tentative": g["tentative"],
                        "status": "cannot_score" if g["score"] is None else ("tentative" if g["tentative"] else "final")},
        "question_states": _question_states_payload(att, user["id"]),
        "explanations": att["explanations"],
        "result": (res or {}).get("current"), "result_original": (res or {}).get("original"),
        "revisions": (res or {}).get("revisions", []),
        "decisions": [{"qv": d["qv"], "type": d["decision_type"], "reason": d["reason"]} for d in decisions],
    }


class QuestionReportRequest(BaseModel):
    attempt_id: str
    qv: str
    report_type: Any = None
    option_oids: Any = None
    note: Any = None


@app.post("/api/report/recognition")
def submit_recognition_report(req: QuestionReportRequest, user=Depends(get_current_user)):
    att = _load_owned_attempt(req.attempt_id, user["id"])
    snap_q = next((q for q in att["snapshot"] if q["qv"] == req.qv), None)
    if snap_q is None:
        raise HTTPException(status_code=404, detail="Câu này không thuộc lượt làm của em.")
    try:
        v = review.validate_report(req.report_type, req.option_oids, req.note, snap_q)
    except review.ReportError as e:
        raise HTTPException(status_code=422, detail=str(e))
    existing = [r for r in db.reports_for_attempt(user["id"], req.attempt_id)
                if r["qv"] == req.qv and r["report_type"] == v["report_type"]]
    if not existing and db.count_question_reports_today(user["id"]) >= _MAX_QUESTION_REPORTS_PER_DAY:
        raise HTTPException(status_code=429, detail="Bạn đã gửi quá nhiều báo cáo hôm nay.")
    row, _created = db.create_report(
        user["id"], req.attempt_id, req.qv, v["report_type"], v["option_oids"], v["note"],
        review.case_id(req.qv, v["report_type"]))
    return _run_report_triage(row, att, snap_q, user["id"])


def _report_payload(row: dict, att: dict, user_id: int) -> dict:
    states = _question_states_payload(att, user_id)
    pos = str(next(q["pos"] for q in att["snapshot"] if q["qv"] == row["qv"]))
    return {"report_id": row["id"], "status": row["status"], "question": states[pos]["question"],
            "explanation": states[pos]["explanation"], "report": states[pos]["report"]}


def _run_report_triage(row: dict, att: dict, snap_q: dict, user_id: int) -> dict:
    """Xét báo cáo (idempotent): trạng thái đã có kết quả thì trả nguyên; chỉ 'received'/'pending_error' mới chạy lại."""
    with review_service._lock_for(f"report:{row['id']}"):
        fresh = next((r for r in db.reports_for_attempt(user_id, att["attempt_id"]) if r["id"] == row["id"]), row)
        if fresh["status"] not in ("received", "pending_error"):
            return _report_payload(fresh, att, user_id)
        db.update_report(fresh["id"], "reviewing")
        kb = load_knowledge_base(att["world_id"], att["level"])
        try:
            outcome = review_service.triage_report(_ask_for("report"), fresh, att, snap_q, kb)
            effects = review_service.apply_triage_effects(fresh, outcome)
            db.update_report(fresh["id"], outcome["status"], outcome, effects.get("decision_id"))
            result = outcome.get("result")
            if outcome["status"] == "accepted" and result and result["decision"] != "keep":
                # Quyết định riêng: rút quy tắc chung. Lỗi ở đây KHÔNG ảnh hưởng việc báo cáo đã được công nhận.
                review_service.propose_rule_from_report(
                    _ask_for("rules"), fresh, snap_q, result, kb, att["world_id"], att["level"])
        except AIRateLimitError:
            db.update_report(fresh["id"], "pending_error", {"error": "rate_limit"})
        except Exception as e:  # noqa: BLE001 - lỗi API/JSON hỏng/schema sai: chờ, KHÔNG phải 'báo cáo sai'
            logger.exception("Xét báo cáo thất bại, chuyển trạng thái chờ")
            db.update_report(fresh["id"], "pending_error", {"error": str(e)[:200]})
        after = next(r for r in db.reports_for_attempt(user_id, att["attempt_id"]) if r["id"] == row["id"])
        return _report_payload(after, att, user_id)


# Mô tả tiêu chí hiển thị ở bước Confidence. Khóa PHẢI trùng với DISTINCTION_CRITERIA/APPLICATION_CRITERIA (điểm tối
# đa lấy thẳng từ đó) để giao diện không nói một đằng, bộ chấm tính một nẻo.
_CONFIDENCE_RUBRIC_TEXT = {
    "distinction": {
        "hieu_goc": "Giải thích đúng nghĩa của từ trong câu",
        "ngu_canh": "Chỉ ra chi tiết trong ngữ cảnh khiến từ đó phù hợp",
        "doi_nghia": "Nêu nghĩa hoặc sắc thái thay đổi thế nào khi thay từ",
        "phan_biet": "Phân biệt chính xác hai từ",
        "so_sanh": "Lập luận rõ vì sao từ ban đầu phù hợp hơn",
    },
    "application": {
        "chon_tu": "Chọn từ phù hợp với tình huống",
        "dung_dung": "Viết câu tiếng Anh dùng từ đúng nghĩa và ngữ pháp",
        "tinh_huong": "Câu viết bám đúng tình huống",
        "giai_thich": "Giải thích có căn cứ vì sao chọn từ",
    },
}
assert set(_CONFIDENCE_RUBRIC_TEXT["distinction"]) == set(DISTINCTION_CRITERIA)
assert set(_CONFIDENCE_RUBRIC_TEXT["application"]) == set(APPLICATION_CRITERIA)


@app.get("/api/confidence/rubric")
def get_confidence_rubric():
    """Rubric đang dùng để chấm, dạng rút gọn cho màn hình Confidence (một nguồn với bộ chấm)."""
    def rows(skill: str, criteria: dict) -> list[dict]:
        return [{"key": k, "text": _CONFIDENCE_RUBRIC_TEXT[skill][k], "max": criteria[k]}
                for k in _CONFIDENCE_RUBRIC_TEXT[skill]]

    return {
        "distinction": {"total": sum(DISTINCTION_CRITERIA.values()), "criteria": rows("distinction", DISTINCTION_CRITERIA)},
        "application": {"total": sum(APPLICATION_CRITERIA.values()), "criteria": rows("application", APPLICATION_CRITERIA)},
        "reasons": list(confidence.REASON_IDS),
        "max_reasons": confidence.MAX_REASONS,
        "max_note_chars": confidence.MAX_NOTE_CHARS,
    }


def _open_prompts_response(session: dict) -> dict:
    return {
        "distinction_prompt": session["distinction_prompt"],
        "application_prompt": session["application_prompt"],
    }


@app.post("/api/chat/submit-confidence")
def submit_confidence(req: SubmitConfidenceRequest, user=Depends(get_current_user)):
    session = get_session(req.session_id)
    legacy = req.predictions is None and req.confidence is not None

    inputs = None
    if not legacy:
        try:
            inputs = confidence.normalize_input(req.predictions, req.reasons, req.note)
        except confidence.ConfidenceError as e:
            raise HTTPException(status_code=422, detail=str(e))

    # Gửi lại cùng một dự đoán sau khi đã khóa (bấm đúp, mạng chậm, mất phản hồi đầu, tải lại trang): trả đề đã
    # sinh, KHÔNG tạo bản thứ hai. Gửi dự đoán KHÁC khi đề đã hiện thì từ chối: dự đoán của lượt này đã khóa.
    locked = session.get("confidence_pred")
    if session["current_state"] == "WAITING_OPEN_ENDED_SUBMISSION" and locked and session.get("distinction_prompt"):
        if inputs is not None and inputs == locked["inputs"]:
            return _open_prompts_response(session)
        raise HTTPException(
            status_code=409, detail="Dự đoán của lượt này đã được khóa, không thể thay đổi sau khi đề đã hiện.")

    if session["current_state"] != "WAITING_CONFIDENCE":
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")

    if legacy:
        if not (0 <= req.confidence <= 10) or round(req.confidence * 2) != req.confidence * 2:
            raise HTTPException(status_code=422, detail="Confidence phải trong khoảng 0-10, bước nhảy 0.5.")
        session["confidence"] = req.confidence
        session["confidence_pred"] = None
    else:
        # KHÓA dự đoán trước khi đề mở được lấy ra để trả về: đề (đã sinh sẵn ở máy chủ) chỉ rời máy chủ sau bước này.
        record = {"measure": confidence.MEASURE_TWO_SKILL, "inputs": inputs,
                  "locked_at": datetime.now(timezone.utc).isoformat()}
        attempt_key = f"{session['session_id']}:{session.get('attempt_no', 1)}"
        try:
            stored, _created = db.lock_confidence_prediction(
                user["id"], session["world_id"], session["level"], attempt_key, confidence.MEASURE_TWO_SKILL, record)
        except Exception:  # noqa: BLE001
            logger.exception("Không lưu được dự đoán Confidence")
            raise HTTPException(status_code=503, detail="Chưa lưu được dự đoán của em. Vui lòng thử lại.")
        if stored["inputs"] != inputs:
            raise HTTPException(status_code=409, detail="Dự đoán của lượt này đã được khóa với giá trị khác.")
        session["confidence_pred"] = stored
        session["confidence"] = None

    prep = session.get("open_prep")
    data = None
    if prep is not None:
        prep["event"].wait(timeout=_PREP_WAIT_SECONDS)
        if prep["status"] == "ready":
            data = {"d": prep["d"], "a": prep["a"]}
    session["open_prep"] = None

    if data is None:
        # Không có bản sinh sẵn (hoặc thất bại): sinh ngay như cũ.
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
        data = parse_ai_json(_ask_for("open_gen")(prompt))

        duplicate_violation = (
            _find_duplicate([data["d"]], req.distinction_history)
            or _find_duplicate([data["a"]], req.application_history)
        )
        if duplicate_violation:
            raise HTTPException(status_code=502, detail=f"{duplicate_violation}, thử lại.")

    session["distinction_prompt"] = data["d"]
    session["application_prompt"] = data["a"]
    session["current_state"] = "WAITING_OPEN_ENDED_SUBMISSION"

    return _open_prompts_response(session)


_THIRD_GRADER_MODEL = os.environ.get("OPENAI_THIRD_GRADER_MODEL") or None   # model riêng cho người chấm thứ ba (nếu cấu hình)
_SPREAD_FLAG = float(open_grading.THIRD_PASS_THRESHOLD)   # lượt ba khi độ lệch > 0,75 (xem open_grading.needs_third_pass)


def _new_open_states(session: dict, d_answer: str, a_answer: str, d_question: str, a_question: str) -> dict:
    return {
        "version": open_grading.RUBRIC_VERSION,
        "distinction": open_grading.new_skill_state("distinction", d_answer, d_question),
        "application": open_grading.new_skill_state("application", a_answer, a_question),
    }


def _run_open_grading(world_id: str, level: int, states: dict) -> None:
    """Làm tiếp các lượt chấm còn thiếu (idempotent). Đầu vào chấm CHỈ gồm đề, bài làm, KB level và quy tắc đã duyệt:
    không có Confidence, điểm trắc nghiệm, Gap hay kết quả lượt khác."""
    kb = load_knowledge_base(world_id, level)
    open_grading.advance(
        states, ask, compact_kb(kb), _safe_lessons(world_id, level, "open"), _THIRD_GRADER_MODEL,
        pass_models={r: ai_router.model_for(r) for r in ("grade_1", "grade_2", "grade_3")},
        efforts={r: ai_router.effort_for(r) for r in ("grade_1", "grade_2", "grade_3")})
    if all(states[sk]["status"] in ("final", "empty") for sk in open_grading.SKILLS):
        _ensure_references(states, compact_kb(kb))


_REFERENCE_ATTEMPTS = 2


def _ensure_references(states: dict, kb_text: str) -> None:
    """Đáp án tham khảo phải qua kiểm tra cấu trúc/ngôn ngữ trước khi hiện. Bản lỗi: tạo lại RIÊNG (điểm đã chấm không đổi); vẫn lỗi
    thì ẩn đáp án mẫu (không hiện bản hỏng) và đánh dấu để học sinh/hệ thống biết đang thiếu."""
    def bad_skills() -> list[str]:
        return [sk for sk in open_grading.SKILLS if open_grading.validate_reference(sk, states[sk].get("model_answer")) is not None]

    for _ in range(_REFERENCE_ATTEMPTS):
        bad = bad_skills()
        if not bad:
            break
        parts = [{"skill": sk, "question": states[sk]["question"]} for sk in bad]
        try:
            data = parse_ai_json(_ask_for("grade_1")(engine_prompts.reference_only_prompt(kb_text, parts)))
        except AIRateLimitError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Không tạo lại được đáp án tham khảo")
            continue
        for sk in bad:
            cand = data.get("d_model" if sk == "distinction" else "a_model") if isinstance(data, dict) else None
            if open_grading.validate_reference(sk, cand) is None:
                states[sk]["model_answer"] = cand.strip()
    for sk in bad_skills():
        states[sk]["model_answer"] = ""
        states[sk]["reference_status"] = "unavailable"


def _open_data(states: dict) -> dict:
    d, a = states["distinction"], states["application"]
    return {
        "d_scores": d["final"]["scores"], "a_scores": a["final"]["scores"],
        "d_total": d["final"]["total"], "a_total": a["final"]["total"],
        "d_fb": d.get("feedback", ""), "a_fb": a.get("feedback", ""),
        "d_model": d.get("model_answer", ""), "a_model": a.get("model_answer", ""),
        "d_spread": d["deviation"], "a_spread": a["deviation"],
        "d_detail": open_grading.grading_detail("distinction", states["distinction"]),
        "a_detail": open_grading.grading_detail("application", states["application"]),
        "d_total_exact": d["final"]["total_exact"], "a_total_exact": a["final"]["total_exact"],
        "grading": {sk: {"status": states[sk]["status"], "deviation": states[sk]["deviation"],
                         "third_pass": len(states[sk]["passes"]) == 3, "method": states[sk]["final"]["method"],
                         "criterion_flags": states[sk]["final"]["flags"], "total_exact": states[sk]["final"]["total_exact"],
                         "rubric_version": states["version"]}
                    for sk in ("distinction", "application")},
    }


def _open_pending_payload(states: dict) -> dict:
    """Bài chưa đủ điều kiện chốt: KHÔNG công bố điểm tạm (kể cả trung bình hai lượt). Bài đã chốt vẫn giữ kết quả."""
    labels = {"pending_pass": "chờ hoàn tất lượt chấm đối chiếu", "pending_third_pass": "chờ hoàn tất lượt chấm thứ ba"}
    out = {"status": "pending", "pending": {}, "message": "Một phần bài chấm chưa hoàn tất. Em bấm 'Thử lại' để chấm nốt phần còn lại; kết quả đã có được giữ nguyên."}
    for sk in ("distinction", "application"):
        st = states[sk]
        if st["status"] in labels:
            out["pending"][sk] = {"status": st["status"], "label": labels[st["status"]], "valid_passes": len(st["passes"])}
        else:
            key = "d" if sk == "distinction" else "a"
            rubric_src = DISTINCTION_CRITERIA if sk == "distinction" else APPLICATION_CRITERIA
            lab = DISTINCTION_LABELS if sk == "distinction" else APPLICATION_LABELS
            out[f"{sk}_score"] = st["final"]["total"]
            out[f"{sk}_rubric"] = _rubric_rows(st["final"]["scores"], rubric_src, lab)
            out[f"{sk}_feedback"] = st.get("feedback", "")
    return out


def _persist_open_states(attempt_id: str | None, user_id: int, states: dict) -> None:
    if not attempt_id:
        return
    try:
        db.save_open_grading(attempt_id, user_id, states)
    except Exception:  # noqa: BLE001
        logger.exception("Không lưu được trạng thái chấm tự luận (không ảnh hưởng kết quả đang hiển thị)")


def _grade_open_ended_sync(world_id: str, level: int, d_q: str, d_a: str, a_q: str, a_a: str,
                           holder: dict | None = None, key: str = "practice_open_grading") -> dict:
    """Bài ôn tập: CÙNG bộ chấm hai lượt + lượt ba như bài chính thức. Trạng thái các lượt hợp lệ được giữ trong `holder[key]`
    nên bấm thử lại chỉ chấm nốt phần còn thiếu (không chấm lại từ đầu); chưa đủ lượt hợp lệ thì 502 để thử lại."""
    states = holder.get(key) if holder is not None else None
    if states is not None and (states["distinction"]["answer"] != d_a or states["application"]["answer"] != a_a
                               or states["distinction"]["question"] != d_q or states["application"]["question"] != a_q):
        states = None                                     # bài làm/đề khác: chấm mới
    if states is None:
        states = _new_open_states({}, d_a, a_a, d_q, a_q)
        if holder is not None:
            holder[key] = states
    _run_open_grading(world_id, level, states)
    if any(states[s]["status"] not in ("final", "empty") for s in ("distinction", "application")):
        raise HTTPException(status_code=502, detail="Chưa chấm xong (lượt chấm lỗi). Vui lòng thử lại, kết quả đã chấm được giữ.")
    return _open_data(states)


def _confidence_comparison(session: dict, d_score: float, a_score: float, d_scores: dict, a_scores: dict) -> dict:
    """Đối chiếu dự đoán đã khóa với điểm thực tế của đúng kỹ năng. Cách đo cũ (1 điểm) giữ công thức cũ.
    gap (dùng cho PASS/RETRY) là None khi chưa đánh giá được độ lệch; khi đó PASS/RETRY chỉ xét Overall."""
    locked = session.get("confidence_pred")
    if not locked:
        # Phiên cũ/Confidence chung: giữ nguyên công thức cũ (Confidence - Overall).
        overall = scoring.calc_overall(session["recognition"], d_score, a_score)
        conf = session.get("confidence")
        gap = scoring.calc_gap(conf, overall) if conf is not None else None
        return {
            "version": 1, "measure": confidence.MEASURE_LEGACY, "confidence": conf, "gap": gap,
            "illusion_status": scoring.classify_illusion(gap) if gap is not None else "NO_PREDICTION",
        }
    cmp = confidence.compare(locked["inputs"], d_score, a_score, session.get("recognition"))
    skills = cmp["skills"]
    for skill, scores, crit, labels in (
        ("distinction", d_scores, DISTINCTION_CRITERIA, DISTINCTION_LABELS),
        ("application", a_scores, APPLICATION_CRITERIA, APPLICATION_LABELS),
    ):
        sk = skills[skill]
        # Nhận xét tiêu chí chỉ khi dự đoán cao hơn kết quả VÀ điểm thành phần chứng minh được (không suy từ lý do).
        sk["weakest_criterion"] = (
            confidence.weakest_criterion(scores, crit, labels) if sk["gap"] is not None and sk["gap"] > 0 else None
        )
    return {
        "version": 2, "measure": confidence.MEASURE_TWO_SKILL, "confidence": cmp["confidence"],
        "confidence_source": cmp["confidence_source"], "actual_average": cmp["actual_average"],
        "reference_score": cmp["reference_score"], "reference_kind": cmp["reference_kind"],
        "formula_version": locked["inputs"].get("formula", 2),
        "gap": cmp["gap_total"], "typical_deviation": cmp["typical_deviation"], "state": cmp["state"],
        "offsetting": cmp["offsetting"], "skills": skills,
        "illusion_status": confidence.classify(cmp),
        "reasons": locked["inputs"]["reasons"], "note": locked["inputs"]["note"],
        "locked_at": locked.get("locked_at"),
    }


def _decision_note(decision: dict) -> str:
    """Lý do qua màn/ôn tập bằng tiếng Việt, một nguồn với scoring.decide_progress (không còn câu 'Overall >= 7 và |Gap| <= 1')."""
    if decision["decision"] == "PASS":
        return decision["reasons"][0]
    tail = ""
    if decision["review_target"]:
        tail = f" Mục tiêu ôn trước tiên: {decision['review_target']}."
    if decision["decision"] == "PASS_WITH_REVIEW":
        return decision["reasons"][0] + tail
    return "Em chưa qua màn lần này: " + " ".join(decision["reasons"]) + tail + " Mình ôn phần trọng tâm rồi thử lại nhé."


def _confidence_summary(comparison: dict) -> dict:
    """Confidence/Gap chính thức + hai dòng chi tiết, để giao diện chỉ việc hiển thị (không tự tính lại)."""
    if comparison["version"] == 1:
        return {"available": comparison["confidence"] is not None, "confidence": comparison["confidence"], "gap": comparison["gap"],
                "gap_text": "", "source": "legacy_single", "details": None,
                "reason": None if comparison["confidence"] is not None else "Chưa đủ dữ liệu tính Confidence/Gap"}
    sk = comparison["skills"]
    gap = comparison["gap"]
    return {
        "available": gap is not None, "confidence": comparison["confidence"], "gap": gap,
        "actual_average": comparison.get("actual_average"), "source": comparison.get("confidence_source"),
        "reference_score": comparison.get("reference_score"), "reference_kind": comparison.get("reference_kind"),
        "gap_text": scoring.describe_total_gap(gap, comparison.get("reference_kind") or "overall"),
        "typical_deviation": comparison.get("typical_deviation"),
        "details": {k: {"predicted": sk[k]["predicted"], "actual": sk[k]["actual"], "gap": sk[k]["gap"], "state": sk[k]["state"]}
                    for k in ("distinction", "application")},
        "reason": None if gap is not None else "Chưa đủ dữ liệu tính Confidence/Gap",
    }


def _finish_open_ended(session: dict, user: dict, states: dict, d_history: list[str], a_history: list[str]) -> dict:
    """Chốt kết quả khi CẢ HAI bài đã có điểm cuối hợp lệ. Công thức v3: tính trên số gốc, hiển thị 2 chữ số; qua màn theo
    điểm kiến thức (scoring.decide_progress), Gap chỉ dùng cho phản hồi tự đánh giá."""
    data = _open_data(states)
    d_scores, a_scores = data["d_scores"], data["a_scores"]
    distinction_score, application_score = data["d_total"], data["a_total"]      # đã là số 2 chữ số (bội của 0,25 nên không mất thông tin)
    d_exact, a_exact = data["d_total_exact"], data["a_total_exact"]

    overall = scoring.calc_overall_v3(session["recognition"], d_exact, a_exact)
    understanding = scoring.understanding_v3(session["recognition"], d_exact, a_exact)
    decision = scoring.decide_progress(session["recognition"], d_exact, a_exact)
    comparison = _confidence_comparison(session, distinction_score, application_score, d_scores, a_scores)
    gap = comparison["gap"]
    illusion = comparison["illusion_status"]
    skill_gaps = ({k: v["gap"] for k, v in comparison["skills"].items()} if comparison["version"] == 2 else None)
    calibration = scoring.calibration_v3(gap, skill_gaps)
    session["accuracy"] = overall  # hiển thị = Overall (tổng hợp recognition + distinction + application)
    final_result = decision["final_result"]
    weak_area = scoring.detect_weakness(session["recognition"], distinction_score, application_score)

    session.update({
        "distinction_score": distinction_score,
        "application_score": application_score,
        "overall": overall,
        "gap": gap,
        "confidence_comparison": comparison,
        "final_result": final_result,
        "progress_decision": decision,
        "d_scores": d_scores,
        "a_scores": a_scores,
        "distinction_feedback": data["d_fb"],
        "application_feedback": data["a_fb"],
        "weak_area": weak_area,
    })
    session["current_state"] = "LEVEL_COMPLETED" if final_result == "PASS" else "RETRY"
    attempt_id = session.get("attempt_id")
    if attempt_id:
        try:
            db.save_attempt_result(attempt_id, user["id"], distinction_score, application_score, {
                "recognition": session["recognition"], "distinction": distinction_score, "application": application_score,
                "overall": overall, "gap": gap, "final_result": final_result, "decision": decision["decision"],
                "formula_version": scoring.FORMULA_VERSION,
                "confidence": comparison.get("confidence") if comparison["version"] == 2 else None,
                "comparison_gap": comparison["gap"] if comparison["version"] == 2 else None,
                "legacy_confidence": comparison.get("confidence") if comparison["version"] == 1 else None,
                "confidence_version": comparison["version"],
            })
        except Exception:  # noqa: BLE001
            logger.exception("Không lưu được kết quả lượt làm (không ảnh hưởng điểm hiển thị)")
    if final_result != "PASS":
        # Sinh sẵn bộ ôn tập trong lúc học sinh đọc báo cáo. Bộ kiểm tra lại chỉ sinh khi học sinh thật sự bắt đầu
        # ôn tập (xem begin_remediation) để khỏi tốn token nếu họ bỏ giữa chừng.
        _start_remediation_prep(session, user["id"], d_history, a_history)

    result = {
        "recognition": session["recognition"],
        "accuracy": session["accuracy"],
        "distinction_score": distinction_score,
        "distinction_feedback": data["d_fb"],
        "distinction_rubric": _rubric_rows(d_scores, DISTINCTION_CRITERIA, DISTINCTION_LABELS),
        "application_score": application_score,
        "application_feedback": data["a_fb"],
        "application_rubric": _rubric_rows(a_scores, APPLICATION_CRITERIA, APPLICATION_LABELS),
        "distinction_model": data["d_model"],
        "application_model": data["a_model"],
        "grading_detail": {"distinction": data["d_detail"], "application": data["a_detail"]},
        "attempt_id": attempt_id,
        "submitted": {"distinction": {"question": states["distinction"]["question"], "answer": states["distinction"]["answer"]},
                      "application": {"question": states["application"]["question"], "answer": states["application"]["answer"]}},
        "grading_spread": {
            "distinction": data["d_spread"], "application": data["a_spread"], "flag_threshold": _SPREAD_FLAG,
        },
        "grading": data["grading"],
        "overall": overall,
        "confidence": comparison["confidence"],
        "gap": gap,
        "confidence_version": comparison["version"],
        "confidence_comparison": comparison,
        "confidence_summary": _confidence_summary(comparison),
        "calibration": calibration,
        "understanding": understanding,
        "understanding_level": understanding["code"],
        "illusion_status": illusion,
        "weak_area": weak_area,
        "final_result": final_result,
        "decision": decision["decision"],
        "decision_info": {**decision, "note": _decision_note(decision)},
        "formula_version": scoring.FORMULA_VERSION,
        "retry_note": None if final_result == "PASS" else _decision_note(decision),
    }
    session["open_result"] = result
    return result


def _advance_open_and_respond(session: dict, user: dict, d_history: list[str], a_history: list[str]) -> dict:
    states = session["open_grading"]
    _run_open_grading(session["world_id"], session["level"], states)
    _persist_open_states(session.get("attempt_id"), user["id"], states)
    if all(states[s]["status"] in ("final", "empty") for s in ("distinction", "application")):
        return _finish_open_ended(session, user, states, d_history, a_history)
    return _open_pending_payload(states)


@app.post("/api/chat/submit-open-ended")
def submit_open_ended(req: SubmitOpenEndedRequest, user=Depends(get_current_user)):
    session = get_session(req.session_id)
    # Nộp hai lần / tải lại: một lượt nộp chỉ có MỘT lần chấm, một lần ghi kết quả, một lượt ba. Cùng bài làm thì trả lại
    # kết quả (hoặc tiếp tục phần còn chờ); khác bài làm sau khi đã nộp thì từ chối.
    with review_service._lock_for("open:" + req.session_id):
        existing = session.get("open_grading")
        if existing is not None:
            same = (existing["distinction"]["answer"] == req.distinction_answer
                    and existing["application"]["answer"] == req.application_answer)
            if not same:
                raise HTTPException(status_code=409, detail="Bài làm của lượt này đã được nộp, không thể thay đổi.")
            if session.get("open_result"):
                return session["open_result"]
            return _advance_open_and_respond(session, user, req.distinction_history, req.application_history)
        if session["current_state"] != "WAITING_OPEN_ENDED_SUBMISSION":
            raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")
        session["open_grading"] = _new_open_states(
            session, req.distinction_answer, req.application_answer, session["distinction_prompt"], session["application_prompt"])
        return _advance_open_and_respond(session, user, req.distinction_history, req.application_history)


class RetryOpenGradingRequest(BaseModel):
    session_id: str
    distinction_history: list[str] = []
    application_history: list[str] = []


@app.post("/api/chat/retry-open-grading")
def retry_open_grading(req: RetryOpenGradingRequest, user=Depends(get_current_user)):
    """Chấm nốt RIÊNG phần còn chờ (lượt đối chiếu hoặc lượt ba); không nộp lại bài, hai kết quả hợp lệ đã lưu được giữ."""
    session = get_session(req.session_id)
    with review_service._lock_for("open:" + req.session_id):
        if session.get("open_result"):
            return session["open_result"]
        if session.get("open_grading") is None:
            raise HTTPException(status_code=409, detail="Chưa có bài tự luận nào đang chờ chấm.")
        return _advance_open_and_respond(session, user, req.distinction_history, req.application_history)


# ---------- báo cáo điểm/nhận xét TỰ LUẬN (xem open_review.py) ----------
_MAX_OPEN_REPORTS_PER_DAY = 20


class OpenReportRequest(BaseModel):
    attempt_id: str
    skill: str
    category: str
    criterion: str | None = None
    target: str | None = None
    quote: str | None = None
    note: str | None = None
    suggested_score: float | None = None


def _open_report_public(row: dict) -> dict:
    """Chỉ phần học sinh cần thấy: trạng thái, lý do cuối cùng, bản sửa (nếu có). Không lộ prompt, điểm rà mù hay ghi chú nội bộ."""
    out = row.get("outcome") or {}
    return {"report_id": row["id"], "skill": row["skill"], "category": row["category"], "criterion": row["criterion"],
            "status": row["status"], "reply": out.get("reply"), "fixed_text": out.get("fixed_text"),
            "decision_state": (out.get("decision") or {}).get("state"), "score_changed": bool(out.get("decision") and out["decision"]["type"] == "score_change"
                                                                                              and out["decision"]["state"] == "applied"),
            "detail": out.get("detail")}


def _run_open_report(row: dict, user_id: int) -> dict:
    """Xét báo cáo (idempotent): trạng thái đã có kết quả thì trả nguyên; chỉ 'received'/'pending_error' mới chạy lại."""
    with review_service._lock_for(f"open-report:{row['id']}"):
        fresh = next((r for r in db.open_reports_for_attempt(user_id, row["attempt_id"]) if r["id"] == row["id"]), row)
        if fresh["status"] not in ("received", "pending_error"):
            return _open_report_public(fresh)
        db.update_open_report(fresh["id"], "reviewing")
        att = db.load_attempt(fresh["attempt_id"])
        res = db.load_attempt_result(fresh["attempt_id"])
        states = db.load_open_grading(fresh["attempt_id"])
        try:
            world, level = (att["world_id"], att["level"]) if att else ("", 0)
            kb_text = compact_kb(load_knowledge_base(world, level)) if att else ""
            outcome = open_review.process_report(_ask_for("report"), fresh, states, (res or {}).get("current"), kb_text,
                                                 _safe_lessons(world, level, "open") if att else [], world, level,
                                                 rule_ask_fn=_ask_for("rules"))
            did = (outcome.get("decision") or {}).get("id")
            db.update_open_report(fresh["id"], outcome["status"], outcome, did)
        except AIRateLimitError:
            db.update_open_report(fresh["id"], "pending_error", {"error": "rate_limit", "reply": "Hệ thống đang bận, em thử lại sau ít phút. Báo cáo đã được lưu."})
        except Exception as e:  # noqa: BLE001 - lỗi API/JSON hỏng/schema sai: chờ, KHÔNG phải 'báo cáo sai'
            logger.exception("Xét báo cáo tự luận thất bại, chuyển trạng thái chờ")
            db.update_open_report(fresh["id"], "pending_error", {"error": str(e)[:200],
                                  "reply": "Hệ thống chưa xét được báo cáo (lỗi kỹ thuật, không phải do báo cáo của em). Em bấm gửi lại để xét tiếp."})
        after = next(r for r in db.open_reports_for_attempt(user_id, row["attempt_id"]) if r["id"] == row["id"])
        return _open_report_public(after)


@app.post("/api/report/open")
def submit_open_report(req: OpenReportRequest, user=Depends(get_current_user)):
    res = db.load_attempt_result(req.attempt_id)
    if not res or res["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Không tìm thấy lượt làm này.")
    states = db.load_open_grading(req.attempt_id) or {}
    try:
        v = open_review.validate_report(req.model_dump(), states.get(req.skill) or {})
    except open_review.OpenReportError as e:
        raise HTTPException(status_code=422, detail=str(e))
    existing = [r for r in db.open_reports_for_attempt(user["id"], req.attempt_id)
                if (r["skill"], r["category"], r["criterion"], r["target"]) == (v["skill"], v["category"], v["criterion"], v["target"])]
    if not existing and db.count_open_reports_today(user["id"]) >= _MAX_OPEN_REPORTS_PER_DAY:
        raise HTTPException(status_code=429, detail="Bạn đã gửi quá nhiều báo cáo hôm nay.")
    row, _created = db.create_open_report(user["id"], req.attempt_id, v["skill"], v["category"], v["criterion"], v["target"],
                                          v["quote"], v["note"], v["suggested_score"], open_grading.RUBRIC_VERSION)
    return _run_open_report(row, user["id"])


@app.get("/api/report/open")
def list_open_reports(attempt_id: str, user=Depends(get_current_user)):
    res = db.load_attempt_result(attempt_id)
    if not res or res["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Không tìm thấy lượt làm này.")
    return {"reports": [_open_report_public(r) for r in db.open_reports_for_attempt(user["id"], attempt_id)]}


# ---------- báo cáo của người dùng + AI lọc ----------
# Mỗi báo cáo được AI thẩm định độc lập dựa trên KB; chỉ báo cáo ACCEPT mới được
# lưu thành "lesson" (câu do AI tự viết lại, không chép nguyên văn người dùng) và
# nạp vào prompt sinh câu/chấm điểm của chính level đó ở các lần sau.
_MAX_REPORTS_PER_DAY = 20


@app.post("/api/report")
def submit_report(req: ReportRequest, user=Depends(get_current_user)):
    session = get_session(req.session_id)
    explanation = req.explanation.strip()
    if len(explanation) < 10 or len(explanation) > 1200:
        raise HTTPException(status_code=422, detail="Giải thích cần từ 10 đến 1200 ký tự.")
    if db.count_reports_today(user["id"]) >= _MAX_REPORTS_PER_DAY:
        raise HTTPException(status_code=429, detail="Bạn đã gửi quá nhiều báo cáo hôm nay.")

    kb = load_knowledge_base(session["world_id"], session["level"])
    extra = ""
    if req.kind == "recognition":
        raise HTTPException(status_code=422, detail="Báo lỗi câu trắc nghiệm dùng /api/report/recognition (theo loại vấn đề).")
    elif req.kind in ("distinction", "application"):
        if "distinction_prompt" not in session:
            raise HTTPException(status_code=409, detail="Chưa có câu hỏi mở để báo cáo.")
        is_d = req.kind == "distinction"
        question = session["distinction_prompt"] if is_d else session["application_prompt"]
        item_ref = req.kind
        score = session.get("distinction_score" if is_d else "application_score")
        fb = session.get("distinction_feedback" if is_d else "application_feedback")
        current = f"điểm {score}/10; nhận xét: {fb}"
        suggested = req.suggested_note.strip()[:300] or "(không nêu)"
    else:
        raise HTTPException(status_code=422, detail="Loại báo cáo không hợp lệ.")

    prompt = assemble(compact_kb(kb), report_judge_task(req.kind, question, current, suggested, explanation, extra))
    try:
        data = parse_ai_json(_ask_for("report")(prompt))
    except AIRateLimitError:
        raise
    accepted = str(data.get("verdict", "")).upper() == "ACCEPT" and bool(data.get("lesson"))
    lesson = str(data["lesson"])[:300] if accepted else None
    inserted = db.save_report(
        user["id"], session["world_id"], session["level"], req.kind, item_ref, question,
        current, suggested, explanation, "accepted" if accepted else "rejected", lesson,
        str(data.get("reason", ""))[:300],
    )
    if not inserted:
        raise HTTPException(status_code=409, detail="Bạn đã báo cáo mục này rồi.")
    return {"accepted": accepted, "reason": str(data.get("reason", ""))}


# ---------- luồng ôn tập trọng tâm (remediation) khi RETRY ----------

@app.post("/api/chat/begin-remediation")
def begin_remediation(req: SessionIdRequest, user=Depends(get_current_user)):
    session = get_session(req.session_id)
    if session["current_state"] != "RETRY":
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")
    _require_keys(user, 1)

    full_history = _server_history(
        user["id"], session["world_id"], session["level"],
        session.get("recognition_history") or [], req.recognition_history,
    )

    pack = None
    prep = session.get("rem_prep")
    if prep is not None:
        prep["event"].wait(timeout=_PREP_WAIT_SECONDS)
        if prep["status"] == "ready":
            pack = prep["pack"]
    session["rem_prep"] = None
    if pack is None:
        # Chưa có bộ sinh sẵn (hoặc thất bại): sinh ngay, vẫn qua đủ bước kiểm tra.
        pack = _generate_remediation_pack(session, user["id"], req.distinction_history, req.application_history)

    questions = pack["questions"]
    _charge_keys(user["id"], 1)
    try:
        db.record_issued_set(
            user["id"], session["world_id"], session["level"], "practice-" + pack.get("set_id", secrets.token_hex(8)),
            "practice", [q["question"] for q in questions],
        )
    except Exception:  # noqa: BLE001
        logger.exception("Không ghi được lịch sử bộ luyện tập đã phát")

    session["practice_open_grading"] = None      # bộ ôn tập mới: trạng thái chấm tự luận cũ không dùng lại
    session["practice_questions"] = questions
    session["practice_secure_answer_key"] = {str(q["id"]): q["correct_index"] for q in questions}
    session["practice_distinction_prompt"] = pack["d"]
    session["practice_application_prompt"] = pack["a"]
    session["recognition_history"] = full_history + [q["question"] for q in questions]
    session["current_state"] = "REMEDIATION_MCQ"
    cards = pack.get("cards") or []
    session["rem_cards"] = {"cards": cards, "logs": {c["target"]["id"]: remediation_plan.new_log() for c in cards},
                            "targets": pack.get("targets") or []}
    session["practice_mcq"] = None

    # Học sinh đã cam kết ôn tập -> sinh sẵn bộ 20 câu kiểm tra lại trong lúc họ làm bài luyện tập.
    _start_recognition_prep(session, user["id"], True)

    return {
        "recap": pack["recap"],
        "cards": _public_cards(session),
        "practice_questions": [
            {"id": q["id"], "question": q["question"], "options": q["options"],
             **({"difficulty": q["meta"]["difficulty"]} if (q.get("meta") or {}).get("difficulty") in ("easy", "medium", "hard") else {})}
            for q in questions
        ],
        "keys_remaining": db.get_keys(user["id"]),
    }


@app.post("/api/chat/submit-remediation-mcq")
def submit_remediation_mcq(req: RemediationMCQRequest, user=Depends(get_current_user)):
    session = get_session(req.session_id)
    if session["current_state"] != "REMEDIATION_MCQ":
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")

    questions = session["practice_questions"]
    snapshot = review.build_snapshot(session["world_id"], session["level"], questions)
    answers_oid = review.answers_by_qv(snapshot, req.answers)
    graded = review.grade(snapshot, answers_oid, {})            # cùng bộ chấm theo mã phương án với bài chính thức
    wrong = _mcq_wrong_list(questions, graded, snapshot)
    session["practice_per_question"] = graded["per_question"]
    # Cùng bộ soạn/kiểm lời giải với bài chính thức. Bộ ôn tập không có bản ghi lượt làm nên không gắn cờ vào phiên bản câu:
    # câu nghi vấn chỉ hiện trạng thái 'đang được xem lại' ở bộ này.
    expl = _build_explanations(
        session["world_id"], session["level"], snapshot, questions, graded["per_question"], {w["id"] for w in wrong})
    session["practice_explanations"] = dict(expl["texts"])
    session["practice_explanation_partial"] = dict(expl["partial"])
    session["practice_explanation_status"] = dict(expl["status"])

    session["current_state"] = "REMEDIATION_OPEN_ENDED"
    session["practice_mcq"] = {"correct": graded["correct"], "total": graded["valid_total"]}

    return {
        "correction_text": "" if wrong else "Bạn đã trả lời đúng tất cả các câu.",
        "correct_count": graded["correct"], "valid_total": graded["valid_total"],
        "explanations": expl["texts"], "explanation_status": expl["status"], "explanation_partial": expl["partial"],
        "wrong_words": [
            {"selected": (wq["options"][wq["selected_index"]] if wq["selected_index"] is not None else None),
             "correct": wq["options"][wq["correct_index"]], "question": wq["question"]}
            for wq in wrong
        ],
        "distinction_prompt": session["practice_distinction_prompt"],
        "application_prompt": session["practice_application_prompt"],
    }


@app.post("/api/chat/submit-remediation-open-ended")
def submit_remediation_open_ended(req: RemediationOpenEndedRequest, user=Depends(get_current_user)):
    session = get_session(req.session_id)
    if session["current_state"] != "REMEDIATION_OPEN_ENDED":
        raise HTTPException(status_code=409, detail=f"Sai trạng thái hiện tại: {session['current_state']}")

    data = _grade_open_ended_sync(
        session["world_id"], session["level"], session["practice_distinction_prompt"], req.distinction_answer,
        session["practice_application_prompt"], req.application_answer, session)
    d_scores, a_scores = data["d_scores"], data["a_scores"]
    distinction_score, application_score = data["d_total"], data["a_total"]

    # REMEDIATION_DONE -> begin-recognition được phép chạy lại (retest) từ đây.
    session["current_state"] = "REMEDIATION_DONE"
    practice_states = session.get("practice_open_grading") or {}
    rc = session.get("rem_cards") or {"cards": [], "logs": {}}
    summary = remediation_plan.build_summary(
        rc["cards"], rc["logs"], remediation_plan.collect_evidence(session),
        {"mcq": session.get("practice_mcq"),
         "writing": {"distinction": {"scores": d_scores, "blank": (practice_states.get("distinction") or {}).get("status") == "empty"},
                     "application": {"scores": a_scores, "blank": (practice_states.get("application") or {}).get("status") == "empty"}}})

    return {
        "summary": summary,
        "distinction_score": distinction_score,
        "distinction_feedback": data["d_fb"],
        "distinction_rubric": _rubric_rows(d_scores, DISTINCTION_CRITERIA, DISTINCTION_LABELS),
        "application_score": application_score,
        "application_feedback": data["a_fb"],
        "application_rubric": _rubric_rows(a_scores, APPLICATION_CRITERIA, APPLICATION_LABELS),
        "distinction_model": data["d_model"],
        "application_model": data["a_model"],
        "grading_spread": {
            "distinction": data["d_spread"], "application": data["a_spread"], "flag_threshold": _SPREAD_FLAG,
        },
    }


# ---------- thẻ ôn + tự thử (xem remediation_plan.py) ----------

_CARD_STATES = ("REMEDIATION_MCQ", "REMEDIATION_OPEN_ENDED", "REMEDIATION_DONE")


class CardRequest(BaseModel):
    session_id: str
    card_id: str
    level: int | None = None
    phase: str | None = None
    choice: int | None = None
    text: str | None = None


def _public_cards(session: dict) -> list[dict]:
    rc = session.get("rem_cards") or {"cards": [], "logs": {}}
    return [remediation_plan.public_card(c, rc["logs"][c["target"]["id"]]) for c in rc["cards"]]


def _card_ctx(req: CardRequest) -> tuple[dict, dict, dict]:
    session = get_session(req.session_id)
    if session["current_state"] not in _CARD_STATES or not session.get("rem_cards"):
        raise HTTPException(status_code=409, detail="Chưa có thẻ ôn trong phiên này.")
    rc = session["rem_cards"]
    card = next((c for c in rc["cards"] if c["target"]["id"] == req.card_id), None)
    if card is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy thẻ này.")
    return session, card, rc["logs"][req.card_id]


@app.post("/api/chat/remediation/cards-state")
def remediation_cards_state(req: SessionIdRequest, user=Depends(get_current_user)):
    """Khôi phục sau khi tải lại: cùng thẻ, cùng gợi ý đã mở, cùng câu đã trả lời (không sinh thẻ khác)."""
    session = get_session(req.session_id)
    return {"cards": _public_cards(session)}


@app.post("/api/chat/remediation/card-hint")
def remediation_card_hint(req: CardRequest, user=Depends(get_current_user)):
    session, card, log = _card_ctx(req)
    with review_service._lock_for(f"card:{req.session_id}:{req.card_id}"):
        ok, msg = remediation_plan.open_hint(log, req.level or 0)
        if not ok:
            raise HTTPException(status_code=409, detail=msg)
        return remediation_plan.public_card(card, log)


@app.post("/api/chat/remediation/card-solution")
def remediation_card_solution(req: CardRequest, user=Depends(get_current_user)):
    session, card, log = _card_ctx(req)
    with review_service._lock_for(f"card:{req.session_id}:{req.card_id}"):
        remediation_plan.open_solution(log)
        return remediation_plan.public_card(card, log)


@app.post("/api/chat/remediation/card-answer")
def remediation_card_answer(req: CardRequest, user=Depends(get_current_user)):
    """Lần trả lời ĐẦU được lưu một lần (gửi lại/tải lại không ghi đè và không mất dấu vết đã dùng gợi ý). Lần SAU gợi ý chỉ khi lần đầu chưa đạt."""
    session, card, log = _card_ctx(req)
    answer = {"choice": req.choice, "text": req.text}
    with review_service._lock_for(f"card:{req.session_id}:{req.card_id}"):
        phase = req.phase or ("first" if log["first"] is None else "after")
        if phase == "first":
            if log["first"] is not None:
                return {**remediation_plan.public_card(card, log), "feedback": log["first"]["comment"]}
            res = remediation_plan.assess_answer(_ask_for("try_assess"), parse_ai_json, card, answer)
            log["first"] = {**res, "answer": answer}
            if log["solution_before_first"]:
                log["first"]["after_solution"] = True
            return {**remediation_plan.public_card(card, log), "feedback": res["comment"]}
        if log["first"] is None:
            raise HTTPException(status_code=409, detail="Em cần trả lời lần đầu trước.")
        if log["first"]["status"] == "solid":
            raise HTTPException(status_code=409, detail="Lần đầu em đã làm được, không cần thử lại.")
        if log["after"] is not None:
            return {**remediation_plan.public_card(card, log), "feedback": log["after"]["comment"]}
        if not log["hints"]:
            raise HTTPException(status_code=409, detail="Em xem ít nhất một gợi ý trước khi sửa lại.")
        res = remediation_plan.assess_answer(_ask_for("try_assess"), parse_ai_json, card, answer)
        log["after"] = {**res, "answer": answer}
        return {**remediation_plan.public_card(card, log), "feedback": res["comment"]}


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

@app.middleware("http")
async def _no_stale_static(request: Request, call_next):
    """JS/CSS/HTML luôn được trình duyệt kiểm tra lại (ETag) nên sửa giao diện không bị kẹt bản cũ trong cache."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith(("/js/", "/css/")) or path in ("/", "/index.html", "/world1.html", "/world2.html"):
        response.headers["Cache-Control"] = "no-cache"
    return response


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


# ---------- Demo Lab (chỉ localhost; xem server/lab.py). Không đặt LAB_ENABLED thì không nạp gì, không có route nào. ----------
if os.environ.get("LAB_ENABLED") == "1":
    try:
        import lab

        app.include_router(lab.router)

        @app.get("/lab.html")
        def serve_lab():
            return FileResponse(str(BASE_DIR / "lab.html"))
    except ImportError:
        logger.warning("LAB_ENABLED=1 nhưng thiếu module lab (hoặc thư viện python-docx): bỏ qua Demo Lab.")
