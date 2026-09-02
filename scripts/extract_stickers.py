"""Cắt từng sticker trong 1 sheet (nền trắng phẳng) thành các file PNG riêng,
nền trong suốt thật. Mỗi sticker trong sheet gốc được vẽ kiểu "die-cut sticker"
gồm 3 lớp lồng nhau: [nền trang trắng phẳng] -> [viền mỏng màu xám/navy] ->
[viền trắng dày ~8-10px] -> [hoạ tiết thật]. Chỉ flood-fill 1 ngưỡng duy nhất
sẽ dừng lại ở lớp viền xám (không lọt được vào viền trắng dày bên trong), để
lại 1 khung/viền trắng lộ liễu quanh mỗi icon khi đặt lên nền tối - đây chính
là lỗi "còn nền trắng" người dùng thấy trên world1.html.

Cách xử lý đúng: hysteresis 2 ngưỡng (giống Canny) thay vì flood-fill 1 ngưỡng:
  - "seed": pixel CHẮC CHẮN là nền (rất gần trắng, ngưỡng chặt SEED_THRESHOLD).
  - "loose": pixel CÓ THỂ là nền (gần trắng hơn, ngưỡng lỏng LOOSE_THRESHOLD -
    đủ rộng để phủ luôn lớp viền xám mỏng nối 2 lớp trắng với nhau).
  - Label các vùng liên thông (8-hướng) trên mask "loose"; vùng loose nào có
    chạm tới ít nhất 1 pixel "seed" thì TOÀN BỘ vùng đó là nền - nhờ vậy nền
    phẳng bên ngoài + viền xám mỏng + viền trắng dày bên trong được nối liền
    thành 1 vùng nền duy nhất, xoá sạch cả 2 lớp viền trắng, chỉ giữ lại đúng
    phần hoạ tiết (nét đậm màu) của sticker.
"""

from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

SRC = Path(r"C:\Users\Admin\Downloads\Gemini_Generated_Image_auyyy8auyyy8auyy.png")
OUT_DIR = Path(r"c:\Users\Admin\Desktop\ioc creation\assets\images\world1-decor")

SEED_THRESHOLD = 40
LOOSE_THRESHOLD = 190
MIN_COMPONENT_AREA = 400  # loại nhiễu nhỏ
PADDING = 3

NAMES = [
    "owl-guardian", "rune-snake", "clockwork-butterfly", "mushroom-trio", "leaf-mask",
    "antler-key", "owl-perched", "badger", "galaxy-shell", "dragonfly-pair", "glowing-orb",
    "skull-bat", "star-frog", "crescent-moon", "acorn-lock", "feather", "spiderweb-gem",
    "stone-tower", "ram-totem", "tree-of-life", "shadow-fox",
]


def main():
    img = Image.open(SRC).convert("RGB")
    arr = np.asarray(img).astype(np.float64)
    h, w, _ = arr.shape

    dist_to_white = np.sqrt(((arr - 255) ** 2).sum(axis=2))

    seed = dist_to_white < SEED_THRESHOLD
    loose = dist_to_white < LOOSE_THRESHOLD

    structure = np.ones((3, 3), dtype=int)
    loose_labeled, _ = ndimage.label(loose, structure=structure)

    # Vùng loose nào chứa >=1 pixel seed ở viền ảnh -> chắc chắn nối thông ra
    # nền ngoài -> cả vùng loose đó là nền (xoá cả viền xám + viền trắng dày).
    seed_on_border = seed.copy()
    seed_on_border[1:-1, 1:-1] = False  # chỉ giữ seed pixels nằm đúng trên viền ảnh
    border_bg_labels = set(np.unique(loose_labeled[seed_on_border]).tolist())
    border_bg_labels.discard(0)

    is_background = np.isin(loose_labeled, list(border_bg_labels))
    foreground = ~is_background

    fg_labeled, fg_num = ndimage.label(foreground, structure=structure)
    print(f"Found {fg_num} connected foreground components")

    objs = ndimage.find_objects(fg_labeled)
    boxes = []
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        ys, xs = sl
        area = (fg_labeled[sl] == i).sum()
        if area < MIN_COMPONENT_AREA:
            continue
        boxes.append((ys.start, ys.stop, xs.start, xs.stop, area))

    print(f"Kept {len(boxes)} components after area filter")
    if len(boxes) != len(NAMES):
        raise SystemExit(f"Expected {len(NAMES)} components, got {len(boxes)} - inspect thresholds before saving.")

    boxes_with_center = [(((b[0] + b[1]) / 2, (b[2] + b[3]) / 2), b) for b in boxes]
    boxes_with_center.sort(key=lambda t: t[0][0])

    rows = []
    row_tol = 60
    for center, b in boxes_with_center:
        placed = False
        for row in rows:
            if abs(row[0][0][0] - center[0]) < row_tol:
                row.append((center, b))
                placed = True
                break
        if not placed:
            rows.append([(center, b)])

    ordered = []
    for row in rows:
        row.sort(key=lambda t: t[0][1])
        ordered.extend(row)

    print(f"Grid rows detected: {len(rows)}, sizes: {[len(r) for r in rows]}")

    # Alpha mượt ở viền (chống răng cưa): trong vùng nền, alpha tỉ lệ theo độ
    # "trắng" (dist_to_white) trong dải soft band; trong vùng hoạ tiết luôn
    # alpha=255 dù có pixel trắng thật bên trong (mắt cú, mặt trăng...).
    soft_low, soft_high = 10.0, 40.0
    soft_alpha = np.clip((dist_to_white - soft_low) / (soft_high - soft_low) * 255, 0, 255)
    alpha = np.where(is_background, soft_alpha, 255).astype(np.uint8)
    rgba = np.dstack([np.asarray(img), alpha])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for name, (center, (y0, y1, x0, x1, area)) in zip(NAMES, ordered):
        py0 = max(0, y0 - PADDING)
        py1 = min(h, y1 + PADDING)
        px0 = max(0, x0 - PADDING)
        px1 = min(w, x1 + PADDING)
        crop = rgba[py0:py1, px0:px1]
        out_path = OUT_DIR / f"{name}.png"
        Image.fromarray(crop, mode="RGBA").save(out_path, optimize=True)
        results.append((name, px0, py0, px1 - px0, py1 - py0, area, out_path.stat().st_size))

    return results


if __name__ == "__main__":
    results = main()
    for name, x, y, w, h, area, fsize in results:
        print(f"{name:22s} pos=({x},{y}) size=({w}x{h}) area={area} file={fsize}B")
