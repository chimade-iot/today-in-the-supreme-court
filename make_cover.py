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


# ==========================================================================
# Social share card and favicons
# ==========================================================================

def make_social_card() -> Image.Image:
    """
    The 1200x630 card link previews use.

    Separate from the podcast cover on purpose: the cover is square because
    podcast apps demand it, while WhatsApp, LinkedIn and Slack render a
    landscape card and letterbox a square one into something small and sad.
    """
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), INK)

    # Ground: a little deeper at the right so the type has somewhere to sit.
    grad = Image.new("L", (W, 1))
    for x in range(W):
        grad.putpixel((x, 0), int((x / W) * 90))
    img = Image.composite(Image.new("RGB", (W, H), INK_DEEP),
                          img, grad.resize((W, H)))

    # Warm halo behind the lamp, on the left third.
    cx, cy = 300, H // 2
    halo = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(halo).ellipse([cx - 260, cy - 260, cx + 260, cy + 260],
                                 fill=(64, 40, 11))
    halo = halo.filter(ImageFilter.GaussianBlur(120))
    import numpy as _np
    img = Image.fromarray(_np.clip(_np.asarray(img).astype(int)
                                   + _np.asarray(halo).astype(int),
                                   0, 255).astype("uint8"))
    d = ImageDraw.Draw(img)

    # Signal arcs, opening toward the type.
    for i, r in enumerate((120, 172, 224)):
        d.arc([cx - r, cy - r, cx + r, cy + r], start=205, end=335,
              fill=LAMP, width=max(2, 6 - i * 2))
    d.ellipse([cx - 34, cy - 34, cx + 34, cy + 34], fill=LAMP)

    # Type block on the right.
    eyebrow = load_font(MONO_CANDIDATES, 26)
    serif = load_font(SERIF_CANDIDATES, 86)
    footer = load_font(MONO_CANDIDATES, 23)

    tx = 560
    draw_tracked(d, (tx, 196), "TODAY IN THE", eyebrow, MUTED,
                 tracking=13, anchor_centre=False)
    d.text((tx - 4, 240), "SUPREME", font=serif, fill=PAPER)
    d.text((tx - 4, 338), "COURT", font=serif, fill=PAPER)
    d.line([(tx, 462), (tx + 300, 462)], fill=(52, 64, 84), width=3)
    draw_tracked(d, (tx, 486), "FREE DAILY AUDIO BULLETIN", footer, LAMP,
                 tracking=10, anchor_centre=False)
    return img


def make_favicon() -> Image.Image:
    """
    Just the lamp and arcs - at 32 pixels the wordmark is unreadable, so the
    icon keeps only the part that still reads at that size.
    """
    S = 512
    img = Image.new("RGB", (S, S), INK)
    d = ImageDraw.Draw(img)
    cx, cy = S // 2, int(S * 0.56)
    for i, r in enumerate((150, 205, 260)):
        d.arc([cx - r, cy - r, cx + r, cy + r], start=203, end=337,
              fill=LAMP, width=max(6, 20 - i * 5))
    d.ellipse([cx - 58, cy - 58, cx + 58, cy + 58], fill=LAMP)
    return img


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

    print("drawing the social share card ...")
    card = make_social_card()
    card.save(ASSETS / "social-card.png", "PNG", optimize=True)
    kb = (ASSETS / "social-card.png").stat().st_size / 1024
    print(f"{ASSETS / 'social-card.png'}  1200x630  {kb:.0f} KB"
          + ("  (WhatsApp may skip images over ~300 KB)" if kb > 300 else ""))

    print("drawing favicons ...")
    fav = make_favicon()
    fav.resize((180, 180), Image.LANCZOS).save(ASSETS / "apple-touch-icon.png",
                                               "PNG", optimize=True)
    fav.resize((32, 32), Image.LANCZOS).save(ASSETS / "favicon-32.png",
                                             "PNG", optimize=True)
    print(f"{ASSETS / 'apple-touch-icon.png'}  180x180")
    print(f"{ASSETS / 'favicon-32.png'}  32x32")


if __name__ == "__main__":
    main()
