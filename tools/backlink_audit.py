#!/usr/bin/env python3
"""Who already links to mikidrummer.ca, and who plainly ought to.

The site's best backlink asset is not the drummer -- it is the fact that it
publishes pages *about other people*. The Punk BC board lists a hundred-odd
bands and every venue's shows; the two press kits belong to bands with their
own followings; the tools get used by people who have websites of their own.
Every one of those is a relationship where a link back is a reasonable thing
to ask for, and most of them have never been asked.

This crawls the sites of the bands, venues and labels the site already
features and reports which of them link back. What comes out is an outreach
list in priority order, which is the part that is usually missing: it is easy
to know you want backlinks and hard to know whose door to knock on first.

Two things it deliberately does not do:

  * Guess at the whole backlink profile. Search Console's Links report is
    authoritative, free, and already the site owner's. Crawling the web to
    approximate it badly would be worse than exporting it.
  * Count links from social profiles as wins. Instagram, Linktree and
    Bandcamp are all nofollow; they are worth having for traffic and they
    are worth nothing for ranking, and conflating the two is how people
    convince themselves an afternoon was well spent.

This container cannot reach any of these hosts, so it runs on a runner:
see .github/workflows/backlink-audit.yml.

    python3 tools/backlink_audit.py --self-test
    python3 tools/backlink_audit.py [--limit N] [--dump]
"""

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from weblinks import is_real_site  # noqa: E402

# Both spellings, with and without the www, plus the bare apex. A link is a
# link whichever way it was typed.
US = re.compile(r"https?://(?:www\.)?mikidrummer\.ca", re.I)

UA = {"User-Agent": "Mozilla/5.0 (mikidrummer-backlink-audit/1.0; "
                    "+https://www.mikidrummer.ca)"}
TIMEOUT = 25
CTX = ssl.create_default_context()

# Real places, but ones where a link is nofollow and therefore passes no
# ranking signal. Still worth listing, never worth counting as a win.
NOFOLLOW_BY_DEFAULT = re.compile(
    r"(^|\.)(instagram\.com|facebook\.com|twitter\.com|x\.com|tiktok\.com|"
    r"linktr\.ee|bandcamp\.com|spotify\.com|youtube\.com|soundcloud\.com|"
    r"songkick\.com|bandsintown\.com|reddit\.com|apple\.com|"
    # Smart-link redirectors. They are a real destination for a fan and an
    # empty one for this: the page is a bounce to somewhere else and will
    # never carry a link to anybody.
    r"lnk\.to|ffm\.to|orcd\.co|smarturl\.it|li\.sten\.to|distrokid\.com)$", re.I)


def host(url):
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def worth_crawling(url):
    """A site where a link back would actually be worth having.

    Two filters. is_real_site throws out the namespaces and script hosts that
    the contact finder used to store as band websites. The second throws out
    the social platforms -- not because they do not matter, but because
    crawling them tells you nothing: the link is nofollow whichever way the
    answer comes back, so the request is wasted either way.
    """
    if not is_real_site(url):
        return False
    return not NOFOLLOW_BY_DEFAULT.search(host(url))


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
        blob = r.read(900_000)
        enc = r.headers.get_content_charset() or "utf-8"
        return r.geturl(), blob.decode(enc, "replace")


def links_to_us(html):
    """Every link to mikidrummer.ca on the page, with how it was marked up.

    rel matters more than the presence of the link: a rel="nofollow" credit
    in a footer is a courtesy, not a ranking signal, and the difference is
    the whole reason to look rather than assume.
    """
    out = []
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", html, re.I | re.S):
        attrs, text = m.group(1), m.group(2)
        href = re.search(r'href\s*=\s*["\']([^"\']+)["\']', attrs, re.I)
        if not href or not US.search(href.group(1)):
            continue
        rel = re.search(r'rel\s*=\s*["\']([^"\']*)["\']', attrs, re.I)
        out.append({
            "href": href.group(1),
            "anchor": re.sub(r"\s+", " ", re.sub("<[^>]+>", "", text)).strip()[:80],
            "rel": (rel.group(1).lower() if rel else ""),
        })
    return out


def mentions_us(html):
    """A bare mention with no link -- the easiest ask there is.

    Someone who has already written the site's name has already decided it is
    worth naming. Asking them to make it a link is a smaller favour than
    asking a stranger for a link, and it converts far better.
    """
    stripped = re.sub(r"<a\b[^>]*>.*?</a>", " ", html, flags=re.I | re.S)
    return bool(re.search(r"mikidrummer|miki\s+drummer|punk\s*bc", stripped, re.I))


def targets():
    """Everyone the site already gives something to.

    Ranked by what a link from them would be worth, which is roughly: a venue
    that lists shows all year, then a label, then a band with its own domain,
    then everything else.
    """
    out, seen = [], set()

    def add(name, url, kind, weight, email="", why=""):
        h = host(url)
        if not h or h in seen or not worth_crawling(url):
            return
        seen.add(h)
        out.append({"name": name, "url": url, "kind": kind, "weight": weight,
                    "email": email, "why": why})

    path = os.path.join(ROOT, "data", "link-targets.json")
    if os.path.exists(path):
        with open(path) as fh:
            curated = json.load(fh)
        for t in curated.get("targets", []):
            add(t["name"], t["url"], t.get("kind", "partner"),
                t.get("weight", 5), t.get("email", ""), t.get("why", ""))

    # Venues whose listings the board already republishes. If the board is
    # sending them anything at all, this is the most defensible ask on the
    # list, and venues keep their links up for years.
    src = os.path.join(ROOT, "data", "show-sources.json")
    if os.path.exists(src):
        with open(src) as fh:
            for s in json.load(fh).get("sources", []):
                if s.get("kind") == "jsonld":
                    add(s.get("id", "").replace("-", " ").title(), s["url"],
                        "venue", 9, why="The board republishes their listings")

    # Bands on the board. Most will have moved on or never reply; the ones
    # with a site of their own and an address on file are the ones worth the
    # typing, and this is what sorts them.
    bc = os.path.join(ROOT, "data", "band-contacts.json")
    if os.path.exists(bc):
        with open(bc) as fh:
            for b in json.load(fh).get("bands", []):
                site = ""
                for p in b.get("profiles") or []:
                    if worth_crawling(p.get("url", "")):
                        site = p["url"]
                        break
                if site:
                    add(b["band"], site, "band", 7 if b.get("email") else 5,
                        b.get("email", ""), "Listed on the Punk BC board")
    out.sort(key=lambda t: -t["weight"])
    return out


def check(t):
    rec = dict(t)
    try:
        final, html = fetch(t["url"])
        rec["status"] = "ok"
        rec["final"] = final
        found = links_to_us(html)
        rec["links"] = found
        rec["follow"] = [l for l in found if "nofollow" not in l["rel"]]
        rec["mention_only"] = (not found) and mentions_us(html)
    except urllib.error.HTTPError as e:
        rec.update(status="http %s" % e.code, links=[], follow=[], mention_only=False)
    except Exception as e:
        rec.update(status=type(e).__name__, links=[], follow=[], mention_only=False)
    return rec


def report(rows):
    have = [r for r in rows if r["follow"]]
    nofollow = [r for r in rows if r["links"] and not r["follow"]]
    mention = [r for r in rows if r["mention_only"]]
    dead = [r for r in rows if r["status"] != "ok"]
    cold = [r for r in rows if r["status"] == "ok" and not r["links"]
            and not r["mention_only"]]

    L = []
    L.append("# Backlinks\n")
    L.append("%d sites checked: **%d link back** (%d of them followed), "
             "%d name the site without linking, %d say nothing, %d unreachable.\n"
             % (len(rows), len(have) + len(nofollow), len(have),
                len(mention), len(cold), len(dead)))

    L.append("\n## Links we already have\n")
    if have:
        for r in sorted(have, key=lambda r: -r["weight"]):
            a = r["follow"][0]
            L.append("- **%s** (%s) — anchor %r  \n  %s"
                     % (r["name"], r["kind"], a["anchor"] or "(image)", r["final"]))
    else:
        L.append("_None found on the sites checked._")

    L.append("\n## Named but not linked — ask these first\n")
    L.append("_Someone who already wrote the name has already decided it is "
             "worth naming. Turning that into a link is the smallest ask on "
             "this page._\n")
    for r in sorted(mention, key=lambda r: -r["weight"]) or []:
        L.append("- **%s** (%s) — %s%s"
                 % (r["name"], r["kind"], r["url"],
                    "  ·  `%s`" % r["email"] if r["email"] else ""))
    if not mention:
        L.append("_None._")

    L.append("\n## Nofollow only\n")
    for r in nofollow:
        L.append("- **%s** — %s (rel=%r)"
                 % (r["name"], r["final"], r["links"][0]["rel"]))
    if not nofollow:
        L.append("_None._")

    L.append("\n## No link, no mention\n")
    L.append("_In weight order. A venue whose listings the board republishes "
             "is a far better use of an email than a touring act who played "
             "here once._\n")
    for r in sorted(cold, key=lambda r: -r["weight"])[:60]:
        L.append("- **%s** (%s, weight %d) — %s%s"
                 % (r["name"], r["kind"], r["weight"], r["url"],
                    "  ·  `%s`" % r["email"] if r["email"] else "  ·  _no address on file_"))

    L.append("\n## Unreachable\n")
    L.append("_Dead or blocking. A dead band site is also a dead link on our "
             "own board, so these are worth fixing in both directions._\n")
    for r in dead:
        L.append("- %s — %s (%s)" % (r["name"], r["url"], r["status"]))
    if not dead:
        L.append("_None._")
    return "\n".join(L) + "\n"


def self_test():
    fails = []

    def eq(got, want, what):
        if got != want:
            fails.append("%s: got %r want %r" % (what, got, want))

    # The junk the contact finder stored as band websites.
    for u in ["https://js.stripe.com", "https://schema.org",
              "http://www.w3.org", "http://opengraphprotocol.org",
              "http://instargam.com", "https://new.express.adobe.com"]:
        eq(worth_crawling(u), False, "reject %s" % u)

    # Real sites, worth the fetch.
    for u in ["https://alienboys.ca/", "https://rickshawtheatre.com",
              "https://brehdren.com/brehdren/", "http://themenzingers.com"]:
        eq(worth_crawling(u), True, "accept %s" % u)

    # Real, but nofollow whatever we find, so not worth a request.
    for u in ["https://www.instagram.com/x", "https://linktr.ee/x",
              "https://somebody.bandcamp.com"]:
        eq(worth_crawling(u), False, "skip social %s" % u)

    eq(worth_crawling("not a url"), False, "garbage input")
    eq(worth_crawling(""), False, "empty input")

    # Finding the link, and reading how it was marked up.
    html = ('<a href="https://www.mikidrummer.ca/">Miki Drummer</a>'
            '<a rel="noopener NOFOLLOW" href="http://mikidrummer.ca/punkbc.html">shows</a>'
            '<a href="https://example.com">other</a>')
    got = links_to_us(html)
    eq(len(got), 2, "found both links")
    eq(got[0]["anchor"], "Miki Drummer", "anchor text")
    eq(got[1]["rel"], "noopener nofollow", "rel lowercased")
    eq([l for l in got if "nofollow" not in l["rel"]][0]["href"],
       "https://www.mikidrummer.ca/", "followed link picked out")

    # An image link has no text; it is still a link.
    eq(links_to_us('<a href="https://mikidrummer.ca"><img src="x.png"></a>')[0]["anchor"],
       "", "image link has empty anchor")

    # A mention is only a mention if it is not already a link -- otherwise
    # every site that links to us would also be filed as an easy ask.
    eq(mentions_us("<p>Thanks to Miki Drummer for the fills</p>"), True, "bare mention")
    eq(mentions_us('<a href="https://www.mikidrummer.ca/">Miki Drummer</a>'), False,
       "linked name is not a mention")
    eq(mentions_us("<p>Nothing to do with us</p>"), False, "no mention")
    eq(mentions_us("<p>See the Punk BC board</p>"), True, "punkbc counts")

    for f in fails:
        print("FAIL", f)
    print("%d checks, %d failed" % (23, len(fails)))
    return 1 if fails else 0


def main():
    if "--self-test" in sys.argv:
        return self_test()

    ts = targets()
    if "--limit" in sys.argv:
        ts = ts[:int(sys.argv[sys.argv.index("--limit") + 1])]
    print("checking %d sites" % len(ts))

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(check, ts))

    if "--dump" in sys.argv:
        for r in rows:
            print("%-28s %-9s %d link(s)%s"
                  % (r["name"][:28], r["status"], len(r["links"]),
                     "  MENTION" if r["mention_only"] else ""))

    md = report(rows)
    with open(os.path.join(ROOT, "backlink-report.md"), "w") as fh:
        fh.write(md)
    with open(os.path.join(ROOT, "data", "backlinks.json"), "w") as fh:
        json.dump(rows, fh, indent=2, ensure_ascii=False)

    have = sum(1 for r in rows if r["follow"])
    print("\n%d of %d link back with a followed link; %d name us without linking"
          % (have, len(rows), sum(1 for r in rows if r["mention_only"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
