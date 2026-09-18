#!/usr/bin/env python3
"""A QR code per press kit, pointing at its booking form.

The kits print to PDF, and a PDF gets forwarded, filed and put on a desk. A
booking form is no use to someone holding a printout: the URL was there as
plain text, so reaching it meant typing it out by hand, which nobody does.

A QR code is the one control that works on paper. Point a phone at it and the
form opens, already scrolled to itself.

    python3 tools/build_epk_qr.py [--check]

Deterministic: same URL in, same bytes out, so rebuilding does not hand git a
changed binary every time.
"""

import os
import sys

import qrcode
from qrcode.constants import ERROR_CORRECT_Q

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "images", "epk")

KITS = {
    "granite-book-qr.png":
        "https://www.mikidrummer.ca/granite-epk.html#book",
    "lift-the-anchor-book-qr.png":
        "https://www.mikidrummer.ca/lift-the-anchor-epk.html#book",
}


def build(path, url):
    # Q correction (25%) rather than the default M: a printed page gets
    # creased, photocopied and photographed at an angle, and the extra
    # redundancy is what survives that. box_size 10 keeps it crisp when the
    # page is scaled to A4.
    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_Q,
                       box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    # Black on white, always. The kits are near-black pages, and a QR inverted
    # or tinted to match the design is a QR that half the scanners refuse.
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img.save(path, "PNG", optimize=True)
    return img.size, qr.version


def main():
    os.makedirs(OUT, exist_ok=True)
    check = "--check" in sys.argv
    missing = []
    for name, url in KITS.items():
        path = os.path.join(OUT, name)
        if check:
            if not os.path.exists(path):
                missing.append(name)
            continue
        size, ver = build(path, url)
        print("%-30s v%-2d %dx%d  %5.1f KB  -> %s"
              % (name, ver, size[0], size[1],
                 os.path.getsize(path) / 1024, url))
    if check:
        print("%d of %d QR codes present" % (len(KITS) - len(missing), len(KITS)))
        for m in missing:
            print("  missing:", m)
        return 1 if missing else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
