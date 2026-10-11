"""AI judge: a small language model that reads each candidate moment and
says how funny / clip-worthy it is, why, and a title idea.

Runs fully on your PC with CTranslate2, the same engine faster-whisper
already uses for subtitles (so nothing new to install, and nothing that
Windows Smart App Control hasn't already allowed). The model is
Qwen3-4B-Instruct-2507 (Alibaba, Apache 2.0, speaks Turkish), converted to
int8: one ~4 GB download, cached in ~/.ubiclipper/models.

On an NVIDIA GPU it judges a moment in about a second; on CPU in ~5-15 s.
It reads what was said (Whisper transcript), what the listening AI heard
(laughter, screams, explosions) and what chat wrote. It can't see the video.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from .reframe import CONFIG_DIR

REPO = "jncraton/Qwen3-4B-Instruct-2507-ct2-int8"
FILES = ["config.json", "generation_config.json", "tokenizer.json",
         "tokenizer_config.json", "vocabulary.json", "model.bin"]
BASE_URL = "https://huggingface.co/{repo}/resolve/main/{file}"
MODEL_DIR = os.path.join(CONFIG_DIR, "models", "judge-qwen3-4b")
APPROX_GB = 4.0

Report = Callable[[str], None]


class JudgeError(RuntimeError):
    pass


@dataclass
class Moment:
    """What the judge gets to see about one candidate clip."""
    transcript: str                       # "[0:03] text" lines (any language)
    audio: list[str] = field(default_factory=list)   # e.g. ["laughter (strong)"]
    chat: list[str] = field(default_factory=list)
    game: str = ""
    language: str = "tr"


@dataclass
class Verdict:
    score: float          # 0..10
    why: str = ""
    title: str = ""
    ok: bool = True       # False = the model's answer couldn't be read


# ------------------------------------------------------------------ download
def is_downloaded() -> bool:
    return all(os.path.exists(os.path.join(MODEL_DIR, f)) for f in FILES)


def download(report: Report | None = None,
             should_cancel: Callable[[], bool] | None = None) -> str:
    """Fetch the model files (resumes after an interrupted download)."""
    say = report or (lambda m: None)
    os.makedirs(MODEL_DIR, exist_ok=True)
    for name in FILES:
        dest = os.path.join(MODEL_DIR, name)
        if os.path.exists(dest):
            continue
        part = dest + ".part"
        have = os.path.getsize(part) if os.path.exists(part) else 0
        req = urllib.request.Request(BASE_URL.format(repo=REPO, file=name),
                                     headers={"User-Agent": "UbiClipper"})
        if have:
            req.add_header("Range", f"bytes={have}-")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                if have and r.status != 206:      # server ignored the range
                    have = 0
                total = have + int(r.headers.get("Content-Length") or 0)
                with open(part, "ab" if have else "wb") as f:
                    done = have
                    while True:
                        if should_cancel and should_cancel():
                            raise InterruptedError("Download cancelled")
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if name == "model.bin" and total:
                            say(f"Downloading the AI judge… {done / 1e9:.1f} of "
                                f"{total / 1e9:.1f} GB ({100 * done // total}%)")
        except InterruptedError:
            raise
        except OSError as e:
            raise JudgeError(f"Couldn't download the AI judge ({e}). It resumes "
                             "where it stopped next time.") from e
        os.replace(part, dest)
    return MODEL_DIR


def delete_model() -> None:
    import shutil
    _LOADED.clear()
    shutil.rmtree(MODEL_DIR, ignore_errors=True)


def downloaded_bytes() -> int:
    if not os.path.isdir(MODEL_DIR):
        return 0
    return sum(os.path.getsize(os.path.join(MODEL_DIR, f)) for f in os.listdir(MODEL_DIR))


# ------------------------------------------------------------------ prompt
# Qwen3 understands 119 languages; these are the names it gets told to write
# titles in (any Whisper language code works, unknown ones fall back to English)
_LANG = {
    "tr": "Turkish", "en": "English", "de": "German", "es": "Spanish", "fr": "French",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "pl": "Polish", "ru": "Russian",
    "uk": "Ukrainian", "ar": "Arabic", "fa": "Persian", "he": "Hebrew", "az": "Azerbaijani",
    "kk": "Kazakh", "uz": "Uzbek", "el": "Greek", "bg": "Bulgarian", "ro": "Romanian",
    "hu": "Hungarian", "cs": "Czech", "sk": "Slovak", "sr": "Serbian", "hr": "Croatian",
    "bs": "Bosnian", "sl": "Slovenian", "sv": "Swedish", "no": "Norwegian", "da": "Danish",
    "fi": "Finnish", "et": "Estonian", "lv": "Latvian", "lt": "Lithuanian", "ka": "Georgian",
    "hy": "Armenian", "hi": "Hindi", "ur": "Urdu", "bn": "Bengali", "ta": "Tamil",
    "id": "Indonesian", "ms": "Malay", "tl": "Filipino", "vi": "Vietnamese", "th": "Thai",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "sw": "Swahili", "ca": "Catalan",
}


def language_name(code: str | None) -> str:
    return _LANG.get((code or "en").lower()[:2], "English")


SYSTEM = """You pick moments from livestream recordings that will do well as short \
TikTok / Instagram Reels / YouTube Shorts clips. You judge ONE moment from:
- an automatic transcript (it can contain recognition mistakes; [m:ss] = time),
- what an audio AI heard (laughter, screaming, explosions...),
- chat messages sent during the moment (if any).

Score 0-10 how funny or entertaining it is as a standalone clip:
0-2 nothing happens / boring talk / only game sounds
3-4 mildly interesting
5-6 decent: a reaction or a small joke
7-8 funny or exciting: banter, roasts, fails, rage, real laughter, chat going wild
9-10 hilarious, must clip
Swearing alone is not funny; context is. Reading donations, ads or plain \
gameplay callouts score low.

Answer with JSON only, no other text:
{"score": <0-10>, "why": "<max 12 words in {why_lang}>", "title": "<catchy title in {lang}, max 8 words>"}"""

# language of the short "why" (follows the app's language; set by the app)
REASON_LANGUAGE = "en"


def build_prompt(m: Moment) -> str:
    lang = language_name(m.language)
    user = []
    if m.game:
        user.append(f"Game / category: {m.game}")
    user.append("Audio AI heard: " + (", ".join(m.audio) if m.audio else "nothing special"))
    if m.chat:
        user.append("Chat during the moment:\n" + "\n".join(f"- {c}" for c in m.chat[:15]))
    text = m.transcript.strip() or "(nobody speaks)"
    if len(text) > 1500:
        text = text[:1500] + " …"
    user.append("Transcript:\n" + text)
    sysmsg = SYSTEM.replace("{lang}", lang).replace("{why_lang}", language_name(REASON_LANGUAGE))
    return ("<|im_start|>system\n" + sysmsg + "<|im_end|>\n"
            "<|im_start|>user\n" + "\n\n".join(user) + "<|im_end|>\n"
            "<|im_start|>assistant\n")


def parse(answer: str) -> Verdict:
    """Read the model's JSON (tolerant of extra text or a missing brace)."""
    text = answer.strip()
    m = re.search(r"\{.*\}", text, re.S)
    data = None
    if m:
        try:
            data = json.loads(m.group(0))
        except ValueError:
            data = None
    if not isinstance(data, dict):
        sc = re.search(r'"?score"?\s*[:=]\s*"?(\d+(?:\.\d+)?)', text)
        if not sc:
            return Verdict(0.0, ok=False)
        why = re.search(r'"why"\s*:\s*"([^"]*)', text)
        title = re.search(r'"title"\s*:\s*"([^"]*)', text)
        data = {"score": sc.group(1), "why": why.group(1) if why else "",
                "title": title.group(1) if title else ""}
    try:
        score = float(str(data.get("score", 0)).split("/")[0])
    except ValueError:
        return Verdict(0.0, ok=False)
    return Verdict(max(0.0, min(10.0, score)), str(data.get("why", "")).strip()[:120],
                   str(data.get("title", "")).strip().strip('"')[:90])


# ------------------------------------------------------------------ model
class Judge:
    def __init__(self, report: Report | None = None, device: str = "auto",
                 should_cancel: Callable[[], bool] | None = None) -> None:
        say = report or (lambda m: None)
        if not is_downloaded():
            download(say, should_cancel)
        try:
            from .transcribe import gpu_status
            gpu_ok = device in ("auto", "cuda") and gpu_status()[0]
        except Exception:
            gpu_ok = False
        try:
            import ctranslate2
            import tokenizers
        except Exception as e:
            raise JudgeError(f"The AI judge needs CTranslate2 and tokenizers, which "
                             f"come with faster-whisper ({e}). Reinstall UbiClipper.") from e
        self.tok = tokenizers.Tokenizer.from_file(os.path.join(MODEL_DIR, "tokenizer.json"))
        attempts = ([("cuda", "int8_float16")] if gpu_ok else []) + [("cpu", "int8")]
        last = None
        for dev, ctype in attempts:
            try:
                say(f"Loading the AI judge ({dev.upper()})…")
                self.gen = ctranslate2.Generator(MODEL_DIR, device=dev, compute_type=ctype)
                if dev == "cuda":   # cuBLAS loads on first use: test it now
                    self.gen.generate_batch([self._tokens("<|im_start|>user\nhi<|im_end|>")],
                                            max_length=1, beam_size=1,
                                            include_prompt_in_result=False)
                self.device = dev
                break
            except Exception as e:   # out of GPU memory, old CTranslate2...
                last = e
        else:
            msg = str(last)
            if "qwen3" in msg.lower() or "unsupported" in msg.lower() or "spec" in msg.lower():
                msg += (" - your CTranslate2 is too old for this model. Install the "
                        "latest UbiClipper.")
            raise JudgeError(f"Couldn't load the AI judge: {msg}")
        self._lock = threading.Lock()

    def _tokens(self, prompt: str) -> list[str]:
        return self.tok.encode(prompt, add_special_tokens=False).tokens

    def rate(self, moments: list[Moment], batch: int = 6) -> list[Verdict]:
        out: list[Verdict] = []
        with self._lock:
            for i in range(0, len(moments), batch):
                group = moments[i:i + batch]
                res = self.gen.generate_batch(
                    [self._tokens(build_prompt(m)) for m in group],
                    max_length=90, sampling_topk=1, beam_size=1,
                    include_prompt_in_result=False,
                    end_token=["<|im_end|>", "<|endoftext|>"])
                for r in res:
                    out.append(parse(self.tok.decode(r.sequences_ids[0])))
        return out

    def ask(self, prompt_text: str, max_length: int = 120) -> str:
        """Free-form question (used by the 'Test the AI' button)."""
        p = ("<|im_start|>user\n" + prompt_text + "<|im_end|>\n<|im_start|>assistant\n")
        with self._lock:
            r = self.gen.generate_batch([self._tokens(p)], max_length=max_length,
                                        sampling_topk=1, include_prompt_in_result=False,
                                        end_token=["<|im_end|>", "<|endoftext|>"])
        return self.tok.decode(r[0].sequences_ids[0]).strip()


_LOADED: dict[str, Judge] = {}


def get_judge(report: Report | None = None, device: str = "auto",
              should_cancel: Callable[[], bool] | None = None) -> Judge:
    j = _LOADED.get(device)
    if j is None:
        j = Judge(report, device, should_cancel)
        _LOADED.clear()
        _LOADED[device] = j
    return j


# ------------------------------------------------------------------ helpers
def audio_tags(heard: dict[str, float]) -> list[str]:
    """Turn listening-AI peaks into words for the prompt."""
    names = {"laugh": "laughter", "scream": "screaming/shouting", "cheer": "cheering",
             "boom": "explosions/gunfire", "cough": "coughing", "music": "music"}
    tags = []
    for k, label in names.items():
        p = heard.get(k, 0.0)
        if p >= 0.45:
            tags.append(f"{label} (strong)")
        elif p >= 0.2:
            tags.append(label)
    return tags


def transcript_lines(words, max_gap: float = 1.2) -> str:
    """Words (clip-relative times) -> '[m:ss] sentence' lines."""
    lines, cur, t0, last = [], [], 0.0, -10.0
    for w in words:
        if cur and (w.start - last > max_gap or len(cur) >= 14):
            lines.append(f"[{int(t0) // 60}:{int(t0) % 60:02d}] " + " ".join(cur))
            cur = []
        if not cur:
            t0 = w.start
        cur.append(w.text.strip())
        last = w.end
    if cur:
        lines.append(f"[{int(t0) // 60}:{int(t0) % 60:02d}] " + " ".join(cur))
    return "\n".join(lines)
