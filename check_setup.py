"""Check that everything UbiClipper needs is installed and loadable.

Double-click check_setup.bat (or run: python check_setup.py) and send the
output if something isn't working.
"""

from __future__ import annotations

import glob
import os
import platform
import shutil
import subprocess
import sys
import sysconfig

OK, WARN, BAD = "  [OK]  ", "  [!!]  ", "  [XX]  "
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
problems = 0


def line(tag: str, text: str) -> None:
    global problems
    if tag == BAD:
        problems += 1
    print(f"{tag}{text}", flush=True)


def try_import(name: str):
    try:
        mod = __import__(name)
        return mod, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def main() -> int:
    from clipper import __version__, bootstrap
    bootstrap.setup()
    print(f"UbiClipper {__version__} setup check\n")
    line(OK, f"Python {platform.python_version()} at {sys.executable}")
    if bootstrap.installed():
        line(OK, f"Installed app in {bootstrap.APP_DIR}")

    # ---------------------------------------------------------------- ffmpeg
    ff = shutil.which("ffmpeg")
    if not ff or not shutil.which("ffprobe"):
        line(BAD, "ffmpeg/ffprobe not found (reinstall UbiClipper, or for the source "
                  "version: winget install Gyan.FFmpeg)")
    else:
        ver = subprocess.run([ff, "-version"], capture_output=True, text=True).stdout.split("\n")[0]
        filters = subprocess.run([ff, "-hide_banner", "-filters"],
                                 capture_output=True, text=True).stdout
        line(OK, ver[:70])
        line(OK if " ass " in filters else BAD,
             "ffmpeg can burn subtitles (libass)" if " ass " in filters
             else "this ffmpeg build has no libass - install the Gyan full build")

    # ---------------------------------------------------------------- python packages
    np_, err = try_import("numpy")
    line(OK if np_ else BAD, f"numpy {getattr(np_, '__version__', '')}" if np_ else f"numpy: {err}")

    # PyAV is never loaded: UbiClipper doesn't need it, and on Windows 11 with
    # Smart App Control even trying pops up a "part of this app was blocked" box.
    line(OK, "PyAV: not needed, skipped (FFmpeg decodes the audio)")

    ct2, err = try_import("ctranslate2")
    line(OK if ct2 else BAD, f"ctranslate2 {getattr(ct2, '__version__', '')}" if ct2 else f"ctranslate2: {err}")
    if ct2:
        try:
            ver = tuple(int(x) for x in ct2.__version__.split(".")[:3])
        except ValueError:
            ver = (0,)
        if ver < (4, 6, 2):
            line(WARN, "ctranslate2 is too old for the AI judge (needs 4.6.2+). "
                       "Install the latest UbiClipper.")
    tk_, err = try_import("tokenizers")
    line(OK if tk_ else WARN, f"tokenizers {getattr(tk_, '__version__', '')} (AI judge)"
         if tk_ else f"tokenizers: {err} (AI judge unavailable)")
    ort, err = try_import("onnxruntime")
    line(OK if ort else BAD,
         f"onnxruntime {getattr(ort, '__version__', '')} (voice detection)" if ort else f"onnxruntime: {err}")

    from clipper.transcribe import gpu_status, import_whisper, WhisperMissing
    try:
        fw, _ = import_whisper()
        line(OK, f"faster-whisper {getattr(fw, '__version__', '')} loads")
    except WhisperMissing as e:
        line(BAD, str(e).replace("\n", " "))

    # ---------------------------------------------------------------- GPU
    smi = shutil.which("nvidia-smi")
    if smi:
        out = subprocess.run([smi, "--query-gpu=name,driver_version,memory.total",
                              "--format=csv,noheader"], capture_output=True, text=True)
        line(OK, f"NVIDIA GPU: {out.stdout.strip() or 'present'}")
    else:
        line(WARN, "nvidia-smi not found (no NVIDIA GPU or driver)")
    usable, why = gpu_status()
    line(OK if usable else WARN, f"GPU subtitles: {why}")

    # ---------------------------------------------------------------- models
    from clipper import getready
    st = getready.status()
    for it in getready.ITEMS:
        ready = st[it.key]
        if ready is None:
            continue
        line(OK if ready else WARN, f"{it.name}: " + ("downloaded" if ready else
             "not downloaded yet (Settings → All AI downloads)"))
    tkm, err = try_import("tkinter")
    line(OK if tkm else BAD, "tkinter (the app window)" if tkm else f"tkinter: {err}")

    # ---------------------------------------------------------------- blocked DLLs
    site = sysconfig.get_paths()["purelib"]
    hits = glob.glob(os.path.join(site, "*", "libstdc++-6*.dll"))
    if hits:
        print("\nUnsigned DLLs found (Smart App Control may block these; UbiClipper "
              "doesn't load them, so this is only for information):")
        for h in hits:
            print(f"        {os.path.basename(os.path.dirname(h))}\\{os.path.basename(h)}")

    print("\nDone." if not problems else f"\n{problems} problem(s) found.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
