"""CI check: the ONNX Whisper engine gives the same words and timings as
faster-whisper's CTranslate2 engine (both on the CPU here; GitHub's machines
have no real GPU, so DirectML itself is tested on users' PCs).

    python test_whisper_onnx.py MODEL_DIR AUDIO.wav [MODEL_DIR2 ...]
"""

import difflib
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from faster_whisper import WhisperModel  # noqa: E402

from clipper.whisper_onnx import OnnxWhisperModel  # noqa: E402

audio_path = sys.argv[2]
import wave  # noqa: E402
with wave.open(audio_path) as w:          # 16 kHz mono 16-bit (jfk.wav)
    assert w.getframerate() == 16000 and w.getnchannels() == 1
    one = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
# speech, 4 s of silence, speech again: tests the voice filter and timing
audio = np.concatenate([one, np.zeros(4 * 16000, np.float32), one])
OPTS = dict(word_timestamps=True, vad_filter=True, beam_size=5,
            condition_on_previous_text=False,
            vad_parameters={"threshold": 0.3, "min_silence_duration_ms": 500,
                            "speech_pad_ms": 400})


def run(model, language=None):
    t = time.time()
    segs, info = model.transcribe(audio, language=language, **OPTS)
    segs = list(segs)
    words = [w for s in segs for w in (s.words or [])]
    return segs, words, info, time.time() - t


ref = WhisperModel("large-v3-turbo", device="cpu", compute_type="float32")
rsegs, rwords, rinfo, rt = run(ref)
rtext = " ".join(s.text.strip() for s in rsegs)
lines = [f"reference (CTranslate2 fp32): {rt:.1f}s, lang {rinfo.language} "
         f"{rinfo.language_probability:.2f}: {rtext[:300]}"]
ok = True
runs = [(sys.argv[1], None), (sys.argv[1], "cpu")] + [(d, None) for d in sys.argv[3:]]
for model_dir, bind in runs:
    if bind:
        os.environ["UBI_ONNX_BIND"] = bind       # the IO-binding path DirectML uses
    else:
        os.environ.pop("UBI_ONNX_BIND", None)
    try:
        m = OnnxWhisperModel(model_dir, device="cpu")
        segs, words, info, t = run(m)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        lines.append(f"{model_dir}{' (bound)' if bind else ''}: FAILED {type(e).__name__}: {str(e)[:300]}")
        ok = False
        continue
    text = " ".join(s.text.strip() for s in segs)
    sim = difflib.SequenceMatcher(None, rtext.lower(), text.lower()).ratio()
    pairs = [(a, b) for a, b in zip(rwords, words) if a.word.strip().lower() == b.word.strip().lower()]
    ds = [abs(a.start - b.start) for a, b in pairs] + [abs(a.end - b.end) for a, b in pairs]
    lines.append(f"{os.path.basename(model_dir.rstrip('/'))}{' (bound)' if bind else ''}: {t:.1f}s, lang {info.language} "
                 f"{info.language_probability:.2f}, text match {sim:.3f}, words {len(words)}/"
                 f"{len(rwords)}, timing diff mean {np.mean(ds) if ds else -1:.3f}s max "
                 f"{np.max(ds) if ds else -1:.2f}s: {text[:300]}")
    lang_ok = info.language == rinfo.language
    if sim < 0.9 or not lang_ok or (ds and np.mean(ds) > 0.15):
        ok = False
print("\n".join(lines))
print("::notice title=ONNX Whisper vs CTranslate2::" + "%0A".join(lines).replace("\n", " "))
sys.exit(0 if ok else 1)
