"""HLS streams (Kick, Twitch): audio for analysis and exact clip sections,
both read from the SAME set of playlists so they share one timeline.

Why not the separate audio-only stream? Over a long VOD its timeline can
drift from the video's (stream hiccups, reconnects, muted parts), so a
moment found in the audio pointed at a different moment in the video.
The smallest *video* rendition carries the same audio with the same
timestamps as the 1080p one; we keep only its sound.
"""

from __future__ import annotations

import os
import re
import subprocess
import urllib.parse

from .media import _require
from .net import UA, request

def variants(master_url: str) -> list[dict]:
    """Parse a master playlist into [{url, bandwidth, height}]."""
    text = request(master_url, headers={"Accept": "*/*"})
    out, info = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = dict(re.findall(r'([A-Z\-]+)=("[^"]*"|[^,]*)', line.split(":", 1)[1]))
            res = attrs.get("RESOLUTION", "")
            info = {"bandwidth": int(attrs.get("BANDWIDTH", "0") or 0),
                    "height": int(res.split("x")[1]) if "x" in res else 0}
        elif line and not line.startswith("#") and info is not None:
            info["url"] = urllib.parse.urljoin(master_url, line)
            out.append(info)
            info = None
    if not out:  # not a master playlist: treat it as a single rendition
        out = [{"url": master_url, "bandwidth": 0, "height": 0}]
    return out


def _ffmpeg_download(args_in: list[str], args_out: list[str], dst: str,
                     duration: float, report: Progress, label: str,
                     should_cancel) -> None:
    """Run ffmpeg reading an HTTP(S)/HLS input, reporting progress."""
    part = dst + ".part" + os.path.splitext(dst)[1]
    cmd = [_require("ffmpeg"), "-nostdin", "-v", "error", "-y",
           "-user_agent", UA,
           "-reconnect", "1", "-reconnect_on_network_error", "1",
           "-reconnect_streamed", "1", "-reconnect_delay_max", "30",
           *args_in, *args_out, "-progress", "pipe:1", "-nostats", part]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    size = 0
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if should_cancel and should_cancel():
                proc.kill()
                raise InterruptedError("Download cancelled")
            key, _, val = line.strip().partition("=")
            if key == "total_size" and val.isdigit():
                size = int(val)
            elif key == "out_time_us" and val.lstrip("-").isdigit() and duration:
                frac = max(0.0, int(val) / 1e6 / duration)
                report(f"{label} – {size / 1e6:.0f} MB", min(frac, 1.0))
        proc.wait()
        if proc.returncode != 0:
            err = (proc.stderr.read() if proc.stderr else "")[-600:]
            raise RuntimeError(f"Download failed:\n{err.strip()}")
        os.replace(part, dst)
    finally:
        if proc.poll() is None:
            proc.kill()
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass




AUDIO_CACHE_TAG = "hls-timeline-v2"   # older cached audio could drift: re-download


def _pick_smallest(vs: list[dict]) -> dict:
    return min(vs, key=lambda v: (v["bandwidth"] or 1e12, v["height"] or 1e9))


def _pick_best(vs: list[dict], max_height: int) -> dict:
    ok = [v for v in vs if not v["height"] or v["height"] <= max_height] or vs
    return max(ok, key=lambda v: (v["height"], v["bandwidth"]))


def download_hls_audio(playlist: str, folder: str, duration: float,
                       report=None, should_cancel=None,
                       renditions: list[dict] | None = None) -> str:
    """Audio of the smallest rendition, re-timed to the playlist timeline
    (gaps filled with silence), saved as small mono 16 kHz AAC."""
    report = report or (lambda m, f: None)
    report("Reading stream", 0.0)
    vs = renditions or variants(playlist)
    dst = os.path.join(folder, "audio.m4a")
    _ffmpeg_download(["-i", _pick_smallest(vs)["url"]],
                     ["-map", "0:a:0", "-vn",
                      "-af", "aresample=async=1:min_hard_comp=0.1:first_pts=0",
                      "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "48k"],
                     dst, duration, report, "Downloading audio", should_cancel)
    with open(os.path.join(folder, "audio.done"), "w") as f:
        f.write(AUDIO_CACHE_TAG)
    return dst


def download_hls_section(playlist: str, folder: str, start: float, end: float,
                         report=None, should_cancel=None, max_height: int = 1080,
                         renditions: list[dict] | None = None) -> str:
    """[start, end] of the best rendition up to max_height, cut exactly.
    Input seeking on HLS only fetches the segments around the clip."""
    start = max(0.0, start)
    dst = os.path.join(folder, f"section_{start:.2f}_{end:.2f}.mp4")
    if os.path.exists(dst):
        return dst
    report = report or (lambda m, f: None)
    vs = renditions or variants(playlist)
    _ffmpeg_download(["-ss", f"{start:.3f}", "-i", _pick_best(vs, max_height)["url"]],
                     ["-t", f"{end - start:.3f}", "-map", "0:v:0", "-map", "0:a:0?",
                      "-af", "aresample=async=1:min_hard_comp=0.1",
                      "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                      "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                      "-movflags", "+faststart"],
                     dst, end - start, report, "Downloading clip video", should_cancel)
    return dst
