#!/usr/bin/env python3
"""
wav_to_mp3.py - Convert WAV files to MP3 using ffmpeg
Usage:
  python wav_to_mp3.py input.wav
  python wav_to_mp3.py input.wav -o output.mp3
  python wav_to_mp3.py /folder/with/wavs  (batch convert)
"""

import argparse
import subprocess
import sys
from pathlib import Path


def convert(input_path: Path, output_path: Path, bitrate: str = "320k"):
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-codec:a", "libmp3lame",
        "-b:a", bitrate,
        str(output_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.splitlines()[-1]}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Convert WAV to MP3")
    parser.add_argument("input", help="WAV file or folder of WAV files")
    parser.add_argument("-o", "--output", help="Output file (single file mode only)")
    parser.add_argument("-b", "--bitrate", default="320k", help="MP3 bitrate (default: 320k)")
    args = parser.parse_args()

    input_path = Path(args.input)

    # Batch mode - folder
    if input_path.is_dir():
        wavs = list(input_path.glob("*.wav")) + list(input_path.glob("*.WAV"))
        if not wavs:
            print("No WAV files found in folder.")
            sys.exit(1)
        print(f"Found {len(wavs)} WAV file(s) — converting at {args.bitrate}...\n")
        ok = fail = 0
        for wav in sorted(wavs):
            out = wav.with_suffix(".mp3")
            print(f"  {wav.name} -> {out.name}", end=" ... ")
            if convert(wav, out, args.bitrate):
                print("done")
                ok += 1
            else:
                fail += 1
        print(f"\nDone: {ok} converted, {fail} failed.")

    # Single file mode
    elif input_path.is_file():
        if input_path.suffix.lower() != ".wav":
            print("Input file must be a .wav")
            sys.exit(1)
        out = Path(args.output) if args.output else input_path.with_suffix(".mp3")
        print(f"{input_path.name} -> {out.name} at {args.bitrate}...", end=" ")
        if convert(input_path, out, args.bitrate):
            print("done.")
        else:
            sys.exit(1)

    else:
        print(f"Input not found: {input_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
