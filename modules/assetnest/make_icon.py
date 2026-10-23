"""生成应用图标（ico + png）。"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_ICO = os.path.join(ROOT, "assets", "assetnest.ico")
OUT_PNG = os.path.join(ROOT, "web", "img", "app-icon.png")


def rounded_gradient(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(img)
    for y in range(size):
        for x in range(size):
            k = (x / size * 0.45 + y / size * 0.55)
            r = int(158 + (91 - 158) * k)
            g = int(139 + (69 - 139) * k)
            b = int(255 + (216 - 255) * k)
            d.point((x, y), (r, g, b))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.26), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def draw_cube(size: int) -> Image.Image:
    img = rounded_gradient(size)
    d = ImageDraw.Draw(img)
    s = size
    cx, cy = s / 2, s / 2
    R = s * 0.255
    dx = R * 0.94
    y_top = cy - R * 1.12
    y_bot = cy + R * 1.12
    y_mid = R * 0.56
    top = (cx, y_top)
    ur = (cx + dx, y_top + y_mid)
    lr = (cx + dx, y_bot - y_mid)
    bot = (cx, y_bot)
    ll = (cx - dx, y_bot - y_mid)
    ul = (cx - dx, y_top + y_mid)
    mid = (cx, cy)
    lw = max(2, int(s * 0.032))
    white = (255, 255, 255)
    d.line([top, ur, lr, bot, ll, ul, top], fill=white, width=lw, joint="curve")
    d.line([mid, top], fill=white, width=lw)
    d.line([mid, ll], fill=white, width=lw)
    d.line([mid, lr], fill=white, width=lw)
    r = lw / 2
    for pt in (top, ur, lr, bot, ll, ul, mid):
        d.ellipse([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r], fill=white)
    return img


def main() -> None:
    os.makedirs(os.path.dirname(OUT_ICO), exist_ok=True)
    os.makedirs(os.path.dirname(OUT_PNG), exist_ok=True)
    big = draw_cube(1024)
    big.save(OUT_PNG)
    big.resize((256, 256), Image.LANCZOS).save(
        OUT_ICO, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon ok", OUT_ICO, OUT_PNG)


if __name__ == "__main__":
    main()
