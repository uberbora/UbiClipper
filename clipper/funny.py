"""Funny-word detector: score what was *said* in a candidate moment.

Audio alone can't tell a funny line from a loud gun. After the audio pass,
the best candidates are transcribed (fast on a GPU) and scored on:
  - laughter written out (hahaha, kdkdkd, jsjsjs, xd)
  - Turkish (and English) reaction words: öldüm, oha, yok artık, ne oluyor…
  - swearing (a strong sign of a genuine reaction)
  - shouted lines (!), repeated words ("hayır hayır hayır")
and moments with no speech at all are pushed down.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .subtitles import is_swear, turkish_lower
from .transcribe import Word

_STRIP = ".,!?…;:\"'“”«»()-"

from .lang_data import LAUGH_WORDS, get as _lang

LAUGH_RE = re.compile(r"^(?:" + LAUGH_WORDS + r")$")


def _lists(language: str | None):
    """Reaction words of the spoken language + English (said everywhere)."""
    own, en = _lang(language), _lang("en")
    return (own["reaction"] | en["reaction"], own["weak"] | en["weak"],
            list(dict.fromkeys(own["phrases"] + en["phrases"])))


# kept for code that imports them (Turkish + English)
REACTION_WORDS, WEAK_WORDS, REACTION_PHRASES = _lists("tr")


@dataclass
class TextScore:
    score: float                      # 0..1
    hits: list[str] = field(default_factory=list)
    laughs: int = 0
    words: int = 0

    def reason(self) -> str | None:
        if self.laughs:
            return "Laughing (heard)"
        if self.hits:
            return "Said: " + ", ".join(dict.fromkeys(self.hits))[:40]
        return None


def score_words(words: list[Word], duration: float,
                language: str | None = "tr") -> TextScore:
    reaction, weak, phrases = _lists(language)
    lower = turkish_lower if (language or "tr")[:2] in ("tr", "az") else str.lower
    toks = [lower(w.text.strip(_STRIP)) for w in words]
    toks = [t for t in toks if t]
    if not toks:
        return TextScore(0.0)
    line = " ".join(toks)
    raw_text = " ".join(w.text for w in words)

    points = 0.0
    hits: list[str] = []
    laughs = sum(1 for t in toks if LAUGH_RE.match(t))
    points += 4.0 * laughs

    for t in toks:
        if t in reaction:
            points += 1.0
            hits.append(t)
        elif t in weak:
            points += 0.15
        elif is_swear(t, language):
            points += 1.5
            hits.append(t)          # shown uncensored in the app (censoring is for the video)
    for ph in phrases:
        n = line.count(ph)
        if n:
            points += 1.5 * n
            hits.append(ph)

    points += 0.5 * min(raw_text.count("!"), 6)
    # stretched letters ("hayııır", "nooo") and repeated words = emphasis
    points += 0.8 * sum(1 for t in toks if re.search(r"(\w)\1\1", t) and not LAUGH_RE.match(t))
    points += 0.8 * sum(1 for a, b in zip(toks, toks[1:]) if a == b and len(a) > 1)

    # a little credit for having speech at all (context helps a clip land)
    wps = len(toks) / max(duration, 1.0)
    points += min(wps, 2.5) * 0.25

    return TextScore(1 - math.exp(-points / 6.0), hits, laughs, len(toks))
