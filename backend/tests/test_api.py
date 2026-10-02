"""HTTP API tests. Reviews run inline in mock mode, so no keys or network are needed."""
import io

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    app = create_app(db_path=tmp_path / "api.db", inline_runner=True, static_dir=tmp_path / "no-dist")
    with TestClient(app) as c:
        yield c


def _review(client, fund_id="F001", mandate="balanced_growth"):
    r = client.post("/api/reviews", json={"dataset_id": "demo", "fund_id": fund_id,
                                           "mandate": mandate, "provider": "mock"})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_config_lists_providers_with_bedrock_primary(client):
    cfg = client.get("/api/config").json()
    providers = {p["id"]: p for p in cfg["providers"]}
    assert providers["bedrock"]["primary"] is True
    assert providers["mock"]["available"] is True
    assert providers["groq"]["available"] is False and "GROQ_API_KEY" in providers["groq"]["detail"]
    assert {m["id"] for m in cfg["mandates"]} == {"balanced_growth", "conservative_income"}
    assert cfg["risk_levels"][0] == "very_low"


def test_demo_dataset_is_available(client):
    ds = client.get("/api/datasets/demo").json()
    assert ds["is_demo"] and ds["row_count"] == 3 and ds["rows"][0]["fund_id"] == "F001"


def test_upload_validates_columns(client):
    bad = client.post("/api/datasets", files={"file": ("x.csv", io.BytesIO(b"fund_id,ticker\nF1,AAA\n"))})
    assert bad.status_code == 422 and "Missing required columns" in bad.json()["detail"]

    csv = ("fund_id,fund_name,ticker,expense_ratio,asset_class,risk_level,history_years\n"
           "Z1,Zeta Fund,ZZZ,0.3,Equity,medium,10\n")
    ok = client.post("/api/datasets", files={"file": ("funds.csv", io.BytesIO(csv.encode()))})
    assert ok.status_code == 201 and ok.json()["rows"][0]["fund_name"] == "Zeta Fund"


def test_review_runs_and_is_stored(client):
    review_id = _review(client, "F002")
    detail = client.get(f"/api/reviews/{review_id}").json()
    assert detail["status"] == "completed"
    assert detail["outcome"]["key"] == "finalize"
    assert detail["fund_name"] == "Beta Balanced Fund"
    assert detail["overview"]["policy"]["total"] > 0
    stages = [(e["stage"], e["status"]) for e in detail["events"]]
    assert stages[0] == ("data_steward", "started") and stages[-1] == ("supervisor", "completed")
    assert [r["id"] for r in client.get("/api/reviews").json()] == [review_id]


def test_outcomes_cover_human_review_and_policy_block(client):
    assert client.get(f"/api/reviews/{_review(client, 'F001')}").json()["outcome"]["key"] == "human_review"
    assert client.get(f"/api/reviews/{_review(client, 'F003')}").json()["outcome"]["key"] == "blocked"


def test_events_stream_finishes(client):
    review_id = _review(client)
    with client.stream("GET", f"/api/reviews/{review_id}/events") as resp:
        body = "".join(resp.iter_text())
    assert "event: stage" in body and "event: done" in body


def test_unavailable_provider_is_rejected(client):
    r = client.post("/api/reviews", json={"dataset_id": "demo", "fund_id": "F001",
                                           "mandate": "balanced_growth", "provider": "groq"})
    assert r.status_code == 422 and "Groq is not available" in r.json()["detail"]


def test_unknown_fund_and_mandate_are_rejected(client):
    r = client.post("/api/reviews", json={"dataset_id": "demo", "fund_id": "NOPE",
                                           "mandate": "balanced_growth", "provider": "mock"})
    assert r.status_code == 422
    r = client.post("/api/reviews", json={"dataset_id": "demo", "fund_id": "F001",
                                           "mandate": "nope", "provider": "mock"})
    assert r.status_code == 422


def test_what_if_scenario_compares_against_original(client):
    review_id = _review(client, "F001")          # medium_high risk -> human review
    r = client.post(f"/api/reviews/{review_id}/scenarios", json={"changes": {"risk_level": "medium"}})
    assert r.status_code == 202, r.text
    scenario = client.get(f"/api/scenarios/{r.json()['id']}").json()
    comp = scenario["comparison"]
    assert comp["changes"][0] == {"field": "risk_level", "label": "Risk level",
                                  "before": "medium_high", "after": "medium"}
    assert comp["before"]["outcome"]["key"] == "human_review"
    assert comp["after"]["outcome"]["key"] == "finalize" and comp["outcome_changed"]
    assert "SUIT-002" in comp["rules_now_passing"]
    assert len(client.get(f"/api/reviews/{review_id}/scenarios").json()) == 1
    # scenarios do not appear in the case list
    assert [x["id"] for x in client.get("/api/reviews").json()] == [review_id]


def test_scenario_rejects_unknown_fields(client):
    review_id = _review(client)
    r = client.post(f"/api/reviews/{review_id}/scenarios", json={"changes": {"fund_name": "x"}})
    assert r.status_code == 422


def test_insights_aggregate_completed_reviews(client):
    for f in ("F001", "F002", "F003"):
        _review(client, f)
    ins = client.get("/api/insights").json()
    assert ins["total_reviews"] == 3
    counts = {o["key"]: o["count"] for o in ins["outcomes"]}
    assert counts == {"finalize": 1, "human_review": 1, "blocked": 1, "rework": 0}
    assert sum(b["count"] for b in ins["trust_distribution"]) == 3
    assert ins["components"] and ins["risk_flags"]


def test_delete_removes_review_and_scenarios(client):
    review_id = _review(client)
    client.post(f"/api/reviews/{review_id}/scenarios", json={"changes": {"expense_ratio": 0.2}})
    assert client.delete(f"/api/reviews/{review_id}").status_code == 204
    assert client.get(f"/api/reviews/{review_id}").status_code == 404
    assert client.get(f"/api/reviews/{review_id}/scenarios").json() == []


def test_failed_review_is_recorded(client, monkeypatch):
    import src.orchestration.pipeline as pipeline

    def boom(*a, **k):
        raise RuntimeError("model unavailable")
    monkeypatch.setattr(pipeline, "run_mandateiq", boom)
    detail = client.get(f"/api/reviews/{_review(client)}").json()
    assert detail["status"] == "failed" and "model unavailable" in detail["error"]
    assert detail["outcome"]["key"] == "failed"


def test_seeded_claims_are_caught_by_firewall_and_debate(client):
    r = client.post("/api/reviews", json={"dataset_id": "demo", "fund_id": "F002", "mandate": "balanced_growth",
                                           "provider": "mock", "seed_unsupported_claims": True})
    detail = client.get(f"/api/reviews/{r.json()['id']}").json()
    debate = detail["state"]["debate"]
    assert debate["total_rounds"] >= 2
    assert {w["claim_id"] for w in debate["withdrawn_claims"]} and detail["options"]["seed_unsupported_claims"]
