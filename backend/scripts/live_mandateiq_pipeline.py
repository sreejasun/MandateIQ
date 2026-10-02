"""
MandateIQ end-to-end command-line demonstration.

Runs the integrated MandateIQ pipeline against one selected fund
from the sample dataset.

The demo exercises the complete application flow:

    Dataset
        ->
    Fund Selection
        ->
    Data Steward / Evidence Ledger
        ->
    Adversarial Committee
        ->
    Policy / Governance
        ->
    Adaptive Supervisor
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.orchestration.pipeline import run_mandateiq  # noqa: E402


# ============================================================
# DEMO CONFIGURATION
# ============================================================

DATASET = "data/sample/fund_sample.csv"

# One MandateIQ case represents exactly one fund.
FUND_ID = "F001"

CASE_ID = f"CASE-LIVE-{FUND_ID}"

MANDATE = "balanced_growth"


# ============================================================
# DEMO
# ============================================================

def main() -> None:

    print()
    print("=" * 72)
    print("                    MANDATEIQ END-TO-END REVIEW")
    print("=" * 72)

    # --------------------------------------------------------
    # INPUT
    # --------------------------------------------------------

    print()
    print("INPUT")
    print("-" * 72)

    print(f"Dataset:             {DATASET}")
    print(f"Selected Fund:       {FUND_ID}")
    print(f"Case ID:             {CASE_ID}")
    print(f"Mandate:             {MANDATE}")

    print()
    print("Running MandateIQ...")
    print()

    # --------------------------------------------------------
    # RUN COMPLETE MANDATEIQ PIPELINE
    # --------------------------------------------------------

    state = run_mandateiq(
        dataset=DATASET,
        fund_id=FUND_ID,
        case_id=CASE_ID,
        mandate=MANDATE,
    )

    # --------------------------------------------------------
    # SELECTED FUND
    # --------------------------------------------------------

    print("-" * 72)
    print("SELECTED FUND")
    print("-" * 72)

    fund = state.fund_record or {}

    print(
        f"Fund ID:             "
        f"{fund.get('fund_id', FUND_ID)}"
    )

    print(
        f"Asset Class:         "
        f"{fund.get('asset_class', 'N/A')}"
    )

    print(
        f"Risk Level:          "
        f"{fund.get('risk_level', 'N/A')}"
    )

    print(
        f"Expense Ratio:       "
        f"{fund.get('expense_ratio', 'N/A')}%"
    )

    print(
        f"History:             "
        f"{fund.get('history_years', 'N/A')} years"
    )

    # --------------------------------------------------------
    # DATA STEWARD
    # --------------------------------------------------------

    print()
    print("-" * 72)
    print("DATA STEWARD")
    print("-" * 72)

    print(
        f"Quality Score:       "
        f"{state.quality_score:.2f}"
    )

    print(
        f"Evidence Records:    "
        f"{len(state.evidence_ledger)}"
    )

    print(
        f"Rows Processed:      "
        f"{state.metadata.get('row_count', 'N/A')}"
    )

    print(
        f"Selected Fund ID:    "
        f"{state.metadata.get('selected_fund_id', 'N/A')}"
    )

    # --------------------------------------------------------
    # ADVERSARIAL COMMITTEE
    # --------------------------------------------------------

    print()
    print("-" * 72)
    print("ADVERSARIAL COMMITTEE")
    print("-" * 72)

    proponent = (
        state.proponent_result
        or {}
    )

    challenger = (
        state.challenger_result
        or {}
    )

    debate = (
        state.debate
        or {}
    )

    print(
        f"Proponent Position:  "
        f"{proponent.get('position', 'N/A')}"
    )

    print(
        f"Proponent Claims:    "
        f"{len(proponent.get('claims', []))}"
    )

    print(
        f"Proponent Confidence:"
        f" {proponent.get('confidence', 'N/A')}"
    )

    print(
        f"Challenger Position: "
        f"{challenger.get('position', 'N/A')}"
    )

    print(
        f"Challenges:          "
        f"{len(challenger.get('challenges', []))}"
    )

    print(
        f"Challenger Confidence:"
        f" {challenger.get('confidence', 'N/A')}"
    )

    print(
        f"Debate Rounds:       "
        f"{debate.get('total_rounds', 0)}"
    )

    print(
        f"Debate Converged:    "
        f"{debate.get('converged', 'N/A')}"
    )

    print(
        f"Debate Stop Reason:  "
        f"{debate.get('stop_reason', 'N/A')}"
    )

    print(
        f"Withdrawn Claims:    "
        f"{len(debate.get('withdrawn_claims', []))}"
    )

    print(
        f"Open Challenges:     "
        f"{len(debate.get('open_challenge_ids', []))}"
    )

    # --------------------------------------------------------
    # POLICY
    # --------------------------------------------------------

    print()
    print("-" * 72)
    print("POLICY / SUITABILITY")
    print("-" * 72)

    policy = (
        state.policy_result
        or {}
    )

    print(
        f"Policy Status:       "
        f"{policy.get('policy_status', 'N/A')}"
    )

    print(
        f"Cost Status:         "
        f"{policy.get('cost_status', 'N/A')}"
    )

    print(
        f"Suitability Status:  "
        f"{policy.get('suitability_status', 'N/A')}"
    )

    print(
        f"Critical Failure:    "
        f"{policy.get('has_critical_failure', 'N/A')}"
    )

    print(
        f"Policy Confidence:   "
        f"{policy.get('confidence', 'N/A')}"
    )

    print(
        f"Rule Version:        "
        f"{policy.get('rule_version', 'N/A')}"
    )

    # --------------------------------------------------------
    # GOVERNANCE
    # --------------------------------------------------------

    print()
    print("-" * 72)
    print("FIREWALL / TRUST / GOVERNANCE")
    print("-" * 72)

    gate = (
        state.governance_gate
        or {}
    )

    print(
        f"Firewall Status:     "
        f"{state.firewall_status or 'N/A'}"
    )

    print(
        f"Hallucination Flags: "
        f"{len(state.hallucination_flags)}"
    )

    print(
        f"Material Conflicts:  "
        f"{gate.get('material_conflicts', 'N/A')}"
    )

    print(
        f"Trust Score:         "
        f"{state.trust_score if state.trust_score is not None else 'N/A'}"
    )

    print(
        f"Trust Band:          "
        f"{gate.get('band', 'N/A')}"
    )

    print(
        f"Governance Gate:     "
        f"{gate.get('gate', 'N/A')}"
    )

    blocked_claims = (
        gate.get(
            "blocked_claim_ids",
            [],
        )
        or []
    )

    print(
        f"Blocked Claims:      "
        f"{len(blocked_claims)}"
    )

    # --------------------------------------------------------
    # ADAPTIVE SUPERVISOR
    # --------------------------------------------------------

    print()
    print("-" * 72)
    print("ADAPTIVE SUPERVISOR")
    print("-" * 72)

    supervisor = (
        state.supervisor_result
        or {}
    )

    print(
        f"Selected Route:      "
        f"{supervisor.get('route', 'N/A')}"
    )

    print(
        f"Reason Code:         "
        f"{supervisor.get('reason_code', 'N/A')}"
    )

    print(
        f"Human Review:        "
        f"{state.human_review_required}"
    )

    print(
        f"Retry Count:         "
        f"{state.retry_count}"
    )

    print(
        f"Reason:              "
        f"{supervisor.get('reason', 'N/A')}"
    )

    # --------------------------------------------------------
    # AUDIT
    # --------------------------------------------------------

    print()
    print("-" * 72)
    print("AUDIT")
    print("-" * 72)

    print(
        f"Route Records:       "
        f"{len(state.route_history)}"
    )

    print(
        f"Risk Flags:          "
        f"{len(state.risk_flags)}"
    )

    print(
        f"Claim Verifications: "
        f"{len(state.claim_verifications)}"
    )

    print(
        f"Evidence Records:    "
        f"{len(state.evidence_ledger)}"
    )

    # --------------------------------------------------------
    # FINAL RESULT
    # --------------------------------------------------------

    print()
    print("=" * 72)
    print("                         FINAL RESULT")
    print("=" * 72)

    print(
        f"Fund:                "
        f"{FUND_ID}"
    )

    print(
        f"Governance Gate:     "
        f"{gate.get('gate', 'N/A')}"
    )

    print(
        f"Supervisor Route:    "
        f"{supervisor.get('route', 'N/A')}"
    )

    print(
        f"Trust Score:         "
        f"{state.trust_score if state.trust_score is not None else 'N/A'}"
    )

    print(
        f"Human Review:        "
        f"{state.human_review_required}"
    )

    print("=" * 72)
    print("                       REVIEW COMPLETE")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()