"""User config: ~/.on-duty/config.json (created with defaults on first run, edited by the /setup page)."""

import json
import pathlib

HOME = pathlib.Path.home() / ".on-duty"
CONFIG_PATH = HOME / "config.json"
CUSTOM_PHRASES = HOME / "phrases.json"  # optional, written by your AI assistant (on-duty-phrases skill) or by hand

VOICES = {"pt_BR": "Luciana", "en_US": "Samantha"}

# How hard it nags. start/cap are level indexes 0..4 (gentle → chaos), per = lines before escalating.
TONES = {
    "friendly": {"start": 0, "cap": 2, "per": 4, "gap": 1.3},
    "balanced": {"start": 0, "cap": 4, "per": 3, "gap": 1.0},
    "ruthless": {"start": 1, "cap": 4, "per": 2, "gap": 0.8},
    "chaos":    {"start": 3, "cap": 4, "per": 2, "gap": 0.7},
}

DEFAULTS = {
    "onboarded": False,       # false → the dashboard redirects to /setup and nothing nags yet
    "name": "",               # used in phrases ("{name}, put the phone down")
    "lang": "pt_BR",          # pt_BR | en_US
    "voice": "",              # empty = default voice for the language (see VOICES)
    "voice_on": True,         # false = notifications + dashboard only
    "tone": "balanced",       # friendly | balanced | ruthless | chaos
    "port": 4269,             # dashboard at http://localhost:<port>
    "retention_days": 365,    # events older than this are deleted at startup (0 = keep forever)
    "camera": 0,
    "phone_detection": True,  # YOLO11n "cell phone" detector (Apple Silicon recommended)
    "custom_phrases_only": False,  # true = use only ~/.on-duty/phrases.json, false = mix with built-ins
    "schedule": {
        "enforce": True,                  # false = always on
        "days": [1, 2, 3, 4, 5],          # 1 = Monday … 7 = Sunday
        "start": "09:00",
        "end": "18:00",
        "breaks": [["12:00", "13:30"]],   # no nagging (and no camera) during these windows
    },
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


def merge(user: dict) -> dict:
    cfg = {**DEFAULTS, **user}
    cfg["thresholds"] = {**DEFAULTS["thresholds"], **user.get("thresholds", {})}
    cfg["schedule"] = {**DEFAULTS["schedule"], **user.get("schedule", {})}
    if cfg["port"] == 7878:  # the default of early builds
        cfg["port"] = DEFAULTS["port"]
    if cfg["tone"] not in TONES:
        cfg["tone"] = "balanced"
    if cfg["lang"] not in VOICES:
        cfg["lang"] = "en_US"
    return cfg


def load() -> dict:
    HOME.mkdir(exist_ok=True)
    existing = CONFIG_PATH.exists()
    cfg = merge(json.loads(CONFIG_PATH.read_text()) if existing else {})
    if existing and "onboarded" not in json.loads(CONFIG_PATH.read_text()):
        cfg["onboarded"] = True  # installs from before the wizard existed keep working as-is
    if not existing or cfg != json.loads(CONFIG_PATH.read_text()):
        save(cfg)
    return cfg


def save(cfg: dict) -> None:
    HOME.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


def voice(cfg: dict) -> str:
    return cfg.get("voice") or VOICES.get(cfg["lang"], "Samantha")
