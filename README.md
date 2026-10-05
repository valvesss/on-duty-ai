<div align="center">

<img src="assets/logo.svg" width="112" alt="on-duty logo">

# on-duty

**Your webcam notices when you stop working and start doomscrolling — and talks you back to your desk.**

Local. Private. Slightly judgmental.

![macOS](https://img.shields.io/badge/macOS-Apple%20Silicon%20%26%20Intel-black?logo=apple)
![Python](https://img.shields.io/badge/python-3.12-3776ab?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
![No cloud](https://img.shields.io/badge/cloud-none-success)

<img src="assets/dashboard.png" width="820" alt="The on-duty live dashboard, camera blurred">

</div>

---

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/valvesss/on-duty-ai/main/install.sh | bash
```

That's it. A setup page opens in your browser and walks you through the rest in about a minute.
Prefer to read the script first? [`install.sh`](install.sh) is short and readable. Or do it by hand:

```bash
git clone https://github.com/valvesss/on-duty-ai && cd on-duty-ai && ./onduty install
```

> Needs macOS and [uv](https://docs.astral.sh/uv/) (the installer gets it for you). When macOS asks, allow **Camera** for *OnDuty* and **Notifications** for *on-duty*. For notifications with the on-duty icon the installer builds a tiny helper app with the Xcode Command Line Tools' Swift compiler (`xcode-select --install`); without it you still get plain notifications.

## What you get

| | |
|---|---|
| 🧭 **First-run wizard** | Name, language, how hard it should push, your work hours and breaks, voice, and a live camera check. Opens by itself after install. |
| 🎭 **A live stage** | A mascot whose face — and the whole page's mood — escalates with every nag. The line being spoken **types out live** in a speech bubble. |
| 📸 **Shareable moments** | One click turns a moment (or any line from the *Hall of shame*) into a 4:5 "caught red-handed" card for stories and group chats. |
| 🎯 **Focus blocks** | Start a 25/50/90-minute block: it nags a bit harder inside it, counts your slips, celebrates when you finish, and logs it. |
| 📊 **Your week** | Time on the phone per day, an hour-of-day heatmap, trend vs. the previous period, longest session, best/worst day, and your focus blocks. |
| 😴 **Not always on** | Sleeps — camera light off — when your screen sleeps or locks, outside your work hours, on breaks, or when you've walked away. |
| 📐 **Calibration that adapts** | Zones for each monitor, a personal sensitivity, and automatic detection when you move, dock, or switch camera. |
| 🧠 **Lines that sound like you** | Your AI assistant can write the phrases from what it already knows about you. |
| 🔒 **Private by design** | No cloud, no account, no LLM at runtime. Frames never leave your Mac and are never saved. |

<table>
<tr>
<td width="58%"><img src="assets/setup.png" alt="The setup wizard, tone step"></td>
<td width="42%"><img src="assets/card.png" alt="A shareable caught-red-handed card"></td>
</tr>
<tr>
<td align="center"><sub>The setup wizard — one question at a time, the mascot follows your cursor</sub></td>
<td align="center"><sub>The shareable card</sub></td>
</tr>
</table>

## How it works

```mermaid
flowchart LR
    cam[Webcam] --> face[MediaPipe<br/>head pitch + gaze]
    cam --> yolo[YOLO11n<br/>phone in frame]
    hid[macOS idle time<br/>keyboard / mouse] --> trig{Trigger}
    face --> trig
    yolo --> trig
    trig -- phone seen + 2 s idle<br/>or looking down + 6 s idle --> nag[Speaks + notifies<br/>escalating levels]
    nag -- you type again --> done[Welcome back 🎉]
```

- **Your posture is the baseline.** Head pitch and eye gaze are measured *relative to how you sit while typing*, so camera angle doesn't matter.
- **Phone in frame** (YOLO11n, COCO "cell phone") is an instant signal. It needs Apple Silicon; on Intel the face signal still works.
- **It's built to avoid false alarms.** Decisions use a smoothed pose (a one-frame flip is ignored); eyes alone only count when strongly down; turning your head to another monitor is "looking away", not "down"; and the trigger never sits below your own natural jitter (it's measured while you type and raised automatically).
- **Only typing ends it.** Once it starts, it keeps talking — five levels, gentle → sarcastic → firm → drama → chaos — until you touch the keyboard or mouse again.

### When it sleeps

on-duty isn't a background hog. It drops the camera and goes quiet when:

| Situation | Behavior |
|---|---|
| Screen asleep, locked, or another user's session in front | Camera released, polls every few seconds |
| An app is using the microphone (a call) | Quiet and camera released until the call ends (turn off with `pause_in_meetings`) |
| Outside your work days/hours, or during a break | Camera released, wakes by itself at the next window |
| You paused it (⏸ in the dashboard, or `./onduty pause 60`) | Camera released until it expires |
| No face for 2 min *and* no input for 3 min | Camera released until you touch the Mac |

The dashboard shows each state (and when it's back) instead of going blank.

## The dashboard

Open <http://localhost:4269> and keep it on a second monitor.

- **Live speech bubble** — each line appears as it's spoken.
- **Smooth live camera** (~20 fps; detection runs separately at its own pace) in a straight polaroid, mirrored like a selfie view, with a stamp and a running clock. The **🎥 Camera** menu has *Mirror*, *Blur*, and **Straighten** — sit upright for 3 seconds and it measures your camera's tilt from your eye line and levels the picture.
- **📸 Snap** — builds the shareable card; download, copy, or share. Level 4–5 lines make the button pulse: those are the ones worth posting.
- **Hall of shame** — today's heaviest lines, one tap each from becoming a card.
- History charts, focus streak, and a collapsible panel with the raw signals and the live head-pose radar.
- **🎯 Focus** starts a timed block (25/50/90 min) with a countdown; **📊** opens your week.
- **📐 Calibrate** is always in the header (amber and pulsing when this setup needs it). **⚙** opens **Settings**; **⏸** pauses for an hour or until tomorrow.

## Personalize the lines

Out of the box on-duty speaks built-in lines in English or Brazilian Portuguese. To make them about *you*:

1. Open Claude Code (or any AI assistant) in this folder.
2. Say: **"Personalize on-duty's phrases for me."**

The bundled [`on-duty-phrases`](.claude/skills/on-duty-phrases/SKILL.md) skill lists the memory and rules files your other assistants left on your Mac (Claude Code, Cursor, Codex, Gemini, Windsurf, Copilot…), **asks before reading any of them**, mines them for things to joke about — your stack, your projects, your running gags; never secrets or anything private — and writes `~/.on-duty/phrases.json`.

Using another assistant? `./onduty phrases template` prints the schema, `./onduty phrases validate` checks the result.

## Calibration

on-duty works out of the box by learning your posture while you type. For a rounder result, run the 40-second calibration (the wizard offers it; `./onduty recalibrate` or the 📐 button reopens it any time):

1. **Where you look while working** — main screen, second monitor, keyboard/notes, laptop screen. Each place is a *zone* with its own baseline, so glancing at the other monitor never counts as scrolling.
2. **How you look at your phone** — I measure how far your head and eyes drop, and set the trigger half-way between "working" and "phone", scaled by *Relaxed / Normal / Strict*.
3. **Try it** — a live radar shows you (the dot), your zones (green) and where I'd nag (red band), before you save.

While you capture, you get live hints (too dark, too far, off-center, moving) and bad captures are rejected instead of saved.

**It also notices when your setup changes** and asks to recalibrate:

| What changed | What happens |
|---|---|
| Plugged in / unplugged a monitor | New *setup* detected (camera + number of displays + resolution). A banner offers to recalibrate; if you calibrated that setup before (home vs. office), it loads automatically. |
| Switched camera (external webcam, another index) | Same: it's a different setup. The wizard has a **Switch camera** button. |
| Moved the laptop, tilted the screen, new chair | Your typing posture shifts by more than ~9° for a few minutes → "your setup seems to have moved" banner. |
| Slouching through the day | Absorbed silently (up to ±8°) without recalibrating. |
| Dark room, camera covered | A "can't see you" banner instead of silent misses. |

Each setup keeps its own saved calibration in `~/.on-duty/on-duty.db`.

### Teach it when it's wrong

Two buttons keep it honest. **🙅 I wasn't on my phone** (on the stage while it nags) stops the nag, pauses it for a minute and makes the trigger more relaxed; **📱 You missed one** (in the dashboard's details) makes it stricter. The adjustment is saved per setup and reset when you recalibrate.

## Focus blocks, meetings and your week

- **🎯 Focus** (dashboard header): pick 25, 50 or 90 minutes. Inside a block it starts at level 2 and nags 20% faster, runs even outside your work hours, counts every slip and the minutes lost, says a closing line when you finish, and saves the block. Stop early any time.
- **Calls:** when another app captures your microphone (Zoom, Meet, Teams, a recorder…), on-duty goes quiet and frees the camera, then resumes on its own. It reads only the "microphone is in use" flag from the OS: it never listens, and it doesn't know which app it is.
- **📊 Your week** (`/summary`): minutes per day, when it happens (hour × day heatmap), trend against the previous period (7/14/30 days), best and worst day, and focus blocks. *Copy as text* makes a shareable summary.

## Updating

```bash
./onduty update      # git pull + reinstall the service in place; your config, calibration and history are kept
```

Want a heads-up? Turn on **Check for updates daily** in Settings: it runs a `git fetch` from GitHub (off by default, the only optional network call) and shows a banner when there's something new.

## Platform support and contributing

| | Status |
|---|---|
| macOS (Apple Silicon and Intel) | ✅ supported |
| Linux, Windows | 🙋 **welcome contributions.** All OS-specific code lives behind [`osal.py`](osal.py) plus the service in [`onduty.py`](onduty.py); [CONTRIBUTING.md](CONTRIBUTING.md) has the contract for each function and ideas per OS. |

```bash
./onduty test        # 60+ unit and API tests: calibration math, detection rules, focus, weekly stats, the HTTP API
```

## Commands

```text
./onduty install | uninstall      install / remove the background service (starts at login)
./onduty update                   pull the latest version and reinstall in place
./onduty start | stop | restart   control it
./onduty open                     open the dashboard
./onduty setup                    open Settings (the first-run wizard is at /setup)
./onduty recalibrate              recalibrate for this desk / monitors / camera
./onduty pause 60 | tomorrow | 0  pause for N minutes, until tomorrow, or resume
./onduty status | logs | stats    what's it doing, tail the log, summary from the local database
./onduty doctor                   check your setup
./onduty test                     run the unit tests
./onduty phrases template | validate | sources
```

## Settings

The **⚙** button (or `./onduty setup`) opens a settings page with everything, saved as you change it: profile and language, humor and alert sounds, work schedule, voice, camera (switch, mirror, straighten) and phone detection, calibration (status, saved setups per desk/monitor, reset fine-tuning), your custom phrases, data retention, **export** and **delete** of your history, and about.

## Configuration

Everything also lives in `~/.on-duty/config.json`.

| Key | Default | |
|---|---|---|
| `name` | `""` | Used in lines (`{name}`); lines that need it are skipped when empty |
| `lang` | `pt_BR` | `pt_BR` or `en_US` — voice and lines |
| `tone` | `balanced` | `friendly` · `balanced` · `ruthless` · `chaos` |
| `voice` / `voice_on` | default / `true` | Any macOS voice; off = notifications and dashboard only |
| `schedule` | Mon–Fri 09:00–18:00, break 12:00–13:30 | `"enforce": false` = always on |
| `camera` | `0` | Camera index (the wizard's *Switch camera* button changes it) |
| `mirror` | `true` | Selfie-style preview (detection always uses the raw image) |
| `rotate` | `0` | Degrees to straighten a tilted camera (set by *Straighten*) |
| `phone_detection` | `true` | The YOLO phone detector |
| `notifications` / `sound_effects` | `true` | macOS notification on start and escalation; the alert sound from level 3 |
| `pause_in_meetings` | `true` | Stay quiet and free the camera while an app uses the microphone |
| `update_check` | `false` | Opt-in daily `git fetch` to tell you about a new version |
| `retention_days` | `365` | Events older than this are deleted at startup (`0` = keep forever) |
| `port` | `4269` | Dashboard at `http://localhost:<port>` (restart after changing) |
| `custom_phrases_only` | `false` | Use only your `phrases.json` instead of mixing with the built-ins |
| `thresholds` | see [`config.py`](config.py) | Head/gaze sensitivity, idle seconds, YOLO confidence |

Your data (events and posture calibration) stays in `~/.on-duty/on-duty.db`, a plain SQLite file. Its schema is versioned (`PRAGMA user_version`) and upgrades itself on start.

## Notifications

Each alert is a real macOS notification from the **on-duty** app (its icon, in *System Settings › Notifications*): the title is the mood (`😇 Gentle`, `😏 Sarcastic`, `😤 Firm`, `🎭 Drama`, `🤪 Chaos`), the subtitle is your name and level, and the body is the line it just said. Clicking one opens the dashboard. You also get `🎯 Focus complete`, `📐 Calibration` (new setup or your posture moved) and `⬆️ Update available`, each only when it matters. Turn them off in Settings. Opening *on-duty* from Spotlight takes you to the dashboard.

## Troubleshooting

<details><summary><b>Notifications say "Script Editor" or have no icon</b></summary>

The helper app wasn't built. Run `xcode-select --install`, then `./onduty install`, and check `./onduty doctor`. If notifications are built but silent, allow them in *System Settings › Notifications › on-duty*.
</details>

<details><summary><b>The camera check says "waiting for permission"</b></summary>

Allow **OnDuty** in *System Settings › Privacy & Security › Camera*. The wizard keeps retrying. If it's not listed, run `./onduty restart`.
</details>

<details><summary><b>It nags while I'm clearly working</b></summary>

It needs a few seconds of typing to learn your posture after install. If it still misfires, raise `pitch_delta` or `down_ratio` in `config.json` (thresholds), or restart after changing your camera position drastically.
</details>

<details><summary><b>It doesn't see my phone</b></summary>

Phone detection needs Apple Silicon and decent light. Check `./onduty doctor`, and make sure the phone is visible in the wizard's camera step.
</details>

<details><summary><b>Does anything leave my Mac?</b></summary>

No. Frames are processed in memory, the dashboard only listens on `127.0.0.1`, and there is no telemetry. The only downloads happen at install (Python packages and the two model files), plus the opt-in update check if you turn it on.
</details>

<details><summary><b>Uninstall</b></summary>

`./onduty uninstall`, then delete the folder and `~/.on-duty`.
</details>

## Under the hood

Python 3.12 · [MediaPipe](https://ai.google.dev/edge/mediapipe) Face Landmarker · [Ultralytics](https://github.com/ultralytics/ultralytics) YOLO11n · macOS `say`, `ioreg` and CoreGraphics · a single-file dashboard and wizard in plain HTML/JS (no build step) · a LaunchAgent that starts it at login.

## License

[MIT](LICENSE) © Vitor Alves
