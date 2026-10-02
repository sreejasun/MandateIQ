"""MandateIQ HTTP API.

Run from the backend/ folder:

    uvicorn api.main:app --reload --port 8000

When frontend/dist exists (after `npm run build`), the same server also serves
the web interface, so the whole app runs as one process.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

# .env at the repository root (preferred) or in backend/. Real environment
# variables always take precedence.
load_dotenv(REPO_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env")

from api import services  # noqa: E402
from api.db import Database  # noqa: E402
from api.jobs import PROVIDERS, Runner, provider_model, provider_status  # noqa: E402
from src import config_loader  # noqa: E402

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

DEMO_DATASET_ID = "demo"
DEMO_DATASET_PATH = BACKEND_DIR / "data" / "sample" / "fund_sample.csv"
PROVIDER_LABELS = {
    "bedrock": "Amazon Bedrock",
    "groq": "Groq",
    "mock": "Mock (offline)",
}


# ============================================================
# REQUEST MODELS
# ============================================================

class ReviewRequest(BaseModel):
    dataset_id: str
    fund_id: str
    mandate: str
    provider: Literal["mock", "bedrock", "groq"] = "mock"
    seed_unsupported_claims: bool = False


class ScenarioRequest(BaseModel):
    changes: dict[str, Any] = Field(min_length=1)


# ============================================================
# APP FACTORY
# ============================================================

def _new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(3).upper()}"


def _summary(record: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in record.items() if k not in ("state", "events")}
    out["outcome"] = services.outcome_meta(record.get("outcome") or "pending")
    return out


def create_app(db_path: str | Path | None = None, inline_runner: bool = False,
               static_dir: str | Path | None = None) -> FastAPI:
    db = Database(db_path or os.environ.get("MANDATEIQ_DB", BACKEND_DIR / "data" / "mandateiq.db"))
    runner = Runner(db, inline=inline_runner)

    interrupted = db.fail_interrupted()
    if interrupted:
        logging.getLogger("mandateiq").warning("%d interrupted review(s) marked as failed.", interrupted)

    db.add_dataset(
        DEMO_DATASET_ID,
        "MandateIQ demo funds",
        DEMO_DATASET_PATH.read_text(),
        len(services.parse_dataset(DEMO_DATASET_PATH.read_text())),
        is_demo=True,
    )

    default_provider = (os.environ.get("LLM_PROVIDER") or "mock").strip().lower()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runner.start()
        yield

    app = FastAPI(title="MandateIQ API", version="2.0.0", lifespan=lifespan)
    app.state.db = db
    app.state.runner = runner

    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------ config
    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        providers = []
        for p in ("bedrock", "groq", "mock"):
            available, detail = provider_status(p)
            providers.append({
                "id": p,
                "label": PROVIDER_LABELS[p],
                "available": available,
                "detail": detail,
                "model": provider_model(p),
                "primary": p == "bedrock",
            })

        mandates_cfg = config_loader.mandates()
        trust_cfg = config_loader.load("trust_score.yaml")
        gates = trust_cfg.get("gates", {})

        return {
            "default_provider": default_provider if default_provider in PROVIDERS else "mock",
            "providers": providers,
            "default_mandate": mandates_cfg.get("default_mandate"),
            "mandates": [
                {"id": k, **v} for k, v in (mandates_cfg.get("mandates") or {}).items()
            ],
            "trust": {
                "finalize_min": gates.get("finalize_min_score", 80),
                "reanalysis_min": gates.get("reanalysis_min_score", 50),
                "weights": trust_cfg.get("weights", {}),
                "version": trust_cfg.get("trust_version"),
            },
            "risk_levels": services.risk_levels(),
            "scenario_fields": services.SCENARIO_FIELDS,
            "required_columns": services.REQUIRED_COLUMNS,
        }

    # ------------------------------------------------------------ datasets
    @app.get("/api/datasets")
    def list_datasets() -> list[dict[str, Any]]:
        return db.list_datasets()

    @app.get("/api/datasets/{dataset_id}")
    def get_dataset(dataset_id: str) -> dict[str, Any]:
        record = db.get_dataset(dataset_id)
        if record is None:
            raise HTTPException(404, "Dataset not found.")
        df = services.parse_dataset(record["csv"])
        return {
            "id": record["id"],
            "name": record["name"],
            "is_demo": bool(record["is_demo"]),
            "row_count": record["row_count"],
            "columns": list(df.columns),
            "rows": services.records(df),
        }

    @app.post("/api/datasets", status_code=201)
    async def upload_dataset(file: UploadFile = File(...)) -> dict[str, Any]:
        raw = await file.read()
        if len(raw) > 5_000_000:
            raise HTTPException(413, "The file is larger than 5 MB.")
        try:
            df = services.parse_dataset(raw)
        except services.DatasetError as exc:
            raise HTTPException(422, str(exc)) from exc
        dataset_id = _new_id("DS")
        db.add_dataset(dataset_id, file.filename or "Uploaded dataset", raw.decode("utf-8-sig"), len(df))
        return get_dataset(dataset_id)

    # ------------------------------------------------------------ reviews
    def _queue(kind: str, dataset_id: str, fund_id: str, mandate: str, provider: str,
               parent_id: str | None = None, changes: dict[str, Any] | None = None,
               options: dict[str, Any] | None = None) -> str:
        available, detail = provider_status(provider)
        if not available:
            raise HTTPException(422, f"{PROVIDER_LABELS[provider]} is not available. {detail}")

        mandates = (config_loader.mandates().get("mandates") or {})
        if mandate not in mandates:
            raise HTTPException(422, f"Unknown mandate '{mandate}'.")

        dataset = db.get_dataset(dataset_id)
        if dataset is None:
            raise HTTPException(404, "Dataset not found.")
        df = services.parse_dataset(dataset["csv"])
        try:
            fund = services.find_fund(df, fund_id)
            if changes:
                services.apply_changes(df, fund_id, changes)
        except services.DatasetError as exc:
            raise HTTPException(422, str(exc)) from exc

        review_id = _new_id("SC" if kind == "scenario" else "FG")
        db.add_review({
            "id": review_id,
            "kind": kind,
            "parent_id": parent_id,
            "dataset_id": dataset_id,
            "fund_id": str(fund["fund_id"]),
            "fund_name": fund.get("fund_name"),
            "ticker": fund.get("ticker"),
            "mandate": mandate,
            "provider": provider,
            "model": provider_model(provider),
            "status": "queued",
            "fund": fund,
            "changes": changes,
            "options": options or {},
        })
        runner.submit(review_id)
        return review_id

    @app.post("/api/reviews", status_code=202)
    def start_review(body: ReviewRequest) -> dict[str, str]:
        return {"id": _queue("review", body.dataset_id, body.fund_id, body.mandate, body.provider,
                             options={"seed_unsupported_claims": body.seed_unsupported_claims})}

    @app.get("/api/reviews")
    def list_reviews() -> list[dict[str, Any]]:
        return [_summary(r) for r in db.list_reviews("review")]

    def _detail(record: dict[str, Any]) -> dict[str, Any]:
        out = _summary(record)
        out["state"] = record.get("state")
        out["events"] = record.get("events") or []
        out["overview"] = services.overview(record["state"]) if record.get("state") else None
        return out

    @app.get("/api/reviews/{review_id}")
    def get_review(review_id: str) -> dict[str, Any]:
        record = db.get_review(review_id)
        if record is None or record["kind"] != "review":
            raise HTTPException(404, "Review not found.")
        return _detail(record)

    @app.delete("/api/reviews/{review_id}", status_code=204)
    def delete_review(review_id: str) -> None:
        record = db.get_review(review_id)
        if record is None:
            raise HTTPException(404, "Review not found.")
        if record["status"] in ("queued", "running"):
            raise HTTPException(409, "Wait for the review to finish before deleting it.")
        db.delete_review(review_id)

    @app.get("/api/reviews/{review_id}/events")
    async def stream_events(review_id: str) -> StreamingResponse:
        if db.get_review(review_id) is None:
            raise HTTPException(404, "Review not found.")

        async def generate():
            sent = 0
            while True:
                record = db.get_review(review_id)
                if record is None:
                    break
                events = record.get("events") or []
                for event in events[sent:]:
                    yield f"event: stage\ndata: {json.dumps(event, default=str)}\n\n"
                sent = len(events)
                if record["status"] in ("completed", "failed"):
                    payload = {"status": record["status"], "error": record.get("error")}
                    yield f"event: done\ndata: {json.dumps(payload)}\n\n"
                    break
                await asyncio.sleep(0.4)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------ scenarios
    @app.post("/api/reviews/{review_id}/scenarios", status_code=202)
    def start_scenario(review_id: str, body: ScenarioRequest) -> dict[str, str]:
        parent = db.get_review(review_id)
        if parent is None or parent["kind"] != "review":
            raise HTTPException(404, "Review not found.")
        if parent["status"] != "completed":
            raise HTTPException(409, "What-if scenarios need a completed review.")
        scenario_id = _queue("scenario", parent["dataset_id"], parent["fund_id"], parent["mandate"],
                             parent["provider"], parent_id=review_id, changes=body.changes,
                             options=parent.get("options"))
        return {"id": scenario_id}

    @app.get("/api/reviews/{review_id}/scenarios")
    def list_scenarios(review_id: str) -> list[dict[str, Any]]:
        return [_summary(r) for r in db.list_reviews("scenario", parent_id=review_id)]

    @app.get("/api/scenarios/{scenario_id}")
    def get_scenario(scenario_id: str) -> dict[str, Any]:
        record = db.get_review(scenario_id)
        if record is None or record["kind"] != "scenario":
            raise HTTPException(404, "Scenario not found.")
        out = _detail(record)
        parent = db.get_review(record["parent_id"])
        out["comparison"] = (
            services.compare(parent["state"], record["state"], parent.get("fund") or {}, record["changes"] or {})
            if record["status"] == "completed" and parent and parent.get("state") else None
        )
        return out

    # ------------------------------------------------------------ insights
    @app.get("/api/insights")
    def get_insights() -> dict[str, Any]:
        return services.insights(db.list_reviews("review", with_state=True))

    # ------------------------------------------------------------ web interface
    dist = Path(static_dir) if static_dir else REPO_DIR / "frontend" / "dist"
    if dist.is_dir() and (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404, "Not found.")
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
