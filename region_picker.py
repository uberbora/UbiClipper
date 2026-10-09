"""Window for marking an area of the video: drag a box over a frame.

Used for the webcam area and the main (gameplay / camera) area. For the main
area the box is locked to the shape it will be shown at, so what you draw is
exactly what ends up in the 9:16 clip. Drag inside an existing box to move it.
"""

from __future__ import annotations

import os
import random
import tempfile
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from clipper.reframe import Region, grab_frame


# ------------------------------------------------------------ geometry (testable)
def box_from_drag(x0: float, y0: float, x1: float, y1: float, W: float, H: float,
                  aspect: float | None) -> tuple[float, float, float, float]:
    """Box from a drag (start -> current), optionally with a fixed width/height
    ratio, kept inside the W x H image."""
    x1, y1 = max(0, min(x1, W)), max(0, min(y1, H))
    if not aspect:
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    sx = 1 if x1 >= x0 else -1
    sy = 1 if y1 >= y0 else -1
    w = abs(x1 - x0)
    h = abs(y1 - y0)
    # follow whichever direction the mouse moved further, keep the ratio
    if w / max(h, 1e-6) > aspect:
        h = w / aspect
    else:
        w = h * aspect
    # don't run off the image
    max_w = (W - x0) if sx > 0 else x0
    max_h = (H - y0) if sy > 0 else y0
    scale = min(1.0, max_w / max(w, 1e-6), max_h / max(h, 1e-6))
    w, h = w * scale, h * scale
    xa, ya = x0 + sx * w, y0 + sy * h
    return min(x0, xa), min(y0, ya), max(x0, xa), max(y0, ya)


def move_box(box: tuple[float, float, float, float], dx: float, dy: float,
             W: float, H: float) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = box
    dx = max(-x0, min(dx, W - x1))
    dy = max(-y0, min(dy, H - y1))
    return x0 + dx, y0 + dy, x1 + dx, y1 + dy


def fit_aspect(box: tuple[float, float, float, float], aspect: float | None,
               W: float, H: float) -> tuple[float, float, float, float]:
    """Reshape a saved box to the required ratio around its centre."""
    if not aspect:
        return box
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = x1 - x0, y1 - y0
    if w / max(h, 1e-6) > aspect:
        w = h * aspect
    else:
        h = w / aspect
    w, h = min(w, W, H * aspect), min(h, H, W / aspect)
    x0 = max(0, min(cx - w / 2, W - w))
    y0 = max(0, min(cy - h / 2, H - h))
    return x0, y0, x0 + w, y0 + h


# ------------------------------------------------------------ window
class RegionPicker(tk.Toplevel):
    def __init__(self, master: tk.Misc, video: str, duration: float,
                 initial: Region | None, on_save: Callable[[Region], None],
                 title: str = "Set webcam area", label: str = "WEBCAM",
                 hint: str = "Drag a box around your webcam, then click Save. "
                             "Tip: keep it tight to the camera, without the frame/border.",
                 color: str = "#00e676", aspect: float | None = None,
                 reference: tuple[Region, str] | None = None) -> None:
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.video, self.duration, self.on_save = video, max(duration, 1.0), on_save
        self.label, self.color, self.aspect, self.reference = label, color, aspect, reference
        self.png = os.path.join(tempfile.gettempdir(), "ubiclipper_frame.png")
        self.start: tuple[float, float] | None = None
        self.moving: tuple[float, float, tuple] | None = None
        self.box: tuple[float, float, float, float] | None = None

        ttk.Label(self, text=hint, padding=(10, 8), wraplength=900).pack(anchor="w")
        self.canvas = tk.Canvas(self, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(padx=10)
        self.size_lbl = ttk.Label(self, text="", padding=(10, 4))
        self.size_lbl.pack(anchor="w")
        bar = ttk.Frame(self, padding=10)
        bar.pack(fill="x")
        ttk.Button(bar, text="Show another frame", command=lambda: self.new_frame()).pack(side="left")
        ttk.Button(bar, text="Whole frame", command=self._whole).pack(side="left", padx=6)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Save", command=self.save).pack(side="right", padx=6)

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)

        if not self.new_frame(at=min(self.duration * 0.3, 600)):
            self.destroy()
            return
        if initial:
            w, h = self.img.width(), self.img.height()
            self.box = fit_aspect((initial.x * w, initial.y * h,
                                   (initial.x + initial.w) * w, (initial.y + initial.h) * h),
                                  self.aspect, w, h)
            self._draw()
        self.after(150, self._modal)

    def _modal(self) -> None:
        try:
            self.grab_set()
        except tk.TclError:
            pass  # window not viewable yet on some systems; non-modal is fine

    def new_frame(self, at: float | None = None) -> bool:
        at = random.uniform(0.05, 0.95) * self.duration if at is None else at
        try:
            grab_frame(self.video, self.png, at)
        except Exception as e:
            messagebox.showerror("UbiClipper", str(e), parent=self)
            return False
        self.img = tk.PhotoImage(file=self.png)
        self.canvas.config(width=self.img.width(), height=self.img.height())
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.img)
        self._draw()
        return True

    # ------------------------------------------------------------ mouse
    def _inside(self, x: float, y: float) -> bool:
        return bool(self.box) and self.box[0] <= x <= self.box[2] and self.box[1] <= y <= self.box[3]

    def _press(self, e) -> None:
        if self._inside(e.x, e.y):
            self.moving = (e.x, e.y, self.box)
            self.start = None
        else:
            self.moving = None
            self.start = (e.x, e.y)

    def _drag(self, e) -> None:
        W, H = self.img.width(), self.img.height()
        if self.moving:
            mx, my, orig = self.moving
            self.box = move_box(orig, e.x - mx, e.y - my, W, H)
        elif self.start:
            self.box = box_from_drag(self.start[0], self.start[1], e.x, e.y, W, H, self.aspect)
        self._draw()

    def _release(self, e) -> None:
        self._drag(e)
        self.start = self.moving = None

    def _whole(self) -> None:
        W, H = self.img.width(), self.img.height()
        self.box = fit_aspect((0, 0, W, H), self.aspect, W, H)
        self._draw()

    def _draw(self) -> None:
        self.canvas.delete("box")
        W, H = self.img.width(), self.img.height()
        if self.reference:  # the other area, faint, for orientation
            r, name = self.reference
            self.canvas.create_rectangle(r.x * W, r.y * H, (r.x + r.w) * W, (r.y + r.h) * H,
                                         outline="#ffffff", dash=(4, 3), width=1, tags="box")
            self.canvas.create_text(r.x * W + 4, r.y * H + 4, anchor="nw", text=name,
                                    fill="#ffffff", font=("Arial", 9), tags="box")
        if not self.box:
            return
        x0, y0, x1, y1 = self.box
        self.canvas.create_rectangle(x0, y0, x1, y1, outline=self.color, width=3, tags="box")
        self.canvas.create_text(x0 + 6, y0 + 6, anchor="nw", text=self.label,
                                fill=self.color, font=("Arial", 12, "bold"), tags="box")
        self.size_lbl.config(text=f"{(x1 - x0) / W:.0%} × {(y1 - y0) / H:.0%} of the frame"
                                  + ("  (shape locked to the 9:16 layout; drag inside to move)"
                                     if self.aspect else "  (drag inside the box to move it)"))

    def save(self) -> None:
        if not self.box or self.box[2] - self.box[0] < 10 or self.box[3] - self.box[1] < 10:
            messagebox.showinfo("UbiClipper", "Drag a box first.", parent=self)
            return
        W, H = self.img.width(), self.img.height()
        x0, y0, x1, y1 = self.box
        self.on_save(Region(x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H))
        self.destroy()


def WebcamPicker(master, video, duration, initial, on_save):  # noqa: N802 (old name)
    return RegionPicker(master, video, duration, initial, on_save)
