"""Add subtitles to clips you already have.

    python subtitle.py clip1.mp4 clip2.mp4
    python subtitle.py my_clips_folder/            # every .mp4 inside
    python subtitle.py clip.mp4 --model small --words "Valorant, Ahmet"

Writes <clip>.srt and <clip>_subtitled.mp4 next to each clip.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

from cli import add_subtitle_args, subtitle_options
from clipper.media import probe
from clipper.subtitles import build_captions, burn, write_ass, write_srt
from clipper.transcribe import Transcriber


def main() -> int:
    p = argparse.ArgumentParser(description="Add subtitles to existing clips.")
    p.add_argument("inputs", nargs="+", help="video files or folders")
    add_subtitle_args(p)
    a = p.parse_args()
    opts = subtitle_options(a)
    if opts is None:
        return 0

    files: list[str] = []
    for item in a.inputs:
        if os.path.isdir(item):
            files += sorted(glob.glob(os.path.join(item, "*.mp4")))
        else:
            files.append(item)
    files = [f for f in files if not f.endswith("_subtitled.mp4")]
    if not files:
        print("No .mp4 files found.")
        return 1

    tr = Transcriber(opts.transcribe, status=print)
    print(f"Using {opts.transcribe.model} on {tr.device}\n")
    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {os.path.basename(f)}")
        t = tr.transcribe_file(f)
        print("   ", t.text or "(no speech found)")
        caps = build_captions(t.words, opts.style, t.language)
        stem = os.path.splitext(f)[0]
        write_srt(caps, stem + ".srt")
        if opts.burn_in and caps:
            info = probe(f)
            write_ass(caps, stem + ".ass", info.width or 1920, info.height or 1080,
                      opts.style)
            burn(f, stem + ".ass", stem + "_subtitled.mp4")
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
