# Contributing to on-duty

Thanks for helping! on-duty is small on purpose: Python, no build step, no cloud. **macOS is the only supported platform
today, and Linux and Windows ports are explicitly welcome.** The code is organized so a port is mostly one new file.

## Setup

```bash
git clone https://github.com/valvesss/on-duty-ai && cd on-duty-ai
uv sync                      # Python 3.12 + dependencies
./onduty test                # or: uv run python -m unittest discover -s tests
./onduty install             # installs the background service (macOS)
```

For quick iteration run the engine in the foreground (stop the service first with `./onduty stop`):

```bash
uv run python on_duty.py --debug      # dashboard at http://localhost:4269
```

## Map of the code

| File | What it is |
|---|---|
| `on_duty.py` | The engine: camera thread, detection loop, HTTP server, modes (active / asleep / off-duty / paused / meeting / away) |
| `osal.py` → `osal_macos.py` | **OS abstraction layer** — everything that touches the operating system. Port here. |
| `onduty.py` + `onduty` | The CLI (`install`, `update`, `doctor`…) and the **service** (launchd). Port here too. |
| `calibration.py`, `logic.py`, `stats.py` | Pure logic: calibration math, debouncing/focus, weekly summary. No OS, fully unit-tested. |
| `config.py`, `db.py` | Settings (`~/.on-duty/config.json`) and the SQLite store with versioned migrations |
| `dashboard.html`, `setup.html`, `settings.html`, `summary.html`, `assets/radar.js` | The UI: plain HTML/JS, no framework, no build |
| `phrases/` | Built-in lines (`pt_BR.py`, `en_US.py`); add a language by adding a module |
| `tests/` | `unittest`. API tests run the real HTTP handler on a temp home and DB |

## Porting to Linux or Windows

1. Create `osal_linux.py` (or `osal_windows.py`) exporting the functions below, then add it to the dispatch in `osal.py`.
2. Replace the launchd service in `onduty.py` (`cmd_install`, `unload`, `cmd_start/stop`, `build_app`) with a
   `systemd --user` unit (Linux) or a Task Scheduler entry / Startup shortcut (Windows).
3. Check the camera backend: OpenCV uses V4L2 on Linux and DirectShow/MSMF on Windows. Camera permission prompts differ.
4. Run `./onduty test` and `./onduty doctor`, and describe what you tested in the PR.

The contract (`tests/test_osal.py` checks that every name exists):

| Function | Must do | macOS today | Ideas |
|---|---|---|---|
| `idle_seconds() -> float` | Seconds since the last keyboard/mouse input | `ioreg` `HIDIdleTime` | Linux: `xprintidle` / `org.gnome.Mutter.IdleMonitor`. Windows: `GetLastInputInfo` |
| `system_asleep() -> bool` | Display off, screen locked, or another user's session in front | CoreGraphics + `ioreg` | Linux: `loginctl show-session -p LockedHint`. Windows: session lock/`WTS` events |
| `display_count() -> int` | Number of active displays (part of the *setup signature*) | `CGGetActiveDisplayList` | `xrandr --listactivemonitors`; `EnumDisplayMonitors` |
| `mic_in_use() -> bool` | Some app is capturing the microphone (a call) | CoreAudio `DeviceIsRunningSomewhere` | `pactl list source-outputs`; Windows audio session API |
| `list_voices() -> list[{name, locale}]` | Text-to-speech voices for `pt`/`en` | `say -v ?` | `espeak-ng --voices`, `spd-say`; SAPI voices |
| `speak(voice, rate, lines) -> Popen-like` | Speak the lines in order, return an object with `.poll()` and `.kill()` | `say` | `espeak-ng`/`spd-say`; PowerShell `System.Speech` |
| `notify(title, message, subtitle, sound, url, thread)` | A desktop notification; clicking it should open `url` (the dashboard); `thread` groups related ones | a small Swift app, `~/Applications/on-duty.app` (`native/notify.swift`), so macOS shows on-duty's icon and name | `notify-send` (`--action`); Windows toast |
| `play_alert(volume)` | Short attention sound | `afplay` | `paplay`; `winsound` |

Things in the engine that currently assume macOS and are fair game for a port: the LaunchAgent/`.app` bundle in
`onduty.py`; the `[[slnc 600]]` pause marker (already inside `osal_macos.speak`); the install script (`install.sh`);
the Apple Silicon note for phone detection (YOLO via PyTorch also runs on CPU/CUDA elsewhere).

## Principles

- **Local and private.** No telemetry, no accounts, no cloud. Frames are processed in memory and never saved. The only
  optional network call is the opt-in update check (`git fetch`). A PR that adds network traffic needs a very good reason.
- **No build step.** The UI is hand-written HTML/JS/CSS so anyone can read and change it.
- **Pure logic gets tests.** If a decision can be written without the camera or the OS, put it in `calibration.py`,
  `logic.py` or `stats.py` and test it. Behavior changes in detection should come with a test of the rule.
- **Be kind about false alarms.** A wrong nag is worse than a missed one. Prefer conservative defaults.
- **Don't fabricate verification.** In your PR, say what you ran on real hardware and what you only reasoned about.

## Pull requests

Small and focused is great. Include: what changed and why, how you tested it (`./onduty test` output, plus anything manual),
and screenshots for UI changes (with the camera **blurred**: use the *Blur* option; please don't post your face).
