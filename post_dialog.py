"""Export All: post finished clips to the connected accounts."""

from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from clipper.pipeline import READY_DIRS
from clipper.social import PostItem, platforms, post_all, posted_log
from ui_help import help_icon


def load_export(folder: str) -> list[dict]:
    """Ready clips of an export folder with their title ideas."""
    manifest = os.path.join(folder, "extras", "clips.json")
    if not os.path.exists(manifest):
        return []
    with open(manifest, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for c in data.get("clips", []):
        video = c.get("vertical_file") or c.get("subtitled_file")
        if not video or not os.path.exists(video):
            # export folder may have moved: look in its own ready folders
            base = os.path.basename(video or c.get("file") or "")
            video = next((p for p in (os.path.join(folder, d, base) for d in READY_DIRS)
                          if os.path.exists(p)), None)
        if not video:
            continue
        post = c.get("post") or {}
        titles = post.get("titles") or [os.path.splitext(os.path.basename(video))[0]]
        out.append({"key": f"{c.get('rank', 0):02d}_{c.get('start', 0)}", "video": video,
                    "title": titles[0], "titles": titles,
                    "hashtags": post.get("hashtags") or [], "reasons": c.get("reasons", [])})
    return out


class PostDialog(tk.Toplevel):
    def __init__(self, master, folder: str, store: dict) -> None:
        super().__init__(master)
        self.title("Export All – post clips")
        self.geometry("900x640")
        self.minsize(760, 520)
        self.transient(master)
        self.store = store
        self.p = platforms(store)
        self.folder = folder if folder and os.path.isdir(folder) else ""
        self.items: list[dict] = []
        self.sel_on: dict[str, bool] = {}
        self.q: queue.Queue = queue.Queue()
        self.running = False
        self.cancel = threading.Event()

        body = ttk.Frame(self, style="Card.TFrame", padding=18)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)

        head = ttk.Frame(body, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="we")
        ttk.Label(head, text="Post clips", style="H2.TLabel").pack(side="left")
        help_icon(head, "export_all").pack(side="left", padx=6)
        ttk.Button(head, text="Choose export folder…", style="Small.TButton",
                   command=self.choose_folder).pack(side="right")
        self.folder_lbl = ttk.Label(body, text="", style="CardMuted.TLabel")
        self.folder_lbl.grid(row=1, column=0, sticky="w", pady=(2, 10))

        plats = ttk.Frame(body, style="Card.TFrame")
        plats.grid(row=2, column=0, sticky="we", pady=(0, 10))
        ttk.Label(plats, text="Post to:", style="Card.TLabel").pack(side="left", padx=(0, 10))
        self.targets: dict[str, tk.BooleanVar] = {}
        for key, pl in self.p.items():
            v = tk.BooleanVar(value=pl.connected)
            cb = ttk.Checkbutton(plats, text=pl.name + ("" if pl.connected else " (not connected)"),
                                 variable=v, state="normal" if pl.connected else "disabled")
            cb.pack(side="left", padx=(0, 14))
            self.targets[key] = v
        ttk.Label(plats, text="YouTube:", style="Card.TLabel").pack(side="left", padx=(10, 4))
        self.yt_privacy = tk.StringVar(value="public")
        ttk.Combobox(plats, textvariable=self.yt_privacy, state="readonly", width=9,
                     values=["public", "unlisted", "private"]).pack(side="left")

        mid = ttk.Panedwindow(body, orient="vertical")
        mid.grid(row=3, column=0, sticky="nsew")
        listf = ttk.Frame(mid, style="Card.TFrame")
        cols = ("use", "clip", "title", "posted")
        self.tree = ttk.Treeview(listf, columns=cols, show="headings", selectmode="browse",
                                 height=8)
        for col, w, t in [("use", 40, "✓"), ("clip", 170, "Clip"), ("title", 330, "Title"),
                          ("posted", 170, "Already posted")]:
            self.tree.heading(col, text=t)
            self.tree.column(col, width=w, anchor="center" if col == "use" else "w",
                             stretch=col == "title")
        sb = ttk.Scrollbar(listf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<Button-1>", self._toggle)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._load_editor())
        mid.add(listf, weight=3)

        ed = ttk.Frame(mid, style="Card.TFrame", padding=(0, 10, 0, 0))
        ed.columnconfigure(1, weight=1)
        ttk.Label(ed, text="Title", style="Card.TLabel").grid(row=0, column=0, sticky="w",
                                                             padx=(0, 10))
        self.title_var = tk.StringVar()
        self.title_box = ttk.Combobox(ed, textvariable=self.title_var)
        self.title_box.grid(row=0, column=1, sticky="we")
        ttk.Label(ed, text="Hashtags", style="Card.TLabel").grid(row=1, column=0, sticky="nw",
                                                                padx=(0, 10), pady=(8, 0))
        self.tags = tk.Text(ed, height=3, wrap="word", relief="flat", padx=8, pady=6)
        self.tags.grid(row=1, column=1, sticky="we", pady=(8, 0))
        self.title_var.trace_add("write", lambda *a: self._save_editor())
        self.tags.bind("<KeyRelease>", lambda e: self._save_editor())
        mid.add(ed, weight=1)

        foot = ttk.Frame(body, style="Card.TFrame")
        foot.grid(row=4, column=0, sticky="we", pady=(12, 0))
        foot.columnconfigure(0, weight=1)
        self.status = ttk.Label(foot, text="", style="Card.TLabel")
        self.status.grid(row=0, column=0, sticky="w")
        self.bar = ttk.Progressbar(foot, maximum=1.0)
        self.bar.grid(row=1, column=0, sticky="we", pady=(6, 0))
        self.post_btn = ttk.Button(foot, text="Post checked clips", style="Accent.TButton",
                                   command=self.start)
        self.post_btn.grid(row=0, column=1, rowspan=2, padx=(12, 0))
        self.close_btn = ttk.Button(foot, text="Close", command=self._close)
        self.close_btn.grid(row=0, column=2, rowspan=2, padx=(8, 0))
        self.protocol("WM_DELETE_WINDOW", self._close)

        self._current: dict | None = None
        if self.folder:
            self.load(self.folder)
        else:
            self.folder_lbl.config(text="No export yet: export clips first, or choose an "
                                        "export folder.")
        if not any(pl.connected for pl in self.p.values()):
            self.status.config(text="Connect an account first (Accounts tab).")
        self.after(100, self._poll)

    # ------------------------------------------------------------ data
    def choose_folder(self) -> None:
        d = filedialog.askdirectory(title="Choose an export folder (the one with extras/ "
                                          "inside)", parent=self)
        if d:
            if os.path.basename(d) in READY_DIRS + ("extras", "raw"):
                d = os.path.dirname(d)
            self.load(d)

    def load(self, folder: str) -> None:
        self.folder = folder
        self.items = load_export(folder)
        log = posted_log(os.path.join(folder, "extras"))
        self.folder_lbl.config(text=folder if self.items else
                               f"{folder}: no finished clips found here.")
        self.tree.delete(*self.tree.get_children())
        self.sel_on.clear()
        for it in self.items:
            done = log.get(it["key"], {})
            names = ", ".join(self.p[k].name.split()[0] for k in done if k in self.p)
            self.sel_on[it["key"]] = not done
            self.tree.insert("", "end", iid=it["key"], values=(
                "☑" if not done else "☐", os.path.basename(it["video"])[:28], it["title"],
                names or "–"))
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[0])

    def _toggle(self, event) -> None:
        if self.tree.identify_column(event.x) != "#1" or self.running:
            return
        iid = self.tree.identify_row(event.y)
        if iid:
            self.sel_on[iid] = not self.sel_on.get(iid, True)
            self.tree.set(iid, "use", "☑" if self.sel_on[iid] else "☐")

    def _item(self, key: str) -> dict | None:
        return next((i for i in self.items if i["key"] == key), None)

    def _load_editor(self) -> None:
        sel = self.tree.selection()
        it = self._item(sel[0]) if sel else None
        self._current = None
        if not it:
            return
        self.title_box["values"] = it["titles"]
        self.title_var.set(it["title"])
        self.tags.delete("1.0", "end")
        self.tags.insert("1.0", " ".join(it["hashtags"]))
        self._current = it

    def _save_editor(self) -> None:
        it = self._current
        if not it:
            return
        it["title"] = self.title_var.get().strip()
        it["hashtags"] = [t if t.startswith("#") else "#" + t
                          for t in self.tags.get("1.0", "end").split() if t.strip("#")]
        if self.tree.exists(it["key"]):
            self.tree.set(it["key"], "title", it["title"])

    # ------------------------------------------------------------ posting
    def start(self) -> None:
        if self.running:
            return
        targets = [self.p[k] for k, v in self.targets.items() if v.get() and self.p[k].connected]
        chosen = [it for it in self.items if self.sel_on.get(it["key"])]
        if not targets:
            messagebox.showinfo("UbiClipper", "Pick at least one connected platform.", parent=self)
            return
        if not chosen:
            messagebox.showinfo("UbiClipper", "No clips are checked.", parent=self)
            return
        names = ", ".join(p.name for p in targets)
        if not messagebox.askyesno("UbiClipper", f"Post {len(chosen)} clip(s) to {names}?",
                                   parent=self):
            return
        items = [PostItem(it["video"], it["title"] + "\n\n" + " ".join(it["hashtags"]),
                          it["title"], it["hashtags"], it["key"]) for it in chosen]
        log_dir = os.path.join(self.folder, "extras")
        opts = {"youtube_privacy": self.yt_privacy.get()}
        self.running = True
        self.cancel.clear()
        self.post_btn.config(state="disabled")
        self.close_btn.config(text="Stop")

        def work():
            try:
                res = post_all(items, targets, log_dir,
                               lambda m, f: self.q.put(("progress", (m, f))),
                               self.cancel.is_set, opts)
                self.q.put(("done", res))
            except InterruptedError:
                self.q.put(("cancelled", None))
            except Exception as e:
                self.q.put(("error", e))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "progress":
                    self.status.config(text=data[0][:110])
                    self.bar["value"] = data[1]
                else:
                    self.running = False
                    self.post_btn.config(state="normal")
                    self.close_btn.config(text="Close")
                    if kind == "done":
                        self._show_results(data)
                    elif kind == "cancelled":
                        self.status.config(text="Stopped.")
                    else:
                        messagebox.showerror("UbiClipper", str(data), parent=self)
                    self.load(self.folder)
        except queue.Empty:
            pass
        try:
            if self.winfo_exists():
                self.after(150, self._poll)
        except tk.TclError:
            pass

    def _show_results(self, results) -> None:
        ok = sum(1 for _, r in results if r.ok)
        lines = [f"{'✔' if r.ok else '✖'} {os.path.basename(it.video)[:30]} → {r.platform}: "
                 f"{r.message}" + (f"\n    {r.url}" if r.url else "") for it, r in results]
        self.status.config(text=f"Done: {ok}/{len(results)} posted.")
        win = tk.Toplevel(self)
        win.title("Posting results")
        txt = tk.Text(win, width=100, height=min(30, 4 + 2 * len(lines)), wrap="word",
                      relief="flat", padx=12, pady=10)
        txt.insert("1.0", "\n".join(lines))
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True)

    def _close(self) -> None:
        if self.running:
            self.cancel.set()
            return
        self.destroy()
