#!/usr/bin/env python3
"""A share card for each press kit.

Both kits already had an og:image, but it was the raw hero photograph: 1600x1067
handed to a slot that crops to 1200x630, so whoever saw it got an arbitrary
middle band of a picture with no band name, no context and no hint that the
link is a press kit rather than a gig photo. Both pages now carry a Share
button, which makes the card the first thing anyone sees of them.

So: a purpose-built 1200x630. Granite gets its logo, which is the one band here
that has one. Lift the Anchor gets its name set in the site's display face,
which is what its own EPK does in place of a logo it does not have.

    python3 tools/build_epk_cards.py [--check]
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "images", "epk")

W, H = 1200, 630
PAD = 78
HOT = (232, 103, 42)
PAPER = (246, 243, 240)
DIM = (176, 170, 164)

WOFF2 = {"display": os.path.join(ROOT, "fonts", "KilnSansSpiked.woff2"),
         "text": os.path.join(ROOT, "fonts", "KilnSansRegular.woff2")}
_cache = {}

KITS = [
    {"out": "granite-epk-card.jpg",
     "hero": "images/granite/hero.jpg",
     "logo": "images/granite/logo.png",
     "name": "GRANITE",
     "meta": "METAL · GRUNGE  ·  VANCOUVER, BC"},
    {"out": "lift-the-anchor-epk-card.jpg",
     "hero": "images/lift-the-anchor/hero.jpg",
     "logo": None,                       # no logo file exists for them
     "name": "LIFT THE ANCHOR",
     "meta": "PUNK ROCK  ·  VANCOUVER, BC"},
]


def ttf(kind):
    if kind not in _cache:
        from fontTools.ttLib import TTFont
        import tempfile
        f = TTFont(WOFF2[kind]); f.flavor = None
        p = os.path.join(tempfile.gettempdir(), "epk-%s.ttf" % kind)
        f.save(p); _cache[kind] = p
    return _cache[kind]


def font(kind, size):
    return ImageFont.truetype(ttf(kind), size)


def backdrop(path):
    im = Image.open(os.path.join(ROOT, path)).convert("RGB")
    s = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    im = im.crop(((im.width - W) // 2, (im.height - H) // 2,
                  (im.width - W) // 2 + W, (im.height - H) // 2 + H))
    im = im.filter(ImageFilter.GaussianBlur(2))
    # Heavier than the band cards: a logo is a flat shape with no outline of
    # its own, so it needs a calmer field behind it than type does.
    shade = Image.new("RGB", (W, H), (10, 9, 9))
    return Image.blend(im, shade, 0.62)


def card(kit):
    im = backdrop(kit["hero"])
    d = ImageDraw.Draw(im)

    eyebrow = font("text", 24)
    d.text((PAD, PAD), "ELECTRONIC PRESS KIT", font=eyebrow, fill=HOT)

    if kit["logo"]:
        logo = Image.open(os.path.join(ROOT, kit["logo"])).convert("RGBA")
        box_w = W - PAD * 2
        box_h = 250
        sc = min(box_w / logo.width, box_h / logo.height)
        lw, lh = round(logo.width * sc), round(logo.height * sc)
        logo = logo.resize((lw, lh), Image.LANCZOS)
        im.paste(logo, (PAD, (H - lh) // 2 - 10), logo)
    else:
        # No logo on file, so the name carries it -- the same choice the kit
        # itself makes.
        size = 104
        while size > 44:
            f = font("display", size)
            if d.textlength(kit["name"], font=f) <= W - PAD * 2:
                break
            size -= 4
        f = font("display", size)
        bbox = d.textbbox((0, 0), kit["name"], font=f)
        d.text((PAD, (H - (bbox[3] - bbox[1])) // 2 - 16), kit["name"], font=f, fill=PAPER)

    meta = font("text", 25)
    d.text((PAD, H - PAD - 56), kit["meta"], font=meta, fill=(219, 214, 209))
    foot = font("text", 22)
    d.text((PAD, H - PAD - 16), "mikidrummer.ca", font=foot, fill=DIM)

    d.rectangle([0, H - 9, W, H], fill=HOT)
    return im


def main():
    os.makedirs(OUT, exist_ok=True)
    if "--check" in sys.argv:
        missing = [k["out"] for k in KITS
                   if not os.path.exists(os.path.join(OUT, k["out"]))]
        print("%d of %d press kit cards present" % (len(KITS) - len(missing), len(KITS)))
        for m in missing:
            print("  missing:", m)
        return 1 if missing else 0

    for kit in KITS:
        p = os.path.join(OUT, kit["out"])
        card(kit).save(p, "JPEG", quality=86, optimize=True, progressive=True)
        print("%-34s %dx%d  %5.0f KB" % (kit["out"], W, H, os.path.getsize(p) / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
