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

    # ── Added 2026-11-06, each checked against what the band is ──
    # Vancouver ska-punk with a horn section. Not BRASS (Vancouver hardcore,
    # brassvan.bandcamp.com) and not The Brass Action (ska, split up).
    "brasser": "https://brasserska.bandcamp.com/",
    # Lethbridge Invasion is a two-night bill; Golers top both nights, so
    # their own page stands for the event.
    "lethbridge invasion — night 1": "https://thegolers.bandcamp.com/",
    "lethbridge invasion — night 2": ["https://thegolers.bandcamp.com/album/backwoods-messages",
                                      "https://thegolers.bandcamp.com/"],
    # Vic Bondi of Articles of Faith; His Issues is his Seattle band on
    # Alternative Tentacles. His own Bandcamp.
    "vic bondi and his issues": "https://vicbondi.bandcamp.com/",
    # Vancouver punk since 2010 -- not The Anchoress (Catherine Anne Davies, UK).
    "anchoress": "https://anchoress.bandcamp.com/",
    # Victoria, BC. Not "Meredith Moon & The Oldest Man I Know", a Toronto
    # folk duo that comes back first on a name search.
    "the oldest man i know": "https://theoldestmaniknow.bandcamp.com/",
    # Portland's "pow wow punk rock" band -- the 1876 touring with Terminal
    # City Rats. Their own Bandcamp.
    # Their own album first -- the newest release on the front page was a
    # "Nun Eyes" single that could not be confirmed as theirs.
    "1876": ["https://1876band.bandcamp.com/album/pow-wow-punk-rock-iiii",
             "https://1876band.bandcamp.com/album/pow-wow-punk-rock-iii",
             "https://1876band.bandcamp.com/"],
    # The Spill Canvas's orchestra tour; its own site.
    # The tour's own event pages: their image is the Emo Orchestra artwork.
    # (emosnotdead.com was tried first and gave its merch shop's banner.)
    # Not the tour's posters: each is printed with another city's date and
    # venue (the Taft Theatre one said "4/8/26 Cincinnati"). A photo of The
    # Spill Canvas, whose show it is, says nothing wrong.
    "emo orchestra": ["https://en.wikipedia.org/wiki/The_Spill_Canvas"],
    # Famous enough that a name search is a minefield of tributes and fan
    # pages: the band's Wikipedia article instead, whose lead image is a
    # free-licensed photo of that exact band.
    "underoath": "https://en.wikipedia.org/wiki/Underoath",
    "dropkick murphys": "https://en.wikipedia.org/wiki/Dropkick_Murphys",
    "frank turner and the sleeping souls": "https://en.wikipedia.org/wiki/Frank_Turner",
    "the bouncing souls": "https://en.wikipedia.org/wiki/Bouncing_Souls",
    # Santa Rosa pop-punk, back since 2023 on SBÄM. No site or Bandcamp of
    # their own, so their Wikipedia article.
    "diesel boy": [
        "https://en.wikipedia.org/wiki/Diesel_Boy",
        # Their publicist's page for the 2023 comeback album: the band's press shot.
        "https://www.earshotmedia.com/diesel-boy/",
        # Their artist page: Apple's picture is the band's own press image.
        "https://music.apple.com/us/artist/diesel-boy/63683166",
    ],
    # Boston hardcore (Haywire 617) on Roadrunner -- no Bandcamp. Rolling
    # Stone's piece on their album carries the band's own press image.
    "haywire": "https://ca.rollingstone.com/music/haywire-617-i-dont-wanna-say-goodbye/",
    # ── Added 2026-11-06 (second pass): shows on a generic or stand-in picture ──
    # Helsinki black metal; their own Bandcamp.
    "ride for revenge": ["https://ride-for-revenge.bandcamp.com/", "https://rideforrevenge.bandcamp.com/"],
    # No page of their own: their album on their label's Bandcamp (Nuclear War Now!).
    "blasphamagoatachrist": ["https://nuclearwarnowproductions.bandcamp.com/album/bastardizing-the-purity",
                             "https://nuclearwarnowproductions.bandcamp.com/album/black-metal-warfare"],
    # The Burnaby war metal band.
    "blasphemy": ["https://en.wikipedia.org/wiki/Blasphemy_(band)"],
    # Montreal, ex-TRUCK; their own Bandcamp, then Southern Lord's page for them.
    "truck violence": ["https://truckviolence.bandcamp.com/", "https://truckviolencesl.bandcamp.com/"],
    # Victoria, BC: the punk-cover elves.
    "angry snowmans": ["https://angrysnowmans.bandcamp.com/"],
    # Nashville, Rise Records. Their cover story in Melodic, then a feature
    # with a credited band photo.
    "winona fighter": ["https://www.melodicmag.com/interviews/cover-story-winona-fighter-is-turning-summer-school-into-a-basement-show/",
                       "https://www.orlandoweekly.com/music/rising-pop-punkers-winona-fighter-do-warped-tour-double-duty-in-orlando/"],
    # Las Vegas, formed 2023: the Astoria's event page is tried first (its
    # ticket link), then their artist page.
    "deathtape": ["https://music.apple.com/us/artist/deathtape/1726844976"],
    # One night is listed twice (Metal Church; Metal Church / Armored Saint):
    # the second listing gets Armored Saint rather than the same photo again.
    "metal church": ["https://en.wikipedia.org/wiki/Metal_Church", "https://en.wikipedia.org/wiki/Armored_Saint"],
    # Two nights: each gets a different picture.
    "3 inches of blood": ["https://en.wikipedia.org/wiki/3_Inches_of_Blood"],
    # Vancouver punk since 1978. The Rickshaw's poster for their final show
    # would be better, but the Rickshaw refuses the art job (406).
    "pointed sticks": ["https://en.wikipedia.org/wiki/Pointed_Sticks"],
    # San Jose death metal; was on a Spotify playlist cover.
    "exhumed": ["https://en.wikipedia.org/wiki/Exhumed_(band)"],
    # Finnish black metal: their album on KVLT, their label's Bandcamp.
    "beherit": ["https://kvltfinland.bandcamp.com/album/bardo-exist",
                "https://en.wikipedia.org/wiki/Beherit"],
    # X-Mas in Skaville has no art of its own anywhere, and one band's photo
    # on a many-band night would be wrong. It keeps the placeholder.
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


# Pictures that are not of the show or the band: a stock mosh-pit photo used
# for four different shows, Google image-search thumbnails, last.fm's stand-in
# images, the site's own crowd shots. A show carrying one of these is treated
# as having no art at all.
GENERIC = ("Moshpit2", "punkbc-crowd", "placeholder", "encrypted-tbn", "gstatic.com",
           "lastfm.freetls.fastly.net", "last.fm", "lastfm.",
           # a Spotify *playlist* cover ("The Complete X Discography", Spotify
           # logo and all) -- not the band's art
           "spotifycdn.com/image/ab67706c")


def is_generic(url: str) -> bool:
    return any(g.lower() in (url or "").lower() for g in GENERIC)


def is_show_page(url: str) -> bool:
    """A ticket link to a venue's home page or its list of shows has that
    venue's logo as its picture -- the same logo for every show there."""
    from urllib.parse import urlsplit
    path = urlsplit(url).path.strip("/").lower()
    return path not in ("", "shows", "events", "calendar", "whats-on", "tickets")


def candidates(show: dict) -> list[tuple[str, str]]:
    """(where it came from, url) in the order they should be tried. "current
    picture" is an image, everything else is a page to read og:image from."""
    out = []
    current = (show.get("image") or "").strip()
    if current.startswith("http") and "mikidrummer.ca/images/shows/" not in current \
            and not is_generic(current):
        out.append(("current picture", current))
    ticket = (show.get("ticket") or "").strip()
    if ticket.startswith("http") and not any(h in ticket for h in SKIP_HOSTS) \
            and is_show_page(ticket):
        out.append(("ticket page", ticket))
    src = ART_SOURCES.get((show.get("band") or "").split(" / ")[0].strip().lower())
    # One page, or several to try in order.
    for u in ([src] if isinstance(src, str) else (src or [])):
        out.append(("band's own page", u))
    return out


# A Bandcamp front page offers only a small band photo (300x200 and
# refused); the art is on the album pages. When the front page's image is
# no good, follow its first album -- the newest, as Bandcamp lists them --
# and take that cover. It is the band's own page either way.
BANDCAMP_ALBUM = re.compile(rb'href=["\']((?:https://[a-z0-9-]+\.bandcamp\.com)?/(?:album|track)/[a-z0-9-]+)', re.I)


def bandcamp_album(html: bytes, page: str) -> str | None:
    if ".bandcamp.com" not in page:
        return None
    m = BANDCAMP_ALBUM.search(html)
    if not m:
        return None
    href = m.group(1).decode()
    if href.startswith("/"):
        from urllib.parse import urlsplit
        p = urlsplit(page)
        href = f"{p.scheme}://{p.netloc}{href}"
    return href


def ahash(raw: bytes) -> int:
    """A 64-bit average hash: the same picture at another size or quality
    hashes the same, which a byte comparison would miss."""
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert("L").resize((8, 8), Image.LANCZOS)
    px = list(im.tobytes())        # one byte per pixel in L mode
    avg = sum(px) / 64
    return sum(1 << i for i, v in enumerate(px) if v >= avg)


def same_picture(a: int, b: int) -> bool:
    return bin(a ^ b).count("1") <= 6


def art_for(show: dict, report: list, taken: list | None = None) -> tuple[bytes, str, str] | None:
    taken = taken if taken is not None else []
    todo = list(candidates(show))
    followed = set()
    while todo:
        where, page = todo.pop(0)
        if where == "current picture":
            # Already an image: no page to read, just check it.
            try:
                raw = get(page)
                time.sleep(PAUSE)
            except Exception as e:
                report.append(f"      {where}: would not download — {e}")
                continue
            ok, why = usable(raw)
            if ok and any(same_picture(ahash(raw), t) for t in taken):
                ok, why = False, "the same picture as another show"
            if not ok:
                report.append(f"      {where}: refused — {why}")
                continue
            report.append(f"      {where}: {why}, kept and saved here")
            return raw, page, where
        try:
            html = get(page)
            time.sleep(PAUSE)
        except Exception as e:
            report.append(f"      {where}: could not open — {e}")
            continue
        album = bandcamp_album(html, page)
        def try_album(why_not: str) -> None:
            if album and album not in followed and album != page:
                followed.add(album)
                report.append(f"      {where}: {why_not} -- trying its latest album")
                todo.insert(0, ("band's album page", album))
        img = og_image(html, page)
        if not img:
            report.append(f"      {where}: no og:image on the page")
            try_album("no picture")
            continue
        try:
            raw = get(img)
            time.sleep(PAUSE)
        except Exception as e:
            report.append(f"      {where}: image would not download — {e}")
            continue
        ok, why = usable(raw)
        if ok and is_generic(img):
            ok, why = False, "a stand-in, not a picture of the band"
        if ok and any(same_picture(ahash(raw), t) for t in taken):
            ok, why = False, "the same picture as another show"
        if not ok:
            report.append(f"      {where}: refused — {why}")
            try_album("no usable picture")
            continue
        report.append(f"      {where}: {why} from {img[:70]}")
        return raw, img, where
    return None


CARD_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
CARD_FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def make_card(show: dict) -> bytes:
    """The last resort, and an honest one: the band's name, the date and the
    room, set in the board's colours. Unique to the show by construction, and
    it says exactly what it is rather than standing a stranger's photo in."""
    from datetime import datetime
    from PIL import Image, ImageDraw, ImageFont

    def font(path, size):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            return ImageFont.load_default(size=size)

    W = H = 1080
    im = Image.new("RGB", (W, H), (11, 12, 14))
    d = ImageDraw.Draw(im)
    # a stripe of checkerboard top and bottom, the board's ska/punk furniture
    sq = 60
    for y0 in (0, H - sq * 2):
        for row in range(2):
            for col in range(W // sq + 1):
                if (row + col) % 2 == 0:
                    d.rectangle([col * sq, y0 + row * sq, col * sq + sq - 1, y0 + row * sq + sq - 1],
                                fill=(233, 235, 238))
    eyebrow = (show.get("genre") or "Live").upper()
    d.text((90, 250), eyebrow[:34], font=font(CARD_FONT, 30), fill=(232, 103, 42))
    name = (show.get("band") or "").split(" / ")[0].upper()
    words, lines, cur = name.split(), [], ""
    size = 130 if len(name) < 14 else 104 if len(name) < 26 else 84
    f = font(CARD_FONT, size)
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) > W - 180 and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    y = 310
    for ln in lines[:4]:
        d.text((90, y), ln, font=f, fill=(233, 235, 238))
        y += int(size * 1.02)
    try:
        when = datetime.fromisoformat(show["date"]).strftime("%A, %B ") + str(int(show["date"][8:]))
    except Exception:
        when = show.get("date", "")
    d.text((90, y + 30), when, font=font(CARD_FONT, 46), fill=(233, 235, 238))
    where = ", ".join(x for x in (show.get("venue"), show.get("city")) if x)
    d.text((90, y + 92), where, font=font(CARD_FONT_REG, 38), fill=(166, 173, 182))
    d.text((W - 90 - d.textlength("PUNK BC", font=font(CARD_FONT, 24)), H - sq * 2 - 70),
           "PUNK BC", font=font(CARD_FONT, 24), fill=(125, 132, 141))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=88)
    return out.getvalue()


def is_card(show: dict) -> bool:
    return (show.get("image_source") or "").startswith("Made for Punk BC")


def needs_art(show: dict) -> bool:
    im = (show.get("image") or "").strip()
    if not im or is_generic(im):
        return True
    if "mikidrummer.ca/images/shows/" in im:
        return not (ART_DIR / im.rsplit("/", 1)[1].split("?")[0]).exists()
    return True        # someone else's server: bring it home, or replace it


def local_hash(show: dict) -> int | None:
    im = (show.get("image") or "")
    if "mikidrummer.ca/images/shows/" not in im:
        return None
    f = ART_DIR / im.rsplit("/", 1)[1].split("?")[0]
    try:
        return ahash(f.read_bytes())
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    data = json.loads(DATA.read_text(encoding="utf-8"))
    shows = sorted(data["shows"], key=lambda s: (s.get("date") or "", s.get("band") or ""))
    ART_DIR.mkdir(parents=True, exist_ok=True)

    # Every show must end with its own picture, saved here. A show whose saved
    # picture is the same as an earlier show's counts as having none.
    # Cards are left out of the comparison: they are unique by what they say,
    # but all look alike to a picture hash. They are tried again each run in
    # case real art has appeared, and kept as they are if it has not.
    taken: list[int] = []
    todo = []
    used_names = {(x.get("image") or "").rsplit("/", 1)[-1] for x in shows}
    for s in shows:
        if is_card(s) and not needs_art(s):
            todo.append(s)
            continue
        h = None if needs_art(s) else local_hash(s)
        if h is not None and not any(same_picture(h, t) for t in taken):
            taken.append(h)
        else:
            todo.append(s)
    print(f"{len(todo)} of {len(shows)} shows need their own picture\n")

    got = cards = 0
    for s in todo:
        head = f"{s['date']}  {s['band'][:52]}"
        report: list[str] = []
        found = art_for(s, report, taken)
        print(head)
        for line in report:
            print(line)
        # The whole bill in the name, and a number if it is still taken: two
        # listings that start with the same band on the same night (Metal
        # Church; Metal Church / Armored Saint) wrote one file, and the second
        # show's picture replaced the first's.
        mine = (s.get("image") or "").rsplit("/", 1)[-1]
        base = f"{slug(s['band'])[:60]}-{s['date']}"
        name, n = f"{base}.jpg", 2
        while name in used_names and name != mine:
            name, n = f"{base}-{n}.jpg", n + 1
        used_names.add(name)
        if not found and is_card(s) and not needs_art(s):
            print("      -> no real picture yet; keeping its card\n")
            continue
        if found:
            raw, src, where = found
            print(f"      -> images/shows/{name}  (via the {where})\n")
            got += 1
        else:
            raw, src, where = make_card(s), "Made for Punk BC: no picture of this show or band could be found.", "card"
            print(f"      -> images/shows/{name}  (a card: nothing unique and right was found)\n")
            cards += 1
        if found:
            taken.append(ahash(raw))
        if not args.check:
            from PIL import Image
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            im.thumbnail((1200, 1200))
            im.save(ART_DIR / name, quality=86, optimize=True, progressive=True)
            s["image"] = f"{SITE}/images/shows/{name}"
            s["image_source"] = src

    if not args.check:
        DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"pictures found for {got}, cards made for {cards}"
          + ("  (check only, nothing written)" if args.check else ""))
    return 0


def _bandcamp_checks(checks: list) -> None:
    html = b'<a href="/album/in-n-outlaws">x</a><a href="/album/older">y</a>'
    checks.append(("bandcamp: first album followed",
                   bandcamp_album(html, "https://thegolers.bandcamp.com/")
                   == "https://thegolers.bandcamp.com/album/in-n-outlaws"))
    checks.append(("bandcamp: only on bandcamp", bandcamp_album(html, "https://x.test/") is None))
    full = b'<a href="https://anchoress.bandcamp.com/album/crime">'
    checks.append(("bandcamp: absolute link kept",
                   bandcamp_album(full, "https://anchoress.bandcamp.com/")
                   == "https://anchoress.bandcamp.com/album/crime"))
    checks.append(("a list of sources is tried in order",
                   [u for _, u in candidates({"band": "Diesel Boy", "ticket": ""})][:1]
                   == ["https://en.wikipedia.org/wiki/Diesel_Boy"]))


def _rule_checks(checks: list) -> None:
    checks.append(("generic: the stock mosh pit", is_generic("https://commons.wikimedia.org/wiki/Special:FilePath/Moshpit2.jpg?width=400")))
    checks.append(("generic: last.fm stand-in", is_generic("https://lastfm.freetls.fastly.net/i/u/300x300/abc")))
    checks.append(("generic: google thumbnail", is_generic("https://encrypted-tbn0.gstatic.com/images?q=x")))
    checks.append(("a band photo is not generic", not is_generic("https://commons.wikimedia.org/wiki/Special:FilePath/Devil_Master.jpg")))
    checks.append(("generic: a Spotify playlist cover", is_generic("https://image-cdn-fa.spotifycdn.com/image/ab67706c0000da84f7")))
    checks.append(("a card is recognised", is_card({"image_source": "Made for Punk BC: no picture"})))
    checks.append(("venue home page is not a show page", not is_show_page("https://rickshawtheatre.com")))
    checks.append(("venue shows list is not a show page", not is_show_page("https://www.commodoreballroom.com/shows")))
    checks.append(("an event page is a show page", is_show_page("https://astoria.pub/events/deathtape-live-in-vancouver/")))
    try:
        from PIL import Image
        card = make_card({"band": "3 Inches of Blood", "date": "2027-01-16", "venue": "Rickshaw Theatre",
                          "city": "Vancouver", "genre": "Heavy Metal"})
        im = Image.open(io.BytesIO(card))
        checks.append(("card is a 1080 square image", im.size == (1080, 1080)))
        other = make_card({"band": "3 Inches of Blood", "date": "2027-01-15", "venue": "Rickshaw Theatre",
                           "city": "Vancouver", "genre": "Heavy Metal"})
        checks.append(("the same band on two nights gets two different cards", card != other))
        a = ahash(card)
        buf = io.BytesIO(); im.resize((540, 540)).save(buf, "JPEG", quality=60)
        checks.append(("a resized copy is the same picture", same_picture(a, ahash(buf.getvalue()))))
        blank = io.BytesIO(); Image.new("RGB", (600, 600), (200, 30, 30)).save(blank, "JPEG")
        checks.append(("a different picture is not", not same_picture(a, ahash(blank.getvalue()))))
    except ImportError:
        pass


def self_test() -> int:
    checks = []
    _bandcamp_checks(checks)
    _rule_checks(checks)

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
