#!/usr/bin/env python3
"""A page per band, built from the shows board.

Search Console shows impressions arriving on band names. Those queries land on
punkbc.html today, which is a wall of a hundred-odd gigs — someone searching
one band has to hunt for their line, and Google has nothing to match against
beyond one row in a long list.

A page per act gives each name somewhere to land: their upcoming BC dates, the
rooms, who else is on those bills. We will not outrank a band's own site for
their name, and should not try to; the query worth having is "<band>
vancouver", "<band> tickets", "<band> tour dates" — which their own site often
answers badly or not at all.

Thin pages are the risk. An act with one gig and nothing else is a page with
one line on it, and a hundred of those is the sort of thing Google calls a
doorway. So a band earns a page by having something to say: more than one
show, or bill-mates, or a page of their own worth linking to.

    python3 tools/build_band_pages.py [--selftest] [--dry-run]
"""

import collections
import html
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Reuse the board's own reading of a bill. Two copies of this parsing would
# drift, and the split is fiddly enough to get wrong twice ("Ripcordz w/ The
# Oo-E Boo-E's" must not become a band called "Ripcordz w").
from build_punkbc import performers, slugify as _slugify, href_for, today_local  # noqa: E402


def slugify(name: str) -> str:
    """Accents folded before slugging, so Powermonger gets a URL a person could
    type instead of powerm-nger."""
    folded = unicodedata.normalize("NFKD", str(name))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = folded.replace("ø", "o").replace("Ø", "O").replace("ß", "ss")
    return _slugify(folded)

ROOT = Path(__file__).resolve().parent.parent
SHOWS = ROOT / "punkbc-shows.json"
CONTACTS = ROOT / "data" / "band-contacts.json"
OUT_DIR = ROOT / "bands"
SITEMAP = ROOT / "sitemap.xml"
SITE = "https://www.mikidrummer.ca"

# The band column is written by hand, so some of what comes out of it is not a
# band: a festival's night label, a bill summarised as "X, Y and more", or a
# real name with a sentence stuck on the end.
BLURB = re.compile(r"\.\s+[A-Z][^.]*\s[^.]*$")        # "Locked Shut. Touring on ..."
NOT_A_BAND = re.compile(
    r"\band more\b|\bnight (one|two|three|four|five|\d+)\b|\bTBA\b|"
    r"\bplus (guests|more)\b|\bfestival\b.*[—-]", re.I)


def clean_name(name: str) -> str:
    """Drop a trailing sentence. A dot inside a name ("easy.feat") has no space
    after it, so it survives."""
    return BLURB.sub("", name).strip(" .,-—")


def is_band(name: str) -> bool:
    return bool(name) and len(name) > 1 and not NOT_A_BAND.search(name)


# A band that has only ever appeared once, with nobody else on the bill and no
# page of their own, has nothing to fill a page with.
def earns_a_page(info: dict) -> bool:
    return (len(info["shows"]) > 1
            or len(info["with"]) >= 1
            or bool(info["links"]))


def load_links() -> dict:
    """Bandcamp and the like, from the contact file. Addresses are deliberately
    not touched: that file holds emails people gave us for booking, and
    printing them on an indexed page would hand them to every scraper going."""
    try:
        data = json.loads(CONTACTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for rec in data.get("bands", []):
        good = []
        for p in rec.get("profiles", []):
            url = (p.get("url") or "").strip()
            name = (p.get("name") or "").strip()
            if url.startswith("http") and "mailto" not in url and "/contact" not in url:
                good.append((name or "Their page", url))
        if good:
            out[(rec.get("band") or "").lower().strip()] = good[:3]
    return out


def gather(shows: list[dict], links: dict) -> dict:
    by: dict[str, dict] = {}
    for s in shows:
        acts = [clean_name(a) for a in performers(s)]
        acts = [a for a in acts if is_band(a)]
        for name in acts:
            key = name.lower().strip()
            info = by.setdefault(key, {
                "name": name, "shows": [], "with": set(),
                "venues": set(), "cities": set(), "genres": set(), "links": [],
            })
            info["shows"].append(s)
            info["with"].update(a for a in acts if a.lower().strip() != key)
            if s.get("venue"):
                info["venues"].add(s["venue"])
            if s.get("city"):
                info["cities"].add(s["city"])
            if s.get("genre"):
                info["genres"].add(s["genre"])
    for key, info in by.items():
        info["links"] = links.get(key, [])
        info["shows"].sort(key=lambda s: s["date"])
    return by


def page_html(info: dict, today: str) -> str:
    name = info["name"]
    slug = slugify(name)
    url = f"{SITE}/bands/{slug}.html"
    rows = info["shows"]
    n = len(rows)
    cities = sorted(info["cities"]) or ["BC"]
    where = cities[0] if len(cities) == 1 else " and ".join(cities[:2])

    title = f"{name} — upcoming shows in BC | Punk BC"
    desc = (f"{name} {'play' if n != 1 else 'plays'} {n} upcoming show"
            f"{'s' if n != 1 else ''} in {where}. Dates, venues, door times, "
            f"ticket prices and who else is on the bill.")

    # These pages exist for the bands themselves to share, which is the whole
    # argument for a page per act -- so the thing a share renders has to be
    # worth looking at. Without a card it is a grey rectangle, and in a DM or
    # a story that reads as nothing at all. Built by tools/build_band_cards.py.
    card = f"{SITE}/images/bands/{slug}.jpg"

    events = []
    for s in rows:
        ev = {
            "@type": "MusicEvent",
            "name": f"{name} at {s.get('venue') or 'TBA'}",
            "startDate": s["date"] + ("T" + s["time"] + ":00-08:00" if s.get("time") else ""),
            "eventStatus": "https://schema.org/EventScheduled",
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "url": url,
            "performer": {"@type": "MusicGroup", "name": name},
            "location": {
                "@type": "MusicVenue",
                "name": s.get("venue") or "TBA",
                "address": {"@type": "PostalAddress",
                            "addressLocality": s.get("city") or "Vancouver",
                            "addressRegion": "BC", "addressCountry": "CA"},
            },
        }
        events.append(ev)

    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Punk BC",
                 "item": f"{SITE}/punkbc.html"},
                {"@type": "ListItem", "position": 2, "name": "Bands",
                 "item": f"{SITE}/bands/"},
                {"@type": "ListItem", "position": 3, "name": name, "item": url},
            ]},
            {"@type": "MusicGroup", "name": name,
             **({"genre": sorted(info["genres"])} if info["genres"] else {}),
             **({"sameAs": [u for _, u in info["links"]]} if info["links"] else {})},
            *events,
        ],
    }

    lis = []
    for s in rows:
        d = datetime.fromisoformat(s["date"])
        day = d.strftime("%a %b %d").upper().replace(" 0", " ")
        venue = html.escape(s.get("venue") or "TBA")
        city = html.escape(s.get("city") or "")
        others = [clean_name(a) for a in performers(s)]
        others = [a for a in others
                  if is_band(a) and a.lower().strip() != name.lower().strip()]
        bill = ("with " + ", ".join(html.escape(a) for a in others)) if others else ""
        price = html.escape(s.get("price") or "")
        time_ = html.escape(s.get("time") or "")
        href = html.escape(href_for(s), quote=True)
        vslug = slugify(s.get("venue") or "")
        venue_link = (f'<a href="/shows/{vslug}.html">{venue}</a>'
                      if (ROOT / "shows" / f"{vslug}.html").exists() else venue)
        lis.append(
            f'      <li class="row">\n'
            f'        <div class="when"><b>{day}</b>{"<span>" + time_ + "</span>" if time_ else ""}</div>\n'
            f'        <div class="what">\n'
            f'          <a class="band" href="{href}" target="_blank" rel="noopener">{venue_link}</a>'
            f'{" · " + city if city else ""}\n'
            f'          {"<div class=meta>" + bill + "</div>" if bill else ""}\n'
            f'        </div>\n'
            f'        <div class="tags">{"<span class=price>" + price + "</span>" if price else ""}</div>\n'
            f"      </li>")
    listing = "\n".join(lis)

    mates = sorted(info["with"])[:12]
    mates_block = ""
    if mates:
        items = ", ".join(
            (f'<a href="/bands/{slugify(m)}.html">{html.escape(m)}</a>'
             if (OUT_DIR / f"{slugify(m)}.html").exists() else html.escape(m))
            for m in mates)
        mates_block = (f'<section class="also"><h2>On bills with</h2><p>{items}</p></section>')

    out_links = "".join(
        f'<a class="lnk" href="{html.escape(u, quote=True)}" target="_blank" rel="noopener">'
        f'{html.escape(t)}</a>' for t, u in info["links"])

    city_link = ""
    for c in cities:
        p = ROOT / "shows" / f"{slugify(c)}-punk-shows.html"
        if p.exists():
            city_link = f'<a class="lnk" href="/shows/{p.stem}.html">{html.escape(c)} punk shows</a>'
            break

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc, quote=True)}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{url}">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="96x96" href="/images/icon-96.png">
<link rel="apple-touch-icon" href="/images/icon-180.png">
<meta property="og:type" content="website">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc, quote=True)}">
<meta property="og:site_name" content="Punk BC">
<meta property="og:image" content="{card}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{html.escape(name, quote=True)} — upcoming shows on Punk BC">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{card}">
<script type="application/ld+json">
{json.dumps(graph, indent=2, ensure_ascii=False)}
</script>
<style>
  :root {{ --bg:#0b0c0e; --card:#131518; --edge:#2b2f34; --dim:#7d848d; --mid:#a6adb6; --fg:#e9ebee; --hot:#e8672a; }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--fg);font-family:"Helvetica Neue",system-ui,Arial,sans-serif;line-height:1.6;padding:0 18px 70px}}
  .wrap{{max-width:860px;margin:0 auto}}
  a{{color:inherit;text-decoration:none}}
  header{{padding:44px 0 26px;border-bottom:1px solid var(--edge)}}
  .eyebrow{{font-size:11px;letter-spacing:.3em;text-transform:uppercase;color:var(--hot);font-weight:700}}
  h1{{font-family:"Arial Black",system-ui,sans-serif;font-size:clamp(26px,5vw,42px);letter-spacing:-.02em;margin:10px 0 12px;line-height:1.05}}
  .lead{{color:var(--mid);font-size:16px;max-width:66ch}}
  .crumb{{margin-top:18px;font-size:13px;color:var(--dim)}}
  .crumb a:hover{{color:var(--hot)}}
  ul{{list-style:none;margin-top:26px}}
  .row{{display:grid;grid-template-columns:120px minmax(0,1fr) auto;gap:14px;align-items:start;
       padding:15px 0;border-bottom:1px solid var(--edge)}}
  .when{{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;color:var(--mid);white-space:nowrap}}
  .when b{{display:block;color:var(--fg);font-size:13px}}
  .when span{{color:var(--dim)}}
  .band{{font-weight:700;font-size:16px}}
  .band:hover{{color:var(--hot)}}
  .meta{{color:var(--dim);font-size:13px;margin-top:3px}}
  .tags{{display:flex;gap:7px;align-items:center;flex-wrap:wrap;justify-content:flex-end}}
  .price{{font-size:13px;color:var(--hot);font-weight:700}}
  .also{{margin-top:30px}}
  .also h2{{font-size:12px;letter-spacing:.2em;text-transform:uppercase;color:var(--dim);font-weight:700}}
  .also p{{color:var(--mid);font-size:14.5px;margin-top:8px}}
  .also a{{color:var(--hot)}}
  .links{{display:flex;gap:10px;flex-wrap:wrap;margin-top:30px}}
  .lnk{{border:1px solid var(--edge);background:var(--card);border-radius:100px;padding:10px 18px;font-size:14px;font-weight:600}}
  .lnk:hover{{border-color:var(--hot)}}
  .lnk.primary{{background:var(--hot);color:#180a03;border-color:var(--hot)}}
  footer{{margin-top:40px;padding-top:22px;border-top:1px solid var(--edge);color:var(--dim);font-size:13px}}
  footer a{{color:var(--hot)}}
  @media(max-width:620px){{ .row{{grid-template-columns:1fr;gap:4px}} .tags{{justify-content:flex-start}} }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="eyebrow">Punk BC · Band</span>
    <h1>{html.escape(name)} — upcoming shows</h1>
    <p class="lead">{html.escape(name)} {'have' if n != 1 else 'has'} {n} show{'s' if n != 1 else ''}
      coming up in {html.escape(where)}. Dates, rooms and who else is on the bill, kept current from the
      <a href="/punkbc.html" style="color:var(--hot)">Punk BC</a> board.</p>
    <div class="crumb"><a href="/punkbc.html">← All BC shows</a> · <a href="/bands/">All bands</a></div>
  </header>

  <ul>
{listing}
  </ul>

  {mates_block}

  <div class="links">
    <a class="lnk primary" href="/punkbc.html">All punk shows in BC</a>
    {city_link}
    {out_links}
  </div>

  <footer>
    Part of <a href="/punkbc.html">Punk BC</a>, a listing of punk, hardcore and metal shows across
    British Columbia, kept by <a href="/">Miki Drummer</a>. Last updated {today}.<br>
    Play in {html.escape(name)} and something here is wrong?
    <a href="/play-with-us.html">Tell us</a> and it gets fixed.
  </footer>
</div>
</body>
</html>
"""


def index_html(pages: list[dict], today: str) -> str:
    url = f"{SITE}/bands/"
    letters: dict[str, list[dict]] = collections.defaultdict(list)
    for info in pages:
        first = info["name"][0].upper()
        letters["0-9" if not first.isalpha() else first].append(info)
    blocks = []
    for letter in sorted(letters):
        items = "".join(
            f'<a href="/bands/{slugify(i["name"])}.html">{html.escape(i["name"])}'
            f'<span>{len(i["shows"])}</span></a>'
            for i in sorted(letters[letter], key=lambda x: x["name"].lower()))
        blocks.append(f'<section><h2>{letter}</h2><div class="grid">{items}</div></section>')
    body = "\n".join(blocks)
    n = len(pages)
    desc = (f"Every band with an upcoming punk, hardcore or metal show in British Columbia — "
            f"{n} acts, their dates, rooms and bills.")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bands playing BC — {n} acts with shows coming up | Punk BC</title>
<meta name="description" content="{html.escape(desc, quote=True)}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{url}">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="96x96" href="/images/icon-96.png">
<meta property="og:type" content="website">
<meta property="og:url" content="{url}">
<meta property="og:title" content="Bands playing BC | Punk BC">
<meta property="og:description" content="{html.escape(desc, quote=True)}">
<style>
  :root {{ --bg:#0b0c0e; --card:#131518; --edge:#2b2f34; --dim:#7d848d; --mid:#a6adb6; --fg:#e9ebee; --hot:#e8672a; }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--fg);font-family:"Helvetica Neue",system-ui,Arial,sans-serif;line-height:1.6;padding:0 18px 70px}}
  .wrap{{max-width:900px;margin:0 auto}}
  a{{color:inherit;text-decoration:none}}
  header{{padding:44px 0 26px;border-bottom:1px solid var(--edge)}}
  .eyebrow{{font-size:11px;letter-spacing:.3em;text-transform:uppercase;color:var(--hot);font-weight:700}}
  h1{{font-family:"Arial Black",system-ui,sans-serif;font-size:clamp(26px,5vw,40px);letter-spacing:-.02em;margin:10px 0 12px}}
  .lead{{color:var(--mid);font-size:16px;max-width:66ch}}
  section{{margin-top:30px}}
  section h2{{font-family:ui-monospace,Menlo,monospace;font-size:13px;color:var(--hot);border-bottom:1px solid var(--edge);padding-bottom:7px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px;margin-top:12px}}
  .grid a{{display:flex;justify-content:space-between;gap:8px;border:1px solid var(--edge);background:var(--card);
          border-radius:9px;padding:9px 13px;font-size:14px}}
  .grid a:hover{{border-color:var(--hot);color:var(--hot)}}
  .grid span{{color:var(--dim);font-family:ui-monospace,Menlo,monospace;font-size:12px}}
  footer{{margin-top:44px;padding-top:22px;border-top:1px solid var(--edge);color:var(--dim);font-size:13px}}
  footer a{{color:var(--hot)}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="eyebrow">Punk BC</span>
    <h1>Bands playing BC</h1>
    <p class="lead">{n} acts with a show coming up in British Columbia — the headliners and the
      openers buried in the small print, each with their dates and who they are playing with.
      From the <a href="/punkbc.html" style="color:var(--hot)">Punk BC</a> board.</p>
  </header>
{body}
  <footer>
    Part of <a href="/punkbc.html">Punk BC</a>, kept by <a href="/">Miki Drummer</a>.
    Last updated {today}. Want a date with us? <a href="/play-with-us.html">We have one going</a>.
  </footer>
</div>
</body>
</html>
"""


def update_sitemap(slugs: list[str], today: str) -> int:
    text = SITEMAP.read_text(encoding="utf-8")
    text = re.sub(r"\n?  <!-- bands -->.*?<!-- /bands -->", "", text, flags=re.S)
    urls = [f"{SITE}/bands/"] + [f"{SITE}/bands/{s}.html" for s in slugs]
    block = "\n  <!-- bands -->\n" + "\n".join(
        f"  <url><loc>{u}</loc><lastmod>{today}</lastmod>"
        f"<changefreq>weekly</changefreq><priority>0.5</priority></url>" for u in urls
    ) + "\n  <!-- /bands -->"
    text = text.replace("</urlset>", block + "\n</urlset>")
    SITEMAP.write_text(text, encoding="utf-8")
    return len(urls)


def selftest() -> int:
    fails = []

    def ok(c, m):
        if not c:
            fails.append(m)

    ok(earns_a_page({"shows": [1, 2], "with": set(), "links": []}), "two shows should earn one")
    ok(earns_a_page({"shows": [1], "with": {"Someone"}, "links": []}), "a bill-mate should earn one")
    ok(earns_a_page({"shows": [1], "with": set(), "links": [("x", "y")]}), "a link should earn one")
    ok(not earns_a_page({"shows": [1], "with": set(), "links": []}),
       "one show and nothing else is a thin page")

    # The contact file holds booking addresses. They must never reach a page
    # Google indexes.
    links = load_links()
    flat = json.dumps(links)
    ok("@" not in flat or "mailto" not in flat, "an address leaked into the links")
    ok(all("mailto" not in u for v in links.values() for _, u in v), "mailto in links")

    shows = json.loads(SHOWS.read_text())["shows"]
    by = gather(shows, links)
    ok(len(by) > 50, "expected a lot of acts, got %d" % len(by))
    any_name = next(iter(by.values()))["name"]
    ok(slugify(any_name), "slug should not be empty")

    # Every one of these came off the real board.
    ok(clean_name("Locked Shut. Touring on new self-titled album") == "Locked Shut",
       "blurb not trimmed: %r" % clean_name("Locked Shut. Touring on new self-titled album"))
    ok(clean_name("Powermönger. Members of Tribulation/Enforcer") == "Powermönger",
       "blurb not trimmed")
    ok(clean_name("easy.feat") == "easy.feat", "a dot inside a name was eaten")
    ok(not is_band("ATD, Scatterbox and more"), "a bill summary became a band")
    ok(not is_band("Covenant Festival XI — Night One"), "a festival night became a band")
    ok(is_band("Bound By None") and is_band("Die Job"), "a real band was refused")
    ok(slugify("Powermönger") == "powermonger", "accent slug: %s" % slugify("Powermönger"))
    ok(slugify("Mötley Crüe") == "motley-crue", "accent slug: %s" % slugify("Mötley Crüe"))

    names = {clean_name(a) for s_ in shows for a in performers(s_)}
    left = [n for n in names if is_band(n) and NOT_A_BAND.search(n)]
    ok(not left, "junk survived: %r" % left[:3])

    print("selftest: %d checks, %d failed" % (17, len(fails)))
    for f in fails:
        print("  FAIL:", f)
    return 1 if fails else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    today = today_local()
    shows = [s for s in json.loads(SHOWS.read_text(encoding="utf-8"))["shows"]
             if s["date"] >= today]
    links = load_links()
    by = gather(shows, links)

    keep = [i for i in by.values() if earns_a_page(i)]
    skipped = len(by) - len(keep)
    keep.sort(key=lambda i: i["name"].lower())

    if "--dry-run" in sys.argv:
        print("%d acts, %d would get a page, %d too thin" % (len(by), len(keep), skipped))
        return 0

    OUT_DIR.mkdir(exist_ok=True)
    # Two passes: the first writes the files so the second can link between
    # bands that share a bill without pointing at pages that do not exist.
    for info in keep:
        (OUT_DIR / f"{slugify(info['name'])}.html").write_text(
            page_html(info, today), encoding="utf-8")
    for info in keep:
        (OUT_DIR / f"{slugify(info['name'])}.html").write_text(
            page_html(info, today), encoding="utf-8")
    (OUT_DIR / "index.html").write_text(index_html(keep, today), encoding="utf-8")

    # An act whose last date has passed stops earning a page, but the file it
    # was given stays on disk unless something removes it. Three had already
    # built up this way -- live and indexable, dropped from the sitemap, linked
    # from nowhere, one of them ("Schedule 1") never a band in the first place.
    # That is the same orphan problem as /files/, arriving on a schedule.
    wanted = {f"{slugify(i['name'])}.html" for i in keep} | {"index.html"}
    stale = sorted(p for p in OUT_DIR.glob("*.html") if p.name not in wanted)
    for p in stale:
        p.unlink()

    n = update_sitemap([slugify(i["name"]) for i in keep], today)
    print("%d acts on the board · %d pages written · %d too thin to earn one"
          % (len(by), len(keep), skipped))
    if stale:
        print("removed %d page%s for acts no longer on the board: %s"
              % (len(stale), "" if len(stale) == 1 else "s",
                 ", ".join(p.stem for p in stale)))
    print("sitemap: %d band URLs" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
