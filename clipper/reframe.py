"""9:16 vertical layout for TikTok / Reels / Shorts.

With a webcam area set:          Without one:
  ┌──────────────┐                 ┌──────────────┐
  │    webcam    │                 │ blurred copy │
  ├──────────────┤  <- captions    │┌────────────┐│
  │              │                 ││  gameplay  ││  <- captions below
  │   gameplay   │                 │└────────────┘│
  │ (centre crop)│                 │ blurred copy │
  └──────────────┘                 └──────────────┘

Regions are stored as fractions of the frame, so one saved layout works for
1080p, 1440p, 720p VODs alike. Everything renders in a single ffmpeg pass,
captions included.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field

from .media import _require

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".ubiclipper")
_OLD_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".streamclipper")
if not os.path.exists(CONFIG_DIR) and os.path.isdir(_OLD_CONFIG_DIR):
    try:  # app was renamed StreamClipper -> UbiClipper: keep the user's settings
        os.rename(_OLD_CONFIG_DIR, CONFIG_DIR)
    except OSError:
        pass
LAYOUT_FILE = os.path.join(CONFIG_DIR, "layout.json")


@dataclass
class Region:
    """Rectangle as fractions (0..1) of the source frame."""
    x: float
    y: float
    w: float
    h: float

    def pixels(self, W: int, H: int) -> tuple[int, int, int, int]:
        """Even-numbered pixel box clamped to the frame (x264 needs even sizes)."""
        x = max(0, min(int(self.x * W) // 2 * 2, W - 2))
        y = max(0, min(int(self.y * H) // 2 * 2, H - 2))
        w = max(2, min(int(self.w * W) // 2 * 2, (W - x) // 2 * 2))
        h = max(2, min(int(self.h * H) // 2 * 2, (H - y) // 2 * 2))
        return x, y, w, h


LAYOUT_MODES = {
    "Webcam on top + main area": "stack",
    "Main area fills the screen": "fill",
    "Main area on blurred background": "blur",
}


@dataclass
class VerticalLayout:
    webcam: Region | None = None
    gameplay: Region | None = None      # the "main area"; None = whole frame
    mode: str = "auto"                  # auto | stack | fill | blur
    width: int = 1080
    height: int = 1920
    cam_max_share: float = 0.40         # webcam may use at most 40% of height
    cam_min_share: float = 0.25

    # ------------------------------------------------------------ geometry
    @property
    def effective_mode(self) -> str:
        """auto = webcam on top when a webcam area is set, else blurred fit.
        'stack' without a webcam area falls back to the blurred fit."""
        m = self.mode if self.mode in ("stack", "fill", "blur") else "auto"
        if m == "auto":
            return "stack" if self.webcam else "blur"
        if m == "stack" and not self.webcam:
            return "blur"
        return m

    def main_aspect(self, src_w: int, src_h: int) -> float | None:
        """Width/height the main area will be shown at (None = any shape)."""
        m = self.effective_mode
        if m == "fill":
            return self.width / self.height
        if m == "stack":
            return self.width / (self.height - self.cam_height(src_w, src_h))
        return None

    def cam_height(self, src_w: int, src_h: int) -> int:
        """Webcam strip height: its natural height at full width, clamped."""
        if not self.webcam or self.effective_mode != "stack":
            return 0
        _, _, cw, ch = self.webcam.pixels(src_w, src_h)
        natural = self.width * ch / cw
        lo, hi = self.cam_min_share * self.height, self.cam_max_share * self.height
        return int(min(max(natural, lo), hi)) // 2 * 2

    def caption_position(self, src_w: int, src_h: int) -> float:
        """Vertical centre (0..1) for captions."""
        if self.effective_mode == "fill":
            return 0.72
        if self.effective_mode == "stack":
            # just below the webcam/gameplay seam - where viewers' eyes are
            return min(0.85, self.cam_height(src_w, src_h) / self.height + 0.10)
        return 0.74  # under the centred gameplay strip

    # ------------------------------------------------------------ ffmpeg
    def filter_graph(self, src_w: int, src_h: int, ass_file: str | None) -> str:
        W, H = self.width, self.height
        g = (self.gameplay or Region(0, 0, 1, 1)).pixels(src_w, src_h)
        crop_game = f"crop={g[2]}:{g[3]}:{g[0]}:{g[1]}"

        mode = self.effective_mode
        if mode == "fill":
            parts = [f"[0:v]{crop_game},scale={W}:{H}:force_original_aspect_ratio=increase,"
                     f"crop={W}:{H},setsar=1[stack]"]
        elif mode == "stack":
            ch = self.cam_height(src_w, src_h)
            c = self.webcam.pixels(src_w, src_h)
            gh = H - ch
            parts = [
                "[0:v]split=2[c][g]",
                f"[c]crop={c[2]}:{c[3]}:{c[0]}:{c[1]},"
                f"scale={W}:{ch}:force_original_aspect_ratio=increase,"
                f"crop={W}:{ch}[cam]",
                f"[g]{crop_game},scale={W}:{gh}:force_original_aspect_ratio=increase,"
                f"crop={W}:{gh}[game]",
                "[cam][game]vstack=inputs=2,setsar=1[stack]",
            ]
        else:
            parts = [
                f"[0:v]{crop_game},split=2[b][f]",
                f"[b]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},boxblur=25:2,eq=brightness=-0.08[bg]",
                f"[f]scale={W}:-2[fg]",
                "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[stack]",
            ]
        last = "[stack]"
        if ass_file:
            parts.append(f"{last}ass='{ass_file}'[out]")
            last = "[out]"
        parts.append(f"{last}format=yuv420p[v]")
        return ";".join(parts)


def render_vertical(src: str, dst: str, layout: VerticalLayout,
                    src_w: int, src_h: int, ass_path: str | None = None,
                    crf: int = 20, preset: str = "veryfast") -> None:
    """Render dst (9:16). Runs inside dst's folder so the .ass path needs no
    Windows drive-letter escaping."""
    folder = os.path.dirname(os.path.abspath(dst))
    ass_rel = None
    if ass_path:
        ass_rel = os.path.relpath(os.path.abspath(ass_path), folder).replace("\\", "/")
    cmd = [
        _require("ffmpeg"), "-nostdin", "-v", "error", "-y",
        "-i", os.path.abspath(src),
        "-filter_complex", layout.filter_graph(src_w, src_h, ass_rel),
        "-map", "[v]", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
        os.path.basename(dst),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=folder)
    if out.returncode != 0:
        raise RuntimeError(f"Vertical render failed:\n{out.stderr.strip()}")


# ------------------------------------------------------------ saved layout

def load_layout() -> VerticalLayout:
    try:
        with open(LAYOUT_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return VerticalLayout(
            webcam=Region(**d["webcam"]) if d.get("webcam") else None,
            gameplay=Region(**d["gameplay"]) if d.get("gameplay") else None,
            mode=str(d.get("mode") or "auto"),
        )
    except (OSError, ValueError, TypeError, KeyError):
        return VerticalLayout()


def save_layout(layout: VerticalLayout) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(LAYOUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"webcam": asdict(layout.webcam) if layout.webcam else None,
                   "gameplay": asdict(layout.gameplay) if layout.gameplay else None,
                   "mode": layout.mode},
                  f, indent=2)


def grab_frame(src: str, dst_png: str, at: float, max_w: int = 960) -> None:
    cmd = [_require("ffmpeg"), "-nostdin", "-v", "error", "-y", "-ss", f"{at:.2f}",
           "-i", src, "-frames:v", "1", "-vf", f"scale='min({max_w},iw)':-2", dst_png]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0 or not os.path.exists(dst_png):
        raise RuntimeError(f"Could not read a frame from the video:\n{out.stderr.strip()}")


def render_preview(src: str, at: float, dst_png: str, src_w: int, src_h: int,
                   layout: VerticalLayout | None, ass_path: str | None,
                   offset: float = 0.25, max_h: int = 640) -> None:
    """One frame of the final look (layout + captions) for the style preview.
    Captions in the .ass should start at 0; we show the frame `offset` s in."""
    folder = os.path.dirname(os.path.abspath(dst_png))
    ass_rel = None
    if ass_path:
        ass_rel = os.path.relpath(os.path.abspath(ass_path), folder).replace("\\", "/")
    if layout:
        graph = layout.filter_graph(src_w, src_h, ass_rel) + f";[v]scale=-2:{max_h}[p]"
        vf = ["-filter_complex", graph, "-map", "[p]"]
    else:
        chain = (f"ass='{ass_rel}'," if ass_rel else "") + f"scale=-2:{max_h // 2 * 1}"
        vf = ["-vf", chain]
    cmd = [_require("ffmpeg"), "-nostdin", "-v", "error", "-y",
           "-ss", f"{max(0.0, at):.2f}", "-i", os.path.abspath(src),
           "-ss", f"{offset:.2f}", *vf, "-frames:v", "1",
           os.path.basename(dst_png)]
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=folder)
    if out.returncode != 0 or not os.path.exists(dst_png):
        raise RuntimeError(f"Preview failed:\n{out.stderr.strip()}")
