#!/usr/bin/env python3
"""Build /photo-credits.html from the art credit files.

Most of the photographs on the board come from Wikimedia Commons under CC BY or
CC BY-SA. Those licences are free to use and they are not free of conditions:
the photographer has to be named and the licence has to be stated. Hotlinking
sidestepped that by never making a copy. Hosting the files ourselves does make
a copy, so the credit has to appear somewhere — this is that somewhere, linked
from the board.

    python3 tools/build_credits.py
"""

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOW_ART = ROOT / "images" / "show-art-credits.json"
CROWD = ROOT / "images" / "crowd-credits.json"
OUT = ROOT / "photo-credits.html"
SITE = "https://www.mikidrummer.ca"


def rows_from_shows():
    if not SHOW_ART.exists():
        return []
    data = json.loads(SHOW_ART.read_text(encoding="utf-8")).get("images", {})
    out = []
    for name, c in sorted(data.items()):
        out.append({
            "file": "/images/shows/" + name,
            "title": (c.get("title") or name).replace("File:", ""),
            "license": c.get("license") or "",
            "license_url": c.get("license_url") or "",
            "author": c.get("author") or "",
            "source": c.get("source") or "",
        })
    return out


def rows_from_crowd():
    if not CROWD.exists():
        return []
    out = []
    for c in json.loads(CROWD.read_text(encoding="utf-8")).get("images", []):
        out.append({
            "file": "/" + c["file"],
            "title": (c.get("title") or "").replace("File:", ""),
            "license": c.get("license") or "",
            "license_url": "",
            "author": c.get("artist") or "",
            "source": c.get("source") or "",
        })
    return out


def block(title, note, rows):
    if not rows:
        return ""
    items = []
    for r in rows:
        lic = html.escape(r["license"])
        if r["license_url"]:
            lic = (f'<a href="{html.escape(r["license_url"], quote=True)}" '
                   f'target="_blank" rel="noopener">{lic}</a>')
        who = html.escape(r["author"]) if r["author"] else "—"
        src = (f'<a href="{html.escape(r["source"], quote=True)}" target="_blank" '
               f'rel="noopener">Commons</a>' if r["source"] else "")
        items.append(
            f'      <li>\n'
            f'        <img src="{html.escape(r["file"], quote=True)}" alt="" loading="lazy">\n'
            f'        <div>\n'
            f'          <div class="t">{html.escape(r["title"])}</div>\n'
            f'          <div class="m">{who} · {lic} {src}</div>\n'
            f'        </div>\n'
            f'      </li>')
    return (f'  <section>\n    <h2>{html.escape(title)}</h2>\n'
            f'    <p class="note">{note}</p>\n'
            f'    <ul>\n' + "\n".join(items) + "\n    </ul>\n  </section>\n")


def main() -> int:
    shows = rows_from_shows()
    crowd = rows_from_crowd()
    n = len(shows) + len(crowd)

    body = block(
        "Show photos", "Used on the show cards, from Wikimedia Commons.", shows
    ) + block(
        "Crowd photos",
        "Used when a show has no photo of its own. Public domain or CC0.", crowd)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Photo credits | Punk BC</title>
<meta name="description" content="Who took the photographs on the Punk BC shows board, and the licence each one is used under.">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{SITE}/photo-credits.html">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="96x96" href="/images/icon-96.png">
<link rel="apple-touch-icon" href="/images/icon-180.png">
<style>
  :root {{ --bg:#0b0c0e; --card:#131518; --edge:#2b2f34; --dim:#7d848d; --mid:#a6adb6; --fg:#e9ebee; --hot:#e8672a; }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--fg);font-family:"Helvetica Neue",system-ui,Arial,sans-serif;line-height:1.6;padding:0 18px 70px}}
  .wrap{{max-width:800px;margin:0 auto}}
  a{{color:var(--hot);text-decoration:none}} a:hover{{text-decoration:underline}}
  header{{padding:44px 0 22px;border-bottom:1px solid var(--edge)}}
  .eyebrow{{font-size:11px;letter-spacing:.3em;text-transform:uppercase;color:var(--hot);font-weight:700}}
  h1{{font-family:"Arial Black",system-ui,sans-serif;font-size:clamp(25px,5vw,38px);letter-spacing:-.02em;margin:10px 0 12px}}
  .lead{{color:var(--mid);font-size:15.5px;max-width:64ch}}
  section{{margin-top:34px}}
  h2{{font-size:12px;letter-spacing:.2em;text-transform:uppercase;color:var(--dim);font-weight:700}}
  .note{{color:var(--mid);font-size:14px;margin:6px 0 14px}}
  ul{{list-style:none}}
  li{{display:flex;gap:14px;align-items:center;padding:10px 0;border-top:1px solid var(--edge)}}
  li img{{width:74px;height:50px;object-fit:cover;border-radius:6px;flex:none;background:var(--card)}}
  .t{{font-size:14.5px;font-weight:600}}
  .m{{color:var(--dim);font-size:12.5px}}
  footer{{margin-top:40px;padding-top:22px;border-top:1px solid var(--edge);color:var(--dim);font-size:13px}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="eyebrow">Punk BC</span>
    <h1>Photo credits</h1>
    <p class="lead">The photographs on the <a href="/punkbc.html">shows board</a> come from
      Wikimedia Commons. Most are used under Creative Commons licences that ask for the
      photographer to be named and the licence stated — so here they are, all {n} of them.
      Shot something here and want it taken down or the credit corrected?
      <a href="/play-with-us.html">Say so</a> and it is done.</p>
  </header>

{body}  <footer>
    Part of <a href="/punkbc.html">Punk BC</a>, kept by <a href="/">Miki Drummer</a>.
    Band promo shots on ticketing sites are linked, not copied, and stay with whoever owns them.
  </footer>
</div>
</body>
</html>
"""
    OUT.write_text(page, encoding="utf-8")
    print("photo-credits.html: %d show photos, %d crowd photos" % (len(shows), len(crowd)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
