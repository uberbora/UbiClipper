"""CI helper: which NVIDIA wheel versions ship *signed* Windows DLLs?
Smart App Control blocks unsigned DLLs, so UbiClipper must download a signed
build. Reads each wheel with HTTP range requests (only the one DLL)."""

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

CHECK = {
    "nvidia-cublas-cu12": "cublas64_12.dll",
    "nvidia-cuda-runtime-cu12": "cudart64_12.dll",
    "nvidia-cudnn-cu12": "cudnn_ops64_9.dll",
}


class HttpFile:
    def __init__(self, url, size):
        self.url, self.size, self.pos = url, size, 0

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def read(self, n=-1):
        if n < 0:
            n = self.size - self.pos
        if n == 0:
            return b""
        end = min(self.size, self.pos + n) - 1
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
        data = urllib.request.urlopen(req, timeout=120).read()
        self.pos += len(data)
        return data


def sig(path):
    ps = (f"$s=Get-AuthenticodeSignature '{path}'; "
          "\"$($s.Status) | $($s.SignerCertificate.Subject)\"")
    return subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                          capture_output=True, text=True).stdout.strip()


lines = []
tmp = tempfile.mkdtemp()
for pkg, dll in CHECK.items():
    data = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json"))
    vers = []
    for v, files in data["releases"].items():
        for f in files:
            if f["filename"].endswith("win_amd64.whl") and not f.get("yanked"):
                vers.append((v, f))
    def key(x):
        try:
            return tuple(int(p) for p in x[0].split("."))
        except ValueError:
            return (0,)
    vers.sort(key=key)
    for v, f in vers[-int(sys.argv[1]) if len(sys.argv) > 1 else -10:]:
        try:
            z = zipfile.ZipFile(HttpFile(f["url"], f["size"]))
            name = next(n for n in z.namelist() if n.lower().endswith("/" + dll.lower()))
            out = os.path.join(tmp, f"{pkg}-{v}-{dll}")
            with z.open(name) as src, open(out, "wb") as dst:
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    dst.write(b)
            res = sig(out)
            os.remove(out)
        except Exception as e:  # noqa: BLE001
            res = f"error {e}"
        line = f"{pkg} {v}: {res}"
        print(line, flush=True)
        lines.append(line)
print("::notice title=NVIDIA signatures::" + "%0A".join(lines))
