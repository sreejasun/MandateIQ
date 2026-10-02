"""
MandateIQ Groq LLM Provider.

Groq is an alternative to Amazon Bedrock for running MandateIQ without
AWS access. Bedrock remains the primary production provider.

Groq exposes an OpenAI-compatible Chat Completions API, while MandateIQ's
tool-using agents were written against the Bedrock Converse API. Rather
than duplicating the agent loop, this module provides `converse()`, an
adapter that accepts Converse-shaped arguments, calls Groq, and returns a
Converse-shaped response. The agent loop in `src/agents/tool_agent.py`
therefore runs unchanged on either provider.

Configuration (environment variables):

    GROQ_API_KEY        required
    GROQ_MODEL          default: openai/gpt-oss-120b
    GROQ_MAX_RETRIES    default: 5  (rate-limit and transient-error retries,
                                     with exponential backoff, handled by the SDK)
    LLM_TIMEOUT_SECONDS default: 60
"""

from __future__ import annotations

import json
import os
import time
import uuid
from types import SimpleNamespace
from typing import Any

from src.llm.provider import LLMProvider
from src.llm.schemas import LLMRequest, LLMResponse


DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"

# Groq returns HTTP 400 "tool_use_failed" when a model emits a malformed
# tool call, or "output_parse_failed" when its output cannot be parsed at all.
# Retrying the same request usually succeeds.
_TOOL_USE_FAILED_RETRIES = 2


class GroqError(RuntimeError):
    """Raised when a Groq request cannot be completed."""


# ============================================================
# CONFIGURATION / CLIENT
# ============================================================

def groq_model() -> str:
    return os.environ.get("GROQ_MODEL", "").strip() or DEFAULT_GROQ_MODEL


def groq_configured() -> bool:
    return bool(os.environ.get("GROQ_API_KEY", "").strip())


def _client() -> Any:
    try:
        from groq import Groq
    except ImportError as exc:  # pragma: no cover
        raise GroqError("The 'groq' package is required when LLM_PROVIDER=groq.") from exc

    if not groq_configured():
        raise GroqError("GROQ_API_KEY is not set.")

    return Groq(
        api_key=os.environ["GROQ_API_KEY"].strip(),
        max_retries=int(os.environ.get("GROQ_MAX_RETRIES", "5")),
        timeout=float(os.environ.get("LLM_TIMEOUT_SECONDS", "60")),
    )


def _create(**kwargs: Any) -> Any:
    """Single chat-completion call with retry on malformed tool calls.

    Separated so tests can patch it without a network connection.
    """

    client = _client()
    last_exc: Exception | None = None

    for _ in range(_TOOL_USE_FAILED_RETRIES + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:  # groq.BadRequestError, RateLimitError, ...
            last_exc = exc
            if "tool_use_failed" in str(exc):
                recovered = _recover_misnamed_submit(exc, kwargs.get("tools"))
                if recovered is not None:
                    return recovered
                continue
            if "output_parse_failed" in str(exc):
                continue
            raise GroqError(f"Groq request failed: {type(exc).__name__}: {exc}") from exc

    raise GroqError(f"Groq request failed after retries: {last_exc}") from last_exc


def _recover_misnamed_submit(exc: Exception, tools: list[dict] | None) -> Any:
    """Turn a call to an unknown tool into a call to the agent's submit tool.

    gpt-oss models sometimes send their final answer to a made-up tool such as
    `json`; Groq rejects that with tool_use_failed and repeating the request
    fails the same way. When the request has exactly one `submit_*` tool and the
    rejected call carries an object of arguments, re-address it to that tool.
    The agent still validates the submission, so a wrong payload is rejected
    there and returned to the model as a tool error.
    """

    body = getattr(exc, "body", None)
    error = (body.get("error", body) if isinstance(body, dict) else None) or {}
    generation = error.get("failed_generation") if isinstance(error, dict) else None
    names = [t["function"]["name"] for t in tools or []]
    submit = [t["function"] for t in tools or [] if t["function"]["name"].startswith("submit_")]
    if not generation or len(submit) != 1:
        return None

    try:
        call = json.loads(generation)
    except (TypeError, json.JSONDecodeError):
        return None
    if isinstance(call, list) and len(call) == 1:
        call = call[0]
    if not isinstance(call, dict) or call.get("name") in names:
        return None
    args = call.get("arguments", call.get("parameters"))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    if not isinstance(args, dict):
        return None
    # Only a payload shaped like a submission: a stray call to another tool is retried instead.
    required = set((submit[0].get("parameters") or {}).get("required") or [])
    if not args or not required <= args.keys():
        return None

    tool_call = SimpleNamespace(
        id=f"call_recovered_{uuid.uuid4().hex[:12]}",
        function=SimpleNamespace(name=submit[0]["name"], arguments=json.dumps(args)),
    )
    message = SimpleNamespace(content=None, tool_calls=[tool_call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="tool_calls")], usage=None)


# ============================================================
# CONVERSE -> OPENAI TRANSLATION
# ============================================================

def _tools_to_openai(tool_config: dict | None) -> tuple[list[dict] | None, Any]:
    if not tool_config:
        return None, None

    tools = []
    for item in tool_config.get("tools", []):
        spec = item.get("toolSpec", {})
        tools.append({
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec.get("description", ""),
                "parameters": (spec.get("inputSchema") or {}).get("json") or {"type": "object"},
            },
        })

    choice = tool_config.get("toolChoice") or {}
    if "any" in choice:
        tool_choice: Any = "required"
    elif "tool" in choice:
        tool_choice = {"type": "function", "function": {"name": choice["tool"]["name"]}}
    else:
        tool_choice = "auto"

    return tools, tool_choice


def _tool_result_content(block: dict) -> str:
    parts = []
    for c in block.get("content", []):
        if "json" in c:
            parts.append(json.dumps(c["json"], default=str))
        elif "text" in c:
            parts.append(str(c["text"]))
    text = "\n".join(parts) or "{}"
    if block.get("status") == "error":
        text = f"ERROR: {text}"
    return text


def _messages_to_openai(system: list[dict] | None, messages: list[dict]) -> list[dict]:
    out: list[dict] = []

    system_text = "\n".join(s.get("text", "") for s in (system or []) if s.get("text"))
    if system_text:
        out.append({"role": "system", "content": system_text})

    for msg in messages:
        role = msg.get("role")
        blocks = msg.get("content", [])

        if role == "assistant":
            text = "".join(b.get("text", "") for b in blocks if "text" in b)
            calls = [
                {
                    "id": b["toolUse"]["toolUseId"],
                    "type": "function",
                    "function": {
                        "name": b["toolUse"]["name"],
                        "arguments": json.dumps(b["toolUse"].get("input") or {}, default=str),
                    },
                }
                for b in blocks if "toolUse" in b
            ]
            entry: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
            continue

        # user turn: plain text and/or tool results
        texts = [b["text"] for b in blocks if "text" in b]
        for b in blocks:
            if "toolResult" in b:
                tr = b["toolResult"]
                out.append({
                    "role": "tool",
                    "tool_call_id": tr["toolUseId"],
                    "content": _tool_result_content(tr),
                })
        if texts:
            out.append({"role": "user", "content": "\n".join(texts)})

    return out


def _response_to_converse(resp: Any) -> dict:
    choice = resp.choices[0]
    message = choice.message
    content: list[dict] = []

    if getattr(message, "content", None):
        content.append({"text": message.content})

    for call in getattr(message, "tool_calls", None) or []:
        raw = call.function.arguments or "{}"
        try:
            args = json.loads(raw)
            if not isinstance(args, dict):
                args = {"value": args}
        except json.JSONDecodeError:
            # Let the agent's validation reject it so the model can correct itself.
            args = {"_unparseable_arguments": raw[:2000]}
        content.append({"toolUse": {"toolUseId": call.id, "name": call.function.name, "input": args}})

    usage = getattr(resp, "usage", None)
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": "tool_use" if choice.finish_reason == "tool_calls" else choice.finish_reason,
        "usage": {
            "inputTokens": getattr(usage, "prompt_tokens", None),
            "outputTokens": getattr(usage, "completion_tokens", None),
        },
    }


# ============================================================
# PUBLIC HELPERS
# ============================================================

def converse(
    *,
    modelId: str | None = None,
    system: list[dict] | None = None,
    messages: list[dict],
    toolConfig: dict | None = None,
    inferenceConfig: dict | None = None,
    **_: Any,
) -> dict:
    """Bedrock-Converse-compatible call executed on Groq."""

    inference = inferenceConfig or {}
    kwargs: dict[str, Any] = {
        "model": modelId or groq_model(),
        "messages": _messages_to_openai(system, messages),
        "max_completion_tokens": int(inference.get("maxTokens", 4000)),
    }
    if "temperature" in inference:
        kwargs["temperature"] = inference["temperature"]

    tools, tool_choice = _tools_to_openai(toolConfig)
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice

    return _response_to_converse(_create(**kwargs))


def chat_text(system: str, user: str, *, max_tokens: int = 4000, json_mode: bool = False) -> str:
    """Plain system+user completion; returns the text content."""

    kwargs: dict[str, Any] = {
        "model": groq_model(),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_completion_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    resp = _create(**kwargs)
    text = resp.choices[0].message.content or ""
    if not text.strip():
        raise GroqError("Groq returned no text content.")
    return text


# ============================================================
# LLMProvider IMPLEMENTATION
# ============================================================

class GroqLLMProvider(LLMProvider):
    """Groq implementation of the MandateIQ LLM provider interface."""

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or groq_model()

    @property
    def provider_name(self) -> str:
        return "groq"

    def invoke(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "max_completion_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        try:
            resp = _create(**kwargs)
        except GroqError as exc:
            raise RuntimeError(str(exc)) from exc

        text = (resp.choices[0].message.content or "").strip()
        if not text:
            raise RuntimeError("Groq returned no text content.")

        usage = getattr(resp, "usage", None)
        return LLMResponse(
            content=text,
            provider=self.provider_name,
            model_id=self.model_id,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            cached=False,
            metadata={
                "response_schema": request.response_schema,
                "stop_reason": resp.choices[0].finish_reason,
                "request_metadata": request.metadata,
            },
        )
