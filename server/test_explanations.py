"""Kiểm thử mô-đun lời giải (explanations.py): ba phần, giới hạn từ, kiểm từng mục AI trả về, tô đậm, các phương án còn lại,
vòng viết lại và lượt rà nội dung. Dữ liệu giả lập, không gọi AI."""

import copy
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import engine_prompts as ep  # noqa: E402
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


def words(n, w="từ"):
    return " ".join([w] * n)


def item(**kw):
    base = {"id": 1, "status": "ready", "evidence": ["seems to ___ that someone accessed the account"],
            "key_clue_vi": "Cảnh báo chỉ gợi khả năng có người truy cập, chưa xác nhận; imply diễn tả điều được gợi ra gián tiếp.",
            "contrast_option": "denote",
            "contrast_vi": "denote báo một nghĩa đã xác định, còn ở đây cảnh báo mới chỉ gợi khả năng.",
            "example_en": "The padlock icon denotes a locked account.", "example_vi": "Biểu tượng ổ khóa biểu thị tài khoản bị khóa.",
            "translation_vi": "Cảnh báo đăng nhập đáng ngờ, dường như gợi ý có người truy cập tài khoản, đã dẫn tới một cuộc điều tra.",
            "translation_over_cap": False,
            "others": [{"option": "infer", "note": "infer là người đọc tự suy ra, còn ở đây cảnh báo là chủ thể gợi ra."},
                       {"option": "refer", "note": "refer cần có đối tượng được nhắc tới, câu này không có."}],
            "emphasis": [{"in": "stem", "text": "seems to"}, {"in": "clue", "text": "gợi khả năng"}],
            "doubt_reason": None, "also_defensible": []}
    base.update(kw)
    return base


class WordCountTests(unittest.TestCase):
    def test_counts_space_separated_units_and_ignores_format_symbols(self):
        self.assertEqual(ex.word_count("  một   hai\nba  "), 3)
        self.assertEqual(ex.word_count("«seems to ___ that» — **ý chính**"), 5)       # bỏ «», ___, —, **
        self.assertEqual(ex.word_count(""), 0)
        self.assertEqual(ex.word_count(None), 0)


class TargetTests(unittest.TestCase):
    def test_mode_choice_and_key_come_from_the_server_not_from_ai_text(self):
        t = target("wrong", "denote")
        self.assertEqual((t["mode"], t["options"][t["selected_index"]], t["options"][t["key_index"]]), ("wrong", "denote", "imply"))
        self.assertEqual(target("correct")["mode"], "correct")
        u = target("unanswered")
        self.assertEqual((u["mode"], u["selected_index"]), ("unanswered", None))

    def test_cache_key_depends_on_version_key_choice_and_format(self):
        a, b, c = target("wrong", "denote"), target("wrong", "infer"), target("correct")
        self.assertNotEqual(ex.cache_key(a), ex.cache_key(b))
        self.assertNotEqual(ex.cache_key(a), ex.cache_key(c))
        self.assertNotEqual(ex.cache_key(a), ex.cache_key(dict(a, key_sig="other")))
        self.assertTrue(ex.cache_key(a)[3].endswith("|" + ex.FORMAT))       # lời giải bản cũ không bị dùng lại


class ThreePartTests(unittest.TestCase):
    def test_wrong_answer_has_three_parts_in_order_with_students_choice(self):
        t = target("wrong", "denote")
        clean, errs = ex.validate_item(item(), t)
        self.assertEqual(errs, [])
        text = ex.compose(clean, t)
        i1, i2, i3 = (text.index(f"**{x}:**") for x in ("Chìa khóa nhận biết", "Phân biệt từ gây nhiễu", "Dịch nghĩa"))
        self.assertTrue(i1 < i2 < i3)
        self.assertIn("Em đã chọn «denote».", text)
        self.assertNotIn("em chọn từ này vì", text)
        self.assertIn("Ví dụ: The padlock icon", text)

    def test_correct_answer_uses_neutral_label_and_never_blames(self):
        t = target("correct")
        clean, errs = ex.validate_item(item(), t)
        self.assertEqual(errs, [])
        text = ex.compose(clean, t)
        self.assertIn("Dễ nhầm với «denote».", text)
        self.assertNotIn("Em đã chọn", text)
        self.assertNotIn("nắm vững", text)

    def test_unanswered_never_assigns_a_choice(self):
        t = target("unanswered")
        clean, errs = ex.validate_item(item(), t)
        self.assertEqual(errs, [])
        text = ex.compose(clean, t)
        self.assertIn("Dễ nhầm với «denote».", text)
        self.assertNotIn("Em đã chọn", text)

    def test_correct_answer_may_skip_contrast_and_then_all_other_options_are_listed(self):
        t = target("correct")
        raw = item(contrast_option=None, contrast_vi="", example_en=None, example_vi=None,
                   others=[{"option": o, "note": f"{o} không khớp cách gợi ý gián tiếp ở đây."} for o in ("denote", "infer", "refer")])
        clean, errs = ex.validate_item(raw, t)
        self.assertEqual(errs, [])
        text = ex.compose(clean, t)
        self.assertNotIn("Phân biệt từ gây nhiễu", text)
        self.assertEqual(text.count("**A. denote:**") + text.count("**B. infer:**") + text.count("**C. refer:**"), 3)

    def test_contrast_must_be_the_students_own_choice_for_wrong_answers(self):
        _, errs = ex.validate_item(item(contrast_option="infer"), target("wrong", "denote"))
        self.assertTrue(any("đúng lựa chọn của học sinh" in e for e in errs))
        t = target("wrong", "infer")
        raw = item(contrast_option="infer", contrast_vi="infer là người quan sát suy ra điều gì từ dấu hiệu, imply là dấu hiệu gợi ra",
                   others=[{"option": "denote", "note": "denote gán một nghĩa cố định cho ký hiệu."},
                           {"option": "refer", "note": "refer cần đối tượng được nhắc tới."}])
        clean, errs = ex.validate_item(raw, t)
        self.assertEqual(errs, [])
        self.assertIn("Em đã chọn «infer».", ex.compose(clean, t))

    def test_contrast_cannot_be_the_key_or_a_made_up_word(self):
        for bad in ("imply", "banana", ""):
            _, errs = ex.validate_item(item(contrast_option=bad), target("wrong", "denote"))
            self.assertTrue(errs, bad)

    def test_evidence_must_be_verbatim_from_the_sentence(self):
        _, errs = ex.validate_item(item(evidence=["someone hacked the account"]), target())
        self.assertTrue(any("không có nguyên văn" in e for e in errs))
        for bad in ([], ["a", "b", "c"], "", None):
            self.assertTrue(ex.validate_item(item(evidence=bad), target())[1])

    def test_clue_is_required_and_markdown_symbols_from_ai_are_stripped(self):
        _, errs = ex.validate_item(item(key_clue_vi=""), target())
        self.assertTrue(any("key_clue_vi" in e for e in errs))
        clean, errs = ex.validate_item(item(key_clue_vi="**Gợi** khả năng chứ chưa xác nhận điều gì cả"), target())
        self.assertEqual(errs, [])
        self.assertNotIn("**Gợi**", clean["key_clue"])

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
        self.assertNotIn("Ví dụ:", ex.compose(clean, target()))

    def test_review_key_status_requires_reason_and_yields_partial_text_only(self):
        raw = item(status="review_key", doubt_reason="chi tiết chưa loại được denote", also_defensible=["denote"])
        clean, errs = ex.validate_item(raw, target())
        self.assertEqual(errs, [])
        self.assertEqual(clean["status"], "review_key")
        partial = ex.compose_partial(clean)
        self.assertIn("Chìa khóa nhận biết", partial)
        self.assertNotIn("Dịch nghĩa", partial)
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


class LengthTests(unittest.TestCase):
    def test_each_part_over_its_cap_is_sent_back_not_truncated(self):
        cases = (("key_clue_vi", words(51), "key_clue_vi", 50), ("contrast_vi", words(56), "contrast_vi", 55),
                 ("translation_vi", words(71), "translation_vi", 70))
        for field, val, label, cap in cases:
            _, errs = ex.validate_item(item(**{field: val}), target())
            self.assertTrue(any(label in e and f"tối đa {cap}" in e for e in errs), (field, errs))

    def test_total_over_135_is_rejected_even_when_each_part_fits(self):
        raw = item(key_clue_vi=words(40), contrast_vi=words(48), translation_vi=words(52), example_en=None, example_vi=None)
        _, errs = ex.validate_item(raw, target())          # 40+7 + 48 + 52 = 147 > 135, nhưng không phần nào vượt trần riêng
        self.assertTrue(any("tổng" in e and "135" in e for e in errs), errs)

    def test_caps_are_ceilings_not_minimums(self):
        raw = item(key_clue_vi="Chỉ gợi khả năng.", contrast_vi="denote nói điều đã chắc chắn.", example_en=None, example_vi=None,
                   translation_vi="Cảnh báo dường như gợi ý có người truy cập.")
        clean, errs = ex.validate_item(raw, target())
        self.assertEqual(errs, [])
        self.assertLess(sum(clean["words"].values()), 40)

    def test_other_option_note_cap_is_25_words(self):
        raw = item(others=[{"option": "infer", "note": words(31)}, {"option": "refer", "note": "refer cần đối tượng được nhắc tới."}])
        _, errs = ex.validate_item(raw, target())
        self.assertTrue(any("tối đa 30" in e for e in errs))

    def test_long_sentence_may_take_a_recorded_translation_exception(self):
        long_sent = "The investigation team, " + words(40, "carefully") + " reviewed whether the alert seems to ___ that someone accessed the account."
        t = dict(target(), sentence=long_sent)
        raw = item(translation_vi=words(85), translation_over_cap=True, key_clue_vi="Cảnh báo chỉ gợi khả năng có người truy cập.",
                   contrast_vi="denote báo nghĩa đã xác định.", example_en=None, example_vi=None)
        clean, errs = ex.validate_item(raw, t)
        self.assertEqual(errs, [])
        self.assertEqual(clean["exceptions"], ["translation_over_cap"])
        _, errs = ex.validate_item(item(translation_vi=words(85), translation_over_cap=True), target())      # câu ngắn: không có ngoại lệ
        self.assertTrue(errs)
        _, errs = ex.validate_item(dict(raw, translation_vi=words(105)), t)                                  # quá trần cứng
        self.assertTrue(errs)


class RepeatAndOthersTests(unittest.TestCase):
    def test_same_sentence_in_two_parts_is_flagged(self):
        same = "Cảnh báo chỉ gợi khả năng có người truy cập chứ chưa xác nhận điều gì cả."
        _, errs = ex.validate_item(item(key_clue_vi=same, contrast_vi=same, example_en=None, example_vi=None), target())
        self.assertTrue(any("lặp nguyên văn" in e for e in errs), errs)

    def test_rephrased_repetition_is_not_judged_by_code(self):
        raw = item(contrast_vi="Từ này nhấn mạnh kết quả nên hợp với kết quả của sự việc.",
                   key_clue_vi="Câu nói tới kết quả, vì vậy từ nhấn mạnh kết quả là hợp lý ở đây.")
        _, errs = ex.validate_item(raw, target())
        self.assertFalse(any("lặp nguyên văn" in e for e in errs))          # việc đó của lượt AI rà nội dung

    def test_others_must_cover_every_remaining_option_once(self):
        t = target()
        _, errs = ex.validate_item(item(others=[{"option": "infer", "note": "ghi chú"}]), t)
        self.assertTrue(any("thiếu phương án" in e and "refer" in e for e in errs))
        _, errs = ex.validate_item(item(others=[{"option": "infer", "note": "a"}, {"option": "infer", "note": "b"},
                                                {"option": "refer", "note": "c"}]), t)
        self.assertTrue(any("lặp" in e for e in errs))
        _, errs = ex.validate_item(item(others=[{"option": "banana", "note": "x"}, {"option": "infer", "note": "a"},
                                                {"option": "refer", "note": "c"}]), t)
        self.assertTrue(any("không thuộc câu" in e for e in errs))
        _, errs = ex.validate_item(item(others="không phải danh sách"), t)
        self.assertTrue(errs)

    def test_key_and_contrast_need_no_own_line_and_expanded_order_matches_what_the_student_saw(self):
        t = target()
        raw = item(others=[{"option": "imply", "note": "khóa, bỏ qua"}, {"option": "infer", "note": "ghi chú B"},
                           {"option": "refer", "note": "ghi chú C"}])
        clean, errs = ex.validate_item(raw, t)
        self.assertEqual(errs, [])
        rows = ex.split_text(ex.compose(clean, t))["others"]
        self.assertEqual([r.split(":**")[0] for r in rows], ["- **A. denote", "- **B. infer", "- **C. refer"])
        self.assertIn("Đã giải thích ở trên.", rows[0])
        self.assertFalse(any("imply" in r for r in rows))

    def test_changing_the_students_choice_changes_only_the_comparison_part(self):
        a = ex.compose(ex.validate_item(item(), target("wrong", "denote"))[0], target("wrong", "denote"))
        raw = item(contrast_option="infer", contrast_vi="infer là người đọc tự suy ra, imply là chính cảnh báo gợi ra.",
                   others=[{"option": "denote", "note": "denote gán nghĩa cố định cho ký hiệu."},
                           {"option": "refer", "note": "refer cần đối tượng được nhắc tới."}])
        b = ex.compose(ex.validate_item(raw, target("wrong", "infer"))[0], target("wrong", "infer"))
        self.assertIn("Em đã chọn «denote».", a)
        self.assertIn("Em đã chọn «infer».", b)
        self.assertEqual(ex.split_text(a)["main"].splitlines()[0], ex.split_text(b)["main"].splitlines()[0])


class EmphasisTests(unittest.TestCase):
    def test_valid_spans_are_marked_once_in_the_right_source(self):
        t = target()
        clean, errs = ex.validate_item(item(), t)
        self.assertEqual(errs, [])
        text = ex.compose(clean, t)
        self.assertEqual(text.count("**gợi khả năng**"), 1)
        self.assertEqual(ex.split_text(text)["stem"], ["seems to"])

    def test_span_not_in_its_source_is_dropped_without_failing_the_item(self):
        t = target()
        clean, errs = ex.validate_item(item(emphasis=[{"in": "stem", "text": "has accessed"}, {"in": "clue", "text": "không có trong lời giải"},
                                                      {"in": "contrast", "text": "báo một nghĩa đã xác định"}]), t)
        self.assertEqual(errs, [])
        self.assertEqual(clean["stem_emphasis"], [])
        self.assertEqual(len(clean["emphasis_errors"]), 2)
        self.assertIn("**báo một nghĩa đã xác định**", ex.compose(clean, t))

    def test_limits_two_stem_spans_one_per_part_and_no_whole_part_or_long_span(self):
        t = target()
        em = [{"in": "stem", "text": "suspicious"}, {"in": "stem", "text": "login alert"}, {"in": "stem", "text": "triggered"},
              {"in": "clue", "text": "gợi khả năng"}, {"in": "clue", "text": "gián tiếp"},
              {"in": "translation", "text": words(9)}]
        clean, _ = ex.validate_item(item(emphasis=em), t)
        self.assertEqual(clean["stem_emphasis"], ["suspicious", "login alert"])
        self.assertEqual(ex.compose(clean, t).count("**gợi khả năng**"), 1)
        self.assertNotIn("**gián tiếp**", ex.compose(clean, t))
        self.assertGreaterEqual(len(clean["emphasis_errors"]), 3)

    def test_html_or_markdown_inside_a_span_is_rejected(self):
        clean, _ = ex.validate_item(item(emphasis=[{"in": "clue", "text": "<b>gợi</b>"}, {"in": "stem", "text": "se*ems"}]), target())
        self.assertEqual(clean["stem_emphasis"], [])
        self.assertNotIn("<b>", ex.compose(clean, target()))

    def test_malformed_emphasis_never_breaks_the_item(self):
        for bad in ("x", {"a": 1}, [None, 3, {"in": "stem"}], None, []):
            clean, errs = ex.validate_item(item(emphasis=bad), target())
            self.assertEqual(errs, [], bad)
            self.assertEqual(clean["stem_emphasis"], [])


class SplitTests(unittest.TestCase):
    def test_roundtrip_and_legacy_text(self):
        t = target()
        text = ex.compose(ex.validate_item(item(), t)[0], t)
        parts = ex.split_text(text)
        self.assertEqual(len(parts["main"].splitlines()), 3)
        self.assertEqual(len(parts["others"]), 3)
        legacy = "- **Dấu hiệu trong đề:** «x» — y\n- **Dịch nghĩa:** z"
        old = ex.split_text(legacy)
        self.assertEqual((len(old["main"].splitlines()), old["others"], old["stem"]), (2, [], []))


class PromptTests(unittest.TestCase):
    def test_prompt_states_caps_sections_and_carries_retry_info(self):
        t = dict(target("wrong", "denote"), _prev={"id": 1, "key_clue_vi": "bản trước"})
        p = ep.explanation_task([t], {1: ["key_clue_vi dài 62 từ, tối đa 50"]})
        for needle in ("tối đa 50 từ", "tối đa 55 từ", "tối đa 70 từ", "tối đa 135 từ", "tối đa 30 từ", "CHÌA KHÓA NHẬN BIẾT", "PHÂN BIỆT TỪ GÂY NHIỄU",
                       "DỊCH NGHĨA", "bản trước", "key_clue_vi dài 62 từ", "SAI: học sinh chọn \"denote\""):
            self.assertIn(needle.lower().replace("chìa khóa nhận biết", "chìa khóa nhận biết"), p.lower(), needle)

    def test_review_prompt_lists_the_six_criteria_and_gives_no_key_authority(self):
        t = target()
        pairs = [{"target": t, "text": "- **Dịch nghĩa:** x", "clean": {}}]
        p = ep.explanation_review_task(pairs)
        for code in ("weak_clue", "wrong_distractor", "translation_drift", "redundant", "unnatural", "contradiction"):
            self.assertIn(code, p)
        self.assertIn("KHÔNG tự đổi khóa", p)


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

    def test_too_long_is_rewritten_with_the_reason_and_the_previous_version(self):
        prompts = []

        def prompt_fn(kb, chunk, errors):
            prompts.append((sorted(k for k, v in errors.items() if v), [bool(t.get("_prev")) for t in chunk], [t["id"] for t in chunk]))
            return "x"

        def ask(prompt):
            ids = prompts[-1][2]
            first = len(prompts) == 1
            return json.dumps({"items": [item(id=i, key_clue_vi=words(75)) if (first and i == 2) else item(id=i) for i in ids]})

        res = ex.build(ask, "KB", self.make_targets(3), prompt_fn)
        self.assertEqual(res["status"], {"1": "ready", "2": "ready", "3": "ready"})
        self.assertEqual(len(prompts), 2)
        self.assertEqual(prompts[1][2], [2])                  # chỉ viết lại câu lỗi
        self.assertEqual(prompts[1][0], [2])
        self.assertEqual(prompts[1][1], [True])               # kèm bản trước để giữ phần đã đạt

    def test_still_too_long_after_two_rewrites_is_unavailable_never_truncated(self):
        def ask(prompt):
            return json.dumps({"items": [item(id=1, key_clue_vi=words(95))]})

        res = ex.build(ask, "KB", self.make_targets(1), self.prompt_fn)
        self.assertEqual(res["status"]["1"], "unavailable")
        self.assertNotIn("1", res["texts"])

    def test_content_review_rejects_repetition_then_accepts_the_rewrite(self):
        calls = {"gen": 0, "rev": 0}

        def ask(prompt):
            if prompt.startswith("R|"):
                calls["rev"] += 1
                ids = [int(x) for x in prompt[2:].split("|")]
                bad = calls["rev"] == 1
                return json.dumps({"items": [{"id": i, "ok": not bad, "issues": [{"part": "contrast", "code": "redundant",
                                                                                 "note": "lặp ý phần 1"}] if bad else []} for i in ids]})
            calls["gen"] += 1
            ids = [int(x) for x in prompt.split("#")[0].split("|")]
            return json.dumps({"items": [item(id=i) for i in ids]})

        cache = {}
        res = ex.build(ask, "KB", self.make_targets(2), self.prompt_fn, cache_get=cache.get, cache_put=cache.__setitem__,
                       review_prompt_fn=lambda kb, pairs: "R|" + "|".join(str(p["target"]["id"]) for p in pairs))
        self.assertEqual(res["status"], {"1": "ready", "2": "ready"})
        self.assertEqual((calls["gen"], calls["rev"]), (2, 2))
        self.assertEqual(len(cache), 2)

    def test_content_review_error_text_reaches_the_rewrite_prompt(self):
        seen = []

        def prompt_fn(kb, chunk, errors):
            seen.append(dict(errors))
            return "|".join(str(t["id"]) for t in chunk)

        state = {"rev": 0}

        def ask(prompt):
            if prompt.startswith("R|"):
                state["rev"] += 1
                return json.dumps({"items": [{"id": 1, "ok": state["rev"] > 1, "issues": [{"part": "clue", "code": "weak_clue",
                                                                                          "note": "dấu hiệu đúng với cả bốn lựa chọn"}]}]})
            return json.dumps({"items": [item(id=1)]})

        ex.build(ask, "KB", self.make_targets(1), prompt_fn, review_prompt_fn=lambda kb, pairs: "R|1")
        self.assertIn("đúng với cả bốn lựa chọn", " ".join(seen[1][1]))
        self.assertIn("weak_clue", " ".join(seen[1][1]))

    def test_content_review_key_doubt_goes_to_the_existing_flag_path_without_changing_anything_else(self):
        def ask(prompt):
            if prompt.startswith("R|"):
                return json.dumps({"items": [{"id": 1, "ok": True, "issues": [], "key_doubt": True, "doubt_reason": "refer cũng hợp ngữ cảnh"}]})
            return json.dumps({"items": [item(id=1)]})

        cache = {}
        res = ex.build(ask, "KB", self.make_targets(1), self.prompt_fn, cache_get=cache.get, cache_put=cache.__setitem__,
                       review_prompt_fn=lambda kb, pairs: "R|1")
        self.assertEqual(res["status"]["1"], "under_review")
        self.assertEqual(res["flagged"], [("qv1", "refer cũng hợp ngữ cảnh")])
        self.assertNotIn("1", res["texts"])
        self.assertEqual(cache, {})

    def test_review_call_failure_does_not_block_a_code_validated_explanation(self):
        def ask(prompt):
            if prompt.startswith("R|"):
                raise RuntimeError("review down")
            return json.dumps({"items": [item(id=1)]})

        res = ex.build(ask, "KB", self.make_targets(1), self.prompt_fn, review_prompt_fn=lambda kb, pairs: "R|1")
        self.assertEqual(res["status"]["1"], "ready")

    def test_exceptions_and_emphasis_errors_are_reported(self):
        def ask(prompt):
            return json.dumps({"items": [item(id=1, emphasis=[{"in": "stem", "text": "nope"}])]})

        res = ex.build(ask, "KB", self.make_targets(1), self.prompt_fn)
        self.assertIn("1", res["emphasis_errors"])
        self.assertEqual(res["status"]["1"], "ready")


if __name__ == "__main__":
    unittest.main()
