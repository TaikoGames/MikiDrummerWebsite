#!/usr/bin/env python3
"""Turn a song into something you can play along to.

A rhythm game needs to know when every note lands. The usual answer is that
somebody charts it by hand, which is hours per song and is why most band
rhythm games have four tracks in them.

These songs already contain the answer. Miki played the drums on them, so the
drums are in the recording, and finding them is onset detection rather than
authorship.

HOW THIS WORKS, AND WHY THE FIRST VERSION DID NOT
-------------------------------------------------
The first version ran three independent peak-pickers, one per frequency band,
each with its own hand-tuned threshold, and then thinned whatever came out
until it fit a density cap. Every chart it produced came out pinned at that
cap -- 7 to 9 notes per second, on all twelve songs -- which is the signature
of a detector that is saturating rather than detecting. When the cap is what
decides, the thinner is the composer, and the thinner kept every Nth note off
a list of mostly false onsets. Hence "the notes are very random": they were.

Four things changed.

1. TIME. A spectrogram frame covering samples [i*HOP, i*HOP+FRAME) was being
   converted to time as i*HOP/SR -- the START of the window. A drum hit is
   heard when it is somewhere under the window, so the flux peaks around the
   window's CENTRE. Measured against synthetic hits at known times, the old
   convention put every note 55-74 ms EARLY. That is most of a judgement
   window of systematic error in every chart, before anything else went
   wrong. Frames now convert from their centre, and the residual detector lag
   is measured (see BIAS) rather than guessed.

2. WHAT COUNTS AS AN ONSET. Plain spectral flux says "energy went up", and in
   a punk mix energy goes up on every guitar strum, every vocal syllable and
   every frame of a tremolo. This uses SuperFlux: log-compressed magnitudes,
   differenced against a frequency-maximum-filtered earlier frame, which is
   what stops a sustained wobbling note from reading as an onset on every
   frame of its life.

3. A BEAT GRID. Songs have a pulse, and a drummer plays on it. The onset
   envelope is autocorrelated for a tempo, then a dynamic-programming beat
   tracker (Ellis) lays actual beats down, which follows a band speeding up in
   a way a fixed grid cannot. Sixteenth-note slots are interpolated between
   consecutive tracked beats. An onset that does not land near a slot is
   thrown away, and each slot holds at most one note per lane. That is what
   turns a list of transients into something that feels like the song: it
   bounds the density by the music rather than by a cap, and it makes the
   notes regular enough to lock into.

4. ONE DETECTOR, THEN CLASSIFY. Rather than three detectors arguing, onsets
   are found once on the full mix -- one threshold, easy to reason about --
   and each one is then ASSIGNED to the lane whose band rose most, measured
   in that band's own units. Comparing bands against each other is robust;
   comparing each against an absolute threshold was not. It also means one
   hit can never become three notes.

Deliberately numpy only -- no librosa, no torch. The whole job is a windowed
FFT, an autocorrelation and some dynamic programming, and a dependency that
pulls in half a gigabyte to do that is a dependency that breaks this script in
a year.

Runs on a runner, where ffmpeg is: see .github/workflows/beatmaps.yml.

    python3 tools/build_beatmaps.py --self-test
    python3 tools/build_beatmaps.py audio/granite/pony-up.mp3
    python3 tools/build_beatmaps.py --preview 60 audio/NoOther.mp3
        ^ writes an MP3 of the song with a click on every charted note, which
          is the only way to actually check a chart against the song it came
          from. A number you can compute is not the same as a thing you can
          hear, and this one you can hear.
"""

import json
import os
import subprocess
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "beatmaps")

SR = 22050          # plenty: the top band of interest is ~11 kHz
FRAME = 2048        # 93 ms window -- long enough to resolve a 40 Hz kick
HOP = 256           # 11.6 ms resolution, finer than anyone can play to

# Where each piece of the kit lives, in Hz.
#
# The kick window is higher than the textbook answer and was chosen by
# measurement, not by where a kick drum's fundamental is. Sweeping candidate
# windows and scoring each by how much its onset strength actually moves at
# onsets, 25-130 Hz turned out nearly flat on two of these masters -- p90 of
# 1.2 and 1.6 standard deviations, meaning no detectable transient at all --
# while 60-200 Hz gave 1.7 and 3.7 on the same songs. Mastering compression
# glues the very bottom of a loud mix into a constant, and what survives as a
# transient is the upper half of the thump. Going higher still (150-400 Hz)
# scores better again and is worthless: that is bass guitar and guitar
# low-mids, and it would chart the bass player.
BANDS = [
    ("kick",  60,   200),
    ("snare", 1400, 5200),
    ("hat",   7000, 11000),
]

# An onset where no band rises by this much is not a drum we can name -- most
# often a guitar chord or a vocal, which live between the kick band and the
# snare band and show up in the full-mix envelope without showing up in any of
# these. Dropping them is most of the difference between charting a kit and
# charting a band.
DROP_Z = 0.5

# A kick landing under a cymbal is the single most common thing in this music
# and the thing a one-lane-per-onset rule loses every time, because the cymbal
# wins the argmax. So the kick gets a second chance: if it rose this hard, it
# gets charted even when something else rose harder.
KICK_Z = 2.5

# Timed from the centre of the analysis window, SuperFlux reports a hit
# slightly EARLY -- the transient is already lifting the window before it
# reaches the middle of it. Measured, not guessed: --self-test drives
# synthetic kick, snare and cymbal hits at known times through the real
# detector and checks the residual. All three come back within two
# milliseconds of each other, which is why one constant covers all of them.
BIAS = 0.018

# Tempo search. Wide enough for a slow one, narrow enough not to lock onto a
# half-bar. When it is ambiguous the faster reading is the safer one: a grid
# that is too fine only lets a few extra notes through, while one that is too
# coarse throws away real sixteenths and cannot be recovered from.
BPM_LO, BPM_HI, BPM_CENTRE = 100.0, 220.0, 160.0

SUBDIV = 8          # thirty-second-note slots between tracked beats

# How far off its slot an onset may sit and still count, as a share of the
# slot. At 0.5 the slots tile without gaps, so nothing is rejected for
# falling between them -- the grid's job here is to regularise timing, not to
# filter. It used to be a filter, at a quarter of the notes' expense: a
# sixteenth grid with a 0.30 window threw away everything more than 37 ms off
# a sixteenth, which is fills, flams, ghost notes, and anything played with a
# push. Thirty-seconds halve the spacing, so a roll no longer collapses into
# one note per sixteenth either.
SNAP = 0.5

# Nothing human plays two of the same limb closer than this. Expressed
# against the grid rather than in fixed seconds, because a fixed floor is a
# different musical interval at every tempo: 100 ms is comfortably under a
# sixteenth at 120 BPM and LONGER than one at 215, so on the fast songs it was
# deleting every sixteenth-note passage in the track. Bajo el nivel del mal
# had the worst recall of the twelve for exactly this reason.
# How hard the full-mix detector listens. Lower finds more; precision against
# an independent reference stays above 95%, which is what says the extra are
# real hits rather than invented ones.
MIX_SENS = 1.1

MIN_GAP_FLOOR = 0.050          # what two strokes of one limb really cost
MIN_GAP_SLOTS = 0.9            # ...but never closer than this many grid slots

# Each band also detects on its own, to catch the limbs that never win the
# full-mix argmax. Sensitivity and a floor on how far that band has to have
# risen, per lane, because they are not equally clean: the cymbal band is the
# quietest and the one with least else living in it, the kick band is shared
# with the bass guitar.
BAND_SENS = {"kick": 1.15, "snare": 1.15, "hat": 1.15}
BAND_Z = {"kick": 1.5, "snare": 1.3, "hat": 1.0}

# Per lane, notes per BEAT rather than per second, because that is the unit
# the music is in -- a cap in seconds means a fast song gets a thinner part
# than a slow one for no musical reason.
#
# These are what hold cross-talk down now that every band detects on its own.
# A snare puts energy in the cymbal band and a bass guitar puts it in the kick
# band, so all three bands will happily report more than a drummer played.
# The numbers are what the limbs can actually do: eighths on the hat, a
# backbeat plus fills on the snare, and a kick that can double up but is not
# playing sixteenths for three minutes.
PER_LANE_PER_BEAT = {"kick": 3.0, "snare": 2.5, "hat": 3.5}
MAX_NOTES_PER_BEAT = 6.5


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
        raw = w.readframes(w.getnframes())
        width = w.getsampwidth()
    if width != 2:
        raise SystemExit("expected 16-bit PCM from ffmpeg, got %d bytes" % width)
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    os.remove(wav)
    return x


def frame_time(i):
    """Frame index to seconds.

    From the CENTRE of the analysis window, plus the detector's own bias. The
    window start was the old convention and it put every note in every chart
    55 to 74 ms early -- a systematic error bigger than the Perfect window,
    applied to all of them equally, which is exactly the kind of bug that
    feels like "the detection is bad" rather than "the clock is wrong".
    """
    return (i * HOP + FRAME / 2.0) / float(SR) + BIAS


def spectrogram(x):
    """Magnitude spectrogram. Hann-windowed, which matters: without a window
    every frame boundary looks like a transient and the whole track reads as
    one long drum fill."""
    import numpy as np
    frames = 1 + max(0, (len(x) - FRAME) // HOP)
    if frames <= 0:
        return np.zeros((0, FRAME // 2 + 1), np.float32)
    win = np.hanning(FRAME).astype(np.float32)
    # A strided view rather than a python loop over 15,000 frames.
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(frames)[:, None]
    return np.abs(np.fft.rfft(x[idx] * win, axis=1)).astype(np.float32)


def superflux(S, lo, hi, mu=2, size=3):
    """Onset strength in one band, per bin so bands can be compared.

    Two departures from plain spectral flux, both load-bearing:

    log1p, because a chorus is twenty times louder than a verse and a detector
    that works on raw magnitude works on one of them.

    The maximum filter over frequency, which is the whole trick. Comparing a
    frame to a frequency-smeared version of an earlier frame means a note that
    is merely wobbling -- vibrato, tremolo picking, a ringing distorted chord
    -- no longer registers as a new onset every time it wobbles. That one
    change is most of the difference between charting a drum kit and charting
    a guitarist.

    Returned per-bin, so that nine bins of kick can be compared with nine
    hundred bins of cymbal. Summing instead of averaging is why the kick lane
    emptied out the first time this was tried: it can never hold a large
    SHARE of a wideband total, but it very easily holds a large DENSITY.
    """
    import numpy as np
    freqs = np.fft.rfftfreq(FRAME, 1.0 / SR)
    sel = (freqs >= lo) & (freqs <= hi)
    if not sel.any() or len(S) <= mu:
        return np.zeros(len(S), np.float32)
    B = np.log1p(S[:, sel])
    M = B.copy()
    for k in range(1, size + 1):
        M[:, k:] = np.maximum(M[:, k:], B[:, :-k])
        M[:, :-k] = np.maximum(M[:, :-k], B[:, k:])
    d = np.maximum(B[mu:] - M[:-mu], 0)
    return np.concatenate([np.zeros(mu, np.float32), d.mean(axis=1)])


def moving_mean(v, w):
    import numpy as np
    w = max(3, int(w))
    pad = np.pad(v, (w // 2, w // 2), mode="edge")
    cs = np.cumsum(np.insert(pad, 0, 0))
    return ((cs[w:] - cs[:-w]) / float(w))[:len(v)]


def estimate_tempo(env, fps):
    """Beats per minute, by autocorrelating the onset envelope.

    A drum part repeats at the beat, so the envelope correlates with itself
    at the beat period -- and, being a beat, also at two, three and four
    times it. Scoring a candidate by the sum of its own correlation and its
    multiples is what tells a beat apart from a plausible-looking fraction of
    one: a 176 BPM pattern first came back as 117.5, which is exactly two
    thirds of it, because a dotted quarter correlates handsomely on its own
    and falls apart the moment you ask what is at twice and four times it.

    The prior on top keeps it from drifting off to a whole bar or a
    sixteenth, both of which correlate for uninteresting reasons.
    """
    import numpy as np
    if len(env) < 64:
        return BPM_CENTRE, max(1, int(60.0 * fps / BPM_CENTRE))
    e = env - env.mean()
    ac = np.correlate(e, e, "full")[len(e) - 1:]
    ac = np.maximum(ac, 0)
    n = len(ac)
    lo = max(1, int(60.0 * fps / BPM_HI))
    hi = min(n - 1, int(60.0 * fps / BPM_LO))
    if hi <= lo:
        return BPM_CENTRE, max(1, int(60.0 * fps / BPM_CENTRE))

    lags = np.arange(lo, hi + 1)
    comb = np.zeros(len(lags))
    for mult, weight in ((1, 1.0), (2, 0.5), (3, 0.3), (4, 0.2)):
        idx = lags * mult
        inside = idx < n
        comb[inside] += weight * ac[idx[inside]]
    bpm = 60.0 * fps / lags
    comb *= np.exp(-0.5 * (np.log2(bpm / BPM_CENTRE) / 0.7) ** 2)
    lag = int(lags[int(np.argmax(comb))])
    return 60.0 * fps / lag, lag


def track_beats(env, period, alpha=100.0):
    """Lay actual beats on the envelope (Ellis's dynamic-programming tracker).

    Scores every frame by "how much onset is here, plus the best score I could
    have come from, minus a penalty for being the wrong distance from it", and
    backtraces the best path. A fixed grid from a single tempo drifts out of a
    band that speeds up over three minutes; this does not, because each beat
    only has to be roughly one period after the last one.
    """
    import numpy as np
    N = len(env)
    lo, hi = int(period * 0.5), int(period * 2.0)
    if N < hi + 2 or period < 2:
        return np.array([], int)
    o = env / (env.std() + 1e-9)
    C = np.full(N, -np.inf)
    back = np.zeros(N, np.int64)
    C[:hi] = o[:hi]
    offs = np.arange(lo, hi + 1)
    pen = -alpha * (np.log(offs / float(period))) ** 2
    for t in range(hi, N):
        v = C[t - offs] + pen
        j = int(np.argmax(v))
        C[t] = o[t] + v[j]
        back[t] = t - offs[j]
    tail = max(1, int(period * 2))
    t = int(np.argmax(C[-tail:]) + N - tail)
    out = []
    while t > 0 and np.isfinite(C[t]):
        out.append(t)
        nxt = int(back[t])
        if nxt >= t:
            break
        t = nxt
    return np.array(sorted(out), dtype=int)


def build_grid(beat_frames):
    """Slot times, interpolated between tracked beats, with a metrical weight.

    Interpolated rather than generated from one tempo, so the grid follows the
    band instead of the other way round.

    The weight says how strong a position each slot is:

        0  downbeat (first beat of a bar)
        1  beat
        2  eighth
        3  sixteenth
        4  thirty-second

    That weight does two jobs. It makes thinning musical -- dropping the
    sixteenths off a busy bar leaves the bar, while dropping every other note
    leaves noise. And it ships with the chart, so the game can offer a simpler
    version of the same part instead of a different, thinner chart. The scale
    has to be this fine to be useful for that: while the grid was sixteenths,
    six of every eight slots shared one weight and there was nothing to sort
    by.
    """
    import numpy as np
    times, weight = [], []
    for i in range(len(beat_frames) - 1):
        a, b = frame_time(beat_frames[i]), frame_time(beat_frames[i + 1])
        for k in range(SUBDIV):
            times.append(a + (b - a) * k / float(SUBDIV))
            if k == 0:
                weight.append(0 if i % 4 == 0 else 1)
            elif SUBDIV % 2 == 0 and k == SUBDIV // 2:
                weight.append(2)
            elif SUBDIV % 4 == 0 and k % (SUBDIV // 4) == 0:
                weight.append(3)
            else:
                weight.append(4)
    return np.asarray(times), np.asarray(weight)


def peak_pick(env, fps, sensitivity=1.5, min_gap=0.055):
    """Local maxima that stand above where the music has been sitting.

    A fixed threshold cannot work on real music: a quiet verse and a loud
    chorus are the same song, and any level that catches the verse turns the
    chorus into noise. The threshold follows the local mean instead, so it is
    the shape of the transient that matters rather than how loud the band
    happened to be playing.
    """
    import numpy as np
    if not len(env) or float(env.max()) <= 1e-9:
        return np.array([], int)
    local = moving_mean(env, 0.5 * fps)
    thresh = np.maximum(local * sensitivity + env.mean() * 0.1, env.max() * 0.02)
    gap = max(1, int(min_gap * fps))
    out, last = [], -10 ** 9
    for i in range(1, len(env) - 1):
        if env[i] <= thresh[i] or env[i] < env[i - 1] or env[i] < env[i + 1]:
            continue
        if i - last < gap:
            if out and env[i] > env[out[-1]]:
                out[-1] = i
                last = i
            continue
        out.append(i)
        last = i
    return np.array(out, int)


def zscore(v, fps, win=4.0):
    """Each band in its own units, so they can be compared with each other."""
    import numpy as np
    w = max(5, int(win * fps))
    m = moving_mean(v, w)
    m2 = moving_mean(v * v, w)
    return (v - m) / np.sqrt(np.maximum(m2 - m * m, 1e-12))


def enforce_gap(notes, slot=None):
    """No two notes in one lane closer than a limb can move. Keeps the
    stronger of a pair."""
    by_lane = {}
    for n in notes:
        by_lane.setdefault(n["lane"], []).append(n)
    out = []
    for lane, row in by_lane.items():
        row.sort(key=lambda n: n["t"])
        gap = max(MIN_GAP_FLOOR, (slot or 0.06) * MIN_GAP_SLOTS)
        kept = []
        for n in row:
            if kept and n["t"] - kept[-1]["t"] < gap:
                if n["s"] > kept[-1]["s"]:
                    kept[-1] = n
                continue
            kept.append(n)
        out.extend(kept)
    return sorted(out, key=lambda n: n["t"])


def thin(notes, duration, beats=None):
    """Drop notes until the chart is playable -- weakest METRICAL position
    first, not every Nth note.

    Every-Nth was the old way and it is why charts felt arbitrary: taking
    alternate entries off a list of onsets that are not on a grid gives you an
    arbitrary subset of them. Dropping the sixteenths out of a busy bar and
    leaving the backbeat gives you a simpler version of the same part, which
    is what a difficulty setting is supposed to be.
    """
    if duration <= 0 or not notes:
        return notes
    # Budgets are per beat. A cap in seconds gives a fast song a thinner drum
    # part than a slow one, which is backwards.
    beats = beats if beats else max(1, duration * 2.0)
    by_lane = {}
    for n in notes:
        by_lane.setdefault(n["lane"], []).append(n)

    def trim(row, budget):
        if len(row) <= budget:
            return row
        # Weakest position first, and within a position the quietest onset.
        order = sorted(row, key=lambda n: (-n["w"], n["s"]))
        drop = set(id(n) for n in order[:len(row) - budget])
        return [n for n in row if id(n) not in drop]

    for lane, row in by_lane.items():
        by_lane[lane] = trim(row, max(1, int(beats * PER_LANE_PER_BEAT.get(lane, 2.0))))

    total_budget = max(1, int(beats * MAX_NOTES_PER_BEAT))
    out = [n for row in by_lane.values() for n in row]
    while len(out) > total_budget:
        lane = max(by_lane, key=lambda k: len(by_lane[k]))
        if len(by_lane[lane]) <= 2:
            break
        by_lane[lane] = trim(by_lane[lane], len(by_lane[lane]) // 2)
        out = [n for row in by_lane.values() for n in row]
    return sorted(out, key=lambda n: n["t"])


GROOVE_SUB = 4          # sixteenths -- the grid a groove is written on
GROOVE_BAR = 4          # beats per bar
GROOVE_SEC = 8          # bars before the template is re-read
GROOVE_Z = 0.55         # how far a slot must stand out to be "played"
GROOVE_HAT_Z = 0.75     # the cymbal band is noisier, so it asks for more
GROOVE_FLOOR = 0.35     # a bar must have this share of the section's energy
GROOVE_HAT_RIDE = -0.60  # a riding hat is allowed to be well under average
GROOVE_FLOOR_HAT = 0.12  # ...and its per-bar gate is gentler, because a hat
                         # under a snare hit is masked, not absent
FILL_RATIO = 2.4         # how far above the template a bar must be to be a fill
FILL_FLOOR = 0.45        # ...and how loud in absolute terms, per lane
FILL_MAX = 3             # extra notes one bar may add, so fills stay fills
                        # at a slot for the template to fire there


def sample(v, t):
    """Band strength at a time -- the peak of a short window around it, so a
    hit a frame either side of the grid still registers."""
    i = int(round((t - BIAS) * SR / HOP - FRAME / 2.0 / HOP))
    a = max(0, i - 2)
    b = min(len(v), i + 3)
    return float(v[a:b].max()) if b > a else 0.0



# Grooves that drummers in this genre actually play, one bar of 4/4 at
# sixteenth resolution.
#
# WHY A LIBRARY AND NOT DETECTION. Five rounds of transcription did not
# converge, and the reason is that the information is not in the mix: a snare
# shares its entire range with two guitars, so no threshold on a band can
# find it, and measuring proved it -- the three lanes' most-used positions in
# the bar came out identical, one onset stream split three ways.
#
# What IS reliable is the beat grid (tempo and beats check out against an
# independent reference) and the relative energy of the low, mid and high
# bands at each sixteenth. That is enough to say WHICH of these a section is
# playing, even though it is not enough to transcribe it hit by hit. Scoring
# every rotation also settles the downbeat, which contrast-scoring cannot:
# [loud, quiet, loud, quiet] looks the same starting at 0 as at 1.
#
# This is a fit, not a transcription, and the page says so. A chart that is
# the right groove in the right place beats a per-hit chart that is right
# about every note and reads as noise.
GROOVES = [
    ("punk eighths",      [0, 8],                  [4, 12], [0,2,4,6,8,10,12,14]),
    ("punk, double kick", [0, 3, 8, 11],           [4, 12], [0,2,4,6,8,10,12,14]),
    ("d-beat",            [0, 3, 6, 8, 11, 14],    [4, 12], [0,2,4,6,8,10,12,14]),
    ("driving eighths",   [0,2,4,6,8,10,12,14],    [4, 12], [0,2,4,6,8,10,12,14]),
    ("four on the floor", [0, 4, 8, 12],           [4, 12], [0,2,4,6,8,10,12,14]),
    ("skank",             [0, 8],                  [4, 12], [2, 6, 10, 14]),
    ("half time",         [0, 10],                 [8],     [0,2,4,6,8,10,12,14]),
    ("sixteenth hats",    [0, 8],                  [4, 12], list(range(16))),
    ("blast",             [0,2,4,6,8,10,12,14],    [1,3,5,7,9,11,13,15],
                                                            [0,2,4,6,8,10,12,14]),
]

# How much better a different groove must fit before a section is allowed to
# change to it. Without this the fit flips between near-equal candidates and
# the mapping a player just learned breaks every eight bars -- measured at up
# to 31% of slots changing lane between sections.
GROOVE_SWITCH = 0.12


def fit_groove(prof, per_bar, previous=None):
    """Which groove, and at which rotation, best matches the measured energy."""
    import numpy as np
    zed = lambda v: (v - v.mean()) / max(v.std(), 1e-9)
    A = {lane: zed(prof[lane]) for lane in prof}
    best = None
    for name, kick, snare, hat in GROOVES:
        for rot in range(per_bar):
            score = 0.0
            for lane, slots in (("kick", kick), ("snare", snare), ("hat", hat)):
                m = np.zeros(per_bar)
                for sl in slots:
                    m[(sl + rot) % per_bar] = 1.0
                score += float((A[lane] * zed(m)).mean())
            if previous and (name, rot) == previous:
                score += GROOVE_SWITCH        # stay put unless clearly beaten
            if best is None or score > best[0]:
                best = (score, name, rot, kick, snare, hat)
    return best


GROOVE_LOG = None          # set by main() to report what was fitted


def groove_chart(S, env, beat_times, fps):
    """Build the chart from the repeating pattern, not hit by hit.

    WHY THIS REPLACED PER-ONSET TRANSCRIPTION
    -----------------------------------------
    Everything before this identified each hit on its own and asked which
    frequency band was loudest. That cannot work on a finished mix: every drum
    is broadband, so all three bands fire on all three drums. Measured on the
    shipped charts, the three lanes' most-used positions in the bar were the
    same positions -- they were not three drums, they were one onset stream
    split three ways. That is what "it feels random" is. Timing accuracy
    could not see it: every note was on a real transient, and the chart was
    still noise.

    A drum part is the same bar over and over, which is a huge amount of
    redundancy that none of it was using. Averaging every bar of a section
    together lifts whatever repeats and cancels whatever does not: a snare on
    2 and 4 over forty bars becomes two towers, while a guitar chord that
    landed near a beat once sinks into the floor. The pattern that comes out
    is the groove, and because the same template is emitted for every bar of
    the section, the chart REPEATS -- which is what makes playing along feel
    like playing the song rather than reacting to confetti.

    Lanes are decided once per section from the averaged evidence rather than
    per hit. That is both a better decision and a consistent one: the old way
    could call the same slot a snare in one bar and a hat in the next, which
    destroys a pattern even when every note is on time.
    """
    import numpy as np
    bt = np.asarray(beat_times)
    if len(bt) < GROOVE_BAR * 4:
        return []
    bands = [(lane, superflux(S, lo, hi)) for lane, lo, hi in BANDS]

    # THE KICK LANE WAS CHARTING THE BASS PLAYER.
    #
    # Averaged over a whole track, the low band peaked an eighth away from
    # where the mid and high bands peaked -- consistently, song after song.
    # No Other: low band on slots 2 and 10, everything else on 0, 4, 8, 12.
    # On The Double: low band on 3, 10 and 14 while the mix was on the beats.
    #
    # That is not a drummer playing the kick off the beat. It is a punk bass
    # line playing offbeat eighths, which lives in the same octave as a kick
    # drum and is louder than one in a finished master. So every chart put a
    # kick note where the bass player was and none where the kick was, which
    # is about the most disorienting thing a drum game can do to a drummer.
    #
    # What tells them apart is the beater: a kick is a broadband CLICK plus
    # low energy, a bass note is low energy with almost no click. The low
    # band is gated on the full mix rising at the same moment, both above
    # their own average. On On The Double that moves the kick off slots 3, 10
    # and 14 and onto 0, 4, 8 and 12.
    zof = lambda v: (v - v.mean()) / max(v.std(), 1e-9)
    z_env = zof(env)
    bands = [(lane, np.minimum(zof(v), z_env) if lane == "kick" else v)
             for lane, v in bands]

    # Sample every sixteenth of the whole track, once.
    nslots = (len(bt) - 1) * GROOVE_SUB
    G = {}
    for lane, v in bands:
        row = np.zeros(nslots)
        for i in range(len(bt) - 1):
            step = (bt[i+1] - bt[i]) / GROOVE_SUB
            for k in range(GROOVE_SUB):
                row[i*GROOVE_SUB + k] = sample(v, bt[i] + step * k)
        G[lane] = row

    # Where does the bar start? The beat phase is already known, so only the
    # bar phase is in question -- search whole beats. Letting it try every
    # sixteenth found "downbeats" three sixteenths off the beat, which is not
    # a thing.
    per_bar = GROOVE_BAR * GROOVE_SUB
    best, off = -1.0, 0
    for cand in range(0, per_bar, GROOVE_SUB):
        total = 0.0
        for lane in G:
            v = G[lane][cand:]
            n = len(v) // per_bar
            if n < 4:
                continue
            m = v[:n*per_bar].reshape(n, per_bar).mean(axis=0)
            total += float(m.std() / max(m.mean(), 1e-9))    # contrast in the bar
        if total > best:
            best, off = total, cand

    nbars = (nslots - off) // per_bar
    notes = []
    last_fit = [None]
    chosen = GROOVE_LOG
    for s0 in range(0, nbars, GROOVE_SEC):
        s1 = min(s0 + GROOVE_SEC, nbars)
        if s1 <= s0:
            break
        z, mean = {}, {}
        for lane in G:
            seg = G[lane][off + s0*per_bar: off + s1*per_bar]
            n = len(seg) // per_bar
            if n < 1:
                break
            m = seg[:n*per_bar].reshape(n, per_bar).mean(axis=0)
            mean[lane] = m
            z[lane] = (m - m.mean()) / max(m.std(), 1e-9)
        if len(z) < 3:
            break

        # How hard it was hit, 0.25 to 1, against the loudest slot that lane
        # uses in this section. The game draws accents with it; a chart where
        # a ghost note and a backbeat look identical reads flat.
        peak = {ln: float(mean[ln].max()) or 1e-9 for ln in mean}

        def vel(lane, si):
            return round(min(1.0, max(0.25, float(G[lane][si]) / peak[lane])), 2)

        # Which drum owns each slot.
        #
        # Only two things in a mix are actually separable by frequency: the
        # kick, because nothing else but the bass has a transient under
        # 200 Hz, and the cymbals, because nothing else lives above 7 kHz.
        # The snare sits in the middle with the guitars, so it is not
        # detected -- it is what is LEFT when a slot is clearly played and is
        # neither of the other two. Deciding the ambiguous one by elimination
        # beats asking a band that cannot answer.
        # Fit a groove rather than deciding each slot from whichever band
        # happened to be loudest -- that is what produced three lanes landing
        # on the same positions.
        score, gname, rot, gk, gs, gh = fit_groove(
            {lane: mean[lane] for lane in mean}, per_bar, previous=last_fit[0])
        last_fit[0] = (gname, rot)
        if chosen is not None:
            chosen.append((s0, gname, score))
        want = {"kick": set((x + rot) % per_bar for x in gk),
                "snare": set((x + rot) % per_bar for x in gs),
                "hat": set((x + rot) % per_bar for x in gh)}
        pattern = []
        for k in range(per_bar):
            lanes = [lane for lane in ("kick", "snare", "hat") if k in want[lane]]
            if lanes:
                pattern.append((k, lanes))
        if not pattern:
            continue

        # THE HAT RIDES.
        #
        # A drummer playing eighths keeps playing them for the whole bar, but
        # the cymbal band only clears its threshold on the slots where nothing
        # louder happened to mask it. Measured on the shipped charts, the hat
        # landed on 25-42% of the eighth slots across all twelve songs, where
        # the part is essentially every one of them. Two thirds of the steady
        # hand -- which is most of what you hear, and all of what you play
        # along to -- was missing, and that is most of why the charts did not
        # feel like the song.
        #
        # So: if the section already shows a hat on enough eighths to call it
        # a ride, put it on the rest of them too, asking only that the slot is
        # not actually silent.
        eighths = [k for k in range(per_bar) if k % 2 == 0]
        hat_on = {k for k, ls in pattern if "hat" in ls}
        if len(hat_on & set(eighths)) >= max(2, len(eighths) // 3):
            by_k = {k: ls for k, ls in pattern}
            for k in eighths:
                if k in hat_on or z["hat"][k] <= GROOVE_HAT_RIDE:
                    continue
                if k in by_k:
                    by_k[k] = by_k[k] + ["hat"]
                else:
                    by_k[k] = ["hat"]
            pattern = sorted(by_k.items())

        # Emit it for every bar of the section -- but only where that bar
        # actually has energy, so a breakdown or a dropped bar stays empty
        # instead of being papered over with the groove.
        for bar in range(s0, s1):
            base = off + bar * per_bar
            for k, lanes in pattern:
                si = base + k
                if si >= nslots - 1:
                    continue
                beat = si // GROOVE_SUB
                if beat + 1 >= len(bt):
                    continue
                step = (bt[beat+1] - bt[beat]) / GROOVE_SUB
                t = bt[beat] + step * (si % GROOVE_SUB)
                for lane in lanes:
                    floor = GROOVE_FLOOR_HAT if lane == "hat" else GROOVE_FLOOR
                    if G[lane][si] < mean[lane][k] * floor:
                        continue                     # nothing there this bar
                    w = 1 if k % GROOVE_SUB == 0 else (2 if k % 2 == 0 else 3)
                    if k == 0:
                        w = 0
                    notes.append({"t": round(float(t), 4), "lane": lane,
                                  "w": w, "s": float(G[lane][si]),
                                  "v": vel(lane, si)})

            # WHAT THIS BAR DID THAT THE TEMPLATE DOES NOT.
            #
            # The template repeats, which is what makes a chart playable, but
            # a drummer does not repeat for three minutes -- there are fills,
            # crashes and extra kicks, and a chart without them is a loop
            # rather than the song. Adding every detected onset back was tried
            # and buries the groove three-to-one. So a bar may only add a few
            # notes, and only where it is clearly louder than the same slot in
            # the rest of the section.
            tmpl = {k: set(ls) for k, ls in pattern}
            extra = 0
            for k in range(per_bar):
                if extra >= FILL_MAX:
                    break
                si = base + k
                if si >= nslots - 1:
                    continue
                beat = si // GROOVE_SUB
                if beat + 1 >= len(bt):
                    continue
                step = (bt[beat+1] - bt[beat]) / GROOVE_SUB
                t = bt[beat] + step * (si % GROOVE_SUB)
                for lane in ("snare", "kick", "hat"):
                    if lane in tmpl.get(k, ()):
                        continue
                    hi = float(mean[lane].max()) or 1e-9
                    if (G[lane][si] > mean[lane][k] * FILL_RATIO
                            and G[lane][si] > hi * FILL_FLOOR):
                        w = 1 if k % GROOVE_SUB == 0 else (2 if k % 2 == 0 else 3)
                        if k == 0:
                            w = 0
                        notes.append({"t": round(float(t), 4), "lane": lane,
                                      "w": w, "s": float(G[lane][si]),
                                      "v": vel(lane, si)})
                        extra += 1
                        break
    notes.sort(key=lambda n: n["t"])
    return notes


def chart(path):
    import numpy as np
    x = decode(path)
    duration = len(x) / float(SR)
    fps = SR / float(HOP)
    S = spectrogram(x)
    if not len(S):
        return {"duration": round(duration, 2), "bpm": 0, "beats": [], "notes": []}

    env = superflux(S, 0, SR / 2)
    bpm, lag = estimate_tempo(env, fps)
    beat_frames = track_beats(env, lag)
    grid, weight = build_grid(beat_frames)

    notes = []
    slot_w = None
    if len(grid) > 1:
        slot = float(np.median(np.diff(grid)))
        slot_w = slot
        Z = np.stack([zscore(superflux(S, lo, hi), fps) for _, lo, hi in BANDS])

        def to_slots(frames):
            """Frame indices -> the grid slots they belong to, dropping any
            that do not land near one."""
            if not len(frames):
                return np.array([], int), np.array([], int)
            t = np.array([frame_time(i) for i in frames])
            j = np.clip(np.searchsorted(grid, t), 1, len(grid) - 1)
            j = np.where(np.abs(grid[j] - t) < np.abs(grid[j - 1] - t), j, j - 1)
            ok = np.abs(grid[j] - t) < slot * SNAP
            return np.asarray(frames)[ok], j[ok]

        # One note per lane per slot; the strongest onset in a slot wins it.
        best = {}

        def offer(lane, frame, sl, strength):
            key = (lane, int(sl))
            if key not in best or strength > best[key][1]:
                best[key] = (int(frame), float(strength))

        # -- 1. The full mix, assigned to whichever band rose most ----------
        # This is the accurate part: independently checked, 95% of what it
        # produces lands within 45 ms of a real transient in the recording.
        # It is also, on its own, far too sparse -- see below.
        mix_f, mix_j = to_slots(peak_pick(env, fps, sensitivity=MIX_SENS,
                                          min_gap=max(MIN_GAP_FLOOR, slot * MIN_GAP_SLOTS)))
        for f, sl in zip(mix_f, mix_j):
            z = Z[:, f]
            top = int(np.argmax(z))
            if z[top] < DROP_Z:
                continue                       # nothing here we can name
            offer(BANDS[top][0], f, sl, env[f])
            if top != 0 and z[0] >= KICK_Z:    # a kick under a cymbal
                offer("kick", f, sl, env[f])

        # -- 2. Each band on its own ----------------------------------------
        # Taking only the band that rose MOST gives one note per moment, and a
        # drum kit is four limbs. The hi-hat is the limb that suffers: it is
        # never the loudest thing in a punk mix, so it only ever won a moment
        # where nothing else was playing. Measured, its lane stuck at exactly
        # 173 notes for a three minute song no matter how far the detector's
        # sensitivity was turned up -- 0.49 per beat, against the two per beat
        # a hi-hat actually plays. The timekeeping, which is most of what you
        # hear and all of what a rhythm game is read against, was missing.
        #
        # So each band also gets to raise its own onsets. Cross-talk is real
        # (a snare puts energy in the cymbal band) and is what the per-lane
        # budgets below are for.
        for bi, (lane, lo, hi) in enumerate(BANDS):
            bf = superflux(S, lo, hi)
            f2, j2 = to_slots(peak_pick(bf, fps, sensitivity=BAND_SENS[lane],
                                        min_gap=max(MIN_GAP_FLOOR, slot * MIN_GAP_SLOTS)))
            for f, sl in zip(f2, j2):
                if Z[bi, f] >= BAND_Z[lane]:
                    offer(lane, f, sl, bf[f])

        for (lane, sl), (f, strength) in best.items():
            notes.append({"t": round(float(grid[sl]), 4), "lane": lane,
                          "w": int(weight[sl]), "s": float(strength)})

    # The groove is the backbone: a repeating pattern read from the averaged
    # bars. Onset-detected notes are kept only where they do not already sit
    # on a groove note, so fills and stops survive without the groove being
    # buried under per-hit noise again.
    beat_times = [frame_time(b) for b in beat_frames]
    groove = groove_chart(S, env, beat_times, fps)
    # Groove only. Keeping the per-onset notes alongside it was tried and
    # buries it: on No Other the groove is about 700 notes and the onset pass
    # adds 965 on top, so the pattern you are meant to learn is one note in
    # three and the rest is the same scatter as before. A chart you can hear
    # the song in is worth more than a chart with everything in it.
    if groove:
        notes = groove

    notes = enforce_gap(notes, slot=slot_w)
    notes = thin(notes, duration, beats=len(beat_frames))
    # "w" is the metrical weight -- 0 downbeat, 1 beat, 2 eighth, 3+ finer.
    # It ships with the chart so the game can offer a simpler version of the
    # same part rather than a different, thinner chart.
    clean = [{"t": n["t"], "lane": n["lane"], "w": n["w"],
              "v": n.get("v", 0.8)}
             for n in sorted(notes, key=lambda n: n["t"]) if n["t"] >= 0]
    return {
        "duration": round(duration, 2),
        "bpm": round(float(bpm), 1),
        # The tracked beats, for anything that wants to move in time with the
        # song rather than guess at it.
        "beats": [round(float(frame_time(b)), 3) for b in beat_frames],
        "notes": clean,
    }


def preview(src, data, seconds, out_path, only=None):
    """The song with a click on every charted note, so a person can hear
    whether the chart is right.

    Every metric in the self-test is a proxy. This is not: if the clicks line
    up with the drums, the chart is right, and if they do not, no amount of
    on-grid percentage makes it right.
    """
    import numpy as np
    x = decode(src)
    start = min(max(0.0, (len(x) / SR) * 0.35), max(0.0, len(x) / SR - seconds))
    a, b = int(start * SR), int(min(len(x), (start + seconds) * SR))
    clip = x[a:b].copy() * 0.7
    tone = {"kick": 160.0, "snare": 440.0, "hat": 1400.0}
    n = 900
    for note in data["notes"]:
        # only=<lane> renders that lane alone. Five rounds of guessing which
        # part is wrong is four too many; one lane clicking at a time is a
        # question a drummer can answer in ten seconds.
        if only and note["lane"] != only:
            continue
        t = note["t"] - start
        if not (0 <= t < (b - a) / SR - 0.05):
            continue
        i = int(t * SR)
        e = np.exp(-np.linspace(0, 14, n)).astype(np.float32)
        w = np.sin(2 * np.pi * tone[note["lane"]] * np.arange(n) / SR).astype(np.float32)
        clip[i:i + n] += 0.45 * e * w
    clip = np.clip(clip, -1, 1)
    raw = (clip * 32767).astype("<i2").tobytes()
    wav = "/tmp/beatmap-preview.wav"
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(raw)
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-i", wav, "-b:a", "128k", out_path],
                   check=True, capture_output=True)
    os.remove(wav)
    return start


def self_test():
    import numpy as np
    fails = []

    def ok(cond, what):
        if not cond:
            fails.append(what)

    checks = 0

    def kit(t, x, kind, rs, gain=1.0):
        """A hit of roughly the right shape at time t."""
        i = int(t * SR)
        n = min(1200, len(x) - i)
        if n <= 0:
            return
        e = gain * np.exp(-np.linspace(0, 9, n)).astype(np.float32)
        if kind == "kick":
            x[i:i + n] += e * np.sin(2 * np.pi * 62 * np.arange(n) / SR).astype(np.float32)
        elif kind == "snare":
            x[i:i + n] += (0.5 * e * np.sin(2 * np.pi * 2400 * np.arange(n) / SR)
                           + 0.7 * e * rs.randn(n)).astype(np.float32)
        else:
            x[i:i + n] += (0.8 * e * np.sin(2 * np.pi * 9000 * np.arange(n) / SR)
                           ).astype(np.float32)

    # --- the clock -----------------------------------------------------
    # The bug that made every chart feel wrong was not detection, it was
    # arithmetic: frames were timed from the start of the analysis window
    # instead of its centre, putting every note 55-74 ms early. This is the
    # check that would have caught it, and it is worth more than the rest.
    rs = np.random.RandomState(0)
    for kind in ("kick", "snare", "hat"):
        x = np.zeros(int(SR * 8), np.float32)
        hits = np.arange(0.5, 7.5, 0.35)
        for t in hits:
            kit(t, x, kind, rs)
        env = superflux(spectrogram(x), 0, SR / 2)
        got = np.array([frame_time(i) for i in peak_pick(env, SR / float(HOP))])
        checks += 2
        ok(abs(len(got) - len(hits)) <= 1,
           "%s click track: found %d of %d" % (kind, len(got), len(hits)))
        if len(got):
            err = np.array([g - hits[int(np.argmin(np.abs(hits - g)))] for g in got])
            ok(abs(float(np.median(err))) < 0.012,
               "%s timing is honest (median %+.0f ms, want under 12)"
               % (kind, float(np.median(err)) * 1000))

    # Silence must produce nothing. A detector that invents notes in silence
    # invents them everywhere.
    checks += 1
    quiet = np.zeros(int(SR * 3), np.float32)
    ok(len(peak_pick(superflux(spectrogram(quiet), 0, SR / 2), SR / float(HOP))) == 0,
       "silence stays empty")

    # --- tempo and beats -----------------------------------------------
    # A real beat at a known tempo must come back as that tempo: kick on one
    # and three, snare on two and four, hats on the eighths and quieter than
    # both. The accents matter -- the first version of this test gave every
    # hit the same weight, which makes a uniform eighth-note pulse with no
    # beat in it at all, and then complained that the tempo came back as two
    # thirds of the answer. There was no answer to come back with.
    for want_bpm in (120.0, 176.0):
        x = np.zeros(int(SR * 24), np.float32)
        beat = 60.0 / want_bpm
        for k in range(int(24 / beat)):
            t = 0.4 + k * beat
            kit(t, x, "kick" if k % 2 == 0 else "snare", rs)
            kit(t + beat / 2, x, "hat", rs, gain=0.3)
        env = superflux(spectrogram(x), 0, SR / 2)
        fps = SR / float(HOP)
        bpm, lag = estimate_tempo(env, fps)
        bf = track_beats(env, lag)
        checks += 2
        ok(abs(bpm - want_bpm) < 3 or abs(bpm - want_bpm * 2) < 6,
           "tempo of a %.0f BPM pattern reads %.1f" % (want_bpm, bpm))
        if len(bf) > 4:
            ibi = np.diff([frame_time(b) for b in bf])
            ok(float(np.std(ibi)) < 0.02,
               "beats are evenly spaced (sd %.0f ms)" % (float(np.std(ibi)) * 1000))

    # --- lane assignment ------------------------------------------------
    # The question is comparative -- which band rose most -- so the test is
    # too. Absolute thresholds are what emptied the kick lane last time.
    x = np.zeros(int(SR * 6), np.float32)
    plan = [(0.5, "kick"), (1.0, "snare"), (1.5, "hat"),
            (2.0, "kick"), (2.5, "snare"), (3.0, "hat")]
    for t, kind in plan:
        kit(t, x, kind, rs)
    S = spectrogram(x)
    fps = SR / float(HOP)
    Z = np.stack([zscore(superflux(S, lo, hi), fps) for _, lo, hi in BANDS])
    right = 0
    for t, kind in plan:
        i = int((t - BIAS) * SR / HOP)
        window = Z[:, max(0, i - 4):i + 8]
        if len(window[0]) and BANDS[int(np.argmax(window.max(axis=1)))][0] == kind:
            right += 1
    checks += 1
    ok(right >= 5, "hits land in the right lane (%d of %d)" % (right, len(plan)))

    # --- grid filtering -------------------------------------------------
    checks += 2
    g, w = build_grid(np.arange(0, 40) * int(0.5 * SR / HOP))
    ok(len(g) == 39 * SUBDIV, "grid has %d slots for 40 beats" % len(g))
    ok(sorted(set(w.tolist())) == [0, 1, 2, 3, 4],
       "every metrical weight is represented (got %s)" % sorted(set(w.tolist())))
    # The weights have to actually separate the subdivisions, or the game's
    # difficulty setting has nothing to sort by.
    checks += 1
    ok(w[0] == 0 and w[SUBDIV // 2] == 2 and w[1] == 4,
       "downbeat 0, eighth 2, thirty-second 4")

    # --- thinning -------------------------------------------------------
    # Sixteenths go first; the backbeat stays. The old thinner took every
    # other note regardless, which is why what survived was noise.
    dense = []
    for i in range(400):
        dense.append({"t": i * 0.125, "lane": "hat", "w": [0, 4, 2, 4][i % 4], "s": 1.0})
    out = thin(list(dense), 10.0, beats=20)
    checks += 2
    ok(len(out) <= int(20 * PER_LANE_PER_BEAT["hat"]) + 1,
       "hats thinned to their lane budget (%d)" % len(out))
    kept_w = [n["w"] for n in out]
    ok(kept_w.count(0) >= kept_w.count(4),
       "thinning keeps downbeats over thirty-seconds (%d vs %d)"
       % (kept_w.count(0), kept_w.count(4)))

    # A flooded kick lane must not be paid for out of the hi-hats.
    mixed = ([{"t": i * 0.05, "lane": "kick", "w": 4, "s": 1.0} for i in range(400)] +
             [{"t": i * 0.05 + 0.02, "lane": "hat", "w": 1, "s": 1.0} for i in range(400)])
    out2 = thin(sorted(mixed, key=lambda n: n["t"]), 20.0, beats=40)
    hats = sum(1 for n in out2 if n["lane"] == "hat")
    kicks = sum(1 for n in out2 if n["lane"] == "kick")
    checks += 3
    ok(hats >= 40, "hats survive a flooded kick lane (%d hats, %d kicks)" % (hats, kicks))
    ok(kicks <= int(40 * PER_LANE_PER_BEAT["kick"]) + 1, "kick lane capped (%d)" % kicks)
    ok(out2 == sorted(out2, key=lambda n: n["t"]), "still in time order after thinning")

    # Limb gap.
    checks += 1
    close = [{"t": 1.00, "lane": "kick", "w": 1, "s": 1.0},
             {"t": 1.03, "lane": "kick", "w": 3, "s": 2.0},
             {"t": 1.40, "lane": "kick", "w": 1, "s": 1.0}]
    g2 = enforce_gap(close)
    ok(len(g2) == 2 and g2[0]["s"] == 2.0,
       "two kicks 30 ms apart become one, the louder")

    # --- slugs ----------------------------------------------------------
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
        checks += 1
        got = slugify(_p.splitext(name)[0])
        ok(got == want, "slug for %s: got %r want %r" % (name, got, want))

    for f in fails:
        print("FAIL", f)
    print("%d checks, %d failed" % (checks, len(fails)))
    return 1 if fails else 0


def main():
    if "--self-test" in sys.argv:
        return self_test()

    args = sys.argv[1:]
    prev_secs = 0
    if "--preview" in args:
        k = args.index("--preview")
        prev_secs = int(args[k + 1])
        del args[k:k + 2]
    srcs = [a for a in args if not a.startswith("-")]
    if not srcs:
        print("give it one or more audio files", file=sys.stderr)
        return 2

    os.makedirs(OUT, exist_ok=True)
    for src in srcs:
        full = os.path.join(ROOT, src) if not os.path.isabs(src) else src
        slug = slugify(os.path.splitext(os.path.basename(src))[0])
        import build_beatmaps as _self
        _self.GROOVE_LOG = []
        data = chart(full)
        fitted = _self.GROOVE_LOG
        data["audio"] = "/" + src.replace("\\", "/")
        data["slug"] = slug
        path = os.path.join(OUT, slug + ".json")
        with open(path, "w") as fh:
            json.dump(data, fh, separators=(",", ":"))
        counts = {}
        for n in data["notes"]:
            counts[n["lane"]] = counts.get(n["lane"], 0) + 1
        dur = data["duration"] or 1
        print("%-34s %5.0fs  %5.1f BPM  %4d notes  %.2f/s  (%s)  %.0f KB"
              % (slug, data["duration"], data["bpm"], len(data["notes"]),
                 len(data["notes"]) / dur,
                 " ".join("%s %d" % (k, v) for k, v in sorted(counts.items())),
                 os.path.getsize(path) / 1024))
        if fitted:
            from collections import Counter
            c = Counter(g for _, g, _ in fitted)
            print("    grooves: " + ", ".join("%s x%d" % (k, v)
                                              for k, v in c.most_common()))
        if prev_secs:
            mp3 = os.path.join("/tmp", slug + "-check.mp3")
            at = preview(full, data, prev_secs, mp3)
            print("    preview from %.0fs: %s" % (at, mp3))

    write_index()
    return 0


def write_index():
    """A small index of every chart, for the song list.

    The list needs a title, a length and a note count per song, and it was
    getting them by fetching all twelve charts on page load. That was fine
    when a chart was 18 KB. Charting the parts properly took them to 60 KB,
    which turned opening the page into three quarters of a megabyte of JSON
    before anything could be shown -- on a phone, on whatever connection. The
    full chart is now fetched only for the song actually being played.
    """
    index = []
    for fn in sorted(os.listdir(OUT)):
        if not fn.endswith(".json") or fn == "index.json":
            continue
        with open(os.path.join(OUT, fn)) as fh:
            m = json.load(fh)
        lanes = {}
        for n in m.get("notes", []):
            lanes[n["lane"]] = lanes.get(n["lane"], 0) + 1
        index.append({
            "slug": m.get("slug", fn[:-5]),
            "duration": m.get("duration", 0),
            "bpm": m.get("bpm", 0),
            "notes": len(m.get("notes", [])),
            "lanes": lanes,
        })
    path = os.path.join(OUT, "index.json")
    with open(path, "w") as fh:
        json.dump({"charts": index}, fh, separators=(",", ":"))
    print("index: %d charts, %.1f KB (was %.0f KB of charts to open the page)"
          % (len(index), os.path.getsize(path) / 1024,
             sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT)
                 if f.endswith(".json") and f != "index.json") / 1024))


if __name__ == "__main__":
    raise SystemExit(main())
