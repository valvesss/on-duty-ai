---
name: on-duty-phrases
description: Write a personalized phrase pack for on-duty (the voice lines it speaks, and shows on the live dashboard, when the user doomscrolls), tailored from what the user's AI assistants already know about them. Use when the user asks to customize, personalize or rewrite on-duty's phrases, voice lines or humor.
---

# on-duty phrases

on-duty speaks lines with macOS `say` (and types them live on the dashboard) while the user is on their phone,
escalating one level every 3 lines. You write the pack yourself — no API key, no script. The better you know
the person, the funnier the lines (and the more likely they screenshot the dashboard).

## 1. Learn who they are (with permission)

1. `cat ~/.on-duty/config.json` → `name`, `lang`.
2. `./onduty phrases sources` lists memory/rules files other assistants left on this Mac (Claude Code memory,
   `~/.claude/CLAUDE.md`, Cursor rules, Codex `AGENTS.md`, Gemini, Windsurf, Copilot, Continue, Cline…).
   It only lists paths and sizes; it reads nothing.
3. **Tell the user which files you want to read and why, and wait for a yes.** Read only the approved ones.
   Your own memory/context counts too — use what you already know, same rules.
4. Pull only comedy material: job and projects (they're in the dev trenches), tools and stacks they love or
   hate, running jokes, hobbies, team/product names, habits, the deadline they're always chasing.
5. **Never use** secrets, keys, customer or employer-confidential data, health, family, money, or anything the
   person would be uncomfortable seeing in a screenshot on social media. Don't quote files verbatim; riff on
   them. If a source has nothing funny, skip it. Without any source, ask 2–3 quick questions instead.

## 2. Write `~/.on-duty/phrases.json`

`./onduty phrases template` prints the schema.
- `levels`: exactly 5 lists — 1 gentle, 2 sarcastic, 3 firm, 4 dramatic, 5 absurd chaos; ~15 items each.
  Level 4–5 lines are the ones people screenshot: make them quotable and absurd, specific to the person.
- An item is a string or a list of 1–4 short sentences spoken with a pause between (comedic timing).
- `back`: `quick` (<1 min), `medium` (1–5 min), `long` (>5 min), ~5 lines each, said on return.
- Placeholders exactly as written: `{name}`, `{time}` (e.g. "3 minutes"), `{n}` (nag count). Use `{name}` in
  about a third of the items; lines with it are skipped when no name is set.
- Written to be spoken: language from config, no emoji/markdown/parentheses, sentences under ~15 words,
  gender-neutral, funny never cruel (nothing about appearance, body or intelligence).

## 3. Check

`./onduty phrases validate`, then `./onduty restart`, then open <http://localhost:7878> and press
**Test alert** so the user sees the line appear live. Offer to adjust the tone.

Built-in lines are mixed in by default; set `"custom_phrases_only": true` in the config to use only yours.
