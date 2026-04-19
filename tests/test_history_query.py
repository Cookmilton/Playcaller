"""Similar-situation query over normalized historical plays."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult, GameContext
from playcaller.game import Game, complete_drive_from_plays
from playcaller.history import (
    HistoryCorpus,
    build_normalized_plays,
    query_similar_plays,
    query_similar_plays_from_context,
    query_similar_plays_from_corpus_context,
    situation_signature_from_context,
)


def _game_one_play(*, pre_snap: dict, play: ActualPlayResult, reco_fam: str | None = "inside_zone"):
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
        aud["bucket"] = "test_bucket"
    else:
        aud["selected_family"] = ""
    g.recommendation_audit = [aud]
    return build_normalized_plays(g, source_path="mem.json")


def _ctx(**kwargs) -> GameContext:
    base = dict(
        down=1,
        distance=10,
        yardline=25,
        territory="own",
        def_personnel="nickel",
        box_count=7,
        coverage_shell="cover_3",
        blitz_likely=False,
        safeties="single_high",
    )
    base.update(kwargs)
    return GameContext(**base)


def test_query_strict_first_and_ten_own() -> None:
    pre = {
        "down": 1,
        "distance": 10,
        "yardline": 25,
        "territory": "own",
        "quarter": 1,
        "seconds_remaining": 900,
        "score_diff": 0,
    }
    plays = []
    for _ in range(4):
        p = ActualPlayResult(
            yards_gained=5,
            family="inside_zone",
            play_type="run",
            result_type="short",
        )
        plays.extend(_game_one_play(pre_snap=pre, play=p))

    sig = situation_signature_from_context(_ctx())
    res = query_similar_plays(plays, sig, min_matches=3)
    assert res.tier == "strict"
    assert len(res.matches) == 4
    assert res.aggregates.match_count == 4
    assert res.aggregates.avg_yards_gained == 5.0
    assert res.trace["rows_skipped_no_signature"] == 0


def test_query_falls_back_when_sparse() -> None:
    """Query midfield; rows are own_territory — strict 0, relax_field should include neighbors."""
    pre_own = {
        "down": 1,
        "distance": 10,
        "yardline": 25,
        "territory": "own",
        "quarter": 1,
        "seconds_remaining": 900,
        "score_diff": 0,
    }
    plays = []
    for y in range(3):
        p = ActualPlayResult(yards_gained=y, family="quick_game", play_type="pass")
        plays.extend(_game_one_play(pre_snap=pre_own, play=p))

    # Midfield LOS: own 45 -> y100 45 still own_territory in our scheme (<=50)
    # Use own 48 -> y100 48 own_territory; need true midfield 51-60: opponents 43 -> y100 57
    pre_mid = {
        "down": 1,
        "distance": 10,
        "yardline": 43,
        "territory": "opponents",
        "quarter": 1,
        "seconds_remaining": 900,
        "score_diff": 0,
    }
    sig = situation_signature_from_context(
        _ctx(down=1, distance=10, yardline=43, territory="opponents")
    )
    assert sig.field_zone == "midfield"

    res = query_similar_plays(plays, sig, min_matches=5)
    assert res.tier != "strict"
    assert len(res.matches) >= 3
    assert "relax" in res.tier


def test_empty_repository() -> None:
    sig = situation_signature_from_context(_ctx())
    res = query_similar_plays([], sig, min_matches=1)
    assert res.matches == []
    assert res.aggregates.match_count == 0
    assert res.trace["rows_considered"] == 0


def test_rows_without_audit_skipped() -> None:
    g = Game.new_game()
    g.drives = [
        complete_drive_from_plays(
            [ActualPlayResult(yards_gained=1, family="power", play_type="run")],
            possessing_team="offense",
        )
    ]
    plays = build_normalized_plays(g)
    sig = situation_signature_from_context(_ctx())
    res = query_similar_plays(plays, sig, min_matches=1)
    assert res.trace["rows_skipped_no_signature"] == 1
    assert res.matches == []


def test_score_diff_filter() -> None:
    pre0 = {
        "down": 1,
        "distance": 10,
        "yardline": 25,
        "territory": "own",
        "quarter": 1,
        "seconds_remaining": 900,
        "score_diff": 0,
    }
    pre10 = {**pre0, "score_diff": 10}
    plays = _game_one_play(
        pre_snap=pre0,
        play=ActualPlayResult(yards_gained=2, family="power", play_type="run"),
    )
    plays.extend(
        _game_one_play(
            pre_snap=pre10,
            play=ActualPlayResult(yards_gained=3, family="power", play_type="run"),
        )
    )
    sig = situation_signature_from_context(_ctx())
    res = query_similar_plays(plays, sig, min_matches=1, score_diff_max=3)
    assert len(res.matches) == 1
    assert res.matches[0].score_diff == 0


def test_query_from_context_wrapper() -> None:
    pre = {
        "down": 2,
        "distance": 7,
        "yardline": 30,
        "territory": "own",
        "quarter": 2,
        "seconds_remaining": 800,
        "score_diff": -3,
    }
    plays = _game_one_play(
        pre_snap=pre,
        play=ActualPlayResult(yards_gained=8, family="draw", play_type="run"),
    )
    ctx = _ctx(down=2, distance=7, yardline=30, territory="own", score_diff=-3)
    res = query_similar_plays_from_context(plays, ctx, min_matches=1)
    assert len(res.matches) == 1
    assert res.tier == "strict"


def test_run_pass_breakdown() -> None:
    pre = {
        "down": 1,
        "distance": 10,
        "yardline": 25,
        "territory": "own",
        "quarter": 1,
        "seconds_remaining": 900,
        "score_diff": 0,
    }
    plays = _game_one_play(
        pre_snap=pre,
        play=ActualPlayResult(yards_gained=4, family="inside_zone", play_type="run"),
        reco_fam="inside_zone",
    )
    plays.extend(
        _game_one_play(
            pre_snap=pre,
            play=ActualPlayResult(yards_gained=0, family="quick_game", play_type="pass"),
            reco_fam="dropback_pass",
        )
    )
    sig = situation_signature_from_context(_ctx())
    res = query_similar_plays(plays, sig, min_matches=1)
    assert res.aggregates.by_recommended_run_pass.get("run_family", 0) >= 1
    assert res.aggregates.by_actual_run_pass.get("pass_family", 0) >= 1


def test_corpus_helper_empty() -> None:
    corpus = HistoryCorpus(plays=[])
    res = query_similar_plays_from_corpus_context(corpus, _ctx(), min_matches=1)
    assert res.matches == []
