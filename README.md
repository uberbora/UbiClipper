# UbiClipper v1.8

Pick a video (6 minutes to 6+ hours), let it find the moments where something
happens — laughter, screams, sudden outbursts, loud reactions — and get
short-form-ready clips (60 s by default, up to 240 s) cut out automatically, turned into 9:16
with your webcam on top, and Turkish (or other language) subtitles burned in,
coloured per person when several people talk. Then post them to TikTok,
Instagram Reels and YouTube Shorts in one click.

## Install (Windows 10/11, 64-bit)

Download from **[Releases](https://github.com/uberbora/UbiClipper/releases/latest)**:

- **UbiClipper-Setup-x.y.z.exe**: the normal installer. No admin rights
  needed; Start menu + desktop shortcut and an uninstaller. Until the app is
  code-signed, Windows says "Windows protected your PC": click
  **More info → Run anyway**.
- **UbiClipper-x.y.z-portable.zip**: the same app without installing. Unzip
  it anywhere and double-click **Start UbiClipper.bat**. Use this if
  *Smart App Control* blocks the installer.

Python, FFmpeg and everything else are included. On the first start the
**Get UbiClipper ready** window downloads the AI models once (about 6 GB with
the AI judge) and, on PCs with an NVIDIA card, the GPU speed-up (about 1.2 GB,
straight from NVIDIA's official packages). Everything after that works
offline. Open it again any time: **Settings → All AI downloads & GPU
speed-up…**

Settings, the AI models and your word fixes live in
`%USERPROFILE%\.ubiclipper`, so updates never touch them. Uninstalling asks
whether to delete them too. Something not working? **Settings → Check setup**
and send the output (the log is in `%USERPROFILE%\.ubiclipper\logs`).

### Run from source (developers)

1. Install **Python 3.10+** (tick "Add Python to PATH") and **FFmpeg**
   (`winget install Gyan.FFmpeg`, macOS: `brew install ffmpeg`).
2. Double-click **`run_windows.bat`** (installs the packages, the NVIDIA
   libraries on NVIDIA PCs and the models, then opens the app), or
   `pip install -r requirements.txt` and `python app.py`.
3. Build the installer yourself: `packaging\build_windows.ps1` (needs
   Inno Setup 6). GitHub Actions does the same for every `v*` tag and
   publishes the result as a release.

## Use it

**App:** start UbiClipper from the Start menu (from source: `run_windows.bat`).
Select a video **or paste a VOD link** (or just **drag a video file or a link
onto the window**) → Analyze → untick moments you don't want (double-click to
preview) → Export checked clips.

Every setting has a small **ⓘ**: hover over it for an explanation.

### Download existing clips

**Download clip…** (or paste / drop a clip link) downloads clips that already
exist: Twitch clips, Kick clips, YouTube Shorts and clips. They're saved to
`<export folder>/Downloaded clips/`, and you can open one right away as a
ready moment to add subtitles, the 9:16 and 1920x1080 versions, title ideas
and posting.

### From a link (Kick / Twitch / YouTube VODs)

Click **Paste link…** or drop the link on the window. Built for slow
connections:

1. only the **audio** is downloaded first (~50-100 MB per hour of stream),
   plus the **chat** for Kick and Twitch,
2. it's analysed like a normal video,
3. only the **video sections of the clips you export** are downloaded.

**Kick** has its own code path: yt-dlp's Kick support is currently broken by
Kick's new video IDs ([yt-dlp #17428](https://github.com/yt-dlp/yt-dlp/issues/17428)).
The new IDs contain the stream's start time, which UbiClipper uses to find
the VOD on the channel and read its stream directly.

**Kick and Twitch** audio and clip video come from the same stream playlists,
so they share one timeline. (Before v0.7 Twitch used a separate audio-only
stream whose timeline could drift from the video over a long VOD: clips,
reasons and subtitles didn't match. Old cached audio is re-downloaded
automatically.) As a safety net, every downloaded clip is checked against the
analysed audio and re-cut if it's off.

Everything is cached in `~/.ubiclipper/downloads/`; delete it to free space.
Sub-only and still-live VODs don't work. If links stop working, run
`update_links.bat`.

**Command line:**
```
python cli.py stream.mp4                     # analyse + export
python cli.py https://kick.com/<channel>/videos/<id>
python cli.py https://www.twitch.tv/videos/123456789
python cli.py stream.mp4 --dry-run           # just list the moments
python cli.py stream.mp4 --max-clips 25 --sensitivity 0.7 --pre-roll 15
```

### Clip list and trimming

Click a column heading (#, Start, Length, Score, **AI**) to sort by it; click
again to flip. **✂ Trim…** opens the trim editor for the selected clip: the
sound around the clip with its score curve, two handles to drag, exact time
fields with ±0.1 s / ±1 s buttons (←/→ keys too), and quick previews of the
whole clip, its first 5 s and its last 5 s. A trimmed clip gets fresh
subtitles on export.

**✎ Edit subtitles…** fixes a clip's subtitles by hand: every line with its
start, end, person (colour) and text. Type the right words (Enter applies),
change times, pick who said a line (select several lines to change them at
once), play a single line, split, merge, delete or add lines. *Transcribe now*
makes subtitles first if the clip has none yet; *Detect speakers* colours the
lines automatically for you to correct. Export uses your edits as they are
(no re-transcribing, and hand-set colours aren't recalculated).

Pick an **export folder** once; it's remembered. Each video gets its own
subfolder, organised like this:

```
<export folder>/<video name>/
  ready_social/      9:16 with captions, for TikTok / Reels / Shorts
  ready_fullscreen/  1920x1080 with captions, for montages and YouTube
  raw/               clean horizontal cuts, no captions
  extras/   thumbnails, .srt subtitle files, clips.json (timings, scores, transcripts)
```

Next to every clip in `ready_social/` there's a **.txt with 3 title ideas and
hashtags** (game, platform, your channel, Turkish discovery tags), built from
what was said and why the clip was picked. For local files, fill in Channel /
Platform / Game in the Export section; links fill these in themselves.

### Subtitles (Turkish by default)

**Also speaks** (Subtitles tab, default English): a second language you
switch to on stream. With the main language fixed, Whisper would otherwise
*translate* those sentences ("Who did this?" became "Kim bu yaptı?"). Now
every sentence is checked and, if it was said in the second language, written
in it (with that language's capital letters and swear list). CLI:
`--also-language en` / `none`.


Uses Whisper (via faster-whisper) with word-level timing, then splits speech
into short 1-3 word captions, TikTok/Reels style.

- **First run downloads the model** (turbo ≈ 1.6 GB) and caches it — later runs start instantly.
- **Models:** `turbo` is the default and the best balance for Turkish. `small`
  is much faster but makes more mistakes; `large-v3` is a bit more accurate
  but several times slower.
- **NVIDIA GPU** is used automatically when the CUDA libraries are installed
  (the GPU speed-up in the Get ready window; from source `install_gpu.bat`). Otherwise it runs
  on CPU — slower, but only the clips are transcribed, never the whole stream.
  The progress bar shows `transcribing (GPU)` or `(CPU)`.
- **Names / words to recognise:** put your name, friends' names, game names,
  catchphrases here (e.g. `Valorant, Ahmet, ezik`). Whisper spells them
  right much more often.
- Turkish uppercase is handled properly (i → İ, ı → I), so captions read
  `İNANILMAZ`, not `INANILMAZ`.
- Whisper's well-known fake lines on silence/music ("Altyazı M.K.",
  "İzlediğiniz için teşekkürler", "Abone olmayı unutmayın") are filtered out.

Already have clips? Caption them without re-analysing:
```
python subtitle.py my_stream_clips/
python subtitle.py clip.mp4 --model small --words "Valorant, Ahmet"
```

CLI subtitle flags: `--language tr|en|auto`, `--model`, `--words`,
`--style "Bold pop"`, `--censor`, `--no-upper`, `--no-burn` (srt only),
`--no-subtitles`, `--device cpu|cuda`.

### Subtitle style

Click **Style…** to pick a preset and tweak it, with a live preview on a frame
of your video:

| Preset | Look |
|---|---|
| Bold pop *(default)* | white Arial Black, the word being spoken turns yellow, captions pop in |
| Classic | plain white with black outline |
| Yellow impact | yellow Impact, pop-in |
| One word | one big word at a time |
| Boxed | normal case on a dark box, spoken word highlighted |

You can change font (any font installed in Windows; check the preview shows
ğ ş ı İ correctly), size, colours, outline, shadow, dark box, words per
caption, animation and position.

**Censor swear words** (a switch on the main screen and in Style…) turns
`amına koyim` into `a***a koyim`, `amk` into `a*k`, etc. in captions only,
which helps with TikTok reach. Normal words that merely start the same
(`ama`, `amca`, `götürmek`, `sıkı`…) are never touched.

### 9:16 vertical

Pick a **Layout**:

| Layout | Use it for |
|---|---|
| Webcam on top + main area | gaming with a facecam: webcam on top, game below, captions at the seam |
| Main area fills the screen | camera-only / just chatting: one area fills the whole phone screen |
| Main area on blurred background | show everything, nothing cut off |

**Set webcam area…** and **Set main area…** let you drag boxes on a frame of
the video. The main-area box is locked to the exact shape it will have in the
clip, so what you draw is what you get; drag inside a box to move it. Areas
are remembered (`~/.ubiclipper/layout.json`).

CLI: `--webcam X,Y,W,H` (source pixels, saved), `--no-webcam`, `--no-vertical`.

#### Where the subtitles go

**Place subtitles…** (9:16 tab) opens a 9:16 frame of your layout with a
sample caption you can drag anywhere. Pick **TikTok**, **Instagram Reels** or
**YouTube Shorts** to see outlines of where that app puts its like/comment/
share buttons, username, Follow/Subscribe button and caption. An outline turns
red and a warning appears when the subtitles would be hidden behind it.
**Check with real subtitles** renders the frame with your actual subtitle
style. The outlines are approximate (apps change, phones differ), so keep a
little distance. **Back to automatic** returns to placing them from the
layout. The 1920×1080 version always keeps its subtitles at the bottom.

### Fixing words Whisper gets wrong

Click **Fix misheard words…** (or open `corrections.txt` in `%USERPROFILE%\.ubiclipper`)
and add lines like `türk 83 => Kırk Seksenüç`. They're
applied to every transcript (case-insensitive, phrases work, timing kept).
The Turkish prompt also includes common slang and swearing, because Whisper
otherwise tends to "hear" a polite phrase instead.

### Settings
| Setting | Default | Meaning |
|---|---|---|
| Max clips | auto | as many as are good enough (Sensitivity decides), up to ~1 per 4 min. Or 5–100, or Custom… for any number |
| Min length | 10 s | short moments are padded with context up to this |
| Max length | 60 s | up to 240 s; under 60 s gets the most reach on short-form apps |
| Setup before moment | 12 s | context before the reaction, so the joke makes sense |
| Sensitivity | 0.5 | how strong a moment must be to count. It never changes *what* counts, only how picky it is: higher = weaker moments also qualify |
| Focus | 0.4 | left: any loud sound counts (great for horror games). Right: only moments where *your voice* is the loud part, so gunfire and explosions stop winning |
| Rank by what's said | on | transcribes the best candidates and moves moments with laughing, reactions or swearing up, and silent ones down (seconds on a GPU) |
| Use chat | on | Kick/Twitch links: moments where chat floods (KEKW, LUL, kdkdkd, 😂) score higher, even if you were quiet |
| Listen to | track 1 | shown when the recording has several audio tracks (OBS). Pick the mic-only track: game sounds are ignored entirely and subtitles get much cleaner |

Your settings, subtitle style, export folder and webcam area are remembered
in `~/.ubiclipper/`.

Speed: a 6-hour stream analyses in well under a minute of CPU (mostly limited
by how fast your disk reads the file); cutting is ~1-3 s per clip.

### A colour per person (up to 10 people)

When more than one person talks in a clip (Discord call, duo stream, IRL),
each person's subtitles get their own colour: person 1 yellow, person 2 green,
person 3 blue, then pink, orange, purple, red, lime, white, peach.

- **Same colour in every clip:** all clips of an export are compared
  together, so the streamer (whoever talks most overall) is yellow everywhere
  and each friend keeps their colour. A clip with only you keeps your normal
  subtitle style.
- **No colour flicker (v1.2):** colours only change when the voice really
  changes, preferably at a pause or the end of a sentence. Moments drowned in
  gunfire or music are ignored by the voice comparison (the listening AI tells
  which bits are speech), and a shout or one odd moment no longer becomes a
  "new person".
- Subtitles tab → **Colour each person differently** and **People**: `Auto`
  is careful and works best for 1–3 people. With 4 or more, pick the number:
  it then separates voices more readily. Click a swatch to change a colour.
- Uses a small voice-fingerprint model (WeSpeaker ResNet34, ~26 MB, downloaded
  once into `~/.ubiclipper/models`). Runs on CPU in a few seconds per clip.
- Limits: voices that sound very alike may share a colour; people talking
  over each other get one colour (whoever Whisper wrote down).
- CLI: `--people auto|2..10|off`.

### Languages

- **App language** (Settings → App language): English and Türkçe. On first
  start the app follows your Windows language when there is a translation.
  Every on-screen text goes through `languages/<code>.json`; to add a
  language, copy `languages/tr.json`, translate the right-hand sides (and the
  `help` texts), rename it (e.g. `es.json`) and it shows up in the menu.
  Untranslated lines simply stay English.
- **Spoken language** (Subtitles tab → Language): 32 languages + auto-detect.
  Funny-word ranking, swear censoring, title ideas, hashtags and Whisper's
  hint prompt have word lists for Turkish, English, Spanish, Portuguese,
  German, French, Italian, Polish, Russian and Arabic
  (`clipper/lang_data.py`); other languages use the English lists, and
  written laughs (hahaha, jajaja, kkkk, mdr, ахах, ㅋㅋ, www…) count in all.
  Japanese, Chinese and Thai captions are written without spaces.
- The AI judge reads any language, writes titles in the stream's language
  and explains its score in the app's language.

### Look and feel

The window is organised in tabs: **Moments**, **Subtitles**, **9:16**,
**Export**, **Accounts** and **Settings**. Dark theme by default; switch to
light in **Settings → Appearance** (applies instantly). Settings also shows
the download cache size (clear it with one click) and runs the setup check.

## Export All: post to TikTok, Instagram and YouTube

After exporting, click **Export All ↗** (or answer *Yes* when export finishes).
Pick the platforms, untick clips you don't want, edit each title and hashtags,
press **Post checked clips**. Clips already posted are marked, so nothing is
posted twice.

First connect your accounts in the **Accounts** tab. Each platform requires
its own free developer app (one-time, 10–20 min). Click **Setup guide** for
step-by-step instructions (`social_setup.html`). What each platform allows a
personal app to do:

| Platform | What happens | Limits |
|---|---|---|
| TikTok | clip lands in your TikTok **drafts/inbox**; you press Post in the app | direct posting needs a TikTok app audit |
| Instagram Reels | published as a Reel with caption + hashtags | needs a Creator/Business account linked to a Facebook Page; login lasts 60 days |
| YouTube Shorts | uploaded as a Short (title, description, tags) | stays **private** until Google audits the project; login expires every 7 days while the consent screen is in Testing |

Keys and login tokens are stored in `~/.ubiclipper/accounts.json`, encrypted
with your Windows account (DPAPI). Nothing is sent anywhere except to the
platform you post to.

### AI (free, runs on your PC, nothing to install)

Two optional AIs in the Moments tab. Both run locally with engines that
UbiClipper already ships for subtitles (onnxruntime and
CTranslate2), so there is no extra program, no account, no API key, and
nothing is sent anywhere. Models download once into `~/.ubiclipper/models`.

- **Listening AI** (on by default, 48 MB once): CED-mini, a sound-recognition
  network trained on Google's AudioSet (2 million YouTube clips, 527 sound
  types). It listens to the whole video in the same pass and recognises
  laughter, screaming, explosions, gunfire and coughs. Laughs count even when
  they're quiet (new reason **Laughter (AI)**), and loud game noise or coughs
  are damped (how strictly follows the Focus slider). Adds roughly 20–60 s
  per hour of video on a laptop CPU.
- **AI judge** (on by default, ~4 GB, downloaded during setup): Qwen3-4B-Instruct, a small
  language model that reads every candidate moment: the transcript, what the
  listening AI heard and what chat wrote. It rates it 0–10, says why
  (**AI: …** in the list) and suggests a title, which becomes the first title
  idea in the post files. It also looks at more candidates (up to 60), so
  quieter funny moments get a chance. About 1 s per moment on an NVIDIA GPU,
  5–15 s on CPU. Works in any language Whisper transcribes (Qwen3 knows 119
  languages); reasons are written in English, titles in the stream's
  language. It turns on *Rank by what's said* (it needs the transcript).
  It can't see the video, and Turkish slang or inside jokes can go over its head.

Settings → AI models: download the judge in advance, **Test** it on a made-up
moment, or delete it to free 4 GB.

CLI: `--no-ai-listen`, `--ai-judge`.

## How it finds moments

Audio is streamed out of the video (never fully loaded into memory) and turned
into a few features every 20 ms. Four detectors then score each half-second:

- **Loud reaction** – much louder than what was happening around it (relative
  to the last few minutes, so game music and mic level don't matter)
- **Sudden outburst** – sharp jump in loudness (jump scares, yelling)
- **Laughter** – loud, voiced, pulsing 3–8 times a second ("ha-ha-ha")
- **Scream** – loud, high-pitched and sustained

Coughs, sneezes, mic bumps and bangs are loud too, but they're *noise* with
no pitch. Every detector is damped on noisy sounds (spectral flatness), so a
coughing fit doesn't become a clip. Breathy laughs still count.

Gunfire and explosions are trickier: a cannon's boom is a low hum, not pure
noise. So each moment also gets a **voice score**: how much of the sound in
the voice band (250-1500 Hz) is clearly pitched like a voice. Only the voice
band is checked because in real streams the game's low rumble is often
10-20 dB louder than your voice and would otherwise hide it (that's what
broke "voice reactions" before v0.6). The **Focus** setting damps loud
moments by how un-voice-like they are. Laughter is detected by its rhythm
and isn't affected.

**Rank by what's said** (the funny-word detector): after the audio pass, a
wider pool of candidates is transcribed (fast on a GPU) and scored on what
was said: laughing written out (hahaha, kdkdkd, jsjsjs), Turkish reactions
(öldüm, oha, yok artık, ne oluyor, ciddi misin…), swearing, shouting and
repeated words. The final order is 60% sound + 40% words; moments where
nobody says anything move down. These transcripts are reused for the
subtitles, so export gets faster too.

Moments where several detectors agree score highest. Each clip is built around
the peak with setup before and the reaction after, then the cut points are
snapped to quiet spots so sentences aren't chopped in half.

## Troubleshooting

**"Subtitles are unavailable" / Windows says "part of this app has been blocked"**
Windows 11 *Smart App Control* blocks unsigned DLLs. The one usually blocked
(`libstdc++-6-….dll`) belongs to PyAV, a video library faster-whisper loads at
start-up. UbiClipper doesn't need it (FFmpeg decodes the audio), so since
v0.3 it skips PyAV when Windows blocks it. If subtitles still fail, run
`check_setup.bat`; it shows exactly which part won't load.

**Subtitles are on CPU even though I have an NVIDIA GPU**
Open **Settings → All AI downloads & GPU speed-up…** and download the GPU
speed-up (CUDA 12 + cuDNN 9 from NVIDIA's official packages). From source:
`install_gpu.bat`.

**AI judge: "too old for this model" or it runs on CPU**
Install the latest UbiClipper (from source: run `run_windows.bat` once); it
needs CTranslate2 4.6.2+ for Qwen3. If the GPU runs out of memory (other games/apps open), the judge
falls back to the CPU by itself; it's slower but gives the same answers.
Analysis never fails because of an AI step: it's skipped with a note in the
status bar.

## Project layout

```
clipper/
  media.py       ffprobe/ffmpeg: probe, stream audio, cut clips, thumbnails
  features.py    one streaming pass -> per-frame audio features
  detectors.py   pluggable detectors -> 0..1 timelines, combined score
  selection.py   score timeline -> clip ranges (length rules, snapping)
  transcribe.py  Whisper wrapper: Turkish prompt, hallucination filter
  subtitles.py   words -> captions -> .srt / .ass -> burned into video
  reframe.py     9:16 layout (webcam on top / blurred fit), one ffmpeg pass
  settings.py    remembered app settings
  funny.py       funny-word scoring of transcripts
  remote.py      VOD links (yt-dlp): audio-first download, clip sections, cache
  kick.py        Kick VODs (new IDs), without yt-dlp
  hls.py         stream playlists: audio + exact sections on one timeline
  chat.py        Kick/Twitch chat replay + chat-reaction signal
  posts.py       title and hashtag ideas
  net.py         browser-like HTTP (curl_cffi when installed)
  pipeline.py    analyze() + export() -> clips + clips.json
  speakers.py    who speaks when (voice fingerprints + clustering)
  listen.py      listening AI: laughter / scream / explosion recognition
  judge.py       AI judge: local language model rates moments
  lang_data.py   per-language words, swear lists, titles, hashtags
  social.py      TikTok / Instagram / YouTube login + upload
app.py           desktop GUI
i18n.py          app translation (languages/*.json)
theme.py         dark / light theme
accounts_ui.py   Accounts tab
post_dialog.py   Export All window
social_setup.html  developer-app setup guide
cli.py           command line
subtitle.py      caption existing clips
check_setup.py   diagnoses installs, GPU, blocked DLLs
region_picker.py drag-a-box window for the webcam / main area
style_editor.py  subtitle style window with live preview
ui_help.py       the ⓘ hover help texts
ready_window.py  the "Get UbiClipper ready" downloads window
clipper/getready.py   what gets downloaded after installing (models, NVIDIA libs)
clipper/bootstrap.py  start-up fixes for the installed app (FFmpeg, no consoles, log)
packaging/       Windows build: build_windows.ps1, Inno Setup script
.github/workflows/build.yml  builds, test-installs and releases the installer
```

## Roadmap — where each planned feature plugs in

| Feature | Where |
|---|---|
| ~~Auto subtitles (Whisper)~~ | done in v0.2 (`transcribe.py`, `subtitles.py`) |
| ~~Funny-word detection~~ | done in v0.6 (`funny.py`) |
| ~~9:16 with webcam on top~~ | done in v0.4 (`reframe.py`); next: auto-detect the webcam with face detection |
| ~~Subtitle fonts / animations~~ | done in v0.5 (`subtitles.py`, `style_editor.py`) |
| ~~AI that recognises laughs / rates moments~~ | done in v1.1 (`listen.py`, `judge.py`) |
| Webcam reactions (faces, motion) | new `Detector` using OpenCV/MediaPipe on low-fps frames |
| ~~Chat reactions~~ | done in v0.7 (`chat.py`), Kick + Twitch |
| ~~Stream replay links~~ | done in v0.6 (`remote.py`) |
| ~~Titles & hashtags~~ | done in v0.7 (`posts.py`) |
| ~~Drag & drop, nicer GUI~~ | done in v0.7 / v1.0 (`app.py`, `theme.py`) |
| ~~Speaker colours~~ | done in v1.0 (`speakers.py`) |
| ~~Export all to socials~~ | done in v1.0 (`social.py`, `post_dialog.py`) |

Adding a detector = subclass `Detector`, implement `compute(ctx)` returning a
0..1 array (one value per 0.5 s), add it to `DEFAULT_DETECTORS`.
