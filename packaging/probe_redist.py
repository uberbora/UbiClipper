"""CI helper: are the DLLs in NVIDIA's official CUDA redistributable
archives (developer.download.nvidia.com/compute/cuda/redist) signed?"""

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe_nvidia import HttpFile  # noqa: E402

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
