"""Tiny HTTP helper.

Kick sits behind Cloudflare and Twitch's GraphQL checks the TLS fingerprint,
so plain Python requests often get a 403. When `curl_cffi` is installed we
use it to look like a real Chrome browser; otherwise we fall back to urllib
with browser headers (which works more often than not).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
BASE_HEADERS = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"}


class NetError(RuntimeError):
    def __init__(self, status: int, url: str, detail: str = "") -> None:
        self.status = status
        msg = {403: "blocked by the site's bot protection (403)",
               404: "not found (404)", 429: "too many requests (429), try again later"
               }.get(status, f"HTTP {status}" if status else "no connection")
        super().__init__(f"{msg}: {url}" + (f"\n{detail}" if detail else ""))


def _curl():
    try:
        from curl_cffi import requests as cr  # optional
        return cr
    except Exception:  # not installed, or its DLL blocked by Windows
        return None


def request(url: str, params: dict | None = None, headers: dict | None = None,
            data: bytes | None = None, timeout: float = 30) -> str:
    hdrs = dict(BASE_HEADERS, **(headers or {}))
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    cr = _curl()
    if cr is not None:
        try:
            r = (cr.post(url, data=data, headers=hdrs, impersonate="chrome", timeout=timeout)
                 if data is not None else
                 cr.get(url, headers=hdrs, impersonate="chrome", timeout=timeout))
            if r.status_code >= 400:
                raise NetError(r.status_code, url, r.text[:200])
            return r.text
        except NetError:
            raise
        except Exception:
            pass  # fall through to urllib
    req = urllib.request.Request(url, data=data, headers=hdrs,
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise NetError(e.code, url, e.read()[:200].decode("utf-8", "replace")) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NetError(0, url, str(e)) from e


def get_json(url: str, params: dict | None = None, headers: dict | None = None):
    return json.loads(request(url, params, headers))


def post_json(url: str, payload, headers: dict | None = None):
    hdrs = dict({"Content-Type": "application/json"}, **(headers or {}))
    return json.loads(request(url, None, hdrs, json.dumps(payload).encode()))
