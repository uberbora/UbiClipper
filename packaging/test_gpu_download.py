"""CI check: the GPU speed-up downloader finds NVIDIA's Windows packages and
can download + unpack one (the small CUDA runtime) for real."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clipper import getready as g  # noqa: E402

for pkg, major, dll in g.NVIDIA_PACKAGES:
    w = g._pick_wheel(pkg, major)
    print(f"{pkg}: {w['filename']} ({w['size'] / 1e6:.0f} MB)")

pkg, major, dll = g.NVIDIA_PACKAGES[0]          # cuda-runtime, a few MB
w = g._pick_wheel(pkg, major)
tmp = tempfile.mkdtemp()
dest = os.path.join(tmp, w["filename"])
g._download(w["url"], dest, w["size"], w["digests"]["sha256"], "test",
            lambda m, f: None, lambda: False, 0.0, 1.0)
n = g._extract_dlls(dest, os.path.join(tmp, "nvidia"))
found = [os.path.join(r, f) for r, _, fs in os.walk(tmp) for f in fs if f == dll]
print(f"unpacked {n} DLLs; {dll}: {'found' if found else 'MISSING'}")
sys.exit(0 if found else 1)
