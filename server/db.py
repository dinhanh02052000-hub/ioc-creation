"""PostgreSQL (Neon) lưu user đăng nhập Google + tiến độ học - persistent
THẬT SỰ, khác với SQLite trước đây (bị xoá sạch mỗi lần server khởi động lại
trên hosting free tier vì ổ đĩa ở đó chỉ tạm thời). Khác hẳn session_store.py
(in-memory, chỉ sống trong 1 phiên chat AI đang làm dở)."""

import json
import os
import secrets

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

# Gọi load_dotenv() ngay ở đây (không dựa vào config.py gọi trước) để module
# này tự chạy đúng dù được import theo thứ tự nào.
load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Số key tặng khi 1 tài khoản Google đăng nhập LẦN ĐẦU TIÊN (xem upsert_user).
# Cũng dùng làm giá trị migrate cho user đã có sẵn từ trước khi tính năng key
# ra mắt - để không ai bị khoá AI đột ngột ngay sau khi cập nhật.
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
    # Postgres hỗ trợ thẳng "ADD COLUMN IF NOT EXISTS" - đơn giản hơn hẳn kiểu
    # tự kiểm tra PRAGMA table_info như SQLite trước đây. An toàn chạy lại
    # nhiều lần (no-op nếu cột đã có).
    conn.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS keys INTEGER NOT NULL DEFAULT {INITIAL_KEYS}")
    conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS purchase_count INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    conn.close()


def upsert_user(google_sub: str, email: str, name: str, picture: str) -> dict:
    """UPSERT nguyên tử trong 1 câu lệnh (Postgres hỗ trợ thật, khác SQLite
    trước đây phải né bằng try/except IntegrityError): tặng INITIAL_KEYS khi
    đây là INSERT thật sự (lần đầu), KHÔNG đụng cột keys khi rơi vào nhánh
    UPDATE (tài khoản đã tồn tại)."""
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
    """Trừ key NGUYÊN TỬ: kiểm tra đủ số dư và trừ trong CÙNG 1 câu UPDATE
    (WHERE keys >= amount) thay vì đọc số dư rồi ghi lại riêng - tránh race
    khi 2 request gần như đồng thời cùng đọc thấy đủ key rồi cùng trừ. Trả về
    False nếu không đủ (không có row nào khớp WHERE) - KHÔNG trừ gì cả."""
    conn = get_conn()
    cur = conn.execute("UPDATE users SET keys = keys - %s WHERE id = %s AND keys >= %s", (amount, user_id, amount))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def create_pending_payment(reference_code: str, user_id: int, package_index: int, amount_vnd: int) -> dict:
    """Có thể raise psycopg.errors.UniqueViolation nếu reference_code trùng
    (main.py tự retry với mã khác) - PHẢI đóng connection ở mọi nhánh kể cả
    lỗi, nếu không aborted transaction sẽ rò rỉ connection."""
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


def get_active_pending_payment(user_id: int, package_index: int) -> dict | None:
    """Trả về giao dịch 'pending' GẦN NHẤT của đúng user + đúng gói này (nếu
    có) - dùng để TÁI SỬ DỤNG khi người dùng bấm "Thanh toán" nhiều lần cho
    cùng 1 gói thay vì tạo mã mới mỗi lần (tránh bỏ rơi 1 giao dịch đang dở
    dang - xem create-payment ở main.py)."""
    conn = get_conn()
    row = conn.execute(
        """SELECT * FROM pending_payments
           WHERE user_id = %s AND package_index = %s AND status = 'pending'
           ORDER BY created_at DESC LIMIT 1""",
        (user_id, package_index),
    ).fetchone()
    conn.close()
    return row


def list_pending_reference_codes() -> list[str]:
    """Toàn bộ mã tham chiếu CHƯA thanh toán - webhook SePay dùng để đối
    chiếu nội dung chuyển khoản. Scan toàn bảng chấp nhận được ở quy mô app
    này (không cần index/phân trang)."""
    conn = get_conn()
    rows = conn.execute("SELECT reference_code FROM pending_payments WHERE status = 'pending'").fetchall()
    conn.close()
    return [r["reference_code"] for r in rows]


def get_pending_payments_by_amount(amount_vnd: int) -> list[dict]:
    """Lớp DỰ PHÒNG khi QR không nhúng được nội dung riêng từng giao dịch (VD
    QR tĩnh tạo qua SePay, đặt sẵn số tiền nhưng dùng chung 1 nội dung cho mọi
    lượt) - webhook đối chiếu theo ĐÚNG số tiền thay vì nội dung. Nếu có nhiều
    hơn 1 kết quả (2 người đang cùng chờ thanh toán đúng gói/giá đó) thì main.py
    KHÔNG được tự đoán, phải coi là mập mờ và chờ đối soát thủ công."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM pending_payments WHERE status = 'pending' AND amount_vnd = %s", (amount_vnd,)
    ).fetchall()
    conn.close()
    return rows


def finalize_payment(reference_code: str, package: dict, bonus_fn) -> dict | None:
    """Xác nhận 1 giao dịch ĐÃ THANH TOÁN THẬT (gọi từ webhook SePay sau khi
    đã đối chiếu nội dung + số tiền khớp) - đánh dấu paid + tăng purchase_count
    + cộng key TRONG CÙNG 1 TRANSACTION (không tách 3 lượt get_conn() riêng)
    để không bao giờ rơi vào tình huống "đã đánh dấu paid nhưng crash giữa
    chừng trước khi cộng key" - lúc đó SePay đã nhận 200 nên sẽ không gọi lại,
    tiền thật sẽ mất trắng không cộng được key nếu tách rời từng bước.

    Trả về None nếu reference_code không tồn tại HOẶC đã được xử lý từ trước
    (status không còn là 'pending') - đây chính là cơ chế chống cộng 2 lần khi
    SePay gọi lại webhook trùng (at-least-once delivery)."""
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
    """Đặt thẳng purchase_count - dùng cho công cụ admin (xem
    hacker prompt/reset_purchase_count.py), không dùng trong luồng mua bình
    thường (xem increment_purchase_count)."""
    conn = get_conn()
    conn.execute("UPDATE users SET purchase_count = %s WHERE id = %s", (count, user_id))
    conn.commit()
    conn.close()


def increment_purchase_count(user_id: int) -> int:
    """Tăng purchase_count thêm 1 (1 lượt mua thành công) - trả về giá trị
    MỚI để main.py tính bonus theo đúng mốc ngay lượt vừa chạm tới."""
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
    """Xoá vĩnh viễn tài khoản: mọi phiên đăng nhập + tiến độ đã lưu + giao
    dịch (đã/đang chờ thanh toán) của user này. Không có ràng buộc khoá ngoại/
    cascade ở schema nên xoá thủ công từng bảng liên quan."""
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
    """Lưu góp ý thẳng vào DB thay vì mailto: (mailto chỉ mở sẵn 1 email nháp,
    KHÔNG tự gửi - im lặng không có gì xảy ra nếu máy người dùng chưa cấu hình
    ứng dụng mail mặc định). Xem lại bằng hacker prompt/view_feedback.py."""
    conn = get_conn()
    conn.execute("INSERT INTO feedback (name, content) VALUES (%s, %s)", (name or None, content))
    conn.commit()
    conn.close()
