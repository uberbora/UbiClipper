"""Kick VOD links, without yt-dlp.

Kick moved to new video IDs (UUIDv7, e.g. 01a0f921-efd0-7dec-...) that its
old video API doesn't know, which broke yt-dlp (issue #17428). A UUIDv7
starts with the creation time in milliseconds, and for Kick VODs that is
exactly the stream's start time. So we:
  1. decode the start time from the link,
  2. find that VOD in the channel's video list (/api/v2/channels/<slug>/videos),
  3. read its HLS stream (master.m3u8) directly with FFmpeg:
       - audio from the smallest rendition (~100 MB per hour),
       - clip sections from the best rendition up to 1080p, cut exactly.
Chat replay comes from /api/v2/channels/<id>/messages (paged by cursor).
"""

from __future__ import annotations

import datetime as dt
import os
import re

from .hls import download_hls_audio, download_hls_section, variants
from .net import NetError, get_json
from .remote import DOWNLOAD_DIR, Progress, RemoteVideo

KICK_BASE = os.environ.get("UBICLIPPER_KICK_BASE", "https://kick.com")
_URL_RE = re.compile(
    r"kick\.com/(?:(?P<chan>[\w.-]+)/videos/|video/)(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I)


def is_kick_url(url: str) -> bool:
    return "kick.com" in url.lower()


def uuid7_time(uid: str) -> dt.datetime | None:
    """Creation time stored in a UUIDv7 (version nibble 7), else None."""
    hexs = uid.replace("-", "")
    if len(hexs) != 32 or hexs[12] != "7":
        return None
    return dt.datetime.fromtimestamp(int(hexs[:12], 16) / 1000, dt.timezone.utc)


def _parse_time(s: str) -> dt.datetime:
    s = s.strip().replace("Z", "+00:00")
    if "T" not in s:
        s = s.replace(" ", "T")
    t = dt.datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _friendly(e: Exception, what: str) -> RuntimeError:
    msg = str(e)
    if isinstance(e, NetError) and e.status == 403:
        msg += ("\n\nKick's bot protection blocked the request. Installing "
                "curl_cffi usually fixes this (run_windows.bat installs it).")
    return RuntimeError(f"Couldn't {what} from Kick.\n\n{msg}")


# ------------------------------------------------------------------ video
class KickVideo(RemoteVideo):
    source: str = ""        # master.m3u8
    channel_id: int = 0
    start_utc: dt.datetime | None = None

    @classmethod
    def open(cls, url: str) -> "KickVideo":
        m = _URL_RE.search(url)
        if not m:
            raise RuntimeError("That Kick link isn't a VOD link. It should look like\n"
                               "https://kick.com/<channel>/videos/<id>")
        chan, vid = (m.group("chan") or "").lower(), m.group("id").lower()
        item = None
        try:
            if chan:
                item = cls._find_in_channel(chan, vid)
            if item is None:  # older links: the classic per-video API
                item = cls._old_api(vid)
        except NetError as e:
            raise _friendly(e, "read the video info") from e
        if item is None:
            raise RuntimeError(
                "Couldn't find this VOD on the channel. Kick deletes VODs after "
                "a while; check the link opens in your browser.")

        ls = item.get("livestream") or item           # old API nests it
        source = item.get("source") or ls.get("source") or ""
        if not source:
            raise RuntimeError("Kick didn't return a stream for this VOD "
                               "(it may be sub-only or still processing).")
        if ls.get("is_live"):
            raise RuntimeError("That stream is still live. Wait until it ends.")
        cats = ls.get("categories") or item.get("categories") or []
        game = (cats[0].get("name") if cats and isinstance(cats[0], dict) else "") or ""
        chan_info = ls.get("channel") or {}
        chan = chan or str(chan_info.get("slug") or "")
        folder = os.path.join(DOWNLOAD_DIR, f"kick_{vid}")
        os.makedirs(folder, exist_ok=True)
        dur_ms = float(ls.get("duration") or item.get("duration") or 0)
        rv = cls(url, str(ls.get("session_title") or item.get("session_title") or vid),
                 dur_ms / 1000.0, vid, "kick", None, None, folder,
                 channel=chan, game=game, platform="kick")
        rv.source = source
        rv.channel_id = int(ls.get("channel_id") or item.get("channel_id") or 0)
        st = ls.get("start_time") or item.get("start_time")
        rv.start_utc = _parse_time(st) if st else uuid7_time(vid)
        rv.audio_path = rv._cached_audio() or ""
        return rv

    @staticmethod
    def _find_in_channel(chan: str, vid: str) -> dict | None:
        videos = get_json(f"{KICK_BASE}/api/v2/channels/{chan}/videos")
        if isinstance(videos, dict):
            videos = videos.get("data") or videos.get("videos") or []
        t7 = uuid7_time(vid)
        best, best_gap = None, 1e9
        for it in videos:
            v = it.get("video") or {}
            if vid in {str(v.get("uuid", "")).lower(), str(it.get("uuid", "")).lower()}:
                return it
            if t7 and it.get("start_time"):
                gap = abs((_parse_time(it["start_time"]) - t7).total_seconds())
                if gap < best_gap:
                    best, best_gap = it, gap
        return best if best_gap <= 120 else None

    @staticmethod
    def _old_api(vid: str) -> dict | None:
        try:
            return get_json(f"{KICK_BASE}/api/v1/video/{vid}")
        except NetError as e:
            if e.status == 404:
                return None
            raise

    # ------------------------------------------------------------ downloads
    def download_audio(self, report: Progress | None = None, should_cancel=None) -> str:
        if self.audio_path and os.path.exists(self.audio_path):
            return self.audio_path
        try:
            self.audio_path = download_hls_audio(self.source, self.folder, self.duration,
                                                 report, should_cancel)
        except NetError as e:
            raise _friendly(e, "read the stream") from e
        return self.audio_path

    def download_section(self, start: float, end: float, report: Progress | None = None,
                         should_cancel=None, max_height: int = 1080) -> str:
        try:
            return download_hls_section(self.source, self.folder, start, end,
                                        report, should_cancel, max_height)
        except NetError as e:
            raise _friendly(e, "read the stream") from e

    # ------------------------------------------------------------ chat
    def _fetch_chat(self, report, should_cancel) -> list[tuple[float, str]]:
        from .chat import fetch_kick_chat
        if not self.channel_id or not self.start_utc:
            return []
        return fetch_kick_chat(KICK_BASE, self.channel_id, self.start_utc,
                               self.duration, report, should_cancel)
