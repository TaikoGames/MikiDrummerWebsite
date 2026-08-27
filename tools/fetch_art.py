#!/usr/bin/env python3
"""Download the show photos once, crop them, and keep them in the repo.

The pictures in the shows sheet point at whoever announced the gig: a 3840px
PNG on a ticketing CDN, a WebP on a band's own site, a Wikimedia file page.
Three problems with sending those straight out in an email:

  * they are the wrong shape, and CSS cannot fix that — object-fit is ignored
    by Outlook's Word engine, which stretches the picture instead of cropping
  * they are the wrong format — Outlook renders no WebP at all
  * they are megabytes down someone's phone

Handing them to a resizing proxy solved the shape and left a worse problem: a
third party between our email and every picture in it. When that fails the
reader gets four empty boxes, and we only find out because someone says so.

So the crop happens here instead, once, and the result lives in the repo and
is served from our own domain like everything else. Each source image is
fetched, cropped to 640x360 and saved as a JPEG; index.json remembers which
file came from which URL so the next run downloads nothing. Files whose show
has left the board are deleted, which keeps this from growing forever.

Only runs where the network is open — the digest workflow does it before
build_digest.py. If a download fails the entry is simply missing from the
index, and build_digest falls back to the original remote URL.

Usage:
  python3 tools/fetch_art.py                # fetch what is missing, prune
  python3 tools/fetch_art.py --force        # re-download everything
  python3 tools/fetch_art.py --self-test    # crop checks, no network
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "punkbc-shows.json"
ART = ROOT / "img" / "digest"
INDEX = ART / "index.json"

# One file serves both places: 640x360 is twice the web card (320x180) and a
# little over twice the email card (270x150), so it stays sharp on a phone.
SIZE = (640, 360)
QUALITY = 82
MAX_BYTES = 24 * 1024 * 1024
TIMEOUT = 30

# Wikimedia refuses a browser User-Agent outright — "your request does not
# comply with our robot policy" — and it is right to: a script pretending to be
# Chrome gives them no way to tell who is hammering them. Say what this is and
# where to complain about it, and the same requests go through.
UA = "MikiDrummerBot/1.0 (+https://www.mikidrummer.ca/punkbc.html) Python-urllib"
PAUSE = 0.4          # between requests to one host, so nobody has to rate-limit us
RETRY_AFTER = 5      # one patient retry when they do anyway

# The generic mosh-pit photo is not worth a file of its own — build_digest
# never features it either.
GENERIC = ("moshpit2", "punkbc-placeholder")


def wanted(s: dict) -> bool:
    img = (s.get("image") or "").lower()
    if not img or any(g in img for g in GENERIC):
        return False
    return "mikidrummer.ca" not in img        # ours already, leave it alone


def name_for(band: str, url: str) -> str:
    """Readable, stable, and unique even for two bands with the same name."""
    slug = re.sub(r"[^a-z0-9]+", "-", (band or "art").lower()).strip("-") or "art"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:40]}-{digest}.jpg"


def anchor(src_w: int, src_h: int, size=SIZE) -> tuple[float, float]:
    """Which part of the picture to keep.

    A picture wider than the card loses its sides, and the middle of it is the
    right guess. A picture taller than the card loses its top or its bottom,
    and the middle is the wrong guess: a gig poster puts the band's name across
    the very top, and the taller the poster the further up that name sits. So
    the crop slides towards the top as the picture gets taller, and is pinned to
    the very top once it is about two and a half times too tall — by then it is
    a poster, and a poster's title is not near the top, it is against the edge.
    A square press shot is barely moved; a 4:3 photo keeps its faces; a 2:3
    poster is taken from the top inch.
    """
    want = size[0] / size[1]
    have = src_w / max(src_h, 1)
    if have >= want:                          # wider than the card: trim the sides
        return (0.5, 0.5)
    excess = want / have                      # times taller than the card needs
    return (0.5, max(0.03, min(0.45, 0.45 - 0.2625 * (excess - 1))))


def crop(raw: bytes, size=SIZE) -> bytes:
    """Source bytes in, a JPEG of exactly `size` out."""
    from PIL import Image, ImageOps

    im = Image.open(io.BytesIO(raw))
    im = ImageOps.exif_transpose(im)
    if im.mode not in ("RGB", "L"):
        # a transparent PNG on a black JPEG background is a silhouette
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, (17, 17, 17))
        flat.paste(im, mask=im.split()[-1])
        im = flat
    else:
        im = im.convert("RGB")
    im = ImageOps.fit(im, size, method=Image.LANCZOS, centering=anchor(*im.size, size=size))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    return buf.getvalue()


_last_hit: dict[str, float] = {}


def download(url: str) -> bytes:
    """One image, politely: spaced out per host, and one retry if asked to wait."""
    host = urllib.parse.urlsplit(url).netloc
    for attempt in (1, 2):
        wait = PAUSE - (time.monotonic() - _last_hit.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*",
        })
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read(MAX_BYTES + 1)
            break
        except urllib.error.HTTPError as e:
            _last_hit[host] = time.monotonic()
            if e.code in (429, 503) and attempt == 1:
                time.sleep(RETRY_AFTER)
                continue
            raise
        finally:
            _last_hit[host] = time.monotonic()
    if len(raw) > MAX_BYTES:
        raise ValueError(f"larger than {MAX_BYTES // 1024 // 1024}MB")
    if not raw:
        raise ValueError("empty response")
    return raw


def self_test() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("Pillow is not installed — pip install pillow")
        return 1

    checks = []

    def shot(mode, size, fmt):
        im = Image.new(mode, size, (200, 30, 40) if mode == "RGB" else 128)
        buf = io.BytesIO()
        im.save(buf, fmt)
        return buf.getvalue()

    # a tall poster, a wide banner and a square press shot all come out identical
    for label, src in [("tall 800x2000", shot("RGB", (800, 2000), "PNG")),
                       ("wide 3840x1000", shot("RGB", (3840, 1000), "JPEG")),
                       ("square 500x500", shot("RGB", (500, 500), "PNG"))]:
        out = crop(src)
        im = Image.open(io.BytesIO(out))
        checks.append((im.size == SIZE, f"{label} -> {im.size[0]}x{im.size[1]}"))
        checks.append((im.format == "JPEG", f"{label} -> {im.format}"))

    # where the crop is taken from: the taller the source, the higher up
    checks.append((anchor(1920, 1080) == (0.5, 0.5), "16:9 source, nothing to choose"))
    checks.append((anchor(3840, 1000) == (0.5, 0.5), "wider than the card, trim the sides"))
    poster = anchor(1000, 1500)[1]        # 2:3 gig poster
    photo = anchor(1200, 900)[1]          # 4:3 press shot
    square = anchor(1000, 1000)[1]
    checks.append((poster < square < photo < 0.45,
                   f"taller crops higher ({poster:.2f} < {square:.2f} < {photo:.2f})"))
    checks.append((poster <= 0.06, f"a 2:3 poster keeps its title ({poster:.2f})"))
    checks.append((0.2 <= square <= 0.35, f"a square photo keeps its faces ({square:.2f})"))
    checks.append((anchor(800, 4000)[1] >= 0.03, "anchor never leaves the picture"))

    # a transparent logo must not come out as a black rectangle. 16:9 on purpose:
    # this is testing the alpha flattening, not where the crop is taken from.
    png = Image.new("RGBA", (640, 360), (0, 0, 0, 0))
    for x in range(280, 360):
        for y in range(140, 220):
            png.putpixel((x, y), (255, 90, 20, 255))
    buf = io.BytesIO()
    png.save(buf, "PNG")
    out = Image.open(io.BytesIO(crop(buf.getvalue())))
    checks.append((out.getpixel((320, 180))[0] > 100, "transparent PNG keeps its subject"))
    checks.append((out.getpixel((10, 10)) != (0, 0, 0), "and its transparency is not black"))

    # the same URL always lands on the same filename, two bands never collide
    a = name_for("Unsane", "https://x.test/a.jpg")
    checks.append((a == name_for("Unsane", "https://x.test/a.jpg"), "filename is stable"))
    checks.append((a != name_for("Unsane", "https://x.test/b.jpg"), "same band, two photos"))
    checks.append((name_for("Bad//Brains", "https://x.test/a.jpg").startswith("bad-brains-"),
                   "punctuation out of the filename"))

    # which shows get a file
    checks.append((wanted({"image": "https://x.test/a.jpg"}), "remote photo wanted"))
    checks.append((not wanted({"image": ""}), "no photo, no file"))
    checks.append((not wanted({"image": "img/moshpit2.jpg"}), "generic photo skipped"))
    checks.append((not wanted({"image": "https://www.mikidrummer.ca/img/x.jpg"}),
                   "our own file left alone"))

    bad = 0
    for ok, label in checks:
        bad += not ok
        print(f"  [{'ok' if ok else 'FAIL'}] {label}")
    print("self-test:", "passed" if not bad else f"{bad} failure(s)")
    return 1 if bad else 0


def main() -> int:
    args = sys.argv[1:]
    if "--self-test" in args:
        return self_test()
    force = "--force" in args

    ART.mkdir(parents=True, exist_ok=True)
    # The index is loaded even under --force. A forced run re-fetches everything,
    # but a host having a bad minute must not cost us a picture we already had:
    # anything that fails keeps the copy on file.
    index = {}
    if INDEX.exists():
        try:
            index = json.loads(INDEX.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("index.json unreadable — starting it again")

    shows = json.loads(DATA.read_text(encoding="utf-8"))["shows"]
    sources = {}
    for s in shows:
        if wanted(s):
            sources.setdefault(s["image"], s.get("band") or "art")

    got = kept = failed = 0
    for url, band in sources.items():
        have = index.get(url)
        on_file = bool(have) and (ART / have).exists()
        if on_file and not force:
            continue
        try:
            data = crop(download(url))
        except Exception as e:
            if on_file:
                print(f"  could not re-fetch {band}'s photo ({e}) — keeping the copy on file")
                kept += 1
            else:
                # A dead link is not a reason to fail the build: build_digest
                # falls back to the original URL, which is where it came from.
                print(f"  could not use {band}'s photo ({e}) — leaving it remote")
                failed += 1
            continue
        name = name_for(band, url)
        (ART / name).write_bytes(data)
        if have and have != name:
            (ART / have).unlink(missing_ok=True)
        index[url] = name
        got += 1
        print(f"  {band} -> img/digest/{name} ({len(data) // 1024}KB)")

    # forget shows that have left the board, and delete the files with them
    index = {u: n for u, n in index.items() if u in sources}
    keep = set(index.values())
    dropped = 0
    for f in ART.glob("*.jpg"):
        if f.name not in keep:
            f.unlink()
            dropped += 1

    INDEX.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"art: {len(index)} on file ({got} fetched, {kept} kept as they were, "
          f"{failed} left remote, {dropped} pruned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
