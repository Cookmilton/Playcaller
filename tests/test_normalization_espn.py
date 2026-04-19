"""ESPN summary → canonical domain normalization."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from football_history_warehouse.domain.enums import GameStatus, PlayFamily, PlayResultCategory
from football_history_warehouse.domain.identifiers import GameId, ImportJobId, LeagueId, SeasonId, TeamId
from football_history_warehouse.normalization.context import GameNormalizationContext
from football_history_warehouse.normalization.espn import normalize_espn_summary_parse_result
from football_history_warehouse.normalization.exceptions import NormalizationError
from football_history_warehouse.parsers.espn_summary import parse_espn_game_summary_json_file

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_live_synthetic.json"


def _ctx() -> GameNormalizationContext:
    return GameNormalizationContext(
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


def test_normalize_synthetic_fixture() -> None:
    parsed = parse_espn_game_summary_json_file(FIXTURE)
    bundle = normalize_espn_summary_parse_result(parsed, _ctx())
    g = bundle.game
    assert g.game_id == GameId("game-401test001")
    assert g.home_team_id == TeamId("team-nyg")
    assert g.away_team_id == TeamId("team-lar")
    assert g.home_score_final == 14
    assert g.away_score_final == 10
    assert g.status == GameStatus.IN_PROGRESS
    assert "espn.event_id" in g.source_extensions
    # current drive skipped (no offense team in fixture)
    assert any(n.code == "drive_skipped_no_offense" for n in bundle.notices)
    assert any(n.code == "period_snapshot_only" for n in bundle.notices)
    # two previous drives only
    assert len(bundle.drives) == 2
    assert len(bundle.plays) == 4
    rush = bundle.plays[0]
    assert rush.play_family == PlayFamily.RUN
    assert rush.outcome.result_category == PlayResultCategory.OTHER
    assert rush.clock_seconds_remaining_in_period == 14 * 60 + 22
    recv = bundle.plays[1]
    assert recv.play_family == PlayFamily.PASS
    assert recv.outcome.result_category == PlayResultCategory.COMPLETE
    td = bundle.plays[3]
    assert td.outcome.is_touchdown is True
    assert td.outcome.result_category == PlayResultCategory.TOUCHDOWN
    assert td.play_family == PlayFamily.PASS


def test_unmapped_team_raises() -> None:
    parsed = parse_espn_game_summary_json_file(FIXTURE)
    bad = GameNormalizationContext(
        league_id=LeagueId("l"),
        season_id=SeasonId("s"),
        game_id=GameId("g"),
        team_id_by_external_ref={},
    )
    with pytest.raises(NormalizationError) as ei:
        normalize_espn_summary_parse_result(parsed, bad)
    assert ei.value.code == "unmapped_team"
