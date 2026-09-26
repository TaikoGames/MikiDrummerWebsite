#!/usr/bin/env python3
"""Turn a song into something you can play along to.

A rhythm game needs to know when every note lands. The usual answer is that
somebody charts it by hand, which is hours per song and is why most band
rhythm games have four tracks in them.

These songs already contain the answer. Miki played the drums on them, so the
drums are in the recording, and finding them is onset detection rather than
authorship: split the spectrum into the bands the kit lives in, look for the
moment energy jumps in each, and that is a chart of what was actually played.
Kick in the low band, snare in the crack around 1.5-4 kHz, cymbals up top.

Deliberately numpy only -- no librosa, no torch. The whole job is a windowed
FFT and a peak picker, and a dependency that pulls in half a gigabyte to do
that is a dependency that breaks this script in a year.

Runs on a runner, where ffmpeg is: see .github/workflows/beatmaps.yml.

    python3 tools/build_beatmaps.py --self-test
    python3 tools/build_beatmaps.py audio/granite/pony-up.mp3
"""

import json
import os
import subprocess
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "beatmaps")

SR = 22050          # plenty: the top band of interest is ~8 kHz
FRAME = 1024
HOP = 256           # 11.6 ms resolution, finer than anyone can play to

# Where each piece of the kit lives, in Hz. Generous and overlapping on
# purpose -- a tom and a kick share a lot of low end, and it is better to
# catch a note in two bands and drop one than to miss it entirely.
BANDS = [
    ("kick",  20,   160),
    ("snare", 1200, 4200),
    ("hat",   6000, 10500),
]

# Nothing human plays two of the same limb closer than this. It is also what
# stops one cymbal wash becoming forty notes.
MIN_GAP = {"kick": 0.150, "snare": 0.110, "hat": 0.085}

# Per lane, notes per second, because one global budget cannot tell a flood
# apart from a part. The first version had a single cap and spent it hats-first
# -- which produced charts of 948 kicks and 2 hi-hats, since a punk bass guitar
# playing eighths reads as a kick drum all the way through and the timekeeping
# the game is actually about got decimated to nothing.
#
# The kick is capped hardest for exactly that reason: a low-band onset every
# 240 ms for three minutes is a bass player, not a foot.
PER_LANE_MAX = {"kick": 3.2, "snare": 3.4, "hat": 5.0}

# A last backstop across all lanes, so an unusual track cannot add up to a
# strobe even with each lane inside its own budget.
MAX_NOTES_PER_SEC = 9.0

# The share of a frame's total flux a band must hold for the onset to be its
# own rather than splatter from a transient elsewhere. The kick needs the most
# because everything sharp leaks downward.
DOMINANCE = {"kick": 0.18, "snare": 0.05, "hat": 0.04}


def slugify(name):
    """The filename a browser will ask for.

    Folds to ASCII first, which is the whole point. Python's isalnum() counts
    "í" as alphanumeric and keeps it; the page builds its slug with
    /[^a-z0-9]+/ and does not. So "Sebastopol García" was written as
    sebastopol-garcía.json and fetched as sebastopol-garc-a.json, the fetch
    404'd, and the song quietly disappeared from the menu with no error
    anywhere -- one of twelve, which is exactly the kind of gap nobody counts.
    """
    import unicodedata
    ascii_name = (unicodedata.normalize("NFKD", name)
                  .encode("ascii", "ignore").decode("ascii"))
    slug = "".join(c if c.isalnum() else "-" for c in ascii_name.lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def decode(path, sr=SR):
    """MP3 in, mono float array out, via ffmpeg because nothing in the
    standard library reads MP3."""
    import numpy as np
    wav = "/tmp/beatmap-src.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-i", path,
                    "-ac", "1", "-ar", str(sr), wav],
                   check=True, capture_output=True)
    with wave.open(wav, "rb") as w:
        n = w.getnframes()
        raw = w.readframes(n)
        width = w.getsampwidth()
    if width != 2:
        raise SystemExit("expected 16-bit PCM from ffmpeg, got %d bytes" % width)
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    os.remove(wav)
    return x


def spectrogram(x):
    """Magnitude spectrogram. Hann-windowed, which matters: without a window
    every frame boundary looks like a transient and the whole track reads as
    one long drum fill."""
    import numpy as np
    frames = 1 + max(0, (len(x) - FRAME) // HOP)
    win = np.hanning(FRAME).astype(np.float32)
    # A strided view rather than a python loop over 15,000 frames.
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(frames)[:, None]
    S = np.abs(np.fft.rfft(x[idx] * win, axis=1))
    return S


def band_flux(S, lo, hi, sr=SR):
    """Spectral flux inside one band: how much energy appeared since the last
    frame. Rising edges only -- a note starting is an onset, a note ending is
    not, and counting both doubles every hit."""
    import numpy as np
    freqs = np.fft.rfftfreq(FRAME, 1.0 / sr)
    sel = (freqs >= lo) & (freqs <= hi)
    band = S[:, sel]
    diff = np.diff(band, axis=0, prepend=band[:1])
    flux = np.maximum(diff, 0).sum(axis=1)
    return flux


def pick(flux, min_gap, total=None, dominance=0.0, sr=SR, hop=HOP, sensitivity=1.4):
    """Peak-pick with a moving threshold.

    A fixed threshold cannot work on real music: a quiet verse and a loud
    chorus are the same song, and any level that catches the verse turns the
    chorus into noise. The threshold follows the local mean instead, so it is
    the shape of the transient that matters rather than how loud the band
    happened to be playing.

    `total` and `dominance` are what stop a cymbal being heard as a kick. A
    sharp transient splatters across the whole spectrum, so the low band does
    see a 7 kHz tick -- it just sees a rounding error of one. Requiring the
    band to hold a real share of the frame's flux tells the two apart; band
    energy on its own cannot.
    """
    import numpy as np
    if not len(flux):
        return []

    # Silence must produce silence. Without this the threshold is zero, every
    # flat frame satisfies `>= 0`, and three seconds of nothing charts as
    # twenty-nine notes.
    peak = float(flux.max())
    if peak <= 1e-8:
        return []
    floor = peak * 0.02

    # Local mean over ~0.7 s, via a cumulative sum so it stays O(n).
    w = max(3, int(0.7 * sr / hop))
    pad = np.pad(flux, (w // 2, w // 2), mode="edge")
    csum = np.cumsum(np.insert(pad, 0, 0))
    local = (csum[w:] - csum[:-w]) / float(w)
    local = local[:len(flux)]
    thresh = np.maximum(local * sensitivity + flux.mean() * 0.06, floor)

    gap = int(min_gap * sr / hop)
    out, last = [], -10 ** 9
    for i in range(1, len(flux) - 1):
        if flux[i] <= thresh[i]:
            continue
        if flux[i] < flux[i - 1] or flux[i] < flux[i + 1]:
            continue                       # only local maxima
        if total is not None and dominance > 0:
            tot = total[i]
            if tot <= 0 or flux[i] / tot < dominance:
                continue                   # splatter from another band
        if i - last < gap:
            # Keep the stronger of two hits too close to both be real.
            if out and flux[i] > flux[last]:
                out[-1] = i
                last = i
            continue
        out.append(i)
        last = i
    return [round(i * hop / float(sr), 4) for i in out]


def thin(notes, duration):
    """Drop notes until the chart is playable, one lane at a time.

    Onset detection is honest about the recording, and the recording is a
    drummer using four limbs -- often over a bass guitar that the low band
    cannot tell from a kick drum. A chart that asks one person with two hands
    to reproduce all of that is not difficult, it is broken.

    Each lane is thinned against its own budget rather than against a shared
    one. The shared version was worse than it looked: it spent the whole
    budget hats-first, so the charts came out at 948 kicks and 2 hi-hats --
    every bass note kept, and the timekeeping that a drum game is actually
    about thrown away.

    Decimation keeps every Nth note, so a sixteenth-note line survives at half
    or a third of its density rather than losing a random half of itself.
    """
    if duration <= 0 or not notes:
        return notes

    by_lane = {}
    for n in notes:
        by_lane.setdefault(n["lane"], []).append(n)

    for lane, row in by_lane.items():
        budget = max(1, int(duration * PER_LANE_MAX.get(lane, 4.0)))
        while len(row) > budget and len(row) > 2:
            row = row[::2]
        by_lane[lane] = row

    out = sorted([n for row in by_lane.values() for n in row], key=lambda n: n["t"])

    # Backstop: if the lanes together are still a strobe, thin whichever is
    # densest, repeatedly, so the balance between them is preserved.
    total_budget = max(1, int(duration * MAX_NOTES_PER_SEC))
    while len(out) > total_budget:
        lane = max(by_lane, key=lambda k: len(by_lane[k]))
        if len(by_lane[lane]) <= 2:
            break
        by_lane[lane] = by_lane[lane][::2]
        out = sorted([n for row in by_lane.values() for n in row], key=lambda n: n["t"])
    return out


def chart(path):
    import numpy as np
    x = decode(path)
    duration = len(x) / float(SR)
    S = spectrogram(x)
    total = band_flux(S, 0, SR / 2)
    notes = []
    for lane, lo, hi in BANDS:
        f = band_flux(S, lo, hi)
        for t in pick(f, MIN_GAP[lane], total=total, dominance=DOMINANCE[lane]):
            notes.append({"t": t, "lane": lane})
    notes.sort(key=lambda n: n["t"])
    notes = thin(notes, duration)
    return {"duration": round(duration, 2), "notes": notes}


def self_test():
    import numpy as np
    fails = []

    def ok(cond, what):
        if not cond:
            fails.append(what)

    # A click track: silence with a 60 Hz thump every half second. A detector
    # that cannot find these cannot find a kick drum.
    sr = SR
    x = np.zeros(int(sr * 5), dtype=np.float32)
    hits = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    for t in hits:
        i = int(t * sr)
        env = np.exp(-np.linspace(0, 8, 2000)).astype(np.float32)
        tone = np.sin(2 * np.pi * 60 * np.arange(2000) / sr).astype(np.float32)
        x[i:i + 2000] += env * tone
    S = spectrogram(x)
    found = pick(band_flux(S, 20, 160), 0.11)
    ok(abs(len(found) - len(hits)) <= 1, "click track: found %d of %d" % (len(found), len(hits)))
    if found:
        err = max(min(abs(f - h) for h in hits) for f in found)
        ok(err < 0.04, "click track timing within 40 ms (worst %.0f ms)" % (err * 1000))

    # Silence must produce nothing. A detector that invents notes in silence
    # invents them everywhere.
    quiet = np.zeros(int(sr * 3), dtype=np.float32)
    ok(len(pick(band_flux(spectrogram(quiet), 20, 160), 0.11)) == 0, "silence stays empty")

    # Band separation: a 7 kHz tick must not land in the kick lane.
    y = np.zeros(int(sr * 3), dtype=np.float32)
    for t in (0.5, 1.0, 1.5):
        i = int(t * sr)
        env = np.exp(-np.linspace(0, 20, 900)).astype(np.float32)
        y[i:i + 900] += env * np.sin(2 * np.pi * 7000 * np.arange(900) / sr).astype(np.float32)
    Sy = spectrogram(y)
    ok(len(pick(band_flux(Sy, 6000, 10500), 0.085)) >= 3, "hat band hears a 7 kHz tick")
    ok(len(pick(band_flux(Sy, 20, 160), 0.11, total=band_flux(Sy, 0, SR / 2),
                dominance=DOMINANCE["kick"])) == 0, "kick band ignores a 7 kHz tick")

    # Thinning must respect the budget and keep the notes sorted.
    dense = [{"t": i * 0.02, "lane": "hat"} for i in range(1000)]
    out = thin(list(dense), 10.0)
    ok(len(out) <= int(10.0 * PER_LANE_MAX["hat"]) + 1, "hats thinned to their lane budget (%d)" % len(out))

    # The case the first version got wrong: a flooded kick lane must not be
    # paid for out of the hi-hats.
    mixed = ([{"t": i * 0.05, "lane": "kick"} for i in range(400)] +
             [{"t": i * 0.05 + 0.02, "lane": "hat"} for i in range(400)])
    out2 = thin(sorted(mixed, key=lambda n: n["t"]), 20.0)
    hats = sum(1 for n in out2 if n["lane"] == "hat")
    kicks = sum(1 for n in out2 if n["lane"] == "kick")
    ok(hats >= 40, "hats survive a flooded kick lane (%d hats, %d kicks)" % (hats, kicks))
    ok(kicks <= int(20.0 * PER_LANE_MAX["kick"]) + 1, "kick lane capped (%d)" % kicks)
    ok(out == sorted(out, key=lambda n: n["t"]), "still in time order after thinning")
    ok(thin([{"t": 1, "lane": "kick"}], 10.0) == [{"t": 1, "lane": "kick"}], "sparse chart untouched")

    # The same table as tools/drum_game_test.mjs. Both sides assert against
    # these literal strings rather than against each other's logic -- checking
    # one implementation against a copy of the other is exactly how
    # "Sebastopol Garcia" 404'd while both tests were green.
    SLUGS = {
        "Sebastopol García.mp3": "sebastopol-garcia",
        "Per mi.mp3": "per-mi",
        "04 - Skamen.mp3": "04-skamen",
        "Bajo el nivel del mal.mp3": "bajo-el-nivel-del-mal",
        "LandSea.mp3": "landsea",
        "Café Über.mp3": "cafe-uber",
    }
    import os.path as _p
    for name, want in SLUGS.items():
        got = slugify(_p.splitext(name)[0])
        ok(got == want, "slug for %s: got %r want %r" % (name, got, want))

    for f in fails:
        print("FAIL", f)
    print("%d checks, %d failed" % (16, len(fails)))
    return 1 if fails else 0


def main():
    if "--self-test" in sys.argv:
        return self_test()
    srcs = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not srcs:
        print("give it one or more audio files", file=sys.stderr)
        return 2
    os.makedirs(OUT, exist_ok=True)
    for src in srcs:
        slug = slugify(os.path.splitext(os.path.basename(src))[0])
        data = chart(os.path.join(ROOT, src) if not os.path.isabs(src) else src)
        data["audio"] = "/" + src.replace("\\", "/")
        data["slug"] = slug
        path = os.path.join(OUT, slug + ".json")
        with open(path, "w") as fh:
            json.dump(data, fh, separators=(",", ":"))
        counts = {}
        for n in data["notes"]:
            counts[n["lane"]] = counts.get(n["lane"], 0) + 1
        print("%-34s %5.0fs  %4d notes  (%s)  %.0f KB"
              % (slug, data["duration"], len(data["notes"]),
                 " ".join("%s %d" % (k, v) for k, v in sorted(counts.items())),
                 os.path.getsize(path) / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
