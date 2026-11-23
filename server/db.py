"""Lớp truy cập PostgreSQL (Neon): user đăng nhập Google, tiến độ học, key,
thanh toán, session, feedback. Lưu trữ persistent lâu dài - khác với
session_store.py (in-memory, chỉ sống trong 1 phiên chat AI đang làm dở)."""

import json
import os
import secrets

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

# Gọi trực tiếp ở đây để module tự chạy đúng dù được import theo thứ tự nào.
load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Số key tặng khi tài khoản đăng nhập lần đầu (xem upsert_user); cũng là giá
# trị migrate cho user cũ để không ai bị mất quyền dùng AI đột ngột.
INITIAL_KEYS = 15


def get_conn() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db() -> None:
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            google_sub TEXT UNIQUE NOT NULL,
            email TEXT,
            name TEXT,
            picture TEXT,
            keys INTEGER NOT NULL DEFAULT 0,
            purchase_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS progress (
            user_id INTEGER PRIMARY KEY,
            data_json TEXT NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_payments (
            reference_code TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            package_index INTEGER NOT NULL,
            amount_vnd INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            paid_at TIMESTAMPTZ
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id SERIAL PRIMARY KEY,
            name TEXT,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_reports (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            world_id TEXT NOT NULL,
            level INTEGER NOT NULL,
            kind TEXT NOT NULL,
            item_ref TEXT NOT NULL,
            question TEXT,
            current_answer TEXT,
            suggested_answer TEXT,
            user_explanation TEXT,
            verdict TEXT NOT NULL,
            lesson TEXT,
            judge_reason TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, world_id, level, kind, item_ref, question)
        )
        """
    )
    conn.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS keys INTEGER NOT NULL DEFAULT {INITIAL_KEYS}")
    conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS purchase_count INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS question_sets (
            user_id INTEGER NOT NULL,
            world_id TEXT NOT NULL,
            level INTEGER NOT NULL,
            payload TEXT NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, world_id, level)
        )
        """
    )
    # Lịch sử câu đã PHÁT cho từng tài khoản (nguồn chống lặp phía máy chủ, không phụ thuộc localStorage).
    # Khoá (user_id, set_id, idx) làm việc ghi lại cùng một lần phát là idempotent.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS issued_questions (
            user_id INTEGER NOT NULL,
            world_id TEXT NOT NULL,
            level INTEGER NOT NULL,
            set_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            kind TEXT NOT NULL,
            question TEXT NOT NULL,
            issued_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, set_id, idx)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS issued_questions_lookup ON issued_questions (user_id, world_id, level)"
    )
    # Dự đoán Confidence đã KHÓA, mỗi lượt làm một bản (attempt_key = session_id:lần nộp Recognition thứ n), không
    # ghi đè lần trước. Có measure để phân biệt với Confidence chung cũ (bản cũ không có dòng ở bảng này).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS confidence_predictions (
            user_id INTEGER NOT NULL,
            world_id TEXT NOT NULL,
            level INTEGER NOT NULL,
            attempt_key TEXT NOT NULL,
            measure TEXT NOT NULL,
            payload TEXT NOT NULL,
            locked_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, attempt_key)
        )
        """
    )
    # ---- Chấm lại / gắn cờ / báo cáo Recognition (xem review.py) ----
    for ddl in (
        """CREATE TABLE IF NOT EXISTS recognition_attempts (
               attempt_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, world_id TEXT NOT NULL, level INTEGER NOT NULL,
               set_id TEXT, snapshot TEXT NOT NULL, answers TEXT NOT NULL,
               original_correct INTEGER, original_total INTEGER, original_score DOUBLE PRECISION,
               correct INTEGER, valid_total INTEGER, score DOUBLE PRECISION,
               applied_decisions TEXT NOT NULL DEFAULT '[]', explanations TEXT NOT NULL DEFAULT '{}',
               submitted_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""",
        "CREATE TABLE IF NOT EXISTS attempt_questions (attempt_id TEXT NOT NULL, qv TEXT NOT NULL, PRIMARY KEY (attempt_id, qv))",
        "CREATE INDEX IF NOT EXISTS attempt_questions_qv ON attempt_questions (qv)",
        """CREATE TABLE IF NOT EXISTS question_versions (
               qv TEXT PRIMARY KEY, world_id TEXT NOT NULL, level INTEGER NOT NULL, text TEXT NOT NULL,
               options TEXT NOT NULL, key_oid TEXT NOT NULL, audit_status TEXT NOT NULL,
               status TEXT NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS question_flags (
               id SERIAL PRIMARY KEY, qv TEXT NOT NULL, flag_type TEXT NOT NULL, reason TEXT, source TEXT,
               status TEXT NOT NULL DEFAULT 'open', created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, closed_at TIMESTAMPTZ)""",
        "CREATE UNIQUE INDEX IF NOT EXISTS question_flags_open ON question_flags (qv, flag_type) WHERE status = 'open'",
        """CREATE TABLE IF NOT EXISTS question_decisions (
               id SERIAL PRIMARY KEY, qv TEXT NOT NULL, decision_type TEXT NOT NULL, key_oids TEXT, explanation_fix TEXT,
               reason TEXT, source_report_id INTEGER, status TEXT NOT NULL DEFAULT 'proposed',
               proposed_by TEXT, applied_by TEXT, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, applied_at TIMESTAMPTZ)""",
        """CREATE TABLE IF NOT EXISTS question_reports (
               id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, attempt_id TEXT NOT NULL, qv TEXT NOT NULL,
               report_type TEXT NOT NULL, option_oids TEXT NOT NULL DEFAULT '[]', note TEXT, case_id TEXT NOT NULL,
               status TEXT NOT NULL DEFAULT 'received', triage TEXT, decision_id INTEGER,
               created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
               UNIQUE (user_id, attempt_id, qv, report_type))""",
        """CREATE TABLE IF NOT EXISTS learning_rules (
               id SERIAL PRIMARY KEY, source_report_id INTEGER, scope TEXT NOT NULL, world_id TEXT, level INTEGER,
               condition_text TEXT NOT NULL, guidance TEXT NOT NULL, block_example TEXT, keep_example TEXT,
               version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'proposed',
               created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, approved_at TIMESTAMPTZ)""",
        """CREATE TABLE IF NOT EXISTS attempt_results (
               attempt_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, distinction DOUBLE PRECISION,
               application DOUBLE PRECISION, original TEXT NOT NULL, current TEXT NOT NULL,
               revisions TEXT NOT NULL DEFAULT '[]', updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""",
    ):
        conn.execute(ddl)
    # Lời giải đã soạn, tái dùng theo (phiên bản câu, khóa hiệu lực, lựa chọn dùng để đối chiếu, chế độ). Khóa đổi -> khóa cache đổi.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS explanation_cache (
               qv TEXT NOT NULL, key_sig TEXT NOT NULL, chosen TEXT NOT NULL, mode TEXT NOT NULL, text TEXT NOT NULL,
               created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (qv, key_sig, chosen, mode))""")
    # Trạng thái chấm tự luận của một lượt làm (rubric version, các lượt chấm hợp lệ, độ lệch, lượt ba, kết quả cuối).
    conn.execute(
        """CREATE TABLE IF NOT EXISTS open_grading_runs (
               attempt_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, state TEXT NOT NULL,
               updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""")
    # ---- Báo cáo tự luận (Distinction/Application): xem open_review.py ----
    for ddl in (
        """CREATE TABLE IF NOT EXISTS open_reports (
               id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, attempt_id TEXT NOT NULL, skill TEXT NOT NULL,
               category TEXT NOT NULL, criterion TEXT NOT NULL DEFAULT '', target TEXT NOT NULL DEFAULT '',
               quote TEXT, note TEXT, suggested_score DOUBLE PRECISION, rubric_version TEXT,
               status TEXT NOT NULL DEFAULT 'received', outcome TEXT, decision_id INTEGER,
               created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
               UNIQUE (user_id, attempt_id, skill, category, criterion, target))""",
        """CREATE TABLE IF NOT EXISTS open_decisions (
               id SERIAL PRIMARY KEY, attempt_id TEXT NOT NULL, skill TEXT NOT NULL, decision_type TEXT NOT NULL,
               payload TEXT NOT NULL, reason TEXT, source_report_id INTEGER, status TEXT NOT NULL DEFAULT 'proposed',
               proposed_by TEXT, applied_by TEXT, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, applied_at TIMESTAMPTZ)""",
    ):
        conn.execute(ddl)
    for ddl in (
        "ALTER TABLE learning_rules ADD COLUMN IF NOT EXISTS domain TEXT NOT NULL DEFAULT 'any'",
        "ALTER TABLE learning_rules ADD COLUMN IF NOT EXISTS source_kind TEXT NOT NULL DEFAULT 'question'",
        "ALTER TABLE learning_rules ADD COLUMN IF NOT EXISTS confirmed_error TEXT",
        "ALTER TABLE learning_rules ADD COLUMN IF NOT EXISTS check_status TEXT NOT NULL DEFAULT 'unchecked'",
        "ALTER TABLE learning_rules ADD COLUMN IF NOT EXISTS check_note TEXT",
    ):
        conn.execute(ddl)
    conn.execute("ALTER TABLE pending_payments ADD COLUMN IF NOT EXISTS verified BOOLEAN NOT NULL DEFAULT FALSE")
    conn.commit()
    conn.close()


def upsert_user(google_sub: str, email: str, name: str, picture: str) -> dict:
    """Upsert nguyên tử: tặng INITIAL_KEYS khi là INSERT thật sự (lần đầu),
    không đụng cột keys khi rơi vào nhánh UPDATE (tài khoản đã tồn tại)."""
    conn = get_conn()
    row = conn.execute(
        """
        INSERT INTO users (google_sub, email, name, picture, keys)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (google_sub) DO UPDATE SET
            email = EXCLUDED.email, name = EXCLUDED.name, picture = EXCLUDED.picture
        RETURNING *
        """,
        (google_sub, email, name, picture, INITIAL_KEYS),
    ).fetchone()
    conn.commit()
    conn.close()
    return row


def get_keys(user_id: int) -> int:
    conn = get_conn()
    row = conn.execute("SELECT keys FROM users WHERE id = %s", (user_id,)).fetchone()
    conn.close()
    return row["keys"] if row else 0


def deduct_keys(user_id: int, amount: int) -> bool:
    """Trừ key nguyên tử: điều kiện đủ số dư nằm ngay trong WHERE của UPDATE
    (không đọc rồi ghi riêng) để tránh race giữa 2 request đồng thời. Trả về
    False nếu không đủ số dư, không trừ gì cả."""
    conn = get_conn()
    cur = conn.execute("UPDATE users SET keys = keys - %s WHERE id = %s AND keys >= %s", (amount, user_id, amount))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def create_pending_payment(reference_code: str, user_id: int, package_index: int, amount_vnd: int) -> dict:
    """Có thể raise psycopg.errors.UniqueViolation nếu reference_code trùng
    (main.py tự retry với mã khác)."""
    conn = get_conn()
    try:
        row = conn.execute(
            """
            INSERT INTO pending_payments (reference_code, user_id, package_index, amount_vnd)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (reference_code, user_id, package_index, amount_vnd),
        ).fetchone()
        conn.commit()
        return row
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_pending_payment(reference_code: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM pending_payments WHERE reference_code = %s", (reference_code,)).fetchone()
    conn.close()
    return row


def mark_payment_verified(reference_code: str) -> None:
    """Đánh dấu giao dịch pending là 'verified' - bằng chứng có người dùng
    thật đang chờ màn hình QR (gọi mỗi lần frontend poll payment-status).
    Chỉ ảnh hưởng thứ tự ưu tiên khớp FIFO, không ảnh hưởng việc cộng key
    (finalize_payment chỉ cần status='pending')."""
    conn = get_conn()
    conn.execute(
        "UPDATE pending_payments SET verified = TRUE WHERE reference_code = %s AND status = 'pending'",
        (reference_code,),
    )
    conn.commit()
    conn.close()


def get_active_pending_payment(user_id: int, package_index: int) -> dict | None:
    """Giao dịch 'pending' gần nhất của đúng user + gói này, để tái sử dụng
    khi người dùng bấm "Thanh toán" nhiều lần thay vì tạo mã mới mỗi lần."""
    conn = get_conn()
    row = conn.execute(
        """SELECT * FROM pending_payments
           WHERE user_id = %s AND package_index = %s AND status = 'pending'
           ORDER BY created_at DESC LIMIT 1""",
        (user_id, package_index),
    ).fetchone()
    conn.close()
    return row


# Giao dịch pending quá hạn này bị loại khỏi so khớp (nội dung lẫn số tiền).
# Cần TTL để tránh 1 giao dịch pending bị bỏ quên (VD test rồi không trả
# tiền) tồn tại mãi và bị khớp FIFO theo số tiền NHẦM với giao dịch thật đến
# sau - khiến tiền khách bị cộng nhầm tài khoản. Vài phút là đủ cho 1 lượt
# quét QR + chuyển khoản bình thường; khách trả chậm hơn chỉ cần lấy mã mới.
PENDING_PAYMENT_TTL_MINUTES = 3


def expire_stale_pending_payments() -> None:
    """Chuyển mọi giao dịch 'pending' quá PENDING_PAYMENT_TTL_MINUTES phút
    thành 'expired'. Gọi ở đầu mỗi lượt xử lý webhook/poll trạng thái thay vì
    dùng cron riêng; idempotent nên an toàn gọi nhiều lần."""
    conn = get_conn()
    conn.execute(
        "UPDATE pending_payments SET status = 'expired' "
        "WHERE status = 'pending' AND created_at < NOW() - make_interval(mins => %s)",
        (PENDING_PAYMENT_TTL_MINUTES,),
    )
    conn.commit()
    conn.close()


def list_pending_reference_codes() -> list[str]:
    """Mã tham chiếu của mọi giao dịch còn 'pending' - webhook SePay dùng để
    đối chiếu nội dung chuyển khoản."""
    conn = get_conn()
    rows = conn.execute("SELECT reference_code FROM pending_payments WHERE status = 'pending'").fetchall()
    conn.close()
    return [r["reference_code"] for r in rows]


def get_pending_payments_by_amount(amount_vnd: int) -> list[dict]:
    """Lớp dự phòng khi QR không nhúng được nội dung riêng từng giao dịch (QR
    tĩnh dùng chung 1 nội dung cho mọi lượt) - webhook đối chiếu theo đúng số
    tiền thay vì nội dung. Yêu cầu gọi expire_stale_pending_payments() trước
    trong cùng request để loại rác cũ. Sắp xếp created_at tăng dần (cũ nhất
    trước).

    Trả về cả ứng viên chưa 'verified'; lọc theo verified (xem
    mark_payment_verified) là trách nhiệm của caller (main.py), vì chỉ riêng
    'pending + chưa hết hạn' không đủ để chắc đây là giao dịch có người thật
    đang chờ - caller cần verified=true để tránh FIFO chọn nhầm 1 giao dịch
    cũ không ai theo dõi."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM pending_payments WHERE status = 'pending' AND amount_vnd = %s ORDER BY created_at ASC",
        (amount_vnd,),
    ).fetchall()
    conn.close()
    return rows


def finalize_payment(reference_code: str, package: dict, bonus_fn) -> dict | None:
    """Xác nhận 1 giao dịch đã thanh toán (gọi từ webhook SePay sau khi đối
    chiếu nội dung + số tiền khớp): đánh dấu paid, tăng purchase_count và
    cộng key trong CÙNG 1 transaction, để không rơi vào tình huống đã đánh
    dấu paid nhưng crash trước khi cộng key (SePay không retry sau khi nhận
    200 nên phần key sẽ mất trắng nếu tách rời từng bước).

    Trả về None nếu reference_code không tồn tại hoặc đã xử lý trước đó -
    đây là cơ chế chống cộng 2 lần khi SePay gọi lại webhook trùng."""
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE pending_payments SET status = 'paid', paid_at = CURRENT_TIMESTAMP "
            "WHERE reference_code = %s AND status = 'pending'",
            (reference_code,),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return None

        user_id = conn.execute(
            "SELECT user_id FROM pending_payments WHERE reference_code = %s", (reference_code,)
        ).fetchone()["user_id"]

        conn.execute("UPDATE users SET purchase_count = purchase_count + 1 WHERE id = %s", (user_id,))
        new_count = conn.execute(
            "SELECT purchase_count FROM users WHERE id = %s", (user_id,)
        ).fetchone()["purchase_count"]

        amount = package["keys"] + bonus_fn(package, new_count)
        conn.execute("UPDATE users SET keys = keys + %s WHERE id = %s", (amount, user_id))
        new_keys = conn.execute("SELECT keys FROM users WHERE id = %s", (user_id,)).fetchone()["keys"]

        conn.commit()
        return {"user_id": user_id, "new_keys": new_keys, "new_purchase_count": new_count, "amount_credited": amount}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_purchase_count(user_id: int) -> int:
    conn = get_conn()
    row = conn.execute("SELECT purchase_count FROM users WHERE id = %s", (user_id,)).fetchone()
    conn.close()
    return row["purchase_count"] if row else 0


def set_purchase_count(user_id: int, count: int) -> None:
    """Đặt thẳng purchase_count - dùng cho công cụ admin, không dùng trong
    luồng mua bình thường (xem increment_purchase_count)."""
    conn = get_conn()
    conn.execute("UPDATE users SET purchase_count = %s WHERE id = %s", (count, user_id))
    conn.commit()
    conn.close()


def increment_purchase_count(user_id: int) -> int:
    """Tăng purchase_count thêm 1, trả về giá trị mới để caller tính bonus
    theo đúng mốc vừa chạm tới."""
    conn = get_conn()
    conn.execute("UPDATE users SET purchase_count = purchase_count + 1 WHERE id = %s", (user_id,))
    row = conn.execute("SELECT purchase_count FROM users WHERE id = %s", (user_id,)).fetchone()
    conn.commit()
    conn.close()
    return row["purchase_count"] if row else 0


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn = get_conn()
    conn.execute("INSERT INTO sessions (token, user_id) VALUES (%s, %s)", (token, user_id))
    conn.commit()
    conn.close()
    return token


def get_user_by_token(token: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        """SELECT users.* FROM sessions JOIN users ON sessions.user_id = users.id
           WHERE sessions.token = %s""",
        (token,),
    ).fetchone()
    conn.close()
    return row


def delete_session(token: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token = %s", (token,))
    conn.commit()
    conn.close()


def delete_user(user_id: int) -> None:
    """Xoá vĩnh viễn tài khoản và mọi dữ liệu liên quan (session, tiến độ,
    giao dịch). Schema không có cascade nên phải xoá thủ công từng bảng."""
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM progress WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM pending_payments WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit()
    conn.close()


def save_progress(user_id: int, data: dict) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO progress (user_id, data_json, updated_at) VALUES (%s, %s, CURRENT_TIMESTAMP)
           ON CONFLICT (user_id) DO UPDATE SET
             data_json = EXCLUDED.data_json, updated_at = CURRENT_TIMESTAMP""",
        (user_id, json.dumps(data)),
    )
    conn.commit()
    conn.close()


def load_progress(user_id: int) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT data_json FROM progress WHERE user_id = %s", (user_id,)).fetchone()
    conn.close()
    if not row:
        return {}
    try:
        return json.loads(row["data_json"])
    except (TypeError, ValueError):
        return {}


def save_feedback(name: str, content: str) -> None:
    """Lưu góp ý vào DB thay vì mailto: (mailto chỉ mở email nháp, không tự
    gửi nếu máy người dùng chưa cấu hình ứng dụng mail mặc định)."""
    conn = get_conn()
    conn.execute("INSERT INTO feedback (name, content) VALUES (%s, %s)", (name or None, content))
    conn.commit()
    conn.close()


def save_question_set(user_id: int, world_id: str, level: int, payload: dict) -> None:
    """Lưu bộ 20 câu recognition đã sinh + xác minh xong (kèm đáp án đúng, chỉ ở server) để
    người dùng thoát ra vào lại vẫn thấy đúng bộ câu đó, không phải sinh lại hay trừ key lần nữa."""
    conn = get_conn()
    conn.execute(
        """INSERT INTO question_sets (user_id, world_id, level, payload) VALUES (%s, %s, %s, %s)
           ON CONFLICT (user_id, world_id, level)
           DO UPDATE SET payload = EXCLUDED.payload, updated_at = CURRENT_TIMESTAMP""",
        (user_id, world_id, level, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def load_question_set(user_id: int, world_id: str, level: int) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT payload FROM question_sets WHERE user_id = %s AND world_id = %s AND level = %s",
        (user_id, world_id, level),
    ).fetchone()
    conn.close()
    return json.loads(row["payload"]) if row else None


def delete_question_set(user_id: int, world_id: str, level: int) -> None:
    conn = get_conn()
    conn.execute(
        "DELETE FROM question_sets WHERE user_id = %s AND world_id = %s AND level = %s",
        (user_id, world_id, level),
    )
    conn.commit()
    conn.close()


def save_report(user_id: int, world_id: str, level: int, kind: str, item_ref: str, question: str,
                current_answer: str, suggested_answer: str, user_explanation: str,
                verdict: str, lesson: str, judge_reason: str) -> bool:
    """Lưu 1 báo cáo của người dùng cùng kết luận của AI lọc ('accepted'/'rejected').
    Trả False nếu người này đã báo cáo đúng câu đó rồi (chống gửi lặp)."""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO user_reports (user_id, world_id, level, kind, item_ref, question, current_answer,
               suggested_answer, user_explanation, verdict, lesson, judge_reason)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT DO NOTHING""",
        (user_id, world_id, level, kind, item_ref, question, current_answer,
         suggested_answer, user_explanation, verdict, lesson, judge_reason),
    )
    inserted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return inserted


def count_reports_today(user_id: int) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM user_reports WHERE user_id = %s AND created_at > NOW() - INTERVAL '1 day'",
        (user_id,),
    ).fetchone()
    conn.close()
    return int(row["n"])


def load_accepted_lessons(world_id: str, level: int, kind_group: str, limit: int = 8) -> list[str]:
    """Các bài học đã được AI lọc duyệt, dùng làm 'knowledge base người dùng' cho level này.
    kind_group: 'recognition' hoặc 'open' (distinction + application)."""
    kinds = ("recognition",) if kind_group == "recognition" else ("distinction", "application")
    conn = get_conn()
    rows = conn.execute(
        """SELECT lesson FROM user_reports
           WHERE world_id = %s AND level = %s AND verdict = 'accepted' AND kind = ANY(%s) AND lesson IS NOT NULL
           ORDER BY id DESC LIMIT %s""",
        (world_id, level, list(kinds), limit),
    ).fetchall()
    conn.close()
    return [r["lesson"] for r in rows]


def record_issued_set(user_id: int, world_id: str, level: int, set_id: str, kind: str, questions: list[str]) -> None:
    """Ghi các câu đã phát (kind: 'recognition' | 'practice'). Idempotent theo (user_id, set_id, idx):
    gọi lại cho cùng một lần phát (bấm lại, mở lại bộ cũ, hai tab) không tạo thêm dòng."""
    rows = [(user_id, world_id, level, set_id, i, kind, q) for i, q in enumerate(questions) if isinstance(q, str) and q.strip()]
    if not rows:
        return
    conn = get_conn()
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO issued_questions (user_id, world_id, level, set_id, idx, kind, question)
               VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (user_id, set_id, idx) DO NOTHING""",
            rows,
        )
    conn.commit()
    conn.close()


def load_issued_questions(user_id: int, world_id: str, level: int, max_sets: int = 3) -> list[str]:
    """Câu của `max_sets` bộ ĐÃ PHÁT gần nhất (đúng người dùng, world, level), cũ trước mới sau. Chỉ bộ thật sự hiển thị
    cho học sinh mới nằm trong bảng này; bản nháp bị loại thì không. Chống lặp chỉ cần trong phạm vi vài lượt gần nhất."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT q.question FROM issued_questions q
           JOIN (SELECT set_id, MAX(issued_at) AS t FROM issued_questions
                 WHERE user_id = %s AND world_id = %s AND level = %s
                 GROUP BY set_id ORDER BY t DESC LIMIT %s) recent ON recent.set_id = q.set_id
           WHERE q.user_id = %s
           ORDER BY recent.t ASC, q.set_id ASC, q.idx ASC""",
        (user_id, world_id, level, max_sets, user_id),
    ).fetchall()
    conn.close()
    return [r["question"] for r in rows]



def lock_confidence_prediction(user_id: int, world_id: str, level: int, attempt_key: str, measure: str,
                               payload: dict) -> tuple[dict, bool]:
    """Khóa dự đoán của 1 lượt làm. Trả (bản đang có hiệu lực, vừa tạo mới?). Gửi lại / hai tab cùng lượt không
    tạo bản thứ hai: bản đã khóa được trả về nguyên trạng (người gọi tự so sánh với dữ liệu vừa gửi)."""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO confidence_predictions (user_id, world_id, level, attempt_key, measure, payload)
           VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (user_id, attempt_key) DO NOTHING""",
        (user_id, world_id, level, attempt_key, measure, json.dumps(payload, ensure_ascii=False)),
    )
    created = cur.rowcount == 1
    row = conn.execute(
        "SELECT payload FROM confidence_predictions WHERE user_id = %s AND attempt_key = %s", (user_id, attempt_key)
    ).fetchone()
    conn.commit()
    conn.close()
    return json.loads(row["payload"]), created


# ==================== Chấm lại / gắn cờ / báo cáo Recognition ====================
# Mọi hàm ở đây tính lại từ dữ liệu gốc (lựa chọn đã lưu + quyết định đang có hiệu lực), không cộng/trừ gia tăng.

def _q(sql: str, params: tuple = (), one: bool = False, fetch: bool = True):
    conn = get_conn()
    cur = conn.execute(sql, params)
    out = None
    if fetch:
        out = cur.fetchone() if one else cur.fetchall()
    rowcount = cur.rowcount
    conn.commit()
    conn.close()
    return out if fetch else rowcount


def save_attempt(attempt_id: str, user_id: int, world_id: str, level: int, set_id: str | None, snapshot: list,
                 answers: dict, correct: int, total: int, score: float | None) -> dict:
    """Lưu lượt làm (ảnh chụp câu + lựa chọn thực tế + điểm gốc). Gửi lại cùng attempt_id không ghi đè (giữ bản đầu)."""
    conn = get_conn()
    conn.execute(
        """INSERT INTO recognition_attempts (attempt_id, user_id, world_id, level, set_id, snapshot, answers,
               original_correct, original_total, original_score, correct, valid_total, score)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (attempt_id) DO NOTHING""",
        (attempt_id, user_id, world_id, level, set_id, json.dumps(snapshot, ensure_ascii=False),
         json.dumps(answers, ensure_ascii=False), correct, total, score, correct, total, score),
    )
    for q in snapshot:
        conn.execute("INSERT INTO attempt_questions (attempt_id, qv) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                     (attempt_id, q["qv"]))
        conn.execute(
            """INSERT INTO question_versions (qv, world_id, level, text, options, key_oid, audit_status)
               VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (qv) DO NOTHING""",
            (q["qv"], world_id, level, q["text"], json.dumps([o["text"] for o in q["options"]], ensure_ascii=False),
             q["key_oid"], q["audit_status"]),
        )
    conn.commit()
    conn.close()
    return load_attempt(attempt_id)


def load_attempt(attempt_id: str) -> dict | None:
    row = _q("SELECT * FROM recognition_attempts WHERE attempt_id = %s", (attempt_id,), one=True)
    if not row:
        return None
    for f in ("snapshot", "answers", "applied_decisions", "explanations"):
        row[f] = json.loads(row[f])
    return row


def update_attempt_grade(attempt_id: str, correct: int, valid_total: int, score: float | None, applied: list[int]) -> None:
    _q("""UPDATE recognition_attempts SET correct=%s, valid_total=%s, score=%s, applied_decisions=%s,
          updated_at=CURRENT_TIMESTAMP WHERE attempt_id=%s""",
       (correct, valid_total, score, json.dumps(applied), attempt_id), fetch=False)


def save_attempt_explanations(attempt_id: str, explanations: dict) -> None:
    _q("UPDATE recognition_attempts SET explanations=%s WHERE attempt_id=%s",
       (json.dumps(explanations, ensure_ascii=False), attempt_id), fetch=False)


def attempts_for_versions(qvs: list[str]) -> list[str]:
    rows = _q("SELECT DISTINCT attempt_id FROM attempt_questions WHERE qv = ANY(%s)", (list(qvs),))
    return [r["attempt_id"] for r in rows]


def get_question_version(qv: str) -> dict | None:
    row = _q("SELECT * FROM question_versions WHERE qv = %s", (qv,), one=True)
    if row:
        row["options"] = json.loads(row["options"])
    return row


def set_version_status(qv: str, status: str) -> None:
    _q("UPDATE question_versions SET status=%s WHERE qv=%s", (status, qv), fetch=False)


def blocked_version_ids(world_id: str, level: int) -> set[str]:
    rows = _q("SELECT qv FROM question_versions WHERE world_id=%s AND level=%s AND status <> 'active'", (world_id, level))
    return {r["qv"] for r in rows}


def open_flag(qv: str, flag_type: str, reason: str, source: str) -> bool:
    n = _q("""INSERT INTO question_flags (qv, flag_type, reason, source) VALUES (%s,%s,%s,%s)
              ON CONFLICT DO NOTHING""", (qv, flag_type, reason, source), fetch=False)
    return n > 0


def close_flags(qv: str, flag_types: list[str]) -> None:
    _q("""UPDATE question_flags SET status='closed', closed_at=CURRENT_TIMESTAMP
          WHERE qv=%s AND flag_type = ANY(%s) AND status='open'""", (qv, flag_types), fetch=False)


def flags_for(qvs: list[str]) -> list[dict]:
    return _q("SELECT qv, flag_type, reason, status FROM question_flags WHERE qv = ANY(%s)", (list(qvs),))


def create_report(user_id: int, attempt_id: str, qv: str, report_type: str, option_oids: list, note: str,
                  case_id: str) -> tuple[dict, bool]:
    """Idempotent theo (user, lượt, câu, loại): gửi lại do lỗi mạng trả về bản đang có, không tạo thêm."""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO question_reports (user_id, attempt_id, qv, report_type, option_oids, note, case_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id, attempt_id, qv, report_type) DO NOTHING""",
        (user_id, attempt_id, qv, report_type, json.dumps(option_oids), note, case_id),
    )
    created = cur.rowcount == 1
    row = conn.execute(
        "SELECT * FROM question_reports WHERE user_id=%s AND attempt_id=%s AND qv=%s AND report_type=%s",
        (user_id, attempt_id, qv, report_type)).fetchone()
    conn.commit()
    conn.close()
    row["option_oids"] = json.loads(row["option_oids"])
    return row, created


def update_report(report_id: int, status: str, triage: dict | None = None, decision_id: int | None = None) -> None:
    _q("""UPDATE question_reports SET status=%s, triage=COALESCE(%s, triage), decision_id=COALESCE(%s, decision_id),
          updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
       (status, json.dumps(triage, ensure_ascii=False) if triage is not None else None, decision_id, report_id), fetch=False)


def reports_for_attempt(user_id: int, attempt_id: str) -> list[dict]:
    rows = _q("SELECT * FROM question_reports WHERE user_id=%s AND attempt_id=%s ORDER BY id", (user_id, attempt_id))
    for r in rows:
        r["option_oids"] = json.loads(r["option_oids"])
    return rows


def create_decision(qv: str, decision_type: str, key_oids: list[str] | None, explanation_fix: str | None, reason: str,
                    source_report_id: int | None, proposed_by: str) -> int:
    row = _q("""INSERT INTO question_decisions (qv, decision_type, key_oids, explanation_fix, reason, source_report_id,
                proposed_by) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
             (qv, decision_type, json.dumps(key_oids) if key_oids is not None else None, explanation_fix, reason,
              source_report_id, proposed_by), one=True)
    return row["id"]


def list_decisions(qvs: list[str] | None = None, status: str | None = None) -> list[dict]:
    sql, params = "SELECT * FROM question_decisions WHERE TRUE", []
    if qvs is not None:
        sql += " AND qv = ANY(%s)"
        params.append(list(qvs))
    if status:
        sql += " AND status = %s"
        params.append(status)
    rows = _q(sql + " ORDER BY id", tuple(params))
    for r in rows:
        r["key_oids"] = json.loads(r["key_oids"]) if r["key_oids"] else None
        r["decision_type"] = r["decision_type"]
    return rows


def set_decision_status(decision_id: int, status: str, by: str) -> bool:
    """Chỉ chuyển trạng thái hợp lệ (proposed->applied, applied->revoked...). Trả False nếu đã ở trạng thái đó (idempotent)."""
    n = _q("""UPDATE question_decisions SET status=%s, applied_by=%s, applied_at=CASE WHEN %s='applied' THEN CURRENT_TIMESTAMP
              ELSE applied_at END WHERE id=%s AND status <> %s""", (status, by, status, decision_id, status), fetch=False)
    return n > 0


def propose_rule(source_report_id: int | None, rule: dict, world_id: str | None, level: int | None,
                 domain: str = "recognition", source_kind: str = "question", confirmed_error: str | None = None) -> int:
    row = _q("""INSERT INTO learning_rules (source_report_id, scope, world_id, level, condition_text, guidance,
                block_example, keep_example, domain, source_kind, confirmed_error) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id""",
             (source_report_id, rule["scope"], world_id, level, rule["condition"], rule["guidance"],
              rule["block_example"], rule["keep_example"], domain, source_kind, confirmed_error), one=True)
    return row["id"]


def approved_rules(world_id: str, level: int, limit: int = 8, domain: str | None = None) -> list[dict]:
    """Chỉ quy tắc ĐÃ DUYỆT (status='approved') đúng phạm vi: 'general', hoặc đúng world/level. domain: quy tắc 'any' (cũ) luôn
    áp dụng; quy tắc rút từ báo cáo tự luận (domain='open') chỉ vào bộ chấm tự luận, không lẫn sang sinh/chấm trắc nghiệm."""
    rows = _q(
        """SELECT scope, condition_text AS condition, guidance, block_example, keep_example FROM learning_rules
           WHERE status='approved' AND (scope='general' OR (world_id=%s AND (level IS NULL OR level=%s)))
             AND (domain='any' OR domain=%s)
           ORDER BY id DESC LIMIT %s""", (world_id, level, domain or "recognition", limit))
    return rows


def set_rule_status(rule_id: int, status: str) -> bool:
    n = _q("""UPDATE learning_rules SET status=%s, approved_at=CASE WHEN %s='approved' THEN CURRENT_TIMESTAMP
              ELSE approved_at END WHERE id=%s AND status <> %s""", (status, status, rule_id, status), fetch=False)
    return n > 0


def save_attempt_result(attempt_id: str, user_id: int, distinction: float, application: float, original: dict) -> None:
    _q("""INSERT INTO attempt_results (attempt_id, user_id, distinction, application, original, current)
          VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (attempt_id) DO NOTHING""",
       (attempt_id, user_id, distinction, application, json.dumps(original, ensure_ascii=False),
        json.dumps(original, ensure_ascii=False)), fetch=False)


def load_attempt_result(attempt_id: str) -> dict | None:
    row = _q("SELECT * FROM attempt_results WHERE attempt_id=%s", (attempt_id,), one=True)
    if row:
        for f in ("original", "current", "revisions"):
            row[f] = json.loads(row[f])
    return row


def update_attempt_result(attempt_id: str, current: dict, revisions: list) -> None:
    _q("UPDATE attempt_results SET current=%s, revisions=%s, updated_at=CURRENT_TIMESTAMP WHERE attempt_id=%s",
       (json.dumps(current, ensure_ascii=False), json.dumps(revisions, ensure_ascii=False), attempt_id), fetch=False)


def count_question_reports_today(user_id: int) -> int:
    row = _q("SELECT COUNT(*) AS n FROM question_reports WHERE user_id=%s AND created_at > NOW() - INTERVAL '1 day'",
             (user_id,), one=True)
    return int(row["n"])


def save_open_grading(attempt_id: str, user_id: int, state: dict) -> None:
    """Lưu (ghi đè bản mới nhất) trạng thái chấm tự luận: dùng để kiểm tra/tiếp tục, không cộng điểm."""
    _q("""INSERT INTO open_grading_runs (attempt_id, user_id, state) VALUES (%s,%s,%s)
          ON CONFLICT (attempt_id) DO UPDATE SET state = EXCLUDED.state, updated_at = CURRENT_TIMESTAMP""",
       (attempt_id, user_id, json.dumps(state, ensure_ascii=False)), fetch=False)


def get_explanation(key: tuple) -> str | None:
    row = _q("SELECT text FROM explanation_cache WHERE qv=%s AND key_sig=%s AND chosen=%s AND mode=%s", key, one=True)
    return row["text"] if row else None


def put_explanation(key: tuple, text: str) -> None:
    _q("""INSERT INTO explanation_cache (qv, key_sig, chosen, mode, text) VALUES (%s,%s,%s,%s,%s)
          ON CONFLICT (qv, key_sig, chosen, mode) DO NOTHING""", (*key, text), fetch=False)


# ---------------------------------------------------------------- báo cáo tự luận

def load_open_grading(attempt_id: str) -> dict | None:
    row = _q("SELECT state FROM open_grading_runs WHERE attempt_id=%s", (attempt_id,), one=True)
    return json.loads(row["state"]) if row else None


def get_confidence_prediction(user_id: int, attempt_key: str) -> dict | None:
    row = _q("SELECT payload FROM confidence_predictions WHERE user_id=%s AND attempt_key=%s", (user_id, attempt_key), one=True)
    return json.loads(row["payload"]) if row else None


def create_open_report(user_id: int, attempt_id: str, skill: str, category: str, criterion: str, target: str,
                       quote: str | None, note: str | None, suggested_score: float | None, rubric_version: str) -> tuple[dict, bool]:
    """Idempotent theo (người, lượt, bài, loại, tiêu chí, đối tượng): gửi lại do mất mạng trả bản đang có, không tạo thêm."""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO open_reports (user_id, attempt_id, skill, category, criterion, target, quote, note, suggested_score, rubric_version)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (user_id, attempt_id, skill, category, criterion, target) DO NOTHING""",
        (user_id, attempt_id, skill, category, criterion, target, quote, note, suggested_score, rubric_version))
    created = cur.rowcount == 1
    row = conn.execute(
        """SELECT * FROM open_reports WHERE user_id=%s AND attempt_id=%s AND skill=%s AND category=%s AND criterion=%s AND target=%s""",
        (user_id, attempt_id, skill, category, criterion, target)).fetchone()
    conn.commit()
    conn.close()
    return _open_report_row(row), created


def _open_report_row(row: dict) -> dict:
    row["outcome"] = json.loads(row["outcome"]) if row.get("outcome") else None
    return row


def update_open_report(report_id: int, status: str, outcome: dict | None = None, decision_id: int | None = None) -> None:
    _q("""UPDATE open_reports SET status=%s, outcome=COALESCE(%s, outcome), decision_id=COALESCE(%s, decision_id),
          updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
       (status, json.dumps(outcome, ensure_ascii=False) if outcome is not None else None, decision_id, report_id), fetch=False)


def open_reports_for_attempt(user_id: int, attempt_id: str) -> list[dict]:
    return [_open_report_row(r) for r in _q("SELECT * FROM open_reports WHERE user_id=%s AND attempt_id=%s ORDER BY id", (user_id, attempt_id))]


def count_open_reports_today(user_id: int) -> int:
    row = _q("SELECT COUNT(*) AS n FROM open_reports WHERE user_id=%s AND created_at > NOW() - INTERVAL '1 day'", (user_id,), one=True)
    return int(row["n"])


def create_open_decision(attempt_id: str, skill: str, decision_type: str, payload: dict, reason: str,
                         source_report_id: int | None, proposed_by: str, status: str = "proposed") -> int:
    row = _q("""INSERT INTO open_decisions (attempt_id, skill, decision_type, payload, reason, source_report_id, status, proposed_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
             (attempt_id, skill, decision_type, json.dumps(payload, ensure_ascii=False), reason, source_report_id, status, proposed_by),
             one=True)
    return row["id"]


def list_open_decisions(attempt_id: str | None = None, status: str | None = None) -> list[dict]:
    sql, params = "SELECT * FROM open_decisions WHERE TRUE", []
    if attempt_id:
        sql += " AND attempt_id=%s"
        params.append(attempt_id)
    if status:
        sql += " AND status=%s"
        params.append(status)
    rows = _q(sql + " ORDER BY id", tuple(params))
    for r in rows:
        r["payload"] = json.loads(r["payload"])
    return rows


def set_open_decision_status(decision_id: int, status: str, by: str) -> bool:
    n = _q("""UPDATE open_decisions SET status=%s, applied_by=%s, applied_at=CASE WHEN %s='applied' THEN CURRENT_TIMESTAMP
              ELSE applied_at END WHERE id=%s AND status <> %s""", (status, by, status, decision_id, status), fetch=False)
    return n > 0


def set_rule_check(rule_id: int, status: str, note: str) -> None:
    _q("UPDATE learning_rules SET check_status=%s, check_note=%s WHERE id=%s", (status, note, rule_id), fetch=False)
