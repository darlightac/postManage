"""根据 SVG 设计生成应用图标（渐变背景 + 双色箭头）"""

from pathlib import Path
from PIL import Image, ImageDraw


def hex2rgb(h: str):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lerp(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


# 设计稿坐标系为 512x512
BG_STOPS = [(0.0, hex2rgb('#0f0c29')), (0.5, hex2rgb('#302b63')), (1.0, hex2rgb('#24243e'))]
SEND_COLORS = (hex2rgb('#f7971e'), hex2rgb('#ffd200'))
RECV_COLORS = (hex2rgb('#00d2ff'), hex2rgb('#3a7bd5'))


def bg_color_at(x: int, y: int, size: int):
    """对角线渐变色 (0,0) -> (1,1)"""
    t = (x + y) / (2 * (size - 1)) if size > 1 else 0.0
    if t <= 0.5:
        return lerp(BG_STOPS[0][1], BG_STOPS[1][1], t / 0.5)
    return lerp(BG_STOPS[1][1], BG_STOPS[2][1], (t - 0.5) / 0.5)


def draw_polyline(draw: ImageDraw.ImageDraw, pts, color_at, width: int):
    """绘制渐变折线（圆角端点）"""
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        length = max(2, int(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5))
        prev = (x1, y1)
        for j in range(1, length + 1):
            t = j / length
            cur = (x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
            midx = (prev[0] + cur[0]) / 2
            draw.line([prev, cur], fill=color_at(midx), width=width)
            prev = cur
    # 圆角端点
    r = width / 2
    for p in (pts[0], pts[-1]):
        draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=color_at(p[0]))


def make_icon(size: int) -> Image.Image:
    """生成指定尺寸的图标"""
    s = size / 512

    # 1. 渐变背景
    grad = Image.new('RGB', (size, size))
    px = grad.load()
    for y in range(size):
        for x in range(size):
            px[x, y] = bg_color_at(x, y, size)

    # 2. 圆角矩形蒙版
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(110 * s), fill=255
    )

    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    draw = ImageDraw.Draw(img)

    width = max(1, int(26 * s))

    # 3. 发送箭头（向右，黄色渐变）
    send_color = lambda x: lerp(SEND_COLORS[0], SEND_COLORS[1], (x / s - 130) / 220)
    draw_polyline(draw, [(130 * s, 210 * s), (350 * s, 210 * s)], send_color, width)
    draw_polyline(draw, [(310 * s, 170 * s), (350 * s, 210 * s), (310 * s, 250 * s)], send_color, width)

    # 4. 接收箭头（向左，蓝色渐变）
    recv_color = lambda x: lerp(RECV_COLORS[0], RECV_COLORS[1], (382 - x / s) / 220)
    draw_polyline(draw, [(382 * s, 310 * s), (162 * s, 310 * s)], recv_color, width)
    draw_polyline(draw, [(202 * s, 270 * s), (162 * s, 310 * s), (202 * s, 350 * s)], recv_color, width)

    # 复制到干净的图像对象，避免 PNG 携带 tRNS 元数据（libpng 警告）
    clean = Image.new('RGBA', img.size)
    clean.paste(img, (0, 0))
    return clean


def generate_icons():
    """生成所有尺寸的图标到 app/resources/icons"""
    base_dir = Path(__file__).parent.parent
    icons_dir = base_dir / "app" / "resources" / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)

    sizes = [16, 32, 64, 128, 256, 512]
    for size in sizes:
        icon = make_icon(size)
        icon.save(icons_dir / f"icon_{size}.png")
        print(f"Generated icon_{size}.png")

    # ICO 文件（多尺寸，main.py 使用 postmanage.ico）
    icon_256 = make_icon(256)
    icon_256.save(
        icons_dir / "postmanage.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("Generated postmanage.ico")


if __name__ == "__main__":
    generate_icons()
