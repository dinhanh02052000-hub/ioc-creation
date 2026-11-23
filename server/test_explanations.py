"""Kiểm thử mô-đun lời giải (explanations.py): kiểm tra từng mục do AI trả về và cách ghép. Dữ liệu giả lập, không gọi AI."""

import copy
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import explanations as ex  # noqa: E402
import review  # noqa: E402

SENT = "The suspicious login alert, which seems to ___ that someone accessed the account, triggered an investigation."
OPTS = ["denote", "infer", "refer", "imply"]


def target(mode="wrong", chosen="denote"):
    qs = [{"id": 1, "question": SENT, "options": list(OPTS), "correct_index": 3}]
    snap = review.build_snapshot("world-2", 1, qs)[0]
    key = snap["key_oid"]
    ch = next((o["oid"] for o in snap["options"] if o["text"] == chosen), None) if mode != "unanswered" else None
    if mode == "correct":
        ch = key
    return ex.make_target(qs[0], snap, {"key_oids": [key], "chosen": ch})


def item(**kw):
    base = {"id": 1, "status": "ready", "evidence": ["seems to ___ that someone accessed the account", "triggered an investigation"],
            "evidence_meaning": "Cảnh báo chỉ gợi ra khả năng có người truy cập; chưa có xác nhận.",
            "why_key": "imply diễn tả một dấu hiệu gián tiếp gợi ra điều gì đó, khớp với việc cảnh báo chỉ gợi khả năng.",
            "translation_vi": "Cảnh báo đăng nhập đáng ngờ, dường như gợi ý có người truy cập tài khoản, đã dẫn tới điều tra.",
            "contrast_option": "denote", "shared_point": "cả hai đều có thể dịch là 'biểu thị'",
            "contrast_vi": "denote nói dấu hiệu mang một nghĩa đã xác định, còn ở đây cảnh báo chỉ gợi khả năng",
            "example_en": "The padlock icon denotes a locked account.", "example_vi": "Biểu tượng ổ khóa biểu thị tài khoản bị khóa.",
            "grammar_vi": None, "grammar_excludes": [], "start_hint": None, "doubt_reason": None, "also_defensible": []}
    base.update(kw)
    return base


class TargetTests(unittest.TestCase):
    def test_mode_choice_and_key_come_from_the_server_not_from_ai_text(self):
        t = target("wrong", "denote")
        self.assertEqual((t["mode"], t["options"][t["selected_index"]], t["options"][t["key_index"]]), ("wrong", "denote", "imply"))
        self.assertEqual(target("correct")["mode"], "correct")
        u = target("unanswered")
        self.assertEqual((u["mode"], u["selected_index"]), ("unanswered", None))

    def test_choice_b_infer_changes_the_target(self):
        t = target("wrong", "infer")
        self.assertEqual(t["options"][t["selected_index"]], "infer")

    def test_cache_key_depends_on_version_key_and_choice(self):
        a, b, c = target("wrong", "denote"), target("wrong", "infer"), target("correct")
        self.assertNotEqual(ex.cache_key(a), ex.cache_key(b))
        self.assertNotEqual(ex.cache_key(a), ex.cache_key(c))
        changed = dict(a, key_sig="other")
        self.assertNotEqual(ex.cache_key(a), ex.cache_key(changed))


class ValidateTests(unittest.TestCase):
    def test_good_item_for_the_photo_case(self):
        clean, errs = ex.validate_item(item(), target())
        self.assertEqual(errs, [])
        text = ex.compose(clean, target())
        self.assertIn("**Dấu hiệu trong đề:**", text)
        self.assertIn("**Vì sao chọn imply:**", text)
        self.assertIn("So với «denote» (em đã chọn)", text)
        self.assertIn("Ví dụ minh họa mới", text)
        self.assertNotIn("em chọn từ này vì", text)

    def test_contrast_must_be_the_students_own_choice_for_wrong_answers(self):
        _, errs = ex.validate_item(item(contrast_option="infer"), target("wrong", "denote"))
        self.assertTrue(any("đúng lựa chọn của học sinh" in e for e in errs))
        t = target("wrong", "infer")
        clean, errs = ex.validate_item(item(contrast_option="infer", shared_point="cùng nói về điều rút ra",
                                            contrast_vi="infer là người quan sát suy ra điều gì từ dấu hiệu, imply là dấu hiệu gợi ra"), t)
        self.assertEqual(errs, [])
        self.assertIn("«infer» (em đã chọn)", ex.compose(clean, t))

    def test_contrast_cannot_be_the_key_or_a_made_up_word(self):
        for bad in ("imply", "banana", ""):
            _, errs = ex.validate_item(item(contrast_option=bad), target("wrong", "denote"))
            self.assertTrue(errs, bad)

    def test_evidence_must_be_verbatim_from_the_sentence(self):
        _, errs = ex.validate_item(item(evidence=["someone hacked the account"]), target())
        self.assertTrue(any("không có nguyên văn" in e for e in errs))
        for bad in ([], ["a", "b", "c"], "", None):
            self.assertTrue(ex.validate_item(item(evidence=bad), target())[1])
        clean, errs = ex.validate_item(item(evidence=['"seems to ___ that someone"; "triggered an investigation"']), target())
        self.assertEqual(errs, [])

    def test_link_step_required_and_no_circular_restatement(self):
        _, errs = ex.validate_item(item(why_key=""), target())
        self.assertTrue(errs)
        same = "Cảnh báo chỉ gợi ra khả năng có người truy cập"
        _, errs = ex.validate_item(item(evidence_meaning=same, why_key=same), target())
        self.assertTrue(any("trùng nguyên văn" in e for e in errs))
        _, errs = ex.validate_item(item(shared_point="giống", contrast_vi="giống"), target())
        self.assertTrue(any("không được trùng nhau" in e for e in errs))

    def test_generic_grammar_claim_is_dropped_unless_it_excludes_a_specific_option(self):
        clean, errs = ex.validate_item(item(grammar_vi="Sau 'to' cần động từ nguyên thể.", grammar_excludes=[]), target())
        self.assertEqual(errs, [])
        self.assertIsNone(clean["grammar_vi"])
        self.assertNotIn("Ngữ pháp", ex.compose(clean, target()))
        clean, _ = ex.validate_item(item(grammar_vi="Sau 'to' cần động từ nguyên thể, loại refer vì ...", grammar_excludes=["refer"]), target())
        self.assertIn("Ngữ pháp", ex.compose(clean, target()))
        clean, _ = ex.validate_item(item(grammar_vi="x", grammar_excludes=["imply"]), target())
        self.assertIsNone(clean["grammar_vi"])

    def test_absolute_claims_are_rejected(self):
        for phrase in ("denote không bao giờ đi với that", "imply luôn luôn đúng", "chỉ dùng được trong tin tức"):
            _, errs = ex.validate_item(item(contrast_vi=phrase), target())
            self.assertTrue(any("tuyệt đối" in e for e in errs), phrase)

    def test_example_must_differ_from_the_sentence_and_have_translation(self):
        _, errs = ex.validate_item(item(example_en=SENT, example_vi="x"), target())
        self.assertTrue(errs)
        _, errs = ex.validate_item(item(example_en="A short new example.", example_vi=""), target())
        self.assertTrue(errs)
        clean, errs = ex.validate_item(item(example_en=None, example_vi=None), target())
        self.assertEqual(errs, [])
        self.assertNotIn("Ví dụ minh họa", ex.compose(clean, target()))

    def test_unanswered_needs_start_hint_and_no_choice_is_assigned(self):
        t = target("unanswered")
        _, errs = ex.validate_item(item(contrast_option="denote"), t)
        self.assertTrue(any("start_hint" in e for e in errs))
        clean, errs = ex.validate_item(item(contrast_option="denote", start_hint="Đọc cả câu, tìm chủ ngữ của seems to."), t)
        self.assertEqual(errs, [])
        text = ex.compose(clean, t)
        self.assertIn("Cách bắt đầu", text)
        self.assertNotIn("em đã chọn", text)

    def test_correct_answer_is_short_and_contrast_optional(self):
        t = target("correct")
        clean, errs = ex.validate_item(item(contrast_option=None, shared_point="", contrast_vi="", example_en=None, example_vi=None), t)
        self.assertEqual(errs, [])
        text = ex.compose(clean, t)
        self.assertNotIn("So với", text)
        self.assertNotIn("nắm vững", text)

    def test_review_key_status_requires_reason_and_yields_partial_text_only(self):
        raw = item(status="review_key", doubt_reason="chi tiết chưa loại được denote", also_defensible=["denote"], why_key=None)
        clean, errs = ex.validate_item(raw, target())
        self.assertEqual(errs, [])
        self.assertEqual(clean["status"], "review_key")
        partial = ex.compose_partial(clean)
        self.assertIn("Dấu hiệu trong đề", partial)
        self.assertNotIn("Vì sao chọn", partial)
        _, errs = ex.validate_item(item(status="review_key", doubt_reason=""), target())
        self.assertTrue(errs)
        _, errs = ex.validate_item(item(status="review_key", doubt_reason="x", also_defensible=["banana"]), target())
        self.assertTrue(errs)

    def test_ready_with_another_defensible_option_is_downgraded_to_review(self):
        clean, errs = ex.validate_item(item(also_defensible=["denote"]), target())
        self.assertEqual(errs, [])
        self.assertEqual(clean["status"], "review_key")

    def test_not_an_object_or_bad_status(self):
        for bad in (None, "x", [], {"id": 1}, item(status="maybe")):
            self.assertTrue(ex.validate_item(bad, target())[1])


class BuildTests(unittest.TestCase):
    def prompt_fn(self, kb, chunk, errors):
        return "|".join(str(t["id"]) for t in chunk) + "#" + str(sorted(k for k, v in errors.items() if v))

    def make_targets(self, n):
        ts = []
        for i in range(1, n + 1):
            t = copy.deepcopy(target())
            t["id"] = i
            t["qv"] = f"qv{i}"
            ts.append(t)
        return ts

    def test_chunks_and_independent_failures(self):
        def ask(prompt):
            ids = [int(x) for x in prompt.split("#")[0].split("|")]
            return json.dumps({"items": [item(id=i) for i in ids if i != 3]})          # câu 3 luôn thiếu mục

        res = ex.build(ask, "KB", self.make_targets(6), self.prompt_fn)
        self.assertEqual(res["status"]["3"], "unavailable")
        self.assertEqual(res["status"]["1"], "ready")
        self.assertEqual(res["status"]["6"], "ready")
        self.assertNotIn("3", res["texts"])

    def test_one_chunk_raising_does_not_lose_the_other_chunks(self):
        def ask(prompt):
            ids = [int(x) for x in prompt.split("#")[0].split("|")]
            if 1 in ids:
                raise RuntimeError("boom")
            return json.dumps({"items": [item(id=i) for i in ids]})

        res = ex.build(ask, "KB", self.make_targets(8), self.prompt_fn)
        self.assertEqual(res["status"]["1"], "unavailable")
        self.assertEqual(res["status"]["8"], "ready")

    def test_cache_hit_skips_ai_and_flagged_skips_ai(self):
        calls = []
        ts = self.make_targets(3)
        cache = {ex.cache_key(ts[0]): "- cached"}
        res = ex.build(lambda p: calls.append(p) or '{"items": []}', "KB", ts, self.prompt_fn, flagged_qvs={"qv2"},
                       cache_get=cache.get, cache_put=cache.__setitem__)
        self.assertEqual(res["texts"]["1"], "- cached")
        self.assertEqual(res["status"]["2"], "under_review")
        self.assertFalse(any("2" in p.split("#")[0].split("|") for p in calls))
        self.assertEqual(res["status"]["3"], "unavailable")

    def test_ready_results_are_cached_and_review_results_are_not(self):
        cache = {}
        ts = self.make_targets(2)

        def ask(prompt):
            return json.dumps({"items": [item(id=1), item(id=2, status="review_key", doubt_reason="r", also_defensible=["denote"])]})

        res = ex.build(ask, "KB", ts, self.prompt_fn, cache_get=cache.get, cache_put=cache.__setitem__)
        self.assertEqual(len(cache), 1)
        self.assertEqual(res["status"], {"1": "ready", "2": "under_review"})
        self.assertEqual(res["flagged"][0][0], "qv2")
        self.assertIn("2", res["partial"])
        self.assertEqual(res["doubts"]["2"]["also_defensible"], ["denote"])

    def test_retry_only_failed_items_with_their_reasons_then_succeeds(self):
        prompts = []

        def ask(prompt):
            prompts.append(prompt)
            ids = [int(x) for x in prompt.split("#")[0].split("|")]
            first = len(prompts) == 1
            return json.dumps({"items": [item(id=i, evidence=["not in sentence"]) if (first and i == 2) else item(id=i) for i in ids]})

        res = ex.build(ask, "KB", self.make_targets(3), self.prompt_fn)
        self.assertEqual(res["status"], {"1": "ready", "2": "ready", "3": "ready"})
        self.assertEqual(len(prompts), 2)
        self.assertEqual(prompts[1].split("#")[0], "2")


if __name__ == "__main__":
    unittest.main()
