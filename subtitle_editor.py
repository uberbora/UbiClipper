"""Subtitle editor: fix the words, the timing and who said each line.

Opens for one clip. Every line of the clip's subtitles is listed with its
start, end, person (colour) and text. Select one or more lines to:
  - type the right words (Enter applies),
  - change start / end (or nudge them),
  - set who said it (several lines at once),
  - play just that line, split, merge with the next, delete, add a line.
Save keeps the edits: export then uses them as they are (no re-transcribing,
and hand-set colours aren't recalculated).

No subtitles yet (the clip wasn't ranked by words)? "Transcribe now" makes
them here first. "Detect speakers" colours the lines automatically, which
you can then correct.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np

import theme
from clipper.subtitles import SPEAKER_PALETTE
from clipper.transcribe import Transcript, Word
from trim_editor import fmt, parse

END_PUNCT = (".", "!", "?", "…")


def group_lines(words: list[Word], max_words: int = 8) -> list[dict]:
    """Words -> editable lines (roughly sentences, one person per line)."""
    lines: list[dict] = []
    cur: list[Word] = []
    for w in words:
        if cur and (w.speaker != cur[-1].speaker or w.start - cur[-1].end > 0.6
                    or cur[-1].text.endswith(END_PUNCT) or len(cur) >= max_words):
            lines.append(_line(cur))
            cur = []
        cur.append(w)
    if cur:
        lines.append(_line(cur))
    return lines


def _line(ws: list[Word]) -> dict:
    return {"start": ws[0].start, "end": ws[-1].end, "speaker": ws[0].speaker,
            "text": " ".join(w.text for w in ws), "lang": ws[0].lang,
            "orig": [(w.start, w.end, w.text, w.prob) for w in ws]}


def lines_to_words(lines: list[dict]) -> list[Word]:
    """Back to timed words. Unchanged lines keep Whisper's word timings; edited
    ones spread their words over the line by length."""
    out: list[Word] = []
    for ln in sorted(lines, key=lambda x: x["start"]):
        toks = ln["text"].split()
        if not toks:
            continue
        orig = ln.get("orig") or []
        same = (len(orig) == len(toks) and abs(orig[0][0] - ln["start"]) < 0.01
                and abs(orig[-1][1] - ln["end"]) < 0.01)
        if same:
            for (s, e, _, p), t in zip(orig, toks):
                out.append(Word(s, e, t, p, ln["speaker"], ln.get("lang", "")))
            continue
        a, b = ln["start"], max(ln["end"], ln["start"] + 0.2)
        weights = [len(t) + 1 for t in toks]
        total = sum(weights)
        t0 = a
        for t, wt in zip(toks, weights):
            t1 = t0 + (b - a) * wt / total
            out.append(Word(round(t0, 3), round(t1, 3), t, 1.0, ln["speaker"],
                            ln.get("lang", "")))
            t0 = t1
    return out


class SubtitleEditor(tk.Toplevel):
    def __init__(self, app, clip, on_save) -> None:
        super().__init__(app)
        self.app, self.clip, self.on_save = app, clip, on_save
        self.title("Edit subtitles")
        self.geometry("1000x620")
        self.minsize(820, 520)
        self.transient(app)
        t = clip.transcript or {}
        self.language = t.get("language") or "tr"
        tr = Transcript.from_dict(t) if t.get("words") else Transcript(self.language)
        self.lines = group_lines(tr.words)
        self.speakers_changed = bool(t.get("speakers_fixed"))
        self.dirty = False
        pal = getattr(app.style_, "palette", None) or SPEAKER_PALETTE
        self.palette = (list(pal) + SPEAKER_PALETTE)[:10]

        body = ttk.Frame(self, style="Card.TFrame", padding=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        head = ttk.Frame(body, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="we")
        ttk.Label(head, text="Edit subtitles", style="H2.TLabel").pack(side="left")
        ttk.Label(head, text=f"{fmt(clip.start)} – {fmt(clip.end)}",
                  style="CardMuted.TLabel").pack(side="left", padx=12)
        ttk.Button(head, text="Detect speakers", style="Small.TButton",
                   command=self.detect_speakers).pack(side="right")
        self.tx_btn = ttk.Button(head, text="Transcribe now", style="Small.TButton",
                                 command=self.transcribe)
        self.tx_btn.pack(side="right", padx=6)

        wrap = ttk.Frame(body, style="Card.TFrame")
        wrap.grid(row=1, column=0, sticky="nsew", pady=(12, 10))
        cols = ("start", "end", "who", "text")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="extended")
        for col, w, txt in (("start", 80, "Start"), ("end", 80, "End"), ("who", 90, "Person"),
                            ("text", 600, "Text")):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w, minwidth=w, anchor="w" if col == "text" else "center",
                             stretch=col == "text")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._load())
        self.tree.bind("<Double-1>", lambda e: self.play())

        ed = ttk.Frame(body, style="Card.TFrame")
        ed.grid(row=2, column=0, sticky="we")
        ed.columnconfigure(1, weight=1)
        ttk.Label(ed, text="Text", style="Card.TLabel").grid(row=0, column=0, sticky="w",
                                                            padx=(0, 10))
        self.v_text = tk.StringVar()
        self.e_text = ttk.Entry(ed, textvariable=self.v_text)
        self.e_text.grid(row=0, column=1, columnspan=3, sticky="we")
        self.e_text.bind("<Return>", lambda e: self.apply())
        row = ttk.Frame(ed, style="Card.TFrame")
        row.grid(row=1, column=0, columnspan=4, sticky="we", pady=(10, 0))
        self.v_start, self.v_end = tk.StringVar(), tk.StringVar()
        for label, var in (("Start", self.v_start), ("End", self.v_end)):
            ttk.Label(row, text=label, style="Card.TLabel").pack(side="left", padx=(0, 6))
            e = ttk.Entry(row, textvariable=var, width=10, justify="center")
            e.pack(side="left", padx=(0, 16))
            e.bind("<Return>", lambda ev: self.apply())
        ttk.Label(row, text="Person", style="Card.TLabel").pack(side="left", padx=(0, 6))
        self.v_who = tk.StringVar()
        self.who_box = ttk.Combobox(row, textvariable=self.v_who, state="readonly", width=12,
                                    values=[self._who(k) for k in range(10)])
        self.who_box.pack(side="left")
        self.who_box.bind("<<ComboboxSelected>>", lambda e: self.set_person())
        self.swatch = tk.Label(row, width=3, relief="flat")
        self.swatch.pack(side="left", padx=(6, 16))
        ttk.Button(row, text="Apply", style="Accent.TButton",
                   command=self.apply).pack(side="left")

        acts = ttk.Frame(body, style="Card.TFrame")
        acts.grid(row=3, column=0, sticky="we", pady=(12, 0))
        for txt, fn in (("▶  Play line", self.play), ("Split", self.split),
                        ("Merge with next", self.merge), ("Add line after", self.add),
                        ("Delete", self.delete)):
            ttk.Button(acts, text=txt, command=fn).pack(side="left", padx=(0, 6))
        ttk.Button(acts, text="Save", style="Accent.TButton",
                   command=self.save).pack(side="right")
        ttk.Button(acts, text="Cancel", command=self._cancel).pack(side="right", padx=8)
        self.note = ttk.Label(body, text="", style="CardMuted.TLabel")
        self.note.grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda e: self._cancel())
        self.refresh()
        if not self.lines:
            self.note.config(text="No subtitles for this clip yet: press Transcribe now.")

    # ------------------------------------------------------------ helpers
    def _who(self, k: int) -> str:
        from i18n import t
        return t("Person {0}").format(k + 1)

    def _color(self, k: int) -> str:
        return "#" + self.palette[k % len(self.palette)].lstrip("#")

    def refresh(self, keep: list[int] | None = None) -> None:
        self.lines.sort(key=lambda ln: ln["start"])
        self.tree.delete(*self.tree.get_children())
        for k in range(10):
            self.tree.tag_configure(f"p{k}", background=self._color(k), foreground="#111111")
        for i, ln in enumerate(self.lines):
            self.tree.insert("", "end", iid=str(i), tags=(f"p{ln['speaker'] % 10}",),
                             values=(fmt(ln["start"]), fmt(ln["end"]),
                                     self._who(ln["speaker"]), ln["text"]))
        if keep:
            ids = [str(i) for i in keep if i < len(self.lines)]
            if ids:
                self.tree.selection_set(ids)
                self.tree.see(ids[0])

    def _sel(self) -> list[int]:
        return sorted(int(i) for i in self.tree.selection())

    def _load(self) -> None:
        sel = self._sel()
        if not sel:
            return
        ln = self.lines[sel[0]]
        self.v_text.set(ln["text"] if len(sel) == 1 else "")
        self.v_start.set(fmt(ln["start"]))
        self.v_end.set(fmt(self.lines[sel[-1]]["end"]))
        self.v_who.set(self._who(ln["speaker"]))
        self.swatch.configure(background=self._color(ln["speaker"]))
        self.e_text.configure(state="normal" if len(sel) == 1 else "disabled")

    # ------------------------------------------------------------ editing
    def apply(self) -> None:
        sel = self._sel()
        if len(sel) != 1:
            return
        ln = self.lines[sel[0]]
        a, b = parse(self.v_start.get()), parse(self.v_end.get())
        if a is None or b is None or b <= a:
            messagebox.showinfo("UbiClipper", "Start must be before End (e.g. 0:00:03.5).",
                                parent=self)
            return
        ln["text"] = " ".join(self.v_text.get().split())
        ln["start"], ln["end"] = max(0.0, a), min(b, self.clip.duration + 1)
        self.dirty = True
        self.refresh(sel)

    def set_person(self) -> None:
        sel = self._sel()
        if not sel:
            return
        k = self.who_box.current()
        for i in sel:
            self.lines[i]["speaker"] = k
        self.speakers_changed = self.dirty = True
        self.swatch.configure(background=self._color(k))
        self.refresh(sel)

    def split(self) -> None:
        sel = self._sel()
        if len(sel) != 1:
            return
        ln = self.lines[sel[0]]
        toks = ln["text"].split()
        if len(toks) < 2:
            return
        half = len(toks) // 2
        mid = ln["start"] + (ln["end"] - ln["start"]) * (
            sum(len(t) + 1 for t in toks[:half]) / sum(len(t) + 1 for t in toks))
        second = dict(ln, start=mid, text=" ".join(toks[half:]), orig=[])
        ln.update(end=mid, text=" ".join(toks[:half]), orig=[])
        self.lines.insert(sel[0] + 1, second)
        self.dirty = True
        self.refresh([sel[0], sel[0] + 1])

    def merge(self) -> None:
        sel = self._sel()
        i = sel[0] if sel else None
        if i is None or i + 1 >= len(self.lines):
            return
        a, b = self.lines[i], self.lines.pop(i + 1)
        a.update(end=max(a["end"], b["end"]), text=(a["text"] + " " + b["text"]).strip(),
                 orig=(a.get("orig") or []) + (b.get("orig") or []))
        self.dirty = True
        self.refresh([i])

    def add(self) -> None:
        sel = self._sel()
        base = self.lines[sel[-1]] if sel else None
        start = base["end"] + 0.05 if base else 0.0
        nxt = self.lines[sel[-1] + 1]["start"] if sel and sel[-1] + 1 < len(self.lines) else None
        end = min(start + 1.5, nxt - 0.05) if nxt else start + 1.5
        new = {"start": start, "end": max(end, start + 0.3), "speaker":
               base["speaker"] if base else 0, "text": "…", "lang": "", "orig": []}
        self.lines.append(new)
        self.dirty = True
        self.refresh()
        idx = self.lines.index(new)
        self.tree.selection_set(str(idx))
        self.tree.see(str(idx))
        self._load()
        self.e_text.focus_set()
        self.e_text.select_range(0, "end")

    def delete(self) -> None:
        sel = self._sel()
        for i in reversed(sel):
            self.lines.pop(i)
        if sel:
            self.dirty = True
            self.refresh([max(0, sel[0] - 1)])

    def play(self) -> None:
        sel = self._sel()
        if not sel:
            return
        a, b = self.lines[sel[0]]["start"], self.lines[sel[-1]]["end"]
        c0 = self.clip.start
        self.app.preview_range(c0 + max(0.0, a - 0.3), c0 + b + 0.3, "subline")

    # ------------------------------------------------------------ AI helpers
    def _audio(self) -> np.ndarray:
        from clipper.media import stream_audio
        chunks = list(stream_audio(self.app.video, track=self.app.result.settings.audio_track,
                                   start=self.clip.start, duration=self.clip.duration))
        return np.concatenate(chunks) if chunks else np.zeros(1, np.float32)

    def _busy(self, msg: str, work, done) -> None:
        self.note.config(text=msg)
        self.configure(cursor="watch")
        out: dict = {}

        def run():
            try:
                out["ok"] = work()
            except Exception as e:
                out["err"] = e
        th = threading.Thread(target=run, daemon=True)
        th.start()

        def poll():
            if th.is_alive():
                self.after(250, poll)
                return
            self.configure(cursor="")
            if "err" in out:
                self.note.config(text="")
                messagebox.showerror("UbiClipper", str(out["err"]), parent=self)
            else:
                done(out["ok"])
        poll()

    def transcribe(self) -> None:
        if self.lines and not messagebox.askyesno(
                "UbiClipper", "Transcribe this clip again? Your edits in this window "
                              "are replaced.", parent=self):
            return
        from clipper.transcribe import check_available, get_transcriber
        ok, msg = check_available()
        if not ok:
            messagebox.showerror("UbiClipper", msg, parent=self)
            return
        opts = self.app._transcribe_opts()

        def work():
            tr = get_transcriber(opts).transcribe_audio(self._audio())
            return tr

        def done(tr):
            self.language = tr.language or self.language
            self.lines = group_lines(tr.words)
            self.speakers_changed = False
            self.dirty = True
            self.note.config(text=f"{len(tr.words)} words.")
            self.refresh()
        self._busy("Transcribing…", work, done)

    def detect_speakers(self) -> None:
        if not self.lines:
            return
        words = lines_to_words(self.lines)
        people = self.app._max_speakers() or 10

        def work():
            from clipper.speakers import diarize
            return diarize(self._audio(), words, max_speakers=people)

        def done(labels):
            for w, k in zip(words, labels):
                w.speaker = k
            self.lines = group_lines(words)
            self.speakers_changed = self.dirty = True
            self.note.config(text=f"{len(set(labels)) or 1} person(s) found. Fix any line by "
                                  "selecting it and picking the person.")
            self.refresh()
        self._busy("Listening to voices…", work, done)

    # ------------------------------------------------------------ save
    def save(self) -> None:
        sel = self._sel()
        if len(sel) == 1 and " ".join(self.v_text.get().split()) != self.lines[sel[0]]["text"]:
            self.apply()                # typed but didn't press Enter
        words = lines_to_words(self.lines)
        t = dict(self.clip.transcript or {})
        t.update(Transcript(self.language, words).to_dict(), edited=True)
        if self.speakers_changed:
            t["speakers_fixed"] = True
        self.clip.transcript = t
        self.dirty = False
        self.destroy()
        self.on_save(self.clip)

    def _cancel(self) -> None:
        if self.dirty and not messagebox.askyesno(
                "UbiClipper", "Close without saving your subtitle changes?", parent=self):
            return
        self.destroy()
