#!/usr/bin/env python3
"""Put the newsletter's subscriber list where the admin page can read it,
without putting anyone's email address in public.

This repository is public: anything committed, and anything a GitHub job
prints, can be read by anyone. Subscriber addresses must not be either. So the
list is encrypted before it is written:

  * The admin page, on each device you set it up on, makes a key pair. The
    private half never leaves that browser. The public half is committed to
    data/newsletter-viewers.json (a public key is safe to publish; it can only
    lock, not unlock).
  * This script fetches the "Punk BC — monthly digest" group from MailerLite,
    encrypts it with a fresh random AES-256-GCM key, and locks that key
    separately for each device's public key (RSA-OAEP, SHA-256).
  * The result, data/newsletter-subs.enc.json, is ciphertext plus per-status
    counts. Only a device holding one of the private keys can read the list.

Nothing here ever prints an address: the job log shows counts only.

Usage:
  python3 tools/newsletter_subs.py              # needs MAILERLITE_API_KEY
  python3 tools/newsletter_subs.py --self-test
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from send_digest import GROUP_NAME, call, find_group  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VIEWERS = ROOT / "data" / "newsletter-viewers.json"
OUT = ROOT / "data" / "newsletter-subs.enc.json"
STATUSES = ("active", "unconfirmed", "unsubscribed", "bounced", "junk")


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def key_id(spki: bytes) -> str:
    return hashlib.sha256(spki).hexdigest()[:16]


def fetch_subscribers(key: str, group_id: str, opener=None) -> list[dict]:
    """Every member of the group, in every status, trimmed to what the admin
    page shows."""
    out = []
    for status in STATUSES:
        cursor = ""
        for _ in range(200):                       # 200 pages x 1000 is plenty
            q = f"/groups/{group_id}/subscribers?limit=1000&filter[status]={status}"
            if cursor:
                q += f"&cursor={cursor}"
            got = call("GET", q, key, opener=opener)
            for s in got.get("data", []):
                fields = s.get("fields") or {}
                name = " ".join(x for x in (fields.get("name"), fields.get("last_name")) if x)
                out.append({
                    "email": s.get("email", ""),
                    "name": name,
                    "status": s.get("status") or status,
                    "subscribed": s.get("subscribed_at") or s.get("created_at") or "",
                    "unsubscribed": s.get("unsubscribed_at") or "",
                    "source": s.get("source") or "",
                })
            cursor = (got.get("meta") or {}).get("next_cursor") or ""
            if not cursor:
                break
    out.sort(key=lambda s: s["subscribed"], reverse=True)
    return out


def encrypt(subs: list[dict], viewers: list[dict]) -> dict:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    plain = json.dumps(subs, ensure_ascii=False).encode()
    aes = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    data = AESGCM(aes).encrypt(iv, plain, None)       # ciphertext || tag, as WebCrypto expects
    oaep = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    locks = []
    for v in viewers:
        spki = base64.b64decode(v["spki"])
        pub = serialization.load_der_public_key(spki)
        locks.append({"key_id": key_id(spki), "key": b64(pub.encrypt(aes, oaep))})
    counts = {st: sum(1 for s in subs if s["status"] == st) for st in STATUSES}
    return {
        "_readme": "Encrypted Punk BC newsletter subscriber list. Only devices set up in the "
                   "admin page can read it; see tools/newsletter_subs.py.",
        "v": 1,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "group": GROUP_NAME,
        "counts": {k: n for k, n in counts.items() if n},
        "total": len(subs),
        "locks": locks,
        "iv": b64(iv),
        "data": b64(data),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    if ap.parse_args().self_test:
        return self_test()
    key = os.environ.get("MAILERLITE_API_KEY", "").strip()
    if not key:
        raise SystemExit("MAILERLITE_API_KEY is not set (repository secret).")
    viewers = (json.loads(VIEWERS.read_text()) if VIEWERS.exists() else {}).get("keys", [])
    if not viewers:
        raise SystemExit("No device is set up to read the list yet: press 'Show subscribers' "
                         "in the admin page first, which adds this device's key.")
    subs = fetch_subscribers(key, find_group(key, GROUP_NAME))
    doc = encrypt(subs, viewers)
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    # counts only: this log is public
    print(f"{doc['total']} subscribers in {GROUP_NAME!r}: {doc['counts']}; "
          f"readable on {len(viewers)} device(s)")
    return 0


def self_test() -> int:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    checks = []

    class Resp:
        def __init__(self, payload): self.payload = json.dumps(payload).encode()
        def read(self): return self.payload
        def __enter__(self): return self
        def __exit__(self, *a): return False

    pages = {
        ("active", ""): {"data": [{"email": "a@x.test", "status": "active", "subscribed_at": "2026-11-01 10:00:00",
                                   "fields": {"name": "Ann"}}], "meta": {"next_cursor": "C2"}},
        ("active", "C2"): {"data": [{"email": "b@x.test", "status": "active", "subscribed_at": "2026-11-05 10:00:00"}],
                           "meta": {"next_cursor": None}},
        ("unsubscribed", ""): {"data": [{"email": "c@x.test", "status": "unsubscribed",
                                         "subscribed_at": "2026-10-01 10:00:00",
                                         "unsubscribed_at": "2026-10-20 10:00:00"}], "meta": {}},
    }

    def fake(req):
        from urllib.parse import parse_qs, urlsplit
        q = parse_qs(urlsplit(req.full_url).query)
        st, cur = q["filter[status]"][0], (q.get("cursor") or [""])[0]
        return Resp(pages.get((st, cur), {"data": [], "meta": {}}))

    subs = fetch_subscribers("k", "1", opener=fake)
    checks.append(("all statuses and pages read", [s["email"] for s in subs] == ["b@x.test", "a@x.test", "c@x.test"]))
    checks.append(("name kept", subs[1]["name"] == "Ann"))

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    spki = priv.public_key().public_bytes(serialization.Encoding.DER,
                                          serialization.PublicFormat.SubjectPublicKeyInfo)
    doc = encrypt(subs, [{"spki": b64(spki)}])
    text = json.dumps(doc)
    checks.append(("no address in the output", "@x.test" not in text))
    lock = doc["locks"][0]
    checks.append(("lock names the device key", lock["key_id"] == key_id(spki)))
    oaep = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    aes = priv.decrypt(base64.b64decode(lock["key"]), oaep)
    back = json.loads(AESGCM(aes).decrypt(base64.b64decode(doc["iv"]), base64.b64decode(doc["data"]), None))
    checks.append(("the device key opens it", back == subs))
    checks.append(("counts by status", doc["counts"] == {"active": 2, "unsubscribed": 1} and doc["total"] == 3))

    for name, ok in checks:
        print(("  [ok] " if ok else "  [FAIL] ") + name)
    bad = sum(1 for _, ok in checks if not ok)
    print("self-test:", "passed" if not bad else f"{bad} FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
