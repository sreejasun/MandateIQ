import pytest

from config.settings import MandateIQSettings, load_settings


def test_default_settings(monkeypatch):
    variables = [
        "LLM_PROVIDER",
        "BEDROCK_MODEL_ID",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "LLM_MAX_TOKENS",
        "LLM_TEMPERATURE",
        "LLM_TIMEOUT_SECONDS",
        "QUALITY_THRESHOLD",
        "CONFIDENCE_THRESHOLD",
        "TRUST_THRESHOLD",
        "MAX_RETRIES",
        "MAX_WORKFLOW_STEPS",
        "LLM_CACHE_ENABLED",
        "LLM_CACHE_MAX_ENTRIES",
    ]

    for variable in variables:
        monkeypatch.delenv(variable, raising=False)

    settings = load_settings()

    assert settings.llm_provider == "mock"
    assert settings.bedrock_model_id == ""
    assert settings.aws_region == "us-east-1"

    assert settings.llm_max_tokens == 1500
    assert settings.llm_temperature == 0.0
    assert settings.llm_timeout_seconds == 30.0

    assert settings.quality_threshold == 0.80
    assert settings.confidence_threshold == 0.70
    assert settings.trust_threshold == 70.0

    assert settings.max_retries == 1
    assert settings.max_workflow_steps == 25

    assert settings.llm_cache_enabled is True
    assert settings.llm_cache_max_entries == 128


def test_environment_overrides(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv(
        "BEDROCK_MODEL_ID",
        "test-model",
    )
    monkeypatch.setenv(
        "AWS_REGION",
        "us-west-2",
    )
    monkeypatch.setenv(
        "QUALITY_THRESHOLD",
        "0.90",
    )
    monkeypatch.setenv(
        "CONFIDENCE_THRESHOLD",
        "0.80",
    )
    monkeypatch.setenv(
        "TRUST_THRESHOLD",
        "85",
    )
    monkeypatch.setenv(
        "MAX_RETRIES",
        "2",
    )
    monkeypatch.setenv(
        "MAX_WORKFLOW_STEPS",
        "40",
    )
    monkeypatch.setenv(
        "LLM_TIMEOUT_SECONDS",
        "45",
    )
    monkeypatch.setenv(
        "LLM_CACHE_ENABLED",
        "false",
    )
    monkeypatch.setenv(
        "LLM_CACHE_MAX_ENTRIES",
        "256",
    )

    settings = load_settings()

    assert settings.llm_provider == "bedrock"
    assert settings.bedrock_model_id == "test-model"
    assert settings.aws_region == "us-west-2"

    assert settings.quality_threshold == 0.90
    assert settings.confidence_threshold == 0.80
    assert settings.trust_threshold == 85.0

    assert settings.max_retries == 2
    assert settings.max_workflow_steps == 40

    assert settings.llm_timeout_seconds == 45.0

    assert settings.llm_cache_enabled is False
    assert settings.llm_cache_max_entries == 256


def test_provider_is_normalized():
    settings = MandateIQSettings(
        llm_provider=" MOCK ",
    )

    assert settings.llm_provider == "mock"


def test_invalid_provider_is_rejected():
    with pytest.raises(
        ValueError,
        match="llm_provider",
    ):
        MandateIQSettings(
            llm_provider="invalid",
        )


def test_invalid_quality_threshold_is_rejected():
    with pytest.raises(
        ValueError,
        match="quality_threshold",
    ):
        MandateIQSettings(
            quality_threshold=1.5,
        )


def test_invalid_confidence_threshold_is_rejected():
    with pytest.raises(
        ValueError,
        match="confidence_threshold",
    ):
        MandateIQSettings(
            confidence_threshold=-0.1,
        )


def test_invalid_trust_threshold_is_rejected():
    with pytest.raises(
        ValueError,
        match="trust_threshold",
    ):
        MandateIQSettings(
            trust_threshold=101,
        )


def test_negative_retries_are_rejected():
    with pytest.raises(
        ValueError,
        match="max_retries",
    ):
        MandateIQSettings(
            max_retries=-1,
        )


def test_invalid_max_workflow_steps_is_rejected():
    with pytest.raises(
        ValueError,
        match="max_workflow_steps",
    ):
        MandateIQSettings(
            max_workflow_steps=0,
        )


def test_invalid_timeout_is_rejected():
    with pytest.raises(
        ValueError,
        match="llm_timeout_seconds",
    ):
        MandateIQSettings(
            llm_timeout_seconds=0,
        )


def test_invalid_cache_size_is_rejected():
    with pytest.raises(
        ValueError,
        match="llm_cache_max_entries",
    ):
        MandateIQSettings(
            llm_cache_max_entries=0,
        )


def test_boolean_environment_values(monkeypatch):
    monkeypatch.setenv(
        "LLM_CACHE_ENABLED",
        "yes",
    )

    assert load_settings().llm_cache_enabled is True

    monkeypatch.setenv(
        "LLM_CACHE_ENABLED",
        "off",
    )

    assert load_settings().llm_cache_enabled is False


def test_invalid_boolean_environment_value(monkeypatch):
    monkeypatch.setenv(
        "LLM_CACHE_ENABLED",
        "maybe",
    )

    with pytest.raises(
        ValueError,
        match="LLM_CACHE_ENABLED",
    ):
        load_settings()