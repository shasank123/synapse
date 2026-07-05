"""LLM provider interface.

Agents talk to the model only through this interface, so swapping mock ->
Anthropic -> OpenAI is a one-line config change. Two calls are provided:

* ``complete`` — free-form text completion.
* ``complete_json`` — completion constrained to return a JSON object; the
  provider is responsible for coaxing valid JSON and this base class parses +
  repairs it.
"""

from __future__ import annotations

import abc
import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


class LLMProvider(abc.ABC):
    """Abstract base for all providers."""

    name: str = "base"

    @abc.abstractmethod
    def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Return the model's text completion for a message list."""

    def complete_json(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Any:
        """Complete and parse a JSON object from the response.

        Appends a JSON-only instruction, then extracts the first JSON object/array
        from the reply and parses it. Raises ValueError if nothing parses.
        """
        json_hint = LLMMessage(
            role="system",
            content=(
                "You must respond with a single valid JSON value and nothing "
                "else — no prose, no markdown fences."
            ),
        )
        raw = self.complete(
            [json_hint, *messages], max_tokens=max_tokens, temperature=temperature
        )
        return self._parse_json(raw)

    @staticmethod
    def _parse_json(raw: str) -> Any:
        raw = raw.strip()
        # Strip ```json fences if present.
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
        if fence:
            raw = fence.group(1).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Fallback: grab the first {...} or [...] block.
        match = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError as exc:
                raise ValueError(f"LLM returned unparseable JSON: {exc}") from exc
        raise ValueError("LLM response contained no JSON")
