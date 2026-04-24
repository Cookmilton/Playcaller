from __future__ import annotations

import os
from pathlib import Path

import pytest

from warehouse.models import DerivedPlayFeatures, Play
from warehouse.recommender import (
    HistoricalRecommendation,
    PlayPool,
    Situation,
    clear_cached_pool,
    get_cached_pool,
    match,
    situation_from_game_context,
)
from warehouse.taxonomy import PlayResult, PlayType


def _feat(**k: object) -> DerivedPlayFeatures:
    return DerivedPlayFeatures(
        play_id=str(k.get("play_id", "pid")),
        red_zone=bool(k.get("red_zone", False)),
        goal_to_go=bool(k.get("goal_to_go", False)),
        four_down_territory=bool(k.get("four_down_territory", False)),
        two_minute=bool(k.get("two_minute", False)),
        score_diff=int(k.get("score_diff", 0)),
        score_diff_bucket=str(k.get("score_diff_bucket", "tied")),
        field_zone=str(k.get("field_zone", "own_deep")),
        distance_bucket=str(k.get("distance_bucket", "long")),
        game_script=str(k.get("game_script", "neutral")),
        previous_play_type=k.get("previous_play_type"),
        drive_number=int(k.get("drive_number", 1)),
    )


def _play(
    *,
    pid: str,
    down: int,
    pt: PlayType = PlayType.PASS,
    pr: PlayResult = PlayResult.COMPLETE,
    succ: bool | None = True,
    epa: float | None = 0.1,
) -> Play:
    return Play(
        id=pid,
        game_id="g",
        external_play_id=pid,
        play_sequence=1,
        quarter=1,
        score_offense=0,
        score_defense=0,
        play_type=pt,
        play_result=pr,
        first_down=True,
        touchdown=False,
        turnover=False,
        raw_description="x",
        clock_seconds=900,
        down=down,
        distance=10,
        yardline_100=75,
        epa=epa,
        success=succ,
    )


def _pool_with(rows: list[tuple[Play, DerivedPlayFeatures]]) -> PlayPool:
    p = PlayPool.from_processed_dir(Path("."), seasons=None)
    p._rows = rows
    return p


def test_feature_flag_off_by_default() -> None:
    old = os.environ.pop("WAREHOUSE_RECOMMENDER_ENABLED", None)
    try:
        from warehouse import recommender as wr

        assert wr.is_enabled() is False
    finally:
        if old is not None:
            os.environ["WAREHOUSE_RECOMMENDER_ENABLED"] = old


def test_confident_tier1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAREHOUSE_RECOMMENDER_ENABLED", "1")
    s = Situation(1, "long", "own_deep", "tied", "neutral")
    rows = []
    for i in range(12):
        pid = f"a{i}"
        rows.append((_play(pid=pid, down=1), _feat(play_id=pid)))
    r = match(s, _pool_with(rows))
    assert r.status == "confident"
    assert r.tier_used == 1
    assert r.sample_size == 12


def test_fallback_best_of_partial_tiers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAREHOUSE_RECOMMENDER_ENABLED", "1")
    s = Situation(1, "long", "own_deep", "tied", "neutral")
    rows = []
    # Tier1: 2 plays (wrong game_script on purpose for others — actually need tier1 match)
    for i in range(2):
        pid = f"t1_{i}"
        rows.append((_play(pid=pid, down=1), _feat(play_id=pid, game_script="neutral")))
    # Extra plays: tier1 mismatch (game_script), tier2 match
    for i in range(8):
        pid = f"t2_{i}"
        rows.append((_play(pid=pid, down=1), _feat(play_id=pid, game_script="catch_up")))
    r = match(s, _pool_with(rows))
    assert r.status == "confident"
    assert r.tier_used == 2
    assert r.sample_size == 10


def test_insufficient_empty_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAREHOUSE_RECOMMENDER_ENABLED", "1")
    s = Situation(3, "short", "red_zone", "trail", "desperate")
    r = match(s, _pool_with([]))
    assert r.status == "insufficient"
    assert r.tier_used == 0
    assert r.sample_size == 0
    assert r.candidates == []


def test_candidates_sorted_by_frequency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAREHOUSE_RECOMMENDER_ENABLED", "1")
    s = Situation(1, "long", "own_deep", "tied", "neutral")
    rows = []
    for i in range(6):
        pid = f"r{i}"
        rows.append((_play(pid=pid, down=1, pt=PlayType.RUN), _feat(play_id=pid)))
    for i in range(3):
        pid = f"p{i}"
        rows.append((_play(pid=pid, down=1, pt=PlayType.PASS), _feat(play_id=pid)))
    r = match(s, _pool_with(rows))
    assert r.status == "fallback"
    assert [c.play_type for c in r.candidates[:2]] == [PlayType.RUN, PlayType.PASS]


def test_success_and_epa_ignore_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAREHOUSE_RECOMMENDER_ENABLED", "1")
    s = Situation(1, "long", "own_deep", "tied", "neutral")
    rows = [
        (_play(pid="a0", down=1, succ=True, epa=1.0), _feat(play_id="a0")),
        (_play(pid="a1", down=1, succ=False, epa=1.0), _feat(play_id="a1")),
        (_play(pid="a2", down=1, succ=None, epa=1.0), _feat(play_id="a2")),
        (_play(pid="a3", down=1, succ=True, epa=None), _feat(play_id="a3")),
        (_play(pid="a4", down=1, succ=True, epa=3.0), _feat(play_id="a4")),
        (_play(pid="a5", down=1, succ=True, epa=3.0), _feat(play_id="a5")),
        (_play(pid="a6", down=1, succ=True, epa=3.0), _feat(play_id="a6")),
        (_play(pid="a7", down=1, succ=True, epa=3.0), _feat(play_id="a7")),
        (_play(pid="a8", down=1, succ=True, epa=3.0), _feat(play_id="a8")),
        (_play(pid="a9", down=1, succ=True, epa=3.0), _feat(play_id="a9")),
    ]
    r = match(s, _pool_with(rows))
    assert r.status == "confident"
    pass_c = r.candidates[0]
    assert pass_c.play_type == PlayType.PASS
    assert pass_c.success_rate == pytest.approx(8 / 9)
    assert pass_c.avg_epa == pytest.approx((1.0 + 1.0 + 1.0 + 3.0 * 6) / 9)


def test_integration_week1_common_situation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WAREHOUSE_RECOMMENDER_ENABLED", "1")
    root = Path(__file__).resolve().parents[1] / "data" / "processed"
    if not (root / "2025").is_dir():
        pytest.skip("no processed 2025 data")
    pool = PlayPool.from_processed_dir(root, seasons=[2025])
    ctx = type(
        "C",
        (),
        {
            "down": 1,
            "distance": 10,
            "territory": "own",
            "yardline": 25,
            "score_diff": 0,
            "quarter": 2,
            "seconds_remaining": 600,
        },
    )()
    sit = situation_from_game_context(ctx)
    r = match(sit, pool)
    assert isinstance(r, HistoricalRecommendation)
    assert r.sample_size >= 0


@pytest.mark.parametrize("val", ("1", "true", "yes"))
def test_flag_enables_detection(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv("WAREHOUSE_RECOMMENDER_ENABLED", val)
    from warehouse import recommender as wr

    assert wr.is_enabled() is True


def test_get_cached_pool_returns_same_instance(tmp_path: Path) -> None:
    clear_cached_pool()
    t = tmp_path / "p"
    t.mkdir()
    assert get_cached_pool(t) is get_cached_pool(t)
    clear_cached_pool()


def test_get_cached_pool_reloads_on_different_root(tmp_path: Path) -> None:
    clear_cached_pool()
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert get_cached_pool(a) is not get_cached_pool(b)
    clear_cached_pool()


def test_clear_cached_pool(tmp_path: Path) -> None:
    clear_cached_pool()
    t = tmp_path / "z"
    t.mkdir()
    first = get_cached_pool(t)
    clear_cached_pool()
    assert get_cached_pool(t) is not first
    clear_cached_pool()


def _capture_info_lines(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture formatted INFO lines (caplog can miss them after long runs mutate root logging)."""
    lines: list[str] = []
    import warehouse.recommender as wr

    real = wr._log.info

    def _wrap(msg: str, *args: object, **kwargs: object) -> None:
        lines.append(msg % args if args else msg)
        real(msg, *args, **kwargs)

    monkeypatch.setattr(wr._log, "info", _wrap)
    return lines


def test_match_logs_confident_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAREHOUSE_RECOMMENDER_ENABLED", "1")
    lines = _capture_info_lines(monkeypatch)
    s = Situation(1, "long", "own_deep", "tied", "neutral")
    rows = [(_play(pid=f"a{i}", down=1), _feat(play_id=f"a{i}")) for i in range(12)]
    match(s, _pool_with(rows))
    assert any("recommender_match status=confident tier=1" in ln for ln in lines)


def test_match_logs_fallback_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAREHOUSE_RECOMMENDER_ENABLED", "1")
    lines = _capture_info_lines(monkeypatch)
    s = Situation(1, "long", "own_deep", "tied", "neutral")
    rows = []
    for i in range(6):
        rows.append((_play(pid=f"r{i}", down=1, pt=PlayType.RUN), _feat(play_id=f"r{i}")))
    for i in range(3):
        rows.append((_play(pid=f"p{i}", down=1, pt=PlayType.PASS), _feat(play_id=f"p{i}")))
    match(s, _pool_with(rows))
    assert any("recommender_match status=fallback" in ln for ln in lines)


def test_match_logs_insufficient_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAREHOUSE_RECOMMENDER_ENABLED", "1")
    lines = _capture_info_lines(monkeypatch)
    s = Situation(3, "short", "red_zone", "trail", "desperate")
    match(s, _pool_with([]))
    assert any("recommender_match status=insufficient tier=0" in ln for ln in lines)
