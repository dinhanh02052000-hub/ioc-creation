"""Đường dẫn & cấu hình dùng chung cho backend.

Quy tắc map (worldId, level) -> file knowledge base: mỗi world ứng với 1 bộ
tiền tố + thư mục riêng. Muốn thêm world mới chỉ cần thêm 1 dòng vào
WORLD_KB_CONFIG, không cần sửa logic nơi khác.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_DIR = BASE_DIR / "database"
ENGINE_DIR = DATABASE_DIR / "engine"

WORLD_KB_CONFIG = {
    "world-1": {
        "prefix": "vocab-b2",
        "folder": DATABASE_DIR / "vocab b2 database",
    },
    "world-2": {
        "prefix": "vocab-c1",
        "folder": DATABASE_DIR / "vocab c1 database",
    },
}


def get_kb_path(world_id: str, level: int) -> Path:
    cfg = WORLD_KB_CONFIG.get(world_id)
    if not cfg:
        raise ValueError(f"Unknown worldId: {world_id}")
    filename = f"{cfg['prefix']}-{level:03d}.json"
    path = cfg["folder"] / filename
    if not path.exists():
        raise FileNotFoundError(f"Knowledge base not found: {path}")
    return path
