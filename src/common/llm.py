"""Anthropic LLM client wrapper with cost tracking."""

from __future__ import annotations

import anthropic
from dotenv import load_dotenv

from .logger import get_logger

load_dotenv()

LOGGER = get_logger(__name__)

# Model IDs
HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-20250514"

# Pricing per million tokens (USD)
_PRICING = {
    HAIKU: {"input": 0.80, "output": 4.00},
    SONNET: {"input": 3.00, "output": 15.00},
}


class LLMClient:
    """Wrapper around Anthropic API with token counting and cost tracking."""

    def __init__(self):
        self.client = anthropic.Anthropic()
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self._calls_by_model: dict[str, dict[str, int]] = {}

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        model: str = HAIKU,
        max_tokens: int = 1024,
    ) -> str:
        """Send a prompt and return the text response."""
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        response = self.client.messages.create(**kwargs)

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens

        if model not in self._calls_by_model:
            self._calls_by_model[model] = {"input": 0, "output": 0, "calls": 0}
        self._calls_by_model[model]["input"] += input_tokens
        self._calls_by_model[model]["output"] += output_tokens
        self._calls_by_model[model]["calls"] += 1

        LOGGER.debug(
            "LLM call: model=%s input=%d output=%d", model, input_tokens, output_tokens
        )

        text_blocks = [b.text for b in response.content if b.type == "text"]
        return "\n".join(text_blocks)

    def estimate_session_cost(self) -> float:
        """Estimate the cost of all API calls in this session."""
        total = 0.0
        for model, usage in self._calls_by_model.items():
            pricing = _PRICING.get(model, {"input": 3.0, "output": 15.0})
            total += (usage["input"] / 1_000_000) * pricing["input"]
            total += (usage["output"] / 1_000_000) * pricing["output"]
        return total

    def get_usage_summary(self) -> dict:
        """Return a summary of token usage for state DB storage."""
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_cost_usd": round(self.estimate_session_cost(), 4),
            "calls_by_model": dict(self._calls_by_model),
        }
