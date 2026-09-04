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

import html
import json
import re
from datetime import datetime
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
}


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
        print("sitemap.xml: punkbc lastmod ->", today)


def main() -> None:
    shows = json.loads(DATA.read_text(encoding="utf-8"))["shows"]
    shows = [s for s in shows if s.get("band") and s.get("date")]
    shows.sort(key=lambda s: s["date"])
    today = datetime.now(_TZ).date().isoformat() if _TZ else datetime.utcnow().date().isoformat()
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
    PAGE.write_text(text, encoding="utf-8")
    update_sitemap(today)
    print(f"punkbc.html: baked {len(shows)} shows + MusicEvent/FAQ structured data")


if __name__ == "__main__":
    main()
