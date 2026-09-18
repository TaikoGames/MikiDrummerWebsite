#!/usr/bin/env python3
"""A share image for every band page.

The band pages were built for other people to share -- a band posts their own
page and Punk BC reaches that band's followers, which is the whole point of
having a page per act. But they shipped with no og:image at all, so a shared
link rendered as a bare grey rectangle. On Instagram and in a DM that is close
to invisible, which made a hundred pages built for sharing unshareable.

So: a 1200x630 card per band, carrying the band name and their next date, on
the same crowd photograph the board uses when a show has no art of its own.

    python3 tools/build_band_cards.py [--force] [--check]

Deterministic on purpose. The crowd photo is picked by hashing the band name
rather than at random, and a card is only rewritten when the thing it depicts
changes, so a rebuild does not produce a hundred modified binaries for git to
carry every time the board refreshes.
"""

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_band_pages import (  # noqa: E402
    SHOWS, earns_a_page, gather, load_links, slugify,
)
from build_punkbc import today_local  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "images" / "bands"
STAMP = OUT_DIR / ".built.json"

W, H = 1200, 630                       # what every platform crops from
PAD = 74
HOT = (232, 103, 42)                   # the board's orange
PAPER = (245, 243, 240)
DIM = (176, 170, 164)

CROWD = [ROOT / "images" / "punkbc-crowd-1-bg.jpg",
         ROOT / "images" / "punkbc-crowd-2-bg.jpg"]

# PIL cannot read woff2, and the site's font only exists as woff2. Converting
# is lossless -- same outlines, different container -- so the cards use the
# real typeface rather than something that merely looks close.
WOFF2 = {"display": ROOT / "fonts" / "KilnSansSpiked.woff2",
         "text": ROOT / "fonts" / "KilnSansRegular.woff2"}
_font_cache = {}


def ttf_for(kind):
    if kind in _font_cache:
        return _font_cache[kind]
    from fontTools.ttLib import TTFont
    import tempfile
    f = TTFont(str(WOFF2[kind]))
    f.flavor = None
    path = Path(tempfile.gettempdir()) / ("punkbc-%s.ttf" % kind)
    f.save(str(path))
    _font_cache[kind] = path
    return path


def font(kind, size):
    return ImageFont.truetype(str(ttf_for(kind)), size)


def measure(draw, text, fnt):
    l, t, r, b = draw.textbbox((0, 0), text, font=fnt)
    return r - l, b - t


def wrap(draw, text, fnt, width):
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = (line + " " + w).strip()
        if measure(draw, trial, fnt)[0] <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def fit(draw, text, kind, width, start, floor, max_lines):
    """Largest size at which the name fits the space it has.

    Band names run from "Diera" to "Chuck Ragan and the Camaraderie", and one
    size cannot serve both. Step down until it fits rather than letting a long
    name run off the edge of the image.
    """
    size = start
    while size > floor:
        fnt = font(kind, size)
        lines = wrap(draw, text, fnt, width)
        if len(lines) <= max_lines:
            return fnt, lines
        size -= 4
    fnt = font(kind, floor)
    return fnt, wrap(draw, text, fnt, width)[:max_lines]


def backdrop(seed):
    """A crowd photo, darkened until white type sits safely on top of it."""
    pick = CROWD[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(CROWD)]
    im = Image.open(pick).convert("RGB")

    # cover-fit
    scale = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    im = im.crop(((im.width - W) // 2, (im.height - H) // 2,
                  (im.width - W) // 2 + W, (im.height - H) // 2 + H))
    im = im.filter(ImageFilter.GaussianBlur(3))

    # A flat overlay would either wash out the photo or fail to cover its
    # bright patches. A gradient, heaviest on the left where the type sits,
    # keeps the crowd legible on the right and the text safe on the left.
    shade = Image.new("L", (W, H), 0)
    px = shade.load()
    for x in range(W):
        v = int(214 - 96 * (x / W) ** 1.5)
        for y in range(H):
            px[x, y] = v
    im = Image.composite(Image.new("RGB", (W, H), (9, 8, 8)), im, shade)
    return im


def date_line(show):
    try:
        d = datetime.fromisoformat(show["date"])
        when = d.strftime("%a %-d %b").upper()
    except (ValueError, KeyError):
        when = str(show.get("date", "")).upper()
    bits = [when]
    if show.get("venue"):
        bits.append(show["venue"])
    if show.get("city"):
        bits.append(show["city"])
    return "  ·  ".join(bits)


def card(name, shows):
    im = backdrop(name)
    d = ImageDraw.Draw(im)
    inner = W - PAD * 2 - 260          # right margin keeps type off the crowd

    y = PAD + 4
    eyebrow = font("text", 25)
    d.text((PAD, y), "PUNK BC", font=eyebrow, fill=HOT)
    y += 54

    fnt, lines = fit(d, name, "display", inner, 96, 42, 3)
    for line in lines:
        d.text((PAD, y), line, font=fnt, fill=PAPER)
        y += round(fnt.size * 1.06)

    y += 22
    if shows:
        sub = font("text", 29)
        d.text((PAD, y), date_line(shows[0]), font=sub, fill=(226, 222, 217))
        y += 44
        if len(shows) > 1:
            more = font("text", 25)
            d.text((PAD, y), "+%d more date%s" % (len(shows) - 1,
                                                  "" if len(shows) == 2 else "s"),
                   font=more, fill=DIM)

    foot = font("text", 24)
    fh = measure(d, "Ag", foot)[1]
    d.text((PAD, H - PAD - fh), "mikidrummer.ca/bands", font=foot, fill=DIM)

    # A rule in the brand orange, so the card reads as one of a set.
    d.rectangle([0, H - 9, W, H], fill=HOT)
    return im


def fingerprint(name, shows):
    """What the card depicts. Changes here, and only here, mean a redraw."""
    return hashlib.sha1(json.dumps(
        [name, [[s.get("date"), s.get("venue"), s.get("city")] for s in shows[:2]],
         len(shows)], sort_keys=True).encode()).hexdigest()[:16]


def main():
    force = "--force" in sys.argv
    check = "--check" in sys.argv

    today = today_local()
    shows = [s for s in json.loads(SHOWS.read_text(encoding="utf-8"))["shows"]
             if s["date"] >= today]
    by = gather(shows, load_links())
    keep = sorted((i for i in by.values() if earns_a_page(i)),
                  key=lambda i: i["name"].lower())

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    old = {}
    if STAMP.exists() and not force:
        try:
            old = json.loads(STAMP.read_text())
        except ValueError:
            old = {}

    if check:
        missing = [i["name"] for i in keep
                   if not (OUT_DIR / ("%s.jpg" % slugify(i["name"]))).exists()]
        print("%d band pages, %d cards on disk, %d missing"
              % (len(keep), len(list(OUT_DIR.glob("*.jpg"))), len(missing)))
        for m in missing[:10]:
            print("  missing:", m)
        return 1 if missing else 0

    new, written = {}, 0
    for info in keep:
        slug = slugify(info["name"])
        fp = fingerprint(info["name"], info["shows"])
        new[slug] = fp
        path = OUT_DIR / ("%s.jpg" % slug)
        if not force and path.exists() and old.get(slug) == fp:
            continue
        card(info["name"], info["shows"]).save(path, "JPEG", quality=84,
                                               optimize=True, progressive=True)
        written += 1

    # Cards for acts no longer on the board would otherwise pile up forever.
    gone = 0
    for p in OUT_DIR.glob("*.jpg"):
        if p.stem not in new:
            p.unlink()
            gone += 1

    STAMP.write_text(json.dumps(new, indent=0, sort_keys=True), encoding="utf-8")
    sizes = [p.stat().st_size for p in OUT_DIR.glob("*.jpg")]
    print("band cards: %d written, %d unchanged, %d removed" %
          (written, len(keep) - written, gone))
    if sizes:
        print("  %d on disk, %.0f KB avg, %.0f KB largest"
              % (len(sizes), sum(sizes) / len(sizes) / 1024, max(sizes) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
