"""Start-up fixes so UbiClipper behaves like a normal installed Windows app.

Called once, first thing, by app.py:

* FFmpeg shipped with the installer (``<app>/ffmpeg``) is found before any
  FFmpeg on the PATH, for us and for yt-dlp.
* Started without a console (pythonw.exe from the Start menu), tools such as
  FFmpeg would each flash a black window: child processes get
  CREATE_NO_WINDOW instead. Output that would go to the missing console is
  written to ``~/.ubiclipper/logs/ubiclipper.log`` (useful for bug reports).
* Windows groups the taskbar button under UbiClipper's own icon instead of
  Python's.
"""

from __future__ import annotations

import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".ubiclipper")
LOG_DIR = os.path.join(CONFIG_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "ubiclipper.log")
APP_ID = "UbiClipper.App"
ICON_ICO = os.path.join(APP_DIR, "assets", "ubiclipper.ico")
ICON_PNG = os.path.join(APP_DIR, "assets", "icon64.png")

_done = False


def ffmpeg_dir() -> str | None:
    """The FFmpeg folder shipped with the installer, if any."""
    for d in (os.path.join(APP_DIR, "ffmpeg", "bin"), os.path.join(APP_DIR, "ffmpeg")):
        exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        if os.path.isfile(os.path.join(d, exe)):
            return d
    return None


def installed() -> bool:
    """True when running from the installer / portable build (bundled Python)."""
    return os.path.isfile(os.path.join(APP_DIR, "ubiclipper.build"))


def _log_to_file() -> None:
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 2_000_000:
            os.replace(LOG_FILE, LOG_FILE + ".old")
        f = open(LOG_FILE, "a", encoding="utf-8", buffering=1, errors="replace")
    except OSError:
        f = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = f
    if sys.stderr is None:
        sys.stderr = f


def _hide_child_consoles() -> None:
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    original = subprocess.Popen.__init__
    if getattr(original, "_ubiclipper", False):
        return

    def __init__(self, *args, **kwargs):
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = flag
        original(self, *args, **kwargs)

    __init__._ubiclipper = True
    subprocess.Popen.__init__ = __init__


def setup() -> None:
    global _done
    if _done:
        return
    _done = True
    _log_to_file()
    d = ffmpeg_dir()
    if d:
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    if sys.platform == "win32":
        # pythonw.exe has no console of its own
        no_console = os.path.basename(sys.executable).lower().startswith("pythonw")
        if no_console:
            _hide_child_consoles()
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass


def set_window_icon(root) -> None:
    """Give a Tk window UbiClipper's icon (title bar, taskbar, Alt+Tab)."""
    try:
        if sys.platform == "win32" and os.path.isfile(ICON_ICO):
            root.iconbitmap(default=ICON_ICO)
        elif os.path.isfile(ICON_PNG):
            import tkinter as tk
            root._ubi_icon = tk.PhotoImage(file=ICON_PNG)
            root.iconphoto(True, root._ubi_icon)
    except Exception:
        pass
