"""
MandateIQ Runtime Configuration.

Owner: Narahari

Centralizes runtime configuration used by MandateIQ's orchestration
and LLM infrastructure.

Configuration values can be supplied through environment variables.
No AWS credentials or secrets are stored here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


# ============================================================
# ENVIRONMENT HELPERS
# ============================================================

def _get_bool(
    name: str,
    default: bool,
) -> bool:
    """
    Read a boolean environment variable.

    Accepted true values:
        1, true, yes, on

    Accepted false values:
        0, false, no, off
    """

    value = os.getenv(name)

    if value is None:
        return default

    normalized = value.strip().lower()

    if normalized in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True

    if normalized in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False

    raise ValueError(
        f"{name} must be a valid boolean value."
    )


def _get_int(
    name: str,
    default: int,
) -> int:
    """
    Read an integer environment variable.
    """

    value = os.getenv(name)

    if value is None:
        return default

    try:
        return int(value)

    except ValueError as exc:
        raise ValueError(
            f"{name} must be an integer."
        ) from exc


def _get_float(
    name: str,
    default: float,
) -> float:
    """
    Read a floating-point environment variable.
    """

    value = os.getenv(name)

    if value is None:
        return default

    try:
        return float(value)

    except ValueError as exc:
        raise ValueError(
            f"{name} must be numeric."
        ) from exc


# ============================================================
# MANDATEIQ SETTINGS
# ============================================================

@dataclass(frozen=True)
class MandateIQSettings:
    """
    Validated runtime configuration for Narahari-owned components.
    """

    # --------------------------------------------------------
    # LLM provider
    # --------------------------------------------------------

    llm_provider: str = "mock"

    bedrock_model_id: str = ""

    groq_model: str = "openai/gpt-oss-120b"

    aws_region: str = "us-east-1"

    llm_max_tokens: int = 1500

    llm_temperature: float = 0.0

    llm_timeout_seconds: float = 30.0

    # --------------------------------------------------------
    # Routing
    # --------------------------------------------------------

    quality_threshold: float = 0.80

    confidence_threshold: float = 0.70

    trust_threshold: float = 70.0

    max_retries: int = 1

    max_workflow_steps: int = 25

    # --------------------------------------------------------
    # LLM response cache
    # --------------------------------------------------------

    llm_cache_enabled: bool = True

    llm_cache_max_entries: int = 128

    # --------------------------------------------------------
    # Validation
    # --------------------------------------------------------

    def __post_init__(self) -> None:
        """
        Validate configuration values immediately.
        """

        provider = self.llm_provider.strip().lower()

        if provider not in {
            "mock",
            "bedrock",
            "groq",
        }:
            raise ValueError(
                "llm_provider must be one of "
                "'mock', 'bedrock' or 'groq'."
            )

        object.__setattr__(
            self,
            "llm_provider",
            provider,
        )

        if not 0.0 <= self.quality_threshold <= 1.0:
            raise ValueError(
                "quality_threshold must be between "
                "0.0 and 1.0."
            )

        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError(
                "confidence_threshold must be between "
                "0.0 and 1.0."
            )

        if not 0.0 <= self.trust_threshold <= 100.0:
            raise ValueError(
                "trust_threshold must be between "
                "0 and 100."
            )

        if self.max_retries < 0:
            raise ValueError(
                "max_retries cannot be negative."
            )

        if self.max_workflow_steps <= 0:
            raise ValueError(
                "max_workflow_steps must be greater "
                "than zero."
            )

        if not 0.0 <= self.llm_temperature <= 1.0:
            raise ValueError(
                "llm_temperature must be between "
                "0.0 and 1.0."
            )

        if self.llm_max_tokens <= 0:
            raise ValueError(
                "llm_max_tokens must be greater "
                "than zero."
            )

        if self.llm_timeout_seconds <= 0:
            raise ValueError(
                "llm_timeout_seconds must be greater "
                "than zero."
            )

        if self.llm_cache_max_entries <= 0:
            raise ValueError(
                "llm_cache_max_entries must be greater "
                "than zero."
            )


# ============================================================
# SETTINGS LOADER
# ============================================================

def load_settings() -> MandateIQSettings:
    """
    Load MandateIQ configuration from environment variables.

    Environment variables override safe local defaults.
    """

    return MandateIQSettings(
        # LLM
        llm_provider=os.getenv(
            "LLM_PROVIDER",
            "mock",
        ),
        bedrock_model_id=os.getenv(
            "BEDROCK_MODEL_ID",
            "",
        ),
        groq_model=(
            os.getenv("GROQ_MODEL", "").strip()
            or "openai/gpt-oss-120b"
        ),
        aws_region=(
            os.getenv("AWS_REGION")
            or os.getenv(
                "AWS_DEFAULT_REGION",
                "us-east-1",
            )
        ),
        llm_max_tokens=_get_int(
            "LLM_MAX_TOKENS",
            1500,
        ),
        llm_temperature=_get_float(
            "LLM_TEMPERATURE",
            0.0,
        ),
        llm_timeout_seconds=_get_float(
            "LLM_TIMEOUT_SECONDS",
            30.0,
        ),

        # Routing
        quality_threshold=_get_float(
            "QUALITY_THRESHOLD",
            0.80,
        ),
        confidence_threshold=_get_float(
            "CONFIDENCE_THRESHOLD",
            0.70,
        ),
        trust_threshold=_get_float(
            "TRUST_THRESHOLD",
            70.0,
        ),
        max_retries=_get_int(
            "MAX_RETRIES",
            1,
        ),
        max_workflow_steps=_get_int(
            "MAX_WORKFLOW_STEPS",
            25,
        ),

        # Cache
        llm_cache_enabled=_get_bool(
            "LLM_CACHE_ENABLED",
            True,
        ),
        llm_cache_max_entries=_get_int(
            "LLM_CACHE_MAX_ENTRIES",
            128,
        ),
    )