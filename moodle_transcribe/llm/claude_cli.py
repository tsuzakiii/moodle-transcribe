"""Claude CLI provider — uses `claude -p` so it billed under the user's
Claude Code subscription rather than via API key."""
from __future__ import annotations

import os
from pathlib import Path

from .. import platform_io


class ClaudeCLI:
    def __init__(self, model: str = "haiku", scratch_dir: str | None = None, **_: object):
        self.model = model
        scratch = scratch_dir or "~/.cache/moodle-transcribe/_routing_scratch"
        self.scratch = Path(os.path.expanduser(scratch))
        self.scratch.mkdir(parents=True, exist_ok=True)

    def complete(self, prompt: str, log) -> str:
        try:
            r = platform_io.run(
                ["claude", "-p", "--model", self.model, prompt],
                cwd=str(self.scratch), capture_output=True, text=True,
                encoding="utf-8", timeout=180,
            )
        finally:
            for f in self.scratch.rglob("*.jsonl"):
                try:
                    f.unlink()
                except Exception:
                    pass
        if r.returncode != 0:
            raise RuntimeError(f"claude -p failed: {r.stderr[-300:]}")
        return (r.stdout or "").strip()
