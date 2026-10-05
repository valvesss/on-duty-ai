"""Generate a personalized phrase pack with Claude → ~/.on-duty/phrases.json

    uv run --extra ai generate_phrases.py [--style "drill sergeant, loves football puns"]

Needs ANTHROPIC_API_KEY (or an `ant auth login` profile). Uses your name and language from
~/.on-duty/config.json. Optional: on-duty works fine with the built-in packs.
"""

import argparse
import importlib
import json
import sys

import anthropic
from pydantic import BaseModel, Field

import config

MODEL = "claude-opus-5-5"
LANG_NAMES = {"pt_BR": "Brazilian Portuguese (casual, Brazilian slang welcome)", "en_US": "American English"}


class Level(BaseModel):
    lines: list[list[str]] = Field(description="Each item is 1-4 short sentences spoken in sequence (a combo).")


class Pack(BaseModel):
    levels: list[Level] = Field(description="Exactly 5 levels: gentle, sarcastic, firm, drama, chaos.")
    back_quick: list[str] = Field(description="Said when the user returns after < 1 minute.")
    back_medium: list[str] = Field(description="Said when the user returns after 1-5 minutes.")
    back_long: list[str] = Field(description="Said when the user returns after > 5 minutes.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--style", default="", help="extra flavor: persona, humor, interests, things to mention")
    p.add_argument("--per-level", type=int, default=15)
    a = p.parse_args()

    cfg = config.load()
    builtin = importlib.import_module(f"phrases.{cfg['lang']}")
    examples = "\n".join(f"Level {i + 1}: {json.dumps(lv[:4], ensure_ascii=False)}" for i, lv in enumerate(builtin.LEVELS))
    name = cfg["name"] or "(no name given — don't use a name)"

    prompt = f"""You write voice lines for on-duty, a local macOS app that watches the user's webcam and
speaks out loud (macOS `say` text-to-speech) when they stop working to doomscroll on their phone.
The app keeps talking, escalating one level every 3 lines, until they put the phone down and touch
the keyboard again. The user opted in and wants it funny and increasingly insistent.

User's name: {name}
Language: {LANG_NAMES.get(cfg['lang'], cfg['lang'])}
Extra style requested by the user: {a.style or "none — use your best comedic judgment"}

Write {a.per_level} items per level, 5 levels: 1 gentle, 2 sarcastic, 3 firm, 4 dramatic, 5 absurd chaos.
- Each item is a list of 1-4 short sentences; multi-sentence items are spoken with a pause between them
  (use that for comedic timing: setups, countdowns, fake news bulletins, dramatic pauses).
- Use the user's name in about a third of the items, written literally (not as a placeholder).
- You may use these placeholders exactly as written: {{time}} (e.g. "3 minutes" on the phone) and {{n}} (nag count).
- Written to be spoken: no emoji, no hashtags, no parentheses, no markdown. Keep each sentence under ~15 words.
- Do not assume the user's gender; keep wording gender-neutral.
- Funny, never cruel: no insults about appearance, body, intelligence, or anything sensitive.
- Avoid repeating the built-in lines; here are a few for tone reference only:
{examples}

Also write 5 lines each for returning after <1 min, 1-5 min, and >5 min (back_quick/back_medium/back_long)."""

    client = anthropic.Anthropic()
    print(f"Asking {MODEL} for a personalized pack…", file=sys.stderr)
    try:
        resp = client.messages.parse(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": prompt}],
            output_format=Pack,
        )
    except anthropic.AuthenticationError:
        sys.exit("No valid Anthropic credentials. Set ANTHROPIC_API_KEY (https://console.anthropic.com).")
    except anthropic.APIStatusError as e:
        sys.exit(f"Anthropic API error {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        sys.exit("Couldn't reach the Anthropic API. Check your connection.")
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        sys.exit(f"Generation stopped ({resp.stop_reason}). Try a different --style.")

    pack = resp.parsed_output
    if len(pack.levels) != 5:
        sys.exit(f"Expected 5 levels, got {len(pack.levels)}. Try again.")
    out = {
        "generated_by": MODEL,
        "name": cfg["name"],
        "lang": cfg["lang"],
        "style": a.style,
        "levels": [[ln[0] if len(ln) == 1 else ln for ln in lv.lines if ln] for lv in pack.levels],
        "back": {"quick": pack.back_quick, "medium": pack.back_medium, "long": pack.back_long},
    }
    config.CUSTOM_PHRASES.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    total = sum(len(lv) for lv in out["levels"])
    print(f"Saved {total} lines to {config.CUSTOM_PHRASES}. Restart to use them: ./onduty restart")
    for lv in out["levels"]:
        print("  ·", lv[0] if isinstance(lv[0], str) else " / ".join(lv[0]))


if __name__ == "__main__":
    main()
