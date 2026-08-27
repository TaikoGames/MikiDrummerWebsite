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

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")

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


def crop(raw: bytes, size=SIZE) -> bytes:
    """Source bytes in, a JPEG of exactly `size` out.

    Centred a little above the middle: posters put the headline at the top and
    photographs put faces above the waist, so a dead-centre crop takes the
    chest of the picture and loses both.
    """
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
    im = ImageOps.fit(im, size, method=Image.LANCZOS, centering=(0.5, 0.38))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    return buf.getvalue()


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read(MAX_BYTES + 1)
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

    # a transparent logo must not come out as a black rectangle
    png = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    for x in range(150, 250):
        for y in range(150, 250):
            png.putpixel((x, y), (255, 90, 20, 255))
    buf = io.BytesIO()
    png.save(buf, "PNG")
    out = Image.open(io.BytesIO(crop(buf.getvalue())))
    checks.append((out.getpixel((320, 180))[0] > 100, "transparent PNG keeps its subject"))

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
    index = {}
    if INDEX.exists() and not force:
        try:
            index = json.loads(INDEX.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("index.json unreadable — starting it again")

    shows = json.loads(DATA.read_text(encoding="utf-8"))["shows"]
    sources = {}
    for s in shows:
        if wanted(s):
            sources.setdefault(s["image"], s.get("band") or "art")

    got = failed = 0
    for url, band in sources.items():
        name = index.get(url)
        if name and (ART / name).exists():
            continue
        name = name_for(band, url)
        try:
            data = crop(download(url))
        except Exception as e:
            # A dead link is not a reason to fail the build: build_digest falls
            # back to the original URL, which is exactly where we are today.
            print(f"  could not use {band}'s photo ({e}) — leaving it remote")
            failed += 1
            continue
        (ART / name).write_bytes(data)
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
    print(f"art: {len(index)} on file ({got} new, {failed} left remote, {dropped} pruned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
