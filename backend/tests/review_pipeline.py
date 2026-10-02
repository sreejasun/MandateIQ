"""Test helper: run Dileep's modules in order on a fixture state (no Supervisor)."""
from src.agents.challenger import run_challenger
from src.agents.policy_suitability import run_policy_review
from src.agents.proponent import run_proponent
from src.trust.governance import run_governance


def run_review(state: dict) -> dict:
    state["proponent_result"] = run_proponent(state).model_dump(mode="json")
    state["challenger_result"] = run_challenger(state).model_dump(mode="json")
    state["policy_result"] = run_policy_review(state).model_dump(mode="json")
    state.update(run_governance(state))
    return state
