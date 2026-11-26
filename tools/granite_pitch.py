#!/usr/bin/env python3
"""Send a booking pitch for GRANITE to a venue or promoter, from a link.

Started by granite-send.html through the granite-pitch workflow:

  1. Open the website that was pasted, find its booking address (plain text,
     mailto links, and Cloudflare's hidden "email protection" form, which
     many venue sites use). If the page has none, try its contact/booking
     pages on the same site.
  2. Pick the best one: booking@ / talent@ / events@ before info@ / hello@,
     never noreply@, privacy@ and the like, and the site's own domain first.
  3. Write a short pitch signed by whoever is writing, with the press kit,
     Instagram and live video, and send it from the Gmail account in the
     GMAIL_ADDRESS / GMAIL_APP_PASSWORD secrets. Replies go to that inbox.
  4. Record it in data/granite-pitches.json, which the page shows as a
     history, and which stops the same address being pitched twice inside
     60 days by accident.

Usage:
  python3 tools/granite_pitch.py --site URL --writer NAME [--note TEXT] [--dry-run]
  python3 tools/granite_pitch.py --self-test
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import os
import re
import smtplib
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "granite-pitches.json"
UA = ("Mozilla/5.0 (compatible; MikiDrummerBot/1.0; +https://www.mikidrummer.ca) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36")
TIMEOUT = 25
REPEAT_DAYS = 60

EPK = "https://www.mikidrummer.ca/granite-epk.html"
INSTAGRAM = "https://www.instagram.com/granitevancouver/"
VIDEO = "https://www.youtube.com/watch?v=Qovij1CQUV4"

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CF = re.compile(r'data-cfemail="([0-9a-fA-F]+)"|/cdn-cgi/l/email-protection#([0-9a-fA-F]+)')
NEVER = ("noreply", "no-reply", "donotreply", "privacy", "abuse", "webmaster", "postmaster",
         "unsubscribe", "example.", "sentry", "wixpress", "domain.com", "email.com",
         "yourname", "jobs@", "careers@", "hr@", "accounts@", "billing@", "invoice")
FILE_EXT = re.compile(r"\.(png|jpe?g|gif|webp|svg|css|js)$", re.I)
GOOD = (("booking", 0), ("book", 0), ("talent", 1), ("events", 1), ("event", 1), ("shows", 1),
        ("music", 1), ("live", 1), ("promo", 2), ("entertainment", 2), ("info", 3), ("hello", 3),
        ("contact", 3), ("hi@", 3), ("general", 4))
CONTACT_LINK = re.compile(r'href=["\']([^"\']+)["\'][^>]*>([^<]{0,60})<', re.I)
CONTACT_WORDS = ("contact", "booking", "book", "about", "info", "rentals", "hire", "promot")


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(3_000_000).decode("utf-8", "replace")


def cf_decode(hexstr: str) -> str:
    """Cloudflare email protection: first byte is the XOR key for the rest."""
    b = bytes.fromhex(hexstr)
    return "".join(chr(c ^ b[0]) for c in b[1:])


def emails_in(page: str) -> list[str]:
    text = htmllib.unescape(page)
    found = [m.group(0) for m in EMAIL.finditer(text)]
    for m in CF.finditer(page):
        try:
            found.append(cf_decode(m.group(1) or m.group(2)))
        except ValueError:
            pass
    out = []
    for e in found:
        e = e.strip(".").lower()
        if FILE_EXT.search(e) or any(n in e for n in NEVER) or not EMAIL.fullmatch(e):
            continue
        if e not in out:
            out.append(e)
    return out


def score(email: str, site_host: str) -> tuple:
    local, _, domain = email.partition("@")
    rank = next((r for word, r in GOOD if (word in local if not word.endswith("@") else email.startswith(word))), 5)
    host = site_host.lower().removeprefix("www.")
    own = 0 if (domain == host or host.endswith("." + domain) or domain.endswith("." + host)) else 1
    return (rank, own, len(email))


def contact_pages(page: str, base: str) -> list[str]:
    host = urlsplit(base).netloc
    out = []
    for href, text in CONTACT_LINK.findall(page):
        u = urljoin(base, htmllib.unescape(href))
        if urlsplit(u).netloc != host or u.split("#")[0] == base.split("#")[0]:
            continue
        hay = (href + " " + text).lower()
        if any(w in hay for w in CONTACT_WORDS) and u not in out:
            out.append(u)
    return out[:4]


def site_name(page: str, url: str) -> str:
    for pat in (r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)',
                r"<title[^>]*>([^<]+)</title>"):
        m = re.search(pat, page, re.I)
        if m:
            name = htmllib.unescape(m.group(1)).strip()
            name = re.split(r"\s+[|\-–—:]\s+", name)[0].strip()
            if 2 <= len(name) <= 60:
                return name
    return urlsplit(url).netloc.removeprefix("www.")


def find_contact(site: str, fetch=get) -> tuple[str | None, str, list[str]]:
    """(best email or None, venue name, what was looked at) for a pasted link."""
    looked = []
    if not site.startswith("http"):
        site = "https://" + site
    page = fetch(site)
    looked.append(site)
    name = site_name(page, site)
    found = emails_in(page)
    if not found:
        for u in contact_pages(page, site):
            try:
                found += [e for e in emails_in(fetch(u)) if e not in found]
                looked.append(u)
            except Exception:
                continue
            if found:
                break
    if not found:
        return None, name, looked
    host = urlsplit(site).netloc
    return sorted(found, key=lambda e: score(e, host))[0], name, looked


def compose(to: str, venue: str, writer: str, note: str, sender: str) -> EmailMessage:
    first = writer.strip().split()[0] if writer.strip() else "GRANITE"
    note_line = f"\n{note.strip()}\n" if note.strip() else ""
    text = f"""Hi {venue} team,

I'm {first} from GRANITE, a metal and grunge band from Vancouver. Downtuned riffs, raw vocals, and a loud, sweaty live show. We'd love to play {venue}.
{note_line}
Everything a booker needs is in our press kit, with photos, music, our bio and a live video:
{EPK}

Live video: {VIDEO}
Instagram: {INSTAGRAM}

If there's a night that could fit us, just reply to this email. Happy to share draw numbers, a stage plot, or anything else you need.

Thanks,
{writer.strip() or first}
GRANITE
"""
    msg = EmailMessage()
    msg["Subject"] = f"GRANITE (Vancouver metal/grunge): booking enquiry for {venue}"
    msg["From"] = formataddr((f"{first} from GRANITE", sender))
    msg["To"] = to
    msg["Reply-To"] = sender
    msg["Message-ID"] = make_msgid(domain="mikidrummer.ca")
    msg.set_content(text)
    return msg


def load_log() -> dict:
    if LOG.exists():
        return json.loads(LOG.read_text())
    return {"_readme": "Booking pitches sent for GRANITE from granite-send.html. Public venue "
                       "contact addresses only. Used to avoid emailing the same place twice.",
            "sent": []}


def recently_pitched(log: dict, to: str, now: datetime) -> dict | None:
    for s in reversed(log.get("sent", [])):
        if s.get("to") == to and now - datetime.fromisoformat(s["at"].replace("Z", "+00:00")) < timedelta(days=REPEAT_DAYS):
            return s
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--writer", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--again", action="store_true", help="send even if pitched recently")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.site.strip() or not a.writer.strip():
        raise SystemExit("Need the website and who's writing.")

    raw = a.site.strip()
    if EMAIL.fullmatch(raw.removeprefix("mailto:")):
        to, venue = raw.removeprefix("mailto:").lower(), raw.split("@")[1].split(".")[0].title()
        print(f"Using the address you gave: {to}")
    else:
        try:
            to, venue, looked = find_contact(raw)
        except Exception as e:
            raise SystemExit(f"Couldn't open {raw}: {e}")
        print("Looked at: " + ", ".join(looked))
        if not to:
            raise SystemExit(f"No email address found on {raw} or its contact pages. "
                             "Paste their email address instead.")
        print(f"Found: {to} ({venue})")

    log = load_log()
    now = datetime.now(timezone.utc)
    prev = recently_pitched(log, to, now)
    if prev and not a.again:
        raise SystemExit(f"Already pitched {to} on {prev['at'][:10]} (by {prev.get('writer', '?')}). "
                         f"Not sending again within {REPEAT_DAYS} days.")

    sender = os.environ.get("GMAIL_ADDRESS", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    msg = compose(to, venue, a.writer, a.note, sender or "granite@example.invalid")
    if a.dry_run:
        print("--- dry run, not sent ---\n" + msg.get_content())
        return 0
    if not sender or not password:
        raise SystemExit("GMAIL_ADDRESS / GMAIL_APP_PASSWORD secrets are not set.")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(sender, password)
        s.send_message(msg)
    log["sent"].append({"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": to, "venue": venue,
                        "site": raw, "writer": a.writer.strip()})
    LOG.write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n")
    print(f"Sent to {to} for {venue}, signed {a.writer.strip()}.")
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::notice title=sent::Sent to {to} ({venue})")
    return 0


def self_test() -> int:
    checks = []
    # Cloudflare's hidden form of booking@venue.test, key 0x42
    key = 0x42
    hidden = format(key, "02x") + "".join(format(ord(c) ^ key, "02x") for c in "booking@venue.test")
    checks.append(("cloudflare email decoded", cf_decode(hidden) == "booking@venue.test"))
    page = (f'<title>The Venue | Vancouver</title><a href="mailto:info@venue.test">x</a>'
            f'<span class="__cf_email__" data-cfemail="{hidden}">[email protected]</span>'
            '<p>noreply@venue.test logo@2x.png privacy@venue.test someone@gmail.com</p>')
    found = emails_in(page)
    checks.append(("finds plain, mailto and hidden; drops junk",
                   sorted(found) == ["booking@venue.test", "info@venue.test", "someone@gmail.com"]))
    best = sorted(found, key=lambda e: score(e, "www.venue.test"))[0]
    checks.append(("booking@ beats info@", best == "booking@venue.test"))
    checks.append(("own domain beats gmail for the same role",
                   sorted(["info@gmail.com", "info@venue.test"], key=lambda e: score(e, "venue.test"))[0] == "info@venue.test"))
    checks.append(("venue name from title", site_name(page, "https://venue.test") == "The Venue"))

    pages = {"https://venue.test": '<title>Venue</title><a href="/contact-us">Contact</a><a href="https://other.test/contact">x</a>',
             "https://venue.test/contact-us": "<p>Bookings: talent@venue.test</p>"}
    to, name, looked = find_contact("venue.test", fetch=lambda u: pages[u])
    checks.append(("follows the site's own contact page", to == "talent@venue.test" and len(looked) == 2))

    msg = compose("talent@venue.test", "Venue", "Miki Drummer", "We'd love a Friday in March.", "me@example.test")
    body = msg.get_content()
    checks.append(("pitch is signed and personal", "I'm Miki from GRANITE" in body and "Miki Drummer\nGRANITE" in body
                   and "Hi Venue team" in body and "Friday in March" in body and EPK in body))
    checks.append(("replies go to the sender", msg["Reply-To"] == "me@example.test"))

    now = datetime(2026, 11, 26, tzinfo=timezone.utc)
    log = {"sent": [{"at": "2026-11-01T00:00:00Z", "to": "talent@venue.test", "writer": "Miki"}]}
    checks.append(("no repeat within 60 days", recently_pitched(log, "talent@venue.test", now) is not None))
    checks.append(("fine after 60 days", recently_pitched(log, "talent@venue.test", now + timedelta(days=40)) is None))

    for n, ok in checks:
        print(("  [ok] " if ok else "  [FAIL] ") + n)
    bad = sum(1 for _, ok in checks if not ok)
    print("self-test:", "passed" if not bad else f"{bad} FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as e:
        # granite-send.html reads this annotation to tell you why, in plain words
        if isinstance(e.code, str) and os.environ.get("GITHUB_ACTIONS"):
            print(f"::error title=why::{e.code}")
            sys.exit(1)
        raise
