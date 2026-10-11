"""The "Get UbiClipper ready" window: downloads the AI models (and the NVIDIA
GPU speed-up) with progress. Opens by itself on the first start and from
Settings → AI models."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from clipper import getready

READY, MISSING, NA = "✓ Ready", "Not downloaded", "No NVIDIA card found: subtitles use the processor"
BLOCKED = "Blocked by Windows' Smart App Control: use the GPU speech model below"
NOT_NEEDED_DML = "Not needed on this PC"


class ReadyWindow(tk.Toplevel):
    def __init__(self, app, model: str = getready.WHISPER_DEFAULT, on_close=None) -> None:
        super().__init__(app)
        self.app, self.model, self.on_close = app, model, on_close
        self.title("Get UbiClipper ready")
        self.resizable(False, False)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.stop = threading.Event()
        self.running = False
        self.state = getready.status(model)

        body = ttk.Frame(self, style="Card.TFrame", padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Get UbiClipper ready", style="H2.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(body, text="UbiClipper's AI runs on your PC, for free. It needs these "
                             "files once; afterwards everything works offline.",
                  style="CardMuted.TLabel", wraplength=520, justify="left").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 14))
        self.vars: dict[str, tk.BooleanVar] = {}
        self.labels: dict[str, ttk.Label] = {}
        self.checks: dict[str, ttk.Checkbutton] = {}
        r = 2
        for it in getready.ITEMS:
            ready = self.state[it.key]
            v = tk.BooleanVar(value=ready is False)
            self.vars[it.key] = v
            cb = ttk.Checkbutton(body, text=it.name, variable=v)
            cb.grid(row=r, column=0, sticky="w", pady=3)
            self.checks[it.key] = cb
            if ready is not False or it.required:
                cb.state(["disabled"])
            ttk.Label(body, text=it.size, style="CardMuted.TLabel").grid(
                row=r, column=1, sticky="e", padx=(16, 16))
            lbl = ttk.Label(body, text="", style="Card.TLabel", wraplength=230, justify="left")
            lbl.grid(row=r, column=2, sticky="w")
            self.labels[it.key] = lbl
            self._show(it.key)
            r += 1
        ttk.Label(body, text="The AI judge and the GPU speed-up are optional but "
                             "recommended: better picks and much faster subtitles.",
                  style="CardMuted.TLabel", wraplength=520, justify="left").grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.bar = ttk.Progressbar(body, length=520, maximum=1.0)
        self.bar.grid(row=r + 1, column=0, columnspan=3, sticky="we", pady=(16, 4))
        self.msg = ttk.Label(body, text="", style="CardMuted.TLabel", wraplength=520)
        self.msg.grid(row=r + 2, column=0, columnspan=3, sticky="w")
        btns = ttk.Frame(body, style="Card.TFrame")
        btns.grid(row=r + 3, column=0, columnspan=3, sticky="e", pady=(16, 0))
        self.go_btn = ttk.Button(btns, text="Download", style="Accent.TButton",
                                 command=self.start)
        self.go_btn.pack(side="left")
        self.later_btn = ttk.Button(btns, text="Later", command=self.close)
        self.later_btn.pack(side="left", padx=(6, 0))
        self._refresh_button()
        self.bind("<Escape>", lambda e: self.close())

    # ------------------------------------------------------------ display
    def _show(self, key: str, text: str | None = None, color: str | None = None) -> None:
        import theme
        p = theme.current
        ready = self.state[key]
        if text is None:
            text = READY if ready else (self._na(key) if ready is None else MISSING)
        if color is None:
            color = p["ok"] if ready else p["muted"]
        self.labels[key].config(text=text, foreground=color)

    @staticmethod
    def _na(key: str) -> str:
        if key == "gpu_dml":
            return NOT_NEEDED_DML
        if key == "gpu" and getready.nvidia_gpu():
            return BLOCKED
        return NA

    def _todo(self) -> list[str]:
        return [it.key for it in getready.ITEMS
                if self.state[it.key] is False and self.vars[it.key].get()]

    def _refresh_button(self) -> None:
        if not self._todo():
            self.go_btn.config(text="Close", command=self.close)
            self.later_btn.pack_forget()
            if not self.running:
                self.msg.config(text="All set. Enjoy!" if all(
                    v is not False for v in self.state.values()) else "")

    # ------------------------------------------------------------ work
    def start(self) -> None:
        todo = self._todo()
        if not todo:
            return self.close()
        self.running = True
        self.stop.clear()
        self.go_btn.state(["disabled"])
        self.later_btn.config(text="Stop", command=self.stop.set)
        for cb in self.checks.values():
            cb.state(["disabled"])
        threading.Thread(target=self._work, args=(todo,), daemon=True).start()

    def _work(self, todo: list[str]) -> None:
        n = len(todo)
        failed = []
        for i, key in enumerate(todo):
            if self.stop.is_set():
                break
            self._ui(lambda k=key: self._show(k, "Downloading…", None))

            def report(text, frac, i=i, key=key):
                overall = (i + (frac or 0)) / n
                self._ui(lambda: (self.bar.config(value=overall),
                                  self.msg.config(text=text),
                                  self._show(key, f"{int(100 * frac)}%" if frac else
                                             "Downloading…", None)))
            try:
                getready.get(key, report, self.stop.is_set, self.model)
                self.state[key] = True
                self._ui(lambda k=key: self._show(k))
            except getready.Cancelled:
                self._ui(lambda k=key: self._show(k, "Stopped", None))
                break
            except Exception as e:      # noqa: BLE001 - shown to the user
                if key == "gpu" and getready.gpu_blocked():
                    self.state[key] = None   # downloaded, but Windows won't load it
                    self._ui(lambda k=key: self._show(k))
                    continue
                failed.append(key)
                err = str(e)[:160]
                self._ui(lambda k=key, err=err: self._show(k, "Failed: " + err, "#E5484D"))
        self._ui(lambda: self._finished(failed))

    def _finished(self, failed: list[str]) -> None:
        self.running = False
        self.bar.config(value=1.0 if not failed and not self.stop.is_set() else self.bar["value"])
        self.go_btn.state(["!disabled"])
        self.later_btn.config(text="Later", command=self.close)
        if failed:
            self.msg.config(text="Some downloads failed. Check your internet connection and "
                                 "press Try again; finished parts are kept.")
            self.go_btn.config(text="Try again", command=self.start)
        elif self.stop.is_set():
            self.msg.config(text="Stopped. Finished parts are kept; Continue picks up "
                                 "where it stopped.")
            self.go_btn.config(text="Continue", command=self.start)
        else:
            self._refresh_button()

    def _ui(self, fn) -> None:
        try:
            self.after(0, fn)
        except (RuntimeError, tk.TclError):
            pass

    def close(self) -> None:
        self.stop.set()
        cb = self.on_close
        self.destroy()
        if cb:
            cb()
