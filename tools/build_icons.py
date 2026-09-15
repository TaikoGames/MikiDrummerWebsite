#!/usr/bin/env python3
"""Build every site icon from images/brand.png.

The logo is a wordmark inside a ring. At 16 pixels the wordmark cannot render
-- it becomes a grey smudge, and the icon reads as a dark blob. The favicon
this replaced had exactly that problem, which is why swapping it appeared to
change nothing at all: both were the same artwork at the same hopeless size.

So below 32px the wordmark is taken out and the ring, the lugs and the sticks
are left to carry it. That is a subtraction from the original artwork, not a
redrawing of it: every pixel that survives came out of brand.png. From 32px up
the full lockup is used, wordmark and all, because there it reads.

    python3 tools/build_icons.py [--check]
"""

import io
import math
import os
import struct
import sys

from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "images", "brand.png")
BG = (11, 13, 16, 255)              # the site's near-black

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
# 48, 96 and 192 are there for Google: it wants a square whose sides are a
# multiple of 48px for the icon beside a search result, and ignores what it
# cannot use.
PNG_SIZES = [16, 32, 48, 96, 180, 192, 512]
PLAIN_BELOW = 32                     # under this, the wordmark comes out


def artwork():
    im = Image.open(SRC).convert("RGBA")
    return im.crop(im.getbbox())


def without_wordmark(src):
    """The same artwork with the lettering dropped.

    The text is gr(e)yish and sits well inside the ring; the lugs are white but
    out on the rim, and the sticks are orange. So removing desaturated pixels
    inside 70% of the radius takes the words and leaves everything else.
    """
    w, h = src.size
    cx, cy, R = w / 2, h / 2, min(w, h) / 2
    out = src.copy()
    px, op = src.load(), out.load()
    dropped = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 8:
                continue
            if math.hypot(x - cx, y - cy) / R >= 0.70:
                continue                      # the rim and its lugs stay
            if max(r, g, b) - min(r, g, b) < 46 and max(r, g, b) > 90:
                op[x, y] = (r, g, b, 0)       # grey and bright: lettering
                dropped += 1
    return out, dropped


def tile(img, size):
    """Fit onto the dark tile, with a light sharpen where the downscale bites."""
    im = img.copy()
    im.thumbnail((size, size), Image.LANCZOS)
    if size <= 64:
        im = im.filter(ImageFilter.UnsharpMask(radius=0.6, percent=120, threshold=2))
    t = Image.new("RGBA", (size, size), BG)
    t.alpha_composite(im, ((size - im.width) // 2, (size - im.height) // 2))
    return t


def write_ico(path, frames):
    """Pillow's ICO writer resizes one image to every size in the list and
    ignores append_images, so it cannot hold a different picture per size. It
    silently wrote a single frame twice while reporting success, so the
    container is assembled here instead."""
    blobs = []
    for f in frames:
        b = io.BytesIO()
        f.save(b, format="PNG")
        blobs.append(b.getvalue())
    out = io.BytesIO()
    out.write(struct.pack("<HHH", 0, 1, len(frames)))
    off = 6 + 16 * len(frames)
    for f, blob in zip(frames, blobs):
        out.write(struct.pack("<BBBBHHII",
                              0 if f.width >= 256 else f.width,
                              0 if f.height >= 256 else f.height,
                              0, 0, 1, 32, len(blob), off))
        off += len(blob)
    for blob in blobs:
        out.write(blob)
    with open(path, "wb") as fh:
        fh.write(out.getvalue())


def frames_in(path):
    """Read the container directly. Pillow's ICO reader returns frame zero
    whatever size is asked of it, which made a correct file look broken."""
    raw = open(path, "rb").read()
    _, _, n = struct.unpack("<HHH", raw[:6])
    out = []
    for i in range(n):
        w, h, _c, _r, _p, _b, size, off = struct.unpack("<BBBBHHII",
                                                        raw[6 + 16*i: 6 + 16*(i+1)])
        out.append(((w or 256), Image.open(io.BytesIO(raw[off:off+size])).convert("RGBA")))
    return out


def greys(im):
    """Lettering shows up as desaturated bright pixels; the lugs are on the rim
    and read the same way, so this counts the middle only."""
    w, h = im.size
    cx, cy, R = w/2, h/2, min(w, h)/2
    n = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = im.getpixel((x, y))
            if a > 20 and math.hypot(x-cx, y-cy)/R < 0.62 \
               and max(r, g, b) - min(r, g, b) < 46 and max(r, g, b) > 110:
                n += 1
    return n


def check():
    bad = []
    for size, im in frames_in(os.path.join(ROOT, "site-icon.ico")):
        has_text = greys(im) > 2
        want_text = size >= PLAIN_BELOW
        ok = has_text == want_text
        print("  %3dpx  %-18s %s" % (size,
              "full lockup" if has_text else "ring and sticks",
              "ok" if ok else "WRONG"))
        if not ok:
            bad.append(size)
    print("check:", "all frames as intended" if not bad else "wrong at %s" % bad)
    return 1 if bad else 0


def main():
    if "--check" in sys.argv:
        return check()

    src = artwork()
    plain, dropped = without_wordmark(src)
    print("wordmark pixels removed: %d" % dropped)

    def art_for(size):
        return src if size >= PLAIN_BELOW else plain

    write_ico(os.path.join(ROOT, "site-icon.ico"),
              [tile(art_for(s), s) for s in ICO_SIZES])
    write_ico(os.path.join(ROOT, "favicon.ico"),
              [tile(art_for(s), s) for s in ICO_SIZES])

    for s in PNG_SIZES:
        t = tile(art_for(s), s)
        # icon-<size>.png is the name the pages point at, with no version on
        # it. Google asks for a favicon URL that does not move, and a query
        # string that changes every time we fiddle is the opposite of that.
        t.save(os.path.join(ROOT, "images", "icon-%d.png" % s))
        t.save(os.path.join(ROOT, "images", "tab-icon-%d.png" % s))
        t.save(os.path.join(ROOT, "images", "miki-icon-%d.png" % s))
    tile(src, 512).save(os.path.join(ROOT, "images", "miki-icon-maskable.png"))

    # The conventional paths a browser probes on its own, so a phone looking
    # for /apple-touch-icon.png does not get the August one.
    tile(src, 180).save(os.path.join(ROOT, "apple-touch-icon.png"))
    tile(src, 32).save(os.path.join(ROOT, "favicon-32.png"))

    print("written. verifying:")
    return check()


if __name__ == "__main__":
    sys.exit(main())
