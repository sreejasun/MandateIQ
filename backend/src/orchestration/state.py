"""
MandateIQ shared workflow state.

Owner: Narahari

This module defines the validated state that moves through the
MandateIQ orchestration graph.

The shared state supports outputs produced by the Data Steward,
adversarial review agents, governance layer, Adaptive Supervisor,
and downstream UI.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RouteRecord(BaseModel):
    """
    Represents one auditable transition in the MandateIQ workflow.
    """

    from_stage: str
    to_stage: str
    reason_code: str
    reason: str

    supporting_claims: list[str] = Field(
        default_factory=list
    )

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )


class WorkflowState(BaseModel):
    """
    Shared validated state for one MandateIQ review case.

    The schema intentionally supports both named configuration
    references and expanded configuration objects where appropriate
    so independently developed MandateIQ modules can communicate
    through one validated contract.
    """

    # ========================================================
    # CASE INPUT
    # ========================================================

    case_id: str

    dataset_uri: str | None = None

    fund_record: dict[str, Any] = Field(
        default_factory=dict
    )

    # A workflow may reference a named mandate such as
    # "balanced_growth" or carry an already-expanded mandate object.
    mandate: str | dict[str, Any] | None = None


    # ========================================================
    # DATA STEWARD OUTPUTS
    # ========================================================

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )

    data_profile: dict[str, Any] = Field(
        default_factory=dict
    )

    quality_report: dict[str, Any] = Field(
        default_factory=dict
    )

    quality_score: float = 0.0

    transformation_log: list[
        dict[str, Any]
    ] = Field(
        default_factory=list
    )


    # ========================================================
    # DETERMINISTIC METRICS AND EVIDENCE
    # ========================================================

    computed_metrics: dict[str, Any] = Field(
        default_factory=dict
    )

    evidence_ledger: list[
        dict[str, Any]
    ] = Field(
        default_factory=list
    )


    # ========================================================
    # ADVERSARIAL REVIEW OUTPUTS
    # ========================================================

    proponent_result: dict[str, Any] | None = None

    challenger_result: dict[str, Any] | None = None

    policy_result: dict[str, Any] | None = None


    # ========================================================
    # CLAIM VERIFICATION / HALLUCINATION FIREWALL
    # ========================================================

    claim_verifications: list[
        dict[str, Any]
    ] = Field(
        default_factory=list
    )

    hallucination_flags: list[
        dict[str, Any]
    ] = Field(
        default_factory=list
    )

    firewall_status: str | None = None


    # ========================================================
    # AI TRUST SCORE
    # ========================================================

    trust_score: float | None = None

    # Trust components may contain simple numeric values or richer
    # auditable component records containing score, weight,
    # weighted contribution, and explanation.
    trust_components: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )


    # ========================================================
    # GOVERNANCE
    # ========================================================

    # Stores the deterministic governance result produced after
    # verification, trust scoring, and conflict analysis.
    #
    # Example:
    # {
    #     "gate": "FINALIZE_ELIGIBLE",
    #     "reasons": [...],
    #     "band": "HIGH",
    #     "raw_score": 93.7,
    #     "caps_applied": [],
    #     "blocked_claim_ids": [],
    #     "material_conflicts": 0,
    # }
    governance_gate: dict[str, Any] | None = None
    debate: dict[str, Any] | None = None


    # ========================================================
    # CONFLICT AND RISK
    # ========================================================

    disagreements: list[
        dict[str, Any]
    ] = Field(
        default_factory=list
    )

    risk_flags: list[
        str | dict[str, Any]
    ] = Field(
        default_factory=list
    )   

    agent_confidences: dict[
        str,
        float,
    ] = Field(
        default_factory=dict
    )


    # ========================================================
    # ORCHESTRATION
    # ========================================================

    route_history: list[
        RouteRecord
    ] = Field(
        default_factory=list
    )

    retry_count: int = 0

    supervisor_result: dict[
        str,
        Any,
    ] | None = None


    # ========================================================
    # HUMAN REVIEW
    # ========================================================

    human_review_required: bool = False

    human_review_reason: str | None = None


    # ========================================================
    # FINAL DECISION
    # ========================================================

    final_status: str | None = None

    final_rationale: str | None = None


    # ========================================================
    # DECISION SANDBOX
    # ========================================================

    sandbox_original: dict[
        str,
        Any,
    ] | None = None

    sandbox_counterfactual: dict[
        str,
        Any,
    ] | None = None


    # ========================================================
    # AUDIT / VERSION INFORMATION
    # ========================================================

    model_version: str | None = None

    prompt_version: str = "1.0"

    rule_version: str = "1.0"


    # ========================================================
    # VALIDATION
    # ========================================================

    @field_validator("case_id")
    @classmethod
    def validate_case_id(
        cls,
        value: str,
    ) -> str:

        value = value.strip()

        if not value:
            raise ValueError(
                "case_id cannot be empty"
            )

        return value


    @field_validator("quality_score")
    @classmethod
    def validate_quality_score(
        cls,
        value: float,
    ) -> float:

        if not 0.0 <= value <= 1.0:
            raise ValueError(
                "quality_score must be between "
                "0.0 and 1.0"
            )

        return value


    @field_validator("trust_score")
    @classmethod
    def validate_trust_score(
        cls,
        value: float | None,
    ) -> float | None:

        if (
            value is not None
            and not 0.0 <= value <= 100.0
        ):
            raise ValueError(
                "trust_score must be between "
                "0 and 100"
            )

        return value


    @field_validator("retry_count")
    @classmethod
    def validate_retry_count(
        cls,
        value: int,
    ) -> int:

        if value < 0:
            raise ValueError(
                "retry_count cannot be negative"
            )

        return value


def add_route_record(
    state: WorkflowState,
    from_stage: str,
    to_stage: str,
    reason_code: str,
    reason: str,
    supporting_claims: list[str] | None = None,
) -> RouteRecord:
    """
    Add an auditable routing transition to the workflow state.
    """

    record = RouteRecord(
        from_stage=from_stage,
        to_stage=to_stage,
        reason_code=reason_code,
        reason=reason,
        supporting_claims=(
            supporting_claims or []
        ),
    )

    state.route_history.append(
        record
    )

    return record