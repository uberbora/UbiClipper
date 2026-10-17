# UbiClipper: handoff document

State as of **15 October 2026, version 1.9.0**. Keep this file updated at the end of every chat; the newest changes are summarised at the top of `changelog.md`. Written for a new chat that has no access to the previous conversation.

## Quick facts

| Thing | Value |
|---|---|
| App repo (public, GPL-3.0) | https://github.com/uberbora/UbiClipper (default branch `main`) |
| Latest release | `v1.9.0`: https://github.com/uberbora/UbiClipper/releases/tag/v1.9.0 |
| GPU speech model release | tag `model-whisper-turbo-onnx-1` on the same repo (prerelease) |
| Website repo | https://github.com/uberbora/uberbora.github.io (live at https://uberbora.github.io) |
| UbiClipper download page | https://uberbora.github.io/ubiclipper/ |
| UbiClipper privacy policy | https://uberbora.github.io/ubiclipper/privacy/ |
| Roadmap | Claude artifact "UbiClipper Roadmap" (private to the owner). The same HTML is bundled in the app as `roadmap.html` and opened by Settings → Roadmap. |
| Owner's GitHub | `uberbora` |
| Public contact e-mail used on the site | `uberyastudios@gmail.com` (already public on the website; don't put other personal data anywhere public) |
| Owner | Turkish streamer on Kick. RTX 4070 laptop, Windows 11 with **Smart App Control (SAC) ON**. UI language Turkish. |

---

## 1. App overview

**What it is:** UbiClipper is a free Windows desktop app.
- It finds the funny or exciting moments in a long stream recording (VOD) and cuts them into short clips.
- It adds subtitles: a colour per speaker, Turkish by default, 30+ other languages.
- It reframes clips to 9:16 for TikTok, Instagram Reels and YouTube Shorts, and can also make a 1920×1080 subtitled copy.
- It can post the clips to those platforms.
- All AI runs locally on the user's PC. Nothing is uploaded unless the user posts.

**Who it's for:**
- First, the owner, a Turkish Kick streamer.
- Then other streamers worldwide. It's published as open source; the owner's framing is "free, fighting the system".

**Core workflow (user's view):**

1. **Get ready (first start only).** The "Get UbiClipper ready" window downloads the AI models once:
   - Whisper turbo (about 1.6 GB)
   - listening AI (48 MB)
   - voice model (26 MB)
   - AI judge (about 4 GB)
   - optionally the NVIDIA CUDA libraries (about 1.2 GB) or the DirectML GPU speech model (about 1.7 GB)
2. **Open a video.** Open a file, paste a Kick, Twitch or YouTube VOD link, or drag a file or link onto the window.
3. **Analyze.** It scores the stream in one audio pass:
   - loudness, voice and laughter detectors
   - listening AI (laugh, scream, cheer, boom)
   - chat replay for Kick and Twitch
   - "rank by words": Whisper transcribes a candidate pool and the text is scored for funny words
   - the AI judge: a local LLM gives a 0–10 score, a reason and a title idea
4. **Review the clip list.** Columns include Score and AI score, all sortable. Double-click to preview. The user can:
   - untick clips,
   - trim them on a waveform timeline (Trim editor),
   - fix subtitles, timing and speakers by hand (Subtitle editor).
5. **Choose the output** on the left-side tabs:
   - 9:16 layout: webcam on top + game below, main area only, or blurred background
   - webcam and main areas drawn as boxes on a frame
   - subtitle style presets
   - subtitle position: automatic, or custom with TikTok/Reels/Shorts UI overlays
6. **Export.** Clips are cut, transcribed, speaker colours assigned (diarization across all clips), subtitles burned in. Results go to `ready_social/` (9:16) and `ready_fullscreen/` (1920×1080).
7. **Export All** (optional) posts to the TikTok, Instagram and YouTube accounts connected in the Accounts tab, with titles and hashtags.

Other features:
- **Clip downloader:** downloads existing Twitch, Kick or YouTube clips.
- **Interface:** Turkish/English with Turkish auto-detected, dark/light theme, an ⓘ hover help on every setting.
- **Fixing misheard words:** `corrections.txt` holds the user's own "misheard → correct" rules.

---

## 2. Tech stack

**Language:** Python 3.12. The Windows build bundles the official python.org 3.12.10 build.

**UI:**
- Tkinter/ttk with a custom dark/light theme (`theme.py`)
- `tkinterdnd2` (optional) for drag and drop

**Video:** FFmpeg and ffprobe, called through `subprocess`.
- The Windows build bundles **Gyan's "release essentials" build** from gyan.dev, which has libass for burning subtitles.
- Subtitles are ASS files burned with FFmpeg's libass.

**Speech to text:**
- **faster-whisper 1.2.1** on **CTranslate2 4.8.x**, model `large-v3-turbo` by default. Other choices: small, medium, large-v3.
- GPU paths:
  - **NVIDIA CUDA** through CTranslate2. Needs cuBLAS, cuDNN and cudart from NVIDIA's pip wheels.
  - **DirectML (new in 1.9.0)** through our own ONNX engine (`clipper/whisper_onnx.py`) on `onnxruntime-directml`. Works on NVIDIA, AMD and Intel Arc.
- PyAV (`av`) is **stubbed and never loaded** (see Key decisions). The Windows build uninstalls it.

**Listening AI:** CED-mini audio tagging, ONNX int8 from a sherpa-onnx GitHub release, run on onnxruntime CPU.
- Kaldi fbank features: 64 mel bins, 2 s windows with a 1 s hop.
- Output groups: laugh, scream, cheer, boom, cough, music, speech.

**Speaker diarization:** WeSpeaker ResNet34 voice embeddings (ONNX from sherpa-onnx), then our own clustering with a Viterbi assignment (`clipper/speakers.py`).

**AI judge:** Qwen3-4B-Instruct-2507, CTranslate2 int8 conversion (`jncraton/Qwen3-4B-Instruct-2507-ct2-int8` on Hugging Face).
- Runs through `ctranslate2.Generator`: CUDA `int8_float16`, otherwise CPU `int8`.
- Tokenised with the `tokenizers` package, ChatML prompt, returns JSON `{score, why, title}`.
- Writes its reasons in the UI language.

**Link downloads:**
- `yt-dlp` for Twitch, YouTube and Kick clips.
- Our own Kick VOD/HLS code (`clipper/kick.py`, `clipper/hls.py`) because yt-dlp's Kick support broke with Kick's new video IDs.
- `curl_cffi` (optional) for browser-like requests.

**Social posting** (`clipper/social.py`):
- OAuth through a local `http://localhost:8765/callback` redirect.
- **Users bring their own developer app keys** (client ID and secret). The guide is `social_setup.html`.
- Tokens are stored encrypted with **Windows DPAPI** in `~/.ubiclipper/accounts.json`.
- Scopes:

  | Platform | Scopes |
  |---|---|
  | TikTok | `user.info.basic,video.upload` |
  | Instagram (Graph) | `instagram_basic,instagram_content_publish,pages_show_list,business_management` |
  | YouTube | `youtube.upload`, `youtube.readonly` |

**Packaging and hosting:**
- Inno Setup 6 installer (per-user, no admin) and a portable zip, both built on **GitHub Actions** (`windows-2022`).
- An MSIX for the Microsoft Store (built and test-installed in CI; not submitted yet).
- Releases on GitHub Releases. The website is static HTML on **GitHub Pages**.

**No database, no backend servers, no paid APIs.** All state is files in `%USERPROFILE%\.ubiclipper`.

**Versions:** these are pinned or noted only where they matter.
- `ctranslate2>=4.6.2`: needed for Qwen3.
- `onnxruntime-directml>=1.20` on Windows.
- faster-whisper is tested with **1.2.1**. Our DirectML adapter subclasses its `WhisperModel`, so a faster-whisper major update could break it (see Known issues).

---

## 3. Architecture

### Flow

```
app.py (Tk GUI) ──► clipper/pipeline.py
                       analyze(): media.stream_audio → features.py → detectors.py (+ listen.py AI,
                                  chat.py signal) → selection.py (clip ranges)
                                  → transcribe a candidate pool (transcribe.py) → funny.py word score
                                  → judge.py (AI judge on the pool) → AnalysisResult
                       export():  cut clips (media.py) → transcribe each clip (transcribe.py; reuses
                                  hand-edited transcripts) → global diarization over all clips
                                  (speakers.py) → subtitles.py (captions → .ass) → reframe.py
                                  (9:16 render + burn) and burn() 1920×1080 → clips.json + post texts
                       Export All: post_dialog.py → social.py uploads
```

### Speech-to-text engine choice

The choice happens in `Transcriber.__init__` in `clipper/transcribe.py`:

1. CUDA (CTranslate2 `float16`) if `gpu_status()` is OK.
2. Otherwise DirectML (`OnnxWhisperModel`), if `dml_usable(model)` is true: the turbo model only, model downloaded, and the one-time child-process probe passed.
3. Otherwise CPU (CTranslate2 `int8`).

The GPU paths run a short warm-up transcription, and any CUDA or DirectML error falls back to the next option.

### Start-up

`app.py` imports `clipper/bootstrap.py` first and calls `setup()`. That:
- puts the bundled `ffmpeg/bin` on PATH,
- sends stdout/stderr to `~/.ubiclipper/logs/ubiclipper.log` when running under pythonw,
- patches `subprocess.Popen` to use CREATE_NO_WINDOW, so no console windows flash,
- sets the taskbar AppUserModelID (skipped inside the MSIX).

### Data on disk: `%USERPROFILE%\.ubiclipper\`

| Path | What |
|---|---|
| `settings.json` | App settings. Keys in `clipper/settings.py` DEFAULTS, `settings_version` 2. |
| `layout.json` | Webcam and main-area boxes for 9:16 |
| `corrections.txt` | User's misheard-word fixes. Moved here in v1.8 from the app folder; the old file is copied over automatically. |
| `accounts.json` | Social account tokens, DPAPI-encrypted |
| `models/ced-mini/`, `models/wespeaker_*.onnx`, `models/judge-qwen3-4b/`, `models/whisper-turbo-onnx/` | Models. Whisper turbo for CTranslate2 lives in the normal Hugging Face cache (`~/.cache/huggingface`). |
| `nvidia/<pkg>/bin/*.dll` | CUDA DLLs downloaded from NVIDIA's PyPI wheels |
| `gpu_check.json` | Remembered "does Smart App Control block the NVIDIA DLLs" result |
| `dml_check.json` | Remembered DirectML probe result, keyed by ORT version, model size and GPU name |
| `downloads/` | Cache of audio and sections downloaded from links |
| `logs/ubiclipper.log` | Log file (for bug reports) |

### Key files

**Top level**

| File | Purpose |
|---|---|
| `app.py` | Main Tk window: tabs (Moments, Subtitles, 9:16, Export, Accounts, Settings), clip list, actions, settings load/save |
| `ready_window.py` | "Get UbiClipper ready" download window (checkboxes, progress, stop/continue) |
| `caption_placer.py` | Drag-the-subtitle window for 9:16 with TikTok/Reels/Shorts UI zone outlines |
| `subtitle_editor.py` | Hand-fix words, timing, speaker, split/merge lines. Saves `edited`/`speakers_fixed` flags. |
| `trim_editor.py` | Waveform and score timeline with start/end handles |
| `style_editor.py` | Subtitle style window with live preview |
| `region_picker.py` | Drag-a-box window for the webcam and main area |
| `post_dialog.py` | Export All window |
| `accounts_ui.py` | Accounts tab |
| `social_setup.html` | Developer-app setup guide |
| `i18n.py` | Runtime translation. Patches Tk text/title/messagebox and similar; strings come from `languages/tr.json` (`strings` + `help`). |
| `languages/tr.json` | Turkish UI strings |
| `theme.py` | Dark and light palettes and ttk styles |
| `ui_help.py` | ⓘ hover help texts (key → English; Turkish in `tr.json` `help`) |
| `check_setup.py` / `check_setup.bat` | Diagnostics (FFmpeg, packages, GPU, DirectML, models). Exit code 1 if something is broken; used by CI. |
| `get_models.py` | Console model downloader (source installs only) |
| `cli.py` | Command line |
| `subtitle.py` | Caption existing clips |
| `run_windows.bat`, `install_gpu.bat`, `update_links.bat` | Source-install helpers (pip). `update_links` updates yt-dlp and works in the bundled Python too. |
| `roadmap.html` | Bundled copy of the roadmap |

**`clipper/`**

| File | Purpose |
|---|---|
| `__init__.py` | `__version__` (currently `"1.9.0"`) |
| `bootstrap.py` | Installed-app start-up fixes (FFmpeg path, log file, no consoles, icon, `packaged()`/`installed()`) |
| `getready.py` | Everything downloaded after install: `ITEMS`, `status()`, `get()`, NVIDIA wheel download/extract, DirectML model download |
| `transcribe.py` | Whisper wrapper: prompts, hallucination filter, mixed-language re-transcription, corrections, CUDA/DirectML/CPU selection, SAC detection (`smart_app_control_on`, `pe_signed`, `gpu_block_reason`) |
| `whisper_onnx.py` | **DirectML engine.** `OnnxEngine` implements CTranslate2's `encode`/`detect_language`/`generate`/`align`. `OnnxWhisperModel` = faster-whisper `WhisperModel` with that engine. Also IO binding, the probe and `dml_status`. |
| `listen.py` | Listening AI (CED) |
| `speakers.py` | Diarization: `voices`, `find_people`, `assign` (Viterbi), `diarize_many`, `diarize` |
| `judge.py` | AI judge (download, prompt, parse, CUDA warm-up with CPU fallback) |
| `pipeline.py` | `analyze()` and `export()` |
| `media.py` | ffprobe/ffmpeg wrappers |
| `features.py` | Per-frame audio features |
| `detectors.py` | Detectors and the combined score |
| `selection.py` | Timeline → clip ranges |
| `funny.py` | Funny-word scoring |
| `lang_data.py` | Per-language words, swear lists, titles, hashtags, Whisper prompts |
| `subtitles.py` | Captions → ASS (styles, speaker colours, censoring, custom `\pos`) and `burn()` |
| `reframe.py` | 9:16 layouts and render. Also defines `CONFIG_DIR`. |
| `remote.py`, `kick.py`, `hls.py`, `chat.py`, `clipdl.py`, `net.py` | Links, Kick/Twitch VODs, chat replay, clip downloads, HTTP |
| `posts.py` | Titles and hashtags |
| `social.py` | Uploads |
| `settings.py` | Settings defaults and migration |

**`packaging/`, CI and docs**

| File | Purpose |
|---|---|
| `packaging/build_windows.ps1` | Builds `dist/UbiClipper`: copies python.org Python, installs packages, removes `av`, swaps `onnxruntime` for `onnxruntime-directml`, adds FFmpeg and the app, runs `check_setup`, makes the portable zip, Inno installer and MSIX |
| `packaging/ubiclipper.iss` | Inno Setup script: per-user, EN/TR, asks on uninstall whether to delete `.ubiclipper` |
| `packaging/Start UbiClipper.bat` | Portable launcher. Runs `Unblock-File` on first start, then `pythonw app.py`. |
| `packaging/msix/AppxManifest.template.xml`, `packaging/msix/Assets/` | Store package. Identity is read from `packaging/msix/store_identity.json` (**doesn't exist yet**; test identity used). |
| `packaging/store_listing.md` | Store listing texts EN/TR and the runFullTrust justification |
| `packaging/models/export_whisper_onnx.py`, `test_whisper_onnx.py` | Export Whisper turbo to ONNX fp16 (fixed 448-slot KV cache, `beam` gather input, alignment-head `qk` output), and test against faster-whisper |
| `packaging/test_gpu_download.py`, `probe_nvidia.py`, `probe_redist.py` | CI checks of NVIDIA downloads and signatures |
| `packaging/release_notes.md` | Body text for GitHub releases |
| `.github/workflows/build.yml` | Builds on every manual run; `release=true` publishes `v<version>`. Also installs, starts, screenshots and uninstalls; test-signs and installs the MSIX; pushes screenshots to the `ci-shots` branch. Uploads two artifacts: `ubiclipper-windows` (exe, zip, msix; kept 7 days) and `ubiclipper-logs` (screenshots and logs; kept 3 days). |
| `.github/workflows/models.yml` | Exports and tests the DirectML model; `publish=true` attaches it to a release |
| `.github/workflows/probe-nvidia.yml` | One-off NVIDIA signature probe |
| `README.md`, `THIRD_PARTY.md`, `LICENSE` | README includes a "Code signing policy" section for SignPath; `LICENSE` is GPL-3.0 |

**Website repo (`uberbora.github.io`)**

| File | Purpose |
|---|---|
| `index.html` | App shelf: UbiClipper featured, plus UbiChef, UbiReader, UbiTracker for Android |
| `ubiclipper/index.html`, `ubiclipper/privacy/index.html` | Download page and privacy policy |
| `assets/site.css`, `assets/site.js` | Shared look; EN/TR switch; the download button asks the GitHub API for the newest release assets |
| `assets/uberbora.svg/.png` | Owner's pixel "U" logo (yellow `#E1C02C` and black) |
| Unchanged files | Existing privacy pages (`ubichef/`, `ubireader/`, `ubitracker/`), `ubichef/r/` (recipe deep link) and `.well-known/assetlinks.json`. **Don't touch these.** |

---

## 4. Key decisions (and rejected approaches)

**Everything free and local, no extra installs**
- The AI uses local engines that ship with the app: CTranslate2, onnxruntime, and models downloaded once.
- Rejected: Ollama and any cloud or paid API.
- The AI judge download is on by default (`settings_version` 2 forces `ai_judge=True`); the owner wants it installed for everyone.

**PyAV is never loaded.** faster-whisper imports `av`; on Windows with SAC, PyAV's unsigned DLLs (`codeccontext.pyd`, `libstdc++`) trigger "part of this app was blocked". `_stub_pyav` always stubs it and FFmpeg decodes the audio instead. The Windows build uninstalls `av`.

**Bundled official Python, not PyInstaller.**
- `python.exe`/`pythonw.exe` and the stdlib are signed by the PSF, so SAC trusts them.
- A custom PyInstaller bootloader would be unsigned and blocked, and tends to trip antivirus.
- The app starts as `python\pythonw.exe app.py`.

**Settings and models live in `~/.ubiclipper`, not the app folder.** Updates and uninstalls never touch them, and the MSIX install folder is read-only.

**GitHub Actions builds everything.**
- The cloud environment can't build Windows binaries; the owner's PC is used only for testing.
- Tags can't be pushed from the Claude session (proxy 403), so releases are made by `build.yml` with `release=true`, which creates the tag.
- The Claude session also can't edit releases, set repo variables, read Actions logs or download artifacts.
- CI reports errors as **annotations**, readable through `gh api .../check-runs/<job>/annotations`. Screenshots and the test log go to the **`ci-shots` branch**.

**CI artifacts expire fast** (15 Oct 2026). The owner's Actions artifact storage filled up because every `build.yml` run kept its exe, zip and msix for GitHub's default 90 days.
- Now: installers kept **7 days** (long enough to test on the owner's PC and to download the `.msix` for the Store; rerun the workflow for a fresh copy), logs and screenshots **3 days** (screenshots and `test.log` are also on `ci-shots`).
- Artifacts are throwaway copies of each run's output. Release assets (exe, zip) are separate, never expire and don't count toward Actions storage, so deleting all artifacts is safe.
- GitHub keeps no minimum: even the newest artifact expires after its retention.
- Rejected: `paths-ignore` for Markdown-only commits. No workflow runs on branch pushes (`build.yml`: manual runs and `v*` tags; the other two: manual only), path filters aren't evaluated for tag pushes, and adding a branch trigger would start *more* builds.
- Not done (owner decided deleting all old artifacts is fine): an automatic "keep the 2 newest artifacts" cleanup step, and attaching the `.msix` to releases.

**NVIDIA CUDA under Smart App Control.**
- NVIDIA ships **no signed cuBLAS or cudart for Windows**. This was checked for every recent version, both pip wheels and the developer.download.nvidia.com redist archives.
- So with SAC ON, CUDA can't work.
- Approach: test once in a child process (`gpu_block_reason`), remember the result, and fall back quietly.
- Rejected: pinning a "signed" version (none exists), and re-signing NVIDIA DLLs ourselves.

**DirectML engine design.**
- Rejected alternatives:
  - **sherpa-onnx DirectML:** would need custom native builds, which are unsigned.
  - **whisper.cpp with Vulkan:** unsigned native build.
  - **onnxruntime-genai Whisper:** no word timestamps.
- Chosen:
  - our own ONNX export plus a **faster-whisper `WhisperModel` subclass** whose `.model` is our `OnnxEngine`. This keeps faster-whisper's VAD, temperature fallback, prompts and word timestamps unchanged.
  - Word timestamps use openai-whisper's method: alignment-head cross-attention, median filter, then DTW.
  - Native fp16 export with `model.half()` and a plain LayerNorm. The onnxconverter float16 conversion failed on LayerNormalization type mismatches.
  - Cross k/v use batch 1 and broadcast. The `beam` input does the cache gather inside the graph, so IO binding can keep the caches on the GPU.
- Verified in CI: fp32, fp32 with IO binding, and fp16 all match CTranslate2 **exactly** on jfk.wav (text 1.000, timing diff 0.000 s).

**Microsoft Store + SignPath for signing** (the owner chose this).
- Azure Artifact Signing is unavailable for individuals in Türkiye.
- Certum's open-source certificate (about €49) is the fallback if SignPath refuses.
- EV certificates were rejected: they no longer bypass SmartScreen.

**Licence: GPL-3.0** (owner chose this over MIT).

**Website on uberbora.github.io**, not a new site or domain.
- Design: the owner's yellow/black pixel logo, stepped "pixel corner" clip-paths, Archivo plus Atkinson Hyperlegible fonts, EN/TR switch.
- Platform UI overlays in the caption placer are **generic outlined zones** only: no logos and no copy of any platform's real UI.

**Ads.** AdMob is for mobile apps only. AdSense on the website was discussed and **not chosen for now**: approval is unlikely with little content, earnings would be tiny, it needs a cookie banner, and it conflicts with the "no tracking" message. Support buttons were proposed instead (see Next steps).

**Translation.** The Turkish UI says "AI", never "YZ" (owner correction). Reasons shown inside the app are **uncensored**; swear censoring applies only to the burned subtitles (owner correction).

**Mixed-language subtitles.**
- How it works: for each segment of 0.8 s or longer, language detection runs. If p(alt) ≥ 0.5 and ≥ 1.5 × p(main), the segment is re-transcribed in the second language ("Also speaks", default English).
- Rejected: forcing Turkish for everything, which translated English speech into Turkish.

**Diarization parameters.**
- Constants:

  | Constant | Value |
  |---|---|
  | `CLUSTER_THRESHOLD` | 0.25 |
  | `MIN_SHARE` | 0.08 |
  | `MIN_WINDOWS` | 5 |
  | `MERGE_ABOVE` | 0.5 |
  | `SWITCH_COST` | 0.30 |
  | `PAUSE_SWITCH_COST` | 0.05 |

- "Told" mode, when a specific number of people is chosen: threshold +0.05, minimum 3 windows, minimum share 0.03.
- A speech mask drops gunfire and music windows.
- `MERGE_ABOVE` 0.4 over-merged and was rejected. Per-clip diarization made colours flicker, so it runs globally across all clips of an export.

---

## 5. Current state

### Working (tested on the owner's PC unless noted)

- **Analysis:** audio detectors, listening AI, chat signal, rank by words, AI judge with AI score column (sortable).
- **Subtitles:**
  - style presets, speaker colours (global diarization)
  - Turkish plus 30+ languages, mixed-language ("Also speaks")
  - correction rules
  - subtitle editor and trim editor
- **Output:**
  - 9:16 layouts and custom subtitle position with platform overlays (v1.7)
  - 1920×1080 subtitled copy
  - max clip length 240 s; max clips auto/75/100/custom
- **Links:** Kick, Twitch and YouTube VOD links; clip downloader.
- **Interface:** Turkish/English UI, dark/light theme, in-app roadmap.
- **Installed app (v1.8+):**
  - The **portable zip** works on the owner's PC with SAC ON after unblocking. Since v1.8.1 the launcher unblocks by itself.
  - **The Setup.exe is blocked by SAC** because it's unsigned. Expected until it's signed.
- **NVIDIA under SAC:** since v1.8.1 there's no error box; it detects the block once and uses the CPU.
- **CI:** builds, installs, starts, screenshots and uninstalls on GitHub's Windows machines; the MSIX test-installs and starts there.

### Partially done / untested

- **DirectML GPU subtitles (v1.9.0):** built, matches CTranslate2 exactly on the CPU in CI, published. **Never run on a real GPU yet.**
  - CI has no GPU; Microsoft's Basic Render Driver is refused by ONNX Runtime.
  - Whether IO binding with device `"dml"` works in this ORT version is unknown. There is a fallback to plain numpy calls.
  - **The owner must test it** (see Next steps).
- **Microsoft Store:** MSIX builds and installs in CI with a test identity. Not submitted. Needs the owner's Partner Center account and identity values.
- **SignPath:** the code signing policy is in the README. **The owner hasn't applied yet.**
- **Social posting** (TikTok, Instagram, YouTube): code exists and the user brings their own developer app keys. **Real uploads with real accounts were never confirmed** in this conversation.
- **Website:** live. No real app screenshots yet; it uses an illustrated timeline instead. The system requirements on the UbiClipper page were updated on 12 Oct 2026:
  - 16 GB RAM, about 10 GB disk (agreed with the owner)
  - CPU 4+ cores; optional DirectX 12 graphics card with 4 GB VRAM, 6 GB+ for the AI judge on NVIDIA (estimates)

### Not started

- AI judge on DirectML (planned next).
- Auto-updates, first-run wizard, bug-report button, licence/privacy note inside the app.
- Support/donation buttons (discussed, waiting on the owner's links).
- Reopen a past link: pick an already downloaded VOD/clip from the Storage cache and continue where you left off (added to the roadmap 16 Oct 2026). Needs a small info file per link folder (link, title, date), since folders are only named `site_id`, and saved analysis results, which aren't stored today.
- Watch my channel, batch mode, scheduled posting, stats.
- Webcam reaction detection, auto-find the webcam, smart zoom, sound effects.
- More interface languages beyond Turkish/English.
- Mobile app (Android first, iOS later). On the roadmap only:
  - phone companion
  - phone-ready engine
  - Android app
  - Play release
  - iPhone

---

## 6. Known issues and limitations

**Smart App Control (the owner's PC has it ON)**
- An unsigned Setup.exe is blocked entirely.
- A downloaded zip needs its "from the internet" mark removed. The portable launcher does `Unblock-File` on first start; before v1.8.1, users had to tick Properties → Unblock.
- NVIDIA CUDA DLLs are unsigned and get blocked, so on the owner's PC the GPU path is DirectML (untested) or the CPU.
- Turning SAC off may not be reversible without resetting Windows. This is uncertain; recent Windows builds may have changed it.

**AI judge runs on the CPU** when CUDA is unavailable, which is the owner's case. Slower: a few seconds per moment.

**DirectML engine risks**
- Speed is unknown. The decoder loop and beam search are Python/numpy.
- DML always uses adapter 0: on hybrid iGPU/dGPU laptops it might pick the integrated GPU. Unverified.
- It only supports the **turbo** model; other model choices use CTranslate2.
- The probe result is cached in `dml_check.json`. Delete that file to force a re-test.

**faster-whisper version coupling.** `OnnxWhisperModel` overrides `WhisperModel.__init__` and `encode`, and relies on internal method names (`_get_feature_kwargs`, `generate_segments` calling `self.model.generate/align/detect_language`). Pin or re-test before upgrading faster-whisper (tested: 1.2.1).

**Release body text.** The v1.8.1 and v1.9.0 releases show stale notes, and the Claude session can't edit releases. `packaging/release_notes.md` is now generic.

**Actions artifact storage was full** (15 Oct 2026). The owner deleted all old artifacts the same day. GitHub recalculates storage usage every 6–12 hours, so the next `build.yml` upload may still fail if run too soon; if so, wait and rerun. Shorter retention applies only to new artifacts; if storage fills up again, delete them by hand (command in Setup and running). The `.msix` exists only as an artifact (releases attach only exe and zip), so it disappears after 7 days.

**GPL and FFmpeg.** The bundled FFmpeg is a GPL build; the app is GPL-3.0, so they're compatible. `THIRD_PARTY.md` lists the parts.

**Turkish glyphs** looked broken only in the Linux test environment's screenshots (missing fonts). Not a bug on Windows.

**Kick:** yt-dlp's Kick VOD support is broken (yt-dlp issue #17428), so our own Kick code path is used. Kick or Twitch site changes can break links; `update_links.bat` updates yt-dlp.

**AdSense:** possible technically (`ads.txt` at the root of uberbora.github.io), but not done (see Key decisions).

---

## 7. Next steps (priority order)

1. **Owner tests v1.9.0 DirectML on the RTX 4070 (SAC ON).**
   - Use the portable zip, then Settings → All AI downloads & GPU speed-up… → "GPU speech model (any graphics card)" (1.7 GB). It runs a one-time card test.
   - Export clips and check that the progress bar says "transcribing (GPU)".
   - If it fails, read `%USERPROFILE%\.ubiclipper\logs\ubiclipper.log` and `dml_check.json`.
   - Then fix and measure speed against the CPU. Possible work: speed up the decoder loop, and verify DirectML IO binding.
2. **Microsoft Store submission.** The owner creates the Partner Center individual account (free) and reserves "UbiClipper". The next chat:
   1. writes `packaging/msix/store_identity.json` with `Name`, `Publisher`, `PublisherDisplayName` from Partner Center → Product identity,
   2. reruns `build.yml`.
   The owner then uploads the `.msix` from the Actions artifact (kept only 7 days; rerun `build.yml` if it has expired), using the texts in `packaging/store_listing.md` plus 2–3 real screenshots.
3. **SignPath Foundation application** (owner applies at signpath.org/apply: repo URL, GPL-3.0, GitHub Actions). If accepted:
   - add SignPath signing steps to `build.yml` (Setup.exe and uninstaller),
   - change the README "Code signing policy" from "application in progress" to final.
   - If refused: Certum Open Source certificate (about €49, cloud signing via SimplySign; CI automation unclear).
4. **AI judge on DirectML** via onnxruntime-genai-directml (Microsoft-signed).
   - There's no ready DirectML build of Qwen3-4B: `onnx-community/Qwen3-4B-ONNX` has only cpu/cuda/webgpu. We'd build one with the onnxruntime-genai model builder in CI and host it.
   - GitHub release assets are limited to 2 GB per file. The int4 model may need splitting, or Hugging Face hosting.
5. **Support buttons.** The owner sets up GitHub Sponsors and/or a Turkish IBAN donation page (ByNoGame/Oyuneks/İtemSatış) and sends the links. Then add:
   - a `.github/FUNDING.yml`,
   - buttons on the website home and UbiClipper pages,
   - "Support UbiClipper ♥" in Settings.

   Region checks done: GitHub Sponsors lists Türkiye as supported; Patreon pays to Türkiye via Payoneer or TL bank transfer; Buy Me a Coffee pays via Stripe Express (Türkiye listed); Ko-fi and PayPal are not usable.
6. **Remaining roadmap phase "Ready for other people":**
   - auto-updates (GitHub Releases based)
   - first-run wizard
   - bug-report button
   - licence/privacy note in the app
7. Later phases, in roadmap order:
   - **Everyday editing:** reopen a past link from the download cache (size M; S if it only reuses the audio and re-analyses).
   - **Hands-off workflow:** watch my channel, batch mode, scheduled posting, stats.
   - **Smarter clips:** webcam reactions, auto-find webcam, smart zoom, sound effects.
   - **Reach:** more UI languages: ES, PT, DE.
   - **Mobile app:** phone companion first, then Android, Play Store, iPhone.

---

## 8. Conventions and preferences

**Owner's communication style:** casual English; Turkish is his native language. He tests on his own PC and reports back with screenshots and clips.
- Give concise summaries of what changed and what to test.
- Don't over-explain.
- Be honest about what wasn't tested.

**Delivery**
- The owner wants **finished, ready-to-run builds**, not diffs.
- Before the GitHub era: zips of the whole project, also copied into a versioned folder on the owner's desktop through the device bridge when it was connected.
- Now: push to GitHub and release through `build.yml` with `release=true`.
- Bump `clipper/__init__.py` `__version__` for each release.
- Update the roadmap (artifact source plus the bundled `roadmap.html`) whenever something ships.

**Git**
- Commit as `Claude <noreply@anthropic.com>`; a stop hook flags other identities.
- Commit message trailer:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01XiD1aEJy5omg83iEXcBXKj
  ```
  (Use the current session's link in a new chat.)
- Push to `main`. The owner didn't ask for PRs.

**Code style**
- Python 3.10+ with `from __future__ import annotations` and type hints.
- Module docstrings explain *why*. Plain readable code, no heavy frameworks.
- UI strings are written in English in code; Turkish goes in `languages/tr.json`. Every new UI string needs a Turkish entry, and every new setting needs an ⓘ help key in `ui_help.py` plus its Turkish `help` text.
- Windows scripts (`.bat`, `.iss`, `.ps1`) use CRLF; `.gitattributes` enforces it.
- Avoid `"` inside PowerShell `-c` Python one-liners (quoting breaks).

**Corrections the owner made**
- Turkish UI: "AI", not "YZ".
- Don't censor words in the app's reasons; censor only the burned subtitles.
- Platform templates must be generic outlines; no brand UI copies.
- The AI judge download is on by default for everyone.
- Speaker colours must not flicker between sentences.

**Writing in UI and docs:** plain words, sentence case, short. Explain limitations honestly in the UI (for example "Blocked by Windows' Smart App Control: use the GPU speech model below").

**Security and privacy**
- No personal data in the public repo; the owner's email is used only for identification.
- Never put secrets in the repo; social app keys are entered by each user and DPAPI-encrypted.
- The owner declined computer-use control of his PC. When the device bridge is connected, only use folders he has granted (his project folder, `%USERPROFILE%\.ubiclipper`, and his Python install for reading). This file is in a public repo: keep personal paths and private details out of it.

---

## 9. Setup and running

### Users (Windows 10/11 64-bit)

- **Portable (works with SAC):** download `UbiClipper-<ver>-portable.zip` from Releases, unzip, double-click **Start UbiClipper.bat**. The first start unblocks the files.
- **Installer:** `UbiClipper-Setup-<ver>.exe`. Unsigned for now: "More info → Run anyway"; blocked entirely by SAC.
- **First start:** the Get-ready window downloads the models: about 6 GB, plus 1.2 GB for CUDA or 1.7 GB for the DirectML model.
- **Diagnostics:** Settings → Check setup. Log in `%USERPROFILE%\.ubiclipper\logs`.

### From source (developers)

1. Install Python 3.10+ and FFmpeg (`winget install Gyan.FFmpeg`).
2. Run `run_windows.bat`. It installs `requirements.txt` and `requirements-optional.txt`, `requirements-gpu.txt` on NVIDIA PCs, downloads the models with `get_models.py`, and starts the app.
3. Or run `pip install -r requirements.txt` then `python app.py`.
4. On Windows, `requirements.txt` installs `onnxruntime-directml`. faster-whisper also pulls in plain `onnxruntime`, and both provide the same module, so uninstall both and reinstall only `onnxruntime-directml --no-deps`, as `build_windows.ps1` does.

### Build and release (GitHub Actions; can't be done from the Claude cloud session itself)

| Task | Command / where |
|---|---|
| Test build | `gh workflow run build.yml -R uberbora/UbiClipper --ref main` |
| Release | `gh workflow run build.yml -R uberbora/UbiClipper --ref main -f release=true`. Uses `__version__` for the tag `v<version>`. |
| DirectML model | `gh workflow run models.yml ... [-f publish=true -f tag=model-whisper-turbo-onnx-N]` (bump `MODEL_TAG` in `clipper/whisper_onnx.py` if the tag changes) |
| Read CI results | `gh api repos/uberbora/UbiClipper/check-runs/<job_id>/annotations` (logs and artifacts aren't downloadable from the session) |
| CI screenshots | `git fetch origin ci-shots` |
| Delete all Actions artifacts (owner's PC, after `gh auth login`) | `gh api repos/uberbora/UbiClipper/actions/artifacts --paginate -q '.artifacts[].id' \| ForEach-Object { gh api -X DELETE repos/uberbora/UbiClipper/actions/artifacts/$_ }` (PowerShell) |
| Local Windows build | `powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1` (python.org 3.12 and Inno Setup 6 needed; Windows SDK for the MSIX; `-NoInstaller`/`-NoMsix` to skip) |

### Configuration and keys

- There are **no environment variables or API keys for the app itself.**
- **Social posting:** each user creates their own developer apps and enters the keys in the Accounts tab (guide: `social_setup.html`):
  - TikTok: Client key and secret
  - Meta: App ID and secret
  - Google: OAuth client ID and secret
- **Store:** `packaging/msix/store_identity.json` (not secret; doesn't exist yet).
- **Test-only environment variable:** `UBI_ONNX_BIND=cpu` forces the IO-binding code path on the CPU.

### Tests

- There's no unit-test suite.
- Checks are: `check_setup.py`, the CI install/start/uninstall test, the MSIX test, `packaging/models/test_whisper_onnx.py` (ONNX against faster-whisper) and `packaging/test_gpu_download.py`.
- GUI changes were previously checked with scripted Tk drives under Xvfb plus screenshots in the cloud environment; those scripts are not in the repo.

---

## Open questions (never decided)

- Which support/donation platforms to use, and their links.
- Whether to get a custom domain later; none bought.
- Whether to keep Setup.exe at all once the Store version exists, or only Store plus portable.
- CPU and graphics-card requirements are estimates, not measured. Measure them once the DirectML test has run.
  - RAM: 16 GB and disk about 10 GB (agreed with the owner).
  - CPU: 4+ cores.
  - Graphics card, optional: DirectX 12 with 4 GB VRAM; 6 GB+ for the AI judge on NVIDIA.
- Whether to keep the `ci-shots` branch public (it holds CI screenshots only).
- Whether to attach the `.msix` to releases too, so it doesn't vanish with the 7-day artifacts.
