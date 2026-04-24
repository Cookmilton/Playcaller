"""
Golden integration: Packers @ Lions (ESPN event 401772891), final 31–24 GB.

Ingest: ``extract_completed_drives_from_espn_payload`` → ``merge_completed_espn_drives_into_game``
(coached as GB). Reconcile via ``reconcile_drive`` / ``compute_drive_audit`` — CI lock-in for
reconciliation + threaded scoring.
"""

from __future__ import annotations

import json
from pathlib import Path

from playcaller.drive_audit_report import compute_drive_audit
from playcaller.game import Game
from playcaller.live_data.espn_completed_drives import extract_completed_drives_from_espn_payload
from playcaller.live_data.espn_import_merge import merge_completed_espn_drives_into_game
from playcaller.reconciliation.drive_reconciler import reconcile_drive

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_packers_lions_401772891.json"
EVENT_ID = "401772891"
GB_ID = "9"
DET_ID = "8"

# Reconciled (outcome_kind, possession_points) for each GB possession in chronological order (9 drives).
_EXPECTED_GB = (
    ("field_goal", 3),
    ("punt", 0),
    ("touchdown", 7),
    ("touchdown", 7),
    ("unknown", 0),  # END_HALF — no score
    ("touchdown", 7),
    ("touchdown", 7),
    ("punt", 0),
    ("punt", 0),
)

# DET possessions (8 drives) when GB is coached team (DET on defense).
_EXPECTED_DET = (
    ("punt", 0),
    ("punt", 0),
    ("touchdown", 7),
    ("touchdown", 7),
    ("turnover_on_downs", 0),
    ("touchdown", 7),
    ("turnover_on_downs", 0),
    ("field_goal", 3),
)


def _load() -> dict:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def test_packers_lions_fixture_scores_and_drive_counts() -> None:
    data = _load()
    comp = data["header"]["competitions"][0]
    assert comp["id"] == EVENT_ID
    scores = {c["team"]["id"]: int(c["score"]) for c in comp["competitors"]}
    assert scores[GB_ID] == 31 and scores[DET_ID] == 24
    prev = data["drives"]["previous"]
    assert len([d for d in prev if d.get("team", {}).get("id") == GB_ID]) == 9
    assert len([d for d in prev if d.get("team", {}).get("id") == DET_ID]) == 8


def test_packers_lions_golden_reconcile_and_audit() -> None:
    """
    Full ingest → merge (both teams' drives in session, same as feed scope **both**) → reconcile.

    **ESPN-over-inferred example:** chronological drive **#1** (first GB possession). ESPN
    classifies the possession as **FG**; the archived plays infer **punt** (drive 0). The reconciler
    keeps ESPN for the primary outcome → Field Goal (+3). Raw bucket disagreement is expected.
    """
    data = _load()
    fds = extract_completed_drives_from_espn_payload(data, event_id=EVENT_ID)
    assert len(fds) == 17

    g = Game.new_game()
    g.offense_points = 31
    g.defense_points = 24
    n, _ = merge_completed_espn_drives_into_game(g, {}, fds, coached_team_id=GB_ID, feed_team_scope="both")
    assert n == 17
    assert len(g.drives) == 17

    gb_got: list[tuple[str, int]] = []
    det_got: list[tuple[str, int]] = []
    for dr in g.drives:
        rec = reconcile_drive(dr, espn=dr.feed_audit)
        tid = dr.feed_team_espn_id
        row = (rec.outcome_kind, rec.possession_points)
        if tid == GB_ID:
            gb_got.append(row)
        elif tid == DET_ID:
            det_got.append(row)
    assert gb_got == list(_EXPECTED_GB)
    assert det_got == list(_EXPECTED_DET)

    d0 = g.drives[0]
    r0 = reconcile_drive(d0, espn=d0.feed_audit)
    assert d0.feed_team_espn_id == GB_ID
    assert r0.espn_coarse_bucket == "FG" and r0.raw_espn_vs_inferred_disagree

    rep = compute_drive_audit(g)
    assert rep.implied_final_us == 31
    assert rep.implied_final_them == 24
    assert not rep.global_score_mismatch

    max_us = max_them = -1
    for r in rep.rows:
        assert r.score_after_us >= max_us and r.score_after_them >= max_them
        max_us = max(max_us, r.score_after_us)
        max_them = max(max_them, r.score_after_them)
    assert rep.rows[-1].score_after_us == 31 and rep.rows[-1].score_after_them == 24
