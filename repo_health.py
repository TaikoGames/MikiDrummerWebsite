#!/usr/bin/env python3
"""
repo_health.py — MikiDrummerWebsite audit tool
Run from the root of your MikiDrummerWebsite repo:
    python repo_health.py
"""

import os
import json
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# ─── ANSI Colors ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

PASS  = f"{GREEN}✔ PASS{RESET}"
WARN  = f"{YELLOW}⚠ WARN{RESET}"
FAIL  = f"{RED}✘ FAIL{RESET}"

results = []  # (status, category, message)

def log(status, category, message):
    results.append((status, category, message))
    icon = {"pass": PASS, "warn": WARN, "fail": FAIL}[status]
    print(f"  {icon}  {DIM}[{category}]{RESET} {message}")

def section(title):
    print(f"\n{BOLD}{CYAN}── {title} {'─' * (50 - len(title))}{RESET}")

# ─── 1. REPO STRUCTURE ───────────────────────────────────────────────────────
section("Repo Structure")

REQUIRED_FILES = [
    "index.html",
    "playlist.json",
    "README.md",
    ".gitignore",
    "sitemap.xml",
    "favicon.ico",
]

for f in REQUIRED_FILES:
    if Path(f).exists():
        log("pass", "structure", f"{f} exists")
    else:
        log("warn", "structure", f"{f} is missing")

# ─── 2. PLAYLIST.JSON VALIDATION ─────────────────────────────────────────────
section("playlist.json")

REQUIRED_TRACK_FIELDS = ["title", "artist", "src"]
OPTIONAL_TRACK_FIELDS = ["art", "band"]

playlist_path = Path("playlist.json")
if playlist_path.exists():
    try:
        with open(playlist_path) as f:
            playlist = json.load(f)

        if not isinstance(playlist, list):
            log("fail", "playlist", "playlist.json root should be a JSON array")
        else:
            log("pass", "playlist", f"{len(playlist)} tracks found")
            missing_fields = []
            missing_art = []
            broken_art = []
            broken_src = []

            for i, track in enumerate(playlist):
                label = track.get("title", f"Track #{i+1}")
                for field in REQUIRED_TRACK_FIELDS:
                    if field not in track or not track[field]:
                        missing_fields.append(f"'{label}' missing '{field}'")

                # Check art file exists
                art = track.get("art", "")
                if not art:
                    missing_art.append(label)
                elif not art.startswith("http"):
                    if not Path(art).exists():
                        broken_art.append(f"'{label}' → {art}")

                # Check src file exists (if local)
                src = track.get("src", "")
                if src and not src.startswith("http"):
                    if not Path(src).exists():
                        broken_src.append(f"'{label}' → {src}")

            for m in missing_fields:
                log("fail", "playlist", m)
            for m in missing_art:
                log("warn", "playlist", f"No art for '{m}'")
            for m in broken_art:
                log("fail", "playlist", f"Art file not found: {m}")
            for m in broken_src:
                log("fail", "playlist", f"Audio file not found: {m}")
            if not missing_fields and not broken_art and not broken_src:
                log("pass", "playlist", "All tracks valid")

    except json.JSONDecodeError as e:
        log("fail", "playlist", f"JSON parse error: {e}")
else:
    log("fail", "playlist", "playlist.json not found")

# ─── 3. OPEN GRAPH META TAGS ─────────────────────────────────────────────────
section("Open Graph / SEO (index.html)")

index_path = Path("index.html")
if index_path.exists():
    html = index_path.read_text(encoding="utf-8")

    og_tags = {
        "og:title":       r'<meta\s+property=["\']og:title["\']\s+content=["\'](.*?)["\']',
        "og:description": r'<meta\s+property=["\']og:description["\']\s+content=["\'](.*?)["\']',
        "og:image":       r'<meta\s+property=["\']og:image["\']\s+content=["\'](.*?)["\']',
        "og:url":         r'<meta\s+property=["\']og:url["\']\s+content=["\'](.*?)["\']',
    }

    for tag, pattern in og_tags.items():
        match = re.search(pattern, html, re.IGNORECASE)
        if match and match.group(1).strip():
            log("pass", "og", f"{tag} = {match.group(1)[:60]}")
        else:
            log("fail", "og", f"{tag} missing or empty")

    # Title tag
    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
    if title_match and title_match.group(1).strip():
        log("pass", "seo", f"<title> = {title_match.group(1)[:60]}")
    else:
        log("fail", "seo", "<title> tag missing or empty")

    # Meta description
    desc_match = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE)
    if desc_match:
        desc = desc_match.group(1).strip()
        length = len(desc)
        if 50 <= length <= 160:
            log("pass", "seo", f"Meta description length OK ({length} chars)")
        else:
            log("warn", "seo", f"Meta description length {length} chars (ideal: 50–160)")
    else:
        log("fail", "seo", "Meta description missing")

    # Canonical
    if re.search(r'<link\s+rel=["\']canonical["\']', html, re.IGNORECASE):
        log("pass", "seo", "Canonical URL tag present")
    else:
        log("warn", "seo", "Canonical URL tag missing")

    # Viewport
    if re.search(r'<meta\s+name=["\']viewport["\']', html, re.IGNORECASE):
        log("pass", "seo", "Viewport meta tag present")
    else:
        log("fail", "seo", "Viewport meta tag missing")

else:
    log("fail", "og", "index.html not found")

# ─── 4. ASSET ORPHAN CHECK ───────────────────────────────────────────────────
section("Orphaned Assets")

# Collect all referenced assets from HTML + playlist
referenced = set()

if index_path.exists():
    html = index_path.read_text(encoding="utf-8")
    # src= and href= references
    for match in re.findall(r'(?:src|href)=["\']((?!http|#|mailto)[^"\']+)["\']', html):
        referenced.add(match.lstrip("/"))

if playlist_path.exists():
    try:
        with open(playlist_path) as f:
            playlist = json.load(f)
        for track in playlist:
            for field in ["src", "art"]:
                val = track.get(field, "")
                if val and not val.startswith("http"):
                    referenced.add(val.lstrip("/"))
    except Exception:
        pass

# Walk asset directories
ASSET_DIRS = ["images", "audio", "assets", "img", "media", "covers", "art"]
orphans = []
for d in ASSET_DIRS:
    dp = Path(d)
    if dp.exists():
        for f in dp.rglob("*"):
            if f.is_file():
                rel = str(f).replace("\\", "/")
                if rel not in referenced:
                    orphans.append(rel)

if not orphans:
    log("pass", "assets", "No orphaned asset files detected")
else:
    log("warn", "assets", f"{len(orphans)} possibly orphaned file(s):")
    for o in orphans[:10]:
        print(f"         {DIM}{o}{RESET}")
    if len(orphans) > 10:
        print(f"         {DIM}... and {len(orphans) - 10} more{RESET}")

# ─── 5. EXTERNAL LINK CHECK ──────────────────────────────────────────────────
section("External Links (index.html)")

if index_path.exists():
    html = index_path.read_text(encoding="utf-8")
    ext_links = re.findall(r'href=["\'](https?://[^"\']+)["\']', html)
    ext_links = list(set(ext_links))

    if not ext_links:
        log("warn", "links", "No external links found in index.html")
    else:
        print(f"  {DIM}Checking {len(ext_links)} external link(s)...{RESET}")
        for url in ext_links:
            try:
                req = urllib.request.Request(url, method="HEAD",
                    headers={"User-Agent": "Mozilla/5.0 (repo-health-check)"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    code = resp.status
                    if code < 400:
                        log("pass", "links", f"{code} {url}")
                    else:
                        log("fail", "links", f"{code} {url}")
            except urllib.error.HTTPError as e:
                log("warn", "links", f"HTTP {e.code} {url}")
            except Exception as e:
                log("warn", "links", f"Could not reach {url} ({type(e).__name__})")
else:
    log("fail", "links", "index.html not found, skipping link check")

# ─── 6. SITEMAP CHECK ────────────────────────────────────────────────────────
section("Sitemap")

sitemap_path = Path("sitemap.xml")
if sitemap_path.exists():
    content = sitemap_path.read_text(encoding="utf-8")
    if "<urlset" in content:
        urls = re.findall(r"<loc>(.*?)</loc>", content)
        log("pass", "sitemap", f"sitemap.xml valid, {len(urls)} URL(s) listed")
        for u in urls:
            print(f"         {DIM}{u}{RESET}")
    else:
        log("warn", "sitemap", "sitemap.xml exists but may be malformed (no <urlset>)")
else:
    log("warn", "sitemap", "sitemap.xml not found")

# ─── 7. .GITIGNORE SANITY ────────────────────────────────────────────────────
section(".gitignore")

gitignore_path = Path(".gitignore")
if gitignore_path.exists():
    content = gitignore_path.read_text()
    checks = {
        ".DS_Store": ".DS_Store",
        "node_modules": "node_modules/",
        "*.log": "*.log files",
    }
    for key, label in checks.items():
        if key in content:
            log("pass", "gitignore", f"{label} ignored")
        else:
            log("warn", "gitignore", f"{label} not in .gitignore")
else:
    log("warn", "gitignore", ".gitignore not found")

# ─── SUMMARY ─────────────────────────────────────────────────────────────────
print(f"\n{BOLD}{'═' * 58}{RESET}")
print(f"{BOLD}  REPO HEALTH SUMMARY — {datetime.now().strftime('%Y-%m-%d %H:%M')}{RESET}")
print(f"{BOLD}{'═' * 58}{RESET}")

counts = {"pass": 0, "warn": 0, "fail": 0}
for status, _, _ in results:
    counts[status] += 1

total = sum(counts.values())
print(f"  {GREEN}{BOLD}{counts['pass']} passed{RESET}   "
      f"{YELLOW}{BOLD}{counts['warn']} warnings{RESET}   "
      f"{RED}{BOLD}{counts['fail']} failed{RESET}   "
      f"{DIM}({total} checks total){RESET}")

if counts["fail"] == 0 and counts["warn"] == 0:
    print(f"\n  {GREEN}{BOLD}All clear! Repo is healthy. 🥁{RESET}")
elif counts["fail"] == 0:
    print(f"\n  {YELLOW}No failures, but {counts['warn']} warning(s) worth a look.{RESET}")
else:
    print(f"\n  {RED}Fix the {counts['fail']} failure(s) above before next deploy.{RESET}")

print()
