"""AI listening: a sound-recognition network that hears *what* a sound is.

The hand-made detectors measure loudness, brightness and rhythm, so they can
be fooled: an explosion is loud, a cough is sudden. This adds CED-mini, a
small audio-tagging network trained on Google's AudioSet (2 million YouTube
clips, 527 sound types). Every 1 s it listens to 2 s of audio and says how
likely it is to be laughter, screaming, an explosion, a cough, music...

  - laughter / screaming become their own detectors ("Laughter (AI)")
  - gunfire, explosions and coughs damp the loudness detectors, so loud game
    noise stops winning (how much depends on the Focus slider)

Runs on the CPU with onnxruntime (already installed with faster-whisper), in
the same pass that reads the audio. The model (~10 MB inside a 48 MB
download) is fetched once from the sherpa-onnx GitHub releases.
"""

from __future__ import annotations

import csv
import io
import os
import tarfile
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .reframe import CONFIG_DIR

PACKAGE = "sherpa-onnx-ced-mini-audio-tagging-2024-04-19"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
             f"audio-tagging-models/{PACKAGE}.tar.bz2")
MODEL_DIR = os.path.join(CONFIG_DIR, "models", "ced-mini")
SR = 16000
WIN = 2 * SR          # 2 s of audio per look
STEP = SR             # one look every 1 s
SHIFT = 160           # 10 ms feature frames
BATCH = 48

# AudioSet class names grouped into what matters for clips
GROUPS: dict[str, list[str]] = {
    "laugh": ["Laughter", "Giggle", "Belly laugh", "Chuckle, chortle", "Snicker",
              "Baby laughter"],
    "scream": ["Screaming", "Shout", "Yell", "Battle cry"],
    "cheer": ["Cheering", "Applause", "Crowd"],
    "boom": ["Gunshot, gunfire", "Machine gun", "Explosion", "Burst, pop",
             "Artillery fire", "Cap gun", "Fusillade", "Boom", "Eruption"],
    "cough": ["Cough", "Throat clearing", "Sneeze", "Sniff"],
    "music": ["Music"],
    "speech": ["Speech"],
}


class ListenError(RuntimeError):
    pass


# ------------------------------------------------------------------ model files
def model_files(report: Callable[[str], None] | None = None) -> tuple[str, str]:
    """(model.onnx, labels.csv), downloading them the first time."""
    onnx = os.path.join(MODEL_DIR, "model.int8.onnx")
    labels = os.path.join(MODEL_DIR, "class_labels_indices.csv")
    if os.path.exists(onnx) and os.path.exists(labels):
        return onnx, labels
    os.makedirs(MODEL_DIR, exist_ok=True)
    say = report or (lambda m: None)
    say("Downloading the listening AI (48 MB, once)…")
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0)
            buf = io.BytesIO()
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                buf.write(chunk)
                if total:
                    say(f"Downloading the listening AI… {100 * buf.tell() // total}%")
    except OSError as e:
        raise ListenError(f"Couldn't download the listening AI ({e}). Check your "
                          "internet connection; analysis continues without it.") from e
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r:bz2") as tar:
        for member in tar.getmembers():
            name = os.path.basename(member.name)
            if name in ("model.int8.onnx", "class_labels_indices.csv"):
                src = tar.extractfile(member)
                tmp = os.path.join(MODEL_DIR, name + ".part")
                with open(tmp, "wb") as f:
                    f.write(src.read())
                os.replace(tmp, os.path.join(MODEL_DIR, name))
    if not (os.path.exists(onnx) and os.path.exists(labels)):
        raise ListenError("The listening AI download was incomplete.")
    return onnx, labels


# ------------------------------------------------------------------ features
def _mel_banks(n_mels=64, n_fft=512, sr=SR, low=0.0, high=8000.0) -> np.ndarray:
    mel = lambda f: 1127.0 * np.log(1.0 + f / 700.0)  # noqa: E731
    nb = n_fft // 2
    m = mel(np.arange(nb) * sr / n_fft)
    lo, hi = mel(low), mel(high)
    d = (hi - lo) / (n_mels + 1)
    banks = np.zeros((n_mels, nb + 1), dtype=np.float32)
    for b in range(n_mels):
        left, c, right = lo + b * d, lo + (b + 1) * d, lo + (b + 2) * d
        banks[b, :nb] = np.maximum(0, np.minimum((m - left) / (c - left),
                                                 (right - m) / (right - c)))
    return banks


_BANKS = _mel_banks()
_HANN = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(512) / 511)).astype(np.float32)


def features(x: np.ndarray) -> np.ndarray:
    """CED input for one window: 64 mel bands x frames, in dB (the Kaldi
    settings sherpa-onnx uses: 32 ms Hann frames every 10 ms, no snipping)."""
    n = len(x)
    nf = (n + SHIFT // 2) // SHIFT
    idx = np.arange(nf)[:, None] * SHIFT + SHIFT // 2 - 256 + np.arange(512)[None, :]
    idx = np.where(idx < 0, -idx - 1, idx)
    idx = np.where(idx >= n, 2 * n - 1 - idx, idx)
    power = np.abs(np.fft.rfft(x[idx] * _HANN, n=512, axis=1)) ** 2
    e = 10 * np.log10(np.maximum(power @ _BANKS.T, 1e-10))
    e = np.maximum(e, e.max() - 120)
    return e.T.astype(np.float32)          # (64, frames)


# ------------------------------------------------------------------ listener
@dataclass
class Hearing:
    """What the AI heard: per group, one probability per second
    (window k covers seconds k..k+2)."""
    step: float
    groups: dict[str, np.ndarray] = field(default_factory=dict)

    def per_hop(self, name: str, n_hops: int, hop: float) -> np.ndarray:
        """Resample to the detectors' hop grid: a hop gets the highest
        probability of the windows that cover it."""
        p = self.groups.get(name)
        out = np.zeros(n_hops, dtype=np.float32)
        if p is None or not len(p):
            return out
        t = (np.arange(n_hops) + 0.5) * hop
        k_hi = np.clip(np.floor(t / self.step).astype(int), 0, len(p) - 1)
        k_lo = np.clip(k_hi - 1, 0, len(p) - 1)
        out[:] = np.maximum(p[k_lo], p[k_hi])
        return out

    def at(self, start: float, end: float) -> dict[str, float]:
        """Peak probability per group inside [start, end] seconds."""
        a = max(0, int(start / self.step) - 1)
        b = max(a + 1, int(end / self.step))
        return {k: float(v[a:b].max()) if len(v[a:b]) else 0.0
                for k, v in self.groups.items()}


class Listener:
    """Feed audio chunks (float32, 16 kHz mono) as they are decoded."""

    def __init__(self, report: Callable[[str], None] | None = None,
                 threads: int = 0) -> None:
        import onnxruntime as ort   # installed with faster-whisper
        onnx, labels = model_files(report)
        with open(labels, encoding="utf-8") as f:
            names = [row[2] for row in csv.reader(f)][1:]
        index = {n: i for i, n in enumerate(names)}
        self.groups = {g: [index[n] for n in ns if n in index] for g, ns in GROUPS.items()}
        so = ort.SessionOptions()
        if threads:
            so.intra_op_num_threads = threads
        so.log_severity_level = 3
        self.sess = ort.InferenceSession(onnx, so, providers=["CPUExecutionProvider"])
        self.buf = np.zeros(0, dtype=np.float32)
        self.pending: list[np.ndarray] = []
        self.out: list[np.ndarray] = []

    def feed(self, chunk: np.ndarray) -> None:
        self.buf = np.concatenate([self.buf, chunk.astype(np.float32, copy=False)])
        k = 0
        while k + WIN <= len(self.buf):
            self.pending.append(features(self.buf[k:k + WIN]))
            k += STEP
            if len(self.pending) >= BATCH:
                self._run()
        self.buf = self.buf[k:]

    def _run(self) -> None:
        if not self.pending:
            return
        probs = self.sess.run(None, {"feats": np.stack(self.pending)})[0]
        self.pending = []
        self.out.append(np.stack([probs[:, ii].max(1) if ii else np.zeros(len(probs))
                                  for ii in self.groups.values()], axis=1))

    def finish(self) -> Hearing:
        if len(self.buf) >= SR // 2:          # last partial window
            tail = np.pad(self.buf, (0, max(0, WIN - len(self.buf))))
            self.pending.append(features(tail[:WIN]))
        self._run()
        allp = (np.concatenate(self.out) if self.out
                else np.zeros((0, len(self.groups)), dtype=np.float32))
        return Hearing(STEP / SR, {g: allp[:, i].astype(np.float32)
                                   for i, g in enumerate(self.groups)})


def hear_file(path: str, start: float = 0.0, duration: float | None = None,
              track: int = 0) -> Hearing:
    """Convenience: listen to (part of) a file in one go."""
    from .media import stream_audio
    lis = Listener()
    for chunk in stream_audio(path, start=start, duration=duration, track=track):
        lis.feed(chunk)
    return lis.finish()
