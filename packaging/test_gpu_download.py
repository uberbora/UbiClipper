"""CI check: the GPU speed-up downloader gets the pinned NVIDIA packages, and
every DLL users will load is validly signed (Smart App Control blocks unsigned
DLLs, so an unsigned build here means a broken GPU speed-up for many users)."""

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

print("unsigned or invalid: " + (", ".join(bad) if bad else "none"))
sys.exit(1 if bad else 0)
