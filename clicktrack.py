#!/usr/bin/env python3
"""
clicktrack.py — build a custom metronome / click-track WAV.

Pure Python standard library. No pip installs, runs anywhere Python 3 does.

Examples:
    python clicktrack.py --bpm 120 --bars 16
    python clicktrack.py --bpm 92 --sig 6/8 --minutes 3 --count-in 1
    python clicktrack.py --bpm 160 --subdiv 2 --accent-off --out fast.wav
    python clicktrack.py --bpm 140 --sig 7/8 --seconds 30

Made for mikidrummer.ca — practice to a click, or bounce a quick guide track.
"""

import argparse
import math
import struct
import wave

SR = 44100  # sample rate


def blip(freq, ms, amp):
    """A short sine 'tick' with a fast exponential decay."""
    n = int(SR * ms / 1000)
    out = [0.0] * n
    for i in range(n):
        t = i / SR
        env = math.exp(-t * 42)
        out[i] = amp * env * math.sin(2 * math.pi * freq * t)
    return out


def build(bpm, beats_per_bar, bars, count_in, subdiv, accent):
    """Render the whole click track into a float sample buffer."""
    sec_per_beat = 60.0 / bpm
    step = sec_per_beat / subdiv                      # seconds between clicks
    total_beats = beats_per_bar * (bars + count_in)
    total_steps = int(round(total_beats * subdiv))
    total_samples = int(SR * (total_steps * step + 0.25))
    buf = [0.0] * total_samples

    accent_tick = blip(1600, 45, 0.95)   # downbeat  — bright + loud
    beat_tick   = blip(1000, 40, 0.60)   # other beats
    sub_tick    = blip(1300, 22, 0.28)   # subdivisions — quiet

    for s in range(total_steps):
        pos = int(s * step * SR)
        beat_index = s // subdiv
        on_beat = (s % subdiv == 0)
        bar_start = (beat_index % beats_per_bar == 0)
        if on_beat and bar_start and accent:
            tick = accent_tick
        elif on_beat:
            tick = beat_tick
        else:
            tick = sub_tick
        for i, v in enumerate(tick):
            if pos + i < total_samples:
                buf[pos + i] += v
    return buf


def write_wav(path, buf):
    frames = bytearray()
    for v in buf:
        s = max(-1.0, min(1.0, v))
        frames += struct.pack("<h", int(s * 32767))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))


def main():
    ap = argparse.ArgumentParser(
        description="Build a metronome / click-track WAV.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--bpm", type=float, required=True, help="tempo in beats per minute")
    ap.add_argument("--sig", default="4/4", help="time signature, e.g. 4/4, 6/8, 7/8")
    length = ap.add_mutually_exclusive_group()
    length.add_argument("--bars", type=int, help="length in bars")
    length.add_argument("--seconds", type=float, help="length in seconds")
    length.add_argument("--minutes", type=float, help="length in minutes")
    ap.add_argument("--count-in", type=int, default=0, help="count-in bars before the track")
    ap.add_argument("--subdiv", type=int, default=1, choices=[1, 2, 3, 4],
                    help="clicks per beat (2=eighths, 3=triplets, 4=sixteenths)")
    ap.add_argument("--accent-off", action="store_true", help="no accent on beat 1")
    ap.add_argument("--out", default="clicktrack.wav", help="output WAV file")
    a = ap.parse_args()

    try:
        num = int(a.sig.split("/")[0])
    except (ValueError, IndexError):
        ap.error("bad --sig; use something like 4/4 or 7/8")

    bar_secs = (60.0 / a.bpm) * num
    if a.bars is not None:
        bars = a.bars
    elif a.seconds is not None:
        bars = max(1, round(a.seconds / bar_secs))
    elif a.minutes is not None:
        bars = max(1, round(a.minutes * 60 / bar_secs))
    else:
        bars = 8

    buf = build(a.bpm, num, bars, a.count_in, a.subdiv, not a.accent_off)
    write_wav(a.out, buf)

    dur = len(buf) / SR
    extra = f" (+{a.count_in} count-in)" if a.count_in else ""
    print(f"✔ {a.out} — {a.bpm:g} BPM, {a.sig}, {bars} bars{extra}, "
          f"{a.subdiv}× subdivision  →  {dur:.1f}s")


if __name__ == "__main__":
    main()
