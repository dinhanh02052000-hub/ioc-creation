"""Kiểm thử báo cáo tự luận: xác thực, tính lại bằng code, rà mù, quyết định có kiểm soát, quy tắc học, và endpoint."""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import db  # noqa: E402
import open_grading as og  # noqa: E402
import open_review as orv  # noqa: E402
import scoring  # noqa: E402
from test_open_grading import A_ANSWER, A_Q, D_ANSWER, D_Q, REF_A, REF_D, make_pass  # noqa: E402

Q_ID = "sess1:1"


def make_states(d_scores=None, a_scores=None, flags=None, third=False):
    d_scores = d_scores or {"hieu_goc": 2, "ngu_canh": 1, "doi_nghia": 1, "phan_biet": 1, "so_sanh": 1}   # 6
    a_scores = a_scores or {"chon_tu": 2, "dung_dung": 3, "tinh_huong": 2, "giai_thich": 2}              # 9
    states = {}
    for sk, sc, ans, q in (("distinction", d_scores, D_ANSWER, D_Q), ("application", a_scores, A_ANSWER, A_Q)):
        st = og.new_skill_state(sk, ans, q)
        ok = og.validate_skill_output(make_pass(sk, sc, ans), sk, ans)[0]
        st["passes"] = [ok, ok]
        og.refresh_status(st)
        st["feedback"] = ("**Điểm làm được (Hiểu từ gốc):** nêu đúng nghĩa (từ bài của em: «Licence means a permit»)\n"
                          "**Cần cải thiện (Thay đổi nghĩa):** em mới nêu một phần.\n**Gợi ý sửa:** thêm một vế chỉ người suy ra.")
        st["model_answer"] = REF_D if sk == "distinction" else REF_A
        states[sk] = st
    if flags:
        states["distinction"]["final"]["flags"] = flags
    return states


def make_result(states, recognition=8.5, confidence_value=8.0):
    d, a = states["distinction"]["final"], states["application"]["final"]
    overall = scoring.calc_overall_v3(recognition, d["total_exact"], a["total_exact"])
    avg = (d["total_exact"] + a["total_exact"]) / 2
    return {
        "recognition": recognition, "distinction_score": d["total"], "application_score": a["total"], "overall": overall,
        "distinction_rubric": [{"label": og.LABELS[c], "score": v, "max": og.CRITERIA["distinction"][c]} for c, v in d["scores"].items()],
        "application_rubric": [{"label": og.LABELS[c], "score": v, "max": og.CRITERIA["application"][c]} for c, v in a["scores"].items()],
        "gap": round(confidence_value - avg, 2),
        "confidence_summary": {"available": True, "confidence": confidence_value},
        "distinction": d["total"], "application": a["total"], "final_result": "PASS", "decision": "PASS",
    }


class FakeOpenDB:
    """Thay các hàm db mà open_review/main dùng; mọi thứ ở RAM."""
    NAMES = ("create_open_decision", "list_open_decisions", "set_open_decision_status", "load_attempt_result", "load_open_grading",
             "get_confidence_prediction", "update_attempt_result", "propose_rule", "create_open_report", "update_open_report",
             "open_reports_for_attempt", "count_open_reports_today", "load_attempt", "set_rule_check")

    def __init__(self, states, result, user_id=1, pred=None):
        self.states, self.user_id, self.pred = states, user_id, pred
        self.res = {"attempt_id": Q_ID, "user_id": user_id, "distinction": result["distinction_score"], "application": result["application_score"],
                    "original": dict(result), "current": dict(result), "revisions": []}
        self.decisions, self.reports, self.rules = [], [], []
        self.reports_today = 0
        self._orig = {}

    def install(self):
        for n in self.NAMES:
            self._orig[n] = getattr(db, n)
            setattr(db, n, getattr(self, "f_" + n))

    def uninstall(self):
        for n, f in self._orig.items():
            setattr(db, n, f)

    def f_create_open_decision(self, attempt_id, skill, decision_type, payload, reason, source_report_id, proposed_by, status="proposed"):
        d = {"id": len(self.decisions) + 1, "attempt_id": attempt_id, "skill": skill, "decision_type": decision_type, "payload": payload,
             "reason": reason, "source_report_id": source_report_id, "status": status, "proposed_by": proposed_by, "applied_by": None}
        self.decisions.append(d)
        return d["id"]

    def f_list_open_decisions(self, attempt_id=None, status=None):
        return [d for d in self.decisions if (not attempt_id or d["attempt_id"] == attempt_id) and (not status or d["status"] == status)]

    def f_set_open_decision_status(self, decision_id, status, by):
        d = self.decisions[decision_id - 1]
        if d["status"] == status:
            return False
        d["status"], d["applied_by"] = status, by
        return True

    def f_load_attempt_result(self, attempt_id):
        return self.res if attempt_id == Q_ID else None

    def f_load_open_grading(self, attempt_id):
        return self.states if attempt_id == Q_ID else None

    def f_get_confidence_prediction(self, user_id, attempt_key):
        return self.pred

    def f_update_attempt_result(self, attempt_id, current, revisions):
        self.res["current"], self.res["revisions"] = current, revisions

    def f_propose_rule(self, source_report_id, rule, world_id, level, domain="recognition", source_kind="question", confirmed_error=None):
        self.rules.append({"id": len(self.rules) + 1, **rule, "domain": domain, "source_kind": source_kind, "confirmed": confirmed_error})
        return len(self.rules)

    def f_create_open_report(self, user_id, attempt_id, skill, category, criterion, target, quote, note, suggested_score, rubric_version):
        key = (user_id, attempt_id, skill, category, criterion, target)
        for r in self.reports:
            if r["_key"] == key:
                return r, False
        r = {"id": len(self.reports) + 1, "_key": key, "user_id": user_id, "attempt_id": attempt_id, "skill": skill, "category": category,
             "criterion": criterion, "target": target, "quote": quote, "note": note, "suggested_score": suggested_score,
             "status": "received", "outcome": None, "decision_id": None}
        self.reports.append(r)
        return r, True

    def f_update_open_report(self, report_id, status, outcome=None, decision_id=None):
        r = self.reports[report_id - 1]
        r["status"] = status
        if outcome is not None:
            r["outcome"] = outcome
        if decision_id is not None:
            r["decision_id"] = decision_id

    def f_open_reports_for_attempt(self, user_id, attempt_id):
        return [r for r in self.reports if r["user_id"] == user_id and r["attempt_id"] == attempt_id]

    def f_count_open_reports_today(self, user_id):
        return self.reports_today + len(self.reports)

    def f_load_attempt(self, attempt_id):
        return {"attempt_id": attempt_id, "user_id": self.user_id, "world_id": "world-1", "level": 1, "snapshot": [], "answers": {}}

    def f_set_rule_check(self, rule_id, status, note):
        pass


def judge_json(score, evidence=None, reason="lý do rà mù"):
    return json.dumps({"score": score, "evidence": evidence if evidence is not None else (["Licence means a permit"] if score else []),
                       "requirement": "so hai từ", "reason": reason})


class ValidateReportTests(unittest.TestCase):
    def setUp(self):
        self.st = make_states()["distinction"]

    def v(self, **kw):
        raw = {"skill": "distinction", "category": "missed_points", "criterion": "hieu_goc", "quote": "Licence means a permit",
               "note": "Em đã nêu nghĩa của từ gốc ở câu đầu.", **kw}
        return orv.validate_report(raw, self.st)

    def test_missed_points_requires_criterion_and_verbatim_quote_from_original_answer(self):
        self.assertEqual(self.v()["criterion"], "hieu_goc")
        with self.assertRaises(orv.OpenReportError):
            self.v(criterion="")
        with self.assertRaises(orv.OpenReportError):
            self.v(quote="")
        with self.assertRaises(orv.OpenReportError):
            self.v(quote="Licence signifies authority")          # không nguyên văn: không phải nội dung đã nộp
        with self.assertRaises(orv.OpenReportError):
            self.v(criterion="chon_tu")                          # tiêu chí không thuộc bài này

    def test_text_added_only_in_the_report_is_not_treated_as_submitted_content(self):
        with self.assertRaises(orv.OpenReportError):
            self.v(quote="Certificates are issued after exams", note="Em có viết ý này nhưng AI bỏ sót.")

    def test_score_suggestion_optional_validated_and_dropped_for_wording_reports(self):
        self.assertIsNone(self.v()["suggested_score"])
        self.assertEqual(self.v(suggested_score=1.5)["suggested_score"], 1.5)
        for bad in (2.5, 0.3, "2"):
            with self.assertRaises(orv.OpenReportError):
                self.v(suggested_score=bad)
        fb = orv.validate_report({"skill": "distinction", "category": "feedback_wrong", "target": "improve", "suggested_score": 9,
                                  "note": "Gợi ý này khó hiểu quá em không rõ làm gì."}, self.st)
        self.assertIsNone(fb["suggested_score"])               # báo cáo cách viết không bị ép (và không dùng) điểm

    def test_conflict_and_calc_reports_do_not_need_explanation_text(self):
        ok = orv.validate_report({"skill": "application", "category": "ai_conflict", "criterion": "giai_thich"}, make_states()["application"])
        self.assertEqual((ok["category"], ok["note"]), ("ai_conflict", None))
        ok = orv.validate_report({"skill": "application", "category": "calc_error", "target": "overall"}, make_states()["application"])
        self.assertEqual(ok["target"], "overall")
        with self.assertRaises(orv.OpenReportError):
            orv.validate_report({"skill": "application", "category": "calc_error", "target": "zzz"}, make_states()["application"])

    def test_rubric_mismatch_quote_must_come_from_the_question(self):
        ok = orv.validate_report({"skill": "distinction", "category": "rubric_mismatch", "criterion": "so_sanh", "quote": "how would the nuance change",
                                  "note": "Đề chỉ hỏi sắc thái thay đổi, không hỏi so sánh."}, self.st)
        self.assertEqual(ok["quote"], "how would the nuance change")
        with self.assertRaises(orv.OpenReportError):
            orv.validate_report({"skill": "distinction", "category": "rubric_mismatch", "criterion": "so_sanh", "quote": "chứa câu không có trong đề",
                                 "note": "Đề không hỏi so sánh nên không nên trừ."}, self.st)

    def test_reject_bad_skill_category_and_long_text(self):
        for raw in ({"skill": "recognition", "category": "missed_points"}, {"skill": "distinction", "category": "x"},
                    {"skill": "distinction", "category": "feedback_wrong", "target": "improve", "note": "x" * 1300}):
            with self.assertRaises(orv.OpenReportError):
                orv.validate_report(raw, self.st)


class RecheckTests(unittest.TestCase):
    def test_consistent_display_has_no_mismatch_and_tampered_values_are_found(self):
        states = make_states()
        res = make_result(states)
        self.assertEqual(orv.recheck_calculation(states, res), [])
        res["overall"] = 9.99
        res["distinction_rubric"][0]["score"] = 0.0
        fields = {m["field"] for m in orv.recheck_calculation(states, res)}
        self.assertIn("overall", fields)
        self.assertTrue(any(f.startswith("distinction_criterion") for f in fields))

    def test_gap_is_recomputed_from_confidence_and_actual_average(self):
        states = make_states()
        res = make_result(states)
        res["gap"] = 0.0
        self.assertIn("gap", {m["field"] for m in orv.recheck_calculation(states, res)})


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.states = make_states()
        self.res = make_result(self.states)
        self.fake = FakeOpenDB(self.states, self.res)
        self.fake.install()
        self.prompts = []
        self.script = {}

    def tearDown(self):
        self.fake.uninstall()

    def ask(self, prompt, **kw):
        self.prompts.append(prompt)
        for marker, fn in self.script.items():
            if marker in prompt:
                return fn(prompt) if callable(fn) else fn
        return json.dumps({"reply": "Cảm ơn em, mình đã xem lại tiêu chí này kỹ lưỡng."})

    def row(self, **kw):
        base = {"id": 1, "attempt_id": Q_ID, "skill": "distinction", "category": "missed_points", "criterion": "ngu_canh", "target": "",
                "quote": "The plant needs permission", "note": "Em đã nối chi tiết cây cần phép lấy nước với từ licence.", "suggested_score": 2.0}
        base.update(kw)
        return base

    def run_(self, row):
        return orv.process_report(self.ask, row, self.states, self.res, "KB-TEXT", ["quy-tac-cu"], "world-1", 1)

    def test_blind_judge_never_sees_old_scores_student_argument_or_suggested_score(self):
        self.script["NGƯỜI CHẤM ĐỘC LẬP"] = judge_json(2.0, ["The plant needs permission"])
        self.run_(self.row())
        blind = next(p for p in self.prompts if "NGƯỜI CHẤM ĐỘC LẬP" in p)
        self.assertNotIn("Em đã nối chi tiết", blind)                 # lập luận của báo cáo
        self.assertNotIn("suggested", blind.lower())
        self.assertNotIn("Điểm đã chốt", blind)
        self.assertIn(D_ANSWER, blind)
        self.assertIn("quy-tac-cu", blind)

    def test_accepted_creates_a_proposed_score_decision_and_never_changes_score_itself(self):
        self.script["NGƯỜI CHẤM ĐỘC LẬP"] = judge_json(2.0, ["The plant needs permission"])
        out = self.run_(self.row())
        self.assertEqual(out["status"], "accepted")
        d = self.fake.decisions[0]
        self.assertEqual((d["decision_type"], d["status"], d["payload"]["from"], d["payload"]["to"]), ("score_change", "proposed", 1.0, 2.0))
        self.assertEqual(self.res["distinction_score"], 6.0)             # điểm chưa đổi cho tới khi người có thẩm quyền áp dụng

    def test_kept_when_blind_judge_agrees_and_never_lowers_score(self):
        self.script["NGƯỜI CHẤM ĐỘC LẬP"] = judge_json(1.0, ["The plant needs permission"])
        self.assertEqual(self.run_(self.row())["status"], "kept")
        self.script["NGƯỜI CHẤM ĐỘC LẬP"] = judge_json(0.0, [])
        self.assertEqual(self.run_(self.row())["status"], "kept")
        self.assertEqual(self.fake.decisions, [])

    def test_disagreeing_original_passes_without_upgrade_wait_for_a_human(self):
        self.states["distinction"]["final"]["flags"] = [{"criterion": "ngu_canh", "scores": [0.0, 2.0], "spread": 2.0}]
        self.script["NGƯỜI CHẤM ĐỘC LẬP"] = judge_json(1.0, ["The plant needs permission"])
        self.assertEqual(self.run_(self.row())["status"], "needs_human")

    def test_invalid_judge_output_is_a_technical_failure_not_a_wrong_report(self):
        self.script["NGƯỜI CHẤM ĐỘC LẬP"] = judge_json(2.0, ["một đoạn trích không có trong bài"])
        with self.assertRaises(ValueError):
            self.run_(self.row())
        self.script["NGƯỜI CHẤM ĐỘC LẬP"] = "{{ không phải json"
        with self.assertRaises(Exception):
            self.run_(self.row())

    def test_missing_grading_record_waits_for_a_human(self):
        out = orv.process_report(self.ask, self.row(), None, None, "", [], "world-1", 1)
        self.assertEqual(out["status"], "needs_human")

    def test_ai_conflict_attaches_pass_scores_automatically(self):
        self.script["NGƯỜI CHẤM ĐỘC LẬP"] = judge_json(1.0, ["The plant needs permission"])
        out = self.run_(self.row(category="ai_conflict", quote=None, note=None, suggested_score=None))
        self.assertEqual(out["dossier"]["pass_scores"], [1.0, 1.0])

    def test_feedback_fix_is_score_neutral_and_applied_for_that_view(self):
        self.script["Kiểm tra nhận xét"] = json.dumps({"verdict": "wrong", "problem": "Gợi ý nói sai chủ thể",
                                                       "fixed_text": "Thêm một vế chỉ ai suy ra kết luận từ dấu hiệu nào.",
                                                       "reply": "Em nói đúng: gợi ý cũ chưa chỉ rõ chủ thể, đã được sửa lại."})
        out = self.run_(self.row(category="feedback_wrong", criterion="", target="hint", quote=None, suggested_score=None))
        self.assertEqual((out["status"], out["score_changed"]), ("accepted", False))
        d = self.fake.decisions[0]
        self.assertEqual((d["decision_type"], d["status"]), ("feedback_fix", "applied"))
        self.assertEqual(self.res["distinction_score"], 6.0)
        self.assertIn("fixed_text", out)

    def test_unclear_wording_is_recorded_as_a_note_and_fine_text_is_kept_with_a_reason(self):
        self.script["Kiểm tra nhận xét"] = json.dumps({"verdict": "unclear", "problem": "Câu dài", "fixed_text": "Viết lại gọn: thêm một vế chỉ người suy ra.",
                                                       "reply": "Đã ghi nhận chỗ khó hiểu của em để viết lại gọn hơn."})
        out = self.run_(self.row(category="feedback_wrong", criterion="", target="improve", quote=None, suggested_score=None))
        self.assertEqual(self.fake.decisions[0]["decision_type"], "wording_note")
        self.script["Kiểm tra nhận xét"] = json.dumps({"verdict": "fine", "problem": "", "fixed_text": "", "reply": "Nhận xét đúng với bài em: em chưa nêu sắc thái thay đổi."})
        out2 = self.run_(self.row(id=2, category="feedback_wrong", criterion="", target="strength", quote=None, suggested_score=None))
        self.assertEqual(out2["status"], "kept")

    def test_reference_issue_with_broken_structure_is_accepted_even_if_ai_says_fine(self):
        self.states["application"]["model_answer"] = "Chỉ là đoạn không có nhãn nhưng đủ dài để qua kiểm tra độ dài tối thiểu."
        self.script["Kiểm tra đáp án tham khảo"] = json.dumps({"verdict": "fine", "problem": "", "fixed_text": "", "reply": "Đáp án mẫu ổn."})
        out = self.run_(self.row(skill="application", category="reference_issue", criterion="", target="", quote=None, suggested_score=None))
        self.assertEqual(out["status"], "accepted")
        self.assertEqual(self.fake.decisions[0]["decision_type"], "reference_fix")

    def test_calc_error_is_checked_by_code_and_both_outcomes_are_explained(self):
        row = self.row(category="calc_error", criterion="", target="overall", quote=None, note=None, suggested_score=None)
        out = self.run_(row)
        self.assertEqual(out["status"], "kept")
        self.assertIn("khớp", out["reply"])
        self.res["overall"] = 1.11
        out = self.run_(row)
        self.assertEqual((out["status"], out["decision"]["type"]), ("accepted", "calc_fix"))
        self.assertTrue(out["code_bug"])
        self.assertEqual(self.fake.decisions[-1]["status"], "proposed")

    def test_rules_only_for_group_or_rubric_errors_and_only_as_proposed_open_domain(self):
        self.script["NGƯỜI CHẤM ĐỘC LẬP"] = judge_json(2.0, ["The plant needs permission"])
        self.script["Phân loại lỗi"] = json.dumps({"error_class": "case_specific", "scope": "question", "condition": "x" * 10, "guidance": "y" * 10,
                                                   "block_example": "z" * 10, "keep_example": "w" * 10})
        self.run_(self.row())
        self.assertEqual(self.fake.rules, [])
        self.script["Phân loại lỗi"] = json.dumps({"error_class": "rubric_application", "scope": "general",
                                                   "condition": "Đề chỉ yêu cầu so một từ", "guidance": "Không trừ vì thiếu từ thứ hai",
                                                   "block_example": "Trừ vì không nhắc refer", "keep_example": "Đề yêu cầu so với mọi từ"})
        out = self.run_(self.row(id=2))
        self.assertEqual(len(self.fake.rules), 1)
        r = self.fake.rules[0]
        self.assertEqual((r["domain"], r["source_kind"], out["rule_proposed"]), ("open", "open_report", 1))


class ApplyDecisionTests(unittest.TestCase):
    def setUp(self):
        self.states = make_states()
        self.res = make_result(self.states, recognition=8.0, confidence_value=8.0)
        pred = {"inputs": {"version": 2, "formula": 3, "predictions": {"distinction": {"status": "scored", "score": 8.0},
                                                                        "application": {"status": "scored", "score": 8.0}}, "joint": None}}
        self.fake = FakeOpenDB(self.states, self.res, pred=pred)
        self.fake.install()
        self.fake.f_create_open_decision(Q_ID, "distinction", "score_change", {"criterion": "ngu_canh", "from": 1.0, "to": 2.0, "evidence": ["x"]},
                                         "r", 1, "ai_blind_rejudge")

    def tearDown(self):
        self.fake.uninstall()

    def test_apply_recomputes_from_original_is_idempotent_and_keeps_locked_prediction(self):
        before = dict(self.fake.res["current"])
        r1 = orv.apply_decision(1, "ngoc")
        cur = self.fake.res["current"]
        self.assertEqual(cur["distinction"], 7.0)
        self.assertEqual(cur["overall"], scoring.calc_overall_v3(8.0, 7.0, 9.0))
        self.assertEqual(cur["gap"], 0.0)                               # dự đoán gốc 8,00 giữ nguyên; điểm đối chiếu mới (7,00 + 9,00)/2 = 8,00
        self.assertEqual(before["recognition"], cur["recognition"])
        revs = len(self.fake.res["revisions"])
        orv.apply_decision(1, "ngoc")                                   # áp dụng lần hai: cùng kết quả, không thêm bản sửa
        self.assertEqual(self.fake.res["current"], cur)
        self.assertEqual(len(self.fake.res["revisions"]), revs)
        self.assertEqual(r1["recompute"]["applied"], [1])

    def test_revoke_returns_to_the_original_numbers_and_never_revokes_progress(self):
        orig = {k: self.fake.res["current"][k] for k in ("distinction", "overall", "gap", "final_result")}
        orv.apply_decision(1, "ngoc")
        orv.revoke_decision(1, "ngoc")
        after = {k: self.fake.res["current"][k] for k in orig}
        self.assertEqual(after, orig)

    def test_decision_flips_pass_outcome_only_through_the_shared_rule(self):
        # Distinction thấp (4,0) kéo Overall xuống; nâng một tiêu chí lên không đủ qua màn nếu vẫn dưới ngưỡng chung
        d = self.states["distinction"]
        d["final"]["scores"] = {"hieu_goc": 1.0, "ngu_canh": 1.0, "doi_nghia": 0.0, "phan_biet": 1.0, "so_sanh": 1.0}
        orv.apply_decision(1, "ngoc")
        cur = self.fake.res["current"]
        self.assertEqual(cur["distinction"], 5.0)                       # đúng ngưỡng sàn kỹ năng 5,00 (số gốc)
        self.assertEqual(cur["decision"], scoring.decide_progress(8.0, 5.0, 9.0)["decision"])


class RuleRegressionTests(unittest.TestCase):
    def test_rule_must_fix_the_misgraded_case_and_not_break_old_correct_cases(self):
        cases = [{"id": "r", "kind": "must_change", "min_score": 2.0}, {"id": "o1", "kind": "must_keep", "min_score": 0.5, "max_score": 1.5}]
        good = lambda c, rule: 2.0 if c["kind"] == "must_change" else 1.0
        self.assertTrue(orv.rule_regression_check(good, {}, cases)["passed"])
        breaks_old = lambda c, rule: 2.0
        res = orv.rule_regression_check(breaks_old, {}, cases)
        self.assertFalse(res["passed"])
        self.assertEqual([r["ok"] for r in res["results"]], [True, False])
        does_nothing = lambda c, rule: 1.0
        self.assertFalse(orv.rule_regression_check(does_nothing, {}, cases)["passed"])

    def test_technical_failure_in_a_case_is_not_a_pass_and_no_cases_is_not_a_pass(self):
        def flaky(c, rule):
            raise RuntimeError("api down")
        self.assertFalse(orv.rule_regression_check(flaky, {}, [{"id": "r", "kind": "must_change", "min_score": 2.0}])["passed"])
        self.assertFalse(orv.rule_regression_check(lambda c, r: 2.0, {}, [])["passed"])
        self.assertFalse(orv.rule_regression_check(lambda c, r: 1.0, {}, [{"id": "o", "kind": "must_keep", "min_score": 0.5, "max_score": 1.5}])["passed"])


class EndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main

    def setUp(self):
        self.states = make_states()
        self.res = make_result(self.states)
        self.fake = FakeOpenDB(self.states, self.res)
        self.fake.install()
        m = self.main
        self.orig_ask, self.orig_kb, self.orig_lessons, self.orig_compact = m.ask, m.load_knowledge_base, m._safe_lessons, m.compact_kb
        m.compact_kb = lambda kb: "KB"
        self.calls = 0

        def fake_ask(prompt, **kw):
            self.calls += 1
            if "NGƯỜI CHẤM ĐỘC LẬP" in prompt:
                return judge_json(1.0, ["Licence means a permit"])
            return json.dumps({"reply": "Cảm ơn em, mình đã xem lại tiêu chí này kỹ lưỡng."})

        m.ask = fake_ask
        m.load_knowledge_base = lambda w, l: {"words": []}
        m._safe_lessons = lambda *a, **k: []
        self.user = {"id": 1, "keys": 15}

    def tearDown(self):
        m = self.main
        m.ask, m.load_knowledge_base, m._safe_lessons, m.compact_kb = self.orig_ask, self.orig_kb, self.orig_lessons, self.orig_compact
        self.fake.uninstall()

    def req(self, **kw):
        base = dict(attempt_id=Q_ID, skill="distinction", category="missed_points", criterion="hieu_goc",
                    quote="Licence means a permit", note="Em đã nêu nghĩa của từ gốc ở câu đầu của bài.")
        base.update(kw)
        return self.main.OpenReportRequest(**base)

    def test_submit_is_idempotent_and_returns_status_with_final_reason(self):
        r1 = self.main.submit_open_report(self.req(), user=self.user)
        self.assertEqual(r1["status"], "kept")
        self.assertIn("Cảm ơn", r1["reply"])
        n = self.calls
        r2 = self.main.submit_open_report(self.req(), user=self.user)         # gửi lại do mất mạng
        self.assertEqual(r2["report_id"], r1["report_id"])
        self.assertEqual(self.calls, n)                                       # không xét lại, không tạo quyết định thứ hai
        self.assertEqual(len(self.fake.reports), 1)
        listed = self.main.list_open_reports(Q_ID, user=self.user)
        self.assertEqual(len(listed["reports"]), 1)

    def test_other_users_attempt_is_not_found_and_bad_input_is_422(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:
            self.main.submit_open_report(self.req(), user={"id": 2, "keys": 1})
        self.assertEqual(cm.exception.status_code, 404)
        with self.assertRaises(HTTPException) as cm:
            self.main.submit_open_report(self.req(quote="không có trong bài"), user=self.user)
        self.assertEqual(cm.exception.status_code, 422)

    def test_technical_error_waits_and_resend_resumes(self):
        m = self.main
        good = m.ask
        m.ask = lambda prompt, **kw: "{{ hỏng"
        r1 = m.submit_open_report(self.req(), user=self.user)
        self.assertEqual(r1["status"], "pending_error")
        self.assertIn("không phải do báo cáo của em", r1["reply"])
        m.ask = good
        r2 = m.submit_open_report(self.req(), user=self.user)
        self.assertEqual((r2["report_id"], r2["status"]), (r1["report_id"], "kept"))

    def test_public_payload_hides_internal_judge_and_prompts(self):
        r = self.main.submit_open_report(self.req(), user=self.user)
        self.assertNotIn("judge", json.dumps(r))
        self.assertNotIn("prompt", json.dumps(r).lower())

    def test_daily_limit(self):
        from fastapi import HTTPException
        self.fake.reports_today = 20
        with self.assertRaises(HTTPException) as cm:
            self.main.submit_open_report(self.req(), user=self.user)
        self.assertEqual(cm.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
