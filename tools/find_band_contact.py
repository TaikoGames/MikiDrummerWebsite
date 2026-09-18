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
# Bandcamp's own CDN, help desk and image hosts. They appear as outbound links
# on every artist page, and the first run happily read all three as "their
# site".
ASSET_HOSTS = ("bcbits.com", "bandcamp.help", "bandcamp.com", "gstatic.com",
               "googleapis.com", "cloudfront.net", "cdn.", "fonts.")

# Link hubs. Not the destination — but the band chose what is on them, so what
# they list is worth following.
HUB_HOSTS = ("linktr.ee", "lnk.bio", "beacons.ai", "allmylinks.com",
             "linkin.bio", "solo.to", "campsite.bio", "hoo.be")

SOCIAL_HOSTS = ("instagram.com", "facebook.com", "twitter.com", "x.com",
                "tiktok.com", "youtube.com", "spotify.com", "apple.com",
                "linktr.ee", "soundcloud.com", "bandsintown.com", "songkick.com")

CONTACT_PATHS = ("", "/contact", "/contact.html", "/contact-us", "/booking",
                 "/about", "/info")

# Instagram paths that are not somebody's profile. /p/ and /reel/ are single
# posts, and the rest are Instagram's own furniture -- all of them turn up as
# links on a band's page, and all of them would read as a handle if the first
# path segment were taken on trust.
IG_RESERVED = {
    "p", "reel", "reels", "tv", "stories", "explore", "accounts", "about",
    "developer", "developers", "legal", "privacy", "terms", "directory",
    "web", "emails", "challenge", "session", "graphql", "ajax", "api",
    "help", "press", "blog", "jobs", "topics", "locations", "create", "your_activity",
}
IG_URL = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9_.]+)", re.I)


# ---------------------------------------------------------------- pure helpers

def slug(name):
    """The shape a band's own bandcamp subdomain usually takes."""
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("&", "and"))


def ig_handle(url):
    """The Instagram handle in a URL, or "" if there is not one.

    A band page links to Instagram in several shapes -- the profile, a single
    post, an embedded reel -- and only the first is an account anyone can be
    written to. Taking the first path segment on trust would file half the
    board under handles like "p" and "reel", which is how the site ended up
    with a band whose Instagram was recorded as @p.
    """
    m = IG_URL.search(url or "")
    if not m:
        return ""
    handle = m.group(1).strip(".").lower()
    if not handle or handle in IG_RESERVED:
        return ""
    # Instagram allows letters, numbers, periods and underscores, up to 30.
    if len(handle) > 30 or not re.fullmatch(r"[a-z0-9_.]+", handle):
        return ""
    return handle


def ig_from_profiles(rec):
    """Recover a handle from the profile links a record already carries.

    Every lookup so far stored Instagram as one entry in a list of links
    without ever pulling the handle out, so the board's handles exist but are
    not usable as a list. This reads them back out with no network at all.
    """
    for p in rec.get("profiles", []):
        h = ig_handle(p.get("url", ""))
        if h:
            return h
    return ""


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


def bad_domain(domain):
    """bandcamp.com was in the list and support@theexitstrategy.bandcamp.com
    still got through, because the check was for the domain exactly. Anything
    hanging off one of these hosts belongs to the host."""
    domain = domain.lower().strip(".")
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in JUNK_DOMAINS or suffix in NOT_THE_BAND:
            return True
    return False


def why_not(addr):
    """Why this address was refused, or '' if it was not. A refusal you cannot
    see is indistinguishable from a page that had nothing on it — which is
    exactly how a filter quietly eating the right answer goes unnoticed."""
    addr = addr.strip().strip(".,;:<>()[]'\"").lower()
    if not addr or addr.count("@") != 1 or len(addr) > 80:
        return "not shaped like an address"
    local, _, domain = addr.partition("@")
    if not local or not domain or ".." in domain or domain.startswith("."):
        return "malformed domain"
    if local in JUNK_LOCALS or local.startswith("sentry"):
        return "boilerplate local part (%s@)" % local
    if bad_domain(domain):
        return "belongs to %s, not the band" % domain
    tld = domain.rsplit(".", 1)[-1]
    if tld in JUNK_DOMAINS or len(tld) < 2:
        return "not a real tld (.%s)" % tld
    if re.search(r"\.(png|jpe?g|gif|svg|webp|css|js)$", addr):
        return "a filename, not an address"
    return ""


def plausible(addr):
    """Could this address belong to a band at all?"""
    return why_not(addr) == ""


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
    # Compare against the registered domain, not the whole host: a band's own
    # name appears in <band>.bandcamp.com, which is Bandcamp's address, not
    # theirs.
    root = ".".join(domain.split(".")[-2:])
    if sl and (sl in slug(root) or slug(root) in sl):
        s += 6                                   # band@theirownband.com
    if page_host and slug(page_host) and slug(page_host) in slug(root):
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

def get_traced(url):
    """Fetch and remember what was on it, refusals included."""
    try:
        html = get(url)
    except Exception as e:
        trace(url=url, status=type(e).__name__)
        raise
    raw = set()
    for m in re.finditer(r'mailto:([^"\'>?\s]+)', html, re.I):
        raw.add(urllib.parse.unquote(m.group(1)).strip().lower())
    for m in EMAIL_RE.finditer(html):
        raw.add(m.group(0).strip().lower())
    trace(url=url, status="%d bytes" % len(html),
          emails=sorted((a, why_not(a)) for a in raw),
          links=links_out(html))
    return html


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


URL_RE = re.compile(r'https?://[^\s"\'<>\\)]+')


def links_out(html):
    """The links a band puts on their own page: their site, their Instagram,
    their linktree. The band saying where they are, rather than a guess.

    Not just href attributes. Bandcamp renders an artist's own links from a
    JSON blob in the page, so an href-only reader comes back empty from a
    157KB page that plainly has them — which is what it did."""
    # JSON inside the page escapes every slash: https:\/\/instagram.com\/band.
    # Unescape first — matching afterwards is too late, the pattern has already
    # stopped dead at the first backslash.
    html = html.replace("\\/", "/").replace("&amp;", "&")
    out, seen = [], set()
    for m in URL_RE.finditer(html):
        u = urllib.parse.unquote(m.group(0).rstrip('\\",;.'))
        # Bandcamp wraps outbound links: /redirect?url=<encoded>
        rm = re.search(r"[?&]url=([^&]+)", u)
        if rm:
            u = urllib.parse.unquote(rm.group(1))
        h = host_of(u)
        if not h or h in seen or any(a in h for a in ASSET_HOSTS):
            continue
        seen.add(h)
        out.append(u)
    return out


TRACE = []


def trace(**kw):
    TRACE.append(kw)


def dump_trace():
    print("\n  ---- everything seen ----")
    for t in TRACE:
        print("  %s  (%s)" % (t["url"], t.get("status", "")))
        for a, reason in t.get("emails", []):
            print("      %-44s %s" % (a, reason or "KEPT"))
        for u in t.get("links", [])[:12]:
            print("      link  %s" % u)
        if not t.get("emails") and not t.get("links"):
            print("      (nothing)")


def look_up(band):
    """Walk the places a band's address tends to live. Returns a record in the
    same shape the research-by-hand entries use, so the page replays both
    identically."""
    profiles, cands = [], []

    def note(name, url, found):
        profiles.append({"name": name, "url": url, "found": found})
        print("    %-26s %-46s %s" % (name[:26], url[:46], found))

    official, social = [], []

    # 1. Their own Bandcamp, at the address bands nearly always have. It never
    #    publishes an address, but it does link out to everywhere they do.
    bc = "https://%s.bandcamp.com/" % slug(band)
    try:
        html = get_traced(bc)
        outbound = links_out(html)
        note("Bandcamp", bc, "form")
        for u in outbound:
            h = host_of(u)
            if any(sh in h for sh in SOCIAL_HOSTS) or any(hh in h for hh in HUB_HOSTS):
                social.append(u)
            elif h not in NOT_THE_BAND:
                official.append(u)
    except Exception:
        note("Bandcamp", bc, "none")
        outbound = []
    time.sleep(PAUSE)

    # 2. Anything the band points at through a link hub counts as theirs.
    hubs = [u for u in list(social) if any(h in host_of(u) for h in HUB_HOSTS)]
    for hub in hubs[:1]:
        try:
            hub_html = get_traced(hub)
            for u in links_out(hub_html):
                h = host_of(u)
                if any(sh in h for sh in SOCIAL_HOSTS):
                    social.append(u)
                elif h not in NOT_THE_BAND:
                    official.append(u)
            for a in emails_in(hub_html):
                cands.append((a, host_of(hub)))
        except Exception:
            pass
        time.sleep(PAUSE)

    # 3. A search, when one answers. It is a bonus, not the spine — the lite
    #    endpoint returns nothing from a runner often enough that relying on
    #    it would mean finding nothing at all.
    hits = search('"%s" band contact email booking' % band)
    print("    search returned %d" % len(hits))
    for u in hits:
        h = host_of(u)
        if any(sh in h for sh in SOCIAL_HOSTS):
            social.append(u)
        elif not h.endswith("bandcamp.com") and h not in NOT_THE_BAND:
            official.append(u)
    time.sleep(PAUSE)

    # Only three profiles are kept, and Instagram is the one being collected
    # for, so it goes first rather than being cut by whatever order the links
    # happened to come back in. A post URL is not an account, so anything
    # without a real handle sorts with the rest.
    social.sort(key=lambda u: 0 if ig_handle(u) else 1)
    for u in social[:3]:
        h = host_of(u)
        name = ("Instagram" if "instagram" in h else
                "Facebook" if "facebook" in h else
                "Linktree" if "linktr.ee" in h else h)
        note(name, u, "profile")

    # 4. Read their own sites, and the pages a contact tends to sit on.
    seen_site = set()
    for site in official[:3]:
        parsed = urllib.parse.urlparse(site)
        root = "%s://%s" % (parsed.scheme, parsed.netloc)
        if root in seen_site:
            continue
        seen_site.add(root)
        got = False
        for path in CONTACT_PATHS:
            url = root + path
            try:
                html = get_traced(url)
            except Exception:
                continue
            found = emails_in(html)
            for a in found:
                cands.append((a, host_of(url)))
            if found:
                note("Site", url, "email")
                got = True
                break
            time.sleep(PAUSE)
        if not got:
            note("Site", root, "form" if root else "none")
        time.sleep(PAUSE)

    email = best_email(cands, band)
    src = ""
    if email:
        for a, h in cands:
            if a == email:
                src = h
                break
    handle = ""
    for u in social:
        handle = ig_handle(u)
        if handle:
            break

    return {
        "band": band,
        "checked": datetime.date.today().isoformat(),
        "email": email,
        "email_source": src,
        "instagram": handle,
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
    # Shipped for real on the first run: the blocklist matched bandcamp.com
    # exactly, so a subdomain sailed past, and the band's name inside that
    # subdomain scored it as their own domain.
    ok(not plausible("support@theexitstrategy.bandcamp.com"),
       "bandcamp subdomain let through")
    ok(not plausible("a@x.wixpress.com"), "wixpress subdomain let through")
    ok(best_email([("support@darkthoughts.bandcamp.com", "darkthoughts.bandcamp.com")],
                  "Dark Thoughts") == "", "bandcamp subdomain ranked as the band's")
    ok(bad_domain("mail.eventbrite.com") and not bad_domain("goodband.ca"),
       "suffix matching")
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

    page = ('<a href="https://bandcamp.com/redirect?url=https%3A%2F%2Fmyband.ca%2F">site</a>'
            '<a href="https://www.instagram.com/myband/">ig</a>'
            '<a href="https://myband.bandcamp.com/album/x">album</a>')
    ok(links_out(page) == ["https://myband.ca/", "https://www.instagram.com/myband/"],
       "links_out: %r" % links_out(page))

    # Every Bandcamp page links its own CDN and help desk. The first run read
    # all three as the band's website and then reported "no address".
    plumbing = ('<a href="https://s4.bcbits.com/img/x.jpg">art</a>'
                '<a href="https://get.bandcamp.help/">help</a>'
                '<a href="http://linktr.ee/theband">links</a>')
    # Bandcamp keeps the band's own links in JSON, escaped, with no href in
    # sight. Reading only href="" came back empty from a 157KB page.
    blob = '{"sites":[{"url":"https:\\/\\/www.instagram.com\\/theband\\/"},' \
           '{"url":"https://theband.ca/"}]}'
    ok(links_out(blob) == ["https://www.instagram.com/theband/", "https://theband.ca/"],
       "json links missed: %r" % links_out(blob))
    ok(links_out(plumbing) == ["http://linktr.ee/theband"],
       "bandcamp plumbing followed as a site: %r" % links_out(plumbing))

    ok(slug("Bound By None") == "boundbynone", "slug")
    ok(slug("Sh*t & Shine") == "shtandshine", "slug with symbols")

    # Re-checking: keep a good address, retry an empty one after a while.
    today = datetime.date(2026, 9, 13)
    ok(not stale({"email": "a@b.ca", "checked": "2020-01-01"}, today),
       "a found address should not be re-looked-up")
    ok(stale({"email": "", "checked": "2026-01-01"}, today), "old empty not retried")
    ok(not stale({"email": "", "checked": "2026-09-01"}, today), "fresh empty retried")
    ok(stale({"email": "", "checked": "nonsense"}, today), "bad date not retried")

    # Instagram handles. The failure that matters is a post URL read as an
    # account: /p/ABC123 would file a band under @p, and a DM to @p reaches a
    # stranger. Every shape below turns up as a link on a real band's page.
    ok(ig_handle("https://www.instagram.com/alienboysvancouver/") == "alienboysvancouver",
       "plain profile URL")
    ok(ig_handle("http://instagram.com/mean.bikini.official") == "mean.bikini.official",
       "dots are legal in a handle")
    ok(ig_handle("https://www.instagram.com/theband/?hl=en") == "theband",
       "query string ignored")
    ok(ig_handle("https://www.instagram.com/p/CVWlA4glQkb/") == "", "a post is not an account")
    ok(ig_handle("https://www.instagram.com/reel/Cabc123/") == "", "a reel is not an account")
    ok(ig_handle("https://www.instagram.com/explore/tags/punk/") == "",
       "a tag page is not an account")
    ok(ig_handle("https://www.instagram.com/accounts/login/") == "",
       "the login page is not an account")
    ok(ig_handle("https://facebook.com/theband") == "", "not instagram at all")
    ok(ig_handle("") == "" and ig_handle(None) == "", "empty input")
    ok(ig_handle("https://www.instagram.com/" + "x" * 40) == "", "over the length limit")
    ok(ig_from_profiles({"profiles": [
        {"url": "https://theband.ca/"},
        {"url": "https://www.instagram.com/theband/"}]}) == "theband",
       "handle recovered from a stored profile list")
    ok(ig_from_profiles({"profiles": [{"url": "https://www.instagram.com/p/abc/"}]}) == "",
       "a stored post URL yields no handle")

    print("selftest: %d checks, %d failed" % (36, len(fails)))
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
    ap.add_argument("--dump", action="store_true",
                    help="print every page read and every address refused")
    ap.add_argument("--backfill", action="store_true",
                    help="recover instagram handles from stored profile links; "
                         "reads no network, so it runs anywhere")
    ap.add_argument("--handles", action="store_true",
                    help="print the outreach list: band, handle, email")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    with open(OUT) as f:
        data = json.load(f)
    have = {b["band"].lower().strip(): b for b in data["bands"]}
    today = datetime.date.today()

    if args.handles:
        rows = sorted((b for b in data["bands"] if b.get("instagram")),
                      key=lambda b: b["band"].lower())
        w = max((len(b["band"]) for b in rows), default=4)
        for b in rows:
            print("%-*s  @%-24s %s" % (w, b["band"], b["instagram"], b.get("email") or ""))
        print("\n%d of %d bands have a handle" % (len(rows), len(data["bands"])))
        return 0

    if args.backfill:
        # Every lookup so far kept Instagram as a link in a list and never
        # pulled the handle out, so the handles are already on disk -- just
        # not in a form anyone can use as a list. No network needed.
        filled = fixed = 0
        for rec in data["bands"]:
            found = ig_from_profiles(rec)
            current = rec.get("instagram", "")
            if current and not ig_handle("instagram.com/" + current):
                # A handle recorded before the reserved-path check existed.
                print("  dropping bad handle for %-26s @%s" % (rec["band"], current))
                rec["instagram"] = found
                fixed += 1
            elif not current and found:
                rec["instagram"] = found
                filled += 1
            elif "instagram" not in rec:
                rec["instagram"] = found
        if args.dry_run:
            print("would fill %d, correct %d" % (filled, fixed))
            return 0
        with open(OUT, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        total = sum(1 for b in data["bands"] if b.get("instagram"))
        print("backfill: filled %d, corrected %d — %d of %d bands now have a handle"
              % (filled, fixed, total, len(data["bands"])))
        return 0

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
                # Only an address is worth protecting. A record of "nothing
                # found", by hand or otherwise, should not stop a better
                # crawler from having a go later.
                #
                # "Has an email" used to be enough to retire a band forever,
                # which was right when an address was the only thing being
                # collected. Now a handle is wanted too, so a record is only
                # done when it has both -- otherwise the fourteen bands whose
                # address was found first would never be looked at again.
                done = rec and rec.get("email") and rec.get("instagram")
                if done or (rec and not stale(rec, today)):
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
        if args.dump:
            dump_trace()
        TRACE[:] = []
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
