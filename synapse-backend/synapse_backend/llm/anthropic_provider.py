"""Anthropic Claude provider."""

from __future__ import annotations

from synapse_backend.config import settings
from synapse_backend.llm.base import LLMMessage, LLMProvider


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self) -> None:
        import anthropic

        if not settings.anthropic_api_key:
            raise ValueError(
                "LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set."
            )
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        # Anthropic takes the system prompt separately from the turn messages.
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        turns = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        resp = self._client.messages.create(
            model=self._model,
            system=system or None,
            messages=turns,
            max_tokens=max_tokens or settings.llm_max_tokens,
            temperature=(
                temperature if temperature is not None else settings.llm_temperature
            ),
        )
        return "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )
