#!/usr/bin/env python3
"""Regenerate the SEO-critical, static parts of gig-checklist.html from gig-checklist.json.

The checklist itself is a JS app: the gear lists only render after the visitor
picks a show type. Crawlers never click, so without this the page ships with no
indexable gear content at all — just the intro paragraph. This bakes the same
data into three marked regions so the lists are in the raw HTML:

  * SHOWS-DATA  – the inline `var SHOWS = {...}` the app reads
  * REFERENCE   – a visible, always-present reference copy of every list
  * FAQ         – visible FAQ block + matching FAQPage JSON-LD

Because all three come from gig-checklist.json, the interactive tool and the
crawlable copy can't drift apart.

Usage:  python3 tools/build_gig_checklist.py
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
PAGE = ROOT / "gig-checklist.html"
DATA = ROOT / "gig-checklist.json"
SITEMAP = ROOT / "sitemap.xml"
PAGE_URL = "https://www.mikidrummer.ca/gig-checklist.html"

# Order the show types appear in, both in the app and in the reference section.
ORDER = ["breakables", "full", "festival", "studio", "rehearsal"]


def ordered(shows: dict) -> list[tuple[str, dict]]:
    keys = [k for k in ORDER if k in shows] + [k for k in shows if k not in ORDER]
    return [(k, shows[k]) for k in keys]


def e(text: str) -> str:
    return html.escape(text or "")


# ── region builders ────────────────────────────────────────────────────────

def build_shows_data(shows: dict) -> str:
    """The inline JS object. JSON is valid JS, so dump it straight in."""
    payload = json.dumps({k: shows[k] for k, _ in ordered(shows)}, indent=2, ensure_ascii=False)
    return "  var SHOWS = " + payload.replace("\n", "\n  ") + ";"


def build_reference(shows: dict) -> str:
    """A visible copy of every list — the part crawlers can actually read."""
    blocks = []
    for key, s in ordered(shows):
        groups = []
        for g in s["groups"]:
            items = "\n".join(f"          <li>{e(i)}</li>" for i in g["items"])
            groups.append(
                f'        <h4>{e(g["name"])}</h4>\n'
                f"        <ul>\n{items}\n        </ul>"
            )
        count = sum(len(g["items"]) for g in s["groups"])
        blocks.append(
            f'      <article class="ref-block" id="list-{e(key)}">\n'
            f'        <h3>{e(s["ico"])} {e(s["name"])}</h3>\n'
            f'        <p class="ref-tag">{e(s["tag"])} · {count} items</p>\n'
            f'        <p class="ref-blurb">{e(s["blurb"])}</p>\n'
            f"{chr(10).join(groups)}\n"
            f"      </article>"
        )
    intro = (
        "      <h2>Every drummer packing list, in full</h2>\n"
        '      <p class="ref-intro">The same five lists the tool above uses, written out so you can '
        "skim or print them without tapping through. Tick them off interactively at the top of the page.</p>"
    )
    return (
        '    <section class="reference" id="reference">\n'
        f"{intro}\n"
        f"{chr(10).join(blocks)}\n"
        "    </section>"
    )


def build_faq(shows: dict) -> str:
    """Visible FAQ + FAQPage JSON-LD, with answers drawn from the real lists."""
    def items_for(key: str, group_name: str | None = None) -> str:
        s = shows[key]
        groups = s["groups"] if group_name is None else [g for g in s["groups"] if g["name"] == group_name]
        names = [i for g in groups for i in g["items"]]
        return ", ".join(names)

    breakables = items_for("breakables", "Breakables")
    festival = items_for("festival", "Bring")

    qa = [
        (
            "What does a drummer need to bring to a gig?",
            f"It depends on the show. On a backline or house kit you bring your breakables — {breakables.lower()} "
            "— plus sticks, a drum key and your in-ears. For your own full-kit show you bring the shells, hardware, "
            "cymbals and rug as well. The checklist above covers five show types.",
        ),
        (
            "What are drummer breakables?",
            f"Breakables are the parts of the kit a drummer brings even when a backline kit is provided: {breakables.lower()}. "
            "They're the pieces that are personal to your setup or that wear out, so venues and backline companies expect you to supply them.",
        ),
        (
            "What should a drummer pack for a festival or fly date?",
            f"Travel light and bring what makes a shared backline feel like yours: {festival.lower()}. "
            "Changeovers are fast and stage times are tight, so pack so you can be set up in minutes.",
        ),
        (
            "Is this drum gig checklist free?",
            "Yes — it's free, needs no account and runs entirely in your browser. Your ticked boxes are saved on your own "
            "device so you can start packing and come back to the list later.",
        ),
    ]

    items = "\n".join(
        f'      <div class="faq-item">\n'
        f"        <h3>{e(q)}</h3>\n"
        f"        <p>{e(a)}</p>\n"
        f"      </div>"
        for q, a in qa
    )
    visible = '    <section class="faq" id="faq">\n      <h2>Drummer packing questions</h2>\n' + items + "\n    </section>"

    jsonld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in qa
        ],
    }
    script = (
        '    <script type="application/ld+json">\n'
        + json.dumps(jsonld, indent=2, ensure_ascii=False)
        + "\n    </script>"
    )
    return visible + "\n" + script


# ── marker replacement ──────────────────────────────────────────────────────

def replace_region(text: str, name: str, start_pat: str, end_pat: str, body: str, indent: str) -> str:
    pattern = re.compile(re.escape(start_pat) + r".*?" + re.escape(end_pat), re.DOTALL)
    replacement = start_pat + "\n" + body + "\n" + indent + end_pat
    new, n = pattern.subn(lambda _m: replacement, text, count=1)
    if n != 1:
        raise SystemExit(f"marker region {name!r} not found in gig-checklist.html")
    return new


def update_sitemap(today: str) -> None:
    text = SITEMAP.read_text(encoding="utf-8")

    def repl(m: re.Match) -> str:
        block = m.group(0)
        if "<lastmod>" in block:
            return re.sub(r"<lastmod>.*?</lastmod>", f"<lastmod>{today}</lastmod>", block)
        return re.sub(r"(</loc>)", r"\1\n    " + f"<lastmod>{today}</lastmod>", block, count=1)

    pattern = re.compile(
        r"<url>\s*<loc>[^<]*gig-checklist\.html</loc>(?:(?!</url>).)*?</url>",
        re.DOTALL,
    )
    new, n = pattern.subn(repl, text, count=1)
    if n != 1:
        raise SystemExit("gig-checklist <url> block not found in sitemap.xml")
    if new != text:
        SITEMAP.write_text(new, encoding="utf-8")
        print("sitemap.xml: gig-checklist lastmod ->", today)


def main() -> None:
    shows = json.loads(DATA.read_text(encoding="utf-8"))["shows"]
    text = PAGE.read_text(encoding="utf-8")

    text = replace_region(
        text, "SHOWS-DATA",
        "/* SHOWS-DATA:START (generated by tools/build_gig_checklist.py — edit gig-checklist.json instead) */",
        "/* SHOWS-DATA:END */",
        build_shows_data(shows), "  ",
    )
    text = replace_region(
        text, "REFERENCE",
        "<!-- REFERENCE:START (generated by tools/build_gig_checklist.py — do not edit by hand) -->",
        "<!-- REFERENCE:END -->",
        build_reference(shows), "    ",
    )
    text = replace_region(
        text, "FAQ",
        "<!-- FAQ:START (generated by tools/build_gig_checklist.py) -->",
        "<!-- FAQ:END -->",
        build_faq(shows), "    ",
    )

    PAGE.write_text(text, encoding="utf-8")
    today = datetime.now(_TZ).date().isoformat() if _TZ else datetime.utcnow().date().isoformat()
    update_sitemap(today)
    total = sum(len(g["items"]) for s in shows.values() for g in s["groups"])
    print(f"gig-checklist.html: baked {len(shows)} lists / {total} items + FAQ structured data")


if __name__ == "__main__":
    main()
