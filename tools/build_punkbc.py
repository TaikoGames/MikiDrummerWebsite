#!/usr/bin/env python3
"""Regenerate the SEO-critical, static parts of punkbc.html from punkbc-shows.json.

This bakes the show list into the raw HTML (so search engines and no-JS users see
it without running JavaScript) and emits schema.org MusicEvent + FAQPage structured
data, so each band/venue/date is eligible for Google's event rich results.

It rewrites four marked regions in punkbc.html and the <lastmod> in sitemap.xml:
  * EVENTS-JSONLD  – <script type="application/ld+json"> array of MusicEvent
  * SHOWS          – static .show-card anchors inside #shows-grid
  * SHOWS-SEED     – the inline `const SEED_SHOWS = [...]` used by the client script
  * FAQ            – visible FAQ block + matching FAQPage JSON-LD

The live page still fetches the Google Sheet at runtime for last-minute additions;
this only regenerates the static baseline. Run it after editing punkbc-shows.json
(the weekly refresh does this automatically).

Usage:  python3 tools/build_punkbc.py
"""

from __future__ import annotations

import collections
import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("America/Vancouver")
except Exception:  # pragma: no cover - fallback if tzdata missing
    _TZ = None

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "punkbc.html"
DATA = ROOT / "punkbc-shows.json"
SITEMAP = ROOT / "sitemap.xml"
SITE = "https://www.mikidrummer.ca"
PAGE_URL = f"{SITE}/punkbc.html"
FALLBACK_IMG = "https://upload.wikimedia.org/wikipedia/commons/9/90/Moshpit2.jpg"

# Venue → ticket/info link (mirrors the client-side venueMap).
VENUE_LINK = {
    "Rickshaw Theatre": "https://rickshawtheatre.com",
    "Biltmore Cabaret": "https://biltmorecabaret.com",
    "Commodore Ballroom": "https://commodoreballroom.com",
    "Cobalt": "https://thecobalt.ca",
    "The Cobalt": "https://thecobalt.ca",
    "Venue": "https://venuelive.ca",
    "Capital Ballroom": "https://capitalballroom.ca",
    "Sugar Nightclub": "https://sugarnightclub.com",
    "The Pearl": "https://thepearlvancouver.com",
    "Astoria": "https://theastoria.ca",
    "The Astoria": "https://theastoria.ca",
    "Red Gate": "https://redgate.tv",
    "Red Gate Arts Society": "https://redgate.tv",
    "Portside Pub": "https://theportsidepub.com",
    "The Portside Pub": "https://theportsidepub.com",
}

# Venue → street address for structured data (public venue addresses).
VENUE_ADDRESS = {
    "Rickshaw Theatre": "254 E Hastings St",
    "The Cobalt": "917 Main St",
    "Cobalt": "917 Main St",
    "Biltmore Cabaret": "2755 Prince Edward St",
    "Astoria": "769 E Hastings St",
    "The Astoria": "769 E Hastings St",
    "Commodore Ballroom": "868 Granville St",
    "The Pearl": "881 Granville St",
    "Capital Ballroom": "858 Yates St",
    "Red Gate": "1965 Main St",
    "Red Gate Arts Society": "1965 Main St",
    "Portside Pub": "7 Alexander St",
    "The Portside Pub": "7 Alexander St",
    "Lucky Bar": "517 Yates St",
    "Hollywood Theatre": "3123 W Broadway",
    "The WISE Hall": "1882 Adanac St",
    "Green Auto": "1822 Pandora St",
    "Jackknife Brewing": "727 Baillie Ave",
}

# The same venue arrives spelled several ways (hand-entered here and in the
# Google Sheet). Left un-normalised it splits the city tabs, produces
# inconsistent MusicVenue entities, and silently misses VENUE_ADDRESS -- which
# is how five Astoria shows ended up with no street address in their schema.
# Keys are lowercased; canonical_venue() does the lookup.
VENUE_ALIAS = {
    "astoria": "The Astoria",
    "astoria pub": "The Astoria",
    "the astoria pub": "The Astoria",
    "cobalt": "The Cobalt",
    "the cobalt cabaret": "The Cobalt",
    "cobalt cabaret": "The Cobalt",
    "wise hall": "The WISE Hall",
    "the wise hall": "The WISE Hall",
    "wise hall & lounge": "The WISE Hall",
    "portside pub": "The Portside Pub",
    "red gate": "Red Gate Arts Society",
    "green auto body": "Green Auto",
    "rickshaw": "Rickshaw Theatre",
    "the rickshaw": "Rickshaw Theatre",
    "the rickshaw theatre": "Rickshaw Theatre",
    "biltmore": "Biltmore Cabaret",
    "the biltmore": "Biltmore Cabaret",
    "the biltmore cabaret": "Biltmore Cabaret",
    "commodore": "Commodore Ballroom",
    "the commodore": "Commodore Ballroom",
    "lanalou's": "LanaLou's",
    "lanalous": "LanaLou's",
    "pearl": "The Pearl",
    "the pearl vancouver": "The Pearl",
    "lucky bar": "Lucky Bar",
    "luckybar": "Lucky Bar",
}

# "Victoria" and "Victoria, BC" are one city, but render as two tabs.
CITY_ALIAS = {
    "victoria, bc": "Victoria",
    "vancouver, bc": "Vancouver",
    "kelowna, bc": "Kelowna",
    "nanaimo, bc": "Nanaimo",
    "burnaby, bc": "Burnaby",
    "surrey, bc": "Surrey",
}


def canonical_venue(name: str) -> str:
    """Fold known spelling variants onto one venue name."""
    name = (name or "").strip()
    if not name:
        return name
    return VENUE_ALIAS.get(name.lower(), name)


def canonical_city(name: str) -> str:
    """Fold '<City>, BC' onto '<City>' so each city gets one tab."""
    name = (name or "").strip()
    if not name:
        return name
    return CITY_ALIAS.get(name.lower(), name)


def today_local() -> str:
    """Today's date in Vancouver, as YYYY-MM-DD.

    zoneinfo needs the `tzdata` package, which isn't installed on this machine
    or necessarily in CI. Without it ZoneInfo() raises, _TZ is None, and a naive
    datetime.utcnow() is already *tomorrow* in Vancouver every evening after 5pm
    PDT -- which silently dropped that night's shows off the board at exactly the
    hour people check what's on tonight. So fall back to UTC minus the Pacific
    offset rather than to UTC itself.
    """
    if _TZ is not None:
        return datetime.now(_TZ).date().isoformat()
    now = datetime.now(timezone.utc)
    # Rough DST fallback, same rule tz_offset() uses below.
    hours = 7 if 4 <= now.month <= 10 else 8
    return (now - timedelta(hours=hours)).date().isoformat()


def tz_offset(date_str: str) -> str:
    """Return the America/Vancouver UTC offset (e.g. '-07:00') for a date."""
    if _TZ is not None:
        try:
            dt = datetime.fromisoformat(date_str + "T20:00").replace(tzinfo=_TZ)
            off = dt.utcoffset()
            total = int(off.total_seconds())
            sign = "+" if total >= 0 else "-"
            total = abs(total)
            return f"{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"
        except Exception:
            pass
    # Rough DST fallback: PDT roughly mid-March .. early-November.
    month = int(date_str[5:7])
    return "-07:00" if 4 <= month <= 10 else "-08:00"


def performers(show: dict) -> list[str]:
    """Every act on the bill, named one at a time.

    A bill arrives from the sheet as a single string — "Belvedere / The Anti
    Queens / Brutal Youth" — and listing all three as one MusicGroup leaves
    none of them searchable by name.

    Split on " / " and never on a bare "/". The same column also holds
    "Ripcordz w/ The Oo-E Boo-E's" and "The Bouncing Souls w/ The Suicide
    Machines", where the slash belongs to "w/"; a bare split would invent a
    band called "Ripcordz w".
    """
    acts = show["band"].split(" / ")
    notes = (show.get("notes") or "").strip()
    if notes.lower().startswith("with "):
        acts += notes[5:].split(",")

    out: list[str] = []
    seen: set[str] = set()
    for name in acts:
        # Support acts are written "With Integrity, Earth Crisis, Juice. 19+",
        # so the last one arrives wearing the door policy. Only a trailing age
        # tag is cut — "easy.feat" is a band name and keeps its dot.
        name = re.sub(r"\.\s*(19\+|all ages)\.?$", "", name.strip(), flags=re.I).strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def href_for(show: dict) -> str:
    return show.get("ticket") or VENUE_LINK.get(show.get("venue", ""), "https://www.eventbrite.ca")


def date_label(show: dict) -> str:
    try:
        dt = datetime.fromisoformat(show["date"])
        label = dt.strftime("%a, %b %-d").upper()
    except Exception:
        return "TBA"
    if show.get("time"):
        label += " · " + show["time"]
    return label


# ── region builders ────────────────────────────────────────────────────────

def build_events_jsonld(shows: list[dict]) -> str:
    events = []
    for s in shows:
        city = s.get("city") or "Vancouver"
        venue = s.get("venue") or "Venue"
        address = {
            "@type": "PostalAddress",
            "addressLocality": city,
            "addressRegion": "BC",
            "addressCountry": "CA",
        }
        if venue in VENUE_ADDRESS:
            address["streetAddress"] = VENUE_ADDRESS[venue]
        img = s.get("image") or FALLBACK_IMG
        offer = {
            "@type": "Offer",
            "url": href_for(s),
            "availability": "https://schema.org/InStock",
        }
        if (s.get("price") or "").strip():
            digits = re.sub(r"[^0-9.]", "", s["price"])
            if digits:
                offer["price"] = digits
                offer["priceCurrency"] = "CAD"
        event = {
            "@context": "https://schema.org",
            "@type": "MusicEvent",
            "name": f"{s['band']} — Live at {venue}, {city}",
            "startDate": f"{s['date']}T{s.get('time') or '20:00'}:00{tz_offset(s['date'])}",
            "eventStatus": "https://schema.org/EventScheduled",
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "location": {"@type": "MusicVenue", "name": venue, "address": address},
            "image": [img],
            "performer": [{"@type": "MusicGroup", "name": n} for n in performers(s)],
            "offers": offer,
            "url": PAGE_URL,
            "organizer": {"@type": "Person", "name": "Miki Drummer", "url": SITE},
        }
        if s.get("genre"):
            event["description"] = f"{s.get('genre')} show at {venue} in {city}, BC."
        events.append(event)
    payload = json.dumps(events, indent=2, ensure_ascii=False)
    return '  <script type="application/ld+json">\n' + payload + "\n  </script>"


def build_show_cards(shows: list[dict]) -> str:
    if not shows:
        # matches the client's empty state, so a no-JS visitor and a crawler see
        # a real message rather than a blank grid
        return ('      <div class="empty-state">\n'
                '        <div class="emoji">\U0001f3b8</div>\n'
                '        <p>No upcoming shows listed right now.<br>'
                'Be the first to submit one!</p>\n'
                '      </div>')
    cards = []
    for s in shows:
        band = html.escape(s["band"])
        venue = html.escape(s.get("venue") or "Venue")
        city = html.escape(s.get("city") or "BC")
        genre = html.escape(s.get("genre") or "")
        notes = html.escape(s.get("notes") or "")
        price = html.escape(s.get("price") or "")
        img = html.escape(s.get("image") or FALLBACK_IMG, quote=True)
        href = html.escape(href_for(s), quote=True)
        genre_tag = f'<span class="tag tag-genre">{genre}</span>' if genre else ""
        price_row = f'<div class="show-price">{price}</div>' if price else ""
        notes_row = (
            f'<div class="show-price" style="color:#6b7280;margin-top:4px;font-size:10px">{notes}</div>'
            if notes else ""
        )
        cards.append(
            f'      <a class="show-card" href="{href}" target="_blank" rel="noopener noreferrer">\n'
            f'        <div style="position:relative;overflow:visible">'
            f'<img class="show-card-img" src="{img}" alt="{band} live in {city}" '
            f'referrerpolicy="no-referrer" loading="lazy" '
            f'onerror="this.src=\'{FALLBACK_IMG}\';this.referrerPolicy=\'no-referrer\'"></div>\n'
            f'        <div class="show-card-body">\n'
            f'          <div class="show-date">{date_label(s)}</div>\n'
            f'          <div class="show-name">{band}</div>\n'
            f'          <div class="show-venue">\U0001f4cd {venue}</div>\n'
            f'          <div class="show-tags"><span class="tag tag-city">{city}</span>{genre_tag}</div>\n'
            f"          {price_row}{notes_row}\n"
            f"        </div>\n"
            f"      </a>"
        )
    return "\n".join(cards)


def build_city_tabs(shows: list[dict]) -> str:
    """Static city tabs — only cities that have shows, ordered by count then name.
    Mirrors the client-side renderCityTabs()."""
    counts: dict[str, int] = {}
    for s in shows:
        city = (s.get("city") or "").strip()
        if city:
            counts[city] = counts.get(city, 0) + 1
    cities = sorted(counts, key=lambda c: (-counts[c], c))

    def tab(city: str, label: str, active: bool) -> str:
        cls = "city-tab active" if active else "city-tab"
        return (
            f'<button class="{cls}" data-city="{html.escape(city, quote=True)}" '
            f'onclick="filterCity(this)">{html.escape(label)}</button>'
        )

    tabs = [tab("all", "All BC", True)] + [tab(c, c, False) for c in cities]
    return "      " + "\n      ".join(tabs)


def build_seed(shows: list[dict]) -> str:
    rows = []
    for s in shows:
        obj = {
            "Band / Artist": s["band"],
            "Date": s.get("date", ""),
            "Time": s.get("time", ""),
            "Venue": s.get("venue", ""),
            "City": s.get("city", ""),
            "Price": s.get("price", ""),
            "Ticket Link": s.get("ticket", ""),
            "Genre": s.get("genre", ""),
            "Notes": s.get("notes", ""),
            "Image URL": s.get("image", ""),
        }
        pairs = ", ".join(f"'{k}': {json.dumps(v, ensure_ascii=False)}" for k, v in obj.items())
        rows.append("    { " + pairs + " },")
    return "  const SEED_SHOWS = [\n" + "\n".join(rows) + "\n  ]"


def build_faq(shows: list[dict]) -> str:
    cities = sorted({s.get("city") or "BC" for s in shows})
    city_phrase = ", ".join(cities[:-1]) + (" and " + cities[-1] if len(cities) > 1 else cities[0])
    qa = [
        (
            "Where can I find upcoming punk shows in Vancouver and BC?",
            "Right here. Punk BC lists upcoming punk, hardcore, metal and crust shows across British Columbia "
            f"— currently including dates in {city_phrase} — with venues, ticket links and lineups, updated regularly.",
        ),
        (
            "What are the main punk and hardcore venues in BC?",
            "In Vancouver: the Rickshaw Theatre, The Cobalt, Astoria, Biltmore Cabaret, Commodore Ballroom and The Pearl. "
            "In Victoria: Capital Ballroom. Plus rooms in Kelowna, Nanaimo and elsewhere around the province.",
        ),
        (
            "How do I get my band's show listed on Punk BC?",
            "Use the “Submit a Show” button at the top of the page with the date, venue, city and a ticket or flyer link. "
            "Submissions are reviewed and added to the board.",
        ),
        (
            "Are the shows all ages?",
            "It varies by venue and event — some are all ages, some are 19+. Check the notes on each listing and the venue's ticket page before you go.",
        ),
    ]
    items = "\n".join(
        f'      <div class="faq-item" itemscope itemprop="mainEntity" itemtype="https://schema.org/Question">\n'
        f'        <h3 itemprop="name">{html.escape(q)}</h3>\n'
        f'        <div itemscope itemprop="acceptedAnswer" itemtype="https://schema.org/Answer">\n'
        f'          <p itemprop="text">{a}</p>\n'
        f"        </div>\n"
        f"      </div>"
        for q, a in qa
    )
    visible = (
        '    <section class="faq" itemscope itemtype="https://schema.org/FAQPage">\n'
        "      <h2>Punk BC — FAQ</h2>\n"
        f"{items}\n"
        "    </section>"
    )
    jsonld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": re.sub("<[^>]+>", "", a)},
            }
            for q, a in qa
        ],
    }
    script = '    <script type="application/ld+json">\n' + json.dumps(jsonld, indent=2, ensure_ascii=False) + "\n    </script>"
    return visible + "\n" + script


# ── marker replacement ──────────────────────────────────────────────────────

def replace_region(text: str, name: str, start_pat: str, end_pat: str, body: str) -> str:
    pattern = re.compile(re.escape(start_pat) + r".*?" + re.escape(end_pat), re.DOTALL)
    replacement = start_pat + "\n" + body + "\n  " + end_pat
    new, n = pattern.subn(lambda _m: replacement, text, count=1)
    if n != 1:
        raise SystemExit(f"marker region {name!r} not found in punkbc.html")
    return new


# ── per-venue landing pages ────────────────────────────────────────────────
#
# The board is one URL, and its city tabs filter in JavaScript without changing
# it, so Google only ever sees a single page. That leaves real queries with no
# page to rank -- "Rickshaw Theatre upcoming shows" has 22 shows of content
# behind it. A page per venue gives each of those its own URL, title and
# MusicEvent block.
#
# Deliberately no per-city pages: Vancouver is ~93% of the board, so a Vancouver
# page would be a near-duplicate of punkbc.html competing with it for the same
# queries. Venues are genuinely distinct subsets; cities here are not.
VENUE_PAGE_DIR = ROOT / "shows"
VENUE_PAGE_MIN = 4  # below this a page is thin content and does more harm than good


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "venue"


def venue_page_html(venue: str, city: str, shows: list[dict], today: str) -> str:
    addr = VENUE_ADDRESS.get(venue)
    link = VENUE_LINK.get(venue)
    slug = slugify(venue)
    url = f"{SITE}/shows/{slug}.html"
    n = len(shows)

    where = f"{addr}, {city}" if addr else city
    title = f"Upcoming Shows at {venue} — {city} | Punk BC"
    if n:
        desc = (
            f"{n} upcoming punk, hardcore and metal show{'s' if n != 1 else ''} at "
            f"{venue} in {city}, BC. Dates, door times, ticket prices and lineups."
        )
    else:
        desc = f"Upcoming punk and hardcore shows at {venue} in {city}, BC."

    events = json.loads(build_events_jsonld(shows).split(">", 1)[1].rsplit("<", 1)[0]) if shows else []
    for e in events:
        e["url"] = url
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Punk BC", "item": PAGE_URL},
                    {"@type": "ListItem", "position": 2, "name": venue, "item": url},
                ],
            },
            {
                "@type": "MusicVenue",
                "name": venue,
                "address": {
                    "@type": "PostalAddress",
                    **({"streetAddress": addr} if addr else {}),
                    "addressLocality": city,
                    "addressRegion": "BC",
                    "addressCountry": "CA",
                },
                **({"url": link} if link else {}),
            },
            *events,
        ],
    }

    rows = []
    for s in shows:
        d = datetime.fromisoformat(s["date"])
        day = d.strftime("%a %b %d").upper().replace(" 0", " ")
        band = html.escape(s["band"])
        notes = html.escape(s.get("notes") or "")
        price = html.escape(s.get("price") or "")
        genre = html.escape(s.get("genre") or "")
        href = html.escape(href_for(s), quote=True)
        time_ = html.escape(s.get("time") or "")
        rows.append(
            f'      <li class="row">\n'
            f'        <div class="when"><b>{day}</b>{"<span>" + time_ + "</span>" if time_ else ""}</div>\n'
            f'        <div class="what">\n'
            f'          <a class="band" href="{href}" target="_blank" rel="noopener">{band}</a>\n'
            f'          {"<div class=meta>" + notes + "</div>" if notes else ""}\n'
            f'        </div>\n'
            f'        <div class="tags">{"<span class=tag>" + genre + "</span>" if genre else ""}'
            f'{"<span class=price>" + price + "</span>" if price else ""}</div>\n'
            f"      </li>"
        )
    listing = "\n".join(rows) if rows else (
        '      <li class="row empty">Nothing listed here right now — '
        f'<a href="/punkbc.html">see the full BC board</a>.</li>'
    )

    other = ""
    if link:
        other = f'<a class="lnk" href="{html.escape(link, quote=True)}" target="_blank" rel="noopener">{html.escape(venue)} website</a>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc, quote=True)}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc, quote=True)}">
<meta property="og:site_name" content="Punk BC">
<meta name="twitter:card" content="summary">
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
  .tag{{border:1px solid var(--edge);border-radius:100px;padding:3px 10px;font-size:11px;color:var(--mid);text-transform:uppercase;letter-spacing:.05em}}
  .price{{font-size:13px;color:var(--hot);font-weight:700}}
  .row.empty{{display:block;color:var(--dim)}}
  .row.empty a{{color:var(--hot)}}
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
    <span class="eyebrow">Punk BC · Venue</span>
    <h1>Upcoming shows at {html.escape(venue)}</h1>
    <p class="lead">{html.escape(str(n))} upcoming punk, hardcore and metal show{'s' if n != 1 else ''} at
      {html.escape(venue)}{' — ' + html.escape(where) if where else ''}. Updated from the
      <a href="/punkbc.html" style="color:var(--hot)">Punk BC</a> board.</p>
    <div class="crumb"><a href="/punkbc.html">← All BC shows</a></div>
  </header>

  <ul>
{listing}
  </ul>

  <div class="links">
    <a class="lnk primary" href="/punkbc.html">All punk shows in BC</a>
    {other}
  </div>

  <footer>
    Part of <a href="/punkbc.html">Punk BC</a>, a listing of punk, hardcore and metal shows across
    British Columbia, kept by <a href="/">Miki Drummer</a>. Last updated {today}.
  </footer>
</div>
</body>
</html>
"""


def build_venue_links(shows: list[dict]) -> str:
    """The 'Browse by venue' block on the board.

    Without this the venue pages are orphans: nothing on the site links to them,
    so crawlers only reach them via the sitemap and they carry no internal link
    equity.
    """
    counts = collections.Counter(s.get("venue") or "Venue" for s in shows)
    listed = [
        (v, n) for v, n in counts.most_common()
        if n >= VENUE_PAGE_MIN or (VENUE_PAGE_DIR / f"{slugify(v)}.html").exists()
    ]
    if not listed:
        return ""
    links = "\n".join(
        f'        <a class="venue-link" href="/shows/{slugify(v)}.html">'
        f"{html.escape(v)} <span>{n}</span></a>"
        for v, n in listed
    )
    return f"""    <section class="venues" id="venues">
      <h2>Browse by venue</h2>
      <p>Every upcoming show at the rooms that book the most punk and hardcore in BC.</p>
      <div class="venue-links">
{links}
      </div>
    </section>"""


def build_venue_pages(shows: list[dict], today: str) -> list[str]:
    """Write shows/<venue>.html for venues with enough upcoming shows.

    Also refreshes any page already on disk even if that venue has since dropped
    below the threshold -- once a URL is indexed, letting it 404 is worse than
    letting it say there is nothing on.
    """
    VENUE_PAGE_DIR.mkdir(exist_ok=True)
    by_venue: dict[str, list[dict]] = {}
    for s in shows:
        by_venue.setdefault(s.get("venue") or "Venue", []).append(s)

    existing = {p.stem for p in VENUE_PAGE_DIR.glob("*.html")}
    wanted = {v for v, rows in by_venue.items() if len(rows) >= VENUE_PAGE_MIN}
    # keep refreshing pages that already exist
    wanted |= {v for v in by_venue if slugify(v) in existing}

    written = []
    for venue in sorted(wanted):
        rows = sorted(by_venue.get(venue, []), key=lambda s: s["date"])
        city = collections.Counter(
            (s.get("city") or "Vancouver") for s in rows
        ).most_common(1)[0][0] if rows else "Vancouver"
        path = VENUE_PAGE_DIR / f"{slugify(venue)}.html"
        path.write_text(venue_page_html(venue, city, rows, today), encoding="utf-8")
        written.append(f"shows/{path.name} ({len(rows)})")
    return written


def update_sitemap(today: str) -> None:
    text = SITEMAP.read_text(encoding="utf-8")

    def repl(m: re.Match) -> str:
        block = m.group(0)
        if "<lastmod>" in block:
            return re.sub(r"<lastmod>.*?</lastmod>", f"<lastmod>{today}</lastmod>", block)
        # insert lastmod immediately after this block's <loc> line
        return re.sub(r"(</loc>)", r"\1\n    " + f"<lastmod>{today}</lastmod>", block, count=1)

    # Match only the single <url> block for punkbc (loc sits right after <url>,
    # and the pattern never crosses a </url>, so it can't leak into other blocks).
    pattern = re.compile(
        r"<url>\s*<loc>[^<]*punkbc\.html</loc>(?:(?!</url>).)*?</url>",
        re.DOTALL,
    )
    new, n = pattern.subn(repl, text, count=1)
    if n != 1:
        raise SystemExit("punkbc <url> block not found in sitemap.xml")
    if new != text:
        SITEMAP.write_text(new, encoding="utf-8")


VENUE_SITEMAP_START = "  <!-- PUNKBC-VENUES:START (generated by tools/build_punkbc.py) -->"
VENUE_SITEMAP_END = "  <!-- PUNKBC-VENUES:END -->"


def update_sitemap_venues(today: str) -> None:
    """Keep the venue-page <url> entries in sitemap.xml in step with shows/."""
    text = SITEMAP.read_text(encoding="utf-8")
    if VENUE_SITEMAP_START not in text:
        # first run: drop the marked region in just before </urlset>
        text = text.replace(
            "</urlset>", f"{VENUE_SITEMAP_START}\n{VENUE_SITEMAP_END}\n</urlset>"
        )

    entries = []
    for p in sorted(VENUE_PAGE_DIR.glob("*.html")):
        entries.append(
            f"  <url>\n"
            f"    <loc>{SITE}/shows/{p.name}</loc>\n"
            f"    <lastmod>{today}</lastmod>\n"
            f"    <priority>0.7</priority>\n"
            f"    <changefreq>weekly</changefreq>\n"
            f"  </url>"
        )
    block = "\n".join([VENUE_SITEMAP_START, *entries, VENUE_SITEMAP_END])
    new = re.sub(
        re.escape(VENUE_SITEMAP_START) + r".*?" + re.escape(VENUE_SITEMAP_END),
        lambda _: block,
        text,
        flags=re.S,
    )
    if new != SITEMAP.read_text(encoding="utf-8"):
        SITEMAP.write_text(new, encoding="utf-8")
        print("sitemap.xml: punkbc lastmod ->", today)


def main() -> None:
    shows = json.loads(DATA.read_text(encoding="utf-8"))["shows"]
    shows = [s for s in shows if s.get("band") and s.get("date")]
    # Fold venue/city spelling variants before anything reads them, so the
    # structured data, the city tabs and the address lookup all agree.
    for s in shows:
        if s.get("venue"):
            s["venue"] = canonical_venue(s["venue"])
        if s.get("city"):
            s["city"] = canonical_city(s["city"])
    shows.sort(key=lambda s: s["date"])
    today = today_local()
    # keep only shows today or later (mirrors the client filter). An empty board
    # is the honest answer when nothing is coming up: baking last month's dates
    # back in would leave the page advertising shows that already happened, and
    # Google drops expired events from its results anyway.
    shows = [s for s in shows if s["date"] >= today]

    text = PAGE.read_text(encoding="utf-8")
    text = replace_region(
        text, "EVENTS-JSONLD",
        "<!-- EVENTS-JSONLD:START (generated by tools/build_punkbc.py — do not edit by hand) -->",
        "<!-- EVENTS-JSONLD:END -->",
        build_events_jsonld(shows),
    )
    text = replace_region(
        text, "SHOWS",
        "<!-- SHOWS:START (generated by tools/build_punkbc.py — do not edit by hand; the client script re-renders this on load) -->",
        "<!-- SHOWS:END -->",
        build_show_cards(shows),
    )
    text = replace_region(
        text, "CITIES",
        "<!-- CITIES:START (generated by tools/build_punkbc.py — only cities with shows; the client script re-renders this from live data) -->",
        "<!-- CITIES:END -->",
        build_city_tabs(shows),
    )
    text = replace_region(
        text, "FAQ",
        "<!-- FAQ:START (generated by tools/build_punkbc.py) -->",
        "<!-- FAQ:END -->",
        build_faq(shows),
    )
    text = replace_region(
        text, "SHOWS-SEED",
        "/* SHOWS-SEED:START (generated by tools/build_punkbc.py — edit punkbc-shows.json instead) */",
        "/* SHOWS-SEED:END */",
        build_seed(shows),
    )
    written = build_venue_pages(shows, today)
    text = replace_region(
        text, "VENUES",
        "<!-- VENUES:START (generated by tools/build_punkbc.py) -->",
        "<!-- VENUES:END -->",
        build_venue_links(shows),
    )
    PAGE.write_text(text, encoding="utf-8")
    update_sitemap(today)
    update_sitemap_venues(today)
    print(f"punkbc.html: baked {len(shows)} shows + MusicEvent/FAQ structured data")
    if written:
        print("venue pages: " + ", ".join(written))


if __name__ == "__main__":
    main()
