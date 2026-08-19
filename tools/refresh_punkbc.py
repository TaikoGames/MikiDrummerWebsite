#!/usr/bin/env python3
"""Pull the shows sheet into punkbc-shows.json and re-bake the static page.

The board reads the published Google Sheet in the browser, which is fine for
visitors and useless for search engines: a crawler runs no JavaScript, so it
only ever sees whatever was last baked into punkbc.html. Left alone, the static
copy ages until the page is advertising shows that already happened — and
Google drops expired events from its event results.

So this runs on a schedule: fetch the sheet, fold it into punkbc-shows.json,
drop anything in the past, and hand over to build_punkbc.py, which rewrites the
show cards, the MusicEvent structured data and the sitemap lastmod.

Sheet rows and hand-written rows are merged rather than one replacing the
other, keyed on band + date + venue, with the sheet winning any conflict. A
show added straight to punkbc-shows.json therefore survives a refresh.

Usage:
  python3 tools/refresh_punkbc.py                # fetch, merge, rebuild
  python3 tools/refresh_punkbc.py --from-file f  # same, from a saved CSV
  python3 tools/refresh_punkbc.py --dry-run      # report, write nothing
  python3 tools/refresh_punkbc.py --self-test    # parsing checks, no network
"""

from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "punkbc-shows.json"

CSV_URL = ("https://docs.google.com/spreadsheets/d/e/2PACX-1vSGC8UWiTGPVcaol0Iu"
           "VAYGH010vzPVZUG40ZpYJJgg7JeQ-2XcEh6CABmK0nKVjzPQ0P5HVILcmAPg/pub?output=csv")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")

# Sheet column → punkbc-shows.json key. The sheet's headers are what the client
# script reads too, so these names have to stay in step with punkbc.html.
COLUMNS = {
    "Band / Artist": "band",
    "Date": "date",
    "Time": "time",
    "Venue": "venue",
    "City": "city",
    "Price": "price",
    "Ticket Link": "ticket",
    "Genre": "genre",
    "Notes": "notes",
    "Image URL": "image",
}
FIELDS = ["band", "date", "time", "venue", "city", "price", "ticket", "genre", "notes", "image"]

# People type dates the way they speak them; the board sorts and compares them
# as plain strings, so everything has to come out as YYYY-MM-DD or not at all.
DATE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%B %d, %Y",
                "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y"]
# 09/05/2026 is the 9th of May to half the world and the 5th of September to the
# other half. Guessing would quietly publish a show on the wrong night, so these
# are only accepted when the day is past the 12th and the reading is unambiguous.
SLASH_FORMATS = ["%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y"]


def today() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Vancouver")).date().isoformat()
    except Exception:
        return datetime.utcnow().date().isoformat()


def norm_date(raw: str, year_hint: int | None = None) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    readings = set()
    for fmt in SLASH_FORMATS:
        try:
            readings.add(datetime.strptime(raw, fmt).date().isoformat())
        except ValueError:
            pass
    if len(readings) == 1:
        return readings.pop()
    if len(readings) > 1:
        print(f"  ambiguous date {raw!r} ({' or '.join(sorted(readings))}) "
              f"— write it as YYYY-MM-DD in the sheet")
        return None
    # "Sep 5" with no year — assume the next one to come round
    for fmt in ("%b %d", "%B %d", "%d %b", "%d %B"):
        try:
            d = datetime.strptime(raw, fmt).date()
            year = year_hint or datetime.now().year
            guess = d.replace(year=year)
            if guess.isoformat() < today():
                guess = guess.replace(year=year + 1)
            return guess.isoformat()
        except ValueError:
            pass
    return None


def parse_csv(text: str) -> list[dict]:
    """Sheet CSV → show dicts. Unknown columns are ignored, blank bands dropped."""
    rows = []
    for raw in csv.DictReader(io.StringIO(text)):
        show = {}
        for header, key in COLUMNS.items():
            value = raw.get(header)
            show[key] = (value or "").strip()
        if not show["band"]:
            continue
        date = norm_date(show["date"])
        if not date:
            print(f"  skipped {show['band']!r}: date {show['date']!r} not understood")
            continue
        show["date"] = date
        rows.append({k: show.get(k, "") for k in FIELDS})
    return rows


def key(show: dict) -> tuple:
    return ((show.get("band") or "").strip().lower(),
            (show.get("date") or "").strip(),
            (show.get("venue") or "").strip().lower())


def merge(existing: list[dict], sheet: list[dict]) -> list[dict]:
    """Union of both, sheet winning on conflict, past shows dropped."""
    by_key: dict[tuple, dict] = {}
    for show in existing:
        if show.get("band") and show.get("date"):
            by_key[key(show)] = dict(show)
    for show in sheet:
        k = key(show)
        if k in by_key:
            # only overwrite fields the sheet actually filled in, so a hand-added
            # image or note is not wiped by an empty cell
            merged = dict(by_key[k])
            merged.update({f: v for f, v in show.items() if v})
            by_key[k] = merged
        else:
            by_key[k] = show
    cutoff = today()
    out = [s for s in by_key.values() if (s.get("date") or "") >= cutoff]
    out.sort(key=lambda s: (s["date"], s.get("time") or "", s["band"].lower()))
    return out


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def self_test() -> int:
    sample = (
        "Band / Artist,Date,Time,Venue,City,Price,Ticket Link,Genre,Notes,Image URL\n"
        "Test Band,2099-01-15,20:00,Rickshaw Theatre,Vancouver,$20,https://x.test,Punk,"
        '"With A, B and C",https://img.test/a.jpg\n'
        "No Date Band,,20:00,Astoria,Vancouver,,,,,\n"
        ",2099-02-01,,Cobalt,Vancouver,,,,,\n"
        "Slash Date,15/03/2099,,The Pearl,Vancouver,,,,,\n"
        "Ambiguous Date,05/09/2099,,Astoria,Vancouver,,,,,\n"
        "Worded Date,\"Sep 5, 2099\",,Cobalt,Vancouver,,,,,\n"
    )
    rows = parse_csv(sample)
    checks = [
        (len(rows) == 3, f"three usable rows, got {len(rows)}"),
        (rows[0]["band"] == "Test Band", "band name read"),
        (rows[0]["notes"] == "With A, B and C", "quoted comma survives"),
        (rows[0]["image"] == "https://img.test/a.jpg", "image column mapped"),
        (any(r["date"] == "2099-03-15" for r in rows), "unambiguous dd/mm/yyyy normalised"),
        (not any(r["band"] == "Ambiguous Date" for r in rows), "ambiguous 05/09 refused, not guessed"),
        (any(r["date"] == "2099-09-05" for r in rows), "written-out date normalised"),
    ]
    existing = [
        {"band": "Test Band", "date": "2099-01-15", "venue": "Rickshaw Theatre",
         "city": "Vancouver", "image": "https://hand.test/keep.jpg", "notes": "", "time": "",
         "price": "", "ticket": "", "genre": ""},
        {"band": "Hand Added", "date": "2099-06-01", "venue": "Red Gate",
         "city": "Vancouver", "image": "", "notes": "", "time": "", "price": "",
         "ticket": "", "genre": ""},
        {"band": "Long Gone", "date": "2001-01-01", "venue": "Cobalt",
         "city": "Vancouver", "image": "", "notes": "", "time": "", "price": "",
         "ticket": "", "genre": ""},
    ]
    merged = merge(existing, rows)
    names = [s["band"] for s in merged]
    checks += [
        ("Hand Added" in names, "hand-written show survives the sheet"),
        ("Long Gone" not in names, "past show dropped"),
        (names.count("Test Band") == 1, "no duplicate for the same band/date/venue"),
        (next(s for s in merged if s["band"] == "Test Band")["price"] == "$20",
         "sheet fills the blank field"),
        (next(s for s in merged if s["band"] == "Test Band")["image"] == "https://img.test/a.jpg",
         "sheet wins where both have a value"),
        (names == sorted(names, key=lambda n: [s["date"] for s in merged if s["band"] == n][0]),
         "sorted by date"),
    ]
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

    if "--from-file" in args:
        text = Path(args[args.index("--from-file") + 1]).read_text(encoding="utf-8")
        print(f"read {len(text)} chars from file")
    else:
        try:
            text = fetch(CSV_URL)
        except Exception as e:
            # Never let a flaky fetch blank the board: leaving yesterday's baked
            # page up is strictly better than publishing an empty one.
            print(f"could not read the sheet ({e}) — leaving the board as it is")
            return 0
        print(f"read {len(text)} chars from the sheet")

    sheet = parse_csv(text)
    print(f"{len(sheet)} usable rows in the sheet")

    doc = json.loads(DATA.read_text(encoding="utf-8"))
    before = doc.get("shows", [])
    after = merge(before, sheet)
    kept = {key(s) for s in before} & {key(s) for s in after}
    print(f"shows: {len(before)} on file -> {len(after)} upcoming "
          f"({len(after) - len(kept)} new, {len(before) - len(kept)} dropped as past)")

    if "--dry-run" in args:
        for s in after:
            print(f"  {s['date']}  {s['band']} @ {s.get('venue')}")
        return 0

    doc["shows"] = after
    DATA.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    sys.path.insert(0, str(ROOT / "tools"))
    import build_punkbc
    build_punkbc.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
