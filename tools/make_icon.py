"""Draw the app icon and write AppIcon.icns (PNG-based icns, no Apple tools needed)."""
import io, struct, sys
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf"


def draw(n):
    s = n / 1024
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = int(100 * s)
    d.rounded_rectangle([pad, pad, n - pad, n - pad], radius=int(185 * s), fill=(255, 255, 255, 255),
                        outline=(214, 214, 219, 255), width=max(1, int(6 * s)))
    red, ink, blue = (158, 13, 20), (28, 28, 30), (20, 77, 179)
    f_ch = ImageFont.truetype(FONT, int(150 * s))
    f_ly = ImageFont.truetype(FONT, int(96 * s))
    d.text((int(190 * s), int(205 * s)), "D/F#", font=f_ch, fill=red)
    d.text((int(560 * s), int(205 * s)), "G", font=f_ch, fill=red)
    for i, y in enumerate((395, 560, 725)):
        w = (640, 560, 470)[i]
        d.rounded_rectangle([int(190 * s), int(y * s), int((190 + w) * s), int((y + 44) * s)],
                            radius=int(22 * s), fill=ink if i != 1 else (90, 90, 96))
    d.rounded_rectangle([int(190 * s), int(805 * s), int(360 * s), int(835 * s)], radius=int(15 * s), fill=blue)
    return im


def png(n):
    b = io.BytesIO()
    draw(n).save(b, "PNG")
    return b.getvalue()


entries = [(b"ic10", 1024), (b"ic09", 512), (b"ic08", 256), (b"ic07", 128), (b"ic14", 512), (b"ic13", 256),
           (b"ic12", 64), (b"ic11", 32)]
body = b"".join(t + struct.pack(">I", len(p) + 8) + p for t, p in ((t, png(n)) for t, n in entries))
open(sys.argv[1], "wb").write(b"icns" + struct.pack(">I", len(body) + 8) + body)
draw(512).save(sys.argv[1].replace(".icns", "-preview.png"))
