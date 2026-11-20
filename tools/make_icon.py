"""Draw the app icon (design 1, the two-column page, in the "Halo" colors Matt picked) and write
AppIcon.icns, AppIcon.ico and AppIcon-preview.png next to the given .icns path.

    python3 tools/make_icon.py tools/AppIcon.icns          (needs Pillow; no Apple tools)

Halo: a navy tile with a violet glow (gradient #0b0c18 -> #1a1f6a -> #a03cf0, top left to bottom right),
a white page, violet chords #7a2cf0 and grey lyric bars #5a5d70. Below 48 px it uses the flat tile
#2a2380 and fewer, thicker bars so it stays readable.
"""
import io
import struct
import sys

from PIL import Image, ImageDraw

STOPS = [(0.0, (0x0b, 0x0c, 0x18)), (0.55, (0x1a, 0x1f, 0x6a)), (1.0, (0xa0, 0x3c, 0xf0))]
FLAT = (0x2a, 0x23, 0x80)
CHORD = (0x7a, 0x2c, 0xf0)
LYRIC = (0x5a, 0x5d, 0x70)
INK = (0x11, 0x11, 0x11)

# (x, y, w, h) on the 100-unit grid of the approved design
DETAIL = [("ink", 28, 21, 30, 4),
          ("chord", 28, 31, 10, 3), ("lyric", 28, 36, 19, 2.5), ("chord", 28, 43, 8, 3), ("lyric", 28, 48, 18, 2.5),
          ("chord", 28, 55, 11, 3), ("lyric", 28, 60, 17, 2.5),
          ("chord", 53, 31, 9, 3), ("lyric", 53, 36, 19, 2.5), ("chord", 53, 43, 11, 3), ("lyric", 53, 48, 17, 2.5)]
SIMPLE = [("chord", 28, 22, 18, 6), ("chord", 53, 22, 18, 6), ("lyric", 28, 34, 18, 5), ("lyric", 53, 34, 18, 5),
          ("chord", 28, 46, 18, 6), ("lyric", 28, 58, 18, 5), ("lyric", 53, 46, 18, 5)]


def _gradient(n):
    """Diagonal gradient, n x n."""
    small = 256
    g = Image.new("RGB", (small, small))
    px = g.load()
    for y in range(small):
        for x in range(small):
            t = (x + y) / (2 * (small - 1))
            for (t0, c0), (t1, c1) in zip(STOPS, STOPS[1:]):
                if t <= t1:
                    k = (t - t0) / (t1 - t0) if t1 > t0 else 0
                    px[x, y] = tuple(round(a + (b - a) * k) for a, b in zip(c0, c1))
                    break
    return g.resize((n, n), Image.BICUBIC)


def draw(n, margin_units=2, mac=False):
    """The icon at n x n pixels. mac=True leaves Apple's standard margin around the tile (100/1024)."""
    ss = 4                                         # draw large, then shrink, for smooth edges
    N = n * ss
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    if mac:
        off, size = N * 100 / 1024, N * 824 / 1024
        u = size / 100
        ox = oy = off
        tile = (ox, oy, ox + size, oy + size)
        radius = N * 185 / 1024
    else:
        u = N / 100
        ox = oy = 0
        tile = (margin_units * u, margin_units * u, (100 - margin_units) * u, (100 - margin_units) * u)
        radius = 22 * u
    small = n < 48
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle(tile, radius=radius, fill=255)
    if small:
        fill = Image.new("RGB", (N, N), FLAT)
    else:
        fill = _gradient(N)
    im.paste(fill, (0, 0), mask)
    d = ImageDraw.Draw(im)

    def box(x, y, w, h, r):
        return (ox + x * u, oy + y * u, ox + (x + w) * u, oy + (y + h) * u), r * u
    b, r = box(22, 14, 56, 72, 4)
    d.rounded_rectangle(b, radius=r, fill=(255, 255, 255, 255))
    colors = {"ink": INK, "chord": CHORD, "lyric": LYRIC}
    for kind, x, y, w, h in (SIMPLE if small else DETAIL):
        b, r = box(x, y, w, h, h / 2 if not small else 0.5)
        d.rounded_rectangle(b, radius=r, fill=colors[kind] + (255,))
    return im.resize((n, n), Image.LANCZOS)


def png(im):
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def write_icns(path):
    entries = [(b"ic10", 1024), (b"ic09", 512), (b"ic08", 256), (b"ic07", 128), (b"ic14", 512), (b"ic13", 256),
               (b"ic12", 64), (b"ic11", 32)]
    body = b"".join(t + struct.pack(">I", len(p) + 8) + p for t, p in ((t, png(draw(n, mac=True))) for t, n in entries))
    with open(path, "wb") as fh:
        fh.write(b"icns" + struct.pack(">I", len(body) + 8) + body)


def write_ico(path):
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    imgs = [draw(n) for n in sizes]
    imgs[-1].save(path, format="ICO", sizes=[(n, n) for n in sizes], append_images=imgs[:-1])


if __name__ == "__main__":
    icns = sys.argv[1] if len(sys.argv) > 1 else "tools/AppIcon.icns"
    write_icns(icns)
    write_ico(icns.replace(".icns", ".ico"))
    draw(512, mac=True).save(icns.replace(".icns", "-preview.png"))
