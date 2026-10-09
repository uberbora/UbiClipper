"""Command-line entry point.

    python cli.py my_stream.mp4
    python cli.py my_stream.mp4 --out clips --max-clips 20 --sensitivity 0.7
    python cli.py my_stream.mp4 --dry-run      # list moments, don't cut
"""

from __future__ import annotations

import argparse
import os
import sys

from clipper.pipeline import PartialExport, SubtitleOptions, analyze, clip_folder, export
from clipper.reframe import Region, load_layout, save_layout
from clipper.remote import RemoteVideo, is_url
from clipper.selection import ClipSettings
from clipper.settings import load_settings
from clipper.subtitles import PRESETS, SubtitleStyle, preset
from clipper.transcribe import TranscribeOptions


def hms(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{(t % 3600) // 60:02d}:{t % 60:02d}"


def add_subtitle_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("subtitles")
    g.add_argument("--no-subtitles", action="store_true")
    g.add_argument("--language", default="tr", help="tr, en, ... or 'auto'")
    g.add_argument("--also-language", default="en",
                   help="second language spoken on stream (code-switching), or 'none'")
    g.add_argument("--model", default="large-v3-turbo",
                   help="small | medium | large-v3-turbo | large-v3")
    g.add_argument("--words", default="",
                   help="names/terms to help recognition, e.g. 'Valorant, Ahmet'")
    g.add_argument("--no-upper", action="store_true", help="keep normal casing")
    g.add_argument("--no-burn", action="store_true",
                   help="only write .srt files, don't render subtitled videos")
    g.add_argument("--device", default="auto", help="auto | cpu | cuda")
    g.add_argument("--style", choices=list(PRESETS),
                   help="subtitle preset (default: the style saved in the app)")
    g.add_argument("--censor", action="store_true", help="censor swear words")
    g.add_argument("--people", default="auto",
                   help="colour subtitles per speaker: auto (up to 10), 2..10, or off")


def _style(a: argparse.Namespace) -> SubtitleStyle:
    saved = load_settings().get("style") or {}
    st = SubtitleStyle.from_dict(saved) if saved else SubtitleStyle()
    if a.style:
        st = preset(a.style, st)
    if a.no_upper:
        st.uppercase = False
    if a.censor:
        st.censor = True
    return st


def subtitle_options(a: argparse.Namespace) -> SubtitleOptions | None:
    if a.no_subtitles:
        return None
    return SubtitleOptions(
        transcribe=TranscribeOptions(
            language=None if a.language == "auto" else a.language,
            model=a.model, custom_words=a.words, device=a.device,
            also_language=None if a.also_language in ("none", "off", "") else a.also_language),
        style=_style(a),
        burn_in=not a.no_burn,
        max_speakers=0 if a.people == "off" else (int(a.people) if a.people.isdigit() else 10))


def main() -> int:
    p = argparse.ArgumentParser(description="UbiClipper: find highlight moments and cut short clips.")
    p.add_argument("video", help="video file, or a Twitch/YouTube/Kick VOD link")
    p.add_argument("--out", help="output folder (default: <export folder>/<video name>)")
    p.add_argument("--max-clips", type=int, help="default scales with length")
    p.add_argument("--max-len", type=float, default=60.0)
    p.add_argument("--min-len", type=float, default=10.0)
    p.add_argument("--pre-roll", type=float, default=12.0,
                   help="seconds of setup before the moment")
    p.add_argument("--post-roll", type=float, default=4.0)
    p.add_argument("--sensitivity", type=float, default=0.5,
                   help="0..1, higher = more clips")
    p.add_argument("--focus", type=float, default=0.4,
                   help="0 = any loud sound counts, 1 = only voice reactions")
    p.add_argument("--audio-track", type=int, default=1,
                   help="audio track to listen to (1 = first; pick your mic-only track)")
    p.add_argument("--no-rank", action="store_true",
                   help="don't re-rank moments by what's said (faster on CPU)")
    p.add_argument("--no-chat", action="store_true", help="don't use VOD chat (links)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-ai-listen", action="store_true",
                   help="don't use the listening AI (laughter/scream/explosion recognition)")
    p.add_argument("--ai-judge", action="store_true",
                   help="let the local AI judge rate each moment (~4 GB download once)")
    add_subtitle_args(p)
    v = p.add_argument_group("vertical 9:16")
    v.add_argument("--no-vertical", action="store_true", help="skip the 9:16 version")
    v.add_argument("--no-fullscreen", action="store_true",
                   help="skip the 1920x1080 subtitled version (ready_fullscreen)")
    v.add_argument("--webcam", metavar="X,Y,W,H",
                   help="webcam box in source pixels, e.g. 30,780,480,270 (saved for next time)")
    v.add_argument("--no-webcam", action="store_true",
                   help="forget the saved webcam box (gameplay on blurred background)")
    a = p.parse_args()

    settings = ClipSettings(max_len=a.max_len, min_len=a.min_len,
                            pre_roll=a.pre_roll, post_roll=a.post_roll,
                            max_clips=a.max_clips, sensitivity=a.sensitivity,
                            voice_focus=a.focus, audio_track=max(0, a.audio_track - 1))

    def progress(msg: str, f: float) -> None:
        bar = "#" * int(f * 30)
        sys.stdout.write(f"\r{msg:<28} [{bar:<30}] {f * 100:5.1f}%")
        sys.stdout.flush()

    remote = None
    chat = None
    path = a.video
    if is_url(a.video):
        remote = RemoteVideo.probe(a.video)
        print(f"{remote.title}  ({hms(remote.duration)})")
        path = remote.download_audio(progress)
        print()
        if not a.no_chat:
            try:
                chat = remote.fetch_chat(progress)
                print(f"\n{len(chat)} chat messages")
            except Exception as e:
                print(f"\nChat unavailable: {str(e).splitlines()[0]}")
    rank = None
    if not a.no_rank and not a.no_subtitles:
        from clipper.transcribe import check_available
        if check_available()[0]:
            rank = subtitle_options(a).transcribe
    game = remote.game if remote and getattr(remote, "game", None) else ""
    res = analyze(path, settings, progress, rank=rank, chat=chat,
                  listen=not a.no_ai_listen, ai_judge=a.ai_judge, game=game)
    res.remote = remote
    print(f"\nAnalysed {hms(res.info.duration)} in {res.seconds_taken:.1f}s "
          f"-> {len(res.clips)} clips\n")
    for n in res.notes:
        print("note:", n)
    for i, c in enumerate(sorted(res.clips, key=lambda c: -c.score), 1):
        ai = f"  [AI {c.ai['score']:.0f}/10]" if c.ai else ""
        print(f"{i:2d}. {hms(c.start)}-{hms(c.end)} ({c.duration:4.1f}s) "
              f"score {c.score:.3f}{ai}  {', '.join(c.reasons)}")
    if a.dry_run or not res.clips:
        return 0

    root = load_settings().get("export_root") or os.path.dirname(os.path.abspath(a.video))
    out = a.out or clip_folder(root, path, res.title)
    vertical = None
    if not a.no_vertical:
        vertical = load_layout()
        if a.no_webcam:
            vertical.webcam = None
            save_layout(vertical)
        elif a.webcam:
            x, y, w, h = (float(n) for n in a.webcam.split(","))
            W, H = res.info.width or 1920, res.info.height or 1080
            vertical.webcam = Region(x / W, y / H, w / W, h / H)
            save_layout(vertical)
    try:
        manifest = export(res, out, progress, subtitles=subtitle_options(a),
                          fullscreen=False if a.no_fullscreen else None,
                          vertical=vertical)
    except PartialExport as e:
        print(f"\n\n{e}")
        manifest = e.manifest
    print(f"\n\nClips written to {out}\nManifest: {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
