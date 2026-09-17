#!/usr/bin/env python3
"""Audit every indexable page on the site and report what is holding it back.

This exists because the two most valuable pages on the site sat broken for
months in ways nobody would notice by looking at them: index.html had no <h1>
at all, services.html had an empty one, and an orphan copy of the services
page was in Google's index under the title "Mirkidrummer". None of that is
visible in a browser. All of it is trivial to see from the HTML.

So: read every page, measure the things Google actually reads, and print what
is wrong ranked by how much it matters. Run it weekly and the next one of
these gets caught in days rather than months.

    python3 tools/seo_audit.py              # human-readable report
    python3 tools/seo_audit.py --json       # machine-readable, for a workflow
    python3 tools/seo_audit.py --fail-on high

What it deliberately does NOT do: tell you how you are ranking. That lives in
Search Console and nothing here can see it. This checks the things that are
true of the site itself -- the half you control.
"""

import argparse
import html
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://www.mikidrummer.ca"

# Google truncates around these; over is not an error, it is a lost sentence.
TITLE_MAX = 60
TITLE_MIN = 15
DESC_MAX = 155
DESC_MIN = 70

# Under this, a page is unlikely to outrank anything for a competitive term.
# Band pages are generated stubs and judged on a lower bar of their own.
THIN_WORDS = 150
THIN_WORDS_GENERATED = 90

SEVERITY = {"high": 0, "medium": 1, "low": 2}


# --------------------------------------------------------------------------
# reading pages
# --------------------------------------------------------------------------

def strip_code(markup):
    """Everything a reader sees, with script and style removed.

    Comments go too -- this file's own explanatory comments should not count
    as page content, and neither should a commented-out block someone left.
    """
    markup = re.sub(r"(?s)<!--.*?-->", "", markup)
    return re.sub(r"(?s)<(script|style)\b.*?</\1>", "", markup)


def visible_text(body):
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", body)).strip()


def tag_text(body, tag):
    out = []
    for m in re.findall(r"(?s)<%s\b[^>]*>(.*?)</%s>" % (tag, tag), body):
        out.append(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m)).strip())
    return out


def meta(markup, name):
    m = re.search(r'<meta\s+name=["\']%s["\']\s+content=["\'](.*?)["\']' % name,
                  markup, re.I | re.S)
    return html.unescape(m.group(1)).strip() if m else None


class Page:
    def __init__(self, path):
        self.path = path                                  # repo-relative
        self.url = "/" + path.replace(os.sep, "/")
        raw = open(os.path.join(ROOT, path), encoding="utf-8", errors="replace").read()
        self.raw = raw
        body = strip_code(raw)
        self.body = body
        self.text = visible_text(body)
        self.words = len(self.text.split())

        t = re.search(r"(?s)<title>(.*?)</title>", raw)
        self.title = html.unescape(re.sub(r"\s+", " ", t.group(1)).strip()) if t else None
        self.description = meta(raw, "description")
        self.robots = (meta(raw, "robots") or "").lower()
        self.noindex = "noindex" in self.robots

        self.h1s = tag_text(body, "h1")
        self.h2s = tag_text(body, "h2")

        c = re.search(r'<link\s+rel=["\']canonical["\']\s+href=["\'](.*?)["\']', raw, re.I)
        self.canonical = c.group(1).strip() if c else None

        self.redirect = bool(re.search(r'http-equiv=["\']refresh["\']', raw, re.I))

        self.jsonld = []
        for blk in re.findall(r'(?s)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', raw):
            try:
                self.jsonld.append(json.loads(blk))
            except ValueError as e:
                self.jsonld.append({"_broken": str(e)})

        self.links = [h for h in re.findall(r'href=["\']([^"\']+)["\']', body)]
        self.imgs = re.findall(r"(?s)<img\b([^>]*)>", body)

    @property
    def generated(self):
        return self.path.startswith("bands/") or self.path.startswith("shows/")


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------

class Report:
    def __init__(self):
        self.items = []

    def add(self, severity, check, where, detail, fix=None):
        self.items.append({"severity": severity, "check": check, "where": where,
                           "detail": detail, "fix": fix})

    def sorted(self):
        return sorted(self.items, key=lambda i: (SEVERITY[i["severity"]], i["check"], i["where"]))


def collect_pages():
    pages = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs
                   if d not in (".git", "node_modules", "css", "js", "images",
                                "audio", "tools", ".github", "digest")]
        for f in files:
            if not f.endswith(".html"):
                continue
            rel = os.path.relpath(os.path.join(base, f), ROOT)
            pages.append(Page(rel))
    return sorted(pages, key=lambda p: p.path)


def sitemap_urls():
    p = os.path.join(ROOT, "sitemap.xml")
    if not os.path.exists(p):
        return {}, False
    s = open(p, encoding="utf-8").read()
    out = {}
    for blk in re.findall(r"(?s)<url>(.*?)</url>", s):
        loc = re.search(r"<loc>(.*?)</loc>", blk)
        if not loc:
            continue
        lm = re.search(r"<lastmod>(.*?)</lastmod>", blk)
        out[loc.group(1).strip()] = lm.group(1).strip() if lm else None
    return out, True


def canonical_forms(path):
    """Every URL that legitimately names this file, best spelling first.

    index.html in a folder is served at both /folder/ and /folder/index.html,
    so a canonical pointing at either is right.
    """
    url = SITE + "/" + path.replace(os.sep, "/")
    if path.replace(os.sep, "/").endswith("index.html"):
        folder = url[: -len("index.html")]
        return [folder, url]
    return [url]


def url_to_path(url):
    """Map a sitemap URL back to the file that serves it."""
    p = url.replace(SITE, "").lstrip("/")
    if p == "" or p.endswith("/"):
        p += "index.html"
    return p


def audit(pages, rep):
    live = [p for p in pages if not p.noindex and not p.redirect]
    by_title = defaultdict(list)
    by_desc = defaultdict(list)

    for p in live:
        # ---- h1 ------------------------------------------------------------
        real_h1 = [h for h in p.h1s if h]
        if not p.h1s:
            rep.add("high", "h1-missing", p.url,
                    "no <h1> on the page at all",
                    "add one carrying the phrase this page should rank for")
        elif not real_h1:
            rep.add("high", "h1-empty", p.url,
                    "<h1> present but empty — the tag is there with nothing in it",
                    "fill it in; an empty h1 is the same as none to a crawler")
        elif len(real_h1) > 1:
            rep.add("low", "h1-multiple", p.url,
                    "%d <h1> elements: %s" % (len(real_h1), " | ".join(real_h1[:3])),
                    "keep one; the rest should be h2")

        # ---- title ---------------------------------------------------------
        if not p.title:
            rep.add("high", "title-missing", p.url, "no <title>",
                    "every indexable page needs one")
        else:
            by_title[p.title.lower()].append(p.url)
            if len(p.title) > TITLE_MAX:
                rep.add("low", "title-long", p.url,
                        "%d chars, Google shows about %d" % (len(p.title), TITLE_MAX),
                        "front-load the important words so the truncation is harmless")
            elif len(p.title) < TITLE_MIN:
                rep.add("medium", "title-short", p.url,
                        "only %d chars: %r" % (len(p.title), p.title),
                        "say what the page is and where it applies")

        # ---- description ---------------------------------------------------
        if not p.description:
            rep.add("medium", "desc-missing", p.url, "no meta description",
                    "Google writes its own when this is absent, usually worse")
        else:
            by_desc[p.description.lower()].append(p.url)
            if len(p.description) > DESC_MAX:
                rep.add("low", "desc-long", p.url,
                        "%d chars, about %d survive" % (len(p.description), DESC_MAX), None)
            elif len(p.description) < DESC_MIN:
                rep.add("low", "desc-short", p.url,
                        "%d chars — room to say more" % len(p.description), None)

        # ---- body ----------------------------------------------------------
        floor = THIN_WORDS_GENERATED if p.generated else THIN_WORDS
        if p.words < floor:
            rep.add("high" if not p.generated else "medium", "thin", p.url,
                    "%d words of visible text (floor %d)" % (p.words, floor),
                    "a page this thin will not outrank anything competitive")

        # ---- canonical -----------------------------------------------------
        if not p.canonical:
            rep.add("medium", "canonical-missing", p.url, "no canonical link",
                    "protects against the same page being reachable two ways")
        else:
            # A directory index may canonicalise either to the folder or to the
            # file -- /bands/ and /bands/index.html are the same page and both
            # spellings are correct. Only flag a canonical pointing somewhere
            # genuinely else, which is the case that quietly hands a page's
            # ranking to another URL.
            for want in canonical_forms(p.path):
                if p.canonical.rstrip("/") == want.rstrip("/"):
                    break
            else:
                rep.add("high", "canonical-wrong", p.url,
                        "points at %s" % p.canonical,
                        "should be %s, or this page hands its ranking elsewhere"
                        % canonical_forms(p.path)[0])

        # ---- images --------------------------------------------------------
        noalt = [a for a in p.imgs if not re.search(r'\balt\s*=', a)]
        if noalt:
            rep.add("low", "img-no-alt", p.url,
                    "%d of %d <img> without alt" % (len(noalt), len(p.imgs)), None)

        # ---- structured data ------------------------------------------------
        for d in p.jsonld:
            if "_broken" in d:
                rep.add("high", "jsonld-broken", p.url,
                        "structured data does not parse: %s" % d["_broken"],
                        "Google discards the whole block when this happens")

    # ---- duplicates across pages --------------------------------------------
    for title, urls in by_title.items():
        if len(urls) > 1:
            rep.add("medium", "title-duplicate", ", ".join(sorted(urls)[:4]),
                    "%d pages share the title %r" % (len(urls), title[:60]),
                    "they compete with each other for the same query")
    for desc, urls in by_desc.items():
        if len(urls) > 1 and len(urls) < 20:
            rep.add("low", "desc-duplicate", ", ".join(sorted(urls)[:4]),
                    "%d pages share a meta description" % len(urls), None)

    return live


def audit_links(pages, rep):
    have = {p.path for p in pages}
    files = set()
    for base, _d, fs in os.walk(ROOT):
        for f in fs:
            files.add(os.path.relpath(os.path.join(base, f), ROOT).replace(os.sep, "/"))

    inbound = defaultdict(set)
    for p in pages:
        if p.noindex:
            continue
        for href in p.links:
            if href.startswith(("http", "mailto:", "tel:", "#", "javascript:")):
                continue
            target = href.split("#")[0].split("?")[0].lstrip("/")
            if not target:
                target = "index.html"
            if target.endswith("/"):
                target += "index.html"
            if target not in files and target not in have:
                rep.add("medium", "link-broken", p.url,
                        "links to /%s which does not exist" % target, None)
            else:
                inbound[target].add(p.path)

    # Orphans: indexable, in the sitemap, but nothing links to them. Google
    # follows links; a page only a sitemap knows about is a page it half-knows.
    smap, _ = sitemap_urls()
    for p in pages:
        if p.noindex or p.redirect or p.path == "index.html":
            continue
        if SITE + ("/" if p.path == "index.html" else "/" + p.path) not in smap:
            continue
        if not inbound.get(p.path):
            rep.add("medium", "orphan", p.url,
                    "in the sitemap but no page on the site links to it",
                    "link it from somewhere relevant, or drop it from the sitemap")


def audit_sitemap(pages, rep):
    smap, exists = sitemap_urls()
    if not exists:
        rep.add("high", "sitemap-missing", "/sitemap.xml", "no sitemap.xml", None)
        return

    listed = set(smap)
    for p in pages:
        url = SITE + ("/" if p.path == "index.html" else "/" + p.path)
        if p.noindex or p.redirect:
            if url in listed:
                rep.add("high", "sitemap-noindex", p.url,
                        "in the sitemap but %s" % ("noindex" if p.noindex else "a redirect"),
                        "a sitemap should only list pages you want indexed")
        elif url not in listed:
            rep.add("medium", "sitemap-absent", p.url,
                    "indexable but not in the sitemap",
                    "add it, or mark it noindex if it is not meant to be found")

    for url in listed:
        path = url_to_path(url)
        if not os.path.exists(os.path.join(ROOT, path)):
            rep.add("high", "sitemap-404", url,
                    "in the sitemap but no such file — a 404 for the crawler", None)

    dated = [d for d in smap.values() if d]
    if len(dated) < len(smap):
        rep.add("low", "sitemap-lastmod", "/sitemap.xml",
                "%d of %d entries have no <lastmod>" % (len(smap) - len(dated), len(smap)),
                "lastmod is the one sitemap field Google still acts on")


def audit_shape(pages, rep):
    """Where the site's weight sits, which is a strategy question, not a bug."""
    live = [p for p in pages if not p.noindex and not p.redirect]
    bands = [p for p in live if p.path.startswith("bands/") and "index" not in p.path]
    cities = [p for p in live if p.path.startswith("shows/")]
    if bands and cities and len(bands) > len(cities) * 8:
        rep.add("medium", "shape", "/bands/ vs /shows/",
                "%d band pages against %d city/venue pages" % (len(bands), len(cities)),
                "single-band queries are tiny; city queries are where the volume is")

    thin = [p for p in live if p.words < THIN_WORDS]
    if live and len(thin) > len(live) * 0.6:
        rep.add("medium", "shape", "whole site",
                "%d of %d indexable pages are under %d words"
                % (len(thin), len(live), THIN_WORDS),
                "Google judges site quality partly on what you submit in bulk")


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on", choices=["high", "medium", "low"], default=None,
                    help="exit non-zero if anything at this severity or worse is found")
    args = ap.parse_args()

    pages = collect_pages()
    rep = Report()
    live = audit(pages, rep)
    audit_links(pages, rep)
    audit_sitemap(pages, rep)
    audit_shape(pages, rep)

    items = rep.sorted()

    if args.json:
        print(json.dumps({
            "pages": len(pages), "indexable": len(live),
            "counts": {s: sum(1 for i in items if i["severity"] == s)
                       for s in ("high", "medium", "low")},
            "findings": items,
        }, indent=2))
    else:
        counts = {s: sum(1 for i in items if i["severity"] == s)
                  for s in ("high", "medium", "low")}
        print("SEO audit — %d pages, %d indexable" % (len(pages), len(live)))
        print("%d high · %d medium · %d low\n" % (counts["high"], counts["medium"], counts["low"]))
        last = None
        for i in items:
            if i["severity"] != last:
                print("\n%s\n%s" % (i["severity"].upper(), "-" * len(i["severity"])))
                last = i["severity"]
            print("  [%s] %s" % (i["check"], i["where"]))
            print("      %s" % i["detail"])
            if i["fix"]:
                print("      → %s" % i["fix"])
        if not items:
            print("nothing found.")

    if args.fail_on:
        limit = SEVERITY[args.fail_on]
        if any(SEVERITY[i["severity"]] <= limit for i in items):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
