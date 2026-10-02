"""
MandateIQ LLM Provider Schemas.

Owner: Narahari

This module defines the provider-level request and response contracts
shared by MandateIQ's mock and Amazon Bedrock LLM providers.

Agent-specific schemas belong to their respective modules. These
schemas only describe communication with the LLM provider layer.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


# ============================================================
# LLM REQUEST
# ============================================================

class LLMRequest(BaseModel):
    """
    Provider-independent request sent to an LLM backend.
    """

    system_prompt: str

    user_prompt: str

    response_schema: str | None = None

    temperature: float = 0.0

    max_tokens: int = 1500

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("system_prompt", "user_prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        """
        Prevent empty prompts from reaching an LLM provider.
        """

        value = value.strip()

        if not value:
            raise ValueError("LLM prompts cannot be empty")

        return value

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, value: float) -> float:
        """
        Keep temperature within a provider-safe range.
        """

        if not 0.0 <= value <= 1.0:
            raise ValueError(
                "temperature must be between 0.0 and 1.0"
            )

        return value

    @field_validator("max_tokens")
    @classmethod
    def validate_max_tokens(cls, value: int) -> int:
        """
        Prevent invalid token limits.
        """

        if value <= 0:
            raise ValueError(
                "max_tokens must be greater than zero"
            )

        return value


# ============================================================
# LLM RESPONSE
# ============================================================

class LLMResponse(BaseModel):
    """
    Provider-independent response returned by an LLM backend.
    """

    content: str

    provider: str

    model_id: str | None = None

    input_tokens: int | None = None

    output_tokens: int | None = None

    latency_ms: float | None = None

    cached: bool = False

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        """
        Reject empty model responses.
        """

        value = value.strip()

        if not value:
            raise ValueError(
                "LLM response content cannot be empty"
            )

        return value

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        """
        Require the provider to identify itself.
        """

        value = value.strip().lower()

        if not value:
            raise ValueError(
                "provider cannot be empty"
            )

        return value

    @field_validator(
        "input_tokens",
        "output_tokens",
    )
    @classmethod
    def validate_token_counts(
        cls,
        value: int | None,
    ) -> int | None:
        """
        Token counts cannot be negative.
        """

        if value is not None and value < 0:
            raise ValueError(
                "token counts cannot be negative"
            )

        return value

    @field_validator("latency_ms")
    @classmethod
    def validate_latency(
        cls,
        value: float | None,
    ) -> float | None:
        """
        Latency cannot be negative.
        """

        if value is not None and value < 0:
            raise ValueError(
                "latency_ms cannot be negative"
            )

        return value


# ============================================================
# PROVIDER ERROR
# ============================================================

class LLMProviderError(BaseModel):
    """
    Structured description of an LLM provider failure.

    This allows orchestration code to surface failures clearly
    instead of silently generating fake production results.
    """

    provider: str

    error_type: str

    message: str

    retryable: bool = False

    metadata: dict[str, Any] = Field(default_factory=dict)