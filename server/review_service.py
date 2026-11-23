"""Điều phối chấm lại / gắn cờ / xét báo cáo (dùng DB). Logic thuần nằm ở review.py.

Quyết định đổi điểm (fix_key, accept_multi, void) và quy tắc dùng chung KHÔNG tự áp dụng: AI chỉ đề xuất
(status 'proposed'); người có thẩm quyền xác nhận qua review_admin.py. Việc gắn cờ + tạm ngừng phát phiên bản câu
(an toàn, đảo ngược được) thì tự động."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

import db
import engine_prompts as ep
import recognition_set as rs
import review
from ai_client import AIProviderError, AIRateLimitError
from ai_json import parse_ai_json

logger = logging.getLogger("ioc.review")

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- chấm lại một lượt

def grade_attempt(att: dict) -> tuple[dict, list[int]]:
    qvs = [q["qv"] for q in att["snapshot"]]
    decisions = db.list_decisions(qvs, "applied")
    eff = review.effective_decisions(decisions)
    flags = db.flags_for(qvs)
    tentative = {f["qv"] for f in flags if f["status"] == "open" and f["flag_type"] == "answer_under_review"}
    g = review.grade(att["snapshot"], att["answers"], eff, tentative)
    applied = sorted({i for e in eff.values() for i in e["ids"]})
    return g, applied


def recompute_attempt(attempt_id: str, reason: str = "") -> dict | None:
    """Tính lại từ lựa chọn GỐC và các quyết định đang có hiệu lực (không cộng/trừ gia tăng) nên chạy lại, bị ngắt
    giữa chừng hay hai yêu cầu cùng đến đều cho cùng kết quả. Giữ nguyên dự đoán/tự tin gốc."""
    with _lock_for("attempt:" + attempt_id):
        att = db.load_attempt(attempt_id)
        if not att:
            return None
        g, applied = grade_attempt(att)
        db.update_attempt_grade(attempt_id, g["correct"], g["valid_total"], g["score"], applied)
        res = db.load_attempt_result(attempt_id)
        summary = {"attempt_id": attempt_id, "recognition": g["score"], "correct": g["correct"],
                   "valid_total": g["valid_total"], "tentative": g["tentative"], "applied_decisions": applied}
        if res:
            orig = res["original"]
            new = review.recompute_results(
                orig, g["score"], res["distinction"], res["application"], orig.get("comparison_gap"),
                orig.get("legacy_confidence"))
            cur = {**res["current"], "recognition": g["score"], **{k: new[k] for k in ("overall", "gap", "final_result")},
                   **({"decision": new["decision"]} if new.get("decision") else {}),
                   "state": new["state"], "tentative": g["tentative"]}
            revisions = list(res["revisions"])
            before = {k: res["current"].get(k) for k in ("recognition", "overall", "gap", "final_result")}
            after = {k: cur.get(k) for k in ("recognition", "overall", "gap", "final_result")}
            if before != after or cur.get("tentative") != res["current"].get("tentative"):
                if before != after and not (revisions and revisions[-1].get("applied") == applied and revisions[-1]["after"] == after):
                    revisions.append({"at": _now(), "applied": applied, "reason": reason, "before": before, "after": after})
                db.update_attempt_result(attempt_id, cur, revisions)
            summary.update({"overall": cur.get("overall"), "gap": cur.get("gap"), "final_result": cur.get("final_result")})
        _refresh_live_session(attempt_id, att, g)
        return summary


def _refresh_live_session(attempt_id: str, att: dict, g: dict) -> None:
    """Nếu phiên trong RAM còn sống, cập nhật điểm Recognition và danh sách câu sai dùng cho ôn tập (best-effort)."""
    try:
        import session_store
        sid = attempt_id.rsplit(":", 1)[0]
        session = session_store.SESSIONS.get(sid)
        if not session or session.get("attempt_no") != int(attempt_id.rsplit(":", 1)[1]):
            return
        if g["score"] is not None:
            session["recognition"] = g["score"]
        wrong_pos = {v["pos"] for v in g["per_question"].values() if v["status"] in ("wrong", "unanswered")}
        if session.get("wrong_questions"):
            session["wrong_questions"] = [w for w in session["wrong_questions"] if w["id"] in wrong_pos]
    except Exception:  # noqa: BLE001
        logger.exception("Không cập nhật được phiên đang sống sau khi chấm lại")


# ---------------------------------------------------------------- áp dụng quyết định (người có thẩm quyền)

def apply_decision(decision_id: int, by: str) -> dict:
    decs = [d for d in db.list_decisions() if d["id"] == decision_id]
    if not decs:
        raise ValueError("Không có quyết định này.")
    d = decs[0]
    with _lock_for("qv:" + d["qv"]):
        changed = db.set_decision_status(decision_id, "applied", by)
        if d["decision_type"] in review.SCORE_DECISIONS:
            db.close_flags(d["qv"], ["answer_under_review"])
            db.set_version_status(d["qv"], "retired")          # không phát lại phiên bản này cho lượt mới
        elif d["decision_type"] == "keep":
            db.close_flags(d["qv"], ["answer_under_review"])
            db.set_version_status(d["qv"], "active")
        elif d["decision_type"] == "fix_explanation":
            db.close_flags(d["qv"], ["explanation_under_review"])
        attempts = db.attempts_for_versions([d["qv"]])
    results = [recompute_attempt(a, reason=f"decision:{decision_id}") for a in attempts]
    return {"decision": decision_id, "newly_applied": changed, "attempts_recomputed": len(attempts), "results": results}


def revoke_decision(decision_id: int, by: str) -> dict:
    decs = [d for d in db.list_decisions() if d["id"] == decision_id]
    if not decs:
        raise ValueError("Không có quyết định này.")
    d = decs[0]
    changed = db.set_decision_status(decision_id, "revoked", by)
    attempts = db.attempts_for_versions([d["qv"]])
    for a in attempts:
        recompute_attempt(a, reason=f"revoke:{decision_id}")
    return {"decision": decision_id, "revoked": changed, "attempts_recomputed": len(attempts)}


# ---------------------------------------------------------------- xét báo cáo

def _ask_json(ask_fn, prompt: str, effort: str = "low") -> dict:
    last: Exception | None = None
    for _ in range(2):
        try:
            return parse_ai_json(ask_fn(prompt, reasoning_effort=effort))
        except AIRateLimitError:
            raise
        except (AIProviderError, ValueError) as e:
            last = e
    raise last  # type: ignore[misc]


def _blind_choice(ask_fn, kb: dict, snap_q: dict) -> tuple[str | None, dict | None]:
    """Đánh giá lại TỪ ĐỀ (chưa cho thấy báo cáo/khóa). Tái dùng hồ sơ hai lượt mù hợp lệ nếu phiên bản có sẵn."""
    answer = next(o["text"] for o in snap_q["options"] if o["oid"] == snap_q["key_oid"])
    item = {"sentence": snap_q["text"], "options": [o["text"] for o in snap_q["options"]], "answer": answer}
    judged = rs.run_blind_judge(ask_fn, kb, [item], None, reverse=True)[0]
    ok, reasons, audit = judged
    if audit is None:                      # đầu ra hỏng sau khi thử lại: không suy diễn
        return None, None
    return review.option_id(audit["chosen"]), audit


def triage_report(ask_fn, report: dict, att: dict, snap_q: dict, kb: dict) -> dict:
    """Xét một báo cáo (ĐÃ qua validate_report). Trả {"status", ...}. Mọi lỗi kỹ thuật -> raise để người gọi đặt
    'pending_error' (chờ), không bao giờ coi là 'báo cáo sai'."""
    rtype = report["report_type"]
    if rtype == "explanation_unclear":
        return {"status": "recorded", "reason": "Đã ghi nhận để rà cách viết; điểm được giữ nguyên."}

    blind_oid, blind_audit = _blind_choice(ask_fn, kb, snap_q)          # bước 1: chưa đọc tranh luận
    options = [o["text"] for o in snap_q["options"]]
    letters_to_oid = {"ABCD"[i]: o["oid"] for i, o in enumerate(snap_q["options"])}
    oid_to_letter = {v: k for k, v in letters_to_oid.items()}
    key_letter = oid_to_letter[snap_q["key_oid"]]
    reported = [oid_to_letter[o] for o in report["option_oids"]]
    blind_summary = None
    if blind_audit:
        blind_summary = {"chosen": oid_to_letter[blind_oid], "options": {
            oid_to_letter[review.option_id(t)]: v["verdict"] for t, v in blind_audit["options"].items()}}

    data = _ask_json(ask_fn, ep.assemble(ep.lesson_kb_text(kb), ep.report_triage_task(
        rtype, snap_q["text"], options, key_letter, reported, report["note"], blind_summary,
        shown_explanation=(att.get("explanations") or {}).get(str(snap_q["pos"])),
    )), "medium")
    result, err = review.validate_triage(data, rtype, snap_q, letters_to_oid)
    if err:
        raise ValueError("Đầu ra xét báo cáo không hợp lệ: " + err)
    result = review.reconcile_with_dossier(result, rtype, snap_q, blind_oid)
    disagree = bool(blind_oid and blind_oid != snap_q["key_oid"])
    return {"status": {"accept": "accepted", "keep": "kept", "needs_human": "needs_human"}[result["verdict"]],
            "result": result, "blind_disagrees_with_key": disagree, "blind": blind_summary}


def apply_triage_effects(report_row: dict, outcome: dict) -> dict:
    """Hiệu ứng AN TOÀN, đảo ngược được, tự động: gắn cờ + tạm ngừng phát phiên bản; ĐỀ XUẤT quyết định (chưa đổi
    điểm). Đổi điểm/áp quy tắc chỉ xảy ra khi người có thẩm quyền xác nhận."""
    qv, rtype = report_row["qv"], report_row["report_type"]
    status = outcome["status"]
    result = outcome.get("result")
    decision_id = None
    scope = review.REPORT_TYPES[rtype]["scope"]
    if status == "accepted" and result:
        flag = "answer_under_review" if scope == "key" else "explanation_under_review"
        db.open_flag(qv, flag, result["reason"], f"report:{report_row['id']}")
        if scope == "key":
            db.set_version_status(qv, "paused")
        decision_id = db.create_decision(
            qv, result["decision"], result["accepted_oids"] or None, result["explanation_fix"], result["reason"],
            report_row["id"], "ai_triage")
    elif status == "needs_human" and outcome.get("blind_disagrees_with_key") and scope == "key":
        # Có bất đồng thật giữa các phán đoán hợp lệ (đánh giá mù mới vs hồ sơ gốc): ghi cờ và chờ người rà.
        db.open_flag(qv, "answer_under_review", "Hai phán đoán hợp lệ bất đồng về đáp án", f"report:{report_row['id']}")
        db.set_version_status(qv, "paused")
    return {"decision_id": decision_id}


def propose_rule_from_report(ask_fn, report_row: dict, snap_q: dict, result: dict, kb: dict, world_id: str, level: int) -> int | None:
    """Tách khỏi việc công nhận báo cáo: lỗi/không đủ cụ thể thì bỏ qua, báo cáo vẫn được công nhận."""
    try:
        data = _ask_json(ask_fn, ep.assemble(ep.lesson_kb_text(kb), ep.rule_proposal_task(
            report_row["report_type"], snap_q["text"], [o["text"] for o in snap_q["options"]], result["reason"],
            result["decision"])))
        rule, err = review.validate_rule_proposal(data)
        if err:
            logger.info("Không rút được quy tắc chung (%s)", err)
            return None
        return db.propose_rule(report_row["id"], rule, world_id, level)
    except Exception:  # noqa: BLE001
        logger.exception("Sinh đề xuất quy tắc thất bại (không ảnh hưởng báo cáo)")
        return None
