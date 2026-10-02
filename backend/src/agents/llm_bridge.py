"""Thin LLM bridge for the review committee (Proponent / Challenger).

LLM_PROVIDER=mock    (default) -> deterministic mock reasoning, zero model calls.
LLM_PROVIDER=bedrock           -> Amazon Bedrock (primary provider) via boto3 Converse.
LLM_PROVIDER=groq              -> Groq Chat Completions (alternative when AWS is unavailable).

Integration with Narahari's provider: if `src.llm.provider` exposes
`generate_json(system: str, user: str, *, agent: str) -> dict | str`, it is used so caching,
timeouts and route logging stay centralized. Otherwise this module calls Bedrock directly.
Failures raise LLMError; agents turn that into a low-confidence result that the Supervisor
escalates. We never silently substitute mock output in bedrock mode.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


def provider_name() -> str:
    return os.environ.get("LLM_PROVIDER", "mock").strip().lower()


def model_id() -> str | None:
    """Model identifier for the active LLM provider (None in mock mode)."""
    provider = provider_name()
    if provider == "bedrock":
        return os.environ.get("BEDROCK_MODEL_ID") or None
    if provider == "groq":
        from src.llm.groq_client import groq_model
        return groq_model()
    return None


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise LLMError("model response contained no JSON object")
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"model returned invalid JSON: {exc}") from exc


def _team_provider() -> Callable[..., Any] | None:
    try:
        from src.llm import provider as team_provider  # type: ignore
    except Exception:
        return None
    return getattr(team_provider, "generate_json", None)


def _bedrock_converse(system: str, user: str) -> str:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise LLMError("boto3 is not installed") from exc
    model_id = os.environ.get("BEDROCK_MODEL_ID")
    if not model_id:
        raise LLMError("BEDROCK_MODEL_ID is not set")
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    client = boto3.client("bedrock-runtime", region_name=region)
    try:
        resp = client.converse(
            modelId=model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": 4000},
        )
    except Exception as exc:
        raise LLMError(f"Bedrock call failed: {exc}") from exc
    parts = resp["output"]["message"]["content"]
    return "".join(p.get("text", "") for p in parts)


def _groq_chat(system: str, user: str) -> str:
    from src.llm.groq_client import GroqError, chat_text
    try:
        return chat_text(system, user, max_tokens=4000, json_mode=True)
    except GroqError as exc:
        raise LLMError(str(exc)) from exc


def _raw_call(system: str, user: str, agent: str) -> dict:
    team = _team_provider()
    if team is not None:
        out = team(system, user, agent=agent)
        return out if isinstance(out, dict) else _extract_json(str(out))
    if provider_name() == "groq":
        return _extract_json(_groq_chat(system, user))
    return _extract_json(_bedrock_converse(system, user))


def generate(
    *,
    agent: str,
    system: str,
    payload: dict,
    model: Type[T],
    mock_fn: Callable[[], T],
    postprocess: Callable[[dict], dict] = lambda d: d,
) -> T:
    """Return a validated `model`. Mock mode calls mock_fn; bedrock/groq mode calls the LLM,
    validates, and retries once with a structured-correction message on invalid output."""
    if provider_name() == "mock":
        return mock_fn()

    user = json.dumps(payload, default=str)
    last_error = ""
    for attempt in range(2):
        prompt = user if attempt == 0 else (
            user + "\n\nYour previous reply was invalid: " + last_error +
            "\nReturn ONLY corrected JSON matching the required keys."
        )
        data = _raw_call(system, prompt, agent)
        try:
            return model.model_validate(postprocess(data))
        except (ValidationError, KeyError, TypeError, ValueError) as exc:
            last_error = str(exc)[:800]
    raise LLMError(f"{agent} output failed validation after retry: {last_error}")
