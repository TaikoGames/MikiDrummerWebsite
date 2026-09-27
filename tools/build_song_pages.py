#!/usr/bin/env python3
"""One page per charted song, under /drum-game/songs/.

WHY THESE EXIST
---------------
The game is one URL, and one URL ranks for one thing. What people actually
search is a song title or a band name -- "bound by none no other", "diera
groenlandia drums" -- and none of that was anywhere in the HTML until
recently, because the song list is built by JavaScript. A page per song puts
each title, each band, and each tempo on its own indexable URL that links
straight into the game with ?song=<slug>.

WHAT KEEPS THEM FROM BEING DOORWAY PAGES
----------------------------------------
Twelve near-identical pages spun off a template is a recognised spam pattern
and gets a site penalised, not ranked. Everything on these pages is real and
differs per song because it is read out of that song's actual chart: the
tempo the beat tracker found, the note count in each lane, the length, the
density, and a difficulty read off that density. The prose describes what is
genuinely different about playing that track -- a song at 215 BPM with a
sparse kick is a different job from one at 115 with a busy one -- and the
band paragraph is written once per band, not once per song.

If a song has no chart, it gets no page. A page about a thing that is not
there is the worst kind.

    python3 tools/build_song_pages.py
"""

import json
import os
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAPS = os.path.join(ROOT, "data", "beatmaps")
OUT = os.path.join(ROOT, "drum-game", "songs")
SITE = "https://www.mikidrummer.ca"

# Written once per band, not once per song -- the point is that the pages
# differ, and twelve copies of the same sentence is what makes them not.
BANDS = {
    "Bound By None": (
        "Bound By None are a Vancouver punk band. Miki plays drums on the "
        "recordings these charts come from, so what comes down the lanes is "
        "his own playing rather than a transcription of it."),
    "Dead Fast": (
        "Dead Fast are a Vancouver punk band with a fast, tight rhythm "
        "section — which makes their tracks some of the busier charts here. "
        "Miki drums on the recordings."),
    "Diera": (
        "Diera are a Barcelona punk band Miki drummed with. The songs are in "
        "Spanish and Catalan and they are quick, so expect high tempos and "
        "short run times."),
    "Granite": (
        "Granite are a Vancouver metal band. Heavier and slower than the punk "
        "on this list, with more room between the hits."),
    "Lift The Anchor": (
        "Lift The Anchor are a Vancouver punk band. The track charted here is "
        "a demo, so the mix is rougher than the finished records — which the "
        "detector notices."),
}


def slugify(name):
    a = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = "".join(c if c.isalnum() else "-" for c in a.lower()).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def difficulty(per_beat):
    """Read off the chart rather than assigned by hand, so it cannot drift
    away from what the chart actually does.

    Notes per BEAT, not per second. Per second makes the rating a measure of
    tempo -- a fast song looks hard and a slow one easy regardless of what is
    being played -- and once the charts were filled in properly it had a
    second problem: every one of the twelve tipped past the top threshold and
    all twelve pages read "Relentless", which is no information at all.
    Per beat, three notes is a rock beat and five is a busy one at any tempo.
    """
    if per_beat < 2.6:
        return "Steady", "room between the hits"
    if per_beat < 3.2:
        return "Busy", "few gaps once it gets going"
    if per_beat < 4.2:
        return "Fast", "close to constant"
    return "Relentless", "almost no rest in it"


def shape_of(notes, dur):
    """What this particular chart does over its length.

    Real per-song detail, computed from that song's notes: where the densest
    stretch is, where the longest breather is, and how lopsided the lanes are.
    Without something like this the twelve pages differ only in their numbers
    and read as twelve copies of one template, which is a recognised spam
    pattern rather than an SEO tactic -- measured at 0.94 text similarity
    between the closest pair before this went in.
    """
    if not notes or dur <= 0:
        return ""
    times = sorted(n["t"] for n in notes)
    # Densest ten seconds.
    win, best, best_at = 10.0, 0, 0.0
    j = 0
    for i, t in enumerate(times):
        while times[j] < t - win:
            j += 1
        if i - j + 1 > best:
            best, best_at = i - j + 1, t - win / 2
    # Longest gap with nothing in it at all.
    gaps = [(times[i + 1] - times[i], times[i]) for i in range(len(times) - 1)]
    gap, gap_at = max(gaps) if gaps else (0, 0)

    def clock(x):
        x = max(0, x)
        return "%d:%02d" % (int(x) // 60, int(x) % 60)

    bits = [("The busiest stretch is around %s — %d notes in ten seconds, "
             "against %.0f for the song as a whole."
             % (clock(best_at), best, len(times) / dur * 10))]
    if gap >= 1.2:
        bits.append("The longest breather is %.1f seconds at %s." % (gap, clock(gap_at)))
    else:
        bits.append("There is no real let-up in it: the biggest gap anywhere is %.1f seconds."
                    % gap)
    return " ".join(bits)


def load():
    """Every charted song, with its title and band from playlist.json."""
    titles = {}
    pl = json.load(open(os.path.join(ROOT, "playlist.json")))
    for s in pl.get("songs", []):
        src = s.get("src", "")
        if src.lower().endswith(".mp3"):
            titles[slugify(os.path.splitext(os.path.basename(src))[0])] = s.get("title", "")
    titles.setdefault("pony-up", "Pony Up - Granite")

    rows = []
    for fn in sorted(os.listdir(MAPS)):
        if not fn.endswith(".json") or fn == "index.json":
            continue
        slug = fn[:-5]
        m = json.load(open(os.path.join(MAPS, fn)))
        if not m.get("notes"):
            continue
        raw = titles.get(slug, slug)
        song, _, band = raw.partition(" - ")
        lanes = {}
        for n in m["notes"]:
            lanes[n["lane"]] = lanes.get(n["lane"], 0) + 1
        rows.append({
            "slug": slug, "title": song.strip() or slug, "band": band.strip(),
            "bpm": m.get("bpm", 0), "dur": m.get("duration", 0),
            "notes": len(m["notes"]), "lanes": lanes, "raw": m["notes"],
            "beats": len(m.get("beats", [])) or 1,
        })
    rows.sort(key=lambda r: (r["band"], r["title"]))
    return rows


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<script src="/js/track.js" defer></script>
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>{title} — {band} | Play the drums free</title>
<meta name="description" content="{desc}">
<meta name="robots" content="index, follow, max-image-preview:large">
<link rel="canonical" href="{site}/drum-game/songs/{slug}.html">
<meta property="og:type" content="article">
<meta property="og:url" content="{site}/drum-game/songs/{slug}.html">
<meta property="og:title" content="{title} — {band} | Play the drums free">
<meta property="og:description" content="{desc}">
<meta property="og:site_name" content="Drum Along">
<meta property="og:image" content="{site}/images/drum-game-play-punk-songs-browser.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{site}/images/drum-game-play-punk-songs-browser.png">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/images/icon-180.png">

<style>
  :root{{ --bg:#0b0c0e; --card:#131518; --edge:#2b2f34; --edge2:#3a4046;
         --dim:#7d848d; --mid:#a6adb6; --fg:#e9ebee; --hot:#e8672a; }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--fg);line-height:1.6;
       font-family:'Helvetica Neue',system-ui,Arial,sans-serif;padding:0 16px 60px}}
  .wrap{{max-width:760px;margin:0 auto}}
  a{{color:var(--hot);text-decoration:none}} a:hover{{text-decoration:underline}}
  nav{{padding:20px 0;font-size:12.5px;color:var(--dim)}}
  header{{padding:14px 0 20px;border-bottom:1px solid var(--edge)}}
  .eyebrow{{font-size:11px;letter-spacing:.3em;text-transform:uppercase;color:var(--hot);font-weight:700}}
  h1{{font-family:'Arial Black',system-ui,sans-serif;font-size:clamp(26px,5.5vw,40px);
     letter-spacing:-.02em;margin:8px 0 6px}}
  h2{{font-size:16px;margin:28px 0 8px}}
  .by{{color:var(--mid);font-size:15px}}
  p{{color:var(--mid);font-size:14.5px;margin-top:12px}}
  .btn{{display:inline-flex;align-items:center;gap:8px;background:var(--hot);border:1px solid var(--hot);
       color:#160802;border-radius:999px;padding:14px 26px;font:inherit;font-size:15px;
       font-weight:800;margin-top:22px}}
  .btn:hover{{text-decoration:none;opacity:.92}}
  .stats{{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:var(--edge);
         border:1px solid var(--edge);border-radius:12px;overflow:hidden;margin-top:22px}}
  @media(min-width:560px){{.stats{{grid-template-columns:repeat(4,1fr)}}}}
  .stat{{background:var(--card);padding:14px 16px}}
  .stat b{{display:block;font-family:'Arial Black',system-ui,sans-serif;font-size:21px}}
  .stat span{{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim)}}
  .lanes{{margin-top:16px;font-size:13.5px;color:var(--mid)}}
  .lanes i{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}}
  .row{{display:flex;gap:18px;flex-wrap:wrap;margin-top:8px}}
  footer{{margin-top:38px;padding-top:18px;border-top:1px solid var(--edge);
         color:var(--dim);font-size:13px}}
  .more{{margin-top:10px;font-size:13.5px;color:var(--mid)}}
</style>
<script type="application/ld+json">
{ld}
</script>
</head>
<body>
<div class="wrap">
  <nav><a href="/">Miki Drummer</a> · <a href="/drum-game/">Drum Along</a> · {title_e}</nav>

  <header>
    <span class="eyebrow">Play the drums to</span>
    <h1>{title_e}</h1>
    <p class="by">{band_e} · {bpm:.0f} BPM · {mins}:{secs:02d}</p>
    <a class="btn" href="/drum-game/?song={slug}">Play this song →</a>
  </header>

  <div class="stats">
    <div class="stat"><b>{bpm:.0f}</b><span>BPM</span></div>
    <div class="stat"><b>{notes}</b><span>Notes</span></div>
    <div class="stat"><b>{per_sec:.1f}</b><span>Notes / sec</span></div>
    <div class="stat"><b>{diff}</b><span>Difficulty</span></div>
  </div>

  <div class="lanes">
    <div class="row">
      <span><i style="background:#7ee7c7"></i>{hat} hi-hat</span>
      <span><i style="background:#f4b400"></i>{snare} snare</span>
      <span><i style="background:#e8672a"></i>{kick} kick</span>
    </div>
  </div>

  <h2>Playing it</h2>
  <p>{playing}</p>
  <p>{shape}</p>

  <h2>About {band_e}</h2>
  <p>{bandtext}</p>

  <p class="more">Charted from the recording rather than by hand —
     <a href="/drum-game/">how that works</a>. Free, no download, no account, works on a phone.</p>

  <h2>Other songs you can play</h2>
  <p class="more">{siblings}</p>

  <footer>
    Part of <a href="/drum-game/">Drum Along</a>, a free browser drum game by
    <a href="/">Miki Drummer</a>. Shows across BC on <a href="/punkbc.html">Punk BC</a>.
  </footer>
</div>
</body>
</html>
"""


def build():
    rows = load()
    os.makedirs(OUT, exist_ok=True)
    by_slug = {r["slug"]: r for r in rows}
    written = []

    for r in rows:
        lanes = r["lanes"]
        per_sec = r["notes"] / max(r["dur"], 1)
        per_beat = r["notes"] / max(r["beats"], 1)
        diff, feel = difficulty(per_beat)
        mins, secs = int(r["dur"]) // 60, int(r["dur"]) % 60
        busiest = max(lanes, key=lambda k: lanes[k]) if lanes else "snare"
        lane_word = {"hat": "hi-hat", "snare": "snare", "kick": "kick"}[busiest]

        playing = (
            f"{r['title']} runs at {r['bpm']:.0f} BPM for {mins}:{secs:02d}, and the chart has "
            f"{r['notes']} notes in it — about {per_beat:.1f} to a beat, which is {feel}. "
            f"The {lane_word} lane is the busiest with {lanes.get(busiest, 0)} of them, so that "
            f"is the hand to sort out first. "
            + ("At this tempo the notes arrive quickly, so it is worth a run at the offset "
               "calibration before you start. " if r["bpm"] >= 190 else
               "The tempo leaves enough room to read the patterns coming. ")
            + "Hi-hat on A, snare on S, kick on space, or three pads on a touchscreen."
        )

        others = [x for x in rows if x["slug"] != r["slug"]]
        same_band = [x for x in others if x["band"] == r["band"]][:3]
        rest = [x for x in others if x["band"] != r["band"]][:4]
        sib = ", ".join(
            f'<a href="/drum-game/songs/{x["slug"]}.html">{esc(x["title"])}</a> ({esc(x["band"])})'
            for x in (same_band + rest))

        desc = (f"Play the drums to {r['title']} by {r['band']} in your browser — free, no "
                f"download. {r['bpm']:.0f} BPM, {r['notes']} notes, charted from the recording.")

        ld = json.dumps({
            "@context": "https://schema.org",
            "@graph": [
                {"@type": "MusicRecording", "name": r["title"],
                 "byArtist": {"@type": "MusicGroup", "name": r["band"]},
                 "duration": "PT%dM%dS" % (mins, secs)},
                {"@type": "BreadcrumbList", "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Miki Drummer",
                     "item": SITE + "/"},
                    {"@type": "ListItem", "position": 2, "name": "Drum Along",
                     "item": SITE + "/drum-game/"},
                    {"@type": "ListItem", "position": 3, "name": r["title"],
                     "item": f"{SITE}/drum-game/songs/{r['slug']}.html"}]},
            ]}, indent=2)

        html = PAGE.format(
            site=SITE, slug=r["slug"], title=esc(r["title"]), title_e=esc(r["title"]),
            band=esc(r["band"]), band_e=esc(r["band"]), desc=esc(desc),
            bpm=r["bpm"], notes=r["notes"], per_sec=per_sec, diff=diff,
            mins=mins, secs=secs,
            hat=lanes.get("hat", 0), snare=lanes.get("snare", 0), kick=lanes.get("kick", 0),
            playing=esc(playing), shape=esc(shape_of(r["raw"], r["dur"])),
            bandtext=esc(BANDS.get(r["band"], "")),
            siblings=sib, ld=ld)

        path = os.path.join(OUT, r["slug"] + ".html")
        with open(path, "w") as fh:
            fh.write(html)
        written.append((r["slug"], r["title"], r["band"], r["notes"], per_sec, diff))

    for slug, title, band, n, ps, d in written:
        print("%-32s %-18s %4d notes  %.1f/s  %s" % (slug, band, n, ps, d))
    print("%d song pages -> drum-game/songs/" % len(written))
    return rows


if __name__ == "__main__":
    build()
