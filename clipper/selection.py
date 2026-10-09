"""Turn a score timeline into concrete clip ranges."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from .detectors import Timeline


@dataclass
class ClipSettings:
    max_len: float = 60.0      # hard cap for Shorts / Reels / TikTok
    min_len: float = 10.0
    pre_roll: float = 12.0     # setup before the reaction (the "why it's funny")
    post_roll: float = 4.0     # let the reaction land
    max_clips: int | None = None  # None = scale with video length
    sensitivity: float = 0.5   # 0 = only the very best, 1 = more clips
    min_gap: float = 5.0       # seconds between clips
    voice_focus: float = 0.4   # 0 = any loud sound counts, 1 = only voice reactions
    audio_track: int = 0       # which audio track to listen to (mic-only track is best)


@dataclass
class Clip:
    start: float
    end: float
    peak: float
    score: float
    reasons: list[str] = field(default_factory=list)
    detail: dict[str, float] = field(default_factory=dict)
    file: str | None = None
    thumbnail: str | None = None
    subtitled_file: str | None = None
    vertical_file: str | None = None      # 9:16 version (captions included)
    subtitle_file: str | None = None      # .srt, for uploading to platforms
    transcript: dict | None = None        # text + word timings (clip-relative)
    audio_score: float | None = None      # from the sound alone
    text_score: float | None = None       # from what was said (funny-word ranking)
    post: dict | None = None              # title ideas + hashtags
    align_shift: float | None = None      # link clips: correction applied (s)
    ai: dict | None = None                # AI judge: score 0-10, why, title

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration"] = round(self.duration, 2)
        return d


def auto_clip_count(duration: float) -> int:
    """Upper limit in 'auto' mode. Sensitivity decides how many moments are
    good enough; this only stops a long stream producing a wall of
    mediocre clips. ~1 per 4 minutes, at least 5, at most 40."""
    return int(np.clip(round(duration / 240), 5, 40))


def _quietest(loud: np.ndarray, hop: float, lo: float, hi: float) -> float:
    a, b = max(0, int(lo / hop)), min(len(loud), int(np.ceil(hi / hop)) + 1)
    if b <= a:
        return lo
    return (a + int(np.argmin(loud[a:b]))) * hop


def select_clips(tl: Timeline, duration: float,
                 s: ClipSettings | None = None) -> list[Clip]:
    s = s or ClipSettings()
    hop, score = tl.hop, tl.combined
    n = len(score)
    duration = min(duration, n * hop) if duration else n * hop
    limit = s.max_clips or auto_clip_count(duration)

    # adaptive threshold: top few % of the video, never below an absolute floor
    pct = 99.0 - 6.0 * s.sensitivity
    thresh = max(np.percentile(score, pct), 0.12 - 0.06 * s.sensitivity)
    if s.max_clips:
        # an exact number was asked for: dig deeper than 'auto' would, so a
        # long stream really yields that many (weak ones sort to the bottom)
        thresh = min(thresh, max(float(np.percentile(score, 75)), 0.03))

    # local maxima within ±10 s
    rad = int(10 / hop)
    order = np.argsort(score)[::-1]
    taken = np.zeros(n, bool)
    peaks: list[int] = []
    for i in order:
        if score[i] < thresh:
            break
        if taken[i]:
            continue
        peaks.append(int(i))
        taken[max(0, i - rad): i + rad + 1] = True

    clips: list[Clip] = []
    for p in peaks:
        if len(clips) >= limit:
            break
        pk = score[p]
        l = r = p
        cap = int(25 / hop)
        while l > 0 and p - l < cap and score[l - 1] > 0.5 * pk:
            l -= 1
        while r < n - 1 and r - p < cap and score[r + 1] > 0.5 * pk:
            r += 1
        peak_t = p * hop
        start = l * hop - s.pre_roll
        end = (r + 1) * hop + s.post_roll

        if end - start > s.max_len:  # keep more setup than aftermath
            start = max(start, peak_t - 0.65 * s.max_len)
            end = start + s.max_len
        if end - start < s.min_len:
            extra = s.min_len - (end - start)
            start -= extra * 0.6
            end += extra * 0.4

        # cut on quiet moments so we don't chop a sentence in half
        if tl.loudness_db is not None:
            start = _quietest(tl.loudness_db, hop, start - 2.0, start + 1.0)
            end = _quietest(tl.loudness_db, hop, end - 1.0, end + 2.0) + hop
        start = max(0.0, min(start, peak_t - 1.0))
        end = min(duration, max(end, peak_t + 1.0))
        if end - start > s.max_len:
            end = start + s.max_len

        if any(start < c.end + s.min_gap and end > c.start - s.min_gap
               for c in clips):
            continue

        # reasons describe THE moment (±1.5 s around the peak), not the
        # strongest thing anywhere in the clip; at most the top 3
        a, b = max(0, p - 3), min(n, p + 4)
        detail = {k: round(float(v[a:b].max()), 3) for k, v in tl.parts.items()}
        reasons = [tl.labels[k] for k, v in
                   sorted(detail.items(), key=lambda kv: -kv[1]) if v >= 0.6][:3]
        clips.append(Clip(round(start, 2), round(end, 2), round(peak_t, 2),
                          round(float(pk), 4), reasons or ["Energy spike"],
                          detail))
    return clips
