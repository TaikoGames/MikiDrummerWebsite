#!/usr/bin/env python3
"""Pull a folder of band artwork off Drive and lay it out to be looked at.

Picking "the white logo in fire" out of a Drive folder needs somebody to see
the images, and half of them are inside zips. So this downloads the lot,
unpacks the archives, flattens anything that is a layered PSD, and builds one
numbered contact sheet. The sheet is the deliverable: it goes in a review
folder, a human points at a number, and only then does anything reach the site.

Nothing here is published. Artwork lands in a scratch folder with a manifest
tying each number back to the file it came from, so a choice can be acted on
without guessing which "image004" was meant.

This container cannot reach Drive, so it runs on a runner: see
.github/workflows/drive-images.yml.

    python3 tools/fetch_drive_images.py --self-test
    FILES="id:name,id:name" python3 tools/fetch_drive_images.py
"""

import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_drive_audio import download  # noqa: E402  (same Drive confirm-token handling)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "images", "granite", "review")

# What is worth opening. A PSD counts: Pillow reads the flattened composite,
# which is all a contact sheet needs, and band artwork is usually delivered as
# layered Photoshop files.
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".psd")

# Junk that rides along in a synced Drive folder and in the zips made from one.
JUNK = ("desktop.ini", ".ds_store", "thumbs.db")


def is_image(name):
    base = os.path.basename(name).lower()
    if not base or base.startswith(".") or base.startswith("__macosx"):
        return False
    if base in JUNK:
        return False
    return base.endswith(IMAGE_EXT)


def gather(blob, source):
    """Every image in one downloaded file, whether or not it is an archive.

    Returns [(label, bytes)]. A zip is walked rather than assumed to be flat:
    these are exports, and exports nest.
    """
    out = []
    if zipfile.is_zipfile(io.BytesIO(blob)):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for info in z.infolist():
                if info.is_dir() or not is_image(info.filename):
                    continue
                # A zip entry can be enormous once expanded; band artwork is
                # not, so anything absurd is a sign of something else.
                if info.file_size > 80 * 1024 * 1024:
                    print("    skipped %s (%.0f MB expanded)" % (info.filename, info.file_size / 1e6))
                    continue
                out.append(("%s!%s" % (source, info.filename), z.read(info)))
    elif is_image(source):
        out.append((source, blob))
    return out


def sheet(items, path, cols=4, cell=420):
    """One numbered page of everything, so a person can point at a number."""
    from PIL import Image, ImageDraw
    rows = (len(items) + cols - 1) // cols
    page = Image.new("RGB", (cols * cell, rows * cell), (22, 22, 24))
    d = ImageDraw.Draw(page)
    for i, (label, im) in enumerate(items):
        t = im.copy()
        t.thumbnail((cell - 16, cell - 46))
        px, py = (i % cols) * cell, (i // cols) * cell
        # A checker behind each one: half this artwork is white on transparent
        # and would be invisible on any flat backdrop I picked.
        for by in range(py + 6, py + cell - 40, 16):
            for bx in range(px + 8, px + cell - 8, 16):
                if ((bx // 16) + (by // 16)) % 2:
                    d.rectangle([bx, by, bx + 15, by + 15], fill=(44, 44, 48))
        page.paste(t, (px + (cell - t.width) // 2, py + 6),
                   t if t.mode in ("RGBA", "LA") else None)
        d.text((px + 10, py + cell - 34), "%d" % i, fill=(255, 170, 70))
        d.text((px + 34, py + cell - 34), os.path.basename(label)[:44], fill=(200, 200, 205))
        d.text((px + 34, py + cell - 20), "%dx%d" % im.size, fill=(130, 130, 136))
    page.save(path, "JPEG", quality=84, optimize=True)
    return page.size


def self_test():
    fails = []

    def eq(got, want, what):
        if got != want:
            fails.append("%s: got %r want %r" % (what, got, want))

    for n in ["logo.png", "Fire/WHITE LOGO.PNG", "art.psd", "x.tif", "a/b/c.jpeg"]:
        eq(is_image(n), True, "accept %s" % n)

    # The debris a synced Drive folder and its zips carry.
    for n in ["desktop.ini", "Thumbs.db", ".DS_Store", "__MACOSX/._logo.png",
              "notes.txt", "font.otf", "", "folder/"]:
        eq(is_image(n), False, "reject %s" % n)

    # A real zip goes in, the images come out and the junk does not.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Logo/white-fire.png", b"\x89PNG\r\n\x1a\n fake")
        z.writestr("Logo/desktop.ini", b"junk")
        z.writestr("Logo/readme.txt", b"words")
        z.writestr("Logo/nested/deep.jpg", b"\xff\xd8\xff fake")
    got = gather(buf.getvalue(), "Logo.zip")
    eq(len(got), 2, "two images out of the zip")
    eq(sorted(os.path.basename(n.split('!')[1]) for n, _ in got),
       ["deep.jpg", "white-fire.png"], "nested entries found, junk dropped")

    # A bare image passed straight through, not mistaken for an archive.
    eq(len(gather(b"\xff\xd8\xff fake jpeg", "image003.jpg")), 1, "loose image")
    eq(len(gather(b"whatever", "desktop.ini")), 0, "loose junk")

    for f in fails:
        print("FAIL", f)
    print("%d checks, %d failed" % (17, len(fails)))
    return 1 if fails else 0


def main():
    if "--self-test" in sys.argv:
        return self_test()

    spec = os.environ.get("FILES", "").strip()
    if not spec:
        print("FILES is required: 'id:name,id:name'", file=sys.stderr)
        return 2

    from PIL import Image
    os.makedirs(OUT, exist_ok=True)

    raw = []
    for pair in spec.split(","):
        pair = pair.strip()
        if not pair:
            continue
        fid, _, name = pair.partition(":")
        print("downloading %-28s %s" % (name or fid, fid))
        tmp = "/tmp/drive-item"
        download(fid.strip(), tmp)
        blob = open(tmp, "rb").read()
        found = gather(blob, name or fid)
        print("    %d image(s)" % len(found))
        raw += found

    items, manifest = [], []
    for label, data in raw:
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
        except Exception as e:
            print("  unreadable %-44s %s" % (label[:44], e))
            continue
        if im.mode not in ("RGB", "RGBA", "LA", "L"):
            im = im.convert("RGBA")
        items.append((label, im))

    # Biggest first: the full-resolution artwork is what the press kit wants,
    # and the thumbnails and social crops sort themselves to the back.
    items.sort(key=lambda p: -(p[1].width * p[1].height))

    for i, (label, im) in enumerate(items):
        name = "%02d.png" % i
        keep = im.copy()
        keep.thumbnail((2000, 2000), Image.LANCZOS)
        keep.save(os.path.join(OUT, name))
        manifest.append({"n": i, "file": name, "from": label,
                         "size": "%dx%d" % im.size, "mode": im.mode})
        print("%2d  %-52s %sx%s  %s" % (i, label[-52:], im.width, im.height, im.mode))

    if not items:
        print("nothing readable found")
        return 1

    dims = sheet(items, os.path.join(OUT, "contact-sheet.jpg"))
    with open(os.path.join(OUT, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    print("\n%d images · contact sheet %dx%d" % (len(items), dims[0], dims[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
