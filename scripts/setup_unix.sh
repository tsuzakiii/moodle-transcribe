#!/usr/bin/env bash
# Mac / Linux setup
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
    echo "Creating venv (Python 3.12+ recommended)…"
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip

EXTRAS="remote"
if [[ "$(uname -s)" == "Linux" ]] && command -v nvidia-smi >/dev/null 2>&1; then
    EXTRAS="gpu,remote"
fi
pip install -e ".[${EXTRAS}]"
python -m playwright install chromium

if [[ "$(uname -s)" == "Darwin" ]]; then
    CFG_DIR="$HOME/Library/Application Support/moodle-transcribe"
else
    CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/moodle-transcribe"
fi
mkdir -p "$CFG_DIR"
[[ -f "$CFG_DIR/config.toml" ]] || {
    cp config.example.toml "$CFG_DIR/config.toml"
    echo "Wrote default config to $CFG_DIR/config.toml"
}

cat <<EOF

Done. Next:
  1. Place moodle_cookies.txt at: $CFG_DIR
  2. (Optional) edit:           $CFG_DIR/config.toml
  3. Set API keys:              export OPENAI_API_KEY=...
  4. Launch:                    .venv/bin/python -m moodle_transcribe.gui
EOF
