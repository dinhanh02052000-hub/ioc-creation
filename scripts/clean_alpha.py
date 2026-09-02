# Xoá nền ca-rô "giả trong suốt" bị in cứng vào pixel (ảnh RGBA nhưng alpha=255
# khắp nơi - không phải preview trong suốt thật, ảnh gốc đã bị flatten mất
# kênh alpha). Quy trình:
#   1. Dò 2 màu nền chủ đạo từ dải viền ảnh (mỗi ảnh có tông nền riêng).
#   2. Xoá toàn cục pixel nào gần 1 trong 2 màu đó (ngưỡng vừa phải - đủ rộng
#      để bắt nhiễu JPEG quanh 2 tông nền, đủ hẹp để không lem vào màu chủ thể).
#   3. Dọn hậu kỳ 2 lượt: pixel đặc còn sót nhưng bị bao quanh chủ yếu bởi
#      vùng đã trong suốt (vệt lưới/watermark mảnh còn sót lại) -> xoá luôn.
#   4. Cắt sát viền theo bounding box thật của chủ thể.

import os
from collections import Counter

from PIL import Image

SRC_DIR = r"c:\Users\Admin\Desktop\ioc creation\world1iconbackground"
DEST_DIR = r"c:\Users\Admin\Desktop\ioc creation\assets\images\world1-decor"

FILE_MAP = {
    "Gemini_Generated_Image_vbcby2vbcby2vbcb.png": "mystic-key",
    "Gemini_Generated_Image_oyc4kpoyc4kpoyc4.png": "armillary-orb",
    "Gemini_Generated_Image_emw123emw123emw1.png": "crystal-lantern",
    "Gemini_Generated_Image_8zs3ks8zs3ks8zs3.png": "rune-gear",
    "Gemini_Generated_Image_8jmazq8jmazq8jma.png": "gear-crown",
    "Gemini_Generated_Image_57zren57zren57zr.png": "clockwork-flower",
    "Gemini_Generated_Image_920muu920muu920m.png": "world-tree",
    "Gemini_Generated_Image_uhwha9uhwha9uhwh.png": "clockwork-bear",
    "Gemini_Generated_Image_x4utv7x4utv7x4ut.png": "clockwork-frog",
    "Gemini_Generated_Image_1xxifw1xxifw1xxi.png": "clockwork-hedgehog",
    "Gemini_Generated_Image_sa0e5rsa0e5rsa0e.png": "clockwork-stag",
    "Gemini_Generated_Image_c3yq8fc3yq8fc3yq.png": "clockwork-owl",
}

COLOR_THRESHOLD = 45
BORDER_SAMPLE = 20
N_BG_COLORS = 6


def color_dist2(c1, c2):
    return (c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2


def detect_bg_colors(img, w, h, n=N_BG_COLORS):
    counter = Counter()
    for x in range(0, w, 1):
        for y in list(range(0, BORDER_SAMPLE)) + list(range(h - BORDER_SAMPLE, h)):
            counter[img.getpixel((x, y))[:3]] += 1
    for y in range(0, h, 1):
        for x in list(range(0, BORDER_SAMPLE)) + list(range(w - BORDER_SAMPLE, w)):
            counter[img.getpixel((x, y))[:3]] += 1
    most_common = [c for c, _ in counter.most_common(60)]
    picked = []
    for c in most_common:
        if all(color_dist2(c, p) > 12 ** 2 for p in picked):
            picked.append(c)
        if len(picked) == n:
            break
    return picked


def isolated_cleanup(pixels, w, h, radius, ratio):
    alpha_grid = [[pixels[x, y][3] for x in range(w)] for y in range(h)]
    to_clear = []
    for y in range(h):
        y0, y1 = max(0, y - radius), min(h, y + radius + 1)
        for x in range(w):
            if alpha_grid[y][x] == 0:
                continue
            x0, x1 = max(0, x - radius), min(w, x + radius + 1)
            total = 0
            transparent = 0
            for yy in range(y0, y1):
                row = alpha_grid[yy]
                for xx in range(x0, x1):
                    total += 1
                    if row[xx] == 0:
                        transparent += 1
            if transparent / total > ratio:
                to_clear.append((x, y))
    for x, y in to_clear:
        r, g, b, a = pixels[x, y]
        pixels[x, y] = (r, g, b, 0)


def remove_checker_bg(img):
    img = img.convert("RGBA")
    w, h = img.size
    bg_colors = detect_bg_colors(img, w, h)
    thresh2 = COLOR_THRESHOLD ** 2

    pixels = img.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if any(color_dist2((r, g, b), c) <= thresh2 for c in bg_colors):
                pixels[x, y] = (r, g, b, 0)

    isolated_cleanup(pixels, w, h, radius=3, ratio=0.75)
    isolated_cleanup(pixels, w, h, radius=4, ratio=0.6)

    bbox = img.getbbox()
    if bbox:
        pad = 8
        left, top, right, bottom = bbox
        left = max(0, left - pad)
        top = max(0, top - pad)
        right = min(w, right + pad)
        bottom = min(h, bottom + pad)
        img = img.crop((left, top, right, bottom))
    return img


def main():
    os.makedirs(DEST_DIR, exist_ok=True)
    for src_name, clean_name in FILE_MAP.items():
        src_path = os.path.join(SRC_DIR, src_name)
        dest_path = os.path.join(DEST_DIR, f"{clean_name}.png")
        img = Image.open(src_path)
        result = remove_checker_bg(img)
        result.save(dest_path, "PNG")
        print(f"{clean_name}.png  size={result.size}")


if __name__ == "__main__":
    main()
