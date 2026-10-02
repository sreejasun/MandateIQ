"""Structured run logging for review agents (requirements §42: simple structured JSON logs)."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from src.agents import llm_bridge
from src.evidence.claims import RunLog
from src.evidence.verifier import EvidenceIndex, sget

logger = logging.getLogger("mandateiq.review")


class Timer:
    def __init__(self) -> None:
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._t0 = time.perf_counter()


def model_id(llm: bool) -> str:
    if not llm:
        return "deterministic"
    if llm_bridge.provider_name() == "mock":
        return "mock"
    return llm_bridge.model_id() or f"{llm_bridge.provider_name()}:unknown"


def attach(result: Any, agent: str, state: Any, timer: Timer, output_ids: list[str], *,
           llm: bool, prompt_version: str | None = None, rule_version: str | None = None) -> Any:
    log = RunLog(
        agent=agent, case_id=sget(state, "case_id"), started_at=timer.started_at,
        ended_at=datetime.now(timezone.utc).isoformat(),
        latency_ms=round((time.perf_counter() - timer._t0) * 1000, 1),
        model_id=model_id(llm), prompt_version=prompt_version, rule_version=rule_version,
        confidence=getattr(result, "confidence", None),
        input_evidence_ids=[r.get("evidence_id") for r in EvidenceIndex(state).records if r.get("evidence_id")],
        output_ids=output_ids, error=getattr(result, "llm_error", None),
    )
    result.run_log = log
    logger.info(json.dumps({"event": "agent_run", **log.model_dump()}))
    return result
