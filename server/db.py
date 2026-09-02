"""SQLite lưu user đăng nhập Google + tiến độ học - persistent qua các lần
restart server, khác hẳn session_store.py (in-memory, chỉ sống trong 1 phiên
chat AI đang làm dở). File .db nằm cạnh main.py, không commit lên git (xem
.gitignore) vì chứa dữ liệu người dùng thật."""

import json
import secrets
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "ioc_users.db"


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
    conn.commit()
    conn.close()


def upsert_user(google_sub: str, email: str, name: str, picture: str) -> sqlite3.Row:
    conn = get_conn()
    conn.execute(
        """INSERT INTO users (google_sub, email, name, picture) VALUES (?, ?, ?, ?)
           ON CONFLICT(google_sub) DO UPDATE SET
             email = excluded.email, name = excluded.name, picture = excluded.picture""",
        (google_sub, email, name, picture),
    )
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
    conn.close()
    return user


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
