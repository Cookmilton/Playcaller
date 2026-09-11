"""Failure-mode classification for :mod:`warehouse.implied_score_audit`."""

from __future__ import annotations

from pathlib import Path

import pytest

from warehouse.implied_score_audit import (
    DOUBLE_COUNT_DELTA,
    DELTA_LAG,
    ENUM_MISSED_TD,
    MIXED_FEED_INCONSISTENCY,
    POSTEAM_MISSING,
    POSTEAM_MISALIGNED,
    UNKNOWN,
    GameClassification,
    classify_game,
    format_summary_text,
    summarize_classifications,
)


def _row(
    *,
    drive_index: int = 0,
    posteam: str = "H",
    posteam_scoring: str | None = None,
    wtype: str = "PASS",
    enum_pt: int = 6,
    skip_delta: bool = False,
    d_home: int = 0,
    d_away: int = 0,
    used: str = "enum",
    td_flag: bool = False,
    cum_off: int = 0,
    cum_def: int = 0,
) -> dict:
    ps = posteam if posteam_scoring is None else posteam_scoring
    return {
        "drive_index": drive_index,
        "posteam": posteam,
        "posteam_scoring": ps,
        "wtype": wtype,
        "enum_pt": enum_pt,
        "skip_delta": skip_delta,
        "d_home": d_home,
        "d_away": d_away,
        "used": used,
        "td_flag": td_flag,
        "cum_off": cum_off,
        "cum_def": cum_def,
    }


def test_classify_pure_clean_game_returns_no_labels() -> None:
    rows = []
    acc_o = acc_a = 0
    for i in range(10):
        acc_o += 6
        rows.append(_row(enum_pt=6, used="enum", cum_off=acc_o, cum_def=acc_a))
    g = classify_game(rows, "clean1", session_home=acc_o, session_away=acc_a)
    assert g.applied_labels == ()
    assert g.dominant_failure_mode is None
    assert g.game_error_magnitude == 0


def test_classify_posteam_missing_fires_below_threshold() -> None:
    rows = []
    co = cd = 0
    for i in range(100):
        pt = "H" if i < 90 else ""
        rows.append(_row(posteam=pt, enum_pt=0, used="none", cum_off=co, cum_def=cd))
    g = classify_game(rows, "pm90", session_home=0, session_away=0)
    assert POSTEAM_MISSING in g.applied_labels

    rows2 = []
    for i in range(100):
        pt = "H" if i < 96 else ""
        rows2.append(_row(posteam=pt, enum_pt=0, used="none", cum_off=0, cum_def=0))
    g2 = classify_game(rows2, "pm96", session_home=0, session_away=0)
    assert POSTEAM_MISSING not in g2.applied_labels


def test_classify_double_count_delta_fires_on_one_event() -> None:
    base = [_row(d_home=0, d_away=0, used="none", enum_pt=0, cum_off=0, cum_def=0)]
    bad = _row(d_home=3, d_away=3, used="none", enum_pt=0, cum_off=0, cum_def=0)
    g = classify_game(base + [bad], "dc1", session_home=0, session_away=0)
    assert DOUBLE_COUNT_DELTA in g.applied_labels
    g2 = classify_game(base, "dc0", session_home=0, session_away=0)
    assert DOUBLE_COUNT_DELTA not in g2.applied_labels


def test_classify_posteam_misaligned_uses_drive_mode() -> None:
    rows = []
    for i in range(18):
        rows.append(_row(drive_index=0, posteam="H", used="none", enum_pt=0, cum_off=0, cum_def=0))
    for i in range(2):
        rows.append(_row(drive_index=0, posteam="A", used="none", enum_pt=0, cum_off=0, cum_def=0))
    g = classify_game(rows, "mis10", session_home=0, session_away=0)
    assert POSTEAM_MISALIGNED in g.applied_labels

    rows_edge = []
    for i in range(19):
        rows_edge.append(_row(drive_index=0, posteam="H", used="none", enum_pt=0, cum_off=0, cum_def=0))
    rows_edge.append(_row(drive_index=0, posteam="A", used="none", enum_pt=0, cum_off=0, cum_def=0))
    g_edge = classify_game(rows_edge, "edge5pct", session_home=0, session_away=0)
    assert POSTEAM_MISALIGNED not in g_edge.applied_labels


def test_classify_delta_lag_fires_high_pct_delta() -> None:
    rows = []
    for i in range(7):
        rows.append(_row(used="enum", enum_pt=0, cum_off=0, cum_def=0))
    for i in range(3):
        rows.append(_row(used="delta", enum_pt=0, cum_off=0, cum_def=0))
    g = classify_game(rows, "lag30", session_home=0, session_away=0)
    assert DELTA_LAG in g.applied_labels

    rows2 = []
    for i in range(9):
        rows2.append(_row(used="enum", enum_pt=0, cum_off=0, cum_def=0))
    rows2.append(_row(used="delta", enum_pt=0, cum_off=0, cum_def=0))
    g2 = classify_game(rows2, "lag10", session_home=0, session_away=0)
    assert DELTA_LAG not in g2.applied_labels


def test_classify_enum_missed_td_requires_two_events() -> None:
    one = [
        _row(d_home=6, d_away=0, enum_pt=0, used="none", cum_off=0, cum_def=0),
    ]
    g1 = classify_game(one, "em1", session_home=0, session_away=0)
    assert ENUM_MISSED_TD not in g1.applied_labels

    three = [
        _row(d_home=6, d_away=0, enum_pt=0, used="none", cum_off=0, cum_def=0),
        _row(d_home=7, d_away=0, enum_pt=0, used="none", cum_off=0, cum_def=0),
        _row(d_home=0, d_away=8, enum_pt=0, used="none", cum_off=0, cum_def=0),
    ]
    g3 = classify_game(three, "em3", session_home=0, session_away=0)
    assert ENUM_MISSED_TD in g3.applied_labels


def test_classify_mixed_feed_either_condition() -> None:
    filler = _row(d_home=0, d_away=0, used="enum", enum_pt=0, skip_delta=False, cum_off=0, cum_def=0)
    r1 = _row(
        d_home=0,
        d_away=0,
        used="delta",
        enum_pt=0,
        skip_delta=True,
        wtype="KICKOFF",
        cum_off=0,
        cum_def=0,
    )
    r2 = _row(
        d_home=0,
        d_away=0,
        used="delta",
        enum_pt=0,
        skip_delta=True,
        wtype="PUNT",
        cum_off=0,
        cum_def=0,
    )
    g = classify_game([filler, r1, r2], "mixskip", session_home=0, session_away=0)
    assert MIXED_FEED_INCONSISTENCY in g.applied_labels

    ex = _row(d_home=12, d_away=0, used="delta", enum_pt=0, skip_delta=False, cum_off=0, cum_def=0)
    g2 = classify_game([filler, ex], "mixext", session_home=0, session_away=0)
    assert MIXED_FEED_INCONSISTENCY in g2.applied_labels


def test_classify_unknown_only_fires_with_real_error() -> None:
    ok = [_row(cum_off=0, cum_def=0, used="none", enum_pt=0)]
    g0 = classify_game(ok, "u0", session_home=0, session_away=0)
    assert UNKNOWN not in g0.applied_labels

    bad = [_row(cum_off=5, cum_def=0, used="enum", enum_pt=0)]
    g5 = classify_game(bad, "u5", session_home=0, session_away=0)
    assert UNKNOWN in g5.applied_labels


def test_dominant_resolution_priority_order() -> None:
    rows: list[dict] = []
    for i in range(7):
        rows.append(
            _row(
                posteam="",
                used="delta",
                enum_pt=0,
                d_home=0,
                d_away=0,
                cum_off=0,
                cum_def=0,
            )
        )
    for i in range(18):
        rows.append(
            _row(
                posteam="H",
                used="delta",
                enum_pt=0,
                d_home=0,
                d_away=0,
                cum_off=0,
                cum_def=0,
            )
        )
    rows.append(_row(posteam="H", used="none", enum_pt=0, d_home=4, d_away=4, cum_off=0, cum_def=0))
    g = classify_game(rows, "dom", session_home=0, session_away=0)
    assert POSTEAM_MISSING in g.applied_labels
    assert DOUBLE_COUNT_DELTA in g.applied_labels
    assert DELTA_LAG in g.applied_labels
    assert g.dominant_failure_mode == POSTEAM_MISSING


def _full_gc(
    game_id: str,
    mag: int | None,
    *,
    dom: str | None = None,
    err_h: int | None = 0,
    err_a: int | None = 0,
) -> GameClassification:
    if dom is None and mag is not None and mag > 0:
        dom = UNKNOWN
    return GameClassification(
        game_id=game_id,
        n_plays=1,
        error_home=err_h,
        error_away=err_a,
        game_error_magnitude=mag,
        pct_enum=0.0,
        pct_delta_only=0.0,
        pct_skipped=0.0,
        posteam_coverage=1.0,
        posteam_display_coverage=1.0,
        posteam_mismatch_rate=0.0,
        n_double_delta=0,
        n_delta_on_skip_play_type=0,
        n_extreme_delta=0,
        n_likely_missed_td=0,
        applied_labels=(UNKNOWN,) if mag and mag > 0 else (),
        dominant_failure_mode=dom,
        explanation="x",
    )


def test_summarize_classifications_top_5_ordering() -> None:
    gcs = [
        _full_gc("a", 1),
        _full_gc("b", 7),
        _full_gc("c", 3),
        _full_gc("d", 2),
        _full_gc("e", 6),
        _full_gc("f", 4),
        _full_gc("g", 5),
    ]
    s = summarize_classifications(gcs, root="/tmp")
    tw = s["top_worst"]
    assert [c.game_id for c in tw] == ["b", "e", "g", "f", "c"]


def test_classify_handles_missing_session_score() -> None:
    rows = [_row(d_home=10, d_away=0, skip_delta=True, used="none", enum_pt=0, cum_off=0, cum_def=0)]
    g = classify_game(rows, "nosess", session_home=None, session_away=None)
    assert g.error_home is None
    assert g.game_error_magnitude is None
    assert g.classification_error is None
    assert UNKNOWN not in g.applied_labels


def test_format_summary_text_includes_sections() -> None:
    gcs = [_full_gc("z9", 9, dom=UNKNOWN, err_h=5, err_a=4)]
    s = summarize_classifications(gcs, root="/r")
    txt = format_summary_text(s)
    assert "Implied score audit summary" in txt
    assert "POSTEAM_MISSING:" in txt
    assert "Top 5 worst games" in txt


def test_classification_csv_writes(tmp_path: Path) -> None:
    from warehouse.implied_score_audit import write_classification_csv

    gcs = [
        GameClassification(
            game_id="g2",
            n_plays=2,
            error_home=1,
            error_away=0,
            game_error_magnitude=1,
            pct_enum=0.5,
            pct_delta_only=0.0,
            pct_skipped=0.5,
            posteam_coverage=1.0,
            posteam_display_coverage=1.0,
            posteam_mismatch_rate=0.0,
            n_double_delta=0,
            n_delta_on_skip_play_type=0,
            n_extreme_delta=0,
            n_likely_missed_td=0,
            applied_labels=(),
            dominant_failure_mode=None,
            explanation="ok",
        ),
        GameClassification(
            game_id="g1",
            n_plays=3,
            error_home=2,
            error_away=2,
            game_error_magnitude=4,
            pct_enum=0.0,
            pct_delta_only=1.0,
            pct_skipped=0.0,
            posteam_coverage=0.8,
            posteam_display_coverage=0.8,
            posteam_mismatch_rate=0.0,
            n_double_delta=0,
            n_delta_on_skip_play_type=0,
            n_extreme_delta=0,
            n_likely_missed_td=0,
            applied_labels=(DELTA_LAG, POSTEAM_MISSING),
            dominant_failure_mode=POSTEAM_MISSING,
            explanation="x",
        ),
    ]
    p = tmp_path / "out.csv"
    write_classification_csv(gcs, p)
    body = p.read_text(encoding="utf-8")
    assert "game_id" in body
    lines = body.strip().splitlines()
    assert lines[1].startswith("g1,")


def test_main_summary_rejects_csv_combo(capsys: pytest.CaptureFixture[str]) -> None:
    from warehouse.implied_score_audit import main

    rc = main(["--summary", "--csv", str(Path(__file__))])
    assert rc == 1
    err = capsys.readouterr().err
    assert "cannot be combined" in err
