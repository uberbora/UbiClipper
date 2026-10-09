"""Chat reactions: download VOD chat and turn it into a highlight signal.

When something funny happens, chat explodes a few seconds later: the
message rate jumps and fills with laughs (KEKW, LUL, kdkdkd, hahaha, 😂, 💀).
We count messages per half-second, weight laugh/hype messages higher, shift
everything back by the usual chat delay, and compare with the normal chat
speed around it (so a busy chat isn't 'always funny').
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re

import numpy as np

from .net import NetError, get_json, post_json

CHAT_DELAY = 6.0     # seconds between a moment and chat reacting to it

_LAUGH = re.compile(
    r"(kekw|omegalul|lul\b|lmao|lmfao|xd+\b|icant|pepelaugh|kappa|"
    r"\b(?:a?h[aeıiu]){2,}|\b(?:[kj][dsş]){2,}|\b(?:s[jk]){2,}|asd[fg]|"
    r"😂|🤣|💀|😭|ölüyorum|öldüm|koptum|gülmekten|"
    r"\b(?:ja){2,}|\bk{4,}|\b(?:rs){2,}|\bmdr|\bptdr|\bjpp|(?:ха){2,}|(?:ах){2,}|ору|"
    r"ه{3,}|哈哈|ㅋㅋ|\bw{3,}\b|草|\b5{3,}\b)", re.I)
_HYPE = re.compile(
    r"(pog|poggers|omg|wtf|oha|yok artık|vay|helal|efsane|clip|klip|"
    r"\?\?\?|!!!|😱|😮|🔥|👀|w+\b)", re.I)


# ------------------------------------------------------------------ cache
def load_cached(folder: str) -> list[tuple[float, str]] | None:
    try:
        with open(os.path.join(folder, "chat.json"), encoding="utf-8") as f:
            return [(float(t), str(m)) for t, m in json.load(f)]
    except (OSError, ValueError, TypeError):
        return None


def save_cache(folder: str, msgs: list[tuple[float, str]]) -> None:
    try:
        with open(os.path.join(folder, "chat.json"), "w", encoding="utf-8") as f:
            json.dump(msgs, f, ensure_ascii=False)
    except OSError:
        pass


# ------------------------------------------------------------------ Kick
def fetch_kick_chat(base: str, channel_id: int, start: dt.datetime, duration: float,
                    report, should_cancel, max_pages: int = 5000
                    ) -> list[tuple[float, str]]:
    """Kick serves chat replay newest-first: /api/v2/channels/<id>/messages
    ?cursor=<µs timestamp> returns messages before that moment plus the next
    (older) cursor. We start at the VOD's end and walk back to its start."""
    from .kick import _parse_time
    t0 = start.timestamp()
    cursor = int((t0 + duration + 5) * 1e6)
    out: list[tuple[float, str]] = []
    seen: set[str] = set()
    for page in range(max_pages):
        if should_cancel and should_cancel():
            raise InterruptedError("Cancelled")
        data = get_json(f"{base}/api/v2/channels/{channel_id}/messages",
                        params={"cursor": str(cursor)})
        body = data.get("data", data) if isinstance(data, dict) else {}
        msgs = body.get("messages") or []
        oldest = None
        for m in msgs:
            ts = m.get("created_at")
            if not ts:
                continue
            t = _parse_time(ts).timestamp() - t0
            oldest = t if oldest is None else min(oldest, t)
            mid = str(m.get("id") or (ts + str(m.get("content"))))
            if 0 <= t <= duration and mid not in seen:
                seen.add(mid)
                out.append((round(t, 2), str(m.get("content") or "")))
        nxt = body.get("cursor")
        try:
            nxt = int(nxt)
        except (TypeError, ValueError):
            nxt = 0
        if oldest is not None:
            report(f"Reading chat ({len(out)} messages)",
                   min(1.0, max(0.0, (duration - oldest) / max(duration, 1))))
        if not msgs or nxt <= 0 or nxt >= cursor or (oldest is not None and oldest < 0):
            break
        cursor = nxt
    out.sort()
    return out


# ------------------------------------------------------------------ Twitch
TWITCH_GQL = os.environ.get("UBICLIPPER_TWITCH_GQL", "https://gql.twitch.tv/gql")
TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"     # Twitch's public web client
_COMMENTS_HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"


def fetch_twitch_chat(video_id: str, duration: float, report, should_cancel,
                      max_pages: int = 20000) -> list[tuple[float, str]]:
    """Page by time offset (paging by cursor trips Twitch's integrity check)."""
    out: list[tuple[float, str]] = []
    offset = 0
    seen: set[str] = set()
    for _ in range(max_pages):
        if should_cancel and should_cancel():
            raise InterruptedError("Cancelled")
        payload = [{"operationName": "VideoCommentsByOffsetOrCursor",
                    "variables": {"videoID": str(video_id), "contentOffsetSeconds": offset},
                    "extensions": {"persistedQuery": {"version": 1,
                                                      "sha256Hash": _COMMENTS_HASH}}}]
        resp = post_json(TWITCH_GQL, payload, headers={"Client-Id": TWITCH_CLIENT_ID})
        first = resp[0] if isinstance(resp, list) and resp else resp
        if first.get("errors"):
            raise NetError(0, TWITCH_GQL, str(first["errors"])[:200])
        comments = (((first.get("data") or {}).get("video") or {}).get("comments") or {})
        edges = comments.get("edges") or []
        last = offset
        for e in edges:
            n = e.get("node") or {}
            t = float(n.get("contentOffsetSeconds") or 0)
            key = str(n.get("id") or (t, len(out)))
            if key in seen:
                continue
            seen.add(key)
            text = "".join(f.get("text", "") for f in
                           ((n.get("message") or {}).get("fragments") or []))
            out.append((t, text))
            last = max(last, int(t))
        report(f"Reading chat ({len(out)} messages)", min(1.0, last / max(duration, 1)))
        if not edges or not (comments.get("pageInfo") or {}).get("hasNextPage"):
            break
        offset = max(offset + 1, last + 1)
        if offset >= duration:
            break
    out.sort()
    return out


# ------------------------------------------------------------------ signal
def chat_timeline(msgs: list[tuple[float, str]], n_hops: int, hop: float,
                  delay: float = CHAT_DELAY) -> tuple[np.ndarray, np.ndarray]:
    """Per hop: weighted message count (laughs x3, hype x1.5) and laugh count,
    moved earlier by the chat delay so it lines up with the moment itself."""
    rate = np.zeros(n_hops)
    laughs = np.zeros(n_hops)
    for t, text in msgs:
        i = int((t - delay) / hop)
        if not 0 <= i < n_hops:
            continue
        if _LAUGH.search(text):
            rate[i] += 3.0
            laughs[i] += 1
        elif _HYPE.search(text):
            rate[i] += 1.5
        else:
            rate[i] += 1.0
    return rate, laughs
