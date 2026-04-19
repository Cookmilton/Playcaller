"""Canonical bundle validation + pipeline reporting."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from football_history_warehouse.domain.enums import GameStatus, PlayFamily, PlayResultCategory
from football_history_warehouse.domain.identifiers import (
    DriveId,
    GameId,
    ImportJobId,
    LeagueId,
    PlayId,
    SeasonId,
    TeamId,
)
from football_history_warehouse.domain import Game, Play
from football_history_warehouse.domain.competition import Drive, PlayOutcome
from football_history_warehouse.normalization.bundle import CanonicalGameBundle
from football_history_warehouse.normalization.context import GameNormalizationContext
from football_history_warehouse.normalization.espn import normalize_espn_summary_parse_result
from football_history_warehouse.parsers.espn_summary import parse_espn_game_summary_json_file
from football_history_warehouse.reporting.pipeline_report import (
    PipelineOutcome,
    build_import_pipeline_report,
    validation_result_to_dict,
)
from football_history_warehouse.validation import validate_canonical_game_bundle
from football_history_warehouse.validation import codes as vc

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_live_synthetic.json"


def _espn_bundle() -> CanonicalGameBundle:
    parsed = parse_espn_game_summary_json_file(FIXTURE)
    ctx = GameNormalizationContext(
        league_id=LeagueId("league-nfl-test"),
        season_id=SeasonId("season-2024-test"),
        game_id=GameId("game-401test001"),
        team_id_by_external_ref={
            "espn:10": TeamId("team-nyg"),
            "espn:14": TeamId("team-lar"),
        },
        import_job_id=ImportJobId("job-test-1"),
        observed_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        parser_version="test-parser",
    )
    return normalize_espn_summary_parse_result(parsed, ctx)


def test_espn_fixture_passes_validation() -> None:
    bundle = _espn_bundle()
    r = validate_canonical_game_bundle(bundle)
    assert r.ok_to_persist
    d = validation_result_to_dict(r)
    assert d["fatal_count"] == 0


def test_fatal_team_conflict() -> None:
    g = Game(
        game_id=GameId("g1"),
        season_id=SeasonId("s"),
        league_id=LeagueId("l"),
        home_team_id=TeamId("x"),
        away_team_id=TeamId("x"),
        status=GameStatus.SCHEDULED,
    )
    r = validate_canonical_game_bundle(CanonicalGameBundle(game=g, drives=(), plays=(), notices=()))
    assert not r.ok_to_persist
    assert any(i.code == vc.TEAM_IDENTITY_CONFLICT for i in r.fatal_issues)


def test_fatal_unknown_drive_reference() -> None:
    g = Game(
        game_id=GameId("g1"),
        season_id=SeasonId("s"),
        league_id=LeagueId("l"),
        home_team_id=TeamId("h"),
        away_team_id=TeamId("a"),
        status=GameStatus.SCHEDULED,
    )
    o = PlayOutcome(result_category=PlayResultCategory.OTHER)
    p = Play(
        play_id=PlayId("p1"),
        game_id=GameId("g1"),
        drive_id=DriveId("missing-drive"),
        sequence_in_game=0,
        offense_team_id=TeamId("h"),
        defense_team_id=TeamId("a"),
        play_family=PlayFamily.RUN,
        outcome=o,
    )
    r = validate_canonical_game_bundle(CanonicalGameBundle(game=g, drives=(), plays=(p,), notices=()))
    assert not r.ok_to_persist
    assert any(i.code == vc.PLAY_DRIVE_UNKNOWN for i in r.fatal_issues)


def test_pipeline_report_validation_failed() -> None:
    g = Game(
        game_id=GameId("g1"),
        season_id=SeasonId("s"),
        league_id=LeagueId("l"),
        home_team_id=TeamId("h"),
        away_team_id=TeamId("h"),
        status=GameStatus.SCHEDULED,
    )
    bundle = CanonicalGameBundle(game=g, drives=(), plays=(), notices=())
    v = validate_canonical_game_bundle(bundle)
    rep = build_import_pipeline_report(import_job_id="job-1", bundle=bundle, validation=v)
    assert rep.outcome == PipelineOutcome.VALIDATION_FAILED
    assert "fatal" in rep.summary.lower()
    jd = rep.to_json_dict()
    assert jd["validation"]["ok_to_persist"] is False
    assert jd["outcome"] == "validation_failed"


def test_pipeline_report_persisted_ok_path() -> None:
    bundle = _espn_bundle()
    v = validate_canonical_game_bundle(bundle)
    from football_history_warehouse.reporting.pipeline_report import PersistenceAttemptReport

    rep = build_import_pipeline_report(
        import_job_id="job-2",
        bundle=bundle,
        validation=v,
        persistence=PersistenceAttemptReport(
            attempted=True,
            succeeded=True,
            persisted_game_id=str(bundle.game.game_id),
            drive_count=len(bundle.drives),
            play_count=len(bundle.plays),
            provenance_rows_written=4,
        ),
    )
    if v.has_warnings:
        assert rep.outcome == PipelineOutcome.PERSISTED_WITH_WARNINGS
    else:
        assert rep.outcome == PipelineOutcome.PERSISTED_OK
