"""LLM providers used for routing decisions."""
from __future__ import annotations

from typing import Callable, Protocol

Logger = Callable[[str], None]


class LLM(Protocol):
    def complete(self, prompt: str, log: Logger) -> str: ...


def get(provider: str, settings: dict) -> LLM:
    if provider == "claude_cli":
        from .claude_cli import ClaudeCLI
        return ClaudeCLI(**settings)
    if provider == "anthropic":
        from .anthropic_sdk import AnthropicLLM
        return AnthropicLLM(**settings)
    if provider == "openai":
        from .openai_sdk import OpenAILLM
        return OpenAILLM(**settings)
    raise ValueError(f"Unknown LLM provider: {provider}")
