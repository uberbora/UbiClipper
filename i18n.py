"""App language (interface translation).

The code is written in English. Every text that reaches the screen (labels,
buttons, tabs, column headings, window titles, message boxes, progress
messages from the engine) goes through t(), which looks it up in
languages/<code>.json:

    {"name": "Türkçe",
     "strings":  {"Open video…": "Video aç…",
                  "Clip {0}/{1}: {2}": "Klip {0}/{1}: {2}"},   <- templates
     "help":     {"max_clips": "…"}}                            <- ⓘ texts

Templates with {0}, {1}… match texts built at runtime; the parts in the
braces are translated too. Anything without a translation stays English, so
a half-finished language file still works. To add a language, copy
languages/tr.json, translate the right-hand sides and pick it in Settings.
"""

from __future__ import annotations

import json
import locale
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
LANG_DIR = os.path.join(HERE, "languages")

_strings: dict[str, str] = {}
_help: dict[str, str] = {}
_patterns: list[tuple[re.Pattern, str]] = []
current = "en"


def available() -> dict[str, str]:
    """code -> display name, English first."""
    out = {"en": "English"}
    if os.path.isdir(LANG_DIR):
        for f in sorted(os.listdir(LANG_DIR)):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(LANG_DIR, f), encoding="utf-8") as fh:
                        out[f[:-5]] = json.load(fh).get("name", f[:-5])
                except (OSError, ValueError):
                    pass
    return out


def system_locale() -> str:
    """Two-letter code of the Windows / OS display language ('' if unknown)."""
    try:
        code = (locale.getlocale()[0] or "")
        if not code and os.name == "nt":
            import ctypes
            code = locale.windows_locale.get(
                ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
    except Exception:
        code = ""
    low = code.lower()
    names = {"turkish": "tr", "english": "en", "german": "de", "spanish": "es",
             "french": "fr", "italian": "it", "portuguese": "pt", "russian": "ru",
             "polish": "pl", "arabic": "ar", "dutch": "nl", "japanese": "ja",
             "korean": "ko", "chinese": "zh"}
    for name, c in names.items():      # 'Turkish_Turkey' on some Windows builds
        if low.startswith(name):
            return c
    return low[:2]


def system_language() -> str:
    """The OS language, if we have a translation of the app for it."""
    code = system_locale()
    return code if code in available() else "en"


def set_language(code: str | None) -> str:
    global current
    _strings.clear()
    _help.clear()
    _patterns.clear()
    current = code or "en"
    if current == "en":
        return current
    path = os.path.join(LANG_DIR, current + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        current = "en"
        return current
    _strings.update(data.get("strings", {}))
    _help.update(data.get("help", {}))
    for src, dst in _strings.items():
        if re.search(r"\{\d+\}", src):
            parts = re.split(r"(\{\d+\})", src)
            literal = "".join(p for p in parts if not re.fullmatch(r"\{\d+\}", p))
            # tiny templates like "{0}s" or "{0} GB" only ever wrap numbers;
            # don't let them grab arbitrary text (titles, transcripts…)
            grp = r"[\d.,:~\-]+" if len(literal.strip()) <= 3 else ".*?"
            rx = "".join(f"(?P<g{p[1:-1]}>{grp})" if re.fullmatch(r"\{\d+\}", p)
                         else re.escape(p) for p in parts)
            _patterns.append((re.compile("^" + rx + "$", re.S), dst))
    # longest templates first: more specific wins
    _patterns.sort(key=lambda p: -len(p[0].pattern))
    return current


def t(text):
    """Translate one on-screen text (unknown texts are returned unchanged)."""
    if current == "en" or not isinstance(text, str) or not text.strip():
        return text
    hit = _strings.get(text)
    if hit is not None:
        return hit
    for rx, dst in _patterns:
        m = rx.match(text)
        if m:
            vals = {k[1:]: t(v) for k, v in m.groupdict().items()}
            try:
                return dst.format(*[vals[str(i)] for i in range(len(vals))])
            except (IndexError, KeyError):
                return text
    if ", " in text:          # lists of reasons: "Laughter, Scream"
        parts = text.split(", ")
        tr = [t(p) for p in parts]
        if tr != parts:
            return ", ".join(tr)
    if "\n" in text:
        lines = text.split("\n")
        tr = [t(x) for x in lines]
        if tr != lines:
            return "\n".join(tr)
    return text


def upper(text: str) -> str:
    """Upper-case in the app language (Turkish: i -> İ, ı -> I)."""
    if current in ("tr", "az"):
        text = text.replace("i", "İ").replace("ı", "I")
    return text.upper()


def help_text(key: str, english: str) -> str:
    return _help.get(key, english) if current != "en" else english


# ------------------------------------------------------------------ Tk hooks
_installed = False


def install() -> None:
    """Translate texts as Tk widgets receive them (no change to app code)."""
    global _installed
    if _installed:
        return
    _installed = True
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    orig_options = tk.Misc._options

    def _options(self, cnf, kw=None):
        def fix(d):
            if isinstance(d, dict):
                for k in ("text", "label", "title"):
                    if isinstance(d.get(k), str):
                        d = dict(d)
                        d[k] = t(d[k])
            return d
        return orig_options(self, fix(cnf), fix(kw))
    tk.Misc._options = _options

    orig_title = tk.Wm.wm_title

    def wm_title(self, string=None):
        return orig_title(self, t(string) if isinstance(string, str) else string)
    tk.Wm.wm_title = tk.Wm.title = wm_title

    orig_add = ttk.Notebook.add

    def nb_add(self, child, **kw):
        if "text" in kw:
            kw["text"] = t(kw["text"])
        return orig_add(self, child, **kw)
    ttk.Notebook.add = nb_add

    orig_heading = ttk.Treeview.heading

    def heading(self, column, option=None, **kw):
        if "text" in kw:
            kw["text"] = t(kw["text"])
        return orig_heading(self, column, option, **kw)
    ttk.Treeview.heading = heading

    def _vals(kw):
        if "values" in kw and isinstance(kw["values"], (list, tuple)):
            kw["values"] = tuple(t(v) if isinstance(v, str) else v for v in kw["values"])
        return kw
    orig_insert = ttk.Treeview.insert

    def insert(self, parent, index, iid=None, **kw):
        return orig_insert(self, parent, index, iid, **_vals(kw))
    ttk.Treeview.insert = insert

    orig_set = ttk.Treeview.set

    def tv_set(self, item, column=None, value=None):
        return orig_set(self, item, column, t(value) if isinstance(value, str) else value)
    ttk.Treeview.set = tv_set

    for name in ("showinfo", "showwarning", "showerror", "askyesno",
                 "askyesnocancel", "askokcancel", "askquestion", "askretrycancel"):
        fn = getattr(messagebox, name)

        def wrap(fn=fn):
            def inner(title=None, message=None, **kw):
                return fn(t(title), t(message), **kw)
            return inner
        setattr(messagebox, name, wrap())

    from tkinter import simpledialog
    orig_ask = simpledialog.askstring

    def askstring(title, prompt, **kw):
        return orig_ask(t(title), t(prompt), **kw)
    simpledialog.askstring = askstring
    orig_int = simpledialog.askinteger

    def askinteger(title, prompt, **kw):
        return orig_int(t(title), t(prompt), **kw)
    simpledialog.askinteger = askinteger

    for name in ("askopenfilename", "askdirectory", "asksaveasfilename"):
        fn = getattr(filedialog, name)

        def wrapf(fn=fn):
            def inner(**kw):
                if "title" in kw:
                    kw["title"] = t(kw["title"])
                return fn(**kw)
            return inner
        setattr(filedialog, name, wrapf())
