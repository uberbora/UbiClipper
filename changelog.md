# Changelog

Newest first. One entry per working session. Full project state: `handoff.md`.

## 2026-10-12 – Installer, website, GPU on any graphics card (v1.7 → v1.9.0)

### What we changed

**v1.7: custom subtitle position on 9:16**
- New `caption_placer.py`: drag the subtitles anywhere, with generic TikTok/Reels/Shorts UI outlines.
- Placement is stored in `clipper/subtitles.py` as `placement="custom"`, `custom_x/y`, and written as `\pos` in the ASS file.

**v1.8: Windows installer**
- `packaging/build_windows.ps1` bundles python.org Python 3.12, FFmpeg (Gyan essentials) and the app.
- Outputs: an Inno Setup installer (`packaging/ubiclipper.iss`, per-user, EN/TR) and a portable zip with `Start UbiClipper.bat`.
- New start-up module `clipper/bootstrap.py`: bundled FFmpeg on PATH, log file, no console windows, taskbar icon.
- New "Get UbiClipper ready" download window: `ready_window.py` and `clipper/getready.py`.
- `corrections.txt` moved to `~/.ubiclipper`.
- New app icon in `assets/`.
- **CI:** `.github/workflows/build.yml` builds, installs, starts and uninstalls on GitHub Windows machines. Errors appear as annotations, screenshots go to the `ci-shots` branch, and `release=true` publishes `v<version>`.

**v1.8.1: Smart App Control fixes**
- NVIDIA's unsigned CUDA DLLs are detected once in a child process (`gpu_block_reason` in `clipper/transcribe.py`), with a quiet CPU fallback.
- Whisper and the AI judge warm up on the GPU first, so a broken GPU falls back to the CPU instead of failing mid-export.
- The portable launcher runs `Unblock-File` on first start.
- `check_setup.py` prints UTF-8, returns an exit code, and shows model/GPU status.

**v1.9.0: GPU subtitles on any graphics card**
- New `clipper/whisper_onnx.py`: Whisper on ONNX Runtime + DirectML, plugged into faster-whisper.
- New `packaging/models/` and `.github/workflows/models.yml`: export the model to fp16 ONNX, test it against faster-whisper, and publish it as release `model-whisper-turbo-onnx-1`.
- New download item "GPU speech model (any graphics card)".
- The Windows build swaps in `onnxruntime-directml` and drops PyAV.

**Microsoft Store**
- MSIX packaging (`packaging/msix/`) built and test-installed in CI.
- Listing texts in `packaging/store_listing.md`.

**Licence and signing**
- GPL-3.0 `LICENSE`, `THIRD_PARTY.md`.
- "Code signing policy" section in the README, needed for SignPath.

**Website (uberbora.github.io, separate repo)**
- Redesign with the owner's yellow/black pixel logo and an EN/TR switch.
- New UbiClipper download page; its button always points to the newest release.
- New UbiClipper privacy policy.
- System requirements set to: 16 GB RAM, about 10 GB disk, 4+ core CPU, optional DirectX 12 graphics card.

**Roadmap**
- Mobile app phase added: phone companion, phone-ready engine, Android, Play Store, iPhone.
- DirectML item added and marked done for subtitles.
- Code signing marked next.

**Docs:** README install section rewritten; `handoff.md` and this `changelog.md` added.

### Why

- The owner wants to use the app for his own streams and publish it for others, without command windows or `.bat` setups.
- His PC runs Windows 11 with Smart App Control on. SAC blocks:
  - unsigned installers,
  - files from downloaded zips,
  - NVIDIA's cuBLAS and cudart. NVIDIA signs no version of these, in pip or in its own redist archives.
- DirectML runs on NVIDIA, AMD and Intel Arc, and its files are signed by Microsoft.
- The Store and SignPath are the free signing routes open to an individual in Türkiye. Azure Artifact Signing is US/Canada only for individuals.

### Unfinished / watch out for

- **DirectML has never run on a real GPU.** CI has none. The owner must test v1.9.0 on his RTX 4070. Speed and DirectML IO binding are unverified; there is a numpy fallback.
- **Store submission is waiting on the owner.** He needs a Partner Center account, then `packaging/msix/store_identity.json` must be created.
- **SignPath application:** the owner hasn't applied yet.
- **AI judge still on the CPU** when CUDA is unavailable. A DirectML judge is next.
- **Stale release notes:** the v1.8.1 and v1.9.0 release pages show outdated notes, and the Claude session can't edit releases. `packaging/release_notes.md` is now generic.
- **faster-whisper upgrades** can break `OnnxWhisperModel`, which uses internal methods. It is tested with 1.2.1.
- **CPU and graphics-card requirements** on the website are estimates until measured.
- **Support/donation buttons** are planned but waiting on the owner's links. AdSense was discussed and not chosen.
