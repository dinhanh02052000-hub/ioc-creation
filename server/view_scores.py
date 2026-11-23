"""Xem điểm làm bài của người dùng, đọc trực tiếp từ dữ liệu gốc trong database.

Nguồn: DATABASE_URL (Supabase, đang chạy) và NEON_DATABASE_URL_BACKUP (Neon cũ)
trong server/.env. Chỉ ĐỌC (SELECT), không sửa dữ liệu.

Mỗi dòng = kết quả lần làm gần nhất của 1 user ở 1 level (hệ thống chỉ giữ lần
gần nhất cho mỗi level), gồm: thời gian làm, gmail, nhóm từ, điểm Recognition /
Distinction / Application / Overall, độ tự tin, GAP, IOC Detected hay không, và
các từ làm sai. Điểm từng tiêu chí của rubric chỉ có với bài làm sau khi hệ
thống bắt đầu lưu chúng.

Cách dùng (chạy trong thư mục server):
    python view_scores.py                       # cả 2 nguồn, mọi user
    python view_scores.py --email abc@gmail.com # chỉ 1 gmail (khớp một phần)
    python view_scores.py --source neon         # chỉ Neon (hoặc supabase)
    python view_scores.py --detected            # chỉ các bài bị IOC Detected
    python view_scores.py --csv ketqua.csv      # xuất thêm file CSV
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()

SOURCES = {
    "supabase": "DATABASE_URL",
    "neon": "NEON_DATABASE_URL_BACKUP",
}

RUBRIC_LABELS = {
    "distinction_rubric": "Phân biệt",
    "application_rubric": "Vận dụng",
}


def fetch_source(name: str, env_key: str) -> list[dict]:
    url = os.environ.get(env_key, "")
    if not url:
        print(f"[bỏ qua] {name}: chưa có {env_key} trong .env", file=sys.stderr)
        return []
    try:
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=15) as conn:
            return conn.execute(
                """SELECT u.id, u.email, u.name, u.created_at, p.data_json
                   FROM users u JOIN progress p ON p.user_id = u.id"""
            ).fetchall()
    except Exception as e:  # noqa: BLE001
        print(f"[lỗi] không đọc được {name}: {e}", file=sys.stderr)
        return []


def rows_from_users(source: str, users: list[dict]) -> list[dict]:
    rows = []
    for u in users:
        try:
            data = json.loads(u["data_json"] or "{}")
        except (TypeError, ValueError):
            continue
        results = data.get("ioc_level_results") or {}
        for world_id, levels in results.items():
            for level, r in (levels or {}).items():
                if not isinstance(r, dict) or r.get("recognition") is None:
                    continue
                ts = r.get("timestamp")
                rows.append({
                    "source": source,
                    "email": u["email"] or "",
                    "name": u["name"] or "",
                    "world": world_id,
                    "level": int(level),
                    "time": datetime.fromtimestamp(ts / 1000) if ts else None,
                    "group_title": r.get("group_title") or "",
                    "recognition": r.get("recognition"),
                    "distinction": r.get("distinction"),
                    "application": r.get("application"),
                    "overall": r.get("overall"),
                    "confidence": r.get("confidence"),
                    "gap": r.get("gap"),
                    "ioc_detected": r.get("illusion_status") == "DETECTED",
                    "illusion_status": r.get("illusion_status") or "",
                    "wrong_words": [w.get("correct") for w in (r.get("wrong_words") or []) if isinstance(w, dict)],
                    "rubric": {k: r.get(k) for k in RUBRIC_LABELS if r.get(k)},
                    "distinction_feedback": r.get("distinction_feedback") or "",
                    "application_feedback": r.get("application_feedback") or "",
                })
    return rows


def fmt(v, digits=1) -> str:
    return "-" if v is None else f"{v:.{digits}f}"


def print_row(r: dict) -> None:
    t = r["time"].strftime("%d/%m/%Y %H:%M:%S") if r["time"] else "(không rõ)"
    flag = "IOC DETECTED" if r["ioc_detected"] else ("không" if r["illusion_status"] else "-")
    print(f"{r['email']}  ({r['name']})  [{r['source']}]")
    print(f"  {r['world']} · Level {r['level']} · {r['group_title']}  |  làm lúc {t}")
    print(
        f"  Recognition {fmt(r['recognition'])} | Distinction {fmt(r['distinction'])} | "
        f"Application {fmt(r['application'])} | Overall {fmt(r['overall'])}"
    )
    gap = r["gap"]
    gap_text = "-" if gap is None else f"{gap:+.1f}"
    print(f"  Tự tin {fmt(r['confidence'])} | GAP {gap_text} | IOC Detected: {flag} ({r['illusion_status'] or '-'})")
    for key, label in RUBRIC_LABELS.items():
        rows = r["rubric"].get(key)
        if rows:
            detail = ", ".join(f"{x['label']} {x['score']}/{x['max']}" for x in rows)
            print(f"  Rubric {label}: {detail}")
    if r["wrong_words"]:
        print(f"  Từ làm sai: {', '.join(w for w in r['wrong_words'] if w)}")
    print()


def write_csv(path: str, rows: list[dict]) -> None:
    cols = ["source", "email", "name", "world", "level", "time", "group_title", "recognition", "distinction",
            "application", "overall", "confidence", "gap", "ioc_detected", "illusion_status", "wrong_words",
            "distinction_rubric", "application_rubric"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig để Excel đọc đúng tiếng Việt
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([
                r["source"], r["email"], r["name"], r["world"], r["level"],
                r["time"].strftime("%Y-%m-%d %H:%M:%S") if r["time"] else "",
                r["group_title"], r["recognition"], r["distinction"], r["application"], r["overall"],
                r["confidence"], r["gap"], "YES" if r["ioc_detected"] else "NO", r["illusion_status"],
                "; ".join(w_ for w_ in r["wrong_words"] if w_),
                json.dumps(r["rubric"].get("distinction_rubric") or "", ensure_ascii=False),
                json.dumps(r["rubric"].get("application_rubric") or "", ensure_ascii=False),
            ])


def main() -> None:
    ap = argparse.ArgumentParser(description="Xem điểm làm bài của người dùng từ Supabase và Neon")
    ap.add_argument("--email", help="lọc theo gmail (khớp một phần, không phân biệt hoa thường)")
    ap.add_argument("--source", choices=["supabase", "neon", "both"], default="both")
    ap.add_argument("--detected", action="store_true", help="chỉ hiện các bài bị IOC Detected")
    ap.add_argument("--csv", help="đường dẫn file CSV để xuất")
    args = ap.parse_args()

    names = list(SOURCES) if args.source == "both" else [args.source]
    rows: list[dict] = []
    for name in names:
        rows += rows_from_users(name, fetch_source(name, SOURCES[name]))

    # Cùng 1 bài có thể nằm ở cả 2 nguồn (Neon là bản cũ đã chuyển sang Supabase): giữ bản Supabase.
    seen, unique = set(), []
    for r in sorted(rows, key=lambda x: x["source"] != "supabase"):
        key = (r["email"].lower(), r["world"], r["level"], r["time"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)

    if args.email:
        unique = [r for r in unique if args.email.lower() in r["email"].lower()]
    if args.detected:
        unique = [r for r in unique if r["ioc_detected"]]
    unique.sort(key=lambda r: (r["time"] or datetime.min), reverse=True)

    for r in unique:
        print_row(r)
    detected = sum(1 for r in unique if r["ioc_detected"])
    print(f"Tổng: {len(unique)} bài làm, {detected} bài bị IOC Detected.")
    if args.csv:
        write_csv(args.csv, unique)
        print(f"Đã xuất CSV: {args.csv}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định không in được tiếng Việt
    main()
