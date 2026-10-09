"""Who is speaking? Speaker diarization for coloured subtitles.

Runs a small speaker-recognition network (WeSpeaker ResNet34, trained on
VoxCeleb: thousands of voices in many languages) with onnxruntime, which
faster-whisper already installs: no PyTorch, no account. The model (~26 MB)
is downloaded once.

How it works on a clip (≤ 60 s):
  1. speech regions come from Whisper's word timings,
  2. every ~1.5 s of speech gets a "voice fingerprint" (embedding),
  3. fingerprints are grouped by similarity (agglomerative clustering) into
     at most 10 people,
  4. every word gets the speaker of the fingerprints covering it, short
     flickers are smoothed out,
  5. people are numbered by how much they talk: person 1 = talks most
     (usually the streamer).
"""

from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .reframe import CONFIG_DIR

MODEL_NAME = "wespeaker_en_voxceleb_resnet34_LM.onnx"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
             "speaker-recongition-models/" + MODEL_NAME)
MODEL_DIR = os.path.join(CONFIG_DIR, "models")
MAX_SPEAKERS = 10
SR = 16000


# ------------------------------------------------------------------ features
def _mel_banks(n_mels: int, n_fft: int, sr: int, low: float = 20.0,
               high: float = 0.0) -> np.ndarray:
    """Kaldi-style triangular mel filters (what WeSpeaker was trained with)."""
    high = high if high > 0 else sr / 2 + high
    mel = lambda f: 1127.0 * np.log(1.0 + f / 700.0)  # noqa: E731
    n_bins = n_fft // 2
    fft_freqs = np.arange(n_bins) * sr / n_fft
    m = mel(fft_freqs)
    lo, hi = mel(low), mel(high)
    delta = (hi - lo) / (n_mels + 1)
    banks = np.zeros((n_mels, n_bins + 1), dtype=np.float32)
    for b in range(n_mels):
        left, center, right = lo + b * delta, lo + (b + 1) * delta, lo + (b + 2) * delta
        up = (m - left) / (center - left)
        down = (right - m) / (right - center)
        banks[b, :n_bins] = np.maximum(0.0, np.minimum(up, down))
    return banks


_BANKS = _mel_banks(80, 512, SR)
_WINDOW = (0.54 - 0.46 * np.cos(2 * np.pi * np.arange(400) / 399)).astype(np.float32)


def fbank(samples: np.ndarray) -> np.ndarray:
    """80-dim log-mel filterbank, 25 ms frames every 10 ms (Kaldi recipe),
    mean-normalised over time. samples: float32 mono 16 kHz in [-1, 1]."""
    x = samples.astype(np.float32) * 32768.0
    if len(x) < 400:
        x = np.pad(x, (0, 400 - len(x)))
    n = 1 + (len(x) - 400) // 160
    idx = np.arange(400)[None, :] + 160 * np.arange(n)[:, None]
    fr = x[idx]
    fr = fr - fr.mean(axis=1, keepdims=True)                  # remove DC
    pre = fr.copy()
    pre[:, 1:] -= 0.97 * fr[:, :-1]                           # pre-emphasis
    pre[:, 0] -= 0.97 * fr[:, 0]
    spec = np.abs(np.fft.rfft(pre * _WINDOW, n=512, axis=1)) ** 2
    feats = np.log(np.maximum(spec @ _BANKS.T, 1.1920929e-07))
    return (feats - feats.mean(axis=0, keepdims=True)).astype(np.float32)


# ------------------------------------------------------------------ model
class SpeakerModelMissing(RuntimeError):
    pass


def model_path(download: bool = True,
               report: Callable[[str, float], None] | None = None) -> str:
    path = os.path.join(MODEL_DIR, MODEL_NAME)
    if os.path.exists(path):
        return path
    if not download:
        raise SpeakerModelMissing("Speaker model not downloaded yet.")
    os.makedirs(MODEL_DIR, exist_ok=True)
    part = path + ".part"
    say = report or (lambda m, f: None)
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    say(f"Downloading speaker model ({done / 1e6:.0f}/{total / 1e6:.0f} MB)",
                        done / total)
        os.replace(part, path)
    except Exception as e:
        if os.path.exists(part):
            os.remove(part)
        raise SpeakerModelMissing(f"Couldn't download the speaker model: {e}") from e
    return path


_SESSION = None


def _session(report=None):
    global _SESSION
    if _SESSION is None:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        _SESSION = ort.InferenceSession(model_path(report=report), opts,
                                        providers=["CPUExecutionProvider"])
    return _SESSION


def embed(segments: list[np.ndarray], report=None) -> np.ndarray:
    """L2-normalised voice fingerprints, one per audio segment."""
    sess = _session(report)
    name = sess.get_inputs()[0].name
    out = []
    for seg in segments:
        e = sess.run(None, {name: fbank(seg)[None]})[0][0]
        out.append(e / (np.linalg.norm(e) + 1e-9))
    return np.array(out, dtype=np.float32)


# ------------------------------------------------------------------ clustering
# Tuned on labelled recordings: same person ≥ ~0.3, different people ≤ ~0.23
# (2 s windows) -> 0.25 found the right number of people in every test.
THRESHOLD = 0.25


def cluster(embs: np.ndarray, threshold: float = THRESHOLD,
            max_speakers: int = MAX_SPEAKERS) -> np.ndarray:
    """Average-linkage agglomerative clustering on cosine similarity.
    Merge while the closest groups are more similar than `threshold`, and
    always until at most `max_speakers` remain."""
    n = len(embs)
    if n == 0:
        return np.zeros(0, dtype=int)
    groups = {i: [i] for i in range(n)}
    sim = embs @ embs.T
    while len(groups) > 1:
        keys = list(groups)
        best, pair = -2.0, None
        for a in range(len(keys)):
            ga = groups[keys[a]]
            for b in range(a + 1, len(keys)):
                s = float(sim[np.ix_(ga, groups[keys[b]])].mean())
                if s > best:
                    best, pair = s, (keys[a], keys[b])
        if best < threshold and len(groups) <= max_speakers:
            break
        ka, kb = pair
        groups[ka] += groups.pop(kb)
    labels = np.zeros(n, dtype=int)
    for lab, members in enumerate(groups.values()):
        labels[members] = lab
    return labels


# ------------------------------------------------------------------ words
@dataclass
class _Win:
    start: float
    end: float


def _speech_windows(words, total: float, win: float = 2.0, hop: float = 1.0):
    """Windows over speech only (from word timings)."""
    regions: list[list[float]] = []
    for w in words:
        if regions and w.start - regions[-1][1] < 0.35:
            regions[-1][1] = max(regions[-1][1], w.end)
        else:
            regions.append([w.start, w.end])
    wins: list[_Win] = []
    for a, b in regions:
        a, b = max(0.0, a - 0.1), min(total, b + 0.1)
        if b - a < win:
            c = (a + b) / 2
            wins.append(_Win(max(0.0, c - max(b - a, 1.0) / 2),
                             min(total, c + max(b - a, 1.0) / 2)))
            continue
        t = a
        while t + win <= b + 1e-6:
            wins.append(_Win(t, t + win))
            t += hop
        if wins[-1].end < b - 0.3:
            wins.append(_Win(b - win, b))
    return wins


# ------------------------------------------------------------------ v2
# Tuned on labelled conversations + one-person recordings mixed with real
# game audio from streams (see README): the old per-word vote changed colour
# far too often on stream audio. Now:
#   - small "people" (< 20 % of the speech, < 3 windows) are merged into the
#     closest real person: a shout or a noisy moment is not a new person,
#   - people whose average voice is very similar are merged,
#   - colours are decided for the whole sentence flow at once (Viterbi):
#     changing colour costs something, so it only happens when the voice
#     really changes, preferably at a pause or the end of a sentence,
#   - in an export, all clips are clustered together, so the streamer is
#     the same colour in every clip (and friends keep theirs).
CLUSTER_THRESHOLD = 0.25
MIN_SHARE = 0.08
MIN_WINDOWS = 5
MERGE_ABOVE = 0.50
SWITCH_COST = 0.30
PAUSE_SWITCH_COST = 0.05


@dataclass
class Voices:
    """Speech windows of one clip and their voice fingerprints."""
    words: list
    wins: list
    emb: np.ndarray
    good: np.ndarray | None = None   # window is really speech (not gunfire/music)

    def __post_init__(self) -> None:
        if self.good is None:
            self.good = np.ones(len(self.wins), dtype=bool)


_LISTENER = None


def speech_mask(segs: list[np.ndarray]) -> np.ndarray:
    """Ask the listening AI which windows are speech. Gunfire, explosions and
    music under a word made 'new people' out of game sounds."""
    global _LISTENER
    try:
        from . import listen
        if _LISTENER is None:
            _LISTENER = listen.Listener()
        lis = _LISTENER
        feats = [listen.features(np.pad(s, (0, max(0, listen.WIN - len(s))))[:listen.WIN])
                 for s in segs]
        probs = lis.sess.run(None, {"feats": np.stack(feats)})[0]
        g = lis.groups
        speech = probs[:, g["speech"]].max(1)
        noise = np.maximum(probs[:, g["boom"]].max(1), probs[:, g["music"]].max(1))
        good = (speech >= 0.2) & (speech >= 0.6 * noise)
        return good if good.sum() >= 2 else np.ones(len(segs), dtype=bool)
    except Exception:        # no model / no internet: use every window
        return np.ones(len(segs), dtype=bool)


def voices(audio: np.ndarray, words, report=None, check_speech: bool = True) -> Voices:
    if not words:
        return Voices([], [], np.zeros((0, 256), np.float32))
    wins = _speech_windows(words, len(audio) / SR)
    segs = [audio[int(w.start * SR):int(w.end * SR)] for w in wins]
    emb = embed(segs, report) if segs else np.zeros((0, 256), np.float32)
    good = speech_mask(segs) if check_speech and segs else None
    return Voices(list(words), wins, emb, good)


def find_people(embs: np.ndarray, max_speakers: int = MAX_SPEAKERS,
                min_share: float | None = None) -> np.ndarray:
    """Average voice of every person found (rows, L2-normalised).
    'Auto' (10) is careful: a new colour needs clear evidence. When the user
    says how many people there are, trust that and split more readily."""
    min_share = MIN_SHARE if min_share is None else min_share
    told = max_speakers < MAX_SPEAKERS
    threshold = CLUSTER_THRESHOLD + (0.05 if told else 0.0)
    min_windows = 3 if told else MIN_WINDOWS
    if told:
        min_share = min(min_share, 0.03)
    if len(embs) == 0:
        return np.zeros((0, 256), np.float32)
    if len(embs) < 2 or max_speakers <= 1:
        c = embs.mean(0, keepdims=True)
        return c / np.linalg.norm(c, axis=1, keepdims=True)
    # cluster freely first (a forced small number would let a few odd
    # windows grab a whole 'person'), clean up, then respect the maximum
    lab = cluster(embs, threshold, MAX_SPEAKERS)

    def cents():
        ks = sorted(set(lab.tolist()))
        c = np.stack([embs[lab == k].mean(0) for k in ks])
        return ks, c / np.linalg.norm(c, axis=1, keepdims=True)

    while True:
        ks, c = cents()
        if len(ks) < 2:
            break
        sizes = np.array([(lab == k).sum() for k in ks])
        small = [i for i, n in enumerate(sizes)
                 if n < max(min_windows, min_share * len(lab))]
        if small and len(small) < len(ks):
            i = min(small, key=lambda i: sizes[i])
            j = max((j for j in range(len(ks)) if j != i), key=lambda j: float(c[i] @ c[j]))
            lab[lab == ks[i]] = ks[j]
            continue
        sim = c @ c.T
        np.fill_diagonal(sim, -1)
        i, j = np.unravel_index(np.argmax(sim), sim.shape)
        if sim[i, j] > MERGE_ABOVE or len(ks) > max_speakers:
            lab[lab == ks[j]] = ks[i]
            continue
        break
    return cents()[1]


def assign(v: Voices, people: np.ndarray) -> list[int]:
    """Person index (row of `people`) for every word of a clip."""
    words, wins = v.words, v.wins
    k = len(people)
    if not words:
        return []
    if k <= 1 or not wins:
        return [0] * len(words)
    simw = v.emb @ people.T
    wq = np.where(v.good, 1.0, 0.15)      # game-noise windows barely count
    em = np.zeros((len(words), k))
    for i, w in enumerate(words):
        mid = (w.start + w.end) / 2
        sc, tw = np.zeros(k), 0.0
        for j, win in enumerate(wins):
            if win.start <= mid <= win.end:
                wt = wq[j] * (1.0 - abs(mid - (win.start + win.end) / 2) / (win.end - win.start))
                sc += wt * simw[j]
                tw += wt
        if tw == 0:
            j = int(np.argmin([min(abs(mid - x.start), abs(mid - x.end)) for x in wins]))
            sc, tw = simw[j], 1.0
        em[i] = sc / tw
    # Viterbi: most likely colours when changing colour has a price
    dur = np.array([max(0.1, w.end - w.start) for w in words])
    score = em[0] * dur[0]
    back = []
    for i in range(1, len(words)):
        gap = words[i].start - words[i - 1].end
        prev = (words[i - 1].text or "").strip()
        cost = PAUSE_SWITCH_COST if gap >= 0.3 or prev[-1:] in ".?!" else SWITCH_COST
        trans = score[:, None] - cost * (1 - np.eye(k))
        back.append(trans.argmax(0))
        score = trans.max(0) + em[i] * dur[i]
    path = [int(score.argmax())]
    for b in reversed(back):
        path.append(int(b[path[-1]]))
    return path[::-1]


def order_by_talk(clips_words: list[list], labels: list[list[int]]) -> dict[int, int]:
    """Renumber people: 0 = talks most over all clips (usually the streamer)."""
    talk: dict[int, float] = {}
    for words, labs in zip(clips_words, labels):
        for w, lab in zip(words, labs):
            talk[lab] = talk.get(lab, 0.0) + (w.end - w.start)
    return {lab: n for n, lab in enumerate(sorted(talk, key=lambda k: -talk[k]))}


def diarize_many(clips: list[Voices], max_speakers: int = MAX_SPEAKERS) -> list[list[int]]:
    """Speaker number per word for several clips of the same stream, with
    the same person getting the same number in every clip."""
    max_speakers = max(1, min(MAX_SPEAKERS, int(max_speakers)))
    if max_speakers == 1 or not any(v.words for v in clips):
        return [[0] * len(v.words) for v in clips]
    embs = [v.emb[v.good] for v in clips if len(v.emb)]
    allemb = np.concatenate(embs) if embs else np.zeros((0, 256), np.float32)
    people = find_people(allemb, max_speakers)
    labels = [assign(v, people) for v in clips]
    order = order_by_talk([v.words for v in clips], labels)
    return [[order[lab] for lab in labs] for labs in labels]


def diarize(audio: np.ndarray, words, threshold: float | None = None,
            max_speakers: int = MAX_SPEAKERS, report=None) -> list[int]:
    """Speaker number (0 = talks most) for every word of one clip."""
    if not words:
        return []
    return diarize_many([voices(audio, words, report)], max_speakers)[0]
