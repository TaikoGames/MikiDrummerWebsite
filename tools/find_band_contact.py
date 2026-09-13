#!/usr/bin/env python3
"""Fill in contacts for the bands on the shows board.

Runs on a GitHub runner, where there is real internet. A browser cannot do this
-- the free CORS proxies are gone and most band sites refuse them -- so the
finding happens here and /ask-a-band.html reads the result. Typing a band name
then fills the contact in with nothing to tap.

The whole risk of this job is a confident wrong answer. A page can easily hand
back a string shaped like an email that will never reach the band: Bandcamp
carries a Sentry telemetry address, Wix and Squarespace sites carry their
vendor's, and a support@ address on a ticketing page belongs to the ticketing
company. An invite sent to one of those is worse than no address at all,
because nobody finds out it went nowhere. So everything below is built to
refuse rather than guess, and each address is kept with the page it came from
so it can be checked by eye.

    python3 tools/find_band_contact.py --selftest
    python3 tools/find_band_contact.py --limit 10 [--band "Name"] [--dry-run]
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOWS = os.path.join(ROOT, "punkbc-shows.json")
OUT = os.path.join(ROOT, "data", "band-contacts.json")

UA = ("Mozilla/5.0 (compatible; PunkBC-contact-finder/1.0; "
      "+https://www.mikidrummer.ca/punkbc.html)")
TIMEOUT = 20
PAUSE = 1.5                     # between requests, to whoever we are reading
RECHECK_DAYS = 45               # how long a fruitless lookup stands before a retry

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}")

# Addresses that exist on a band's page but are not the band. Every one of
# these has been seen in the wild on a page that otherwise looks right.
JUNK_DOMAINS = {
    "sentry.io", "sentry-next.wixpress.com", "wixpress.com", "wix.com",
    "squarespace.com", "sentry.wixpress.com", "shopify.com", "bandcamp.com",
    "example.com", "example.org", "domain.com", "yourdomain.com", "email.com",
    "godaddy.com", "cloudflare.com", "gstatic.com", "w3.org", "schema.org",
    "sentry.example.com", "bandzoogle.com", "wordpress.com", "weebly.com",
    "sentry-next.wix.com", "png", "jpg", "jpeg", "webp", "svg", "gif",
}
JUNK_LOCALS = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "postmaster",
    "abuse", "hostmaster", "sentry", "wix", "your", "youremail", "email",
    "name", "user", "username", "someone", "test", "admin@2x",
}
# Ticketing, venues and press: real addresses, wrong recipient.
NOT_THE_BAND = {
    "eventbrite.com", "ticketmaster.com", "showpass.com", "orangetickets.ca",
    "songkick.com", "bandsintown.com", "ticketweb.ca", "dice.fm",
    "stripe.com", "paypal.com", "instagram.com", "facebook.com",
}
SOCIAL_HOSTS = ("instagram.com", "facebook.com", "twitter.com", "x.com",
                "tiktok.com", "youtube.com", "spotify.com", "apple.com",
                "linktr.ee", "soundcloud.com", "bandsintown.com", "songkick.com")

CONTACT_PATHS = ("", "/contact", "/contact.html", "/contact-us", "/booking",
                 "/about", "/info")


# ---------------------------------------------------------------- pure helpers

def slug(name):
    """The shape a band's own bandcamp subdomain usually takes."""
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("&", "and"))


def acts_from(show):
    """Both halves of the board: the billed act and the support in the notes."""
    out = str(show.get("band") or "").split(" / ")
    note = str(show.get("notes") or "").strip()
    if re.match(r"^with ", note, re.I):
        out += note[5:].split(",")
    cleaned = []
    for s in out:
        s = re.sub(r"\.\s*(19\+|all ages)\.?$", "", s, flags=re.I).strip()
        if 1 < len(s) < 60:
            cleaned.append(s)
    return cleaned


def plausible(addr):
    """Could this address belong to a band at all?"""
    addr = addr.strip().strip(".,;:<>()[]'\"").lower()
    if not addr or addr.count("@") != 1 or len(addr) > 80:
        return False
    local, _, domain = addr.partition("@")
    if not local or not domain or ".." in domain or domain.startswith("."):
        return False
    if local in JUNK_LOCALS or local.startswith("sentry"):
        return False
    if domain in JUNK_DOMAINS or domain in NOT_THE_BAND:
        return False
    tld = domain.rsplit(".", 1)[-1]
    if tld in JUNK_DOMAINS or len(tld) < 2:
        return False
    # "logo@2x.png" and friends survive the regex otherwise.
    if re.search(r"\.(png|jpe?g|gif|svg|webp|css|js)$", addr):
        return False
    return True


def emails_in(html):
    """Addresses on a page, mailto: links first — those are deliberate."""
    found, seen = [], set()
    for m in re.finditer(r'mailto:([^"\'>?\s]+)', html, re.I):
        a = urllib.parse.unquote(m.group(1)).strip().lower()
        if plausible(a) and a not in seen:
            seen.add(a)
            found.append(a)
    for m in EMAIL_RE.finditer(html):
        a = m.group(0).strip().lower()
        if plausible(a) and a not in seen:
            seen.add(a)
            found.append(a)
    return found


def score(addr, band, page_host):
    """How likely is this the band's own address rather than someone else's."""
    local, _, domain = addr.partition("@")
    s = 0
    sl = slug(band)
    bare = domain.rsplit(".", 2)[0]
    if sl and (sl in slug(domain) or slug(domain) in sl):
        s += 6                                   # band@theirownband.com
    if page_host and slug(page_host) and slug(page_host) in slug(domain):
        s += 3                                   # matches the site it is on
    if local in ("booking", "bookings", "contact", "info", "band", "mail"):
        s += 2
    if sl and sl in slug(local):
        s += 4                                   # theband@gmail.com
    if domain in ("gmail.com", "hotmail.com", "outlook.com", "yahoo.com",
                  "protonmail.com", "proton.me", "icloud.com"):
        s += 1
    if local in ("webmaster", "support", "help", "sales", "privacy", "legal"):
        s -= 4                                   # usually the host, not the band
    if bare in ("wixsite", "squarespace"):
        s -= 5
    return s


def best_email(cands, band):
    """cands: list of (addr, page_host). Returns the best, or ''."""
    ranked = sorted(((score(a, band, h), a, h) for a, h in cands), reverse=True)
    for s, a, _h in ranked:
        if s > 0:
            return a
    return ""


def stale(rec, today, days=RECHECK_DAYS):
    """A lookup that found nothing is worth repeating eventually; one that
    found an address is not — re-running could only replace a known-good
    address with a worse guess."""
    if rec.get("email"):
        return False
    try:
        when = datetime.date.fromisoformat(rec.get("checked", ""))
    except ValueError:
        return True
    return (today - when).days >= days


# ------------------------------------------------------------------- the world

def get(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-CA,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if int(r.headers.get("Content-Length") or 0) > 3_000_000:
            return ""
        raw = r.read(3_000_000)
    enc = r.headers.get_content_charset() or "utf-8"
    return raw.decode(enc, "replace")


def search(query, limit=8):
    """DuckDuckGo's lite endpoint: plain HTML, no javascript, no key."""
    url = "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query)
    try:
        html = get(url)
    except Exception as e:
        print("    search failed:", e)
        return []
    out, seen = [], set()
    for m in re.finditer(r'href="(https?://[^"]+)"', html):
        u = urllib.parse.unquote(m.group(1))
        if "duckduckgo.com" in u:
            continue
        host = urllib.parse.urlparse(u).netloc.lower()
        if host in seen:
            continue
        seen.add(host)
        out.append(u)
        if len(out) >= limit:
            break
    return out


def host_of(url):
    return urllib.parse.urlparse(url).netloc.lower().replace("www.", "")


def look_up(band):
    """Walk the places a band's address tends to live. Returns a record in the
    same shape the research-by-hand entries use, so the page replays both
    identically."""
    profiles, cands = [], []

    def note(name, url, found):
        profiles.append({"name": name, "url": url, "found": found})
        print("    %-26s %-46s %s" % (name[:26], url[:46], found))

    # 1. Their own Bandcamp, at the address bands nearly always have.
    bc = "https://%s.bandcamp.com/" % slug(band)
    try:
        html = get(bc)
        found = emails_in(html)
        # Bandcamp never publishes the address, but it confirms the band and
        # carries links out to wherever they do.
        for a in found:
            cands.append((a, host_of(bc)))
        note("Bandcamp", bc, "email" if found else "form")
    except Exception:
        note("Bandcamp", bc, "none")
    time.sleep(PAUSE)

    # 2. Whatever the web says is theirs.
    hits = search('"%s" band contact email booking' % band)
    official = []
    for u in hits:
        h = host_of(u)
        if any(s in h for s in SOCIAL_HOSTS):
            kind = "profile"
            if "instagram.com" in h or "facebook.com" in h:
                note("Instagram" if "instagram" in h else "Facebook", u, kind)
            continue
        if h.endswith("bandcamp.com") or h in NOT_THE_BAND:
            continue
        official.append(u)
    time.sleep(PAUSE)

    # 3. Read the first couple of real sites, and their contact pages.
    for site in official[:2]:
        root = "%s://%s" % (urllib.parse.urlparse(site).scheme, urllib.parse.urlparse(site).netloc)
        for path in CONTACT_PATHS:
            url = site if path == "" else root + path
            try:
                html = get(url)
            except Exception:
                continue
            found = emails_in(html)
            for a in found:
                cands.append((a, host_of(url)))
            if found:
                note("Site", url, "email")
                break
            if re.search(r"<form|contact", html, re.I) and path:
                note("Site", url, "form")
                break
            time.sleep(PAUSE)
        time.sleep(PAUSE)

    email = best_email(cands, band)
    src = ""
    if email:
        for a, h in cands:
            if a == email:
                src = h
                break
    return {
        "band": band,
        "checked": datetime.date.today().isoformat(),
        "email": email,
        "email_source": src,
        "profiles": profiles,
        "note": "" if email else "Found automatically; no address published.",
        "by": "auto",
    }


# ------------------------------------------------------------------- self-test

def selftest():
    fails = []

    def ok(cond, msg):
        if not cond:
            fails.append(msg)

    # The addresses that would have sent a gig offer to an error tracker.
    ok(not plausible("a1b2c3@sentry.wixpress.com"), "sentry address let through")
    ok(not plausible("noreply@aband.com"), "noreply let through")
    ok(not plausible("logo@2x.png"), "image filename let through")
    ok(not plausible("support@eventbrite.com"), "ticketing address let through")
    ok(not plausible("hello@bandcamp.com"), "bandcamp address let through")
    ok(plausible("diejobpunk@gmail.com"), "real address rejected")
    ok(plausible("booking@thefomites.ca"), "real address rejected")

    # mailto: wins over a bare string further up the page.
    html = 'junk@sentry.io <a href="mailto:band@band.ca">write</a> hi@other.com'
    ok(emails_in(html)[0] == "band@band.ca", "mailto not preferred")
    ok("junk@sentry.io" not in emails_in(html), "sentry survived extraction")

    # Ranking: the band's own domain beats a generic, and the host's own
    # webmaster address loses to both.
    cands = [("webmaster@wixsite.com", "wixsite.com"),
             ("meanbikini@gmail.com", "mean-bikini.com"),
             ("info@mean-bikini.com", "mean-bikini.com")]
    ok(best_email(cands, "Mean Bikini") == "info@mean-bikini.com",
       "wrong pick: " + best_email(cands, "Mean Bikini"))
    ok(best_email([("webmaster@somehost.com", "somehost.com")], "X") == "",
       "a host address was accepted as the band's")
    ok(best_email([], "X") == "", "empty candidates should give empty")

    # Board parsing matches the page's own reading of it.
    show = {"band": "Alien Boys / Die Job", "notes": "With Kids on Fire, Brehdren. 19+"}
    ok(acts_from(show) == ["Alien Boys", "Die Job", "Kids on Fire", "Brehdren"],
       "acts: %r" % acts_from(show))
    # One-character names are noise from a split, not bands.
    ok(acts_from({"band": "X / Real Band"}) == ["Real Band"], "single letter kept")

    ok(slug("Bound By None") == "boundbynone", "slug")
    ok(slug("Sh*t & Shine") == "shtandshine", "slug with symbols")

    # Re-checking: keep a good address, retry an empty one after a while.
    today = datetime.date(2026, 9, 13)
    ok(not stale({"email": "a@b.ca", "checked": "2020-01-01"}, today),
       "a found address should not be re-looked-up")
    ok(stale({"email": "", "checked": "2026-01-01"}, today), "old empty not retried")
    ok(not stale({"email": "", "checked": "2026-09-01"}, today), "fresh empty retried")
    ok(stale({"email": "", "checked": "nonsense"}, today), "bad date not retried")

    print("selftest: %d checks, %d failed" % (17, len(fails)))
    for f in fails:
        print("  FAIL:", f)
    return 1 if fails else 0


# ------------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--band", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    with open(OUT) as f:
        data = json.load(f)
    have = {b["band"].lower().strip(): b for b in data["bands"]}
    today = datetime.date.today()

    if args.band:
        wanted = args.band
    else:
        with open(SHOWS) as f:
            shows = json.load(f)["shows"]
        seen, wanted = set(), []
        for s in shows:
            for a in acts_from(s):
                k = a.lower().strip()
                if k in seen:
                    continue
                seen.add(k)
                rec = have.get(k)
                # Anything a person looked up by hand is left alone.
                if rec and (rec.get("by") != "auto" or not stale(rec, today)):
                    continue
                wanted.append(a)

    print("%d band(s) to look up, doing %d" % (len(wanted), min(len(wanted), args.limit)))
    added = 0
    for band in wanted[:args.limit]:
        print("\n==", band)
        try:
            rec = look_up(band)
        except Exception as e:
            print("    gave up:", e)
            continue
        print("    ->", rec["email"] or "(no address published)")
        k = band.lower().strip()
        if k in have:
            data["bands"][data["bands"].index(have[k])] = rec
        else:
            data["bands"].append(rec)
            have[k] = rec
        added += 1

    if args.dry_run:
        print("\ndry run, nothing written")
        return 0

    data["bands"].sort(key=lambda b: b["band"].lower())
    with open(OUT, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    withmail = sum(1 for b in data["bands"] if b.get("email"))
    print("\n%d looked up this run · %d bands on file · %d with an address"
          % (added, len(data["bands"]), withmail))
    return 0


if __name__ == "__main__":
    sys.exit(main())
