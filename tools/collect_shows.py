#!/usr/bin/env python3
"""Collect shows from every source in data/show-sources.json.

Adding a venue is one entry in that file. There is no per-venue code, because
per-venue code is what rots: two kinds of reader cover almost everything.

  jsonld  A normal web page carrying schema.org Event markup — the same data a
          venue already publishes so its listings show up in Google. Restyling
          the page does not break it; only dropping the markup does.
  ics     A calendar feed. Every public Google Calendar has one.

Nothing here writes to the board. Everything new lands in data/shows-queue.json
for review, because a venue feed carries whatever the room booked — comedy,
tribute nights, a wedding band — and this board is punk shows.

Two failure modes are handled on purpose:

  A source that used to find shows and now finds none has almost certainly
  broken rather than gone quiet, so that is an error, not a shrug. Silence is
  how a board goes stale without anyone noticing.

  A venue writes its own name three ways over a year. Everything is folded
  through the same canonical_venue() the site uses, so "Astoria Pub" and "The
  Astoria" cannot become two rooms — which is what put six gigs on the board
  twice before.

Usage:
  python3 tools/collect_shows.py                 # fetch, queue what is new
  python3 tools/collect_shows.py --dry-run       # report, write nothing
  python3 tools/collect_shows.py --only rickshaw # one source
  python3 tools/collect_shows.py --self-test
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from build_punkbc import canonical_venue, canonical_city  # noqa: E402

SOURCES = ROOT / "data" / "show-sources.json"
QUEUE = ROOT / "data" / "shows-queue.json"
BOARD = ROOT / "punkbc-shows.json"
PLACEHOLDER = "https://www.mikidrummer.ca/punkbc-placeholder.svg"

UA = "MikiDrummerBot/1.0 (+https://www.mikidrummer.ca/punkbc.html) Python-urllib"
TIMEOUT = 30
PAUSE = 1.0            # one polite second between requests to the same host
HORIZON_DAYS = 400     # anything further out is almost always a bad parse


# ── fetching ────────────────────────────────────────────────────────────────

def get(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,text/calendar,application/json;q=0.9,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read(4_000_000)
    return raw.decode("utf-8", "replace")


# ── readers ─────────────────────────────────────────────────────────────────

def walk_jsonld(node, out):
    """schema.org nests events in @graph, in arrays, and inside each other."""
    if isinstance(node, list):
        for n in node:
            walk_jsonld(n, out)
        return
    if not isinstance(node, dict):
        return
    t = node.get("@type")
    types = t if isinstance(t, list) else [t]
    if any(isinstance(x, str) and x.endswith("Event") for x in types if x):
        out.append(node)
    for key in ("@graph", "subEvent", "event", "events", "itemListElement", "item"):
        if key in node:
            walk_jsonld(node[key], out)


def read_jsonld(text: str) -> list[dict]:
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        text, re.S | re.I)
    found: list[dict] = []
    for b in blocks:
        try:
            walk_jsonld(json.loads(b.strip()), found)
        except Exception:
            continue          # one malformed block must not lose the others
    rows = []
    for e in found:
        name = str(e.get("name") or "").strip()
        start = str(e.get("startDate") or "").strip()
        if not name or not start:
            continue
        loc = e.get("location") or {}
        if isinstance(loc, list):
            loc = loc[0] if loc else {}
        venue = str((loc or {}).get("name") or "").strip() if isinstance(loc, dict) else ""
        city = ""
        if isinstance(loc, dict):
            addr = loc.get("address") or {}
            if isinstance(addr, dict):
                city = str(addr.get("addressLocality") or "").strip()
        offers = e.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = ""
        if isinstance(offers, dict) and offers.get("price") not in (None, "", 0, "0"):
            price = "$" + str(offers["price"]).rstrip("0").rstrip(".")
        rows.append({
            "band": name,
            "date": start[:10],
            "time": start[11:16] if len(start) >= 16 and start[10] in "T " else "",
            "venue": venue,
            "city": city,
            "price": price,
            "ticket": str((offers or {}).get("url") or e.get("url") or "").strip(),
        })
    return rows


def unfold(text: str) -> str:
    # .ics wraps long lines; a continuation starts with a space or tab. Without
    # this a long bill is cut in half mid-word.
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n ", "").replace("\n\t", "")


def ics_field(block: str, name: str) -> str:
    m = re.search(rf"^{name}(?:;[^:\n]*)?:(.*)$", block, re.M)
    if not m:
        return ""
    return (m.group(1).strip()
            .replace("\\n", " ").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\"))


def read_ics(text: str) -> list[dict]:
    rows = []
    for block in unfold(text).split("BEGIN:VEVENT")[1:]:
        block = block.split("END:VEVENT")[0]
        if re.search(r"^STATUS:CANCELLED$", block, re.M):
            continue
        start = ics_field(block, "DTSTART")
        m = re.search(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2}))?", start)
        name = ics_field(block, "SUMMARY")
        if not m or not name:
            continue
        loc = ics_field(block, "LOCATION").split("\n")[0].strip()
        desc = ics_field(block, "DESCRIPTION")
        link = re.search(r"https?://[^\s<>\"']+", desc)
        rows.append({
            "band": name,
            "date": f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
            "time": f"{m.group(4)}:{m.group(5)}" if m.group(4) else "",
            "venue": loc.split(",")[0].strip(),
            "city": "",
            "price": "",
            "ticket": link.group(0).split("?")[0] if link else "",
        })
    return rows


READERS = {"jsonld": read_jsonld, "ics": read_ics}


# ── tidying ─────────────────────────────────────────────────────────────────

def clean_band(name: str, venue: str) -> str:
    """"Dead Pioneers @ Wise Hall" is a band and a room; the room has a column."""
    s = re.sub(r"\s*\|\s*", " / ", name).strip()
    v = re.sub(r"[^A-Za-z0-9 ]", " ", venue or "").strip()
    if v:
        pat = r"\s*(?:@|\bat\b)\s*(?:the\s+)?" + r"\s+".join(map(re.escape, v.split())) + r"\s*$"
        s = re.sub(pat, "", s, flags=re.I)
    return s.strip(" -–—·|,") or name


def key(row: dict) -> tuple:
    return (str(row.get("band", "")).strip().lower(),
            str(row.get("date", "")).strip(),
            canonical_venue(str(row.get("venue", ""))).strip().lower())


def normalise(row: dict, src: dict) -> dict | None:
    band = clean_band(str(row.get("band") or ""), str(row.get("venue") or ""))
    date = str(row.get("date") or "")
    if not band or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return None
    venue = canonical_venue(str(row.get("venue") or "") or src.get("venue", ""))
    city = canonical_city(str(row.get("city") or "") or src.get("city", ""))
    ticket = str(row.get("ticket") or "")
    if ticket and not ticket.startswith("http"):
        ticket = ""
    return {
        "band": band, "date": date, "time": str(row.get("time") or ""),
        "venue": venue, "city": city, "price": str(row.get("price") or ""),
        "ticket": ticket.split("?")[0], "genre": "", "notes": "",
        "image": PLACEHOLDER, "source": src["id"],
    }


def in_window(date: str, today: str, horizon: str) -> bool:
    return today <= date <= horizon


# ── the run ─────────────────────────────────────────────────────────────────

def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="", help="only sources whose id contains this")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    cfg = load(SOURCES, {})
    queue = load(QUEUE, {})
    queue.setdefault("_readme", "Shows found by tools/collect_shows.py, waiting for review "
                                "at /shows-queue.html. Nothing here is on the site.")
    queue.setdefault("pending", [])
    queue.setdefault("dismissed", [])
    queue.setdefault("last_good", {})

    board = load(BOARD, {"shows": []})["shows"]
    today = datetime.now().date().isoformat()
    horizon = (datetime.now().date() + timedelta(days=HORIZON_DAYS)).isoformat()

    # Anything already on the board, already queued, or already turned down.
    known = {key(s) for s in board}
    known |= {key(s) for s in queue["pending"]}
    known |= {key(s) for s in queue["dismissed"]}

    sources = [s for s in cfg.get("sources", [])
               if s.get("enabled") and (not args.only or args.only in s["id"])]
    if not sources:
        print("No sources enabled." if not args.only else f"No enabled source matches {args.only!r}.")
        return 0

    added, problems = [], []
    for src in sources:
        reader = READERS.get(src.get("kind", ""))
        if not reader:
            problems.append(f"{src['id']}: unknown kind {src.get('kind')!r}")
            continue
        try:
            text = get(src["url"])
            time.sleep(PAUSE)
            rows = reader(text)
        except Exception as e:
            problems.append(f"{src['id']}: could not read — {e}")
            print(f"  {src['id']:<26} FAILED  {e}")
            continue

        fresh = []
        for r in rows:
            n = normalise(r, src)
            if not n or not in_window(n["date"], today, horizon):
                continue
            k = key(n)
            if k in known:
                continue
            known.add(k)
            n["first_seen"] = today
            fresh.append(n)

        found = len(rows)
        was_good = queue["last_good"].get(src["id"], 0)
        print(f"  {src['id']:<26} {found:>3} on the page, {len(fresh):>3} new")
        # A source that used to work and now returns nothing is broken, not idle.
        if found == 0 and was_good > 0:
            problems.append(f"{src['id']}: found nothing, but found {was_good} last time — "
                            "the page has probably changed")
        if found:
            queue["last_good"][src["id"]] = found
        added += fresh

    queue["pending"] += added
    queue["pending"].sort(key=lambda s: (s.get("date", ""), s.get("venue", "")))
    queue["updated"] = today

    print(f"\n{len(added)} new, {len(queue['pending'])} waiting for review"
          + ("  (dry run, nothing written)" if args.dry_run else ""))
    for s in added[:15]:
        print(f"   {s['date']}  {s['band'][:46]:<48} {s['venue']}")
    if len(added) > 15:
        print(f"   … and {len(added) - 15} more")

    if not args.dry_run:
        QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print("  " + p)
        return 1
    return 0


# ── tests ───────────────────────────────────────────────────────────────────

def self_test() -> int:
    checks = []

    page = '''<script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"MusicEvent","name":"Chain Whip","startDate":"2026-11-04T20:00",
       "location":{"@type":"MusicVenue","name":"Astoria Pub",
                   "address":{"addressLocality":"Vancouver, BC"}},
       "offers":{"@type":"Offer","price":"18.00","url":"https://x.test/t?utm=1"}}]}
    </script>'''
    rows = read_jsonld(page)
    checks.append(("jsonld: event found", len(rows) == 1))
    if rows:
        n = normalise(rows[0], {"id": "t", "city": "Vancouver"})
        checks.append(("jsonld: date", n["date"] == "2026-11-04"))
        checks.append(("jsonld: time", n["time"] == "20:00"))
        checks.append(("jsonld: venue folded", n["venue"] == "The Astoria"))
        checks.append(("jsonld: city folded", n["city"] == "Vancouver"))
        checks.append(("jsonld: price", n["price"] == "$18"))
        checks.append(("jsonld: tracking stripped", n["ticket"] == "https://x.test/t"))

    checks.append(("jsonld: bad block skipped",
                   read_jsonld('<script type="application/ld+json">{oops</script>'
                               + page) and True))
    checks.append(("jsonld: non-events ignored",
                   read_jsonld('<script type="application/ld+json">'
                               '{"@type":"Organization","name":"A venue"}</script>') == []))

    ics = ("BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261120\r\n"
           "SUMMARY:Brasser | Curb Zombie | Brehdren at Green A\r\n uto\r\n"
           "LOCATION:Green Auto\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261121\r\nSUMMARY:Off\r\n"
           "LOCATION:X\r\nSTATUS:CANCELLED\r\nEND:VEVENT")
    r = read_ics(ics)
    checks.append(("ics: cancelled skipped", len(r) == 1))
    if r:
        n = normalise(r[0], {"id": "t", "city": "Vancouver"})
        checks.append(("ics: folded line kept whole", n["band"].endswith("Brehdren")))
        checks.append(("ics: pipes to slashes", " / " in n["band"]))
        checks.append(("ics: venue cut from bill", "Green Auto" not in n["band"]))
        checks.append(("ics: all-day has no time", n["time"] == ""))

    checks.append(("key folds venue spellings",
                   key({"band": "X", "date": "2026-01-01", "venue": "Astoria Pub"}) ==
                   key({"band": "x", "date": "2026-01-01", "venue": "The Astoria"})))
    checks.append(("rows without a date are dropped",
                   normalise({"band": "X", "date": "soon"}, {"id": "t"}) is None))
    checks.append(("rows without a band are dropped",
                   normalise({"band": "", "date": "2026-01-01"}, {"id": "t"}) is None))
    checks.append(("window excludes the past",
                   not in_window("2020-01-01", "2026-09-09", "2027-10-14")))

    for name, ok in checks:
        print(("  [ok] " if ok else "  [FAIL] ") + name)
    bad = sum(1 for _, ok in checks if not ok)
    print("self-test:", "passed" if not bad else f"{bad} FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
