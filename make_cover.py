#!/usr/bin/env python3
"""
Draw the podcast cover art.

Apple requires a square JPEG or PNG between 1400 and 3000 pixels. This
draws one at 2000, in the same ink-and-lamp palette as the site: a
transmitter lamp with signal arcs, over the Court's name.

Run it once and commit the result. It never changes between editions, so
the build workflow just copies it - which also means the build never
depends on a particular font being installed on the runner.

    python3 make_cover.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ASSETS = Path(__file__).parent / "assets"
SIZE = 2000

INK       = (13, 17, 25)
INK_DEEP  = (8, 11, 17)
PAPER     = (238, 241, 247)
MUTED     = (118, 127, 150)
LAMP      = (232, 163, 61)

SERIF_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "C:/Windows/Fonts/timesbd.ttf",
]
MONO_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "C:/Windows/Fonts/consola.ttf",
]


def load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def text_width(draw, text, font, tracking=0):
    w = draw.textlength(text, font=font)
    return w + tracking * max(len(text) - 1, 0)


def draw_tracked(draw, xy, text, font, fill, tracking=0, anchor_centre=True):
    """PIL has no letter-spacing, so place each glyph by hand."""
    x, y = xy
    total = text_width(draw, text, font, tracking)
    if anchor_centre:
        x -= total / 2
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return total


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)

    # --- ground: a soft vertical gradient, deeper at the edges ------------
    img = Image.new("RGB", (SIZE, SIZE), INK)
    grad = Image.new("L", (1, SIZE))
    for y in range(SIZE):
        t = abs(y / SIZE - 0.42) * 2          # darkest away from the lamp
        grad.putpixel((0, y), int(min(1.0, t) * 120))
    grad = grad.resize((SIZE, SIZE))
    img = Image.composite(Image.new("RGB", (SIZE, SIZE), INK_DEEP), img, grad)

    # --- warm halo behind the lamp ---------------------------------------
    halo = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    hd = ImageDraw.Draw(halo)
    cx, cy = SIZE // 2, int(SIZE * 0.335)
    hd.ellipse([cx - 420, cy - 420, cx + 420, cy + 420], fill=(70, 44, 12))
    halo = halo.filter(ImageFilter.GaussianBlur(190))
    img = Image.blend(img, Image.blend(img, halo, 0.0), 0.0)
    img = Image.fromarray(
        __import__("numpy").clip(
            __import__("numpy").asarray(img).astype(int)
            + __import__("numpy").asarray(halo).astype(int), 0, 255
        ).astype("uint8")
    )

    d = ImageDraw.Draw(img)

    # --- transmission arcs radiating from the lamp ------------------------
    for i, r in enumerate((250, 360, 470, 580)):
        fade = int(150 - i * 32)
        box = [cx - r, cy - r, cx + r, cy + r]
        d.arc(box, start=203, end=337, fill=(LAMP[0], LAMP[1], LAMP[2]), width=max(3, 9 - i))
        # fade the outer arcs by overdrawing with the ground at low alpha
        if i:
            veil = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
            vd = ImageDraw.Draw(veil)
            vd.arc(box, start=203, end=337,
                   fill=(INK[0], INK[1], INK[2], 255 - fade), width=max(3, 9 - i) + 2)
            img = Image.alpha_composite(img.convert("RGBA"), veil).convert("RGB")
            d = ImageDraw.Draw(img)

    # --- the lamp itself --------------------------------------------------
    d.ellipse([cx - 62, cy - 62, cx + 62, cy + 62], fill=LAMP)
    d.ellipse([cx - 104, cy - 104, cx + 104, cy + 104],
              outline=(90, 63, 24), width=6)

    # --- type -------------------------------------------------------------
    mono_sm = load_font(MONO_CANDIDATES, 58)
    serif_xl = load_font(SERIF_CANDIDATES, 250)
    mono_md = load_font(MONO_CANDIDATES, 52)

    draw_tracked(d, (cx, int(SIZE * 0.545)), "TODAY IN THE", mono_sm, MUTED, tracking=26)

    # "SUPREME COURT" on two lines so it stays huge and legible as a
    # 55-pixel thumbnail, which is how most people will first see it.
    for line, y in (("SUPREME", 0.615), ("COURT", 0.735)):
        w = d.textlength(line, font=serif_xl)
        d.text((cx - w / 2, int(SIZE * y)), line, font=serif_xl, fill=PAPER)

    rule_y = int(SIZE * 0.876)
    d.line([(cx - 300, rule_y), (cx + 300, rule_y)], fill=(45, 56, 74), width=4)

    draw_tracked(d, (cx, int(SIZE * 0.900)), "DAILY AUDIO BULLETIN",
                 mono_md, LAMP, tracking=20)

    out = ASSETS / "cover.png"
    img.save(out, "PNG", optimize=True)
    kb = out.stat().st_size / 1024
    print(f"{out}  {SIZE}x{SIZE}  {kb:.0f} KB")

    # A small copy for the web page's link previews.
    img.resize((600, 600), Image.LANCZOS).save(ASSETS / "cover-600.png",
                                               "PNG", optimize=True)
    print(f"{ASSETS / 'cover-600.png'}  600x600")


if __name__ == "__main__":
    main()
