"""A rate-limited model run fails with a clear message instead of storing a capped trust score."""
import pytest

from api.jobs import RateLimitedError, _raise_if_rate_limited


def test_rate_limited_run_raises_with_wait_hint():
    data = {"proponent_result": {"llm_error": "Groq request failed: RateLimitError: Error code: 429 - "
                                              "{'code': 'rate_limit_exceeded', 'message': 'Please try again in 1m45.408s.'}"}}
    with pytest.raises(RateLimitedError, match="Try again in about 1m45.408s"):
        _raise_if_rate_limited(data)


def test_other_agent_errors_are_left_to_the_trust_score():
    _raise_if_rate_limited({"proponent_result": {"llm_error": "did not submit a valid result"}})
