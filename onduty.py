"""onduty: manage the on-duty service.  ./onduty install | setup | doctor | phrases | ..."""

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import config

DIR = Path(__file__).resolve().parent
APP = DIR / "OnDuty.app"
LABEL = "com.onduty.service"
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
LOG = Path.home() / "Library/Logs/on-duty.log"
DB = Path.home() / ".on-duty/on-duty.db"
MODELS = {
    "face_landmarker.task": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    "yolo11n.pt": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt",
}
UID = os.getuid()


def sh(*cmd, check=False, **kw):
    return subprocess.run(cmd, check=check, **kw)


def download_models() -> None:
    (DIR / "models").mkdir(exist_ok=True)
    for name, url in MODELS.items():
        dest = DIR / "models" / name
        if dest.exists():
            continue
        print(f"downloading {name}…")
        urllib.request.urlretrieve(url, dest)


def build_app() -> None:
    shutil.rmtree(APP, ignore_errors=True)
    (APP / "Contents/MacOS").mkdir(parents=True)
    (APP / "Contents/Info.plist").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>{LABEL}</string>
  <key>CFBundleName</key><string>OnDuty</string>
  <key>CFBundleExecutable</key><string>on-duty</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSUIElement</key><true/>
  <key>NSCameraUsageDescription</key><string>on-duty watches for you leaving work for your phone. Nothing leaves this machine.</string>
</dict></plist>
""")
    (APP / "Contents/Resources").mkdir()
    shutil.copy(DIR / "assets/icon.icns", APP / "Contents/Resources/icon.icns")
    launcher = APP / "Contents/MacOS/on-duty"
    launcher.write_text(f"""#!/bin/zsh
cd "{DIR}"
export MPLCONFIGDIR=/tmp/on-duty-mpl GLOG_minloglevel=2
exec "{DIR}/.venv/bin/python" "{DIR}/on_duty.py" --debug >> "{LOG}" 2>&1
""")
    launcher.chmod(0o755)
    sh("codesign", "--force", "-s", "-", str(APP), check=True)


def unload() -> None:
    """launchctl bootout is asynchronous: wait until the job is really gone before bootstrapping again."""
    sh("launchctl", "bootout", f"gui/{UID}/{LABEL}", stderr=subprocess.DEVNULL)
    for _ in range(40):
        if sh("launchctl", "print", f"gui/{UID}/{LABEL}", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            return
        time.sleep(0.25)


def cmd_install(_a) -> None:
    sh("uv", "sync", "-q", cwd=DIR, check=True)
    download_models()
    config.load()
    build_app()
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array><string>/usr/bin/open</string><string>-W</string><string>{APP}</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
</dict></plist>
""")
    legacy = PLIST.with_name("com.valvesss.onduty.plist")  # pre-0.3 label of the author's install
    if legacy.exists():
        sh("launchctl", "bootout", f"gui/{UID}/com.valvesss.onduty", stderr=subprocess.DEVNULL)
        legacy.unlink()
    unload()
    sh("pkill", "-f", f"{DIR}/on_duty.py")  # bootout doesn't always take down the app `open` launched
    sh("launchctl", "bootstrap", f"gui/{UID}", str(PLIST), check=True)
    cfg = config.load()
    url = f"http://localhost:{cfg['port']}"
    print(f"installed. Allow Camera for OnDuty if macOS asks. Log: {LOG}")
    for _ in range(40):  # the engine needs a few seconds to load its models
        try:
            urllib.request.urlopen(url + "/status", timeout=1)
            break
        except OSError:
            time.sleep(1)
    else:
        sys.exit(f"the service didn't come up; see {LOG}")
    sh("open", url + ("" if cfg["onboarded"] else "/setup"))
    print(f"opened {url}{'' if cfg['onboarded'] else '/setup — finish the setup there'}")


def cmd_uninstall(_a) -> None:
    cmd_stop(_a)
    PLIST.unlink(missing_ok=True)
    print("removed")


def cmd_start(_a) -> None:
    sh("launchctl", "bootstrap", f"gui/{UID}", str(PLIST), check=True)
    print("started")


def cmd_stop(_a) -> None:
    unload()
    sh("pkill", "-f", f"{DIR}/on_duty.py")
    print("stopped (back at next login; ./onduty start to resume now)")


def cmd_restart(a) -> None:
    cmd_stop(a)
    time.sleep(1)
    cmd_start(a)


def cmd_open(_a) -> None:
    sh("open", f"http://localhost:{config.load()['port']}")


def cmd_recalibrate(_a) -> None:
    sh("open", f"http://localhost:{config.load()['port']}/setup?calibrate")


def cmd_test(_a) -> None:
    sh(sys.executable, "-m", "unittest", "discover", "-s", "tests", cwd=DIR, check=True)


def cmd_pause(a) -> None:
    body = json.dumps({"minutes": "tomorrow" if a.minutes == "tomorrow" else float(a.minutes)}).encode()
    req = urllib.request.Request(f"http://localhost:{config.load()['port']}/api/pause", body, {"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=3)
    print("resumed" if a.minutes == "0" else f"paused ({a.minutes})")


def cmd_status(_a) -> None:
    running = sh("pgrep", "-fl", f"{DIR}/on_duty.py").returncode == 0
    if not running:
        print("not running")
    status = DIR / "status.json"
    if status.exists():
        print(status.read_text())


def cmd_logs(_a) -> None:
    sh("tail", "-f", str(LOG))


def cmd_db(_a) -> None:
    sh("sqlite3", "-box", str(DB))


def cmd_stats(_a) -> None:
    con = sqlite3.connect(DB)
    q = lambda title, sql: print(f"— {title} —", *("  " + " · ".join(map(str, r)) for r in con.execute(sql)), sep="\n")  # noqa: E731
    q("per day (14 days): day · times · phone min · longest · lines",
      "SELECT date(start,'unixepoch','localtime'), count(*), round(sum(minutes),1), round(max(minutes),1), sum(n) "
      "FROM events WHERE kind='back' AND start > strftime('%s','now','-14 days') GROUP BY 1 ORDER BY 1 DESC")
    q("worst hours: hour · times · phone min",
      "SELECT strftime('%H',start,'unixepoch','localtime')||'h', count(*), round(sum(minutes),1) "
      "FROM events WHERE kind='back' GROUP BY 1 ORDER BY 3 DESC LIMIT 5")


def cmd_setup(a) -> None:
    cfg = config.load()
    if a.name is None and a.lang is None and a.voice is None:  # no flags: the wizard is the setup
        sh("open", f"http://localhost:{cfg['port']}/setup?edit")
        return
    cfg["name"] = cfg["name"] if a.name is None else a.name
    cfg["lang"] = a.lang or cfg["lang"]
    cfg["voice"] = cfg["voice"] if a.voice is None else a.voice
    config.save(cfg)
    print(f"saved {config.CONFIG_PATH}")
    if PLIST.exists():
        cmd_restart(a)


def cmd_doctor(_a) -> None:
    def check(label, ok, fix=""):
        print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f"  → {fix}" if not ok and fix else ""))

    check("macOS", platform.system() == "Darwin", "on-duty is macOS-only")
    check("Apple Silicon (phone detection)", platform.machine() == "arm64", "face signal still works; phone detection is off")
    check("uv installed", shutil.which("uv") is not None, "brew install uv")
    check(".venv", (DIR / ".venv/bin/python").exists(), "./onduty install")
    for name in MODELS:
        check(f"model {name}", (DIR / "models" / name).exists(), "./onduty install")
    check("service installed", PLIST.exists(), "./onduty install")
    try:
        cal = json.loads(urllib.request.urlopen(f"http://localhost:{config.load()['port']}/status", timeout=2).read()).get("calibration", {})
        check(f"calibrated for this setup ({cal.get('label') or cal.get('state')})", cal.get("state") == "ok", "./onduty recalibrate")
    except OSError:
        pass
    check("service running", sh("pgrep", "-f", f"{DIR}/on_duty.py", stdout=subprocess.DEVNULL).returncode == 0,
          f"./onduty logs  (Camera permission for OnDuty?)")


TEMPLATE = {
    "levels": [
        ["Gentle line.", ["Combo line one.", "Combo line two."]],
        ["Sarcastic line, {time} on the phone."],
        ["Firm line, {name}."],
        ["Dramatic line."],
        ["Absurd chaos line, nag number {n}."],
    ],
    "back": {"quick": ["Welcome back."], "medium": ["Welcome back, that was {time}."], "long": ["Finally. {time}."]},
}


def cmd_phrases(a) -> None:
    if a.action == "sources":
        home = Path.home()
        globs = [".claude/CLAUDE.md", ".claude/projects/*/memory/*.md", ".cursor/rules/*", ".cursorrules",
                 ".codex/AGENTS.md", ".codex/memories/*", ".gemini/GEMINI.md", ".codeium/windsurf/memories/*",
                 ".github/copilot-instructions.md", ".aider.conf.yml", ".continue/rules/*", ".clinerules/*",
                 "AGENTS.md", "CLAUDE.md"]
        found = [f for g in globs for f in sorted(home.glob(g)) if f.is_file()]
        for f in found:
            print(f"{f.stat().st_size:>8}  {f}")
        print(f"{len(found)} candidate files (nothing was read). Ask the user before opening any.", file=sys.stderr)
        return
    if a.action == "template":
        print(json.dumps(TEMPLATE, indent=2, ensure_ascii=False))
        return
    if not config.CUSTOM_PHRASES.exists():
        sys.exit(f"{config.CUSTOM_PHRASES} not found. See the on-duty-phrases skill or ./onduty phrases template")
    try:
        pack = json.loads(config.CUSTOM_PHRASES.read_text())
        assert len(pack["levels"]) == 5, "levels must have exactly 5 lists"
        assert all(pack["levels"]), "every level needs at least one line"
        assert all(pack["back"].get(k) for k in ("quick", "medium", "long")), "back needs quick, medium and long"
        fmt = {"time": "3 minutes", "n": 1, "name": "X"}
        for lv in [*pack["levels"], *pack["back"].values()]:
            for item in lv:
                [x.format(**fmt) for x in ([item] if isinstance(item, str) else item)]
    except (KeyError, AssertionError, ValueError, IndexError, json.JSONDecodeError) as e:
        sys.exit(f"invalid phrases.json: {e!r}")
    print(f"ok: {sum(map(len, pack['levels']))} lines. ./onduty restart to use them.")


def main() -> None:
    p = argparse.ArgumentParser(prog="onduty", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, h in [("install", cmd_install, "install/update the service (starts at login)"),
                        ("uninstall", cmd_uninstall, "remove the service"), ("start", cmd_start, "start now"),
                        ("stop", cmd_stop, "stop until next login"), ("restart", cmd_restart, "stop + start"),
                        ("status", cmd_status, "is it running?"), ("logs", cmd_logs, "tail the log"),
                        ("stats", cmd_stats, "summary from the local database"), ("db", cmd_db, "SQL shell"),
                        ("doctor", cmd_doctor, "check the setup")]:
        sub.add_parser(name, help=h).set_defaults(fn=fn)
    sub.add_parser("open", help="open the dashboard").set_defaults(fn=cmd_open)
    sub.add_parser("recalibrate", help="recalibrate for this desk / monitors / camera").set_defaults(fn=cmd_recalibrate)
    sub.add_parser("test", help="run the unit tests").set_defaults(fn=cmd_test)
    pz = sub.add_parser("pause", help="pause: <minutes> | tomorrow | 0 (resume)")
    pz.add_argument("minutes"), pz.set_defaults(fn=cmd_pause)
    s = sub.add_parser("setup", help="open the setup wizard (or set --name/--lang/--voice directly)")
    s.add_argument("--name"), s.add_argument("--lang", choices=list(config.VOICES)), s.add_argument("--voice")
    s.set_defaults(fn=cmd_setup)
    ph = sub.add_parser("phrases", help="phrases template | validate | sources  (custom pack: ~/.on-duty/phrases.json)")
    ph.add_argument("action", choices=["template", "validate", "sources"])
    ph.set_defaults(fn=cmd_phrases)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
