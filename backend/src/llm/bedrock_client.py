"""
MandateIQ Amazon Bedrock LLM Provider.

Owner: Narahari

Implements the MandateIQ LLMProvider interface using Amazon Bedrock
Runtime.

The provider uses Bedrock's Converse API so MandateIQ's agent code
does not depend on provider-specific model request formats.

Runtime configuration such as model ID, AWS region, and network
timeout can be supplied through centralized MandateIQ settings.

The provider also handles model-specific Converse compatibility.
For example, Claude Sonnet 5 and Claude Opus 5 do not accept the
legacy temperature parameter through the challenge environment.
"""

from __future__ import annotations

import os
import time
from typing import Any

from src.llm.provider import LLMProvider
from src.llm.schemas import LLMRequest, LLMResponse


# ============================================================
# BEDROCK CONFIGURATION
# ============================================================

DEFAULT_AWS_REGION = "us-east-1"

DEFAULT_TIMEOUT_SECONDS = 30.0


# ============================================================
# BEDROCK PROVIDER
# ============================================================

class BedrockLLMProvider(LLMProvider):
    """
    Amazon Bedrock implementation of the MandateIQ LLM provider.

    The boto3 client is created lazily so importing this module does
    not require an active AWS session.

    A preconstructed client may be injected for unit tests so tests
    never need to make real AWS requests.
    """

    def __init__(
        self,
        model_id: str | None = None,
        region_name: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: Any | None = None,
    ) -> None:
        """
        Initialize the Bedrock provider.

        Args:
            model_id:
                Bedrock model/inference-profile identifier.
                Falls back to BEDROCK_MODEL_ID.

            region_name:
                AWS region used for Bedrock Runtime.
                Falls back to AWS_REGION, AWS_DEFAULT_REGION,
                and finally us-east-1.

            timeout_seconds:
                Network connect/read timeout used when creating
                the Bedrock Runtime client.

            client:
                Optional preconstructed Bedrock Runtime client.
                Primarily used for automated testing.
        """

        self.model_id = (
            model_id
            or os.getenv("BEDROCK_MODEL_ID")
            or ""
        )

        self.region_name = (
            region_name
            or os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or DEFAULT_AWS_REGION
        )

        self.timeout_seconds = timeout_seconds

        if self.timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be greater than zero."
            )

        self._client = client


    # ========================================================
    # PROVIDER IDENTITY
    # ========================================================

    @property
    def provider_name(self) -> str:
        """
        Return the provider identifier.
        """

        return "bedrock"


    # ========================================================
    # CLIENT INITIALIZATION
    # ========================================================

    def _get_client(self) -> Any:
        """
        Lazily create the Bedrock Runtime boto3 client.

        boto3 and botocore are imported only when a real Bedrock
        client is needed. Mock-mode development therefore remains
        independent from AWS initialization.
        """

        if self._client is not None:
            return self._client

        try:
            import boto3
            from botocore.config import Config

        except ImportError as exc:
            raise RuntimeError(
                "boto3 and botocore are required when "
                "LLM_PROVIDER=bedrock."
            ) from exc

        client_config = Config(
            connect_timeout=self.timeout_seconds,
            read_timeout=self.timeout_seconds,
            retries={
                "max_attempts": 2,
                "mode": "standard",
            },
        )

        self._client = boto3.client(
            "bedrock-runtime",
            region_name=self.region_name,
            config=client_config,
        )

        return self._client


    # ========================================================
    # CONFIGURATION VALIDATION
    # ========================================================

    def _validate_configuration(self) -> None:
        """
        Ensure the provider has the configuration required to invoke
        Amazon Bedrock.
        """

        if not self.model_id:
            raise ValueError(
                "BEDROCK_MODEL_ID is required when using the "
                "Bedrock LLM provider."
            )


    # ========================================================
    # MODEL-SPECIFIC INFERENCE CONFIGURATION
    # ========================================================

    def _build_inference_config(
        self,
        request: LLMRequest,
    ) -> dict[str, Any]:
        """
        Build a Bedrock Converse inference configuration compatible
        with the selected model.

        Claude Sonnet 5 and Claude Opus 5 reject the legacy
        temperature parameter in the challenge Bedrock environment.

        Other models continue to receive temperature so the common
        LLMRequest contract remains provider-independent.
        """

        inference_config: dict[str, Any] = {
            "maxTokens": request.max_tokens,
        }

        model_id = self.model_id.lower()

        temperature_deprecated_models = (
            "claude-sonnet-5",
            "claude-opus-5",
        )

        temperature_is_deprecated = any(
            model_name in model_id
            for model_name in temperature_deprecated_models
        )

        if not temperature_is_deprecated:
            inference_config["temperature"] = (
                request.temperature
            )

        return inference_config


    # ========================================================
    # MODEL INVOCATION
    # ========================================================

    def invoke(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        """
        Invoke Amazon Bedrock using the Converse API.

        Raises a clear RuntimeError when the Bedrock request fails.

        The provider never silently substitutes a fake production
        response when Bedrock fails.
        """

        self._validate_configuration()

        client = self._get_client()

        started = time.perf_counter()

        try:
            response = client.converse(
                modelId=self.model_id,
                system=[
                    {
                        "text": request.system_prompt,
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "text": request.user_prompt,
                            }
                        ],
                    }
                ],
                inferenceConfig=self._build_inference_config(
                    request
                ),
            )

        except Exception as exc:
            raise RuntimeError(
                "Amazon Bedrock invocation failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        latency_ms = (
            time.perf_counter() - started
        ) * 1000.0

        content = self._extract_text(
            response
        )

        usage = response.get(
            "usage",
            {},
        )

        return LLMResponse(
            content=content,
            provider=self.provider_name,
            model_id=self.model_id,
            input_tokens=usage.get(
                "inputTokens"
            ),
            output_tokens=usage.get(
                "outputTokens"
            ),
            latency_ms=latency_ms,
            cached=False,
            metadata={
                "region": self.region_name,
                "timeout_seconds": self.timeout_seconds,
                "response_schema": request.response_schema,
                "stop_reason": response.get(
                    "stopReason"
                ),
                "request_metadata": request.metadata,
            },
        )


    # ========================================================
    # RESPONSE EXTRACTION
    # ========================================================

    @staticmethod
    def _extract_text(
        response: dict[str, Any],
    ) -> str:
        """
        Extract text from a Bedrock Converse response.

        Raises RuntimeError if Bedrock returns an unexpected
        structure or no usable text.
        """

        try:
            content_blocks = (
                response["output"]["message"]["content"]
            )

        except (
            KeyError,
            TypeError,
        ) as exc:
            raise RuntimeError(
                "Amazon Bedrock returned an unexpected "
                "response structure."
            ) from exc

        text_parts: list[str] = []

        for block in content_blocks:

            if not isinstance(
                block,
                dict,
            ):
                continue

            text = block.get(
                "text"
            )

            if (
                isinstance(text, str)
                and text.strip()
            ):
                text_parts.append(
                    text.strip()
                )

        if not text_parts:
            raise RuntimeError(
                "Amazon Bedrock returned no text content."
            )

        return "\n".join(
            text_parts
        )