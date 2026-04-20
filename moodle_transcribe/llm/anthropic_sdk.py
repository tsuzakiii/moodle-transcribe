"""Anthropic API provider."""
from __future__ import annotations

from ..config import get_api_key


class AnthropicLLM:
    def __init__(self, model: str = "claude-haiku-4-5", **_: object):
        from anthropic import Anthropic
        key = get_api_key("anthropic")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self.client = Anthropic(api_key=key)
        self.model = model

    def complete(self, prompt: str, log) -> str:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")
