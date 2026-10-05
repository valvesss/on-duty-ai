# on-duty

<img src="assets/logo.svg" width="96" align="right" alt="">

Your webcam notices when you stop working and start doomscrolling on your phone — and talks you back
to your desk. Everything runs locally on your Mac: no cloud, no LLM at runtime, no frames leave the machine.

*[Português abaixo](#português)*

## How it works

| Signal | How |
|---|---|
| Head pitch / eyes looking down | MediaPipe Face Landmarker, relative to **your** working posture (learned while you type, so camera angle doesn't matter) |
| Phone in frame | YOLO11n (COCO "cell phone") |
| You stopped typing | macOS `HIDIdleTime` |

**Trigger:** phone seen (~1 s) + 2 s without keyboard/mouse, **or** looking down for ≥60% of the last 8 s + 6 s without input.
Then it speaks, escalating every 3 lines through 5 levels (gentle → sarcastic → firm → drama → chaos),
until you touch the keyboard again.

Dashboard at <http://localhost:7878>: live camera (with a blur button), signals, history. Your data
(events + calibration) lives in `~/.on-duty/on-duty.db`.

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
./onduty phrases generate [--style "drill sergeant who loves football puns"]
```

Settings live in `~/.on-duty/config.json` (name, language, voice, port, camera, thresholds).

### Personalized phrases (optional)

`./onduty phrases generate` asks Claude to write a pack with your name and chosen style, saved to
`~/.on-duty/phrases.json` and mixed with the built-in lines (`"custom_phrases_only": true` to use only yours).
Needs `ANTHROPIC_API_KEY`. The only network call in the project, only when you run it.

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
`./onduty phrases generate --style "..."` cria frases personalizadas com Claude (opcional, precisa de `ANTHROPIC_API_KEY`).

## License

MIT
