"""Claude CLI provider — uses `claude -p` so it's billed under the user's
Claude Code subscription rather than via API key.

Each call uses an isolated temp scratch directory so:
  - the prompt is *not* visible on `ps`/`tasklist` (passed via stdin)
  - concurrent calls don't delete each other's transcript files
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .. import platform_io


class ClaudeCLI:
    def __init__(self, model: str = "haiku", scratch_dir: str | None = None, **_: object):
        self.model = model
        scratch = scratch_dir or "~/.cache/moodle-transcribe/_routing_scratch"
        self.parent_scratch = Path(os.path.expanduser(scratch))
        self.parent_scratch.mkdir(parents=True, exist_ok=True)

    def complete(self, prompt: str, log) -> str:
        # Isolated subdir per call → no shared rmtree race
        call_dir = Path(tempfile.mkdtemp(prefix="call_", dir=str(self.parent_scratch)))
        try:
            r = platform_io.run(
                ["claude", "-p", "--model", self.model],
                cwd=str(call_dir), input=prompt,        # ← prompt via stdin, off the cmdline
                capture_output=True, text=True,
                encoding="utf-8", timeout=180,
            )
        finally:
            shutil.rmtree(call_dir, ignore_errors=True)
        if r.returncode != 0:
            raise RuntimeError(f"claude -p failed: {r.stderr[-300:]}")
        return (r.stdout or "").strip()
