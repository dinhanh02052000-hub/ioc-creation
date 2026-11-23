"""Chạy THẬT pipeline sinh bộ Recognition qua mô hình (cần OPENAI_API_KEY trong .env). Không dùng DB.

Dùng: python -B run_real_check.py <world> <level> [out.json]
In ra thống kê độ phủ từ, phân bố khó, số lần gọi AI và lưu bộ câu (kèm meta máy chủ) để đọc bằng mắt."""

import json
import logging
import random
import sys
import time

sys.dont_write_bytecode = True
logging.basicConfig(level=logging.INFO, format="%(message)s")

import ai_client
import recognition_set as rs
from engine_prompts import load_knowledge_base

world, level = sys.argv[1], int(sys.argv[2])
kb = load_knowledge_base(world, level)
calls = []


def counting_ask(prompt, reasoning_effort="low", model=None):
    t = time.time()
    out = ai_client.ask(prompt, reasoning_effort=reasoning_effort, model=model)
    calls.append((prompt[:60].replace("\n", " "), round(time.time() - t, 1)))
    return out


start = time.time()
payload = rs.build_recognition_set(
    kb, ask_fn=counting_ask, history_fn=lambda: [], refs_fn=lambda wait: [], rng=random.Random()
)
print(f"\n=== {world} level {level}: xong sau {time.time() - start:.0f}s, {len(calls)} lượt gọi AI ===")
words, diffs = {}, {}
for q in payload["questions"]:
    w = q["options"][q["correct_index"]]
    words[w] = words.get(w, 0) + 1
    diffs[q["meta"]["difficulty"]] = diffs.get(q["meta"]["difficulty"], 0) + 1
print("độ phủ từ:", words)
print("phân bố khó (đã thẩm định):", diffs)
print("kiểm tra bất biến:", rs.check_set_invariants(payload["questions"], kb) or "đạt")
for q in payload["questions"]:
    print(f"{q['id']:>2} [{q['meta']['difficulty']:<6}] {q['question']}  -> {q['options']} = {q['options'][q['correct_index']]}")
if len(sys.argv) > 3:
    json.dump(payload, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
