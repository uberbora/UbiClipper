"""CI check: the GPU speed-up downloader gets the pinned NVIDIA packages, and
reports which DLLs are signed (NVIDIA doesn't sign cuBLAS / the CUDA runtime;
UbiClipper tests on each PC whether Smart App Control lets them load)."""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clipper import getready as g  # noqa: E402

tmp = tempfile.mkdtemp()
bad = []
for pkg, major, exact, dll in g.NVIDIA_PACKAGES:
    w = g._pick_wheel(pkg, major, exact)
    print(f"{pkg}: {w['filename']} ({w['size'] / 1e6:.0f} MB)", flush=True)
    dest = os.path.join(tmp, w["filename"])
    g._download(w["url"], dest, w["size"], w["digests"]["sha256"], pkg,
                lambda m, f: None, lambda: False, 0.0, 1.0)
    n = g._extract_dlls(dest, os.path.join(tmp, "nvidia"))
    os.remove(dest)
    print(f"  unpacked {n} DLLs", flush=True)

for root, _, files in os.walk(os.path.join(tmp, "nvidia")):
    for f in files:
        p = os.path.join(root, f)
        out = subprocess.run(["pwsh", "-NoProfile", "-Command",
                              f"(Get-AuthenticodeSignature '{p}').Status"],
                             capture_output=True, text=True).stdout.strip()
        print(f"  {f}: {out}")
        if out != "Valid":
            bad.append(f)

print("not signed: " + (", ".join(bad) if bad else "none"))
found = {f.lower() for _, _, fs in os.walk(os.path.join(tmp, "nvidia")) for f in fs}
need = {dll.lower() for *_, dll in g.NVIDIA_PACKAGES}
sys.exit(0 if need <= found else 1)
