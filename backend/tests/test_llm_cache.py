import pytest

from config.settings import MandateIQSettings

from src.llm.cached_provider import CachedLLMProvider
from src.llm.mock_client import MockLLMProvider
from src.llm.provider import get_llm_provider
from src.llm.schemas import LLMRequest


# ============================================================
# COUNTING MOCK PROVIDER
# ============================================================

class CountingMockProvider(MockLLMProvider):
    """
    Mock provider that records actual provider invocations.

    This allows tests to prove that cached requests do not invoke
    the underlying provider again.
    """

    def __init__(self):
        super().__init__()

        self.call_count = 0

    def invoke(self, request):
        self.call_count += 1

        return super().invoke(request)


# ============================================================
# TEST HELPERS
# ============================================================

def make_request(
    user_prompt: str = "Analyze evidence.",
) -> LLMRequest:
    """
    Create a deterministic LLM request for cache testing.
    """

    return LLMRequest(
        system_prompt="MandateIQ",
        user_prompt=user_prompt,
    )


# ============================================================
# BASIC CACHE BEHAVIOR
# ============================================================

def test_first_request_is_not_cached():
    underlying = CountingMockProvider()

    provider = CachedLLMProvider(
        provider=underlying,
        max_entries=10,
    )

    response = provider.invoke(
        make_request()
    )

    assert response.cached is False

    assert underlying.call_count == 1


def test_repeated_request_uses_cache():
    underlying = CountingMockProvider()

    provider = CachedLLMProvider(
        provider=underlying,
        max_entries=10,
    )

    first = provider.invoke(
        make_request()
    )

    second = provider.invoke(
        make_request()
    )

    assert first.cached is False

    assert second.cached is True

    # Only the first request should reach the underlying provider.
    assert underlying.call_count == 1


def test_different_requests_do_not_share_cache():
    underlying = CountingMockProvider()

    provider = CachedLLMProvider(
        provider=underlying,
        max_entries=10,
    )

    provider.invoke(
        make_request("Request A")
    )

    provider.invoke(
        make_request("Request B")
    )

    assert underlying.call_count == 2

    assert provider.cache_size == 2


# ============================================================
# CACHE SIZE / LRU EVICTION
# ============================================================

def test_cache_respects_max_entries():
    underlying = CountingMockProvider()

    provider = CachedLLMProvider(
        provider=underlying,
        max_entries=2,
    )

    provider.invoke(
        make_request("A")
    )

    provider.invoke(
        make_request("B")
    )

    provider.invoke(
        make_request("C")
    )

    assert provider.cache_size == 2


def test_lru_entry_is_evicted():
    underlying = CountingMockProvider()

    provider = CachedLLMProvider(
        provider=underlying,
        max_entries=2,
    )

    # Cache A and B.
    provider.invoke(
        make_request("A")
    )

    provider.invoke(
        make_request("B")
    )

    # Access A again so A becomes the most recently used entry.
    cached_a = provider.invoke(
        make_request("A")
    )

    assert cached_a.cached is True

    # Adding C should now evict B.
    provider.invoke(
        make_request("C")
    )

    # B should require another real provider invocation.
    response_b = provider.invoke(
        make_request("B")
    )

    assert response_b.cached is False

    # Real calls:
    # A = 1
    # B = 1
    # A cached = 0
    # C = 1
    # B again = 1
    assert underlying.call_count == 4


# ============================================================
# CACHE MANAGEMENT
# ============================================================

def test_clear_cache():
    underlying = CountingMockProvider()

    provider = CachedLLMProvider(
        provider=underlying,
        max_entries=10,
    )

    provider.invoke(
        make_request()
    )

    assert provider.cache_size == 1

    provider.clear_cache()

    assert provider.cache_size == 0


def test_invalid_cache_size_is_rejected():
    with pytest.raises(
        ValueError,
        match="max_entries",
    ):
        CachedLLMProvider(
            provider=MockLLMProvider(),
            max_entries=0,
        )


# ============================================================
# PROVIDER FACTORY CACHE INTEGRATION
# ============================================================

def test_factory_wraps_provider_when_cache_enabled():
    settings = MandateIQSettings(
        llm_provider="mock",
        llm_cache_enabled=True,
        llm_cache_max_entries=25,
    )

    provider = get_llm_provider(
        settings=settings
    )

    assert isinstance(
        provider,
        CachedLLMProvider,
    )

    assert provider.provider_name == "mock"

    assert provider.max_entries == 25


def test_factory_returns_raw_provider_when_cache_disabled():
    settings = MandateIQSettings(
        llm_provider="mock",
        llm_cache_enabled=False,
    )

    provider = get_llm_provider(
        settings=settings
    )

    assert isinstance(
        provider,
        MockLLMProvider,
    )

    assert not isinstance(
        provider,
        CachedLLMProvider,
    )