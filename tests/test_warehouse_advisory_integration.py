"""
File-backed SQLite: ``recommend(..., warehouse_advisory=True)`` must not alter scores
and must attach a stable advisory payload shape.
"""

from __future__ import annotations

from playcaller.domain import GameContext
from playcaller.engine import FootballPlayPredictor
from playcaller.game import Game
from playcaller.state import DriveLogger
from playcaller.warehouse.binding import WarehouseBinding

from football_history_warehouse.consumer import FootballWarehouseClient
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import session_scope
from football_history_warehouse.storage.repositories.transactional import insert_minimal_warehouse_chain


def _warehouse_fixture_client(tmp_path):
    """SQLite URL + client + binding aligned to :func:`insert_minimal_warehouse_chain` defaults."""
    url = f"sqlite+pysqlite:///{tmp_path / 'warehouse_advisory.sqlite'}"
    upgrade_to_head(database_url=url)
    client = FootballWarehouseClient.from_database_url(url)
    with session_scope(client._engine) as session:
        ids = insert_minimal_warehouse_chain(
            session,
            job_id="job-wa-1",
            league_id="league-wa",
            season_id="season-wa",
            home_team_id="team-home-wa",
            away_team_id="team-away-wa",
            game_id="game-wa-1",
            drive_id="drive-wa-1",
            play_id="play-wa-1",
        )
    binding = WarehouseBinding(
        league_id=ids.league_id,
        season_id=ids.season_id,
        coached_team_id=ids.home_team_id,
    )
    return client, binding, ids


def _context_matching_minimal_play() -> GameContext:
    """
    Matches the first play from ``insert_minimal_warehouse_chain`` (1&10, own 25 → 75 ytg, Q1, clock 900s).
    """
    return GameContext(
        down=1,
        distance=10,
        yardline=25,
        territory="own",
        def_personnel="nickel",
        box_count=7,
        coverage_shell="cover_3",
        blitz_likely=False,
        safeties="single_high",
        score_diff=0,
        quarter=1,
        seconds_remaining=900,
    )


def test_recommend_warehouse_advisory_preserves_scores_and_payload_shape(tmp_path) -> None:
    client, binding, ids = _warehouse_fixture_client(tmp_path)
    try:
        pred = FootballPlayPredictor()
        dl = DriveLogger()
        g = Game.new_game()
        g.possession = "offense"
        ctx = _context_matching_minimal_play()

        base = pred.recommend(ctx, dl, g, warehouse_advisory=False)
        assert "warehouse_advisory" not in base

        adv = pred.recommend(
            ctx,
            dl,
            g,
            warehouse_advisory=True,
            warehouse_client=client,
            warehouse_binding=binding,
            warehouse_similar_play_limit=12,
        )

        assert base["scores"] == adv["scores"]
        assert base["play_family"] == adv["play_family"]
        assert base["bucket"] == adv["bucket"]

        wa = adv["warehouse_advisory"]
        assert wa["mode"] == "advisory"
        assert wa["scores_were_unchanged"] is True
        assert wa["enabled"] is True
        assert isinstance(wa.get("disclaimer"), str) and wa["disclaimer"]
        assert isinstance(wa.get("situation_summary"), str) and wa["situation_summary"]

        scope = wa["scope_binding"]
        assert scope["league_id"] == ids.league_id
        assert scope["season_id"] == ids.season_id
        assert scope.get("game_id") in (None, "")

        outcome = wa.get("outcome_league_season")
        assert isinstance(outcome, dict)
        assert "total_plays" in outcome
        assert outcome["total_plays"] >= 1

        similar = wa.get("similar_plays")
        assert isinstance(similar, dict)
        assert "plays" in similar
        assert "limit" in similar
        assert "offset" in similar
        assert "has_more" in similar
        assert isinstance(similar["plays"], list)

        tendency = wa.get("offense_team_tendency")
        assert isinstance(tendency, dict)
        assert tendency.get("team_id") == ids.home_team_id
        assert tendency.get("total_plays", 0) >= 1
    finally:
        client.dispose()
