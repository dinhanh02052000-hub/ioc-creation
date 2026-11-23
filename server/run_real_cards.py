"""Chạy THẬT bước soạn thẻ ôn qua mô hình (cần OPENAI_API_KEY trong .env). Không dùng DB.
Dùng: python -B run_real_cards.py <world> <level>
In thẻ cho ba kiểu bài Distinction (bỏ trống / chỉ dịch nghĩa / nhầm vai trò) và một mục tiêu Application để đọc bằng mắt."""

import json
import sys

sys.dont_write_bytecode = True

import ai_client
import remediation_plan as rp
from ai_json import parse_ai_json
from engine_prompts import compact_kb, load_knowledge_base
from test_remediation_plan import make_session

world, level = sys.argv[1], int(sys.argv[2])
kb = load_knowledge_base(world, level)
words = list(kb["target_words"])
kb_text = compact_kb(kb)
cases = {
    "bỏ trống": make_session(d_answer=""),
    "chỉ dịch nghĩa": make_session(d={"hieu_goc": 2, "ngu_canh": 2, "doi_nghia": 0, "phan_biet": 1, "so_sanh": 1}),
    "nhầm vai trò": make_session(d={"hieu_goc": 2, "ngu_canh": 2, "doi_nghia": 2, "phan_biet": 0, "so_sanh": 2}),
    "application mất giải thích": make_session(a={"chon_tu": 2, "dung_dung": 3, "tinh_huong": 2, "giai_thich": 0}),
}
for name, sess in cases.items():
    t = rp.select_targets(rp.collect_evidence(sess))[0]
    card = rp.build_card(ai_client.ask, parse_ai_json, t, words, kb_text)
    print("=" * 70)
    print(name, "->", t["kind"], "|", t["action"])
    print("WHY:", t["why"])
    print(json.dumps(card and {k: v for k, v in card.items() if k != "target"}, ensure_ascii=False, indent=1) if card else "KHÔNG SOẠN ĐƯỢC THẺ HỢP LỆ")
