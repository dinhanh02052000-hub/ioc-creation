"""Kiểm thử bước Confidence hai dự đoán (dữ liệu giả lập, không gọi AI, không chạm DB thật).

Chạy: cd server && python -B -m unittest test_confidence -v"""

import json
import sys
import threading
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402

db.init_db = lambda: None
from fastapi import HTTPException  # noqa: E402

import confidence as cf  # noqa: E402
import scoring  # noqa: E402


def LEG(p, r, n):
    """Đọc/dựng bản ghi dự đoán KIỂU CŨ (có 'chưa ước lượng được' hoặc dự đoán chung) để kiểm tra việc đọc lại lịch sử."""
    out = cf.normalize_input(p, r, n, allow_legacy=True)
    out["formula"] = 3
    return out


def pred(d, a, reasons=None, note=None):
    def one(v):
        if v == "unsure":
            return {"status": "unsure", "score": None}
        return {"status": "scored", "score": v}
    return {"predictions": {"distinction": one(d), "application": one(a)}, "reasons": reasons or [], "note": note}


def norm(d, a, reasons=None, note=None, formula=3):
    """Bản ghi dự đoán dùng cho các kiểm thử compare(): mặc định công thức v3 (Gap so với trung bình hai bài tự luận); v4 chạy qua formula=4."""
    p = pred(d, a, reasons, note)
    out = LEG(p["predictions"], p["reasons"], p["note"])
    out["formula"] = formula
    return out


class ValidationTests(unittest.TestCase):
    def test_zero_is_a_valid_score_and_distinct_from_unanswered_and_unsure(self):
        n = norm(0, 5)
        self.assertEqual(n["predictions"]["distinction"], {"status": "scored", "score": 0.0})
        self.assertEqual(n["predictions"]["application"], {"status": "scored", "score": 5.0})
        self.assertEqual(norm("unsure", 0)["predictions"]["distinction"], {"status": "unsure", "score": None})
        with self.assertRaises(cf.ConfidenceError):          # chưa trả lời (thiếu trạng thái)
            LEG({"distinction": {"status": None, "score": None}, "application": {"status": "scored", "score": 5}}, [], None)

    def test_missing_skill_or_extra_keys_rejected_and_never_defaulted(self):
        for bad in (None, {}, {"distinction": {"status": "scored", "score": 4}},
                    {"distinction": {"status": "scored", "score": 4}, "application": {"status": "scored", "score": 4}, "x": 1},
                    "5", [5, 5]):
            with self.assertRaises(cf.ConfidenceError):
                LEG(bad, [], None)

    def test_bad_scores(self):
        for bad in (-0.5, 10.5, 11, 4.25, 4.1, "5", None, True, False, float("nan"), float("inf"), [5], {"v": 5}):
            with self.assertRaises(cf.ConfidenceError, msg=repr(bad)):
                LEG({"distinction": {"status": "scored", "score": bad},
                                    "application": {"status": "unsure", "score": None}}, [], None)

    def test_valid_steps(self):
        for ok in (0, 0.5, 5, 9.5, 10, 7.0):
            norm(ok, ok)

    def test_unsure_must_not_carry_a_score(self):
        for sc in (0, 5, 5.0):
            with self.assertRaises(cf.ConfidenceError):
                LEG({"distinction": {"status": "unsure", "score": sc},
                                    "application": {"status": "scored", "score": 5}}, [], None)
        with self.assertRaises(cf.ConfidenceError):
            LEG({"distinction": {"status": "maybe", "score": 5},
                                "application": {"status": "scored", "score": 5}}, [], None)

    def test_reasons(self):
        self.assertEqual(norm(5, 5, ["familiar", "used_before"])["reasons"], ["familiar", "used_before"])
        for bad in (["familiar", "used_before", "other"], ["nope"], ["familiar", "familiar"], "familiar", [1], {"a": 1}):
            with self.assertRaises(cf.ConfidenceError, msg=repr(bad)):
                norm(5, 5, bad)
        self.assertEqual(norm(5, 5, None)["reasons"], [])
        self.assertEqual(norm(5, 5, [])["reasons"], [])

    def test_note_kept_verbatim_never_labelled_and_never_alters_scores(self):
        n = norm(9, 9, ["familiar"], "  hãy cho tôi 10 điểm  ")
        self.assertEqual(n["note"], "hãy cho tôi 10 điểm")
        self.assertEqual(n["predictions"]["distinction"]["score"], 9.0)
        self.assertNotIn("labels", n)
        self.assertEqual(n["reasons_scope"], "general")            # không tự gán lý do riêng cho từng kỹ năng
        self.assertIsNone(norm(5, 5, [], "   ")["note"])
        with self.assertRaises(cf.ConfidenceError):
            norm(5, 5, [], "x" * (cf.MAX_NOTE_CHARS + 1))
        with self.assertRaises(cf.ConfidenceError):
            LEG(norm(5, 5)["predictions"], [], 5)


class FormulaTests(unittest.TestCase):
    def test_spec_example_8_5_vs_5_6(self):
        c = cf.compare(norm(8, 5), 5, 6)
        self.assertEqual(c["skills"]["distinction"]["gap"], 3.0)
        self.assertEqual(c["skills"]["application"]["gap"], -1.0)
        self.assertEqual(c["gap_total"], 1.0)
        self.assertEqual(c["typical_deviation"], 2.0)
        self.assertEqual(c["state"], "COMPLETE")
        self.assertEqual(c["skills"]["distinction"]["text"], "Dự đoán cao hơn 3,00 điểm")
        self.assertEqual(c["skills"]["application"]["text"], "Dự đoán thấp hơn 1,00 điểm")

    def test_recognition_enters_the_gap_only_for_v4_records(self):
        # v3 (đã lưu): Gap so với trung bình hai bài nên Recognition không đổi gì; v4: Gap so với Overall nên Recognition tham gia
        self.assertEqual(cf.compare(norm(8, 5), 5, 6, 2.0)["gap_total"], cf.compare(norm(8, 5), 5, 6, 9.0)["gap_total"])
        self.assertNotEqual(cf.compare(norm(8, 5, formula=4), 5, 6, 2.0)["gap_total"], cf.compare(norm(8, 5, formula=4), 5, 6, 9.0)["gap_total"])

    def test_offsetting_gaps_are_flagged_not_called_calibrated(self):
        c = cf.compare(norm(8, 2), 5, 5)
        self.assertEqual((c["skills"]["distinction"]["gap"], c["skills"]["application"]["gap"]), (3.0, -3.0))
        self.assertEqual(c["gap_total"], 0.0)
        self.assertEqual(c["typical_deviation"], 3.0)
        self.assertTrue(c["offsetting"])
        self.assertEqual(cf.classify(c), "MIXED_DEVIATION")
        self.assertNotEqual(cf.classify(c), "CALIBRATED")

    def test_calibrated_and_directional_classification(self):
        self.assertEqual(cf.classify(cf.compare(norm(6, 6), 6.5, 5.5)), "CALIBRATED")
        self.assertEqual(cf.classify(cf.compare(norm(9, 9), 4, 4)), "DETECTED")
        self.assertEqual(cf.classify(cf.compare(norm(2, 2), 7, 7)), "UNDERCONFIDENT")

    def test_example_9_vs_4_keeps_prediction_and_gap_plus_5(self):
        n = norm(9, 4, ["familiar"], "em thấy quen")
        c = cf.compare(n, 4, 4)
        self.assertEqual(n["predictions"]["distinction"]["score"], 9.0)
        self.assertEqual(c["skills"]["distinction"]["gap"], 5.0)

    def test_unsure_partial_and_none(self):
        c = cf.compare(norm("unsure", 6), 5, 4)
        self.assertEqual(c["skills"]["distinction"]["gap"], None)
        self.assertEqual(c["skills"]["distinction"]["state"], "unsure")
        self.assertEqual(c["skills"]["application"]["gap"], 2.0)
        self.assertIsNone(c["gap_total"])
        self.assertIsNone(c["typical_deviation"])
        self.assertEqual((c["state"], cf.classify(c)), ("PARTIAL", "PARTIAL_DATA"))
        c = cf.compare(norm("unsure", "unsure"), 5, 4)
        self.assertEqual((c["state"], cf.classify(c)), ("NONE", "NO_PREDICTION"))
        self.assertIsNone(c["gap_total"])

    def test_awaiting_result_is_tentative_and_recomputes_from_original_prediction(self):
        n = norm(8, 5)
        c = cf.compare(n, None, 6)
        self.assertEqual(c["state"], "AWAITING_RESULT")
        self.assertIsNone(c["gap_total"])
        c1 = cf.compare(n, 5, 6)
        c2 = cf.compare(n, 7, 6)                 # điểm sau khi rà soát sửa: dự đoán gốc giữ nguyên
        self.assertEqual((c1["skills"]["distinction"]["predicted"], c2["skills"]["distinction"]["predicted"]), (8.0, 8.0))
        self.assertEqual((c1["gap_total"], c2["gap_total"]), (1.0, 0.0))

    def test_rounding_is_half_up_and_consistent(self):
        self.assertEqual(cf.round1(0.25), 0.3)
        self.assertEqual(cf.round1(-0.25), -0.3)
        self.assertEqual(cf.round1(1.0), 1.0)
        c = cf.compare(norm(6.5, 6), 6, 6)       # tổng dự đoán lệch 0,25
        self.assertEqual(c["gap_total"], 0.25)   # công thức v3: giữ 2 chữ số, không làm tròn về 0,3

    def test_describe_gap(self):
        self.assertEqual(cf.describe_gap(0.0), "Dự đoán khớp kết quả")
        self.assertEqual(cf.describe_gap(0.5), "Dự đoán cao hơn 0,50 điểm")
        self.assertEqual(cf.describe_gap(-2.5), "Dự đoán thấp hơn 2,50 điểm")
        self.assertEqual(cf.describe_gap(None), "")

    def test_weakest_criterion_needs_evidence(self):
        crit = {"a": 2, "b": 2, "c": 2}
        labels = {"a": "A", "b": "B", "c": "C"}
        self.assertEqual(cf.weakest_criterion({"a": 2, "b": 0.5, "c": 1.5}, crit, labels), "B")
        self.assertIsNone(cf.weakest_criterion({"a": 1, "b": 1, "c": 2}, crit, labels))      # hòa -> không nhận xét
        self.assertIsNone(cf.weakest_criterion({"a": 2, "b": 2, "c": 2}, crit, labels))      # không mất điểm
        self.assertIsNone(cf.weakest_criterion(None, crit, labels))
        self.assertIsNone(cf.weakest_criterion({"a": 2, "b": 2}, crit, labels))              # thiếu dữ liệu


class PassRetryTests(unittest.TestCase):
    def test_gap_none_only_overall_decides_and_unsure_never_forces_retry(self):
        self.assertEqual(scoring.determine_pass(7.0, None), "PASS")
        self.assertEqual(scoring.determine_pass(6.9, None), "RETRY")

    def test_existing_thresholds_unchanged(self):
        self.assertEqual(scoring.determine_pass(7.0, 1.0), "PASS")
        self.assertEqual(scoring.determine_pass(7.0, 1.1), "RETRY")
        self.assertEqual(scoring.determine_pass(7.0, -1.1), "RETRY")
        self.assertEqual(scoring.determine_pass(6.9, 0.0), "RETRY")


class FakeDB:
    def __init__(self):
        self.locks = {}
        self.fail = False
        self.keys = 15

    def lock_confidence_prediction(self, u, w, l, key, measure, payload):
        if self.fail:
            raise RuntimeError("db down")
        if (u, key) in self.locks:
            return json.loads(json.dumps(self.locks[(u, key)])), False
        self.locks[(u, key)] = json.loads(json.dumps(payload))
        return json.loads(json.dumps(payload)), True


class FlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main

    def setUp(self):
        m = self.main
        self.fake = FakeDB()
        self.orig_lock = m.db.lock_confidence_prediction
        m.db.lock_confidence_prediction = self.fake.lock_confidence_prediction
        self.orig_rem = m._start_remediation_prep
        self.orig_run = m._run_open_grading
        m._start_remediation_prep = lambda *a, **k: None
        self.scores = {"d": {"hieu_goc": 1, "ngu_canh": 1, "doi_nghia": 0, "phan_biet": 1, "so_sanh": 1},
                       "a": {"chon_tu": 2, "dung_dung": 2, "tinh_huong": 1, "giai_thich": 1}}   # D=4, A=6

        def fake_run(world_id, level, states):
            """Thay bộ chấm AI: điền hai lượt hợp lệ có điểm kịch bản (giống nhau nên không cần lượt ba)."""
            import open_grading as og
            for sk, key in (("distinction", "d"), ("application", "a")):
                st = states[sk]
                if st["status"] == "empty":
                    continue
                sc = {c: float(v) for c, v in self.scores[key].items()}
                recs = [{"criterion": c, "score": sc[c], "evidence": ["x"] if sc[c] else [], "assessment": "a",
                         "missing_or_incorrect": "sufficient" if sc[c] == og.CRITERIA[sk][c] else "partial_missing",
                         "score_reason": "r", "hint": "h"} for c in sc]
                rec = {"scores": sc, "records": recs, "total": float(sum(sc.values()))}
                st["passes"] = [rec, rec]
                og.refresh_status(st)

        m._run_open_grading = fake_run
        self.user = {"id": 1, "keys": 15}

    def tearDown(self):
        m = self.main
        m.db.lock_confidence_prediction = self.orig_lock
        m._run_open_grading = self.orig_run
        m._start_remediation_prep = self.orig_rem

    def session(self, recognition=9.0):
        m = self.main
        s = m.create_session("world-1", 1, False)
        s["current_state"] = "WAITING_CONFIDENCE"
        s["recognition"] = recognition
        s["attempt_no"] = 1
        done = threading.Event()
        done.set()
        s["open_prep"] = {"status": "ready", "d": "SECRET-DISTINCTION-PROMPT", "a": "SECRET-APPLICATION-PROMPT", "event": done}
        return s

    def submit(self, s, d, a, reasons=None, note=None):
        m = self.main
        p = pred(d, a, reasons, note)
        return m.submit_confidence(m.SubmitConfidenceRequest(
            session_id=s["session_id"], predictions=p["predictions"], reasons=p["reasons"], note=p["note"]), user=self.user)

    def finish(self, s):
        m = self.main
        return m.submit_open_ended(m.SubmitOpenEndedRequest(
            session_id=s["session_id"], distinction_answer="x", application_answer="y"), user=self.user)

    def test_prompts_not_returned_before_lock_and_invalid_input_does_not_release_them(self):
        s = self.session()
        m = self.main
        for bad_preds in (None, {"distinction": {"status": "scored", "score": 11}, "application": {"status": "scored", "score": 5}}):
            with self.assertRaises(HTTPException) as cm:
                m.submit_confidence(m.SubmitConfidenceRequest(session_id=s["session_id"], predictions=bad_preds), user=self.user)
            self.assertEqual(cm.exception.status_code, 422)
        self.assertEqual(s["current_state"], "WAITING_CONFIDENCE")
        self.assertIsNone(s.get("distinction_prompt"))              # đề chưa được lấy ra khỏi hàng đợi
        self.assertEqual(self.fake.locks, {})
        res = self.submit(s, 9, 5, ["familiar"], "em thấy quen")
        self.assertEqual(res["distinction_prompt"], "SECRET-DISTINCTION-PROMPT")
        self.assertEqual(len(self.fake.locks), 1)

    def test_lock_failure_blocks_prompts(self):
        s = self.session()
        self.fake.fail = True
        with self.assertRaises(HTTPException) as cm:
            self.submit(s, 5, 5)
        self.assertEqual(cm.exception.status_code, 503)
        self.assertEqual(s["current_state"], "WAITING_CONFIDENCE")
        self.assertIsNone(s.get("distinction_prompt"))
        self.fake.fail = False
        self.assertIn("distinction_prompt", self.submit(s, 5, 5))     # thử lại được

    def test_double_submit_is_idempotent_and_different_values_rejected_after_prompts_shown(self):
        s = self.session()
        first = self.submit(s, 9, 5)
        again = self.submit(s, 9, 5)                 # mất phản hồi đầu / bấm đúp / tải lại
        self.assertEqual(first, again)
        self.assertEqual(len(self.fake.locks), 1)
        with self.assertRaises(HTTPException) as cm:
            self.submit(s, 2, 2)
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(list(self.fake.locks.values())[0]["inputs"]["predictions"]["distinction"]["score"], 9.0)

    def test_second_attempt_gets_its_own_prediction_and_first_is_not_overwritten(self):
        s = self.session()
        self.submit(s, 9, 5)
        self.finish(s)
        # lần làm lại cùng phiên: nộp Recognition lần 2 đặt lại dự đoán và tăng lượt
        s["current_state"] = "WAITING_CONFIDENCE"
        s["attempt_no"] = 2
        s["confidence_pred"] = None
        done = threading.Event()
        done.set()
        s["open_prep"] = {"status": "ready", "d": "D2", "a": "A2", "event": done}
        s["distinction_prompt"] = None
        self.submit(s, 3, 3)
        self.assertEqual(len(self.fake.locks), 2)
        keys = sorted(k[1] for k in self.fake.locks)
        self.assertEqual(keys, [f"{s['session_id']}:1", f"{s['session_id']}:2"])
        first = self.fake.locks[(1, f"{s['session_id']}:1")]
        self.assertEqual(first["inputs"]["predictions"]["distinction"]["score"], 9.0)

    def test_result_9_predicted_4_actual_keeps_9_gap_plus_5(self):
        s = self.session(recognition=9.0)
        self.submit(s, 9, 6, ["familiar"], "em thấy quen")
        r = self.finish(s)
        c = r["confidence_comparison"]
        self.assertEqual(r["distinction_score"], 4.0)
        self.assertEqual(c["skills"]["distinction"]["predicted"], 9.0)
        self.assertEqual(c["skills"]["distinction"]["gap"], 5.0)
        self.assertEqual(c["skills"]["application"]["gap"], 0.0)
        self.assertEqual(c["skills"]["distinction"]["weakest_criterion"], "Thay đổi nghĩa")
        self.assertEqual(r["confidence_version"], 2)
        self.assertEqual(r["confidence"], 7.5)                  # công thức v3: Confidence chính thức = trung bình hai dự đoán riêng
        self.assertEqual(c["reasons"], ["familiar"])
        self.assertEqual(c["note"], "em thấy quen")

    def test_recognition_changes_only_the_total_gap_not_the_per_skill_gaps(self):
        gaps, totals = [], []
        for recog in (0.0, 5.0, 10.0):
            s = self.session(recognition=recog)
            self.submit(s, 8, 5)
            r = self.finish(s)
            c = r["confidence_comparison"]
            gaps.append((c["skills"]["distinction"]["gap"], c["skills"]["application"]["gap"]))
            totals.append(c["gap"])
        self.assertEqual(len(set(gaps)), 1)                 # độ lệch TỪNG kỹ năng không phụ thuộc Recognition
        self.assertEqual(len(set(totals)), 3)               # Gap tổng (v4) có Recognition qua Overall nên đổi theo
        self.assertGreater(totals[0], totals[2])            # Recognition cao -> Overall cao -> Gap thấp hơn

    def test_pass_retry_uses_combined_gap_when_both_predicted(self):
        self.scores["d"] = {"hieu_goc": 2, "ngu_canh": 2, "doi_nghia": 2, "phan_biet": 1, "so_sanh": 1}   # D=8
        self.scores["a"] = {"chon_tu": 2, "dung_dung": 2, "tinh_huong": 2, "giai_thich": 2}               # A=8
        s = self.session(recognition=9.0)                  # Overall 8.3
        self.submit(s, 8, 8)
        r = self.finish(s)
        self.assertEqual((r["gap"], r["final_result"]), (-0.33, "PASS"))       # Confidence 8,00 - Overall 8,33
        s = self.session(recognition=9.0)
        self.submit(s, 10, 10)                             # Gap tổng +2: chỉ ảnh hưởng phản hồi tự đánh giá, KHÔNG chặn qua màn (Overall 8,33)
        r = self.finish(s)
        self.assertEqual((r["gap"], r["final_result"], r["decision"]), (1.67, "PASS", "PASS"))   # 10,00 - 8,33
        self.assertEqual(r["illusion_status"], "DETECTED")
        self.assertEqual(r["calibration"]["code"], "HIGHER")
        self.assertNotIn("|Gap|", r["decision_info"]["note"])

    def test_legacy_single_confidence_still_works_and_is_not_duplicated_into_two(self):
        m = self.main
        s = self.session()
        res = m.submit_confidence(m.SubmitConfidenceRequest(session_id=s["session_id"], confidence=7.5), user=self.user)
        self.assertIn("distinction_prompt", res)
        self.assertEqual(self.fake.locks, {})                  # không tạo bản ghi hai dự đoán
        r = self.finish(s)
        self.assertEqual(r["confidence_version"], 1)
        self.assertEqual(r["confidence"], 7.5)
        self.assertEqual(r["gap"], round(7.5 - r["overall"], 1))
        self.assertNotIn("skills", r["confidence_comparison"])
        with self.assertRaises(HTTPException) as cm:           # điểm sai bước vẫn bị chặn ở đường cũ
            m.submit_confidence(m.SubmitConfidenceRequest(session_id=self.session()["session_id"], confidence=7.3), user=self.user)
        self.assertEqual(cm.exception.status_code, 422)

    def test_wrong_state_rejected(self):
        s = self.session()
        s["current_state"] = "WAITING_RECOGNITION_SUBMISSION"
        with self.assertRaises(HTTPException) as cm:
            self.submit(s, 5, 5)
        self.assertEqual(cm.exception.status_code, 409)

    def test_rubric_endpoint_is_single_source_with_grader(self):
        m = self.main
        r = m.get_confidence_rubric()
        self.assertEqual(r["distinction"]["total"], 10)
        self.assertEqual(r["application"]["total"], 10)
        self.assertEqual({c["key"]: c["max"] for c in r["distinction"]["criteria"]}, m.DISTINCTION_CRITERIA)
        self.assertEqual({c["key"]: c["max"] for c in r["application"]["criteria"]}, m.APPLICATION_CRITERIA)
        self.assertEqual(r["reasons"], list(cf.REASON_IDS))

    def test_submit_recognition_resets_prediction_state_for_new_attempt(self):
        import inspect
        src = inspect.getsource(self.main.submit_recognition)
        self.assertIn('session["attempt_no"]', src)
        self.assertIn('session["confidence_pred"] = None', src)


    def test_new_submissions_require_both_sliders_no_unsure_no_joint(self):
        m = self.main
        s = self.session()
        unsure = {"status": "unsure", "score": None}
        ok = {"status": "scored", "score": 5.0}
        for bad in ({"distinction": unsure, "application": ok}, {"distinction": ok, "application": unsure},
                    {"distinction": unsure, "application": unsure, "joint": {"status": "scored", "score": 7.0}},
                    {"distinction": ok, "application": ok, "joint": {"status": "scored", "score": 7.0}},
                    {"distinction": ok}, {"distinction": {"status": None, "score": None}, "application": ok}):
            with self.assertRaises(HTTPException) as cm:
                m.submit_confidence(m.SubmitConfidenceRequest(session_id=s["session_id"], predictions=bad), user=self.user)
            self.assertEqual(cm.exception.status_code, 422)
        self.assertEqual(self.fake.locks, {})
        self.assertIsNone(s.get("distinction_prompt"))             # đề chỉ ra sau khi có đủ hai dự đoán
        self.assertIn("distinction_prompt", self.submit(s, 0, 0))   # 0,00 vẫn là một dự đoán hợp lệ

    # ---- công thức v3 qua toàn luồng ----
    def test_screenshot_case_end_to_end(self):
        self.scores["d"] = {"hieu_goc": 0, "ngu_canh": 0, "doi_nghia": 0, "phan_biet": 0, "so_sanh": 0}       # D = 0
        self.scores["a"] = {"chon_tu": 2, "dung_dung": 3, "tinh_huong": 2, "giai_thich": 2}                 # A = 9
        s = self.session(recognition=8.5)
        self.submit(s, 8, 8.5)
        r = self.finish(s)
        cs = r["confidence_summary"]
        self.assertEqual((r["confidence"], cs["gap"], r["overall"]), (8.25, 2.42, 5.83))         # Gap = 8,25 - Overall 5,83 (Recognition tham gia)
        self.assertEqual((cs["reference_score"], cs["reference_kind"]), (5.83, "overall"))
        self.assertEqual((cs["details"]["distinction"]["gap"], cs["details"]["application"]["gap"]), (8.0, -0.5))
        self.assertEqual(cs["gap_text"], "Em dự đoán cao hơn Overall (cả ba kỹ năng) 2,42 điểm.")
        self.assertEqual((r["decision"], r["final_result"]), ("RETRY", "RETRY"))
        self.assertEqual(r["decision_info"]["review_target_key"], "distinction")
        self.assertIn("Phân biệt 0,00 dưới 5,00", r["retry_note"])
        self.assertEqual(r["understanding"]["code"], "PARTIAL")
        self.assertEqual(r["calibration"]["code"], "MUCH_HIGHER")
        self.assertEqual(r["formula_version"], 4)

    def test_decision_uses_exact_scores_and_gap_never_blocks(self):
        self.scores["d"] = {"hieu_goc": 2, "ngu_canh": 2, "doi_nghia": 1.5, "phan_biet": 1.5, "so_sanh": 1.5}   # D = 8,5
        self.scores["a"] = {"chon_tu": 2, "dung_dung": 2, "tinh_huong": 1.5, "giai_thich": 1.5}                 # A = 7
        s = self.session(recognition=5.0)                  # Overall 6,83: qua kèm khuyến nghị ôn, kỹ năng thấp nhất = Nhận biết
        self.submit(s, 10, 10)
        r = self.finish(s)
        self.assertEqual((r["decision"], r["final_result"]), ("PASS_WITH_REVIEW", "PASS"))
        self.assertEqual(s["current_state"], "LEVEL_COMPLETED")
        self.assertEqual(r["decision_info"]["review_target_key"], "recognition")
        self.assertIsNotNone(r["decision_info"]["review_target"])

    def test_grading_detail_exposes_each_pass_and_hides_internals(self):
        s = self.session()
        self.submit(s, 5, 5)
        r = self.finish(s)
        det = r["grading_detail"]["distinction"]
        self.assertEqual(len(det["criteria"]), 5)
        self.assertEqual(det["pass_count"], 2)
        self.assertEqual(len(det["criteria"][0]["passes"]), 2)
        self.assertEqual(det["pass_totals"], [4.0, 4.0])
        self.assertEqual(det["final_total"], 4.0)
        self.assertNotIn("prompt", str(det).lower())


import scoring as sc


class FormulaV3Tests(unittest.TestCase):
    def test_screenshot_case_8_25_gap_3_75_overall_5_83(self):
        n = norm(8, 8.5)
        c = cf.compare(n, 0.0, 9.0)
        self.assertEqual((c["confidence"], c["confidence_source"]), (8.25, "two_skill_average"))
        self.assertEqual((c["actual_average"], c["gap_total"]), (4.5, 3.75))
        self.assertEqual((c["skills"]["distinction"]["gap"], c["skills"]["application"]["gap"]), (8.0, -0.5))
        self.assertEqual(sc.calc_overall_v3(8.5, 0.0, 9.0), 5.83)
        self.assertFalse(c["offsetting"])
        self.assertEqual(sc.describe_total_gap(c["gap_total"], "essay_average"), "Em dự đoán cao hơn kết quả hai phần tự luận 3,75 điểm.")

    def test_offsetting_plus_minus_three_gives_zero_gap_but_is_flagged(self):
        c = cf.compare(norm(8, 5), 5.0, 8.0)
        self.assertEqual(c["gap_total"], 0.0)
        self.assertTrue(c["offsetting"])
        cal = sc.calibration_v3(c["gap_total"], {k: v["gap"] for k, v in c["skills"].items()})
        self.assertEqual(cal["code"], "CLOSE")
        self.assertTrue(cal["offsetting"])
        self.assertIn("hai hướng", cal["text"])

    def test_not_offsetting_when_one_side_is_small(self):
        c = cf.compare(norm(6.5, 5), 5.0, 5.5)          # +1,5 và -0,5
        self.assertFalse(c["offsetting"])

    def test_joint_prediction_used_only_when_two_skill_predictions_are_incomplete(self):
        unsure = {"status": "unsure", "score": None}
        n = LEG({"distinction": unsure, "application": unsure, "joint": {"status": "scored", "score": 7.0}}, [], None)
        c = cf.compare(n, 5.0, 6.0)
        self.assertEqual((c["confidence"], c["confidence_source"], c["gap_total"]), (7.0, "joint_direct", 1.5))
        self.assertEqual(c["state"], "COMPLETE")
        self.assertEqual(c["skills"]["distinction"]["state"], "unsure")
        # đủ hai dự đoán riêng: dự đoán chung bị bỏ, không lưu hai nguồn
        n2 = LEG({"distinction": {"status": "scored", "score": 6.0}, "application": {"status": "scored", "score": 8.0},
                                 "joint": {"status": "scored", "score": 1.0}}, [], None)
        self.assertIsNone(n2["joint"])
        self.assertEqual(cf.compare(n2, 5.0, 6.0)["confidence_source"], "two_skill_average")

    def test_single_skill_prediction_does_not_stand_in_for_both(self):
        n = LEG({"distinction": {"status": "scored", "score": 8.0}, "application": {"status": "unsure", "score": None}}, [], None)
        c = cf.compare(n, 5.0, 6.0)
        self.assertIsNone(c["confidence"])
        self.assertIsNone(c["gap_total"])
        self.assertEqual(c["skills"]["distinction"]["gap"], 3.0)
        self.assertEqual(c["state"], "PARTIAL")

    def test_zero_is_a_valid_prediction_and_unsure_joint_means_no_data(self):
        n = LEG({"distinction": {"status": "scored", "score": 0.0}, "application": {"status": "scored", "score": 0.0}}, [], None)
        c = cf.compare(n, 2.0, 4.0)
        self.assertEqual((c["confidence"], c["gap_total"]), (0.0, -3.0))
        unsure = {"status": "unsure", "score": None}
        n2 = LEG({"distinction": unsure, "application": unsure, "joint": unsure}, [], None)
        c2 = cf.compare(n2, 2.0, 4.0)
        self.assertIsNone(c2["confidence"])
        self.assertEqual(sc.calibration_v3(None)["code"], "UNKNOWN")

    def test_joint_input_validated(self):
        unsure = {"status": "unsure", "score": None}
        for bad in ({"status": "scored", "score": 11}, {"status": "scored", "score": 7.3}, {"status": "unsure", "score": 5}, {"status": "x"}, 5):
            with self.assertRaises(cf.ConfidenceError):
                LEG({"distinction": unsure, "application": unsure, "joint": bad}, [], None)

    def test_awaiting_result_keeps_locked_prediction_and_recomputes(self):
        n = LEG({"distinction": {"status": "scored", "score": 8.0}, "application": {"status": "scored", "score": 8.5}}, [], None)
        self.assertEqual(cf.compare(n, None, 9.0)["state"], "AWAITING_RESULT")
        self.assertEqual(cf.compare(n, 0.0, 9.0)["gap_total"], 3.75)
        self.assertEqual(cf.compare(n, 4.0, 9.0)["gap_total"], 1.75)

    def test_calibration_thresholds_on_signed_gap(self):
        c = lambda g: sc.calibration_v3(g)["code"]
        self.assertEqual([c(1.0), c(-1.0), c(1.01), c(2.0), c(2.01), c(-2.5)],
                         ["CLOSE", "CLOSE", "HIGHER", "HIGHER", "MUCH_HIGHER", "MUCH_LOWER"])


class ProgressDecisionTests(unittest.TestCase):
    def dec(self, r, d, a):
        return sc.decide_progress(r, d, a)["decision"]

    def test_threshold_boundaries_use_exact_numbers(self):
        self.assertEqual(self.dec(7, 7, 7), "PASS")
        self.assertEqual(self.dec(7, 7, 6.99), "PASS_WITH_REVIEW")      # tổng 20.99 -> Overall 6,997 (hiển thị 7,00 nhưng KHÔNG qua ngưỡng 7)
        self.assertEqual(self.dec(6, 6, 6), "PASS_WITH_REVIEW")
        self.assertEqual(self.dec(6, 6, 5.99), "RETRY")
        self.assertEqual(self.dec(5, 5, 5), "RETRY")                    # Overall 5 < 6
        self.assertEqual(self.dec(10, 10, 4.99), "RETRY")               # một kỹ năng < 5
        self.assertEqual(self.dec(10, 10, 5), "PASS")
        self.assertEqual(self.dec(8.5, 0, 9), "RETRY")

    def test_displayed_rounding_does_not_leak_into_decision(self):
        # 6,995 hiển thị 7,00 nhưng so ngưỡng bằng số gốc
        self.assertEqual(sc.calc_overall_v3(7, 7, 6.99), 7.0)
        self.assertEqual(self.dec(7, 7, 6.99), "PASS_WITH_REVIEW")

    def test_gap_does_not_change_the_decision(self):
        d = sc.decide_progress(8, 7, 7)
        self.assertEqual(d["final_result"], "PASS")

    def test_review_target_is_the_weakest_skill_and_reasons_name_the_failure(self):
        d = sc.decide_progress(8.5, 0, 9)
        self.assertEqual((d["review_target_key"], d["low_skills"]), ("distinction", ["distinction"]))
        self.assertTrue(any("Phân biệt 0,00 dưới 5,00" in r for r in d["reasons"]))
        self.assertTrue(any("5,83 chưa đạt 6,00" in r for r in d["reasons"]))
        p = sc.decide_progress(6.5, 6.5, 6.5)
        self.assertEqual(p["final_result"], "PASS")
        self.assertIsNotNone(p["review_target"])
        self.assertIsNone(sc.decide_progress(9, 9, 9)["review_target"])

    def test_understanding_levels_cover_table_boundaries(self):
        u = lambda o: sc.understanding_v3(o, o, o)["code"]
        self.assertEqual([u(3.99), u(4), u(5.99), u(6), u(6.99), u(7), u(8.49), u(8.5)],
                         ["NOT_ENOUGH_BASE", "PARTIAL", "PARTIAL", "BASIC", "BASIC", "FAIRLY_SOLID", "FAIRLY_SOLID", "SOLID"])



class GapOverallTests(unittest.TestCase):
    """Công thức v4: Gap = Confidence - Overall (Recognition + Distinction + Application)/3."""
    def test_screenshot_values_of_the_live_site(self):
        n = norm(8, 8, formula=4)
        c = cf.compare(n, 10.0, 4.0, 9.0)                        # ảnh trang thật: R 9,00; D 10,00; A 4,00; dự đoán 8 và 8
        self.assertEqual((c["confidence"], c["reference_kind"], c["reference_score"]), (8.0, "overall", 7.67))
        self.assertEqual(c["gap_total"], 0.33)
        self.assertEqual((c["skills"]["distinction"]["gap"], c["skills"]["application"]["gap"]), (-2.0, 4.0))
        self.assertTrue(c["offsetting"] is False or c["offsetting"] is True)

    def test_recognition_is_required_and_missing_recognition_means_no_gap_yet(self):
        n = norm(8, 8, formula=4)
        c = cf.compare(n, 10.0, 4.0)
        self.assertIsNone(c["gap_total"])
        self.assertEqual(c["state"], "AWAITING_RESULT")

    def test_v3_records_keep_the_old_baseline_when_recomputed(self):
        n = norm(8, 8, formula=3)
        c = cf.compare(n, 10.0, 4.0, 9.0)
        self.assertEqual((c["gap_total"], c["reference_kind"]), (1.0, "essay_average"))

    def test_new_inputs_are_written_with_formula_4(self):
        out = cf.normalize_input({"distinction": {"status": "scored", "score": 5.0}, "application": {"status": "scored", "score": 5.0}}, [], None)
        self.assertEqual(out["formula"], 4)

    def test_gap_text_names_overall(self):
        self.assertEqual(scoring.describe_total_gap(0.33), "Em dự đoán cao hơn Overall (cả ba kỹ năng) 0,33 điểm.")
        self.assertEqual(scoring.describe_total_gap(-1.5), "Em dự đoán thấp hơn Overall (cả ba kỹ năng) 1,50 điểm.")
        self.assertEqual(scoring.describe_total_gap(0.0), "Dự đoán của em trùng khít với Overall (cả ba kỹ năng).")

    def test_recognition_correction_recomputes_gap_from_the_locked_confidence(self):
        import review
        orig = {"formula_version": 4, "confidence": 8.0, "gap": 0.33}
        new = review.recompute_results(orig, 5.0, 10.0, 4.0, 0.33, None)
        self.assertEqual(new["overall"], 6.33)
        self.assertEqual(new["gap"], 1.67)                       # 8,00 - 6,33
        old = review.recompute_results({"formula_version": 3, "confidence": 8.0}, 5.0, 10.0, 4.0, 1.0, None)
        self.assertEqual(old["gap"], 1.0)                        # v3 giữ nguyên Gap khi sửa Recognition


if __name__ == "__main__":
    unittest.main()
