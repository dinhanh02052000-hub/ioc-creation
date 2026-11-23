"""Kiểm thử chấm tự luận hai lượt + lượt ba (dữ liệu giả lập; không gọi AI thật, không chạm DB thật).

Chạy: cd server && python -B -m unittest test_open_grading -v"""

import json
import re
import sys
import threading
import unittest
from decimal import Decimal
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402

db.init_db = lambda: None
from fastapi import HTTPException  # noqa: E402

import open_grading as og  # noqa: E402
from ai_client import AIProviderError  # noqa: E402

D_ANSWER = "Licence means a permit to do something, while certificate proves you finished a course. The plant needs permission to take water so licence fits."
A_ANSWER = "The plant had a licence to take water because the permit allowed it. A certificate only proves a course."
REF_D = "REFMODEL-D-UNIQUE: từ gốc nghĩa là giấy phép; chi tiết 'holds' cho thấy quyền được cấp; thay bằng certificate làm câu mất sắc thái cho phép."
REF_A = "**Câu tiếng Anh:** The plant holds a licence to take water from the river.\n**Giải thích:** Tình huống cần sự cho phép nên chọn licence."
D_Q = "The plant holds a licence. If licence were replaced with certificate, how would the nuance change?"
A_Q = "A plant wants to take water from a river. Choose one word and explain why."


def make_pass(skill, scores, answer, evid_words=3, miss=None):
    """Bản ghi hợp lệ cho một kỹ năng; trích dẫn lấy nguyên văn từ bài."""
    quote = " ".join(answer.split()[:evid_words])
    recs = []
    for c, mx in og.CRITERIA[skill].items():
        sc = scores[c]
        recs.append({"criterion": c, "score": sc, "evidence": [quote] if sc > 0 else [],
                     "assessment": f"nhận xét {c}", "missing_or_incorrect": "sufficient" if sc == mx else (miss or "partial_missing"),
                     "score_reason": f"lý do {c}", "hint": None if sc == mx else f"gợi ý {c}"})
    return {"criteria": recs}


def scores_for_total(skill, total):
    """Phân bổ tổng (bội 0,5) lên các tiêu chí theo thứ tự, không vượt trần."""
    out, left = {}, Decimal(str(total))
    for c, mx in og.CRITERIA[skill].items():
        take = min(Decimal(mx), left)
        out[c] = float(take)
        left -= take
    assert left == 0, "tổng vượt 10"
    return out


class FakeGrader:
    """AI giả lập: lượt thứ n trả điểm theo kịch bản totals[n] = {skill: tổng}. Ghi lại mọi prompt."""

    def __init__(self, totals_by_call, answers=None):
        self.totals = totals_by_call
        self.prompts = []
        self.lock = threading.Lock()
        self.fail_calls = set()           # chỉ số lượt gọi phải lỗi mạng
        self.broken = {}                   # chỉ số lượt gọi -> hàm biến đổi đầu ra (làm hỏng)
        self.answers = answers or {"distinction": D_ANSWER, "application": A_ANSWER}
        self.calls = 0

    def __call__(self, prompt, reasoning_effort="low", model=None):
        with self.lock:
            idx = self.calls
            self.calls += 1
            self.prompts.append((prompt, model))
        if idx in self.fail_calls:
            raise AIProviderError("mạng lỗi")
        sec = {}
        for sk, tag in (("distinction", "[DISTINCTION]"), ("application", "[APPLICATION]")):
            if tag in prompt.split("BÀI CẦN CHẤM LƯỢT NÀY:")[-1]:
                sec[sk] = True
        out = {}
        plan = self.totals[min(idx, len(self.totals) - 1)]
        for sk in sec:
            out[sk] = make_pass(sk, scores_for_total(sk, plan[sk]), self.answers[sk])
        if "reference" in prompt.split("CHỈ trả JSON")[-1]:
            out["reference"] = {"d_model": REF_D, "a_model": REF_A}
        if idx in self.broken:
            out = self.broken[idx](out)
        return json.dumps(out, ensure_ascii=False)


def states(d_answer=D_ANSWER, a_answer=A_ANSWER):
    return {"version": og.RUBRIC_VERSION,
            "distinction": og.new_skill_state("distinction", d_answer, D_Q),
            "application": og.new_skill_state("application", a_answer, A_Q)}


def run(g, st=None, lessons=None):
    st = st or states()
    og.advance(st, g, "KB-TEXT", lessons, None)
    return st


class ThresholdTests(unittest.TestCase):
    def test_boundary_0_74_0_75_0_76_exact_comparison(self):
        self.assertFalse(og.needs_third_pass(5.0, 5.74))
        self.assertFalse(og.needs_third_pass(5.0, 5.75))          # đúng 0,75: KHÔNG kích hoạt (phép so sánh là '>' chứ không phải '>=')
        self.assertTrue(og.needs_third_pass(5.0, 5.76))
        self.assertTrue(og.needs_third_pass(5.76, 5.0))            # đối xứng
        self.assertEqual(og.deviation(7.0, 8.0), Decimal("1.0"))
        self.assertFalse(og.needs_third_pass(7.0, 7.5))

    def test_first_deviation_above_threshold_on_half_step_grid_is_1_0(self):
        devs = sorted({abs(a - b) / 2 for a in range(0, 21) for b in range(0, 21)})
        above = [d for d in devs if Decimal(str(d)) > Decimal("0.75")]
        self.assertEqual(min(above), 1.0)
        self.assertIn(0.5, devs)
        self.assertNotIn(0.75, devs)                               # với hai tổng hợp lệ độ lệch không bao giờ đúng 0,75

    def test_compares_raw_not_rounded_or_averaged(self):
        # hai bài lệch ngược chiều: không được triệt tiêu nhau
        self.assertTrue(og.needs_third_pass(7.0, 8.0))
        self.assertFalse(og.needs_third_pass(8.0, 8.5))


class ValidateTests(unittest.TestCase):
    ANS = "Licence means a permit. It fits because the plant needs permission."

    def ok(self, skill="distinction", **kw):
        return make_pass(skill, scores_for_total(skill, kw.get("total", 6)), self.ANS)

    def test_valid(self):
        res, errs = og.validate_skill_output(self.ok(), "distinction", self.ANS)
        self.assertEqual(errs, [])
        self.assertEqual(res["total"], 6.0)

    def test_missing_criterion_duplicate_extra_and_wrong_skill_codes(self):
        raw = self.ok()
        raw["criteria"] = [c for c in raw["criteria"] if c["criterion"] != "ngu_canh"]
        res, errs = og.validate_skill_output(raw, "distinction", self.ANS)
        self.assertIsNone(res)
        self.assertTrue(any("thiếu tiêu chí ngu_canh" in e for e in errs))
        raw = self.ok()
        raw["criteria"].append(dict(raw["criteria"][0]))
        self.assertTrue(any("nhiều hơn một lần" in e for e in og.validate_skill_output(raw, "distinction", self.ANS)[1]))
        raw = self.ok()
        raw["criteria"][0]["criterion"] = "chon_tu"                    # mã của bài kia
        self.assertTrue(any("không thuộc bài này" in e for e in og.validate_skill_output(raw, "distinction", self.ANS)[1]))

    def test_scores_are_never_coerced(self):
        for bad in ("1", "1.0", None, True, False, float("nan"), float("inf"), -0.5, 2.5, 1.25, 1.1, [1], {"v": 1}):
            raw = self.ok()
            raw["criteria"][0]["score"] = bad
            res, errs = og.validate_skill_output(raw, "distinction", self.ANS)
            self.assertIsNone(res, repr(bad))
            self.assertTrue(any("score phải là số" in e for e in errs), repr(bad))
        raw = self.ok("application")
        raw["criteria"][1]["score"] = 3.5                                # dung_dung tối đa 3: không ép xuống 3
        self.assertIsNone(og.validate_skill_output(raw, "application", self.ANS)[0])
        raw["criteria"][1]["score"] = 3
        raw["criteria"][1]["missing_or_incorrect"] = "sufficient"
        self.assertIsNotNone(og.validate_skill_output(raw, "application", self.ANS)[0])

    def test_quote_must_come_from_the_students_answer_verbatim(self):
        raw = self.ok()
        raw["criteria"][0]["evidence"] = ["The plant holds a licence"]          # câu của ĐỀ, không có trong bài
        res, errs = og.validate_skill_output(raw, "distinction", self.ANS)
        self.assertIsNone(res)
        self.assertTrue(any("không có nguyên văn" in e for e in errs))
        raw = self.ok()
        raw["criteria"][0]["evidence"] = ["LICENCE   means\na permit"]             # chuẩn hóa khoảng trắng/xuống dòng/hoa-thường
        self.assertIsNotNone(og.validate_skill_output(raw, "distinction", self.ANS)[0])
        raw = self.ok()
        raw["criteria"][0]["evidence"] = ["Licence signifies a permit"]            # đổi từ ngữ: không phải nguyên văn
        self.assertIsNone(og.validate_skill_output(raw, "distinction", self.ANS)[0])

    def test_positive_score_requires_evidence_and_wrong_verdict_requires_quote(self):
        raw = self.ok()
        raw["criteria"][0]["evidence"] = []
        self.assertTrue(any("bắt buộc kèm" in e for e in og.validate_skill_output(raw, "distinction", self.ANS)[1]))
        raw = self.ok()
        raw["criteria"][2]["score"] = 0
        raw["criteria"][2]["evidence"] = []
        raw["criteria"][2]["hint"] = "Thêm một vế nêu chi tiết của đề."
        raw["criteria"][2]["missing_or_incorrect"] = "completely_missing"          # 0 do thiếu hoàn toàn: không cần trích dẫn
        self.assertIsNotNone(og.validate_skill_output(raw, "distinction", self.ANS)[0])
        raw["criteria"][2]["missing_or_incorrect"] = "incorrect"                   # 0 do sai: phải trích phần sai
        self.assertTrue(any("trích phần sai" in e for e in og.validate_skill_output(raw, "distinction", self.ANS)[1]))

    def test_consistency_between_score_and_missing_state(self):
        raw = self.ok()
        raw["criteria"][0]["score"] = 1
        raw["criteria"][0]["missing_or_incorrect"] = "sufficient"
        self.assertTrue(any("không thể là 'sufficient'" in e for e in og.validate_skill_output(raw, "distinction", self.ANS)[1]))
        raw = self.ok()
        raw["criteria"][0]["score"] = 2
        raw["criteria"][0]["missing_or_incorrect"] = "partial_missing"
        self.assertTrue(any("phải có missing_or_incorrect='sufficient'" in e for e in og.validate_skill_output(raw, "distinction", self.ANS)[1]))
        raw = self.ok()
        raw["criteria"][0]["missing_or_incorrect"] = "maybe"
        self.assertIsNotNone(og.validate_skill_output(raw, "distinction", self.ANS)[1])

    def test_same_quote_may_support_two_criteria_with_separate_reasons(self):
        ans = "The plant needed a licence because the permit allowed it to take water."
        raw = make_pass("application", {"chon_tu": 2, "dung_dung": 3, "tinh_huong": 1, "giai_thich": 2}, ans, evid_words=6)
        res, errs = og.validate_skill_output(raw, "application", ans)
        self.assertEqual(errs, [])
        quotes = [r["evidence"][0] for r in res["records"]]
        self.assertEqual(len(set(quotes)), 1)                                    # một đoạn hỗ trợ nhiều tiêu chí


class FinalizeTests(unittest.TestCase):
    def passes(self, *totals_by_crit):
        out = []
        for sc in totals_by_crit:
            full = {"hieu_goc": 0, "ngu_canh": 0, "doi_nghia": 0, "phan_biet": 0, "so_sanh": 0}
            full.update(sc)
            recs = [{"criterion": c, "score": float(full[c]), "evidence": ["x"] if full[c] else [], "assessment": "a",
                     "missing_or_incorrect": "sufficient" if full[c] == 2 else "partial_missing", "score_reason": "r", "hint": "h"}
                    for c in full]
            out.append({"scores": {c: float(v) for c, v in full.items()}, "records": recs, "total": float(sum(full.values()))})
        return out

    def test_mean_of_two_keeps_intermediate_values(self):
        p = self.passes({"hieu_goc": 1.0, "ngu_canh": 2}, {"hieu_goc": 1.5, "ngu_canh": 2})
        f = og.finalize_skill("distinction", p)
        self.assertEqual(f["scores"]["hieu_goc"], 1.25)                       # không âm thầm làm tròn về bước 0,5
        self.assertEqual(f["total_exact"], 3.25)
        self.assertEqual(f["total"], 3.25)                                      # công thức v3: hiển thị đủ 2 chữ số, không làm tròn về 3,3
        self.assertEqual(f["method"], "mean_of_two")

    def test_median_of_three_per_criterion(self):
        p = self.passes({"hieu_goc": 0.5, "ngu_canh": 2, "doi_nghia": 1}, {"hieu_goc": 1.5, "ngu_canh": 0, "doi_nghia": 1},
                        {"hieu_goc": 1.5, "ngu_canh": 1, "doi_nghia": 2})
        f = og.finalize_skill("distinction", p)
        self.assertEqual(f["scores"]["hieu_goc"], 1.5)                          # 0,5 / 1,5 / 1,5 -> 1,5
        self.assertEqual(f["scores"]["ngu_canh"], 1.0)
        self.assertEqual(f["scores"]["doi_nghia"], 1.0)
        self.assertEqual(f["total_exact"], 3.5)                                 # tổng = tổng các trung vị
        self.assertEqual(f["method"], "median_of_three")

    def test_criterion_flags_for_same_total_different_components(self):
        p = self.passes({"hieu_goc": 2, "ngu_canh": 0, "doi_nghia": 2}, {"hieu_goc": 0, "ngu_canh": 2, "doi_nghia": 2})
        self.assertEqual(p[0]["total"], p[1]["total"])
        self.assertFalse(og.needs_third_pass(p[0]["total"], p[1]["total"]))
        flags = og.finalize_skill("distinction", p)["flags"]
        self.assertEqual({f["criterion"] for f in flags}, {"hieu_goc", "ngu_canh"})

    def test_feedback_is_composed_from_final_result_and_avoids_confident_claims_on_flagged_criteria(self):
        p = self.passes({"hieu_goc": 2, "ngu_canh": 0, "doi_nghia": 1}, {"hieu_goc": 2, "ngu_canh": 2, "doi_nghia": 1})
        f = og.finalize_skill("distinction", p)
        fb = og.compose_feedback("distinction", f, p)
        self.assertIn("Điểm làm được", fb)
        self.assertIn("Cần cải thiện", fb)
        self.assertNotIn("không hiểu", fb)
        self.assertIn("«x»", fb)                                                 # điểm làm được kèm đoạn có thật trong bài
        # tiêu chí bị cờ bất đồng không được đưa lời phê chắc chắn
        self.assertNotIn("Phù hợp ngữ cảnh): em chưa nêu", fb)

    def test_finalize_requires_two_or_three_passes(self):
        with self.assertRaises(ValueError):
            og.finalize_skill("distinction", self.passes({"hieu_goc": 1}))


class ThirdPassFlowTests(unittest.TestCase):
    def test_example_only_distinction_gets_third_pass(self):
        g = FakeGrader([{"distinction": 7.0, "application": 8.0}, {"distinction": 8.0, "application": 8.5},
                        {"distinction": 7.5}])
        st = run(g)
        self.assertEqual(g.calls, 3)
        third = g.prompts[2][0].split("BÀI CẦN CHẤM LƯỢT NÀY:")[-1]
        self.assertIn("[DISTINCTION]", third)
        self.assertNotIn("[APPLICATION]", third)                              # lượt ba chỉ cho Distinction
        self.assertEqual(st["distinction"]["status"], "final")
        self.assertEqual(len(st["distinction"]["passes"]), 3)
        self.assertEqual(len(st["application"]["passes"]), 2)
        self.assertEqual(st["application"]["final"]["method"], "mean_of_two")
        self.assertEqual(st["distinction"]["final"]["method"], "median_of_three")
        self.assertAlmostEqual(st["application"]["deviation"], 0.5)

    def test_both_deviating_get_third_pass_in_one_request_each_with_own_result(self):
        g = FakeGrader([{"distinction": 5.0, "application": 4.0}, {"distinction": 6.5, "application": 5.0},
                        {"distinction": 6.0, "application": 5.0}])
        st = run(g)
        self.assertEqual(g.calls, 3)
        third = g.prompts[2][0].split("BÀI CẦN CHẤM LƯỢT NÀY:")[-1]
        self.assertIn("[DISTINCTION]", third)
        self.assertIn("[APPLICATION]", third)
        self.assertEqual(st["distinction"]["status"], "final")
        self.assertEqual(st["application"]["status"], "final")

    def test_no_third_pass_when_deviation_is_small(self):
        g = FakeGrader([{"distinction": 7.0, "application": 8.0}, {"distinction": 7.5, "application": 8.5}])
        st = run(g)
        self.assertEqual(g.calls, 2)
        self.assertEqual(st["distinction"]["status"], "final")
        self.assertEqual(len(st["distinction"]["passes"]), 2)

    def test_third_pass_input_has_no_scores_feedback_evidence_or_other_passes(self):
        g = FakeGrader([{"distinction": 5.0, "application": 8.0}, {"distinction": 7.0, "application": 8.0}, {"distinction": 6.0}])
        st = run(g)
        third = g.prompts[2][0]
        for marker in ("nhận xét hieu_goc", "lý do hieu_goc", "gợi ý hieu_goc", REF_D):
            self.assertNotIn(marker, third)                                    # không thấy nhận xét/lý do/bằng chứng của lượt trước
        self.assertNotIn("5.0", third.split("BÀI CẦN CHẤM LƯỢT NÀY:")[-1])
        self.assertNotIn("reference", third.split("CHỈ trả JSON")[-1])        # lượt ba không soạn đáp án tham khảo

    def test_third_grader_model_config_is_used_for_third_pass_only(self):
        g = FakeGrader([{"distinction": 5.0, "application": 8.0}, {"distinction": 7.0, "application": 8.0}, {"distinction": 6.0}])
        st = states()
        og.advance(st, g, "KB", None, "third-model-x")
        self.assertEqual([m for _, m in g.prompts], [None, None, "third-model-x"])

    def test_third_pass_failure_keeps_two_valid_results_and_pending_until_retry(self):
        g = FakeGrader([{"distinction": 5.0, "application": 8.0}, {"distinction": 7.0, "application": 8.0}, {"distinction": 6.0}])
        g.fail_calls = set(range(2, 60))                                       # lượt ba (và mọi lần thử lại) lỗi mạng
        st = run(g)
        d = st["distinction"]
        self.assertEqual(d["status"], "pending_third_pass")
        self.assertEqual(len(d["passes"]), 2)                                   # hai kết quả hợp lệ được giữ
        self.assertIsNone(d["final"])                                           # KHÔNG công bố trung bình hai lượt
        self.assertEqual(st["application"]["status"], "final")                  # bài kia vẫn giữ kết quả
        calls_before = g.calls
        g.fail_calls = set()
        og.advance(st, g, "KB", None, None)                                     # thử lại RIÊNG lượt còn thiếu
        self.assertEqual(g.calls, calls_before + 1)
        self.assertEqual(st["distinction"]["status"], "final")
        self.assertEqual(len(st["distinction"]["passes"]), 3)

    def test_one_of_first_two_passes_failing_is_handled_before_claiming_cross_check(self):
        g = FakeGrader([{"distinction": 7.0, "application": 8.0}])
        g.fail_calls = {1}                                                      # lượt song song thứ hai lỗi (cả các lần thử lại)
        st = run(g)
        for sk in ("distinction", "application"):
            self.assertEqual(len(st[sk]["passes"]), 2)                          # đã bổ sung lượt thứ hai trước khi chốt
            self.assertEqual(st[sk]["status"], "final")

    def test_cannot_get_two_valid_passes_stays_pending_not_published(self):
        g = FakeGrader([{"distinction": 7.0, "application": 8.0}])
        g.fail_calls = set(range(1, 40))
        st = run(g)
        self.assertEqual(st["distinction"]["status"], "pending_pass")
        self.assertIsNone(st["distinction"]["final"])
        self.assertEqual(len(st["distinction"]["passes"]), 1)

    def test_invalid_outputs_are_grader_errors_retried_with_reasons_and_not_counted(self):
        g = FakeGrader([{"distinction": 6.0, "application": 6.0}])

        def drop_ngu_canh(out):
            out["distinction"]["criteria"] = [c for c in out["distinction"]["criteria"] if c["criterion"] != "ngu_canh"]
            return out

        g.broken = {0: drop_ngu_canh}                                           # lượt 0 thiếu ngu_canh; lượt thử lại (3) đúng
        st = run(g)
        self.assertEqual(len(st["distinction"]["passes"]), 2)
        retry_prompts = [p for p, _ in g.prompts if "LẦN TRẢ LỜI TRƯỚC KHÔNG HỢP LỆ" in p]
        self.assertTrue(retry_prompts)
        self.assertIn("thiếu tiêu chí ngu_canh", retry_prompts[0])
        self.assertNotIn("[APPLICATION]", retry_prompts[0].split("BÀI CẦN CHẤM LƯỢT NÀY:")[-1])    # chỉ thử lại bài lỗi
        # không bao giờ có điểm 0 do trường thiếu
        for p in st["distinction"]["passes"]:
            self.assertGreater(p["scores"]["ngu_canh"], -1)
            self.assertEqual(p["total"], 6.0)

    def test_bad_score_type_or_fabricated_quote_is_invalid_not_zero(self):
        g = FakeGrader([{"distinction": 6.0, "application": 6.0}])

        def bad(out):
            out["application"]["criteria"][0]["score"] = "2"
            out["distinction"]["criteria"][0]["evidence"] = ["a sentence the student never wrote"]
            return out

        g.broken = {0: bad, 1: bad}                                              # cả hai lượt đầu đều hỏng
        st = run(g)
        for sk in ("distinction", "application"):
            self.assertEqual(len(st[sk]["passes"]), 2)                           # đã thử lại và có đủ hai lượt hợp lệ
            self.assertEqual(st[sk]["status"], "final")


class BlankAnswerTests(unittest.TestCase):
    def test_blank_gets_zero_by_rule_without_ai(self):
        g = FakeGrader([{"distinction": 6.0, "application": 6.0}])
        st = run(g, states("   \n\t ", ""))
        self.assertEqual(g.calls, 0)
        for sk in ("distinction", "application"):
            self.assertEqual(st[sk]["status"], "empty")
            self.assertEqual(st[sk]["final"]["total"], 0.0)
            self.assertEqual(st[sk]["final"]["method"], "empty_by_rule")
            self.assertIn("chưa nhập câu trả lời", st[sk]["feedback"])

    def test_one_blank_only_other_skill_is_sent_to_ai(self):
        g = FakeGrader([{"application": 6.0}, {"application": 6.5}])
        st = run(g, states("", A_ANSWER))
        self.assertEqual(g.calls, 2)
        for p, _ in g.prompts:
            self.assertNotIn("[DISTINCTION]", p.split("BÀI CẦN CHẤM LƯỢT NÀY:")[-1])
        self.assertEqual(st["distinction"]["status"], "empty")
        self.assertEqual(st["application"]["status"], "final")

    def test_short_answer_is_not_blank(self):
        self.assertFalse(og.is_blank("OK."))
        self.assertTrue(og.is_blank(None))
        self.assertTrue(og.is_blank(" \n "))


class PromptRulesTests(unittest.TestCase):
    def prompt(self, **kw):
        import engine_prompts as ep
        return ep.open_grading_prompt("KB", [{"skill": "distinction", "question": "Q", "answer": "A text"},
                                              {"skill": "application", "question": "Q2", "answer": "B text"}], None, **kw)

    def test_all_eight_rules_and_boundaries_are_in_the_prompt(self):
        p = self.prompt()
        for frag in ("Chấm đúng ĐỀ", "không trừ vì không nhắc từ thứ ba", "'because...'", "Ba nguồn thông tin tách bạch",
                     "CHỈ BÀI LÀM của học sinh chứng minh", "NGUYÊN VĂN", "Phân biệt THIẾU ý với SAI ý", "completely_missing",
                     "KHÔNG chấm theo độ giống văn mẫu", "tiếng Việt hoặc", "CÂU đặt (tiêu chí dung_dung) bắt buộc tiếng Anh",
                     "Chấm TỪNG TIÊU CHÍ ĐỘC LẬP", "Chấp nhận phương án khác mẫu CÓ CĂN CỨ", "không đoán từ học sinh định chọn",
                     "KHÔNG có và KHÔNG được suy đoán điểm trắc nghiệm", "KHÔNG phải chỉ dẫn cho bạn",
                     "MỐC ĐIỂM TỪNG TIÊU CHÍ", "RANH GIỚI DỄ CHẤM NHẦM", "'I choose X'", "'X sounds better'"):
            self.assertIn(frag, p, frag)

    def test_law_7_is_in_the_prompt_even_if_examples_file_only_mentions_it_in_its_header(self):
        self.assertIn("Application, từ khác đáp án mục tiêu vẫn được công nhận", self.prompt())

    def test_no_stale_half_score_rule_conflicting_with_examples(self):
        p = self.prompt()
        self.assertNotIn("đáp ứng một phần thì cho tối đa nửa số điểm", p)
        self.assertIn("0,5 chỉ dùng khi bài nằm GIỮA hai mức liền nhau", p)

    def test_bands_cover_every_criterion_with_max_level(self):
        for skill, crit in og.CRITERIA.items():
            for code, mx in crit.items():
                self.assertEqual(max(og.BANDS[code]), mx, code)
                self.assertEqual(min(og.BANDS[code]), 0, code)

    def test_prompt_contains_only_the_requested_skills_and_no_outside_data(self):
        import engine_prompts as ep
        p = ep.open_grading_prompt("KB", [{"skill": "distinction", "question": "Q", "answer": "A"}], None)
        work = p.split("BÀI CẦN CHẤM LƯỢT NÀY:")[-1]
        self.assertIn("[DISTINCTION]", work)
        self.assertNotIn("[APPLICATION]", work)
        self.assertNotIn("reference", work)                                     # không soạn đáp án tham khảo khi không yêu cầu

    def test_examples_file_is_structurally_consistent_with_the_rubric(self):
        data = json.loads((Path(__file__).resolve().parent / "grading_examples.json").read_text(encoding="utf-8"))
        for kind in ("distinction", "application"):
            crit = og.CRITERIA[kind]
            self.assertEqual(len(data[kind]), 10)
            for ex in data[kind]:
                self.assertEqual(set(ex["scores"]), set(crit))
                for k, v in ex["scores"].items():
                    self.assertLessEqual(v, crit[k])
                    self.assertEqual(v * 2, int(v * 2))
                self.assertAlmostEqual(sum(ex["scores"].values()), ex["tong_diem"])


class MainFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main

    def setUp(self):
        m = self.main
        self.orig = (m.ask, m._start_remediation_prep, db.save_attempt_result, db.save_open_grading, m._safe_lessons)
        m._start_remediation_prep = lambda *a, **k: None
        db.save_attempt_result = lambda *a, **k: None
        self.saved = []
        db.save_open_grading = lambda aid, uid, st: self.saved.append((aid, json.loads(json.dumps(st))))
        m._safe_lessons = lambda *a, **k: []
        self.user = {"id": 1, "keys": 15}

    def tearDown(self):
        m = self.main
        m.ask, m._start_remediation_prep, db.save_attempt_result, db.save_open_grading, m._safe_lessons = self.orig

    def session(self, conf_note="SENTINEL-NOTE-9"):
        m = self.main
        s = m.create_session("world-1", 1, False)
        s["current_state"] = "WAITING_OPEN_ENDED_SUBMISSION"
        s["recognition"] = 9.0
        s["distinction_prompt"], s["application_prompt"] = D_Q, A_Q
        s["attempt_id"] = s["session_id"] + ":1"
        s["confidence_pred"] = {"inputs": {"version": 2, "predictions": {"distinction": {"status": "scored", "score": 9.0},
                                                                         "application": {"status": "scored", "score": 3.0}},
                                           "reasons": [], "note": conf_note}, "measure": "two_skill_v2"}
        return s

    def submit(self, s, d=D_ANSWER, a=A_ANSWER):
        m = self.main
        return m.submit_open_ended(m.SubmitOpenEndedRequest(session_id=s["session_id"], distinction_answer=d, application_answer=a),
                                   user=self.user)

    def test_full_flow_scores_feedback_and_overall_with_third_pass_only_for_distinction(self):
        g = FakeGrader([{"distinction": 7.0, "application": 8.0}, {"distinction": 8.0, "application": 8.5}, {"distinction": 7.5}])
        self.main.ask = g
        s = self.session()
        r = self.submit(s)
        self.assertEqual(g.calls, 3)
        self.assertEqual(r["distinction_score"], 7.5)                           # trung vị từng tiêu chí rồi cộng
        self.assertEqual(r["application_score"], 8.25)                          # trung bình hai lượt, giữ 2 chữ số
        self.assertEqual(r["grading"]["distinction"]["third_pass"], True)
        self.assertEqual(r["grading"]["application"]["third_pass"], False)
        self.assertEqual(r["grading_spread"]["flag_threshold"], 0.75)
        self.assertAlmostEqual(r["overall"], round((9.0 + 7.5 + 8.25) / 3, 2))
        self.assertEqual(len(r["distinction_rubric"]), 5)
        self.assertEqual(len(r["application_rubric"]), 4)
        self.assertEqual(r["distinction_model"], REF_D)                      # đáp án tham khảo tách khỏi bằng chứng
        self.assertIn("Điểm làm được", r["distinction_feedback"])
        self.assertEqual(r["confidence_comparison"]["skills"]["distinction"]["predicted"], 9.0)
        self.assertEqual(s["current_state"], "RETRY" if r["final_result"] == "RETRY" else "LEVEL_COMPLETED")
        self.assertTrue(self.saved)                                              # trạng thái chấm được lưu (rubric version, lượt, độ lệch)
        st = self.saved[-1][1]
        self.assertEqual(st["version"], og.RUBRIC_VERSION)
        self.assertEqual(len(st["distinction"]["passes"]), 3)

    def test_confidence_note_and_prediction_never_reach_any_grader_prompt_and_scores_do_not_depend_on_it(self):
        results = []
        for pred_note, d_pred in (("SENTINEL-NOTE-LOW", 3.0), ("SENTINEL-NOTE-HIGH", 9.0)):
            g = FakeGrader([{"distinction": 6.0, "application": 6.0}])
            self.main.ask = g
            s = self.session(conf_note=pred_note)
            s["confidence_pred"]["inputs"]["predictions"]["distinction"]["score"] = d_pred
            r = self.submit(s)
            for p, _ in g.prompts:
                self.assertNotIn(pred_note, p)
                self.assertNotIn("Recognition", p.split("KB:")[-1])
            results.append((r["distinction_score"], r["application_score"], sorted(p for p, _ in g.prompts)))   # hai lượt chạy song song: so theo tập
        self.assertEqual(results[0][0:2], results[1][0:2])
        self.assertEqual(results[0][2], results[1][2])                         # đầu vào chấm học thuật giống hệt

    def test_double_submit_is_idempotent_and_changed_answer_is_rejected(self):
        g = FakeGrader([{"distinction": 7.0, "application": 8.0}, {"distinction": 8.0, "application": 8.5}, {"distinction": 7.5}])
        self.main.ask = g
        s = self.session()
        r1 = self.submit(s)
        calls = g.calls
        r2 = self.submit(s)
        self.assertEqual(r1, r2)
        self.assertEqual(g.calls, calls)                                        # không chấm lại, không lượt ba thứ hai
        with self.assertRaises(HTTPException) as cm:
            self.submit(s, d="a different answer")
        self.assertEqual(cm.exception.status_code, 409)

    def test_concurrent_double_submit_runs_one_grading_only(self):
        g = FakeGrader([{"distinction": 7.0, "application": 8.0}, {"distinction": 8.0, "application": 8.5}, {"distinction": 7.5}])
        self.main.ask = g
        s = self.session()
        out = []
        ts = [threading.Thread(target=lambda: out.append(self.submit(s))) for _ in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(g.calls, 3)
        self.assertEqual(out[0], out[1])

    def test_pending_third_pass_returns_no_provisional_score_then_retry_completes(self):
        g = FakeGrader([{"distinction": 5.0, "application": 8.0}, {"distinction": 7.0, "application": 8.0}, {"distinction": 6.0}])
        g.fail_calls = set(range(2, 60))
        self.main.ask = g
        s = self.session()
        r = self.submit(s)
        self.assertEqual(r["status"], "pending")
        self.assertEqual(list(r["pending"]), ["distinction"])
        self.assertNotIn("distinction_score", r)                                # không công bố trung bình hai lượt
        self.assertNotIn("overall", r)
        self.assertEqual(r["application_score"], 8.0)                           # bài đã chốt giữ nguyên
        self.assertEqual(s["current_state"], "WAITING_OPEN_ENDED_SUBMISSION")   # chưa chốt Overall/Gap/PASS
        calls = g.calls
        g.fail_calls = set()
        m = self.main
        r2 = m.retry_open_grading(m.RetryOpenGradingRequest(session_id=s["session_id"]), user=self.user)
        self.assertEqual(g.calls, calls + 1)                                    # chỉ chấm lại lượt còn thiếu
        self.assertNotEqual(r2.get("status"), "pending")
        self.assertIn("overall", r2)
        r3 = m.retry_open_grading(m.RetryOpenGradingRequest(session_id=s["session_id"]), user=self.user)
        self.assertEqual(r3, r2)
        self.assertEqual(g.calls, calls + 1)

    def test_retake_resets_open_grading_state(self):
        import inspect
        src = inspect.getsource(self.main.submit_recognition)
        self.assertIn('session["open_grading"] = None', src)

    def test_remediation_uses_same_grader_and_fails_retryably_if_incomplete(self):
        g = FakeGrader([{"distinction": 6.0, "application": 6.0}])
        self.main.ask = g
        data = self.main._grade_open_ended_sync("world-1", 1, D_Q, D_ANSWER, A_Q, A_ANSWER)
        self.assertEqual((data["d_total"], data["a_total"]), (6.0, 6.0))
        g2 = FakeGrader([{"distinction": 7.0, "application": 8.0}, {"distinction": 5.0, "application": 8.0}, {"distinction": 6.0}])
        g2.fail_calls = set(range(2, 60))
        self.main.ask = g2
        with self.assertRaises(HTTPException) as cm:
            self.main._grade_open_ended_sync("world-1", 1, D_Q, D_ANSWER, A_Q, A_ANSWER)
        self.assertEqual(cm.exception.status_code, 502)

    def test_old_clamp_helper_is_gone(self):
        self.assertFalse(hasattr(self.main, "_clamp_scores"))
        self.assertFalse(hasattr(self.main, "_grade_open_ended_twice"))


if __name__ == "__main__":
    unittest.main()


class ReferenceTests(unittest.TestCase):
    def test_validate_reference_rules(self):
        ok_a = "**Câu tiếng Anh:** The plant holds a licence to take water from the river.\n**Giải thích:** Tình huống cần sự cho phép nên chọn licence."
        self.assertIsNone(og.validate_reference("application", ok_a))
        self.assertIsNotNone(og.validate_reference("application", "Chỉ là một đoạn văn tiếng Việt dài hơn bốn mươi ký tự nhưng thiếu nhãn."))
        self.assertIsNotNone(og.validate_reference("application", "**Câu tiếng Anh:** Licence.\n**Giải thích:** Tình huống cần sự cho phép nên chọn licence thật chắc."))
        self.assertIsNotNone(og.validate_reference("application", "**Câu tiếng Anh:** Nhà máy có giấy phép lấy nước từ sông.\n**Giải thích:** Tình huống cần sự cho phép."))
        self.assertIsNotNone(og.validate_reference("application", "**Câu tiếng Anh:** The plant holds a licence to take water from the river.\n**Giải thích:** English only explanation here."))
        self.assertIsNone(og.validate_reference("distinction", REF_D))
        self.assertIsNotNone(og.validate_reference("distinction", ""))
        self.assertIsNotNone(og.validate_reference("distinction", "English only text that is long enough to pass the length check easily."))
