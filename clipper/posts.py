"""Title and hashtag suggestions for each finished clip.

Built offline from what we already know about the clip: what was said
(transcript), why it was picked (laughing, scream, chat…), the game and the
platform/channel for links. Three title ideas + hashtags, saved as a .txt
next to the clip so posting is copy-paste.
"""

from __future__ import annotations

import re
import unicodedata

from .funny import score_words
from .subtitles import censor_word
from .transcribe import Word

from .lang_data import get as _lang

_EMOJI = {"laugh": "😂", "scream": "😱", "chat": "😂", "loud": "😳", "any": "💀"}
_PLATFORM = {"kick": ["#kick", "#kickstreamer"],
             "twitch": ["#twitch", "#twitchclips"],
             "youtube": ["#youtube", "#shorts"]}


def _kind(reasons: list[str]) -> str:
    joined = " ".join(reasons).lower()
    for key, words in [("laugh", ("laugh",)), ("chat", ("chat",)),
                       ("scream", ("scream",)), ("loud", ("loud", "outburst"))]:
        if any(w in joined for w in words):
            return key
    return "any"


def _tag(text: str) -> str:
    """'Iron Nest' -> '#ironnest' (keeps Turkish letters, drops symbols).
    Plain lower(): game and channel names are usually English ('Iron' must
    not become 'ıron')."""
    t = unicodedata.normalize("NFC", text).lower()
    t = re.sub(r"[^\wçğıöşü]+", "", t)
    return f"#{t}" if len(t) >= 2 else ""


def _best_line(words: list[Word], censor: bool, language: str | None = None) -> str | None:
    """The most reaction-heavy short sentence that was actually said."""
    if not words:
        return None
    lines, cur = [], []
    for w in words:
        cur.append(w)
        if w.text.rstrip().endswith((".", "!", "?", "…")) or len(cur) >= 9:
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    best, best_score = None, 0.15
    for ln in lines:
        if not 2 <= len(ln) <= 9:
            continue
        sc = score_words(ln, max(ln[-1].end - ln[0].start, 1.0), language).score
        sc *= min(1.0, len(ln) / 4)        # a line that says what happened beats "hahaha"
        if sc > best_score:
            best, best_score = ln, sc
    if not best:
        return None
    from .lang_data import NO_SPACES
    sep = "" if (language or "")[:2] in NO_SPACES else " "
    text = sep.join((censor_word(w.text, language) if censor else w.text).strip()
                    for w in best)
    text = re.sub(r"\s+([,.!?…])", r"\1", text).strip(" ,").rstrip(".")
    return text[:1].upper() + text[1:] if text else None


def suggest(words: list[Word], reasons: list[str], language: str | None,
            game: str = "", platform: str = "", channel: str = "",
            censor: bool = False, seed: int = 0) -> dict:
    data = _lang(language)
    pool = data["titles"]
    kind = _kind(reasons)
    e = _EMOJI[kind]

    titles: list[str] = []
    line = _best_line(words, censor, language)
    if line:
        titles.append(f"{line} {e}" if not line.endswith(tuple("😂😱😳💀🔥")) else line)
    opts = list(pool[kind]) + list(pool["any"])
    if game:
        g = pool["game"][seed % len(pool["game"])]
        titles.append(g.format(game=game, e=e))
    for k in range(len(opts)):
        if len(titles) >= 3:
            break
        cand = opts[(seed + k) % len(opts)]
        if cand not in titles:
            titles.append(cand)

    tags: list[str] = []
    for t in [_tag(game) if game else "", _tag(channel) if channel else ""]:
        if t:
            tags.append(t)
    tags += _PLATFORM.get(platform, []) + data.get("platform", {}).get(platform, [])
    tags += data["hashtags"]
    if kind == "laugh":
        tags.insert(2, data["laugh_tag"])
    seen, out = set(), []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return {"titles": titles[:3], "hashtags": out[:12]}


def write_post_file(path: str, post: dict, language: str | None) -> None:
    tags = " ".join(post["hashtags"])
    head_t, head_h, head_c = _lang(language)["post_heads"]
    lines = [f"{head_t}:"] + [f"  {i}. {t}" for i, t in enumerate(post["titles"], 1)]
    lines += ["", f"{head_h}:", f"  {tags}", "", f"{head_c}:",
              post["titles"][0] if post["titles"] else "", "", tags, ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
