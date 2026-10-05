"""User config: ~/.on-duty/config.json (created with defaults on first run, edited by `onduty setup`)."""

import json
import pathlib

HOME = pathlib.Path.home() / ".on-duty"
CONFIG_PATH = HOME / "config.json"
CUSTOM_PHRASES = HOME / "phrases.json"  # optional, written by your AI assistant (on-duty-phrases skill) or by hand

VOICES = {"pt_BR": "Luciana", "en_US": "Samantha"}

DEFAULTS = {
    "name": "",               # used in phrases ("{name}, put the phone down")
    "lang": "pt_BR",          # pt_BR | en_US
    "voice": "",              # empty = default voice for the language (see VOICES)
    "port": 7878,             # dashboard at http://localhost:<port>
    "camera": 0,
    "phone_detection": True,  # YOLO11n "cell phone" detector (Apple Silicon recommended)
    "custom_phrases_only": False,  # true = use only ~/.on-duty/phrases.json, false = mix with built-ins
    "thresholds": {
        "pitch_delta": 12,    # degrees below your working posture that count as "looking down"
        "gaze_delta": 0.25,   # eyeLookDown above your normal (0..1)
        "window": 8,          # seconds of face history considered
        "down_ratio": 0.6,    # fraction of the window looking down
        "idle": 6,            # seconds without keyboard/mouse (face trigger)
        "phone_idle": 2,      # seconds without keyboard/mouse (phone trigger, ~instant)
        "phone_conf": 0.35,   # YOLO confidence
    },
}


def load() -> dict:
    HOME.mkdir(exist_ok=True)
    user = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    cfg = {**DEFAULTS, **user, "thresholds": {**DEFAULTS["thresholds"], **user.get("thresholds", {})}}
    if not CONFIG_PATH.exists():
        save(cfg)
    return cfg


def save(cfg: dict) -> None:
    HOME.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


def voice(cfg: dict) -> str:
    return cfg.get("voice") or VOICES.get(cfg["lang"], "Samantha")
