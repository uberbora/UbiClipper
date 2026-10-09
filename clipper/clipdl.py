"""Download clips that already exist on Twitch, Kick or YouTube.

Paste a clip link and get the mp4, no other software needed. The clip can
then be opened in UbiClipper as-is (whole clip = one moment) to add
subtitles, the 9:16 version and posting.

Links that work:
  Twitch   clips.twitch.tv/<slug>, twitch.tv/<channel>/clip/<slug>
  Kick     kick.com/<channel>/clips/clip_..., kick.com/<channel>?clip=clip_...
  YouTube  youtube.com/clip/..., youtube.com/shorts/..., youtu.be/... (any video)
"""

from __future__ import annotations

import os
import re
from typing import Callable

Progress = Callable[[str, float], None]

_KICK_CLIP = re.compile(r"kick\.com/(?P<chan>[\w.-]+)(?:/clips/|/?\?(?:[^#]+&)?clip=)"
                        r"(?P<id>clip_[\w-]+)", re.I)
_TWITCH_CLIP = re.compile(r"(?:clips\.twitch\.tv/(?:embed\?clip=)?|twitch\.tv/[\w-]+/clip/)"
                          r"(?P<id>[\w-]+)", re.I)
_YT_CLIP = re.compile(r"youtube\.com/(?:clip|shorts)/(?P<id>[\w-]+)", re.I)
_YT_ANY = re.compile(r"(?:youtube\.com/watch\?|youtu\.be/)", re.I)


def clip_kind(url: str) -> str | None:
    """'kick' / 'twitch' / 'youtube' for clip links, None for anything else
    (stream VODs are analysed instead of downloaded whole)."""
    u = url.strip()
    if _KICK_CLIP.search(u):
        return "kick"
    if _TWITCH_CLIP.search(u):
        return "twitch"
    if _YT_CLIP.search(u):
        return "youtube"
    return None


def is_youtube_video(url: str) -> bool:
    return bool(_YT_ANY.search(url))


def _safe(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" ._")
    return (name or "clip")[:80]


def download_clip(url: str, folder: str, report: Progress | None = None,
                  should_cancel: Callable[[], bool] | None = None) -> str:
    """Download a clip (or a whole YouTube video) to `folder`; returns the mp4."""
    report = report or (lambda m, f: None)
    os.makedirs(folder, exist_ok=True)
    kind = clip_kind(url)
    errors = []
    try:
        return _with_ytdlp(url, folder, report, should_cancel)
    except InterruptedError:
        raise
    except Exception as e:      # yt-dlp missing, Kick's bot wall, …
        errors.append(str(e).splitlines()[0] if str(e) else type(e).__name__)
    if kind == "kick":
        try:
            return _kick_direct(url, folder, report, should_cancel)
        except InterruptedError:
            raise
        except Exception as e:
            errors.append(str(e).splitlines()[0])
    raise RuntimeError("Couldn't download this clip.\n\n" + "\n".join(errors))


def _with_ytdlp(url, folder, report, should_cancel) -> str:
    from .remote import _downloaded_path, _hook, _run, _ytdlp
    yt = _ytdlp()
    opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(folder, "%(uploader,channel,creator|clip)s - "
                                        "%(title).70B [%(id)s].%(ext)s"),
        "restrictfilenames": False, "windowsfilenames": True,
        "progress_hooks": [_hook(report, "Downloading clip", should_cancel)],
        "retries": 10, "fragment_retries": 10, "concurrent_fragment_downloads": 4,
    }
    with yt.YoutubeDL(opts) as ydl:
        info = _run(ydl, url, download=True)
    path = _downloaded_path(info)
    if not path:
        raise RuntimeError("The download finished but the file wasn't found.")
    return path


def _kick_direct(url, folder, report, should_cancel) -> str:
    """Kick's own clip API (what the website uses) + FFmpeg."""
    from .hls import _ffmpeg_download
    from .kick import KICK_BASE
    from .net import get_json
    m = _KICK_CLIP.search(url)
    clip_id = m.group("id")
    data = get_json(f"{KICK_BASE}/api/v2/clips/{clip_id}/play")
    clip = data.get("clip") or data
    src = clip.get("clip_url") or clip.get("video_url")
    if not src:
        raise RuntimeError("Kick didn't return a video for this clip.")
    chan = (clip.get("channel") or {}).get("slug") or m.group("chan")
    title = clip.get("title") or clip_id
    dst = os.path.join(folder, _safe(f"{chan} - {title} [{clip_id}]") + ".mp4")
    if os.path.exists(dst):
        return dst
    dur = float(clip.get("duration") or 60)
    _ffmpeg_download(["-i", src], ["-c", "copy", "-movflags", "+faststart"],
                     dst, dur, report, "Downloading clip", should_cancel)
    return dst
