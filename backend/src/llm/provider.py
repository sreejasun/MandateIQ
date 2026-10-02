"""
MandateIQ LLM Provider Interface.

Owner: Narahari

This module defines the common interface used by MandateIQ to interact
with LLM backends.

The rest of the application should depend on this interface rather than
directly depending on Amazon Bedrock, Groq, or the mock implementation.

Provider selection and runtime configuration are supplied through the
centralized MandateIQ settings layer.

Optional response caching is applied as a provider-independent wrapper
so the same caching behavior can be used with both Mock and Bedrock.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from config.settings import MandateIQSettings, load_settings
from src.llm.schemas import LLMRequest, LLMResponse


# ============================================================
# SUPPORTED PROVIDERS
# ============================================================

SUPPORTED_PROVIDERS = {
    "mock",
    "bedrock",
    "groq",
}


# ============================================================
# BASE PROVIDER
# ============================================================

class LLMProvider(ABC):
    """
    Abstract interface implemented by every MandateIQ LLM provider.

    Agent code should communicate with an LLM through this interface
    instead of importing a provider-specific client directly.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Return the provider identifier.
        """

        raise NotImplementedError

    @abstractmethod
    def invoke(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        """
        Execute one LLM request and return a validated response.
        """

        raise NotImplementedError


# ============================================================
# PROVIDER FACTORY
# ============================================================

def get_llm_provider(
    provider_name: str | None = None,
    settings: MandateIQSettings | None = None,
) -> LLMProvider:
    """
    Create the configured MandateIQ LLM provider.

    Configuration precedence:

        1. Explicit provider_name argument
        2. MandateIQSettings.llm_provider
        3. Safe mock default supplied by MandateIQSettings

    Provider-specific configuration such as Bedrock model ID,
    AWS region, and timeout is supplied through centralized settings.

    When LLM caching is enabled, the selected provider is wrapped in
    CachedLLMProvider.

    Imports are intentionally local so mock-mode development does not
    initialize boto3 or require an active AWS session.
    """

    settings = (
        settings
        or load_settings()
    )

    selected_provider = (
        provider_name
        or settings.llm_provider
    )

    selected_provider = (
        selected_provider
        .strip()
        .lower()
    )

    # --------------------------------------------------------
    # Validate provider selection
    # --------------------------------------------------------

    if selected_provider not in SUPPORTED_PROVIDERS:

        supported = ", ".join(
            sorted(
                SUPPORTED_PROVIDERS
            )
        )

        raise ValueError(
            f"Unsupported LLM provider "
            f"'{selected_provider}'. "
            f"Supported providers: {supported}"
        )

    # --------------------------------------------------------
    # Build raw provider
    # --------------------------------------------------------

    if selected_provider == "mock":

        from src.llm.mock_client import MockLLMProvider

        provider: LLMProvider = MockLLMProvider()

    elif selected_provider == "bedrock":

        from src.llm.bedrock_client import BedrockLLMProvider

        provider = BedrockLLMProvider(
            model_id=settings.bedrock_model_id,
            region_name=settings.aws_region,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    elif selected_provider == "groq":

        from src.llm.groq_client import GroqLLMProvider

        provider = GroqLLMProvider(
            model_id=settings.groq_model or None,
        )

    else:
        # Defensive fallback.
        # Provider validation above should make this unreachable.
        raise RuntimeError(
            "Unable to initialize the configured "
            "LLM provider."
        )

    # --------------------------------------------------------
    # Optional response cache
    # --------------------------------------------------------

    if settings.llm_cache_enabled:

        from src.llm.cached_provider import CachedLLMProvider

        return CachedLLMProvider(
            provider=provider,
            max_entries=settings.llm_cache_max_entries,
        )

    # --------------------------------------------------------
    # Raw provider when caching is disabled
    # --------------------------------------------------------

    return provider