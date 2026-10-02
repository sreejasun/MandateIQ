"""Background execution of reviews and what-if scenarios.

Reviews run one at a time on a single worker thread. The Evidence Ledger is
process-local and is cleared at the start of each run, so running two reviews
at once could mix their evidence. A queue keeps runs isolated.
"""
from __future__ import annotations

import io
import json
import logging
import os
import queue
import re
import threading
import traceback
from typing import Any

import pandas as pd

from api import services
from api.db import Database, now

log = logging.getLogger("mandateiq.jobs")

PROVIDERS = ("mock", "bedrock", "groq")


def provider_model(provider: str) -> str | None:
    if provider == "bedrock":
        return os.environ.get("BEDROCK_MODEL_ID") or None
    if provider == "groq":
        from src.llm.groq_client import groq_model
        return groq_model()
    return None


def provider_status(provider: str) -> tuple[bool, str]:
    """Whether a provider can be used right now, and why not."""
    if provider == "mock":
        return True, "Deterministic reasoning with no model calls."
    if provider == "bedrock":
        if not os.environ.get("BEDROCK_MODEL_ID"):
            return False, "Set BEDROCK_MODEL_ID and AWS credentials in .env to enable."
        try:
            import boto3  # noqa: F401
        except ImportError:
            return False, "Install boto3 to use Bedrock."
        return True, "Uses your AWS credentials and the configured Bedrock model."
    if provider == "groq":
        from src.llm.groq_client import groq_configured
        if not groq_configured():
            return False, "Set GROQ_API_KEY in .env to enable."
        return True, "Uses the Groq API key from .env."
    return False, "Unknown provider."


class RateLimitedError(RuntimeError):
    """The model provider refused requests for quota reasons, so the review has no real result."""


def _raise_if_rate_limited(data: dict[str, Any]) -> None:
    """Fail the run instead of storing a trust score that only reflects the provider's quota.

    Agents record provider errors in their result rather than raising, so a rate-limited run
    otherwise completes with the agent-error cap and looks like a weak fund.
    """
    text = json.dumps(data, default=str)
    if "rate_limit_exceeded" not in text and "RateLimitError" not in text:
        return
    wait = re.search(r"try again in ([0-9hms.]+)", text)
    hint = f" Try again in about {wait.group(1).rstrip('.')}." if wait else " Try again later."
    raise RateLimitedError(
        "The model provider's rate limit was reached, so the agents could not run." + hint
        + " Mock needs no quota."
    )


class Runner:
    def __init__(self, db: Database, inline: bool = False) -> None:
        self.db = db
        self.inline = inline
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.inline or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="mandateiq-runner", daemon=True)
        self._thread.start()

    def submit(self, review_id: str) -> None:
        if self.inline:
            self.run(review_id)
        else:
            self._queue.put(review_id)

    def _loop(self) -> None:
        while True:
            review_id = self._queue.get()
            try:
                self.run(review_id)
            except Exception:  # pragma: no cover - run() records its own failures
                log.exception("Unexpected runner failure for %s", review_id)
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------ one run
    def run(self, review_id: str) -> None:
        from src.orchestration.pipeline import run_mandateiq

        record = self.db.get_review(review_id)
        if record is None:
            return

        events: list[dict[str, Any]] = []

        def on_stage(stage: str, status: str, details: dict[str, Any]) -> None:
            events.append({"stage": stage, "status": status, "details": details, "at": now()})
            self.db.update_review(review_id, events=events)

        self.db.update_review(review_id, status="running", started_at=now())
        previous_provider = os.environ.get("LLM_PROVIDER")

        try:
            dataset = self.db.get_dataset(record["dataset_id"])
            if dataset is None:
                raise services.DatasetError("The dataset for this review no longer exists.")

            df = pd.read_csv(io.StringIO(dataset["csv"]))
            if record.get("changes"):
                df = services.apply_changes(df, record["fund_id"], record["changes"])

            options = record.get("options") or {}
            injections = (
                {"proponent_claims": services.SEEDED_CLAIMS} if options.get("seed_unsupported_claims") else None
            )

            os.environ["LLM_PROVIDER"] = record["provider"]
            state = run_mandateiq(
                df,
                fund_id=record["fund_id"],
                case_id=review_id,
                mandate=record["mandate"],
                on_stage=on_stage,
                demo_injections=injections,
            )
            data = state.model_dump(mode="json")
            _raise_if_rate_limited(data)
            self.db.update_review(
                review_id,
                status="completed",
                outcome=services.outcome_of(data, "completed"),
                trust_score=data.get("trust_score"),
                state=data,
                completed_at=now(),
            )
        except Exception as exc:
            log.error("Review %s failed:\n%s", review_id, traceback.format_exc())
            events.append({"stage": "error", "status": "failed", "details": {"message": str(exc)}, "at": now()})
            self.db.update_review(
                review_id,
                status="failed",
                outcome="failed",
                error=f"{type(exc).__name__}: {exc}",
                events=events,
                completed_at=now(),
            )
        finally:
            if previous_provider is None:
                os.environ.pop("LLM_PROVIDER", None)
            else:
                os.environ["LLM_PROVIDER"] = previous_provider

