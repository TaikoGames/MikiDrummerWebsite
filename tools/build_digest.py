#!/usr/bin/env python3
"""Turn the shows board into a monthly digest — web page, RSS item, email HTML.

The board already knows every upcoming show and is refreshed daily. A digest is
just that data cut to one month and written three ways:

  digest/YYYY-MM.html        a page anyone can read and link to, and Google can
                             index — it doubles as the newsletter's "view in
                             browser" copy
  digest/index.html          the archive, so past issues are reachable
  punkbc-digest.xml          RSS, one item per issue. This is the piece an email
                             service points at: Mailchimp, MailerLite and
                             Buttondown can all send a campaign from a feed, so
                             nothing here needs an API key or a password.
  digest/YYYY-MM.email.html  the same issue as email-safe HTML (tables, inline
                             styles) to paste in if the RSS route is not used.

Usage:
  python3 tools/build_digest.py                  # the month we are in
  python3 tools/build_digest.py --month 2026-09
  python3 tools/build_digest.py --next           # the month coming up
"""

from __future__ import annotations

import functools
import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "punkbc-shows.json"
OUT = ROOT / "digest"
FEED = ROOT / "punkbc-digest.xml"
SITEMAP = ROOT / "sitemap.xml"
SITE = "https://www.mikidrummer.ca"
BOARD = f"{SITE}/punkbc.html"

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Vancouver")
except Exception:                                    # pragma: no cover
    TZ = timezone.utc


def today():
    return datetime.now(TZ).date()


def month_name(ym: str) -> str:
    return datetime.strptime(ym + "-01", "%Y-%m-%d").strftime("%B %Y")


def day_label(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%a %-d %b")
    except ValueError:
        return date_str


def tidy_city(name: str) -> str:
    """The sheet has both "Victoria" and "Victoria, BC" — one city, two spellings."""
    return re.sub(r",?\s*(BC|B\.C\.|British Columbia)$", "", (name or "").strip(), flags=re.I).strip()


def tidy_time(t: str) -> str:
    """The sheet has "19" as often as "19:00"; both mean seven o'clock."""
    t = (t or "").strip()
    if re.fullmatch(r"\d{1,2}", t):
        return f"{int(t):02d}:00"
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else t


def shows_for(ym: str) -> list[dict]:
    shows = json.loads(DATA.read_text(encoding="utf-8"))["shows"]
    picked = [s for s in shows if (s.get("date") or "").startswith(ym)]
    for s in picked:
        s["time"] = tidy_time(s.get("time"))
        s["city"] = tidy_city(s.get("city"))
    picked.sort(key=lambda s: (s["date"], s.get("time") or "", s["band"].lower()))
    return picked


# The generic mosh-pit photo stands in wherever a show has no picture of its
# own. It is fine as a thumbnail on the board and pointless at the top of an
# email — four identical crowd shots is worse than none.
GENERIC = ("moshpit2", "punkbc-placeholder")
MAX_FEATURED = 4


ART_INDEX = ROOT / "img" / "digest" / "index.json"


@functools.lru_cache(maxsize=1)
def _art_map() -> dict:
    try:
        return json.loads(ART_INDEX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def art(url: str) -> str:
    """The cropped copy of a photo if we have one, otherwise the original.

    The pictures come from wherever the show was announced: a 3840px PNG on a
    ticketing CDN, a WebP on a band's own site, a Wikimedia file. Dropping those
    straight into an email means megabytes down a phone, formats Outlook cannot
    render, and every card a different shape. CSS cannot rescue it — object-fit
    is ignored by Outlook's Word engine, which stretches instead of cropping.

    tools/fetch_art.py crops them ahead of time into img/digest and writes down
    which file came from which URL. Anything it could not fetch is sent as it
    always was: the wrong shape beats an empty box, and an empty box is what a
    resizing proxy leaves behind on the day it is unreachable.
    """
    if not url:
        return url
    name = _art_map().get(url)
    return f"{SITE}/img/digest/{name}" if name else url


def has_photo(s: dict) -> bool:
    img = (s.get("image") or "").lower()
    return bool(img) and not any(g in img for g in GENERIC)


def featured(shows: list[dict]) -> list[dict]:
    """Which acts get a picture.

    Whatever is ticked Curated in the sheet — the same flag that puts the
    Recommended seal on the board, so one decision drives both. If nothing is
    ticked, the month still gets a face on it: the first few shows that have a
    picture of their own, spread out rather than three from the same week.
    """
    picked = [s for s in shows if s.get("curated") and has_photo(s)]
    if picked:
        return picked[:MAX_FEATURED]
    withpics = [s for s in shows if has_photo(s)]
    if len(withpics) <= MAX_FEATURED:
        return withpics
    step = len(withpics) / MAX_FEATURED
    return [withpics[int(i * step)] for i in range(MAX_FEATURED)]


def line_for(s: dict) -> str:
    """One show as plain text — used in the RSS summary and nowhere fancy."""
    bits = [day_label(s["date"]), "—", s["band"], "@", s.get("venue") or "TBA"]
    if s.get("city"):
        bits.append(f"({s['city']})")
    if (s.get("price") or "").strip():
        bits.append("· " + s["price"])
    return " ".join(bits)


# ── the web copy ───────────────────────────────────────────────────────────

def render_page(ym: str, shows: list[dict]) -> str:
    rows = []
    for s in shows:
        ticket = s.get("ticket") or ""
        name = html.escape(s["band"])
        title = (f'<a class="b" href="{html.escape(ticket, quote=True)}" target="_blank" '
                 f'rel="noopener">{name}</a>') if ticket else f'<span class="b">{name}</span>'
        notes = html.escape(s.get("notes") or "")
        price = html.escape(s.get("price") or "")
        rows.append(
            '      <li class="show">\n'
            f'        <div class="when">{html.escape(day_label(s["date"]))}'
            + (f'<span class="time">{html.escape(s["time"])}</span>' if s.get("time") else "")
            + "</div>\n"
            f'        <div class="what">{title}\n'
            f'          <div class="where">{html.escape(s.get("venue") or "TBA")}'
            f'{" · " + html.escape(s["city"]) if s.get("city") else ""}'
            f'{" · " + price if price else ""}</div>\n'
            + (f'          <div class="notes">{notes}</div>\n' if notes else "")
            + "        </div>\n"
            "      </li>"
        )
    listing = "\n".join(rows) if rows else '      <li class="show"><div class="what">Nothing listed for this month yet.</div></li>'

    picks = featured(shows)
    cards = []
    for s2 in picks:
        href = html.escape(s2.get("ticket") or BOARD, quote=True)
        cards.append(
            f'      <a class="pick" href="{href}" target="_blank" rel="noopener">\n'
            f'        <img src="{html.escape(art(s2["image"]), quote=True)}" alt="{html.escape(s2["band"])}" '
            f'loading="lazy" referrerpolicy="no-referrer">\n'
            f'        <div class="pick-b">{html.escape(s2["band"])}</div>\n'
            f'        <div class="pick-m">{html.escape(day_label(s2["date"]))} · '
            f'{html.escape(s2.get("venue") or "TBA")}'
            f'{" · " + html.escape(s2["city"]) if s2.get("city") else ""}</div>\n'
            "      </a>"
        )
    picks_block = ('    <div class="picks">\n' + "\n".join(cards) + "\n    </div>") if cards else ""
    label = month_name(ym)
    count = len(shows)
    cities = sorted({tidy_city(s.get("city")) for s in shows if tidy_city(s.get("city"))})
    blurb = (f"{count} punk, hardcore and metal show{'s' if count != 1 else ''} across "
             + (", ".join(cities) if cities else "British Columbia") + f" in {label}.")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Punk BC — {label} shows</title>
<meta name="description" content="{html.escape(blurb)}">
<link rel="canonical" href="{SITE}/digest/{ym}.html">
<meta property="og:title" content="Punk BC — {label} shows">
<meta property="og:description" content="{html.escape(blurb)}">
<meta property="og:type" content="article">
<meta property="og:url" content="{SITE}/digest/{ym}.html">
<link rel="alternate" type="application/rss+xml" title="Punk BC digest" href="{SITE}/punkbc-digest.xml">
<style>
  :root{{--bg:#0a0a0a;--card:#111;--border:#222;--red:#dc2626;--white:#f5f5f5;--gray:#9ca3af;}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--white);font-family:'Courier New',Courier,monospace;
    line-height:1.5;padding:24px 16px 60px}}
  .wrap{{max-width:680px;margin:0 auto}}
  .kicker{{color:var(--red);font-size:12px;letter-spacing:.2em;text-transform:uppercase}}
  h1{{font-size:26px;margin:6px 0 4px}}
  .sub{{color:var(--gray);font-size:13px}}
  .list{{list-style:none;margin:26px 0 0}}
  .show{{display:flex;gap:14px;padding:14px 0;border-top:1px solid var(--border)}}
  .show:first-child{{border-top:none}}
  .when{{flex:0 0 108px;color:var(--red);font-size:13px;text-transform:uppercase}}
  .when .time{{display:block;color:var(--gray);font-size:11px}}
  .what{{flex:1;min-width:0}}
  .b{{color:var(--white);font-size:15px;font-weight:bold;text-decoration:none}}
  a.b:hover{{color:var(--red)}}
  .where{{color:var(--gray);font-size:12.5px;margin-top:3px}}
  .notes{{color:#6b7280;font-size:11.5px;margin-top:3px}}
  .foot{{margin-top:32px;padding-top:18px;border-top:1px solid var(--border);
    color:var(--gray);font-size:12px;line-height:1.8}}
  .foot a{{color:var(--red)}}
  .picks{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:22px}}
  .pick{{display:block;text-decoration:none;color:inherit;border:1px solid var(--border);
    border-radius:8px;overflow:hidden;background:var(--card)}}
  .pick:hover{{border-color:var(--red)}}
  .pick img{{display:block;width:100%;height:auto;aspect-ratio:16/9;object-fit:cover;background:#000}}
  .pick-b{{font-size:13px;font-weight:bold;padding:8px 10px 0}}
  .pick-m{{font-size:11px;color:var(--gray);padding:2px 10px 10px}}
</style>
</head>
<body>
  <div class="wrap">
    <p class="kicker">🤘 Punk BC · monthly</p>
    <h1>{label}</h1>
    <p class="sub">{html.escape(blurb)}</p>
{picks_block}
    <ul class="list">
{listing}
    </ul>
    <div class="foot">
      Dates change and shows sell out — always check the ticket link before you go.<br>
      <a href="{BOARD}">The full board</a> ·
      <a href="{SITE}/digest/">past issues</a> ·
      <a href="{SITE}/punkbc-digest.xml">RSS</a>
    </div>
  </div>
</body>
</html>
"""


def render_index(issues: list[str]) -> str:
    items = "\n".join(
        f'      <li><a href="{ym}.html">{month_name(ym)}</a></li>' for ym in issues
    ) or "      <li>No issues yet.</li>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Punk BC — monthly digest archive</title>
<meta name="description" content="Every issue of the Punk BC monthly digest: punk, hardcore and metal shows across British Columbia, month by month.">
<link rel="canonical" href="{SITE}/digest/">
<link rel="alternate" type="application/rss+xml" title="Punk BC digest" href="{SITE}/punkbc-digest.xml">
<style>
  :root{{--bg:#0a0a0a;--border:#222;--red:#dc2626;--white:#f5f5f5;--gray:#9ca3af;}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--white);font-family:'Courier New',Courier,monospace;
    line-height:1.6;padding:24px 16px 60px}}
  .wrap{{max-width:680px;margin:0 auto}}
  .kicker{{color:var(--red);font-size:12px;letter-spacing:.2em;text-transform:uppercase}}
  h1{{font-size:24px;margin:6px 0 10px}}
  p{{color:var(--gray);font-size:13px}}
  ul{{list-style:none;margin:24px 0 0}}
  li{{padding:12px 0;border-top:1px solid var(--border)}}
  a{{color:var(--white);text-decoration:none}}
  a:hover{{color:var(--red)}}
  .foot{{margin-top:28px;color:var(--gray);font-size:12px}}
  .foot a{{color:var(--red)}}
  .picks{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:22px}}
  .pick{{display:block;text-decoration:none;color:inherit;border:1px solid var(--border);
    border-radius:8px;overflow:hidden;background:var(--card)}}
  .pick:hover{{border-color:var(--red)}}
  .pick img{{display:block;width:100%;height:auto;aspect-ratio:16/9;object-fit:cover;background:#000}}
  .pick-b{{font-size:13px;font-weight:bold;padding:8px 10px 0}}
  .pick-m{{font-size:11px;color:var(--gray);padding:2px 10px 10px}}
</style>
</head>
<body>
  <div class="wrap">
    <p class="kicker">🤘 Punk BC</p>
    <h1>Monthly digest — archive</h1>
    <p>What was on, month by month. The <a href="{BOARD}" style="color:var(--red)">board</a> always has the live list.</p>
    <ul>
{items}
    </ul>
    <p class="foot"><a href="{SITE}/punkbc-digest.xml">RSS</a> · <a href="{BOARD}">back to the board</a></p>
  </div>
</body>
</html>
"""


# ── the email copy ─────────────────────────────────────────────────────────

def render_email(ym: str, shows: list[dict]) -> str:
    """Tables and inline styles, because email clients are stuck in 2003.

    Light background on purpose: dark-themed email is a lottery across clients.
    """
    label = month_name(ym)

    # Featured acts, two to a row. Tables and fixed widths because Outlook has
    # no grid, and every client blocks images until the reader allows them —
    # hence the alt text carrying the band name.
    picks = featured(shows)
    pick_cells = []
    for s2 in picks:
        href = html.escape(s2.get("ticket") or BOARD, quote=True)
        src = art(s2["image"])
        # A cropped file is 16:9 already, so telling the client its height costs
        # nothing and stops the layout jumping as it loads. A photo we could not
        # crop is whatever shape it was: give it a width and let it keep its own
        # ratio, because Outlook obeys a height attribute by stretching to it.
        cropped = src.startswith(f"{SITE}/img/digest/")
        dims = 'width="270" height="150"' if cropped else 'width="270"'
        pick_cells.append(f"""
            <td width="50%" valign="top" style="padding:6px;">
              <a href="{href}" style="text-decoration:none;color:#111111;">
                <img src="{html.escape(src, quote=True)}" {dims}
                     alt="{html.escape(s2['band'])}"
                     style="display:block;width:100%;max-width:270px;height:auto;border-radius:6px;background:#eeeeee;border:0;">
                <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;font-weight:bold;margin-top:6px;">{html.escape(s2['band'])}</div>
                <div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#555555;">{html.escape(day_label(s2['date']))} &middot; {html.escape(s2.get('venue') or 'TBA')}</div>
              </a>
            </td>""")
    pick_rows = []
    for i in range(0, len(pick_cells), 2):
        pair = pick_cells[i:i + 2]
        if len(pair) == 1:
            pair.append('<td width="50%"></td>')
        pick_rows.append("          <tr>" + "".join(pair) + "\n          </tr>")
    picks_block = ("""
      <tr><td style="padding-top:18px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
""" + "\n".join(pick_rows) + """
        </table>
      </td></tr>""") if pick_rows else ""

    rows = []
    for s in shows:
        ticket = html.escape(s.get("ticket") or BOARD, quote=True)
        meta = " · ".join(x for x in [html.escape(s.get("venue") or "TBA"),
                                      html.escape(s.get("city") or ""),
                                      html.escape(s.get("price") or "")] if x)
        notes = html.escape(s.get("notes") or "")
        rows.append(f"""
          <tr>
            <td style="padding:12px 0;border-top:1px solid #e5e5e5;font-family:Arial,Helvetica,sans-serif;">
              <div style="color:#dc2626;font-size:12px;letter-spacing:.06em;text-transform:uppercase;">
                {html.escape(day_label(s['date']))}{' · ' + html.escape(s['time']) if s.get('time') else ''}
              </div>
              <div style="font-size:16px;font-weight:bold;margin-top:2px;">
                <a href="{ticket}" style="color:#111111;text-decoration:none;">{html.escape(s['band'])}</a>
              </div>
              <div style="color:#555555;font-size:13px;margin-top:2px;">{meta}</div>
              {f'<div style="color:#777777;font-size:12px;margin-top:2px;">{notes}</div>' if notes else ''}
            </td>
          </tr>""")
    listing = "".join(rows) or """
          <tr><td style="padding:14px 0;font-family:Arial,Helvetica,sans-serif;color:#555;">
            Nothing listed yet this month — <a href="%s" style="color:#dc2626;">check the board</a>.
          </td></tr>""" % BOARD

    return f"""<!-- Punk BC digest — {label}. Paste into your email service, or let it
     pull {SITE}/punkbc-digest.xml as an RSS campaign.
     Your provider adds the unsubscribe link; if it does not, add one — it is
     required by CASL for commercial email in Canada. -->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f6f6;padding:24px 12px;">
  <tr><td align="center">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:620px;background:#ffffff;border-radius:10px;padding:26px;">
      <tr><td style="font-family:Arial,Helvetica,sans-serif;">
        <div style="color:#dc2626;font-size:12px;letter-spacing:.2em;text-transform:uppercase;">Punk BC · monthly</div>
        <h1 style="font-size:24px;margin:6px 0 4px;color:#111111;">{label}</h1>
        <div style="color:#555555;font-size:13px;">
          {len(shows)} show{'s' if len(shows) != 1 else ''} across British Columbia.
          <a href="{SITE}/digest/{ym}.html" style="color:#dc2626;">Read it in a browser</a>.
        </div>
      </td></tr>{picks_block}
      <tr><td>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px;">{listing}
        </table>
      </td></tr>
      <tr><td style="padding-top:20px;font-family:Arial,Helvetica,sans-serif;color:#777777;font-size:12px;line-height:1.7;">
        Dates change and shows sell out — check the ticket link before you go.<br>
        <a href="{BOARD}" style="color:#dc2626;">The full board</a> ·
        <a href="{SITE}/digest/" style="color:#dc2626;">past issues</a>
      </td></tr>
    </table>
  </td></tr>
</table>
"""


# ── the feed ───────────────────────────────────────────────────────────────

def render_feed(issues: list[str]) -> str:
    items = []
    for ym in issues[:24]:
        shows = shows_for(ym)
        summary = "<br>".join(html.escape(line_for(s)) for s in shows) or "No shows listed."
        # first of the month, which is when the issue is considered published
        pub = datetime.strptime(ym + "-01", "%Y-%m-%d").replace(tzinfo=TZ)
        items.append(f"""  <item>
    <title>Punk BC — {month_name(ym)} shows</title>
    <link>{SITE}/digest/{ym}.html</link>
    <guid isPermaLink="true">{SITE}/digest/{ym}.html</guid>
    <pubDate>{pub.strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>
    <description>{html.escape('<p>' + summary + '</p>')}</description>
  </item>""")
    now = datetime.now(TZ).strftime('%a, %d %b %Y %H:%M:%S %z')
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Punk BC — monthly digest</title>
  <link>{SITE}/digest/</link>
  <description>Punk, hardcore and metal shows across British Columbia, once a month.</description>
  <language>en-ca</language>
  <lastBuildDate>{now}</lastBuildDate>
{chr(10).join(items)}
</channel>
</rss>
"""


def update_sitemap(url: str, lastmod: str) -> None:
    """Keep the archive in the sitemap with a current lastmod."""
    text = SITEMAP.read_text(encoding="utf-8")
    if url in text:
        block = re.search(r"<url>\s*<loc>" + re.escape(url) + r"</loc>(?:(?!</url>).)*?</url>",
                          text, re.DOTALL)
        if block:
            new_block = re.sub(r"<lastmod>.*?</lastmod>", f"<lastmod>{lastmod}</lastmod>", block.group(0)) \
                if "<lastmod>" in block.group(0) else \
                block.group(0).replace("</loc>", f"</loc>\n    <lastmod>{lastmod}</lastmod>", 1)
            text = text.replace(block.group(0), new_block)
    else:
        entry = (f"  <url>\n    <loc>{url}</loc>\n    <lastmod>{lastmod}</lastmod>\n"
                 f"    <priority>0.6</priority>\n    <changefreq>monthly</changefreq>\n  </url>\n")
        text = text.replace("</urlset>", entry + "</urlset>")
    SITEMAP.write_text(text, encoding="utf-8")


def render_send(ym: str, email_html: str, count: int) -> str:
    """The one page needed to actually send the thing.

    The email copy is built every time the digest is, and then has to get from
    this repository into MailerLite. Hunting down digest/2026-09.email.html on
    GitHub, opening raw, selecting all — that is four steps too many for a job
    done twice a month, and the kind of friction that ends with the newsletter
    quietly not going out.

    So this is a button. It always shows the current issue, because it is
    rebuilt alongside it, and it carries the steps next to the thing they
    describe rather than in someone's memory.

    Deliberately kept out of search results: it is a tool, not a page anyone
    should land on from Google.
    """
    label = month_name(ym)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>Send the {html.escape(label)} digest</title>
<style>
  :root {{ --red:#dc2626; --ink:#111; --grey:#555; --line:#e5e5e5; }}
  * {{ box-sizing:border-box }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;
         margin:0; padding:24px 16px; background:#fafafa; color:var(--ink); line-height:1.6 }}
  .wrap {{ max-width:760px; margin:0 auto }}
  h1 {{ font-size:24px; margin:0 0 4px }}
  .sub {{ color:var(--grey); font-size:14px; margin-bottom:22px }}
  .sub a {{ color:var(--red) }}
  button {{ background:var(--red); color:#fff; border:0; border-radius:8px;
            padding:14px 22px; font-size:16px; font-weight:600; cursor:pointer; width:100% }}
  button:hover {{ filter:brightness(1.08) }}
  #said {{ min-height:22px; font-size:14px; color:#15803d; margin:10px 0 0; font-weight:600 }}
  ol {{ padding-left:22px; margin:24px 0 0 }}
  li {{ margin-bottom:10px }}
  code {{ background:#eee; padding:2px 6px; border-radius:4px; font-size:13px }}
  textarea {{ width:100%; height:220px; margin-top:20px; font-family:ui-monospace,Menlo,Consolas,monospace;
              font-size:11px; border:1px solid var(--line); border-radius:8px; padding:12px; background:#fff }}
  .note {{ margin-top:24px; padding:14px 16px; background:#fffbe6; border:1px solid #e6d68a;
           border-radius:8px; font-size:14px; color:#5a4a10 }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Send the {html.escape(label)} digest</h1>
  <div class="sub">{count} shows &middot;
    <a href="{ym}.html">read the issue</a> &middot;
    rebuilt automatically whenever the board changes</div>

  <button id="copy" type="button">Copy the email HTML</button>
  <p id="said"></p>

  <ol>
    <li>MailerLite &rarr; <b>Campaigns</b> &rarr; <b>Create campaign</b> &rarr; <i>Regular campaign</i></li>
    <li>Subject: <code>Punk BC &mdash; {html.escape(label)} shows</code></li>
    <li>Pick the group <b>Punk BC &mdash; monthly digest</b></li>
    <li>For the content choose <b>Custom HTML</b> and paste</li>
    <li><b>Send a test email</b> to yourself and check the photos load</li>
    <li>Send it</li>
  </ol>

  <div class="note">
    Send from a verified <b>mikidrummer.ca</b> address, not a Gmail one, and leave
    MailerLite's unsubscribe link in place &mdash; CASL requires it for commercial
    email in Canada.
  </div>

  <textarea id="html" readonly spellcheck="false">{html.escape(email_html)}</textarea>
</div>
<script>
  var box = document.getElementById('html'),
      said = document.getElementById('said');
  document.getElementById('copy').addEventListener('click', function () {{
    // The clipboard API needs a secure context and permission; select() and
    // execCommand work everywhere and are the fallback, not the other way round.
    function ok() {{ said.textContent = 'Copied \\u2014 paste it into MailerLite.'; }}
    if (navigator.clipboard && window.isSecureContext) {{
      navigator.clipboard.writeText(box.value).then(ok, manual);
    }} else {{ manual(); }}
    function manual() {{
      box.focus(); box.select();
      var done = false;
      try {{ done = document.execCommand('copy'); }} catch (e) {{}}
      said.textContent = done ? 'Copied \\u2014 paste it into MailerLite.'
                              : 'Selected below \\u2014 press Ctrl/Cmd+C to copy.';
    }}
  }});
</script>
</body>
</html>
"""


def main() -> int:
    args = sys.argv[1:]
    if "--month" in args:
        ym = args[args.index("--month") + 1]
    elif "--next" in args:
        d = today().replace(day=28) + timedelta(days=7)
        ym = d.strftime("%Y-%m")
    else:
        ym = today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-\d{2}", ym):
        print(f"month should look like 2026-09, got {ym!r}")
        return 1

    shows = shows_for(ym)
    OUT.mkdir(exist_ok=True)
    (OUT / f"{ym}.html").write_text(render_page(ym, shows), encoding="utf-8")
    # An email fragment carries no <meta charset>, and the client decides what
    # the bytes mean — get it wrong and every "·" becomes "Â·". Numeric entities
    # cannot be misread, so nothing non-ASCII survives into the file.
    email_html = render_email(ym, shows).encode("ascii", "xmlcharrefreplace").decode("ascii")
    (OUT / f"{ym}.email.html").write_text(email_html, encoding="utf-8")
    # Always the current issue, at a URL that never changes, so the monthly job
    # is "open the bookmark, press the button" rather than a hunt through git.
    (OUT / "send.html").write_text(render_send(ym, email_html, len(shows)), encoding="utf-8")

    issues = sorted((p.stem for p in OUT.glob("*.html")
                     if re.fullmatch(r"\d{4}-\d{2}", p.stem)), reverse=True)
    (OUT / "index.html").write_text(render_index(issues), encoding="utf-8")
    FEED.write_text(render_feed(issues), encoding="utf-8")
    update_sitemap(f"{SITE}/digest/", today().isoformat())

    print(f"{ym}: {len(shows)} shows -> digest/{ym}.html, email copy, "
          f"archive of {len(issues)} issue(s), feed, sitemap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
