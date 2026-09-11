"""Two-field posteam: scoring (feed) vs display (inference) + :func:`playcaller.implied_scoring.attribute_scoring_points`."""

from __future__ import annotations

import importlib

import pytest

from playcaller.domain import ActualPlayResult
from playcaller.implied_scoring import (
    UnattributableScoreAccumulator,
    attribute_scoring_points,
    points_for_play,
)
from playcaller.game import DRIVE_END_UNKNOWN, Game, complete_drive_from_plays
from warehouse.models import DataSource, DerivedPlayFeatures, Game as WarehouseGame, GameStatus, GameType, Play
from warehouse.posteam_inference import infer_warehouse_plays
from warehouse.taxonomy import PlayResult, PlayType


def test_inferred_does_not_reach_scoring() -> None:
    acc = UnattributableScoreAccumulator()
    p = ActualPlayResult(
        feed_warehouse_play_type=PlayType.PASS.value,
        feed_warehouse_play_result=PlayResult.TOUCHDOWN_PASS.value,
        feed_possession_team_abbr=None,
        display_possession_team_abbr="H",
        posteam_source="inferred_offense_team",
        defteam_source="feed",
        feed_defense_team_abbr="A",
    )
    pt, s = points_for_play(p, home_team="H", away_team="A", unattributable=acc)
    assert (pt, s) == (0, None)
    assert acc.n_unattributable_scores == 1


def test_feed_value_drives_scoring() -> None:
    acc = UnattributableScoreAccumulator()
    p = ActualPlayResult(
        feed_warehouse_play_type=PlayType.PASS.value,
        feed_warehouse_play_result=PlayResult.TOUCHDOWN_PASS.value,
        feed_possession_team_abbr="H",
        display_possession_team_abbr="H",
        posteam_source="feed",
        defteam_source="feed",
        feed_defense_team_abbr="A",
    )
    pt, s = points_for_play(p, home_team="H", away_team="A", unattributable=acc)
    assert pt == 6 and s == "home"
    assert acc.n_unattributable_scores == 0


def test_runtime_guard_raises_on_inferred_in_test_mode() -> None:
    p = ActualPlayResult(
        feed_warehouse_play_type=PlayType.PASS.value,
        feed_warehouse_play_result=PlayResult.TOUCHDOWN_PASS.value,
        feed_possession_team_abbr="H",
        posteam_source="inferred_offense_team",
    )
    with pytest.raises(AssertionError):
        attribute_scoring_points(
            p, 6, team_abbr="H", provenance="inferred_offense_team", role="poss"
        )


def test_no_silent_fallback_in_scoring() -> None:
    p = ActualPlayResult(
        feed_warehouse_play_type=PlayType.PASS.value,
        feed_warehouse_play_result=PlayResult.TOUCHDOWN_PASS.value,
        feed_possession_team_abbr=None,
        display_possession_team_abbr="H",
        posteam_source="inferred_offense_team",
    )
    pt, s = points_for_play(p, home_team="H", away_team="A")
    assert (pt, s) == (0, None)


def test_ui_uses_display_for_resolve_path() -> None:
    from playcaller.reconciliation.play_context import resolve_archived_pre_snap_situation

    p = ActualPlayResult(
        feed_possession_team_abbr=None,
        display_possession_team_abbr="A",
        posteam_source="inferred_defense_team",
    )
    _d, _di, _t, _y, _g, _hs, _aw, poss, _opp, prov = resolve_archived_pre_snap_situation(
        p, 0, None, type("R", (), {"start_field_position": None})(),
        prior_play=None,
        offense_team_abbr="H",
        defense_team_abbr="A",
    )
    assert poss == "A"
    assert prov.get("possession_team") == "warehouse_display"


def test_unattributable_counter_increments() -> None:
    acc = UnattributableScoreAccumulator()
    p = ActualPlayResult(
        feed_warehouse_play_type=PlayType.PASS.value,
        feed_warehouse_play_result=PlayResult.TOUCHDOWN_PASS.value,
        feed_possession_team_abbr=None,
        posteam_source="missing",
    )
    points_for_play(p, home_team="H", away_team="A", unattributable=acc)
    assert acc.n_unattributable_scores == 1
    assert acc.unattributable_by_reason.get("missing_feed_posteam") == 1


def test_unattributable_counter_separates_play_types() -> None:
    acc = UnattributableScoreAccumulator()
    p1 = ActualPlayResult(
        feed_warehouse_play_type=PlayType.PASS.value,
        feed_warehouse_play_result=PlayResult.TOUCHDOWN_PASS.value,
        posteam_source="missing",
    )
    p2 = ActualPlayResult(
        feed_warehouse_play_type=PlayType.RUN.value,
        feed_warehouse_play_result=PlayResult.TOUCHDOWN_RUN.value,
        posteam_source="missing",
    )
    for p in (p1, p2):
        points_for_play(p, home_team="H", away_team="A", unattributable=acc)
    assert acc.unattributable_by_play_type.get("PASS", 0) == 1
    assert acc.unattributable_by_play_type.get("RUN", 0) == 1


def test_full_game_scoring_unchanged_when_all_feed_present() -> None:
    d = [
        ActualPlayResult(
            feed_warehouse_play_type=PlayType.PASS.value,
            feed_warehouse_play_result=PlayResult.TOUCHDOWN_PASS.value,
            feed_possession_team_abbr="H",
            display_possession_team_abbr="H",
            posteam_source="feed",
            defteam_source="feed",
            feed_defense_team_abbr="A",
        )
    ]
    g = Game(
        drives=[complete_drive_from_plays(d, end_kind_override=DRIVE_END_UNKNOWN)],
        offense_points=6,
        defense_points=0,
        session_metadata={
            "warehouse_processed": True,
            "warehouse_home_team": "H",
            "warehouse_away_team": "A",
        },
    )
    from playcaller import implied_scoring

    o, de, _ = implied_scoring.implied_totals_and_breakdown_from_warehouse_plays(g)
    assert o == 6 and de == 0


def test_full_game_with_some_missing_feed_undercounts() -> None:
    d = [
        ActualPlayResult(
            feed_warehouse_play_type=PlayType.PASS.value,
            feed_warehouse_play_result=PlayResult.TOUCHDOWN_PASS.value,
            feed_possession_team_abbr=None,
            display_possession_team_abbr="H",
            posteam_source="inferred_offense_team",
        )
    ]
    g = Game(
        drives=[complete_drive_from_plays(d, end_kind_override=DRIVE_END_UNKNOWN)],
        offense_points=6,
        defense_points=0,
        session_metadata={
            "warehouse_processed": True,
            "warehouse_home_team": "H",
            "warehouse_away_team": "A",
        },
    )
    u = UnattributableScoreAccumulator()
    from playcaller import implied_scoring

    o, de, _ = implied_scoring.implied_totals_and_breakdown_from_warehouse_plays(
        g, unattributable=u
    )
    assert o == 0
    assert u.n_unattributable_scores == 1


def test_inference_module_does_not_set_scoring_field() -> None:
    p = Play(
        id="p1",
        game_id="g1",
        external_play_id="1",
        play_sequence=1,
        quarter=1,
        score_offense=0,
        score_defense=0,
        play_type=PlayType.PASS,
        play_result=PlayResult.INCOMPLETE,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="",
        scoring_possession_team=None,
        display_possession_team=None,
        posteam_source="missing",
        defense_team="A",
        defteam_source="feed",
    )
    wh = WarehouseGame(
        id="g",
        source=DataSource.OTHER,
        external_game_id="e",
        season=0,
        week=0,
        game_type=GameType.REG,
        home_team="H",
        away_team="A",
        game_date=__import__("datetime").date(2000, 1, 1),
        status=GameStatus.FINAL,
    )
    f = DerivedPlayFeatures(
        play_id="p1",
        red_zone=False,
        goal_to_go=False,
        four_down_territory=False,
        two_minute=False,
        score_diff=0,
        score_diff_bucket="n",
        field_zone="m",
        distance_bucket="m",
        game_script="n",
        previous_play_type=None,
        drive_number=1,
    )
    o, _t, _ = infer_warehouse_plays([p], [f], wh)
    assert o[0].scoring_possession_team is None


def test_safety_unattributable_without_deffeed() -> None:
    acc = UnattributableScoreAccumulator()
    p = ActualPlayResult(
        feed_warehouse_play_type=PlayType.PASS.value,
        feed_warehouse_play_result=PlayResult.SAFETY.value,
        feed_possession_team_abbr="H",
        posteam_source="feed",
        feed_defense_team_abbr=None,
        defteam_source="missing",
    )
    pt, s = points_for_play(p, home_team="H", away_team="A", unattributable=acc)
    assert (pt, s) == (0, None)
    assert acc.unattributable_by_reason.get("missing_feed_defteam", 0) == 1


def test_separate_scoring_and_display_on_warehouse_play() -> None:
    p = Play(
        id="x",
        game_id="g",
        external_play_id="1",
        play_sequence=1,
        quarter=1,
        score_offense=0,
        score_defense=0,
        play_type=PlayType.PASS,
        play_result=PlayResult.INCOMPLETE,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="",
        scoring_possession_team="KC",
        display_possession_team="BUF",
        posteam_source="feed",
        defense_team="BUF",
        defteam_source="feed",
    )
    assert p.scoring_possession_team == "KC"
    assert p.display_possession_team == "BUF"


def test_no_unified_accessor() -> None:
    m = importlib.import_module("warehouse.models")
    assert not hasattr(m.Play, "effective_posteam")
    assert not hasattr(m.Play, "posteam_or_inferred")
