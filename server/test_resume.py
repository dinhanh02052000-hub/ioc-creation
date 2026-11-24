"""Vào lại giữa chừng khi phiên trong RAM đã mất: mở lại đúng bộ câu đã phát, không sinh lại bài học, không trừ key, giữ nguyên thứ tự."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import db  # noqa: E402


def qs(n=3):
    return [{"id": i, "question": f"Q{i} ____", "options": ["a", "b", "c", "d"], "correct_index": i % 4,
             "meta": {"difficulty": "easy"}} for i in range(1, n + 1)]


class ResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main

    def setUp(self):
        m = self.main
        self.stored = None
        self.orig = (db.load_question_set, db.get_keys, m._start_recognition_prep, m.load_knowledge_base)
        db.load_question_set = lambda *a, **k: self.stored
        db.get_keys = lambda uid: 13
        self.prep_calls = []
        m._start_recognition_prep = lambda session, uid, retry: self.prep_calls.append(session["session_id"])
        m.load_knowledge_base = lambda w, l: {"group_title": "g"}
        self.user = {"id": 1, "keys": 13}

    def tearDown(self):
        m = self.main
        db.load_question_set, db.get_keys, m._start_recognition_prep, m.load_knowledge_base = self.orig

    def req(self, **kw):
        base = dict(world_id="world-1", level=1)
        base.update(kw)
        return self.main.ResumeRequest(**base)

    def test_lost_session_with_issued_set_reopens_the_same_questions_without_lesson_or_charge(self):
        self.stored = {"questions": qs(), "charged": True, "set_id": "SET1"}
        r = self.main.resume_session(self.req(session_id="gone"), user=self.user)
        self.assertEqual((r["state"], r["recovered"]), ("WAITING_RECOGNITION_SUBMISSION", True))
        self.assertEqual([q["id"] for q in r["questions"]], [1, 2, 3])
        self.assertEqual(r["questions"][0]["options"], ["a", "b", "c", "d"])      # cùng thứ tự lựa chọn
        self.assertTrue(r["resumed"])
        self.assertNotIn("correct_index", r["questions"][0])                      # không lộ đáp án
        s = self.main.get_session(r["session_id"])
        self.assertEqual(s["secure_answer_key"], {"1": 1, "2": 2, "3": 3})
        self.assertEqual(s["set_id"], "SET1")
        self.assertEqual(self.prep_calls, [])                                       # không sinh lại bộ câu hỏi

    def test_alive_session_is_returned_untouched(self):
        s = self.main.create_session("world-1", 1, False)
        s["current_state"] = "WAITING_RECOGNITION_SUBMISSION"
        s["generated_questions"] = qs()
        r = self.main.resume_session(self.req(session_id=s["session_id"]), user=self.user)
        self.assertEqual((r["session_id"], r["recovered"]), (s["session_id"], False))
        self.assertEqual(len(r["questions"]), 3)
        s2 = self.main.create_session("world-1", 1, False)
        s2["current_state"] = "READY_FOR_RECOGNITION"
        r2 = self.main.resume_session(self.req(session_id=s2["session_id"]), user=self.user)
        self.assertEqual((r2["session_id"], r2["state"], "questions" in r2), (s2["session_id"], "READY_FOR_RECOGNITION", False))

    def test_session_of_another_level_is_not_reused(self):
        s = self.main.create_session("world-1", 2, False)
        r = self.main.resume_session(self.req(session_id=s["session_id"]), user=self.user)
        self.assertNotEqual(r["session_id"], s["session_id"])

    def test_nothing_issued_yet_gives_a_ready_session_and_one_background_prep(self):
        r = self.main.resume_session(self.req(session_id="gone"), user=self.user)
        self.assertEqual((r["state"], r["recovered"], "questions" in r), ("READY_FOR_RECOGNITION", True, False))
        self.assertEqual(self.prep_calls, [r["session_id"]])

    def test_unissued_stored_set_is_used_as_prep_instead_of_generating_again(self):
        self.stored = {"questions": qs(), "set_id": "SET2"}            # đã sinh nhưng chưa phát (chưa charged)
        r = self.main.resume_session(self.req(session_id=None), user=self.user)
        self.assertEqual(r["state"], "READY_FOR_RECOGNITION")
        self.assertEqual(self.prep_calls, [])
        self.assertEqual(self.main.get_session(r["session_id"])["prep"]["status"], "ready")

    def test_requires_a_valid_level(self):
        from fastapi import HTTPException
        self.main.load_knowledge_base = lambda w, l: (_ for _ in ()).throw(ValueError("không có level"))
        with self.assertRaises(HTTPException) as cm:
            self.main.resume_session(self.req(world_id="zzz"), user=self.user)
        self.assertEqual(cm.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
