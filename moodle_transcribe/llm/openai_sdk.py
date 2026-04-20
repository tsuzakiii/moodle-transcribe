"""OpenAI API provider (gpt-5-mini, gpt-4o-mini, etc.)."""
from __future__ import annotations

from ..config import get_api_key


class OpenAILLM:
    def __init__(self, model: str = "gpt-5-mini", **_: object):
        from openai import OpenAI
        key = get_api_key("openai")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self.client = OpenAI(api_key=key)
        self.model = model

    def complete(self, prompt: str, log) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=1024,
        )
        return resp.choices[0].message.content or ""
