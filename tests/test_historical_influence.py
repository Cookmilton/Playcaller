"""Conservative historical nudge on family scores (after base heuristic + calibration)."""

from __future__ import annotations

import pytest

from playcaller import FootballPlayPredictor, GameContext
from playcaller.domain import ActualPlayResult
from playcaller.game import Game, complete_drive_from_plays
from playcaller.history import HistoricalInfluenceConfig, build_normalized_plays
from playcaller.history.influence import _unique_games_lane_scale, similarity_tier_strength
from playcaller.state import DriveLogger


def _pre_short_own_25(*, distance: int = 2) -> dict:
    """Pre-snap dict for own 25; default distance matches ``_ctx`` (short to-go)."""
    return {
        "down": 1,
        "distance": int(distance),
        "yardline": 25,
        "territory": "own",
        "quarter": 1,
        "seconds_remaining": 900,
        "score_diff": 0,
    }


def _rows_from_play(*, pre_snap: dict, play: ActualPlayResult, reco_fam: str | None = "inside_zone"):
    g = Game.new_game()
    g.drives = [complete_drive_from_plays([play], possessing_team="offense")]
    linked = {
        "concept_name": play.concept_name,
        "family": play.family,
        "yards_gained": play.yards_gained,
        "result_type": play.result_type,
    }
    aud: dict = {
        "snap_id": "s",
        "status": "closed",
        "drive_epoch": 0,
        "plays_at_recommend": 0,
        "pre_snap": pre_snap,
        "linked_actual": linked,
    }
    if reco_fam:
        aud["selected_family"] = reco_fam
        aud["selected_play_name"] = "X"
        aud["bucket"] = "medium_yardage"
    else:
        aud["selected_family"] = ""
    g.recommendation_audit = [aud]
    return build_normalized_plays(g, source_path="mem.json")


def _rows_clustered_same_game(*, pre_snap: dict, n: int) -> list:
    """Several plays from one ``game_id`` (low independence vs spread across games)."""
    plays_data: list[ActualPlayResult] = []
    audits: list[dict] = []
    for i in range(n):
        p = ActualPlayResult(
            yards_gained=8,
            family="inside_zone",
            play_type="run",
            result_type="first_down",
            first_down=True,
            turnover=False,
        )
        plays_data.append(p)
        linked = {
            "concept_name": p.concept_name,
            "family": p.family,
            "yards_gained": p.yards_gained,
            "result_type": p.result_type,
        }
        audits.append(
            {
                "snap_id": f"s{i}",
                "status": "closed",
                "drive_epoch": 0,
                "plays_at_recommend": i,
                "pre_snap": pre_snap,
                "linked_actual": linked,
                "selected_family": "inside_zone",
                "selected_play_name": "X",
                "bucket": "medium_yardage",
            }
        )
    g = Game.new_game()
    g.drives = [complete_drive_from_plays(plays_data, possessing_team="offense")]
    g.recommendation_audit = audits
    return build_normalized_plays(g, source_path="mem.json")


def _ctx() -> GameContext:
    return GameContext(
        down=1,
        distance=2,
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
        own_timeouts=3,
        opp_timeouts=3,
        weather="clear",
        wind_mph=0,
        qb_limited=False,
        mismatch=None,
        game_mode="normal",
        plays_this_drive=0,
        shown_concepts=[],
        run_plays_this_drive=0,
    )


def test_no_history_identical_scores() -> None:
    pred = FootballPlayPredictor()
    ctx = _ctx()
    dl = DriveLogger()
    g = Game.new_game()
    a = pred.recommend(ctx, dl, g)
    b = pred.recommend(ctx, dl, g, historical_plays=None)
    assert a["scores"] == b["scores"]
    assert b.get("historical_influence", {}).get("reason") == "no_corpus_for_call"
    hm = b.get("historical_metadata") or {}
    assert hm.get("status") == "unavailable"
    assert hm.get("corpus_supplied") is False


def test_empty_historical_plays_skips() -> None:
    pred = FootballPlayPredictor()
    ctx = _ctx()
    dl = DriveLogger()
    g = Game.new_game()
    base = pred.recommend(ctx, dl, g)
    z = pred.recommend(ctx, dl, g, historical_plays=[])
    assert z["scores"] == base["scores"]


def test_favorable_run_history_boosts_run_families() -> None:
    pre = _pre_short_own_25()
    plays: list = []
    for _ in range(12):
        p = ActualPlayResult(
            yards_gained=8,
            family="inside_zone",
            play_type="run",
            result_type="first_down",
            first_down=True,
            turnover=False,
        )
        plays.extend(_rows_from_play(pre_snap=pre, play=p, reco_fam="inside_zone"))

    pred = FootballPlayPredictor()
    ctx = _ctx()
    dl = DriveLogger()
    g = Game.new_game()
    base = pred.recommend(ctx, dl, g)
    adj = pred.recommend(ctx, dl, g, historical_plays=plays)
    assert adj["historical_influence"]["applied"] is True
    meta = adj.get("historical_metadata") or {}
    assert meta.get("status") == "applied"
    assert meta.get("corpus_supplied") is True
    assert meta.get("overall_matches", 0) >= 8
    assert "Historical note" in (meta.get("headline") or "")
    assert adj["scores"]["inside_zone"] > base["scores"]["inside_zone"]
    # Cap: delta should stay modest
    delta = adj["scores"]["inside_zone"] - base["scores"]["inside_zone"]
    assert 0 < delta <= 0.07


def test_poor_pass_history_penalizes_pass_families() -> None:
    pre = _pre_short_own_25()
    plays: list = []
    for _ in range(12):
        p = ActualPlayResult(
            yards_gained=0,
            family="quick_game",
            play_type="pass",
            result_type="interception",
            pass_result="intercepted",
            turnover=True,
            turnover_kind="interception",
        )
        plays.extend(_rows_from_play(pre_snap=pre, play=p, reco_fam="quick_game"))

    pred = FootballPlayPredictor()
    ctx = _ctx()
    dl = DriveLogger()
    g = Game.new_game()
    base = pred.recommend(ctx, dl, g)
    adj = pred.recommend(ctx, dl, g, historical_plays=plays)
    assert adj["historical_influence"]["applied"] is True
    assert adj["scores"]["quick_game"] < base["scores"]["quick_game"]
    delta = adj["scores"]["quick_game"] - base["scores"]["quick_game"]
    assert -0.07 <= delta < 0


def test_tiny_overall_sample_not_applied() -> None:
    pre = _pre_short_own_25()
    plays: list = []
    for _ in range(4):
        p = ActualPlayResult(
            yards_gained=4,
            family="inside_zone",
            play_type="run",
            result_type="short",
        )
        plays.extend(_rows_from_play(pre_snap=pre, play=p))

    pred = FootballPlayPredictor()
    ctx = _ctx()
    dl = DriveLogger()
    g = Game.new_game()
    base = pred.recommend(ctx, dl, g)
    adj = pred.recommend(ctx, dl, g, historical_plays=plays)
    assert adj["historical_influence"]["applied"] is False
    assert adj["scores"] == base["scores"]


def test_predictor_level_enabled_uses_config_plays() -> None:
    pre = _pre_short_own_25()
    plays: list = []
    for _ in range(12):
        p = ActualPlayResult(
            yards_gained=8,
            family="inside_zone",
            play_type="run",
            result_type="first_down",
            first_down=True,
        )
        plays.extend(_rows_from_play(pre_snap=pre, play=p))

    cfg = HistoricalInfluenceConfig(enabled=True, plays=tuple(plays))
    pred = FootballPlayPredictor(historical_influence=cfg)
    ctx = _ctx()
    dl = DriveLogger()
    g = Game.new_game()
    base = FootballPlayPredictor().recommend(ctx, dl, g)
    adj = pred.recommend(ctx, dl, g)
    assert adj["historical_influence"]["applied"] is True
    assert adj["scores"]["inside_zone"] >= base["scores"]["inside_zone"]


def test_similarity_tier_strength_strict_full() -> None:
    assert similarity_tier_strength("strict") == 1.0
    assert similarity_tier_strength("relax_distance") < 1.0


def test_unique_games_lane_scale_monotonic() -> None:
    assert _unique_games_lane_scale(12, 1) < _unique_games_lane_scale(12, 12)
    assert _unique_games_lane_scale(12, 12) == pytest.approx(1.0)


def test_widened_similarity_weaker_lane_nudge_than_strict() -> None:
    """Same qualitative history; relaxed distance tier must not out-strength strict."""
    pre_strict = _pre_short_own_25(distance=2)
    plays_strict: list = []
    for _ in range(12):
        p = ActualPlayResult(
            yards_gained=8,
            family="inside_zone",
            play_type="run",
            result_type="first_down",
            first_down=True,
            turnover=False,
        )
        plays_strict.extend(_rows_from_play(pre_snap=pre_strict, play=p, reco_fam="inside_zone"))

    pre_wide = _pre_short_own_25(distance=5)
    plays_wide: list = []
    for _ in range(12):
        p = ActualPlayResult(
            yards_gained=8,
            family="inside_zone",
            play_type="run",
            result_type="first_down",
            first_down=True,
            turnover=False,
        )
        plays_wide.extend(_rows_from_play(pre_snap=pre_wide, play=p, reco_fam="inside_zone"))

    pred = FootballPlayPredictor()
    ctx = _ctx()
    dl = DriveLogger()
    g = Game.new_game()
    a = pred.recommend(ctx, dl, g, historical_plays=plays_strict)
    b = pred.recommend(ctx, dl, g, historical_plays=plays_wide)
    assert a["historical_influence"]["similarity_tier"] == "strict"
    assert b["historical_influence"]["similarity_tier"] == "relax_distance"
    ra = float((a["historical_influence"].get("run_lane") or {}).get("adjustment") or 0.0)
    rb = float((b["historical_influence"].get("run_lane") or {}).get("adjustment") or 0.0)
    assert ra > 1e-6
    assert rb > 1e-6
    assert rb < ra


def test_clustered_games_weaker_lane_nudge_than_spread() -> None:
    pre = _pre_short_own_25(distance=2)
    spread: list = []
    for _ in range(12):
        p = ActualPlayResult(
            yards_gained=8,
            family="inside_zone",
            play_type="run",
            result_type="first_down",
            first_down=True,
            turnover=False,
        )
        spread.extend(_rows_from_play(pre_snap=pre, play=p, reco_fam="inside_zone"))
    clustered = _rows_clustered_same_game(pre_snap=pre, n=12)

    pred = FootballPlayPredictor()
    ctx = _ctx()
    dl = DriveLogger()
    g = Game.new_game()
    a = pred.recommend(ctx, dl, g, historical_plays=spread)
    b = pred.recommend(ctx, dl, g, historical_plays=clustered)
    assert a["historical_influence"]["applied"] is True
    assert b["historical_influence"]["applied"] is True
    ra = float((a["historical_influence"].get("run_lane") or {}).get("adjustment") or 0.0)
    rb = float((b["historical_influence"].get("run_lane") or {}).get("adjustment") or 0.0)
    assert ra > 1e-6
    assert rb > 1e-6
    assert rb < ra
    assert int(a["historical_influence"].get("overall_unique_games") or 0) == 12
    assert int(b["historical_influence"].get("overall_unique_games") or 0) == 1


def test_historical_metadata_matches_influence_debug() -> None:
    pre = _pre_short_own_25()
    plays: list = []
    for _ in range(12):
        p = ActualPlayResult(
            yards_gained=8,
            family="inside_zone",
            play_type="run",
            result_type="first_down",
            first_down=True,
            turnover=False,
        )
        plays.extend(_rows_from_play(pre_snap=pre, play=p, reco_fam="inside_zone"))

    pred = FootballPlayPredictor()
    ctx = _ctx()
    dl = DriveLogger()
    g = Game.new_game()
    out = pred.recommend(ctx, dl, g, historical_plays=plays)
    hi = out["historical_influence"] or {}
    hm = out["historical_metadata"] or {}
    assert hm["overall_matches"] == hi["overall_matches"]
    assert hm["similarity_tier"] == hi["similarity_tier"]
    rl = hi.get("run_lane") or {}
    hm_r = hm.get("run_lane") or {}
    if hm_r:
        assert hm_r["n"] == rl.get("n")
        assert hm_r["adjustment"] == pytest.approx(float(rl.get("adjustment") or 0.0), abs=1e-4)
        if rl.get("success_rate") is not None:
            assert hm_r["success_rate"] == pytest.approx(float(rl["success_rate"]), abs=1e-5)


def test_per_family_deltas_within_config_cap() -> None:
    pre = _pre_short_own_25()
    plays: list = []
    for _ in range(12):
        p = ActualPlayResult(
            yards_gained=8,
            family="inside_zone",
            play_type="run",
            result_type="first_down",
            first_down=True,
            turnover=False,
        )
        plays.extend(_rows_from_play(pre_snap=pre, play=p, reco_fam="inside_zone"))

    pred = FootballPlayPredictor()
    ctx = _ctx()
    dl = DriveLogger()
    g = Game.new_game()
    out = pred.recommend(ctx, dl, g, historical_plays=plays)
    cap = float((out["historical_influence"].get("config") or {}).get("max_abs_adjustment") or 0.06)
    for _fam, row in (out["historical_influence"].get("per_family") or {}).items():
        assert abs(float(row.get("delta") or 0.0)) <= cap + 1e-6


def test_influence_debug_includes_baseline_and_inputs_when_applied() -> None:
    pre = _pre_short_own_25()
    plays: list = []
    for _ in range(12):
        p = ActualPlayResult(
            yards_gained=8,
            family="inside_zone",
            play_type="run",
            result_type="first_down",
            first_down=True,
            turnover=False,
        )
        plays.extend(_rows_from_play(pre_snap=pre, play=p, reco_fam="inside_zone"))

    pred = FootballPlayPredictor()
    ctx = _ctx()
    dl = DriveLogger()
    g = Game.new_game()
    out = pred.recommend(ctx, dl, g, historical_plays=plays)
    hi = out["historical_influence"]
    assert hi["applied"] is True
    assert "baseline_scores_for_history" in hi
    inputs = hi.get("influence_inputs") or {}
    assert inputs.get("similarity_tier") == "strict"
    assert inputs.get("similarity_tier_strength") == pytest.approx(1.0)
    assert inputs.get("situation_dampener") == pytest.approx(1.0)
    rl = hi.get("run_lane") or {}
    assert "adjustment_pre_cap" in rl
    assert "unique_games_scale" in rl
    assert "success_evaluable_scale" in rl
