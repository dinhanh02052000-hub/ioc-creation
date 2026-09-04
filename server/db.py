"""SQLite lưu user đăng nhập Google + tiến độ học - persistent qua các lần
restart server, khác hẳn session_store.py (in-memory, chỉ sống trong 1 phiên
chat AI đang làm dở). File .db nằm cạnh main.py, không commit lên git (xem
.gitignore) vì chứa dữ liệu người dùng thật."""

import json
import secrets
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "ioc_users.db"

# Số key tặng khi 1 tài khoản Google đăng nhập LẦN ĐẦU TIÊN (xem upsert_user).
# Cũng dùng làm giá trị migrate cho user đã có sẵn từ trước khi tính năng key
# ra mắt - để không ai bị khoá AI đột ngột ngay sau khi cập nhật.
INITIAL_KEYS = 15


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            google_sub TEXT UNIQUE NOT NULL,
            email TEXT,
            name TEXT,
            picture TEXT,
            keys INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS progress (
            user_id INTEGER PRIMARY KEY,
            data_json TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # Migrate DB đã tồn tại từ trước khi có cột "keys" (CREATE TABLE IF NOT
    # EXISTS ở trên là no-op với bảng đã có sẵn) - grandfathering: user cũ
    # cũng được INITIAL_KEYS luôn, không bị khoá AI đột ngột sau khi cập nhật.
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "keys" not in cols:
        # SQLite không cho bind param trong DEFAULT của ALTER TABLE - INITIAL_KEYS
        # là hằng số int cố định trong code (không phải input người dùng) nên
        # nhét thẳng vào chuỗi SQL ở đây an toàn, không có rủi ro injection.
        conn.execute(f"ALTER TABLE users ADD COLUMN keys INTEGER NOT NULL DEFAULT {INITIAL_KEYS}")
    conn.commit()
    conn.close()


def upsert_user(google_sub: str, email: str, name: str, picture: str) -> sqlite3.Row:
    """Tặng INITIAL_KEYS CHỈ khi đây là lần đăng nhập ĐẦU TIÊN (insert thật sự
    thành công) - dùng INSERT trước, bắt IntegrityError để fallback sang
    UPDATE (không đụng cột keys) thay vì kiểu "SELECT kiểm tra tồn tại rồi mới
    quyết định" - tránh race khi 2 request đăng nhập gần như đồng thời (VD 2
    tab) cùng tưởng là "chưa có" rồi tặng key 2 lần: ràng buộc UNIQUE(google_sub)
    của SQLite đảm bảo chỉ 1 INSERT có thể thắng, request còn lại chắc chắn rơi
    vào nhánh UPDATE."""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO users (google_sub, email, name, picture, keys) VALUES (?, ?, ?, ?, ?)",
            (google_sub, email, name, picture, INITIAL_KEYS),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.execute(
            "UPDATE users SET email = ?, name = ?, picture = ? WHERE google_sub = ?",
            (email, name, picture, google_sub),
        )
        conn.commit()
    user = conn.execute("SELECT * FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
    conn.close()
    return user


def get_keys(user_id: int) -> int:
    conn = get_conn()
    row = conn.execute("SELECT keys FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row["keys"] if row else 0


def deduct_keys(user_id: int, amount: int) -> bool:
    """Trừ key NGUYÊN TỬ: kiểm tra đủ số dư và trừ trong CÙNG 1 câu UPDATE
    (WHERE keys >= amount) thay vì đọc số dư rồi ghi lại riêng - tránh race
    khi 2 request gần như đồng thời cùng đọc thấy đủ key rồi cùng trừ. Trả về
    False nếu không đủ (không có row nào khớp WHERE) - KHÔNG trừ gì cả."""
    conn = get_conn()
    cur = conn.execute("UPDATE users SET keys = keys - ? WHERE id = ? AND keys >= ?", (amount, user_id, amount))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn = get_conn()
    conn.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
    conn.commit()
    conn.close()
    return token


def get_user_by_token(token: str) -> sqlite3.Row | None:
    conn = get_conn()
    row = conn.execute(
        """SELECT users.* FROM sessions JOIN users ON sessions.user_id = users.id
           WHERE sessions.token = ?""",
        (token,),
    ).fetchone()
    conn.close()
    return row


def delete_session(token: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def delete_user(user_id: int) -> None:
    """Xoá vĩnh viễn tài khoản: mọi phiên đăng nhập + tiến độ đã lưu của user
    này. Không có ràng buộc khoá ngoại/cascade ở schema nên xoá thủ công cả 3
    bảng liên quan."""
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM progress WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def save_progress(user_id: int, data: dict) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO progress (user_id, data_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(user_id) DO UPDATE SET
             data_json = excluded.data_json, updated_at = CURRENT_TIMESTAMP""",
        (user_id, json.dumps(data)),
    )
    conn.commit()
    conn.close()


def load_progress(user_id: int) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT data_json FROM progress WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return {}
    try:
        return json.loads(row["data_json"])
    except (TypeError, ValueError):
        return {}
