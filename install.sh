#!/usr/bin/env bash
# on-duty installer:  curl -fsSL https://raw.githubusercontent.com/valvesss/on-duty-ai/main/install.sh | bash
set -euo pipefail

[ "$(uname)" = "Darwin" ] || { echo "on-duty only runs on macOS."; exit 1; }
DIR="${ON_DUTY_DIR:-$HOME/on-duty-ai}"

command -v git >/dev/null || { echo "git is missing: run 'xcode-select --install' first."; exit 1; }
if ! command -v uv >/dev/null; then
  echo "→ installing uv (Python package manager)"
  if command -v brew >/dev/null; then brew install uv; else curl -LsSf https://astral.sh/uv/install.sh | sh; fi
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ -d "$DIR/.git" ]; then
  echo "→ updating $DIR"; git -C "$DIR" pull --ff-only
else
  echo "→ cloning into $DIR"; git clone --depth 1 https://github.com/valvesss/on-duty-ai "$DIR"
fi

cd "$DIR" && ./onduty install
