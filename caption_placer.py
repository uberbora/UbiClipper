"""Place the subtitles on the 9:16 screen by hand.

Shows a real frame of your 9:16 layout. Drag the sample caption to where you
want the subtitles. Pick TikTok, Instagram Reels or YouTube Shorts to see
outlines of where that app puts its buttons, username, follow/subscribe
button and caption, so the subtitles don't end up hidden behind them. The
outlines are approximate (apps change their layout now and then, and phones
differ), so keep a little distance.

"Check with real subtitles" renders the frame with the actual subtitle
style at that spot.
"""

from __future__ import annotations

import os
import tempfile
import threading
import tkinter as tk
from tkinter import ttk

import theme

W, H = 405, 720            # preview size (9:16)

# Areas covered by each app's buttons and texts, as fractions of the 9:16
# screen (x0, y0, x1, y1). Approximate: measured on typical phones.
TEMPLATES: dict[str, list[tuple[tuple[float, float, float, float], str]]] = {
    "TikTok": [
        ((0.00, 0.00, 1.00, 0.08), "Top tabs"),
        ((0.83, 0.38, 1.00, 0.82), "Like · comment · share"),
        ((0.00, 0.80, 0.83, 1.00), "Username · caption · sound"),
    ],
    "Instagram Reels": [
        ((0.00, 0.00, 1.00, 0.08), "Reels header"),
        ((0.85, 0.55, 1.00, 0.90), "Like · comment · share"),
        ((0.00, 0.78, 0.85, 1.00), "Username · Follow · caption"),
    ],
    "YouTube Shorts": [
        ((0.00, 0.00, 1.00, 0.08), "Search · menu"),
        ((0.84, 0.48, 1.00, 0.86), "Like · comment · share"),
        ((0.00, 0.80, 0.84, 1.00), "Channel · Subscribe · title"),
    ],
}
NONE = "None"


class CaptionPlacer(tk.Toplevel):
    def __init__(self, app, frame_video: str | None, at: float, on_save) -> None:
        super().__init__(app)
        self.app, self.on_save = app, on_save
        self.title("Place subtitles")
        self.resizable(False, False)
        self.transient(app)
        st = app.style_
        self.x = st.custom_x if st.placement == "custom" else 0.5
        self.y = st.custom_y if st.placement == "custom" else 0.62
        self.tmp = tempfile.mkdtemp(prefix="ubiclipper_place_")
        self.frame_video, self.at = frame_video, at
        self.photo = None
        self.real = False          # frame shows the real subtitles
        self.drag = None

        body = ttk.Frame(self, style="Card.TFrame", padding=16)
        body.pack(fill="both", expand=True)
        self.cv = tk.Canvas(body, width=W, height=H, highlightthickness=0, cursor="fleur")
        self.cv.grid(row=0, column=0, rowspan=8, sticky="n")
        self.cv.bind("<Button-1>", self._press)
        self.cv.bind("<B1-Motion>", self._move)
        self.cv.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", None))

        side = ttk.Frame(body, style="Card.TFrame", padding=(18, 0, 0, 0))
        side.grid(row=0, column=1, sticky="n")
        ttk.Label(side, text="Place subtitles", style="H2.TLabel").pack(anchor="w")
        ttk.Label(side, text="Drag the sample caption to where your subtitles should be.",
                  style="CardMuted.TLabel", wraplength=260, justify="left").pack(
            anchor="w", pady=(4, 14))
        ttk.Label(side, text="Show the buttons of", style="Card.TLabel").pack(anchor="w")
        self.v_tpl = tk.StringVar(value=app.cfg.get("safe_template") or "TikTok")
        cb = ttk.Combobox(side, textvariable=self.v_tpl, state="readonly", width=22,
                          values=[NONE] + list(TEMPLATES))
        cb.pack(anchor="w", pady=(4, 4))
        cb.bind("<<ComboboxSelected>>", lambda e: self.draw())
        ttk.Label(side, text="Outlines are approximate: keep a little distance.",
                  style="CardMuted.TLabel", wraplength=260, justify="left").pack(anchor="w")
        self.warn = ttk.Label(side, text="", style="Card.TLabel", wraplength=260,
                              justify="left")
        self.warn.pack(anchor="w", pady=(14, 0))
        ttk.Label(side, text="Quick spots", style="Card.TLabel").pack(anchor="w", pady=(16, 4))
        quick = ttk.Frame(side, style="Card.TFrame")
        quick.pack(anchor="w")
        for txt, y in (("Upper", 0.30), ("Centre", 0.50), ("Lower", 0.68)):
            ttk.Button(quick, text=txt, style="Small.TButton",
                       command=lambda y=y: self._set(0.5, y)).pack(side="left", padx=(0, 4))
        ttk.Button(side, text="Check with real subtitles",
                   command=self.real_preview).pack(anchor="w", pady=(18, 0))
        self.status = ttk.Label(side, text="", style="CardMuted.TLabel", wraplength=260)
        self.status.pack(anchor="w", pady=(6, 0))
        btns = ttk.Frame(side, style="Card.TFrame")
        btns.pack(anchor="w", pady=(24, 0))
        ttk.Button(btns, text="Save", style="Accent.TButton", command=self.save).pack(side="left")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(side, text="Back to automatic", style="Small.TButton",
                   command=self.automatic).pack(anchor="w", pady=(10, 0))
        self.bind("<Escape>", lambda e: self.destroy())
        self.draw()
        self.load_frame()

    # ------------------------------------------------------------ frame
    def load_frame(self, with_subs: bool = False) -> None:
        if not self.frame_video:
            self.draw()
            return
        self.status.config(text="Rendering…")
        self._want_real = with_subs
        from clipper.media import probe
        from clipper.reframe import render_preview
        app = self.app
        png = os.path.join(self.tmp, "subs.png" if with_subs else "frame.png")
        ass = self._sample_ass() if with_subs else None

        def work():
            try:
                info = probe(self.frame_video)
                render_preview(self.frame_video, self.at, png, info.width or 1920,
                               info.height or 1080, app.layout, ass, offset=0.3, max_h=H)
                self.after(0, lambda: self._shown(png, None))
            except Exception as e:
                self.after(0, lambda: self._shown(None, e))
        threading.Thread(target=work, daemon=True).start()

    def _shown(self, png, err) -> None:
        if not self.winfo_exists():
            return
        if err:
            self.status.config(text=f"Preview failed: {err}"[:200])
            return
        try:
            self.photo = tk.PhotoImage(file=png)
        except tk.TclError:
            self.photo = None
        self.real = getattr(self, "_want_real", False)
        self.status.config(text="")
        self.draw()

    def _sample_ass(self) -> str:
        from dataclasses import replace
        from clipper.subtitles import Caption, write_ass
        st = replace(self.app.style_, placement="custom", custom_x=self.x, custom_y=self.y,
                     max_chars=min(self.app.style_.max_chars, 16))
        words = ["SAMPLE", "CAPTION"] if st.uppercase else ["Sample", "caption"]
        path = os.path.join(self.tmp, "sample.ass")
        lay = self.app.layout
        write_ass([Caption(0.0, 5.0, " ".join(words), words, [0.0, 0.1])], path,
                  lay.width, lay.height, st)
        return path

    def real_preview(self) -> None:
        self.load_frame(with_subs=True)

    # ------------------------------------------------------------ drawing
    def _caption_box(self) -> tuple[float, float, float, float]:
        st = self.app.style_
        fs = 0.048 * st.size * H
        w = min(W * 0.88, fs * 0.62 * len("SAMPLE CAPTION"))
        h = fs * 1.25
        cx, cy = self.x * W, self.y * H
        return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2

    def draw(self) -> None:
        cv = self.cv
        p = theme.current
        cv.delete("all")
        cv.configure(background="#000000")
        if self.photo:
            cv.create_image(W / 2, H / 2, image=self.photo)
        else:
            cv.create_text(W / 2, H / 2, text="No video open: showing an empty screen",
                           fill="#777777", width=W - 40)
        hits = []
        x0, y0, x1, y1 = self._caption_box()
        for (a, b, c, d), label in TEMPLATES.get(self.v_tpl.get(), []):
            rx0, ry0, rx1, ry1 = a * W, b * H, c * W, d * H
            over = x0 < rx1 and x1 > rx0 and y0 < ry1 and y1 > ry0
            col = "#FF4D4D" if over else "#FFFFFF"
            cv.create_rectangle(rx0 + 1, ry0 + 1, rx1 - 1, ry1 - 1, outline=col, width=2,
                                dash=(6, 4))
            cv.create_text((rx0 + rx1) / 2, (ry0 + ry1) / 2, text=label, fill=col,
                           width=max(40, rx1 - rx0 - 8), justify="center",
                           font=(theme._family(self), 9, "bold"))
            if over:
                hits.append(label)
        # sample caption with an outline, like the real subtitles
        st = self.app.style_
        size = max(10, round(0.048 * st.size * H))
        font = (st.font or "Arial Black", -size, "bold")
        text = "SAMPLE CAPTION" if st.uppercase else "Sample caption"
        cx, cy = self.x * W, self.y * H
        for dx, dy in (() if self.real else ((-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2), (-2, 2), (2, -2))):
            cv.create_text(cx + dx, cy + dy, text=text, fill="#000000", font=font)
        if not self.real:
            cv.create_text(cx, cy, text=text, fill="#" + st.text_color.lstrip("#"), font=font)
        cv.create_rectangle(x0, y0, x1, y1, outline=p["accent"], width=2)
        if hits:
            self.warn.config(text="⚠ Covered by: " + ", ".join(hits), foreground="#E5484D")
        else:
            self.warn.config(text="✓ Not covered by the app's buttons", foreground=p["ok"])

    # ------------------------------------------------------------ dragging
    def _press(self, e) -> None:
        self.drag = (e.x - self.x * W, e.y - self.y * H)
        self._move(e)

    def _move(self, e) -> None:
        if not self.drag:
            return
        dx, dy = self.drag
        self._set((e.x - dx) / W, (e.y - dy) / H)

    def _set(self, x: float, y: float) -> None:
        self.x = round(min(0.85, max(0.15, x)), 3)
        self.y = round(min(0.92, max(0.06, y)), 3)
        if self.real:
            self.real = False
            self.load_frame()
        self.draw()

    # ------------------------------------------------------------ result
    def save(self) -> None:
        st = self.app.style_
        st.placement, st.custom_x, st.custom_y = "custom", self.x, self.y
        self.app.cfg["safe_template"] = self.v_tpl.get()
        self.destroy()
        self.on_save()

    def automatic(self) -> None:
        self.app.style_.placement = "auto"
        self.app.cfg["safe_template"] = self.v_tpl.get()
        self.destroy()
        self.on_save()
