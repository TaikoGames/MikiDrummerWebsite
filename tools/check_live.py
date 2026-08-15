#!/usr/bin/env python3
"""Detect whether the YouTube channel is streaming, and flip the site overlay.

Runs from GitHub Actions on a schedule. Checking server-side rather than in the
browser means one request per run no matter how many visitors are on the site,
and no API key sitting in the page.

Two detection paths:
  * YOUTUBE_API_KEY set  – YouTube Data API search, the reliable route
  * no key               – fetch youtube.com/channel/<id>/live and look for the
                           live markers in the page. Free and quota-less, but it
                           reads undocumented markup, so it can break if YouTube
                           changes their page.

config.json keys this touches:
  liveNow           "yes" / "no"  – last detected state, always written
  liveAuto          "yes" / "no"  – when yes, this script drives showOverlay
  showOverlay       "yes" / "no"  – only changed while liveAuto is yes and no
                                    manual hold is in force
  overlayManual     "on"/"off"/"" – the admin switch used by hand; while set and
                                    unexpired, automatic changes stand down
  overlayManualUntil ISO-8601      – when that hold lapses back to automatic

Usage:  python3 tools/check_live.py [--self-test]
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.json"
YT_URL = ROOT / "youtubeurl.json"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")

# Markers that appear on a channel's /live page while a stream is running.
LIVE_MARKERS = ('"isLiveNow":true', '"isLive":true', 'hlsManifestUrl',
                '"liveBroadcastContent":"live"')
# ...and ones that positively indicate it is not.
OFFLINE_MARKERS = ('"isLiveNow":false', '"liveBroadcastContent":"none"')


def channel_id() -> str | None:
    """Pull the channel id out of youtubeurl.json."""
    try:
        url = json.loads(YT_URL.read_text(encoding="utf-8")).get("youtube_url", "")
    except Exception:
        return None
    m = re.search(r"[?&]channel=([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"/channel/([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else None


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def live_via_api(cid: str, key: str) -> bool | None:
    url = ("https://www.googleapis.com/youtube/v3/search"
           f"?part=snippet&channelId={cid}&eventType=live&type=video&maxResults=1&key={key}")
    try:
        data = json.loads(fetch(url))
    except Exception as e:
        print(f"  API check failed: {e}")
        return None
    if "error" in data:
        print(f"  API error: {data['error'].get('message','?')}")
        return None
    return bool(data.get("items"))


def parse_live(html: str) -> bool:
    """True when the page looks like an in-progress stream."""
    for m in OFFLINE_MARKERS:
        if m in html:
            return False
    return any(m in html for m in LIVE_MARKERS)


def live_via_scrape(cid: str) -> bool | None:
    try:
        html = fetch(f"https://www.youtube.com/channel/{cid}/live")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False               # no live page at all == not streaming
        print(f"  scrape failed: HTTP {e.code}")
        return None
    except Exception as e:
        print(f"  scrape failed: {e}")
        return None
    return parse_live(html)


def _future(stamp: str, now: str | None = None) -> bool:
    """True when an ISO-8601 UTC timestamp is still ahead of now."""
    stamp = (stamp or "").strip()
    if not stamp:
        return False
    now = now or datetime.now(timezone.utc).isoformat()
    # both are ISO-8601 UTC strings, so comparing the text is enough
    return stamp.replace("Z", "+00:00") > now


def timer_running(cfg: dict, now: str | None = None) -> bool:
    """True while a manual 'show for the next N hours' timer is still going."""
    if cfg.get("showOverlay") != "yes":
        return False
    return _future(cfg.get("overlayUntil"), now)


def manual_hold(cfg: dict, now: str | None = None) -> bool:
    """True while someone has taken the overlay off automatic from admin.

    Detection is the convenience; the switch in admin is the guarantee. When it
    is used it wins outright — on or off — so a stream the checker misses can
    still be put on screen by hand. The hold carries its own expiry so a
    forgotten override drifts back to automatic instead of sticking forever.
    """
    if cfg.get("overlayManual") not in ("on", "off"):
        return False
    return _future(cfg.get("overlayManualUntil"), now)


def apply(is_live: bool, now: str | None = None) -> bool:
    """Write the state into config.json. Returns True if the file changed."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    before = json.dumps(cfg, sort_keys=True)

    cfg["liveNow"] = "yes" if is_live else "no"
    held = manual_hold(cfg, now) or timer_running(cfg, now)
    if cfg.get("liveAuto") == "yes" and not held:
        if is_live:
            cfg["showOverlay"] = "yes"
            # a stale timer would otherwise switch it off mid-stream
            cfg["overlayUntil"] = ""
        else:
            cfg["showOverlay"] = "no"
        # an expired hold is spent — drop it so the file says what is true
        if cfg.get("overlayManual"):
            cfg["overlayManual"] = ""
            cfg["overlayManualUntil"] = ""

    if json.dumps(cfg, sort_keys=True) == before:
        return False
    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return True


def self_test() -> int:
    """Check the marker parsing without needing the network."""
    cases = [
        ('{"videoDetails":{"isLiveNow":true}}', True, "isLiveNow true"),
        ('{"videoDetails":{"isLiveNow":false}}', False, "isLiveNow false"),
        ('..."hlsManifestUrl":"https://x/y.m3u8"...', True, "hls manifest"),
        ('..."liveBroadcastContent":"none"...', False, "broadcastContent none"),
        ('..."liveBroadcastContent":"live"...', True, "broadcastContent live"),
        ("<html>nothing here</html>", False, "no markers"),
        # an offline marker must win even when a stale live one is also present
        ('"isLiveNow":false ... hlsManifestUrl', False, "offline marker wins"),
    ]
    bad = 0
    for html, want, label in cases:
        got = parse_live(html)
        ok = got == want
        bad += not ok
        print(f"  [{'ok' if ok else 'FAIL'}] {label}: expected {want}, got {got}")

    NOW = "2026-08-15T12:00:00+00:00"
    timers = [
        ({"showOverlay": "yes", "overlayUntil": "2026-08-15T18:00:00.000Z"}, True, "timer still running"),
        ({"showOverlay": "yes", "overlayUntil": "2026-08-15T06:00:00.000Z"}, False, "timer expired"),
        ({"showOverlay": "yes"}, False, "on with no timer"),
        ({"showOverlay": "no", "overlayUntil": "2026-08-15T18:00:00.000Z"}, False, "off with a stale timer"),
    ]
    for cfg, want, label in timers:
        got = timer_running(cfg, NOW)
        ok = got == want
        bad += not ok
        print(f"  [{'ok' if ok else 'FAIL'}] {label}: expected {want}, got {got}")

    holds = [
        ({"overlayManual": "on", "overlayManualUntil": "2026-08-16T00:00:00.000Z"}, True, "forced on, still held"),
        ({"overlayManual": "off", "overlayManualUntil": "2026-08-16T00:00:00.000Z"}, True, "forced off, still held"),
        ({"overlayManual": "on", "overlayManualUntil": "2026-08-15T06:00:00.000Z"}, False, "hold expired"),
        ({"overlayManual": "", "overlayManualUntil": ""}, False, "no hold"),
        ({"overlayManual": "on"}, False, "hold with no expiry is not a hold"),
    ]
    for cfg, want, label in holds:
        got = manual_hold(cfg, NOW)
        ok = got == want
        bad += not ok
        print(f"  [{'ok' if ok else 'FAIL'}] {label}: expected {want}, got {got}")

    print("self-test:", "passed" if not bad else f"{bad} failure(s)")
    return 1 if bad else 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    cid = channel_id()
    if not cid:
        print("no channel id in youtubeurl.json — nothing to check")
        return 0
    print(f"channel {cid}")

    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    is_live = live_via_api(cid, key) if key else None
    if is_live is None:
        if key:
            print("  falling back to page check")
        is_live = live_via_scrape(cid)
    if is_live is None:
        print("could not determine live state — leaving config.json alone")
        return 0

    print(f"live: {is_live}")
    changed = apply(is_live)
    print("config.json:", "updated" if changed else "unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
