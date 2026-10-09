"""Dark / light theme for the whole app, built on ttk's 'clam' engine.

No extra packages (nothing for Windows Smart App Control to block).
apply_theme() can be called again at runtime to switch themes instantly.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

PALETTES = {
    "dark": {
        "bg": "#121318", "panel": "#181A21", "card": "#1F222A", "input": "#2A2E38",
        "border": "#343946", "text": "#ECEDF2", "muted": "#9AA1B2",
        "accent": "#8B5CF6", "accent_hover": "#7A4AE8", "accent_text": "#FFFFFF",
        "select": "#3A2E66", "ok": "#22C55E", "warn": "#F59E0B", "bad": "#EF4444",
        "tooltip_bg": "#2A2E38", "tooltip_fg": "#ECEDF2",
    },
    "light": {
        "bg": "#F2F3F7", "panel": "#FFFFFF", "card": "#FFFFFF", "input": "#F5F6FA",
        "border": "#D8DBE4", "text": "#1B1D24", "muted": "#5E6575",
        "accent": "#7C3AED", "accent_hover": "#6D28D9", "accent_text": "#FFFFFF",
        "select": "#E6DCFF", "ok": "#16A34A", "warn": "#D97706", "bad": "#DC2626",
        "tooltip_bg": "#FFFFE8", "tooltip_fg": "#1B1D24",
    },
}

current: dict = dict(PALETTES["dark"])
_listeners: list = []


def on_change(fn) -> None:
    """Call fn(palette) whenever the theme changes (for non-ttk widgets)."""
    _listeners.append(fn)


def _family(root: tk.Misc) -> str:
    fams = {f.lower(): f for f in tkfont.families(root)}
    for f in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue",
              "DejaVu Sans", "Arial", "Helvetica"):
        if f.lower() in fams:
            return fams[f.lower()]
    # keep whatever the system default font is
    return tkfont.nametofont("TkDefaultFont", root=root).actual("family")


def apply_theme(root: tk.Misc, mode: str = "dark") -> dict:
    p = PALETTES.get(mode, PALETTES["dark"])
    current.clear()
    current.update(p, mode=mode)
    fam = _family(root)
    base, small, bold = (fam, 10), (fam, 9), (fam, 10, "bold")
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        try:
            tkfont.nametofont(name).configure(family=fam, size=10)
        except tk.TclError:
            pass

    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=p["bg"], foreground=p["text"], fieldbackground=p["input"],
                bordercolor=p["border"], lightcolor=p["card"], darkcolor=p["card"],
                troughcolor=p["input"], focuscolor=p["accent"], selectbackground=p["select"],
                selectforeground=p["text"], insertcolor=p["text"], font=base,
                arrowcolor=p["muted"])
    s.map(".", foreground=[("disabled", p["muted"])])

    # surfaces
    s.configure("TFrame", background=p["bg"])
    s.configure("Panel.TFrame", background=p["panel"])
    s.configure("Card.TFrame", background=p["card"])
    for sty, bgc in (("TLabel", p["bg"]), ("Panel.TLabel", p["panel"]), ("Card.TLabel", p["card"])):
        s.configure(sty, background=bgc, foreground=p["text"])
    s.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"], font=small)
    s.configure("CardMuted.TLabel", background=p["card"], foreground=p["muted"], font=small)
    s.configure("PanelMuted.TLabel", background=p["panel"], foreground=p["muted"], font=small)
    s.configure("Title.TLabel", background=p["panel"], foreground=p["text"], font=(fam, 17, "bold"))
    s.configure("Brand.TLabel", background=p["panel"], foreground=p["accent"], font=(fam, 17, "bold"))
    s.configure("H2.TLabel", background=p["card"], foreground=p["text"], font=(fam, 11, "bold"))
    s.configure("Section.TLabel", background=p["card"], foreground=p["accent"],
                font=(fam, 9, "bold"))
    s.configure("Help.TLabel", background=p["card"], foreground=p["accent"], font=small)
    s.configure("PanelHelp.TLabel", background=p["panel"], foreground=p["accent"], font=small)
    s.configure("Ok.TLabel", background=p["card"], foreground=p["ok"], font=bold)
    s.configure("Bad.TLabel", background=p["card"], foreground=p["muted"], font=small)

    # buttons
    s.configure("TButton", background=p["input"], foreground=p["text"], bordercolor=p["border"],
                lightcolor=p["input"], darkcolor=p["input"], padding=(12, 6), relief="flat",
                focusthickness=0, focuscolor=p["input"])
    s.map("TButton", background=[("disabled", p["card"]), ("pressed", p["border"]),
                                 ("active", p["border"])],
          lightcolor=[("active", p["border"])], darkcolor=[("active", p["border"])])
    s.configure("Accent.TButton", background=p["accent"], foreground=p["accent_text"],
                bordercolor=p["accent"], lightcolor=p["accent"], darkcolor=p["accent"],
                padding=(18, 8), font=bold, focuscolor=p["accent"])
    s.map("Accent.TButton",
          background=[("disabled", p["input"]), ("pressed", p["accent_hover"]),
                      ("active", p["accent_hover"])],
          foreground=[("disabled", p["muted"])],
          lightcolor=[("active", p["accent_hover"])], darkcolor=[("active", p["accent_hover"])],
          bordercolor=[("disabled", p["border"])])
    s.configure("Small.TButton", padding=(8, 3), font=small)

    # toggles
    for sty, bgc in (("TCheckbutton", p["card"]), ("TRadiobutton", p["card"]),
                     ("Panel.TCheckbutton", p["panel"])):
        s.configure(sty, background=bgc, foreground=p["text"], indicatorbackground=p["input"],
                    indicatorforeground=p["accent_text"], indicatormargin=(0, 0, 8, 0),
                    focuscolor=bgc, padding=(0, 3))
        s.map(sty, indicatorbackground=[("selected", p["accent"]), ("active", p["border"])],
              background=[("active", bgc)])

    # inputs
    for sty in ("TEntry", "TCombobox", "TSpinbox"):
        s.configure(sty, fieldbackground=p["input"], background=p["input"], foreground=p["text"],
                    bordercolor=p["border"], lightcolor=p["input"], darkcolor=p["input"],
                    padding=5, arrowcolor=p["muted"], insertcolor=p["text"])
        s.map(sty, fieldbackground=[("readonly", p["input"]), ("disabled", p["card"])],
              bordercolor=[("focus", p["accent"])], lightcolor=[("focus", p["accent"])],
              foreground=[("disabled", p["muted"])], selectbackground=[("readonly", p["input"])],
              selectforeground=[("readonly", p["text"])])
    root.option_add("*TCombobox*Listbox.background", p["input"])
    root.option_add("*TCombobox*Listbox.foreground", p["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["select"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["text"])
    root.option_add("*TCombobox*Listbox.font", base)

    # sliders, progress
    s.configure("Horizontal.TScale", background=p["accent"], troughcolor=p["input"],
                bordercolor=p["card"], lightcolor=p["accent"], darkcolor=p["accent"])
    s.configure("Horizontal.TProgressbar", background=p["accent"], troughcolor=p["input"],
                bordercolor=p["panel"], lightcolor=p["accent"], darkcolor=p["accent"], thickness=8)

    # tabs
    s.configure("TNotebook", background=p["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
    s.configure("TNotebook.Tab", background=p["bg"], foreground=p["muted"], padding=(14, 8),
                bordercolor=p["bg"], lightcolor=p["bg"], darkcolor=p["bg"], font=bold)
    s.map("TNotebook.Tab", background=[("selected", p["card"]), ("active", p["panel"])],
          foreground=[("selected", p["text"]), ("active", p["text"])],
          lightcolor=[("selected", p["card"])], bordercolor=[("selected", p["card"])])

    # clip list
    s.configure("Treeview", background=p["card"], fieldbackground=p["card"],
                foreground=p["text"], bordercolor=p["card"], lightcolor=p["card"],
                darkcolor=p["card"], rowheight=30)
    s.map("Treeview", background=[("selected", p["select"])],
          foreground=[("selected", p["text"])])
    s.configure("Treeview.Heading", background=p["panel"], foreground=p["muted"],
                bordercolor=p["card"], lightcolor=p["panel"], darkcolor=p["panel"],
                relief="flat", font=(fam, 9, "bold"), padding=(6, 6))
    s.map("Treeview.Heading", background=[("active", p["input"])])
    s.configure("Vertical.TScrollbar", background=p["input"], troughcolor=p["card"],
                bordercolor=p["card"], lightcolor=p["input"], darkcolor=p["input"],
                arrowcolor=p["muted"], gripcount=0)
    s.map("Vertical.TScrollbar", background=[("active", p["border"])])
    s.configure("TSeparator", background=p["border"])
    s.configure("TPanedwindow", background=p["bg"])
    s.configure("Sash", sashthickness=6, gripcount=0, background=p["bg"])

    # classic Tk widgets (dialogs, text boxes, canvases)
    root.option_add("*Toplevel.background", p["bg"])
    root.option_add("*Text.background", p["input"])
    root.option_add("*Text.foreground", p["text"])
    root.option_add("*Text.insertBackground", p["text"])
    root.option_add("*Text.font", base)
    root.option_add("*Canvas.background", p["bg"])
    try:
        root.configure(background=p["bg"])
    except tk.TclError:
        pass
    for fn in list(_listeners):
        try:
            fn(current)
        except Exception:
            pass
    return current
