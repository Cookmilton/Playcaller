"""K1.4: Undo after a drive-ending Log voids the snap-review row that Log closed.

Defect: ``_snapshot_archive_state`` deep-copied ``recommendation_audit`` *after*
``close_snap_review_row_with_logged_actual``, and restore reinstated the closed row.
Board / possession / drive restored correctly, but the ghost closed row kept
``linked_actual`` / ``actual_result``. Plain End-drive undo must leave the row closed
(play stays in the drive).
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from playcaller.domain import ActualPlayResult
from playcaller.evaluation.audit import void_last_closed_audit
from playcaller.evaluation.metrics import evaluate_audit_records
from playcaller.game import Game, game_to_dict
from playcaller.history.normalize import _map_closed_audits_to_plays, build_normalized_plays
from playcaller.services.drive_archive import (
    ARCHIVE_KIND_MANUAL,
    archive_open_drive,
    restore_last_drive_archive,
)
from playcaller.state import DriveLogger
from playcaller.streamlit_state.keys import (
    DRIVE_ARCHIVE_UNDO_STACK,
    GAME_DISTANCE,
    GAME_DOWN,
    GAME_POSSESSION_SIDE,
    GAME_TERRITORY,
    GAME_YARDLINE,
)
from tests.test_k11_drive_ending_log import ARCHIVING_LOGS, BOARD, _boot_manual, _generate


def _assert_row_voided(row: dict) -> None:
    assert row["status"] == "void_undone"
    assert row.get("completed") is False
    assert "linked_actual" not in row
    assert "actual_result" not in row


# ──────────────────────────────────────────────────────────────────────────────
# Unit: void_last_closed_audit(row_id=…) is the single voiding path
# ──────────────────────────────────────────────────────────────────────────────


def test_k14_void_by_row_id_leaves_other_closed_rows() -> None:
    audit = [
        {
            "row_id": "keep",
            "status": "closed",
            "linked_actual": {"family": "inside_zone"},
            "actual_result": "run",
            "completed": True,
        },
        {
            "row_id": "void_me",
            "status": "closed",
            "linked_actual": {"family": "quick_game"},
            "actual_result": "pass",
            "completed": True,
        },
    ]
    void_last_closed_audit(audit, row_id="void_me")
    assert audit[0]["status"] == "closed"
    assert audit[0]["linked_actual"] == {"family": "inside_zone"}
    _assert_row_voided(audit[1])


def test_k14_void_without_row_id_still_voids_most_recent_closed() -> None:
    audit = [
        {"row_id": "a", "status": "closed", "linked_actual": {"family": "x"}, "completed": True},
        {"row_id": "b", "status": "closed", "linked_actual": {"family": "y"}, "completed": True},
        {"row_id": "c", "status": "open"},
    ]
    void_last_closed_audit(audit)
    assert audit[0]["status"] == "closed"
    _assert_row_voided(audit[1])


# ──────────────────────────────────────────────────────────────────────────────
# Unit: archive undo entry + restore
# ──────────────────────────────────────────────────────────────────────────────


def _archive_ss() -> dict:
    g = Game.new_game()
    g.possession = "offense"
    return {
        "game": g,
        "drive_log": DriveLogger(),
        GAME_DOWN: 4,
        GAME_DISTANCE: 6,
        GAME_TERRITORY: "opponents",
        GAME_YARDLINE: 35,
        GAME_POSSESSION_SIDE: "Our team",
        "eval_drive_epoch": 0,
        "ui_drive_end_on_new": "auto",
        "ui_game_period": 1,
        "ui_quarter_clock_mins": 5,
        "ui_quarter_clock_secs": 0,
    }


def test_k14_restore_after_drop_last_voids_recorded_row_id() -> None:
    ss = _archive_ss()
    play = ActualPlayResult(result_type="field_goal_miss", description="FG miss")
    ss["drive_log"].log(play)
    row = {
        "row_id": "closed-by-log",
        "status": "closed",
        "linked_actual": {"result_type": "field_goal_miss"},
        "actual_result": "field_goal_miss",
        "completed": True,
        "plays_at_recommend": 0,
    }
    ss["game"].recommendation_audit = [row]
    res = archive_open_drive(
        ss,
        kind=ARCHIVE_KIND_MANUAL,
        update_board=True,
        undo_drop_last_logged_play=True,
        undo_closed_snap_review_row_id="closed-by-log",
        undo_pre_log_board={
            "territory": "opponents",
            "yardline": 35,
            "down": 4,
            "distance": 6,
        },
    )
    assert res.archived is not None
    entry = (ss.get(DRIVE_ARCHIVE_UNDO_STACK) or [])[-1]
    assert entry["drop_last_logged_play"] is True
    assert entry["closed_snap_review_row_id"] == "closed-by-log"

    assert restore_last_drive_archive(ss) is True
    assert ss["game"].drives == []
    assert ss["drive_log"].results == []
    _assert_row_voided(ss["game"].recommendation_audit[0])


def test_k14_end_drive_undo_does_not_void_closed_row() -> None:
    """Plain End drive keeps the play in the archived drive; undo must not void its row."""
    ss = _archive_ss()
    play = ActualPlayResult(yards_gained=5, description="gain")
    ss["drive_log"].log(play)
    row = {
        "row_id": "stay-closed",
        "status": "closed",
        "linked_actual": {"yards_gained": 5},
        "actual_result": "run +5",
        "completed": True,
        "plays_at_recommend": 0,
    }
    ss["game"].recommendation_audit = [row]
    res = archive_open_drive(ss, kind=ARCHIVE_KIND_MANUAL, update_board=True)
    assert res.archived is not None
    entry = (ss.get(DRIVE_ARCHIVE_UNDO_STACK) or [])[-1]
    assert entry.get("drop_last_logged_play") is False
    assert "closed_snap_review_row_id" not in entry

    assert restore_last_drive_archive(ss) is True
    restored = ss["game"].recommendation_audit[0]
    assert restored["status"] == "closed"
    assert restored.get("linked_actual") == {"yards_gained": 5}
    assert restored.get("actual_result") == "run +5"
    assert restored.get("completed") is True
    assert len(ss["drive_log"].results) == 1


def test_k14_voided_row_excluded_from_metrics_and_normalize() -> None:
    voided = {
        "row_id": "ghost",
        "status": "void_undone",
        "selected_family": "inside_zone",
        "completed": False,
        "plays_at_recommend": 0,
    }
    closed = {
        "row_id": "real",
        "status": "closed",
        "selected_family": "quick_game",
        "linked_actual": {
            "family": "quick_game",
            "concept_name": "Slant",
            "yards_gained": 8,
            "result_type": "complete",
            "call_source": "operator_confirmed",
        },
        "completed": True,
        "plays_at_recommend": 0,
    }
    ev = evaluate_audit_records([voided, closed])
    # metrics.py:72 closed — void_undone excluded; metrics.py:74 all_reco likewise.
    assert ev["n_closed_vs_actual"] == 1
    assert sum(ev["reco_family_counts"].values()) == 1
    assert ev["reco_family_counts"]["quick_game"] == 1
    assert "inside_zone" not in ev["reco_family_counts"]

    g = Game.new_game()
    g.recommendation_audit = [voided]
    g.drives = []
    assert _map_closed_audits_to_plays(g) == {}
    assert build_normalized_plays(g) == []


# ──────────────────────────────────────────────────────────────────────────────
# AppTest: drive-ending Log → Undo voids the row
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("log_key", sorted(ARCHIVING_LOGS))
def test_k14_drive_ending_log_undo_voids_the_closed_row(log_key: str) -> None:
    at = _boot_manual()
    _generate(at)
    row_before = at.session_state.game.recommendation_audit[0]
    row_id = str(row_before["row_id"])
    before_board = {k: at.session_state[k] for k in BOARD}
    before_possession = at.session_state.game.possession

    at.button(key=log_key).click().run()
    assert not at.exception, at.exception
    closed = next(r for r in at.session_state.game.recommendation_audit if r.get("row_id") == row_id)
    assert closed["status"] == "closed"
    assert closed.get("linked_actual")
    assert closed.get("actual_result")

    at.button(key="main_console_undo_drive_archive").click().run()
    assert not at.exception, at.exception

    assert at.session_state.game.drives == []
    assert at.session_state.drive_log.results == []
    assert at.session_state.game.possession == before_possession
    assert {k: at.session_state[k] for k in BOARD} == before_board
    voided = next(r for r in at.session_state.game.recommendation_audit if r.get("row_id") == row_id)
    _assert_row_voided(voided)


def test_k14_end_drive_archive_undo_leaves_last_row_closed() -> None:
    at = _boot_manual({"ui_down": 1, "ui_distance": 10, "ui_territory": "own", "ui_yardline": 25})
    _generate(at)
    at.button(key="main_log_yards_plus5").click().run()
    assert not at.exception, at.exception
    assert at.session_state.game.drives == []
    assert len(at.session_state.drive_log.results) == 1
    row_id = str(at.session_state.game.recommendation_audit[0]["row_id"])
    assert at.session_state.game.recommendation_audit[0]["status"] == "closed"

    at.button(key="sidebar_btn_end_drive_next").click().run()
    assert not at.exception, at.exception
    assert len(at.session_state.game.drives) == 1

    at.button(key="main_console_undo_drive_archive").click().run()
    assert not at.exception, at.exception
    assert at.session_state.game.drives == []
    assert len(at.session_state.drive_log.results) == 1
    row = next(r for r in at.session_state.game.recommendation_audit if r.get("row_id") == row_id)
    assert row["status"] == "closed"
    assert row.get("linked_actual")
    assert row.get("actual_result")
    assert row.get("completed") is True


def test_k14_export_after_log_undo_has_no_ghost_closed_row() -> None:
    """Exported game must not contain a closed row with no matching play in drives/logger."""
    at = _boot_manual()
    _generate(at)
    at.button(key="main_log_fg_miss").click().run()
    assert not at.exception, at.exception
    at.button(key="main_console_undo_drive_archive").click().run()
    assert not at.exception, at.exception

    payload = game_to_dict(at.session_state.game)
    plays = [
        p
        for d in (payload.get("drives") or [])
        for p in (d.get("plays") or [])
    ]
    logger_plays = list(at.session_state.drive_log.results)
    assert plays == []
    assert logger_plays == []

    for key in ("snap_review_log", "recommendation_audit"):
        for row in payload.get(key) or []:
            if not isinstance(row, dict):
                continue
            assert row.get("status") != "closed", (
                f"ghost closed row in {key}: {row.get('row_id')}"
            )


def test_k14_later_log_closes_only_the_new_open_row() -> None:
    """After voiding a drive-ending row, a later Log closes only the new open row."""
    from playcaller.evaluation.snap_review_lifecycle import (
        close_snap_review_row_with_logged_actual,
    )

    ss = _archive_ss()
    g = ss["game"]
    dl = ss["drive_log"]
    void_row = {
        "row_id": "void-me",
        "status": "closed",
        "linked_actual": {"result_type": "field_goal_miss"},
        "actual_result": "field_goal_miss",
        "completed": True,
        "plays_at_recommend": 0,
        "selected_family": "field_goal",
    }
    g.recommendation_audit = [void_row]
    dl.log(ActualPlayResult(result_type="field_goal_miss", description="FG miss"))
    archive_open_drive(
        ss,
        kind=ARCHIVE_KIND_MANUAL,
        update_board=True,
        undo_drop_last_logged_play=True,
        undo_closed_snap_review_row_id="void-me",
        undo_pre_log_board={
            "territory": "opponents",
            "yardline": 35,
            "down": 4,
            "distance": 6,
        },
    )
    assert restore_last_drive_archive(ss) is True
    _assert_row_voided(g.recommendation_audit[0])

    # New Generate → open row, then a non-ending Log closes only that row.
    open_row = {
        "row_id": "fresh-open",
        "status": "open",
        "plays_at_recommend": 0,
        "selected_family": "inside_zone",
    }
    g.recommendation_audit.append(open_row)
    actual = ActualPlayResult(yards_gained=5, family="inside_zone", description="+5")
    dl.log(actual)
    closed = close_snap_review_row_with_logged_actual(
        g.recommendation_audit,
        plays_after_log=len(dl.results),
        actual=actual,
    )
    assert closed is not None
    assert closed["row_id"] == "fresh-open"
    by_id = {r["row_id"]: r for r in g.recommendation_audit}
    _assert_row_voided(by_id["void-me"])
    assert by_id["fresh-open"]["status"] == "closed"
    assert by_id["fresh-open"].get("linked_actual")
    assert by_id["fresh-open"].get("completed") is True


def test_k14_restore_does_not_write_widget_keys() -> None:
    """Same post-widget-safe contract as G2.3: restore uses backend keys + hydrate only."""
    import inspect

    from playcaller.services import drive_archive as mod

    src = inspect.getsource(mod.restore_last_drive_archive)
    assert "request_widget_hydrate_from_backend(ss)" in src
    # Must not assign widget-bound keys directly.
    for bad in (
        'ss["ui_',
        "ss['ui_",
        'ss[f"ui_',
    ):
        assert bad not in src
