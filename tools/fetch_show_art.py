#!/usr/bin/env python3
"""Give shows a real image instead of the placeholder, and prove it lands.

Runs on a GitHub runner, because the machine this was written on cannot reach
a single image host — bcbits, last.fm, Wikimedia, ytimg and gigpit are all
refused at its egress proxy, so nothing here could be checked from there.

Where the art comes from, in order:

  1. The ticket page already on the show — gigpit, Eventbrite, Facebook, the
     venue's own calendar. Its og:image is the poster the promoter published
     for that exact night, which is better provenance than a band photo found
     by name: there is no chance of pulling the wrong band with a similar one.
  2. Failing that, the band's own page named in ART_SOURCES below, hand-checked
     rather than guessed at from a search result.

Every candidate is downloaded and opened before it is accepted. A URL that
404s, redirects to a login wall, or serves a 1x1 tracking pixel or a tiny
avatar is refused, and the show keeps the placeholder. Anything accepted is
saved under images/shows/ and served from this site, so it cannot rot when
someone reorganises their CDN, and no visitor is tracked by a third party.

Usage:
  python3 tools/fetch_show_art.py            # fill in missing art, write files
  python3 tools/fetch_show_art.py --check    # report only, write nothing
  python3 tools/fetch_show_art.py --self-test
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "punkbc-shows.json"
ART_DIR = ROOT / "images" / "shows"
SITE = "https://www.mikidrummer.ca"
PLACEHOLDER = f"{SITE}/punkbc-placeholder.svg"

UA = "MikiDrummerBot/1.0 (+https://www.mikidrummer.ca/punkbc.html) Python-urllib"
PAUSE = 0.5          # be a polite guest on other people's servers
TIMEOUT = 25
MIN_SIDE = 300       # below this it is an avatar or a favicon, not a poster
MAX_BYTES = 8_000_000

# Bands whose own page is the fallback when a show has no ticket link. Each of
# these was looked up by hand — a name search alone is how a listing ends up
# showing a different band with the same name.
ART_SOURCES = {
    # Denver, Gregg Deal's band — deadpioneers.bandcamp.com is their own page.
    "dead pioneers": "https://deadpioneers.bandcamp.com/album/dead-pioneers",
    # West Philly trio. Not "darkthoughtspom", and not the Funeral Portrait
    # song of the same name — both come back first on a plain name search.
    "dark thoughts": "https://dark-thoughts.bandcamp.com/",
    # London, going since 1995. Their own Bandcamp, not a label compilation.
    "the restarts": "https://therestarts.bandcamp.com/",
    # Toronto. Their own site rather than a label or a festival listing.
    "the obgms": "https://theobgms.com/",
}

# Hosts that hand back a login wall or an expiring signed URL rather than the
# picture. Fetching them wastes the run and can bake in a link that dies.
SKIP_HOSTS = ("facebook.com", "fbcdn.net", "instagram.com", "cdninstagram.com")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "show"


def get(url: str, limit: int = MAX_BYTES) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,image/avif,image/webp,image/*,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(limit + 1)[:limit]


# og:image, then twitter:image, then a JSON-LD "image". Ordered by how likely
# each is to be the poster rather than a logo in the page furniture.
META = [
    re.compile(rb'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(rb'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I),
    re.compile(rb'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(rb'"image"\s*:\s*"([^"]+\.(?:jpe?g|png|webp)[^"]*)"', re.I),
]


def og_image(html: bytes, base: str) -> str | None:
    for pat in META:
        m = pat.search(html)
        if not m:
            continue
        url = m.group(1).decode("utf-8", "replace").strip()
        url = url.replace("&amp;", "&")
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            m2 = re.match(r"(https?://[^/]+)", base)
            if not m2:
                continue
            url = m2.group(1) + url
        if url.startswith("http"):
            return url
    return None


def usable(raw: bytes) -> tuple[bool, str]:
    """Is this actually a picture worth putting on a listing?"""
    if not raw:
        return False, "empty response"
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception as e:
        return False, f"not a readable image ({type(e).__name__})"
    w, h = im.size
    if w < MIN_SIDE or h < MIN_SIDE:
        return False, f"too small at {w}x{h} — avatar or tracking pixel"
    return True, f"{w}x{h} {im.format}"


def candidates(show: dict) -> list[tuple[str, str]]:
    """(where it came from, url) in the order they should be tried."""
    out = []
    ticket = (show.get("ticket") or "").strip()
    if ticket.startswith("http") and not any(h in ticket for h in SKIP_HOSTS):
        out.append(("ticket page", ticket))
    src = ART_SOURCES.get((show.get("band") or "").split(" / ")[0].strip().lower())
    if src:
        out.append(("band's own page", src))
    return out


def art_for(show: dict, report: list) -> tuple[bytes, str, str] | None:
    for where, page in candidates(show):
        try:
            html = get(page)
            time.sleep(PAUSE)
        except Exception as e:
            report.append(f"      {where}: could not open — {e}")
            continue
        img = og_image(html, page)
        if not img:
            report.append(f"      {where}: no og:image on the page")
            continue
        try:
            raw = get(img)
            time.sleep(PAUSE)
        except Exception as e:
            report.append(f"      {where}: image would not download — {e}")
            continue
        ok, why = usable(raw)
        if not ok:
            report.append(f"      {where}: refused — {why}")
            continue
        report.append(f"      {where}: {why} from {img[:70]}")
        return raw, img, where
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    data = json.loads(DATA.read_text(encoding="utf-8"))
    shows = data["shows"]
    ART_DIR.mkdir(parents=True, exist_ok=True)

    todo = [s for s in shows if not (s.get("image") or "").strip()
            or s.get("image") == PLACEHOLDER]
    print(f"{len(todo)} of {len(shows)} shows have no real art\n")

    got = kept = 0
    for s in todo:
        head = f"{s['date']}  {s['band'][:52]}"
        report: list[str] = []
        found = art_for(s, report)
        print(head)
        for line in report:
            print(line)
        if not found:
            print("      -> keeping the placeholder\n")
            kept += 1
            continue
        raw, src, where = found
        name = f"{slug(s['band'].split(' / ')[0])}-{s['date']}.jpg"
        if not args.check:
            from PIL import Image
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            im.thumbnail((1200, 1200))
            im.save(ART_DIR / name, quality=86, optimize=True, progressive=True)
            s["image"] = f"{SITE}/images/shows/{name}"
            s.setdefault("image_source", src)
        print(f"      -> images/shows/{name}  (via the {where})\n")
        got += 1

    if not args.check:
        DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"art found for {got}, placeholder kept for {kept}"
          + ("  (check only, nothing written)" if args.check else ""))
    return 0


def self_test() -> int:
    checks = []

    html = b'<meta property="og:image" content="https://x.test/a.jpg">'
    checks.append(("og:image read", og_image(html, "https://x.test/p") == "https://x.test/a.jpg"))

    html = b'<meta content="https://x.test/b.jpg" property="og:image">'
    checks.append(("attributes reversed", og_image(html, "https://x.test/p") == "https://x.test/b.jpg"))

    html = b'<meta property="og:image" content="/rel/c.jpg">'
    checks.append(("relative made absolute",
                   og_image(html, "https://x.test/page") == "https://x.test/rel/c.jpg"))

    html = b'<meta property="og:image" content="//cdn.test/d.jpg">'
    checks.append(("protocol-relative", og_image(html, "https://x.test/p") == "https://cdn.test/d.jpg"))

    checks.append(("no image found", og_image(b"<html></html>", "https://x.test/p") is None))

    ok, why = usable(b"")
    checks.append(("empty refused", not ok))
    ok, why = usable(b"<html>not an image</html>")
    checks.append(("html refused", not ok))

    try:
        from PIL import Image
        buf = io.BytesIO(); Image.new("RGB", (1, 1)).save(buf, "PNG")
        ok, why = usable(buf.getvalue())
        checks.append(("1x1 pixel refused", not ok and "too small" in why))
        buf = io.BytesIO(); Image.new("RGB", (800, 800)).save(buf, "JPEG")
        ok, why = usable(buf.getvalue())
        checks.append(("real image accepted", ok))
    except ImportError:
        checks.append(("Pillow present", False))

    checks.append(("facebook skipped",
                   candidates({"ticket": "https://facebook.com/events/s/x/1/"}) == []))
    checks.append(("ticket page used",
                   candidates({"ticket": "https://gigpit.ca/shows/event:x"})[0][0] == "ticket page"))

    for name, ok in checks:
        print(("  [ok] " if ok else "  [FAIL] ") + name)
    bad = sum(1 for _, ok in checks if not ok)
    print("self-test:", "passed" if not bad else f"{bad} FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
