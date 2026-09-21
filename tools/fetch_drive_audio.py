#!/usr/bin/env python3
"""Pull a master off Google Drive and turn it into something a website can serve.

A finished mix arrives as a WAV, because that is what a mastering engineer
sends back. "Pony Up mix17_DGSmaster.wav" is 55 MB. Committing that to a repo
that GitHub Pages serves would be wrong twice over: the file sits in git
history forever at full size, and every promoter who opens the press kit on a
phone downloads 55 MB to hear one song.

So it gets transcoded. Nothing else is done to it -- no normalising, no
limiting, no fades. It is a master; somebody was paid to decide how it sounds,
and a build script is not entitled to a second opinion.

This container has neither ffmpeg nor a route to Drive, so it runs on a
runner: see .github/workflows/drive-audio.yml.

    python3 tools/fetch_drive_audio.py --self-test
    FILE_ID=... OUT=audio/granite/pony-up.mp3 python3 tools/fetch_drive_audio.py
"""

import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 192k CBR stereo. A press kit is listened to on laptop speakers and phones to
# decide whether a band goes on a bill; the ceiling is the listener, not the
# codec. It puts a four-minute song around 5-6 MB, which is a download someone
# will actually wait for.
BITRATE = "192k"

UA = {"User-Agent": "Mozilla/5.0 (mikidrummer-audio/1.0; +https://www.mikidrummer.ca)"}


def drive_url(file_id):
    return "https://drive.google.com/uc?export=download&id=" + urllib.parse.quote(file_id)


def confirm_token(body):
    """Drive interrupts larger downloads with a scan-warning page.

    The real file is behind a confirm token on that page rather than at the
    URL you asked for, so a script that does not look for it cheerfully saves
    the HTML warning and calls it a WAV.
    """
    if not body:
        return None
    m = re.search(r'name="confirm"\s+value="([^"]+)"', body)
    if m:
        return m.group(1)
    # The ampersand is HTML-escaped in the page source, so the character
    # before "confirm" is a semicolon rather than the "&" you would expect.
    m = re.search(r'[?&](?:amp;)?confirm=([0-9A-Za-z_-]+)', body)
    return m.group(1) if m else None


def looks_like_html(head):
    return head[:15].lstrip().lower().startswith((b"<!doctype", b"<html"))


def download(file_id, dest):
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor())
    req = urllib.request.Request(drive_url(file_id), headers=UA)
    with opener.open(req, timeout=120) as r:
        first = r.read(65536)
        if looks_like_html(first):
            tok = confirm_token(first.decode("utf-8", "replace") + r.read().decode("utf-8", "replace"))
            if not tok:
                raise SystemExit("Drive returned a page, not a file, and no confirm token was on it. "
                                 "Is the file shared with anyone who has the link?")
            req2 = urllib.request.Request(drive_url(file_id) + "&confirm=" + tok, headers=UA)
            with opener.open(req2, timeout=600) as r2, open(dest, "wb") as fh:
                while True:
                    chunk = r2.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
        else:
            with open(dest, "wb") as fh:
                fh.write(first)
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
    return dest


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,bit_rate:stream=codec_name,channels,sample_rate",
         "-of", "default=nw=1", path],
        capture_output=True, text=True, check=True).stdout
    d = dict(l.split("=", 1) for l in out.strip().splitlines() if "=" in l)
    return d


def transcode(src, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-i", src,
         "-codec:a", "libmp3lame", "-b:a", BITRATE,
         # Strip whatever the DAW left in the file. A master can carry the
         # engineer's name, a studio path and a session comment, and a press
         # kit is handed to strangers by design.
         "-map_metadata", "-1",
         dest],
        check=True, capture_output=True)
    return dest


def self_test():
    fails = []

    def eq(got, want, what):
        if got != want:
            fails.append("%s: got %r want %r" % (what, got, want))

    eq(drive_url("abc123"), "https://drive.google.com/uc?export=download&id=abc123", "url")

    # The scan-warning page, in both shapes Drive has served it.
    eq(confirm_token('<form><input type="hidden" name="confirm" value="t9xQ"></form>'), "t9xQ",
       "token from a form field")
    eq(confirm_token('<a href="/uc?export=download&amp;confirm=AbC-1_2&amp;id=x">Download</a>'),
       "AbC-1_2", "token from a link")
    eq(confirm_token("<html>no token here</html>"), None, "no token")
    eq(confirm_token(""), None, "empty body")

    # Telling the warning page from the audio, which is the thing that stops a
    # 3 KB HTML file being committed as a master.
    eq(looks_like_html(b"<!DOCTYPE html><html>"), True, "doctype")
    eq(looks_like_html(b"\n  <html lang=\"en\">"), True, "leading whitespace")
    eq(looks_like_html(b"RIFF\x24\x08\x00\x00WAVE"), False, "a real wav")
    eq(looks_like_html(b"ID3\x03\x00\x00\x00"), False, "an mp3")

    for f in fails:
        print("FAIL", f)
    print("%d checks, %d failed" % (10, len(fails)))
    return 1 if fails else 0


def main():
    if "--self-test" in sys.argv:
        return self_test()

    file_id = os.environ.get("FILE_ID", "").strip()
    out = os.environ.get("OUT", "").strip()
    if not file_id or not out:
        print("FILE_ID and OUT are both required", file=sys.stderr)
        return 2

    raw = "/tmp/master-source"
    print("downloading %s" % file_id)
    download(file_id, raw)
    size = os.path.getsize(raw)
    print("  %.1f MB" % (size / 1e6))
    if size < 100_000:
        print("that is too small to be a master — Drive probably served a page", file=sys.stderr)
        return 1

    print("source: %s" % probe(raw))
    dest = os.path.join(ROOT, out)
    transcode(raw, dest)
    print("wrote %s  %.1f MB" % (out, os.path.getsize(dest) / 1e6))
    print("result: %s" % probe(dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
