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
    conn.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS keys INTEGER NOT NULL DEFAULT {INITIAL_KEYS}")
    conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS purchase_count INTEGER NOT NULL DEFAULT 0")
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
