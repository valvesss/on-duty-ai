"""on-duty: your webcam notices when you leave work for your phone, and talks you back.

Signals (all local, no cloud, no LLM at runtime):
  • MediaPipe Face Landmarker → head pitch + eyeLookDown, relative to YOUR working posture
    (learned while you type, so camera angle doesn't matter)
  • YOLO11n (COCO class 67 "cell phone") → phone visible in frame = instant trigger
  • macOS HIDIdleTime → seconds since you last touched keyboard/mouse

Trigger: phone seen (~1 s) + phone_idle s without input, OR looking down for down_ratio of the
last `window` s + `idle` s without input. Then it talks, escalating through 5 levels, until you
touch the keyboard again.
"""

import argparse
import collections
import ctypes
import ctypes.util
import datetime as dt
import importlib
import json
import os
import platform
import random
import statistics
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

import calibration
import config
import db

HERE = Path(__file__).resolve().parent
PHONE_CLASS = 67  # COCO "cell phone"
FACE_MODEL = HERE / "models" / "face_landmarker.task"
YOLO_MODEL = HERE / "models" / "yolo11n.pt"

STATE: dict = {"status": {}, "jpeg": b"", "events": collections.deque(maxlen=30),
               "series": collections.deque(maxlen=240), "test": False, "blur": False, "said": None, "said_id": 0,
               "reload": False, "pause_until": 0.0, "preview": None, "cmds": collections.deque()}

T = {  # the few strings the engine says outside the phrase packs
    "pt_BR": {"level": "Nível {lv} de 5", "sec": "{n} segundos", "min1": "1 minuto", "min": "{n} minutos"},
    "en_US": {"level": "Level {lv} of 5", "sec": "{n} seconds", "min1": "1 minute", "min": "{n} minutes"},
}


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)
    if msg[:1] in "📵✅":
        STATE["events"].appendleft(f"{dt.datetime.now():%H:%M:%S} {msg}")


ASSETS = {"/radar.js": ("radar.js", "text/javascript"), "/logo.svg": ("logo.svg", "image/svg+xml"), "/favicon.svg": ("favicon.svg", "image/svg+xml"),
          "/favicon.ico": ("favicon.ico", "image/x-icon"), "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png")}
CFG: dict = {}  # live config; mutated in place by POST /api/config, picked up by the main loop
HHMM = __import__("re").compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def voices() -> list[dict]:
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    res = []
    for line in out.splitlines():
        head = line.split("#")[0].split()
        if len(head) >= 2 and head[-1][:2] in ("pt", "en"):
            res.append({"name": " ".join(head[:-1]), "locale": head[-1]})
    return res


def sample_line(lang: str, tone: str, name: str) -> str:
    pack = importlib.import_module(f"phrases.{lang if lang in config.VOICES else 'en_US'}")
    t = config.TONES.get(tone, config.TONES["balanced"])
    pool = [x for x in pack.LEVELS[t["start"] + (0 if t["cap"] < 3 else 1)] if isinstance(x, str) and ("{name}" in x) == bool(name)]
    pool = pool or [x for x in pack.LEVELS[t["start"]] if isinstance(x, str)]
    return random.choice(pool).format(name=name, time="3", n=3)


def validate_config(new: dict) -> dict:
    """Merge a partial config from the setup page over the current one; raises ValueError on junk."""
    cfg = config.merge({**CFG, **{k: v for k, v in new.items() if k in config.DEFAULTS}})
    cfg["name"] = str(cfg["name"]).strip()[:40]
    sch = cfg["schedule"]
    times = [sch["start"], sch["end"], *[t for b in sch["breaks"] for t in b]]
    if not all(isinstance(t, str) and HHMM.match(t) for t in times):
        raise ValueError("times must be HH:MM")
    cfg["retention_days"] = max(0, int(cfg["retention_days"]))
    sch["days"] = sorted({int(d) for d in sch["days"] if 1 <= int(d) <= 7})
    cfg["port"] = CFG["port"]  # needs a restart; not editable from the page
    cfg["camera"] = max(0, min(9, int(cfg["camera"])))
    cfg["mirror"] = bool(cfg["mirror"])
    cfg["rotate"] = round(max(-25.0, min(25.0, float(cfg["rotate"]))), 1)
    return cfg


def work_window(now: dt.datetime) -> tuple[bool, str]:
    """(inside working hours?, why not: day | hours | break)"""
    sch = CFG["schedule"]
    if not sch["enforce"]:
        return True, ""
    if now.isoweekday() not in sch["days"]:
        return False, "day"
    hm = now.strftime("%H:%M")
    if any(a <= hm < b for a, b in sch["breaks"]):
        return False, "break"
    return (sch["start"] <= hm < sch["end"]), "hours"


def next_on(now: dt.datetime) -> int:
    """Epoch of the next minute that is inside working hours (for 'back at 09:00')."""
    t = now.replace(second=0, microsecond=0)
    for _ in range(8 * 24 * 60):
        t += dt.timedelta(minutes=1)
        if work_window(t)[0]:
            return int(t.timestamp())
    return 0


_cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
_cg.CGMainDisplayID.restype = ctypes.c_uint32
_cg.CGDisplayIsAsleep.argtypes = [ctypes.c_uint32]


_cg.CGGetActiveDisplayList.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]


def display_count() -> int:
    n, buf = ctypes.c_uint32(0), (ctypes.c_uint32 * 16)()
    _cg.CGGetActiveDisplayList(16, buf, ctypes.byref(n))
    return max(1, n.value)


def system_asleep() -> bool:
    """Display asleep, screen locked, or another user's session is in front."""
    if _cg.CGDisplayIsAsleep(_cg.CGMainDisplayID()):
        return True
    root = subprocess.run(["ioreg", "-n", "Root", "-d1"], capture_output=True, text=True).stdout
    return '"IOConsoleLocked" = Yes' in root or '"kCGSSessionOnConsoleKey"=No' in root


class Camera:
    """Reads the webcam on its own thread so the preview is smooth (~30 fps) while detection runs at its own pace."""

    def __init__(self):
        self.cap, self.frame, self.seq, self._t = None, None, 0, None
        self.cond, self._stop = threading.Condition(), threading.Event()

    @property
    def is_open(self) -> bool:
        return self.cap is not None

    def open(self, idx: int) -> bool:
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            return False
        self.cap, self.frame = cap, None
        self._stop.clear()
        self._t = threading.Thread(target=self._run, args=(cap,), daemon=True)
        self._t.start()
        return True

    def _run(self, cap) -> None:
        while not self._stop.is_set():
            ok, f = cap.read()
            if ok:
                with self.cond:
                    self.frame, self.seq = f, self.seq + 1
                    self.cond.notify_all()
            else:
                time.sleep(0.05)

    def close(self) -> None:
        self._stop.set()
        if self._t:
            self._t.join(timeout=2)
        if self.cap:
            self.cap.release()
        with self.cond:
            self.cap, self.frame = None, None
            self.cond.notify_all()

    def wait(self, seq: int, timeout: float = 1.0):
        """Block until a frame newer than `seq` exists (or the camera closes). Returns (frame, seq)."""
        with self.cond:
            self.cond.wait_for(lambda: self.seq != seq or self.cap is None, timeout)
            return self.frame, self.seq


CAM = Camera()
STATE["boxes"] = []


def encode_preview(frame, boxes, blur: bool, mirror: bool = True, rotate: float = 0.0) -> bytes:
    """480 px wide JPEG for the dashboard: phone boxes drawn on, or heavily pixelated when blur is on."""
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (480, int(480 * h / w)))
    if blur:  # preview only; detection already ran on the sharp frame
        sh, sw = small.shape[:2]
        small = cv2.resize(cv2.GaussianBlur(cv2.resize(small, (24, 18), interpolation=cv2.INTER_AREA), (0, 0), 2), (sw, sh), interpolation=cv2.INTER_CUBIC)
    k = 480 / w
    for x1, y1, x2, y2 in boxes:  # boxes are in raw coordinates; draw them before flipping so the label text stays readable
        cv2.rectangle(small, (int(x1 * k), int(y1 * k)), (int(x2 * k), int(y2 * k)), (94, 63, 244), 3)
    if mirror:
        small = cv2.flip(small, 1)
        for x1, y1, x2, y2 in boxes:
            cv2.putText(small, "phone", (480 - int(x2 * k), max(18, int(y1 * k) - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (94, 63, 244), 2)
    else:
        for x1, y1, x2, y2 in boxes:
            cv2.putText(small, "phone", (int(x1 * k), max(18, int(y1 * k) - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (94, 63, 244), 2)
    if rotate:  # straighten a tilted camera; zoom just enough to hide the empty corners
        sh, sw = small.shape[:2]
        t = np.radians(abs(rotate))
        m = cv2.getRotationMatrix2D((sw / 2, sh / 2), rotate, np.cos(t) + np.sin(t) * sw / sh)
        small = cv2.warpAffine(small, m, (sw, sh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 72])[1].tobytes()


class Dashboard(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200, headers: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if "Cache-Control" not in (headers or {}):
            self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(json.dumps(obj).encode(), "application/json", code)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        args = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        if path == "/status":
            out = {**STATE["status"], "events": list(STATE["events"])}
            if args.get("series"):
                out["series"] = list(STATE["series"])
            self._json(out)
        elif path == "/history":
            self._send(db.history_ndjson(), "application/x-ndjson")
        elif path == "/frame.jpg":
            frame, _ = CAM.wait(-1, 0)
            self._send(encode_preview(frame, STATE["boxes"], STATE["blur"], CFG["mirror"], CFG["rotate"]) if frame is not None else BLANK, "image/jpeg")
        elif path == "/stream.mjpg":  # smooth live preview: multipart JPEG, ~20 fps
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seq, last = -1, 0.0
            try:
                while True:
                    frame, seq = CAM.wait(seq, 1.0)
                    time.sleep(max(0.0, 0.05 - (time.time() - last)))
                    frame, seq = CAM.wait(seq - 1, 0)  # freshest frame after the throttle sleep
                    jpg = encode_preview(frame, STATE["boxes"], STATE["blur"], CFG["mirror"], CFG["rotate"]) if frame is not None else BLANK
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpg) + jpg + b"\r\n")
                    last = time.time()
                    if frame is None:
                        time.sleep(0.6)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        elif path in ASSETS:
            name, ctype = ASSETS[path]
            self._send((HERE / "assets" / name).read_bytes(), ctype, headers={"Cache-Control": "public, max-age=3600"})
        elif path == "/api/config":
            self._json({"config": CFG, "voices": voices(), "tones": config.TONES})
        elif path == "/api/setups":
            cur = (STATE["status"].get("calibration") or {}).get("sig")
            out = []
            for k in db.keys("setup:"):
                prof, _ = db.get(k)
                out.append({"sig": k[6:], "label": prof.get("label", ""), "zones": [z["name"] for z in prof.get("zones", [])],
                            "created": prof.get("created", 0), "sensitivity": prof.get("sensitivity", "normal"), "active": k[6:] == cur})
            self._json(sorted(out, key=lambda x: -x["created"]))
        elif path == "/api/phrases":
            custom = json.loads(config.CUSTOM_PHRASES.read_text()) if config.CUSTOM_PHRASES.exists() else None
            self._json({"custom": bool(custom), "lines": sum(map(len, custom["levels"])) if custom else 0, "path": str(config.CUSTOM_PHRASES)})
        elif path == "/api/about":
            m = __import__("re").search(r'^version = "(.*?)"', (HERE / "pyproject.toml").read_text(), __import__("re").M)
            self._json({"version": m.group(1) if m else "?", "port": CFG["port"], "events": db.count_events(), "db": str(db.DB_PATH), "config": str(config.CONFIG_PATH)})
        elif path == "/api/export":
            self._send(db.export_ndjson(), "application/x-ndjson", headers={"Content-Disposition": 'attachment; filename="on-duty-history.ndjson"'})
        elif path == "/settings":
            self._send((HERE / "settings.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/sample":
            self._json({"text": sample_line(args.get("lang", "en_US"), args.get("tone", "balanced"), args.get("name", ""))})
        elif path == "/setup":
            self._send((HERE / "setup.html").read_bytes(), "text/html; charset=utf-8")
        elif not CFG["onboarded"]:
            self._send(b"", "text/plain", 302, {"Location": "/setup"})
        else:
            self._send((HERE / "dashboard.html").read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        if self.path == "/blur":
            STATE["blur"] = not STATE["blur"]
        elif self.path == "/test":
            STATE["test"] = True
        elif self.path == "/api/config":
            try:
                new = validate_config(body)
            except (ValueError, TypeError, KeyError) as e:
                return self._json({"error": str(e)}, 400)
            CFG.clear()
            CFG.update(new)
            config.save(CFG)
            STATE["reload"] = True
            return self._json({"config": CFG})
        elif self.path == "/api/pause":  # minutes: 0 resumes, "tomorrow" = until 06:00 tomorrow
            m = body.get("minutes", 0)
            if m == "tomorrow":
                tm = dt.datetime.now().replace(hour=6, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
                STATE["pause_until"] = tm.timestamp()
            else:
                STATE["pause_until"] = time.time() + float(m) * 60 if float(m) > 0 else 0
        elif self.path == "/api/feedback":  # {"kind": "false_positive" | "missed"}
            STATE["cmds"].append({"action": "feedback", "kind": body.get("kind", "false_positive")})
        elif self.path == "/api/data" and body.get("action") == "clear_history":
            return self._json({"removed": db.clear_events()})
        elif self.path == "/api/phrases" and body.get("action") == "remove":
            config.CUSTOM_PHRASES.unlink(missing_ok=True)
            STATE["reload"] = True
        elif self.path == "/api/level":  # measure the camera tilt from your eye line (sit upright for 3 s)
            STATE["cmds"].append({"action": "level"})
        elif self.path == "/api/calibrate":  # start | finish | cancel | reset | discard — handled by the engine loop
            STATE["cmds"].append(body)
        elif self.path == "/api/say":  # voice preview in the setup wizard
            if STATE["preview"] and STATE["preview"].poll() is None:
                STATE["preview"].kill()
            voice = body.get("voice") or config.voice(CFG)
            if voice in {v["name"] for v in voices()}:
                STATE["preview"] = subprocess.Popen(["say", "-v", voice, "-r", "190", str(body.get("text", ""))[:300]])
        self._send(b"ok", "text/plain")


def idle_seconds() -> float:
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "HIDIdleTime" in line:
            return int(line.rsplit("=", 1)[1]) / 1e9
    return 0.0


def load_phrases(cfg: dict) -> tuple[list, dict]:
    """Built-in pack for the language, merged with (or replaced by) ~/.on-duty/phrases.json."""
    pack = importlib.import_module(f"phrases.{cfg['lang']}")
    levels, back = [list(lv) for lv in pack.LEVELS], {k: list(v) for k, v in pack.BACK.items()}
    if config.CUSTOM_PHRASES.exists():
        custom = json.loads(config.CUSTOM_PHRASES.read_text())
        if cfg["custom_phrases_only"]:
            levels, back = [[] for _ in levels], {k: [] for k in back}
        for i, lv in enumerate(custom.get("levels", [])[:5]):
            levels[i] += lv
        for k, v in custom.get("back", {}).items():
            back.setdefault(k, []).extend(v)
    if not cfg["name"]:  # lines that need a name are skipped when there isn't one
        has_name = lambda it: "{name}" in (it if isinstance(it, str) else " ".join(it))  # noqa: E731
        levels = [[it for it in lv if not has_name(it)] for lv in levels]
        back = {k: [it for it in v if not has_name(it)] for k, v in back.items()}
    return levels, back


class Nagger:
    """Talks without overlapping itself; escalates by tone."""

    GAP = [10, 8, 6, 5, 4]  # seconds of silence between lines, per level (scaled by the tone)
    RATE = [185, 190, 200, 210, 225]  # `say` words per minute, per level

    def __init__(self, cfg: dict, voice_on: bool):
        self.cfg, self.voice_on, self.voice = cfg, voice_on and cfg["voice_on"], config.voice(cfg)
        self.tone = config.TONES[cfg["tone"]]
        self.t = T.get(cfg["lang"], T["en_US"])
        self.levels, self.back = load_phrases(cfg)
        self.proc, self.ended, self.bags = None, 0.0, {}

    def tempo(self, minutes: float) -> str:
        sec = round(minutes * 60)
        if sec < 60:
            return self.t["sec"].format(n=max(sec, 5))
        return self.t["min1"] if round(minutes) == 1 else self.t["min"].format(n=round(minutes))

    def _pick(self, key, pool):
        if not self.bags.get(key):  # shuffle; only repeat after using them all
            self.bags[key] = random.sample(pool, len(pool))
        return self.bags[key].pop()

    def speaking(self) -> bool:
        if self.proc and self.proc.poll() is None:
            return True
        if self.proc:
            self.ended, self.proc = time.time(), None
        return False

    def say(self, item, level: int, minutes: float = 0, n: int = 0, kind: str = "nag") -> str:
        parts = [item] if isinstance(item, str) else item
        fmt = {"time": self.tempo(minutes), "n": n, "name": self.cfg["name"]}
        lines = [x.format(**fmt) for x in parts]
        if self.voice_on:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
            self.proc = subprocess.Popen(["say", "-v", self.voice, "-r", str(self.RATE[level]),
                                          " [[slnc 600]] ".join(lines)])
        text = " ".join(lines)
        STATE["said_id"] += 1  # the dashboard types this out live
        STATE["said"] = {"id": STATE["said_id"], "text": text, "level": level + 1, "kind": kind,
                         "t": int(time.time()), "minutes": round(minutes, 1), "n": n}
        return text

    def level(self, n: int) -> int:
        return min(self.tone["cap"], self.tone["start"] + max(0, n - 1) // self.tone["per"])

    def shut_up(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def ready(self, n: int) -> bool:
        return not self.speaking() and time.time() - self.ended >= self.GAP[self.level(n)] * self.tone["gap"]

    def nag(self, n: int, minutes: float) -> str:
        lv = self.level(n)
        if n == 1 or lv != self.level(n - 1):  # notification only at the start and on level-up
            title = f"📵 on-duty{' · ' + self.cfg['name'] if self.cfg['name'] else ''}"
            if self.cfg["notifications"]:
                subprocess.Popen(["osascript", "-e", f'display notification "{self.t["level"].format(lv=lv + 1)}" '
                                                     f'with title "{title}" sound name "Basso"'])
        if lv >= 2 and self.cfg["sound_effects"]:
            subprocess.Popen(["afplay", "-v", str(lv), "/System/Library/Sounds/Sosumi.aiff"])
        return self.say(self._pick(lv, self.levels[lv]), lv, minutes, n)

    def welcome(self, minutes: float) -> str:
        tier = "quick" if minutes < 1 else "medium" if minutes < 5 else "long"
        return self.say(self._pick(tier, self.back[tier]), 0, minutes, kind="back")


Pose = collections.namedtuple("Pose", "pitch yaw gaze face_h cx roll")


def head_pose(lm: vision.FaceLandmarker, frame) -> Pose | None:
    """Head pitch (degrees, positive = head down), yaw, eyeLookDown (0..1) and the face box height/centre, or None."""
    r = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
    if not r.face_landmarks:
        return None
    R = np.array(r.facial_transformation_matrixes[0])[:3, :3]
    pitch = float(np.degrees(np.arctan2(R[2, 1], R[2, 2])))
    yaw = float(np.degrees(np.arctan2(-R[2, 0], np.hypot(R[2, 1], R[2, 2]))))
    bs = {c.category_name: c.score for c in r.face_blendshapes[0]}
    xs, ys = [p.x for p in r.face_landmarks[0]], [p.y for p in r.face_landmarks[0]]
    a, b = sorted((r.face_landmarks[0][33], r.face_landmarks[0][263]), key=lambda p: p.x)  # outer eye corners, left→right in the image
    h, w = frame.shape[:2]
    roll = float(np.degrees(np.arctan2((b.y - a.y) * h, (b.x - a.x) * w)))  # image tilt of the eye line, clockwise positive
    return Pose(pitch, yaw, (bs["eyeLookDownLeft"] + bs["eyeLookDownRight"]) / 2, max(ys) - min(ys), (max(xs) + min(xs)) / 2, roll)


def load_yolo(cfg: dict):
    if not cfg["phone_detection"]:
        return None
    if platform.machine() != "arm64":
        log("phone detection off: needs Apple Silicon (PyTorch has no Intel macOS builds)")
        return None
    try:
        from ultralytics import YOLO
    except ImportError:
        log("phone detection off: ultralytics not installed")
        return None
    return YOLO(str(YOLO_MODEL))  # ~5 MB, downloaded on first run


AWAY_IDLE = 180    # s without input AND ...
AWAY_NOFACE = 120  # ... s without seeing a face → release the camera and sleep until you touch the machine
SLEEP_POLL = {"asleep": 3, "paused": 5, "offduty": 15, "away": 1}
BLANK = cv2.imencode(".jpg", np.zeros((360, 480, 3), np.uint8))[1].tobytes()


def main() -> None:
    p = argparse.ArgumentParser(description="on-duty engine (normally started by the OnDuty.app service)")
    p.add_argument("--no-voice", action="store_true")
    p.add_argument("--fps", type=float, default=3.0)
    p.add_argument("--debug", action="store_true", help="log signals every 5 s")
    a = p.parse_args()
    CFG.update(config.load())
    th = CFG["thresholds"]  # (rebuilt below once the personal overrides are known)
    if (gone := db.prune(CFG["retention_days"])):
        log(f"retention: removed {gone} events older than {CFG['retention_days']} days")

    lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(FACE_MODEL)),
        output_face_blendshapes=True, output_facial_transformation_matrixes=True, num_faces=1))
    yolo = load_yolo(CFG)
    smoother = calibration.Smoother(3)
    level_ses: dict | None = None  # auto-level: median eye-line tilt over 3 s

    hist: collections.deque[bool] = collections.deque(maxlen=max(1, int(th["window"] * a.fps)))
    phone_hist: collections.deque[bool] = collections.deque(maxlen=hist.maxlen)
    recent_phone: collections.deque[bool] = collections.deque(maxlen=3)
    work_pitch: collections.deque[float] = collections.deque(maxlen=int(600 * a.fps))  # last ~10 min typing
    work_gaze: collections.deque[float] = collections.deque(maxlen=int(600 * a.fps))
    calib, calib_t = db.get("calibration", {})
    if calib and time.time() - calib_t < 12 * 3600:  # recent posture: no need to recalibrate
        work_pitch.extend(calib["pitch"])
        work_gaze.extend(calib["gaze"])
        log(f"calibration restored ({len(work_pitch)} samples)")

    zones: list[dict] = []        # where you look while working, for the current setup (camera + displays)
    overrides: dict = {}          # personal pitch/gaze deltas measured by the calibration
    resid: collections.deque[float] = collections.deque(maxlen=int(300 * a.fps))  # typing pitch − zone pitch, ~5 min
    setup = {"sig": None, "label": "", "state": "never", "created": 0, "displays": 1}
    drifting, last_sig_check, last_drift_check, bright = False, 0.0, 0.0, 128.0
    seen_hist: collections.deque[bool] = collections.deque(maxlen=int(120 * a.fps))  # face seen while typing, ~2 min
    cal = {"zones": [], "phone": None, "last": None}  # an in-progress calibration session
    cap_ses: dict | None = None
    cal_until = 0.0  # while > now the calibration page is open: the camera stays on and nothing nags
    cam_idx, good_cam = CFG["camera"], None
    eff_th = lambda: calibration.effective_thresholds(CFG["thresholds"], overrides, tuning, noise, setup["state"] in ("ok", "drift"))  # noqa: E731
    tuning, noise, last_noise, last_vals, last_seq, grace_until = {"pitch": 0.0, "gaze": 0.0}, 0.0, 0.0, "", 0, 0.0
    th = eff_th()

    nag = Nagger(CFG, not a.no_voice)
    streak_start, n_nags, last_seen_t, last_phone_t = None, 0, time.time(), 0.0
    last_down, last_face_t, last_dbg, last_save = False, 0.0, 0.0, time.time()
    mode, away, camera_ok = "active", False, False
    srv = ThreadingHTTPServer(("127.0.0.1", CFG["port"]), Dashboard)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"on-duty running · http://localhost:{CFG['port']}{'' if CFG['onboarded'] else '/setup'} · voice {nag.voice} · "
        f"phone detection {'on' if yolo else 'off'}")

    def publish_sleep(m: str, why: str = "") -> None:
        now = time.time()
        STATE["status"] = {**STATE["status"], "t": int(now), "mode": m, "mode_why": why, "name": CFG["name"], "lang": CFG["lang"],
                           "onboarded": CFG["onboarded"], "scrolling": False, "level": 0, "nags": 0, "phone_min": 0,
                           "resume_at": STATE["pause_until"] and int(STATE["pause_until"]) or (next_on(dt.datetime.now()) if m == "offduty" else 0),
                           "blur": STATE["blur"], "said": STATE["said"], "mirror": CFG["mirror"]}

    try:
        while True:
            t0 = time.time()
            if STATE["reload"]:
                STATE["reload"] = False
                th = eff_th()
                nag.shut_up()
                nag = Nagger(CFG, not a.no_voice)
                yolo = (yolo or load_yolo(CFG)) if CFG["phone_detection"] else None
                streak_start, n_nags = None, 0
                if CFG["camera"] != cam_idx:  # switched camera from the wizard
                    cam_idx = CFG["camera"]
                    CAM.close()
                log(f"config reloaded · tone {CFG['tone']} · voice {nag.voice}")

            idle = idle_seconds()
            while STATE["cmds"]:  # calibration commands from the setup page
                c = STATE["cmds"].popleft()
                act = c.get("action")
                if act == "start":
                    cal_until = t0 + 600
                    if mode == "active" and CAM.is_open and cap_ses is None:
                        cap_ses = calibration.CaptureSession(c.get("kind", "zone"), str(c.get("name", ""))[:30], float(c.get("seconds", 8)), t0)
                        streak_start, n_nags = None, 0
                        nag.shut_up()
                    else:
                        cal["last"] = {"kind": c.get("kind"), "ok": False, "error": "camera"}
                elif act == "cancel":
                    cap_ses, cal, cal_until = None, {"zones": [], "phone": None, "last": None}, 0.0
                elif act == "discard" and 0 <= int(c.get("index", -1)) < len(cal["zones"]):
                    cal["zones"].pop(int(c["index"]))
                elif act == "feedback":
                    kind = c.get("kind", "false_positive")
                    tuning = calibration.adjust_tuning(tuning, kind)
                    if setup["sig"]:
                        db.put(f"tuning:{setup['sig']}", tuning)
                    db.record("feedback", cause=kind, said=last_vals)
                    if kind == "false_positive":  # stop now, and don't restart for a minute
                        nag.shut_up()
                        streak_start, n_nags, grace_until = None, 0, t0 + 60
                    th = eff_th()
                    log(f"feedback {kind}: tuning now {tuning} → pitch_delta {th['pitch_delta']}, gaze_delta {th['gaze_delta']}")
                elif act == "level" and mode == "active" and CAM.is_open:
                    level_ses = {"t0": t0, "vals": []}
                elif act == "unphone":
                    cal["phone"] = None
                elif act == "delete_setup" and c.get("sig"):
                    db.delete(f"setup:{c['sig']}")
                    db.delete(f"tuning:{c['sig']}")
                    if c["sig"] == setup["sig"]:
                        zones, overrides, tuning = [], {}, {"pitch": 0.0, "gaze": 0.0}
                        setup.update(state="new_setup" if db.keys("setup:") else "never", label="")
                        resid.clear()
                        drifting = False
                    log(f"setup {c['sig']} removed")
                elif act == "reset_tuning" and setup["sig"]:
                    tuning = {"pitch": 0.0, "gaze": 0.0}
                    db.delete(f"tuning:{setup['sig']}")
                    log("fine-tuning reset")
                elif act == "reset" and setup["sig"]:
                    db.delete(f"setup:{setup['sig']}")
                    zones, overrides, th = [], {}, eff_th()
                    setup.update(state="new_setup" if db.keys("setup:") else "never", label="")
                    resid.clear()
                    drifting = False
                    log("calibration cleared for this setup")
                elif act == "finish" and cal["zones"] and setup["sig"]:
                    derived = calibration.derive_thresholds(cal["zones"], cal["phone"], c.get("sensitivity", "normal"))
                    label = calibration.setup_label(setup["displays"], CFG["camera"])
                    db.put(f"setup:{setup['sig']}", {"label": label, "zones": cal["zones"], "thresholds": derived, "phone": cal["phone"],
                                                     "sensitivity": c.get("sensitivity", "normal"), "created": int(time.time())})
                    zones, overrides = list(cal["zones"]), derived
                    tuning = {"pitch": 0.0, "gaze": 0.0}
                    db.delete(f"tuning:{setup['sig']}")
                    th = eff_th()
                    setup.update(state="ok", label=label, created=int(time.time()))
                    resid.clear()
                    drifting = False
                    log(f"calibrated {label}: {len(zones)} zone(s), thresholds {derived or 'default'}")
                    cap_ses, cal, cal_until = None, {"zones": [], "phone": None, "last": None}, 0.0
            th = eff_th()
            calibrating = cal_until > t0
            if system_asleep():
                new_mode, why = "asleep", "screen"
            elif calibrating:
                new_mode, why = "active", ""
            elif STATE["pause_until"] > t0:
                new_mode, why = "paused", ""
            elif CFG["onboarded"] and not work_window(dt.datetime.now())[0]:
                new_mode, why = "offduty", work_window(dt.datetime.now())[1]
            else:
                if idle < 2:
                    away = False
                elif not streak_start and idle >= AWAY_IDLE and t0 - last_seen_t >= AWAY_NOFACE:
                    away = True
                new_mode, why = ("away", "idle") if away else ("active", "")
            if STATE["pause_until"] and STATE["pause_until"] <= t0:
                STATE["pause_until"] = 0.0
            if new_mode != mode:
                log(f"mode {mode} → {new_mode}{' (' + why + ')' if why else ''}")
                mode = new_mode
                if mode != "active":  # camera light off, speech off, streak closed without a welcome
                    nag.shut_up()
                    streak_start, n_nags = None, 0
                    CAM.close()
                    camera_ok = False
                else:
                    last_seen_t = t0
                    hist.clear()
                    phone_hist.clear()
            if mode != "active":
                publish_sleep(mode, why)
                pu = STATE["pause_until"]
                for _ in range(SLEEP_POLL[mode]):  # wake early on config / pause changes
                    if STATE["reload"] or STATE["pause_until"] != pu:
                        break
                    time.sleep(1)
                continue

            if not CAM.is_open:
                if not CAM.open(CFG["camera"]):
                    if good_cam is not None and CFG["camera"] != good_cam:  # tried another camera and it isn't there
                        log(f"no camera at index {CFG['camera']}, back to {good_cam}")
                        CFG["camera"] = cam_idx = good_cam
                        config.save(CFG)
                        STATE["camera_note"] = int(t0)
                        continue
                    if camera_ok is not None:
                        log("Camera didn't open: allow OnDuty in System Settings › Privacy & Security › Camera.")
                    camera_ok = None
                    STATE["status"] = {**STATE["status"], "t": int(t0), "mode": "active", "camera_ok": False, "lang": CFG["lang"],
                                       "onboarded": CFG["onboarded"], "name": CFG["name"], "said": STATE["said"], "blur": STATE["blur"]}
                    time.sleep(3)
                    continue
            frame, seq = CAM.wait(last_seq, 1.0)
            if frame is None or seq == last_seq:
                continue
            last_seq = seq
            frame = frame.copy()
            camera_ok = True
            good_cam = CFG["camera"]
            bright += 0.2 * (float(cv2.cvtColor(frame[::8, ::8], cv2.COLOR_BGR2GRAY).mean()) - bright)

            if t0 - last_sig_check >= 10:  # which physical setup is this? (camera + displays + resolution)
                last_sig_check = t0
                sig = calibration.setup_signature(CFG["camera"], display_count(), frame.shape[1], frame.shape[0])
                if sig != setup["sig"]:
                    first = setup["sig"] is None
                    prof, _ = db.get(f"setup:{sig}")
                    setup.update(sig=sig, displays=display_count(), label=prof["label"] if prof else "", created=prof["created"] if prof else 0,
                                 state="ok" if prof else ("new_setup" if db.keys("setup:") else "never"))
                    zones, overrides = (prof["zones"], calibration.derive_thresholds(prof["zones"], prof.get("phone"), prof.get("sensitivity", "normal"))) if prof else ([], {})  # re-derived: profiles saved by older builds pick up the current floors
                    tuning = db.get(f"tuning:{sig}", {"pitch": 0.0, "gaze": 0.0})[0]
                    th = eff_th()
                    resid.clear()
                    drifting = False
                    if first and calib and calib.get("sig", sig) != sig:
                        work_pitch.clear()
                        work_gaze.clear()
                    elif not first:  # moved to another desk/monitor: the old rolling posture no longer applies
                        work_pitch.clear()
                        work_gaze.clear()
                    log(f"setup {sig}: " + (f"calibrated ({len(zones)} zone(s))" if prof else f"not calibrated ({setup['state']})"))

            pose = head_pose(lm, frame)
            phone_boxes = []
            if yolo:
                r = yolo.predict(frame, classes=[PHONE_CLASS], conf=th["phone_conf"], imgsz=480, verbose=False)[0]
                phone_boxes = r.boxes.xyxy.int().tolist()
            STATE["boxes"] = phone_boxes
            if phone_boxes:
                last_phone_t = t0
            phone = t0 - last_phone_t < 3  # phone seen in the last 3 s (it drifts in and out of frame)
            phone_hist.append(bool(phone_boxes))
            recent_phone.append(bool(phone_boxes))

            sm = smoother.push((pose.pitch, pose.yaw, pose.gaze) if pose else None)
            ps = pose._replace(pitch=sm[0], yaw=sm[1], gaze=sm[2]) if pose else None  # smoothed: decisions use this, calibration the raw one
            zone = calibration.nearest_zone(zones, ps.yaw) if ps and zones else None
            if zone:  # calibrated: compare against the zone you're facing, plus slow slouch drift
                drift = calibration.clamp_drift(statistics.median(resid)) if len(resid) >= 20 else 0.0
                base, gbase = zone["pitch"] + drift, zone["gaze"]
            else:  # not calibrated: learn your posture while you type
                base = statistics.median(work_pitch) if len(work_pitch) >= 10 else None
                gbase = statistics.median(work_gaze) if work_gaze else 0.5
            dpitch = gaze = None
            if idle < 3:
                seen_hist.append(bool(pose))
            if pose:
                pitch, gaze = ps.pitch, ps.gaze
                last_face_t = t0
                if idle < 3:  # typing/using the mouse: this is the working posture
                    work_pitch.append(pitch)
                    work_gaze.append(gaze)
                    if zone:
                        resid.append(pitch - zone["pitch"])
                dpitch = pitch - base if base is not None else 0.0
                turned = bool(zone) and calibration.turned_away(ps.yaw, zone["yaw"])
                face_down = base is not None and calibration.is_face_down(dpitch, gaze - gbase, th["pitch_delta"], th["gaze_delta"], turned)
                last_down = face_down
                last_vals = f"dpitch={dpitch:.1f} gaze={gaze - gbase:+.2f} yaw={ps.yaw:.0f} pd={th['pitch_delta']} gd={th['gaze_delta']} phone={bool(phone_boxes)}"
            else:
                # a very lowered head often drops out of the detector: keep the last state for up to 10 s
                face_down = last_down and t0 - last_face_t < 10
            down = face_down or phone
            hist.append(down)
            ratio = sum(hist) / len(hist)

            phone_now = sum(recent_phone) >= 2 and idle >= th["phone_idle"]  # phone in hand: instant
            face_now = ratio >= th["down_ratio"] and idle >= th["idle"]

            now = time.time()
            if pose or phone_boxes:
                last_seen_t = now
            if streak_start and idle < 2:  # back on the keyboard: the only thing that ends it
                mins = (now - streak_start) / 60
                said = nag.welcome(mins) if n_nags else ""
                log(f"✅ back ({mins:.1f} min on the phone, {n_nags} lines) {said}")
                db.record("back", start=int(streak_start), minutes=round(mins, 2), n=n_nags, said=said)
                streak_start, n_nags = None, 0
            elif CFG["onboarded"] and not calibrating and now > grace_until and (phone_now or face_now) and not streak_start:  # the wizard never nags
                streak_start = now - (2 if phone_now else th["window"] * th["down_ratio"])
            if streak_start and now - last_seen_t < 20 and nag.ready(n_nags + 1):
                # keeps talking until you're back (pauses if you walked away from the camera)
                n_nags += 1
                cause = "+".join(c for c, on in (("face", face_down), ("phone", any(phone_hist))) if on) or "face"
                said = nag.nag(n_nags, (now - streak_start) / 60)
                log(f"📵 line #{n_nags} level {nag.level(n_nags) + 1} via {cause}: {said}")
                db.record("alert", n=n_nags, cause=cause, level=nag.level(n_nags) + 1, said=said)

            if t0 - last_noise >= 30:
                last_noise = t0
                centred = list(resid) if zones else [p - statistics.median(work_pitch) for p in work_pitch] if len(work_pitch) >= 60 else []
                noise = calibration.noise_floor(centred)
            if zones and t0 - last_drift_check >= 30 and len(resid) >= int(120 * a.fps):
                last_drift_check = t0
                was = drifting
                drifting = calibration.drift_state(drifting, statistics.median(resid))
                if drifting != was:
                    log(f"posture drift {'detected' if drifting else 'cleared'} (median {statistics.median(resid):+.1f}°)")
            if STATE["test"]:
                STATE["test"] = False
                lv = random.randrange(nag.tone["start"], nag.tone["cap"] + 1)
                log(f"📵 test (level {lv + 1}): {nag.say(random.choice(nag.levels[lv]), lv, 3, 7, kind='test')}")
            if now - last_save >= 60 and work_pitch:  # persist posture so restarts don't recalibrate
                last_save = now
                db.put("calibration", {"pitch": list(work_pitch)[-300:], "gaze": list(work_gaze)[-300:], "sig": setup["sig"]})
            if a.debug and now - last_dbg >= 5:
                last_dbg = now
                log(f"face={'y' if pose else 'n'} dpitch={dpitch if dpitch is None else round(dpitch, 1)} "
                    f"gaze={gaze if gaze is None else round(gaze, 2)} base={base if base is None else round(base, 1)} "
                    f"phone={'y' if phone_boxes else 'n'} down={ratio:.0%} idle={idle:.0f}s")

            if level_ses:
                if pose:
                    level_ses["vals"].append(-pose.roll if CFG["mirror"] else pose.roll)  # tilt as the viewer sees it
                if now - level_ses["t0"] >= 3:
                    vals = level_ses["vals"]
                    if len(vals) >= 4:
                        CFG["rotate"] = round(max(-25.0, min(25.0, statistics.median(vals))), 1)
                        config.save(CFG)
                        log(f"auto-level: rotate {CFG['rotate']}° from {len(vals)} samples")
                    else:
                        log("auto-level: no face seen, nothing changed")
                    STATE["level_note"] = {"t": int(now), "ok": len(vals) >= 4}
                    level_ses = None
            cal_live = None
            if cap_ses:
                cap_ses.add((pose.pitch, pose.yaw, pose.gaze) if pose else None, bright, pose.face_h if pose else 0.0, pose.cx if pose else 0.5, phone=bool(phone_boxes))
                cal_live = cap_ses.live(now)
                if cap_ses.done(now):
                    res = cap_ses.result()
                    if res["ok"] and res["kind"] == "zone":
                        cal["zones"].append({"name": res["name"] or f"Zone {len(cal['zones']) + 1}", **res["summary"]})
                    elif res["ok"]:
                        cal["phone"] = res["summary"]
                    cal["last"] = res
                    log(f"calibration {res['kind']} '{res['name']}': {res['summary'] or res['error']}")
                    cap_ses, cal_live = None, None
            health = [h for h, bad in (("dark", bright < 45), ("blocked", len(seen_hist) >= int(60 * a.fps) and sum(seen_hist) / len(seen_hist) < 0.4)) if bad]
            state = "drift" if drifting else setup["state"]
            STATE["status"] = {
                "calibration": {"sig": setup["sig"], "state": state, "label": setup["label"], "zones": [z["name"] for z in zones], "zone_data": zones, "tuning": tuning, "noise": round(noise, 1), "displays": setup["displays"],
                                "created": setup["created"], "thresholds": overrides, "camera": CFG["camera"]},
                "cal": {"open": calibrating, "live": cal_live, "zones": cal["zones"], "phone": cal["phone"], "last": cal["last"]},
                "pose": ({"pitch": round(ps.pitch, 1), "yaw": round(ps.yaw, 1), "gaze": round(ps.gaze, 2), "base": round(base, 1) if base is not None else None} if ps else None),
                "health": health, "camera_note": STATE.get("camera_note", 0), "level_note": STATE.get("level_note"),
                "t": int(now), "mode": "active", "mode_why": "", "resume_at": 0, "camera_ok": True, "onboarded": CFG["onboarded"],
                "name": CFG["name"], "lang": CFG["lang"], "face": bool(pose),
                "dpitch": dpitch, "gaze": gaze, "gaze_base": gbase, "down": down, "face_down": face_down,
                "phone": bool(phone_boxes), "phone_on": yolo is not None,
                "phone_ratio": round(sum(phone_hist) / len(phone_hist), 2), "down_ratio": round(ratio, 2),
                "idle": round(idle), "scrolling": bool(streak_start), "level": nag.level(n_nags) + 1 if n_nags else 0,
                "nags": n_nags, "calibrated": base is not None, "work_samples": len(work_pitch),
                "phone_min": round((now - streak_start) / 60, 1) if streak_start else 0, "cfg": th,
                "blur": STATE["blur"], "said": STATE["said"], "mirror": CFG["mirror"], "rotate": CFG["rotate"],
                "level": level_ses and {"progress": min(1.0, (now - level_ses["t0"]) / 3)},
            }
            STATE["series"].append([int(now), dpitch, gaze - gbase if gaze is not None else None, down,
                                    idle >= th["idle"], bool(phone_boxes)])
            time.sleep(max(0, 1 / (6.0 if cap_ses else a.fps) - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        CAM.close()


if __name__ == "__main__":
    main()
