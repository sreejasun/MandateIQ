"""
MandateIQ integrated application pipeline.

Coordinates the completed MandateIQ specialist modules through the
shared WorkflowState contract.

Pipeline:

    Dataset
        ->
    Fund Selection
        ->
    Data Steward / Evidence Ledger
        ->
    Adversarial Committee
        ->
    Policy & Suitability
        ->
    Governance
        ->
    Adaptive Supervisor

One MandateIQ case represents exactly one fund.

The specialist modules retain ownership of their own business logic.
This module only adapts their inputs and outputs into the shared
WorkflowState contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.agents.data_steward import run_data_steward
from src.agents.debate import run_committee
from src.agents.policy_suitability import run_policy_review
from src.agents.supervisor import (
    SupervisorResult,
    run_supervisor,
)
from src.evidence.ledger import clear_evidence
from src.orchestration.state import WorkflowState
from src.trust.governance import run_governance


# ============================================================
# DATASET / FUND SELECTION
# ============================================================

def _load_dataset_frame(
    dataset: pd.DataFrame | str | Path,
) -> pd.DataFrame:
    """
    Load the supplied dataset into a DataFrame.

    A copy is always returned so the caller's DataFrame is never
    modified by MandateIQ fund-selection logic.
    """

    if isinstance(dataset, pd.DataFrame):
        return dataset.copy()

    path = Path(dataset)

    if not path.exists():
        raise FileNotFoundError(
            f"Dataset not found: {path}"
        )

    return pd.read_csv(path)


def _select_dataset_fund(
    dataset: pd.DataFrame | str | Path,
    fund_id: str | None,
) -> pd.DataFrame:
    """
    Select exactly one fund for one MandateIQ review case.

    A multi-row dataset must provide fund_id so evidence from
    different funds cannot be mixed into the same review.

    When the dataset already contains exactly one row, fund_id may
    be omitted.
    """

    frame = _load_dataset_frame(dataset)

    if frame.empty:
        raise ValueError(
            "Dataset contains no fund records."
        )

    # --------------------------------------------------------
    # No explicit fund requested
    # --------------------------------------------------------

    if fund_id is None:

        if len(frame) != 1:
            raise ValueError(
                "Dataset contains multiple funds. "
                "Provide fund_id to select exactly one fund."
            )

        return frame.reset_index(drop=True)

    # --------------------------------------------------------
    # Explicit fund requested
    # --------------------------------------------------------

    if "fund_id" not in frame.columns:
        raise ValueError(
            "fund_id selection was requested, but the dataset "
            "does not contain a 'fund_id' column."
        )

    requested_id = str(fund_id).strip()

    matches = frame[
        frame["fund_id"]
        .astype(str)
        .str.strip()
        == requested_id
    ]

    if matches.empty:
        raise ValueError(
            f"Fund ID '{requested_id}' was not found "
            "in the dataset."
        )

    if len(matches) > 1:
        raise ValueError(
            f"Fund ID '{requested_id}' matched multiple rows. "
            "Each MandateIQ review requires one unique fund."
        )

    return matches.reset_index(drop=True).copy()


# ============================================================
# EVIDENCE ADAPTERS
# ============================================================

def _evidence_to_json(
    records: list[Any],
) -> list[dict[str, Any]]:
    """
    Convert Data Steward EvidenceRecord objects into JSON-safe
    dictionaries consumed by downstream review/governance modules.
    """

    output: list[dict[str, Any]] = []

    for record in records:

        if hasattr(record, "model_dump"):

            output.append(
                record.model_dump(
                    mode="json"
                )
            )

        elif isinstance(record, dict):

            output.append(
                dict(record)
            )

        else:

            raise TypeError(
                "Evidence records must be Pydantic models "
                "or dictionaries."
            )

    return output


# ============================================================
# SHARED STATE ADAPTER
# ============================================================

def _apply_updates(
    state: WorkflowState,
    updates: dict[str, Any],
) -> WorkflowState:
    """
    Merge module updates through WorkflowState validation.

    Re-validating after module boundaries prevents incompatible
    cross-team state from silently entering the workflow.
    """

    data = state.model_dump(
        mode="json"
    )

    data.update(
        updates
    )

    return WorkflowState.model_validate(
        data
    )


# ============================================================
# FUND RECORD
# ============================================================

def _select_fund_record(
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Build a compact fund record from the selected fund's Evidence
    Ledger.

    The complete Evidence Ledger remains authoritative. fund_record
    exists for workflow context and UI display.
    """

    if not evidence:
        return {}

    fund_identifier = (
        evidence[0]
        .get("metadata", {})
        .get("fund_id")
    )

    record: dict[str, Any] = {}

    for item in evidence:

        metadata = item.get(
            "metadata",
            {},
        )

        # Defensive protection against accidental cross-fund evidence.
        if (
            fund_identifier is not None
            and metadata.get("fund_id")
            != fund_identifier
        ):
            continue

        field = item.get(
            "field"
        )

        if field:
            record[field] = item.get(
                "value"
            )

    if fund_identifier is not None:
        record["fund_id"] = fund_identifier

    return record


# ============================================================
# INTEGRATED MANDATEIQ PIPELINE
# ============================================================

def run_mandateiq(
    dataset: pd.DataFrame | str | Path,
    *,
    fund_id: str | None = None,
    case_id: str = "CASE-LIVE-001",
    mandate: str | dict[str, Any] | None = "balanced_growth",
    clear_ledger: bool = True,
    on_stage: Callable[[str, str, dict[str, Any]], None] | None = None,
    demo_injections: dict[str, Any] | None = None,
) -> WorkflowState:
    """
    Execute the integrated MandateIQ review pipeline.

    One invocation represents exactly one fund review.

    Args:
        dataset:
            Pandas DataFrame or CSV path containing fund data.

        fund_id:
            Fund identifier to review.

            Required when the supplied dataset contains multiple rows.
            May be omitted when the dataset contains exactly one row.

        case_id:
            Identifier shared across all workflow stages.

        mandate:
            Named mandate or expanded mandate dictionary.

        clear_ledger:
            Clear the process-local Evidence Ledger before execution.
            Useful for isolated application/demo runs.

        on_stage:
            Optional progress callback, called as
            on_stage(stage, status, details) with status "started" or
            "completed". Used by the API to stream live progress.
            Callback errors never interrupt the review.

        demo_injections:
            Optional demonstration data, e.g. {"proponent_claims": [...]}
            to seed unsupported claims and exercise the Hallucination
            Firewall and debate. Seeded claims are tagged [SEEDED].

    Returns:
        Fully populated WorkflowState containing:

            - Data quality information
            - Evidence Ledger
            - Proponent result
            - Challenger result
            - Debate transcript
            - Policy review
            - Hallucination Firewall result
            - Conflict detection
            - Trust Score
            - Governance gate
            - Adaptive Supervisor routing decision
    """

    def emit(stage: str, status: str, **details: Any) -> None:
        if on_stage is None:
            return
        try:
            on_stage(stage, status, details)
        except Exception:  # progress reporting must never break a review
            pass

    # --------------------------------------------------------
    # Validate / select one fund
    # --------------------------------------------------------

    selected_dataset = _select_dataset_fund(
        dataset=dataset,
        fund_id=fund_id,
    )

    selected_fund_id: str | None = None

    if "fund_id" in selected_dataset.columns:
        selected_fund_id = str(
            selected_dataset.iloc[0]["fund_id"]
        ).strip()

    # --------------------------------------------------------
    # Reset process-local evidence for an isolated run
    # --------------------------------------------------------

    if clear_ledger:
        clear_evidence()

    # --------------------------------------------------------
    # 1. DATA STEWARD
    # --------------------------------------------------------

    emit("data_steward", "started")

    steward = run_data_steward(
        dataset=selected_dataset,
        case_id=case_id,
    )

    evidence = _evidence_to_json(
        steward.evidence_ledger
    )

    # Defensive check:
    # one review case should contain evidence for only one fund.
    evidence_fund_ids = {
        str(
            item.get(
                "metadata",
                {},
            ).get(
                "fund_id"
            )
        )
        for item in evidence
        if item.get(
            "metadata",
            {},
        ).get(
            "fund_id"
        )
        is not None
    }

    if len(evidence_fund_ids) > 1:
        raise RuntimeError(
            "Data Steward produced evidence for multiple funds "
            "inside one MandateIQ review case."
        )

    # --------------------------------------------------------
    # Build shared WorkflowState
    # --------------------------------------------------------

    metadata = dict(
        steward.metadata
    )

    metadata["selected_fund_id"] = (
        selected_fund_id
    )

    if demo_injections:
        metadata["demo_injections"] = dict(
            demo_injections
        )

    # Preserve the original dataset path for auditability even
    # though the Data Steward receives a selected DataFrame.
    if isinstance(
        dataset,
        (str, Path),
    ):
        metadata["dataset_source"] = str(
            dataset
        )

    state = WorkflowState(
        case_id=steward.case_id,

        dataset_uri=(
            str(dataset)
            if isinstance(
                dataset,
                (str, Path),
            )
            else None
        ),

        fund_record=_select_fund_record(
            evidence
        ),

        mandate=mandate,

        metadata=metadata,

        data_profile=dict(
            steward.profile
        ),

        quality_report=dict(
            steward.quality_report
        ),

        quality_score=(
            steward.quality_score
        ),

        transformation_log=list(
            steward.transformations
        ),

        evidence_ledger=evidence,
    )

    # --------------------------------------------------------
    # 2. ADVERSARIAL COMMITTEE
    #
    # Agents v2 performs:
    #
    #   Proponent
    #   Challenger
    #   Tool investigation
    #   Bounded multi-round debate
    # --------------------------------------------------------

    emit(
        "data_steward",
        "completed",
        quality_score=state.quality_score,
        evidence_count=len(evidence),
    )
    emit("committee", "started")

    committee_updates = run_committee(
        state
    )

    state = _apply_updates(
        state,
        committee_updates,
    )

    # --------------------------------------------------------
    # 3. POLICY / COST / SUITABILITY
    # --------------------------------------------------------

    debate = committee_updates.get("debate") or {}
    emit(
        "committee",
        "completed",
        rounds=debate.get("total_rounds"),
        converged=debate.get("converged"),
    )
    emit("policy", "started")

    policy = run_policy_review(
        state
    )

    state = _apply_updates(
        state,
        {
            "policy_result": (
                policy.model_dump(
                    mode="json"
                )
            )
        },
    )

    # --------------------------------------------------------
    # 4. GOVERNANCE
    #
    # run_governance performs:
    #
    #   Hallucination Firewall
    #   Conflict Detection
    #   Trust Score
    #   Governance Gate
    # --------------------------------------------------------

    emit(
        "policy",
        "completed",
        rules_passed=sum(1 for r in policy.rule_results if r.passed),
        rules_total=len(policy.rule_results),
    )
    emit("governance", "started")

    governance_updates = (
        run_governance(
            state
        )
    )

    state = _apply_updates(
        state,
        governance_updates,
    )

    # --------------------------------------------------------
    # 5. ADAPTIVE SUPERVISOR
    # --------------------------------------------------------

    emit(
        "governance",
        "completed",
        trust_score=state.trust_score,
        firewall_status=state.firewall_status,
    )
    emit("supervisor", "started")

    supervisor: SupervisorResult = (
        run_supervisor(
            state
        )
    )

    # run_supervisor mutates WorkflowState by recording:
    #
    #   supervisor_result
    #   route_history
    #   human-review/finalization effects
    #
    # Revalidate the final state before returning it.

    state = WorkflowState.model_validate(
        state.model_dump(
            mode="json"
        )
    )

    # Keep the Supervisor result explicitly available in the
    # returned shared state.

    state.supervisor_result = (
        supervisor.model_dump(
            mode="json"
        )
    )

    emit(
        "supervisor",
        "completed",
        route=state.supervisor_result.get("route")
        if isinstance(state.supervisor_result, dict)
        else None,
    )

    return state