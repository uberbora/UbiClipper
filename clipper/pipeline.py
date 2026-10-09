"""End-to-end pipeline: video -> analysis -> clips on disk + manifest.

The manifest (clips.json) is the hand-off point for future features:
subtitles, 9:16 reframing, titles/hashtags and auto-posting all read it.
"""

from __future__ import annotations

import json
import os
import re
import time

import numpy as np
from dataclasses import asdict, dataclass, field, replace
from typing import Callable

from . import __version__
from .detectors import Timeline, run_detectors
from .features import extract
from .media import MediaInfo, cut_clip, probe, save_thumbnail
from .selection import Clip, ClipSettings, select_clips
from .reframe import VerticalLayout, render_vertical
from .remote import RemoteVideo
from .subtitles import SubtitleStyle, build_captions, burn, placement_y, write_ass, write_srt
from .funny import score_words
from .posts import suggest, write_post_file
from .transcribe import TranscribeOptions, Transcript, get_transcriber

Progress = Callable[[str, float], None]

SOCIAL_DIR = "ready_social"          # 9:16 for TikTok / Reels / Shorts
FULLSCREEN_DIR = "ready_fullscreen"  # 1920x1080 for montages / YouTube
READY_DIRS = (SOCIAL_DIR, FULLSCREEN_DIR, "ready")   # "ready" = exports before 1.4
FULL_W, FULL_H = 1920, 1080   # (stage message, 0..1 overall)


@dataclass
class SubtitleOptions:
    transcribe: TranscribeOptions = field(default_factory=TranscribeOptions)
    style: SubtitleStyle = field(default_factory=SubtitleStyle)
    burn_in: bool = True        # also render a copy with captions on the video
    voice_track: int = 0        # audio track with just the mic, if the recording has one
    max_speakers: int = 10      # colour per person: 0/1 = off, 2..10 = at most that many
    source: str = ""            # set by export(): the original video


@dataclass
class PostInfo:
    """Used for title/hashtag ideas; filled from the link when there is one."""
    channel: str = ""
    platform: str = ""      # kick / twitch / youtube
    game: str = ""


@dataclass
class AnalysisResult:
    info: MediaInfo
    clips: list[Clip]
    timeline: Timeline
    settings: ClipSettings
    seconds_taken: float
    remote: "RemoteVideo | None" = None   # set when analysing a stream link
    notes: list[str] = field(default_factory=list)   # AI steps that were skipped, and why
    hearing: object = None                # listening-AI result (clipper.listen.Hearing)

    @property
    def title(self) -> str:
        if self.remote:
            return self.remote.safe_title
        return os.path.splitext(os.path.basename(self.info.path))[0]


def _fmt(t: float) -> str:
    t = int(t)
    return f"{t // 3600:02d}h{(t % 3600) // 60:02d}m{t % 60:02d}s"


def analyze(path: str, settings: ClipSettings | None = None,
            progress: Progress | None = None,
            should_cancel: Callable[[], bool] | None = None,
            rank: TranscribeOptions | None = None,
            chat: list[tuple[float, str]] | None = None,
            listen: bool = False, ai_judge: bool = False,
            game: str = "") -> AnalysisResult:
    """Find moments. With `rank`, the best candidates are also transcribed and
    re-ranked by what was said (laughing, reactions, swearing).
    listen: the listening AI (laughter/scream/explosion recognition).
    ai_judge: a local language model rates each transcribed candidate
    (needs `rank`)."""
    settings = settings or ClipSettings()
    report = progress or (lambda msg, f: None)
    t0 = time.time()
    notes: list[str] = []

    report("Reading video info", 0.0)
    info = probe(path)
    if not info.has_audio:
        raise RuntimeError("This video has no audio track. UbiClipper finds "
                           "highlights from the audio.")

    track = min(settings.audio_track, max(0, len(info.audio_tracks) - 1))
    listen_share = 0.6 if rank else 0.85
    listener = None
    if listen:
        try:
            from .listen import Listener
            listener = Listener(report=lambda m: report(m, 0.0))
        except Exception as e:      # no internet on first use, broken onnxruntime...
            notes.append(f"Listening AI skipped: {e}")
    what = "Listening to the video" + (" (with AI)" if listener else "")
    feats = extract(path, info.duration,
                    progress=lambda f: report(what, listen_share * f),
                    should_cancel=should_cancel, audio_track=track,
                    on_audio=listener.feed if listener else None)
    hearing = None
    if listener:
        try:
            hearing = listener.finish()
        except Exception as e:
            notes.append(f"Listening AI skipped: {e}")
    report("Scoring moments", listen_share + 0.02)
    tl = run_detectors(feats, voice_focus=settings.voice_focus, chat=chat,
                       hearing=hearing)
    duration = info.duration or feats.duration
    clips = select_clips(tl, duration, settings)
    for c in clips:
        c.audio_score = c.score
    if ai_judge and not rank:
        notes.append("AI judge skipped: it needs 'Rank by what's said' (it reads "
                     "the transcript).")
    if rank and clips:
        clips = _rank_by_words(path, track, tl, duration, settings, clips, rank,
                               lambda m, f: report(m, listen_share + 0.05 + (0.95 - listen_share) * f),
                               should_cancel, chat=chat, hearing=hearing,
                               ai_judge=ai_judge, game=game, notes=notes)
    report(f"Found {len(clips)} clips", 1.0)
    res = AnalysisResult(info, clips, tl, settings, time.time() - t0, notes=notes)
    res.hearing = hearing
    return res


def _rank_by_words(path, track, tl, duration, settings, strict, opts, report,
                   should_cancel, chat=None, hearing=None, ai_judge=False, game="",
                   notes=None) -> list[Clip]:
    """Transcribe a wider pool of candidates and re-rank by sound + words
    (+ the AI judge's opinion when it's on)."""
    n_final = settings.max_clips or len(strict)
    # the judge can spot quiet funny moments, so give it more to look at
    pool_size = int(max(16 if ai_judge else 10, min(2 * n_final, n_final + 40)))
    pool = select_clips(tl, duration, replace(
        settings, max_clips=pool_size, sensitivity=min(1.0, settings.sensitivity + 0.3)))
    report("Loading speech model", 0.0)
    transcriber = get_transcriber(opts, status=lambda m: report(m, 0.0))
    top_audio = max(c.score for c in pool) or 1.0
    share = 0.6 if ai_judge else 1.0      # progress bar split: words / judge
    words_of: dict[int, list] = {}
    for k, c in enumerate(pool):
        if should_cancel and should_cancel():
            raise InterruptedError("Analysis cancelled")
        report(f"Checking what's said ({k + 1}/{len(pool)}, "
               f"{transcriber.device.upper()})", share * k / len(pool))
        tr = transcriber.transcribe_file(path, start=c.start, duration=c.duration,
                                         track=track)
        c.transcript = dict(tr.to_dict(), model=opts.model, also=opts.also_language)
        ts = score_words(tr.words, c.duration, tr.language or opts.language)
        c.audio_score, c.text_score = c.score, round(ts.score, 3)
        combined = 0.6 * (c.score / top_audio) + 0.4 * ts.score
        if ts.words == 0:
            combined -= 0.15          # nobody says anything: rarely a good short
        c.score = round(max(combined, 0.0), 4)
        why = ts.reason()
        if why:
            c.reasons = [why] + [r for r in c.reasons if r != "Energy spike"]
        words_of[id(c)] = tr.words
    if ai_judge:
        try:
            _judge_pool(pool, words_of, top_audio, chat, hearing, game,
                        opts.language,
                        lambda m, f: report(m, share + (1 - share) * f), should_cancel)
        except InterruptedError:
            raise
        except Exception as e:     # never lose an analysis over the judge
            if notes is not None:
                notes.append(f"AI judge skipped: {e}")
    ranked = sorted(pool, key=lambda c: -c.score)
    chosen = ranked[:n_final]
    if not settings.max_clips:
        # auto: also keep clearly funny extras, and drop moments that are far
        # weaker than the best once words are counted (e.g. a lone gunshot)
        extra = [c for c in ranked[n_final:] if (c.text_score or 0) >= 0.55
                 or (c.ai or {}).get("score", 0) >= 7]
        chosen += extra[: max(0, int(np.clip(round(duration / 120), 8, 80)) - n_final)]
        top = chosen[0].score if chosen else 0
        chosen = [c for c in chosen if c.score >= 0.2 * top] or chosen[:1]
    return chosen


def _judge_pool(pool, words_of, top_audio, chat, hearing, game, language, report,
                should_cancel) -> None:
    """Let the AI judge rate every transcribed candidate and fold its score in."""
    from .judge import Moment, audio_tags, get_judge, transcript_lines
    judge = get_judge(report=lambda m: report(m, 0.0), should_cancel=should_cancel)
    moments = []
    for c in pool:
        heard = hearing.at(c.start, c.end) if hearing is not None else {}
        said = [m for t, m in (chat or []) if c.start <= t <= c.end + 8][:15]
        # 'auto' language: use what Whisper detected for this moment
        lang = language or (c.transcript or {}).get("language") or "en"
        moments.append(Moment(transcript_lines(words_of.get(id(c), [])),
                              audio_tags(heard), said, game, lang))
    step = 6
    for i in range(0, len(pool), step):
        if should_cancel and should_cancel():
            raise InterruptedError("Analysis cancelled")
        report(f"AI judge reading moments ({min(i + step, len(pool))}/{len(pool)}, "
               f"{judge.device.upper()})", i / len(pool))
        for c, v in zip(pool[i:i + step], judge.rate(moments[i:i + step], batch=step)):
            if not v.ok:
                continue
            c.ai = {"score": round(v.score, 1), "why": v.why, "title": v.title}
            ai = v.score / 10.0
            audio = (c.audio_score or 0) / top_audio
            c.score = round(max(0.45 * audio + 0.2 * (c.text_score or 0) + 0.35 * ai
                                - (0.1 if not words_of.get(id(c)) else 0), 0.0), 4)
            if v.why and v.score >= 5:
                c.reasons = [f"AI: {v.why}"] + c.reasons[:2]


def export(result: AnalysisResult, out_dir: str,
           progress: Progress | None = None,
           should_cancel: Callable[[], bool] | None = None,
           thumbnails: bool = True,
           subtitles: SubtitleOptions | None = None,
           vertical: VerticalLayout | None = None,
           post_info: PostInfo | None = None,
           fullscreen: bool | None = None) -> str:
    """Cut clips; optionally transcribe, and render the finished versions:
    ready_social/      9:16 with captions (TikTok / Reels / Shorts)
    ready_fullscreen/  1920x1080 with captions (montages, YouTube)
    fullscreen=None follows subtitles.burn_in (the old 'burn captions' switch)."""
    report = progress or (lambda msg, f: None)
    src = result.info.path
    # ready_social/ + ready_fullscreen/ = finished   raw/ = clean cuts   extras/ = the rest
    if fullscreen is None:
        fullscreen = bool(subtitles and subtitles.burn_in)
    finished_elsewhere = bool(vertical or fullscreen)
    folders = {"social": os.path.join(out_dir, SOCIAL_DIR),
               "fullscreen": os.path.join(out_dir, FULLSCREEN_DIR),
               "raw": os.path.join(out_dir, "raw") if finished_elsewhere
               else os.path.join(out_dir, "ready"),
               "extras": os.path.join(out_dir, "extras")}
    if not vertical:
        folders.pop("social")
    if not fullscreen:
        folders.pop("fullscreen")
    for d in folders.values():
        os.makedirs(d, exist_ok=True)
    base = re.sub(r"_+", "_", re.sub(r"[^\w\-]+", "_", result.title)).strip("_")[:40] or "clip"
    remote = result.remote
    ranked = sorted(result.clips, key=lambda c: -c.score)
    n = max(1, len(ranked))

    transcriber = None
    failures: list[str] = []
    if subtitles:
        subtitles.source = src
        subtitles.voice_track = result.settings.audio_track
        transcriber = get_transcriber(subtitles.transcribe,
                                      status=lambda m: report(m, 0.0))

    # Pass 1: cut + transcribe every clip. Pass 2 (after finding who speaks
    # across ALL clips, so everyone keeps one colour): render + post files.
    speak = bool(subtitles and subtitles.max_speakers > 1)
    P1 = 0.55 if speak else 0.5            # share of the progress bar for pass 1
    state: dict[int, dict] = {}
    for i, clip in enumerate(ranked, 1):
        def step(msg: str, within: float) -> None:
            report(f"Clip {i}/{n}: {msg}", P1 * (i - 1 + within) / n)

        if should_cancel and should_cancel():
            raise InterruptedError("Export cancelled")
        name = f"{i:02d}_{base}_{_fmt(clip.start)}"
        clip.file = os.path.join(folders["raw"], name + ".mp4")
        if remote:
            # link: fetch just this clip's video, already cut exactly
            section = remote.download_section(
                clip.start, clip.end, report=lambda m, f: step(m, 0.2 * f),
                should_cancel=should_cancel)
            # safety net: does the downloaded video really show the moment
            # we analysed? Compare loudness patterns; fix the cut if not.
            shift = section_offset(section, result.timeline, clip.start)
            if shift:
                clip.align_shift = shift
                section = remote.download_section(
                    clip.start - shift, clip.end - shift,
                    report=lambda m, f: step(m, 0.2 * f), should_cancel=should_cancel)
            step("cutting", 0.2)
            cut_clip(section, clip.file, 0.0, clip.duration, copy=True)
            frame_src, offset = section, 0.0
        else:
            step("cutting", 0.0)
            cut_clip(src, clip.file, clip.start, clip.duration)
            frame_src, offset = src, clip.start
        if thumbnails:
            clip.thumbnail = os.path.join(folders["extras"], name + ".jpg")
            save_thumbnail(frame_src, clip.thumbnail, offset + (clip.peak - clip.start))

        words, lang = None, None
        if subtitles and transcriber:
            if should_cancel and should_cancel():
                raise InterruptedError("Export cancelled")
            try:
                tr = _transcribe_clip(clip, name, folders, subtitles, transcriber, step,
                                      reuse=not remote)
                words, lang = tr.words, tr.language
            except Exception as e:  # keep going; the clean clip is still saved
                failures.append(f"Clip {i} subtitles: {e}")
                clip.transcript = {"error": str(e)}

        state[i] = {"name": name, "words": words, "lang": lang}
        fixed = bool((clip.transcript or {}).get("speakers_fixed"))
        if not fixed:
            for w in words or []:
                w.speaker = 0          # decided below for all clips together
        if speak and words and not fixed:      # colours set by hand stay as they are
            step("listening to voices", 0.9)
            try:
                from .speakers import voices
                state[i]["voices"] = voices(_voice_audio(clip, subtitles), words)
            except Exception as e:
                clip.transcript = dict(clip.transcript or {}, speaker_error=str(e)[:200])

    if speak:
        report("Finding who speaks (all clips together)", P1)
        try:
            from .speakers import diarize_many
            idx = [i for i in state if state[i].get("voices")]
            labels = diarize_many([state[i]["voices"] for i in idx], subtitles.max_speakers)
            for i, labs in zip(idx, labels):
                clip = ranked[i - 1]
                for w, spk in zip(state[i]["words"], labs):
                    w.speaker = spk
                tr = Transcript(state[i]["lang"], state[i]["words"])
                clip.transcript = dict(clip.transcript or {}, words=tr.to_dict()["words"],
                                       speakers=len(set(labs)), diarized=True)
        except Exception as e:  # subtitles still work, just one colour
            failures.append(f"Speaker colours: {e}")

    for i, clip in enumerate(ranked, 1):
        def step(msg: str, within: float) -> None:
            report(f"Clip {i}/{n}: {msg}", P1 + (1 - P1) * (i - 1 + within) / n)

        if should_cancel and should_cancel():
            raise InterruptedError("Export cancelled")
        name, words, lang = state[i]["name"], state[i]["words"], state[i]["lang"]
        w, h = result.info.width, result.info.height
        if not w or not h:            # e.g. analysed from audio only (links)
            ci = probe(clip.file)
            w, h = ci.width or 1920, ci.height or 1080
        style = subtitles.style if subtitles else None
        if vertical:
            try:
                step("making 9:16 version", 0.5)
                ass = None
                if words:
                    st = replace(style, max_chars=min(style.max_chars, 16))
                    caps = build_captions(words, st, lang)
                    ass = os.path.join(folders["extras"], name + "_vertical.ass")
                    write_ass(caps, ass, vertical.width, vertical.height, st,
                              placement_y(st, vertical.caption_position(w, h), True))
                clip.vertical_file = os.path.join(folders["social"], name + ".mp4")
                render_vertical(clip.file, clip.vertical_file, vertical, w, h, ass)
            except Exception as e:
                failures.append(f"Clip {i} render: {e}")
        if fullscreen:
            try:
                step("making 1920x1080 version", 0.8)
                ass = None
                if words and style:
                    caps = build_captions(words, style, lang)
                    ass = os.path.join(folders["extras"], name + "_fullscreen.ass")
                    write_ass(caps, ass, FULL_W, FULL_H, style,
                              placement_y(style, 0.80, False))
                clip.subtitled_file = os.path.join(folders["fullscreen"], name + ".mp4")
                burn(clip.file, ass, clip.subtitled_file, size=(FULL_W, FULL_H))
            except Exception as e:
                failures.append(f"Clip {i} render: {e}")

        # title + hashtag ideas, saved next to the finished clip
        try:
            info = post_info or PostInfo()
            if remote:
                info = PostInfo(remote.channel or info.channel,
                                remote.platform or info.platform, remote.game or info.game)
            lang = (subtitles.transcribe.language if subtitles else None) or "tr"
            said = words or (Transcript.from_dict(clip.transcript).words
                             if clip.transcript and clip.transcript.get("words") else [])
            clip.post = suggest(said, clip.reasons, lang, info.game, info.platform,
                                info.channel, bool(style and style.censor), seed=i)
            ai_title = (clip.ai or {}).get("title")
            if ai_title and ai_title not in clip.post["titles"]:
                clip.post["titles"] = [ai_title] + clip.post["titles"][:2]
            final = clip.vertical_file or clip.subtitled_file or clip.file
            write_post_file(os.path.splitext(final)[0] + ".txt", clip.post, lang)
        except Exception as e:  # never lose an export over a text file
            failures.append(f"Clip {i} title ideas: {e}")

    if failures:
        report(f"Done, but {len(failures)} step(s) failed", 1.0)

    manifest = os.path.join(folders["extras"], "clips.json")
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump({
            "app": "UbiClipper", "version": __version__,
            "source": remote.url if remote else os.path.abspath(src),
            "title": result.title,
            "link_duration": round(remote.duration, 2) if remote else None,
            "source_duration": round(result.info.duration, 2),
            "analysis_seconds": round(result.seconds_taken, 1),
            "settings": asdict(result.settings),
            "subtitles": asdict(subtitles) if subtitles else None,
            "vertical": asdict(vertical) if vertical else None,
            "clips": [dict(rank=i, **c.to_dict()) for i, c in enumerate(ranked, 1)],
        }, f, indent=2)
    if failures:
        raise PartialExport(manifest, failures)
    report("Done", 1.0)
    return manifest


class PartialExport(RuntimeError):
    """Clips were exported but some subtitle/render steps failed."""

    def __init__(self, manifest: str, failures: list[str]) -> None:
        self.manifest, self.failures = manifest, failures
        super().__init__("Clips were exported, but some steps failed:\n"
                         + "\n".join(failures[:5]))


def section_offset(section: str, tl: Timeline, start: float,
                   search: float = 30.0) -> float:
    """Seconds by which a downloaded section is off from the analysed audio
    (0 if it lines up or we can't tell). Compares the loudness pattern of the
    section with the analysis around `start`."""
    try:
        from .detectors import Context
        a = Context.build(extract(section)).db
        L = tl.loudness_db
        if L is None or len(a) < 8 or np.std(a) < 2.0:
            return 0.0
        s0 = int(round(start / tl.hop))
        n = len(a)
        scores = {}
        for lag in range(-int(search / tl.hop), int(search / tl.hop) + 1):
            i = s0 + lag
            if i < 0 or i + n > len(L):
                continue
            b = L[i:i + n]
            if np.std(b) < 2.0:
                continue
            scores[lag] = float(np.corrcoef(a, b)[0, 1])
        if not scores:
            return 0.0
        lag, best = max(scores.items(), key=lambda kv: kv[1])
        at_zero = max((scores.get(k, -1) for k in (-1, 0, 1)), default=-1)
        if abs(lag) >= 2 and best > 0.6 and best - at_zero > 0.15:
            return lag * tl.hop
    except Exception:
        pass
    return 0.0


def clip_folder(root: str, video: str, title: str | None = None) -> str:
    """<root>/<video name>, or '<video name> (2)' etc. if that's taken."""
    stem = re.sub(r'[<>:"/\\|?*]+', "_",
                  title or os.path.splitext(os.path.basename(video))[0]).strip()
    path = os.path.join(root, stem or "clips")
    n = 2
    while os.path.exists(path):
        path = os.path.join(root, f"{stem} ({n})")
        n += 1
    return path


def _voice_audio(clip, subtitles) -> np.ndarray:
    """The clip's audio for voice fingerprints (mic-only track if there is one)."""
    from .media import stream_audio
    track = subtitles.voice_track
    chunks = (list(stream_audio(clip.file)) if track == 0 else
              list(stream_audio(subtitles.source, track=track,
                                start=clip.start, duration=clip.duration)))
    return np.concatenate(chunks) if chunks else np.zeros(1, np.float32)


def _transcribe_clip(clip, name, folders, subtitles, transcriber, step, reuse=True):
    """Subtitles come from the clip's own audio. Transcripts made while
    ranking are reused only for local files, where they are guaranteed to be
    the same audio; for links we always listen to the downloaded clip."""
    t = clip.transcript or {}
    if t.get("edited") and t.get("words") is not None:
        tr = Transcript.from_dict(t)      # fixed by hand in the subtitle editor: keep it
    elif reuse and t.get("words") is not None and t.get("model") == subtitles.transcribe.model \
            and t.get("language") == subtitles.transcribe.language \
            and t.get("also") == subtitles.transcribe.also_language:
        tr = Transcript.from_dict(t)      # already transcribed while ranking
    else:
        step(f"transcribing ({transcriber.device.upper()})", 0.25)
        track = subtitles.voice_track
        tr = transcriber.transcribe_file(clip.file) if track == 0 else \
            transcriber.transcribe_file(subtitles.source, start=clip.start,
                                        duration=clip.duration, track=track)
        clip.transcript = dict(tr.to_dict(), model=subtitles.transcribe.model,
                               also=subtitles.transcribe.also_language)
    clip.subtitle_file = os.path.join(folders["extras"], name + ".srt")
    write_srt(build_captions(tr.words, subtitles.style, tr.language), clip.subtitle_file)
    return tr
