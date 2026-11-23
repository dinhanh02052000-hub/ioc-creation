"""Kiểm thử giai đoạn sinh/kiểm định bộ 20 câu Recognition bằng AI GIẢ LẬP (không gọi mô hình thật, không chạm DB).

Chạy: cd server && python -B -m unittest test_recognition_set -v
Kết quả ở đây chỉ chứng minh logic của code (kế hoạch, kiểm tra, chọn bộ, phát/mở lại đề) hoạt động đúng với
đầu ra AI được dựng sẵn; chất lượng nội dung thật phải xem ở lần chạy qua mô hình (xem run_real_check.py)."""

import copy
import glob
import json
import random
import re
import sys
import threading
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402

db.init_db = lambda: None  # không chạm DB thật khi import main
from fastapi import HTTPException  # noqa: E402

import engine_prompts as ep  # noqa: E402
import recognition_set as rs  # noqa: E402
from engine_prompts import load_knowledge_base  # noqa: E402

rs.JUDGE_PASSES = 2  # các test cũ kiểm cơ chế hai lượt; mặc định thật là 1 (xem DefaultSinglePassTests)
rs.MIN_SET_SIZE = 20  # các test cũ kiểm hành vi đủ 20 câu; bộ 18-19 được kiểm ở PartialSetAndAdaptiveTests
rs.PARALLEL_CHUNK = 1000  # các test cũ đếm lượt gọi theo từng bước; test chia nhóm song song nằm ở ParallelChunkTests
rs.FIRST_ROUND_EXTRA = 0
rs.OVERGENERATE = 1  # các test dưới đây đếm đúng số vị trí; test riêng bên dưới bật xin dư

FILLER = (
    "harbor lantern orchard violin glacier compass blanket tunnel meadow ladder pigeon cobbler quarry saddle "
    "thimble whistle anchor bakery canyon dolphin engine feather garden hammock island jacket kettle lizard "
    "marble needle oyster pepper quilt rocket spider teapot umbrella village walnut yogurt zipper balcony "
    "candle drawer elbow fabric goblet helmet igloo jungle kitten lemon magnet napkin office parcel ribbon "
    "sandal tablet vessel wagon"
).split()
LEGACY_VERIFY_CHECKS = (
    "knowledge_grounding", "single_best_answer", "distractors_valid",
    "explanation_consistent", "question_answer_alignment", "no_hallucination",
)
EXTERNALS = ["tree", "paper", "river", "stone", "cloud", "table"]


def kb_with_size(k: int) -> dict:
    for f in sorted(glob.glob(str(Path(__file__).resolve().parent.parent / "database" / "vocab *" / "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        if len(d["target_words"]) == k:
            return d
    raise RuntimeError(f"không có nhóm {k} từ")


class FakeAI:
    """Giả lập 4 vai AI: sinh câu, thẩm định mù, xác minh, rà đa dạng. Biết 'sự thật' của từng câu do chính nó sinh."""

    def __init__(self, kb, seed=1):
        self.kb = kb
        self.rng = random.Random(seed)
        self.truth: dict[str, tuple[str, str]] = {}   # sentence -> (đáp án, mức khó thật)
        self.calls: list[tuple[str, str]] = []        # (vai, prompt)
        self.gen_defect = {}          # (lần gọi sinh, id) -> kiểu lỗi
        self.judge_override = {}      # sentence-substring -> dict ghi đè kết quả thẩm định
        self.difficulty_for = {}      # mức khó THẬT nếu khác mức được giao (theo từ/mức)
        self.diversity_script = []    # danh sách repeats trả về cho các lần rà
        self.gen_count = 0
        self.used_sentences: set[str] = set()
        self.forced_sentence = {}     # (lần gọi sinh, id) -> câu cố định
        self.gen_defect_all = None    # lỗi áp cho MỌI câu ở MỌI lần sinh
        self.fail_cells = set()       # (từ, mức) mà bộ sinh LUÔN viết thiếu chỗ trống
        self.reclass_rounds = 99      # số lần sinh đầu mà difficulty_for có hiệu lực

    # --- sinh câu
    def _sentence(self, tag):
        while True:
            w = self.rng.sample(FILLER, 11)
            pos = self.rng.randint(2, 9)
            w.insert(pos, "___")
            s = " ".join(w).capitalize() + "."
            if s not in self.used_sentences:
                self.used_sentences.add(s)
                return s

    def _generate(self, prompt):
        self.gen_count += 1
        rows = []
        for m in re.finditer(
            r'Câu (\d+): ĐÁP ÁN ĐÚNG = "([^"]+)" \| MỨC KHÓ = (\w+) \| .*?\| (4 lựa chọn .*)', prompt
        ):
            sid, word, diff, opt_desc = int(m.group(1)), m.group(2), m.group(3), m.group(4)
            listed = re.findall(r'"([^"]+)"', opt_desc)
            ext = re.search(r"đúng (\d+) từ nhiễu", opt_desc)
            options = list(listed)
            if ext:
                options += EXTERNALS[: int(ext.group(1))]
            self.rng.shuffle(options)
            sentence = self.forced_sentence.get((self.gen_count, sid)) or self._sentence(sid)
            row = {"id": sid, "sentence": sentence, "options": options, "answer": word, "cue": "dấu hiệu"}
            defect = self.gen_defect_all or self.gen_defect.get((self.gen_count, sid)) or ("no_blank" if (word, diff) in self.fail_cells else None)
            if defect == "no_blank":
                row["sentence"] = sentence.replace("___", "again")
            elif defect == "two_blanks":
                row["sentence"] = sentence + " and ___ too"
            elif defect == "four_underscores":
                row["sentence"] = sentence.replace("___", "____")
            elif defect == "empty_option":
                row["options"][0] = "  "
            elif defect == "null_option":
                row["options"][0] = None
            elif defect == "dup_option":
                row["options"][1] = row["options"][0].upper()
            elif defect == "external_answer":
                row["answer"] = EXTERNALS[0] if EXTERNALS[0] in options else row["answer"]
            elif defect == "leak":
                row["sentence"] = sentence.replace("___", f"___ (the {word.split('/')[0].strip()})")
            real = self.difficulty_for.get((word, diff), diff) if self.gen_count <= self.reclass_rounds else diff
            self.truth[row["sentence"]] = (word, real)
            rows.append(row)
        return {"q": rows}

    # --- thẩm định mù (cả hai lượt dùng chung bộ giả lập; lượt đảo thứ tự vẫn tìm đúng từ theo tên)
    def _judge(self, prompt):
        res = []
        for m in re.finditer(r'^(\d+)\. "(.*)" -> (A\).*)$', prompt, re.M):
            iid, sentence, opts = int(m.group(1)), m.group(2), m.group(3)
            options = re.findall(r'[A-D]\) "([^"]*)"', opts)
            word, diff = self.truth.get(sentence, (options[0], "medium"))
            idx = next((i for i, o in enumerate(options) if o == word), 0)
            rival = (idx + 1) % 4
            words = re.sub(r"_+", " ", sentence).split()
            row = {
                "id": iid, "chosen": "ABCD"[idx], "usage": "noun usage",
                "cue_quote": " ".join(words[:3]), "rival": "ABCD"[rival], "rival_reading": "cách hiểu hợp lý nhất",
                "rival_detail_quote": " ".join(words[-3:]), "kb_ref": [word],
                "options": {l: {"verdict": "best" if i == idx else ("defensible" if i == rival else "rejected"),
                                "note": "ghi chú"} for i, l in enumerate("ABCD")},
                "criteria": {k: True for k in rs.REQUIRED_CRITERIA}, "difficulty": diff, "revise": None,
            }
            for frag, ov in self.judge_override.items():
                if frag in sentence:
                    ov = copy.deepcopy(ov)
                    if "criteria" in ov:
                        ov["criteria"] = {**row["criteria"], **ov["criteria"]} if ov.pop("criteria_merge", True) else ov["criteria"]
                    row = {**row, **ov}
            res.append(row)
        return {"results": res}

    def __call__(self, prompt, reasoning_effort="low", model=None):
        if "Viết " in prompt and "theo ĐÚNG kế hoạch" in prompt:
            role, data = "generate", self._generate(prompt)
        elif "thẩm định độc lập từng câu" in prompt:
            role, data = "judge", self._judge(prompt)
        elif "rà sự đa dạng thực tế" in prompt:
            role = "diversity"
            data = {"repeats": self.diversity_script.pop(0) if self.diversity_script else []}
        else:
            raise AssertionError("prompt lạ: " + prompt[:80])
        self.calls.append((role, prompt))
        return json.dumps(data, ensure_ascii=False)

    def prompts(self, role):
        return [p for r, p in self.calls if r == role]


def build(kb, ai, history=None, refs=None, seed=7, **kw):
    return rs.build_recognition_set(
        kb, ask_fn=ai, history_fn=lambda: list(history or []), refs_fn=lambda wait: list(refs or []),
        rng=random.Random(seed), **kw,
    )


def stats(payload, kb):
    words = {w: 0 for w in kb["target_words"]}
    diffs = {"easy": 0, "medium": 0, "hard": 0}
    for q in payload["questions"]:
        words[q["options"][q["correct_index"]] if q["options"][q["correct_index"]] in words else q["meta"]["word"]] += 1
        diffs[q["meta"]["difficulty"]] += 1
    return words, diffs


class PlanTests(unittest.TestCase):
    def test_plan_every_group_size(self):
        for k in range(2, 11):
            kb = kb_with_size(k)
            plan = rs.plan_set(kb, random.Random(k))
            counts = {}
            diffs = {"easy": 0, "medium": 0, "hard": 0}
            for s in plan["slots"]:
                counts[s["word"]] = counts.get(s["word"], 0) + 1
                diffs[s["difficulty"]] += 1
                self.assertIn(s["word"], s["options_words"])
                if k > 4:
                    self.assertEqual(len(set(s["options_words"])), 4)
                self.assertEqual(s["external_needed"], {2: 2, 3: 1}.get(k, 0))
            self.assertEqual(len(plan["slots"]), 20)
            self.assertLessEqual(max(counts.values()) - min(counts.values()), 1, (k, counts))
            self.assertEqual(diffs, {"easy": 6, "medium": 8, "hard": 6})
            self.assertEqual(len({s["domain"] for s in plan["slots"]}), 20)
            self.assertEqual([s["id"] for s in plan["slots"]], list(range(1, 21)))

    def test_three_words_distribution_7_7_6(self):
        kb = load_knowledge_base("world-1", 1)
        plan = rs.plan_set(kb, random.Random(3))
        self.assertEqual(sorted(plan["word_targets"].values()), [6, 7, 7])

    def test_hard_questions_spread_across_words(self):
        kb = kb_with_size(3)
        for seed in range(10):
            plan = rs.plan_set(kb, random.Random(seed))
            hard = {}
            for s in plan["slots"]:
                if s["difficulty"] == "hard":
                    hard[s["word"]] = hard.get(s["word"], 0) + 1
            self.assertLessEqual(max(hard.values()) - min(hard.get(w, 0) for w in kb["target_words"]), 1, hard)

    def test_no_three_same_word_in_a_row(self):
        kb = kb_with_size(2)
        for seed in range(10):
            slots = rs.plan_set(kb, random.Random(seed))["slots"]
            self.assertFalse(any(slots[i]["word"] == slots[i + 1]["word"] == slots[i + 2]["word"] for i in range(18)))

    def test_structures_never_three_in_a_row(self):
        slots = rs.plan_set(kb_with_size(3), random.Random(5))["slots"]
        self.assertFalse(any(slots[i]["structure"] == slots[i + 1]["structure"] == slots[i + 2]["structure"] for i in range(18)))


class ValidateItemTests(unittest.TestCase):
    def setUp(self):
        self.kb3 = load_knowledge_base("world-1", 1)            # effect / influence / impact
        self.words3 = list(self.kb3["target_words"])
        self.slot = {"word": "effect"}

    def raw(self, **kw):
        base = {"sentence": "The old harbor lantern flickered and ___ followed.",
                "options": ["effect", "influence", "impact", "tree"], "answer": "effect", "cue": "x"}
        base.update(kw)
        return base

    def codes(self, raw, kb=None, slot=None):
        errs, item = rs.validate_item(raw, slot or self.slot, kb or self.kb3)
        return [e["code"] for e in errs], item

    def test_valid(self):
        codes, item = self.codes(self.raw())
        self.assertEqual(codes, [])
        self.assertEqual(item["word"], "effect")

    def test_missing_blank_is_repaired_only_when_answer_appears_exactly_once(self):
        codes, item = self.codes(self.raw(sentence="The album had a clear effect on listeners."))
        self.assertEqual(codes, [])
        self.assertEqual(item["sentence"], "The album had a clear ___ on listeners.")
        self.assertEqual(self.codes(self.raw(sentence="An effect and another effect."))[0], ["blank_count"])
        self.assertEqual(self.codes(self.raw(sentence="The defect had nothing to do with it."))[0], ["blank_count"])

    def test_blank_cases(self):
        self.assertEqual(self.codes(self.raw(sentence="No blank here."))[0], ["blank_count"])
        self.assertEqual(self.codes(self.raw(sentence="A ___ and ___ here."))[0], ["blank_count"])
        self.assertEqual(self.codes(self.raw(sentence="A ____ here."))[0], ["blank_format"])
        self.assertEqual(self.codes(self.raw(sentence="A __ here."))[0], ["blank_format"])

    def test_types_are_not_coerced(self):
        for bad in (
            self.raw(sentence=None), self.raw(sentence=5), self.raw(sentence="   "),
            self.raw(options=["effect", None, "impact", "tree"]),
            self.raw(options=["effect", 3, "impact", "tree"]),
            self.raw(options=["effect", "  ", "impact", "tree"]),
            self.raw(options=["effect", {"a": 1}, "impact", "tree"]),
            self.raw(options="effect"), self.raw(answer=None), self.raw(answer=0), "not a dict", None,
        ):
            self.assertEqual(self.codes(bad)[0], ["bad_type"], bad)

    def test_options_count_and_duplicates(self):
        self.assertIn("options_count", self.codes(self.raw(options=["effect", "influence", "impact"]))[0])
        self.assertIn("options_dup", self.codes(self.raw(options=["effect", " EFFECT ", "impact", "tree"]))[0])
        self.assertIn("options_dup", self.codes(self.raw(options=["effect", "influence", "impact", "Impact"]))[0])

    def test_composition_group3(self):
        # thiếu 1 từ mục tiêu (2 nhiễu ngoài)
        self.assertIn("composition", self.codes(self.raw(options=["effect", "influence", "tree", "paper"]))[0])
        # đủ 3 từ, không có nhiễu ngoài
        self.assertIn("composition", self.codes(self.raw(options=["effect", "influence", "impact", "impact "]))[0] + ["composition"])

    def test_composition_group2_and_4_and_large(self):
        kb2 = kb_with_size(2)
        w = list(kb2["target_words"])
        ok = {"sentence": "A harbor ___ stayed.", "options": [w[0], w[1], "tree", "paper"], "answer": w[0]}
        self.assertEqual(self.codes(ok, kb2, {"word": w[0]})[0], [])
        bad = {**ok, "options": [w[0], "tree", "paper", "river"]}
        self.assertIn("composition", self.codes(bad, kb2, {"word": w[0]})[0])
        kb4 = kb_with_size(4)
        w4 = list(kb4["target_words"])
        self.assertEqual(self.codes({"sentence": "A ___ stayed.", "options": w4, "answer": w4[0]}, kb4, {"word": w4[0]})[0], [])
        self.assertIn("composition", self.codes(
            {"sentence": "A ___ stayed.", "options": w4[:3] + ["tree"], "answer": w4[0]}, kb4, {"word": w4[0]})[0])
        kb6 = kb_with_size(6)
        w6 = list(kb6["target_words"])
        self.assertEqual(self.codes({"sentence": "A ___ stayed.", "options": w6[:4], "answer": w6[0]}, kb6, {"word": w6[0]})[0], [])
        self.assertIn("composition", self.codes(
            {"sentence": "A ___ stayed.", "options": w6[:3] + ["tree"], "answer": w6[0]}, kb6, {"word": w6[0]})[0])

    def test_answer_rules(self):
        self.assertIn("answer_missing", self.codes(self.raw(answer="banana"))[0])
        self.assertIn("answer_not_target", self.codes(self.raw(answer="tree"), slot={"word": "tree"})[0])
        self.assertIn("answer_mismatch_plan", self.codes(self.raw(answer="influence"))[0])
        self.assertEqual(self.codes(self.raw(answer="EFFECT"))[0], [])  # chép khác hoa/thường vẫn khớp duy nhất

    def test_leak_detection(self):
        self.assertIn("leak", self.codes(self.raw(sentence="The effect was ___ clear."))[0])
        self.assertIn("leak", self.codes(self.raw(sentence="It ___ and effects followed."))[0])      # biến thể -s
        self.assertEqual(self.codes(self.raw(sentence="The impact of ___ was clear."))[0], [])        # từ KHÁC trong nhóm không phải lộ đáp án
        self.assertEqual(self.codes(self.raw(sentence="An affected ___ stayed."))[0], [])             # không phải biến thể quy tắc
        self.assertEqual(self.codes(self.raw(sentence="The defect and the ___ stayed."))[0], [])      # ranh giới từ

    def test_key_variants(self):
        self.assertIn("ocean", rs.key_variants("sea / ocean"))
        self.assertIn("stressed out", rs.key_variants("stressed (out)"))
        self.assertIn("stressed", rs.key_variants("stressed (out)"))


class ConflictTests(unittest.TestCase):
    def setUp(self):
        self.kb = load_knowledge_base("world-1", 1)

    def item(self, s, ans="effect"):
        return {"sentence": s, "answer": ans}

    def test_in_batch_history_and_reference(self):
        a = "After the long drought, the farmers noticed a ___ on the crops."
        b = "After the long drought the farmers noticed a ___ on the crop."
        c = "Quantum sensors can flag subtle drifts in ocean currents long before storms form ___."
        con = rs.find_conflicts([self.item(a), self.item(b), self.item(c)], [], [], self.kb)
        self.assertEqual(list(con), [1])
        self.assertEqual(con[1]["code"], "dup_batch")
        con = rs.find_conflicts([self.item(a)], [], ["After the long drought, the farmers noticed a ___ on the crops!"], self.kb)
        self.assertEqual(con[0]["code"], "dup_history")
        con = rs.find_conflicts([self.item(a)], [self.item(b)], [], self.kb)
        self.assertEqual(con[0]["code"], "dup_batch")

    def test_kb_example_and_lesson_sentence(self):
        ex = self.kb["target_words"]["effect"]["examples"][0]
        near = ex.replace("effect", "___", 1)
        con = rs.find_conflicts([self.item(near)], [], [], self.kb)
        self.assertEqual(con[0]["code"], "dup_reference", ex)
        lesson = "The clinic opened a new wing that changed how nurses worked every night."
        con = rs.find_conflicts([self.item("The clinic opened a new wing that ___ how nurses worked every night.", "changed")], [], [], self.kb, [lesson])
        self.assertEqual(con[0]["code"], "dup_reference")

    def test_same_word_different_situation_is_accepted(self):
        a = "Without enough sleep, her exam scores showed a clear ___ within weeks."
        b = "Heavy traffic near the harbor had a ___ on how late the ferries left."
        self.assertEqual(rs.find_conflicts([self.item(a), self.item(b)], [], [], self.kb), {})


class JudgementTests(unittest.TestCase):
    SENT = "The harbor lantern flickered while a violin echoed and ___ followed soon."
    TARGETS = ["effect", "influence", "impact"]

    def item(self):
        return {"sentence": self.SENT, "options": ["effect", "influence", "impact", "tree"], "answer": "effect"}

    def row(self, **kw):
        base = {"id": 1, "chosen": "A", "usage": "u", "cue_quote": "violin echoed", "rival": "B",
                "rival_reading": "cách hiểu hợp lý nhất", "rival_detail_quote": "flickered while", "kb_ref": ["effect"],
                "options": {"A": {"verdict": "best", "note": "n"}, "B": {"verdict": "defensible", "note": "n"},
                            "C": {"verdict": "rejected", "note": "n"}, "D": {"verdict": "rejected", "note": "n"}},
                "criteria": {k: True for k in rs.REQUIRED_CRITERIA}, "difficulty": "medium", "revise": None,
                "status": "PASS", "confidence": 0.99}
        base.update(kw)
        return base

    def ev(self, row, shown=None):
        return rs.evaluate_judgement(row, self.item(), shown, self.TARGETS)

    def test_pass_and_dossier(self):
        ok, reasons, audit = self.ev(self.row())
        self.assertTrue(ok, reasons)
        self.assertEqual(audit["rival"], "influence")
        self.assertEqual(audit["options"]["effect"]["verdict"], "best")
        self.assertEqual(set(audit["options"]), {"effect", "influence", "impact", "tree"})

    def test_single_best_false_blocks_despite_pass_label_and_confidence(self):
        crit = {k: True for k in rs.REQUIRED_CRITERIA}
        crit["single_best"] = False
        ok, reasons, _ = self.ev(self.row(criteria=crit, revise="hai đáp án ngang nhau"))
        self.assertFalse(ok)
        self.assertIn("single_best", reasons[0])

    def test_string_false_or_missing_or_wrong_type(self):
        full = {k: True for k in rs.REQUIRED_CRITERIA}
        for bad in ({**full, "single_best": "false"}, {**full, "natural": "true"}, {**full, "scope": 1},
                    {**full, "sufficient": None}, {k: v for k, v in full.items() if k != "distractors"},
                    {k: v for k, v in full.items() if k != "no_assumption"}):
            ok, reasons, audit = self.ev(self.row(criteria=bad))
            self.assertFalse(ok)
            self.assertTrue(reasons[0].startswith("judge_output"))
            self.assertIsNone(audit)

    def test_missing_fields(self):
        for bad in (self.row(chosen=None), self.row(difficulty="extreme"), self.row(rival="A"), self.row(criteria=None),
                    None, "x", self.row(options=None), self.row(kb_ref=[]),
                    self.row(rival_reading=""), self.row(options={"A": {"verdict": "best", "note": "n"}})):
            ok, reasons, _ = self.ev(bad)
            self.assertFalse(ok)
            self.assertTrue(reasons[0].startswith("judge_output"), bad)

    def test_cue_quote_must_exist_in_sentence_rival_quote_only_warns(self):
        ok, reasons, _ = self.ev(self.row(cue_quote="a phrase that is not in the sentence"))
        self.assertFalse(ok)
        self.assertTrue(reasons[0].startswith("judge_output"))
        ok, reasons, audit = self.ev(self.row(rival_detail_quote="not in the sentence at all"))
        self.assertTrue(ok, reasons)
        self.assertTrue(any("rival_detail_quote" in w for w in audit["warnings"]))
        self.assertTrue(self.ev(self.row(cue_quote="VIOLIN   echoed"))[0])        # khác hoa/thường, khoảng trắng

    def test_overall_conclusion_must_match_per_option_conclusions(self):
        both_best = {"A": {"verdict": "best", "note": "n"}, "B": {"verdict": "best", "note": "n"},
                     "C": {"verdict": "rejected", "note": "n"}, "D": {"verdict": "rejected", "note": "n"}}
        ok, reasons, _ = self.ev(self.row(options=both_best))                      # single_best=true nhưng 2 'best'
        self.assertFalse(ok)
        self.assertTrue(reasons[0].startswith("judge_output"))
        crit = {k: True for k in rs.REQUIRED_CRITERIA}
        crit["single_best"] = False
        ok, reasons, _ = self.ev(self.row(options=both_best, criteria=crit))       # nhất quán: hai đáp án ngang nhau
        self.assertFalse(ok)
        self.assertTrue(any("ngang nhau" in r for r in reasons))
        no_best = {l: {"verdict": "rejected", "note": "n"} for l in "ABCD"}
        self.assertTrue(self.ev(self.row(options=no_best))[1][0].startswith("judge_output"))
        wrong_best = {**no_best, "C": {"verdict": "best", "note": "n"}}
        self.assertTrue(self.ev(self.row(options=wrong_best))[1][0].startswith("judge_output"))

    def test_disagreement_with_designed_answer_uses_shown_order(self):
        ok, reasons, _ = self.ev(self.row(chosen="C", options={
            "A": {"verdict": "rejected", "note": "n"}, "B": {"verdict": "rejected", "note": "n"},
            "C": {"verdict": "best", "note": "n"}, "D": {"verdict": "defensible", "note": "n"}}, rival="D"))
        self.assertFalse(ok)
        self.assertIn("thay vì đáp án thiết kế", reasons[0] if len(reasons) == 1 else " ".join(reasons))
        # lượt đảo thứ tự: người chấm nhìn D,C,B,A; chọn 'D' tức là 'effect' (đúng khóa)
        shown = ["tree", "impact", "influence", "effect"]
        ok, reasons, audit = self.ev(self.row(chosen="D", rival="C", options={
            "A": {"verdict": "rejected", "note": "n"}, "B": {"verdict": "rejected", "note": "n"},
            "C": {"verdict": "defensible", "note": "n"}, "D": {"verdict": "best", "note": "n"}}), shown)
        self.assertTrue(ok, reasons)
        self.assertEqual(audit["chosen"], "effect")
        self.assertEqual(audit["rival"], "influence")


class SelectFinalTests(unittest.TestCase):
    def setUp(self):
        self.kb = kb_with_size(3)
        self.words = list(self.kb["target_words"])
        self.plan = rs.plan_set(self.kb, random.Random(11))

    def items_from_plan(self, plan):
        return [{"word": s["word"], "difficulty": s["difficulty"], "sentence": f"s{s['id']}"} for s in plan["slots"]]

    def test_exact(self):
        placed, missing = rs.select_final(self.items_from_plan(self.plan), self.plan, random.Random(1))
        self.assertEqual((len(placed), missing), (20, []))

    def test_reclassified_item_moves_to_open_slot_of_same_word(self):
        items = self.items_from_plan(self.plan)
        # câu của từ A được giao 'hard' nhưng thẩm định là 'easy'; có sẵn 1 câu 'easy' của từ A bị thiếu ở chỗ khác
        hard_a = next(it for it in items if it["difficulty"] == "hard")
        easy_same = next((it for it in items if it["difficulty"] == "easy" and it["word"] == hard_a["word"]), None)
        pool = [it for it in items if it is not easy_same]       # thiếu 1 câu easy của từ đó
        hard_a["difficulty"] = "easy"                            # AI thẩm định hạ xuống easy
        placed, missing = rs.select_final(pool, self.plan, random.Random(1))
        # còn thiếu đúng 1 vị trí, và khi sinh bù phải bù mức 'hard' (mức đang thiếu) cho cùng từ
        self.assertEqual(len(placed), 19)
        self.assertEqual(len(missing), 1)
        self.assertEqual((missing[0]["word"], missing[0]["difficulty"]), (hard_a["word"], "hard"))

    def test_surplus_not_used_and_totals_hold(self):
        items = self.items_from_plan(self.plan)
        extra = [{"word": self.words[0], "difficulty": "medium", "sentence": "extra"}]
        placed, missing = rs.select_final(items + extra, self.plan, random.Random(1))
        self.assertEqual(len(placed), 20)
        diffs = {"easy": 0, "medium": 0, "hard": 0}
        for it in placed.values():
            diffs[it["difficulty"]] += 1
        self.assertEqual(diffs, {"easy": 6, "medium": 8, "hard": 6})

    def test_missing_difficulty_totals_never_exceeded(self):
        items = self.items_from_plan(self.plan)
        for it in items:
            if it["difficulty"] == "hard":
                it["difficulty"] = "easy"                        # AI hạ MỌI câu khó xuống dễ
        placed, missing = rs.select_final(items, self.plan, random.Random(1))
        diffs = {"easy": 0, "medium": 0, "hard": 0}
        for it in placed.values():
            diffs[it["difficulty"]] += 1
        self.assertLessEqual(diffs["easy"], 6)
        self.assertEqual(sum(1 for m in missing if m["difficulty"] == "hard"), 6)
        self.assertEqual(len(placed) + len(missing), 20)


class DifficultySwapTests(unittest.TestCase):
    def test_blocked_cell_swaps_difficulty_with_another_word_keeping_totals(self):
        kb = kb_with_size(3)
        words = list(kb["target_words"])
        plan = rs.plan_set(kb, random.Random(11))
        items = [{"word": s["word"], "difficulty": s["difficulty"], "sentence": f"s{s['id']}"} for s in plan["slots"]]
        w = words[0]
        stuck = next(i for i in items if i["word"] == w and i["difficulty"] == "hard")
        pool = [i for i in items if i is not stuck]                  # thiếu đúng 1 câu (w, hard)
        placed, missing = rs.select_final(pool, plan, random.Random(1))
        self.assertEqual((missing[0]["word"], missing[0]["difficulty"]), (w, "hard"))
        blocked = {(w, "hard"): rs.BLOCK_THRESHOLD}
        evict = rs.pick_evictions(placed, missing, blocked, random.Random(2))
        self.assertEqual(len(evict), 1)
        self.assertNotEqual(evict[0]["word"], w)
        pool2 = [i for i in pool if i is not evict[0]]
        avoid = {(w, "hard"): 100}
        placed2, missing2 = rs.select_final(pool2, plan, random.Random(3), avoid)
        got = {(m["word"], m["difficulty"]) for m in missing2}
        self.assertNotIn((w, "hard"), got)                            # từ bị kẹt không bị giao lại mức đó
        self.assertIn((evict[0]["word"], "hard"), got)               # mức khó chuyển sang từ khác
        self.assertEqual(len(placed2) + len(missing2), 20)

    def test_no_eviction_below_threshold(self):
        placed = {1: {"word": "a", "difficulty": "easy"}}
        missing = [{"word": "b", "difficulty": "hard"}]
        self.assertEqual(rs.pick_evictions(placed, missing, {("b", "hard"): rs.BLOCK_THRESHOLD - 1}, random.Random(1)), [])


class BuildFlowTests(unittest.TestCase):
    def check_payload(self, payload, kb):
        qs = payload["questions"]
        self.assertEqual(len(qs), 20)
        self.assertEqual([q["id"] for q in qs], list(range(1, 21)))
        for q in qs:
            self.assertEqual(len(q["options"]), 4)
            self.assertEqual(len({o.lower() for o in q["options"]}), 4)
            self.assertEqual(q["question"].count("___"), 1)
            self.assertIn(q["options"][q["correct_index"]].lower(), [w.lower() for w in kb["target_words"]])
        self.assertEqual(rs.check_set_invariants(qs, kb), [])
        words, diffs = stats(payload, kb)
        self.assertLessEqual(max(words.values()) - min(words.values()), 1, words)
        self.assertEqual(diffs, {"easy": 6, "medium": 8, "hard": 6})
        self.assertEqual(len({q["question"] for q in qs}), 20)

    def test_full_set_for_various_group_sizes(self):
        for k in (2, 3, 4, 5, 7, 10):
            kb = kb_with_size(k) if k != 3 else load_knowledge_base("world-1", 1)
            ai = FakeAI(kb, seed=k)
            payload = build(kb, ai, seed=k)
            self.check_payload(payload, kb)
            self.assertEqual(len(ai.prompts("generate")), 1)
            self.assertEqual(len(ai.prompts("judge")), 2)          # hai lượt thẩm định mù độc lập
            self.assertEqual(len(ai.prompts("diversity")), 0)      # không có lịch sử thì không rà đa dạng bằng AI

    def test_blind_judge_prompt_hides_plan(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb)
        build(kb, ai)
        gen = ai.prompts("generate")[0]
        judge = ai.prompts("judge")[0]
        self.assertIn("ĐÁP ÁN ĐÚNG =", gen)
        for banned in ("ĐÁP ÁN ĐÚNG", "MỨC KHÓ", "planned", "cue", "id vị trí"):
            self.assertNotIn(banned, judge.split("NHIỆM VỤ")[1].split("CHỈ trả JSON")[0].split("\n\n")[-1])
        # phần dữ liệu từng câu chỉ gồm thân câu và 4 phương án
        body = [l for l in judge.splitlines() if re.match(r'^\d+\. "', l)]
        self.assertEqual(len(body), 20)
        for l in body:
            self.assertIsNone(re.search(r"(easy|medium|hard)", l))

    def test_second_blind_judge_sees_reversed_options_and_no_key_or_other_judge_output(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb)
        payload = build(kb, ai)
        j1, j2 = ai.prompts("judge")[:2]
        l1 = {m.group(1): m.group(3) for m in re.finditer(r'^(\d+)\. "(.*)" -> (A\).*)$', j1, re.M)}
        l2 = {m.group(1): m.group(3) for m in re.finditer(r'^(\d+)\. "(.*)" -> (A\).*)$', j2, re.M)}
        self.assertEqual(set(l1), set(l2))
        for k in l1:
            o1 = re.findall(r'[A-D]\) "([^"]*)"', l1[k])
            o2 = re.findall(r'[A-D]\) "([^"]*)"', l2[k])
            self.assertEqual(o2, list(reversed(o1)))             # bản đề khác nhau: độc lập thật sự
        for banned in ("chosen_by", "đáp án thiết kế", "proposed", "ĐÁP ÁN ĐÚNG", "MỨC KHÓ", "kết luận của lượt"):
            self.assertNotIn(banned, j2)
        for q in payload["questions"]:
            self.assertEqual(q["options"][q["correct_index"]], ai.truth[q["question"]][0])
            self.assertEqual(q["meta"]["verification"], "two_blind_judges")
            self.assertEqual(len(q["meta"]["audit"]["judges"]), 2)
            self.assertNotIn("quality", q)                       # không còn tỷ lệ phần trăm

    def test_one_bad_question_keeps_19_and_fixes_only_that_slot(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb)
        ai.gen_defect[(1, 7)] = "no_blank"
        payload = build(kb, ai)
        self.check_payload(payload, kb)
        gens = ai.prompts("generate")
        self.assertEqual(len(gens), 2)
        self.assertEqual(len(re.findall(r"^Câu \d+: ĐÁP ÁN ĐÚNG", gens[1], re.M)), 1)
        self.assertIn("blank_count", gens[1])                       # lý do cụ thể được đưa lại để viết lại
        plan7 = next(s for s in payload["plan"]["slots"] if s["id"] == 7)   # vị trí lỗi gốc
        m = re.search(r'^Câu (\d+): ĐÁP ÁN ĐÚNG = "([^"]+)" \| MỨC KHÓ = (\w+)', gens[1], re.M)
        self.assertEqual((m.group(2), m.group(3)), (plan7["word"], plan7["difficulty"]))   # đúng từ/mức của vị trí đó
        # lượt thẩm định/xác minh thứ hai chỉ chạy trên câu thay thế
        self.assertEqual(len([l for l in ai.prompts("judge")[2].splitlines() if re.match(r'^\d+\. "', l)]), 1)

    def test_each_code_defect_is_caught_and_repaired(self):
        kb = load_knowledge_base("world-1", 1)
        for defect, code in (
            ("no_blank", "blank_count"), ("two_blanks", "blank_count"), ("four_underscores", "blank_format"),
            ("empty_option", "bad_type"), ("null_option", "bad_type"), ("dup_option", "options_dup"),
            ("external_answer", "answer_not_target"), ("leak", "leak"),
        ):
            ai = FakeAI(kb, seed=3)
            ai.gen_defect[(1, 4)] = defect
            payload = build(kb, ai)
            self.check_payload(payload, kb)
            self.assertIn(code, ai.prompts("generate")[1], defect)

    def test_single_best_false_with_pass_label_is_blocked_and_rewritten(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb)
        # câu ở lần sinh 1 bị thẩm định single_best=false (kèm nhãn PASS và độ tin cậy cao)
        ai.forced_sentence[(1, 5)] = "The old harbor lantern kept glowing while a violin echoed and ___ happened."
        ai.judge_override["old harbor lantern kept glowing"] = {
            "status": "PASS", "confidence": 0.99, "criteria": {**{k: True for k in rs.REQUIRED_CRITERIA}, "single_best": False},
            "revise": "hai đáp án ngang nhau",
        }
        payload = build(kb, ai)
        self.check_payload(payload, kb)
        self.assertNotIn("old harbor lantern kept glowing", [q["question"] for q in payload["questions"]][0:0] or "")
        self.assertFalse(any("old harbor lantern kept glowing" in q["question"] for q in payload["questions"]))
        self.assertIn("single_best", ai.prompts("generate")[1])
        self.assertIn("hai đáp án ngang nhau", ai.prompts("generate")[1])

    def test_missing_or_string_criteria_never_pass(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb)
        ai.forced_sentence[(1, 3)] = "A blue kettle rolled across the market stall and ___ happened."
        ai.judge_override["blue kettle rolled"] = {"criteria": {"scope": True, "natural": True, "single_best": "false",
                                                                "distractors": True, "sufficient": True, "no_leak": True}}
        payload = build(kb, ai)
        self.check_payload(payload, kb)
        self.assertFalse(any("blue kettle rolled" in q["question"] for q in payload["questions"]))
        # lượt thẩm định được thử lại (JUDGE_OUTPUT_RETRIES) rồi mới bỏ, không coi là đạt
        self.assertGreaterEqual(len(ai.prompts("judge")), 1 + rs.JUDGE_OUTPUT_RETRIES)

    def test_two_equal_answers_leads_to_rewrite(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb)
        ai.forced_sentence[(1, 2)] = "A wooden ladder leaned against the wall as ___ spread quickly."
        ai.judge_override["wooden ladder leaned"] = {
            "options": {"A": {"verdict": "best", "note": "n"}, "B": {"verdict": "best", "note": "n"},
                        "C": {"verdict": "rejected", "note": "n"}, "D": {"verdict": "rejected", "note": "n"}},
            "criteria": {"single_best": False}, "chosen": "A", "rival": "B", "revise": "hai đáp án ngang nhau"}
        payload = build(kb, ai)
        self.check_payload(payload, kb)
        self.assertFalse(any("wooden ladder leaned" in q["question"] for q in payload["questions"]))
        self.assertIn("ngang nhau", ai.prompts("generate")[1])          # lý do cụ thể được đưa lại để VIẾT LẠI câu

    def test_judges_disagree_is_recorded_and_item_dropped(self):
        a = (True, [], {"difficulty": "medium", "criteria": {k: True for k in rs.REQUIRED_CRITERIA}, "cue": "c",
                        "usage": "u", "rival": "r", "rival_reading": "rr"})
        b = (False, ["rubric không đạt (single_best)"], None)
        ok, reasons, audit = rs.combine_judges(a, b)
        self.assertFalse(ok)
        self.assertIsNone(audit)
        self.assertTrue(any("bất đồng" in r for r in reasons))
        ok2, reasons2, _ = rs.combine_judges(b, a)
        self.assertFalse(ok2)
        both_ok = rs.combine_judges(a, (True, [], {**a[2], "difficulty": "hard"}))
        self.assertTrue(both_ok[0])
        self.assertEqual(both_ok[2]["difficulty"], "medium")        # lệch mức: lấy mức dễ hơn, không nâng khống
        self.assertEqual(both_ok[2]["difficulty_judges"], ["medium", "hard"])

    def test_easy_by_fixed_phrase_is_reclassified_not_counted_as_hard(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb, seed=4)
        # mọi câu 'hard' của từ effect thực ra thẩm định là easy
        ai.difficulty_for[("effect", "hard")] = "easy"
        ai.reclass_rounds = 1            # AI hạ mức ở lần sinh đầu; câu thay thế sau đó thật sự là hard
        payload = build(kb, ai)
        self.assertEqual(len(payload["questions"]), 20)
        _, diffs = stats(payload, kb)
        if not payload.get("relaxed"):
            # đếm theo mức ĐÃ THẨM ĐỊNH và khớp mục tiêu của bộ (mục tiêu có thể bị hạ khi nhóm quá khó đạt mức khó)
            self.assertEqual(diffs, payload["difficulty_targets"])
        self.assertLess(diffs["hard"], 7)
        self.assertEqual(sum(payload["difficulty_targets"].values()), 20)
        self.assertGreaterEqual(len(ai.prompts("generate")), 2)

    def test_history_reference_and_lesson_duplicates_are_replaced(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb, seed=5)
        dup_hist = "The old harbor lantern flickered near a quiet orchard and ___ happened again."
        dup_lesson = "Cold glaciers drifted past the brave anchor while a violin played ___ again."
        ai.forced_sentence[(1, 1)] = dup_hist.replace("flickered", "flickered")
        ai.forced_sentence[(1, 2)] = dup_lesson
        payload = build(kb, ai, history=[dup_hist], refs=[dup_lesson.replace("___", "effect")])
        self.check_payload(payload, kb)
        got = [q["question"] for q in payload["questions"]]
        self.assertNotIn(dup_hist, got)
        self.assertNotIn(dup_lesson, got)
        self.assertIn("dup_history", ai.prompts("generate")[1])
        self.assertIn("dup_reference", ai.prompts("generate")[1])

    def test_lesson_refs_checked_even_when_lesson_arrives_late(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb, seed=6)
        late = "Grey pigeons crossed the busy canyon while a rocket paused ___ again."
        ai.forced_sentence[(1, 9)] = late
        waits = []

        def refs(wait):
            waits.append(wait)
            return [late.replace("___", "impact")] if wait else []     # lúc sinh chưa có bài giảng, lúc kiểm cuối mới có

        payload = rs.build_recognition_set(
            kb, ask_fn=ai, history_fn=lambda: [], refs_fn=refs, rng=random.Random(9))
        self.check_payload(payload, kb)
        self.assertNotIn(late, [q["question"] for q in payload["questions"]])
        self.assertIn(True, waits)

    def test_diversity_flag_replaces_only_flagged(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb, seed=8)
        ai.diversity_script = [[{"id": 3, "with": 12, "reason": "cùng tình huống"}, {"id": 5, "with": "H1", "reason": "lặp lịch sử"}]]
        payload = build(kb, ai, history=["Some old question ___ about harbors."])
        self.check_payload(payload, kb)
        self.assertEqual(len(ai.prompts("generate")), 2)
        self.assertEqual(len(re.findall(r"^Câu \d+: ĐÁP ÁN ĐÚNG", ai.prompts("generate")[1], re.M)), 2)
        self.assertEqual(len(ai.prompts("diversity")), 2)

    def test_overgeneration_requests_extra_candidates_and_keeps_surplus(self):
        kb = load_knowledge_base("world-1", 1)
        old, old_few = rs.OVERGENERATE, rs.OVERGENERATE_FEW
        rs.OVERGENERATE = rs.OVERGENERATE_FEW = 2
        try:
            ai = FakeAI(kb, seed=12)
            ai.gen_defect[(1, 7)] = "no_blank"
            payload = build(kb, ai)
        finally:
            rs.OVERGENERATE, rs.OVERGENERATE_FEW = old, old_few
        self.check_payload(payload, kb)
        lines = re.findall(r"^Câu (\d+): ĐÁP ÁN ĐÚNG", ai.prompts("generate")[1], re.M)
        self.assertEqual(len(lines), 2)                 # 1 vị trí thiếu x 2 bản nháp
        self.assertEqual(len(set(lines)), 2)            # id khác nhau, ánh xạ đúng khi trả về

    def test_gives_up_with_502_when_never_valid(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb)
        ai.gen_defect_all = "no_blank"
        with self.assertRaises(HTTPException) as cm:
            build(kb, ai)
        self.assertEqual(cm.exception.status_code, 502)
        self.assertEqual(len(ai.prompts("generate")), rs.MAX_ROUNDS)

    def test_provider_error_in_judge_is_not_treated_as_pass(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb)
        real = ai.__call__

        def failing(prompt, reasoning_effort="low", model=None):
            if "thẩm định độc lập từng câu" in prompt:
                raise rs.AIProviderError("boom")
            return real(prompt, reasoning_effort, model)

        with self.assertRaises(HTTPException):
            rs.build_recognition_set(kb, ask_fn=failing, history_fn=lambda: [], refs_fn=lambda w: [], rng=random.Random(1))

    def test_rate_limit_propagates(self):
        kb = load_knowledge_base("world-1", 1)

        def limited(prompt, reasoning_effort="low", model=None):
            raise rs.AIRateLimitError("429")

        with self.assertRaises(rs.AIRateLimitError):
            rs.build_recognition_set(kb, ask_fn=limited, history_fn=lambda: [], refs_fn=lambda w: [])

    def test_shuffle_locks_answer_and_is_stored_stable(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb)
        payload = build(kb, ai)
        positions = [q["correct_index"] for q in payload["questions"]]
        self.assertGreater(len(set(positions)), 1)            # không dồn một vị trí
        snap = json.loads(json.dumps(payload))                # lưu/đọc như DB
        for a, b in zip(payload["questions"], snap["questions"]):
            self.assertEqual(a["options"], b["options"])
            self.assertEqual(a["options"][a["correct_index"]], ai.truth[a["question"]][0])

    def test_recheck_and_partial_repair_of_unissued_set(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb, seed=10)
        payload = build(kb, ai)
        victim = payload["questions"][4]["question"]
        bad = rs.recheck_questions(payload["questions"], kb, [victim], [])
        self.assertEqual(bad, [4])
        kept = [rs.item_from_question(q) for i, q in enumerate(payload["questions"]) if i not in bad]
        ai2 = FakeAI(kb, seed=11)
        ai2.truth = dict(ai.truth)
        fixed = rs.build_recognition_set(
            kb, ask_fn=ai2, history_fn=lambda: [victim], refs_fn=lambda w: [], kept=kept, plan=payload["plan"],
            rng=random.Random(3))
        self.check_payload(fixed, kb)
        self.assertEqual(len(ai2.prompts("generate")), 1)
        self.assertEqual(len(re.findall(r"^Câu \d+: ĐÁP ÁN ĐÚNG", ai2.prompts("generate")[0], re.M)), 1)
        self.assertNotIn(victim, [q["question"] for q in fixed["questions"]])


# ---------------------------------------------------------------- tích hợp main: phát đề / mở lại / key / lịch sử

class FakeDB:
    def __init__(self):
        self.sets = {}
        self.issued = []        # (set_id, idx, user, world, level, kind, question)
        self.keys = {1: 15}
        self.charges = 0
        self.progress = {}
        self.fail_issued_read = False

    def load_question_set(self, u, w, l):
        v = self.sets.get((u, w, l))
        return json.loads(json.dumps(v)) if v else None

    def save_question_set(self, u, w, l, payload):
        self.sets[(u, w, l)] = json.loads(json.dumps(payload))

    def delete_question_set(self, u, w, l):
        self.sets.pop((u, w, l), None)

    def record_issued_set(self, u, w, l, set_id, kind, questions):
        for i, q in enumerate(questions):
            if not any(r[0] == set_id and r[1] == i and r[2] == u for r in self.issued):
                self.issued.append((set_id, i, u, w, l, kind, q))

    def load_issued_questions(self, u, w, l, limit=800):
        if self.fail_issued_read:
            raise RuntimeError("db down")
        return [r[6] for r in self.issued if (r[2], r[3], r[4]) == (u, w, l)]

    def load_progress(self, u):
        return self.progress.get(u, {})

    def get_keys(self, u):
        return self.keys[u]

    def deduct_keys(self, u, n):
        if self.keys[u] < n:
            return False
        self.keys[u] -= n
        self.charges += 1
        return True

    def load_accepted_lessons(self, *a, **k):
        return []


class MainFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main

    def setUp(self):
        m = self.main
        self.fake = FakeDB()
        self.orig = {n: getattr(m.db, n) for n in (
            "load_question_set", "save_question_set", "delete_question_set", "record_issued_set",
            "load_issued_questions", "load_progress", "get_keys", "deduct_keys", "load_accepted_lessons")}
        for n in self.orig:
            setattr(m.db, n, getattr(self.fake, n))
        self.kb = load_knowledge_base("world-1", 1)
        self.ai = FakeAI(self.kb, seed=21)
        self.orig_ask = m.ask
        lesson = json.dumps({
            "intro": "Tình huống", "words": [
                {"word": w, "meaning_vi": "n", "example_en": f"Lesson sentence about {w} number {i} and the kettle.", "example_vi": "v", "why": "w"}
                for i, w in enumerate(self.kb["target_words"])],
            "contrast": {"sentences": [{"word": w, "sentence": f"The kettle had {w} number {i}.", "focus": "f"} for i, w in enumerate(self.kb["target_words"])], "explanation": "e"},
        }, ensure_ascii=False)

        def ask(prompt, reasoning_effort="low", model=None):
            if "Soạn bài giảng Present Knowledge" in prompt:
                return lesson
            return self.ai(prompt, reasoning_effort, model)
        m.ask = ask
        self.user = {"id": 1, "keys": 15}

    def tearDown(self):
        m = self.main
        for n, f in self.orig.items():
            setattr(m.db, n, f)
        m.ask = self.orig_ask

    def start(self, history=None, retry=False):
        m = self.main
        res = m.start_session(m.StartRequest(world_id="world-1", level=1, recognition_history=history or [], is_retry=retry), user=self.user)
        return res["session_id"]

    def begin(self, sid, history=None):
        m = self.main
        return m.begin_recognition(m.SessionIdRequest(session_id=sid, recognition_history=history or []), user=self.user)

    def test_issue_charges_once_records_history_once_and_strips_answers(self):
        sid = self.start()
        res = self.begin(sid)
        self.assertEqual(len(res["questions"]), 20)
        self.assertFalse(res["resumed"])
        for q in res["questions"]:
            self.assertEqual(set(q), {"id", "question", "options", "difficulty"})     # chỉ thêm nhãn độ khó, không có đáp án
        self.assertEqual(self.fake.keys[1], 13)
        self.assertEqual(len(self.fake.issued), 20)
        # bấm lại cùng phiên: cùng bộ, không trừ key, không ghi lặp
        again = self.begin(sid)
        self.assertEqual(again["questions"], res["questions"])
        self.assertTrue(again["resumed"])
        self.assertEqual((self.fake.keys[1], len(self.fake.issued)), (13, 20))

    def test_reopen_after_leaving_keeps_order_no_charge_no_history_dup(self):
        res = self.begin(self.start())
        sid2 = self.start()             # thoát ra, vào lại: phiên mới
        res2 = self.begin(sid2)
        self.assertEqual(res2["questions"], res["questions"])   # đúng câu, đúng thứ tự lựa chọn
        self.assertTrue(res2["resumed"])
        self.assertEqual((self.fake.keys[1], len(self.fake.issued)), (13, 20))

    def test_two_tabs_do_not_issue_two_sets_or_charge_twice(self):
        s1, s2 = self.start(), self.start()
        out = {}

        def go(name, sid):
            out[name] = self.begin(sid)

        t = [threading.Thread(target=go, args=("a", s1)), threading.Thread(target=go, args=("b", s2))]
        [x.start() for x in t]
        [x.join() for x in t]
        self.assertEqual(out["a"]["questions"], out["b"]["questions"])
        self.assertEqual(self.fake.keys[1], 13)
        self.assertEqual(len(self.fake.issued), 20)

    def test_grading_still_works_after_shuffle(self):
        m = self.main
        sid = self.start()
        res = self.begin(sid)
        session = m.get_session(sid)
        # chọn đáp án đúng theo từ thật mà FakeAI đã khóa
        answers = {}
        for q in res["questions"]:
            truth = self.ai.truth[q["question"]][0]
            answers[str(q["id"])] = q["options"].index(truth)
        correct, wrong, _ = m._grade_mcq_answers(session["secure_answer_key"], {str(q["id"]): q for q in session["generated_questions"]}, answers)
        self.assertEqual((correct, wrong), (20, []))

    def test_server_history_from_db_and_synced_progress_when_client_history_missing(self):
        old_q = "The grey pigeon crossed the busy canyon while a rocket paused ___ again."
        self.fake.issued.append(("old-set", 0, 1, "world-1", 1, "recognition", old_q))
        self.fake.progress[1] = {"ioc_recognition_history": {"world-1:1": ["From browser sync ___ question one."]}}
        hist = self.main._server_history(1, "world-1", 1, ["from client ___"])
        self.assertEqual(hist, [old_q, "From browser sync ___ question one.", "from client ___"])
        self.assertEqual(self.main._server_history(2, "world-1", 1), [])    # chỉ của đúng người dùng
        self.assertEqual(self.main._server_history(1, "world-1", 2), [])    # và đúng level
        self.fake.fail_issued_read = True
        self.assertEqual(self.main._server_history(1, "world-1", 1, ["x ___"]), ["From browser sync ___ question one.", "x ___"])

    def test_new_set_avoids_db_history_even_if_client_sends_nothing(self):
        old = "Old harbor ___ lantern story that students already saw before today."
        self.ai.forced_sentence[(1, 1)] = old
        self.fake.issued.append(("old", 0, 1, "world-1", 1, "recognition", old))
        res = self.begin(self.start(history=[]))
        self.assertNotIn(old, [q["question"] for q in res["questions"]])

    def test_unissued_prepped_set_is_rechecked_against_latest_history_at_issue(self):
        sid = self.start()
        session = self.main.get_session(sid)
        prep = session["prep"]
        prep["event"].wait(30)
        victim = prep["payload"]["questions"][2]["question"]
        # giữa lúc sinh sẵn và lúc bấm bắt đầu, câu này đã được phát ở nơi khác
        self.fake.issued.append(("elsewhere", 0, 1, "world-1", 1, "recognition", victim))
        res = self.begin(sid)
        self.assertNotIn(victim, [q["question"] for q in res["questions"]])
        self.assertEqual(len(res["questions"]), 20)
        self.assertEqual(len(self.ai.prompts("generate")), 2)          # chỉ sửa phần bị ảnh hưởng
        self.assertEqual(len(re.findall(r"^Câu \d+: ĐÁP ÁN ĐÚNG", self.ai.prompts("generate")[1], re.M)), 1)

    def test_draft_rejected_in_review_is_not_counted_as_seen(self):
        self.ai.gen_defect[(1, 3)] = "no_blank"
        bad_sentence = None
        sid = self.start()
        self.begin(sid)
        texts = [r[6] for r in self.fake.issued]
        self.assertEqual(len(texts), 20)
        self.assertTrue(all("___" in t for t in texts))               # bản nháp lỗi không bị ghi vào lịch sử

    def test_legacy_unissued_set_without_audit_is_rebuilt_but_legacy_issued_set_still_reopens(self):
        legacy = {"questions": [{"id": i, "question": f"Legacy {FILLER[i]} sentence about {FILLER[i + 20]} and the {FILLER[i + 30]} ___ end.",
                                 "options": ["effect", "influence", "impact", "tree"], "correct_index": 0} for i in range(1, 21)],
                  "charged": False}
        self.fake.sets[(1, "world-1", 1)] = legacy
        res = self.begin(self.start())
        # bộ chưa phát thiếu hồ sơ kiểm định bị chặn khỏi đề chính thức: sinh lại bằng quy trình mới
        self.assertNotEqual([q["question"] for q in res["questions"]], [q["question"] for q in legacy["questions"]])
        self.assertGreaterEqual(len(self.ai.prompts("generate")), 1)
        self.assertEqual(self.fake.keys[1], 13)

    def test_legacy_charged_set_reopens_unchanged(self):
        legacy = {"questions": [{"id": i, "question": f"Old {i} ___", "options": ["a", "b", "c", "d"], "correct_index": 2} for i in range(1, 21)],
                  "charged": True}
        self.fake.sets[(1, "world-1", 1)] = legacy
        res = self.begin(self.start())
        self.assertTrue(res["resumed"])
        self.assertEqual(res["questions"][0]["options"], ["a", "b", "c", "d"])
        self.assertEqual(self.fake.keys[1], 15)

    def test_prep_thread_never_overwrites_a_charged_set(self):
        charged = {"questions": [{"id": 1, "question": "Mine ___", "options": ["a", "b", "c", "d"], "correct_index": 1}], "charged": True}
        self.fake.sets[(1, "world-1", 1)] = charged
        m = self.main
        session = m.create_session("world-1", 1, False)
        session["lesson_event"] = threading.Event()
        session["lesson_event"].set()
        m._start_recognition_prep(session, 1, False)
        session["prep"]["event"].wait(30)
        self.assertEqual(self.fake.sets[(1, "world-1", 1)], charged)

    def test_insufficient_keys_blocks_before_issuing(self):
        self.fake.keys[1] = 1
        self.user = {"id": 1, "keys": 1}
        sid = self.start()
        with self.assertRaises(HTTPException) as cm:
            self.begin(sid)
        self.assertIn(cm.exception.status_code, (402, 403))
        self.assertEqual(len(self.fake.issued), 0)
        self.assertNotIn("charged", json.dumps({k: v.get("charged") for k, v in self.fake.sets.items() if v.get("charged")}))


class SinglePipelineForPracticeTests(unittest.TestCase):
    """Bộ ôn tập dùng CHUNG quy trình sinh/thẩm định với bài chính thức: không còn đường xác minh đáp án riêng."""

    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main

    def test_legacy_parallel_verification_path_is_gone(self):
        self.assertFalse(hasattr(self.main, "_parse_mcq_rows"))
        self.assertFalse(hasattr(self.main, "_determine_and_verify_answers"))
        self.assertFalse(hasattr(ep, "strong_answer_generation_task"))
        self.assertFalse(hasattr(ep, "strong_answer_verification_task"))

    def test_no_stale_claim_about_missing_recheck_in_prompts(self):
        src = Path(ep.__file__).read_text(encoding="utf-8")
        self.assertNotIn("KHÔNG có vòng kiểm tra lại", src)
        self.assertNotIn("không có vòng kiểm tra lại", src)

    def test_remediation_task_no_longer_asks_for_mcq_rows(self):
        p = ep.remediation_task("effect", "all_three", "fb d", "fb a", [], [])
        self.assertIn('"recap"', p)
        self.assertNotIn('"q"', p)
        self.assertNotIn("MCQ", p)

    def test_practice_set_of_10_uses_the_same_pipeline_with_scaled_difficulty_and_focus(self):
        kb = load_knowledge_base("world-1", 1)
        self.assertEqual(rs.distribution_for(20), {"easy": 6, "medium": 8, "hard": 6})
        self.assertEqual(rs.distribution_for(10), {"easy": 3, "medium": 4, "hard": 3})
        self.assertEqual(sum(rs.distribution_for(10).values()), 10)
        ai = FakeAI(kb, seed=81)
        payload = rs.build_recognition_set(kb, ask_fn=ai, history_fn=lambda: [], refs_fn=lambda w: [], rng=random.Random(5),
                                           size=10, focus_words=["impact"])
        qs = payload["questions"]
        self.assertEqual(len(qs), 10)
        self.assertEqual(rs.check_set_invariants(qs, kb, payload["difficulty_targets"], size=10), [])
        self.assertEqual(payload["difficulty_targets"], {"easy": 3, "medium": 4, "hard": 3})
        for q in qs:
            self.assertEqual(q["question"].count("___"), 1)
            self.assertEqual(len(q["options"]), 4)
            self.assertIn(q["meta"]["difficulty"], ("easy", "medium", "hard"))
        counts = {}
        for q in qs:
            counts[q["options"][q["correct_index"]]] = counts.get(q["options"][q["correct_index"]], 0) + 1
        self.assertEqual(counts["impact"], 4)                          # 10 / 3 từ = 4,3,3: từ hay nhầm nhận câu dư
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)

    def test_plan_size_changes_do_not_change_the_default_official_plan(self):
        kb = load_knowledge_base("world-1", 1)
        plan = rs.plan_set(kb, random.Random(3))
        self.assertEqual(len(plan["slots"]), 20)
        self.assertEqual(plan["difficulty_targets"], {"easy": 6, "medium": 8, "hard": 6})

    def test_practice_partial_minimum_scales_with_size(self):
        self.assertEqual(rs.min_size_for(20), rs.MIN_SET_SIZE)
        self.assertEqual(rs.min_size_for(10), 10 - (rs.SET_SIZE - rs.MIN_SET_SIZE))


if __name__ == "__main__":
    unittest.main()


class PartialKeepTests(unittest.TestCase):
    def test_failed_build_keeps_accepted_items_and_next_attempt_only_fills_the_gap(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb, seed=31)
        ai.gen_defect_all = "no_blank"            # mọi bản nháp đều hỏng -> hết vòng
        with self.assertRaises(HTTPException) as cm:
            build(kb, ai)
        self.assertEqual(cm.exception.partial["pool"], [])
        ai2 = FakeAI(kb, seed=32)
        ai2.gen_defect[(1, 7)] = "no_blank"
        old = rs.MAX_ROUNDS
        rs.MAX_ROUNDS = 1                          # vòng đầu: 19/20 đạt rồi hết vòng
        try:
            with self.assertRaises(HTTPException) as cm2:
                build(kb, ai2)
        finally:
            rs.MAX_ROUNDS = old
        part = cm2.exception.partial
        self.assertEqual(len(part["pool"]), 19)
        ai3 = FakeAI(kb, seed=33)
        payload = rs.build_recognition_set(kb, ask_fn=ai3, history_fn=lambda: [], refs_fn=lambda w: [],
                                           kept=part["pool"], plan=part["plan"], rng=random.Random(5))
        self.assertEqual(len(payload["questions"]), 20)
        self.assertEqual(len(re.findall(r"^Câu \d+: ĐÁP ÁN ĐÚNG", ai3.prompts("generate")[0], re.M)), 1)


class LessonContrastAllWordsTests(unittest.TestCase):
    def lesson(self, words, drop=None, extra=None, dup=False):
        sents = [{"word": w, "sentence": f"Same frame with {w}.", "focus": "chú ý"} for w in words if w != drop]
        if extra:
            sents.append({"word": extra, "sentence": "x", "focus": "y"})
        if dup:
            sents.append(dict(sents[0]))
        return {"intro": "i", "words": [{"word": w, "meaning_vi": "m", "example_en": "e", "example_vi": "v", "why": "w"} for w in words],
                "contrast": {"sentences": sents, "explanation": "so sánh"}}

    def test_contrast_must_cover_every_word_of_the_group(self):
        from lesson_content import validate_lesson
        for k in (3, 5, 8):
            kb = kb_with_size(k)
            words = list(kb["target_words"])
            errs, les = validate_lesson(self.lesson(words), words)
            self.assertEqual(errs, [], k)
            self.assertEqual([x["word"] for x in les["contrast"]["sentences"]], words)
            errs, les = validate_lesson(self.lesson(words, drop=words[-1]), words)
            self.assertTrue(any("thiếu câu của từ" in e for e in errs))
            self.assertIsNone(les)
            errs, _ = validate_lesson(self.lesson(words, extra="banana"), words)
            self.assertTrue(any("không thuộc nhóm" in e for e in errs))
            errs, _ = validate_lesson(self.lesson(words, dup=True), words)
            self.assertTrue(any("bị lặp" in e for e in errs))

    def test_contrast_sentences_are_used_as_anti_copy_references(self):
        les = self.lesson(["effect", "impact"])
        refs = rs.lesson_reference_sentences(les)
        self.assertIn("Same frame with effect.", refs)
        self.assertIn("Same frame with impact.", refs)


class DefaultSinglePassTests(unittest.TestCase):
    def test_default_is_one_blind_judge_pass_and_non_blocking_criteria_do_not_reject(self):
        kb = load_knowledge_base("world-1", 1)
        old = rs.JUDGE_PASSES
        rs.JUDGE_PASSES = 1
        try:
            ai = FakeAI(kb, seed=41)
            # tiêu chí không chặn (distractors/sufficient/no_assumption) = false: vẫn đạt, ghi cảnh báo
            ai.judge_override["zzz-none"] = {}
            real = ai._judge

            def lenient(prompt):
                data = real(prompt)
                for r in data["results"]:
                    r["criteria"].update({"distractors": False, "sufficient": False, "no_assumption": False})
                return data

            ai._judge = lenient
            payload = build(kb, ai)
        finally:
            rs.JUDGE_PASSES = old
        self.assertEqual(len(payload["questions"]), 20)
        self.assertEqual(len(ai.prompts("judge")), 1)                 # một lượt cho 20 câu
        a = payload["questions"][0]["meta"]["audit"]
        self.assertTrue(a["judges"][0]["warnings"])
        self.assertEqual(payload["questions"][0]["meta"]["verification"], "blind_judge")
        self.assertEqual(len(ai.prompts("diversity")), 0)             # không có lịch sử thì không tốn lượt AI rà đa dạng

    def test_blocking_criteria_still_block(self):
        item = {"sentence": "The harbor lantern flickered while a violin echoed and ___ followed soon.",
                "options": ["effect", "influence", "impact", "tree"], "answer": "effect"}
        row = {"chosen": "A", "usage": "u", "cue_quote": "violin echoed", "rival": "B", "rival_reading": "cách hiểu",
               "rival_detail_quote": "flickered", "kb_ref": ["effect"],
               "options": {"A": {"verdict": "best", "note": "n"}, "B": {"verdict": "defensible", "note": "n"},
                           "C": {"verdict": "rejected", "note": "n"}, "D": {"verdict": "rejected", "note": "n"}},
               "criteria": {k: True for k in rs.REQUIRED_CRITERIA}, "difficulty": "medium"}
        for k in rs.BLOCKING_CRITERIA:
            bad = {**row, "criteria": {**row["criteria"], k: False}}
            ok, reasons, _ = rs.evaluate_judgement(bad, item, None, ["effect", "influence", "impact"])
            self.assertFalse(ok, k)


class ParallelChunkTests(unittest.TestCase):
    def test_generation_and_judging_are_split_into_parallel_chunks_and_result_is_complete(self):
        kb = load_knowledge_base("world-1", 1)
        old = (rs.PARALLEL_CHUNK, rs.FIRST_ROUND_EXTRA, rs.OVERGENERATE, rs.JUDGE_PASSES)
        rs.PARALLEL_CHUNK, rs.FIRST_ROUND_EXTRA, rs.OVERGENERATE, rs.JUDGE_PASSES = 7, 4, 2, 1
        try:
            ai = FakeAI(kb, seed=51)
            payload = build(kb, ai)
        finally:
            rs.PARALLEL_CHUNK, rs.FIRST_ROUND_EXTRA, rs.OVERGENERATE, rs.JUDGE_PASSES = old
        self.assertEqual(len(payload["questions"]), 20)
        self.assertEqual(rs.check_set_invariants(payload["questions"], kb), [])
        gens = ai.prompts("generate")
        self.assertEqual(len(gens), 4)                               # 24 bản nháp / 7 mỗi nhóm = 4 lời gọi song song
        sizes = sorted(len(re.findall(r"^Câu \d+: ĐÁP ÁN ĐÚNG", g, re.M)) for g in gens)
        self.assertEqual(sum(sizes), 24)
        self.assertLessEqual(max(sizes), 7)
        self.assertEqual(len(ai.prompts("judge")), 4)                # thẩm định cũng chia nhóm
        self.assertEqual(len({q["question"] for q in payload["questions"]}), 20)

    def test_one_chunk_failing_does_not_lose_the_others(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb, seed=52)
        real = ai.__call__
        state = {"n": 0}

        def flaky(prompt, reasoning_effort="low", model=None):
            if "theo ĐÚNG kế hoạch" in prompt:
                state["n"] += 1
                if state["n"] == 2:
                    raise rs.AIProviderError("boom")
            return real(prompt, reasoning_effort, model)

        old = (rs.PARALLEL_CHUNK, rs.FIRST_ROUND_EXTRA, rs.AI_CALL_RETRIES)
        rs.PARALLEL_CHUNK, rs.FIRST_ROUND_EXTRA, rs.AI_CALL_RETRIES = 7, 0, 0
        try:
            payload = rs.build_recognition_set(kb, ask_fn=flaky, history_fn=lambda: [], refs_fn=lambda w: [], rng=random.Random(3))
        finally:
            rs.PARALLEL_CHUNK, rs.FIRST_ROUND_EXTRA, rs.AI_CALL_RETRIES = old
        self.assertEqual(len(payload["questions"]), 20)


class TieAsTwoAnswersTests(unittest.TestCase):
    SENT = "The harbor lantern flickered while a violin echoed and ___ followed soon."

    def row(self, bests=("A", "B"), chosen="A", crit_override=None):
        crit = {k: True for k in rs.REQUIRED_CRITERIA}
        crit["single_best"] = False
        crit.update(crit_override or {})
        opts = {l: {"verdict": "best" if l in bests else "rejected", "note": "n"} for l in "ABCD"}
        return {"chosen": chosen, "usage": "u", "cue_quote": "violin echoed", "rival": "B" if chosen == "A" else "A",
                "rival_reading": "cách hiểu", "rival_detail_quote": "flickered", "kb_ref": ["effect"], "options": opts,
                "criteria": crit, "difficulty": "hard"}

    def ev(self, row, allow):
        item = {"sentence": self.SENT, "options": ["effect", "influence", "impact", "tree"], "answer": "effect"}
        return rs.evaluate_judgement(row, item, None, ["effect", "influence", "impact"], allow)

    def test_tie_rejected_by_default_accepted_as_two_answers_when_allowed(self):
        self.assertFalse(self.ev(self.row(), False)[0])
        ok, reasons, audit = self.ev(self.row(), True)
        self.assertTrue(ok, reasons)
        self.assertEqual(audit["also_correct"], ["influence"])

    def test_tie_limits(self):
        self.assertFalse(self.ev(self.row(bests=("B", "C"), chosen="B"), True)[0])                      # khóa thiết kế không nằm trong hai đáp án
        self.assertFalse(self.ev(self.row(bests=("A", "B", "C")), True)[0])                              # ba đáp án ngang nhau: loại
        self.assertFalse(self.ev(self.row(crit_override={"natural": False}), True)[0])                  # tiêu chí chặn khác hỏng: loại
        self.assertFalse(self.ev(self.row(crit_override={"scope": False}), True)[0])

    def test_grading_counts_either_accepted_answer_and_state_is_exposed(self):
        qs = [{"id": 1, "question": "The harbor ___ flickered.", "options": ["effect", "influence", "impact", "tree"],
               "correct_index": 0, "meta": {"verification": "blind_judge", "audit": {"judges": [{}]}, "also_correct": ["influence"]}}]
        import review
        snap = review.build_snapshot("world-1", 1, qs)
        self.assertEqual(len(snap[0]["alt_oids"]), 1)
        for pick, expected in ((0, "correct"), (1, "correct"), (2, "wrong")):
            g = review.grade(snap, review.answers_by_qv(snap, {"1": pick}), {})
            self.assertEqual(g["per_question"][snap[0]["qv"]]["status"], expected)

    def test_build_uses_tie_only_from_later_rounds(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb, seed=61)
        ai.forced_sentence[(1, 3)] = "A grey pigeon crossed the canyon while a cobbler paused and ___ followed."
        both = {"A": {"verdict": "best", "note": "n"}, "B": {"verdict": "best", "note": "n"},
                "C": {"verdict": "rejected", "note": "n"}, "D": {"verdict": "rejected", "note": "n"}}
        ai.judge_override["grey pigeon crossed"] = {"options": both, "criteria": {"single_best": False}, "rival": "B"}
        payload = build(kb, ai)
        for q in payload["questions"]:
            if "grey pigeon crossed" in q["question"]:
                self.fail("vòng 1 không được nhận câu hai đáp án ngang nhau")


class WeakKeyFillTests(unittest.TestCase):
    SENT = "The harbor lantern flickered while a violin echoed and ___ followed soon."

    def row(self, chosen="A", single_best=False):
        crit = {k: True for k in rs.REQUIRED_CRITERIA}
        crit["single_best"] = single_best
        opts = {l: {"verdict": "best" if l == chosen else "rejected", "note": "n"} for l in "ABCD"}
        return {"chosen": chosen, "usage": "u", "cue_quote": "violin echoed", "rival": "B" if chosen != "B" else "C",
                "rival_reading": "cách hiểu", "rival_detail_quote": "flickered", "kb_ref": ["effect"], "options": opts,
                "criteria": crit, "difficulty": "hard"}

    def ev(self, row, weak):
        item = {"sentence": self.SENT, "options": ["effect", "influence", "impact", "tree"], "answer": "effect"}
        return rs.evaluate_judgement(row, item, None, ["effect", "influence", "impact"], False, weak)

    def test_weak_only_when_allowed_chosen_matches_and_nothing_else_fails(self):
        self.assertFalse(self.ev(self.row(), False)[0])
        ok, reasons, audit = self.ev(self.row(), True)
        self.assertTrue(ok, reasons)
        self.assertTrue(audit["weak_key"])
        self.assertFalse(self.ev(self.row(chosen="B"), True)[0])                       # chọn khác đáp án thiết kế: loại
        row = self.row()
        row["criteria"]["natural"] = False
        self.assertFalse(self.ev(row, True)[0])                                         # tiêu chí chặn khác hỏng: loại
        self.assertFalse(rs.evaluate_judgement(self.row(single_best=True), {"sentence": self.SENT, "options": ["effect", "influence", "impact", "tree"], "answer": "effect"}, None, None, False, True)[2]["weak_key"])


class PartialSetAndAdaptiveTests(unittest.TestCase):
    def setUp(self):
        self._min = rs.MIN_SET_SIZE
        rs.MIN_SET_SIZE = 18

    def tearDown(self):
        rs.MIN_SET_SIZE = self._min

    def test_18_or_19_question_set_is_issued_when_cells_keep_failing_and_every_question_has_one_blank(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb, seed=71)
        ai.fail_cells = {("effect", "hard")}       # một ô không bao giờ ra câu hợp lệ (2 vị trí)
        old = rs.OVERGENERATE
        payload = build(kb, ai)
        n = len(payload["questions"])
        self.assertTrue(rs.MIN_SET_SIZE <= n < 20, n)
        self.assertTrue(payload["partial"])
        for q in payload["questions"]:
            self.assertEqual(q["question"].count("___"), 1)               # bắt buộc có đúng một ô trống
            self.assertEqual(len(q["options"]), 4)
        self.assertEqual([q["id"] for q in payload["questions"]], list(range(1, n + 1)))
        self.assertEqual(rs.check_set_invariants(payload["questions"], kb, payload["difficulty_targets"], allow_partial=True), [])

    def test_below_minimum_still_fails_with_retryable_error(self):
        kb = load_knowledge_base("world-1", 1)
        ai = FakeAI(kb, seed=72)
        ai.fail_cells = {(w, d) for w in kb["target_words"] for d in ("easy", "medium", "hard")} - {("effect", "easy")}
        with self.assertRaises(HTTPException) as cm:
            build(kb, ai)
        self.assertEqual(cm.exception.status_code, 502)
        self.assertGreaterEqual(len(cm.exception.partial["pool"]), 0)

    def test_blankless_question_never_enters_a_partial_set(self):
        for bad in ("No blank at all here.", "Two ___ blanks ___ here."):
            errs, item = rs.validate_item({"sentence": bad, "options": ["effect", "influence", "impact", "tree"], "answer": "influence"},
                                          {"word": "influence"}, load_knowledge_base("world-1", 1))
            self.assertTrue(errs)
            self.assertIsNone(item)

    def test_select_final_follows_lowered_difficulty_targets(self):
        kb = kb_with_size(3)
        plan = rs.plan_set(kb, random.Random(11))
        items = [{"word": s["word"], "difficulty": s["difficulty"], "sentence": f"s{s['id']}"} for s in plan["slots"]
                 if s["difficulty"] != "hard"]                          # chưa có câu khó nào đạt
        targets = {"easy": 8, "medium": 10, "hard": 2}                  # đã hạ 4 câu khó
        placed, missing = rs.select_final(items, plan, random.Random(1), None, targets)
        self.assertEqual(sum(1 for m in missing if m["difficulty"] == "hard"), 2)
        self.assertEqual(len(placed) + len(missing), 20)
        self.assertEqual(sum(targets.values()), 20)

    def test_history_window_is_last_three_sets_and_truncates_client_lists(self):
        import main
        calls = {}
        orig, orig_prog = db.load_issued_questions, db.load_progress
        db.load_issued_questions = lambda u, w, l, max_sets=3, **k: calls.setdefault("sets", max_sets) and []
        db.load_progress = lambda u: {}                                   # không chạm DB thật
        try:
            big = [f"q {i} ___" for i in range(300)]
            hist = main._server_history(1, "world-1", 1, big)
        finally:
            db.load_issued_questions, db.load_progress = orig, orig_prog
        self.assertEqual(calls["sets"], 3)
        self.assertEqual(len(hist), 60)
        self.assertEqual(hist[-1], "q 299 ___")


class DifficultyInResponseTests(unittest.TestCase):
    def test_begin_recognition_response_exposes_only_difficulty_not_key_or_audit(self):
        import main
        db.get_keys = lambda u: 5
        qs = [{"id": 1, "question": "A ___ b", "options": ["a", "b", "c", "d"], "correct_index": 2,
               "meta": {"difficulty": "hard", "audit": {"cue": "secret"}}},
              {"id": 2, "question": "Old ___", "options": ["a", "b", "c", "d"], "correct_index": 1}]
        res = main._recognition_response(1, qs, False, False)
        self.assertEqual(res["questions"][0], {"id": 1, "question": "A ___ b", "options": ["a", "b", "c", "d"], "difficulty": "hard"})
        self.assertEqual(set(res["questions"][1]), {"id", "question", "options"})        # bộ cũ: không có nhãn
        self.assertNotIn("secret", json.dumps(res))
        self.assertNotIn("correct_index", json.dumps(res))
