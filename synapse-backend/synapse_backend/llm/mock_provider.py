"""Mock LLM provider — lets the whole pipeline run with no API key.

It does NOT try to imitate a real model. Instead, the endpoint detector and the
generator agent contain deterministic heuristics that are used whenever the
configured provider is ``mock`` (see ``settings.llm_provider``). This provider
is therefore only a safe stub: if some code path calls it directly it returns a
clearly-labelled placeholder rather than throwing.
"""

from __future__ import annotations

from synapse_backend.llm.base import LLMMessage, LLMProvider


class MockProvider(LLMProvider):
    name = "mock"

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        return (
            "[mock-llm] No LLM configured. This deterministic stub echoes intent "
            "so the pipeline can run offline.\n"
            f"[mock-llm] prompt-preview: {last_user[:160]}"
        )
