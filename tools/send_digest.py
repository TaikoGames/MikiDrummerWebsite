#!/usr/bin/env python3
"""Put the month's digest into MailerLite, as a draft or as a send.

Everything up to this point is automatic: the board refreshes daily, the digest
and its email copy are rebuilt on the 1st and 15th. The send was the one step
left by hand, which was fine until it needed doing from somewhere without a
MailerLite connector attached — a phone, a chat, a session that has none.

So the send lives here instead, behind a workflow. The API key is a repository
secret, so it is never in a transcript or a checkout, and anyone who can
dispatch the workflow can send without holding the key themselves.

Two modes on purpose:

  draft (default)  builds the campaign in MailerLite and stops. Nothing is
                   delivered; someone opens it, looks, and presses send.
  send             schedules it for instant delivery to the group.

Draft is the default because a newsletter cannot be unsent, and the difference
between the two is one word typed by someone who meant it.

Usage:
  MAILERLITE_API_KEY=... python3 tools/send_digest.py                # draft, this month
  MAILERLITE_API_KEY=... python3 tools/send_digest.py --month 2026-09
  MAILERLITE_API_KEY=... python3 tools/send_digest.py --send         # actually deliver
  python3 tools/send_digest.py --self-test                           # no network, no key
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "digest"
API = "https://connect.mailerlite.com/api"

GROUP_NAME = "Punk BC — monthly digest"
FROM_NAME = "Punk BC"
TIMEOUT = 30

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Vancouver")
except Exception:                                     # pragma: no cover
    TZ = None


def this_month() -> str:
    now = datetime.now(TZ) if TZ else datetime.utcnow()
    return now.strftime("%Y-%m")


def month_name(ym: str) -> str:
    return datetime.strptime(ym + "-01", "%Y-%m-%d").strftime("%B %Y")


def call(method: str, path: str, key: str, body: dict | None = None, opener=None):
    """One MailerLite request. `opener` exists so the self-test can stand in."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    send = opener or (lambda r: urllib.request.urlopen(r, timeout=TIMEOUT))
    try:
        with send(req) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        # MailerLite answers a rejected sender or an unverified domain with a
        # perfectly clear message; passing it straight through beats paraphrasing.
        raise SystemExit(f"MailerLite said {e.code}: {detail}")
    return json.loads(raw) if raw else {}


def find_group(key: str, name: str, opener=None) -> str:
    """The group id for a name, because ids are not something to hardcode."""
    got = call("GET", "/groups?limit=100", key, opener=opener)
    groups = got.get("data", [])
    for g in groups:
        if (g.get("name") or "").strip() == name.strip():
            return g["id"]
    known = ", ".join(repr(g.get("name")) for g in groups) or "none"
    raise SystemExit(f"no group named {name!r} in MailerLite — found: {known}")


def build(key: str, ym: str, html: str, group_id: str, sender: str, opener=None) -> dict:
    label = month_name(ym)
    return call("POST", "/campaigns", key, {
        "name": f"Punk BC — {label}",
        "type": "regular",
        "groups": [group_id],
        "emails": [{
            "subject": f"Punk BC — {label} shows",
            "from_name": FROM_NAME,
            "from": sender,
            "content": html,
        }],
    }, opener=opener)


def deliver(key: str, campaign_id: str, opener=None) -> dict:
    return call("POST", f"/campaigns/{campaign_id}/schedule", key,
                {"delivery": "instant"}, opener=opener)


def self_test() -> int:
    """Exercises the whole path against a stand-in for MailerLite."""
    seen = []

    class Reply:
        def __init__(self, payload): self.payload = json.dumps(payload).encode()
        def read(self): return self.payload
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(req):
        seen.append((req.method, req.full_url, req.headers,
                     json.loads(req.data) if req.data else None))
        if req.full_url.endswith("/groups?limit=100"):
            return Reply({"data": [{"id": "111", "name": "Other list"},
                                   {"id": "999", "name": GROUP_NAME}]})
        if req.full_url.endswith("/campaigns"):
            return Reply({"data": {"id": "camp42", "name": "Punk BC — September 2026"}})
        return Reply({"data": {"status": "sent"}})

    gid = find_group("k", GROUP_NAME, opener=fake)
    made = build("k", "2026-09", "<b>hi</b>", gid, "digest@mikidrummer.ca", opener=fake)
    deliver("k", made["data"]["id"], opener=fake)

    _, _, hdrs, _ = seen[0]
    _, _, _, campaign = seen[1]
    _, sched_url, _, sched = seen[2]
    checks = [
        (gid == "999", f"group matched by name, not position (got {gid})"),
        (hdrs.get("Authorization") == "Bearer k", "key sent as a bearer token"),
        (campaign["groups"] == ["999"], "campaign points at that group"),
        (campaign["emails"][0]["subject"] == "Punk BC — September 2026 shows",
         f"subject reads {campaign['emails'][0]['subject']!r}"),
        (campaign["emails"][0]["from"] == "digest@mikidrummer.ca", "sender carried through"),
        (campaign["emails"][0]["content"] == "<b>hi</b>", "email html carried through"),
        (sched_url.endswith("/campaigns/camp42/schedule"), "sends the campaign it just made"),
        (sched == {"delivery": "instant"}, "instant delivery"),
    ]

    # a draft run must never reach the schedule endpoint
    seen.clear()
    gid = find_group("k", GROUP_NAME, opener=fake)
    build("k", "2026-09", "<b>hi</b>", gid, "digest@mikidrummer.ca", opener=fake)
    checks.append((not any("schedule" in u for _, u, _, _ in seen),
                   "draft mode never calls schedule"))

    # a missing group is refused rather than guessed at
    try:
        find_group("k", "Nope", opener=fake)
        checks.append((False, "unknown group should stop the run"))
    except SystemExit as e:
        checks.append(("no group named" in str(e), "unknown group stops the run, and says so"))

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

    ym = args[args.index("--month") + 1] if "--month" in args else this_month()
    if not re.fullmatch(r"\d{4}-\d{2}", ym):
        print(f"month should look like 2026-09, got {ym!r}")
        return 1

    key = os.environ.get("MAILERLITE_API_KEY", "").strip()
    if not key:
        print("MAILERLITE_API_KEY is not set — add it as a repository secret")
        return 1
    sender = os.environ.get("MAILERLITE_FROM", "").strip()
    if not sender:
        print("MAILERLITE_FROM is not set — it must be an address on a domain "
              "verified in MailerLite, not a Gmail one")
        return 1

    email = OUT / f"{ym}.email.html"
    if not email.exists():
        print(f"{email.relative_to(ROOT)} does not exist — build the digest first")
        return 1
    html = email.read_text(encoding="utf-8")

    group_id = find_group(key, GROUP_NAME)
    made = build(key, ym, html, group_id, sender)
    campaign_id = made.get("data", {}).get("id")
    print(f"campaign created for {month_name(ym)} (id {campaign_id}), "
          f"{len(html)} characters of html, group {group_id}")

    if "--send" not in args:
        print("draft only — open it in MailerLite, check it, and press send there")
        return 0

    deliver(key, campaign_id)
    print("sent to the group")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
