"""Bounded tool-use agent loop (Converse API shape with toolConfig).

Runs on Amazon Bedrock (primary) or on Groq through a Converse-compatible adapter
(src/llm/groq_client.py), selected by LLM_PROVIDER.

The model decides which tools to call and in what order; Python executes them and feeds the
results back. The agent finishes by calling its `submit_*` tool, whose input is validated with
Pydantic. An invalid submission is returned to the agent as a tool error so it can correct
itself inside the same loop. The loop is bounded by `max_tool_steps` (config/agents.yaml).
"""
from __future__ import annotations

import os
from typing import Any, Callable

from src import config_loader
from src.agents import llm_bridge
from src.agents.llm_bridge import LLMError
from src.agents.tools import ReviewTools


def agent_config() -> dict:
    return config_loader.load("agents.yaml")


def agent_mode() -> str:
    return os.environ.get("MANDATEIQ_AGENT_MODE", agent_config().get("mode", "tool_use")).lower()


def _converse(**kwargs) -> dict:
    """Single Converse call on the active provider (patched in tests)."""
    if llm_bridge.provider_name() == "groq":
        from src.llm.groq_client import GroqError, converse
        try:
            return converse(**kwargs)
        except GroqError as exc:
            raise LLMError(str(exc)) from exc
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise LLMError("boto3 is not installed") from exc
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    try:
        return boto3.client("bedrock-runtime", region_name=region).converse(**kwargs)
    except Exception as exc:
        raise LLMError(f"Bedrock call failed: {exc}") from exc


def run_tool_agent(
    *,
    tools: ReviewTools,
    system: str,
    user: str,
    tool_names: list[str],
    submit_name: str,
    submit_description: str,
    submit_schema: dict,
    validate: Callable[[dict], Any],
    max_steps: int | None = None,
) -> Any:
    """Run the loop; return validate(submit_input). Raises LLMError if the agent never submits."""
    if llm_bridge.provider_name() == "groq":
        model_id = llm_bridge.model_id()
    else:
        model_id = os.environ.get("BEDROCK_MODEL_ID")
        if not model_id:
            raise LLMError("BEDROCK_MODEL_ID is not set")
    max_steps = max_steps or int(agent_config().get("max_tool_steps", 8))
    tool_config = {
        "tools": tools.specs(tool_names) + [{"toolSpec": {
            "name": submit_name, "description": submit_description,
            "inputSchema": {"json": submit_schema}}}],
        "toolChoice": {"any": {}},          # every turn must be a tool call
    }
    messages: list[dict] = [{"role": "user", "content": [{"text": user}]}]
    for turn in range(1, max_steps + 1):
        if turn == max_steps:
            # Last step: require the submission so the agent cannot run out of steps investigating.
            tool_config = {**tool_config, "tools": tool_config["tools"][-1:]}
            messages[-1] = {**messages[-1], "content": messages[-1]["content"] + [{"text":
                f"This is your final step. Call {submit_name} now with your best result."}]}
        resp = _converse(modelId=model_id, system=[{"text": system}], messages=messages,
                         toolConfig=tool_config, inferenceConfig={"maxTokens": 4000})
        msg = resp["output"]["message"]
        messages.append(msg)
        uses = [c["toolUse"] for c in msg.get("content", []) if "toolUse" in c]
        if not uses:
            messages.append({"role": "user", "content": [{"text":
                f"Call a tool. When finished, call {submit_name}."}]})
            continue
        results = []
        for use in uses:
            name, args = use["name"], use.get("input") or {}
            if name == submit_name:
                try:
                    value = validate(args)
                except Exception as exc:
                    tools.record(submit_name, {"turn": turn}, f"rejected: {exc}"[:240], ok=False)
                    out, ok = {"error": f"Submission rejected, fix and resubmit: {exc}"[:1500]}, False
                else:
                    tools.record(submit_name, {"turn": turn}, "accepted", ok=True)
                    return value
            else:
                out, ok = tools.call(name, args)
            results.append({"toolResult": {"toolUseId": use["toolUseId"],
                                           "content": [{"json": out}],
                                           "status": "success" if ok else "error"}})
        remaining = max_steps - turn
        results.append({"text": f"{remaining} tool step(s) remain, including {submit_name}."})
        messages.append({"role": "user", "content": results})
    raise LLMError(f"{tools.agent} did not submit a valid result within {max_steps} tool steps")
