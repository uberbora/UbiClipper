"""Post finished clips to TikTok, Instagram Reels and YouTube Shorts.

Every platform only allows uploads through a developer app that YOU create
(free). You paste its Client ID / Secret once in the Accounts tab; the app
then opens the platform's official login page, catches the answer on
http://localhost:8765/callback and stores the tokens encrypted with Windows
DPAPI (only your Windows account can read them).

What each platform allows for a new, unreviewed app (2026):
  TikTok    - videos go to your TikTok INBOX/drafts; you tap Post in the app
              (direct public posting needs TikTok's audit).
  Instagram - Reels are published directly to your own Creator/Business
              account (must be linked to a Facebook Page). No review needed
              for your own account. Max 100 API posts per 24 h.
  YouTube   - uploads arrive PRIVATE until Google verifies your app; flip
              them to public in YouTube Studio.
"""

from __future__ import annotations

import base64
import hashlib
import http.server as _hs
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from typing import Callable

from .reframe import CONFIG_DIR

ACCOUNTS_FILE = os.path.join(CONFIG_DIR, "accounts.json")
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
GRAPH_VERSION = "v23.0"

# All endpoints in one place (tests point these at a local stand-in).
ENDPOINTS = {
    "tiktok_auth": "https://www.tiktok.com/v2/auth/authorize/",
    "tiktok_api": "https://open.tiktokapis.com",
    "fb_auth": f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth",
    "fb_graph": f"https://graph.facebook.com/{GRAPH_VERSION}",
    "fb_rupload": f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VERSION}",
    "google_auth": "https://accounts.google.com/o/oauth2/v2/auth",
    "google_token": "https://oauth2.googleapis.com/token",
    "youtube_api": "https://www.googleapis.com/youtube/v3",
    "youtube_upload": "https://www.googleapis.com/upload/youtube/v3/videos",
}

Report = Callable[[str, float], None]


class SocialError(RuntimeError):
    pass


# ------------------------------------------------------------------ token store
def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    inp = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    fn = (ctypes.windll.crypt32.CryptProtectData if protect
          else ctypes.windll.crypt32.CryptUnprotectData)
    if not fn(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("Windows could not encrypt/decrypt the saved accounts")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _seal(obj: dict) -> dict:
    raw = json.dumps(obj).encode()
    if sys.platform.startswith("win"):
        return {"dpapi": base64.b64encode(_dpapi(raw, True)).decode()}
    return {"plain": base64.b64encode(raw).decode()}


def _unseal(d: dict) -> dict:
    if "dpapi" in d:
        return json.loads(_dpapi(base64.b64decode(d["dpapi"]), False))
    if "plain" in d:
        return json.loads(base64.b64decode(d["plain"]))
    return {}


def load_accounts() -> dict:
    try:
        with open(ACCOUNTS_FILE, encoding="utf-8") as f:
            return {k: _unseal(v) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


def save_accounts(acc: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = ACCOUNTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: _seal(v) for k, v in acc.items()}, f)
    os.replace(tmp, ACCOUNTS_FILE)


# ------------------------------------------------------------------ HTTP
def http(method: str, url: str, *, params: dict | None = None, data: bytes | None = None,
         form: dict | None = None, json_body=None, headers: dict | None = None,
         timeout: float = 120) -> tuple[int, dict, bytes]:
    hdrs = dict(headers or {})
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif json_body is not None:
        data = json.dumps(json_body).encode()
        hdrs.setdefault("Content-Type", "application/json; charset=UTF-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SocialError(f"No connection to {urllib.parse.urlparse(url).netloc}: {e}") from e


def _json(status: int, body: bytes, what: str) -> dict:
    try:
        d = json.loads(body or b"{}")
    except ValueError:
        d = {"raw": body[:300].decode("utf-8", "replace")}
    err = d.get("error") if isinstance(d, dict) else None
    tiktok_ok = isinstance(err, dict) and err.get("code") in ("ok", None, "")
    if status >= 400 or (err and not tiktok_ok):
        msg = err.get("message") if isinstance(err, dict) else err
        raise SocialError(f"{what} failed ({status}): {msg or d}")
    return d


# ------------------------------------------------------------------ OAuth
def _pkce(hex_digest: bool = False) -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = (digest.hex() if hex_digest
                 else base64.urlsafe_b64encode(digest).rstrip(b"=").decode())
    return verifier, challenge


def browser_login(auth_url: str, params: dict, timeout: float = 300) -> dict:
    """Open the platform's login page and wait for it to come back to
    localhost:8765/callback. Returns the query parameters (code, state…)."""
    state = secrets.token_urlsafe(24)
    params = dict(params, state=state)
    result: dict = {}
    done = threading.Event()

    class Handler(_hs.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" not in q and "error" not in q:
                self.send_response(404)
                self.end_headers()
                return
            result.update({k: v[0] for k, v in q.items()})
            ok = "code" in q and q.get("state", [""])[0] == state
            page = ("<h2>UbiClipper: account connected ✔</h2><p>You can close this tab.</p>"
                    if ok else "<h2>UbiClipper: connecting failed</h2><p>Go back to the app.</p>")
            body = f"<html><body style='font-family:sans-serif'>{page}</body></html>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            done.set()

    # Browsers may send "localhost" to 127.0.0.1 or to ::1 (IPv6): listen on both.
    servers = []
    try:
        servers.append(_hs.HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler))
    except OSError as e:
        raise SocialError(f"Port {REDIRECT_PORT} is busy; close other apps using it. ({e})")
    try:
        class V6(_hs.HTTPServer):
            address_family = __import__("socket").AF_INET6
        servers.append(V6(("::1", REDIRECT_PORT), Handler))
    except OSError:
        pass  # no IPv6 on this PC: fine
    for srv in servers:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        webbrowser.open(auth_url + "?" + urllib.parse.urlencode(params))
        if not done.wait(timeout):
            raise SocialError("Login timed out (5 minutes). Try again.")
    finally:
        for srv in servers:
            srv.shutdown()
            srv.server_close()
    if result.get("error"):
        raise SocialError(f"Login was cancelled or refused: "
                          f"{result.get('error_description') or result['error']}")
    if result.get("state") != state:
        raise SocialError("Login answer didn't match (state mismatch). Try again.")
    return result


# ------------------------------------------------------------------ platforms
@dataclass
class PostResult:
    platform: str
    ok: bool
    message: str
    url: str = ""


class Platform:
    key = ""
    name = ""
    needs = ("client_id", "client_secret")
    labels = {"client_id": "Client ID", "client_secret": "Client secret"}
    note = ""

    def __init__(self, store: dict) -> None:
        self.store = store          # shared dict of all accounts (mutated in place)

    @property
    def acc(self) -> dict:
        return self.store.setdefault(self.key, {})

    @property
    def connected(self) -> bool:
        return bool(self.acc.get("access_token"))

    @property
    def account_name(self) -> str:
        return self.acc.get("account_name", "")

    def disconnect(self) -> None:
        keep = {k: self.acc[k] for k in self.needs if k in self.acc}
        self.store[self.key] = keep
        save_accounts(self.store)

    def save(self) -> None:
        save_accounts(self.store)

    # implemented per platform
    def connect(self) -> str:
        raise NotImplementedError

    def post(self, video: str, caption: str, title: str, tags: list[str],
             report: Report, options: dict | None = None) -> PostResult:
        raise NotImplementedError


class TikTok(Platform):
    key, name = "tiktok", "TikTok"
    labels = {"client_id": "Client key", "client_secret": "Client secret"}
    note = "Goes to your TikTok inbox/drafts: open TikTok and tap Post."

    def _token(self, form: dict) -> None:
        s, _, b = http("POST", ENDPOINTS["tiktok_api"] + "/v2/oauth/token/", form=dict(
            client_key=self.acc["client_id"], client_secret=self.acc["client_secret"], **form))
        d = _json(s, b, "TikTok login")
        d = d.get("data", d)
        if not d.get("access_token"):
            raise SocialError(f"TikTok didn't return a token: {d}")
        self.acc.update(access_token=d["access_token"],
                        refresh_token=d.get("refresh_token", self.acc.get("refresh_token")),
                        expires_at=time.time() + float(d.get("expires_in", 86400)) - 60,
                        open_id=d.get("open_id", ""))

    def connect(self) -> str:
        verifier, challenge = _pkce(hex_digest=True)   # TikTok desktop: hex SHA-256
        q = browser_login(ENDPOINTS["tiktok_auth"], dict(
            client_key=self.acc["client_id"], response_type="code",
            scope="user.info.basic,video.upload", redirect_uri=REDIRECT_URI,
            code_challenge=challenge, code_challenge_method="S256"))
        self._token(dict(code=q["code"], grant_type="authorization_code",
                         redirect_uri=REDIRECT_URI, code_verifier=verifier))
        try:
            s, _, b = http("GET", ENDPOINTS["tiktok_api"] + "/v2/user/info/",
                           params={"fields": "open_id,display_name"},
                           headers={"Authorization": "Bearer " + self.acc["access_token"]})
            user = _json(s, b, "TikTok profile").get("data", {}).get("user", {})
            self.acc["account_name"] = user.get("display_name", "") or "TikTok account"
        except SocialError:
            self.acc["account_name"] = "TikTok account"
        self.save()
        return self.account_name

    def _fresh(self) -> str:
        if time.time() > self.acc.get("expires_at", 0) and self.acc.get("refresh_token"):
            self._token(dict(grant_type="refresh_token", refresh_token=self.acc["refresh_token"]))
            self.save()
        return self.acc["access_token"]

    def post(self, video, caption, title, tags, report, options=None) -> PostResult:
        token = self._fresh()
        size = os.path.getsize(video)
        # TikTok chunk rules: one chunk up to 64 MB; else 10 MB chunks, the
        # last one absorbs the remainder
        chunk = size if size <= 64 * 1024 * 1024 else 10 * 1024 * 1024
        count = max(1, size // chunk)
        api = ENDPOINTS["tiktok_api"]
        auth = {"Authorization": "Bearer " + token}
        report("TikTok: starting upload", 0.05)
        s, _, b = http("POST", api + "/v2/post/publish/inbox/video/init/", headers=auth,
                       json_body={"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                                  "chunk_size": chunk,
                                                  "total_chunk_count": count}})
        d = _json(s, b, "TikTok upload start").get("data", {})
        upload_url, publish_id = d.get("upload_url"), d.get("publish_id")
        if not upload_url:
            raise SocialError(f"TikTok didn't return an upload address: {d}")
        with open(video, "rb") as f:
            for i in range(count):
                first = i * chunk
                last = size - 1 if i == count - 1 else first + chunk - 1
                f.seek(first)
                part = f.read(last - first + 1)
                s, _, b = http("PUT", upload_url, data=part, headers={
                    "Content-Type": "video/mp4", "Content-Range": f"bytes {first}-{last}/{size}"})
                if s >= 300:
                    raise SocialError(f"TikTok upload failed ({s}): {b[:200]!r}")
                report("TikTok: uploading", 0.1 + 0.8 * (i + 1) / count)
        status = ""
        for _ in range(30):
            s, _, b = http("POST", api + "/v2/post/publish/status/fetch/", headers=auth,
                           json_body={"publish_id": publish_id})
            status = _json(s, b, "TikTok status").get("data", {}).get("status", "")
            if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE", "FAILED"):
                break
            time.sleep(2)
        if status == "FAILED":
            return PostResult(self.name, False, "TikTok rejected the video.")
        return PostResult(self.name, True,
                          "In your TikTok inbox: open TikTok, add the caption, tap Post.")


class Instagram(Platform):
    key, name = "instagram", "Instagram Reels"
    labels = {"client_id": "App ID", "client_secret": "App secret"}
    note = "Publishes the Reel directly to your Creator/Business account."

    def connect(self) -> str:
        q = browser_login(ENDPOINTS["fb_auth"], dict(
            client_id=self.acc["client_id"], redirect_uri=REDIRECT_URI, response_type="code",
            scope="instagram_basic,instagram_content_publish,pages_show_list,"
                  "business_management"))
        g = ENDPOINTS["fb_graph"]
        s, _, b = http("GET", g + "/oauth/access_token", params=dict(
            client_id=self.acc["client_id"], client_secret=self.acc["client_secret"],
            redirect_uri=REDIRECT_URI, code=q["code"]))
        short = _json(s, b, "Facebook login")["access_token"]
        s, _, b = http("GET", g + "/oauth/access_token", params=dict(
            grant_type="fb_exchange_token", client_id=self.acc["client_id"],
            client_secret=self.acc["client_secret"], fb_exchange_token=short))
        d = _json(s, b, "Facebook long-lived token")
        token = d["access_token"]
        s, _, b = http("GET", g + "/me/accounts", params=dict(
            fields="name,instagram_business_account{id,username}", access_token=token))
        pages = _json(s, b, "Reading your Facebook Pages").get("data", [])
        ig = next((p["instagram_business_account"] for p in pages
                   if p.get("instagram_business_account")), None)
        if not ig:
            raise SocialError(
                "No Instagram Creator/Business account found. In the Instagram app: "
                "Settings > Account type > switch to Creator, then link it to a "
                "Facebook Page (Accounts Center), and connect again.")
        self.acc.update(access_token=token, ig_id=ig["id"],
                        account_name="@" + ig.get("username", "instagram"),
                        expires_at=time.time() + float(d.get("expires_in", 60 * 86400)))
        self.save()
        return self.account_name

    def post(self, video, caption, title, tags, report, options=None) -> PostResult:
        if time.time() > self.acc.get("expires_at", 1e18):
            raise SocialError("Instagram login expired (they last 60 days). "
                              "Reconnect in the Accounts tab.")
        g, token, ig = ENDPOINTS["fb_graph"], self.acc["access_token"], self.acc["ig_id"]
        size = os.path.getsize(video)
        report("Instagram: creating Reel", 0.05)
        s, _, b = http("POST", f"{g}/{ig}/media", params=dict(
            media_type="REELS", upload_type="resumable", caption=caption[:2200],
            share_to_feed="true", access_token=token))
        container = _json(s, b, "Instagram Reel container")["id"]
        report("Instagram: uploading", 0.2)
        with open(video, "rb") as f:
            data = f.read()
        s, _, b = http("POST", f"{ENDPOINTS['fb_rupload']}/{container}", data=data, headers={
            "Authorization": "OAuth " + token, "offset": "0", "file_size": str(size)})
        _json(s, b, "Instagram upload")
        status = ""
        for i in range(60):          # Instagram processes the video
            s, _, b = http("GET", f"{g}/{container}", params=dict(
                fields="status_code,status", access_token=token))
            d = _json(s, b, "Instagram processing")
            status = d.get("status_code", "")
            if status in ("FINISHED", "ERROR", "EXPIRED"):
                break
            report("Instagram: processing", 0.4 + 0.4 * i / 60)
            time.sleep(3)
        if status != "FINISHED":
            return PostResult(self.name, False, f"Instagram couldn't process the video "
                                                f"({status or 'timeout'}).")
        s, _, b = http("POST", f"{g}/{ig}/media_publish", params=dict(
            creation_id=container, access_token=token))
        media = _json(s, b, "Instagram publish")["id"]
        url = ""
        try:
            s, _, b = http("GET", f"{g}/{media}", params=dict(fields="permalink",
                                                               access_token=token))
            url = _json(s, b, "permalink").get("permalink", "")
        except SocialError:
            pass
        return PostResult(self.name, True, "Published.", url)


class YouTube(Platform):
    key, name = "youtube", "YouTube Shorts"
    note = "Uploads as a Short; private until Google verifies your app."

    def _token(self, form: dict) -> None:
        s, _, b = http("POST", ENDPOINTS["google_token"], form=dict(
            client_id=self.acc["client_id"], client_secret=self.acc["client_secret"], **form))
        d = _json(s, b, "Google login")
        self.acc.update(access_token=d["access_token"],
                        refresh_token=d.get("refresh_token", self.acc.get("refresh_token")),
                        expires_at=time.time() + float(d.get("expires_in", 3600)) - 60)

    def connect(self) -> str:
        verifier, challenge = _pkce()
        redirect = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
        q = browser_login(ENDPOINTS["google_auth"], dict(
            client_id=self.acc["client_id"], redirect_uri=redirect, response_type="code",
            scope="https://www.googleapis.com/auth/youtube.upload "
                  "https://www.googleapis.com/auth/youtube.readonly",
            access_type="offline", prompt="consent",
            code_challenge=challenge, code_challenge_method="S256"))
        self._token(dict(code=q["code"], code_verifier=verifier,
                         grant_type="authorization_code", redirect_uri=redirect))
        try:
            s, _, b = http("GET", ENDPOINTS["youtube_api"] + "/channels",
                           params={"part": "snippet", "mine": "true"},
                           headers={"Authorization": "Bearer " + self.acc["access_token"]})
            items = _json(s, b, "YouTube channel").get("items", [])
            self.acc["account_name"] = (items[0]["snippet"]["title"] if items
                                        else "YouTube channel")
        except SocialError:
            self.acc["account_name"] = "YouTube channel"
        self.save()
        return self.account_name

    def post(self, video, caption, title, tags, report, options=None) -> PostResult:
        if time.time() > self.acc.get("expires_at", 0):
            self._token(dict(grant_type="refresh_token", refresh_token=self.acc["refresh_token"]))
            self.save()
        privacy = (options or {}).get("youtube_privacy", "public")
        size = os.path.getsize(video)
        clean_title = (title or "Clip").replace("<", "").replace(">", "")
        if "#shorts" not in clean_title.lower():
            clean_title = (clean_title[:90] + " #Shorts")
        meta = {"snippet": {"title": clean_title[:100], "description": caption[:4900],
                            "tags": [t.lstrip("#") for t in tags][:15], "categoryId": "20"},
                "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
        report("YouTube: starting upload", 0.05)
        s, h, b = http("POST", ENDPOINTS["youtube_upload"],
                       params={"uploadType": "resumable", "part": "snippet,status"},
                       json_body=meta, headers={
                           "Authorization": "Bearer " + self.acc["access_token"],
                           "X-Upload-Content-Type": "video/mp4",
                           "X-Upload-Content-Length": str(size)})
        if s >= 300:
            _json(s, b, "YouTube upload start")
        location = h.get("Location") or h.get("location")
        if not location:
            raise SocialError("YouTube didn't return an upload address.")
        report("YouTube: uploading", 0.3)
        with open(video, "rb") as f:
            s, _, b = http("PUT", location, data=f.read(), headers={"Content-Type": "video/mp4"},
                           timeout=600)
        d = _json(s, b, "YouTube upload")
        vid = d.get("id", "")
        st = (d.get("status") or {}).get("privacyStatus", privacy)
        msg = "Uploaded." if st == "public" else (
            f"Uploaded as {st}. Google keeps uploads from unverified apps private; "
            "make it public in YouTube Studio.")
        return PostResult(self.name, True, msg, f"https://youtube.com/shorts/{vid}" if vid else "")


PLATFORMS = (TikTok, Instagram, YouTube)


def platforms(store: dict | None = None) -> dict[str, Platform]:
    store = store if store is not None else load_accounts()
    return {cls.key: cls(store) for cls in PLATFORMS}


# ------------------------------------------------------------------ posting
@dataclass
class PostItem:
    video: str
    caption: str          # title + hashtags (Instagram / YouTube description)
    title: str
    tags: list
    key: str = ""         # stable id to remember what was posted


def posted_log(folder: str) -> dict:
    try:
        with open(os.path.join(folder, "posted.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def mark_posted(folder: str, key: str, platform: str, url: str) -> None:
    log = posted_log(folder)
    log.setdefault(key, {})[platform] = {"at": time.strftime("%Y-%m-%d %H:%M"), "url": url}
    with open(os.path.join(folder, "posted.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def post_all(items: list[PostItem], targets: list[Platform], log_folder: str,
             report: Report, should_cancel=None, options: dict | None = None
             ) -> list[tuple[PostItem, PostResult]]:
    results = []
    total = max(1, len(items) * len(targets))
    n = 0
    for item in items:
        for p in targets:
            if should_cancel and should_cancel():
                raise InterruptedError("Posting cancelled")
            base = n / total

            def sub(msg, f, base=base, item=item):
                report(f"{os.path.basename(item.video)} – {msg}", base + f / total)
            try:
                r = p.post(item.video, item.caption, item.title, item.tags, sub, options)
            except SocialError as e:
                r = PostResult(p.name, False, str(e))
            except Exception as e:  # never stop the batch on one failure
                r = PostResult(p.name, False, f"{type(e).__name__}: {e}")
            if r.ok and item.key:
                mark_posted(log_folder, item.key, p.key, r.url)
            results.append((item, r))
            n += 1
    report("Posting finished", 1.0)
    return results
