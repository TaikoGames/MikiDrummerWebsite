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
    "/punkbc.html", "/bands.html",
    "/granite-epk.html", "/lift-the-anchor-epk.html",
]

# Extra external sources whose outbound links we also want to verify
EXTRA_SOURCES = [
    "https://linktr.ee/mikidrummer",
]

# The "two-way" profiles that must stay reachable in both directions.
KEY_PROFILES = {
    "Website":   "https://www.mikidrummer.ca/",
    "YouTube":   "https://www.youtube.com/@CompanyMiki",
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
    print(report)

    profiles_broken = [n for n, r in profile_results.items() if not r[0]]
    if internal_bad or profiles_broken:
        print(f"\nFAIL: {len(internal_bad)} broken internal link(s) + "
              f"{len(profiles_broken)} key-profile problem(s): {', '.join(profiles_broken) or 'none'}")
        return 1
    print(f"\nPASS. Warnings: {len(missing_img)} missing images, {len(external_bad)} external.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
