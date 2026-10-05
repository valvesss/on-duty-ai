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

import config
import db

HERE = Path(__file__).resolve().parent
PHONE_CLASS = 67  # COCO "cell phone"
FACE_MODEL = HERE / "models" / "face_landmarker.task"
YOLO_MODEL = HERE / "models" / "yolo11n.pt"

STATE: dict = {"status": {}, "jpeg": b"", "events": collections.deque(maxlen=30),
               "series": collections.deque(maxlen=240), "test": False, "blur": False, "said": None, "said_id": 0,
               "reload": False, "pause_until": 0.0, "preview": None}

T = {  # the few strings the engine says outside the phrase packs
    "pt_BR": {"level": "Nível {lv} de 5", "sec": "{n} segundos", "min1": "1 minuto", "min": "{n} minutos"},
    "en_US": {"level": "Level {lv} of 5", "sec": "{n} seconds", "min1": "1 minute", "min": "{n} minutes"},
}


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)
    if msg[:1] in "📵✅":
        STATE["events"].appendleft(f"{dt.datetime.now():%H:%M:%S} {msg}")


ASSETS = {"/logo.svg": ("logo.svg", "image/svg+xml"), "/favicon.svg": ("favicon.svg", "image/svg+xml"),
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
    sch["days"] = sorted({int(d) for d in sch["days"] if 1 <= int(d) <= 7})
    cfg["port"], cfg["camera"] = CFG["port"], CFG["camera"]  # needs a restart; not editable from the page
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


def system_asleep() -> bool:
    """Display asleep, screen locked, or another user's session is in front."""
    if _cg.CGDisplayIsAsleep(_cg.CGMainDisplayID()):
        return True
    root = subprocess.run(["ioreg", "-n", "Root", "-d1"], capture_output=True, text=True).stdout
    return '"IOConsoleLocked" = Yes' in root or '"kCGSSessionOnConsoleKey"=No' in root


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
            self._json({**STATE["status"], "events": list(STATE["events"]), "series": list(STATE["series"])})
        elif path == "/history":
            self._send(db.history_ndjson(), "application/x-ndjson")
        elif path == "/frame.jpg":
            self._send(STATE["jpeg"], "image/jpeg")
        elif path in ASSETS:
            name, ctype = ASSETS[path]
            self._send((HERE / "assets" / name).read_bytes(), ctype, headers={"Cache-Control": "public, max-age=3600"})
        elif path == "/api/config":
            self._json({"config": CFG, "voices": voices(), "tones": config.TONES})
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
            subprocess.Popen(["osascript", "-e", f'display notification "{self.t["level"].format(lv=lv + 1)}" '
                                                 f'with title "{title}" sound name "Basso"'])
        if lv >= 2:
            subprocess.Popen(["afplay", "-v", str(lv), "/System/Library/Sounds/Sosumi.aiff"])
        return self.say(self._pick(lv, self.levels[lv]), lv, minutes, n)

    def welcome(self, minutes: float) -> str:
        tier = "quick" if minutes < 1 else "medium" if minutes < 5 else "long"
        return self.say(self._pick(tier, self.back[tier]), 0, minutes, kind="back")


def head_pose(lm: vision.FaceLandmarker, frame) -> tuple[float, float] | None:
    """(pitch in degrees, positive = head down; eyeLookDown 0..1) or None without a face."""
    r = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
    if not r.face_landmarks:
        return None
    R = np.array(r.facial_transformation_matrixes[0])[:3, :3]
    pitch = float(np.degrees(np.arctan2(R[2, 1], R[2, 2])))
    bs = {c.category_name: c.score for c in r.face_blendshapes[0]}
    return pitch, (bs["eyeLookDownLeft"] + bs["eyeLookDownRight"]) / 2


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
    p.add_argument("--fps", type=float, default=2.0)
    p.add_argument("--debug", action="store_true", help="log signals every 5 s")
    a = p.parse_args()
    CFG.update(config.load())
    th = CFG["thresholds"]

    lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(FACE_MODEL)),
        output_face_blendshapes=True, output_facial_transformation_matrixes=True, num_faces=1))
    yolo = load_yolo(CFG)
    cap = None

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
                           "blur": STATE["blur"], "said": STATE["said"]}

    try:
        while True:
            t0 = time.time()
            if STATE["reload"]:
                STATE["reload"] = False
                th = CFG["thresholds"]
                nag.shut_up()
                nag = Nagger(CFG, not a.no_voice)
                yolo = (yolo or load_yolo(CFG)) if CFG["phone_detection"] else None
                streak_start, n_nags = None, 0
                log(f"config reloaded · tone {CFG['tone']} · voice {nag.voice}")

            idle = idle_seconds()
            if system_asleep():
                new_mode, why = "asleep", "screen"
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
                    if cap:
                        cap.release()
                        cap = None
                    camera_ok = False
                    STATE["jpeg"] = BLANK
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

            if cap is None:
                cap = cv2.VideoCapture(CFG["camera"])
                if not cap.isOpened():
                    cap = None
                    if camera_ok is not None:
                        log("Camera didn't open: allow OnDuty in System Settings › Privacy & Security › Camera.")
                    camera_ok = None
                    STATE["status"] = {**STATE["status"], "t": int(t0), "mode": "active", "camera_ok": False, "lang": CFG["lang"],
                                       "onboarded": CFG["onboarded"], "name": CFG["name"], "said": STATE["said"], "blur": STATE["blur"]}
                    time.sleep(3)
                    continue
            ok, frame = cap.read()
            if not ok:
                time.sleep(1)
                continue
            camera_ok = True

            pose = head_pose(lm, frame)
            phone_boxes = []
            if yolo:
                r = yolo.predict(frame, classes=[PHONE_CLASS], conf=th["phone_conf"], imgsz=480, verbose=False)[0]
                phone_boxes = r.boxes.xyxy.int().tolist()
            if phone_boxes:
                last_phone_t = t0
            phone = t0 - last_phone_t < 3  # phone seen in the last 3 s (it drifts in and out of frame)
            phone_hist.append(bool(phone_boxes))
            recent_phone.append(bool(phone_boxes))

            base = statistics.median(work_pitch) if len(work_pitch) >= 10 else None
            gbase = statistics.median(work_gaze) if work_gaze else 0.5
            dpitch = gaze = None
            if pose:
                pitch, gaze = pose
                last_face_t = t0
                if idle < 3:  # typing/using the mouse: this is the working posture
                    work_pitch.append(pitch)
                    work_gaze.append(gaze)
                dpitch = pitch - base if base is not None else 0.0
                face_down = base is not None and (dpitch > th["pitch_delta"] or gaze - gbase > th["gaze_delta"])
                last_down = face_down
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
            elif CFG["onboarded"] and (phone_now or face_now) and not streak_start:  # the wizard never nags
                streak_start = now - (2 if phone_now else th["window"] * th["down_ratio"])
            if streak_start and now - last_seen_t < 20 and nag.ready(n_nags + 1):
                # keeps talking until you're back (pauses if you walked away from the camera)
                n_nags += 1
                cause = "+".join(c for c, on in (("face", face_down), ("phone", any(phone_hist))) if on) or "face"
                said = nag.nag(n_nags, (now - streak_start) / 60)
                log(f"📵 line #{n_nags} level {nag.level(n_nags) + 1} via {cause}: {said}")
                db.record("alert", n=n_nags, cause=cause, level=nag.level(n_nags) + 1, said=said)

            if STATE["test"]:
                STATE["test"] = False
                lv = random.randrange(nag.tone["start"], nag.tone["cap"] + 1)
                log(f"📵 test (level {lv + 1}): {nag.say(random.choice(nag.levels[lv]), lv, 3, 7, kind='test')}")
            if now - last_save >= 60 and work_pitch:  # persist posture so restarts don't recalibrate
                last_save = now
                db.put("calibration", {"pitch": list(work_pitch)[-300:], "gaze": list(work_gaze)[-300:]})
            if a.debug and now - last_dbg >= 5:
                last_dbg = now
                log(f"face={'y' if pose else 'n'} dpitch={dpitch if dpitch is None else round(dpitch, 1)} "
                    f"gaze={gaze if gaze is None else round(gaze, 2)} base={base if base is None else round(base, 1)} "
                    f"phone={'y' if phone_boxes else 'n'} down={ratio:.0%} idle={idle:.0f}s")

            STATE["status"] = {
                "t": int(now), "mode": "active", "mode_why": "", "resume_at": 0, "camera_ok": True, "onboarded": CFG["onboarded"],
                "name": CFG["name"], "lang": CFG["lang"], "face": bool(pose),
                "dpitch": dpitch, "gaze": gaze, "gaze_base": gbase, "down": down, "face_down": face_down,
                "phone": bool(phone_boxes), "phone_on": yolo is not None,
                "phone_ratio": round(sum(phone_hist) / len(phone_hist), 2), "down_ratio": round(ratio, 2),
                "idle": round(idle), "scrolling": bool(streak_start), "level": nag.level(n_nags) + 1 if n_nags else 0,
                "nags": n_nags, "calibrated": base is not None, "work_samples": len(work_pitch),
                "phone_min": round((now - streak_start) / 60, 1) if streak_start else 0, "cfg": th,
                "blur": STATE["blur"], "said": STATE["said"],
            }
            STATE["series"].append([int(now), dpitch, gaze - gbase if gaze is not None else None, down,
                                    idle >= th["idle"], bool(phone_boxes)])
            for x1, y1, x2, y2 in phone_boxes:
                cv2.rectangle(frame, (x1, y1), (x2, y2), (94, 63, 244), 4)
                cv2.putText(frame, "phone", (x1, max(30, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (94, 63, 244), 3)
            small = cv2.resize(frame, (480, int(480 * frame.shape[0] / frame.shape[1])))
            if STATE["blur"]:  # dashboard preview only; detection already ran on the sharp frame
                h, w = small.shape[:2]  # heavy pixelate + blur: unrecognizable but still shows the pose
                small = cv2.resize(cv2.GaussianBlur(cv2.resize(small, (24, 18), interpolation=cv2.INTER_AREA), (0, 0), 2), (w, h), interpolation=cv2.INTER_CUBIC)
            STATE["jpeg"] = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()

            time.sleep(max(0, 1 / a.fps - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        if cap:
            cap.release()


if __name__ == "__main__":
    main()
