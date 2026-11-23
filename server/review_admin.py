"""Công cụ nội bộ tối giản để NGƯỜI CÓ THẨM QUYỀN xác nhận các ca tranh chấp (chạy trực tiếp trên máy chủ có DATABASE_URL).

AI chỉ đề xuất; không quyết định đổi điểm hay quy tắc dùng chung nào có hiệu lực nếu chưa qua lệnh ở đây.

Lệnh:
  python review_admin.py pending                  # quyết định/báo cáo/quy tắc đang chờ
  python review_admin.py show-decision <id>
  python review_admin.py apply <decision_id> --by <tên>     # áp dụng: chấm lại MỌI lượt bị ảnh hưởng
  python review_admin.py revoke <decision_id> --by <tên>    # thu hồi, tính lại từ lựa chọn gốc
  python review_admin.py keep <qv> --by <tên>               # giữ đáp án: đóng cờ, phát lại phiên bản
  python review_admin.py rules                    # liệt kê quy tắc
  python review_admin.py approve-rule <id> [--override-check] | revoke-rule <id>   # quy tắc tự luận phải qua test-rule trước
  python review_admin.py open-pending             # báo cáo tự luận cần người + quyết định đổi điểm đang chờ
  python review_admin.py open-apply <decision_id> --by <tên>    # áp dụng (tính lại từ hồ sơ gốc, giữ dự đoán đã khóa)
  python review_admin.py open-revoke <decision_id> --by <tên>
  python review_admin.py test-rule <rule_id>      # chạy bộ chấm có chèn quy tắc trên bài từng bị chấm sai + bài cũ đang đúng
  python review_admin.py legacy-lessons           # ghi chú cũ (user_reports.lesson) CHƯA được duyệt, không vào prompt
"""

import argparse
import json
import sys

import db
import open_review
import review_service


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def test_rule(rule_id: int) -> dict:
    """Kiểm quy tắc đề xuất bằng bộ chấm THẬT (cần OPENAI_API_KEY): (1) bài từng bị chấm sai phải được chấm đúng mức; (2) tối đa 5 bài cũ cùng
    nhóm từ đang được chấm đúng phải giữ nguyên điểm tiêu chí. Kết quả lưu vào quy tắc (check_status) nhưng KHÔNG tự duyệt."""
    import json as _json
    from ai_client import ask
    import engine_prompts as ep
    import open_grading as og
    rule = db._q("SELECT * FROM learning_rules WHERE id=%s", (rule_id,), one=True)
    if not rule or rule["source_kind"] != "open_report":
        sys.exit("Chỉ kiểm được quy tắc rút từ báo cáo tự luận.")
    rep = db._q("SELECT * FROM open_reports WHERE id=%s", (rule["source_report_id"],), one=True)
    dec = next((d for d in db.list_open_decisions(rep["attempt_id"]) if d["source_report_id"] == rep["id"]), None) if rep else None
    states = db.load_open_grading(rep["attempt_id"]) if rep else None
    if not states or not rep or not rep["criterion"]:
        db.set_rule_check(rule_id, "failed", "thiếu hồ sơ bài gốc hoặc tiêu chí để kiểm")
        return {"passed": False, "note": "thiếu hồ sơ bài gốc hoặc tiêu chí để kiểm"}
    skill, crit = rep["skill"], rep["criterion"]
    target = dec["payload"]["to"] if dec and dec["decision_type"] == "score_change" else states[skill]["final"]["scores"][crit]
    cases = [{"id": f"report-{rep['id']}", "kind": "must_change", "skill": skill, "criterion": crit, "question": states[skill]["question"],
              "answer": states[skill]["answer"], "min_score": target}]
    att = db.load_attempt(rep["attempt_id"])
    older = db._q("""SELECT g.state FROM open_grading_runs g JOIN recognition_attempts a ON a.attempt_id = g.attempt_id
                     WHERE a.world_id=%s AND a.level=%s AND g.attempt_id <> %s ORDER BY g.updated_at DESC LIMIT 5""",
                  (att["world_id"], att["level"], rep["attempt_id"])) if att else []
    for i, row in enumerate(older):
        st = _json.loads(row["state"]).get(skill)
        if st and st.get("final") and st["status"] == "final":
            f = st["final"]["scores"][crit]
            cases.append({"id": f"old-{i}", "kind": "must_keep", "skill": skill, "criterion": crit, "question": st["question"],
                          "answer": st["answer"], "min_score": f - 0.5, "max_score": f + 0.5})
    kb_text = ep.compact_kb(ep.load_knowledge_base(att["world_id"], att["level"])) if att else ""

    def grade(case, r):
        lesson = [f"[{r['scope']}] Khi {r['condition_text']}: {r['guidance']} (ví dụ cần chặn: {r['block_example']}; ví dụ hợp lệ phải giữ: {r['keep_example']})"]
        out = og._parse_json(ask(open_review.blind_prompt(kb_text, case["skill"], case["question"], case["answer"], case["criterion"], lesson),
                                 reasoning_effort="medium"))
        j, err = open_review.validate_blind(out, case["skill"], case["criterion"], case["answer"])
        if err:
            raise ValueError(err)
        return j["score"]

    res = open_review.rule_regression_check(grade, rule, cases)
    db.set_rule_check(rule_id, "passed" if res["passed"] else "failed", _json.dumps(res, ensure_ascii=False)[:1500])
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--by", default="")
    ap.add_argument("--override-check", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "pending":
        _print({"decisions": db.list_decisions(None, "proposed"),
                "rules": db._q("SELECT * FROM learning_rules WHERE status='proposed' ORDER BY id"),
                "needs_human_reports": db._q("SELECT id, qv, report_type, status, case_id FROM question_reports "
                                             "WHERE status IN ('needs_human','pending_error') ORDER BY id")})
    elif a.cmd == "show-decision":
        _print([d for d in db.list_decisions() if d["id"] == int(a.arg)])
    elif a.cmd in ("apply", "revoke", "keep"):
        if not a.by:
            sys.exit("Cần --by <tên người xác nhận>.")
        if a.cmd == "apply":
            _print(review_service.apply_decision(int(a.arg), a.by))
        elif a.cmd == "revoke":
            _print(review_service.revoke_decision(int(a.arg), a.by))
        else:
            did = db.create_decision(a.arg, "keep", None, None, "Giữ đáp án (người rà soát)", None, a.by)
            _print(review_service.apply_decision(did, a.by))
    elif a.cmd == "rules":
        _print(db._q("SELECT * FROM learning_rules ORDER BY id"))
    elif a.cmd == "approve-rule":
        rule = db._q("SELECT * FROM learning_rules WHERE id=%s", (int(a.arg),), one=True)
        if not rule:
            sys.exit("Không có quy tắc này.")
        if rule["source_kind"] == "open_report" and rule["check_status"] != "passed" and not a.override_check:
            sys.exit("Quy tắc từ báo cáo tự luận phải đạt 'test-rule' trước khi duyệt (hoặc dùng --override-check kèm --by).")
        _print({"changed": db.set_rule_status(int(a.arg), "approved")})
    elif a.cmd == "open-pending":
        _print({"decisions": db.list_open_decisions(None, "proposed"),
                "needs_human_reports": db._q("SELECT id, attempt_id, skill, category, criterion, status FROM open_reports "
                                             "WHERE status IN ('needs_human','pending_error') ORDER BY id")})
    elif a.cmd in ("open-apply", "open-revoke"):
        if not a.by:
            sys.exit("Cần --by <tên người xác nhận>.")
        fn = open_review.apply_decision if a.cmd == "open-apply" else open_review.revoke_decision
        _print(fn(int(a.arg), a.by))
    elif a.cmd == "test-rule":
        _print(test_rule(int(a.arg)))
    elif a.cmd == "revoke-rule":
        _print({"changed": db.set_rule_status(int(a.arg), "revoked")})
    elif a.cmd == "legacy-lessons":
        _print(db._q("SELECT id, world_id, level, kind, lesson FROM user_reports WHERE verdict='accepted' AND lesson IS NOT NULL ORDER BY id"))
    else:
        sys.exit("Lệnh không hợp lệ.")


if __name__ == "__main__":
    main()
