"""UbiClipper desktop app.

Layout: header (open a video / paste a link) · settings tabs on the left ·
clip list with details on the right · action bar at the bottom.
Flow: pick a video -> Analyze -> untick what you don't want -> Export ->
Export All (post to your accounts). Settings are remembered between runs.
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from clipper import bootstrap
bootstrap.setup()   # before anything starts FFmpeg or prints

from clipper import __version__
from clipper.media import MediaInfo, cut_clip, probe
from clipper.pipeline import (AnalysisResult, PartialExport, PostInfo, SubtitleOptions,
                              analyze, clip_folder, export)
from clipper.reframe import CONFIG_DIR, LAYOUT_MODES, load_layout, save_layout
from clipper.remote import DOWNLOAD_DIR, RemoteVideo, YtDlpMissing, is_url
from clipper.selection import ClipSettings
from clipper.settings import load_settings, save_settings
from clipper.subtitles import SubtitleStyle, preset
from clipper.transcribe import (LANGUAGES, MODELS, Transcript, TranscribeOptions,
                                check_available, ensure_corrections_file)
import i18n
import theme
from accounts_ui import AccountsTab
from post_dialog import PostDialog
from region_picker import RegionPicker
from style_editor import StyleEditor
from ui_help import help_icon

_LAYOUT_EN, _MODELS_EN = dict(LAYOUT_MODES), dict(MODELS)
PEOPLE = ["Auto (up to 10)"] + [str(n) for n in range(2, 11)]


def hms(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{(t % 3600) // 60:02d}:{t % 60:02d}"


def open_path(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _dnd_base():
    """Use tkinterdnd2 for drag & drop if it loads; otherwise a plain window.
    (Its native tkdnd library can be missing, or blocked by Windows Smart
    App Control - the app must still open then.)"""
    try:
        from tkinterdnd2 import DND_FILES, DND_TEXT, TkinterDnD
        probe_root = TkinterDnD.Tk()
        probe_root.withdraw()
        probe_root.destroy()
        return TkinterDnD.Tk, (DND_FILES, DND_TEXT)
    except Exception:
        return tk.Tk, None


_Base, _DND_TYPES = _dnd_base()


def _dir_size(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


class Form:
    """Rows of  label · control · ⓘ  inside a card."""

    def __init__(self, parent: ttk.Frame) -> None:
        self.f = parent
        self.r = 0
        parent.columnconfigure(1, weight=1)

    def section(self, text: str) -> None:
        ttk.Label(self.f, text=i18n.upper(i18n.t(text)), style="Section.TLabel").grid(
            row=self.r, column=0, columnspan=3, sticky="w", pady=(14 if self.r else 2, 6))
        self.r += 1

    def row(self, label: str | None, widget: tk.Widget, help_key: str | None = None,
            sticky: str = "we") -> tk.Widget:
        if label:
            ttk.Label(self.f, text=label, style="Card.TLabel").grid(
                row=self.r, column=0, sticky="w", padx=(0, 12), pady=5)
            widget.grid(row=self.r, column=1, sticky=sticky, pady=5)
        else:
            widget.grid(row=self.r, column=0, columnspan=2, sticky=sticky, pady=5)
        if help_key:
            help_icon(self.f, help_key).grid(row=self.r, column=2, sticky="w", padx=(8, 0))
        self.r += 1
        return widget


class App(_Base):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_settings()
        i18n.set_language(self.cfg.get("ui_language") or i18n.system_language())
        i18n.install()
        global LAYOUT_MODES, MODELS                 # menus shown in the app language
        LAYOUT_MODES = {i18n.t(k): v for k, v in _LAYOUT_EN.items()}
        MODELS = {i18n.t(k): v for k, v in _MODELS_EN.items()}
        from clipper import judge as _judge
        _judge.REASON_LANGUAGE = i18n.current     # AI judge explains in the app's language
        theme.apply_theme(self, self.cfg.get("theme", "dark"))
        self.title(f"UbiClipper {__version__}")
        bootstrap.set_window_icon(self)
        self.geometry("1320x860")
        self.minsize(1100, 700)
        self.layout = load_layout()
        st = self.cfg.get("style") or {}
        self.style_ = (SubtitleStyle.from_dict(st) if st
                       else preset(self.cfg.get("style_preset", "Bold pop")))
        self.video: str | None = None          # local file (or downloaded audio for links)
        self.remote: RemoteVideo | None = None  # set when working from a link
        self.chat: list | None = None
        self.chat_note = ""
        self.info: MediaInfo | None = None
        self.result: AnalysisResult | None = None
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.mode = ""
        self.export_dir = self.cfg.get("last_export", "")
        self._frames_then = lambda path: None
        self.checked: dict[str, bool] = {}
        self._build()
        self._setup_drop()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._poll)
        self.after(700, self._maybe_get_ready)

    # ================================================================ layout
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()
        body = ttk.Panedwindow(self, orient="horizontal")
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(10, 0))
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=0)
        body.add(right, weight=1)
        self._build_tabs(left)
        self._build_clips(right)
        self._build_footer()

    def _card(self, parent, **grid) -> ttk.Frame:
        outer = ttk.Frame(parent, style="Card.TFrame", padding=16)
        return outer

    # ---------------------------------------------------------------- header
    def _build_header(self) -> None:
        hdr = ttk.Frame(self, style="Panel.TFrame", padding=(18, 12))
        hdr.grid(row=0, column=0, sticky="we")
        hdr.columnconfigure(2, weight=1)
        brand = ttk.Frame(hdr, style="Panel.TFrame")
        brand.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 24))
        self.logo = tk.Canvas(brand, width=30, height=30, highlightthickness=0)
        self.logo.pack(side="left", padx=(0, 10))
        self._draw_logo()
        ttk.Label(brand, text="UbiClipper", style="Title.TLabel").pack(side="left")
        btns = ttk.Frame(hdr, style="Panel.TFrame")
        btns.grid(row=0, column=1, rowspan=2, sticky="w")
        ttk.Button(btns, text="Open video…", command=self.pick).pack(side="left")
        ttk.Button(btns, text="Paste link…", command=self.paste_link).pack(side="left", padx=6)
        ttk.Button(btns, text="Download clip…", command=self.download_clip).pack(side="left")
        help_icon(btns, "link", "PanelHelp.TLabel").pack(side="left", padx=(6, 18))
        src = ttk.Frame(hdr, style="Panel.TFrame")
        src.grid(row=0, column=2, rowspan=2, sticky="we")
        self.file_lbl = ttk.Label(src, text="No video selected", style="Panel.TLabel",
                                  font=(theme._family(self), 11, "bold"))
        self.file_lbl.pack(anchor="w")
        self.file_sub = ttk.Label(src, text="Open a video, paste a Kick / Twitch / YouTube "
                                            "link" + (", or drop one onto this window"
                                                      if _DND_TYPES else ""),
                                  style="PanelMuted.TLabel")
        self.file_sub.pack(anchor="w")
        self.track_row = ttk.Frame(hdr, style="Panel.TFrame")
        self.track_row.grid(row=0, column=3, rowspan=2, sticky="e")
        ttk.Label(self.track_row, text="Listen to", style="Panel.TLabel").pack(side="left")
        self.track_box = ttk.Combobox(self.track_row, state="readonly", width=28)
        self.track_box.pack(side="left", padx=6)
        help_icon(self.track_row, "track", "PanelHelp.TLabel").pack(side="left")
        self.track_row.grid_remove()

    # ---------------------------------------------------------------- tabs
    def _build_tabs(self, parent: ttk.Frame) -> None:
        nb = ttk.Notebook(parent, width=470)
        nb.pack(fill="both", expand=True)
        c = self.cfg

        # -- Moments
        t = ttk.Frame(nb, style="Card.TFrame", padding=18)
        nb.add(t, text="Moments")
        f = Form(t)
        self.max_clips = tk.StringVar(value=str(c["max_clips"]))
        self.max_len = tk.DoubleVar(value=c["max_len"])
        self.pre_roll = tk.DoubleVar(value=c["pre_roll"])
        self.sens = tk.DoubleVar(value=c["sensitivity"])
        self.focus = tk.DoubleVar(value=c["voice_focus"])
        self.rank_on = tk.BooleanVar(value=c.get("rank_words", True))
        self.chat_on = tk.BooleanVar(value=c.get("use_chat", True))
        f.section("Clips")
        mc = ttk.Combobox(t, textvariable=self.max_clips, width=10,
                          values=["auto", "5", "10", "20", "30", "50", "75", "100",
                                  i18n.t("Custom…")])
        mc.bind("<<ComboboxSelected>>", lambda e: self._custom_clips())
        f.row("Max clips", mc, "max_clips", sticky="w")
        self.min_len = tk.DoubleVar(value=c.get("min_len", 10))
        f.row("Min length (s)", ttk.Spinbox(t, from_=5, to=240, increment=5, width=7,
                                            textvariable=self.min_len, format="%.0f"), "min_len", sticky="w")
        f.row("Max length (s)", ttk.Spinbox(t, from_=15, to=240, increment=5, width=7,
                                            textvariable=self.max_len, format="%.0f"), "max_len", sticky="w")
        f.row("Setup before moment (s)", ttk.Spinbox(t, from_=0, to=30, increment=1, width=7,
                                                     textvariable=self.pre_roll, format="%.0f"),
              "pre_roll", sticky="w")
        f.section("What counts")
        f.row("Sensitivity", self._slider(t, self.sens, "fewer", "more"), "sensitivity")
        f.row("Focus", self._slider(t, self.focus, "any loud sound", "voice"), "focus")
        f.row(None, ttk.Checkbutton(t, text="Rank by what's said (funny words)",
                                    variable=self.rank_on), "rank", sticky="w")
        f.row(None, ttk.Checkbutton(t, text="Use chat reactions (Kick / Twitch links)",
                                    variable=self.chat_on), "chat", sticky="w")
        f.section("AI (free, runs on your PC)")
        self.ai_listen = tk.BooleanVar(value=c.get("ai_listen", True))
        self.ai_judge = tk.BooleanVar(value=c.get("ai_judge", False))
        f.row(None, ttk.Checkbutton(t, text="Listening AI: recognise laughs, screams, explosions",
                                    variable=self.ai_listen), "ai_listen", sticky="w")
        f.row(None, ttk.Checkbutton(t, text="AI judge: reads each moment and rates how funny",
                                    variable=self.ai_judge, command=self._judge_toggled),
              "ai_judge", sticky="w")
        self.judge_lbl = ttk.Label(t, text="", style="CardMuted.TLabel", wraplength=400,
                                   justify="left")
        f.row(None, self.judge_lbl, sticky="w")

        # -- Subtitles
        t = ttk.Frame(nb, style="Card.TFrame", padding=18)
        nb.add(t, text="Subtitles")
        f = Form(t)
        self.sub_on = tk.BooleanVar(value=c["subtitles_on"])
        if c["language"] not in LANGUAGES:     # first start: the language Windows is in
            loc = i18n.system_locale()
            c["language"] = next((k for k, v in LANGUAGES.items() if v == loc), "English")
        self.sub_lang = tk.StringVar(value=c["language"])
        saved = _MODELS_EN.get(c["model"], c["model"])       # old English name or model id
        self.sub_model = tk.StringVar(value=next((k for k, v in MODELS.items() if v == saved
                                                  or k == c["model"]), next(iter(MODELS))))
        self.sub_words = tk.StringVar(value=c["words"])
        self.censor = tk.BooleanVar(value=self.style_.censor)
        self.spk_on = tk.BooleanVar(value=c.get("speaker_colors", True))
        people_vals = [i18n.t(PEOPLE[0])] + PEOPLE[1:]
        saved = c.get("people", PEOPLE[0])
        self.spk_people = tk.StringVar(value=saved if saved.isdigit() else people_vals[0])
        f.section("Speech to text")
        f.row(None, ttk.Checkbutton(t, text="Add subtitles", variable=self.sub_on), sticky="w")
        f.row("Language", ttk.Combobox(t, textvariable=self.sub_lang, values=list(LANGUAGES),
                                       state="readonly", width=16), "language", sticky="w")
        none = i18n.t("None (one language)")
        also_vals = [none] + [k for k, v in LANGUAGES.items() if v]
        saved_also = c.get("also_language", "English")
        self.sub_also = tk.StringVar(value=saved_also if saved_also in LANGUAGES else none)
        f.row("Also speaks", ttk.Combobox(t, textvariable=self.sub_also, values=also_vals,
                                          state="readonly", width=16), "also_language",
              sticky="w")
        f.row("Model", ttk.Combobox(t, textvariable=self.sub_model, values=list(MODELS),
                                    state="readonly", width=28), "model", sticky="w")
        f.row("Names / words", ttk.Entry(t, textvariable=self.sub_words), "words")
        f.row(None, ttk.Button(t, text="Fix misheard words…",
                               command=lambda: open_path(ensure_corrections_file())),
              "fix_words", sticky="w")
        f.section("Look")
        style_row = ttk.Frame(t, style="Card.TFrame")
        ttk.Button(style_row, text="Style…", command=self.edit_style).pack(side="left")
        self.style_lbl = ttk.Label(style_row, text="", style="CardMuted.TLabel")
        self.style_lbl.pack(side="left", padx=10)
        f.row(None, style_row, sticky="we")
        f.row(None, ttk.Checkbutton(t, text="Censor swear words", variable=self.censor,
                                    command=self._censor_changed), "censor", sticky="w")
        f.section("Several people talking")
        f.row(None, ttk.Checkbutton(t, text="Colour each person differently",
                                    variable=self.spk_on), "speakers", sticky="w")
        f.row("People", ttk.Combobox(t, textvariable=self.spk_people, values=people_vals,
                                     state="readonly", width=20), sticky="w")
        sw = ttk.Frame(t, style="Card.TFrame")
        self.swatch_canvas = tk.Canvas(sw, height=22, width=330, highlightthickness=0,
                                       cursor="hand2")
        self.swatch_canvas.pack(side="left")
        self.swatch_canvas.bind("<Button-1>", self._pick_speaker_color)
        ttk.Label(sw, text="click to change", style="CardMuted.TLabel").pack(side="left", padx=6)
        f.row(None, sw, sticky="w")
        self._draw_swatches()
        self._show_style()

        # -- 9:16
        t = ttk.Frame(nb, style="Card.TFrame", padding=18)
        nb.add(t, text="9:16")
        f = Form(t)
        self.vert_on = tk.BooleanVar(value=c["vertical_on"])
        f.section("Vertical video")
        f.row(None, ttk.Checkbutton(t, text="Make a 9:16 version (TikTok / Reels / Shorts)",
                                    variable=self.vert_on), "vertical", sticky="w")
        cur = next((k for k, v in LAYOUT_MODES.items() if v == self.layout.effective_mode),
                   next(iter(LAYOUT_MODES)))
        self.layout_mode = tk.StringVar(value=cur)
        lm = ttk.Combobox(t, textvariable=self.layout_mode, values=list(LAYOUT_MODES),
                          state="readonly", width=32)
        lm.bind("<<ComboboxSelected>>", lambda e: self._layout_changed())
        f.row("Layout", lm, "layout", sticky="w")
        f.section("Areas")
        self.cam_btn = ttk.Button(t, text="Set webcam area…", command=self.set_webcam)
        f.row(None, self.cam_btn, "webcam", sticky="w")
        f.row(None, ttk.Button(t, text="Set main area…", command=self.set_main),
              "main_area", sticky="w")
        f.row(None, ttk.Button(t, text="Reset areas", command=self.reset_areas), sticky="w")
        self.cam_lbl = ttk.Label(t, text="", style="CardMuted.TLabel", wraplength=380)
        f.row(None, self.cam_lbl, sticky="w")
        self._show_cam()
        f.section("Subtitles on the 9:16 screen")
        f.row(None, ttk.Button(t, text="Place subtitles…", command=self.place_subtitles),
              "place_subs", sticky="w")
        self.place_lbl = ttk.Label(t, text="", style="CardMuted.TLabel", wraplength=380)
        f.row(None, self.place_lbl, sticky="w")
        self._show_place()

        # -- Export
        t = ttk.Frame(nb, style="Card.TFrame", padding=18)
        nb.add(t, text="Export")
        f = Form(t)
        f.section("Export folder")
        self.out_lbl = ttk.Label(t, text="", style="Card.TLabel", wraplength=380)
        f.row(None, self.out_lbl, "export", sticky="w")
        row = ttk.Frame(t, style="Card.TFrame")
        ttk.Button(row, text="Change…", command=self.choose_root).pack(side="left")
        ttk.Button(row, text="Open", command=self.open_root).pack(side="left", padx=6)
        f.row(None, row, sticky="w")
        self._show_root()
        f.section("Finished versions")
        self.full_on = tk.BooleanVar(value=c.get("fullscreen_on", True))
        f.row(None, ttk.Checkbutton(t, text="9:16 for TikTok / Reels / Shorts (ready_social)",
                                    variable=self.vert_on), "vertical", sticky="w")
        f.row(None, ttk.Checkbutton(t, text="1920×1080 with subtitles for montages "
                                            "(ready_fullscreen)",
                                    variable=self.full_on), "fullscreen", sticky="w")
        f.section("Titles & hashtags (local files)")
        self.post_channel = tk.StringVar(value=c.get("post_channel", ""))
        self.post_platform = tk.StringVar(value=c.get("post_platform", "Kick"))
        self.post_game = tk.StringVar(value=c.get("post_game", ""))
        f.row("Channel", ttk.Entry(t, textvariable=self.post_channel), "post_info")
        f.row("Platform", ttk.Combobox(t, textvariable=self.post_platform, state="readonly",
                                       width=12, values=["Kick", "Twitch", "YouTube"]),
              sticky="w")
        f.row("Game", ttk.Entry(t, textvariable=self.post_game))

        # -- Accounts
        t = ttk.Frame(nb, style="Card.TFrame", padding=18)
        nb.add(t, text="Accounts")
        self.accounts = AccountsTab(t, self)

        # -- Settings
        t = ttk.Frame(nb, style="Card.TFrame", padding=18)
        nb.add(t, text="Settings")
        f = Form(t)
        f.section("Appearance")
        self.theme_var = tk.StringVar(value=c.get("theme", "dark"))
        tr = ttk.Frame(t, style="Card.TFrame")
        for val, txt in (("dark", "Dark"), ("light", "Light")):
            ttk.Radiobutton(tr, text=txt, value=val, variable=self.theme_var,
                            command=self._theme_changed).pack(side="left", padx=(0, 16))
        f.row("Theme", tr, "theme", sticky="w")
        langs = i18n.available()
        self.ui_lang = tk.StringVar(value=langs.get(i18n.current, "English"))
        lang_box = ttk.Combobox(t, textvariable=self.ui_lang, values=list(langs.values()),
                                state="readonly", width=16)
        lang_box.bind("<<ComboboxSelected>>", lambda e: self._ui_language_changed())
        f.row("App language", lang_box, "ui_language", sticky="w")
        f.section("Storage")
        self.cache_lbl = ttk.Label(t, text="", style="Card.TLabel")
        f.row("Link downloads", self.cache_lbl, "cache", sticky="w")
        row = ttk.Frame(t, style="Card.TFrame")
        ttk.Button(row, text="Open folder", command=lambda: (
            os.makedirs(DOWNLOAD_DIR, exist_ok=True), open_path(DOWNLOAD_DIR))).pack(side="left")
        ttk.Button(row, text="Clear", command=self._clear_cache).pack(side="left", padx=6)
        f.row(None, row, sticky="w")
        self._show_cache()
        f.section("AI models")
        self.models_lbl = ttk.Label(t, text="", style="Card.TLabel")
        f.row("AI judge", self.models_lbl, "ai_models", sticky="w")
        row = ttk.Frame(t, style="Card.TFrame")
        self.dl_btn = ttk.Button(row, text="Download now", command=self._download_judge)
        self.dl_btn.pack(side="left")
        ttk.Button(row, text="Test", command=self._test_judge).pack(side="left", padx=6)
        ttk.Button(row, text="Delete", command=self._delete_judge).pack(side="left")
        f.row(None, row, sticky="w")
        f.row(None, ttk.Button(t, text="All AI downloads & GPU speed-up…",
                               command=self._open_ready), "get_ready", sticky="w")
        self._show_models()
        f.section("Help")
        hb = ttk.Frame(t, style="Card.TFrame")
        ttk.Button(hb, text="Check setup (GPU, FFmpeg, …)",
                   command=self._check_setup).pack(side="left")
        ttk.Button(hb, text="Roadmap", command=self._open_roadmap).pack(side="left", padx=6)
        f.row(None, hb, "roadmap", sticky="w")
        f.row(None, ttk.Label(t, text=f"UbiClipper {__version__} · settings in {CONFIG_DIR}",
                              style="CardMuted.TLabel", wraplength=380), sticky="w")

    def _slider(self, parent, var, left: str, right: str) -> ttk.Frame:
        fr = ttk.Frame(parent, style="Card.TFrame")
        ttk.Label(fr, text=left, style="CardMuted.TLabel").pack(side="left")
        ttk.Scale(fr, from_=0, to=1, variable=var).pack(side="left", fill="x", expand=True,
                                                        padx=8)
        ttk.Label(fr, text=right, style="CardMuted.TLabel").pack(side="left")
        return fr

    # ---------------------------------------------------------------- clips
    def _build_clips(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=(16, 14))
        card.pack(fill="both", expand=True, padx=(12, 0))
        top = ttk.Frame(card, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Clips", style="H2.TLabel").pack(side="left")
        self.count_lbl = ttk.Label(top, text="Analyze a video to find moments",
                                   style="CardMuted.TLabel")
        self.count_lbl.pack(side="left", padx=12)
        ttk.Button(top, text="None", style="Small.TButton",
                   command=lambda: self._check_all(False)).pack(side="right")
        ttk.Button(top, text="All", style="Small.TButton",
                   command=lambda: self._check_all(True)).pack(side="right", padx=4)

        tv_wrap = ttk.Frame(card, style="Card.TFrame")
        tv_wrap.pack(fill="both", expand=True, pady=(10, 8))
        cols = ("use", "rank", "start", "len", "score", "ai", "why")
        self.tree = ttk.Treeview(tv_wrap, columns=cols, show="headings", selectmode="browse")
        self._col_names = {"use": "✓", "rank": "#", "start": "Start", "len": "Length",
                           "score": "Score", "ai": "AI", "why": "Why"}
        for col, w in [("use", 44), ("rank", 40), ("start", 84), ("len", 70), ("score", 70),
                       ("ai", 64), ("why", 300)]:
            self.tree.heading(col, text=self._col_names[col],
                              command=(lambda c=col: self._sort_by(c)) if col not in ("use", "why")
                              else "")
            self.tree.column(col, width=w, minwidth=w, anchor="w" if col == "why" else "center",
                             stretch=col == "why")
        self.sort_col, self.sort_desc = "score", True
        sb = ttk.Scrollbar(tv_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<Button-1>", self._toggle)
        self.tree.bind("<Double-1>", lambda e: self.preview())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_detail())
        self.tree.bind("<space>", self._toggle_key)
        self._tag_colors()

        det = ttk.Frame(card, style="Card.TFrame")
        det.pack(fill="x")
        ttk.Separator(det).pack(fill="x", pady=(0, 8))
        self.det_title = ttk.Label(det, text="Select a clip to see details",
                                   style="Card.TLabel", font=(theme._family(self), 10, "bold"),
                                   wraplength=700, justify="left")
        self.det_title.pack(anchor="w")
        self.det_text = ttk.Label(det, text="", style="CardMuted.TLabel", wraplength=700,
                                  justify="left")
        self.det_text.pack(anchor="w", pady=(2, 8))
        acts = ttk.Frame(card, style="Card.TFrame")
        acts.pack(fill="x")
        ttk.Button(acts, text="▶  Preview", command=self.preview).pack(side="left")
        ttk.Button(acts, text="✂  Trim…", command=self.trim).pack(side="left", padx=6)
        ttk.Button(acts, text="✎  Edit subtitles…", command=self.edit_subtitles).pack(side="left")
        self.post_btn = ttk.Button(acts, text="Export All ↗", command=self.open_post)
        self.post_btn.pack(side="right")
        help_icon(acts, "export_all").pack(side="right", padx=(0, 6))
        self.export_btn = ttk.Button(acts, text="Export checked clips", style="Accent.TButton",
                                     command=self.start_export, state="disabled")
        self.export_btn.pack(side="right", padx=10)

    def _tag_colors(self, *_):
        p = theme.current
        self.tree.tag_configure("off", foreground=p["muted"])

    # ---------------------------------------------------------------- footer
    def _build_footer(self) -> None:
        bar = ttk.Frame(self, style="Panel.TFrame", padding=(18, 12))
        bar.grid(row=2, column=0, sticky="we", pady=(12, 0))
        bar.columnconfigure(2, weight=1)
        self.analyze_btn = ttk.Button(bar, text="Analyze", style="Accent.TButton",
                                      command=self.start_analyze)
        self.analyze_btn.grid(row=0, column=0, rowspan=2)
        self.cancel_btn = ttk.Button(bar, text="Cancel", command=self.cancel.set,
                                     state="disabled")
        self.cancel_btn.grid(row=0, column=1, rowspan=2, padx=10)
        self.status = ttk.Label(bar, text="Ready.", style="Panel.TLabel")
        self.status.grid(row=0, column=2, sticky="w", padx=(8, 0))
        self.bar = ttk.Progressbar(bar, maximum=1.0)
        self.bar.grid(row=1, column=2, sticky="we", padx=(8, 0), pady=(6, 0))

    # ================================================================ theme
    def _ui_language_changed(self) -> None:
        code = next((k for k, v in i18n.available().items() if v == self.ui_lang.get()), "en")
        if code == i18n.current:
            return
        self.cfg["ui_language"] = code
        self._collect()
        if self.busy:
            messagebox.showinfo("UbiClipper", "The new language is used the next time "
                                              "UbiClipper starts.")
            return
        if messagebox.askyesno("UbiClipper", "Restart UbiClipper now to switch the "
                                             "language?"):
            self._close()
            here = os.path.dirname(os.path.abspath(__file__))
            subprocess.Popen([sys.executable, os.path.join(here, "app.py")], cwd=here)

    def _theme_changed(self) -> None:
        mode = self.theme_var.get()
        theme.apply_theme(self, mode)
        self.cfg["theme"] = mode
        save_settings(self.cfg)
        self._tag_colors()
        self._draw_swatches()
        self._draw_logo()

    def _draw_logo(self) -> None:
        p, cv = theme.current, self.logo
        cv.configure(background=p["panel"])
        cv.delete("all")
        r, w = 8, 30   # rounded square
        for x0, y0, x1, y1 in ((r, 0, w - r, w), (0, r, w, w - r)):
            cv.create_rectangle(x0, y0, x1, y1, fill=p["accent"], outline=p["accent"])
        for x, y in ((0, 0), (w - 2 * r, 0), (0, w - 2 * r), (w - 2 * r, w - 2 * r)):
            cv.create_oval(x, y, x + 2 * r, y + 2 * r, fill=p["accent"], outline=p["accent"])
        cv.create_polygon(12, 9, 12, 21, 21, 15, fill="#FFFFFF", outline="#FFFFFF")

    def _pick_speaker_color(self, event) -> None:
        i = int(event.x // 32)
        pal = list(self.style_.palette or [])
        if not 0 <= i < len(pal):
            return
        from tkinter import colorchooser
        rgb = colorchooser.askcolor(color="#" + pal[i], parent=self,
                                    title=f"Colour for person {i + 1}")[1]
        if rgb:
            pal[i] = rgb.lstrip("#").upper()
            self.style_.palette = pal
            self._draw_swatches()
            self._collect()

    def _draw_swatches(self) -> None:
        cv = self.swatch_canvas
        cv.configure(background=theme.current["card"])
        cv.delete("all")
        for i, col in enumerate((self.style_.palette or [])[:10]):
            x = i * 32
            cv.create_rectangle(x, 2, x + 26, 20, fill="#" + col, outline=theme.current["border"])
            cv.create_text(x + 13, 11, text=str(i + 1), font=(theme._family(self), 8, "bold"),
                           fill="#111" if col.upper() not in ("B388FF",) else "#111")

    # ================================================================ drag & drop
    def _setup_drop(self) -> None:
        if not _DND_TYPES:
            return
        try:
            self.drop_target_register(*_DND_TYPES)
            self.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass

    def _on_drop(self, event):
        items = [i.strip() for i in self.tk.splitlist(event.data) if i.strip()]
        if not items:
            return event.action
        first = items[0]
        if is_url(first):
            self._open_link(first)
        elif os.path.isfile(first):
            self._open_file(first)
        elif os.path.isdir(first):
            messagebox.showinfo("UbiClipper", "Drop a video file, not a folder.")
        else:
            messagebox.showinfo("UbiClipper", "That isn't a video file or a link.")
        return event.action

    # ================================================================ settings
    def _collect(self) -> None:
        self.cfg.update(
            max_clips=self.max_clips.get().strip() or "auto",
            max_len=float(self.max_len.get()), pre_roll=float(self.pre_roll.get()),
            min_len=float(self.min_len.get()),
            sensitivity=round(float(self.sens.get()), 2),
            voice_focus=round(float(self.focus.get()), 2),
            subtitles_on=self.sub_on.get(), language=self.sub_lang.get(),
            model=MODELS.get(self.sub_model.get(), self.sub_model.get()),
            also_language=(self.sub_also.get() if self.sub_also.get() in LANGUAGES
                           else ""),
            words=self.sub_words.get(),
            style=self.style_.to_dict(), vertical_on=self.vert_on.get(),
            rank_words=self.rank_on.get(), use_chat=self.chat_on.get(),
            post_channel=self.post_channel.get().strip(),
            post_platform=self.post_platform.get(), post_game=self.post_game.get().strip(),
            speaker_colors=self.spk_on.get(), people=self.spk_people.get(),
            theme=self.theme_var.get(), last_export=self.export_dir,
            fullscreen_on=self.full_on.get(),
            ai_listen=self.ai_listen.get(), ai_judge=self.ai_judge.get())
        save_settings(self.cfg)

    def _close(self) -> None:
        try:
            self._collect()
        finally:
            self.destroy()

    # ================================================================ video
    def pick(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a video",
            filetypes=[("Video", "*.mp4 *.mkv *.mov *.flv *.webm *.ts *.avi"),
                       ("All files", "*.*")])
        if path:
            self._open_file(path)

    def _open_file(self, path: str) -> None:
        if self.busy:
            return
        try:
            info = probe(path)
        except Exception as e:
            messagebox.showerror("UbiClipper", str(e))
            return
        self._set_source(path, info, None, os.path.basename(path))

    def _set_source(self, path: str, info: MediaInfo, remote: RemoteVideo | None,
                    label: str) -> None:
        self.video, self.info, self.remote, self.result = path, info, remote, None
        self.chat, self.chat_note = None, ""
        self.tree.delete(*self.tree.get_children())
        self.export_btn.config(state="disabled")
        self.count_lbl.config(text="Click Analyze to find moments")
        dur = remote.duration if remote and remote.duration else info.duration
        self.file_lbl.config(text=label)
        sub = [hms(dur)]
        if remote:
            sub += [remote.platform.capitalize() or "Link"]
            if remote.game:
                sub.append(remote.game)
        elif info.width:
            sub.append(f"{info.width}×{info.height}")
        self.file_sub.config(text="  ·  ".join(sub))
        if len(info.audio_tracks) > 1:
            self.track_box["values"] = [t.label() for t in info.audio_tracks]
            self.track_box.current(0)
            self.track_row.grid()
        else:
            self.track_row.grid_remove()

    def _track(self) -> int:
        return max(0, self.track_box.current()) if self.track_row.winfo_ismapped() else 0

    # ================================================================ links
    def paste_link(self) -> None:
        if self.busy:
            return
        url = simpledialog.askstring(
            "Paste link", "Kick / Twitch / YouTube VOD link:", parent=self)
        if url and url.strip():
            self._open_link(url.strip())

    # ---------------------------------------------------------------- clips
    def download_clip(self) -> None:
        if self.busy:
            return
        url = simpledialog.askstring(
            "Download clip", "Twitch / Kick / YouTube clip link:", parent=self)
        if url and url.strip():
            self._download_clip(url.strip())

    def _download_clip(self, url: str) -> None:
        if not is_url(url):
            messagebox.showinfo("UbiClipper", "That doesn't look like a link (https://…).")
            return
        root = self.cfg.get("export_root")
        if not root or not os.path.isdir(root):
            messagebox.showinfo("UbiClipper",
                                "Choose a folder for your clips. It's remembered, and each "
                                "video gets its own subfolder inside it.")
            if not self.choose_root():
                return
            root = self.cfg["export_root"]
        folder = os.path.join(root, "Downloaded clips")
        from clipper.clipdl import download_clip

        def work():
            self._progress("Reading link…", 0.0)
            return download_clip(url, folder, lambda m, f: self._progress(m, f),
                                 self.cancel.is_set)
        self.mode = "clipdl"
        self._run(work)

    def _clip_downloaded(self, path: str) -> None:
        self.status.config(text=f"Clip downloaded: {os.path.basename(path)}")
        choice = messagebox.askyesnocancel(
            "Clip downloaded",
            f"{os.path.basename(path)}\n\nYes: open it here to add subtitles / make the "
            "9:16 version\nNo: open the folder\nCancel: close")
        if choice:
            self._open_whole_clip(path)
        elif choice is False:
            open_path(os.path.dirname(path))

    def _open_whole_clip(self, path: str) -> None:
        """Open a short video as ONE ready moment (no analysis needed): export
        adds subtitles, the 9:16 and 1920x1080 versions, titles and posting."""
        import numpy as np
        from clipper.detectors import Timeline
        from clipper.selection import Clip
        self._open_file(path)
        if not self.info or not self.info.duration:
            return
        d = float(self.info.duration)
        hop = 0.5
        tl = Timeline(hop, np.zeros(max(4, int(d / hop) + 1)))
        clip = Clip(0.0, round(d, 2), round(d / 2, 2), 1.0, ["Downloaded clip"])
        self.result = AnalysisResult(self.info, [clip], tl, self._settings(), 0.0)
        self._fill()
        self._set_busy(False)
        self.status.config(text="Clip ready: export it, or ✂ Trim… it first.")

    def _open_link(self, url: str) -> None:
        if self.busy:
            return
        if not is_url(url):
            messagebox.showinfo("UbiClipper", "That doesn't look like a link (https://…).")
            return
        from clipper.clipdl import clip_kind
        if clip_kind(url):          # a clip, not a stream: just download it
            self._download_clip(url)
            return

        def work():
            self._progress("Reading link…", 0.0)
            rv = RemoteVideo.probe(url)
            if not rv.audio_path:
                rv.download_audio(lambda m, f: self._progress(m, f), self.cancel.is_set)
            chat, note = None, ""
            try:   # best effort: analysis works without it
                chat = rv.fetch_chat(lambda m, f: self._progress(m, f), self.cancel.is_set)
                note = (f"{len(chat)} chat messages" if chat else "no chat replay")
            except InterruptedError:
                raise
            except Exception as e:
                note = "chat unavailable: " + str(e).splitlines()[0][:80]
            return rv, probe(rv.audio_path), chat, note

        self.mode = "link"
        self._run(work)

    def _with_frames(self, at: float, then) -> None:
        """Call then(video_path, time_in_that_file, duration_of_that_file).
        For links, a few seconds of video are downloaded first."""
        if not self.remote:
            then(self.video, at, self.info.duration if self.info else 0)
            return
        rv = self.remote
        at = max(0.0, min(at, (rv.duration or at + 10) - 5))

        def work():
            self._progress("Downloading a few seconds of video…", 0.0)
            return rv.download_section(at, at + 4, lambda m, f: self._progress(m, f),
                                       self.cancel.is_set)

        self.mode = "frames"
        self._frames_then = lambda path: then(path, 1.0, 4.0)
        self._run(work)

    # ================================================================ style
    def place_subtitles(self) -> None:
        if self.busy:
            return
        from caption_placer import CaptionPlacer
        at = 0.0
        if self.info:
            at = (sorted(self.result.clips, key=lambda c: -c.score)[0].peak
                  if self.result and self.result.clips
                  else (self.remote.duration if self.remote else self.info.duration) * 0.3)
        if self.video:
            self._with_frames(at, lambda path, t, d: CaptionPlacer(self, path, t,
                                                                   self._placed))
        else:
            CaptionPlacer(self, None, 0.0, self._placed)

    def _placed(self) -> None:
        self._show_place()
        self._collect()

    def _show_place(self) -> None:
        st = self.style_
        if st.placement == "custom":
            txt = i18n.t("Custom spot ({0}% from left, {1}% from top)").format(
                round(st.custom_x * 100), round(st.custom_y * 100))
        else:
            txt = i18n.t("Automatic (from the layout and the subtitle style)")
        self.place_lbl.config(text=txt)

    def _show_style(self) -> None:
        name = self.cfg.get("style_preset", "Custom")
        anim = {"none": "no animation", "pop": "pop in", "highlight": "highlighted words",
                "pop+highlight": "pop + highlighted words"}.get(self.style_.animation, "")
        self.style_lbl.config(text=f"{name} · {self.style_.font} · {anim}")

    def edit_style(self) -> None:
        if self.busy:
            return
        at = 0.0
        if self.info:
            at = (sorted(self.result.clips, key=lambda c: -c.score)[0].peak
                  if self.result and self.result.clips
                  else (self.remote.duration if self.remote else self.info.duration) * 0.3)
        if self.video:
            self._with_frames(at, lambda path, t, d: self._open_style(path, t))
        else:
            self._open_style(None, 0.0)

    def _open_style(self, frame_video: str | None, at: float) -> None:
        size = (1920, 1080)
        if frame_video:
            try:
                fi = probe(frame_video)
                size = (fi.width or 1920, fi.height or 1080)
            except Exception:
                pass

        def saved(style: SubtitleStyle, name: str) -> None:
            self.style_ = style
            self.cfg["style_preset"] = name
            self.censor.set(style.censor)
            self._show_style()
            self._draw_swatches()
            self._collect()

        StyleEditor(self, self.style_, self.cfg.get("style_preset", "Custom"),
                    frame_video, size, at, self.layout if self.vert_on.get() else None,
                    saved)

    def _censor_changed(self) -> None:
        self.style_.censor = self.censor.get()
        self._collect()

    # ================================================================ 9:16 areas
    def _show_cam(self) -> None:
        mode = self.layout.effective_mode
        main = "chosen main area" if self.layout.gameplay else "whole frame"
        if self.layout.mode == "stack" and not self.layout.webcam:
            txt = "Set a webcam area for this layout (until then: blurred background)"
        elif mode == "stack":
            txt = f"Now: webcam on top, {main} below"
        elif mode == "fill":
            txt = f"Now: {main} fills the 9:16 screen"
        else:
            txt = f"Now: {main} on a blurred background"
        self.cam_lbl.config(text=txt)
        try:
            self.cam_btn.config(state="normal" if self.layout.mode in ("stack", "auto")
                                else "disabled")
        except (AttributeError, tk.TclError):
            pass

    def _layout_changed(self) -> None:
        self.layout.mode = LAYOUT_MODES[self.layout_mode.get()]
        save_layout(self.layout)
        self._show_cam()

    def _frame_size(self, path: str) -> tuple[int, int]:
        if not self.remote and self.info and self.info.width:
            return self.info.width, self.info.height or 1080
        try:
            fi = probe(path)
            return fi.width or 1920, fi.height or 1080
        except Exception:
            return 1920, 1080

    def set_main(self) -> None:
        if not self.video or not self.info:
            messagebox.showinfo("UbiClipper", "Open a video first.")
            return
        if self.busy:
            return

        def saved(region) -> None:
            self.layout.gameplay = region
            save_layout(self.layout)
            self._show_cam()

        def open_picker(path, t, d) -> None:
            w, h = self._frame_size(path)
            mode = self.layout.effective_mode
            what = {"stack": "the part shown BELOW your webcam (usually the game)",
                    "fill": "what should fill the whole 9:16 screen (e.g. your camera "
                            "on a camera-only stream)",
                    "blur": "what should sit in the middle, over the blurred background"}[mode]
            ref = (self.layout.webcam, "webcam") if self.layout.webcam and mode == "stack" else None
            RegionPicker(self, path, d, self.layout.gameplay, saved,
                         title="Set main area", label="MAIN", color="#4FC3F7",
                         hint=f"Drag a box around {what}, then click Save. "
                              "Drag inside the box to move it.",
                         aspect=self.layout.main_aspect(w, h), reference=ref)

        dur = self.remote.duration if self.remote else self.info.duration
        self._with_frames(dur * 0.3, open_picker)

    def reset_areas(self) -> None:
        self.layout.webcam = None
        self.layout.gameplay = None
        save_layout(self.layout)
        self._show_cam()

    def set_webcam(self) -> None:
        if not self.video or not self.info:
            messagebox.showinfo("UbiClipper", "Open a video first.")
            return
        if self.busy:
            return

        def saved(region) -> None:
            self.layout.webcam = region
            save_layout(self.layout)
            self._show_cam()

        dur = self.remote.duration if self.remote else self.info.duration
        self._with_frames(dur * 0.3, lambda path, t, d: RegionPicker(
            self, path, d, self.layout.webcam, saved,
            reference=(self.layout.gameplay, "main") if self.layout.gameplay else None))

    # ================================================================ export folder
    def _show_root(self) -> None:
        root = self.cfg.get("export_root") or ""
        self.out_lbl.config(text=root or "Not set yet: you'll be asked on the first export.")

    def choose_root(self) -> bool:
        path = filedialog.askdirectory(title="Where should clips be exported?",
                                       initialdir=self.cfg.get("export_root") or None)
        if not path:
            return False
        self.cfg["export_root"] = path
        save_settings(self.cfg)
        self._show_root()
        return True

    def open_root(self) -> None:
        root = self.cfg.get("export_root")
        if root and os.path.isdir(root):
            open_path(root)
        else:
            messagebox.showinfo("UbiClipper", "No export folder set yet.")

    # ================================================================ settings tab
    def _show_cache(self) -> None:
        size = _dir_size(DOWNLOAD_DIR) if os.path.isdir(DOWNLOAD_DIR) else 0
        self.cache_lbl.config(text=f"{size / 1e9:.2f} GB" if size > 1e8 else f"{size / 1e6:.0f} MB")

    def _clear_cache(self) -> None:
        if self.busy or not os.path.isdir(DOWNLOAD_DIR):
            return
        if messagebox.askyesno("UbiClipper", "Delete all downloaded link audio and clip "
                                             "pieces? They download again when needed."):
            shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
            if self.remote:   # the open link's audio is gone now
                self.remote.audio_path = ""
            self._show_cache()

    # ---------------------------------------------------------------- AI
    def _judge_toggled(self) -> None:
        if self.ai_judge.get() and not self.rank_on.get():
            self.rank_on.set(True)      # the judge reads the transcript
        self._show_models()

    # ------------------------------------------------------------ get ready
    def _maybe_get_ready(self) -> None:
        """First start (or essentials missing): offer the downloads."""
        from clipper import getready
        st = getready.status(MODELS.get(self.sub_model.get(), getready.WHISPER_DEFAULT))
        essentials = all(st[it.key] for it in getready.ITEMS if it.required)
        extras_missing = any(st[k] is False for k in ("judge", "gpu"))
        if not essentials or (extras_missing and not self.cfg.get("ready_asked")):
            self._open_ready()

    def _open_ready(self) -> None:
        from ready_window import ReadyWindow
        if getattr(self, "_ready_win", None) and self._ready_win.winfo_exists():
            self._ready_win.lift()
            return

        def closed():
            self.cfg["ready_asked"] = True
            save_settings(self.cfg)
            self._show_models()
        self._ready_win = ReadyWindow(
            self, MODELS.get(self.sub_model.get(), "large-v3-turbo"), on_close=closed)

    def _show_models(self) -> None:
        from clipper import judge as J
        size = J.downloaded_bytes()
        if J.is_downloaded():
            txt = f"Downloaded ({size / 1e9:.1f} GB)"
            hint = "Ready. Moments get an AI score, a reason and a title idea."
        elif size:
            txt = f"Partly downloaded ({size / 1e9:.1f} of ~{J.APPROX_GB:.0f} GB)"
            hint = "Finishes downloading on the next Analyze (or Settings → Download now)."
        else:
            txt = f"Not downloaded (~{J.APPROX_GB:.0f} GB)"
            hint = (f"Downloads once (~{J.APPROX_GB:.0f} GB) on the first Analyze, or now "
                    "in Settings → AI models.")
        self.models_lbl.config(text=txt)
        self.judge_lbl.config(text=hint if self.ai_judge.get() else "")

    def _download_judge(self) -> None:
        if self.busy:
            return
        from clipper import judge as J
        if J.is_downloaded():
            self.status.config(text="The AI judge is already downloaded.")
            return
        self.mode = "models"

        def work():
            J.download(lambda m: self._progress(m, 0.0), self.cancel.is_set)
            return None
        self._run(work)

    def _test_judge(self) -> None:
        if self.busy:
            return
        from clipper import judge as J
        if not J.is_downloaded():
            messagebox.showinfo("UbiClipper", "Download the AI judge first "
                                              "(Download now).")
            return
        self.mode = "judgetest"
        sample = J.Moment(
            "[0:01] abi dur dur dur ne yapıyorsun\n[0:04] gemi batıyor gemi batıyor\n"
            "[0:07] ahahaha ben bittim ya\n[0:10] kim bu gemiyi buraya koydu",
            ["laughter (strong)", "explosions/gunfire"], ["KEKW", "kdkdkdkd", "OMEGALUL"],
            "Iron Nest", "tr")

        def work():
            import time
            t = time.time()
            j = J.get_judge(lambda m: self._progress(m, 0.0))
            v = j.rate([sample])[0]
            return (j.device, v, time.time() - t)
        self._run(work)

    def _delete_judge(self) -> None:
        from clipper import judge as J
        if self.busy or not J.downloaded_bytes():
            return
        if messagebox.askyesno("UbiClipper", "Delete the AI judge model (~4 GB)? It "
                                             "downloads again when you use it."):
            J.delete_model()
            self._show_models()

    def _open_roadmap(self) -> None:
        import webbrowser
        page = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roadmap.html")
        webbrowser.open("file:///" + page.replace("\\", "/").lstrip("/"))

    def _check_setup(self) -> None:
        here = os.path.dirname(os.path.abspath(__file__))
        out = subprocess.run([sys.executable, os.path.join(here, "check_setup.py")],
                             capture_output=True, text=True, cwd=here).stdout
        win = tk.Toplevel(self)
        win.title("Setup check")
        txt = tk.Text(win, width=110, height=24, relief="flat", padx=12, pady=10,
                      font=("Consolas", 10))
        txt.insert("1.0", out or "No output.")
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True)

    # ================================================================ work
    def _settings(self) -> ClipSettings:
        mc = self.max_clips.get().strip()
        lo, hi = float(self.min_len.get()), float(self.max_len.get())
        return ClipSettings(max_len=max(hi, lo), min_len=min(lo, hi),
                            pre_roll=float(self.pre_roll.get()),
                            sensitivity=float(self.sens.get()),
                            voice_focus=float(self.focus.get()),
                            audio_track=self._track(),
                            max_clips=int(mc) if mc.isdigit() else None)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.cancel.clear()
        self.analyze_btn.config(state="disabled" if busy else "normal")
        self.cancel_btn.config(state="normal" if busy else "disabled")
        self.export_btn.config(state="disabled" if busy or not self.result else "normal")
        self.post_btn.config(state="disabled" if busy else "normal")

    def _run(self, fn) -> None:
        def work():
            try:
                self.events.put(("done", fn()))
            except InterruptedError:
                self.events.put(("cancelled", None))
            except Exception as e:  # surfaced to the user
                self.events.put(("error", e))
        self._set_busy(True)
        threading.Thread(target=work, daemon=True).start()

    def _progress(self, msg: str, f: float) -> None:
        self.events.put(("progress", (msg, f)))

    def start_analyze(self) -> None:
        if not self.video:
            messagebox.showinfo("UbiClipper", "Open a video or paste a link first.")
            return
        self._collect()
        settings = self._settings()
        rank = None
        judge = self.ai_judge.get()
        if self.rank_on.get() or judge:
            ok, msg = check_available()
            if ok:
                rank = self._transcribe_opts()
            else:
                self.status.config(text="Ranking by words is off: subtitles engine unavailable.")
        self.mode = "analyze"
        remote = self.remote
        chat = self.chat if self.chat_on.get() else None

        def work():
            game = (remote.game if remote and remote.game else self.post_game.get().strip())
            res = analyze(self.video, settings, self._progress, self.cancel.is_set,
                          rank=rank, chat=chat, listen=self.ai_listen.get(),
                          ai_judge=judge, game=game)
            res.remote = remote
            return res

        self._run(work)

    def _transcribe_opts(self) -> TranscribeOptions:
        return TranscribeOptions(language=LANGUAGES[self.sub_lang.get()],
                                 model=MODELS[self.sub_model.get()],
                                 custom_words=self.sub_words.get(),
                                 also_language=LANGUAGES.get(self.sub_also.get()))

    def _max_speakers(self) -> int:
        if not self.spk_on.get():
            return 0
        v = self.spk_people.get()
        return int(v) if v.isdigit() else 10

    def start_export(self) -> None:
        if not self.result:
            return
        keep = [c for c in self.result.clips if self.checked.get(self._iid(c), True)]
        if not keep:
            messagebox.showinfo("UbiClipper", "No clips are checked.")
            return
        root = self.cfg.get("export_root")
        if not root or not os.path.isdir(root):
            messagebox.showinfo("UbiClipper",
                                "Choose a folder for your clips. It's remembered, and each "
                                "video gets its own subfolder inside it.")
            if not self.choose_root():
                return
            root = self.cfg["export_root"]

        subs = None
        if self.sub_on.get():
            ok, msg = check_available()
            if not ok:
                if not messagebox.askyesno(
                        "Subtitles unavailable",
                        msg + "\n\nExport the clips without subtitles?"):
                    return
                self.sub_on.set(False)
            else:
                self.status.config(text=msg)
        if self.sub_on.get():
            self.style_.speaker_colors = self.spk_on.get()
            subs = SubtitleOptions(transcribe=self._transcribe_opts(), style=self.style_,
                                   max_speakers=self._max_speakers())
        self._collect()
        res = AnalysisResult(self.result.info, keep, self.result.timeline,
                             self.result.settings, self.result.seconds_taken,
                             self.result.remote)
        out = clip_folder(root, self.result.info.path, res.title)
        self.mode = "export"
        self.export_dir = out
        vertical = self.layout if self.vert_on.get() else None
        post = PostInfo(self.post_channel.get().strip(),
                        self.post_platform.get().lower(), self.post_game.get().strip())
        full = self.full_on.get()
        self._run(lambda: export(res, out, self._progress, self.cancel.is_set,
                                 subtitles=subs, vertical=vertical, post_info=post,
                                 fullscreen=full))

    def preview(self) -> None:
        sel = self.tree.selection()
        if not sel or not self.result or self.busy:
            return
        clip = next(c for c in self.result.clips if self._iid(c) == sel[0])
        self.preview_range(clip.start, clip.end, sel[0])

    def preview_range(self, start: float, end: float, tag: str = "x") -> None:
        """Cut start..end and open it in the system video player."""
        if self.busy or not self.result:
            return
        if self.remote:
            rv = self.remote

            def work():
                return rv.download_section(start, end, lambda m, f: self._progress(m, f),
                                           self.cancel.is_set)
            self.mode = "frames"
            self._frames_then = open_path
            self._run(work)
            return
        tmp = os.path.join(tempfile.gettempdir(), f"ubiclipper_preview_{tag}.mp4")
        self.status.config(text="Rendering preview…")
        self.update_idletasks()
        try:
            cut_clip(self.result.info.path, tmp, start, max(0.5, end - start),
                     preset="ultrafast")
            open_path(tmp)
            self.status.config(text="")
        except Exception as e:
            messagebox.showerror("Preview failed", str(e))

    def trim(self) -> None:
        sel = self.tree.selection()
        if not sel or not self.result or self.busy:
            return
        clip = next(c for c in self.result.clips if self._iid(c) == sel[0])
        from trim_editor import TrimEditor
        TrimEditor(self, clip, self.result, self._trimmed)

    def edit_subtitles(self) -> None:
        sel = self.tree.selection()
        if not sel or not self.result or self.busy:
            return
        clip = next(c for c in self.result.clips if self._iid(c) == sel[0])
        from subtitle_editor import SubtitleEditor
        SubtitleEditor(self, clip, self._subs_edited)

    def _subs_edited(self, clip) -> None:
        self._show_detail()
        self.status.config(text="Subtitles saved for this clip. Export uses them as they are.")

    def _trimmed(self, clip) -> None:
        self._fill(keep_checks=True)
        self._show_detail()
        self.status.config(text=f"Clip trimmed: {hms(clip.start)} – {hms(clip.end)}")

    def open_post(self) -> None:
        if self.busy:
            return
        PostDialog(self, self.export_dir, self.accounts.store)

    # ================================================================ list
    def _iid(self, c) -> str:
        """Stable row id (start times change when a clip is trimmed)."""
        return f"c{next(k for k, x in enumerate(self.result.clips) if x is c)}"

    def _set_check(self, iid: str, on: bool) -> None:
        self.checked[iid] = on
        self.tree.set(iid, "use", "☑" if on else "☐")
        self.tree.item(iid, tags=() if on else ("off",))

    def _toggle(self, event) -> None:
        if self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if iid:
            self._set_check(iid, not self.checked.get(iid, True))

    def _toggle_key(self, _e=None) -> None:
        for iid in self.tree.selection():
            self._set_check(iid, not self.checked.get(iid, True))

    def _check_all(self, on: bool) -> None:
        for iid in self.tree.get_children():
            self._set_check(iid, on)

    def _custom_clips(self) -> None:
        if self.max_clips.get() != i18n.t("Custom…"):
            return
        n = simpledialog.askinteger("UbiClipper", "How many clips at most? (1-500)",
                                    minvalue=1, maxvalue=500, parent=self)
        self.max_clips.set(str(n) if n else "auto")

    def _sort_by(self, col: str) -> None:
        """Click a column heading: sort by it (click again to flip)."""
        if not self.result:
            return
        if self.sort_col == col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col, self.sort_desc = col, col in ("score", "ai", "len")
        self._fill(keep_checks=True)

    def _sort_value(self, c):
        return {"rank": -c.score, "score": c.score, "start": c.start, "len": c.duration,
                "ai": (c.ai or {}).get("score", -1)}.get(self.sort_col, c.score)

    def _fill(self, keep_checks: bool = False) -> None:
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        if not keep_checks:
            self.checked.clear()
        rank = {id(c): i for i, c in enumerate(sorted(self.result.clips, key=lambda c: -c.score), 1)}
        rows = sorted(self.result.clips, key=self._sort_value,
                      reverse=self.sort_desc and self.sort_col != "rank")
        for c in rows:
            iid = self._iid(c)
            on = self.checked.setdefault(iid, True)
            self.tree.insert("", "end", iid=iid, tags=() if on else ("off",), values=(
                "☑" if on else "☐", rank[id(c)], hms(c.start), f"{c.duration:.0f}s",
                f"{c.score:.2f}", f"{c.ai['score']:.0f}/10" if c.ai else "–",
                ", ".join(c.reasons)))
        for col, name in self._col_names.items():
            arrow = (" ▼" if self.sort_desc else " ▲") if col == self.sort_col else ""
            self.tree.heading(col, text=i18n.t(name) + arrow)
        n = len(self.result.clips)
        self.count_lbl.config(text=f"{n} moment{'s' if n != 1 else ''} · untick what you "
                                   "don't want · double-click to preview")
        kids = self.tree.get_children()
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])
        elif kids:
            self.tree.selection_set(kids[0])

    def _show_detail(self) -> None:
        sel = self.tree.selection()
        if not sel or not self.result:
            return
        clip = next((c for c in self.result.clips if self._iid(c) == sel[0]), None)
        if not clip:
            return
        head = f"{hms(clip.start)} – {hms(clip.end)}   ·   {', '.join(clip.reasons)}"
        said = ""
        t = clip.transcript or {}
        if t.get("words"):
            words = Transcript.from_dict(t).words
            said = "“" + " ".join(w.text for w in words)[:260] + "”"
            try:
                from clipper.posts import suggest
                title = suggest(words, clip.reasons, t.get("language"),
                                (self.remote.game if self.remote else self.post_game.get()),
                                censor=False)["titles"][0]
                said = f"Title idea: {title}\n{said}"
            except Exception:
                pass
        if clip.ai:
            said = (f"AI judge: {clip.ai.get('score', 0):.0f}/10 – {clip.ai.get('why', '')}\n"
                    + (f"AI title: {clip.ai['title']}\n" if clip.ai.get("title") else "")
                    + said)
        if t.get("edited"):
            said = "✎ Subtitles edited by hand\n" + said
        self.det_title.config(text=head)
        self.det_text.config(text=said or "Tip: turn on 'Rank by what's said' to see what was "
                                          "said in each moment here.")

    # ================================================================ events
    def _finished_export(self, warning: str | None = None) -> None:
        self._set_busy(False)
        self.bar["value"] = 1.0
        self._collect()
        ready = self.export_dir
        if warning:
            self.status.config(text="Exported, but some steps failed.")
            messagebox.showwarning("UbiClipper", warning)
        else:
            self.status.config(text=f"Export finished: {self.export_dir}")
        choice = messagebox.askyesnocancel(
            "Done", "Clips exported.\n\nYes: post them now (Export All)\n"
                    "No: open the export folder\nCancel: close")
        if choice:
            self.open_post()
        elif choice is False and os.path.isdir(ready):
            open_path(ready)

    def _poll(self) -> None:
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "progress":
                    msg, f = data
                    self.status.config(text=msg)
                    self.bar["value"] = f
                elif kind == "done" and self.mode == "link":
                    self._set_busy(False)
                    rv, info, chat, note = data
                    self._set_source(rv.audio_path, info, rv, f"🔗 {rv.title}")
                    self.chat, self.chat_note = chat, note
                    self.status.config(text=f"Audio downloaded ({note}). Click Analyze.")
                    self.bar["value"] = 0
                    self._show_cache()
                elif kind == "done" and self.mode == "models":
                    self._set_busy(False)
                    self.bar["value"] = 0
                    self.status.config(text="AI judge downloaded.")
                    self._show_models()
                elif kind == "done" and self.mode == "judgetest":
                    self._set_busy(False)
                    self.bar["value"] = 0
                    dev, v, secs = data
                    self.status.config(text=f"AI judge works ({dev.upper()}, {secs:.0f}s).")
                    messagebox.showinfo(
                        "AI judge test",
                        "Made-up moment: ship sinks, streamer can't stop laughing, chat "
                        f"spams KEKW.\n\nScore: {v.score:.0f}/10\nWhy: {v.why or '–'}\n"
                        f"Title: {v.title or '–'}\n\nRan on: {dev.upper()} "
                        f"({secs:.0f} s incl. loading)" if v.ok else
                        "The AI answered, but not in the expected format. Analysis "
                        "still works; that moment just gets no AI score.")
                elif kind == "done" and self.mode == "clipdl":
                    self._set_busy(False)
                    self.bar["value"] = 0
                    self._show_cache()
                    self._clip_downloaded(data)
                elif kind == "done" and self.mode == "frames":
                    self._set_busy(False)
                    self.status.config(text="")
                    self.bar["value"] = 0
                    self._frames_then(data)
                elif kind == "done":
                    if self.mode == "analyze":
                        self.result = data
                        self._fill()
                        self.status.config(
                            text=f"Found {len(data.clips)} clips in "
                                 f"{data.seconds_taken:.0f}s."
                                 + (f"  ⚠ {data.notes[0]}" if data.notes else ""))
                        self._show_models()
                        self._set_busy(False)
                    else:
                        self._finished_export()
                elif kind == "cancelled":
                    self._set_busy(False)
                    self.status.config(text="Cancelled.")
                    self.bar["value"] = 0
                    self._show_models()
                elif kind == "error" and isinstance(data, PartialExport):
                    self._finished_export(str(data))
                elif kind == "error" and isinstance(data, YtDlpMissing):
                    self._set_busy(False)
                    self.status.config(text="")
                    messagebox.showerror("UbiClipper", str(data) +
                                         "\n\n(run_windows.bat installs it automatically.)")
                elif kind == "error":
                    self._set_busy(False)
                    self.status.config(text="Error.")
                    messagebox.showerror("UbiClipper", str(data))
        except queue.Empty:
            pass
        self.after(100, self._poll)


if __name__ == "__main__":
    App().mainloop()
