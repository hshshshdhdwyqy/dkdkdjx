"""ساخت بنر «NRT self» با عکس پروفایل خود کاربر وسط دایره.

make_banner(photo_bytes_or_None, out_path, initial="N")  -> بنر 1280x720 رو می‌سازه
refresh_banner(client, out_path)                          -> عکس پروفایل اکانت رو می‌گیره و بنر می‌سازه
"""
import io
import math
import os
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720
HERE = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(HERE, "assets", "fonts", "Poppins-Bold.ttf")
TITLE = "NRT self"


def _font(size):
    for p in (FONT_PATH, "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _background():
    # گرادیانت قطری بنفش تیره -> قرمز تیره + ستاره‌های ریز
    base = Image.new("RGB", (W, H))
    px = base.load()
    c1, c2, c3 = (14, 6, 34), (58, 14, 96), (96, 10, 40)
    for y in range(H):
        for x in range(W):
            t = (x / W * 0.6 + y / H * 0.4)
            if t < 0.5:
                k = t / 0.5
                a, b = c1, c2
            else:
                k = (t - 0.5) / 0.5
                a, b = c2, c3
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))
    rnd = random.Random(7)
    d = ImageDraw.Draw(base)
    for _ in range(140):
        x, y, r = rnd.randrange(W), rnd.randrange(H), rnd.choice((1, 1, 2))
        v = rnd.randint(120, 230)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(v, v, 255))
    return base


def _glow(size, box, color, blur, width=None):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if width:
        d.ellipse(box, outline=color, width=width)
    else:
        d.ellipse(box, fill=color)
    return layer.filter(ImageFilter.GaussianBlur(blur))


def _circle_photo(img, d):
    img = img.convert("RGB")
    s = min(img.size)
    img = img.crop(((img.width - s) // 2, (img.height - s) // 2,
                    (img.width + s) // 2, (img.height + s) // 2)).resize((d, d), Image.LANCZOS)
    mask = Image.new("L", (d * 4, d * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, d * 4 - 1, d * 4 - 1), fill=255)
    mask = mask.resize((d, d), Image.LANCZOS)
    out = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _placeholder(d, initial):
    img = Image.new("RGB", (d, d), (40, 20, 70))
    dr = ImageDraw.Draw(img)
    f = _font(int(d * 0.5))
    bb = dr.textbbox((0, 0), initial, font=f)
    dr.text(((d - (bb[2] - bb[0])) / 2 - bb[0], (d - (bb[3] - bb[1])) / 2 - bb[1]),
            initial, font=f, fill=(235, 220, 255))
    return img


def _gradient_text(text, font, colors):
    tmp = Image.new("L", (W, 260), 0)
    d = ImageDraw.Draw(tmp)
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((W - tw) / 2 - bb[0], (260 - th) / 2 - bb[1]), text, font=font, fill=255)
    grad = Image.new("RGBA", (W, 260))
    gp = grad.load()
    x0, x1 = (W - tw) / 2, (W + tw) / 2
    for x in range(W):
        t = min(1, max(0, (x - x0) / max(1, x1 - x0)))
        seg = t * (len(colors) - 1)
        i = min(int(seg), len(colors) - 2)
        k = seg - i
        col = tuple(int(colors[i][j] + (colors[i + 1][j] - colors[i][j]) * k) for j in range(3))
        for y in range(260):
            gp[x, y] = col + (255,)
    grad.putalpha(tmp)
    return grad, tmp


def make_banner(photo_bytes, out_path, initial="N"):
    bg = _background().convert("RGBA")
    cx, cy = W // 2, 285
    R = 185                       # شعاع دایره‌ی عکس
    ring = 16

    # هاله‌ی نورانی پشت دایره
    bg = Image.alpha_composite(bg, _glow((W, H), (cx - R - 40, cy - R - 40, cx + R + 40, cy + R + 40),
                                         (200, 40, 255, 170), 45))
    bg = Image.alpha_composite(bg, _glow((W, H), (cx - R - 12, cy - R - 12, cx + R + 12, cy + R + 12),
                                         (255, 40, 90, 200), 14, width=10))

    # حلقه‌ی گرادیانتی دور عکس
    rd = (R + ring) * 2
    ring_img = Image.new("RGBA", (rd, rd))
    rp = ring_img.load()
    for y in range(rd):
        for x in range(rd):
            t = (x + y) / (2 * rd)
            rp[x, y] = (int(255 * (1 - t) + 150 * t), int(40 * (1 - t) + 50 * t),
                        int(90 * (1 - t) + 255 * t), 255)
    m = Image.new("L", (rd * 3, rd * 3), 0)
    md = ImageDraw.Draw(m)
    md.ellipse((0, 0, rd * 3 - 1, rd * 3 - 1), fill=255)
    md.ellipse((ring * 3, ring * 3, rd * 3 - ring * 3, rd * 3 - ring * 3), fill=0)
    ring_img.putalpha(m.resize((rd, rd), Image.LANCZOS))
    bg.alpha_composite(ring_img, (cx - R - ring, cy - R - ring))

    # عکس پروفایل (یا حرف اول اسم)
    try:
        src = Image.open(io.BytesIO(photo_bytes)) if photo_bytes else None
    except Exception:
        src = None
    if src is None:
        src = _placeholder(R * 2, (initial or "N")[:1].upper())
    bg.alpha_composite(_circle_photo(src, R * 2), (cx - R, cy - R))

    # متن NRT self با هاله
    f = _font(135)
    grad, mask = _gradient_text(TITLE, f, [(255, 60, 70), (200, 60, 255), (90, 120, 255)])
    ty = 590
    glow = Image.new("RGBA", (W, 260), (255, 70, 200, 255))
    glow.putalpha(mask.filter(ImageFilter.GaussianBlur(18)))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.alpha_composite(glow, (0, ty - 130))
    layer.alpha_composite(grad, (0, ty - 130))
    bg = Image.alpha_composite(bg, layer)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    bg.convert("RGB").save(out_path, "JPEG", quality=90)
    return out_path


async def refresh_banner(client, out_path):
    """عکس پروفایل فعلی اکانت رو می‌گیره و بنر رو دوباره می‌سازه (اگه عکس عوض شده باشه، به‌روز می‌شه)."""
    me = await client.get_me()
    data = None
    try:
        buf = io.BytesIO()
        res = await client.download_profile_photo(me, file=buf)
        data = buf.getvalue() if res and buf.getbuffer().nbytes else None
    except Exception as ex:
        print("banner: profile photo error:", ex)
    name = (getattr(me, "first_name", None) or getattr(me, "username", None) or "N")
    make_banner(data, out_path, name)
    return out_path


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else None
    make_banner(open(p, "rb").read() if p else None, "preview_banner.jpg")
    print("preview_banner.jpg")
