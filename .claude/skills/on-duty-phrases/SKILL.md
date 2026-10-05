---
name: on-duty-phrases
description: Write a personalized phrase pack for on-duty (the voice lines it speaks when the user doomscrolls). Use when the user asks to customize, personalize or rewrite on-duty's phrases/voice lines/humor.
---

# on-duty phrases

on-duty speaks lines with macOS `say` while the user is on their phone, escalating one level every 3 lines.
You write the pack yourself — no API key, no script.

1. Read `~/.on-duty/config.json` (`name`, `lang`) and ask the user for a style if they didn't give one
   (persona, humor, interests). Built-in packs for tone reference: `phrases/pt_BR.py`, `phrases/en_US.py`.
2. Write `~/.on-duty/phrases.json` (`./onduty phrases template` prints the schema):
   - `levels`: exactly 5 lists — 1 gentle, 2 sarcastic, 3 firm, 4 dramatic, 5 absurd chaos; ~15 items each.
   - An item is a string or a list of 1–4 short sentences spoken with a pause between (comedic timing).
   - `back`: `quick` (<1 min), `medium` (1–5 min), `long` (>5 min), ~5 lines each, said on return.
   - Placeholders exactly as written: `{name}`, `{time}` (e.g. "3 minutes"), `{n}` (nag count). Use `{name}`
     in about a third of the items; lines with it are skipped when no name is set.
   - Written to be spoken: language from config, no emoji/markdown/parentheses, sentences under ~15 words,
     gender-neutral, funny never cruel (nothing about appearance, body or intelligence).
3. Run `./onduty phrases validate`, then `./onduty restart`, then offer a test: dashboard "Test alert" button.

Built-in lines are mixed in by default; set `"custom_phrases_only": true` in the config to use only yours.
