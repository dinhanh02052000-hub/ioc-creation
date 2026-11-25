"""Định tuyến model theo khâu + hai nhà cung cấp. KHÔNG gọi API thật: mọi client đều là hàm/đối tượng giả."""
import json
import os
import sys
import threading
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import ai_client  # noqa: E402
import ai_router  # noqa: E402
import open_grading as og  # noqa: E402
from test_open_grading import A_ANSWER, A_Q, D_ANSWER, D_Q, FakeGrader  # noqa: E402


class EnvCase(unittest.TestCase):
    KEYS = [f"AI_MODEL_{r.upper()}" for r in ai_router.ROLES] + [f"AI_EFFORT_{r.upper()}" for r in ai_router.ROLES] + ["AI_EFFORT_DEFAULT"]

    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in self.KEYS}

    def tearDown(self):
        for k in self.KEYS:
            os.environ.pop(k, None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v


class RouterTests(EnvCase):
    def test_unconfigured_roles_change_nothing(self):
        got = {}
        fn = ai_router.routed(lambda prompt, **kw: got.update(kw) or "ok", "grade_1")
        fn("p")
        self.assertEqual(got, {})
        fn("p", reasoning_effort="low")
        self.assertEqual(got, {"reasoning_effort": "low"})

    def test_configured_role_adds_model_and_effort_but_never_overrides_an_explicit_model(self):
        os.environ["AI_MODEL_GRADE_2"] = "gpt-6.2-sol"
        os.environ["AI_EFFORT_GRADE_2"] = "medium"
        got = {}
        fn = ai_router.routed(lambda prompt, **kw: got.update(kw) or "ok", "grade_2")
        fn("p", reasoning_effort="low")
        self.assertEqual(got, {"model": "gpt-6.2-sol", "reasoning_effort": "medium"})
        fn("p", model="claude-opus-5-5")
        self.assertEqual(got["model"], "claude-opus-5-5")

    def test_default_effort_applies_to_every_role_without_its_own(self):
        os.environ["AI_EFFORT_DEFAULT"] = "medium"
        os.environ["AI_EFFORT_CARDS"] = "low"
        self.assertEqual((ai_router.effort_for("grade_1"), ai_router.effort_for("cards")), ("medium", "low"))

    def test_unknown_role_is_an_error_not_a_silent_default(self):
        with self.assertRaises(KeyError):
            ai_router.model_for("typo_role")

    def test_provider_detection(self):
        self.assertTrue(ai_router.is_anthropic("claude-sonnet-5-5"))
        self.assertTrue(ai_router.is_anthropic("anthropic:claude-opus-5-5"))
        self.assertFalse(ai_router.is_anthropic("gpt-6.2-sol"))
        self.assertFalse(ai_router.is_anthropic(None))


class _Block:
    def __init__(self, type_, text=""):
        self.type, self.text = type_, text


class FakeAnthropic:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.response, self.error = response, error
        self.messages = types.SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return self.response


def resp(blocks, stop="end_turn"):
    return types.SimpleNamespace(content=blocks, stop_reason=stop, usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))


class AnthropicClientTests(unittest.TestCase):
    def setUp(self):
        self.orig = ai_client.get_anthropic_client

    def tearDown(self):
        ai_client.get_anthropic_client = self.orig

    def use(self, fake):
        ai_client.get_anthropic_client = lambda: fake

    def test_claude_model_goes_to_messages_api_with_adaptive_thinking_and_effort(self):
        fake = FakeAnthropic(resp([_Block("thinking"), _Block("text", '{"a": 1}'), _Block("text", " tail")]))
        self.use(fake)
        out = ai_client.ask("hello", reasoning_effort="medium", model="claude-sonnet-5-5")
        self.assertEqual(out, '{"a": 1} tail')                       # chỉ ghép khối text, bỏ khối thinking
        c = fake.calls[0]
        self.assertEqual(c["model"], "claude-sonnet-5-5")
        self.assertEqual(c["thinking"], {"type": "adaptive"})
        self.assertEqual(c["output_config"], {"effort": "medium"})
        self.assertEqual(c["messages"], [{"role": "user", "content": "hello"}])
        for banned in ("temperature", "top_p", "top_k", "tool_choice", "budget_tokens"):
            self.assertNotIn(banned, c)

    def test_anthropic_prefix_is_stripped_and_unusual_effort_is_mapped(self):
        fake = FakeAnthropic(resp([_Block("text", "x")]))
        self.use(fake)
        ai_client.ask("p", reasoning_effort="none", model="anthropic:claude-opus-5-5")
        self.assertEqual((fake.calls[0]["model"], fake.calls[0]["output_config"]), ("claude-opus-5-5", {"effort": "low"}))

    def test_refusal_and_truncation_are_provider_errors_not_empty_text(self):
        for stop in ("refusal", "max_tokens"):
            self.use(FakeAnthropic(resp([_Block("text", "partial")], stop)))
            with self.assertRaises(ai_client.AIProviderError):
                ai_client.ask("p", model="claude-sonnet-5-5")

    def test_rate_limit_and_overload_map_to_rate_limit_error_others_to_provider_error(self):
        class E(Exception):
            def __init__(self, status, msg="x"):
                super().__init__(msg)
                self.status_code = status
        for status in (429, 529):
            self.use(FakeAnthropic(error=E(status)))
            with self.assertRaises(ai_client.AIRateLimitError):
                ai_client.ask("p", model="claude-sonnet-5-5")
        self.use(FakeAnthropic(error=E(500, "server blew up")))
        with self.assertRaises(ai_client.AIProviderError):
            ai_client.ask("p", model="claude-sonnet-5-5")

    def test_non_claude_models_still_use_openai(self):
        calls = []
        fake_openai = types.SimpleNamespace(responses=types.SimpleNamespace(
            create=lambda **kw: calls.append(kw) or types.SimpleNamespace(output_text="hi", usage=None)))
        orig = ai_client.get_client
        ai_client.get_client = lambda: fake_openai
        try:
            self.assertEqual(ai_client.ask("p", reasoning_effort="medium", model="gpt-6.2-sol"), "hi")
        finally:
            ai_client.get_client = orig
        self.assertEqual((calls[0]["model"], calls[0]["reasoning"]), ("gpt-6.2-sol", {"effort": "medium"}))


class Recorder:
    """Bọc FakeGrader: ghi model + effort của từng lượt gọi (an toàn khi hai lượt chạy song song)."""
    def __init__(self, totals):
        self.g = FakeGrader(totals)
        self.log = []
        self.lock = threading.Lock()
        self.fail_models = set()

    def __call__(self, prompt, reasoning_effort="low", model=None):
        with self.lock:
            self.log.append((model, reasoning_effort))
        if model in self.fail_models:
            from ai_client import AIProviderError
            self.fail_models.discard(model)
            raise AIProviderError("mạng lỗi")
        return self.g(prompt, reasoning_effort=reasoning_effort, model=model)


def fresh_states():
    return {"version": og.RUBRIC_VERSION, "distinction": og.new_skill_state("distinction", D_ANSWER, D_Q),
            "application": og.new_skill_state("application", A_ANSWER, A_Q)}


MODELS = {"grade_1": "claude-sonnet-5-5", "grade_2": "gpt-6.2-sol", "grade_3": "claude-opus-5-5"}
EFFORTS = {"grade_1": "medium", "grade_2": "medium", "grade_3": "medium"}


class GradingRoutingTests(unittest.TestCase):
    def test_two_passes_use_two_different_models_and_efforts(self):
        rec = Recorder([{"distinction": 7.0, "application": 8.0}])
        st = fresh_states()
        og.advance(st, rec, "KB", [], pass_models=MODELS, efforts=EFFORTS)
        self.assertEqual(sorted(m for m, _ in rec.log), ["claude-sonnet-5-5", "gpt-6.2-sol"])
        self.assertEqual({e for _, e in rec.log}, {"medium"})
        roles = sorted(p["role"] for p in st["distinction"]["passes"])
        self.assertEqual(roles, ["grade_1", "grade_2"])
        self.assertEqual(st["distinction"]["status"], "final")

    def test_third_pass_goes_to_the_third_model_only_when_needed(self):
        rec = Recorder([{"distinction": 5.0, "application": 8.0}, {"distinction": 8.0, "application": 8.0}, {"distinction": 6.5}])
        st = fresh_states()
        og.advance(st, rec, "KB", [], pass_models=MODELS, efforts=EFFORTS)
        models = [m for m, _ in rec.log]
        self.assertEqual(models.count("claude-opus-5-5"), 1)
        self.assertEqual(models[-1], "claude-opus-5-5")
        self.assertEqual(len(st["distinction"]["passes"]), 3)
        self.assertEqual(len(st["application"]["passes"]), 2)
        self.assertEqual(st["distinction"]["passes"][2]["role"], "grade_3")

    def test_a_failed_pass_is_regraded_by_the_same_missing_model_not_swapped(self):
        rec = Recorder([{"distinction": 7.0, "application": 8.0}])
        rec.fail_models.add("gpt-6.2-sol")                          # lượt Sol lỗi mạng ở lần đầu
        st = fresh_states()
        og.advance(st, rec, "KB", [], pass_models=MODELS, efforts=EFFORTS)
        self.assertEqual(sorted(m for m, _ in rec.log), ["claude-sonnet-5-5", "gpt-6.2-sol", "gpt-6.2-sol"])
        self.assertEqual(sorted(p["role"] for p in st["distinction"]["passes"]), ["grade_1", "grade_2"])

    def test_unconfigured_routing_keeps_the_old_behaviour(self):
        rec = Recorder([{"distinction": 7.0, "application": 8.0}])
        st = fresh_states()
        og.advance(st, rec, "KB", [])
        self.assertEqual({(m, e) for m, e in rec.log}, {(None, "low")})
        self.assertEqual(st["distinction"]["status"], "final")

    def test_legacy_third_model_argument_still_works(self):
        rec = Recorder([{"distinction": 5.0, "application": 8.0}, {"distinction": 8.0, "application": 8.0}, {"distinction": 6.5}])
        st = fresh_states()
        og.advance(st, rec, "KB", [], "legacy-third")
        self.assertEqual(rec.log[-1][0], "legacy-third")


class RecognitionRoutingTests(EnvCase):
    def test_generation_judge_and_diversity_each_use_their_own_model(self):
        import recognition_set as rs
        seen = []

        def fake_ask(prompt, reasoning_effort="low", model=None):
            seen.append((model, reasoning_effort))
            return "{}"

        os.environ["AI_MODEL_RECOGNITION_GEN"] = "claude-sonnet-5-5"
        os.environ["AI_MODEL_RECOGNITION_JUDGE"] = "gpt-6.2-sol"
        os.environ["AI_EFFORT_DEFAULT"] = "medium"
        rs._call(fake_ask, "p", "generate")
        rs._call(fake_ask, "p", "judge")
        rs._call(fake_ask, "p", "diversity")
        self.assertEqual(seen, [("claude-sonnet-5-5", "medium"), ("gpt-6.2-sol", "medium"), (None, "medium")])

    def test_explicit_answer_model_beats_the_role_model(self):
        import recognition_set as rs
        seen = []
        os.environ["AI_MODEL_RECOGNITION_JUDGE"] = "gpt-6.2-sol"
        rs._call(lambda p, reasoning_effort="low", model=None: seen.append(model) or "{}", "p", "judge", "gpt-answer")
        self.assertEqual(seen, ["gpt-answer"])



class TwoJudgeModelsTests(EnvCase):
    """AI 1 (lượt thuận) và AI 2 (lượt đảo) có thể là hai model khác nhau; chưa cấu hình AI 2 thì giống AI 1 như cũ."""
    def run_judges(self, answer_model=None):
        import recognition_set as rs
        import engine_prompts as ep
        seen = []

        def fake(prompt, reasoning_effort="low", model=None):
            seen.append((model, reasoning_effort))
            return "{}"
        kb = ep.load_knowledge_base("world-1", 1)
        items = [{"sentence": "S ____", "options": ["effect", "influence", "impact", "melody"], "answer": "effect", "word": "effect"}]
        rs.run_blind_judge(fake, kb, items, answer_model, False)
        fwd = list(seen)
        seen.clear()
        rs.run_blind_judge(fake, kb, items, answer_model, True)
        return fwd[0], seen[0]

    def test_second_pass_uses_its_own_model_while_first_keeps_the_judge_model(self):
        os.environ["AI_MODEL_RECOGNITION_JUDGE"] = "gpt-6.2-sol"
        os.environ["AI_MODEL_RECOGNITION_JUDGE_2"] = "claude-sonnet-5-5"
        os.environ["AI_EFFORT_DEFAULT"] = "low"
        first, second = self.run_judges()
        self.assertEqual(first[0], "gpt-6.2-sol")
        self.assertEqual(second[0], "claude-sonnet-5-5")

    def test_without_judge_2_both_passes_use_the_same_model_as_before(self):
        os.environ["AI_MODEL_RECOGNITION_JUDGE"] = "gpt-6.2-sol"
        first, second = self.run_judges()
        self.assertEqual((first[0], second[0]), ("gpt-6.2-sol", "gpt-6.2-sol"))
        os.environ.pop("AI_MODEL_RECOGNITION_JUDGE")
        first, second = self.run_judges()
        self.assertEqual((first[0], second[0]), (None, None))

    def test_judge_2_model_beats_the_shared_answer_model_but_ai_1_keeps_it(self):
        os.environ["AI_MODEL_RECOGNITION_JUDGE_2"] = "claude-sonnet-5-5"
        first, second = self.run_judges(answer_model="gpt-answer")
        self.assertEqual((first[0], second[0]), ("gpt-answer", "claude-sonnet-5-5"))
        os.environ.pop("AI_MODEL_RECOGNITION_JUDGE_2")
        first, second = self.run_judges(answer_model="gpt-answer")
        self.assertEqual((first[0], second[0]), ("gpt-answer", "gpt-answer"))

    def test_judge_2_effort_falls_back_to_the_judge_effort(self):
        os.environ["AI_EFFORT_RECOGNITION_JUDGE"] = "medium"
        _first, second = self.run_judges()
        self.assertEqual(second[1], "medium")


class WiringTests(EnvCase):
    """Mỗi khâu nối đúng vào nơi gọi: kiểm bằng ask giả, không gọi mạng."""
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main

    def test_ask_for_applies_the_role_and_reaches_the_patched_ask(self):
        m = self.main
        seen = []
        orig = m.ask
        m.ask = lambda prompt, **kw: seen.append(kw) or "ok"
        try:
            os.environ["AI_MODEL_LESSON"] = "gpt-6-luna"
            os.environ["AI_MODEL_RULES"] = "claude-sonnet-5-5"
            m._ask_for("lesson")("p")
            m._ask_for("rules")("p")
            m._ask_for("report")("p")
        finally:
            m.ask = orig
        self.assertEqual(seen[0].get("model"), "gpt-6-luna")
        self.assertEqual(seen[1].get("model"), "claude-sonnet-5-5")
        self.assertNotIn("model", seen[2])

    def test_every_role_has_a_name_and_main_only_uses_known_roles(self):
        import re
        src = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
        used = set(re.findall(r'_ask_for\("([a-z_0-9]+)"\)', src))
        self.assertTrue(used <= set(ai_router.ROLES), used - set(ai_router.ROLES))
        self.assertTrue({"lesson", "explanation", "report", "rules", "cards", "try_assess", "open_gen", "grade_1"} <= used)


if __name__ == "__main__":
    unittest.main()
