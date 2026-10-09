"""Highlight detectors.

Each detector turns the analysis context into a "how interesting is this
moment" timeline sampled every HOP seconds (0.5 s). Values are normalised to
0..1 so detectors can be mixed with weights.

To add a new signal later (laughter ML model, funny words from a transcript,
webcam face/motion, chat activity...), subclass Detector, implement compute()
and add it to DEFAULT_DETECTORS. Nothing else needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .features import AudioFeatures

HOP = 0.5  # seconds per timeline step


# ---------------------------------------------------------------- helpers

def _clip01(x: np.ndarray) -> np.ndarray:
    return np.clip(x, 0.0, 1.0)


def robust_z(x: np.ndarray) -> np.ndarray:
    med = np.median(x)
    mad = np.median(np.abs(x - med)) * 1.4826
    if mad < 1e-9:
        mad = np.std(x) + 1e-9
    return (x - med) / mad


def squash(z: np.ndarray, scale: float = 2.5) -> np.ndarray:
    """Map a positive z-score to 0..1 (0 = ordinary, ~1 = extreme)."""
    return 1.0 - np.exp(-np.clip(z, 0, None) / scale)


def smooth(x: np.ndarray, width: int) -> np.ndarray:
    if width <= 1 or len(x) < width:
        return x
    k = np.ones(width) / width
    return np.convolve(x, k, mode="same")


def rolling_baseline(x: np.ndarray, hops_per_block: int, blocks: int) -> np.ndarray:
    """Slow-moving median baseline. Streams get louder/quieter over hours
    (music, game volume, different segments), so 'loud' must be relative to
    what was happening nearby, not to the whole video."""
    n = len(x)
    nb = max(1, int(np.ceil(n / hops_per_block)))
    padded = np.full(nb * hops_per_block, np.nan)
    padded[:n] = x
    block_med = np.nanmedian(padded.reshape(nb, hops_per_block), axis=1)
    half = blocks // 2
    smoothed = np.array([
        np.median(block_med[max(0, i - half): i + half + 1]) for i in range(nb)
    ])
    centers = (np.arange(nb) + 0.5) * hops_per_block
    return np.interp(np.arange(n), centers, smoothed)


def _noisiness(flatness: np.ndarray) -> np.ndarray:
    """Speech, laughs, yells and screams have a pitch (flatness ≲ 0.1);
    coughs, sneezes, mic bumps and bangs are noise (≳ 0.25). Take the max over
    neighbouring hops so a cough's onset and tail are both covered."""
    noisy = np.clip((flatness - 0.13) / 0.14, 0, 1)
    return np.maximum.reduce([noisy, np.r_[noisy[1:], 0], np.r_[0, noisy[:-1]]])


def _voiced_share(harm: np.ndarray, vband: np.ndarray) -> np.ndarray:
    """Per hop: share of voice-band energy in clearly pitched frames."""
    return (vband * (harm > 0.75)).sum(1) / (vband.sum(1) + 1e-12)


def _voiceness(voiced_share: np.ndarray, centroid: np.ndarray,
               flatness: np.ndarray) -> np.ndarray:
    """0..1 how much a moment sounds like a human voice.

    voiced_share = fraction of the voice-band energy in this half-second
    that is clearly pitched. Talking/laughing/yelling: 0.5-1. Guns,
    explosions, machinery: ~0.1-0.3 (tested on real Iron Nest audio, where
    the voice sits 10-20 dB under the engine rumble). Screams pitch above
    the normal range, so 'bright and tonal' counts as voice too."""
    pitched = np.clip((voiced_share - 0.25) / 0.35, 0, 1)
    shriek = (np.clip((centroid - 900) / 400, 0, 1)
              * np.clip((0.12 - flatness) / 0.06, 0, 1))
    return np.maximum(pitched, shriek)


# ---------------------------------------------------------------- context

@dataclass
class Context:
    """Per-hop arrays shared by all detectors (computed once)."""
    feats: AudioFeatures
    frames_per_hop: int
    n_hops: int
    db_frames: np.ndarray
    db: np.ndarray          # per-hop loudness (90th pct of frames, dB)
    baseline: np.ndarray    # local loudness baseline (dB)
    excess: np.ndarray      # db - baseline
    centroid: np.ndarray
    hiratio: np.ndarray
    zcr: np.ndarray
    noisy: np.ndarray       # 0 = pitched voice, 1 = pure noise (cough, bang)
    voice: np.ndarray       # 0..1 how much this moment sounds like a human voice
    chat: tuple | None = None   # (weighted message rate, laughs) per hop, if chat known
    ai: dict | None = None      # AI listening: group -> probability per hop

    @classmethod
    def build(cls, feats: AudioFeatures) -> "Context":
        fph = int(round(HOP * feats.frame_rate))
        n_hops = len(feats.rms) // fph
        if n_hops < 4:
            raise RuntimeError("Video is too short to analyse.")
        cut = n_hops * fph

        def hops(a: np.ndarray) -> np.ndarray:
            return a[:cut].reshape(n_hops, fph)

        db_frames = 20 * np.log10(feats.rms + 1e-6)
        db = np.percentile(hops(db_frames), 90, axis=1)
        # 15 s blocks, median over ~2.5 minutes
        baseline = rolling_baseline(db, hops_per_block=30, blocks=11)
        loud_w = hops(feats.rms) ** 2 + 1e-12
        wmean = lambda a: (hops(a) * loud_w).sum(1) / loud_w.sum(1)  # noqa: E731
        return cls(
            feats=feats, frames_per_hop=fph, n_hops=n_hops,
            db_frames=db_frames, db=db, baseline=baseline,
            excess=db - baseline,
            centroid=wmean(feats.centroid),
            hiratio=wmean(feats.hiratio),
            zcr=hops(feats.zcr).mean(1),
            noisy=_noisiness(wmean(feats.flatness)),
            voice=_voiceness(_voiced_share(hops(feats.harmonic), hops(feats.vband)),
                             wmean(feats.centroid), wmean(feats.flatness)),
        )


# ---------------------------------------------------------------- detectors

@dataclass
class Detector:
    name: str = "base"
    label: str = "Base"
    weight: float = 1.0
    # how much to damp this detector on noisy, unpitched sounds (coughs...)
    noise_penalty: float = 0.9
    # follow the 'voice focus' setting (damp loud non-voice game sounds)?
    voice_gated: bool = True

    def compute(self, ctx: Context) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError


@dataclass
class LoudMoment(Detector):
    """Moments clearly louder than what was happening around them
    (yelling, big reactions). Noisy sounds like coughs are damped centrally."""
    name: str = "loud"
    label: str = "Loud reaction"
    weight: float = 1.0

    def compute(self, ctx: Context) -> np.ndarray:
        # dB above local baseline; 6 dB ≈ twice as loud
        return squash(smooth(ctx.excess, 3) - 4.0, scale=6.0)


@dataclass
class SuddenBurst(Detector):
    """Sharp jumps in loudness: jump-scares, sudden screams, outbursts."""
    name: str = "burst"
    label: str = "Sudden outburst"
    weight: float = 0.7

    def compute(self, ctx: Context) -> np.ndarray:
        look = 6  # compare with previous 3 s
        prev = np.convolve(ctx.db, np.ones(look) / look, mode="full")[: ctx.n_hops]
        prev = np.concatenate([[ctx.db[0]], prev[:-1]])
        rise = ctx.db - prev
        return squash(rise - 6.0, scale=6.0)


@dataclass
class LaughterRhythm(Detector):
    """Laughter is loud, voiced and *pulsed*: 'ha-ha-ha' modulates loudness
    roughly 3-8 times per second. We measure how much of the loudness
    envelope's movement sits in that band over a 2 s window."""
    name: str = "laugh"
    label: str = "Laughter"
    weight: float = 1.3
    # laughs can be breathy; coughs pulse ~2x/s, below the 3-8 Hz laugh band,
    # so this detector needs only a light penalty
    noise_penalty: float = 0.3
    voice_gated: bool = False    # its rhythm test is already voice-specific
    window_s: float = 2.0

    def compute(self, ctx: Context) -> np.ndarray:
        fr = ctx.feats.frame_rate
        win = int(self.window_s * fr)
        env = np.maximum(ctx.db_frames, ctx.db_frames.max() - 60)  # floor silence
        if len(env) < win:
            return np.zeros(ctx.n_hops)
        # one window centred on each hop
        centres = (np.arange(ctx.n_hops) + 0.5) * ctx.frames_per_hop
        starts = np.clip((centres - win / 2).astype(int), 0, len(env) - win)
        idx = starts[:, None] + np.arange(win)[None, :]
        seg = env[idx]
        seg = seg - seg.mean(axis=1, keepdims=True)
        seg *= np.hanning(win)[None, :]
        spec = np.abs(np.fft.rfft(seg, axis=1)) ** 2
        f = np.fft.rfftfreq(win, 1.0 / fr)
        band = spec[:, (f >= 3) & (f <= 8)].sum(1)
        total = spec[:, (f >= 0.5) & (f <= 20)].sum(1) + 1e-9
        # Absolute thresholds (not relative to the video): normal speech is
        # also syllable-pulsed, so we need rhythm AND depth AND loudness.
        rhythm = np.clip((band / total - 0.5) / 0.35, 0, 1)
        pulse = np.clip((np.sqrt(band) / win - 1.0) / 2.0, 0, 1)
        gate = 1 / (1 + np.exp(-(ctx.excess - 5.0) / 1.5))  # louder than talk
        raw = smooth(rhythm * np.sqrt(pulse) * gate, 3)
        return squash(raw * 5.0, scale=1.0)


@dataclass
class Scream(Detector):
    """Screams/shrieks: loud *and* bright (energy pushed into high
    frequencies), sustained for a moment."""
    name: str = "scream"
    label: str = "Scream"
    weight: float = 1.0

    def compute(self, ctx: Context) -> np.ndarray:
        bright = robust_z(ctx.hiratio) + 0.5 * robust_z(ctx.centroid)
        loud = np.clip(ctx.excess - 3.0, 0, None) / 6.0
        # harsh broadband noise (bangs, mic bumps) is bright too; a scream
        # has a pitch, so damp very noisy frames
        tonal = np.clip(1.0 - (ctx.zcr - 0.3) / 0.2, 0, 1)
        raw = np.clip(bright, 0, None) * loud * tonal
        # must last ~1 s: a hop only counts if a neighbour is also bright
        nb = np.maximum(np.r_[raw[1:], 0], np.r_[0, raw[:-1]])
        sustained = np.minimum(raw, nb)
        return squash(sustained - 0.5, scale=1.5)


@dataclass
class ChatReaction(Detector):
    """Chat explodes: far more messages than usual for this stream, and
    especially laughs (KEKW, LUL, kdkdkd, 😂). Already shifted for the chat
    delay. Compared with the chat speed of the last few minutes, so a busy
    chat isn't 'always funny' and a quiet chat's small burst still counts."""
    name: str = "chat"
    label: str = "Chat reacted"
    weight: float = 1.2
    noise_penalty: float = 0.0
    voice_gated: bool = False

    def compute(self, ctx: Context) -> np.ndarray:
        if ctx.chat is None:
            return np.zeros(ctx.n_hops)
        rate, laughs = ctx.chat
        burst = smooth(rate, 6) * 6                     # messages per 3 s
        base = rolling_baseline(burst, hops_per_block=60, blocks=11)
        z = (burst - base) / np.sqrt(base + 1.0)        # ~Poisson spread
        laugh_bonus = np.clip(smooth(laughs, 6) * 6 / 3.0, 0, 1)
        return np.clip(squash(z - 2.0, scale=2.0) + 0.3 * laugh_bonus, 0, 1)


@dataclass
class AILaugh(Detector):
    """The listening AI recognises laughter (giggles, belly laughs,
    chuckles) by how it sounds, not just by loudness or rhythm, so quiet
    laughs count and loud game noise doesn't."""
    name: str = "ai_laugh"
    label: str = "Laughter (AI)"
    weight: float = 1.6
    noise_penalty: float = 0.0
    voice_gated: bool = False

    def compute(self, ctx: Context) -> np.ndarray:
        p = ctx.ai["laugh"] if ctx.ai else np.zeros(ctx.n_hops)
        return np.clip((p - 0.08) / 0.3, 0, 1) ** 0.8


@dataclass
class AIScream(Detector):
    """Screaming, shouting, yelling as recognised by the listening AI."""
    name: str = "ai_scream"
    label: str = "Scream (AI)"
    weight: float = 0.9
    noise_penalty: float = 0.0
    voice_gated: bool = False

    def compute(self, ctx: Context) -> np.ndarray:
        p = ctx.ai["scream"] if ctx.ai else np.zeros(ctx.n_hops)
        return np.clip((p - 0.15) / 0.4, 0, 1)


# loudness-based detectors that game noise and coughs can fool
_FOOLED_BY_BOOMS = ("loud", "burst", "scream")
_FOOLED_BY_COUGHS = ("loud", "burst", "scream", "laugh")


DEFAULT_DETECTORS: list[Detector] = [
    LoudMoment(), SuddenBurst(), LaughterRhythm(), Scream(),
]


@dataclass
class Timeline:
    hop: float
    combined: np.ndarray
    parts: dict[str, np.ndarray] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    loudness_db: np.ndarray | None = None


def run_detectors(feats: AudioFeatures,
                  detectors: list[Detector] | None = None,
                  voice_focus: float = 0.5,
                  chat: list[tuple[float, str]] | None = None,
                  hearing=None) -> Timeline:
    """voice_focus 0 = any loud moment counts (great for horror games),
    1 = only moments where a human voice is the loud part.
    `hearing` (from clipper.listen) adds the listening AI."""
    detectors = list(detectors or DEFAULT_DETECTORS)
    ctx = Context.build(feats)
    if hearing is not None:
        ctx.ai = {g: hearing.per_hop(g, ctx.n_hops, HOP) for g in hearing.groups}
        detectors += [AILaugh(), AIScream()]
    if chat and len(chat) >= 20:   # too few messages say nothing
        from .chat import chat_timeline
        ctx.chat = chat_timeline(chat, ctx.n_hops, HOP)
        detectors.append(ChatReaction())
    parts, labels = {}, {}
    # AI detectors add on top instead of diluting: when the AI hears nothing
    # special, scores stay exactly comparable with analysis without it
    total_w = sum(d.weight for d in detectors if not d.name.startswith("ai_")) or 1.0
    combined = np.zeros(ctx.n_hops)
    for d in detectors:
        s = np.nan_to_num(d.compute(ctx))[: ctx.n_hops]
        s = s * (1 - d.noise_penalty * ctx.noisy)
        if d.voice_gated:
            s = s * (1 - voice_focus * (1 - ctx.voice))
        if ctx.ai:
            # the AI heard an explosion / gunfire / a cough here: the loudness
            # detectors were probably fooled (Focus decides how much for booms)
            if d.name in _FOOLED_BY_BOOMS:
                boom = np.clip((ctx.ai["boom"] - 0.1) / 0.4, 0, 1)
                s = s * (1 - 0.85 * voice_focus * boom * (1 - _clip01(ctx.ai["laugh"] * 3)))
            if d.name in _FOOLED_BY_COUGHS:
                s = s * (1 - 0.8 * np.clip((ctx.ai["cough"] - 0.1) / 0.4, 0, 1))
        parts[d.name], labels[d.name] = s, d.label
        combined += d.weight * s
    combined /= total_w
    # Moments where several detectors agree are the best ones: reward overlap.
    agreement = np.mean([p > 0.35 for k, p in parts.items()
                         if not k.startswith("ai_")], axis=0)
    combined = smooth(combined * (1 + agreement), 4)
    return Timeline(HOP, combined, parts, labels, loudness_db=ctx.db)
