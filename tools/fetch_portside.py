#!/usr/bin/env python3
"""Pull the Portside live set out of Drive and turn it into something a site can serve.

The recordings arrive as WAV: seven songs, about 440MB of them, which is the
right format for a master and the wrong one for a web page. Nobody is
streaming 55MB to hear thirty seconds of a live take, and git would carry
those bytes forever.

So they are fetched once, encoded to MP3, and committed at a size a browser
can start playing immediately. VBR around 165kbps rather than 128: this is a
drummer's press kit and 128 is where cymbals start to sound like static.

Runs on a GitHub runner, not here — Drive is unreachable from the sandbox this
was written in, and ffmpeg is not installed there either. The files are shared
"anyone with the link", so no credentials are involved.

Writes an index.json alongside the audio with the real duration and size of
each track, so the page can state them rather than guess.

Usage:
  python3 tools/fetch_portside.py              # fetch what is missing
  python3 tools/fetch_portside.py --force      # re-encode everything
  python3 tools/fetch_portside.py --self-test  # no network, no ffmpeg
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "audio" / "live" / "portside-2026-08-29"
INDEX = OUT / "index.json"

# Drive ids for the set, in the order they are meant to be listened to.
# Ordering is a guess until someone who was there says otherwise — the files
# carry no track numbers and were all uploaded within the same minute.
TRACKS = [
    ("Hello RPM",      "1fKDTAkM3mfNcP_af9FeFd2hB0eGDNuvR"),
    ("Aurora",         "1v8bkOkwUYyqS3hKr3fZgB1iUYL3CKJZF"),
    ("Cornered",       "1WrrdnlSvnawH1OH8JCJ5UNOSkes5CKzg"),
    ("Shadows",        "1FPz1Gk0KJODwtp5-BH112IqpSGLxjoiD"),
    ("Terrified",      "1aN8L9LhS7dV775N1KJFrnSnFmTxrBwfe"),
    ("Liminal Divide", "1SY5NZKuv9S_-gUOyeuG3mI7MhSwdYe7Y"),
    ("The Crow",       "1EHP5q13gcz8Dszf6aPKPRpMNiZyNZ0N4"),
]

QUALITY = "4"          # lame VBR, roughly 165kbps
TIMEOUT = 600
MAX_BYTES = 400 * 1024 * 1024


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def download(file_id: str, dest: Path) -> None:
    """A public Drive file, without the browser in the middle.

    Anything over ~100MB gets an interstitial "this file is too big to scan"
    page rather than the bytes; confirm=t is what the button on that page
    would have sent, so asking for it up front skips the round trip.
    """
    url = (f"https://drive.usercontent.google.com/download"
           f"?id={file_id}&export=download&confirm=t")
    req = urllib.request.Request(url, headers={"User-Agent": "MikiDrummerBot/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        kind = (r.headers.get("Content-Type") or "").lower()
        if "text/html" in kind:
            raise SystemExit(f"Drive returned a web page, not audio, for {file_id} — "
                             f"check the file is still shared with anyone who has the link")
        size = 0
        with dest.open("wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise SystemExit(f"{file_id} is larger than {MAX_BYTES >> 20}MB — refusing")
                f.write(chunk)
    if size == 0:
        raise SystemExit(f"{file_id} downloaded as an empty file")


def encode(src: Path, dest: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-codec:a", "libmp3lame", "-q:a", QUALITY, str(dest)],
        check=True,
    )


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return round(float(out.stdout.strip()), 1)


def clock(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def self_test() -> int:
    checks = [
        (slug("The Crow") == "the-crow", "title becomes a filename"),
        (slug("Liminal Divide") == "liminal-divide", "spaces become dashes"),
        (slug("Hello RPM!") == "hello-rpm", "punctuation dropped"),
        (clock(312.4) == "5:12", f"312.4s reads as {clock(312.4)}"),
        (clock(59.6) == "1:00", f"59.6s rounds to {clock(59.6)}"),
        (clock(3.2) == "0:03", f"3.2s reads as {clock(3.2)}"),
        (len(TRACKS) == 7, f"seven tracks listed, got {len(TRACKS)}"),
        (len({i for _, i in TRACKS}) == 7, "no duplicate Drive ids"),
        (all(re.fullmatch(r"[A-Za-z0-9_-]{20,}", i) for _, i in TRACKS),
         "every id looks like a Drive id"),
        (len({slug(n) for n, _ in TRACKS}) == 7, "no two tracks share a filename"),
    ]
    bad = 0
    for ok, label in checks:
        bad += not ok
        print(f"  [{'ok' if ok else 'FAIL'}] {label}")
    print("self-test:", "passed" if not bad else f"{bad} failure(s)")
    return 1 if bad else 0


def main() -> int:
    args = sys.argv[1:]
    if "--self-test" in args:
        return self_test()
    force = "--force" in args

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"{tool} is not installed — this is meant to run on a GitHub runner")
            return 1

    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_tmp.wav"
    manifest = []

    for title, file_id in TRACKS:
        mp3 = OUT / f"{slug(title)}.mp3"
        if mp3.exists() and not force:
            print(f"  {title}: already encoded")
        else:
            print(f"  {title}: downloading…", flush=True)
            download(file_id, tmp)
            print(f"  {title}: encoding…", flush=True)
            encode(tmp, mp3)
            tmp.unlink(missing_ok=True)
            print(f"  {title}: {mp3.stat().st_size // 1024}KB")
        secs = duration(mp3)
        manifest.append({
            "title": title,
            "file": mp3.name,
            "seconds": secs,
            "length": clock(secs),
            "bytes": mp3.stat().st_size,
        })

    INDEX.write_text(json.dumps({
        "venue": "The Portside Pub",
        "city": "Vancouver, BC",
        "date": "2026-08-29",
        "band": "Lift the Anchor",
        "tracks": manifest,
    }, indent=2) + "\n", encoding="utf-8")

    total = sum(t["bytes"] for t in manifest)
    run = clock(sum(t["seconds"] for t in manifest))
    print(f"portside: {len(manifest)} tracks, {run} of music, {total // 1024 // 1024}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
