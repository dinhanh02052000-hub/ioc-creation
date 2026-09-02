"""Cắt từng sticker trong sheet World 2 (ice theme) thành PNG riêng, nền trong
suốt THẬT. Sheet có nền checkerboard GIẢ (bake cứng vào pixel, alpha=255 khắp
ảnh). Ban đầu thử flood-fill theo vị trí ô caro (giả định lưới đều period=18)
nhưng THẤT BẠI vì caro bị trôi pha nhẹ trên ảnh lớn (không phải lưới toàn cục
hoàn hảo) -> nhiều vùng nền rõ ràng vẫn không khớp đúng vị trí dự đoán.

Quay lại đúng phương pháp đã chứng minh hiệu quả ở scripts/clean_alpha.py:
KHÔNG dùng flood-fill/vị trí, chỉ dùng khoảng cách MÀU toàn cục tới các màu
nền lấy mẫu từ viền ảnh (không quan tâm pixel đó nằm ở đâu), sau đó dọn hậu kỳ
bằng tỉ lệ trong suốt xung quanh (ăn dần các vệt/viền mỏng còn sót, không cần
biết trước hình dạng caro). Cách này miễn nhiễm với việc caro trôi pha vì
hoàn toàn không dựa vào vị trí (x, y).

Sau khi có mask trong suốt sạch, mới tách từng sticker bằng connected-
components + bounding box, giống hệt extract_stickers.py (World 1).
"""

from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

SRC = Path(r"C:\Users\Admin\Downloads\Gemini_Generated_Image_p7tczup7tczup7tc.png")
OUT_DIR = Path(r"C:\Users\Admin\AppData\Local\Temp\claude\c--Users-Admin-Desktop-ioc-creation\351d30cd-1224-41ca-b7be-309547a7e82b\scratchpad\sticker_preview_ice")

BORDER_SAMPLE = 20
N_BG_COLORS = 6
COLOR_THRESHOLD = 38
MIN_COMPONENT_AREA = 500
PADDING = 4

# Gán tên theo VỊ TRÍ (x0,y0) đã đối chiếu bằng mắt với ảnh gốc (xem
# annotated_boxes debug), KHÔNG gán theo thứ tự "ordered" của thuật toán gom-
# hàng-rồi-sort-x - thứ tự đó phụ thuộc y-center nên dễ đổi khi bounding box
# đổi (VD sau khi gộp fragment nhỏ), làm sai lệch việc gán tên nếu gán cứng
# theo index.
POSITION_NAMES = [
    ((273, 44), "crystal-seal"),
    ((999, 36), "aurora-orb"),
    ((1287, 46), "snowflake-1"),
    ((1409, 61), "snowflake-2"),
    ((50, 46), "crystal-penguin"),
    ((656, 45), "crystal-polar-bear"),
    ((1254, 165), "snowflake-3"),
    ((1297, 244), "snowflake-4"),
    ((1365, 149), "snowflake-5"),
    ((1442, 242), "snowflake-6"),
    ((262, 282), "pine-tree-tall"),
    ((418, 313), "ice-mountain"),
    ((807, 340), "frost-reindeer"),
    ((1151, 315), "snowman"),
    ((45, 405), "pine-tree-small-a"),
    ((159, 459), "pine-tree-small-b"),
    ((1149, 476), "snowflake-7"),
    ((1286, 382), "campfire"),
]
POSITION_MATCH_TOLERANCE = 30


def detect_bg_colors(arr: np.ndarray, n=N_BG_COLORS) -> np.ndarray:
    h, w, _ = arr.shape
    border_pixels = np.concatenate([
        arr[:BORDER_SAMPLE].reshape(-1, 3),
        arr[-BORDER_SAMPLE:].reshape(-1, 3),
        arr[:, :BORDER_SAMPLE].reshape(-1, 3),
        arr[:, -BORDER_SAMPLE:].reshape(-1, 3),
    ])
    colors, counts = np.unique(border_pixels, axis=0, return_counts=True)
    order = np.argsort(-counts)
    colors = colors[order]

    picked = []
    for c in colors:
        if all(np.sum((c.astype(np.float64) - p) ** 2) > 12 ** 2 for p in picked):
            picked.append(c.astype(np.float64))
        if len(picked) == n:
            break
    return np.array(picked)


def isolated_cleanup(alpha: np.ndarray, radius: int, ratio: float) -> np.ndarray:
    """Pixel còn đặc (alpha>0) nhưng phần lớn hàng xóm đã trong suốt -> xoá
    luôn (vệt/viền mỏng còn sót lại của caro/anti-alias)."""
    size = radius * 2 + 1
    transparent_frac = ndimage.uniform_filter((alpha == 0).astype(np.float64), size=size, mode="constant", cval=1.0)
    to_clear = (alpha > 0) & (transparent_frac > ratio)
    alpha = alpha.copy()
    alpha[to_clear] = 0
    return alpha


def main():
    img = Image.open(SRC).convert("RGB")
    arr = np.asarray(img).astype(np.float64)
    h, w, _ = arr.shape

    bg_colors = detect_bg_colors(arr)
    # Mỗi sticker còn có viền trắng "die-cut" RIÊNG (~255,255,255) SÁT cạnh
    # hoạ tiết - khác hẳn tông xám của nền caro nên không được border-sampling
    # bắt được (viền trắng chỉ xuất hiện cạnh icon, không lộ ra viền ngoài
    # cùng của cả tấm ảnh). Icon nằm sát nhau sẽ dính liền qua đúng lớp viền
    # trắng này nếu không thêm nó vào danh sách màu nền cần xoá.
    bg_colors = np.vstack([bg_colors, [[255.0, 255.0, 255.0]]])
    print(f"Detected {len(bg_colors)} background colors: {bg_colors.tolist()}")

    dist = np.stack([np.sqrt(((arr - c) ** 2).sum(axis=2)) for c in bg_colors], axis=0).min(axis=0)
    bg_candidate = dist <= COLOR_THRESHOLD

    structure = np.ones((3, 3), dtype=int)

    # Highlight sáng/gần trắng NẰM TRONG hoạ tiết (VD tuyết phản sáng trên
    # lưng gấu, mặt băng tinh thể bông tuyết) đôi khi cũng rơi vào ngưỡng màu
    # nền -> nếu xoá thẳng sẽ tạo lỗ thủng đen bên trong icon. Phân biệt bằng
    # DIỆN TÍCH vùng liên thông: nền thật là vùng caro/viền trắng RỘNG (hàng
    # nghìn px), còn highlight lọt ngưỡng chỉ là đốm nhỏ cô lập - loại các đốm
    # nhỏ (< HOLE_MIN_AREA) ra khỏi mask nền (coi là hoạ tiết, giữ opaque),
    # không cần closing/dãn-co gì cả nên không có rủi ro nối nhầm 2 icon sát
    # nhau như cách làm trước.
    HOLE_MIN_AREA = 350
    bg_labeled, _ = ndimage.label(bg_candidate, structure=structure)
    bg_sizes = ndimage.sum(bg_candidate, bg_labeled, index=np.arange(1, bg_labeled.max() + 1))
    small_bg_labels = np.where(bg_sizes < HOLE_MIN_AREA)[0] + 1
    real_bg = bg_candidate & ~np.isin(bg_labeled, small_bg_labels)

    alpha = np.where(real_bg, 0, 255).astype(np.uint8)
    alpha = isolated_cleanup(alpha, radius=3, ratio=0.75)
    alpha = isolated_cleanup(alpha, radius=4, ratio=0.6)

    foreground = alpha > 0

    # Vài icon vẫn còn sát nhau tới mức viền trắng riêng chạm nhau 1-2px -> ăn
    # mòn (erode) nhẹ để cắt đứt cầu nối mảnh này trước khi label, rồi bù lại
    # đúng bằng số pixel đã ăn mòn (+ PADDING) khi lấy bounding box - không
    # ảnh hưởng ảnh crop cuối cùng vì vẫn crop từ alpha mask GỐC (chưa erode),
    # erosion chỉ dùng để tách nhãn, không dùng để cắt pixel thật.
    EROSION = 1
    eroded_fg = ndimage.binary_erosion(foreground, iterations=EROSION, border_value=0)
    fg_labeled, fg_num = ndimage.label(eroded_fg, structure=structure)
    print(f"Found {fg_num} connected foreground components (after erosion={EROSION})")

    objs = ndimage.find_objects(fg_labeled)
    boxes = []
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        ys, xs = sl
        area = (fg_labeled[sl] == i).sum()
        if area < MIN_COMPONENT_AREA:
            continue
        y0 = max(0, ys.start - EROSION)
        y1 = min(alpha.shape[0], ys.stop + EROSION)
        x0 = max(0, xs.start - EROSION)
        x1 = min(alpha.shape[1], xs.stop + EROSION)
        boxes.append([y0, y1, x0, x1, area])

    print(f"Kept {len(boxes)} components after area filter (min_area={MIN_COMPONENT_AREA})")

    # Vài chi tiết nhỏ (đầu ngón chân, mẩu gạc...) đôi khi vẫn tách rời khỏi
    # icon chính dù đã closing - gộp mảnh nhỏ (area < SMALL_FRAGMENT_AREA) vào
    # icon lớn gần nhất nếu bbox của nó nằm sát/nằm trong bbox icon đó (nới
    # thêm biên dung sai), thay vì coi là 1 sticker riêng.
    SMALL_FRAGMENT_AREA = 3000
    MERGE_TOLERANCE = 40
    boxes.sort(key=lambda b: -b[4])  # to lon truoc
    merged = []
    for b in boxes:
        y0, y1, x0, x1, area = b
        if area >= SMALL_FRAGMENT_AREA:
            merged.append(b)
            continue
        host = None
        for m in merged:
            my0, my1, mx0, mx1, _ = m
            if (x0 >= mx0 - MERGE_TOLERANCE and x1 <= mx1 + MERGE_TOLERANCE and
                    y0 >= my0 - MERGE_TOLERANCE and y1 <= my1 + MERGE_TOLERANCE):
                host = m
                break
        if host is not None:
            host[0] = min(host[0], y0)
            host[1] = max(host[1], y1)
            host[2] = min(host[2], x0)
            host[3] = max(host[3], x1)
            host[4] += area
            print(f"  merged fragment area={area} pos=({x0},{y0}) into host bbox")
        else:
            merged.append(b)
    boxes = merged
    print(f"After small-fragment merge: {len(boxes)} components")

    boxes_with_center = [(((b[0] + b[1]) / 2, (b[2] + b[3]) / 2), b) for b in boxes]
    boxes_with_center.sort(key=lambda t: t[0][0])

    rows = []
    row_tol = 90
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

    rgba = np.dstack([np.asarray(img), alpha])

    print("\nBounding boxes (index: pos, size, area):")
    for idx, (center, (y0, y1, x0, x1, area)) in enumerate(ordered, start=1):
        print(f"{idx:2d}: pos=({x0},{y0}) size=({x1-x0}x{y1-y0}) area={area}")

    if len(ordered) != len(POSITION_NAMES):
        raise SystemExit(f"Expected {len(POSITION_NAMES)} components, got {len(ordered)} - fix mapping first.")

    named = []
    for center, (y0, y1, x0, x1, area) in ordered:
        best = min(POSITION_NAMES, key=lambda pn: (pn[0][0] - x0) ** 2 + (pn[0][1] - y0) ** 2)
        (rx, ry), name = best
        dist = ((rx - x0) ** 2 + (ry - y0) ** 2) ** 0.5
        if dist > POSITION_MATCH_TOLERANCE:
            raise SystemExit(f"No name match within tolerance for box pos=({x0},{y0}) (closest={name} dist={dist:.0f})")
        named.append((name, (y0, y1, x0, x1, area)))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for name, (y0, y1, x0, x1, area) in named:
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
    if results:
        for name, x, y, w, h, area, fsize in results:
            print(f"{name:22s} pos=({x},{y}) size=({w}x{h}) area={area} file={fsize}B")
