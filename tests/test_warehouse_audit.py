"""Tests for :mod:`warehouse.audit` (processed JSON aggregate validation + quality)."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from warehouse.audit import (
    audit_processed,
    audit_summary_to_json_dict,
    compute_distribution_stats,
    discover_processed_json_paths,
    filter_affected_files,
    filtered_issue_totals,
)


def _base_game(*, gid: str = "aaaaaaaaaaaaaaaa", ext: str = "2025_01_BUF_KC") -> dict:
    return {
        "id": gid,
        "source": "NFLVERSE",
        "external_game_id": ext,
        "season": 2025,
        "week": 1,
        "game_type": "REG",
        "home_team": "KC",
        "away_team": "BUF",
        "game_date": "2025-09-05",
        "status": "FINAL",
        "final_home_score": 24,
        "final_away_score": 21,
    }


def _base_play(
    *,
    pid: str,
    seq: int,
    y100: int = 50,
) -> dict:
    return {
        "id": pid,
        "game_id": "aaaaaaaaaaaaaaaa",
        "external_play_id": str(seq),
        "play_sequence": seq,
        "quarter": 1,
        "score_offense": 0,
        "score_defense": 0,
        "play_type": "PASS",
        "play_result": "COMPLETE",
        "first_down": False,
        "touchdown": False,
        "turnover": False,
        "raw_description": "test play",
        "clock_seconds": 900,
        "possession_team": "BUF",
        "defense_team": "KC",
        "down": 1,
        "distance": 10,
        "yardline_100": y100,
        "yards_gained": 0,
    }


def _feat(play_id: str, drive: int = 1) -> dict:
    return {
        "play_id": play_id,
        "red_zone": False,
        "goal_to_go": False,
        "four_down_territory": False,
        "two_minute": False,
        "score_diff": 0,
        "score_diff_bucket": "even",
        "field_zone": "mid",
        "distance_bucket": "short",
        "game_script": "neutral",
        "previous_play_type": None,
        "drive_number": drive,
    }


def _payload(*, plays: list[dict], feats: list[dict], game: dict | None = None) -> dict:
    return {
        "schema_version": "2.0",
        "game": game or _base_game(),
        "plays": plays,
        "features": feats,
    }


def test_audit_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    root.mkdir()
    s = audit_processed(root)
    assert s.total_files == 0
    assert s.total_games == 0
    assert s.total_plays == 0
    assert s.validation_issue_total == 0
    assert s.quality_issue_total == 0
    assert s.counts_by_rule == ()
    assert s.affected_files == ()
    assert s.load_errors == ()


def test_audit_one_clean_game(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    week = root / "2025" / "week_01"
    week.mkdir(parents=True)
    p1 = _base_play(pid="p1", seq=1)
    f1 = _feat("p1")
    data = _payload(plays=[p1], feats=[f1])
    (week / "gameclean.json").write_text(json.dumps(data), encoding="utf-8")

    s = audit_processed(root)
    assert s.total_files == 1
    assert s.total_games == 1
    assert s.total_plays == 1
    assert s.validation_issue_total == 0
    assert s.quality_issue_total == 0
    assert s.affected_files == ()
    assert s.total_drives == 1


def test_audit_validation_issue_clock_monotonic(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    week = root / "2025" / "week_01"
    week.mkdir(parents=True)
    p1 = _base_play(pid="p1", seq=1)
    p2 = {**_base_play(pid="p2", seq=2), "clock_seconds": 920}
    f1 = _feat("p1")
    f2 = _feat("p2")
    (week / "bad.json").write_text(json.dumps(_payload(plays=[p1, p2], feats=[f1, f2])), encoding="utf-8")

    s = audit_processed(root)
    assert s.validation_issue_total == 1
    assert s.quality_issue_total == 0
    rules = {(ic.category, ic.rule_name, ic.count) for ic in s.counts_by_rule}
    assert ("validation", "clock_monotonic", 1) in rules
    assert len(s.affected_files) == 1
    assert s.affected_files[0].issue_counts_by_rule.get("clock_monotonic") == 1


def test_audit_quality_issue_missing_situation(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    week = root / "2025" / "week_01"
    week.mkdir(parents=True)
    p1 = {**_base_play(pid="p1", seq=1), "down": None}
    f1 = _feat("p1")
    (week / "qual.json").write_text(json.dumps(_payload(plays=[p1], feats=[f1])), encoding="utf-8")

    s = audit_processed(root)
    assert s.validation_issue_total == 0
    assert s.quality_issue_total == 1
    assert any(ic.rule_name == "missing_situation" and ic.count == 1 for ic in s.counts_by_rule)
    assert s.affected_files[0].quality_count == 1


def test_audit_mixed_two_files_sorting_stable(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    w = root / "2025" / "week_01"
    w.mkdir(parents=True)
    # clean
    c_play = _base_play(pid="c1", seq=1)
    c_feat = _feat("c1")
    (w / "zzz_clean.json").write_text(json.dumps(_payload(plays=[c_play], feats=[c_feat])), encoding="utf-8")
    # validation clock_monotonic + quality missing_situation (same file)
    p1 = _base_play(pid="a1", seq=1)
    p2 = {**_base_play(pid="a2", seq=2), "clock_seconds": 920, "down": None, "distance": None}
    f1 = _feat("a1")
    f2 = _feat("a2")
    (w / "aaa_messy.json").write_text(json.dumps(_payload(plays=[p1, p2], feats=[f1, f2])), encoding="utf-8")

    s = audit_processed(root)
    assert s.total_files == 2
    by_rule = {(ic.category, ic.rule_name): ic.count for ic in s.counts_by_rule}
    assert by_rule[("validation", "clock_monotonic")] == 1
    assert by_rule[("quality", "missing_situation")] == 1
    cats = [ic.category for ic in s.counts_by_rule]
    assert cats == sorted(cats)
    for i in range(len(s.counts_by_rule) - 1):
        a, b = s.counts_by_rule[i], s.counts_by_rule[i + 1]
        if a.category == b.category and a.count == b.count:
            assert a.rule_name <= b.rule_name


def test_discover_season_week_filter(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    (root / "2025" / "week_01").mkdir(parents=True)
    (root / "2025" / "week_02").mkdir(parents=True)
    (root / "2025" / "week_01" / "a.json").write_text("{}", encoding="utf-8")
    (root / "2025" / "week_02" / "b.json").write_text("{}", encoding="utf-8")

    all_p = discover_processed_json_paths(root)
    assert len(all_p) == 2
    w1 = discover_processed_json_paths(root, season=2025, week=1)
    assert [p.name for p in w1] == ["a.json"]


def test_audit_unreadable_json_recorded(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    week = root / "2025" / "week_01"
    week.mkdir(parents=True)
    (week / "bad.json").write_text("{ not json", encoding="utf-8")
    p1 = _base_play(pid="p1", seq=1)
    (week / "good.json").write_text(json.dumps(_payload(plays=[p1], feats=[_feat("p1")])), encoding="utf-8")

    s = audit_processed(root)
    assert s.total_files == 2
    assert s.total_games == 1
    assert len(s.load_errors) == 1
    assert "bad.json" in s.load_errors[0][0]


def test_filtered_issue_totals_and_file_filter(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    w = root / "2025" / "week_01"
    w.mkdir(parents=True)
    p1 = _base_play(pid="p1", seq=1)
    p2 = {**_base_play(pid="p2", seq=2), "clock_seconds": 920}
    (w / "v.json").write_text(
        json.dumps(_payload(plays=[p1, p2], feats=[_feat("p1"), _feat("p2")])),
        encoding="utf-8",
    )

    s = audit_processed(root)
    v0, q0 = filtered_issue_totals(s, rule_filter=None)
    assert v0 == 1 and q0 == 0
    v1, q1 = filtered_issue_totals(s, rule_filter=frozenset({"clock_monotonic"}))
    assert v1 == 1 and q1 == 0
    v2, q2 = filtered_issue_totals(s, rule_filter=frozenset({"duplicate_play_sequence"}))
    assert v2 == 0 and q2 == 0

    shown = filter_affected_files(s, rule_filter=frozenset({"clock_monotonic"}), search_text="")
    assert len(shown) == 1
    shown2 = filter_affected_files(s, rule_filter=frozenset({"clock_monotonic"}), search_text="nope")
    assert shown2 == []


def test_audit_summary_json_dict_paths_are_strings(tmp_path: Path) -> None:
    from warehouse.audit import AuditSummary, AffectedFile, IssueCount

    p = tmp_path / "x.json"
    af = AffectedFile(
        path=p,
        season=1,
        week=1,
        game_id="g",
        external_game_id="e",
        validation_count=0,
        quality_count=0,
        issue_counts_by_rule={},
    )
    s = AuditSummary(
        root=Path("/tmp/root"),
        total_files=0,
        total_games=0,
        total_plays=0,
        total_drives=None,
        validation_issue_total=0,
        quality_issue_total=0,
        counts_by_rule=(IssueCount(rule_name="r", category="quality", count=1),),
        affected_files=(af,),
        scanned_paths=(),
        load_errors=(),
        diagnostics=None,
    )
    d = audit_summary_to_json_dict(s)
    assert isinstance(d["root"], str)
    assert isinstance(d["affected_files"][0]["path"], str)
    assert d.get("diagnostics") is None


def test_distribution_stats_basic() -> None:
    ds = compute_distribution_stats([10.0, 20, 30, 40, 50])
    assert ds.median == 30.0
    ref = statistics.quantiles([10, 20, 30, 40, 50], n=100, method="inclusive")
    assert abs(ds.p25 - float(ref[24])) < 1e-9
    assert abs(ds.p75 - float(ref[74])) < 1e-9
    assert abs(ds.p95 - float(ref[94])) < 1e-9


def test_outlier_detection_iqr(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    wk = root / "2025" / "week_01"
    wk.mkdir(parents=True)
    for i in range(9):
        n = 40 + i * 2
        plays = [_base_play(pid=f"p{j}", seq=j + 1) for j in range(n)]
        feats = [_feat(plays[j]["id"], drive=1) for j in range(n)]
        (wk / f"g{i}.json").write_text(
            json.dumps(
                _payload(plays=plays, feats=feats, game={**_base_game(), "id": f"gid{i:02d}"})
            ),
            encoding="utf-8",
        )
    p_lo = [
        _base_play(pid="p1", seq=1, y100=50),
        _base_play(pid="p2", seq=2, y100=50),
    ]
    f_lo = [_feat("p1", drive=1), _feat("p2", drive=1)]
    (wk / "outlier.json").write_text(
        json.dumps(_payload(plays=p_lo, feats=f_lo, game={**_base_game(), "id": "outliergid"})),
        encoding="utf-8",
    )
    s = audit_processed(root)
    d = s.diagnostics
    assert d is not None
    assert any(
        o.metric == "plays_per_game" and o.direction == "low" for o in d.outliers
    )


def test_invalid_yards_outlier(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    wk = root / "2025" / "week_01"
    wk.mkdir(parents=True)
    p1 = {**_base_play(pid="p1", seq=1), "yards_gained": 150}
    f1 = _feat("p1")
    (wk / "bad_yds.json").write_text(
        json.dumps(_payload(plays=[p1], feats=[f1])),
        encoding="utf-8",
    )
    s = audit_processed(root)
    assert s.diagnostics is not None
    assert any(o.metric == "invalid_yards" and o.value >= 1.0 for o in s.diagnostics.outliers)


def test_completeness_required_field_missing(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    wk = root / "2025" / "week_01"
    wk.mkdir(parents=True)
    p1 = {**_base_play(pid="p1", seq=1), "down": None}
    f1 = _feat("p1")
    (wk / "missdown.json").write_text(
        json.dumps(_payload(plays=[p1], feats=[f1])),
        encoding="utf-8",
    )
    s = audit_processed(root)
    comp = s.diagnostics.completeness if s.diagnostics else ()
    down_row = next((c for c in comp if c.field == "down"), None)
    assert down_row is not None
    assert down_row.required is True
    assert down_row.missing_rows == 1
    assert down_row.affected_games == 1


def test_health_signal_degraded_when_all_rules_silent(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    wk = root / "2025" / "week_01"
    wk.mkdir(parents=True)
    p1 = _base_play(pid="p1", seq=1)
    f1 = _feat("p1")
    (wk / "clean.json").write_text(
        json.dumps(_payload(plays=[p1], feats=[f1])),
        encoding="utf-8",
    )
    s = audit_processed(root)
    assert s.diagnostics is not None
    assert s.diagnostics.health_signal == "degraded"
    assert s.validation_issue_total == 0 and s.quality_issue_total == 0


def test_top_suspicious_deterministic_tie_break(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    wk = root / "2025" / "week_01"
    wk.mkdir(parents=True)
    p1 = _base_play(pid="p1", seq=1)
    f1 = _feat("p1")
    for name, gid in (("a_first.json", "zgame"), ("z_second.json", "agame")):
        (wk / name).write_text(
            json.dumps(
                _payload(plays=[p1], feats=[f1], game={**_base_game(), "id": gid})
            ),
            encoding="utf-8",
        )
    s = audit_processed(root)
    ts = s.diagnostics.top_suspicious
    assert len(ts) == 2
    paths = [t.path.name for t in ts]
    assert paths == ["a_first.json", "z_second.json"]


def test_no_diagnostics_flag_returns_none(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    wk = root / "2025" / "week_01"
    wk.mkdir(parents=True)
    p1 = _base_play(pid="p1", seq=1)
    f1 = _feat("p1")
    (wk / "g.json").write_text(json.dumps(_payload(plays=[p1], feats=[f1])), encoding="utf-8")
    s0 = audit_processed(root, compute_diagnostics=True)
    s1 = audit_processed(root, compute_diagnostics=False)
    assert s0.diagnostics is not None
    assert s1.diagnostics is None
    assert s0.total_games == s1.total_games and s0.total_plays == s1.total_plays
