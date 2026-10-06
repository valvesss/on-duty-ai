"""macOS implementation of the OS abstraction layer (see osal.py and CONTRIBUTING.md).

Everything here is stdlib + ctypes + the macOS command line tools; no pyobjc."""

import ctypes
import ctypes.util
import subprocess
from pathlib import Path

_cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
_cg.CGMainDisplayID.restype = ctypes.c_uint32
_cg.CGDisplayIsAsleep.argtypes = [ctypes.c_uint32]
_cg.CGGetActiveDisplayList.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]

_ca = ctypes.CDLL(ctypes.util.find_library("CoreAudio"))


class _PropAddr(ctypes.Structure):
    _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("element", ctypes.c_uint32)]


_ca.AudioObjectGetPropertyData.argtypes = [ctypes.c_uint32, ctypes.POINTER(_PropAddr), ctypes.c_uint32, ctypes.c_void_p,
                                          ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
_ca.AudioObjectGetPropertyData.restype = ctypes.c_int32
_fourcc = lambda s: int.from_bytes(s.encode(), "big")  # noqa: E731


def idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input."""
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "HIDIdleTime" in line:
            return int(line.rsplit("=", 1)[1]) / 1e9
    return 0.0


def system_asleep() -> bool:
    """Display asleep, screen locked, or another user's session is in front."""
    if _cg.CGDisplayIsAsleep(_cg.CGMainDisplayID()):
        return True
    root = subprocess.run(["ioreg", "-n", "Root", "-d1"], capture_output=True, text=True).stdout
    return '"IOConsoleLocked" = Yes' in root or '"kCGSSessionOnConsoleKey"=No' in root


def display_count() -> int:
    n, buf = ctypes.c_uint32(0), (ctypes.c_uint32 * 16)()
    _cg.CGGetActiveDisplayList(16, buf, ctypes.byref(n))
    return max(1, n.value)


def mic_in_use() -> bool:
    """True when some app (a video call, a recorder, dictation…) is capturing from the default microphone."""
    dev, size = ctypes.c_uint32(0), ctypes.c_uint32(4)
    addr = _PropAddr(_fourcc("dIn "), _fourcc("glob"), 0)
    if _ca.AudioObjectGetPropertyData(1, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(dev)) or not dev.value:
        return False
    running = ctypes.c_uint32(0)
    addr = _PropAddr(_fourcc("gone"), _fourcc("glob"), 0)
    if _ca.AudioObjectGetPropertyData(dev.value, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(running)):
        return False
    return bool(running.value)


def list_voices() -> list[dict]:
    """[{name, locale}] for the languages on-duty speaks (Portuguese and English)."""
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    res = []
    for line in out.splitlines():
        head = line.split("#")[0].split()
        if len(head) >= 2 and head[-1][:2] in ("pt", "en"):
            res.append({"name": " ".join(head[:-1]), "locale": head[-1]})
    return res


def speak(voice: str, rate: int, lines: list[str]) -> subprocess.Popen:
    """Start speaking the lines in order (with a short pause between) and return the process (needs .poll() and .kill())."""
    return subprocess.Popen(["say", "-v", voice, "-r", str(rate), " [[slnc 600]] ".join(lines)])


_NOTIFIER = Path.home() / "Applications/on-duty.app"  # built by `onduty install` (see build_notifier)


def notify(title: str, message: str, subtitle: str = "", sound: bool = False, url: str = "", thread: str = "") -> None:
    """A desktop notification from the on-duty app (its icon and name; a click opens `url`). Falls back to a plain
    AppleScript notification if the notifier app isn't built."""
    if _NOTIFIER.exists():
        cmd = ["open", "-g", "-n", str(_NOTIFIER), "--args", "--title", title, "--body", message]
        for flag, val in (("--subtitle", subtitle), ("--url", url), ("--thread", thread)):
            if val:
                cmd += [flag, val]
        if sound:
            cmd.append("--sound")
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    safe = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
    script = f'display notification "{safe(message)}" with title "{safe(title)}"' + (f' subtitle "{safe(subtitle)}"' if subtitle else "") + (' sound name "Basso"' if sound else "")
    subprocess.Popen(["osascript", "-e", script])


def play_alert(volume: float) -> None:
    subprocess.Popen(["afplay", "-v", str(volume), "/System/Library/Sounds/Sosumi.aiff"])
