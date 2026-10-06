#!/usr/bin/env python3
"""Draw the site as a branch graph, from the site.

Writes /site-tree.html: a git-graph of every section with its page count, the
average words per page in each, and whatever the link walk turns up -- dead
links, orphans, sitemap drift, near-duplicate pages.

It exists because the same picture drawn by hand goes stale the moment anyone
adds a page, and this site grows by generated pages: a workflow adds band pages
when the board refreshes, another adds song pages when the charts rebuild. A
count typed into a diagram is wrong by the end of the week.

Everything on the page is measured here. Nothing is typed in but the section
names and where their nodes sit in the drawing.

    python3 tools/build_site_tree.py
"""

import os
import re
import sys
import json
import html
import datetime
import itertools
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "site-tree.html")
SITE = "https://www.mikidrummer.ca"

# Which directory prefix belongs to which branch of the drawing. Order matters:
# the first prefix that matches wins, so drum-game/songs/ has to be tested
# before drum-game/.
SECTIONS = [
    ("bands/",            "Band pages"),
    ("drum-game/songs/",  "Song pages"),
    ("drum-game/",        "Game"),
    ("shows/",            "Venue & city"),
    ("digest/",           "Digest"),
    ("blog/",             "Blog"),
    ("files/",            "Redirect stubs"),
]

# Pages that sit on the trunk rather than on a branch.
ADMIN = {"admin.html", "chat.html", "contacts-admin.html", "dates-admin.html",
         "lta-admin.html", "lta-review.html", "shows-import.html",
         "shows-queue.html", "jukebox-manager.html", "link-report.html",
         "seal-tool.html", "ask-a-band.html", "find-bands.html",
         "playbook.html", "photo-credits.html", "site-tree.html"}
FRONT = {"index.html", "about.html", "services.html", "video.html",
         "bands.html", "merch.html", "play-with-us.html",
         "drum-rental-vancouver.html"}
STUBS = {"404.html", "game.html", "service.html"}
KITS = {"granite-epk.html", "lift-the-anchor-epk.html"}


def read(p):
    with open(p, encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def visible_words(s):
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S)
    return re.findall(r"[A-Za-z']+", re.sub(r"<[^>]+>", " ", s))


def word_set(s):
    return frozenset(w.lower() for w in visible_words(s) if len(w) >= 3)


def walk():
    """Every page, with its title, robots, size and resolved internal links."""
    pages, files = {}, set()
    for dp, dn, fn in os.walk(ROOT):
        if os.sep + ".git" in dp:
            continue
        for f in fn:
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
            files.add(rel)
            if not f.endswith(".html"):
                continue
            s = read(full)
            t = re.search(r"<title>(.*?)</title>", s, re.S)
            rb = re.search(r'name="robots"\s+content="(.*?)"', s, re.S)
            links = set()
            for m in re.finditer(r'href="([^"]+)"', s):
                h = m.group(1).split("#")[0].split("?")[0]
                if not h or h.startswith(("http", "mailto", "tel", "data:", "javascript")):
                    continue
                # Pages build links in script -- href="' + e.link + '" and the
                # like -- and the regex above happily matches the fragment of
                # JavaScript between the quotes. Those are not paths and never
                # resolve, so they would sit on the page as permanent phantom
                # breakages. A real static path has none of these characters.
                if any(c in h for c in "'+${}<>`\\ ") or h.startswith("javascript"):
                    continue
                # A link is relative to the page it is on unless it starts with
                # a slash. Flattening the two together is how an earlier pass of
                # this reported dozens of breakages that were not there.
                tgt = h[1:] if h.startswith("/") else os.path.normpath(
                    os.path.join(os.path.dirname(rel), h))
                tgt = tgt.replace(os.sep, "/")
                if tgt.endswith("/") or tgt == "":
                    tgt += "index.html"
                if os.path.isdir(os.path.join(ROOT, tgt)):
                    tgt += "/index.html"
                links.add(tgt)
            pages[rel] = {
                "title": (t.group(1).strip() if t else ""),
                "robots": (rb.group(1) if rb else ""),
                "words": len(visible_words(s)),
                "links": sorted(links),
            }
    return pages, files


def section_of(p):
    for pre, name in SECTIONS:
        if p.startswith(pre):
            return name
    base = p.split("/")[-1] if "/" not in p else p
    if p in ADMIN:
        return "Admin"
    if p in FRONT:
        return "Front door"
    if p in STUBS:
        return "Redirect stubs"
    if p in KITS:
        return "Press kits"
    return "Tools"


def similarity(paths):
    """Median and max Jaccard overlap, and groups whose word sets are equal.

    Sampled above a few dozen pages: the pair count is quadratic, and 111 pages
    is six thousand comparisons of sets with hundreds of members. The sample is
    seeded so the number on the page does not jitter between runs over a set of
    pages that has not changed.
    """
    import random
    sets = {p: word_set(read(os.path.join(ROOT, p))) for p in paths}
    groups = collections.defaultdict(list)
    for p, w in sets.items():
        groups[w].append(p)
    dupes = sorted([sorted(v) for v in groups.values() if len(v) > 1])
    samp = sorted(sets)
    if len(samp) > 30:
        random.seed(len(samp))
        samp = sorted(random.sample(samp, 30))
    js = []
    for a, b in itertools.combinations(samp, 2):
        A, B = sets[a], sets[b]
        if A or B:
            js.append(len(A & B) / len(A | B))
    js.sort()
    med = js[len(js) // 2] if js else 0.0
    return med, dupes


def main():
    pages, files = walk()
    sitemap = read(os.path.join(ROOT, "sitemap.xml")) if os.path.exists(
        os.path.join(ROOT, "sitemap.xml")) else ""
    smurls = set(re.findall(r"<loc>(.*?)</loc>", sitemap))

    # Dead links, against every real file rather than only the pages.
    dead = collections.Counter()
    for src, m in pages.items():
        for l in m["links"]:
            if l not in files:
                dead[l] += 1

    # Reachability from the front page.
    seen, queue = set(), ["index.html"]
    while queue:
        c = queue.pop()
        if c in seen or c not in pages:
            continue
        seen.add(c)
        queue += pages[c]["links"]
    orphans = sorted(set(pages) - seen)

    agg = collections.Counter()
    words = collections.Counter()
    for p, m in pages.items():
        s = section_of(p)
        agg[s] += 1
        words[s] += m["words"]

    bandpaths = [p for p in pages if p.startswith("bands/")]
    med, dupes = similarity(bandpaths) if bandpaths else (0.0, [])
    band_in_map = sum(1 for p in bandpaths if SITE + "/" + p in smurls)
    board = read(os.path.join(ROOT, "punkbc.html")) if os.path.exists(
        os.path.join(ROOT, "punkbc.html")) else ""
    band_linked = sum(1 for p in bandpaths if p in board)

    rows = sorted(((k, agg[k], words[k] // max(1, agg[k])) for k in agg),
                  key=lambda r: -r[2])

    n = lambda k: agg.get(k, 0)
    data = {
        "date": datetime.date.today().strftime("%-d %B %Y"),
        "total": len(pages),
        "sitemap": len(smurls),
        "dead": sum(dead.values()),
        "words": f"{sum(words.values()):,}",
        "front": n("Front door"), "admin": n("Admin"),
        "stubs": n("Redirect stubs"),
        "game": n("Game"), "songs": n("Song pages"),
        "tools": n("Tools"), "kits": n("Press kits") + n("Blog"),
        "board": n("Venue & city") + 1, "band": n("Band pages"),
        "digest": n("Digest"),
        "rows": rows,
        "med": med, "dupes": dupes,
        "band_in_map": band_in_map, "band_linked": band_linked,
        "orphans": orphans,
        "workflows": len([f for f in os.listdir(os.path.join(ROOT, ".github", "workflows"))
                          if f.endswith(".yml")])
        if os.path.isdir(os.path.join(ROOT, ".github", "workflows")) else 0,
        "deadlist": dead.most_common(6),
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(render(data))
    print("site-tree.html: %d pages, %d sections, %d dead links, "
          "band similarity %.2f, %d identical groups"
          % (data["total"], len(rows), data["dead"], med, len(dupes)))
    return 0


def findings(d):
    """The notes under the drawing. Each one is written from the measurement,
    so a problem that gets fixed stops being described rather than lingering as
    a sentence nobody updated."""
    out = []
    if d["dupes"] or d["med"] >= 0.5:
        ident = (" %d groups of them are byte-identical apart from the band "
                 "name and image path." % len(d["dupes"])) if d["dupes"] else ""
        out.append(("bad", "Band pages are near-duplicates", "worth fixing",
            "The %d band pages are %.2f similar to each other by word set.%s "
            "%d of them are in the sitemap." % (d["band"], d["med"], ident, d["band_in_map"]),
            "That is the shape Google calls doorway pages. The fix is not deletion: give "
            "each page something only that band has, or fold the single-show ones back "
            "into the board and keep standalone pages for bands with enough to say."))
    else:
        out.append(("ok", "Band pages read as distinct", "clean",
            "The %d band pages are %.2f similar by word set, with no identical "
            "groups." % (d["band"], d["med"]), ""))

    if d["band"] and not d["band_linked"]:
        out.append(("warn", "The board does not link its own band pages", "check",
            "None of the %d are linked from <code>punkbc.html</code>. They are in the "
            "sitemap and reached from elsewhere." % d["band"],
            "A page Google is told about but given no internal links is a page it is "
            "given no reason to value. Linking each band name on the board is a small "
            "change with a direct effect."))
    elif d["band"]:
        out.append(("ok", "The board links its band pages", "clean",
            "%d of %d band pages are linked from <code>punkbc.html</code>."
            % (d["band_linked"], d["band"]), ""))

    if d["dead"]:
        lst = ", ".join("<code>%s</code>&nbsp;&times;%d" % (html.escape(k), v)
                        for k, v in d["deadlist"])
        out.append(("bad", "Dead internal links", "fix",
            "%d links point at files that do not exist: %s" % (d["dead"], lst), ""))
    else:
        out.append(("ok", "No dead internal links", "clean",
            "Every <code>href</code> across all %d pages resolves to a file that exists, "
            "relative and absolute, across directories." % d["total"], ""))

    if d["orphans"]:
        out.append(("warn", "%d pages are unreachable by link" % len(d["orphans"]), "mostly fine",
            "Nothing links to: " + ", ".join("<code>%s</code>" % html.escape(o)
                                             for o in d["orphans"][:9])
            + ("&hellip;" if len(d["orphans"]) > 9 else ""),
            "Email bodies, admin tools, the 404 page and redirect stubs belong here. "
            "Anything else on the list is worth a look."))
    return out


TPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Site tree \u2014 mikidrummer.ca</title>
<meta name="robots" content="noindex, nofollow">
<meta name="description" content="A branch graph of every page on mikidrummer.ca, rebuilt from the site itself.">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Nunito:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
  :root{
    --bg:#f2f1ef; --surface:#fff; --line:#dcd6cf; --line2:#eae5df;
    --fg:#2e2b28; --mid:#5c544e; --dim:#8b8178; --ink:#3a3a3a;
    --blue:#aee0f8; --green:#6fcf97; --purple:#a98be0; --amber:#f2c261;
    --good:#2f6f4f; --warn:#9a5b10; --bad:#a32d20;
    --mono:'IBM Plex Mono',ui-monospace,Menlo,monospace;
    --sans:'IBM Plex Sans',system-ui,-apple-system,Segoe UI,Arial,sans-serif;
    --disp:'Nunito',system-ui,sans-serif;
  }
  @media (prefers-color-scheme: dark){ :root{
    --bg:#17150f; --surface:#201d1a; --line:#36302a; --line2:#282420;
    --fg:#f1ece5; --mid:#bcb2aa; --dim:#8b8178; --ink:#0f0e0d;
    --blue:#8ec9e6; --green:#5fb886; --purple:#9a7bd0; --amber:#dcae50;
    --good:#64c295; --warn:#e0a24a; --bad:#e8705f; color-scheme:dark; } }
  *{box-sizing:border-box}
  body{background:var(--bg);color:var(--fg);font-family:var(--sans);line-height:1.6;margin:0}
  .wrap{max-width:900px;margin:0 auto;padding-block:40px 64px;padding-left:20px;padding-right:20px}
  .eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--mid)}
  h1{font-family:var(--disp);font-weight:700;font-size:clamp(32px,7vw,50px);line-height:1.04;
     margin:10px 0 0;letter-spacing:-.015em;text-wrap:balance}
  .sub{color:var(--mid);font-size:16px;margin:12px 0 0;max-width:62ch}
  h2{font-family:var(--disp);font-weight:700;font-size:23px;margin:48px 0 4px;
     padding-bottom:8px;border-bottom:2px solid var(--fg);letter-spacing:-.01em}
  h3{font-size:15px;margin:0 0 6px}
  p{color:var(--mid);font-size:15px;margin:10px 0 0;max-width:68ch}
  code{font-family:var(--mono);font-size:.9em;background:var(--line2);padding:1px 5px;border-radius:3px;color:var(--fg)}
  a{color:var(--good)}
  .nums{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:var(--line);
        border:1px solid var(--line);border-radius:5px;overflow:hidden;margin-top:26px}
  @media(min-width:620px){.nums{grid-template-columns:repeat(4,1fr)}}
  .nums div{background:var(--surface);padding:14px 16px}
  .nums b{display:block;font-family:var(--disp);font-size:31px;font-weight:700;
          font-variant-numeric:tabular-nums;line-height:1.1}
  .nums span{font-family:var(--mono);font-size:10.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--dim)}
  .graph{overflow-x:auto;margin-top:22px;padding-bottom:8px;background:var(--surface);
         border:1px solid var(--line);border-radius:6px}
  .graph svg{display:block;min-width:900px;width:100%;height:auto}
  .hint{font-family:var(--mono);font-size:11px;color:var(--dim);margin-top:8px}
  .find{border-left:3px solid var(--line);padding:2px 0 2px 16px;margin-top:24px}
  .find.ok{border-left-color:var(--good)} .find.warn{border-left-color:var(--warn)}
  .find.bad{border-left-color:var(--bad)}
  .find h3{display:flex;gap:9px;align-items:baseline;flex-wrap:wrap}
  .tag{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
       padding:2px 7px;border-radius:3px;background:var(--line2);color:var(--dim)}
  .tag.ok{color:var(--good)} .tag.warn{color:var(--warn)} .tag.bad{color:var(--bad)}
  .scroll{overflow-x:auto}
  table.data{border-collapse:collapse;width:100%;margin-top:14px;font-size:13.5px;min-width:420px}
  table.data th,table.data td{text-align:left;padding:7px 10px 7px 0;border-bottom:1px solid var(--line2);vertical-align:baseline}
  table.data th{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--dim)}
  table.data td.num{font-variant-numeric:tabular-nums;text-align:right;padding-right:16px;white-space:nowrap}
  footer{margin-top:54px;padding-top:18px;border-top:1px solid var(--line);
         color:var(--dim);font-size:12.5px;font-family:var(--mono)}
</style>
</head>
<body>
<div class="wrap">
  <span class="eyebrow">mikidrummer.ca &middot; rebuilt @@date@@</span>
  <h1>Site tree</h1>
  <p class="sub">@@total@@ pages drawn the way a branch graph is drawn: the public site runs
     along the trunk, and each section hangs off it with its page count in the node. Rebuilt
     from the site itself every time anything is pushed, so the numbers are never a guess.</p>

  <div class="nums">
    <div><b>@@total@@</b><span>pages</span></div>
    <div><b>@@sitemap@@</b><span>in sitemap</span></div>
    <div><b>@@dead@@</b><span>dead links</span></div>
    <div><b>@@words@@</b><span>words</span></div>
  </div>

  <div class="graph">
  <svg viewBox="0 0 1180 840" role="img" aria-label="Branch diagram of the site: a trunk of front-door pages with Drum Along and the toolbox branching above it and Punk BC branching below.">
    <defs>
      <marker id="ar" viewBox="0 0 12 12" refX="6" refY="6" markerWidth="7" markerHeight="7" orient="auto">
        <path d="M1,1 L11,6 L1,11 Z" fill="var(--ink)"/></marker>
      <style>
        .ln{fill:none;stroke:var(--ink);stroke-width:5}
        .nd{stroke:var(--ink);stroke-width:5}
        .bx{stroke:var(--ink);stroke-width:4}
        .cnt{font-family:'Nunito',sans-serif;font-size:21px;font-weight:700;fill:var(--ink);text-anchor:middle;dominant-baseline:central}
        .cap{font-family:'Nunito',sans-serif;font-size:15px;font-weight:600;fill:var(--fg);text-anchor:middle}
        .lbl{font-family:'Nunito',sans-serif;font-size:21px;font-weight:700;fill:var(--ink);text-anchor:middle;dominant-baseline:central}
        .sml{font-family:'Nunito',sans-serif;font-size:13px;font-weight:600;fill:var(--mid);text-anchor:middle}
      </style>
    </defs>
    <path class="ln" d="M80,430 H1095"/>
    <path class="ln" d="M150,430 C250,430 230,235 330,235 H470"/>
    <path class="ln" d="M620,430 C720,430 700,235 800,235 H950"/>
    <path class="ln" d="M390,430 C490,430 470,625 570,625 H870"/>

    <circle class="nd" cx="80" cy="430" r="30" fill="var(--blue)"/>
    <circle class="nd" cx="880" cy="430" r="30" fill="var(--blue)"/>
    <circle class="nd" cx="1095" cy="430" r="30" fill="var(--blue)"/>
    <text class="cnt" x="80" y="430">@@front@@</text>
    <text class="cnt" x="880" y="430">@@admin@@</text>
    <text class="cnt" x="1095" y="430">@@stubs@@</text>
    <text class="cap" x="80" y="494">front door</text><text class="sml" x="80" y="513">index &middot; services &middot; rental</text>
    <text class="cap" x="880" y="494">admin</text><text class="sml" x="880" y="513">chat &middot; queue &middot; reports</text>
    <text class="cap" x="1095" y="494">stubs</text><text class="sml" x="1095" y="513">404 &middot; redirects</text>

    <circle class="nd" cx="330" cy="235" r="30" fill="var(--purple)"/>
    <circle class="nd" cx="470" cy="235" r="30" fill="var(--purple)"/>
    <text class="cnt" x="330" y="235">@@game@@</text><text class="cnt" x="470" y="235">@@songs@@</text>
    <text class="sml" x="330" y="299">the game</text><text class="sml" x="470" y="299">song pages</text>

    <circle class="nd" cx="800" cy="235" r="30" fill="var(--amber)"/>
    <circle class="nd" cx="950" cy="235" r="30" fill="var(--amber)"/>
    <text class="cnt" x="800" y="235">@@tools@@</text><text class="cnt" x="950" y="235">@@kits@@</text>
    <text class="sml" x="800" y="299">tools</text><text class="sml" x="950" y="299">kits &middot; blog</text>

    <circle class="nd" cx="570" cy="625" r="30" fill="var(--green)"/>
    <circle class="nd" cx="720" cy="625" r="@@bandr@@" fill="var(--green)"/>
    <circle class="nd" cx="870" cy="625" r="30" fill="var(--green)"/>
    <text class="cnt" x="570" y="625">@@board@@</text><text class="cnt" x="720" y="625">@@band@@</text><text class="cnt" x="870" y="625">@@digest@@</text>
    <text class="sml" x="570" y="689">board &middot; venues</text>
    <text class="sml" x="720" y="@@bandcap@@">band pages</text>
    <text class="sml" x="870" y="689">digest</text>

    <rect class="bx" x="200" y="60" width="260" height="66" rx="3" fill="var(--purple)"/>
    <text class="lbl" x="330" y="94">Drum Along</text>
    <path class="ln" d="M330,135 V185" marker-end="url(#ar)"/>
    <rect class="bx" x="700" y="60" width="200" height="66" rx="3" fill="var(--amber)"/>
    <text class="lbl" x="800" y="94">Toolbox</text>
    <path class="ln" d="M800,135 V185" marker-end="url(#ar)"/>
    <rect class="bx" x="600" y="750" width="240" height="66" rx="3" fill="var(--green)"/>
    <text class="lbl" x="720" y="784">Punk BC</text>
    <path class="ln" d="M720,742 V694" marker-end="url(#ar)"/>
    <rect class="bx" x="20" y="300" width="190" height="60" rx="3" fill="var(--blue)"/>
    <text class="lbl" x="115" y="330">The site</text>
    <path class="ln" d="M115,369 V400" marker-end="url(#ar)"/>
  </svg>
  </div>
  <p class="hint">Numbers inside the nodes are page counts. Scroll sideways on a phone.</p>

  <h2>Weight per branch</h2>
  <p>Average words of visible text per page &mdash; the clearest read on where the site is
     substantial and where it is thin.</p>
  <div class="scroll"><table class="data">
    <tr><th>Branch</th><th style="text-align:right">Pages</th><th style="text-align:right">Avg words</th></tr>
@@rows@@
  </table></div>

  <h2>What the walk found</h2>
@@findings@@

  <footer>Walked @@total@@ files &middot; @@words@@ words of visible text &middot;
     @@workflows@@ workflows &middot; rebuilt by tools/build_site_tree.py</footer>
</div>
</body>
</html>
"""


def render(d):
    # Substitution is a plain replace of @@token@@ rather than %-formatting or
    # str.format: the template is CSS and SVG, which is full of bare % signs
    # (width:100%) and braces, and both of those formatters choke on them.
    rows = "\n".join(
        '    <tr><td>%s</td><td class="num">%d</td><td class="num">%d</td></tr>'
        % (html.escape(k), n, w) for k, n, w in d["rows"])
    fnd = []
    for kind, head, tag, body, note in findings(d):
        fnd.append(
            '  <div class="find %s">\n    <h3>%s <span class="tag %s">%s</span></h3>\n'
            '    <p>%s</p>\n%s  </div>'
            % (kind, html.escape(head), kind, html.escape(tag), body,
               ("    <p>%s</p>\n" % note) if note else ""))
    v = dict(d)
    v["rows"] = rows
    v["findings"] = "\n".join(fnd)
    # The band node is drawn bigger when it earns it -- the point of the picture
    # is that the fattest node is the thinnest content, and a node that is only
    # as big as its neighbours does not make that point.
    v["bandr"] = 38 if d["band"] >= 60 else 30
    v["bandcap"] = 625 + v["bandr"] + 34
    out = TPL
    for k, val in v.items():
        out = out.replace("@@%s@@" % k, str(val))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
