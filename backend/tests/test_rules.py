"""Policy / cost / suitability rules (Dileep). Rules live in config/rules.yaml + mandates.yaml."""
from tests.fixtures.mock_llm import force_mock_llm  # noqa: F401
from src import config_loader
from src.agents.policy_suitability import CHECKS, run_policy_review
from tests.fixtures import review_cases as rc
from tests.review_pipeline import run_review


def test_every_configured_rule_has_an_implementation():
    for rule in config_loader.rules()["rules"]:
        assert rule["check"] in CHECKS, f"{rule['id']} references unknown check {rule['check']}"
        assert rule["severity"] in {"CRITICAL", "MAJOR", "MINOR"}
        assert rule["dimension"] in {"policy", "cost", "suitability"}


def test_rule_ids_unique():
    ids = [r["id"] for r in config_loader.rules()["rules"]]
    assert len(ids) == len(set(ids))


def test_mandates_have_required_keys():
    for key, m in config_loader.mandates()["mandates"].items():
        for k in ("max_risk_level", "allowed_asset_classes", "max_expense_ratio", "minimum_history_years"):
            assert k in m, f"mandate {key} missing {k}"


def test_policy_rule_negative_expense_ratio():
    r = run_policy_review(rc.case_c_policy_failure())
    failed = {x.rule_id: x for x in r.rule_results if not x.passed}
    assert "POL-002" in failed and failed["POL-002"].severity == "CRITICAL"


def test_policy_rule_disallowed_asset_class():
    r = run_policy_review(rc.case_c_policy_failure())
    assert any(x.rule_id == "SUIT-001" and not x.passed for x in r.rule_results)
    assert r.suitability_status.value == "FAIL"


def test_policy_rule_missing_required_evidence_is_critical():
    r = run_policy_review(rc.case_e_low_evidence())
    assert any(x.rule_id == "POL-001" and not x.passed for x in r.rule_results)
    assert r.has_critical_failure


def test_not_evaluable_rules_are_never_silently_passed_when_serious():
    r = run_policy_review(rc.case_e_low_evidence())
    for x in r.rule_results:
        if x.detail.startswith("NOT EVALUABLE") and x.severity in {"CRITICAL", "MAJOR"}:
            assert not x.passed, f"{x.rule_id} passed without data"


def test_stricter_mandate_changes_outcome_without_code_change():
    s = rc.case_a_clean()
    s["mandate"] = {"id": "custom", "max_risk_level": "medium",
                    "allowed_asset_classes": ["equity"], "max_expense_ratio": 0.40,
                    "minimum_history_years": 3}
    r = run_policy_review(s)
    assert r.cost_status.value == "REVIEW"


def test_conservative_mandate_rejects_equity_fund():
    s = rc.case_a_clean()
    s["mandate"] = "conservative_income"
    r = run_policy_review(s)
    assert r.has_critical_failure  # equity not allowed in conservative_income


def test_critical_failure_escalation():
    s = run_review(rc.case_c_policy_failure())
    assert s["governance_gate"]["gate"] == "HUMAN_REVIEW_REQUIRED"
    assert s["human_review_required"] is True
    assert "Critical policy failure" in s["human_review_reason"]


def test_policy_output_has_contract_keys():
    d = run_policy_review(rc.case_a_clean()).model_dump()
    for k in ("policy_status", "cost_status", "suitability_status", "confidence", "rule_results",
              "risk_flags", "evidence_ids", "next_action", "rule_version", "has_critical_failure"):
        assert k in d
