#!/usr/bin/env python3
"""Telling a website from a piece of markup that happens to be a URL.

A page's HTML is full of http:// strings that are not links to anywhere: XML
namespaces, schema vocabularies, script hosts, analytics beacons. A scraper
that collects "every URL on the page" collects all of them, and they look
exactly like a band's website until you try to visit one.

That is not hypothetical here. The contact finder stored them, and the band
page builder published them: 72 of 114 band pages went out with a "Facebook"
button pointing at http://www.facebook.com/2008/fbml -- the XML namespace
declared in the page's own <html> tag -- and a "Site" button pointing at
opengraphprotocol.org. The same URLs went into each page's schema.org
`sameAs`, which is the field Google reads to work out which accounts belong
to whom, so the structured data was asserting that a Vancouver punk band's
official profiles include an XML namespace.

Both tools need the same judgement, so it lives here rather than in two
denylists that drift apart.

    python3 tools/weblinks.py --self-test
"""

import re
import sys
import urllib.parse

# Namespaces and vocabularies. These appear in xmlns and itemtype attributes
# and in JSON-LD @context; none of them is a place.
NAMESPACE = re.compile(
    r"^(schema\.org|opengraphprotocol\.org|ogp\.me|purl\.org|xmlns\.com|"
    r"rdfs?\.org|creativecommons\.org/ns)", re.I)

# Infrastructure: scripts, fonts, analytics, payment widgets, image CDNs.
# Present on the page, never somewhere a reader goes.
PLUMBING = re.compile(
    r"(^|\.)(stripe\.com|paypal\.com|googleapis\.com|gstatic\.com|"
    r"google-analytics\.com|googletagmanager\.com|doubleclick\.net|"
    r"cloudflare\.com|cloudfront\.net|jsdelivr\.net|unpkg\.com|jquery\.com|"
    r"bootstrapcdn\.com|fontawesome\.com|gravatar\.com|w3\.org|"
    r"schema\.org|opengraphprotocol\.org|sentry\.io|sentry-cdn\.com|"
    r"newrelic\.com|hotjar\.com|segment\.com|intercom\.io)$", re.I)

# Platform boilerplate: a path that exists on every site built with the tool,
# and identifies the tool rather than the band.
BOILERPLATE = re.compile(
    r"(/2008/fbml|/1999/xhtml|/xml/|/ns#|/wp-json|/feed/?$|"
    r"^https?://(new\.express\.adobe\.com|www\.blogger\.com))", re.I)

# Typos worth catching because they are somebody's dead link, not a site.
TYPO = re.compile(r"(^|\.)(instargam\.com|instagarm\.com|faceboook\.com)$", re.I)


def host(url):
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def is_real_site(url):
    """True when a person could click this and arrive somewhere.

    Deliberately strict about the path as well as the host: facebook.com is a
    real place, and facebook.com/2008/fbml is the namespace URI that every
    Facebook-aware page declares in its <html> tag.
    """
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return False
    h = host(url)
    if not h or "." not in h:
        return False
    if NAMESPACE.match(h) or PLUMBING.search(h) or TYPO.search(h):
        return False
    if BOILERPLATE.search(url):
        return False
    return True


def self_test():
    fails = []

    def eq(got, want, what):
        if got != want:
            fails.append("%s: got %r want %r" % (what, got, want))

    # An error-reporting DSN, stored as a band's website. It carries the
    # site's own ingest key in the userinfo, which is another reason not to
    # be republishing it.
    eq(is_real_site("https://7c33659f@o363271.ingest.us.sentry.io"), False,
       "reject a Sentry DSN")

    # Everything that actually shipped onto the band pages.
    for u in ["http://www.facebook.com/2008/fbml",
              "http://opengraphprotocol.org",
              "https://schema.org",
              "http://www.w3.org",
              "http://www.w3.org/1999/xhtml",
              "https://js.stripe.com",
              "https://new.express.adobe.com",
              "http://instargam.com"]:
        eq(is_real_site(u), False, "reject %s" % u)

    # Real destinations, including the social pages a band page should keep --
    # this filter is about whether a URL is a place, not whether a link from
    # it would pass ranking signal.
    for u in ["https://alienboys.ca/",
              "https://www.facebook.com/alienboysvancouver",
              "https://blasphemy.bandcamp.com/",
              "https://www.instagram.com/mikibdrummer/",
              "https://rickshawtheatre.com",
              "http://themenzingers.com",
              "https://www.kindacoolrecords.com/diejob"]:
        eq(is_real_site(u), True, "accept %s" % u)

    # Not URLs at all.
    for u in ["", None, "mailto:x@y.com", "not a url", "/relative/path",
              "javascript:void(0)", "http://", "https://localhost"]:
        eq(is_real_site(u), False, "reject non-url %r" % u)

    for f in fails:
        print("FAIL", f)
    print("%d checks, %d failed" % (24, len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv else 0)
