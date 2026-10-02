"""
MandateIQ Cached LLM Provider.

Owner: Narahari

Provides a bounded in-memory cache around any MandateIQ LLMProvider.

The cache reduces repeated model invocations for identical requests.
It is provider-independent and can wrap either Mock or Bedrock.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict

from src.llm.provider import LLMProvider
from src.llm.schemas import LLMRequest, LLMResponse


class CachedLLMProvider(LLMProvider):
    """
    Bounded in-memory cache wrapper for an LLM provider.
    """

    def __init__(
        self,
        provider: LLMProvider,
        max_entries: int = 128,
    ) -> None:

        if max_entries <= 0:
            raise ValueError(
                "max_entries must be greater than zero."
            )

        self._provider = provider
        self.max_entries = max_entries

        self._cache: OrderedDict[
            str,
            LLMResponse,
        ] = OrderedDict()


    @property
    def provider_name(self) -> str:
        """
        Preserve the wrapped provider identifier.
        """

        return self._provider.provider_name


    @property
    def cache_size(self) -> int:
        """
        Return the current number of cached responses.
        """

        return len(self._cache)


    def clear_cache(self) -> None:
        """
        Remove all cached responses.
        """

        self._cache.clear()


    def invoke(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        """
        Return a cached response when the same request has already
        been processed.

        Otherwise invoke the wrapped provider and cache the result.
        """

        key = self._cache_key(request)

        if key in self._cache:

            cached_response = self._cache.pop(key)

            # Reinsert so the entry becomes most recently used.
            self._cache[key] = cached_response

            response = cached_response.model_copy(deep=True)

            response.cached = True

            return response

        response = self._provider.invoke(request)

        stored_response = response.model_copy(deep=True)

        stored_response.cached = False

        self._cache[key] = stored_response

        self._evict_if_needed()

        return response


    def _evict_if_needed(self) -> None:
        """
        Enforce the configured maximum cache size using LRU eviction.
        """

        while len(self._cache) > self.max_entries:
            self._cache.popitem(
                last=False
            )


    @staticmethod
    def _cache_key(
        request: LLMRequest,
    ) -> str:
        """
        Build a stable SHA-256 cache key from all request fields
        that can affect model output.
        """

        payload = request.model_dump(
            mode="json"
        )

        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest()