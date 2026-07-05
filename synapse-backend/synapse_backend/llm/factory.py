"""Provider factory. ``get_llm()`` returns the configured provider (cached)."""

from __future__ import annotations

import logging
from functools import lru_cache

from synapse_backend.config import settings
from synapse_backend.llm.base import LLMProvider
from synapse_backend.llm.mock_provider import MockProvider

logger = logging.getLogger(__name__)


def is_mock() -> bool:
    """True when no real model is configured (heuristic paths should be used)."""
    return settings.llm_provider.lower() == "mock"


@lru_cache
def get_llm() -> LLMProvider:
    provider = settings.llm_provider.lower()
    try:
        if provider == "anthropic":
            from synapse_backend.llm.anthropic_provider import AnthropicProvider

            return AnthropicProvider()
        if provider == "openai":
            from synapse_backend.llm.openai_provider import OpenAIProvider

            return OpenAIProvider()
    except Exception as exc:  # noqa: BLE001 - degrade gracefully to mock
        logger.warning(
            "LLM provider '%s' unavailable (%s) — falling back to mock.",
            provider,
            exc,
        )
        return MockProvider()

    if provider != "mock":
        logger.warning("Unknown LLM_PROVIDER '%s' — using mock.", provider)
    return MockProvider()
