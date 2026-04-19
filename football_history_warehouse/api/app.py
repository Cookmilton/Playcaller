"""
Thin HTTP façade over :class:`~football_history_warehouse.consumer.client.FootballWarehouseClient`.

Run (requires ``FOOTBALL_WAREHOUSE_DATABASE_URL``)::

    uvicorn football_history_warehouse.api.app:app --host 127.0.0.1 --port 8000

Or::

    python -m football_history_warehouse.cli.serve

JSON shapes match ``model_dump(mode="json")`` on review and consumer DTOs.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from football_history_warehouse.api.deps import get_warehouse_client
from football_history_warehouse.api.schemas import (
    PlaysBySituationRequest,
    SituationOutcomeRequest,
    TeamTendencyRequest,
)
from football_history_warehouse.consumer.client import FootballWarehouseClient
from football_history_warehouse.query.pagination import PageParams


@asynccontextmanager
async def lifespan(app: FastAPI):
    echo = os.environ.get("FOOTBALL_WAREHOUSE_SQL_ECHO", "").strip().lower() in ("1", "true", "yes")
    client = FootballWarehouseClient.from_env(echo_sql=echo)
    app.state.warehouse_client = client
    try:
        yield
    finally:
        client.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Football history warehouse",
        description="Read-only JSON API over normalized game history (consumer boundary).",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/games/{game_id}/review")
    def get_game_review(
        game_id: str,
        client: FootballWarehouseClient = Depends(get_warehouse_client),
    ) -> dict[str, Any]:
        pkg = client.get_game_review_package(game_id)
        if pkg is None:
            raise HTTPException(status_code=404, detail="game not found")
        return pkg.model_dump(mode="json")

    @app.post("/v1/plays/by_situation")
    def post_plays_by_situation(
        body: PlaysBySituationRequest,
        client: FootballWarehouseClient = Depends(get_warehouse_client),
    ) -> dict[str, Any]:
        situation = body.situation.to_play_situation_filter()
        try:
            page = PageParams(limit=body.limit, offset=body.offset)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            result = client.get_plays_by_situation(situation, page=page)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    @app.post("/v1/analytics/team_tendency")
    def post_team_tendency(
        body: TeamTendencyRequest,
        client: FootballWarehouseClient = Depends(get_warehouse_client),
    ) -> dict[str, Any]:
        situation = body.situation.to_play_situation_filter()
        try:
            summary = client.get_team_tendency_summary(body.team_id, situation=situation)
        except ValueError as exc:
            # Scope / filter validation vs offense_team conflict
            msg = str(exc).lower()
            code = 400 if "offense_team_id" in msg else 422
            raise HTTPException(status_code=code, detail=str(exc)) from exc
        return summary.model_dump(mode="json")

    @app.post("/v1/analytics/situation_outcome")
    def post_situation_outcome(
        body: SituationOutcomeRequest,
        client: FootballWarehouseClient = Depends(get_warehouse_client),
    ) -> dict[str, Any]:
        situation = body.situation.to_play_situation_filter()
        try:
            summary = client.get_situation_outcome_summary(situation)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return summary.model_dump(mode="json")

    return app


app = create_app()
