"""Make clips from a stream link (Twitch / YouTube / Kick VODs, via yt-dlp).

Built for slow connections:
  1. download ONLY the audio (Twitch offers an audio-only stream; that's
     roughly 60-130 MB per hour instead of several GB of video),
  2. analyse it like a normal video,
  3. download only the few video *sections* the user exports.
Everything is cached per video, so re-analysing with other settings or
exporting again doesn't download anything twice.
"""

from __future__ import annotations

import glob
import os
import re
import time
from dataclasses import dataclass
from typing import Callable

from .reframe import CONFIG_DIR

DOWNLOAD_DIR = os.path.join(CONFIG_DIR, "downloads")
URL_RE = re.compile(r"^https?://", re.I)

Progress = Callable[[str, float], None]


class YtDlpMissing(RuntimeError):
    pass


def is_url(text: str) -> bool:
    return bool(URL_RE.match(text.strip()))


def _ytdlp():
    try:
        import yt_dlp
        return yt_dlp
    except ImportError as e:
        raise YtDlpMissing("Links need yt-dlp. Install it with:\n    pip install yt-dlp") from e


def _hook(report: Progress, label: str, should_cancel):
    def hook(d: dict) -> None:
        if should_cancel and should_cancel():
            raise InterruptedError("Download cancelled")
        if d.get("status") != "downloading":
            return
        done = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        if total:
            frac = done / total
        elif d.get("fragment_count"):
            frac = (d.get("fragment_index") or 0) / d["fragment_count"]
        else:
            frac = 0.0
        speed = d.get("speed") or 0
        extra = f" – {done / 1e6:.0f}/{total / 1e6:.0f} MB" if total else f" – {done / 1e6:.0f} MB"
        if speed:
            extra += f" @ {speed / 1e6:.1f} MB/s"
        report(label + extra, min(frac, 1.0))
    return hook


def _run(ydl, url: str, download: bool):
    yt = _ytdlp()
    try:
        return ydl.extract_info(url, download=download)
    except yt.utils.DownloadError as e:
        if "cancel" in str(e).lower() or isinstance(e.__cause__, InterruptedError):
            raise InterruptedError("Download cancelled") from e
        raise RuntimeError(_friendly(str(e))) from e


def _friendly(msg: str) -> str:
    low = msg.lower()
    if "subscriber" in low or "login" in low or "sign in" in low:
        return ("This video needs a login (sub-only VOD or age-restricted). "
                "Only public videos work for now.\n\n" + msg)
    if "unsupported url" in low:
        return "This site or link isn't supported.\n\n" + msg
    return msg


@dataclass
class RemoteVideo:
    url: str
    title: str
    duration: float
    video_id: str
    site: str
    width: int | None
    height: int | None
    folder: str                      # cache folder for this video
    audio_path: str = ""             # local audio file once downloaded
    channel: str = ""
    game: str = ""
    platform: str = ""               # "kick", "twitch", "youtube", ...

    # ------------------------------------------------------------ factory
    @classmethod
    def probe(cls, url: str) -> "RemoteVideo":
        from .kick import KickVideo, is_kick_url
        if is_kick_url(url):
            # yt-dlp's Kick support is broken since Kick's new video IDs
            # (yt-dlp issue #17428), so Kick has its own code path.
            return KickVideo.open(url)
        yt = _ytdlp()
        with yt.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True,
                           "skip_download": True}) as ydl:
            info = _run(ydl, url, download=False)
        if info.get("_type") == "playlist":
            raise RuntimeError("That's a playlist or channel link. Paste the link of one video.")
        if info.get("is_live"):
            raise RuntimeError("That stream is still live. Wait until it ends and use the VOD link.")
        site = re.sub(r"\W+", "", str(info.get("extractor_key") or "web")).lower()
        vid = re.sub(r"[^\w\-]+", "_", str(info.get("id") or "video"))
        folder = os.path.join(DOWNLOAD_DIR, f"{site}_{vid}")
        os.makedirs(folder, exist_ok=True)
        rv = cls(url, str(info.get("title") or vid), float(info.get("duration") or 0),
                 vid, site, info.get("width"), info.get("height"), folder,
                 channel=str(info.get("uploader") or info.get("channel") or ""),
                 game=str(info.get("game") or (info.get("categories") or [""])[0] or ""),
                 platform="twitch" if "twitch" in site else
                          "youtube" if "youtube" in site else site)
        rv.audio_path = rv._cached_audio() or ""
        rv._set_renditions(info)
        return rv

    # ------------------------------------------------------------ HLS (Twitch)
    def _set_renditions(self, info: dict) -> None:
        """Video+audio HLS renditions (Twitch). Audio and clips are then read
        from these, so they share one timeline (the separate audio-only
        stream can drift from the video over a long VOD)."""
        rs = []
        for f in info.get("formats") or []:
            if not str(f.get("protocol", "")).startswith("m3u8"):
                continue
            if f.get("vcodec") in (None, "none") or f.get("acodec") == "none":
                continue
            rs.append({"url": f["url"], "bandwidth": int((f.get("tbr") or 0) * 1000),
                       "height": int(f.get("height") or 0)})
        self._renditions = rs if self.platform == "twitch" else []
        self._renditions_at = time.time()

    def _hls(self) -> list[dict]:
        rs = getattr(self, "_renditions", None) or []
        if rs and time.time() - getattr(self, "_renditions_at", 0) > 1800:
            # Twitch playlist links carry an expiring token: refresh them
            yt = _ytdlp()
            with yt.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True,
                               "skip_download": True}) as ydl:
                self._set_renditions(_run(ydl, self.url, download=False))
            rs = self._renditions
        return rs

    # ------------------------------------------------------------ chat
    def fetch_chat(self, report: Progress | None = None,
                   should_cancel=None) -> list[tuple[float, str]]:
        """[(seconds into the VOD, message)], cached. Empty if the site has
        no chat replay we can read."""
        from .chat import load_cached, save_cache
        cached = load_cached(self.folder)
        if cached is not None:
            return cached
        msgs = self._fetch_chat(report or (lambda m, f: None), should_cancel)
        save_cache(self.folder, msgs)
        return msgs

    def _fetch_chat(self, report, should_cancel) -> list[tuple[float, str]]:
        if self.platform == "twitch":
            from .chat import fetch_twitch_chat
            return fetch_twitch_chat(self.video_id.lstrip("v"), self.duration,
                                     report, should_cancel)
        return []

    @property
    def safe_title(self) -> str:
        return re.sub(r'[<>:"/\\|?*]+', "_", self.title).strip()[:80] or self.video_id

    # ------------------------------------------------------------ audio
    def _cached_audio(self) -> str | None:
        marker = os.path.join(self.folder, "audio.done")
        if not os.path.exists(marker):
            return None
        if self.platform in ("twitch", "kick"):
            from .hls import AUDIO_CACHE_TAG
            try:
                with open(marker) as f:
                    if f.read().strip() != AUDIO_CACHE_TAG:
                        return None   # made by an older version that could drift
            except OSError:
                return None
        files = [f for f in glob.glob(os.path.join(self.folder, "audio.*"))
                 if not f.endswith((".done", ".part", ".ytdl"))]
        return files[0] if files else None

    def download_audio(self, report: Progress | None = None,
                       should_cancel=None) -> str:
        """Audio only; reused if already downloaded."""
        if self.audio_path and os.path.exists(self.audio_path):
            return self.audio_path
        if self._hls():
            from .hls import download_hls_audio
            rs = self._hls()
            self.audio_path = download_hls_audio(rs[0]["url"], self.folder, self.duration,
                                                 report, should_cancel, renditions=rs)
            return self.audio_path
        report = report or (lambda m, f: None)
        yt = _ytdlp()
        opts = {
            "quiet": True, "no_warnings": True, "noplaylist": True,
            # audio-only if the site has it, else the smallest video+audio
            "format": "bestaudio/worst",
            "outtmpl": os.path.join(self.folder, "audio.%(ext)s"),
            "progress_hooks": [_hook(report, "Downloading audio", should_cancel)],
            "concurrent_fragment_downloads": 4,
            "continuedl": True,          # resume if the wifi drops
            "retries": 10, "fragment_retries": 10,
        }
        with yt.YoutubeDL(opts) as ydl:
            info = _run(ydl, self.url, download=True)
        path = _downloaded_path(info) or self._any_audio_file()
        if not path:
            raise RuntimeError("Download finished but the audio file wasn't found.")
        open(os.path.join(self.folder, "audio.done"), "w").close()
        self.audio_path = path
        return path

    def _any_audio_file(self) -> str | None:
        files = [f for f in glob.glob(os.path.join(self.folder, "audio.*"))
                 if not f.endswith((".done", ".part", ".ytdl"))]
        return files[0] if files else None

    # ------------------------------------------------------------ video sections
    def download_section(self, start: float, end: float,
                         report: Progress | None = None, should_cancel=None,
                         max_height: int = 1080) -> str:
        """Download just [start, end] of the video (frame-accurate cut)."""
        start = max(0.0, start)
        if self._hls():
            from .hls import download_hls_section
            rs = self._hls()
            return download_hls_section(rs[0]["url"], self.folder, start, end, report,
                                        should_cancel, max_height, renditions=rs)
        name = f"section_{start:.2f}_{end:.2f}"
        done = os.path.join(self.folder, name + ".done")
        if os.path.exists(done):
            hits = [f for f in glob.glob(os.path.join(self.folder, name + ".*"))
                    if not f.endswith((".done", ".part", ".ytdl"))]
            if hits:
                return hits[0]
        report = report or (lambda m, f: None)
        yt = _ytdlp()
        opts = {
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "format": (f"bestvideo[height<={max_height}]+bestaudio/"
                       f"best[height<={max_height}]/best"),
            "download_ranges": yt.utils.download_range_func(None, [(start, end)]),
            # re-encode at the cut points so the section starts exactly at
            # `start` (otherwise it snaps to the nearest keyframe, ~2 s off)
            "force_keyframes_at_cuts": True,
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(self.folder, name + ".%(ext)s"),
            "progress_hooks": [_hook(report, "Downloading clip video", should_cancel)],
            "concurrent_fragment_downloads": 4,
            "retries": 10, "fragment_retries": 10,
        }
        with yt.YoutubeDL(opts) as ydl:
            info = _run(ydl, self.url, download=True)
        path = _downloaded_path(info)
        if not path or not os.path.exists(path):
            hits = [f for f in glob.glob(os.path.join(self.folder, name + ".*"))
                    if not f.endswith((".done", ".part", ".ytdl"))]
            path = hits[0] if hits else None
        if not path:
            raise RuntimeError("Section download finished but the file wasn't found.")
        open(done, "w").close()
        return path


def _downloaded_path(info: dict | None) -> str | None:
    if not info:
        return None
    for d in info.get("requested_downloads") or []:
        p = d.get("filepath") or d.get("_filename")
        if p and os.path.exists(p):
            return p
    p = info.get("filepath") or info.get("_filename")
    return p if p and os.path.exists(p) else None
