import pytest

from config.settings import MandateIQSettings

from src.llm.bedrock_client import BedrockLLMProvider
from src.llm.cached_provider import CachedLLMProvider
from src.llm.provider import get_llm_provider
from src.llm.schemas import LLMRequest, LLMResponse


# ============================================================
# FAKE BEDROCK CLIENTS
# ============================================================

class FakeBedrockClient:
    """
    Fake Bedrock Runtime client used for unit testing.

    No AWS request is made.
    """

    def __init__(self):
        self.last_request = None

    def converse(self, **kwargs):
        self.last_request = kwargs

        return {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": (
                                '{"status":"PASS",'
                                '"confidence":0.91}'
                            )
                        }
                    ]
                }
            },
            "usage": {
                "inputTokens": 120,
                "outputTokens": 35,
            },
            "stopReason": "end_turn",
        }


class FailingBedrockClient:
    """
    Fake client that simulates an AWS/Bedrock failure.
    """

    def converse(self, **kwargs):
        raise RuntimeError(
            "Simulated Bedrock failure"
        )


class MalformedBedrockClient:
    """
    Fake client returning an unexpected response structure.
    """

    def converse(self, **kwargs):
        return {
            "unexpected": "response"
        }


class EmptyContentBedrockClient:
    """
    Fake client returning no usable text.
    """

    def converse(self, **kwargs):
        return {
            "output": {
                "message": {
                    "content": []
                }
            }
        }


# ============================================================
# PROVIDER CONFIGURATION
# ============================================================

def test_bedrock_provider_name():
    provider = BedrockLLMProvider(
        model_id="test-model",
        client=FakeBedrockClient(),
    )

    assert provider.provider_name == "bedrock"


def test_bedrock_provider_requires_model_id(monkeypatch):
    monkeypatch.delenv(
        "BEDROCK_MODEL_ID",
        raising=False,
    )

    provider = BedrockLLMProvider(
        model_id="",
        client=FakeBedrockClient(),
    )

    request = LLMRequest(
        system_prompt="MandateIQ",
        user_prompt="Analyze evidence.",
    )

    with pytest.raises(
        ValueError,
        match="BEDROCK_MODEL_ID",
    ):
        provider.invoke(request)


def test_bedrock_provider_uses_default_region(
    monkeypatch,
):
    """
    Default region should be us-east-1 when no AWS region
    environment variable is configured.
    """

    monkeypatch.delenv(
        "AWS_REGION",
        raising=False,
    )

    monkeypatch.delenv(
        "AWS_DEFAULT_REGION",
        raising=False,
    )

    provider = BedrockLLMProvider(
        model_id="test-model",
        client=FakeBedrockClient(),
    )

    assert provider.region_name == "us-east-1"


def test_bedrock_provider_uses_configured_timeout():
    provider = BedrockLLMProvider(
        model_id="test-model",
        timeout_seconds=15.0,
        client=FakeBedrockClient(),
    )

    assert provider.timeout_seconds == 15.0


def test_invalid_timeout_is_rejected():
    with pytest.raises(
        ValueError,
        match="timeout_seconds",
    ):
        BedrockLLMProvider(
            model_id="test-model",
            timeout_seconds=0,
            client=FakeBedrockClient(),
        )


# ============================================================
# SUCCESSFUL INVOCATION
# ============================================================

def test_bedrock_provider_returns_valid_response():
    fake_client = FakeBedrockClient()

    provider = BedrockLLMProvider(
        model_id="test-model",
        region_name="us-east-1",
        timeout_seconds=20.0,
        client=fake_client,
    )

    request = LLMRequest(
        system_prompt="You are MandateIQ.",
        user_prompt="Analyze verified evidence.",
        response_schema="TestResult",
        temperature=0.0,
        max_tokens=500,
    )

    response = provider.invoke(request)

    assert isinstance(
        response,
        LLMResponse,
    )

    assert response.provider == "bedrock"

    assert response.model_id == "test-model"

    assert response.input_tokens == 120

    assert response.output_tokens == 35

    assert response.cached is False

    assert (
        response.metadata["region"]
        == "us-east-1"
    )

    assert (
        response.metadata["timeout_seconds"]
        == 20.0
    )

    assert (
        response.metadata["response_schema"]
        == "TestResult"
    )

    assert (
        response.metadata["stop_reason"]
        == "end_turn"
    )


def test_bedrock_request_uses_converse_format():
    fake_client = FakeBedrockClient()

    provider = BedrockLLMProvider(
        model_id="test-model",
        client=fake_client,
    )

    request = LLMRequest(
        system_prompt="System instructions",
        user_prompt="User instructions",
        temperature=0.2,
        max_tokens=750,
    )

    provider.invoke(request)

    sent = fake_client.last_request

    assert sent["modelId"] == "test-model"

    assert sent["system"] == [
        {
            "text": "System instructions"
        }
    ]

    assert sent["messages"] == [
        {
            "role": "user",
            "content": [
                {
                    "text": "User instructions"
                }
            ],
        }
    ]

    assert sent["inferenceConfig"] == {
        "maxTokens": 750,
        "temperature": 0.2,
    }


def test_bedrock_extracts_multiple_text_blocks():
    response = {
        "output": {
            "message": {
                "content": [
                    {
                        "text": "First"
                    },
                    {
                        "text": "Second"
                    },
                ]
            }
        }
    }

    content = BedrockLLMProvider._extract_text(
        response
    )

    assert content == "First\nSecond"


# ============================================================
# MODEL-SPECIFIC INFERENCE CONFIGURATION
# ============================================================

def test_claude_sonnet_5_omits_temperature():
    """
    Claude Sonnet 5 rejects the legacy temperature parameter
    through the challenge Bedrock environment.
    """

    fake_client = FakeBedrockClient()

    provider = BedrockLLMProvider(
        model_id="us.anthropic.claude-sonnet-5",
        client=fake_client,
    )

    request = LLMRequest(
        system_prompt="MandateIQ",
        user_prompt="Analyze evidence.",
        temperature=0.0,
        max_tokens=500,
    )

    provider.invoke(request)

    assert (
        fake_client.last_request["inferenceConfig"]
        == {
            "maxTokens": 500,
        }
    )


def test_claude_opus_5_omits_temperature():
    """
    Claude Opus 5 should use the same compatibility behavior
    as Claude Sonnet 5.
    """

    fake_client = FakeBedrockClient()

    provider = BedrockLLMProvider(
        model_id="us.anthropic.claude-opus-5",
        client=fake_client,
    )

    request = LLMRequest(
        system_prompt="MandateIQ",
        user_prompt="Analyze evidence.",
        temperature=0.5,
        max_tokens=500,
    )

    provider.invoke(request)

    assert (
        fake_client.last_request["inferenceConfig"]
        == {
            "maxTokens": 500,
        }
    )


def test_other_models_can_include_temperature():
    """
    Models without the Claude 5 compatibility restriction
    should continue receiving temperature.
    """

    fake_client = FakeBedrockClient()

    provider = BedrockLLMProvider(
        model_id="test-model",
        client=fake_client,
    )

    request = LLMRequest(
        system_prompt="MandateIQ",
        user_prompt="Analyze evidence.",
        temperature=0.2,
        max_tokens=500,
    )

    provider.invoke(request)

    assert (
        fake_client.last_request["inferenceConfig"]
        == {
            "maxTokens": 500,
            "temperature": 0.2,
        }
    )


# ============================================================
# FAILURE HANDLING
# ============================================================

def test_bedrock_failure_is_reported():
    provider = BedrockLLMProvider(
        model_id="test-model",
        client=FailingBedrockClient(),
    )

    request = LLMRequest(
        system_prompt="MandateIQ",
        user_prompt="Analyze evidence.",
    )

    with pytest.raises(
        RuntimeError,
        match="Amazon Bedrock invocation failed",
    ):
        provider.invoke(request)


def test_malformed_bedrock_response_is_rejected():
    provider = BedrockLLMProvider(
        model_id="test-model",
        client=MalformedBedrockClient(),
    )

    request = LLMRequest(
        system_prompt="MandateIQ",
        user_prompt="Analyze evidence.",
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected response structure",
    ):
        provider.invoke(request)


def test_empty_bedrock_content_is_rejected():
    provider = BedrockLLMProvider(
        model_id="test-model",
        client=EmptyContentBedrockClient(),
    )

    request = LLMRequest(
        system_prompt="MandateIQ",
        user_prompt="Analyze evidence.",
    )

    with pytest.raises(
        RuntimeError,
        match="returned no text content",
    ):
        provider.invoke(request)


# ============================================================
# PROVIDER FACTORY - RAW BEDROCK
# ============================================================

def test_provider_factory_creates_raw_bedrock_provider():
    """
    With caching disabled, the factory should return the
    Bedrock provider directly and pass centralized settings.
    """

    settings = MandateIQSettings(
        llm_provider="bedrock",
        bedrock_model_id="factory-test-model",
        aws_region="us-west-2",
        llm_timeout_seconds=17.0,
        llm_cache_enabled=False,
    )

    provider = get_llm_provider(
        settings=settings
    )

    assert isinstance(
        provider,
        BedrockLLMProvider,
    )

    assert provider.provider_name == "bedrock"

    assert (
        provider.model_id
        == "factory-test-model"
    )

    assert (
        provider.region_name
        == "us-west-2"
    )

    assert provider.timeout_seconds == 17.0


# ============================================================
# PROVIDER FACTORY - CACHED BEDROCK
# ============================================================

def test_provider_factory_wraps_bedrock_when_cache_enabled():
    """
    With caching enabled, the factory should return the
    provider-independent cache wrapper.
    """

    settings = MandateIQSettings(
        llm_provider="bedrock",
        bedrock_model_id="factory-test-model",
        aws_region="us-east-1",
        llm_timeout_seconds=30.0,
        llm_cache_enabled=True,
        llm_cache_max_entries=50,
    )

    provider = get_llm_provider(
        settings=settings
    )

    assert isinstance(
        provider,
        CachedLLMProvider,
    )

    assert provider.provider_name == "bedrock"

    assert provider.max_entries == 50