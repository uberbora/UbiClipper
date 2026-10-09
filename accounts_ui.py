"""Accounts tab: connect TikTok, Instagram and YouTube for Export All."""

from __future__ import annotations

import os
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from clipper.social import PLATFORMS, SocialError, load_accounts, platforms
from ui_help import help_icon

GUIDE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "social_setup.html")


def open_guide(anchor: str = "") -> None:
    url = "file:///" + GUIDE.replace("\\", "/").lstrip("/")
    webbrowser.open(url + (f"#{anchor}" if anchor else ""))


class CredentialsDialog(tk.Toplevel):
    """Ask for the developer app's ID and secret (once)."""

    def __init__(self, master, platform, on_ok) -> None:
        super().__init__(master)
        self.title(f"Connect {platform.name}")
        self.resizable(False, False)
        self.transient(master)
        self.platform, self.on_ok = platform, on_ok
        body = ttk.Frame(self, style="Card.TFrame", padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"Connect {platform.name}", style="H2.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text="Paste the keys of the developer app you created for "
                             "UbiClipper. Not created one yet? Open the setup guide.",
                  style="CardMuted.TLabel", wraplength=420, justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(4, 14))
        self.vars = {}
        for r, k in enumerate(platform.needs, start=2):
            ttk.Label(body, text=platform.labels[k], style="Card.TLabel").grid(
                row=r, column=0, sticky="w", pady=5, padx=(0, 12))
            v = tk.StringVar(value=platform.acc.get(k, ""))
            ttk.Entry(body, textvariable=v, width=42,
                      show="•" if "secret" in k else "").grid(row=r, column=1, sticky="we", pady=5)
            self.vars[k] = v
        ttk.Label(body, text="Redirect URI to enter in the developer app:",
                  style="CardMuted.TLabel").grid(row=10, column=0, columnspan=2, sticky="w",
                                                 pady=(12, 0))
        uri = ttk.Entry(body, width=42)
        uri.insert(0, "http://127.0.0.1:8765/callback" if platform.key == "youtube"
                   else "http://localhost:8765/callback")
        uri.configure(state="readonly")
        uri.grid(row=11, column=0, columnspan=2, sticky="we", pady=(2, 0))
        btns = ttk.Frame(body, style="Card.TFrame")
        btns.grid(row=12, column=0, columnspan=2, sticky="we", pady=(18, 0))
        ttk.Button(btns, text="Setup guide",
                   command=lambda: open_guide(platform.key)).pack(side="left")
        ttk.Button(btns, text="Log in & connect", style="Accent.TButton",
                   command=self._ok).pack(side="right")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=8)
        self.after(150, self._modal)

    def _modal(self) -> None:
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _ok(self) -> None:
        vals = {k: v.get().strip() for k, v in self.vars.items()}
        if not all(vals.values()):
            messagebox.showinfo("UbiClipper", "Fill in both fields.", parent=self)
            return
        self.platform.acc.update(vals)
        self.destroy()
        self.on_ok()


class AccountsTab:
    def __init__(self, parent: ttk.Frame, app) -> None:
        self.app = app
        self.store = load_accounts()
        self.p = platforms(self.store)
        self.rows: dict[str, dict] = {}
        top = ttk.Frame(parent, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="CONNECTED ACCOUNTS", style="Section.TLabel").pack(side="left")
        help_icon(top, "accounts").pack(side="left", padx=6)
        for cls in PLATFORMS:
            pl = self.p[cls.key]
            box = ttk.Frame(parent, style="Card.TFrame", padding=(0, 12, 0, 4))
            box.pack(fill="x")
            ttk.Separator(box).pack(fill="x", pady=(0, 10))
            head = ttk.Frame(box, style="Card.TFrame")
            head.pack(fill="x")
            ttk.Label(head, text=pl.name, style="H2.TLabel").pack(side="left")
            status = ttk.Label(head, text="", style="Bad.TLabel")
            status.pack(side="left", padx=10)
            ttk.Label(box, text=pl.note, style="CardMuted.TLabel", wraplength=400,
                      justify="left").pack(anchor="w", pady=(2, 8))
            btns = ttk.Frame(box, style="Card.TFrame")
            btns.pack(fill="x")
            connect = ttk.Button(btns, text="Connect…",
                                 command=lambda k=cls.key: self.connect(k))
            connect.pack(side="left")
            disc = ttk.Button(btns, text="Disconnect",
                              command=lambda k=cls.key: self.disconnect(k))
            disc.pack(side="left", padx=6)
            ttk.Button(btns, text="Setup guide", style="Small.TButton",
                       command=lambda k=cls.key: open_guide(k)).pack(side="right")
            self.rows[cls.key] = {"status": status, "connect": connect, "disc": disc}
        self.refresh()

    def refresh(self) -> None:
        for key, row in self.rows.items():
            pl = self.p[key]
            if pl.connected:
                row["status"].config(text=f"✔ {pl.account_name}", style="Ok.TLabel")
                row["connect"].config(text="Reconnect…")
                row["disc"].config(state="normal")
            else:
                row["status"].config(text="not connected", style="Bad.TLabel")
                row["connect"].config(text="Connect…")
                row["disc"].config(state="disabled")

    def connect(self, key: str) -> None:
        pl = self.p[key]
        CredentialsDialog(self.app, pl, lambda: self._login(key))

    def _login(self, key: str) -> None:
        pl = self.p[key]
        self.app.status.config(text=f"Log in to {pl.name} in your browser…")
        result: dict = {}

        def work():
            try:
                result["name"] = pl.connect()
            except SocialError as e:
                result["error"] = str(e)
            except Exception as e:
                result["error"] = f"{type(e).__name__}: {e}"

        th = threading.Thread(target=work, daemon=True)
        th.start()

        def wait():
            if th.is_alive():
                self.app.after(300, wait)
                return
            self.refresh()
            if "error" in result:
                self.app.status.config(text=f"{pl.name}: not connected.")
                messagebox.showerror("UbiClipper", f"{pl.name}: {result['error']}")
            else:
                self.app.status.config(text=f"{pl.name} connected as {result['name']}.")
        wait()

    def disconnect(self, key: str) -> None:
        pl = self.p[key]
        if messagebox.askyesno("UbiClipper", f"Disconnect {pl.name}? (Your app keys are kept, "
                                             "so reconnecting is one click.)"):
            pl.disconnect()
            self.refresh()
