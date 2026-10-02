"""Typed contracts for the adversarial review committee and governance layer.

Owner: Dileep. These are the objects Proponent, Challenger, Policy, Firewall, Conflict
Detection and Trust Score exchange with the Supervisor and the dashboard.
Every model is Pydantic-validated; call .model_dump() to store in WorkflowState.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- enums
class Position(str, Enum):
    SUPPORT = "SUPPORT"
    CONDITIONAL_SUPPORT = "CONDITIONAL_SUPPORT"
    OPPOSE = "OPPOSE"
    CHALLENGE = "CHALLENGE"
    NO_MATERIAL_OBJECTION = "NO_MATERIAL_OBJECTION"


class Status(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"      # policy dimension status
    REJECT = "REJECT"  # agent recommendation


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ChallengeType(str, Enum):
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    WEAK_EVIDENCE = "WEAK_EVIDENCE"
    RISK_CONCERN = "RISK_CONCERN"
    MANDATE_CONFLICT = "MANDATE_CONFLICT"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNSUPPORTED = "UNSUPPORTED"                  # cited evidence does not back the claim
    CONTRADICTED = "CONTRADICTED"                # cited number disagrees with stored value
    INVALID_REFERENCE = "INVALID_REFERENCE"      # evidence ID does not exist
    FOREIGN_EVIDENCE = "FOREIGN_EVIDENCE"        # evidence belongs to another case
    NO_EVIDENCE_CITED = "NO_EVIDENCE_CITED"


class FirewallStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class Gate(str, Enum):
    FINALIZE_ELIGIBLE = "FINALIZE_ELIGIBLE"
    REANALYSIS_SUGGESTED = "REANALYSIS_SUGGESTED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


# ---------------------------------------------------------------- observability
class RunLog(BaseModel):
    """Per-agent run record (requirements §42 Observability, §18 model/prompt/rule version)."""
    agent: str
    case_id: Optional[str] = None
    started_at: str
    ended_at: str
    latency_ms: float
    model_id: str                         # Bedrock model ID, or "mock" / "deterministic"
    prompt_version: Optional[str] = None
    rule_version: Optional[str] = None
    confidence: Optional[float] = None
    input_evidence_ids: list[str] = Field(default_factory=list)
    output_ids: list[str] = Field(default_factory=list)   # claim / challenge / failed-rule IDs
    error: Optional[str] = None


# ---------------------------------------------------------------- claims
class CitedValue(BaseModel):
    evidence_id: str
    value: Any


class AgentClaim(BaseModel):
    claim_id: str
    agent: str
    claim: str
    evidence_ids: list[str] = Field(default_factory=list)
    cited_values: list[CitedValue] = Field(default_factory=list)
    field: Optional[str] = None           # primary evidence field the claim is about
    confidence: Optional[float] = None


class Challenge(BaseModel):
    challenge_id: str
    target_claim: Optional[str] = None    # Proponent claim_id, or None for an independent risk
    challenge_type: ChallengeType
    severity: Severity
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)
    field: Optional[str] = None
    resolved: bool = False                # set by the debate when the Challenger accepts a rebuttal
    resolution: Optional[str] = None


class ToolCall(BaseModel):
    """One step an agent took: which tool it chose, with what input, and what came back."""
    step: int
    agent: str
    tool: str
    input: dict = Field(default_factory=dict)
    ok: bool = True
    result_summary: str = ""


def _conf(v: float) -> float:
    if not 0.0 <= float(v) <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return round(float(v), 3)


class ProponentResult(BaseModel):
    agent: str = "proponent"
    position: Position
    recommended_status: Status
    confidence: float
    claims: list[AgentClaim]
    weaknesses_acknowledged: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    rationale: str = ""
    next_action: str = "CHALLENGE"
    generation_mode: str = "mock"         # mock | bedrock | groq
    llm_error: Optional[str] = None
    prompt_version: Optional[str] = None
    run_log: Optional[RunLog] = None
    trace: list[ToolCall] = Field(default_factory=list)
    withdrawn_claims: list[AgentClaim] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)

    @field_validator("confidence")
    @classmethod
    def _check_confidence(cls, v: float) -> float:
        return _conf(v)


class ChallengerResult(BaseModel):
    agent: str = "challenger"
    position: Position
    recommended_status: Status
    confidence: float
    challenges: list[Challenge]
    unresolved_questions: list[str] = Field(default_factory=list)
    rationale: str = ""
    next_action: str = "POLICY_REVIEW"
    generation_mode: str = "mock"
    llm_error: Optional[str] = None
    prompt_version: Optional[str] = None
    run_log: Optional[RunLog] = None
    trace: list[ToolCall] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)

    @field_validator("confidence")
    @classmethod
    def _check_confidence(cls, v: float) -> float:
        return _conf(v)


# ---------------------------------------------------------------- debate
class Rebuttal(BaseModel):
    challenge_id: str
    target_claim: Optional[str] = None
    action: Literal["CONCEDE", "DEFEND", "REVISE"]
    response: str
    evidence_ids: list[str] = Field(default_factory=list)
    revised_claim: Optional[str] = None
    cited_values: list[CitedValue] = Field(default_factory=list)


class Verdict(BaseModel):
    challenge_id: str
    verdict: Literal["ACCEPT", "MAINTAIN"]
    reason: str


class DebateRound(BaseModel):
    round: int
    open_challenge_ids: list[str]
    rebuttals: list[Rebuttal] = Field(default_factory=list)
    verdicts: list[Verdict] = Field(default_factory=list)
    firewall_status_before: Optional[str] = None
    blocked_claim_ids_before: list[str] = Field(default_factory=list)
    proponent_trace: list[ToolCall] = Field(default_factory=list)
    challenger_trace: list[ToolCall] = Field(default_factory=list)


class WithdrawnClaim(BaseModel):
    claim_id: str
    claim: str
    round: int
    reason: str
    verification_status: str             # firewall status of the claim when it was withdrawn


class DebateResult(BaseModel):
    enabled: bool = True
    rounds: list[DebateRound] = Field(default_factory=list)
    total_rounds: int = 1                  # round 1 = opening statements
    max_rounds: int
    converged: bool
    stop_reason: str
    open_challenge_ids: list[str] = Field(default_factory=list)
    withdrawn_claims: list[WithdrawnClaim] = Field(default_factory=list)
    revised_claim_ids: list[str] = Field(default_factory=list)
    resolved_challenge_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- policy
class RuleResult(BaseModel):
    rule_id: str
    dimension: str                        # policy | cost | suitability
    severity: str                         # CRITICAL | MAJOR | MINOR
    passed: bool
    description: str
    detail: str
    evidence_ids: list[str] = Field(default_factory=list)


class PolicyResult(BaseModel):
    agent: str = "policy_suitability"
    policy_status: Status
    cost_status: Status
    suitability_status: Status
    has_critical_failure: bool
    confidence: float
    rule_results: list[RuleResult]
    risk_flags: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    mandate_id: Optional[str] = None
    rule_version: str
    rationale: str = ""
    next_action: str = "ADJUDICATE"
    run_log: Optional[RunLog] = None
    created_at: str = Field(default_factory=utc_now)


# ---------------------------------------------------------------- firewall
class ClaimVerification(BaseModel):
    claim_id: str
    agent: str
    status: VerificationStatus
    checks: list[str] = Field(default_factory=list)   # human-readable check log
    problems: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class HallucinationFlag(BaseModel):
    flag_id: str
    code: str                             # e.g. CONTRADICTED, INVALID_REFERENCE, MISSING_REQUIRED_EVIDENCE
    agent: Optional[str] = None
    claim_id: Optional[str] = None
    detail: str
    blocking: bool


class ClaimVerificationResult(BaseModel):
    firewall_status: FirewallStatus
    verifications: list[ClaimVerification]
    flags: list[HallucinationFlag]
    verified_claim_ids: list[str]
    blocked_claim_ids: list[str]          # must not influence final routing
    missing_required_evidence: list[str]
    firewall_version: str
    created_at: str = Field(default_factory=utc_now)


# ---------------------------------------------------------------- conflicts
class Conflict(BaseModel):
    conflict_id: str
    conflict_type: str                    # POSITION_DISAGREEMENT | CLAIM_CHALLENGED | POLICY_VS_PROPONENT | ...
    material: bool
    severity: Severity
    description: str
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confirmed_by_firewall: bool = False
    resolved: bool = False


# ---------------------------------------------------------------- trust
class TrustComponent(BaseModel):
    name: str
    score: float                          # 0-100
    weight: float
    weighted: float
    explanation: str


class TrustScoreResult(BaseModel):
    score: float                          # 0-100 after caps
    raw_score: float                      # before caps
    band: str                             # HIGH | MEDIUM | LOW
    components: dict[str, TrustComponent]
    caps_applied: list[str] = Field(default_factory=list)
    recommended_gate: Gate
    gate_reasons: list[str] = Field(default_factory=list)
    trust_version: str
    created_at: str = Field(default_factory=utc_now)
