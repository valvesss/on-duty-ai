"""Calibration math, kept free of camera/OS code so it can be unit-tested.

A *setup* is one physical arrangement: camera + number of displays + camera resolution. Each setup keeps its own
*zones* (the places you look at while working: main screen, second monitor, laptop…) and a personalized
sensitivity measured from a short "now look at your phone" sample. Pitch is in degrees, positive = head down.
"""

import collections
import statistics

MIN_SAMPLES = 6
MAX_MAD = 8.0  # degrees of pitch spread beyond which a capture is rejected
SENSITIVITY = {"relaxed": 1.3, "normal": 1.0, "strict": 0.75}
DRIFT_ON, DRIFT_OFF = 9.0, 6.0  # degrees of typing-posture shift that flags / clears "your setup moved"
DRIFT_CLAMP = 8.0               # how much slow drift the engine absorbs silently
PITCH_FLOOR = 7.0               # never trigger on less head drop than this: it's inside natural jitter
GAZE_FLOOR = 0.22
UNCALIBRATED_FACTOR = 1.4       # until calibrated, be 40% less trigger-happy
TURNED_YAW = 25.0               # degrees away from the zone you face: pitch is unreliable, so it's "looking away", not "down"


def median(xs):
    return statistics.median(xs) if xs else 0.0


def mad(xs):
    m = median(xs)
    return median([abs(x - m) for x in xs]) if xs else 0.0


def summarize(samples: list[tuple[float, float, float]]) -> dict | None:
    """(pitch, yaw, gaze) samples → robust centre of the cluster, or None when there aren't enough."""
    if len(samples) < MIN_SAMPLES:
        return None
    pm, spread = median([s[0] for s in samples]), max(2.0, 3 * mad([s[0] for s in samples]))
    kept = [s for s in samples if abs(s[0] - pm) <= spread]  # drop the head-turn / glance outliers
    if len(kept) < MIN_SAMPLES:
        return None
    p, y, g = ([s[i] for s in kept] for i in range(3))
    if mad(p) > MAX_MAD:  # you were moving around: a median of that would be meaningless
        return None
    return {"n": len(kept), "pitch": round(median(p), 2), "yaw": round(median(y), 2), "gaze": round(median(g), 3),
            "pitch_mad": round(mad(p), 2)}


def nearest_zone(zones: list[dict], yaw: float) -> dict | None:
    """The zone you're facing, by head yaw (so a second monitor to the side gets its own baseline)."""
    return min(zones, key=lambda z: abs(z["yaw"] - yaw)) if zones else None


def separation(zones: list[dict], phone: dict | None) -> dict:
    """How different the phone pose is from working: pitch drop in degrees and a verdict (good | weak | none)."""
    if not zones or not phone:
        return {"pitch": 0.0, "verdict": "none"}
    dp = phone["pitch"] - median([z["pitch"] for z in zones])
    return {"pitch": round(dp, 1), "verdict": "good" if dp >= 12 else "weak" if dp >= 6 else "none"}


def derive_thresholds(zones: list[dict], phone: dict | None, sensitivity: str = "normal") -> dict:
    """Personal pitch/gaze deltas: half way between how you sit and how you sit with the phone, scaled by sensitivity,
    never below the natural-jitter floors. Returns only the keys it could measure; the caller keeps its defaults."""
    if not zones or not phone:
        return {}
    mult = SENSITIVITY.get(sensitivity, 1.0)
    ref_g = median([z["gaze"] for z in zones])
    out = {}
    if (dp := phone["pitch"] - median([z["pitch"] for z in zones])) >= 4:
        out["pitch_delta"] = round(min(20.0, max(PITCH_FLOOR, dp * 0.5 * mult)), 1)
    if (dg := phone["gaze"] - ref_g) >= 0.05:
        out["gaze_delta"] = round(min(0.45, max(GAZE_FLOOR, dg * 0.5 * mult)), 2)
    return out


def noise_floor(resid: list[float]) -> float:
    """Pitch delta below which a trigger would just be your own jitter, from how much you move while typing."""
    return 2.5 * mad(resid) + 2.0 if len(resid) >= 60 else 0.0


def effective_thresholds(cfg_th: dict, overrides: dict, tuning: dict, noise: float, calibrated: bool) -> dict:
    th = {**cfg_th, **overrides}
    th["pitch_delta"] = max(th["pitch_delta"] + tuning.get("pitch", 0.0), PITCH_FLOOR - 2, noise)
    th["gaze_delta"] = max(th["gaze_delta"] + tuning.get("gaze", 0.0), 0.1)
    if not calibrated:
        th["pitch_delta"] *= UNCALIBRATED_FACTOR
        th["gaze_delta"] *= UNCALIBRATED_FACTOR
    return {**th, "pitch_delta": round(th["pitch_delta"], 1), "gaze_delta": round(th["gaze_delta"], 2)}


def adjust_tuning(tuning: dict, kind: str) -> dict:
    """User feedback nudges the thresholds: 'false_positive' relaxes, 'missed' tightens."""
    sign = 1 if kind == "false_positive" else -1
    return {"pitch": max(-4.0, min(12.0, tuning.get("pitch", 0.0) + 2.0 * sign)),
            "gaze": max(-0.1, min(0.3, round(tuning.get("gaze", 0.0) + 0.04 * sign, 2)))}


def is_face_down(dpitch: float, gaze_excess: float, pitch_delta: float, gaze_delta: float, turned: bool) -> bool:
    """Head drop decides. Eyes alone only count when strongly down, or when the head is already part-way."""
    if turned:
        return False
    return dpitch > pitch_delta or gaze_excess > 1.8 * gaze_delta or (gaze_excess > gaze_delta and dpitch > 0.5 * pitch_delta)


def turned_away(pose_yaw: float, zone_yaw: float) -> bool:
    return abs(pose_yaw - zone_yaw) > TURNED_YAW


class Smoother:
    """Median of the last few poses: kills single-frame flips without adding noticeable lag."""

    def __init__(self, n: int = 3):
        self.buf: collections.deque = collections.deque(maxlen=n)

    def push(self, sample: tuple[float, ...] | None):
        if sample is None:
            self.buf.clear()
            return None
        self.buf.append(sample)
        return tuple(median([b[i] for b in self.buf]) for i in range(len(sample)))


def setup_signature(camera: int, displays: int, width: int, height: int) -> str:
    return f"cam{camera}-{displays}d-{width}x{height}"


def setup_label(displays: int, camera: int) -> str:
    return f"{displays} display{'s' if displays != 1 else ''} · camera {camera}"


def quality(face_ratio: float, brightness: float, face_h: float, cx: float, pitch_mad: float) -> dict:
    """What to tell the user while capturing. Issue codes are translated by the UI."""
    issues = []
    if face_ratio < 0.7:
        issues.append("no_face")
    if brightness < 55:
        issues.append("dark")
    elif brightness > 205:
        issues.append("bright")
    if face_h and face_h < 0.16:
        issues.append("far")
    elif face_h > 0.62:
        issues.append("close")
    if face_h and abs(cx - 0.5) > 0.3:
        issues.append("off_center")
    if pitch_mad > 3.5:
        issues.append("moving")
    return {"ok": not issues, "issues": issues}


def drift_state(was_drifting: bool, median_residual: float) -> bool:
    """Hysteresis around the drift thresholds so the banner doesn't flicker."""
    return abs(median_residual) > (DRIFT_OFF if was_drifting else DRIFT_ON)


def clamp_drift(median_residual: float) -> float:
    return max(-DRIFT_CLAMP, min(DRIFT_CLAMP, median_residual))


class CaptureSession:
    """One timed capture (a zone or the phone pose). The engine feeds it one sample per frame."""

    def __init__(self, kind: str, name: str, dur: float, t0: float):
        self.kind, self.name, self.dur, self.t0 = kind, name, dur, t0
        self.samples: list[tuple[float, float, float]] = []
        self.frames = 0
        self.bright: list[float] = []
        self.face_h: list[float] = []
        self.cx: list[float] = []
        self.phone_frames = 0

    def add(self, sample: tuple[float, float, float] | None, brightness: float, face_h: float = 0.0, cx: float = 0.5, phone: bool = False) -> None:
        self.frames += 1
        self.phone_frames += bool(phone)
        self.bright.append(brightness)
        if sample:
            self.samples.append(sample)
            self.face_h.append(face_h)
            self.cx.append(cx)

    def quality(self) -> dict:
        return quality(len(self.samples) / self.frames if self.frames else 0.0, median(self.bright), median(self.face_h),
                       median(self.cx), mad([s[0] for s in self.samples]))

    def live(self, now: float) -> dict:
        return {"kind": self.kind, "name": self.name, "progress": min(1.0, (now - self.t0) / self.dur),
                "quality": self.quality(), "samples": len(self.samples), "phone_seen": self.phone_frames > 0}

    def done(self, now: float) -> bool:
        return now - self.t0 >= self.dur

    def result(self) -> dict:
        summary = summarize(self.samples)
        err = None if summary else ("moving" if len(self.samples) >= MIN_SAMPLES else "no_face")
        return {"kind": self.kind, "name": self.name, "ok": bool(summary), "error": err, "summary": summary, "quality": self.quality(),
                "phone_ratio": round(self.phone_frames / self.frames, 2) if self.frames else 0.0}
