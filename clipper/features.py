"""Low-level audio features computed in a single streaming pass.

We compute a few cheap per-frame features (20 ms frames) for the whole video:
  rms       - loudness
  zcr       - zero-crossing rate (noisy/harsh sounds, screams, laughter breaths)
  centroid  - spectral centroid in Hz (brightness / pitch-ish)
  hiratio   - share of energy above 2 kHz (screams, shrieks)
  flatness  - spectral flatness 0..1: ~0 for pitched voice, high for noise
              (coughs, sneezes, mic bumps, bangs)
  harmonic  - 0..1 how periodic the sound is at a voice pitch, measured only
              in the voice band (250-1500 Hz) so engine/explosion rumble
              underneath can't hide or fake a voice.
  vband     - energy in that voice band (to weight the above)

Detectors then work on these arrays, which for a 6-hour video are ~1M floats
each - tiny. Future detectors (speech-to-text, webcam, chat) produce their own
timelines and get combined the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .media import SAMPLE_RATE, stream_audio

FRAME = 320                      # 20 ms at 16 kHz
FRAME_RATE = SAMPLE_RATE / FRAME  # 50 frames per second


@dataclass
class AudioFeatures:
    rms: np.ndarray
    zcr: np.ndarray
    centroid: np.ndarray
    hiratio: np.ndarray
    flatness: np.ndarray
    harmonic: np.ndarray
    vband: np.ndarray
    frame_rate: float = FRAME_RATE

    @property
    def duration(self) -> float:
        return len(self.rms) / self.frame_rate


def _frame_features(frames: np.ndarray) -> tuple[np.ndarray, ...]:
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    signs = np.signbit(frames)
    zcr = np.mean(signs[:, 1:] != signs[:, :-1], axis=1)

    window = np.hanning(FRAME).astype(np.float32)
    spec = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2
    freqs = np.fft.rfftfreq(FRAME, 1.0 / SAMPLE_RATE)
    total = spec.sum(axis=1) + 1e-12
    centroid = (spec * freqs).sum(axis=1) / total
    hiratio = spec[:, freqs >= 2000].sum(axis=1) / total
    band = spec[:, (freqs >= 100) & (freqs <= 4000)] + 1e-10
    flatness = np.exp(np.mean(np.log(band), axis=1)) / np.mean(band, axis=1)
    harmonic, vband = _harmonicity(frames)
    return rms, zcr, centroid, hiratio, flatness, harmonic, vband


_LAG_LO, _LAG_HI = SAMPLE_RATE // 500, SAMPLE_RATE // 70   # 500 Hz .. 70 Hz


def _harmonicity(frames: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Peak of the normalised autocorrelation in the voice-pitch range,
    computed on the 250-1500 Hz band only. Real streams have a loud low
    rumble (engines, music bass, explosions) that is often 10-20 dB louder
    than the voice; looking only where voice harmonics live lets the voice
    show through. Returns (periodicity 0..1, voice-band energy)."""
    y = frames - frames.mean(axis=1, keepdims=True)
    n = y.shape[1]
    spec = np.abs(np.fft.rfft(y, 2 * n, axis=1)) ** 2
    f = np.fft.rfftfreq(2 * n, 1.0 / SAMPLE_RATE)
    spec *= ((f >= 250) & (f <= 1500))[None, :]
    r = np.fft.irfft(spec, axis=1)[:, :n]
    lags = np.arange(_LAG_LO, _LAG_HI + 1)
    # unbiased: correct for fewer overlapping samples at longer lags
    rr = r[:, lags] * (n / (n - lags))[None, :]
    return np.clip(rr.max(axis=1) / (r[:, 0] + 1e-9), 0, 1), r[:, 0]


def extract(path: str, duration: float | None = None,
            progress: Callable[[float], None] | None = None,
            should_cancel: Callable[[], bool] | None = None,
            audio_track: int = 0,
            on_audio: Callable[[np.ndarray], None] | None = None) -> AudioFeatures:
    """on_audio gets every decoded chunk too (the listening AI rides along
    in the same pass instead of decoding the audio twice)."""
    parts: list[tuple[np.ndarray, ...]] = []
    leftover = np.zeros(0, dtype=np.float32)
    seconds_done = 0.0

    for chunk in stream_audio(path, track=audio_track):
        if should_cancel and should_cancel():
            raise InterruptedError("Analysis cancelled")
        if on_audio:
            on_audio(chunk)
        data = np.concatenate([leftover, chunk])
        n = len(data) // FRAME
        leftover = data[n * FRAME:]
        if n:
            parts.append(_frame_features(data[: n * FRAME].reshape(n, FRAME)))
        seconds_done += len(chunk) / SAMPLE_RATE
        if progress and duration:
            progress(min(seconds_done / duration, 1.0))

    if not parts:
        raise RuntimeError("No audio could be decoded from this file.")
    cols = list(zip(*parts))
    return AudioFeatures(*(np.concatenate(c).astype(np.float32) for c in cols))
