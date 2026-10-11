## Install

- **UbiClipper-x.y.z-portable.zip** (works with Smart App Control): unzip anywhere and double-click **Start UbiClipper.bat**.
- **UbiClipper-Setup-x.y.z.exe**: the normal installer. Until the app is code-signed, Windows says "Windows protected your PC": click **More info → Run anyway**. Smart App Control blocks it completely; use the zip.

## What changed

- No more "cublas64_12.dll cannot be loaded" error. NVIDIA doesn't sign its GPU files, so on PCs with Smart App Control Windows may block them. UbiClipper now checks this once and quietly uses the processor instead.
- The portable version removes Windows' "downloaded from the internet" mark on its first start, so you no longer need to unblock the zip by hand.
