"""Convenience pipeline for demos/tests: debate committee -> policy -> governance.

In the real app Narahari's graph calls these steps; this helper runs them in order.
"""
from __future__ import annotations

from typing import Any

from src.agents.debate import run_committee
from src.agents.policy_suitability import run_policy_review
from src.trust.governance import run_governance


def run_full_review(state: dict) -> dict:
    state.update(run_committee(state))
    state["policy_result"] = run_policy_review(state).model_dump(mode="json")
    state.update(run_governance(state))
    return state
