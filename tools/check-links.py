#!/usr/bin/env python3
"""
Weekly link checker for mikidrummer.ca and Miki's linked profiles.

- Crawls the live site pages, extracts every href/src link.
- Checks each link's HTTP status (internal + external), with timeouts.
- Also checks the Linktree page and its outbound links.
- Verifies the "two-way" key profiles stay reachable: YouTube, TikTok,
  Instagram, the website, and Linktree.

Writes a Markdown report to link-report.md and prints a summary.
Exit code 1 if any INTERNAL link (something we control) is broken, so a
CI job can flag it. External breakages are reported as warnings.

No third-party dependencies — standard library only.
"""
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SITE = "https://www.mikidrummer.ca"

# Pages to crawl for links (the site we control)
PAGES = [
    "/", "/about.html", "/video.html", "/services.html",
    "/punkbc.html", "/bands.html", "/meet-mat.html",
    "/granite-epk.html", "/lift-the-anchor-epk.html",
]

# Extra external sources whose outbound links we also want to verify
EXTRA_SOURCES = [
    "https://linktr.ee/mikidrummer",
]

# The "two-way" profiles that must stay reachable in both directions.
KEY_PROFILES = {
    "Website":   "https://www.mikidrummer.ca/",
    "YouTube":   "https://www.youtube.com/@MikiDrummerBC",
    "TikTok":    "https://www.tiktok.com/@mikibdrummer",
    "Instagram": "https://www.instagram.com/mikibdrummer/",
    "Linktree":  "https://linktr.ee/mikidrummer",
}

UA = "Mozilla/5.0 (mikidrummer-link-check/1.0; +https://www.mikidrummer.ca)"
TIMEOUT = 20
CTX = ssl.create_default_context()


def _request(url, method="GET"):
    return urllib.request.Request(url, method=method, headers={"User-Agent": UA})


def get_html(url):
    try:
        with urllib.request.urlopen(_request(url), timeout=TIMEOUT, context=CTX) as r:
            if "html" not in (r.headers.get_content_type() or ""):
                return ""
            return r.read(3_000_000).decode("utf-8", "ignore")
    except Exception:
        return ""


def normalize(url):
    """Percent-encode the path (spaces, accents) so urllib accepts it."""
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (p.scheme, p.netloc, urllib.parse.quote(p.path), p.query, p.fragment)
    )


def extract_links(html, base):
    out = set()
    # `(?<![.\w])` skips JS property assignments like `location.href = '...'`.
    for m in re.finditer(r'(?<![.\w])(?:href|src)\s*=\s*["\']([^"\']+)["\']', html, re.I):
        u = m.group(1).strip()
        if not u or u.startswith(("mailto:", "tel:", "javascript:", "data:", "#")):
            continue
        if "${" in u or "{{" in u or "}}" in u:   # template-literal placeholders, not real links
            continue
        out.add(normalize(urllib.parse.urljoin(base, u)))
    return out


def check(url):
    """Return (ok, status, note)."""
    for method in ("HEAD", "GET"):
        try:
            with urllib.request.urlopen(_request(url, method), timeout=TIMEOUT, context=CTX) as r:
                return r.status < 400, r.status, ("redirect" if 300 <= r.status < 400 else "")
        except urllib.error.HTTPError as e:
            # Some hosts reject HEAD (405/403/501) — retry with GET before failing.
            if method == "HEAD" and e.code in (403, 405, 501, 400):
                continue
            # 3xx = reachable (redirect); 401/403/429 = up but anti-bot gated.
            ok = e.code < 400 or e.code in (401, 403, 429)
            note = "redirect" if e.code < 400 else ("reachable but gated" if ok else "")
            return ok, e.code, note
        except Exception as e:
            if method == "HEAD":
                continue
            return False, None, str(e).split("]")[-1].strip()[:70]
    return False, None, "unreachable"


def is_internal(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    return host.endswith("mikidrummer.ca")


HTML_CSS = """
body{margin:0;background:#0f1012;color:#e9ebee;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:28px 20px 70px}
h1{font-size:26px;margin:0} .sub{color:#9ca3af;font-size:13px;margin:4px 0 18px}
.banner{padding:16px 20px;border-radius:12px;font-weight:800;font-size:20px;margin-bottom:22px;display:flex;align-items:center;gap:12px}
.banner.ok{background:rgba(34,197,94,.12);color:#22c55e;border:1px solid rgba(34,197,94,.4)}
.banner.bad{background:rgba(220,38,38,.12);color:#f87171;border:1px solid rgba(220,38,38,.45)}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:8px}
.tile{background:#16181b;border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:16px}
.tile .num{font-size:30px;font-weight:800} .tile .lbl{color:#9ca3af;font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin-top:2px}
.tile.ok .num{color:#22c55e} .tile.bad .num{color:#f87171} .tile.warn .num{color:#f59e0b}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:#9ca3af;margin:28px 0 12px;border-top:1px solid rgba(255,255,255,.08);padding-top:20px}
.profiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px}
.card{display:block;text-decoration:none;color:inherit;border-radius:12px;padding:16px 12px;border:1px solid;text-align:center;transition:transform .1s}
.card:hover{transform:translateY(-2px)}
.card.ok{background:rgba(34,197,94,.08);border-color:rgba(34,197,94,.35)}
.card.bad{background:rgba(220,38,38,.10);border-color:rgba(220,38,38,.5)}
.card .mark{font-size:32px;font-weight:900;line-height:1}
.card.ok .mark{color:#22c55e} .card.bad .mark{color:#f87171}
.card .cname{font-weight:700;margin-top:8px} .card .cstat{font-size:12px;color:#9ca3af;margin-top:2px}
.card .curl{font-size:10px;color:#6b7280;margin-top:6px;word-break:break-all}
.row{display:flex;align-items:center;gap:12px;padding:11px 14px;border-radius:10px;background:#16181b;margin-bottom:8px;border-left:4px solid #333}
.row.bad{border-left-color:#dc2626} .row.warn{border-left-color:#f59e0b}
.pill{font-weight:800;font-size:12px;padding:3px 9px;border-radius:20px;flex:none;min-width:44px;text-align:center}
.pill.bad{background:rgba(220,38,38,.16);color:#f87171} .pill.warn{background:rgba(245,158,11,.16);color:#f59e0b}
.from{color:#a6adb6;font-size:12px;font-family:ui-monospace,Menlo,Consolas,monospace;flex:none;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.arrow{color:#f4933f;font-weight:800;flex:none}
.url{color:#e9ebee;text-decoration:none;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;word-break:break-all;flex:1;min-width:0}
.url:hover{color:#f4933f} .note{color:#f59e0b;font-size:11px;flex:none}
.hint{color:#6b7280;font-size:12px;margin:-8px 0 18px} .hint b{color:#a6adb6}
.card .cfrom{font-size:10px;color:#7d848d;margin-top:8px;border-top:1px solid rgba(255,255,255,.07);padding-top:6px}
.none{color:#22c55e;padding:8px 4px}
@media(max-width:640px){.tiles{grid-template-columns:repeat(2,1fr)}.from{max-width:120px}}
"""


def write_html(path, total, ok_count, profile_items, internal_bad, missing_img,
               external_bad, link_sources):
    import html as _h
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    broken_profiles = [p for p in profile_items if not p[2]]
    broken = len(internal_bad) + len(broken_profiles)
    warnings = len(missing_img) + len(external_bad)
    ok = broken == 0

    def esc(s):
        return _h.escape(str(s))

    def short(p):
        return p.replace(SITE, "") or "home"

    def rows(items, level):
        if not items:
            return '<div class="none">None. ✓</div>'
        out = []
        for url, status, note, pages in items:
            src = " · ".join(short(p) for p in sorted(pages))
            note_html = f'<span class="note">{esc(note)}</span>' if note else ""
            out.append(
                f'<div class="row {level}">'
                f'<span class="pill {level}">{esc(status if status is not None else "ERR")}</span>'
                f'<span class="from" title="on page(s): {esc(src)}">{esc(src)}</span>'
                f'<span class="arrow">&rarr;</span>'
                f'<a class="url" href="{esc(url)}" target="_blank" rel="noopener">{esc(url)}</a>'
                f'{note_html}</div>'
            )
        return "\n".join(out)

    cards = []
    for name, url, pok, status, note in profile_items:
        cls = "ok" if pok else "bad"
        cstat = esc(status if status is not None else "ERR") + (f" · {esc(note)}" if note else "")
        srcs = sorted(link_sources.get(normalize(url), link_sources.get(url, set())))
        from_txt = ("linked from: " + " · ".join(short(p) for p in srcs)) if srcs else "not linked from the site"
        cards.append(
            f'<a class="card {cls}" href="{esc(url)}" target="_blank" rel="noopener">'
            f'<div class="mark">{"✓" if pok else "✗"}</div>'
            f'<div class="cname">{esc(name)}</div><div class="cstat">{cstat}</div>'
            f'<div class="curl">{esc(url)}</div>'
            f'<div class="cfrom">{esc(from_txt)}</div></a>'
        )

    banner = ('<div class="banner ok">✓ All good — every internal link and key profile is working.</div>'
              if ok else
              f'<div class="banner bad">✗ {broken} problem(s) need attention.</div>')

    html_doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Link Check — mikidrummer.ca</title><style>{HTML_CSS}</style></head><body>
<div class="wrap">
  <h1>Link Check</h1>
  <div class="sub">mikidrummer.ca · {ts} · {total} links checked</div>
  {banner}
  <div class="hint">Each row reads <b>source page</b> &rarr; <b>destination URL</b> — where the link lives and where it points.</div>
  <div class="tiles">
    <div class="tile"><div class="num">{total}</div><div class="lbl">Checked</div></div>
    <div class="tile ok"><div class="num">{ok_count}</div><div class="lbl">Working</div></div>
    <div class="tile bad"><div class="num">{broken}</div><div class="lbl">Broken</div></div>
    <div class="tile warn"><div class="num">{warnings}</div><div class="lbl">Warnings</div></div>
  </div>
  <h2>Key profiles — two-way (YouTube · TikTok · Instagram · site · Linktree)</h2>
  <div class="profiles">{''.join(cards)}</div>
  <h2>Broken links — must fix ({len(internal_bad)})</h2>
  {rows(internal_bad, "bad")}
  <h2>Warnings — missing / placeholder images ({len(missing_img)})</h2>
  {rows(missing_img, "warn")}
  <h2>Warnings — external links ({len(external_bad)})</h2>
  {rows(external_bad, "warn")}
</div></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)


def main():
    # 1) Gather all links from the pages we control + the extra sources.
    sources = [SITE + p for p in PAGES] + EXTRA_SOURCES
    link_sources = {}  # url -> set of pages it appears on
    print("Crawling", len(sources), "source pages...")
    for src in sources:
        for link in extract_links(get_html(src), src):
            link_sources.setdefault(link, set()).add(src)

    all_links = sorted(link_sources)
    print("Found", len(all_links), "unique links. Checking...")

    # 2) Check every link (in parallel).
    results = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        for url, res in zip(all_links, ex.map(check, all_links)):
            results[url] = res

    # 3) Check the key two-way profiles explicitly.
    profile_results = {name: check(url) for name, url in KEY_PROFILES.items()}

    # 4) Build report.
    IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg")
    internal_bad, missing_img, external_bad = [], [], []
    for url in all_links:
        ok, status, note = results[url]
        if not ok:
            row = (url, status, note, sorted(link_sources[url]))
            if not is_internal(url):
                external_bad.append(row)
            elif url.lower().rsplit("?", 1)[0].endswith(IMG_EXT):
                missing_img.append(row)   # optional/placeholder art — warning, not failure
            else:
                internal_bad.append(row)

    lines = ["# Link check — mikidrummer.ca", ""]
    lines.append(f"Checked **{len(all_links)}** links across {len(sources)} pages.")
    lines.append("")

    lines.append("## Key profiles (two-way: YouTube / TikTok / IG / site / Linktree)")
    for name, url in KEY_PROFILES.items():
        ok, status, note = profile_results[name]
        mark = "OK" if ok else "BROKEN"
        extra = f" ({note})" if note else ""
        lines.append(f"- [{mark}] **{name}** {status or ''}{extra} — {url}")
    lines.append("")

    def section(title, rows):
        lines.append(f"## {title} ({len(rows)})")
        if rows:
            for url, status, note, pages in rows:
                tag = f" ({note})" if note else ""
                lines.append(f"- {status or 'ERR'} `{url}`{tag} — on: {', '.join(p.replace(SITE, '') or '/' for p in pages)}")
        else:
            lines.append("- None.")
        lines.append("")

    section("Broken internal links (FAIL)", internal_bad)
    section("Missing optional images / placeholder art (warning)", missing_img)
    section("Broken external links (warning)", external_bad)

    report = "\n".join(lines)
    with open("link-report.md", "w", encoding="utf-8") as f:
        f.write(report)

    # Visual HTML dashboard
    total = len(all_links)
    ok_count = sum(1 for u in all_links if results[u][0])
    profile_items = [(n, KEY_PROFILES[n], *profile_results[n]) for n in KEY_PROFILES]
    write_html("link-report.html", total, ok_count, profile_items,
               internal_bad, missing_img, external_bad, link_sources)
    print(report)
    print("\nWrote link-report.html (visual) and link-report.md")

    profiles_broken = [n for n, r in profile_results.items() if not r[0]]
    if internal_bad or profiles_broken:
        print(f"\nFAIL: {len(internal_bad)} broken internal link(s) + "
              f"{len(profiles_broken)} key-profile problem(s): {', '.join(profiles_broken) or 'none'}")
        return 1
    print(f"\nPASS. Warnings: {len(missing_img)} missing images, {len(external_bad)} external.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
