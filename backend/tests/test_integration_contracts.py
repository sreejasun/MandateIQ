"""Post-merge integration contract tests for Dileep's modules.

Each test checks that a TEAMMATE's module fits the interface Dileep's code relies on.
  * Before the merge (teammate files empty)  -> the test SKIPS and says what it is waiting for.
  * After the merge                          -> the test RUNS; a failure message says exactly
                                                 what does not fit and who needs to change what.

Run with:  python3 -m pytest -rs tests/test_integration_contracts.py
(-rs prints the reason for every skip.)
"""
from __future__ import annotations

import glob
import importlib
import inspect
import re
import typing
from pathlib import Path

import pytest

from tests.fixtures.mock_llm import force_mock_llm  # noqa: F401
from tests.fixtures import review_cases as rc
from tests.review_pipeline import run_review

ROOT = Path(__file__).resolve().parent.parent

# Keys Dileep's modules READ from WorkflowState, and keys run_governance WRITES.
KEYS_READ = ["case_id", "fund_record", "mandate", "metadata", "quality_score", "evidence_ledger",
             "proponent_result", "challenger_result", "policy_result", "risk_flags",
             "agent_confidences", "claim_verifications"]
KEYS_WRITTEN = ["claim_verifications", "hallucination_flags", "firewall_status", "disagreements",
                "trust_score", "trust_components", "risk_flags", "agent_confidences",
                "human_review_required", "human_review_reason"]
PROPOSED_KEYS = ["governance_gate", "debate"]   # additions requested from Narahari

MY_MODULES = ["src.agents.proponent", "src.agents.challenger", "src.agents.policy_suitability",
              "src.agents.tools", "src.agents.tool_agent", "src.agents.debate",
              "src.agents.committee_pipeline",
              "src.agents.llm_bridge", "src.evidence.claims", "src.evidence.conflicts",
              "src.evidence.verifier", "src.trust.hallucination_firewall", "src.trust.trust_score",
              "src.trust.governance", "src.config_loader"]


# ------------------------------------------------------------------ helpers
def _teammate_attr(module: str, attr: str, owner: str):
    """Return module.attr, or skip the test if the teammate has not implemented it yet."""
    try:
        mod = importlib.import_module(module)
    except Exception as exc:  # teammate module present but broken -> that IS an integration failure
        path = ROOT / (module.replace(".", "/") + ".py")
        if path.exists() and path.stat().st_size > 0:
            pytest.fail(f"{module} ({owner}) exists but fails to import: {exc!r}")
        pytest.skip(f"waiting for {owner}: {module} not implemented yet")
    obj = getattr(mod, attr, None)
    if obj is None:
        pytest.skip(f"waiting for {owner}: {module}.{attr} not implemented yet")
    return obj


def _field_names(model) -> set[str]:
    if hasattr(model, "model_fields"):                 # Pydantic v2
        return set(model.model_fields)
    try:                                               # TypedDict / dataclass / annotated class
        return set(typing.get_type_hints(model))
    except Exception:
        return set(getattr(model, "__annotations__", {}))


def _to_teammate_state(WorkflowState, state_dict: dict):
    if hasattr(WorkflowState, "model_validate"):
        names = _field_names(WorkflowState)
        try:
            return WorkflowState.model_validate({k: v for k, v in state_dict.items() if k in names})
        except Exception as exc:
            pytest.fail("Dileep's seeded state does not validate against WorkflowState "
                        f"(Narahari's schema). Fix the schema or the fixture:\n{exc}")
    return state_dict   # TypedDict / plain dict states are just dicts


def _route_name(decision) -> str:
    for attr in ("to", "next", "route", "next_route", "next_node", "destination", "decision"):
        v = decision.get(attr) if isinstance(decision, dict) else getattr(decision, attr, None)
        if v:
            return str(getattr(v, "value", v))
    return str(getattr(decision, "value", decision))


# ------------------------------------------------------------------ always-on checks
@pytest.mark.parametrize("module", MY_MODULES)
def test_my_modules_import(module):
    importlib.import_module(module)


def test_my_public_contract_functions_exist():
    """The interface names frozen in the team requirements doc."""
    from src.agents.challenger import run_challenger
    from src.agents.policy_suitability import run_policy_review
    from src.agents.proponent import run_proponent
    from src.trust.hallucination_firewall import verify_agent_claims
    from src.trust.trust_score import calculate_trust_score
    for fn in (run_proponent, run_challenger, run_policy_review, verify_agent_claims, calculate_trust_score):
        params = list(inspect.signature(fn).parameters)
        assert params[0] == "state", f"{fn.__name__} must take `state` first"


def test_my_config_files_are_valid():
    from src import config_loader as cl
    w = cl.trust_config()["weights"]
    assert abs(sum(w.values()) - 1) < 1e-9, "trust_score.yaml weights must sum to 1"
    g = cl.trust_config()["gates"]
    assert g["reanalysis_min_score"] < g["finalize_min_score"]
    assert set(cl.rules()["required_evidence"]) <= set(cl.rules()["field_aliases"])
    assert {"proponent", "challenger", "prompt_version"} <= set(cl.prompts())
    tol = cl.firewall_config()["numeric_tolerance"]
    assert tol["absolute"] >= 0 and tol["relative"] >= 0


def test_accepts_state_as_plain_dict_and_as_object():
    """Supervisor may pass a dict or a Pydantic/attribute object; both must work."""
    class Obj:
        def __init__(self, d):
            self.__dict__.update(d)
    out_dict = run_review(rc.case_a_clean())
    s = rc.case_a_clean()
    from src.agents.proponent import run_proponent
    assert run_proponent(Obj(s)).claims == run_proponent(s).claims
    assert out_dict["governance_gate"]["gate"] == "FINALIZE_ELIGIBLE"


def test_governance_output_is_json_serialisable():
    """State is persisted to S3 / shown in the UI, so everything written must be JSON-safe."""
    import json
    s = run_review(rc.case_b_unsupported_claim())
    json.dumps(s)


def test_no_secrets_in_my_files():
    pattern = re.compile(r"AKIA[0-9A-Z]{16}|aws_secret_access_key\s*=|AWS_SESSION_TOKEN\s*=\s*\S{20,}")
    files = [p for d in ("src", "config", "tests", "scripts", "docs") for p in (ROOT / d).rglob("*")
             if p.is_file() and p.suffix in {".py", ".yaml", ".yml", ".md", ".sh", ".txt"}]
    leaks = [str(p) for p in files if pattern.search(p.read_text(errors="ignore"))]
    assert not leaks, f"possible credentials committed: {leaks}"


# ------------------------------------------------------------------ Narahari (state / LLM / Supervisor)
def test_workflowstate_has_every_key_my_code_uses():
    WorkflowState = _teammate_attr("src.orchestration.state", "WorkflowState", "Narahari")
    names = _field_names(WorkflowState)
    missing = [k for k in KEYS_READ + KEYS_WRITTEN if k not in names]
    assert not missing, f"WorkflowState (Narahari) is missing keys Dileep's modules use: {missing}"


def test_workflowstate_has_proposed_governance_gate():
    WorkflowState = _teammate_attr("src.orchestration.state", "WorkflowState", "Narahari")
    missing = [k for k in PROPOSED_KEYS if k not in _field_names(WorkflowState)]
    assert not missing, (f"WorkflowState is missing {missing}. `governance_gate` carries the routing "
                         "recommendation and `debate` the committee transcript (run_committee). Either "
                         "Narahari adds them, or the Supervisor reads them another way (then update this test).")


def test_full_review_runs_on_teammate_workflowstate():
    WorkflowState = _teammate_attr("src.orchestration.state", "WorkflowState", "Narahari")
    state = _to_teammate_state(WorkflowState, rc.case_b_unsupported_claim())
    from src.agents.challenger import run_challenger
    from src.agents.policy_suitability import run_policy_review
    from src.agents.proponent import run_proponent
    from src.trust.governance import run_governance

    def put(st, key, val):
        if isinstance(st, dict):
            st[key] = val
            return st
        return type(st).model_validate({**st.model_dump(), key: val})

    state = put(state, "proponent_result", run_proponent(state).model_dump(mode="json"))
    state = put(state, "challenger_result", run_challenger(state).model_dump(mode="json"))
    state = put(state, "policy_result", run_policy_review(state).model_dump(mode="json"))
    update = run_governance(state)
    if hasattr(WorkflowState, "model_validate"):
        names = _field_names(WorkflowState)
        merged = {**state.model_dump(), **{k: v for k, v in update.items() if k in names}}
        try:
            WorkflowState.model_validate(merged)
        except Exception as exc:
            pytest.fail(f"run_governance output has types WorkflowState rejects:\n{exc}")
    assert update["firewall_status"] == "FAIL"


def _find_router():
    for module, attr in (("src.orchestration.routing", "choose_next_route"),
                         ("src.agents.supervisor", "choose_next_route")):
        try:
            fn = getattr(importlib.import_module(module), attr, None)
        except Exception:
            fn = None
        if fn:
            return fn
    pytest.skip("waiting for Narahari: choose_next_route not implemented yet")


def test_supervisor_routes_my_outputs_differently():
    choose_next_route = _find_router()
    try:
        WorkflowState = importlib.import_module("src.orchestration.state").WorkflowState
    except Exception:
        WorkflowState = None
    routes = {}
    for name, fn in (("A", rc.case_a_clean), ("B", rc.case_b_unsupported_claim),
                     ("C", rc.case_c_policy_failure)):
        s = run_review(fn())
        s = _to_teammate_state(WorkflowState, s) if WorkflowState is not None else s
        routes[name] = _route_name(choose_next_route(s)).lower()
    assert len(set(routes.values())) >= 2, f"Supervisor ignores governance output: {routes}"
    assert "human" in routes["C"], f"Critical policy failure must route to human review: {routes}"
    assert routes["A"] != routes["C"], routes


# ------------------------------------------------------------------ Sreeja (evidence ledger / data steward)
def test_evidence_record_model_accepts_my_record_shape():
    EvidenceRecord = _teammate_attr("src.evidence.ledger", "EvidenceRecord", "Sreeja")
    rec = rc.case_a_clean()["evidence_ledger"][0]
    try:
        obj = EvidenceRecord(**rec) if not hasattr(EvidenceRecord, "model_validate") \
            else EvidenceRecord.model_validate(rec)
    except Exception as exc:
        pytest.fail(f"EvidenceRecord (Sreeja) rejects the record shape Dileep reads "
                    f"{sorted(rec)}: {exc}")
    from src.evidence.verifier import EvidenceIndex
    idx = EvidenceIndex({"case_id": "CASE-A", "evidence_ledger": [obj]})
    assert idx.get(rec["evidence_id"]) is not None and idx.has("expense_ratio")


def test_add_evidence_output_is_readable():
    add_evidence = _teammate_attr("src.evidence.ledger", "add_evidence", "Sreeja")
    sig = inspect.signature(add_evidence)
    sample = {"case_id": "CASE-X", "source": "computed_metric", "field": "expense_ratio",
              "value": 0.45, "calculation": "raw field validation", "created_by": "test",
              "metadata": {}}
    kwargs = {k: v for k, v in sample.items() if k in sig.parameters}
    try:
        rec = add_evidence(**kwargs)
    except TypeError as exc:
        pytest.skip(f"add_evidence signature needs arguments this test cannot guess: {exc}")
    from src.evidence.verifier import EvidenceIndex
    idx = EvidenceIndex({"case_id": "CASE-X", "evidence_ledger": [rec]})
    assert idx.has("expense_ratio"), "record from add_evidence has no readable `field`/`value`"
    assert idx.records[0].get("evidence_id"), "record from add_evidence has no `evidence_id`"


def test_data_steward_evidence_resolves_my_required_fields():
    run_data_steward = _teammate_attr("src.agents.data_steward", "run_data_steward", "Sreeja")
    csvs = sorted(glob.glob(str(ROOT / "data" / "sample" / "*.csv")))
    if not csvs:
        pytest.skip("waiting for Sreeja: no sample CSV in data/sample/")
    result = run_data_steward(csvs[0])
    ledger = result.get("evidence_ledger") if isinstance(result, dict) \
        else getattr(result, "evidence_ledger", None)
    if ledger is None:
        pytest.fail("DataStewardResult has no `evidence_ledger`; Dileep's modules cannot read evidence.")
    from src import config_loader
    from src.evidence.verifier import EvidenceIndex
    idx = EvidenceIndex({"case_id": None, "evidence_ledger": ledger})
    required = config_loader.rules()["required_evidence"]
    unresolved = [f for f in required if not idx.has(f)]
    present = sorted({r.get("field") for r in idx.records})
    assert not unresolved, (f"Required evidence {unresolved} not found. Fields Sreeja produced: "
                            f"{present}. Add the matching names to field_aliases in config/rules.yaml.")
    er = idx.number("expense_ratio")
    assert er is None or er == 0 or er >= 0.02, (
        f"expense_ratio={er} looks like a fraction (0.0045) not a percent (0.45); "
        "rules and mandates use percent.")


# ------------------------------------------------------------------ shared files
def test_shared_requirements_include_my_dependencies():
    text = "".join(
        f.read_text().lower() for f in (ROOT / "requirements.txt", ROOT / "requirements-dev.txt") if f.exists()
    )
    if not text.strip():
        pytest.skip("waiting for team: requirements.txt is still empty")
    missing = [p for p in ("pydantic", "pyyaml", "boto3", "pytest") if p not in text]
    assert not missing, f"requirements files are missing review-committee dependencies: {missing}"


def test_gitignore_blocks_env_files():
    gi = ROOT.parent / ".gitignore"
    text = gi.read_text() if gi.exists() else ""
    if not text.strip():
        pytest.skip("waiting for team: .gitignore is still empty")
    assert ".env" in text, ".gitignore must ignore .env so AWS keys are never committed"
