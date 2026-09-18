#!/usr/bin/env python3
"""Photographs of blank merch, for the mockup tool to print onto.

The first cut of /merch.html drew its blanks as vectors. They were honest
shapes, and they looked like vectors -- which is the one thing a mockup must
not look like, because the whole point is to answer "what will this actually
be". So: real photographs.

Which means licensing. A mockup made here gets sent to a printer, posted to
Instagram, put on a Bandcamp page -- it leaves. That rules out anything with
conditions attached:

  * CC BY needs a credit line travelling with the image. It won't.
  * CC BY-SA needs the *output* shared alike. A band's own artwork is not
    ours to put a share-alike condition on.

So public domain and CC0 only, and the licence is read off the file rather
than assumed from the search that found it.

This container cannot reach Commons, so it runs on a runner: see
.github/workflows/merch-photos.yml. It downloads to images/merch/candidates/
for review -- nothing goes near the site until a human has looked at it.

    python3 tools/fetch_merch_photos.py --self-test
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "images", "merch", "candidates")

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "MikiDrummer/1.0 (https://www.mikidrummer.ca; merch mockups)"}

# Matched against LicenseShortName. Commons writes these a dozen ways
# ("Public domain", "CC0", "PD-self", "PD-USGov", "No restrictions"), so match
# the family rather than listing every tag.
PD = re.compile(r"^(public domain|cc0|pd[-\s]|no restrictions)", re.I)

# Anything with a share-alike or attribution condition, named explicitly so a
# stray "CC BY-SA 4.0 / Public domain in the US" dual-licence line cannot slip
# through on the strength of its second half.
CONDITIONAL = re.compile(r"(cc[-\s]?by|share[-\s]?alike|gfdl|fal\b|attribut)", re.I)

# A garment shot side-on or worn at an angle has no flat panel to print on.
# These words in a title are a reliable sign of that, and cheaper to check
# than looking at every candidate.
REJECT_TITLE = re.compile(
    r"(sleeve detail|collar|folded|stack|pile|hanger rack|laundry|"
    r"back view|rear view|drying|ironing|sewing|factory|protest|rally|"
    r"demonstration|march\b|cosplay|mannequin head)", re.I)

PRODUCTS = [
    # slug, what to search Commons for
    ("tee",        ["blank t-shirt", "plain t-shirt front", "black t-shirt",
                    "white t-shirt plain", "t-shirt template"]),
    ("longsleeve", ["long sleeve shirt plain", "longsleeve t-shirt",
                    "long-sleeved shirt blank"]),
    ("hoodie",     ["blank hoodie", "plain hooded sweatshirt", "hoodie front",
                    "pullover sweatshirt plain"]),
    ("tote",       ["tote bag", "canvas shopping bag", "cotton bag plain"]),
    ("cap",        ["baseball cap", "snapback cap", "plain cap hat"]),
    ("beanie",     ["beanie hat", "knit cap wool", "watch cap"]),
    ("drumhead",   ["bass drum head", "drum head front", "bass drum front"]),
    ("sticks",     ["drumsticks", "drum sticks pair"]),
    ("sticker",    ["blank sticker", "vinyl sticker square"]),
    ("pin",        ["enamel pin badge", "button badge pin", "pin badge blank"]),
    ("mug",        ["plain mug", "coffee mug white blank", "black mug"]),
    ("vinyl",      ["vinyl record sleeve", "LP record jacket", "12 inch record"]),
    ("banner",     ["fabric banner blank", "vinyl banner plain"]),
    ("koozie",     ["can cooler sleeve", "beer koozie"]),
]


def api(**params):
    params.update(format="json")
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def strip(html):
    return re.sub(r"\s+", " ", re.sub("<[^>]+>", "", html or "")).strip()


def usable(lic, usage):
    """True only when nothing is asked of whoever uses the picture.

    Read both fields: a file can carry a permissive LicenseShortName and a
    UsageTerms that quietly adds a condition, and it is the condition that
    would follow a mockup out of the door.
    """
    blob = "%s %s" % (lic or "", usage or "")
    if CONDITIONAL.search(blob):
        return False
    return bool(PD.match((lic or "").strip()))


def shootable(title, w, h):
    """A picture worth printing onto.

    Wants a flat panel facing the camera and enough pixels to stand a 1200px
    mockup, so: no junk in the title, no thumbnails, and nothing wildly
    panoramic (a 4:1 crop is a detail shot, not a product).
    """
    if REJECT_TITLE.search(title or ""):
        return False
    if not w or not h or min(w, h) < 800:
        return False
    ratio = max(w, h) / min(w, h)
    return ratio <= 2.2


def search(product, queries, per_query=30):
    seen, keep = set(), []
    for q in queries:
        try:
            res = api(action="query", generator="search",
                      gsrsearch="%s filetype:bitmap" % q, gsrnamespace=6,
                      gsrlimit=per_query, prop="imageinfo",
                      iiprop="url|extmetadata|size", iiurlwidth=1600)
        except Exception as e:
            print("    ! %-34s %s" % (q, e))
            continue
        for page in (res.get("query", {}).get("pages") or {}).values():
            title = page.get("title", "")
            if title in seen:
                continue
            seen.add(title)
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            lic = (meta.get("LicenseShortName", {}).get("value") or "").strip()
            usage = strip(meta.get("UsageTerms", {}).get("value"))
            w, h = info.get("width"), info.get("height")
            if not usable(lic, usage) or not shootable(title, w, h):
                continue
            keep.append({
                "product": product, "title": title, "license": lic,
                "usage": usage,
                "credit": strip(meta.get("Artist", {}).get("value"))[:140],
                "descurl": info.get("descriptionurl"),
                "src": info.get("thumburl") or info.get("url"),
                "w": w, "h": h, "query": q,
            })
    return keep


def download(cands, per_product):
    from PIL import Image
    saved = []
    for cand in cands[:per_product]:
        i = len([s for s in saved if s["product"] == cand["product"]])
        name = "%s-%02d.jpg" % (cand["product"], i)
        path = os.path.join(OUT, cand["product"], name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            req = urllib.request.Request(cand["src"], headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                blob = r.read()
            tmp = os.path.join(OUT, ".tmp")
            open(tmp, "wb").write(blob)
            im = Image.open(tmp).convert("RGB")
            im.thumbnail((1600, 1600), Image.LANCZOS)
            im.save(path, quality=88, optimize=True)
            cand["file"] = os.path.relpath(path, ROOT)
            saved.append(cand)
            print("    saved %-18s %-46s %s" % (name, cand["title"][3:49], cand["license"]))
        except Exception as e:
            print("    failed %-46s %s" % (cand["title"][3:49], e))
    return saved


def self_test():
    fails = []

    def eq(got, want, what):
        if got != want:
            fails.append("%s: got %r want %r" % (what, got, want))

    # Licences that let a mockup leave the building.
    for lic in ["Public domain", "CC0", "PD-self", "PD-USGov-Military",
                "public domain", "No restrictions"]:
        eq(usable(lic, ""), True, "usable(%s)" % lic)

    # Licences that do not.
    for lic in ["CC BY 4.0", "CC BY-SA 3.0", "GFDL", "cc-by-sa-2.0", "FAL"]:
        eq(usable(lic, ""), False, "usable(%s)" % lic)

    # A permissive tag with a condition hiding in the usage terms. This is the
    # case the whole two-field check exists for.
    eq(usable("Public domain", "CC BY-SA 4.0"), False, "dual-licence tag")
    eq(usable("Public domain", "You must attribute the author"), False,
       "attribution in usage terms")
    eq(usable("", ""), False, "no licence at all")

    # Framing.
    eq(shootable("File:Blank black t-shirt.jpg", 1200, 1600), True, "good tee")
    eq(shootable("File:T-shirt back view.jpg", 1200, 1600), False, "back view")
    eq(shootable("File:Shirts folded stack.jpg", 1200, 1600), False, "folded")
    eq(shootable("File:Tee.jpg", 400, 600), False, "too small")
    eq(shootable("File:Banner.jpg", 4000, 900), False, "panoramic detail")
    eq(shootable("File:Protest march t-shirts.jpg", 1600, 1600), False, "protest")

    for f in fails:
        print("FAIL", f)
    print("%d checks, %d failed" % (23, len(fails)))
    return 1 if fails else 0


def main():
    if "--self-test" in sys.argv:
        return self_test()

    only = os.environ.get("PRODUCTS", "").strip()
    per_product = int(os.environ.get("PER_PRODUCT", "6"))
    wanted = [p for p in PRODUCTS if not only or p[0] in only.split(",")]

    os.makedirs(OUT, exist_ok=True)
    manifest = []
    for slug, queries in wanted:
        print("%s:" % slug)
        found = search(slug, queries)
        print("    %d usable of %d queries" % (len(found), len(queries)))
        manifest += download(found, per_product)

    tmp = os.path.join(OUT, ".tmp")
    if os.path.exists(tmp):
        os.remove(tmp)
    with open(os.path.join(OUT, "candidates.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    print("\n%d photographs, %d products covered"
          % (len(manifest), len({m["product"] for m in manifest})))
    empty = [s for s, _ in wanted if not any(m["product"] == s for m in manifest)]
    if empty:
        print("nothing public-domain found for: %s" % ", ".join(empty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
