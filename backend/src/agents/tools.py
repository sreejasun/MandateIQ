"""Tools the review agents can call (deterministic Python; the LLM decides WHICH to call).

Every call is recorded as a ToolCall in the agent's trace, so the dashboard and demo can show
the agent's reasoning step by step.
"""
from __future__ import annotations

import inspect
import json
from typing import Any

from src import config_loader
from src.agents.policy_suitability import CHECKS
from src.evidence.claims import AgentClaim, CitedValue, ToolCall
from src.evidence.verifier import EvidenceIndex, sget

_SPECS: dict[str, dict] = {
    "list_evidence": {
        "description": "List every verified evidence record for this case (id, field, value, and "
                       "whether the Data Steward flagged it as imputed/low quality).",
        "schema": {"type": "object", "properties": {}},
    },
    "get_evidence": {
        "description": "Get one evidence record by evidence_id, or the latest record for a field "
                       "name such as expense_ratio, risk_level, history_years.",
        "schema": {"type": "object", "properties": {
            "evidence_id": {"type": "string"}, "field": {"type": "string"}}},
    },
    "get_mandate": {
        "description": "Get the illustrative investment mandate for this case (limits and allowed classes).",
        "schema": {"type": "object", "properties": {}},
    },
    "list_rules": {
        "description": "Run every deterministic policy/cost/suitability rule at once and list each "
                       "rule's id, description, severity, pass/fail and the evidence it used. Use "
                       "check_rule only when you need one rule's full detail again.",
        "schema": {"type": "object", "properties": {}},
    },
    "check_rule": {
        "description": "Run one deterministic policy/cost/suitability rule by id (e.g. COST-001, "
                       "SUIT-002) and get pass/fail, detail and the evidence it used.",
        "schema": {"type": "object", "properties": {"rule_id": {"type": "string"}},
                   "required": ["rule_id"]},
    },
    "verify_claim": {
        "description": "Run the Hallucination Firewall on a draft claim BEFORE submitting it. Returns "
                       "VERIFIED or the exact problems (non-existent evidence, misquoted numbers, "
                       "numbers not found in the ledger).",
        "schema": {"type": "object", "properties": {
            "claim": {"type": "string"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "cited_values": {"type": "array", "items": {"type": "object", "properties": {
                "evidence_id": {"type": "string"}, "value": {}}}}},
            "required": ["claim", "evidence_ids"]},
    },
}


def _summary(obj: Any, limit: int = 240) -> str:
    text = json.dumps(obj, default=str)
    return text if len(text) <= limit else text[: limit - 3] + "..."


class ReviewTools:
    def __init__(self, state: Any, agent: str):
        self.state = state
        self.agent = agent
        self.idx = EvidenceIndex(state)
        self.mandate = config_loader.resolve_mandate(sget(state, "mandate"))
        self.trace: list[ToolCall] = []

    # ------------------------------------------------------------ bedrock tool specs
    def specs(self, names: list[str]) -> list[dict]:
        return [{"toolSpec": {"name": n, "description": _SPECS[n]["description"],
                              "inputSchema": {"json": _SPECS[n]["schema"]}}} for n in names]

    # ------------------------------------------------------------ dispatch + trace
    def call(self, name: str, args: dict | None = None) -> tuple[dict, bool]:
        args = args or {}
        fn = getattr(self, f"_t_{name}", None)
        if fn is None:
            out, ok = {"error": f"unknown tool {name}"}, False
        else:
            # Models sometimes add arguments a tool does not take (e.g. case_id); ignore them.
            accepted = inspect.signature(fn).parameters
            call_args = {k: v for k, v in args.items() if k in accepted}
            try:
                out, ok = fn(**call_args), True
            except Exception as exc:  # tool errors are returned to the agent, never raised
                out, ok = {"error": f"{type(exc).__name__}: {exc}"}, False
        self.trace.append(ToolCall(step=len(self.trace) + 1, agent=self.agent, tool=name,
                                   input=args, ok=ok, result_summary=_summary(out)))
        return out, ok

    def record(self, name: str, args: dict, summary: str, ok: bool = True) -> None:
        """Record a non-dispatched step (e.g. the final submit) in the trace."""
        self.trace.append(ToolCall(step=len(self.trace) + 1, agent=self.agent, tool=name,
                                   input=args, ok=ok, result_summary=summary))

    # ------------------------------------------------------------ tools
    def _t_list_evidence(self) -> dict:
        return {"evidence": [{"evidence_id": r.get("evidence_id"), "field": r.get("field"),
                              "value": r.get("value"),
                              "flagged": self.idx.is_flagged(r.get("evidence_id", ""))}
                             for r in self.idx.records]}

    def _t_get_evidence(self, evidence_id: str | None = None, field: str | None = None) -> dict:
        rec = self.idx.get(evidence_id) if evidence_id else self.idx.field(field or "")
        if rec is None:
            return {"found": False, "note": f"no evidence for {evidence_id or field}"}
        return {"found": True, **{k: rec.get(k) for k in
                                  ("evidence_id", "field", "value", "source", "calculation", "metadata")}}

    def _t_get_mandate(self) -> dict:
        return {"mandate": self.mandate}

    def _t_list_rules(self) -> dict:
        # Results are included so an agent needs one call, not one per rule.
        cfg = config_loader.rules()
        rules = []
        for r in cfg["rules"]:
            passed, _, eids = CHECKS[r["check"]](self.idx, self.mandate, cfg)
            rules.append({"rule_id": r["id"], "dimension": r["dimension"], "severity": r["severity"],
                          "description": r["description"], "passed": passed, "evidence_ids": eids})
        return {"rules": rules}

    def _t_check_rule(self, rule_id: str) -> dict:
        cfg = config_loader.rules()
        rule = next((r for r in cfg["rules"] if r["id"] == rule_id), None)
        if rule is None:
            raise ValueError(f"unknown rule {rule_id}; valid ids: {[r['id'] for r in cfg['rules']]}")
        passed, detail, eids = CHECKS[rule["check"]](self.idx, self.mandate, cfg)
        return {"rule_id": rule_id, "description": rule["description"], "severity": rule["severity"],
                "passed": passed, "detail": detail, "evidence_ids": eids}

    def _t_verify_claim(self, claim: str, evidence_ids: list[str],
                        cited_values: list[dict] | None = None) -> dict:
        from src.trust.hallucination_firewall import _allowed_numbers, _verify_claim
        c = AgentClaim(claim_id="DRAFT", agent="proponent", claim=claim, evidence_ids=evidence_ids,
                       cited_values=[CitedValue(**cv) for cv in (cited_values or [])])
        v = _verify_claim(c, self.idx, _allowed_numbers(self.idx, self.mandate))
        return {"status": v.status.value, "problems": v.problems}
