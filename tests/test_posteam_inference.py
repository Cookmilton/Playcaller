"""Posteam gap-fill (``warehouse.posteam_inference``) for processed warehouse Plays."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

import warehouse.posteam_inference as pti

from warehouse.models import DataSource, DerivedPlayFeatures, Game as WarehouseGame, GameStatus, GameType, Play
from warehouse.posteam_inference import (
    SOURCE_FEED,
    SOURCE_MISSING,
    TAG_INFERRED_BFILL,
    TAG_INFERRED_DEFENSE,
    TAG_INFERRED_FFILL,
    TAG_INFERRED_MODE,
    TAG_INFERRED_OFFENSE,
    _drive_modal_feed_only,
    infer_warehouse_plays,
    is_skip_play_type,
)
from warehouse.taxonomy import PlayResult, PlayType


def _wh() -> WarehouseGame:
    return WarehouseGame(
        id="g1",
        source=DataSource.NFLVERSE,
        external_game_id="demo",
        season=2025,
        week=1,
        game_type=GameType.REG,
        home_team="KC",
        away_team="BUF",
        game_date=date(2025, 9, 5),
        status=GameStatus.FINAL,
    )


def _feat(play_id: str, drive_number: int) -> DerivedPlayFeatures:
    return DerivedPlayFeatures(
        play_id=play_id,
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
        drive_number=drive_number,
    )


@dataclass(kw_only=True)
class PlayR1(Play):
    """Optional ``offense_team`` for §10.1 rule 1 (not in on-disk schema)."""

    offense_team: str | None = None


def _feed_src(s: str | None) -> str:
    if s is None or not str(s).strip():
        return "missing"
    return "feed"


def _play(
    pid: str,
    seq: int,
    *,
    wtype: PlayType = PlayType.PASS,
    wres: PlayResult = PlayResult.COMPLETE,
    pos: str | None = None,
    deff: str | None = None,
) -> Play:
    return Play(
        id=pid,
        game_id="g1",
        external_play_id=f"e{seq}",
        play_sequence=seq,
        quarter=1,
        score_offense=0,
        score_defense=0,
        play_type=wtype,
        play_result=wres,
        first_down=True,
        touchdown=False,
        turnover=False,
        raw_description="",
        scoring_possession_team=pos,
        display_possession_team=pos,
        posteam_source=_feed_src(pos),
        defense_team=deff,
        defteam_source=_feed_src(deff),
    )


def test_rule_1_offense_team() -> None:
    p = PlayR1(
        id="p0",
        game_id="g1",
        external_play_id="a",
        play_sequence=1,
        quarter=1,
        score_offense=0,
        score_defense=0,
        play_type=PlayType.PASS,
        play_result=PlayResult.COMPLETE,
        first_down=True,
        touchdown=False,
        turnover=False,
        raw_description="",
        scoring_possession_team=None,
        display_possession_team=None,
        posteam_source="missing",
        defense_team=None,
        defteam_source="missing",
        offense_team="KC",
    )
    fd = _feat("p0", 1)
    o, tags, _res = infer_warehouse_plays([p], [fd], _wh())
    assert o[0].scoring_possession_team is None
    assert o[0].display_possession_team == "KC"
    assert tags[0] == TAG_INFERRED_OFFENSE


def test_rule_2_inverse_defense() -> None:
    p0 = _play("p0", 1, pos=None, deff="KC")
    o, tags, _ = infer_warehouse_plays([p0], [_feat("p0", 1)], _wh())
    assert o[0].scoring_possession_team is None
    assert o[0].display_possession_team == "BUF"
    assert tags[0] == TAG_INFERRED_DEFENSE


def test_rule_3_drive_forward_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pti, "INFER_ENABLE_DRIVE_HEURISTICS", True)
    p0 = _play("p0", 1, pos="KC")
    p1 = _play("p1", 2, pos=None)
    o, tags, _ = infer_warehouse_plays(
        [p0, p1], [_feat("p0", 1), _feat("p1", 1)], _wh()
    )
    assert o[1].scoring_possession_team is None
    assert o[1].display_possession_team == "KC"
    assert tags[1] == TAG_INFERRED_FFILL


def test_rule_4_drive_backward_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pti, "INFER_ENABLE_DRIVE_HEURISTICS", True)
    p0 = _play("p0", 1, pos=None)
    p1 = _play("p1", 2, pos="KC")
    o, tags, _ = infer_warehouse_plays(
        [p0, p1], [_feat("p0", 1), _feat("p1", 1)], _wh()
    )
    assert o[0].scoring_possession_team is None
    assert o[0].display_possession_team == "KC"
    assert tags[0] == TAG_INFERRED_BFILL


def test_rule_5_drive_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pti, "INFER_ENABLE_DRIVE_HEURISTICS", True)
    monkeypatch.setattr(pti, "INFER_ENABLE_DRIVE_MODE", True)
    p0 = _play("p0", 1, pos="KC")
    p1 = _play("p1", 2, pos="KC")
    p2 = _play("p2", 3, pos="KC")
    p3 = _play("p3", 4, pos=None)
    pls = [p0, p1, p2, p3]
    feats = [_feat("p0", 1), _feat("p1", 1), _feat("p2", 1), _feat("p3", 1)]
    o, tags, _ = infer_warehouse_plays(pls, feats, _wh())
    assert o[3].scoring_possession_team is None
    assert o[3].display_possession_team == "KC"
    assert tags[3] in (TAG_INFERRED_FFILL, TAG_INFERRED_MODE)


def test_rule_5_modal_unit() -> None:
    p0 = _play("p0", 1, pos="KC")
    p1 = _play("p1", 2, pos="KC")
    p2 = _play("p2", 3, pos="KC")
    assert _drive_modal_feed_only([p0, p1, p2], "KC", "BUF") == "KC"


def test_existing_value_never_overridden() -> None:
    p = PlayR1(
        id="p0",
        game_id="g1",
        external_play_id="a",
        play_sequence=1,
        quarter=1,
        score_offense=0,
        score_defense=0,
        play_type=PlayType.PASS,
        play_result=PlayResult.COMPLETE,
        first_down=True,
        touchdown=False,
        turnover=False,
        raw_description="",
        scoring_possession_team="KC",
        display_possession_team="KC",
        posteam_source="feed",
        defense_team="BUF",
        defteam_source="feed",
        offense_team="BUF",
    )
    o, tags, _ = infer_warehouse_plays([p], [_feat("p0", 1)], _wh())
    assert o[0].display_possession_team == "KC"
    assert o[0].scoring_possession_team == "KC"
    assert tags[0] == SOURCE_FEED


def test_no_inference_across_drive_boundary() -> None:
    p0 = _play("p0", 1, pos="KC")
    p1 = _play("p1", 2, pos=None, deff=None)
    o, tags, _ = infer_warehouse_plays(
        [p0, p1], [_feat("p0", 1), _feat("p1", 2)], _wh()
    )
    assert o[1].scoring_possession_team is None
    assert o[1].display_possession_team is None
    assert tags[1] == SOURCE_MISSING


def test_kickoff_excluded_from_possession_coverage() -> None:
    k = PlayType.KICKOFF
    pls: list[Play] = []
    feats: list[DerivedPlayFeatures] = []
    for i in range(10):
        pls.append(_play(f"p{i}", i + 1, wtype=PlayType.PASS, pos="KC"))
        feats.append(_feat(f"p{i}", 1))
    pls.append(_play("pk", 11, wtype=k, pos=None, deff=None))
    feats.append(_feat("pk", 2))
    o, _tags, res = infer_warehouse_plays(pls, feats, _wh())
    assert res.coverage_possession_after == 1.0
    # Kickoff in its own drive with no fill signals stays empty → overall 10/11
    assert res.coverage_overall_after == pytest.approx(10.0 / 11.0)
    assert is_skip_play_type(k)


def test_priority_order_rule_1_beats_rule_3() -> None:
    p0 = _play("p0", 1, pos="KC")
    p1 = PlayR1(
        id="p1",
        game_id="g1",
        external_play_id="b",
        play_sequence=2,
        quarter=1,
        score_offense=0,
        score_defense=0,
        play_type=PlayType.PASS,
        play_result=PlayResult.COMPLETE,
        first_down=True,
        touchdown=False,
        turnover=False,
        raw_description="",
        scoring_possession_team=None,
        display_possession_team=None,
        posteam_source="missing",
        defense_team=None,
        defteam_source="missing",
        offense_team="BUF",
    )
    o, tags, _ = infer_warehouse_plays(
        [p0, p1], [_feat("p0", 1), _feat("p1", 1)], _wh()
    )
    assert o[1].scoring_possession_team is None
    assert o[1].display_possession_team == "BUF"
    assert tags[1] == TAG_INFERRED_OFFENSE


def test_irrecoverable_drive_stays_missing() -> None:
    p0 = _play("p0", 1, pos=None)
    p1 = _play("p1", 2, pos=None)
    o, tags, _ = infer_warehouse_plays(
        [p0, p1], [_feat("p0", 1), _feat("p1", 1)], _wh()
    )
    assert tags[0] == SOURCE_MISSING
    assert tags[1] == SOURCE_MISSING
    assert o[0].scoring_possession_team is None
    assert o[0].display_possession_team is None


def test_provenance_for_feed_values() -> None:
    p0 = _play("p0", 1, pos="KC")
    o, tags, _ = infer_warehouse_plays([p0], [_feat("p0", 1)], _wh())
    assert tags[0] == SOURCE_FEED
    assert o[0] is p0


def test_recovery_rate_calculation() -> None:
    pls: list[Play] = [
        _play("a", 1, pos=None, deff="KC"),
        _play("b", 2, pos=None, deff="KC"),
        _play("c", 3, pos=None, deff="JAX"),
    ]
    feats = [_feat("a", 1), _feat("b", 2), _feat("c", 3)]
    o, _tags, res = infer_warehouse_plays(pls, feats, _wh())
    assert res.n_originally_missing == 3
    assert res.n_inferred_filled == 2
    assert abs(res.recovery_rate - 2.0 / 3.0) < 1e-6
