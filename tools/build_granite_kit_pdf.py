#!/usr/bin/env python3
"""GRANITE's press kit as one PDF, for attaching to booking emails.

Page 1 is a one-sheet: logo, press photo, the bio (read off granite-epk.html so
it cannot drift from the page), the facts and every link a booker needs.
The pages after it are the photos and artwork, one per page, full bleed.

    python3 tools/build_granite_kit_pdf.py [out.pdf]

Default output: files/granite-press-kit.pdf
"""
import html
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "images" / "granite"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "files" / "granite-press-kit.pdf"

W, H = 1275, 1650                      # US letter at 150 dpi
M = 90
BG = (17, 18, 20)
INK = (236, 234, 230)
DIM = (160, 164, 170)
HOT = (232, 103, 42)
FONT = "/usr/share/fonts/opentype/inter/Inter-Regular.otf"
BOLD = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
LINKS = [("Press kit", "mikidrummer.ca/granite-epk.html"),
         ("Listen", "soundcloud.com/user-968824092/pony-up-1"),
         ("Live video", "youtube.com/watch?v=Qovij1CQUV4"),
         ("Instagram", "@granitevancouver")]
PHOTOS = ["press-photo.jpg", "hero.jpg", "feature.jpg", "live-01.jpg", "live-02.jpg", "live-03.jpg",
          "live-07.jpg", "live-08.jpg", "live-09.jpg", "logo-fire.jpg", "tiamat-demon.jpg"]


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)


def bio():
    s = (ROOT / "granite-epk.html").read_text(encoding="utf-8")
    seg = s[s.find('id="bio"'):][:12000]
    clean = lambda t: re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "", t))).strip()
    paras = [clean(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", seg, re.S)]
    paras = [p for p in paras if p and not p.lower().startswith("press photo, live shots")]
    facts = [(clean(k), clean(v)) for k, v in
             re.findall(r'class="row"[^>]*>.*?class="k"[^>]*>(.*?)</.*?class="v"[^>]*>(.*?)</div>', seg, re.S)]
    return paras, facts


def wrap(draw, text, f, width):
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=f) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def cover():
    page = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(page)
    logo = Image.open(IMG / "logo.png").convert("RGBA")
    logo.thumbnail((W - 2 * M, 190))
    page.paste(logo, (M, M), logo)
    y = M + logo.height + 30
    photo = Image.open(IMG / "press-photo.jpg").convert("RGB")
    pw = W - 2 * M
    ph = int(photo.height * pw / photo.width)
    ph = min(ph, 500)
    photo = photo.resize((pw, int(photo.height * pw / photo.width))).crop((0, 0, pw, ph))
    page.paste(photo, (M, y))
    y += ph + 40
    paras, facts = bio()
    body = font(FONT, 25)
    for p in paras:
        for line in wrap(d, p, body, W - 2 * M):
            d.text((M, y), line, font=body, fill=INK)
            y += 36
        y += 14
    y += 6
    d.line((M, y, W - M, y), fill=(60, 63, 68), width=2)
    y += 22
    k, v = font(BOLD, 22), font(FONT, 22)
    col = (W - 2 * M) // 2
    rows = [(a, b) for a, b in facts] + LINKS
    for i, (a, b) in enumerate(rows):
        x = M + (i % 2) * col
        yy = y + (i // 2) * 62
        d.text((x, yy), a.upper(), font=font(BOLD, 17), fill=HOT)
        d.text((x, yy + 24), b, font=v, fill=INK)
    end = y + ((len(rows) + 1) // 2) * 62 + 16
    d.text((M, max(end, H - M - 10)), "Booking: reply to the email this came with.", font=font(FONT, 20), fill=DIM)
    return page


def photo_page(name):
    page = Image.new("RGB", (W, H), BG)
    im = Image.open(IMG / name).convert("RGB")
    im.thumbnail((W - 2 * M, H - 2 * M - 60))
    page.paste(im, ((W - im.width) // 2, (H - 60 - im.height) // 2))
    d = ImageDraw.Draw(page)
    d.text((M, H - M), "GRANITE · " + name.rsplit(".", 1)[0].replace("-", " "), font=font(FONT, 20), fill=DIM)
    return page


def main():
    pages = [cover()] + [photo_page(n) for n in PHOTOS if (IMG / n).exists()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(OUT, "PDF", resolution=150, save_all=True, append_images=pages[1:], quality=82)
    print(f"{OUT} · {len(pages)} pages · {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
