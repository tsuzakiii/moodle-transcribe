#!/usr/bin/env bash
# Launch GUI on macOS (double-click in Finder, or drag to Dock)
cd "$(dirname "$0")/.."
exec .venv/bin/python -m moodle_transcribe.gui
