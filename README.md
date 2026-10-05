# on-duty

<img src="assets/logo.svg" width="96" align="right" alt="">

Your webcam notices when you stop working and start doomscrolling on your phone — and talks you back
to your desk. Everything runs locally on your Mac: no cloud, no LLM at runtime, no frames leave the machine.

*[Português abaixo](#português)*

<p align="center"><img src="assets/dashboard.png" width="720" alt="Dashboard (camera blurred)"></p>

## How it works

| Signal | How |
|---|---|
| Head pitch / eyes looking down | MediaPipe Face Landmarker, relative to **your** working posture (learned while you type, so camera angle doesn't matter) |
| Phone in frame | YOLO11n (COCO "cell phone") |
| You stopped typing | macOS `HIDIdleTime` |

**Trigger:** phone seen (~1 s) + 2 s without keyboard/mouse, **or** looking down for ≥60% of the last 8 s + 6 s without input.
Then it speaks, escalating every 3 lines through 5 levels (gentle → sarcastic → firm → drama → chaos),
until you touch the keyboard again.

Dashboard at <http://localhost:7878> — keep it open and it becomes a show:

- **Live stage:** a mascot whose face (and the whole page's mood) escalates with the nag level, and the
  line being spoken **types out live** in a speech bubble.
- **"Caught red-handed" polaroid** with your camera frame, a stamp and a running clock.
- **📸 Snap:** turns any moment (or any line from the *Hall of shame*) into a 4:5 card for stories/chats —
  download, copy or share. Level 4–5 lines pulse the button: those are the ones worth posting.
- Blur button for the camera preview, history charts, and a collapsible panel with the raw signals.

Your data (events + calibration) lives in `~/.on-duty/on-duty.db`.

## Install

Needs macOS, [uv](https://docs.astral.sh/uv/), and Apple Silicon for phone detection (Intel works with the face signal only).

```bash
git clone https://github.com/valvesss/on-duty-ai && cd on-duty-ai
./onduty install     # deps, models, LaunchAgent (starts at login)
./onduty setup       # your name + language (pt_BR | en_US)
./onduty doctor      # check everything
```

Allow **Camera** for OnDuty when macOS asks.

## Commands

```
./onduty install | uninstall | start | stop | restart | status | logs | stats | db | doctor
./onduty setup [--name N] [--lang en_US] [--voice Samantha]
./onduty phrases template | validate | sources
```

Settings live in `~/.on-duty/config.json` (name, language, voice, port, camera, thresholds).

### Personalized phrases (optional)

Ask your AI assistant to personalize the lines — in Claude Code, open this repo and say
"personalize on-duty's phrases". The `on-duty-phrases` skill (`.claude/skills/`) lists the memory/rules
files other assistants left on your Mac (Claude Code, Cursor, Codex, Gemini, Windsurf, Copilot…) with
`./onduty phrases sources`, **asks before reading any of them**, mines them for things to joke about
(your stack, projects, running gags — never secrets or anything private), and writes
`~/.on-duty/phrases.json`. Any assistant works: `./onduty phrases template` prints the schema and
`./onduty phrases validate` checks the result. Built-in lines are mixed in
(`"custom_phrases_only": true` to use only yours). No API key, no network.

---

## Português

A webcam percebe quando você larga o trabalho pra rolar o celular e te chama de volta. Tudo roda local
no seu Mac: sem nuvem, sem LLM em execução, nenhuma imagem sai da máquina.

**Gatilho:** celular visto (~1 s) + 2 s sem teclado/mouse, **ou** cabeça/olhar pra baixo em ≥60% dos
últimos 8 s + 6 s sem teclado. Aí ela fala sem parar, subindo de nível a cada 3 falas (gentil →
sarcástico → cobrança → drama → caos) até você voltar a digitar.

```bash
git clone https://github.com/valvesss/on-duty-ai && cd on-duty-ai
./onduty install
./onduty setup --lang pt_BR --name "Seu nome"
./onduty doctor
```

Painel em <http://localhost:7878> (idioma segue a configuração; botão para borrar a câmera).
Frases personalizadas: peça ao seu assistente de IA (no Claude Code, a skill `on-duty-phrases`) e valide com `./onduty phrases validate`.

## License

MIT
