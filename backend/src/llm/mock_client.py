"""
MandateIQ Mock LLM Provider.

Owner: Narahari

Provides a deterministic local LLM implementation for development,
testing, and integration without making external model calls.

The mock provider follows the same interface as the Bedrock provider.
"""

from __future__ import annotations

import json
from typing import Any

from src.llm.provider import LLMProvider
from src.llm.schemas import LLMRequest, LLMResponse


class MockLLMProvider(LLMProvider):
    """
    Deterministic mock implementation of the MandateIQ LLM provider.

    Responses can either be generated from a simple default fixture or
    supplied explicitly for tests.
    """

    def __init__(
        self,
        responses: dict[str, str] | None = None,
    ) -> None:
        """
        Initialize the mock provider.

        Args:
            responses:
                Optional mapping of response-schema names to predefined
                response strings.
        """

        self._responses = responses or {}


    @property
    def provider_name(self) -> str:
        """
        Return the provider identifier.
        """

        return "mock"


    def invoke(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        """
        Execute a deterministic mock LLM request.

        No network request or external model invocation occurs.
        """

        content = self._resolve_response(request)

        return LLMResponse(
            content=content,
            provider=self.provider_name,
            model_id="mandateiq-mock-v1",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0.0,
            cached=False,
            metadata={
                "mock": True,
                "response_schema": request.response_schema,
            },
        )


    def _resolve_response(
        self,
        request: LLMRequest,
    ) -> str:
        """
        Resolve the deterministic response for a request.

        Priority:
            1. Explicit fixture matching response_schema.
            2. Generic deterministic JSON response.
        """

        if (
            request.response_schema
            and request.response_schema in self._responses
        ):
            return self._responses[request.response_schema]

        return self._default_response(request)


    def _default_response(
        self,
        request: LLMRequest,
    ) -> str:
        """
        Generate a deterministic fallback response.

        The response intentionally contains no invented financial facts.
        """

        payload: dict[str, Any] = {
            "status": "MOCK_RESPONSE",
            "message": (
                "Deterministic MandateIQ mock response. "
                "No external LLM was invoked."
            ),
            "response_schema": request.response_schema,
        }

        return json.dumps(
            payload,
            sort_keys=True,
        )