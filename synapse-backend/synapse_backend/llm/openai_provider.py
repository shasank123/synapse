"""OpenAI GPT provider."""

from __future__ import annotations

from synapse_backend.config import settings
from synapse_backend.llm.base import LLMMessage, LLMProvider


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self) -> None:
        import openai

        if not settings.openai_api_key:
            raise ValueError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set.")
        self._client = openai.OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=max_tokens or settings.llm_max_tokens,
            temperature=(
                temperature if temperature is not None else settings.llm_temperature
            ),
        )
        return resp.choices[0].message.content or ""
