"""Small ⓘ help icons that show an explanation on hover, plus the help texts."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

HELP = {
    "max_clips": (
        "How many clips to make at most.\n\n"
        "auto: as many as are good enough (the Sensitivity slider decides), "
        "with a sensible upper limit for very long streams.\n"
        "A number (up to 100, or Custom… for any number): the best N moments, "
        "digging deeper into quieter moments if needed."),
    "max_len": (
        "Longest a clip can be, in seconds (up to 240). Under 60 s still "
        "gets the most reach on TikTok, Reels and Shorts; longer clips are "
        "great for YouTube or montages."),
    "min_len": (
        "Shortest a clip can be. Short moments are padded with what happened "
        "around them until they reach this length. Raise it (e.g. 60-120 s) "
        "if you want longer, story-like clips."),
    "pre_roll": (
        "Seconds kept BEFORE the loud/funny moment, so viewers see what "
        "led up to it. Too short and the joke has no setup; too long and "
        "people swipe away before it lands. 8-15 s is usually right."),
    "sensitivity": (
        "How strong a moment has to be to become a clip.\n\n"
        "Left: only the very biggest moments.\n"
        "Right: smaller moments count too, so you get more clips (and more "
        "misses to untick).\n\n"
        "It never changes WHAT counts as a moment, only how picky the app is."),
    "focus": (
        "What kind of loud counts.\n\n"
        "Left (any loud sound): game sounds like guns, explosions and jump "
        "scares count as much as you. Great for horror games.\n"
        "Right (voice reactions): a moment only counts if YOUR VOICE is the "
        "loud part, so gunfire and explosions stop filling the list.\n\n"
        "In the middle, both count but your voice wins ties."),
    "rank": (
        "After finding loud moments, quickly transcribe the best candidates "
        "and move the ones where something is SAID up the list: laughing, "
        "'no way', 'bro what', swearing, shouting… Moments where "
        "nobody says anything move down.\n\n"
        "Uses the subtitle model below (seconds on a GPU, slower on CPU). "
        "The transcripts are reused for subtitles, so export gets faster."),
    "chat": (
        "For Kick and Twitch links: download the VOD's chat and use it. "
        "When chat suddenly floods with messages, laughs (KEKW, LUL, kdkdkd, "
        "😂) or hype, that moment scores higher, even if you were quiet. "
        "Chat's few-second delay is taken into account.\n\n"
        "Only works for links (a local file has no chat). Small chats with "
        "fewer than ~20 messages are ignored."),
    "track": (
        "Your recording has several audio tracks (OBS can record your mic "
        "separately). Pick the track with only your microphone: game sounds "
        "are then ignored completely and subtitles get much cleaner. The "
        "finished clips still use the full mix."),
    "language": (
        "The language you speak on stream. Setting it (instead of "
        "auto-detect) avoids Whisper switching languages on short clips."),
    "also_language": (
        "A second language you switch to on stream (e.g. Turkish with English "
        "in between). Every sentence is checked: if it was said in this "
        "language, the subtitle is written in it. Without this, Whisper "
        "TRANSLATES those sentences into your main language instead of writing "
        "what you said.\n\n"
        "Pick 'None' if you only ever speak one language (slightly faster)."),
    "model": (
        "The speech-to-text model.\n\n"
        "turbo: best balance, recommended.\n"
        "small: much faster, more mistakes.\n"
        "medium: in between.\n"
        "large-v3: most accurate, slowest.\n\n"
        "Each is downloaded once (0.5-3 GB)."),
    "words": (
        "Names and words Whisper should know: your name, friends, game "
        "names, inside jokes. Separate with commas, e.g.\n"
        "Iron Nest, Kırk Seksenüç, Ahmet"),
    "fix_words": (
        "Open the list of automatic fixes. Add a line like\n"
        "türk 83 => Kırk Seksenüç\n"
        "and every future subtitle gets fixed. Your list is kept when you "
        "update the app."),
    "censor": (
        "Hide swear words in the captions: 'fuck' becomes 'f**k', "
        "'amına koyim' becomes 'a***a koyim'. Can help TikTok reach. "
        "The audio isn't changed."),
    "vertical": (
        "Make a 9:16 version for TikTok / Reels / Shorts. With a webcam "
        "area set, your webcam goes on top and the gameplay below; "
        "without one, the gameplay sits on a blurred background."),
    "fullscreen": (
        "Also make a 1920x1080 copy of every clip with the subtitles burned "
        "in, in its own folder (ready_fullscreen). Handy for montages, "
        "compilations and YouTube. The 9:16 versions for TikTok / Reels / "
        "Shorts go to ready_social."),
    "webcam": (
        "Draw a box around your webcam once; it's remembered for every "
        "video until your stream layout changes. Only used by the "
        "'Webcam on top' layout."),
    "layout": (
        "How the 9:16 clip is built:\n\n"
        "Webcam on top + main area: your webcam fills the top, the main area "
        "(usually the game) fills the rest.\n"
        "Main area fills the screen: one area fills the whole phone screen. "
        "Use this for camera-only / just chatting streams: set the main area "
        "around yourself.\n"
        "Main area on blurred background: the main area sits in the middle "
        "over a blurred copy, nothing gets cut off."),
    "main_area": (
        "Choose which part of the stream is shown as the main picture. "
        "The box keeps the exact shape it will have in the clip, so what you "
        "draw is what you get. Not set = the whole frame (centre-cropped)."),
    "export": (
        "Where clips are saved. Each video gets its own folder with:\n"
        "ready  - finished clips to post\n"
        "raw    - clean cuts without captions\n"
        "extras - thumbnails, subtitle files, details"),
    "speakers": (
        "When several people talk (Discord call, friends in the room), each "
        "person's subtitles get their own colour: person 1 yellow, person 2 "
        "green, then cyan, pink, orange… up to 10 people.\n\n"
        "All clips of an export are compared together, so everyone keeps the "
        "same colour in every clip. Person 1 (yellow) is whoever talks most "
        "over all clips, usually you.\n\n"
        "People: 'Auto' is careful: a new colour needs a clearly different "
        "voice, so shouting, game sounds or a bad mic moment don't become a "
        "'new person'. With 4 or more people, pick the number: it then "
        "separates voices more readily.\n\n"
        "Clips with one person keep your normal subtitle colours. The voice "
        "model (26 MB) downloads once."),
    "place_subs": (
        "Pick exactly where the subtitles go on the 9:16 video. Drag a sample "
        "caption over a real frame of your layout, with the buttons of TikTok, "
        "Instagram Reels or YouTube Shorts outlined, so the subtitles never hide "
        "behind a username, a Follow button or the like/comment column.\n\n"
        "The 1920x1080 version keeps its subtitles at the bottom."),
    "get_ready": (
        "Everything UbiClipper downloads after installing, in one window: "
        "speech to text, the listening AI, the voice model, the AI judge and, "
        "on PCs with an NVIDIA card, the GPU speed-up that makes subtitles "
        "several times faster. Stopped downloads continue where they "
        "stopped."),
    "roadmap": (
        "What's planned for UbiClipper next, in build order, and what's "
        "already done. Opens in your browser."),
    "theme": "Dark or light look. Changes immediately and is remembered.",
    "ui_language": (
        "The language of the app's buttons and texts. It starts in your "
        "Windows language when there is a translation, otherwise English.\n\n"
        "This is only the app itself: the language you SPEAK on stream is set "
        "in the Subtitles tab."),
    "ai_listen": (
        "A small sound-recognition AI (trained on 2 million YouTube clips) "
        "listens along and recognises WHAT a sound is: laughter, screaming, "
        "explosions, gunfire, coughs.\n\n"
        "Laughs count even when they're quiet, and loud game noise or coughs "
        "stop winning (how strictly follows the Focus slider). Free, runs on "
        "your PC, adds a little time to the analysis. 48 MB download once."),
    "ai_judge": (
        "A local language AI (Qwen3 4B) reads every candidate moment: what "
        "was said, what the listening AI heard and what chat wrote. It rates "
        "how funny / clip-worthy it is (0-10), says why, and suggests a title.\n\n"
        "Free and private: runs on your PC, nothing is sent anywhere. One "
        "~4 GB download the first time. About 1 s per moment on an NVIDIA GPU, "
        "5-15 s on CPU. Turns on 'Rank by what's said' too (it reads the "
        "transcript). It can't see the video, and Turkish slang or inside "
        "jokes can go over its head."),
    "ai_models": (
        "Downloaded AI models live in your settings folder. The judge is "
        "~4 GB: delete it here if you need the space (it downloads again when "
        "you use it). 'Test' asks the judge to rate a made-up moment so you "
        "can see it works on your PC."),
    "cache": (
        "Audio and clip pieces downloaded from links are kept so nothing "
        "downloads twice. Clear them to free disk space (they download again "
        "when needed)."),
    "accounts": (
        "Connect your accounts once to post clips with Export All. Each "
        "platform only allows uploads through a free developer app you create "
        "(about 15-30 minutes each); 'Setup guide' walks you through it.\n\n"
        "Your logins are stored encrypted with Windows (DPAPI)."),
    "export_all": (
        "Post finished clips straight to your connected accounts, with the "
        "title ideas and hashtags as caption (you can edit them first).\n\n"
        "TikTok: arrives in your TikTok inbox, tap Post in the app.\n"
        "Instagram: published as a Reel.\n"
        "YouTube: uploaded as a Short (private until Google verifies your app)."),
    "post_info": (
        "Each finished clip gets a .txt next to it with 3 title ideas and "
        "hashtags to copy-paste. Fill in your channel, platform and the game "
        "you're playing so the hashtags fit (e.g. #ironnest #kickturkiye).\n\n"
        "For links this is filled in automatically from the stream."),
    "link": (
        "Paste a Kick, Twitch or YouTube VOD link (or drag it onto the window). "
        "Only the AUDIO is downloaded first (much smaller than the video) plus "
        "the chat, then only the video pieces of the clips you export. "
        "Everything is cached, so nothing downloads twice.\n\n"
        "Clip links (Twitch / Kick clips, YouTube Shorts and clips) are simply "
        "downloaded: use Download clip… or paste them here. You can open a "
        "downloaded clip right away to add subtitles and the 9:16 version."),

}


class Tooltip:
    def __init__(self, widget: tk.Widget, text: str, wrap: int = 340) -> None:
        self.widget, self.text, self.wrap = widget, text, wrap
        self.tip: tk.Toplevel | None = None
        self._after: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None) -> None:
        self._cancel()
        self._after = self.widget.after(250, self._show)

    def _cancel(self) -> None:
        if self._after:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _show(self) -> None:
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.attributes("-topmost", True)
        try:
            from theme import current as pal
        except Exception:
            pal = {}
        tk.Label(tw, text=self.text, justify="left", wraplength=self.wrap,
                 background=pal.get("tooltip_bg", "#FFFFE6"),
                 foreground=pal.get("tooltip_fg", "#222"), relief="solid",
                 borderwidth=1, padx=10, pady=8).pack()
        # keep it on screen
        tw.update_idletasks()
        sw = tw.winfo_screenwidth()
        if x + tw.winfo_width() > sw - 10:
            x = max(10, sw - tw.winfo_width() - 10)
        tw.wm_geometry(f"+{x}+{y}")

    def _hide(self, _e=None) -> None:
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


class HelpIcon(tk.Canvas):
    """A small drawn (i) in a circle: looks the same with any font."""

    def __init__(self, parent: tk.Widget, surface: str = "card") -> None:
        super().__init__(parent, width=17, height=17, highlightthickness=0,
                         borderwidth=0, cursor="hand2")
        self.surface = surface
        self.redraw()
        try:
            import theme
            theme.on_change(lambda pal: self.redraw())
        except Exception:
            pass

    def redraw(self) -> None:
        try:
            from theme import current as pal
        except Exception:
            pal = {}
        if not self.winfo_exists():
            return
        accent = pal.get("accent", "#2A7FD4")
        self.configure(background=pal.get(self.surface, pal.get("card", "#FFFFFF")))
        self.delete("all")
        self.create_oval(1, 1, 15, 15, outline=accent, width=1.5)
        self.create_rectangle(7.2, 7, 8.8, 12, fill=accent, outline=accent)
        self.create_oval(7, 3.6, 9, 5.6, fill=accent, outline=accent)


def help_icon(parent: tk.Widget, key: str, style: str = "Help.TLabel") -> tk.Widget:
    """A small (i) that shows HELP[key] on hover. Pack/grid it yourself."""
    icon = HelpIcon(parent, "panel" if style.startswith("Panel") else "card")
    import i18n
    Tooltip(icon, i18n.help_text(key, HELP[key]))
    return icon
