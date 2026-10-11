"""Speech-to-text with faster-whisper (word-level timestamps).

Transcription runs per exported clip (max 60 s each), not on the whole
6-hour stream, so it stays fast even on CPU.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import sys
import types
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .media import SAMPLE_RATE, stream_audio

# Display name -> Whisper language code (None = auto-detect)
from .lang_data import SPOKEN as LANGUAGES  # noqa: E402  (native name -> code)

# Display name -> faster-whisper model name
MODELS = {
    "turbo (recommended)": "large-v3-turbo",
    "small (fastest)": "small",
    "medium": "medium",
    "large-v3 (most accurate, slow)": "large-v3",
}

# Whisper is known to "hear" these on silence/music, because they appear at
# the end of countless subtitled videos it was trained on.
HALLUCINATIONS = [
    r"altyaz[ıi]\s*m\.?\s*k\.?",
    r"izledi[ğg]iniz i[çc]in te[şs]ekk[üu]r",
    r"abone olmay[ıi] unutmay[ıi]n",
    r"altyaz[ıi].*(taraf[ıi]ndan|haz[ıi]rlad[ıi])",
    r"thanks? (you )?for watching",
    r"subtitles? by",
    r"please subscribe",
]
_HALLU_RE = re.compile("|".join(HALLUCINATIONS), re.IGNORECASE)

# The prompt nudges Whisper toward Turkish spelling and casual stream talk.
# Whisper learned mostly from cleaned-up subtitles, so it tends to "hear" a
# polite phrase instead of a swear word; showing it some slang and swearing
# in the prompt makes it write what was actually said.
from .lang_data import DATA as _LANG_DATA  # noqa: E402
DEFAULT_PROMPTS = {code: d["prompt"] for code, d in _LANG_DATA.items()
                   if code != "en"}   # English needs no hint

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Kept with the user's settings so installing a new version never touches it.
CORRECTIONS_FILE = os.path.join(os.path.expanduser("~"), ".ubiclipper", "corrections.txt")
_OLD_CORRECTIONS = os.path.join(PROJECT_DIR, "corrections.txt")   # before v1.8
_STRIP = ".,!?…;:\"'“”«»()"


_FILLER_RE = re.compile(r"^(?:ı{2,}|e{2,}h*|ee+m+|hm+|h?mm+|uh+|um+|eh+m*|erm+|ah+m+)$", re.I)


def clean_words(words: list["Word"]) -> list["Word"]:
    """Tidy Whisper's raw words before they become captions:
    - drop pure hesitation sounds ("ııı", "eee", "hmm", "uh", "um"), which
      only flash on screen; reaction sounds like "aaa" or "oha" stay,
    - cut looped repeats ("ya ya ya ya ya ya ya…") down to three,
    - fix words stretched over silence: Whisper often starts the first word
      of a phrase long before it's said, or ends the last one long after,
      which makes a caption sit on screen in silence.
    """
    out: list[Word] = []
    for w in words:
        core = w.text.strip(_STRIP).lower()
        if _FILLER_RE.match(core):
            continue
        if len(out) >= 3 and all(o.text.strip(_STRIP).lower() == core for o in out[-3:]):
            continue
        out.append(w)
    for k, w in enumerate(out):
        cap = max(0.9, 0.09 * len(w.text) + 0.35)       # longest a word plausibly lasts
        if w.end - w.start <= cap:
            continue
        gap_before = w.start - out[k - 1].end if k else 99.0
        gap_after = out[k + 1].start - w.end if k + 1 < len(out) else 99.0
        if k == 0 or gap_before >= gap_after:
            w.start = w.end - cap          # first word after a pause: started too early
        else:
            w.end = w.start + cap          # last word before a pause: ended too late
    return out


def _norm(word: str) -> str:
    w = word.strip(_STRIP).replace("I", "ı").replace("İ", "i").lower()
    return w.replace("’", "'")


CORRECTIONS_TEMPLATE = """# Fix words Whisper keeps getting wrong.
# One per line:   what it wrote => what you actually said
# Not case-sensitive, works for phrases, and keeps the subtitle timing.
# Lines starting with # are ignored. Save the file; no restart needed.
# (This file isn't in the download, so updates never overwrite it.)
#
# Examples (remove the # to use them):
# ama koy => amına koyim
# türk 83 => Kırk Seksenüç
"""


def ensure_corrections_file(path: str = CORRECTIONS_FILE) -> str:
    if not os.path.exists(path) and path == CORRECTIONS_FILE and os.path.isfile(_OLD_CORRECTIONS):
        try:   # move the user's own fixes over from the old place
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copyfile(_OLD_CORRECTIONS, path)
        except OSError:
            pass
    if not os.path.exists(path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except OSError:
            pass
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(CORRECTIONS_TEMPLATE)
        except OSError:
            pass
    return path


def load_corrections(path: str = CORRECTIONS_FILE) -> list[tuple[list[str], str]]:
    """Lines like `ama koy => amına koyim`. Lines starting with # are ignored."""
    ensure_corrections_file(path)
    rules: list[tuple[list[str], str]] = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=>" not in line:
                    continue
                wrong, right = (x.strip() for x in line.split("=>", 1))
                tokens = [_norm(t) for t in wrong.split() if _norm(t)]
                if tokens:
                    rules.append((tokens, right))
    except OSError:
        pass
    # longest phrases first, so "ama koy" wins over "ama"
    return sorted(rules, key=lambda r: -len(r[0]))


def apply_corrections(words: list["Word"], rules) -> list["Word"]:
    """Replace misheard words/phrases, keeping timings and end punctuation."""
    if not rules:
        return words
    out: list[Word] = []
    i = 0
    norm = [_norm(w.text) for w in words]
    while i < len(words):
        for tokens, right in rules:
            k = len(tokens)
            if norm[i:i + k] == tokens:
                span = words[i:i + k]
                start, end = span[0].start, span[-1].end
                tail = span[-1].text[len(span[-1].text.rstrip(_STRIP)):]
                new = right.split()
                if tail and new and not new[-1][-1:] in _STRIP:
                    new[-1] += tail
                step = (end - start) / max(1, len(new))
                for j, t in enumerate(new):
                    out.append(Word(start + j * step, start + (j + 1) * step, t,
                                    min(w.prob for w in span), span[0].speaker,
                                    span[0].lang))
                i += k
                break
        else:
            out.append(words[i])
            i += 1
    return out


@dataclass
class Word:
    start: float
    end: float
    text: str
    prob: float = 1.0
    speaker: int = 0        # 0 = person who talks most in the clip
    lang: str = ""          # set when this word is in the second language ("" = main)


@dataclass
class Transcript:
    language: str | None
    words: list[Word] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)   # for diagnosing gaps

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words).strip()

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        return cls(d.get("language"),
                   [Word(float(w[0]), float(w[1]), str(w[2]), float(w[3]),
                         int(w[4]) if len(w) > 4 else 0, str(w[5]) if len(w) > 5 else "")
                    for w in d.get("words", [])],
                   list(d.get("dropped", [])))

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "text": self.text,
            "words": [[round(w.start, 2), round(w.end, 2), w.text, round(w.prob, 2), w.speaker]
                      + ([w.lang] if w.lang else []) for w in self.words],
            "speakers": len({w.speaker for w in self.words}) if self.words else 0,
            "dropped": self.dropped,
        }


@dataclass
class TranscribeOptions:
    language: str | None = "tr"
    model: str = "large-v3-turbo"
    custom_words: str = ""          # streamer name, game terms, inside jokes
    device: str = "auto"            # auto | cpu | cuda
    # Second language spoken on stream (code-switching, e.g. Turkish + English).
    # With the main language fixed, Whisper TRANSLATES other-language speech
    # into it ("Who did this?" -> "Kim bu yaptı?"), so every sentence is
    # checked and re-written in this language when that's what was spoken.
    also_language: str | None = "en"


class WhisperMissing(RuntimeError):
    pass


# ------------------------------------------------------------ loading

def _stub_pyav() -> str | None:
    """faster-whisper imports PyAV at start-up, but we never use it: audio is
    decoded by FFmpeg and handed over as a numpy array. PyAV ships unsigned
    DLLs (libstdc++-6-*.dll) that Windows Smart App Control may block, so if
    it won't load we put a harmless placeholder in its place.

    Since 1.5 we never even try the real one: on Windows 11 with Smart App
    Control, just *trying* pops up a "part of this app has been blocked"
    warning (e.g. for codeccontext.pyd), even though nothing breaks."""
    if True:
        for name in [m for m in sys.modules if m == "av" or m.startswith("av.")]:
            del sys.modules[name]

        class _Unused:
            def __getattr__(self, _):
                return self

            def __call__(self, *a, **k):
                raise RuntimeError("PyAV is unavailable; UbiClipper decodes "
                                   "audio with FFmpeg instead.")

        stub = types.ModuleType("av")
        stub.__getattr__ = lambda name: _Unused()  # type: ignore[attr-defined]
        sys.modules["av"] = stub
        return "PyAV skipped (not needed; FFmpeg decodes the audio)"


def _nvidia_lib_dirs() -> list[str]:
    """Folders of the NVIDIA pip wheels (nvidia-cublas-cu12, nvidia-cudnn-cu12…)."""
    dirs: list[str] = []
    try:
        spec = importlib.util.find_spec("nvidia")
    except (ImportError, ValueError):
        spec = None
    for root in (spec.submodule_search_locations if spec else None) or []:
        for pkg in sorted(os.listdir(root)):
            for sub in ("bin", "lib"):
                d = os.path.join(root, pkg, sub)
                if os.path.isdir(d):
                    dirs.append(d)
    # downloaded by the installed app's "Get ready" window (no pip there)
    own = os.path.join(os.path.expanduser("~"), ".ubiclipper", "nvidia")
    if os.path.isdir(own):
        for pkg in sorted(os.listdir(own)):
            for sub in ("bin", "lib"):
                d = os.path.join(own, pkg, sub)
                if os.path.isdir(d):
                    dirs.append(d)
    return dirs


_cuda_prepared = False


def _prepare_cuda() -> None:
    """Make CUDA/cuDNN DLLs from the NVIDIA wheels findable by CTranslate2."""
    global _cuda_prepared
    if _cuda_prepared:
        return
    _cuda_prepared = True
    dirs = _nvidia_lib_dirs()
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])
        if hasattr(os, "add_dll_directory"):
            for d in dirs:
                try:
                    os.add_dll_directory(d)
                except OSError:
                    pass


def _missing_cuda_libs() -> list[str]:
    """CTranslate2 loads cuBLAS/cuDNN lazily; if they're missing it can crash
    mid-transcription instead of raising, so check before picking the GPU."""
    if not sys.platform.startswith("win"):
        return []  # on Linux the loader reports errors cleanly
    needed = ["cublas64_12.dll", "cudnn_ops64_9.dll"]
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    return [n for n in needed
            if not any(os.path.isfile(os.path.join(d, n)) for d in path_dirs if d)]


def smart_app_control_on() -> bool:
    """Windows 11 Smart App Control in "On" mode blocks unsigned DLLs."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\CI\Policy") as k:
            return winreg.QueryValueEx(k, "VerifiedAndReputablePolicyState")[0] == 1
    except OSError:
        return False


def pe_signed(path: str) -> bool:
    """Does this DLL carry a digital signature? (Reads the PE header only;
    Windows checks the signature itself when it loads the file.)"""
    import struct
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
        pe = struct.unpack_from("<I", head, 0x3C)[0]
        magic = struct.unpack_from("<H", head, pe + 24)[0]
        dirs = pe + 24 + (112 if magic == 0x20B else 96)
        _, size = struct.unpack_from("<II", head, dirs + 4 * 8)
        return size > 0
    except (OSError, struct.error):
        return False


def _unsigned_cuda_libs() -> list[str]:
    names = ("cudart64_12.dll", "cublas64_12.dll", "cublasLt64_12.dll", "cudnn_ops64_9.dll")
    bad = []
    for d in _nvidia_lib_dirs():
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p) and not pe_signed(p):
                bad.append(n)
    return bad


_GPU_BROKEN: list[str] = []      # set when the GPU failed for real this session


def gpu_status() -> tuple[bool, str]:
    """(usable, human-readable explanation)."""
    _prepare_cuda()
    try:
        import ctranslate2
        count = ctranslate2.get_cuda_device_count()
    except Exception as e:
        return False, f"CTranslate2 could not check for a GPU ({e})"
    if count == 0:
        return False, ("No CUDA GPU visible. If you have an NVIDIA card, update "
                       "its driver.")
    if _GPU_BROKEN:
        return False, _GPU_BROKEN[0]
    if smart_app_control_on():
        unsigned = _unsigned_cuda_libs()
        if unsigned:
            return False, ("Smart App Control blocks the unsigned NVIDIA files ("
                           + ", ".join(sorted(set(unsigned))) + "). Settings → All AI "
                           "downloads & GPU speed-up downloads signed ones.")
    missing = _missing_cuda_libs()
    if missing:
        return False, ("NVIDIA GPU found, but CUDA libraries are missing ("
                       + ", ".join(missing) + "). Settings → All AI downloads & GPU speed-up.")
    return True, "NVIDIA GPU ready"


def import_whisper():
    """Import faster-whisper, returning (module, note). Raises WhisperMissing
    with the *real* reason when it can't be loaded."""
    # harmless model-download warnings (no symlinks on Windows, no HF account)
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    import warnings
    warnings.filterwarnings("ignore", message=".*unauthenticated requests.*")
    warnings.filterwarnings("ignore", message=".*symlinks.*")
    note = _stub_pyav()
    try:
        import faster_whisper
    except Exception as e:
        hint = ("pip install faster-whisper" if isinstance(e, ModuleNotFoundError)
                and "faster_whisper" in str(e) else "run check_setup.bat and send "
                "the output")
        raise WhisperMissing(
            f"Subtitles are unavailable: {type(e).__name__}: {e}\n\nFix: {hint}") from e
    return faster_whisper, note


def check_available() -> tuple[bool, str]:
    try:
        import_whisper()
    except WhisperMissing as e:
        return False, str(e)
    usable, why = gpu_status()
    return True, ("Subtitles will run on the GPU." if usable
                  else f"Subtitles will run on the CPU (slower). {why}")


_LOADED: dict[tuple[str, str], "Transcriber"] = {}


def get_transcriber(opts: "TranscribeOptions",
                    status: Callable[[str], None] | None = None) -> "Transcriber":
    """Load a model once per app session (several seconds + GPU memory) and
    reuse it for ranking and for every export."""
    key = (opts.model, opts.device)
    tr = _LOADED.get(key)
    if tr is None:
        tr = Transcriber(opts, status)
        _LOADED.clear()          # keep only one model in (GPU) memory
        _LOADED[key] = tr
    tr.opts = opts               # language / custom words may have changed
    return tr


class Transcriber:
    """Loads the model once and reuses it for every clip."""

    def __init__(self, opts: TranscribeOptions,
                 status: Callable[[str], None] | None = None) -> None:
        fw, _ = import_whisper()
        self.opts = opts
        say = status or (lambda m: None)

        attempts: list[tuple[str, str]] = []
        gpu_ok, gpu_why = gpu_status()
        if opts.device in ("auto", "cuda") and gpu_ok:
            attempts.append(("cuda", "float16"))
        elif opts.device == "cuda":
            raise RuntimeError(f"GPU requested but not usable: {gpu_why}")
        if opts.device != "cuda":
            attempts.append(("cpu", "int8"))

        last_err: Exception | None = None
        for device, compute in attempts:
            say(f"Loading speech model on {device.upper()} "
                "(first run downloads it, ~1.6 GB)…")
            try:
                self.model = fw.WhisperModel(opts.model, device=device,
                                             compute_type=compute)
                if device == "cuda":
                    self._warm_up()      # CUDA libraries load on first use
                self.device = device
                self.device_note = gpu_why if device == "cpu" else "GPU"
                return
            except Exception as e:  # e.g. driver too old -> fall back to CPU
                last_err = e
                if device == "cuda":
                    gpu_why = f"GPU didn't work ({str(e)[:160]}), using the CPU"
                    _GPU_BROKEN[:] = [gpu_why]
                    self.model = None
        raise RuntimeError(f"Could not load Whisper model '{opts.model}': {last_err}")

    def _warm_up(self) -> None:
        """Transcribe half a second of quiet noise so a missing or blocked
        cuBLAS/cuDNN shows up now (and we fall back to the CPU) instead of
        in the middle of an export."""
        noise = (np.random.default_rng(0).standard_normal(SAMPLE_RATE // 2) * 1e-3)
        segs, _ = self.model.transcribe(noise.astype(np.float32), language="en",
                                        beam_size=1, vad_filter=False,
                                        condition_on_previous_text=False)
        list(segs)

    def transcribe_file(self, path: str, start: float | None = None,
                        duration: float | None = None, track: int = 0) -> Transcript:
        """Transcribe a file, or a time range of it, from a given audio track
        (a mic-only track gives much cleaner subtitles than the game mix)."""
        chunks = list(stream_audio(path, track=track, start=start, duration=duration))
        audio = np.concatenate(chunks) if chunks else np.zeros(1, np.float32)
        return self.transcribe_audio(audio)

    def _language_probs(self, audio: np.ndarray) -> dict[str, float]:
        m = self.model
        if hasattr(m, "detect_language"):                  # faster-whisper 1.1+
            lang, prob, allp = m.detect_language(audio)
            return dict(allp) if allp else {lang: prob}
        _, info = m.transcribe(audio, language=None, beam_size=1)   # detection only
        return dict(getattr(info, "all_language_probs", None)
                    or [(info.language, info.language_probability)])

    def _second_language(self, audio: np.ndarray, s0: float, s1: float,
                         main: str, alt: str) -> list["Word"] | None:
        """Was this sentence actually said in the second language? Then write
        it down in that language instead of a translation."""
        a = max(0, int((s0 - 0.15) * SAMPLE_RATE))
        b = min(len(audio), int((s1 + 0.15) * SAMPLE_RATE))
        piece = audio[a:b]
        probs = self._language_probs(piece)
        pa, pm = probs.get(alt, 0.0), probs.get(main, 0.0)
        if pa < 0.5 or pa < 1.5 * pm:
            return None
        segs, _ = self.model.transcribe(
            piece, language=alt, word_timestamps=True, vad_filter=False, beam_size=5,
            condition_on_previous_text=False,
            initial_prompt=DEFAULT_PROMPTS.get(alt) or None)
        out = []
        off = a / SAMPLE_RATE
        for seg in segs:
            for w in seg.words or []:
                if w.word.strip():
                    out.append(Word(off + float(w.start), off + float(w.end), w.word.strip(),
                                    float(w.probability), lang=alt))
        return out or None

    def transcribe_audio(self, audio: np.ndarray) -> Transcript:
        if len(audio) < SAMPLE_RATE // 2:
            return Transcript(self.opts.language)
        prompt = DEFAULT_PROMPTS.get(self.opts.language or "", "")
        if self.opts.custom_words.strip():
            prompt = (prompt + " " + self.opts.custom_words.strip()).strip()

        segments, info = self.model.transcribe(
            audio,
            language=self.opts.language,
            word_timestamps=True,
            # The voice-activity filter skips music/silence, but its default
            # threshold also skips shouting over loud game audio. Be lenient
            # and pad generously; Whisper's own checks catch the rest.
            vad_filter=True,
            vad_parameters={"threshold": 0.3, "min_silence_duration_ms": 500,
                            "speech_pad_ms": 400},
            beam_size=5,
            condition_on_previous_text=False,      # fewer repeated-line loops
            initial_prompt=prompt or None,
        )
        words: list[Word] = []
        dropped: list[dict] = []
        kept: list[tuple[float, float, list[Word]]] = []
        for seg in segments:
            reason = None
            # only drop when Whisper is BOTH sure there's no speech AND unsure
            # of the text (shouted/distorted speech has low confidence alone)
            if seg.no_speech_prob > 0.8 and seg.avg_logprob < -1.0:
                reason = "no speech"
            elif _HALLU_RE.search(seg.text or ""):
                reason = "known Whisper filler line"
            if reason:
                dropped.append({"start": round(getattr(seg, "start", 0.0), 2),
                                "end": round(getattr(seg, "end", 0.0), 2),
                                "text": (seg.text or "").strip(), "reason": reason})
                continue
            seg_words = [Word(float(w.start), float(w.end), w.word.strip(), float(w.probability))
                         for w in (seg.words or []) if w.word.strip()]
            if seg_words:
                kept.append((float(seg.start), float(seg.end), seg_words))
        alt = (self.opts.also_language or "").lower()[:2]
        main = (self.opts.language or "").lower()[:2]
        for k, (s0, s1, seg_words) in enumerate(kept):
            if alt and main and alt != main and s1 - s0 >= 0.8:
                try:
                    redo = self._second_language(audio, s0, s1, main, alt)
                except Exception:
                    redo = None
                if redo:
                    seg_words = redo
            words.extend(seg_words)
        words = clean_words(words)
        words = apply_corrections(words, load_corrections())
        return Transcript(self.opts.language or info.language, words, dropped)
