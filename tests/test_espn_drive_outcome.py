"""ESPN completed-drive outcome → Drive.result mapping (J1.1)."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult
from playcaller.espn_drive_outcome import drive_result_kind_from_espn_audit, espn_drive_outcome_bucket
from playcaller.game import (
    DRIVE_END_PUNT,
    DRIVE_END_TOUCHDOWN,
    DRIVE_END_UNKNOWN,
    DriveFeedAuditSnapshot,
    OUTCOME_SOURCE_ESPN,
    OUTCOME_SOURCE_INFERRED,
    complete_drive_from_plays,
)


def test_espn_bucket_td_and_end_half() -> None:
    from playcaller.game import DRIVE_END_END_OF_HALF

    td = DriveFeedAuditSnapshot(espn_result_code="TD", espn_display_result="Touchdown")
    assert espn_drive_outcome_bucket(td) == "TD"
    assert drive_result_kind_from_espn_audit(td) == (DRIVE_END_TOUCHDOWN, "TD")

    half = DriveFeedAuditSnapshot(espn_result_code="END OF HALF", espn_display_result="End of Half")
    assert espn_drive_outcome_bucket(half) == "END_HALF"
    assert drive_result_kind_from_espn_audit(half) == (DRIVE_END_END_OF_HALF, "END_HALF")


def test_complete_drive_prefers_espn_audit_over_last_play() -> None:
    """Official-timeout trailer would punt under inference; ESPN TD wins."""
    plays = [
        ActualPlayResult(
            yards_gained=15,
            family="draw",
            play_type="run",
            result_type="touchdown",
            touchdown=True,
            description="[ESPN] QB run · TD · +15 yds",
        ),
        ActualPlayResult(
            yards_gained=0,
            family="dropback_pass",
            play_type="pass",
            result_type="unknown",
            description="[ESPN] official timeout · 0 yds — Official Timeout at 08:11.",
            concept_name="official timeout",
        ),
    ]
    audit = DriveFeedAuditSnapshot(
        espn_result_code="TD",
        espn_display_result="Touchdown",
        espn_is_score=True,
    )
    d = complete_drive_from_plays(plays, feed_audit=audit, possessing_team="defense")
    assert d.result is not None
    assert d.result.kind == DRIVE_END_TOUCHDOWN
    assert d.outcome_source == OUTCOME_SOURCE_ESPN


def test_complete_drive_infers_when_espn_absent() -> None:
    plays = [
        ActualPlayResult(
            yards_gained=0,
            family="special_teams",
            play_type="special",
            result_type="punt",
            description="[ESPN] Punt · 0 yds",
        ),
    ]
    d = complete_drive_from_plays(plays)
    assert d.result is not None
    assert d.result.kind == DRIVE_END_PUNT
    assert d.outcome_source == OUTCOME_SOURCE_INFERRED
