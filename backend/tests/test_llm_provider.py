import json

import pytest
from pydantic import ValidationError

from config.settings import MandateIQSettings

from src.llm.cached_provider import CachedLLMProvider
from src.llm.mock_client import MockLLMProvider
from src.llm.provider import get_llm_provider
from src.llm.schemas import LLMRequest, LLMResponse


# ============================================================
# REQUEST SCHEMA
# ============================================================

def test_llm_request_defaults():
    request = LLMRequest(
        system_prompt="MandateIQ system",
        user_prompt="Analyze verified evidence.",
    )

    assert request.temperature == 0.0
    assert request.max_tokens == 1500
    assert request.response_schema is None
    assert request.metadata == {}


def test_empty_prompt_is_rejected():
    with pytest.raises(ValidationError):
        LLMRequest(
            system_prompt="",
            user_prompt="Analyze evidence.",
        )


def test_invalid_temperature_is_rejected():
    with pytest.raises(ValidationError):
        LLMRequest(
            system_prompt="MandateIQ",
            user_prompt="Analyze evidence.",
            temperature=1.5,
        )


def test_invalid_max_tokens_is_rejected():
    with pytest.raises(ValidationError):
        LLMRequest(
            system_prompt="MandateIQ",
            user_prompt="Analyze evidence.",
            max_tokens=0,
        )


# ============================================================
# RESPONSE SCHEMA
# ============================================================

def test_llm_response_validation():
    response = LLMResponse(
        content="Valid response",
        provider="MOCK",
        model_id="test-model",
        input_tokens=10,
        output_tokens=5,
        latency_ms=1.5,
    )

    assert response.provider == "mock"
    assert response.content == "Valid response"


def test_negative_token_count_is_rejected():
    with pytest.raises(ValidationError):
        LLMResponse(
            content="Response",
            provider="mock",
            input_tokens=-1,
        )


# ============================================================
# RAW MOCK PROVIDER
# ============================================================

def test_mock_provider_name():
    provider = MockLLMProvider()

    assert provider.provider_name == "mock"


def test_mock_provider_returns_valid_response():
    provider = MockLLMProvider()

    request = LLMRequest(
        system_prompt="MandateIQ system",
        user_prompt="Analyze evidence.",
    )

    response = provider.invoke(request)

    assert isinstance(
        response,
        LLMResponse,
    )

    assert response.provider == "mock"

    assert (
        response.model_id
        == "mandateiq-mock-v1"
    )

    assert response.metadata["mock"] is True

    assert response.cached is False

    payload = json.loads(
        response.content
    )

    assert payload["status"] == "MOCK_RESPONSE"


def test_mock_provider_uses_schema_fixture():
    provider = MockLLMProvider(
        responses={
            "ProponentResult": (
                '{"position":"SUPPORT",'
                '"confidence":0.90}'
            )
        }
    )

    request = LLMRequest(
        system_prompt="MandateIQ system",
        user_prompt="Analyze evidence.",
        response_schema="ProponentResult",
    )

    response = provider.invoke(request)

    assert response.content == (
        '{"position":"SUPPORT",'
        '"confidence":0.90}'
    )


# ============================================================
# PROVIDER FACTORY - CACHE ENABLED
# ============================================================

def test_provider_factory_wraps_mock_when_cache_enabled():
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


def test_provider_factory_defaults_to_cached_mock(
    monkeypatch,
):
    monkeypatch.delenv(
        "LLM_PROVIDER",
        raising=False,
    )

    monkeypatch.delenv(
        "LLM_CACHE_ENABLED",
        raising=False,
    )

    provider = get_llm_provider()

    # Default MandateIQ configuration uses:
    #   LLM_PROVIDER=mock
    #   LLM_CACHE_ENABLED=true
    assert isinstance(
        provider,
        CachedLLMProvider,
    )

    assert provider.provider_name == "mock"


def test_provider_factory_reads_environment(
    monkeypatch,
):
    monkeypatch.setenv(
        "LLM_PROVIDER",
        "mock",
    )

    monkeypatch.setenv(
        "LLM_CACHE_ENABLED",
        "true",
    )

    provider = get_llm_provider()

    assert isinstance(
        provider,
        CachedLLMProvider,
    )

    assert provider.provider_name == "mock"


# ============================================================
# PROVIDER FACTORY - CACHE DISABLED
# ============================================================

def test_provider_factory_returns_raw_mock_when_cache_disabled():
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


def test_explicit_provider_name_overrides_settings():
    settings = MandateIQSettings(
        llm_provider="bedrock",
        bedrock_model_id="test-model",
        llm_cache_enabled=False,
    )

    provider = get_llm_provider(
        provider_name="mock",
        settings=settings,
    )

    assert isinstance(
        provider,
        MockLLMProvider,
    )

    assert provider.provider_name == "mock"


# ============================================================
# INVALID PROVIDER
# ============================================================

def test_invalid_provider_is_rejected():
    settings = MandateIQSettings(
        llm_cache_enabled=False,
    )

    with pytest.raises(
        ValueError,
        match="Unsupported LLM provider",
    ):
        get_llm_provider(
            provider_name="invalid-provider",
            settings=settings,
        )