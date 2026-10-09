"""Subtitle style editor with a live preview rendered on a real frame."""

from __future__ import annotations

import os
import queue
import tempfile
import threading
import tkinter as tk
from dataclasses import replace
from tkinter import colorchooser, font as tkfont, messagebox, ttk
from typing import Callable

from clipper.reframe import VerticalLayout, render_preview
from clipper.subtitles import (ANIMATIONS, PLACEMENTS, PRESETS, SubtitleStyle,
                               build_captions, placement_y, preset, write_ass)
from clipper.transcribe import Word

SAMPLE = "Oha amına koyim, bu ne ya! İnanılmaz şaka mı?"


def _key(mapping: dict, value: str) -> str:
    return next((k for k, v in mapping.items() if v == value), next(iter(mapping)))


def _localise() -> None:
    """Menus in the app language (keys are display names)."""
    global ANIMATIONS, PLACEMENTS
    import i18n
    ANIMATIONS = {i18n.t(k): v for k, v in _ANIM_EN.items()}
    PLACEMENTS = {i18n.t(k): v for k, v in _PLACE_EN.items()}


_ANIM_EN, _PLACE_EN = dict(ANIMATIONS), dict(PLACEMENTS)


class StyleEditor(tk.Toplevel):
    def __init__(self, master: tk.Misc, style: SubtitleStyle, preset_name: str,
                 video: str | None, video_size: tuple[int, int], at: float,
                 layout: VerticalLayout | None,
                 on_save: Callable[[SubtitleStyle, str], None]) -> None:
        super().__init__(master)
        _localise()
        global SAMPLE                 # sample caption in the language you stream in
        try:
            from clipper.lang_data import get as _lang
            from clipper.transcribe import LANGUAGES
            SAMPLE = _lang(LANGUAGES.get(master.sub_lang.get()) or "en")["sample"]
        except Exception:
            pass
        self.title("Subtitle style")
        self.transient(master)
        self.resizable(False, False)
        self.style_ = style
        self.video, self.size_, self.at, self.layout = video, video_size, at, layout
        self.on_save = on_save
        self.tmp = tempfile.mkdtemp(prefix="ubiclipper_style_")
        self._render_id = 0
        self._q: queue.Queue = queue.Queue()   # worker thread -> UI thread

        left = ttk.Frame(self, padding=12)
        left.grid(row=0, column=0, sticky="n")
        right = ttk.Frame(self, padding=12)
        right.grid(row=0, column=1, sticky="n")

        self.v_preset = tk.StringVar(value=preset_name if preset_name in PRESETS else "Custom")
        self.v_font = tk.StringVar(value=style.font)
        self.v_size = tk.DoubleVar(value=style.size)
        self.v_outline = tk.DoubleVar(value=style.outline)
        self.v_words = tk.IntVar(value=style.max_words)
        self.v_anim = tk.StringVar(value=_key(ANIMATIONS, style.animation))
        self.v_place = tk.StringVar(value=_key(PLACEMENTS, style.placement))
        self.v_bold = tk.BooleanVar(value=style.bold)
        self.v_upper = tk.BooleanVar(value=style.uppercase)
        self.v_shadow = tk.BooleanVar(value=style.shadow)
        self.v_box = tk.BooleanVar(value=style.box)
        self.v_censor = tk.BooleanVar(value=style.censor)
        self.colors = {"text_color": style.text_color,
                       "highlight_color": style.highlight_color,
                       "outline_color": style.outline_color}

        r = 0

        def row(label: str, widget: tk.Widget) -> None:
            nonlocal r
            ttk.Label(left, text=label).grid(row=r, column=0, sticky="w", pady=3)
            widget.grid(row=r, column=1, sticky="we", pady=3, padx=(8, 0))
            r += 1

        cb = ttk.Combobox(left, textvariable=self.v_preset, state="readonly",
                          values=list(PRESETS) + ["Custom"], width=24)
        cb.bind("<<ComboboxSelected>>", lambda e: self._apply_preset())
        row("Preset", cb)

        families = sorted({f for f in tkfont.families(self) if not f.startswith("@")})
        fc = ttk.Combobox(left, textvariable=self.v_font, values=families, width=24)
        fc.bind("<<ComboboxSelected>>", lambda e: self._changed())
        fc.bind("<Return>", lambda e: self._changed())
        row("Font", fc)
        row("Size", ttk.Scale(left, from_=0.6, to=1.8, variable=self.v_size,
                              command=lambda e: self._changed(delay=400)))
        row("Outline", ttk.Scale(left, from_=0, to=2, variable=self.v_outline,
                                 command=lambda e: self._changed(delay=400)))
        sp = ttk.Spinbox(left, from_=1, to=5, width=5, textvariable=self.v_words,
                         command=self._changed)
        row("Words per caption", sp)
        for label, var, mapping in [("Animation", self.v_anim, ANIMATIONS),
                                    ("Position", self.v_place, PLACEMENTS)]:
            c = ttk.Combobox(left, textvariable=var, values=list(mapping),
                             state="readonly", width=24)
            c.bind("<<ComboboxSelected>>", lambda e: self._changed())
            row(label, c)

        self.swatches: dict[str, tk.Button] = {}
        for key, label in [("text_color", "Text colour"),
                           ("highlight_color", "Spoken-word colour"),
                           ("outline_color", "Outline colour")]:
            b = tk.Button(left, width=10, relief="groove",
                          command=lambda k=key: self._pick_color(k))
            self.swatches[key] = b
            row(label, b)
        self._paint_swatches()

        checks = ttk.Frame(left)
        checks.grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))
        r += 1
        for text, var in [("Bold", self.v_bold), ("UPPERCASE", self.v_upper),
                          ("Shadow", self.v_shadow), ("Dark box", self.v_box)]:
            ttk.Checkbutton(checks, text=text, variable=var,
                            command=self._changed).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(left, text="Censor swear words",
                        variable=self.v_censor, command=self._changed).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
        r += 1

        btns = ttk.Frame(left)
        btns.grid(row=r, column=0, columnspan=2, sticky="we", pady=(16, 0))
        ttk.Button(btns, text="Save", command=self.save).pack(side="right")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=6)

        self.preview = ttk.Label(right, text="Select a video to see a preview",
                                 anchor="center", width=40)
        self.preview.pack()
        self.preview_note = ttk.Label(right, text="", foreground="#666")
        self.preview_note.pack(pady=(6, 0))

        self.after(100, self._render)
        self.after(150, self._modal)
        self.after(100, self._poll)

    def _poll(self) -> None:
        try:
            while True:
                kind, data, my_id = self._q.get_nowait()
                if kind == "ok":
                    self._show(data, my_id)
                elif my_id == self._render_id:
                    self.preview_note.config(text=f"Preview failed: {data}"[:160])
        except queue.Empty:
            pass
        try:
            if self.winfo_exists():
                self.after(100, self._poll)
        except tk.TclError:
            pass  # window closed

    def _modal(self) -> None:
        try:
            self.grab_set()
        except tk.TclError:
            pass

    # ------------------------------------------------------------ state
    def current(self) -> SubtitleStyle:
        return replace(
            self.style_, font=self.v_font.get().strip() or "Arial",
            size=round(float(self.v_size.get()), 2),
            outline=round(float(self.v_outline.get()), 2),
            max_words=max(1, min(5, int(self.v_words.get() or 3))),
            animation=ANIMATIONS[self.v_anim.get()],
            placement=PLACEMENTS[self.v_place.get()],
            bold=self.v_bold.get(), uppercase=self.v_upper.get(),
            shadow=self.v_shadow.get(), box=self.v_box.get(),
            censor=self.v_censor.get(), **self.colors)

    def _apply_preset(self) -> None:
        name = self.v_preset.get()
        if name not in PRESETS:
            return
        st = preset(name, self.current())
        self.v_font.set(st.font)
        self.v_size.set(st.size)
        self.v_outline.set(st.outline)
        self.v_words.set(st.max_words)
        self.v_anim.set(_key(ANIMATIONS, st.animation))
        self.v_bold.set(st.bold)
        self.v_upper.set(st.uppercase)
        self.v_shadow.set(st.shadow)
        self.v_box.set(st.box)
        self.colors = {"text_color": st.text_color,
                       "highlight_color": st.highlight_color,
                       "outline_color": st.outline_color}
        self._paint_swatches()
        self._changed(keep_preset=True)

    def _pick_color(self, key: str) -> None:
        rgb = colorchooser.askcolor(color="#" + self.colors[key], parent=self)[1]
        if rgb:
            self.colors[key] = rgb.lstrip("#").upper()
            self._paint_swatches()
            self._changed()

    def _paint_swatches(self) -> None:
        for key, b in self.swatches.items():
            c = "#" + self.colors[key]
            b.config(bg=c, activebackground=c, text=c.upper())

    def _changed(self, delay: int = 150, keep_preset: bool = False) -> None:
        if not keep_preset:
            self.v_preset.set("Custom")
        self._render_id += 1
        my_id = self._render_id
        self.after(delay, lambda: self._render() if my_id == self._render_id else None)

    # ------------------------------------------------------------ preview
    def _render(self) -> None:
        if not self.video:
            return
        st = self.current()
        my_id = self._render_id
        self.preview_note.config(text="Rendering…")
        words = [Word(i * 0.12, i * 0.12 + 0.1, w) for i, w in enumerate(SAMPLE.split())]
        w, h = self.size_
        vertical = self.layout is not None
        ass = os.path.join(self.tmp, f"p{my_id}.ass")
        png = os.path.join(self.tmp, f"p{my_id}.png")

        def work() -> None:
            try:
                if vertical:
                    s2 = replace(st, max_chars=min(st.max_chars, 16))
                    caps = build_captions(words, s2, "tr")
                    write_ass(caps, ass, self.layout.width, self.layout.height, s2,
                              placement_y(s2, self.layout.caption_position(w, h), True))
                else:
                    caps = build_captions(words, st, "tr")
                    write_ass(caps, ass, w, h, st, placement_y(st, 0.80, False))
                render_preview(self.video, self.at, png, w, h, self.layout, ass,
                               offset=0.15)
                self._q.put(("ok", png, my_id))
            except Exception as e:
                self._q.put(("error", str(e), my_id))

        threading.Thread(target=work, daemon=True).start()

    def _show(self, png: str, my_id: int) -> None:
        if my_id != self._render_id:
            return
        self._img = tk.PhotoImage(file=png)
        self.preview.config(image=self._img, text="")
        self.preview_note.config(
            text="Sample text, shown on a frame of your video. "
                 "Fonts must be installed in Windows to appear.")

    def save(self) -> None:
        st = self.current()
        if not st.font:
            messagebox.showinfo("UbiClipper", "Choose a font.", parent=self)
            return
        self.on_save(st, self.v_preset.get())
        self.destroy()
