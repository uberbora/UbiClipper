"""Turn word timestamps into short-form captions and burn them into video.

Styling (fonts, colours, size, placement, animations, censoring) lives in
SubtitleStyle; PRESETS are ready-made starting points the user can tweak.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import asdict, dataclass, field, fields

from .media import _require
from .transcribe import Word

PUNCT_BREAK = (".", "!", "?", "…", ",", ";", ":")
_STRIP = ".,!?…;:\"'“”«»()"

# person 1 .. 10
SPEAKER_PALETTE = ["FFE600", "00E676", "4FC3F7", "FF6EC7", "FF9100",
                   "B388FF", "FF5252", "C6FF00", "FFFFFF", "FFD180"]

ANIMATIONS = {
    "None": "none",
    "Pop in": "pop",
    "Highlight spoken word": "highlight",
    "Pop + highlight": "pop+highlight",
}
PLACEMENTS = {
    "Auto (under webcam)": "auto",
    "Top": "top",
    "Middle": "middle",
    "Bottom": "bottom",
    "Custom (place on the 9:16 screen)": "custom",
}


@dataclass
class SubtitleStyle:
    font: str = "Arial Black"       # must contain Turkish glyphs (ğ ş ı İ ç ö ü)
    size: float = 1.0               # 1.0 = default size for the video shape
    bold: bool = True
    uppercase: bool = True
    text_color: str = "FFFFFF"      # RRGGBB
    highlight_color: str = "FFE600"  # colour of the word being spoken
    outline_color: str = "000000"
    outline: float = 1.0            # 1.0 = default thickness, 0 = none
    shadow: bool = True
    box: bool = False               # dark box behind the text instead of outline
    animation: str = "pop+highlight"
    placement: str = "auto"
    custom_x: float = 0.5           # placement "custom": centre on the 9:16 screen (0..1)
    custom_y: float = 0.62
    max_words: int = 3
    max_chars: int = 20
    max_seconds: float = 1.8
    censor: bool = False            # a***a koyim
    speaker_colors: bool = True     # colour each person differently (if >1 talk)
    palette: list = field(default_factory=lambda: list(SPEAKER_PALETTE))

    @classmethod
    def from_dict(cls, d: dict | None) -> "SubtitleStyle":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})

    def to_dict(self) -> dict:
        return asdict(self)


PRESETS: dict[str, dict] = {
    "Bold pop": dict(font="Arial Black", text_color="FFFFFF", highlight_color="FFE600",
                     animation="pop+highlight", box=False, max_words=3, size=1.0),
    "Classic": dict(font="Arial", bold=True, text_color="FFFFFF", animation="none",
                    box=False, max_words=3, size=1.0),
    "Yellow impact": dict(font="Impact", bold=False, text_color="FFE600",
                          highlight_color="FFFFFF", animation="pop", box=False,
                          max_words=3, size=1.1),
    "One word": dict(font="Arial Black", text_color="FFFFFF", highlight_color="00E676",
                     animation="pop", box=False, max_words=1, size=1.35),
    "Boxed": dict(font="Arial", bold=True, text_color="FFFFFF", highlight_color="4FC3F7",
                  animation="highlight", box=True, uppercase=False, max_words=4,
                  size=0.9),
}


def preset(name: str, base: SubtitleStyle | None = None) -> SubtitleStyle:
    """Apply a preset on top of `base`, keeping settings presets don't touch
    (placement, censor)."""
    d = (base or SubtitleStyle()).to_dict()
    d.update(PRESETS[name])
    return SubtitleStyle.from_dict(d)


@dataclass
class Caption:
    start: float
    end: float
    text: str
    words: list[str] = field(default_factory=list)       # displayed words
    times: list[float] = field(default_factory=list)     # start time of each word
    speaker: int = 0
    sep: str = " "          # "" for languages written without spaces (ja, zh, th)


# ------------------------------------------------------------- text helpers

def turkish_upper(s: str) -> str:
    """Python's .upper() turns 'i' into 'I'; Turkish needs 'İ' (and 'ı'->'I')."""
    return s.replace("i", "İ").replace("ı", "I").upper()


def turkish_lower(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def make_upper(s: str, language: str | None) -> str:
    return turkish_upper(s) if language in ("tr", "az") else s.upper()


# Swear words for the censor switch, per language (clipper/lang_data.py):
# exact words, plus stems that only ever start a swear word (so normal words
# like "götürmek", "ama", "amca" or "sıkı" are never touched).
_SWEAR_CACHE: dict = {}


def _swears(language: str | None):
    key = (language or "").lower()[:2]
    if key not in _SWEAR_CACHE:
        from .lang_data import swear_sets
        _SWEAR_CACHE[key] = swear_sets(language)
    return _SWEAR_CACHE[key]


def is_swear(word: str, language: str | None = None) -> bool:
    exact, prefix = _swears(language)
    w = turkish_lower(word.strip(_STRIP)) if (language or "tr")[:2] in ("tr", "az") \
        else word.strip(_STRIP).lower()
    return bool(w) and (w in exact or w.startswith(prefix))


def censor_word(word: str, language: str | None = None) -> str:
    """amına -> a***a, amk -> a*k, fuck -> f**k  (punctuation kept)."""
    core = word.strip(_STRIP)
    if not core or not is_swear(core, language):
        return word
    i = word.index(core)
    hidden = core[0] + "*" * (len(core) - 1) if len(core) <= 2 else \
        core[0] + "*" * (len(core) - 2) + core[-1]
    return word[:i] + hidden + word[i + len(core):]


# ------------------------------------------------------------- chunking

LEAD_IN = 0.06      # s a caption appears before its first word
BRIDGE_GAP = 0.6    # gaps shorter than this between captions are bridged


def build_captions(words: list[Word], style: SubtitleStyle,
                   language: str | None = None) -> list[Caption]:
    """Group words into short punchy captions (TikTok/Reels style)."""
    from .lang_data import NO_SPACES
    sep = "" if (language or "")[:2] in NO_SPACES else " "
    chunks: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            text_len = len(sep.join(x.text.strip() for x in cur + [w]))
            gap = w.start - cur[-1].end
            # short sentence-enders ("ya!", "mı?", "ki") stick to the caption
            # instead of flashing alone on screen
            tail = (style.max_words > 1 and len(w.text.strip(_STRIP)) <= 3
                    and gap < 0.3 and text_len <= style.max_chars + 4
                    and not cur[-1].text.endswith(PUNCT_BREAK))
            if w.speaker != cur[-1].speaker:      # never mix two people in one caption
                chunks.append(cur)
                cur = []
            elif not tail and (len(cur) >= style.max_words or text_len > style.max_chars
                             or w.end - cur[0].start > style.max_seconds or gap > 0.5
                             or cur[-1].text.endswith(PUNCT_BREAK)):
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)

    caps: list[Caption] = []
    for i, ch in enumerate(chunks):
        start = ch[0].start
        end = ch[-1].end + 0.25
        if i + 1 < len(chunks):
            end = min(end, chunks[i + 1][0].start)
        end = max(end, start + 0.35)
        shown = []
        for w in ch:
            wl = getattr(w, "lang", "") or language        # mixed-language clips
            t = censor_word(w.text, wl) if style.censor else w.text
            t = t.strip() if not sep else t
            shown.append(make_upper(t, wl) if style.uppercase else t)
        caps.append(Caption(start, end, sep.join(shown), shown, [w.start for w in ch],
                            ch[0].speaker, sep))
    # show each caption a hair before its first word (reads as in sync) and
    # bridge tiny gaps so the screen doesn't blink empty between captions
    for k, c in enumerate(caps):
        c.start = max(0.0, c.start - LEAD_IN)
        if k + 1 < len(caps):
            nxt = caps[k + 1].start - LEAD_IN
            if 0 < nxt - c.end < BRIDGE_GAP:
                c.end = nxt
    # keep captions from overlapping after the minimum-duration bump
    for a, b in zip(caps, caps[1:]):
        if a.end > b.start:
            a.end = b.start
    return [c for c in caps if c.end > c.start]


# ------------------------------------------------------------- writers

def _srt_time(t: float) -> str:
    ms = int(round(max(t, 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(caps: list[Caption], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for i, c in enumerate(caps, 1):
            f.write(f"{i}\n{_srt_time(c.start)} --> {_srt_time(c.end)}\n{c.text}\n\n")


def _ass_time(t: float) -> str:
    cs = int(round(max(t, 0) * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_color(rrggbb: str, alpha: str = "00") -> str:
    rrggbb = (rrggbb or "FFFFFF").lstrip("#").upper().ljust(6, "0")[:6]
    return f"&H{alpha}{rrggbb[4:6]}{rrggbb[2:4]}{rrggbb[0:2]}"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def placement_y(style: SubtitleStyle, auto_y: float, vertical: bool) -> float:
    """Vertical centre (0..1) of the captions for a placement choice."""
    if style.placement == "custom":
        # placed by hand on the 9:16 screen; the 1920x1080 copy uses the bottom
        return min(0.9, max(0.08, style.custom_y)) if vertical else 0.85
    table = ({"top": 0.22, "middle": 0.50, "bottom": 0.76} if vertical
             else {"top": 0.15, "middle": 0.50, "bottom": 0.85})
    return table.get(style.placement, auto_y)


def write_ass(caps: list[Caption], path: str, width: int, height: int,
              style: SubtitleStyle, position: float | None = None) -> None:
    vertical = height > width
    base = 0.048 if vertical else 0.065          # font size, fraction of height
    size = max(12, round(base * style.size * height))
    outline = round(size * 0.08 * style.outline)
    shadow = round(size * 0.04) if style.shadow else 0
    border_style = 3 if style.box else 1          # 3 = opaque box
    back = _ass_color("000000", "60") if style.box else _ass_color("000000", "80")
    if style.box:
        outline = max(outline, round(size * 0.15))  # box padding
    y = position if position is not None else placement_y(
        style, 0.80 if not vertical else 0.74, vertical)
    margin_v = max(0, round((1 - y) * height - size / 2))
    margin_h = round(0.06 * width)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{style.font},{size},{_ass_color(style.text_color)},&H000000FF,{_ass_color(style.outline_color) if not style.box else back},{back},{-1 if style.bold else 0},0,0,0,100,100,0,0,{border_style},{outline},{shadow},2,{margin_h},{margin_h},{margin_v},162

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    pop = "{\\fscx75\\fscy75\\t(0,90,\\fscx108\\fscy108)\\t(90,160,\\fscx100\\fscy100)}"
    def bgr(hex_rgb: str) -> str:            # \c takes &HBBGGRR&
        return "&H" + _ass_color(hex_rgb)[4:]

    # Colour per person only when more than one person talks in this clip;
    # a solo clip keeps the normal style.
    # colour per person when someone other than person 1 talks (person 1 alone
    # keeps the normal style; a clip of only person 2 stays green like elsewhere)
    multi = style.speaker_colors and any(c.speaker for c in caps)
    palette = list(style.palette or SPEAKER_PALETTE) + SPEAKER_PALETTE
    lines: list[str] = []
    for c in caps:
        base = bgr(palette[c.speaker % len(palette)]) if multi else None
        # spoken word: highlight colour normally; white on coloured speaker
        # text (yellow-on-yellow would be invisible)
        hl = bgr("FFFFFF" if multi else style.highlight_color)
        if multi and palette[c.speaker % len(palette)].upper() in ("FFFFFF", "FFFFFE"):
            hl = bgr("FFE600")
        color_tag = f"{{\\c{base}&}}" if base else ""
        reset = f"{{\\c{base}&}}" if base else "{\\r}"
        anim = style.animation
        if "highlight" in anim and len(c.words) > 1:
            # one event per spoken word, with that word coloured
            starts = [max(c.start, t) for t in c.times]
            starts[0] = c.start
            for k, word_start in enumerate(starts):
                word_end = starts[k + 1] if k + 1 < len(starts) else c.end
                if word_end <= word_start:
                    continue
                parts = [(f"{{\\c{hl}&}}{_esc(w)}{reset}" if j == k else _esc(w))
                         for j, w in enumerate(c.words)]
                prefix = pop if (k == 0 and "pop" in anim) else ""
                lines.append(f"Dialogue: 0,{_ass_time(word_start)},{_ass_time(word_end)},"
                             f"Caption,,0,0,0,,{prefix}{color_tag}{c.sep.join(parts)}")
        else:
            prefix = pop if "pop" in anim else ""
            lines.append(f"Dialogue: 0,{_ass_time(c.start)},{_ass_time(c.end)},"
                         f"Caption,,0,0,0,,{prefix}{color_tag}{_esc(c.text)}")

    if vertical and style.placement == "custom":
        # exact spot chosen on the 9:16 preview: centre of the text there
        px = round(min(0.85, max(0.15, style.custom_x)) * width)
        py = round(min(0.92, max(0.06, style.custom_y)) * height)
        tag = "{\\an5\\pos(%d,%d)}" % (px, py)
        lines = [ln.replace("Caption,,0,0,0,,", "Caption,,0,0,0,," + tag, 1) for ln in lines]
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(header)
        f.write("\n".join(lines) + "\n")


def burn(video: str, ass_path: str | None, dst: str, crf: int = 20,
         preset: str = "veryfast", size: tuple[int, int] | None = None) -> None:
    """Render the .ass captions onto the video. With `size`, the video is
    first fitted into that frame (e.g. 1920x1080; letterboxed if the shape
    differs), and the captions must have been written for that size.

    ffmpeg's filter syntax chokes on Windows paths ('C:\\...'), so we run
    inside the clip folder and pass a relative path.
    """
    folder = os.path.dirname(os.path.abspath(dst))
    filters = []
    if size:
        w, h = size
        filters.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
                       f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")
    if ass_path:
        filters.append(f"ass='{_rel(ass_path, folder)}'")
    cmd = [
        _require("ffmpeg"), "-nostdin", "-v", "error", "-y",
        "-i", os.path.abspath(video),
        "-vf", ",".join(filters) or "null",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
        os.path.basename(dst),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=folder)
    if out.returncode != 0:
        raise RuntimeError(f"Burning subtitles failed:\n{out.stderr.strip()}")


def _rel(path: str, folder: str) -> str:
    """Path of `path` relative to `folder`, with forward slashes, safe to put
    inside an ffmpeg filter (no drive letter / colon)."""
    rel = os.path.relpath(os.path.abspath(path), folder).replace("\\", "/")
    if re.match(r"^[A-Za-z]:", rel):
        raise RuntimeError("Subtitle file must be on the same drive as the output.")
    return rel.replace("'", r"\'")
