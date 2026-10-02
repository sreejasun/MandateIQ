// Shapes returned by the MandateIQ API. The full WorkflowState is large and
// loosely structured, so only the parts the interface reads are typed.

export type Tone = "positive" | "caution" | "negative" | "rework" | "neutral";
export type OutcomeKey = "finalize" | "human_review" | "blocked" | "rework" | "failed" | "pending";
export type ProviderId = "bedrock" | "groq" | "mock";
export type RunStatus = "queued" | "running" | "completed" | "failed";

export interface Outcome {
  key: OutcomeKey;
  label: string;
  tone: Tone;
}

export interface ProviderInfo {
  id: ProviderId;
  label: string;
  available: boolean;
  detail: string;
  model: string | null;
  primary: boolean;
}

export interface Mandate {
  id: string;
  name: string;
  objective?: string;
  max_risk_level: string;
  allowed_asset_classes: string[];
  max_expense_ratio: number;
  minimum_history_years: number;
}

export interface ScenarioField {
  label: string;
  type: "number" | "select";
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
}

export interface AppConfig {
  default_provider: ProviderId;
  providers: ProviderInfo[];
  default_mandate: string;
  mandates: Mandate[];
  trust: { finalize_min: number; reanalysis_min: number; weights: Record<string, number>; version?: string };
  risk_levels: string[];
  scenario_fields: Record<string, ScenarioField>;
  required_columns: string[];
}

export type FundRow = Record<string, string | number | null>;

export interface DatasetSummary {
  id: string;
  name: string;
  row_count: number;
  is_demo: number | boolean;
  created_at: string;
}

export interface Dataset {
  id: string;
  name: string;
  is_demo: boolean;
  row_count: number;
  columns: string[];
  rows: FundRow[];
}

export interface ReviewSummary {
  id: string;
  kind: "review" | "scenario";
  parent_id: string | null;
  dataset_id: string;
  fund_id: string;
  fund_name: string | null;
  ticker: string | null;
  mandate: string;
  provider: ProviderId;
  model: string | null;
  status: RunStatus;
  outcome: Outcome;
  trust_score: number | null;
  fund?: FundRow;
  changes?: Record<string, string | number> | null;
  options?: { seed_unsupported_claims?: boolean } | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface StageEvent {
  stage: string;
  status: "started" | "completed" | "failed";
  details: Record<string, unknown>;
  at: string;
}

export interface Overview {
  reasons: string[];
  human_review_items: string[];
  route: string | null;
  route_reason: string | null;
  gate: string | null;
  band: string | null;
  trust_score: number | null;
  quality_score: number | null;
  firewall_status: string | null;
  policy: { policy: string; cost: string; suitability: string; passed: number; total: number };
  committee: {
    proponent_position: string;
    proponent_confidence: number;
    challenger_position: string;
    challenger_confidence: number;
    claims: number;
    challenges: number;
    open_high_challenges: number;
  };
  risk_flags: string[];
}

export interface ToolCall {
  step: number;
  agent: string;
  tool: string;
  input: Record<string, unknown>;
  ok: boolean;
  result_summary: string;
}

export interface RunLog {
  agent: string;
  started_at: string;
  ended_at: string;
  latency_ms: number;
  model_id: string;
  prompt_version: string | null;
  rule_version: string | null;
  confidence: number;
  error: string | null;
}

export interface Claim {
  claim_id: string;
  agent: string;
  claim: string;
  evidence_ids: string[];
  cited_values?: { evidence_id: string; value: unknown }[];
  field?: string | null;
  confidence?: number;
}

export interface Challenge {
  challenge_id: string;
  target_claim: string | null;
  challenge_type: string;
  severity: string;
  reason: string;
  evidence_ids: string[];
  field?: string | null;
  resolved: boolean;
  resolution: string | null;
}

export interface AgentResult {
  agent: string;
  position: string;
  recommended_status: string;
  confidence: number;
  rationale: string;
  generation_mode: string;
  llm_error: string | null;
  run_log?: RunLog;
  trace?: ToolCall[];
}

export interface ProponentResult extends AgentResult {
  claims: Claim[];
  weaknesses_acknowledged: string[];
  missing_evidence: string[];
  withdrawn_claims: Claim[];
}

export interface ChallengerResult extends AgentResult {
  challenges: Challenge[];
  unresolved_questions: string[];
}

export interface Rebuttal {
  challenge_id: string;
  target_claim: string | null;
  action: "CONCEDE" | "DEFEND" | "REVISE";
  response: string;
  evidence_ids: string[];
  revised_claim: string | null;
}

export interface Verdict {
  challenge_id: string;
  verdict: "ACCEPT" | "MAINTAIN";
  reason: string;
}

export interface DebateRound {
  round: number;
  open_challenge_ids: string[];
  rebuttals: Rebuttal[];
  verdicts: Verdict[];
  firewall_status_before: string | null;
  blocked_claim_ids_before: string[];
  proponent_trace: ToolCall[];
  challenger_trace: ToolCall[];
}

export interface WithdrawnClaim {
  claim_id: string;
  claim: string;
  round: number;
  reason: string;
  verification_status: string;
}

export interface Debate {
  enabled: boolean;
  rounds: DebateRound[];
  total_rounds: number;
  max_rounds: number;
  converged: boolean;
  stop_reason: string;
  open_challenge_ids: string[];
  withdrawn_claims: WithdrawnClaim[];
  revised_claim_ids: string[];
  resolved_challenge_ids: string[];
}

export interface EvidenceRecord {
  evidence_id: string;
  case_id: string;
  source: string;
  field: string;
  value: unknown;
  calculation: string;
  created_by: string;
  timestamp: string;
  metadata: Record<string, unknown>;
}

export interface ClaimVerification {
  claim_id: string;
  agent: string;
  status: string;
  checks: string[];
  problems: string[];
  evidence_ids: string[];
}

export interface RuleResult {
  rule_id: string;
  dimension: string;
  severity: string;
  passed: boolean;
  description: string;
  detail: string;
  evidence_ids: string[];
}

export interface TrustComponent {
  name: string;
  score: number;
  weight: number;
  weighted: number;
  explanation: string;
}

export interface Disagreement {
  conflict_id: string;
  conflict_type: string;
  material: boolean;
  severity: string;
  description: string;
  claim_ids: string[];
  resolved?: boolean;
}

export interface RouteStep {
  from_stage: string;
  to_stage: string;
  reason_code: string;
  reason: string;
  timestamp: string;
}

export interface PolicyResult {
  policy_status: string;
  cost_status: string;
  suitability_status: string;
  has_critical_failure: boolean;
  confidence: number;
  rule_results: RuleResult[];
  rule_version: string;
  rationale: string;
  run_log?: RunLog;
}

export interface WorkflowState {
  case_id: string;
  fund_record: FundRow;
  mandate: string | Record<string, unknown>;
  quality_score: number | null;
  quality_report: { quality_score: number; passed: boolean; issues: unknown[] } | null;
  transformation_log: unknown[];
  evidence_ledger: EvidenceRecord[];
  proponent_result: ProponentResult | null;
  challenger_result: ChallengerResult | null;
  policy_result: PolicyResult | null;
  claim_verifications: ClaimVerification[];
  hallucination_flags: Record<string, unknown>[];
  firewall_status: string | null;
  trust_score: number | null;
  trust_components: Record<string, TrustComponent>;
  governance_gate: {
    gate: string;
    reasons: string[];
    band: string;
    raw_score: number;
    caps_applied: string[];
    blocked_claim_ids: string[];
    material_conflicts: number;
  } | null;
  debate: Debate | null;
  disagreements: Disagreement[];
  risk_flags: string[];
  agent_confidences: Record<string, number>;
  route_history: RouteStep[];
  supervisor_result: { route: string; reason_code: string; reason: string; human_review_required: boolean } | null;
  human_review_required: boolean;
  human_review_reason: string | null;
}

export interface ReviewDetail extends ReviewSummary {
  state: WorkflowState | null;
  events: StageEvent[];
  overview: Overview | null;
}

export interface Snapshot {
  outcome: Outcome;
  trust_score: number | null;
  gate: string | null;
  route: string | null;
  firewall_status: string | null;
  policy_status: string;
  cost_status: string;
  suitability_status: string;
  failed_rules: { rule_id: string; description: string; detail: string }[];
  components: Record<string, number>;
}

export interface Comparison {
  changes: { field: string; label: string; before: unknown; after: unknown }[];
  before: Snapshot;
  after: Snapshot;
  trust_delta: number | null;
  outcome_changed: boolean;
  rules_now_failing: string[];
  rules_now_passing: string[];
}

export interface ScenarioDetail extends ReviewDetail {
  comparison: Comparison | null;
}

export interface Insights {
  total_reviews: number;
  average_trust: number | null;
  human_review_rate: number | null;
  firewall_failures: number;
  average_debate_rounds: number | null;
  outcomes: (Outcome & { count: number })[];
  trust_distribution: { range: string; count: number }[];
  components: { key: string; average: number }[];
  risk_flags: { code: string; count: number; example: string }[];
  agent_latency_ms: { agent: string; average: number }[];
  providers: { provider: string; count: number }[];
  trust_by_mandate: { mandate: string; average: number; count: number }[];
}
