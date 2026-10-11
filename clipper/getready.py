"""Everything UbiClipper downloads after installing, in one place.

The installer stays small; the AI models (and, on NVIDIA PCs, the CUDA
libraries that make subtitles fast) come down on the first start, with
progress, in the "Get UbiClipper ready" window. Everything here resumes or
skips what's already there, so it is safe to run again.

The NVIDIA libraries come straight from the official NVIDIA packages on PyPI
(the same files ``pip install nvidia-cublas-cu12`` would get): the wheel is
downloaded, its checksum checked, and only the DLLs are kept in
``~/.ubiclipper/nvidia``. No pip needed, so it works in the installed app.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Callable

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".ubiclipper")
NVIDIA_DIR = os.path.join(CONFIG_DIR, "nvidia")
WHISPER_DEFAULT = "large-v3-turbo"

Report = Callable[[str, float | None], None]     # (message, fraction 0..1 or None)
Cancel = Callable[[], bool]

# package, required major version, exact version (None = newest), DLL that
# proves it's there. NVIDIA doesn't sign cuBLAS / the CUDA runtime on Windows
# (no version, in any download: packaging/probe_*.py checked), so on PCs with
# Smart App Control the GPU may be blocked; transcribe.gpu_status() tests that
# once and falls back to the CPU quietly.
NVIDIA_PACKAGES = [
    ("nvidia-cuda-runtime-cu12", 12, None, "cudart64_12.dll"),
    ("nvidia-cublas-cu12", 12, None, "cublas64_12.dll"),
    ("nvidia-cudnn-cu12", 9, None, "cudnn_ops64_9.dll"),
]


@dataclass
class Item:
    key: str
    name: str
    size: str
    required: bool


ITEMS = [
    Item("whisper", "Speech to text (Whisper)", "1.6 GB", True),
    Item("listen", "Listening AI (laughs, screams)", "48 MB", True),
    Item("voices", "Voice model for speaker colours", "26 MB", True),
    Item("judge", "AI judge", "4 GB", False),
    Item("gpu", "GPU speed-up for NVIDIA cards", "1.2 GB", False),
    Item("gpu_dml", "GPU speech model (any graphics card)", "1.7 GB", False),
]


class Cancelled(Exception):
    pass


# ------------------------------------------------------------------ status
def whisper_repo(model: str = WHISPER_DEFAULT) -> str:
    try:
        from faster_whisper.utils import _MODELS
        return _MODELS.get(model, model)
    except Exception:
        return {"large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo"}.get(
            model, f"Systran/faster-whisper-{model}")


def _hf_cache() -> str:
    try:
        from huggingface_hub import constants
        return constants.HF_HUB_CACHE
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")


def _whisper_folder(model: str) -> str:
    return os.path.join(_hf_cache(), "models--" + whisper_repo(model).replace("/", "--"))


def whisper_ready(model: str = WHISPER_DEFAULT) -> bool:
    snaps = os.path.join(_whisper_folder(model), "snapshots")
    if not os.path.isdir(snaps):
        return False
    for snap in os.listdir(snaps):
        if os.path.exists(os.path.join(snaps, snap, "model.bin")):
            return True
    return False


def listen_ready() -> bool:
    from . import listen
    return all(os.path.exists(os.path.join(listen.MODEL_DIR, f))
               for f in ("model.int8.onnx", "class_labels_indices.csv"))


def voices_ready() -> bool:
    from . import speakers
    return os.path.exists(os.path.join(speakers.MODEL_DIR, speakers.MODEL_NAME))


def judge_ready() -> bool:
    from . import judge
    return judge.is_downloaded()


def nvidia_gpu() -> bool:
    """An NVIDIA card with a driver is present (whether or not CUDA libs are)."""
    if shutil.which("nvidia-smi"):
        return True
    win = os.environ.get("SystemRoot", r"C:\Windows")
    return os.path.isfile(os.path.join(win, "System32", "nvidia-smi.exe"))


def _have_dll(dll: str) -> bool:
    from .transcribe import _nvidia_lib_dirs
    return any(os.path.isfile(os.path.join(d, dll)) for d in _nvidia_lib_dirs())


def gpu_blocked() -> bool:
    """The NVIDIA files are here but Windows (Smart App Control) won't load them."""
    from .transcribe import gpu_block_reason
    return bool(gpu_block_reason())


def gpu_libs_ready() -> bool:
    return all(_have_dll(dll) for _, _, _, dll in NVIDIA_PACKAGES)


def status(model: str = WHISPER_DEFAULT) -> dict[str, bool | None]:
    """key -> ready? (None = not applicable on this PC)."""
    def safe(fn):
        try:
            return fn()
        except Exception:
            return False
    return {
        "whisper": safe(lambda: whisper_ready(model)),
        "listen": safe(listen_ready),
        "voices": safe(voices_ready),
        "judge": safe(judge_ready),
        # None = nothing to download here: no NVIDIA card, or Windows blocks it
        "gpu": (None if not nvidia_gpu() or (safe(gpu_libs_ready) and safe(gpu_blocked))
                else safe(gpu_libs_ready)),
        # the DirectML model: for AMD / Intel cards, and NVIDIA ones Windows blocks
        "gpu_dml": _dml_state(safe),
    }


def _dml_state(safe):
    from . import whisper_onnx as wo
    if not safe(wo.directml_installed):
        return None
    if nvidia_gpu() and safe(gpu_libs_ready) and not safe(gpu_blocked):
        return None                        # NVIDIA's own (faster) path works
    return safe(wo.model_ready)


# ------------------------------------------------------------------ getting
def get(key: str, report: Report, cancel: Cancel, model: str = WHISPER_DEFAULT) -> None:
    {"whisper": lambda: get_whisper(report, cancel, model),
     "listen": lambda: _get_listen(report),
     "voices": lambda: _get_voices(report),
     "judge": lambda: _get_judge(report, cancel),
     "gpu": lambda: get_gpu_libs(report, cancel),
     "gpu_dml": lambda: get_dml_model(report, cancel)}[key]()


def _folder_size(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def get_whisper(report: Report, cancel: Cancel, model: str = WHISPER_DEFAULT) -> None:
    from .transcribe import import_whisper
    import_whisper()
    from faster_whisper.utils import download_model
    expected = {"large-v3-turbo": 1.62e9, "large-v3": 3.09e9, "medium": 1.53e9,
                "small": 0.48e9}.get(model, 1.6e9)
    folder = _whisper_folder(model)
    done = threading.Event()
    err: list[BaseException] = []

    def work():
        try:
            download_model(model)
        except BaseException as e:      # noqa: BLE001 - reported below
            err.append(e)
        finally:
            done.set()

    threading.Thread(target=work, daemon=True).start()
    while not done.wait(0.5):
        if cancel():
            raise Cancelled()      # the download thread finishes on its own
        have = _folder_size(folder)
        report(f"{have / 1e9:.2f} of {expected / 1e9:.1f} GB", min(0.99, have / expected))
    if err:
        raise err[0]


def _get_listen(report: Report) -> None:
    from . import listen

    def say(msg: str) -> None:
        m = re.search(r"(\d+)%", msg)
        report(msg, int(m.group(1)) / 100 if m else None)
    listen.model_files(say)


def _get_voices(report: Report) -> None:
    from . import speakers
    speakers.model_path(report=lambda m, f: report(m, f))


def _get_judge(report: Report, cancel: Cancel) -> None:
    from . import judge

    def say(msg: str) -> None:
        m = re.search(r"\((\d+)%\)", msg)
        report(msg, int(m.group(1)) / 100 if m else None)
    try:
        judge.download(say, should_cancel=cancel)
    except InterruptedError:
        raise Cancelled()


# ------------------------------------------------------------------ NVIDIA
def _version_key(v: str) -> tuple[int, ...] | None:
    if not re.fullmatch(r"\d+(\.\d+)*", v):      # skip pre-releases
        return None
    return tuple(int(p) for p in v.split("."))


def _pick_wheel(package: str, major: int | None, exact: str | None = None) -> dict:
    """The Windows x64 wheel of `package`: version `exact` when given (and
    available), otherwise the newest of that major version."""
    req = urllib.request.Request(f"https://pypi.org/pypi/{package}/json",
                                 headers={"User-Agent": "UbiClipper"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    best: tuple[tuple[int, ...], dict] | None = None
    for ver, files in data.get("releases", {}).items():
        key = _version_key(ver)
        if not key or (major is not None and key[0] != major):
            continue
        if exact and ver != exact and exact in data.get("releases", {}):
            continue
        for f in files:
            if (f.get("packagetype") == "bdist_wheel" and f["filename"].endswith("win_amd64.whl")
                    and not f.get("yanked")):
                if best is None or key > best[0]:
                    best = (key, f)
    if not best:
        raise RuntimeError(f"No Windows download found for {package}.")
    return best[1]


def _download(url: str, dest: str, size: int, sha256: str | None, label: str,
              report: Report, cancel: Cancel, base: float, share: float) -> None:
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    if have > size:
        os.remove(part)
        have = 0
    req = urllib.request.Request(url, headers={"User-Agent": "UbiClipper"})
    if have:
        req.add_header("Range", f"bytes={have}-")
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:
            have = 0
        with open(part, "ab" if have else "wb") as f:
            done, last = have, 0.0
            while True:
                if cancel():
                    raise Cancelled()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if time.monotonic() - last > 0.3:
                    last = time.monotonic()
                    report(f"{label}: {done / 1e6:.0f} of {size / 1e6:.0f} MB",
                           base + share * done / max(1, size))
    if sha256:
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        if h.hexdigest() != sha256:
            os.remove(part)
            raise RuntimeError(f"{label}: the download was damaged, please try again.")
    os.replace(part, dest)


def _extract_dlls(wheel: str, target_root: str) -> int:
    """Keep only nvidia/<pkg>/bin/*.dll from the wheel, as <target>/<pkg>/bin."""
    n = 0
    with zipfile.ZipFile(wheel) as z:
        for info in z.infolist():
            parts = info.filename.split("/")
            if (len(parts) == 4 and parts[0] == "nvidia" and parts[2] == "bin"
                    and parts[3].lower().endswith(".dll")):
                out_dir = os.path.join(target_root, parts[1], "bin")
                os.makedirs(out_dir, exist_ok=True)
                tmp = os.path.join(out_dir, parts[3] + ".part")
                with z.open(info) as src, open(tmp, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                os.replace(tmp, os.path.join(out_dir, parts[3]))
                n += 1
    return n


def get_gpu_libs(report: Report, cancel: Cancel) -> None:
    dl_dir = os.path.join(NVIDIA_DIR, "_downloads")
    os.makedirs(dl_dir, exist_ok=True)
    report("Looking up the NVIDIA libraries…", None)
    wheels = [(pkg, _pick_wheel(pkg, major, exact), dll)
              for pkg, major, exact, dll in NVIDIA_PACKAGES]
    total = sum(w["size"] for _, w, _ in wheels) or 1
    base = 0.0
    for pkg, w, dll in wheels:
        share = w["size"] / total
        if _have_dll(dll):
            base += share
            continue
        dest = os.path.join(dl_dir, w["filename"])
        label = pkg.replace("nvidia-", "").replace("-cu12", "")
        _download(w["url"], dest, w["size"], (w.get("digests") or {}).get("sha256"),
                  label, report, cancel, base, share)
        report(f"{label}: unpacking…", base + share)
        if not _extract_dlls(dest, NVIDIA_DIR):
            raise RuntimeError(f"{label}: no libraries found in the download.")
        os.remove(dest)
        base += share
    shutil.rmtree(dl_dir, ignore_errors=True)
    from . import transcribe
    transcribe._cuda_prepared = False       # pick up the new folders
    reason = transcribe.gpu_block_reason()
    if reason:
        raise RuntimeError(reason)
    report("GPU speed-up ready", 1.0)


# ------------------------------------------------------------------ DirectML model
def get_dml_model(report: Report, cancel: Cancel) -> None:
    """The ONNX Whisper model for DirectML, from UbiClipper's GitHub release,
    then a one-time test that this graphics card can run it."""
    from . import whisper_onnx as wo
    os.makedirs(wo.MODEL_DIR, exist_ok=True)
    report("Looking up the GPU speech model…", None)
    sizes = {}
    for f in wo.MODEL_FILES:
        req = urllib.request.Request(wo.MODEL_URL.format(file=f), method="HEAD",
                                     headers={"User-Agent": "UbiClipper"})
        with urllib.request.urlopen(req, timeout=60) as r:
            sizes[f] = int(r.headers.get("Content-Length") or 0)
    total = sum(sizes.values()) or 1
    base = 0.0
    for f in wo.MODEL_FILES:
        dest = os.path.join(wo.MODEL_DIR, f)
        share = sizes[f] / total
        if not (os.path.isfile(dest) and os.path.getsize(dest) == sizes[f]):
            _download(wo.MODEL_URL.format(file=f), dest, sizes[f], None, f, report, cancel,
                      base, share)
        base += share
    report("Testing the graphics card (once, up to a minute)…", None)
    ok, why = wo.dml_status()
    if not ok:
        raise RuntimeError(f"This graphics card can't run it ({why}); subtitles use the "
                           "processor.")
    report("GPU speech model ready", 1.0)
