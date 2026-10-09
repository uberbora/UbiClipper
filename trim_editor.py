"""Trim editor: fine-tune where a clip starts and ends.

Shows the sound around the clip (waveform) with the moment's score curve,
two handles to drag, exact time fields with nudge buttons, and quick
previews of the whole clip, its first and its last seconds.

Keys: ← / → move the last-used handle 0.1 s (Shift: 1 s).
"""

from __future__ import annotations

import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np

import theme

MAX_CLIP = 600.0        # trimming may go beyond the analysis' max length


def fmt(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:04.1f}"


def parse(text: str) -> float | None:
    """'1:02:10.5', '62:10', '3730.5' -> seconds."""
    text = text.strip().replace(",", ".")
    if not re.fullmatch(r"[\d:.]+", text or "x"):
        return None
    try:
        parts = [float(p) for p in text.split(":")]
    except ValueError:
        return None
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


class TrimEditor(tk.Toplevel):
    def __init__(self, app, clip, result, on_save) -> None:
        super().__init__(app)
        self.app, self.clip, self.result, self.on_save = app, clip, result, on_save
        self.title("Trim clip")
        self.geometry("980x470")
        self.minsize(720, 420)
        self.transient(app)
        self.total = float(result.info.duration or (len(result.timeline.combined)
                                                    * result.timeline.hop))
        self.start, self.end = float(clip.start), float(clip.end)
        self.orig = (self.start, self.end)
        self.pad = max(20.0, 0.6 * (self.end - self.start))
        self.active = "start"
        self.drag: str | None = None
        self.env: np.ndarray | None = None
        self._loading = False

        body = ttk.Frame(self, style="Card.TFrame", padding=16)
        body.pack(fill="both", expand=True)
        head = ttk.Frame(body, style="Card.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Trim clip", style="H2.TLabel").pack(side="left")
        ttk.Label(head, text="Drag the two handles, or type exact times. "
                             "←/→ nudge 0.1 s, Shift+←/→ 1 s.",
                  style="CardMuted.TLabel").pack(side="left", padx=12)
        ttk.Button(head, text="Show more around", style="Small.TButton",
                   command=self.zoom_out).pack(side="right")
        ttk.Button(head, text="Zoom in", style="Small.TButton",
                   command=self.zoom_in).pack(side="right", padx=6)

        self.cv = tk.Canvas(body, height=210, highlightthickness=0, cursor="sb_h_double_arrow")
        self.cv.pack(fill="both", expand=True, pady=(12, 10))
        self.cv.bind("<Configure>", lambda e: self.draw())
        self.cv.bind("<Button-1>", self._press)
        self.cv.bind("<B1-Motion>", self._move)
        self.cv.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", None))

        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x")
        self.v_start, self.v_end = tk.StringVar(), tk.StringVar()
        for label, var, which in (("Start", self.v_start, "start"), ("End", self.v_end, "end")):
            box = ttk.Frame(row, style="Card.TFrame")
            box.pack(side="left", padx=(0, 22))
            ttk.Label(box, text=label, style="Card.TLabel").pack(side="left", padx=(0, 6))
            for d, txt in ((-1.0, "−1s"), (-0.1, "−0.1")):
                ttk.Button(box, text=txt, style="Small.TButton", width=4,
                           command=lambda d=d, w=which: self.nudge(w, d)).pack(side="left")
            e = ttk.Entry(box, textvariable=var, width=11, justify="center")
            e.pack(side="left", padx=4)
            e.bind("<Return>", lambda ev, w=which: self._typed(w))
            e.bind("<FocusOut>", lambda ev, w=which: self._typed(w))
            for d, txt in ((0.1, "+0.1"), (1.0, "+1s")):
                ttk.Button(box, text=txt, style="Small.TButton", width=4,
                           command=lambda d=d, w=which: self.nudge(w, d)).pack(side="left")
        self.len_lbl = ttk.Label(row, text="", style="Card.TLabel")
        self.len_lbl.pack(side="left")

        acts = ttk.Frame(body, style="Card.TFrame")
        acts.pack(fill="x", pady=(14, 0))
        ttk.Button(acts, text="▶  Play clip",
                   command=lambda: self.play(self.start, self.end)).pack(side="left")
        ttk.Button(acts, text="▶  First 5 s",
                   command=lambda: self.play(self.start, min(self.end, self.start + 5))
                   ).pack(side="left", padx=6)
        ttk.Button(acts, text="▶  Last 5 s",
                   command=lambda: self.play(max(self.start, self.end - 5), self.end)
                   ).pack(side="left")
        ttk.Button(acts, text="Save", style="Accent.TButton",
                   command=self.save).pack(side="right")
        ttk.Button(acts, text="Cancel", command=self.destroy).pack(side="right", padx=8)
        ttk.Button(acts, text="Reset", command=self.reset).pack(side="right")

        self.bind("<Left>", lambda e: self.nudge(self.active, -0.1))
        self.bind("<Right>", lambda e: self.nudge(self.active, 0.1))
        self.bind("<Shift-Left>", lambda e: self.nudge(self.active, -1.0))
        self.bind("<Shift-Right>", lambda e: self.nudge(self.active, 1.0))
        self.bind("<Escape>", lambda e: self.destroy())
        theme.on_change(lambda p: self.draw() if self.winfo_exists() else None)
        self._sync()
        self.load_audio()

    # ------------------------------------------------------------ view
    @property
    def view(self) -> tuple[float, float]:
        a = max(0.0, self.start - self.pad)
        b = min(self.total, self.end + self.pad)
        return a, max(b, a + 1.0)

    def x_of(self, t: float) -> float:
        a, b = self.view
        return 10 + (t - a) / (b - a) * (self.cv.winfo_width() - 20)

    def t_of(self, x: float) -> float:
        a, b = self.view
        return a + (x - 10) / max(1, self.cv.winfo_width() - 20) * (b - a)

    def zoom_out(self) -> None:
        self.pad = min(self.pad * 2, 600.0)
        self.load_audio()

    def zoom_in(self) -> None:
        self.pad = max(3.0, self.pad / 2)
        self.load_audio()

    # ------------------------------------------------------------ audio
    def load_audio(self) -> None:
        """Waveform of the view window (decoded in the background)."""
        if self._loading:
            return
        self._loading = True
        a, b = self.view
        self._env_view = (a, b)
        path = self.app.video
        track = self.result.settings.audio_track

        def work():
            env = None
            try:
                from clipper.media import stream_audio
                chunks = list(stream_audio(path, track=track, start=a, duration=b - a))
                audio = np.concatenate(chunks) if chunks else np.zeros(1, np.float32)
                n = 800
                step = max(1, len(audio) // n)
                frames = audio[: step * (len(audio) // step)].reshape(-1, step)
                env = np.sqrt((frames ** 2).mean(1)) if len(frames) else None
            except Exception:
                env = None
            self.after(0, lambda: self._loaded(env))
        threading.Thread(target=work, daemon=True).start()
        self.draw()

    def _loaded(self, env) -> None:
        self._loading = False
        if not self.winfo_exists():
            return
        self.env = env
        if self._env_view != self.view:     # handles moved far while loading
            self.load_audio()
        self.draw()

    # ------------------------------------------------------------ drawing
    def draw(self) -> None:
        cv = self.cv
        if not cv.winfo_exists():
            return
        p = theme.current
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 50:
            return
        cv.delete("all")
        cv.configure(background=p["input"])
        a, b = self.view
        mid = H * 0.55
        # outside the clip is darker (drawn first, under everything)
        xs0, xe0 = self.x_of(self.start), self.x_of(self.end)
        for x0, x1 in ((0, xs0), (xe0, W)):
            if x1 > x0:
                cv.create_rectangle(x0, 0, x1, H, fill=p["bg"], width=0)
        # waveform (dB-ish so quiet talk is visible next to screams)
        if self.env is not None and len(self.env):
            ea, eb = self._env_view
            db = 20 * np.log10(self.env + 1e-5)
            lvl = np.clip((db + 60) / 60, 0, 1)
            for i, v in enumerate(lvl):
                t = ea + (i + 0.5) / len(lvl) * (eb - ea)
                if t < a or t > b:
                    continue
                x = self.x_of(t)
                h = 4 + v * (H * 0.42)
                inside = self.start <= t <= self.end
                cv.create_line(x, mid - h, x, mid + h * 0.6,
                               fill=p["text"] if inside else p["muted"])
        else:
            cv.create_text(W / 2, mid, text="Loading sound…", fill=p["muted"])
        # score curve from the analysis
        tl = self.result.timeline
        if tl is not None and len(tl.combined):
            i0, i1 = int(a / tl.hop), int(b / tl.hop) + 1
            seg = tl.combined[i0:i1]
            if len(seg) > 1:
                top = max(float(tl.combined.max()), 1e-6)
                pts = []
                for k, v in enumerate(seg):
                    pts += [self.x_of((i0 + k + 0.5) * tl.hop), 12 + (1 - v / top) * (H * 0.35)]
                cv.create_line(*pts, fill=p["accent"], width=2, smooth=True)
        xs, xe = self.x_of(self.start), self.x_of(self.end)
        # peak marker
        xp = self.x_of(self.clip.peak)
        cv.create_polygon(xp - 6, 2, xp + 6, 2, xp, 11, fill=p["warn"], outline="")
        # handles
        for x, which in ((xs, "start"), (xe, "end")):
            col = p["accent"] if which == self.active else p["text"]
            cv.create_line(x, 0, x, H, fill=col, width=3)
            cv.create_rectangle(x - 7, H / 2 - 18, x + 7, H / 2 + 18, fill=col, outline="")
        # ruler
        span = b - a
        step = next(s for s in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600) if span / s <= 12)
        t = np.ceil(a / step) * step
        while t <= b:
            x = self.x_of(t)
            cv.create_line(x, H - 24, x, H - 17, fill=p["muted"])
            cv.create_text(x, H - 15, text=fmt(t)[:-2], anchor="n", fill=p["muted"],
                           font=(theme._family(self), 8))
            t += step

    # ------------------------------------------------------------ editing
    def _press(self, e) -> None:
        xs, xe = self.x_of(self.start), self.x_of(self.end)
        self.drag = "start" if abs(e.x - xs) <= abs(e.x - xe) else "end"
        self.active = self.drag
        self._move(e)

    def _move(self, e) -> None:
        if not self.drag:
            return
        t = max(0.0, min(self.total, self.t_of(e.x)))
        self.set(self.drag, round(t, 1), redraw_audio=False)

    def set(self, which: str, t: float, redraw_audio: bool = True) -> None:
        if which == "start":
            self.start = max(0.0, min(t, self.end - 1.0))
        else:
            self.end = min(self.total, max(t, self.start + 1.0))
        self.active = which
        self._sync()
        a, b = getattr(self, "_env_view", self.view)
        if redraw_audio and (self.start < a or self.end > b):
            self.load_audio()
        self.draw()

    def nudge(self, which: str, d: float) -> None:
        self.set(which, round((self.start if which == "start" else self.end) + d, 1))

    def _typed(self, which: str) -> None:
        var = self.v_start if which == "start" else self.v_end
        t = parse(var.get())
        if t is None:
            self._sync()
            return
        self.set(which, t)

    def _sync(self) -> None:
        self.v_start.set(fmt(self.start))
        self.v_end.set(fmt(self.end))
        n = self.end - self.start
        warn = "  ⚠ over 60 s" if n > 60 else ""
        self.len_lbl.config(text=f"Length {n:.1f} s{warn}")

    def reset(self) -> None:
        self.start, self.end = self.orig
        self._sync()
        self.draw()

    def play(self, a: float, b: float) -> None:
        self.app.preview_range(a, b, "trim")

    def save(self) -> None:
        if self.end - self.start > MAX_CLIP:
            messagebox.showinfo("UbiClipper", "A clip can be at most 10 minutes long.",
                                parent=self)
            return
        c = self.clip
        changed = (round(c.start, 2), round(c.end, 2)) != (round(self.start, 2), round(self.end, 2))
        if changed and (c.transcript or {}).get("edited") and not messagebox.askyesno(
                "UbiClipper", "Trimming makes new subtitles for this clip, so your "
                              "subtitle edits for it are lost. Trim anyway?", parent=self):
            return
        if changed:
            c.start, c.end = round(self.start, 2), round(self.end, 2)
            c.peak = min(max(c.peak, c.start), c.end)
            c.transcript = None        # new range: subtitles are made fresh on export
            c.align_shift = None
        self.destroy()
        self.on_save(c)
