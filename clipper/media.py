"""Thin wrappers around ffprobe / ffmpeg.

Everything that touches the video file lives here, so swapping the backend
(e.g. hardware encoders, or downloading a VOD from a replay link) later only
changes this module.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np

SAMPLE_RATE = 16_000  # mono 16 kHz is plenty for laughs/screams/speech


class FFmpegMissing(RuntimeError):
    pass


def _require(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise FFmpegMissing(
            f"'{tool}' was not found on PATH. Install FFmpeg "
            "(https://ffmpeg.org/download.html) and make sure ffmpeg and "
            "ffprobe are on your PATH."
        )
    return path


@dataclass
class AudioTrack:
    index: int          # 0-based among audio tracks (ffmpeg "0:a:N")
    title: str
    channels: int

    def label(self) -> str:
        return f"Track {self.index + 1}" + (f" – {self.title}" if self.title else "")


@dataclass
class MediaInfo:
    path: str
    duration: float
    has_audio: bool
    width: int | None
    height: int | None
    fps: float | None
    audio_tracks: list[AudioTrack] = field(default_factory=list)


def probe(path: str) -> MediaInfo:
    cmd = [
        _require("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}:\n{out.stderr.strip()}")
    data = json.loads(out.stdout)

    duration = float(data.get("format", {}).get("duration") or 0)
    has_audio = False
    width = height = None
    fps = None
    tracks: list[AudioTrack] = []
    for s in data.get("streams", []):
        if s.get("codec_type") == "audio":
            has_audio = True
            tags = s.get("tags") or {}
            # OBS writes the track names you set in Output > Audio as "title"
            tracks.append(AudioTrack(len(tracks), tags.get("title", "").strip(),
                                     int(s.get("channels") or 0)))
        elif s.get("codec_type") == "video" and width is None:
            width, height = s.get("width"), s.get("height")
            rate = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1"
            try:
                num, den = rate.split("/")
                fps = float(num) / float(den) if float(den) else None
            except ValueError:
                fps = None
        if not duration and s.get("duration"):
            duration = float(s["duration"])
    return MediaInfo(path, duration, has_audio, width, height, fps, tracks)


def stream_audio(path: str, chunk_seconds: float = 30.0, track: int = 0,
                 start: float | None = None,
                 duration: float | None = None) -> Iterator[np.ndarray]:
    """Yield one audio track as float32 mono chunks in [-1, 1].

    Streams through a pipe, so a 6-hour VOD never has to fit in memory.
    `track` is the audio track number (0 = first); start/duration read a range.
    """
    cmd = [_require("ffmpeg"), "-nostdin", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", path]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    # aresample async: follow the timestamps, filling gaps (stream hiccups,
    # reconnects, dropped packets) with silence. Without it, sample counting
    # and timestamp seeking (-ss, used for cutting) drift apart over a long VOD.
    cmd += ["-map", f"0:a:{track}", "-vn",
            "-af", "aresample=async=1:min_hard_comp=0.1:first_pts=0",
            "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    bytes_per_chunk = int(chunk_seconds * SAMPLE_RATE) * 2
    try:
        assert proc.stdout is not None
        while True:
            buf = proc.stdout.read(bytes_per_chunk)
            if not buf:
                break
            if len(buf) % 2:
                buf = buf[:-1]
            yield np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768.0
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def cut_clip(src: str, dst: str, start: float, duration: float,
             crf: int = 20, preset: str = "veryfast", copy: bool = False) -> None:
    """Cut [start, start+duration) into dst with a frame-accurate re-encode.
    copy=True just remuxes (for sections that are already cut exactly)."""
    if copy:
        cmd = [_require("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", src,
               "-t", f"{duration:.3f}", "-map", "0:v:0?", "-map", "0:a:0?",
               "-c", "copy", "-movflags", "+faststart", dst]
        out = subprocess.run(cmd, capture_output=True, text=True)
        if out.returncode == 0:
            return
        start = 0.0  # fall back to a normal re-encode below
    cmd = [
        _require("ffmpeg"), "-nostdin", "-v", "error", "-y",
        "-ss", f"{start:.3f}", "-i", src, "-t", f"{duration:.3f}",
        "-map", "0:v:0?", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        dst,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg failed cutting {dst}:\n{out.stderr.strip()}")


def save_thumbnail(src: str, dst: str, at: float) -> None:
    cmd = [
        _require("ffmpeg"), "-nostdin", "-v", "error", "-y",
        "-ss", f"{at:.3f}", "-i", src, "-frames:v", "1",
        "-vf", "scale=480:-2", dst,
    ]
    subprocess.run(cmd, capture_output=True)
