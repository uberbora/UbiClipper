"""CI helper: are the DLLs in NVIDIA's official CUDA redistributable
archives (developer.download.nvidia.com/compute/cuda/redist) signed?"""

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

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



BASE = "https://developer.download.nvidia.com/compute/cuda/redist/"
WANT = {"libcublas": ["cublas64_12.dll", "cublasLt64_12.dll"], "cuda_cudart": ["cudart64_12.dll"]}
lines = []
tmp = tempfile.mkdtemp()
for ver in sys.argv[1:]:
    man = json.load(urllib.request.urlopen(BASE + f"redistrib_{ver}.json"))
    for comp, dlls in WANT.items():
        info = man[comp]["windows-x86_64"]
        url = BASE + info["relative_path"]
        size = int(urllib.request.urlopen(urllib.request.Request(url, method="HEAD")).headers["Content-Length"])
        z = zipfile.ZipFile(HttpFile(url, size))
        for dll in dlls:
            try:
                name = next(n for n in z.namelist() if n.lower().endswith("/" + dll.lower()))
                out = os.path.join(tmp, dll)
                with z.open(name) as s, open(out, "wb") as d:
                    while True:
                        b = s.read(1 << 20)
                        if not b:
                            break
                        d.write(b)
                r = subprocess.run(["pwsh", "-NoProfile", "-Command",
                                    f"$s=Get-AuthenticodeSignature '{out}'; \"$($s.Status) | $($s.SignerCertificate.Subject)\""],
                                   capture_output=True, text=True)
                res = (r.stdout + r.stderr).strip()[:160]
            except Exception as e:  # noqa: BLE001
                res = f"error {e}"
            line = f"{ver} {comp} {info['relative_path'].split('/')[-1]} {dll}: {res} ({size/1e6:.0f} MB)"
            print(line, flush=True)
            lines.append(line)
print("::notice title=Redist signatures::" + "%0A".join(lines))
