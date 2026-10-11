"""Whisper on ONNX Runtime: runs on any DirectX 12 graphics card (NVIDIA, AMD,
Intel Arc) through DirectML, whose files Microsoft signs, so Windows' Smart
App Control doesn't block it the way it blocks NVIDIA's unsigned CUDA files.

It plugs into faster-whisper: `OnnxWhisperModel` is faster-whisper's own
WhisperModel (same voice-activity filter, temperature fallback, prompts and
word timestamps) with CTranslate2 swapped for `OnnxEngine`, which implements
the few CTranslate2 calls faster-whisper makes: encode, detect_language,
generate (beam search / sampling with Whisper's timestamp rules) and align
(cross-attention + DTW word timing, as in openai-whisper).

Model files (packaging/models/export_whisper_onnx.py): encoder.onnx,
decoder.onnx, config.json, tokenizer.json, preprocessor_config.json.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import numpy as np

NEG_INF = -np.inf


# ------------------------------------------------------------------ results
@dataclass
class GenResult:
    sequences_ids: list = field(default_factory=list)
    scores: list = field(default_factory=list)
    no_speech_prob: float = 0.0


@dataclass
class AlignResult:
    alignments: list = field(default_factory=list)
    text_token_probs: list = field(default_factory=list)


@dataclass
class EncoderOutput:
    cross_k: np.ndarray       # (L, B, 1500, D)
    cross_v: np.ndarray

    @property
    def shape(self):
        return (self.cross_k.shape[1], self.cross_k.shape[2], self.cross_k.shape[3])


# ------------------------------------------------------------------ sessions
def available_providers() -> list[str]:
    try:
        import onnxruntime as ort
        return list(ort.get_available_providers())
    except Exception:
        return []


def make_session(path: str, device: str):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.log_severity_level = 3
    if device == "dml":
        # DirectML wants these (it can't run nodes in parallel or reuse
        # memory patterns across differently shaped calls)
        so.enable_mem_pattern = False
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        providers = [("DmlExecutionProvider", {"device_id": 0}), "CPUExecutionProvider"]
    else:
        providers = ["CPUExecutionProvider"]
    sess = ort.InferenceSession(path, sess_options=so, providers=providers)
    if device == "dml" and "DmlExecutionProvider" not in sess.get_providers():
        raise RuntimeError("DirectML is not available on this PC")
    return sess


def _log_softmax(x: np.ndarray) -> np.ndarray:
    m = np.max(x, axis=-1, keepdims=True)
    m = np.where(np.isfinite(m), m, 0.0)
    y = x - m
    return y - np.log(np.sum(np.exp(y), axis=-1, keepdims=True))


def _softmax(x: np.ndarray) -> np.ndarray:
    return np.exp(_log_softmax(x))


# ------------------------------------------------------------------ engine
class OnnxEngine:
    """The subset of ctranslate2.models.Whisper that faster-whisper uses."""

    def __init__(self, model_dir: str, device: str = "dml") -> None:
        with open(os.path.join(model_dir, "config.json"), encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.device = device
        self.device_index = [0]
        self.is_multilingual = bool(self.cfg.get("is_multilingual", True))
        self.n_mels = int(self.cfg["n_mels"])
        self.n_ctx = int(self.cfg["n_text_ctx"])
        self.n_layer = int(self.cfg["n_text_layer"])
        self.d = int(self.cfg["n_text_state"])
        self.enc = make_session(os.path.join(model_dir, "encoder.onnx"), device)
        self.dec = make_session(os.path.join(model_dir, "decoder.onnx"), device)

        import tokenizers
        tok = tokenizers.Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        tid = tok.token_to_id
        self.eot = tid("<|endoftext|>")
        self.sot = tid("<|startoftranscript|>")
        self.no_timestamps = tid("<|notimestamps|>")
        self.timestamp_begin = self.no_timestamps + 1
        self.no_speech = tid("<|nospeech|>") or tid("<|nocaptions|>")
        self.blank = tok.encode(" ", add_special_tokens=False).ids
        translate = tid("<|translate|>")
        self.lang_ids = list(range(self.sot + 1, translate))
        self.lang_tokens = [tok.id_to_token(i) for i in self.lang_ids]

    # ---------------------------------------------------------------- encoder
    def encode(self, features, to_cpu: bool = False) -> EncoderOutput:
        x = np.asarray(features, dtype=np.float32)
        if x.ndim == 2:
            x = x[None]
        k, v = self.enc.run(None, {"mel": np.ascontiguousarray(x)})
        return EncoderOutput(k, v)

    # ---------------------------------------------------------------- decoder
    def _empty_cache(self, b: int) -> tuple[np.ndarray, np.ndarray]:
        z = np.zeros((self.n_layer, b, self.n_ctx, self.d), np.float32)
        return z, z.copy()

    def _step(self, tokens, k, v, ck, cv, offset):
        logits, k, v, qk = self.dec.run(None, {
            "tokens": np.ascontiguousarray(tokens, dtype=np.int64),
            "self_k": k, "self_v": v, "cross_k": ck, "cross_v": cv,
            "offset": np.array([offset], dtype=np.int64)})
        return logits, k, v, qk

    @staticmethod
    def _tile(enc: EncoderOutput, index: int, n: int):
        ck = np.repeat(enc.cross_k[:, index:index + 1], n, axis=1)
        cv = np.repeat(enc.cross_v[:, index:index + 1], n, axis=1)
        return ck, cv

    def detect_language(self, encoder_output: EncoderOutput):
        out = []
        for b in range(encoder_output.cross_k.shape[1]):
            ck, cv = self._tile(encoder_output, b, 1)
            k, v = self._empty_cache(1)
            logits, *_ = self._step(np.array([[self.sot]]), k, v, ck, cv, 0)
            lg = logits[0, -1, self.lang_ids]
            p = _softmax(lg)
            order = np.argsort(-p)
            out.append([(self.lang_tokens[i], float(p[i])) for i in order])
        return out

    # ---------------------------------------------------------------- rules
    def _filter(self, logits: np.ndarray, seqs: list[list[int]], sample_begin: int,
                suppress, suppress_blank: bool, timestamps: bool,
                max_initial_ts: int | None, rep_penalty: float,
                no_repeat: int) -> np.ndarray:
        """Whisper's logit rules for one step. logits: (N, V) float64."""
        n = logits.shape[0]
        first = len(seqs[0]) == sample_begin
        if suppress_blank and first:
            logits[:, self.blank + [self.eot]] = NEG_INF
        if suppress:
            logits[:, list(suppress)] = NEG_INF
        if rep_penalty and rep_penalty != 1.0:
            for i in range(n):
                prev = list(set(seqs[i][sample_begin:]))
                if prev:
                    s = logits[i, prev]
                    logits[i, prev] = np.where(s < 0, s * rep_penalty, s / rep_penalty)
        if no_repeat and no_repeat > 0:
            for i in range(n):
                gen = seqs[i][sample_begin:]
                if len(gen) >= no_repeat:
                    tail = tuple(gen[-(no_repeat - 1):]) if no_repeat > 1 else ()
                    for j in range(len(gen) - no_repeat + 1):
                        if tuple(gen[j:j + no_repeat - 1]) == tail:
                            logits[i, gen[j + no_repeat - 1]] = NEG_INF
        if not timestamps:
            return logits
        tb = self.timestamp_begin
        logits[:, self.no_timestamps] = NEG_INF
        for i in range(n):
            seq = seqs[i][sample_begin:]
            last_ts = len(seq) >= 1 and seq[-1] >= tb
            penult_ts = len(seq) < 2 or seq[-2] >= tb
            if last_ts:
                if penult_ts:       # a pair just closed: next is text
                    logits[i, tb:] = NEG_INF
                else:               # a timestamp must be followed by text or another timestamp
                    logits[i, :self.eot] = NEG_INF
            stamps = [t for t in seq if t >= tb]
            if stamps:
                floor = stamps[-1] if (last_ts and not penult_ts) else stamps[-1] + 1
                logits[i, tb:floor] = NEG_INF
        if first:
            logits[:, :tb] = NEG_INF
            if max_initial_ts is not None:
                logits[:, tb + max_initial_ts + 1:] = NEG_INF
        lp = _log_softmax(logits)
        for i in range(n):
            ts_lp = lp[i, tb:]
            ts_lp = ts_lp[np.isfinite(ts_lp)]
            if ts_lp.size:
                ts_sum = np.log(np.sum(np.exp(ts_lp)))
                text_max = np.max(lp[i, :tb])
                if ts_sum > text_max:
                    logits[i, :tb] = NEG_INF
        return logits

    # ---------------------------------------------------------------- generate
    def generate(self, encoder_output: EncoderOutput, prompts, beam_size: int = 5,
                 patience: float = 1.0, length_penalty: float = 1.0,
                 repetition_penalty: float = 1.0, no_repeat_ngram_size: int = 0,
                 max_length: int = 448, return_scores: bool = True,
                 return_no_speech_prob: bool = True, suppress_blank: bool = True,
                 suppress_tokens=(-1,), max_initial_timestamp_index: int = 50,
                 num_hypotheses: int = 1, sampling_topk: int = 1,
                 sampling_temperature: float = 1.0, **_ignored):
        results = []
        suppress = [t for t in (suppress_tokens or ()) if t is not None and t >= 0]
        for b, prompt in enumerate(prompts):
            prompt = list(prompt)
            timestamps = self.no_timestamps not in prompt
            sot_index = prompt.index(self.sot) if self.sot in prompt else 0
            limit = min(self.n_ctx, max_length if max_length else self.n_ctx)
            sampling = sampling_temperature > 0 and beam_size == 1 and (
                sampling_topk == 0 or sampling_topk > 1 or num_hypotheses > 1)
            n = max(1, num_hypotheses if sampling else beam_size)
            rules = dict(suppress=suppress, suppress_blank=suppress_blank, timestamps=timestamps,
                         max_initial_ts=max_initial_timestamp_index,
                         rep_penalty=repetition_penalty, no_repeat=no_repeat_ngram_size)
            if sampling:
                res = self._sample(encoder_output, b, prompt, n, limit, sampling_temperature,
                                   length_penalty, rules, sot_index)
            else:
                res = self._beam(encoder_output, b, prompt, n, patience, limit,
                                 length_penalty, rules, sot_index)
            results.append(res)
        return results

    def _first_pass(self, enc, b, prompt, n):
        ck, cv = self._tile(enc, b, 1)
        k, v = self._empty_cache(1)
        logits, k, v, _ = self._step(np.array([prompt]), k, v, ck, cv, 0)
        k = np.repeat(k, n, axis=1)
        v = np.repeat(v, n, axis=1)
        ck, cv = self._tile(enc, b, n)
        return logits[0], k, v, ck, cv

    def _beam(self, enc, b, prompt, beam, patience, limit, lp_pen, rules, sot_index):
        logits_all, k, v, ck, cv = self._first_pass(enc, b, prompt, 1)
        no_speech = float(_softmax(logits_all[sot_index].astype(np.float64))[self.no_speech])
        start = len(prompt)
        # beams: (tokens, sum_logprob)
        beams = [(list(prompt), 0.0)]
        last = logits_all[-1][None].astype(np.float64)
        finished: list[tuple[list[int], float]] = []
        max_finished = max(1, int(round(beam * patience)))
        offset = start
        while True:
            seqs = [t for t, _ in beams]
            lg = self._filter(last.copy(), seqs, start, **rules)
            lp = _log_softmax(lg)
            cand = []
            for i, (toks, score) in enumerate(beams):
                top = np.argsort(-lp[i])[:beam + 1]
                for tkn in top:
                    if not np.isfinite(lp[i, tkn]):
                        continue
                    cand.append((score + float(lp[i, tkn]), i, int(tkn)))
            cand.sort(key=lambda c: -c[0])
            new_beams, parents = [], []
            for total, i, tkn in cand:
                seq = beams[i][0] + [tkn]
                if tkn == self.eot:
                    if len(finished) < max_finished:
                        finished.append((seq, total))
                else:
                    new_beams.append((seq, total))
                    parents.append(i)
                if len(new_beams) >= beam:
                    break
            done = (len(finished) >= max_finished or not new_beams
                    or offset + 1 >= limit)
            if done:
                break
            # reorder caches to the surviving beams, then one step for all of them
            if len(parents) != k.shape[1] or parents != list(range(k.shape[1])):
                k = k[:, parents]
                v = v[:, parents]
                if ck.shape[1] != len(parents):
                    ck, cv = self._tile(enc, b, len(parents))
            beams = new_beams
            toks = np.array([[s[-1]] for s, _ in beams])
            logits, k, v, _ = self._step(toks, k, v, ck, cv, offset)
            offset += 1
            last = logits[:, -1].astype(np.float64)
        if not finished:
            finished = [(s, sc) for s, sc in beams]
        ranked = []
        for seq, total in finished:
            gen = [t for t in seq[start:] if t != self.eot]
            ranked.append((total / max(1, len(gen)) ** lp_pen, gen))
        ranked.sort(key=lambda r: -r[0])
        best = ranked[0]
        return GenResult([best[1]], [best[0]], no_speech)

    def _sample(self, enc, b, prompt, n, limit, temperature, lp_pen, rules, sot_index):
        logits_all, k, v, ck, cv = self._first_pass(enc, b, prompt, n)
        no_speech = float(_softmax(logits_all[sot_index].astype(np.float64))[self.no_speech])
        start = len(prompt)
        seqs = [list(prompt) for _ in range(n)]
        scores = [0.0] * n
        alive = [True] * n
        last = np.repeat(logits_all[-1][None], n, axis=0).astype(np.float64)
        rng = np.random.default_rng()
        offset = start
        while any(alive) and offset < limit:
            lg = self._filter(last.copy(), seqs, start, **rules)
            lp = _log_softmax(lg)
            probs = _softmax(lg / temperature)
            nxt = []
            for i in range(n):
                if not alive[i]:
                    nxt.append(self.eot)
                    continue
                p = probs[i]
                p = np.where(np.isfinite(p), p, 0.0)
                tkn = int(rng.choice(len(p), p=p / p.sum()))
                scores[i] += float(lp[i, tkn])
                seqs[i].append(tkn)
                if tkn == self.eot:
                    alive[i] = False
                nxt.append(tkn)
            if not any(alive) or offset + 1 >= limit:
                break
            logits, k, v, _ = self._step(np.array([[t] for t in nxt]), k, v, ck, cv, offset)
            offset += 1
            last = logits[:, -1].astype(np.float64)
        ranked = []
        for i in range(n):
            gen = [t for t in seqs[i][start:] if t != self.eot]
            ranked.append((scores[i] / max(1, len(gen)) ** lp_pen, gen))
        ranked.sort(key=lambda r: -r[0])
        return GenResult([r[1] for r in ranked], [r[0] for r in ranked], no_speech)

    # ---------------------------------------------------------------- align
    def align(self, encoder_output: EncoderOutput, start_sequence, text_tokens,
              num_frames, median_filter_width: int = 7):
        out = []
        frames = num_frames if isinstance(num_frames, (list, tuple)) else None
        for j, text in enumerate(text_tokens):
            b = j if encoder_output.cross_k.shape[1] > j else 0
            nf = int(frames[j] if frames else num_frames)
            tokens = list(start_sequence) + [self.no_timestamps] + list(text) + [self.eot]
            ck, cv = self._tile(encoder_output, b, 1)
            k, v = self._empty_cache(1)
            logits, _, _, qk = self._step(np.array([tokens]), k, v, ck, cv, 0)
            sampled = logits[0, len(start_sequence):, :self.eot].astype(np.float64)
            probs = _softmax(sampled)
            text_probs = [float(probs[i, t]) for i, t in enumerate(text)]
            w = qk[0][:, :, : max(1, nf // 2)].astype(np.float64)    # (A, T, F)
            w = _softmax(w)
            mean = w.mean(axis=-2, keepdims=True)
            std = w.std(axis=-2, keepdims=True)
            w = (w - mean) / np.where(std > 0, std, 1.0)
            w = _median_filter(w, median_filter_width)
            matrix = w.mean(axis=0)[len(start_sequence):-1]
            ti, fi = _dtw(-matrix)
            out.append(AlignResult(list(zip(ti.tolist(), fi.tolist())), text_probs))
        return out


def _median_filter(x: np.ndarray, width: int) -> np.ndarray:
    """Median over the last axis, like openai-whisper's (reflect padding)."""
    if width <= 1 or x.shape[-1] <= width // 2:
        return x
    pad = width // 2
    xp = np.pad(x, [(0, 0)] * (x.ndim - 1) + [(pad, pad)], mode="reflect")
    win = np.lib.stride_tricks.sliding_window_view(xp, width, axis=-1)
    return np.median(win, axis=-1)


def _dtw(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """openai-whisper's DTW on a cost matrix (tokens × frames)."""
    n, m = x.shape
    cost = np.full((n + 1, m + 1), np.inf)
    trace = np.full((n + 1, m + 1), -1, dtype=np.int8)
    cost[0, 0] = 0.0
    for j in range(1, m + 1):
        for i in range(1, n + 1):
            c0, c1, c2 = cost[i - 1, j - 1], cost[i - 1, j], cost[i, j - 1]
            if c0 < c1 and c0 < c2:
                c, t = c0, 0
            elif c1 < c0 and c1 < c2:
                c, t = c1, 1
            else:
                c, t = c2, 2
            cost[i, j] = x[i - 1, j - 1] + c
            trace[i, j] = t
    trace[0, :] = 2
    trace[:, 0] = 1
    i, j = n, m
    res = []
    while i > 0 or j > 0:
        res.append((i - 1, j - 1))
        t = trace[i, j]
        if t == 0:
            i, j = i - 1, j - 1
        elif t == 1:
            i -= 1
        else:
            j -= 1
    arr = np.array(res[::-1], dtype=np.int64)
    if arr.size == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    return arr[:, 0], arr[:, 1]


# ------------------------------------------------------------------ model
def OnnxWhisperModel(model_dir: str, device: str = "dml"):
    """faster-whisper's WhisperModel running on OnnxEngine."""
    import faster_whisper.transcribe as fwt
    import tokenizers

    class _Model(fwt.WhisperModel):
        def __init__(self) -> None:
            self.logger = fwt.get_logger()
            self.model = OnnxEngine(model_dir, device)
            self.hf_tokenizer = tokenizers.Tokenizer.from_file(
                os.path.join(model_dir, "tokenizer.json"))
            self.feat_kwargs = self._get_feature_kwargs(model_dir, None)
            self.feature_extractor = fwt.FeatureExtractor(**self.feat_kwargs)
            self.input_stride = 2
            self.num_samples_per_token = self.feature_extractor.hop_length * self.input_stride
            self.frames_per_second = (self.feature_extractor.sampling_rate
                                      // self.feature_extractor.hop_length)
            self.tokens_per_second = (self.feature_extractor.sampling_rate
                                      // self.num_samples_per_token)
            self.time_precision = 0.02
            self.max_length = 448

        def encode(self, features):
            if features.ndim == 2:
                features = np.expand_dims(features, 0)
            return self.model.encode(np.ascontiguousarray(features, dtype=np.float32))

    return _Model()
