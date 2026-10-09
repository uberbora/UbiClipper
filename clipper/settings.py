"""Remembered app settings (~/.ubiclipper/settings.json)."""

from __future__ import annotations

import json
import os

from .reframe import CONFIG_DIR

SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")

DEFAULTS: dict = {
    "export_root": "",            # default export folder ("" = ask once)
    "max_clips": "auto",
    "max_len": 60,
    "min_len": 10,
    "pre_roll": 12,
    "sensitivity": 0.5,
    "voice_focus": 0.4,
    "rank_words": True,
    "use_chat": True,
    "post_channel": "",
    "post_platform": "Kick",
    "post_game": "",
    "subtitles_on": True,
    "language": "",             # spoken language; "" = follow the OS language
    "also_language": "English",   # second language on stream ("" = none)
    "model": "turbo (recommended)",
    "words": "",
    "style": {},                  # SubtitleStyle fields
    "style_preset": "Bold pop",
    "vertical_on": True,
    "theme": "dark",
    "ui_language": "",          # "" = follow Windows' language
    "ai_listen": True,
    "ai_judge": True,
    "speaker_colors": True,
    "people": "Auto (up to 10)",
    "last_export": "",
    "fullscreen_on": True,        # also a 1920x1080 subtitled copy (montages)
    "safe_template": "TikTok",    # app buttons shown when placing subtitles
    "ready_asked": False,         # the "Get ready" downloads were offered once
    "settings_version": 0,
}
SETTINGS_VERSION = 2          # 2 = v1.4: AI judge on for everyone


def load_settings() -> dict:
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            stored = json.load(f)
        if isinstance(stored, dict):
            data.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    if int(data.get("settings_version") or 0) < 2:
        data["ai_judge"] = True       # 1.4: the AI judge is part of the normal setup
    data["settings_version"] = SETTINGS_VERSION
    return data


def save_settings(data: dict) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, SETTINGS_FILE)
    except OSError:
        pass  # settings are a convenience; never break the app over them
